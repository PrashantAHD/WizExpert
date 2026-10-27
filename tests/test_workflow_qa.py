import json
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest

from wizexpert.__main__ import main
from wizexpert.workflow_qa import (
    digest,
    hook,
    receipt,
    required_checks,
    rule_hashes,
    rule_inventory,
    validate_review,
)

NOW = datetime(2026, 10, 27, 8, tzinfo=UTC)
QUERY = {
    "tool_name": "list_issues",
    "parameters": {
        "first": 20,
        "severity": ["HIGH"],
        "status": ["OPEN", "IN_PROGRESS"],
    },
}


def save(path, data):
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def review_payload(tmp_path, phase="collection", workflow="governance"):
    evidence = tmp_path / "reviewed-evidence.json"
    evidence.write_text('{"synthetic": true}', encoding="utf-8")
    return {
        "schema_version": 2,
        "workflow": workflow,
        "phase": phase,
        "run_id": "synthetic-run",
        "scope": "Synthetic approved tenant",
        "preparer": "report-preparer",
        "reviewer": "separate-reviewer",
        "started_at": (NOW - timedelta(hours=2)).isoformat(),
        "reviewed_at": (NOW - timedelta(hours=1)).isoformat(),
        "expires_at": (NOW + timedelta(hours=1)).isoformat(),
        "rule_sha256": rule_hashes(workflow),
        "evidence_sha256": {str(evidence): digest(evidence)},
        "request_evidence": str(evidence),
        "requested_deliverables": [],
        "private_rule_sources": {},
        "parity_groups": [],
        "unresolved_conflicts": [],
        "rule_coverage": {
            name: {
                "source_sha256": value,
                "verdict": "pass",
                "rationale": "Synthetic section review.",
                "evidence": [str(evidence)],
            }
            for name, value in rule_inventory(workflow).items()
        },
        "checks": {
            name: {
                "verdict": "pass",
                "rationale": "Reviewed against synthetic evidence.",
                "evidence": [str(evidence)],
            }
            for name in required_checks(workflow, phase)
        },
        "allowed_wiz_queries": [QUERY],
    }


@pytest.fixture
def reviewed(tmp_path):
    return save(tmp_path / "review.json", review_payload(tmp_path))


@pytest.mark.parametrize(
    "mutation,message",
    [
        ("self", "self-certify"),
        ("missing", "Missing or unexpected"),
        ("pending", "not verified"),
        ("evidence", "evidence changed"),
        ("rules", "rules changed"),
        ("expired", "expired"),
        ("rationale", "reasoning"),
        ("future", "future-dated"),
    ],
)
def test_qa_fails_closed(reviewed, mutation, message):
    data = json.loads(reviewed.read_text())
    first = next(iter(data["checks"]))
    if mutation == "self":
        data["reviewer"] = " REPORT-PREPARER "
    elif mutation == "missing":
        del data["checks"][first]
    elif mutation == "pending":
        data["checks"][first]["verdict"] = "not_verified"
    elif mutation == "evidence":
        Path = type(reviewed)
        Path(next(iter(data["evidence_sha256"]))).write_text("changed")
    elif mutation == "rules":
        data["rule_sha256"][next(iter(data["rule_sha256"]))] = "0" * 64
    elif mutation == "expired":
        data["expires_at"] = NOW.isoformat()
    elif mutation == "rationale":
        data["checks"][first]["rationale"] = ""
    else:
        data["reviewed_at"] = (NOW + timedelta(minutes=1)).isoformat()
    save(reviewed, data)
    with pytest.raises(ValueError, match=message):
        validate_review(reviewed, now=NOW)


def test_hook_blocks_unreviewed_bulk_and_allows_count_probe():
    with pytest.raises(ValueError, match="requires a workflow QA"):
        hook({"tool_name": "wiz-execute", "tool_input": QUERY}, None)
    count = {"tool_name": "list_issues", "parameters": {"first": 1}}
    assert hook({"tool_name": "wiz-execute", "tool_input": count}, None) == {}
    with pytest.raises(ValueError, match="requires"):
        hook(
            {
                "tool_name": "multi_tool_use.parallel",
                "tool_input": {
                    "tool_uses": [{"recipient_name": "functions.wiz-execute", "parameters": QUERY}]
                },
            },
            None,
        )


def test_hook_exact_query_and_pagination(reviewed):
    with patch("wizexpert.workflow_qa.datetime") as clock:
        clock.now.return_value = NOW
        clock.fromisoformat = datetime.fromisoformat
        page = json.loads(json.dumps(QUERY))
        page["parameters"]["after"] = "returned-cursor"
        assert hook({"tool_name": "functions.wiz-execute", "tool_input": page}, reviewed) == {}
        page["parameters"]["status"] = ["RESOLVED"]
        with pytest.raises(ValueError, match="outside the reviewed plan"):
            hook({"tool_name": "wiz-execute", "tool_input": page}, reviewed)


def test_full_history_needs_evidence_backed_approval(reviewed):
    data = json.loads(reviewed.read_text())
    data["allowed_wiz_queries"][0]["parameters"]["status"] = ["OPEN", "IN_PROGRESS", "RESOLVED"]
    save(reviewed, data)
    with pytest.raises(ValueError, match="historical collection"):
        validate_review(reviewed, now=NOW)
    data["full_refresh_approval"] = {
        "reason": "Documented coverage gap",
        "approved_by": "report-owner",
        "evidence": next(iter(data["evidence_sha256"])),
    }
    save(reviewed, data)
    assert validate_review(reviewed, now=NOW)["phase"] == "collection"


@pytest.mark.parametrize("premature", [True, False])
def test_actual_calls_detect_deviation_even_when_all_checkboxes_pass(tmp_path, premature):
    collection = save(tmp_path / "collection.json", review_payload(tmp_path))
    data = review_payload(tmp_path, "generation")
    data["reviewed_at"] = (NOW - timedelta(minutes=1)).isoformat()
    data["previous_review"] = str(collection)
    args = json.loads(json.dumps(QUERY))
    if not premature:
        args["parameters"]["severity"] = ["LOW"]
    event_time = NOW - timedelta(minutes=90 if premature else 30)
    log = tmp_path / "activity.jsonl"
    log.write_text(
        json.dumps(
            {
                "timestamp": event_time.isoformat(),
                "type": "tool.execution_start",
                "data": {"toolName": "wiz-execute", "arguments": args},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    data["activity_log"] = str(log)
    data["evidence_sha256"].update({str(collection): digest(collection), str(log): digest(log)})
    generation = save(tmp_path / "generation.json", data)
    with pytest.raises(ValueError, match="before workflow QA|deviated"):
        validate_review(generation, now=NOW)


def test_qa_receipt_never_claims_release_approval(reviewed):
    with patch("wizexpert.workflow_qa.datetime") as clock:
        clock.now.return_value = NOW
        clock.fromisoformat = datetime.fromisoformat
        result = receipt(reviewed, "collection")
    assert result["status"] == "workflow_checks_passed"
    assert result["share_ready"] is False
    assert len(result["limitations"]) == 3


def test_requirements_cli_and_invalid_review_exit(capsys, tmp_path):
    assert main(["workflow-qa", "requirements", "--workflow", "finding", "--phase", "handoff"]) == 0
    assert (
        "email-template-and-identifiers" in json.loads(capsys.readouterr().out)["required_checks"]
    )
    with pytest.raises(SystemExit) as exc:
        main(["workflow-qa", "check", "--review", str(tmp_path / "missing.json")])
    assert exc.value.code == 1


@pytest.mark.parametrize(
    "workflow", ["governance", "finding", "setup", "publication", "remediation"]
)
def test_broad_profiles_are_explicit_and_evidence_bound(tmp_path, workflow):
    data = review_payload(tmp_path, workflow=workflow)
    if workflow == "remediation":
        data["target_stage"] = 5
    path = save(tmp_path / "review.json", data)
    assert validate_review(path, now=NOW)["workflow"] == workflow
    data["rule_coverage"].pop(next(iter(data["rule_coverage"])))
    save(path, data)
    with pytest.raises(ValueError, match="coverage is incomplete"):
        validate_review(path, now=NOW)


def test_campaign_requires_current_private_rules(tmp_path):
    data = review_payload(tmp_path, workflow="campaign")
    path = save(tmp_path / "review.json", data)
    with pytest.raises(ValueError, match="private campaign rules"):
        validate_review(path, now=NOW)
    private = tmp_path / "private-rules.md"
    private.write_text("# Metrics\nFinding counts are not asset counts.\n", encoding="utf-8")
    data["private_rule_sources"] = {str(private): digest(private)}
    data["evidence_sha256"].update(data["private_rule_sources"])
    for name, value in rule_inventory("campaign", data["private_rule_sources"]).items():
        if name not in data["rule_coverage"]:
            data["rule_coverage"][name] = {
                "source_sha256": value,
                "verdict": "pass",
                "rationale": "Synthetic private rules checked.",
                "evidence": [str(private)],
            }
    save(path, data)
    assert validate_review(path, now=NOW)["workflow"] == "campaign"
    private.write_text("# Changed metrics\nReview again.", encoding="utf-8")
    with pytest.raises(ValueError, match="evidence changed"):
        validate_review(path, now=NOW)


@pytest.mark.parametrize(
    "mutation,message",
    [
        ("unverified", "unverified"),
        ("stale", "stale"),
        ("out_of_scope", "scope decision"),
        ("conflict", "conflicts"),
        ("request", "original request"),
        ("missing_manifest", "requested-deliverable"),
    ],
)
def test_rule_coverage_and_original_request_cannot_be_skipped(tmp_path, mutation, message):
    data = review_payload(tmp_path)
    section = next(iter(data["rule_coverage"].values()))
    if mutation == "unverified":
        section["verdict"] = "unsupported"
    elif mutation == "stale":
        section["source_sha256"] = "0" * 64
    elif mutation == "out_of_scope":
        section["verdict"] = "out_of_scope"
    elif mutation == "conflict":
        data["unresolved_conflicts"] = ["Unresolved instruction conflict"]
    elif mutation == "request":
        del data["request_evidence"]
    else:
        del data["requested_deliverables"]
    path = save(tmp_path / "review.json", data)
    with pytest.raises(ValueError, match=message):
        validate_review(path, now=NOW)


def test_heading_only_rules_are_included_and_code_examples_are_not(tmp_path):
    private = tmp_path / "rules.md"
    private.write_text(
        "# Never skip approval\n## Evidence\n```text\n# Example\n```\n", encoding="utf-8"
    )
    inventory = rule_inventory("setup", {str(private): digest(private)})
    assert any("Never skip approval" in name for name in inventory)
    assert not any(name.endswith(":Example") for name in inventory)


def test_stage_tracker_cannot_certify_unapproved_remediation(tmp_path):
    from wizexpert.workflow import create_tracker
    from wizexpert.workflow_qa import validate_remediation

    data = review_payload(tmp_path, phase="generation", workflow="remediation")
    data["target_stage"] = 6
    tracker = tmp_path / "tracker.json"
    create_tracker(
        tracker,
        finding_id="synthetic",
        control_id="rule",
        scope=data["scope"],
        summary="Starting",
        next_action="Collect evidence",
    )
    data["tracker"] = str(tracker)
    data["evidence_sha256"][str(tracker)] = digest(tracker)
    with pytest.raises(ValueError, match="authorization/verification"):
        validate_remediation(data, data["evidence_sha256"])


def test_complete_finding_review_checks_requested_html_without_forcing_email(tmp_path):
    from test_artifact_qa import artifact, native_review

    item, evidence = artifact(tmp_path, "html")
    native_review(tmp_path, item, evidence)
    log = tmp_path / "activity.jsonl"
    log.write_text(
        json.dumps(
            {
                "timestamp": (NOW - timedelta(minutes=30)).isoformat(),
                "type": "tool.execution_start",
                "data": {"toolName": "view", "arguments": {}},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    previous = None
    for phase, minutes in (("collection", 60), ("generation", 20), ("handoff", 1)):
        data = review_payload(tmp_path, phase, workflow="finding")
        data["reviewer"] = "reviewer"
        data["requested_deliverables"] = [{"id": "html", "kind": "html"}]
        data["reviewed_at"] = (NOW - timedelta(minutes=minutes)).isoformat()
        if previous:
            data["previous_review"], data["activity_log"] = str(previous), str(log)
            data["evidence_sha256"].update({str(previous): digest(previous), str(log): digest(log)})
        if phase == "handoff":
            data["artifacts"] = [item]
            data["evidence_sha256"].update(evidence)
        previous = save(tmp_path / f"{phase}.json", data)
    assert validate_review(previous, now=NOW)["phase"] == "handoff"


def test_deliverables_cannot_be_removed_between_phases(tmp_path):
    data = review_payload(tmp_path)
    data["requested_deliverables"] = [{"id": "report", "kind": "xlsx"}]
    collection = save(tmp_path / "collection.json", data)
    generation = review_payload(tmp_path, "generation")
    generation["previous_review"] = str(collection)
    generation["evidence_sha256"][str(collection)] = digest(collection)
    path = save(tmp_path / "generation.json", generation)
    with pytest.raises(ValueError, match="deliverables cannot disappear"):
        validate_review(path, now=NOW)
