import json

import pytest

from wizexpert.__main__ import main
from wizexpert.email_qa import NOTICE, validate_email
from wizexpert.workflow_qa import digest

FOOTER = "Confidential - Example Org | Example Security | Source: Wiz | Reporting dates: UTC"
SUBJECT = "Reviewed update"
BODY = (
    "Hi Team, Thank you for the update. Attached Assessment.pdf contains the details. "
    "Best Regards, Example Security Team"
)


@pytest.fixture
def email(tmp_path):
    attachment = tmp_path / "Assessment.pdf"
    attachment.write_bytes(b"synthetic attachment identity only")
    html = f"""<!doctype html><html><head><style>
    .header {{background:#16324f;color:white}} .gold {{background:#fff4d6}}
    </style></head><body>
    <header id="header" class="header">PRIVATE COMMUNICATION DRAFT
    <h1>Synthetic update</h1></header>
    <p id="badge" class="gold">Draft - not sent | 2026-10-27</p>
    <p id="notice" class="gold">{NOTICE}</p>
    <p id="confidentiality" class="gold">{FOOTER}</p>
    <p id="subject">Subject: {SUBJECT}</p>
    <section id="email-body"><p>Hi Team,</p>
    <p>Thank you for the update.</p><p>Attached Assessment.pdf contains the details.</p>
    <p>Best Regards,<br>Example Security Team</p>
    </section></body></html>"""
    target = tmp_path / "email.html"
    template = tmp_path / "approved.html"
    for path in (target, template):
        path.write_text(html, encoding="utf-8")
    contract = {
        "schema_version": 1,
        "kind": "progress",
        "signature": "Example Security Team",
        "title": "Synthetic update",
        "draft_date": "2026-10-27",
        "approved_subject": SUBJECT,
        "approved_body": BODY,
        "body_id": "email-body",
        "subject_id": "subject",
        "header_id": "header",
        "badge_id": "badge",
        "notice_id": "notice",
        "confidentiality": FOOTER,
        "confidentiality_id": "confidentiality",
        "approved_template": str(template),
        "approved_template_sha256": digest(template),
        "attachments": {str(attachment): digest(attachment)},
    }
    contract_path = tmp_path / "contract.json"
    contract_path.write_text(json.dumps(contract), encoding="utf-8")
    return target, contract_path


def test_actual_template_pass_remains_draft(email):
    result = validate_email(*email)
    assert result["errors"] == []
    assert result["status"] == "email_template_checks_passed"
    assert result["share_ready"] is False


@pytest.mark.parametrize(
    "old,new,expected",
    [
        ("Hi Team,", "Hello everyone,", "Greeting"),
        ("Example Security Team", "Unapproved Sender", "signature"),
        ("Thank you for the update.", "Everything is fixed.", "reviewed wording"),
        (f"Subject: {SUBJECT}", "Subject: Something else", "subject"),
        ("PRIVATE COMMUNICATION DRAFT", "Customer email", "header"),
        ("#16324f", "#ff0000", "CSS"),
        ("Thank you for the update.", "Please close Wiz issues.", "Disallowed"),
        ("Assessment.pdf contains", "Other.xlsx contains", "attachment"),
        ("Draft - not sent | 2026-10-27", "Sent successfully", "badge"),
        (f'<p id="confidentiality" class="gold">{FOOTER}</p>', "", "confidentiality"),
        (f'class="gold">{FOOTER}', 'class="gold">Confidential', "confidentiality"),
        (f'class="gold">{FOOTER}', f'class="gold" hidden>{FOOTER}', "confidentiality"),
        (f'class="gold">{FOOTER}', f'class="other">{FOOTER}', "confidentiality styling"),
        ("<p>Hi Team,</p>", f"<p>Hi Team,</p><p>{FOOTER}</p>", "leaked"),
    ],
)
def test_style_and_wording_drift_fail(email, old, new, expected):
    target, contract = email
    content = target.read_text(encoding="utf-8")
    assert old in content
    target.write_text(content.replace(old, new), encoding="utf-8")
    result = validate_email(target, contract)
    assert result["status"] == "blocked"
    assert any(expected.lower() in e.lower() for e in result["errors"])


def test_confidentiality_decision_must_be_recorded(email):
    target, contract = email
    payload = json.loads(contract.read_text())
    del payload["confidentiality"]
    contract.write_text(json.dumps(payload), encoding="utf-8")
    assert any(
        "confidentiality-line decision" in e for e in validate_email(target, contract)["errors"]
    )
    payload["confidentiality"] = None
    contract.write_text(json.dumps(payload), encoding="utf-8")
    assert validate_email(target, contract)["errors"] == []


@pytest.mark.parametrize("kind", ["reply", "progress", "blocker", "closure"])
def test_message_kinds_preserve_approved_wording(email, kind):
    target, contract = email
    payload = json.loads(contract.read_text())
    payload["kind"] = kind
    contract.write_text(json.dumps(payload), encoding="utf-8")
    assert validate_email(target, contract)["errors"] == []


def test_unsupported_message_kind_is_rejected(email):
    target, contract = email
    payload = json.loads(contract.read_text())
    payload["kind"] = "initial"
    contract.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="Unsupported email contract"):
        validate_email(target, contract)


def test_html_hidden_body_does_not_count(email):
    target, contract = email
    content = target.read_text().replace(
        '<section id="email-body">', '<section hidden id="email-body">'
    )
    target.write_text(content, encoding="utf-8")
    assert validate_email(target, contract)["errors"]


def test_email_cli_returns_failure_for_real_template_drift(email, capsys):
    target, contract = email
    target.write_text(target.read_text().replace("Best Regards,", "Cheers,"), encoding="utf-8")
    assert main(["email-qa", "--html", str(target), "--contract", str(contract)]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "blocked"


def test_workflow_handoff_cannot_pass_by_attesting_to_a_bad_email(email, tmp_path):
    from datetime import timedelta

    from test_workflow_qa import NOW, review_payload, save

    from wizexpert.workflow_qa import validate_review

    html, contract = email
    html.write_text(html.read_text().replace("Best Regards,", "Cheers,"), encoding="utf-8")
    log = tmp_path / "activity.jsonl"
    log.write_text(
        json.dumps(
            {
                "timestamp": (NOW - timedelta(minutes=30)).isoformat(),
                "type": "tool.execution_start",
                "data": {"toolName": "view", "arguments": {"path": str(html)}},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    previous = None
    for phase, minutes in (("collection", 60), ("generation", 20), ("handoff", 1)):
        payload = review_payload(tmp_path, phase, workflow="setup")
        payload["requested_deliverables"] = [{"id": "email", "kind": "email"}]
        payload["reviewed_at"] = (NOW - timedelta(minutes=minutes)).isoformat()
        if previous:
            payload["previous_review"] = str(previous)
            payload["activity_log"] = str(log)
            payload["evidence_sha256"].update(
                {str(previous): digest(previous), str(log): digest(log)}
            )
        if phase == "handoff":
            payload["artifacts"] = [
                {"id": "email", "kind": "email", "path": str(html), "contract": str(contract)}
            ]
            payload["evidence_sha256"].update(
                {str(html): digest(html), str(contract): digest(contract)}
            )
        previous = save(tmp_path / f"{phase}.json", payload)
    with pytest.raises(ValueError, match="Actual email failed template QA"):
        validate_review(previous, now=NOW)
