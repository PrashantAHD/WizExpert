import json

import pytest

from wizexpert.__main__ import main
from wizexpert.follow_up_email import render, render_file

LINE = "Confidential - Example Org | Example Security | Source: Wiz | Reporting dates: UTC"
def ph(name):
    return "{{" + name + "}}"


def h3(title):
    return f'<h3 style="margin:0">{title}</h3>'


def rep(name, tag):
    item = f"<li>{ph('.text')}</li>"
    block = f"<!-- repeat:{name} -->{item}<!-- /repeat:{name} -->"
    return f"<{tag}>{block}</{tag}>"


TEMPLATE = "\n".join(
    [
        f"<!doctype html><html><head><title>{ph('topic')}</title></head><body>",
        f'<header id="email-header"><h1>{ph("email_title")}</h1>',
        f'<span id="email-badge">Draft | {ph("draft_date")}</span></header>',
        '<aside id="email-notice">Internal preparation note - do not copy into email: '
        "confirm recipients.</aside>",
        f'<p id="email-confidentiality">{LINE}</p>',
        f'<section><p id="email-subject">{ph("subject_prefix")}: {ph("subject_topic")}'
        f" | SNOW: {ph('snow_reference')}</p>",
        '<div id="email-body">',
        "<p>Hi Team,</p>",
        "<!-- mode:reply -->",
        f"<p>Thanks for {ph('subject_topic')}.</p>",
        h3("What We Received:") + f"<p>{ph('received_summary')}</p>",
        h3("Acknowledged:") + rep("acknowledgements", "ul"),
        h3("Answers and Next Steps:") + rep("answers_next_steps", "ol"),
        h3("Confirmations Requested:") + rep("requested_confirmations", "ul"),
        "<!-- /mode:reply -->",
        "<!-- mode:progress -->",
        f"<p>{ph('progress_request')}</p>",
        h3("Issue and Control Context:") + f"<ul><li>{ph('issue_rule_id')}</li></ul>",
        h3("Last Agreed Action:") + f"<p>{ph('last_agreed_action')}</p>",
        h3("Response Requested:") + rep("response_requested", "ul"),
        "<!-- /mode:progress -->",
        f"<p>{ph('closing_note')} Let us know if you need any assistance.</p>",
        "<p>Best Regards,<br>Example Sender</p>",
        "</div></section>",
        f'<div class="links"><a href="{ph("attachment_name")}">'
        f"Attachment: {ph('attachment_name')}</a></div>",
        "</body></html>",
    ]
)


NAMES = [
    "topic email_title draft_date subject_prefix subject_topic snow_reference closing_note",
    "received_summary acknowledgements answers_next_steps requested_confirmations",
    "progress_request issue_rule_id last_agreed_action response_requested attachment_name",
]
FIELDS = {
    "output": {"confidentiality_line": LINE},
    "fields": {name: "x" for group in NAMES for name in group.split()},
}
ITEMS = [{"text": "One & <two>"}]
COMMON = {
    "topic": "T",
    "email_title": "Title",
    "draft_date": "1 Jan 2026",
    "subject_topic": "Topic",
    "snow_reference": "Pending",
    "closing_note": "Thanks.",
}
REPLY = {
    **COMMON,
    "subject_prefix": "Re",
    "received_summary": "A <b>summary</b>",
    "acknowledgements": ITEMS,
    "answers_next_steps": ITEMS,
    "requested_confirmations": ITEMS,
}
PROGRESS = {
    **COMMON,
    "subject_prefix": "Follow-up",
    "progress_request": "Please update.",
    "issue_rule_id": "rule-1",
    "last_agreed_action": "Action",
    "response_requested": ITEMS,
}


def test_reply_renders_escaped_without_markers_or_attachment():
    out = render(TEMPLATE, FIELDS, "reply", REPLY)
    assert "A &lt;b&gt;summary&lt;/b&gt;" in out and "One &amp; &lt;two&gt;" in out
    assert "<!--" not in out and "{{" not in out and "Please update" not in out
    assert 'class="links"' not in out and LINE in out


def test_progress_with_attachment():
    out = render(TEMPLATE, FIELDS, "progress", PROGRESS, "Report.xlsx")
    assert 'href="Report.xlsx"' in out and "What We Received" not in out


@pytest.mark.parametrize("mode", [None, "", "other", ["reply", "progress"], []])
def test_mode_rejected(mode):
    with pytest.raises(ValueError, match="mode"):
        render(TEMPLATE, FIELDS, mode, REPLY)


def test_missing_unknown_and_other_mode_fields():
    with pytest.raises(ValueError, match="Missing"):
        render(TEMPLATE, FIELDS, "reply", {k: v for k, v in REPLY.items() if k != "topic"})
    with pytest.raises(ValueError, match="Unknown"):
        render(TEMPLATE, FIELDS, "reply", {**REPLY, "extra": "x"})
    with pytest.raises(ValueError, match="other mode"):
        render(TEMPLATE, FIELDS, "reply", {**REPLY, "progress_request": "x"})
    with pytest.raises(ValueError, match="non-empty"):
        render(TEMPLATE, FIELDS, "reply", {**REPLY, "acknowledgements": []})
    with pytest.raises(ValueError, match="only 'text'"):
        render(TEMPLATE, FIELDS, "reply", {**REPLY, "acknowledgements": ["raw"]})


def test_unresolved_marker_in_value_rejected():
    with pytest.raises(ValueError, match="unresolved"):
        render(TEMPLATE, FIELDS, "reply", {**REPLY, "received_summary": "{{leak}}"})


def test_subject_prefix_and_attachment_rules():
    with pytest.raises(ValueError, match="Subject"):
        render(TEMPLATE, FIELDS, "reply", {**REPLY, "subject_prefix": "Follow-up"})
    for bad in ("..\\x.pdf", "a/b.pdf", "http://x/y.pdf", ""):
        with pytest.raises(ValueError):
            render(TEMPLATE, FIELDS, "reply", REPLY, bad)
    with pytest.raises(ValueError, match="attachment_name"):
        render(TEMPLATE, FIELDS, "reply", {**REPLY, "attachment_name": "a.pdf"})


def test_template_rules():
    with pytest.raises(ValueError, match="confidentiality"):
        render(TEMPLATE.replace(LINE, "Changed"), FIELDS, "reply", REPLY)
    with pytest.raises(ValueError, match="client data"):
        render(
            TEMPLATE.replace("Example Sender", "a" + chr(64) + "b.example"), FIELDS, "reply", REPLY
        )
    with pytest.raises(ValueError, match="Headings|exactly one"):
        render(TEMPLATE.replace("Acknowledged:", "Noted:"), FIELDS, "reply", REPLY)
    with pytest.raises(ValueError, match="greeting|start"):
        render(TEMPLATE.replace("Hi Team,", "Hello,"), FIELDS, "reply", REPLY)


def test_destination_html_only(tmp_path):
    template = tmp_path / "t.html"
    template.write_text(TEMPLATE, encoding="utf-8")
    fields = tmp_path / "f.json"
    fields.write_text(json.dumps(FIELDS), encoding="utf-8")
    for name in ("a.txt", "a.pdf", "a.md"):
        with pytest.raises(ValueError):
            render_file(template, fields, "reply", REPLY, tmp_path / name)
    target = render_file(template, fields, "reply", REPLY, tmp_path / "a.html")
    assert target.exists()
    with pytest.raises(ValueError, match="exists"):
        render_file(template, fields, "reply", REPLY, target)


def test_cli(tmp_path, capsys):
    (tmp_path / "t.html").write_text(TEMPLATE, encoding="utf-8")
    (tmp_path / "f.json").write_text(json.dumps(FIELDS), encoding="utf-8")
    (tmp_path / "v.json").write_text(json.dumps(PROGRESS), encoding="utf-8")
    base = [
        "follow-up-email",
        "--template",
        str(tmp_path / "t.html"),
        "--fields",
        str(tmp_path / "f.json"),
        "--values",
        str(tmp_path / "v.json"),
        "--output",
        str(tmp_path / "o.html"),
    ]
    with pytest.raises(SystemExit):
        main(base)
    assert main([*base, "--mode", "progress"]) == 0
    assert '"sent": false' in capsys.readouterr().out


