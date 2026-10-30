import json
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest

from wizexpert.__main__ import main
from wizexpert.workflow_qa import (
    collection_check,
    digest,
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
    }


@pytest.fixture
def reviewed(tmp_path):
    return save(tmp_path / "review.json", review_payload(tmp_path))


@pytest.mark.parametrize(
    "mutation,message",
    [
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
    if mutation == "missing":
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


COUNT = {"tool_name": "list_issues", "parameters": {"first": 1}}


@pytest.mark.parametrize(
    "parameters",
    [
        {"first": 1, "after": ""},
        {"first": 1, "after": 0},
        {"first": 1, "after": 5},
        {"first": 1, "after": ["c"]},
        {"first": 1, "after": False},
    ],
)
def test_is_bulk_rejects_odd_cursor_values(parameters):
    from wizexpert.workflow_qa import is_bulk

    with pytest.raises(ValueError, match="cursor"):
        is_bulk({"tool_name": "list_issues", "parameters": parameters})
    for args in ({"first": 1}, {"first": 1, "after": None}):
        assert is_bulk({"tool_name": "list_issues", "parameters": args}) is False
    assert is_bulk({"tool_name": "list_issues", "parameters": {"first": 1, "after": "c"}}) is True
    assert is_bulk({"tool_name": " LIST_ISSUES ", "parameters": {"first": 20}}) is True
    assert is_bulk({"tool_name": "Execute_Graph_Query", "parameters": {"first": 9}}) is True
    assert is_bulk({"tool_name": "get_issue", "parameters": {"first": 50}}) is False
    with pytest.raises(ValueError, match="tool name"):
        is_bulk({"tool_name": ["list_issues"], "parameters": {"first": 50}})


def manifest(tmp_path, **override):
    data = {
        "started_at": (NOW - timedelta(hours=2)).isoformat(),
        "ended_at": (NOW - timedelta(minutes=10)).isoformat(),
        "reused_sources": ["prior-snapshot"],
        "counts": [{"name": "open-issues", "expected": 5, "collected": 5}],
    }
    data.update(override)
    return data


def activity(tmp_path, args=None):
    log = tmp_path / "activity.jsonl"
    event = {
        "timestamp": (NOW - timedelta(minutes=30)).isoformat(),
        "type": "tool.execution_start",
        "data": {"toolName": "wiz-execute", "arguments": args or QUERY},
    }
    log.write_text(json.dumps(event) + "\n", encoding="utf-8")
    return log


def test_collection_check_passes_reuse_first_and_reconciled_counts(tmp_path):
    result = collection_check(activity(tmp_path), manifest(tmp_path))
    assert result["status"] == "pass" and result["flags"] == []


@pytest.mark.parametrize(
    "override,message",
    [
        ({"reused_sources": []}, "Reuse-first: name"),
        ({"counts": [{"name": "n", "expected": 5, "collected": 4}]}, "mismatch"),
        ({"counts": []}, "no counts"),
        ({"started_at": "bad"}, "started_at"),
    ],
)
def test_collection_check_flags_report_not_calls(tmp_path, override, message):
    result = collection_check(activity(tmp_path), manifest(tmp_path, **override))
    assert result["status"] == "flagged"
    assert any(message in flag for flag in result["flags"])


def test_collection_check_flags_unjustified_full_history_only(tmp_path):
    full = {"tool_name": "list_issues", "parameters": {"first": 20, "status": ["RESOLVED"]}}
    log = activity(tmp_path, full)
    assert collection_check(log, manifest(tmp_path))["status"] == "flagged"
    justified = manifest(tmp_path, full_refresh_reason="Documented coverage gap")
    assert collection_check(log, justified)["status"] == "pass"


def test_collection_check_cli_exit_codes(tmp_path, capsys):
    log = activity(tmp_path)
    ok = save(tmp_path / "ok.json", manifest(tmp_path))
    bad = save(tmp_path / "bad.json", manifest(tmp_path, reused_sources=[]))
    base = ["workflow-qa", "collection-check", "--activity-log", str(log)]
    assert main([*base, "--manifest", str(ok)]) == 0
    assert main([*base, "--manifest", str(bad)]) == 1
    assert "flagged" in capsys.readouterr().out


def test_generation_requires_independent_reviewer_and_passing_collection_check(tmp_path):
    collection = save(tmp_path / "collection.json", review_payload(tmp_path))
    assert validate_review(collection, now=NOW)["phase"] == "collection"
    data = review_payload(tmp_path, "generation")
    data["reviewer"] = " REPORT-PREPARER "
    path = save(tmp_path / "generation.json", data)
    with pytest.raises(ValueError, match="self-certify"):
        validate_review(path, now=NOW)
    data["reviewer"] = "separate-reviewer"
    data["reviewed_at"] = (NOW - timedelta(minutes=1)).isoformat()
    data["previous_review"] = str(collection)
    log = activity(tmp_path)
    flagged = save(tmp_path / "manifest.json", manifest(tmp_path, reused_sources=[]))
    data["activity_log"], data["collection_manifest"] = str(log), str(flagged)
    data["evidence_sha256"].update({str(p): digest(p) for p in (collection, log, flagged)})
    path = save(tmp_path / "generation.json", data)
    with pytest.raises(ValueError, match="Post-collection check flagged"):
        validate_review(path, now=NOW)


def test_qa_receipt_never_claims_release_approval(reviewed):
    with patch("wizexpert.workflow_qa.datetime") as clock:
        clock.now.return_value = NOW
        clock.fromisoformat = datetime.fromisoformat
        result = receipt(reviewed, "collection")
    assert result["status"] == "workflow_checks_passed"
    assert result["share_ready"] is False
    assert len(result["limitations"]) == 3


def test_requirements_cli_and_invalid_review_exit(capsys, tmp_path):
    argv = ["workflow-qa", "requirements", "--workflow", "campaign", "--phase", "handoff"]
    assert main(argv) == 0
    assert (
        "campaign-closure-criteria" in json.loads(capsys.readouterr().out)["required_checks"]
    )
    with pytest.raises(SystemExit) as exc:
        main(["workflow-qa", "check", "--review", str(tmp_path / "missing.json")])
    assert exc.value.code == 1


@pytest.mark.parametrize("workflow", ["governance", "setup", "publication"])
def test_broad_profiles_are_explicit_and_evidence_bound(tmp_path, workflow):
    data = review_payload(tmp_path, workflow=workflow)
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


def test_complete_review_checks_requested_html_without_forcing_email(tmp_path):
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
    checked = save(tmp_path / "manifest.json", manifest(tmp_path))
    previous = None
    for phase, minutes in (("collection", 60), ("generation", 20), ("handoff", 1)):
        data = review_payload(tmp_path, phase, workflow="setup")
        data["reviewer"] = "reviewer"
        data["requested_deliverables"] = [{"id": "html", "kind": "html"}]
        data["reviewed_at"] = (NOW - timedelta(minutes=minutes)).isoformat()
        if previous:
            data["previous_review"], data["activity_log"] = str(previous), str(log)
            data["collection_manifest"] = str(checked)
            data["evidence_sha256"].update({str(f): digest(f) for f in (previous, log, checked)})
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


HTML = {"id": "html", "kind": "html"}
SUMMARY = {"id": "summary", "kind": "xlsx"}


def owner_request(tmp_path):
    request = tmp_path / "owner-request.txt"
    request.write_text("Synthetic owner request.", encoding="utf-8")
    return request


def owner_change(request_path, **override):
    entry = {
        "id": "change-1",
        "kind": "addition",
        "request": str(request_path),
        "summary": "Synthetic owner-requested summary workbook.",
        "prior_logic_verified": True,
        "deliverables": ["summary"],
    }
    entry.update(override)
    return entry


def chain(tmp_path, first, second, first_changes=None, second_changes=None):
    """Save a collection review and a generation review; return the generation path."""
    request = owner_request(tmp_path)
    log = activity(tmp_path)
    checked = save(tmp_path / "manifest.json", manifest(tmp_path))
    collection = review_payload(tmp_path, workflow="setup")
    collection["requested_deliverables"] = first
    if first_changes is not None:
        collection["owner_changes"] = first_changes
    collection["evidence_sha256"][str(request)] = digest(request)
    collection_path = save(tmp_path / "collection.json", collection)
    generation = review_payload(tmp_path, "generation", workflow="setup")
    generation["requested_deliverables"] = second
    if second_changes is not None:
        generation["owner_changes"] = second_changes
    generation["reviewed_at"] = (NOW - timedelta(minutes=20)).isoformat()
    generation["previous_review"], generation["activity_log"] = str(collection_path), str(log)
    generation["collection_manifest"] = str(checked)
    generation["evidence_sha256"].update(
        {str(f): digest(f) for f in (request, collection_path, log, checked)}
    )
    return save(tmp_path / "generation.json", generation), request


def test_owner_added_deliverable_is_accepted_as_scope_change(tmp_path):
    request = owner_request(tmp_path)
    path, request = chain(tmp_path, [HTML], [HTML, SUMMARY], second_changes=[owner_change(request)])
    assert validate_review(path, now=NOW)["phase"] == "generation"


def test_owner_added_deliverable_without_owner_change_is_rejected(tmp_path):
    path, _ = chain(tmp_path, [HTML], [HTML, SUMMARY])
    with pytest.raises(ValueError, match="owner-requested addition"):
        validate_review(path, now=NOW)


def test_owner_added_deliverable_needs_matching_addition_entry(tmp_path):
    request = owner_request(tmp_path)
    changes = [owner_change(request, deliverables=["html"])]
    path, _ = chain(tmp_path, [HTML], [HTML, SUMMARY], second_changes=changes)
    with pytest.raises(ValueError, match="owner-requested addition"):
        validate_review(path, now=NOW)
    changes = [owner_change(request, kind="rule_update", persisted_in=[str(request)])]
    path, _ = chain(tmp_path, [HTML], [HTML, SUMMARY], second_changes=changes)
    with pytest.raises(ValueError, match="owner-requested addition"):
        validate_review(path, now=NOW)


def test_owner_change_cannot_remove_or_alter_existing_deliverable(tmp_path):
    request = owner_request(tmp_path)
    changes = [owner_change(request, deliverables=[])]
    path, _ = chain(tmp_path, [HTML, SUMMARY], [HTML], second_changes=changes)
    with pytest.raises(ValueError, match="deliverables cannot disappear"):
        validate_review(path, now=NOW)
    altered = [{"id": "html", "kind": "pdf"}, SUMMARY]
    path, _ = chain(tmp_path, [HTML], altered, second_changes=changes)
    with pytest.raises(ValueError, match="deliverables cannot disappear"):
        validate_review(path, now=NOW)


@pytest.mark.parametrize(
    "override,message",
    [
        ({"kind": "other"}, "kind must be"),
        ({"kind": None}, "kind must be"),
        ({"id": ""}, "ID must be"),
        ({"id": 5}, "ID must be"),
        ({"request": "relative-request.txt"}, "hash-bound"),
        ({"request": "C:\\Unbound\\request.txt"}, "hash-bound"),
        ({"request": None}, "hash-bound"),
        ({"summary": " "}, "needs a summary"),
        ({"prior_logic_verified": False}, "previously applicable logic"),
        ({"prior_logic_verified": "true"}, "previously applicable logic"),
        ({"prior_logic_verified": 1}, "previously applicable logic"),
        ({"deliverables": "summary"}, "deliverables must be"),
        ({"deliverables": ["unknown"]}, "deliverables must be"),
        ({"deliverables": ["summary", "summary"]}, "deliverables must be"),
        ({"persisted_in": ["C:\\Unbound\\rules.md"]}, "persisted_in must be"),
        ({"persisted_in": "rules.md"}, "persisted_in must be"),
        ({"kind": "rule_update"}, "must record where it was persisted"),
        ({"kind": "rule_update", "persisted_in": []}, "must record where it was persisted"),
    ],
)
def test_malformed_owner_changes_fail_closed(tmp_path, override, message):
    request = owner_request(tmp_path)
    path, _ = chain(
        tmp_path,
        [HTML],
        [HTML, SUMMARY],
        second_changes=[owner_change(request, **override)],
    )
    with pytest.raises(ValueError, match=message):
        validate_review(path, now=NOW)


def test_malformed_owner_change_containers_fail_closed(tmp_path):
    request = owner_request(tmp_path)
    for bad, message in (
        ("change-1", "must be a list"),
        (["change-1"], "must be an object"),
        ([owner_change(request), owner_change(request)], "Duplicate owner change ID"),
    ):
        path, _ = chain(tmp_path, [HTML], [HTML, SUMMARY], second_changes=bad)
        with pytest.raises(ValueError, match=message):
            validate_review(path, now=NOW)


def test_rule_update_with_persisted_evidence_is_accepted(tmp_path):
    request = owner_request(tmp_path)
    changes = [
        owner_change(request, kind="rule_update", deliverables=[], persisted_in=[str(request)])
    ]
    path, _ = chain(tmp_path, [HTML], [HTML], second_changes=changes)
    assert validate_review(path, now=NOW)["owner_changes"] == changes


def test_rule_update_does_not_bypass_rule_hash_binding(tmp_path):
    request = owner_request(tmp_path)
    changes = [
        owner_change(request, kind="rule_update", deliverables=[], persisted_in=[str(request)])
    ]
    path, _ = chain(tmp_path, [HTML], [HTML], second_changes=changes)
    data = json.loads(path.read_text())
    data["rule_sha256"][next(iter(data["rule_sha256"]))] = "0" * 64
    save(path, data)
    with pytest.raises(ValueError, match="rules changed"):
        validate_review(path, now=NOW)


def test_owner_change_from_previous_phase_cannot_disappear_or_change(tmp_path):
    request = owner_request(tmp_path)
    change = owner_change(request)
    for later in (
        [],
        None,
        [owner_change(request, summary="Different summary.")],
        [owner_change(request, id="change-2")],
    ):
        path, _ = chain(
            tmp_path,
            [HTML, SUMMARY],
            [HTML, SUMMARY],
            first_changes=[change],
            second_changes=later,
        )
        with pytest.raises(ValueError, match="cannot disappear or change"):
            validate_review(path, now=NOW)


def test_owner_change_kept_across_phases_is_accepted(tmp_path):
    request = owner_request(tmp_path)
    change = owner_change(request)
    path, _ = chain(
        tmp_path, [HTML, SUMMARY], [HTML, SUMMARY], first_changes=[change], second_changes=[change]
    )
    assert validate_review(path, now=NOW)["owner_changes"] == [change]


def test_receipt_reports_owner_changes(tmp_path):
    request = owner_request(tmp_path)
    change = owner_change(request)
    path, _ = chain(tmp_path, [HTML], [HTML, SUMMARY], second_changes=[change])
    with patch("wizexpert.workflow_qa.datetime") as clock:
        clock.now.return_value = NOW
        clock.fromisoformat = datetime.fromisoformat
        result = receipt(path, "generation")
    assert result["owner_changes"] == [
        {
            "id": "change-1",
            "kind": "addition",
            "summary": change["summary"],
            "deliverables": ["summary"],
        }
    ]
    assert [r["id"] for r in result["requested_deliverables"]] == ["html", "summary"]


def test_missing_owner_changes_behaves_as_before(tmp_path, reviewed):
    path, _ = chain(tmp_path, [HTML], [HTML])
    assert "owner_changes" not in validate_review(path, now=NOW)
    with patch("wizexpert.workflow_qa.datetime") as clock:
        clock.now.return_value = NOW
        clock.fromisoformat = datetime.fromisoformat
        assert receipt(reviewed, "collection")["owner_changes"] == []


def test_requirements_cli_describes_owner_changes(capsys):
    assert (
        main(["workflow-qa", "requirements", "--workflow", "setup", "--phase", "collection"]) == 0
    )
    assert "owner_changes" in capsys.readouterr().out
