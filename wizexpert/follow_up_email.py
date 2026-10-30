"""Render and validate the Risk Issues follow-up email draft (HTML only, never sent)."""

from __future__ import annotations

import argparse
import html
import json
import re
from pathlib import Path

from wizexpert.email_qa import Document

MODES = ("reply", "progress")
HEADINGS = {
    "reply": [
        "What We Received:",
        "Acknowledged:",
        "Answers and Next Steps:",
        "Confirmations Requested:",
    ],
    "progress": [
        "Issue and Control Context:",
        "Last Agreed Action:",
        "Response Requested:",
    ],
}
SUBJECT_PREFIX = {"reply": "Re", "progress": "Follow-up"}
GREETING = "Hi Team,"
CLOSING = "Let us know if you need any assistance."
SIGNATURE_START = "Best Regards,"
WRAPPER_IDS = (
    "email-header",
    "email-badge",
    "email-notice",
    "email-confidentiality",
    "email-subject",
    "email-body",
)
ATTACHMENT_FIELD = "attachment_name"
FORBIDDEN_DESTINATIONS = {".txt", ".pdf"}

MODE_BLOCK = re.compile(r"<!-- mode:(\w+) -->(.*?)<!-- /mode:\1 -->", re.S)
REPEAT_BLOCK = re.compile(
    r"<!-- repeat:(\w+)((?:\s+(?:sep|end)=\"[^\"]*\")*) -->(.*?)<!-- /repeat:\1 -->", re.S
)
REPEAT_ATTR = re.compile(r"(sep|end)=\"([^\"]*)\"")
SCALAR = re.compile(r"\{\{(\w+)\}\}")
ITEM = re.compile(r"\{\{\.(\w+)\}\}")
LINKS = re.compile(r"<div class=\"links\">.*?</div>", re.S)
UNRESOLVED = re.compile(r"\{\{\s*\.?\w*\s*\}\}|<!--|-->|<!--\s*/?(?:mode|repeat):")
# Client data indicators that must never appear in a reusable template.
CLIENT_DATA = (
    re.compile(r"https?://", re.I),
    re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"),
    re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I),
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def select_mode(modes: list[str] | tuple[str, ...] | str | None) -> str:
    """Return the single requested mode; reject missing, unknown or multiple modes."""
    selected = [modes] if isinstance(modes, str) else list(modes or [])
    require(bool(selected), "Exactly one mode is required: reply or progress.")
    require(len(selected) == 1, f"Exactly one mode is allowed, got {len(selected)}.")
    require(selected[0] in MODES, f"Unknown mode {selected[0]!r}; use reply or progress.")
    return selected[0]


def check_template(template: str, fields: dict) -> dict[str, str]:
    """Validate the private template source; return the mode blocks by name."""
    found = MODE_BLOCK.findall(template)
    blocks = dict(found)
    require(
        len(found) == len(MODES) and sorted(blocks) == sorted(MODES),
        "Template must hold exactly one reply and one progress block.",
    )
    for pattern in CLIENT_DATA:
        require(
            not pattern.search(template), "Template source holds client data (URL, email or ID)."
        )
    require("###" not in template, "Template must use h3 elements, not Markdown headings.")
    line = fields.get("output", {}).get("confidentiality_line")
    require(
        isinstance(line, str) and bool(line.strip()),
        "fields.json output.confidentiality_line is required.",
    )
    require(
        template.count(f">{line}</p>") == 1,
        "Template must hold the exact confidentiality line once.",
    )
    document = Document(template)
    require(not document.errors, f"Template HTML is malformed: {document.errors}")
    for identifier in WRAPPER_IDS:
        document.by_id(identifier)
    documented = set(fields.get("fields", {}))
    used = set(SCALAR.findall(template)) | {name for name, _, _ in REPEAT_BLOCK.findall(template)}
    require(
        used <= documented, f"Placeholders missing from fields.json: {sorted(used - documented)}"
    )
    return blocks


def placeholders(text: str) -> tuple[set[str], set[str]]:
    repeats = {name for name, _, _ in REPEAT_BLOCK.findall(text)}
    plain = set(SCALAR.findall(REPEAT_BLOCK.sub("", text)))
    return plain, repeats


def text_value(name: str, value: object) -> str:
    require(
        isinstance(value, str) and bool(value.strip()),
        f"Field {name!r} must be a non-empty string.",
    )
    return value.strip()


def item_list(name: str, value: object) -> list[str]:
    require(isinstance(value, list) and bool(value), f"Field {name!r} must be a non-empty list.")
    items = []
    for item in value:
        require(
            isinstance(item, dict) and set(item) == {"text"},
            f"Field {name!r} items must be objects with only 'text'.",
        )
        items.append(text_value(name, item["text"]))
    return items


def constant(value: str):
    """Return a replacement function that always yields value."""
    return lambda _match: value


def render(
    template: str,
    fields: dict,
    mode: str,
    values: dict,
    attachment_name: str | None = None,
) -> str:
    """Render the template for one mode; raise ValueError on any rule breach."""
    mode = select_mode(mode)
    blocks = check_template(template, fields)
    other = next(m for m in MODES if m != mode)
    need_plain, need_repeat = placeholders(MODE_BLOCK.sub("", template) + blocks[mode])
    other_plain, other_repeat = placeholders(blocks[other])
    foreign = (other_plain | other_repeat) - need_plain - need_repeat
    need_plain.discard(ATTACHMENT_FIELD)
    require(
        ATTACHMENT_FIELD not in values, "Supply the attachment through attachment_name, not values."
    )
    require(
        not (set(values) & foreign), f"Fields for the other mode: {sorted(set(values) & foreign)}"
    )
    unknown = set(values) - need_plain - need_repeat
    require(not unknown, f"Unknown fields: {sorted(unknown)}")
    missing = (need_plain | need_repeat) - set(values)
    require(not missing, f"Missing fields: {sorted(missing)}")
    if attachment_name is not None:
        attachment_name = text_value(ATTACHMENT_FIELD, attachment_name)
        require(
            re.fullmatch(r"\w[\w .()-]*\.\w{1,8}", attachment_name) is not None,
            "attachment_name must be one plain file name.",
        )
    body = MODE_BLOCK.sub(lambda m: m.group(2) if m.group(1) == mode else "", template)

    def repeat(match: re.Match) -> str:
        name, attributes, inner = match.groups()
        options = dict(REPEAT_ATTR.findall(attributes))
        rendered = [
            ITEM.sub(constant(html.escape(text, quote=True)), inner)
            for text in item_list(name, values[name])
        ]
        return options.get("sep", "").join(rendered) + options.get("end", "")

    body = REPEAT_BLOCK.sub(repeat, body)
    if attachment_name is None:
        body = LINKS.sub("", body)
    allowed = dict(values)
    if attachment_name is not None:
        allowed[ATTACHMENT_FIELD] = attachment_name

    def scalar(match: re.Match) -> str:
        return html.escape(text_value(match.group(1), allowed[match.group(1)]), quote=True)

    body = SCALAR.sub(scalar, body)
    validate_output(body, fields, mode, template, attachment_name)
    return body


def validate_output(
    rendered: str, fields: dict, mode: str, template: str, attachment_name: str | None
) -> None:
    """Check rendered HTML against the documented follow-up rules."""
    mode = select_mode(mode)
    require(
        not UNRESOLVED.search(rendered), "Rendered output has unresolved placeholders or markers."
    )
    document = Document(rendered)
    require(not document.errors, f"Rendered HTML is malformed: {document.errors}")
    require(
        document.by_id("email-confidentiality").text() == fields["output"]["confidentiality_line"],
        "Confidentiality line is missing or changed.",
    )
    require(
        document.by_id("email-notice").text().startswith("Internal preparation note"),
        "Private preparation notice is missing.",
    )
    for identifier in WRAPPER_IDS:
        document.by_id(identifier)
    body = document.by_id("email-body")
    inner = [e for e in body.elements() if e is not body]
    require(
        not any(e.attrs.get("id") in WRAPPER_IDS for e in inner),
        "Wrapper elements must stay outside #email-body.",
    )
    require(
        not any(e.tag in {"a", "script", "style", "img"} for e in inner),
        "#email-body must contain no links, scripts or images.",
    )
    require("###" not in body.text(), "Literal Markdown headings are not allowed.")
    paragraphs = [c for c in body.children if getattr(c, "tag", "") == "p"]
    require(
        len(paragraphs) >= 3 and paragraphs[0].text() == GREETING,
        f"Body must start with {GREETING!r}.",
    )
    require(
        paragraphs[-1].text().startswith(SIGNATURE_START)
        and paragraphs[-2].text().endswith(CLOSING),
        "Body must end with the closing sentence and signature.",
    )
    template_body = Document(template).by_id("email-body")
    template_signature = [c for c in template_body.children if getattr(c, "tag", "") == "p"][-1]
    require(
        paragraphs[-1].text() == template_signature.text(), "Signature differs from the template."
    )
    headings = [e.text() for e in inner if e.tag == "h3"]
    require(headings == HEADINGS[mode], f"Headings must be {HEADINGS[mode]}, got {headings}.")
    prefix = SUBJECT_PREFIX[mode]
    require(
        re.fullmatch(
            re.escape(prefix) + r": .+ \| SNOW: .+", document.by_id("email-subject").text()
        )
        is not None,
        f"Subject must read '{prefix}: <topic> | SNOW: <reference>'.",
    )
    links = [e for e in document.root.elements() if e.tag == "a"]
    if attachment_name is None:
        require(not links, "Attachment link must be removed when there is no attachment.")
    else:
        require(len(links) == 1, "At most one attachment link is allowed.")
        require(
            links[0].attrs.get("href") == attachment_name
            and links[0].text() == f"Attachment: {attachment_name}",
            "Attachment link must name only the selected attachment.",
        )


def check_destination(destination: Path) -> None:
    suffix = destination.suffix.lower()
    require(suffix not in FORBIDDEN_DESTINATIONS, f"Destination must be HTML only, not {suffix}.")
    require(suffix == ".html", "Destination must be an .html file.")
    require(not destination.exists(), "Destination exists; archive it first, nothing overwritten.")


def render_file(
    template_path: Path,
    fields_path: Path,
    mode: str,
    values: dict,
    destination: Path,
    attachment_name: str | None = None,
) -> Path:
    """Render to a new HTML file. The draft is never sent."""
    check_destination(destination)
    fields = json.loads(fields_path.read_text(encoding="utf-8"))
    output = render(
        template_path.read_text(encoding="utf-8"), fields, mode, values, attachment_name
    )
    destination.write_text(output, encoding="utf-8")
    return destination


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument("--fields", type=Path, required=True)
    parser.add_argument("--mode", action="append", default=[])
    parser.add_argument("--values", type=Path, required=True, help="JSON file of field values")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--attachment")
    args = parser.parse_args(argv)
    try:
        values = json.loads(args.values.read_text(encoding="utf-8"))
        require(isinstance(values, dict), "Values file must hold a JSON object.")
        result = render_file(
            args.template,
            args.fields,
            select_mode(args.mode),
            values,
            args.output,
            args.attachment,
        )
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(1, f"Follow-up email blocked: {error}\n")
    print(json.dumps({"output": str(result), "sent": False}, indent=2))
    return 0

