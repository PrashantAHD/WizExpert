import json
import re

import pytest

from wizexpert.__main__ import main
from wizexpert.email_qa import CLOSING, NOTICE, validate_email
from wizexpert.workflow_qa import digest


@pytest.fixture
def email(tmp_path):
    attachment = tmp_path / "Assessment.pdf"
    attachment.write_bytes(b"synthetic attachment identity only")
    html = f"""<!doctype html><html><head><style>
    .header {{background:#16324f;color:white}} .gold {{background:#fff4d6}}
    </style></head><body>
    <header id="header" class="header">PRIVATE COMMUNICATION DRAFT
    <h1>Synthetic finding</h1></header>
    <p id="badge" class="gold">Draft - not sent | 2026-10-27</p>
    <p id="notice" class="gold">{NOTICE}</p>
    <p id="subject">Subject: Review requested: Synthetic finding | SNOW: INC123</p>
    <section id="email-body"><p>Hi Team,</p>
    <h3>Issue Description:</h3><p>Observed synthetic risk.</p>
    <h3>Issue Details:</h3><p>SNOW: INC123</p>
    <p>wc-id-example | issue-example</p><p>Attached Assessment.pdf contains the findings.</p>
    <h3>Recommended Remediation Approaches:</h3><p>Review the scoped permissions.</p>
    <p>{CLOSING}</p><p>Best Regards,<br>Example Security Team</p>
    </section></body></html>"""
    target = tmp_path / "email.html"
    template = tmp_path / "approved.html"
    for path in (target, template):
        path.write_text(html, encoding="utf-8")
    contract = {
        "schema_version": 1,
        "kind": "initial",
        "signature": "Example Security Team",
        "title": "Synthetic finding",
        "draft_date": "2026-10-27",
        "ticket": "INC123",
        "body_id": "email-body",
        "subject_id": "subject",
        "header_id": "header",
        "badge_id": "badge",
        "notice_id": "notice",
        "approved_template": str(template),
        "approved_template_sha256": digest(template),
        "attachments": {str(attachment): digest(attachment)},
        "issue_mappings": [{"control_id": "wc-id-example", "issue_id": "issue-example"}],
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
        ("<h3>Issue Description:</h3>", "<h2>Issue Description:</h2>", "h3"),
        ("Issue Details:", "Issue Details", "trailing colons"),
        ("Hi Team,", "Hello everyone,", "Greeting"),
        (CLOSING, "Please fix this soon.", "closing"),
        ("Example Security Team", "Unapproved Sender", "signature"),
        ("PRIVATE COMMUNICATION DRAFT", "Customer email", "header"),
        ("wc-id-example | issue-example", "wc-id-example", "identifier"),
        ("#16324f", "#ff0000", "CSS"),
        ("Review the scoped permissions.", "Please close Wiz issues.", "Disallowed"),
        ("Review the scoped permissions.", "Please provide the ServiceNow ticket.", "Disallowed"),
        ("Assessment.pdf contains", "Other.xlsx contains", "attachment"),
        ("Draft - not sent | 2026-10-27", "Sent successfully", "badge"),
    ],
)
def test_style_and_workflow_drift_fail(email, old, new, expected):
    target, contract = email
    target.write_text(target.read_text(encoding="utf-8").replace(old, new), encoding="utf-8")
    result = validate_email(target, contract)
    assert result["status"] == "blocked"
    assert any(expected.lower() in e.lower() for e in result["errors"])


def test_pending_ticket_is_draft_only(email):
    target, contract = email
    payload = json.loads(contract.read_text())
    payload["ticket"] = None
    contract.write_text(json.dumps(payload), encoding="utf-8")
    target.write_text(target.read_text().replace("INC123", "Pending"), encoding="utf-8")
    result = validate_email(target, contract)
    assert result["errors"] == []
    assert any("outreach remains blocked" in e for e in result["manual_checks_required"])


@pytest.mark.parametrize("kind", ["reply", "progress", "blocker", "closure"])
def test_concise_message_kinds_preserve_approved_wording_without_initial_sections(email, kind):
    target, contract = email
    payload = json.loads(contract.read_text())
    body = "Hi Team, Thank you for the update. Best Regards, Example Security Team"
    payload.update(
        kind=kind,
        approved_subject="Reviewed update",
        approved_body=body,
        issue_mappings=[],
        attachments={},
    )
    contract.write_text(json.dumps(payload), encoding="utf-8")
    content = target.read_text().replace(
        "Review requested: Synthetic finding | SNOW: INC123", "Reviewed update"
    )
    content = re.sub(
        r'<section id="email-body">.*?</section>',
        f'<section id="email-body"><p>{body}</p></section>',
        content,
        flags=re.S,
    )
    target.write_text(content, encoding="utf-8")
    assert validate_email(target, contract)["errors"] == []
    target.write_text(
        content.replace("Thank you for the update.", "Everything is fixed."), encoding="utf-8"
    )
    assert any("reviewed wording" in e for e in validate_email(target, contract)["errors"])


def test_html_hidden_headings_do_not_count(email):
    target, contract = email
    target.write_text(target.read_text().replace("<h3>", "<h3 hidden>"), encoding="utf-8")
    assert validate_email(target, contract)["errors"]


def test_hidden_ancestor_cannot_supply_required_headings(email):
    target, contract = email
    content = target.read_text().replace(
        "<h3>Issue Description:</h3>",
        "<div hidden><h3>Issue Description:</h3></div>",
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
        payload = review_payload(tmp_path, phase, workflow="finding")
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
