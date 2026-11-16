import csv
import json
from copy import deepcopy
from datetime import UTC, datetime

import pytest

from wizexpert.__main__ import main
from wizexpert.governance.dashboard_data import DashboardError
from wizexpert.governance.monthly_files import digest
from wizexpert.governance.reconcile import (
    COVERAGE,
    FIELDS,
    SEVERITIES,
    check_plan,
    read_rows,
    reconcile,
    reconcile_rows,
    require_current_delta,
    verify_reconciliation,
)


def row(issue_id, status="RESOLVED", closed="2026-09-10", severity="HIGH"):
    return dict(
        zip(
            FIELDS,
            ["2026-01-01", issue_id, closed, severity, status, "Synthetic issue", ""],
            strict=True,
        )
    )


def counts():
    return {s: {"OPEN": 0, "IN_PROGRESS": 0} for s in SEVERITIES}


def write_csv(path, rows):
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return path


@pytest.fixture
def collected(tmp_path):
    previous = write_csv(
        tmp_path / "previous.csv",
        [
            row("reopened"),
            row("retained"),
            row("closed-now", "OPEN", ""),
        ],
    )
    active = write_csv(tmp_path / "active.csv", [row("reopened", "IN_PROGRESS", "")])
    fresh = write_csv(tmp_path / "changes.csv", [row("closed-now", closed="2026-10-20")])
    expected = counts()
    expected["HIGH"]["IN_PROGRESS"] = 1
    evidence = tmp_path / "coverage.json"
    evidence.write_text('{"synthetic": true}', encoding="utf-8")
    plan = {
        "schema_version": 1,
        "strategy": "reuse_history",
        "previous_collected_at": "2026-10-15T19:00:00Z",
        "changes_since": "2026-10-15T18:59:00Z",
        "collected_through": "2026-10-27T06:00:00Z",
        "approved_sources": {str(previous): digest(previous)},
        "partitions": [
            {
                "role": "active",
                "expected_count": 41,
                "page_size": 500,
                "query": {"status": ["OPEN", "IN_PROGRESS"]},
            }
        ],
        "coverage": {
            k: {"complete": True, "basis": "Synthetic reviewed evidence", "evidence": str(evidence)}
            for k in COVERAGE
        },
        "active_pagination_complete": True,
        "active_counts": expected,
        "unresolved_gaps": [],
    }
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    return (
        plan_path,
        [previous],
        [fresh],
        [active],
        tmp_path / "reviewed.csv",
        tmp_path / "audit.json",
    )


def test_reopening_overrides_history_once_and_retains_original_creation(collected):
    before = digest(collected[1][0])
    result = reconcile(*collected)
    merged = read_rows([collected[4]])
    assert len(merged) == 3
    assert merged["reopened"]["Status"] == "IN_PROGRESS"
    assert merged["reopened"]["Created At"] == "2026-01-01"
    assert merged["reopened"]["Resolved Time"] == ""
    assert result["retained_ids"] == ["retained"]
    assert next(c for c in result["changes"] if c["issue_id"] == "reopened")["kind"] == "reopened"
    assert result["share_ready"] is False
    assert digest(collected[1][0]) == before
    verify_reconciliation(collected[5], [collected[4]], datetime(2026, 10, 27, 6, tzinfo=UTC))
    with pytest.raises(DashboardError, match="cutoffs differ"):
        verify_reconciliation(collected[5], [collected[4]], datetime(2026, 10, 28, tzinfo=UTC))


@pytest.mark.parametrize(
    "change,message",
    [
        ("missing", "disappeared"),
        ("counts", "does not reconcile"),
        ("conflict", "Active/delta conflict"),
    ],
)
def test_incomplete_or_conflicting_current_state_fails_closed(change, message):
    previous = {"old": row("old", "OPEN", "")}
    active = {"old": row("old", "OPEN", "")}
    fresh = {}
    expected = counts()
    expected["HIGH"]["OPEN"] = 1
    if change == "missing":
        active = {}
        expected["HIGH"]["OPEN"] = 0
    elif change == "counts":
        expected["HIGH"]["OPEN"] = 2
    else:
        fresh["old"] = row("old")
    with pytest.raises(DashboardError, match=message):
        reconcile_rows(previous, fresh, active, expected)


def test_reclosed_and_reclassified_are_not_invented_new_issues():
    previous = {"old": row("old")}
    fresh = {"old": row("old", closed="2026-10-20", severity="MEDIUM")}
    merged, audit = reconcile_rows(previous, fresh, {}, counts())
    assert len(merged) == 1
    assert audit["changes"][0]["kind"] == "closed_record_changed"
    assert {"Severity", "Resolved Time"} <= set(audit["changes"][0]["fields"])


@pytest.mark.parametrize(
    "change,message",
    [
        ("full", "report-owner agreement"),
        ("disguised", "cannot be labelled"),
        ("watermark", "actual collection"),
        ("source", "missing or changed"),
        ("coverage", "Coverage is not established"),
        ("pagination", "pagination"),
        ("gap", "gaps remain"),
    ],
)
def test_preflight_and_coverage_gates(collected, change, message):
    path = collected[0]
    plan = json.loads(path.read_text())
    assert check_plan(path)["estimated_page_requests"] == 1
    if change == "full":
        plan["strategy"] = "full_refresh"
    elif change == "disguised":
        plan["partitions"][0]["role"] = "full_history"
    elif change == "watermark":
        plan["changes_since"] = "2026-10-15T23:59:59Z"
    elif change == "source":
        plan["approved_sources"][str(collected[1][0])] = "0" * 64
    elif change == "coverage":
        del plan["coverage"]["historical_closed_changes"]
    elif change == "pagination":
        plan["active_pagination_complete"] = False
    else:
        plan["unresolved_gaps"] = ["Closed severity changes not checked"]
    path.write_text(json.dumps(plan), encoding="utf-8")
    with pytest.raises(DashboardError, match=message):
        reconcile(*collected)
    assert not collected[4].exists()
    assert not collected[5].exists()


def test_identical_overlap_is_deduplicated_but_conflicts_fail(tmp_path):
    original = row("same")
    path = write_csv(tmp_path / "overlap.csv", [original, original])
    assert len(read_rows([path])) == 1
    changed = deepcopy(original)
    changed["Severity"] = "LOW"
    write_csv(path, [original, changed])
    with pytest.raises(DashboardError, match="Conflicting duplicate"):
        read_rows([path])


def test_audit_binds_inputs_and_does_not_overwrite(collected):
    reconcile(*collected)
    with pytest.raises(DashboardError, match="must be new"):
        reconcile(*collected)
    collected[4].write_text("changed", encoding="utf-8")
    with pytest.raises(DashboardError, match="changed after QA"):
        verify_reconciliation(collected[5], [collected[4]], datetime(2026, 10, 27, 6, tzinfo=UTC))


def test_cli_plan_only_is_not_collection_success(collected, capsys):
    assert main(["governance", "reconcile", "--plan", str(collected[0]), "--plan-only"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["estimated_page_requests"] == 1
    assert result["collection_complete"] is False
    assert not collected[4].exists()


WATERMARK = "2026-10-28T05:55:49Z"
CUTOFF = "2026-11-15T23:59:59Z"


def retained(tmp_path):
    evidence = tmp_path / "retained"
    evidence.mkdir()
    (evidence / "collection-plan.json").write_text(
        json.dumps({"collected_through": WATERMARK}), encoding="utf-8"
    )
    return evidence


def test_stale_retained_watermark_drafts_delta_plan_and_fails_closed(tmp_path):
    evidence = retained(tmp_path)
    before = (evidence / "collection-plan.json").read_bytes()
    plan = tmp_path / "delta.json"
    with pytest.raises(DashboardError, match="before cutoff"):
        require_current_delta(evidence, CUTOFF, plan)
    draft = json.loads(plan.read_text(encoding="utf-8"))
    assert draft["changes_since"] == draft["previous_collected_at"] == WATERMARK
    assert draft["collected_through"] == CUTOFF
    assert (evidence / "collection-plan.json").read_bytes() == before
    with pytest.raises(DashboardError, match="not approved"):
        require_current_delta(evidence, CUTOFF, plan)


def test_draft_cannot_be_written_inside_retained_evidence(tmp_path):
    evidence = retained(tmp_path)
    with pytest.raises(DashboardError, match="outside the retained evidence"):
        require_current_delta(evidence, CUTOFF, evidence / "delta.json")
    assert [p.name for p in evidence.iterdir()] == ["collection-plan.json"]


def test_current_watermark_needs_no_delta(tmp_path):
    evidence = retained(tmp_path)
    result = require_current_delta(evidence, WATERMARK, tmp_path / "unused.json")
    assert result["status"] == "retained_evidence_current"
    assert not (tmp_path / "unused.json").exists()


def approved_delta(tmp_path, **changes):
    source = tmp_path / "prior.csv"
    source.write_text("x", encoding="utf-8")
    plan = {
        "schema_version": 1,
        "strategy": "reuse_history",
        "previous_collected_at": WATERMARK,
        "changes_since": WATERMARK,
        "collected_through": CUTOFF,
        "retained_watermark": WATERMARK,
        "approved_by": "owner",
        "approved_at": "2026-11-16T00:00:00Z",
        "approved_sources": {str(source): digest(source)},
        "partitions": [
            {
                "role": "changes",
                "expected_count": 5,
                "page_size": 500,
                "query": {"since": WATERMARK},
            }
        ],
    }
    plan.update(changes)
    path = tmp_path / "delta.json"
    path.write_text(json.dumps(plan), encoding="utf-8")
    return path


def test_check_plan_rejects_page_size_20(tmp_path):
    from wizexpert.governance.reconcile import check_plan

    bad = [{"role": "changes", "expected_count": 5, "page_size": 20, "query": {"s": 1}}]
    path = approved_delta(tmp_path, partitions=bad)
    with pytest.raises(Exception, match="MG-COL-02"):
        check_plan(path)
    good = approved_delta(tmp_path)
    assert check_plan(good)["estimated_page_requests"] == 1


def test_approved_delta_plan_is_accepted_but_not_fresh_evidence(tmp_path):
    evidence = retained(tmp_path)
    result = require_current_delta(evidence, CUTOFF, approved_delta(tmp_path))
    assert result["collected_through"] == CUTOFF
    assert result["evidence_is_fresh"] is False


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"collected_through": "2026-11-10T00:00:00Z"}, "requested cutoff"),
        ({"changes_since": "2026-10-29T00:00:00Z"}, "retained watermark"),
        ({"retained_watermark": "2026-10-01T00:00:00Z"}, "retained watermark"),
        ({"approved_by": ""}, "not approved"),
        ({"partitions": []}, "partitions"),
        ({"approved_sources": {}}, "Approved source"),
    ],
)
def test_incomplete_or_mismatched_delta_plan_fails(tmp_path, changes, message):
    evidence = retained(tmp_path)
    with pytest.raises(DashboardError, match=message):
        require_current_delta(evidence, CUTOFF, approved_delta(tmp_path, **changes))
