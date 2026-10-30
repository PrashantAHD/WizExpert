"""Check actual email HTML against the approved style and message contract."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path

NOTICE = (
    "Internal preparation note - do not copy into email: Confirm named recipients before "
    "outreach. Attachment identities must be confirmed when sending."
)
VOID = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
}


def compact(value: str) -> str:
    return " ".join(value.split())


@dataclass
class Element:
    tag: str
    attrs: dict = field(default_factory=dict)
    children: list = field(default_factory=list)

    def hidden(self) -> bool:
        return (
            "hidden" in self.attrs
            or self.attrs.get("aria-hidden") == "true"
            or bool(
                re.search(
                    r"(display\s*:\s*none|visibility\s*:\s*hidden)",
                    self.attrs.get("style", ""),
                    re.I,
                )
            )
        )

    def elements(self, *, visible_only: bool = False):
        if visible_only and self.hidden():
            return
        yield self
        for child in self.children:
            if isinstance(child, Element):
                yield from child.elements(visible_only=visible_only)

    def text(self) -> str:
        if self.tag in {"script", "style", "head"}:
            return ""
        if self.hidden():
            return ""
        return compact(
            " ".join(
                child.text() if isinstance(child, Element) else child for child in self.children
            )
        )


class Document(HTMLParser):
    def __init__(self, content: str):
        super().__init__(convert_charrefs=True)
        self.root = Element("document")
        self.stack = [self.root]
        self.errors = []
        self.feed(content)
        self.close()
        if len(self.stack) != 1:
            self.errors.append("Unclosed HTML elements.")

    def handle_starttag(self, tag, attrs):
        if len({name for name, _ in attrs}) != len(attrs):
            self.errors.append(f"Duplicate HTML attributes: {tag}")
        node = Element(tag, dict(attrs))
        self.stack[-1].children.append(node)
        if tag not in VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if len(self.stack) > 1 and self.stack[-1].tag == tag:
            self.stack.pop()
        else:
            self.errors.append(f"Unmatched closing element: {tag}")

    def handle_data(self, data):
        self.stack[-1].children.append(data)

    def by_id(self, identifier: str) -> Element:
        found = [e for e in self.root.elements() if e.attrs.get("id") == identifier]
        if len(found) != 1:
            raise ValueError(f"Expected exactly one element with id={identifier!r}.")
        return found[0]


def stylesheet(document: Document) -> str:
    return "\n".join(
        "".join(c for c in node.children if isinstance(c, str))
        for node in document.root.elements()
        if node.tag == "style"
    )


def validate_email(html: Path, contract_path: Path) -> dict:
    from wizexpert.workflow_qa import digest, load

    contract = load(contract_path)
    if contract.get("schema_version") != 1 or contract.get("kind") not in {
        "reply",
        "progress",
        "blocker",
        "closure",
    }:
        raise ValueError("Unsupported email contract version or message kind.")
    document = Document(html.read_text(encoding="utf-8-sig"))
    errors = list(document.errors)
    regions = {
        name: document.by_id(contract[f"{name}_id"])
        for name in ("body", "subject", "header", "badge", "notice")
    }
    body = regions["body"]
    visible_nodes = list(document.root.elements(visible_only=True))
    for name, region in regions.items():
        if not any(node is region for node in visible_nodes):
            errors.append(f"{name} region is hidden by itself or an ancestor.")
    body_nodes = list(body.elements(visible_only=True))
    for name in ("subject", "header", "badge", "notice"):
        if any(node is regions[name] for node in body_nodes):
            errors.append(f"{name} must be outside the copyable email body.")
    actual = body.text()
    if not actual.startswith("Hi Team, "):
        errors.append("Greeting must be Hi Team,.")
    signature = compact(contract["signature"])
    if not signature or not actual.endswith(f"Best Regards, {signature}"):
        errors.append("Approved closing signature is missing or changed.")
    subject = regions["subject"].text().removeprefix("Subject: ").strip()
    if not compact(contract.get("approved_subject", "")) or subject != contract["approved_subject"]:
        errors.append("Reply/update subject differs from the reviewed wording.")
    expected_body = compact(contract.get("approved_body", ""))
    if not expected_body or actual != expected_body:
        errors.append("Reply/update body differs from the reviewed wording.")
    if "PRIVATE COMMUNICATION DRAFT" not in regions["header"].text():
        errors.append("Private draft header is missing.")
    if not compact(contract.get("title", "")) or contract["title"] not in regions["header"].text():
        errors.append("Descriptive communication title is missing or changed.")
    if regions["badge"].text() != f"Draft - not sent | {contract['draft_date']}":
        errors.append("Draft badge/date differs from the contract.")
    if regions["notice"].text() != NOTICE:
        errors.append("Required internal preparation notice is missing or changed.")
    if NOTICE in actual or "PRIVATE COMMUNICATION DRAFT" in actual:
        errors.append("Internal preview text leaked into the copyable body.")
    confidentiality = None
    if "confidentiality" not in contract:
        errors.append("Contract must record the confidentiality-line decision (text or null).")
    elif contract["confidentiality"] is not None:
        line = compact(str(contract["confidentiality"]))
        try:
            confidentiality = document.by_id(contract["confidentiality_id"])
        except (KeyError, ValueError):
            errors.append("Required confidentiality line is missing from the private wrapper.")
        if confidentiality is not None:
            if not any(node is confidentiality for node in visible_nodes):
                errors.append("Confidentiality line is hidden by itself or an ancestor.")
            if any(node is confidentiality for node in body.elements()):
                errors.append("Confidentiality line must be in the private wrapper, not the body.")
            if not line or confidentiality.text() != line:
                errors.append("Confidentiality line differs from the approved text.")
        if line and line in actual:
            errors.append("Confidentiality line leaked into the copyable body.")
    if contract.get("campaign") is True:
        from wizexpert.campaign import campaign_wording_errors

        errors.extend(
            campaign_wording_errors(
                f"{subject} {actual}",
                partial_day=contract.get("partial_day") is True,
                reconstructed=contract.get("reconstructed") is True,
            )
        )
    for forbidden in (
        r"###",
        r"(?:please|you must|you should)\s+(?:refresh|close|track)\s+wiz",
    ):
        if re.search(forbidden, actual, re.I):
            errors.append(f"Disallowed stakeholder wording: {forbidden}")
    attachments = contract.get("attachments", {})
    for name, expected_hash in attachments.items():
        path = Path(name)
        if not path.is_absolute() or not path.is_file() or digest(path) != expected_hash:
            errors.append(f"Selected attachment missing or changed: {name}")
        if path.name not in actual:
            errors.append(f"Selected attachment not named in the email: {path.name}")
    selected_names = {Path(p).name for p in attachments}
    remaining = actual
    for name in sorted(selected_names, key=len, reverse=True):
        remaining = remaining.replace(name, "")
    for mentioned in re.findall(r"[\w.-]+\.(?:pdf|xlsx|txt)\b", remaining, re.I):
        if mentioned not in selected_names:
            errors.append(f"Unselected attachment mentioned: {mentioned}")
    for node in document.root.elements():
        if node.tag in {"script", "iframe", "object", "embed", "form"}:
            errors.append(f"Active content is not allowed in email previews: {node.tag}")
        for attr, value in node.attrs.items():
            if attr.startswith("on"):
                errors.append("Inline event handlers are not allowed.")
            if attr in {"src", "srcset"} and value:
                errors.append(
                    "External/embedded image assets need a separate approved preview review."
                )
            if attr == "href" and value and node.tag == "link":
                errors.append("External stylesheets are not allowed.")
            if (
                attr == "href"
                and value
                and re.match(r"\s*(javascript|data|vbscript):", value, re.I)
            ):
                errors.append("Active-content links are not allowed.")
            if attr == "style" and value and re.search(r"@import|url\s*\(", value, re.I):
                errors.append("Inline CSS assets/imports are not allowed.")
    styles = stylesheet(document)
    if re.search(r"@import|url\s*\(", styles, re.I):
        errors.append("CSS external assets/imports are not allowed.")
    template = Path(contract["approved_template"])
    if template.resolve() == html.resolve():
        errors.append("A new draft cannot be its own approved template.")
    if digest(template) != contract["approved_template_sha256"]:
        errors.append("Approved email template changed.")
    approved = Document(template.read_text(encoding="utf-8-sig"))
    approved_styles = stylesheet(approved)
    if not compact(styles) or compact(styles) != compact(approved_styles):
        errors.append("Preview CSS differs from the approved template.")
    for name in ("body", "header", "badge", "notice"):
        reference = approved.by_id(contract[f"{name}_id"])
        if any(
            regions[name].attrs.get(a, "") != reference.attrs.get(a, "") for a in ("class", "style")
        ):
            errors.append(f"{name} styling differs from the approved template.")
    if confidentiality is not None:
        try:
            reference = approved.by_id(contract["confidentiality_id"])
        except ValueError:
            errors.append("Approved template lacks the confidentiality wrapper line.")
        else:
            if any(
                confidentiality.attrs.get(a, "") != reference.attrs.get(a, "")
                for a in ("class", "style")
            ):
                errors.append("confidentiality styling differs from the approved template.")
    return {
        "status": "blocked" if errors else "email_template_checks_passed",
        "errors": errors,
        "share_ready": False,
        "html_sha256": digest(html),
        "contract_sha256": digest(contract_path),
        "manual_checks_required": [
            "Render desktop/mobile and verify actual navy/gold styling, visibility and clipping.",
            "Review accuracy, recipients and approval boundaries.",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--html", type=Path, required=True)
    parser.add_argument("--contract", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = validate_email(args.html, args.contract)
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(1, f"Email QA blocked: {error}\n")
    print(json.dumps(result, indent=2))
    return 1 if result["errors"] else 0
