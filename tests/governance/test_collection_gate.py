import json

import pytest

from wizexpert.governance.collection_gate import (
    check_step,
    partition_id,
    plan_step,
    require_ready_receipt,
)
from wizexpert.governance.dashboard_data import DashboardError
from wizexpert.governance.monthly_files import digest
from wizexpert.governance.reconcile import utc

WATERMARK = "2026-10-28T05:55:49Z"
CUTOFF = "2026-11-15T23:59:59Z"


def setup(tmp_path):
    evidence = tmp_path / "retained"
    evidence.mkdir()
    (evidence / "collection-plan.json").write_text(
        json.dumps({"collected_through": WATERMARK}), encoding="utf-8"
    )
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
            {"role": "changes", "expected_count": 5, "page_size": 500, "query": {"s": 1}}
        ],
    }
    plan_path = tmp_path / "delta.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    return evidence, plan_path, source, tmp_path / "receipt.json"


def fresh_outputs(tmp_path, plan_path, source, collected=5):
    log = tmp_path / "activity.jsonl"
    log.write_text(
        json.dumps(
            {
                "type": "tool.execution_start",
                "timestamp": "2026-11-16T01:30:00Z",
                "data": {"toolName": "wiz-execute"},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "started_at": "2026-11-16T01:00:00Z",
                "ended_at": "2026-11-16T02:00:00Z",
                "reused_sources": [str(source)],
                "counts": [
                    {
                        "name": "changes",
                        "expected": 5,
                        "collected": collected,
                        "pagination_complete": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "changes.json").write_text("[]", encoding="utf-8")
    reconciled = tmp_path / "reviewed.csv"
    reconciled.write_text("Issue ID\n", encoding="utf-8")
    audit = tmp_path / "audit.json"
    audit.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "status": "reconciled",
                "output": str(reconciled),
                "output_sha256": digest(reconciled),
                "collected_through": CUTOFF,
                "collection_plan": str(plan_path),
                "source_sha256": {},
            }
        ),
        encoding="utf-8",
    )
    return log, manifest, raw, audit


def test_stale_watermark_blocks_until_fresh_collection_checks_pass(tmp_path):
    evidence, plan, source, receipt = setup(tmp_path)
    before = (evidence / "collection-plan.json").read_bytes()
    result = plan_step(evidence, CUTOFF, plan, receipt)
    assert result["status"] == "blocked"
    outputs = fresh_outputs(tmp_path, plan, source)
    done = check_step(evidence, CUTOFF, plan, receipt, *outputs)
    assert done["status"] == "ready", done["blockers"]
    assert (evidence / "collection-plan.json").read_bytes() == before
    assert require_ready_receipt(receipt, outputs[3], utc(CUTOFF))["mode"] == "delta_collection"


def test_missing_plan_drafts_and_blocks(tmp_path):
    evidence, plan, _, receipt = setup(tmp_path)
    plan.unlink()
    result = plan_step(evidence, CUTOFF, plan, receipt)
    assert result["status"] == "blocked"
    assert "before cutoff" in result["blockers"][0]
    assert json.loads(plan.read_text())["changes_since"] == WATERMARK


def test_check_without_fresh_outputs_is_blocked(tmp_path):
    evidence, plan, _, receipt = setup(tmp_path)
    plan_step(evidence, CUTOFF, plan, receipt)
    result = check_step(evidence, CUTOFF, plan, receipt, None, None, None, None)
    assert result["status"] == "blocked"
    assert any("Missing fresh" in blocker for blocker in result["blockers"])
    with pytest.raises(DashboardError, match="blocked"):
        require_ready_receipt(receipt, None, utc(CUTOFF))


def test_count_mismatch_blocks(tmp_path):
    evidence, plan, source, receipt = setup(tmp_path)
    plan_step(evidence, CUTOFF, plan, receipt)
    outputs = fresh_outputs(tmp_path, plan, source, collected=4)
    result = check_step(evidence, CUTOFF, plan, receipt, *outputs)
    assert result["status"] == "blocked"


def test_retained_evidence_tamper_blocks(tmp_path):
    evidence, plan, source, receipt = setup(tmp_path)
    plan_step(evidence, CUTOFF, plan, receipt)
    (evidence / "collection-plan.json").write_text(
        json.dumps({"collected_through": CUTOFF}), encoding="utf-8"
    )
    outputs = fresh_outputs(tmp_path, plan, source)
    result = check_step(evidence, CUTOFF, plan, receipt, *outputs)
    assert result["status"] == "blocked"


def test_current_retained_watermark_is_ready_without_collection(tmp_path):
    evidence, plan, _, receipt = setup(tmp_path)
    assert plan_step(evidence, WATERMARK, plan, receipt)["status"] == "ready"


def _runs(tmp_path, **over):
    run = {
        "id": "20261116T023721Z-1b65ff",
        "category_id": "monthly-governance-reporting",
        "values": {"month": "2026-11"},
        "parent": "",
        "gates": [{"id": "collection-plan", "state": "approved"}],
        "decisions": [{"gate": "collection-plan", "decision": "approve", "at": 1794796644.0}],
    }
    run.update(over)
    path = tmp_path / "runs.json"
    path.write_text(json.dumps([run]), encoding="utf-8")
    return path


def _unapprove(plan, **drop):
    data = json.loads(plan.read_text())
    data["approved_by"] = data["approved_at"] = ""
    data.update(drop)
    plan.write_text(json.dumps(data), encoding="utf-8")


def test_console_approval_binds_into_drafted_plan(tmp_path):
    evidence, plan, source, receipt = setup(tmp_path)
    _unapprove(plan)
    runs = _runs(tmp_path)
    plan_step(evidence, CUTOFF, plan, receipt, runs)
    bound = json.loads(plan.read_text())
    assert bound["approved_at"] == "2026-11-16T02:37:24Z"
    assert "20261116T023721Z-1b65ff" in bound["approved_by"]
    assert bound["approved_sources"] == {str(source): digest(source)}
    outputs = fresh_outputs(tmp_path, plan, source)
    assert check_step(evidence, CUTOFF, plan, receipt, *outputs, runs)["status"] == "ready"


@pytest.mark.parametrize(
    "over",
    [
        {"category_id": "risk-issues"},
        {"values": {"month": "2026-10"}},
        {"gates": [{"id": "collection-plan", "state": "pending"}]},
        {
            "decisions": [
                {"gate": "collection-plan", "decision": "approve", "at": 1.0, "auto": True}
            ]
        },
    ],
)
def test_non_matching_console_approval_stays_blocked(tmp_path, over):
    evidence, plan, _, receipt = setup(tmp_path)
    _unapprove(plan)
    result = plan_step(evidence, CUTOFF, plan, receipt, _runs(tmp_path, **over))
    assert result["status"] == "blocked"
    assert json.loads(plan.read_text())["approved_by"] == ""


def test_console_approval_never_invents_partitions(tmp_path):
    evidence, plan, _, receipt = setup(tmp_path)
    _unapprove(plan, partitions=[], approved_sources={})
    result = plan_step(evidence, CUTOFF, plan, receipt, _runs(tmp_path))
    assert result["status"] == "blocked"
    assert json.loads(plan.read_text())["approved_by"] == ""


def test_stale_console_approval_stays_blocked(tmp_path):
    evidence, plan, _, receipt = setup(tmp_path)
    _unapprove(plan)
    runs = _runs(tmp_path)
    data = json.loads(runs.read_text())
    data[0]["decisions"][0]["at"] = 1793166949.0
    runs.write_text(json.dumps(data))
    result = plan_step(evidence, CUTOFF, plan, receipt, runs)
    assert result["status"] == "blocked"
    assert json.loads(plan.read_text())["approved_by"] == ""


def _dup_plan(plan_path):
    data = json.loads(plan_path.read_text())
    data["partitions"] = [
        {"role": "active", "expected_count": 1, "page_size": 500, "query": {"sev": "CRITICAL"}},
        {"role": "active", "expected_count": 12, "page_size": 500, "query": {"sev": "HIGH"}},
    ]
    plan_path.write_text(json.dumps(data), encoding="utf-8")
    return data["partitions"]


def _set_counts(manifest, counts):
    data = json.loads(manifest.read_text())
    data["counts"] = counts
    manifest.write_text(json.dumps(data), encoding="utf-8")


def _dup_run(tmp_path, counts_for):
    evidence, plan, source, receipt = setup(tmp_path)
    parts = _dup_plan(plan)
    plan_step(evidence, CUTOFF, plan, receipt)
    outputs = fresh_outputs(tmp_path, plan, source)
    _set_counts(outputs[1], counts_for(parts))
    return check_step(evidence, CUTOFF, plan, receipt, *outputs)


def _entry(part, **over):
    item = {
        "name": "active-" + part["query"]["sev"].lower(),
        "role": "active",
        "query_sha256": partition_id(part),
        "expected": part["expected_count"],
        "collected": part["expected_count"],
        "pagination_complete": True,
    }
    item.update(over)
    return item


def test_duplicate_roles_match_by_query_identity(tmp_path):
    result = _dup_run(tmp_path, lambda parts: [_entry(p) for p in parts])
    assert result["status"] == "ready", result["blockers"]


def test_duplicate_roles_without_query_identity_are_ambiguous(tmp_path):
    result = _dup_run(
        tmp_path,
        lambda parts: [
            {"name": "active", "expected": p["expected_count"], "collected": p["expected_count"]}
            for p in parts
        ],
    )
    assert result["status"] == "blocked"
    assert any("uniquely cover" in b for b in result["blockers"])


def test_duplicate_role_entry_cannot_cover_two_partitions(tmp_path):
    result = _dup_run(tmp_path, lambda parts: [_entry(parts[0]), _entry(parts[0])])
    assert result["status"] == "blocked"


def test_duplicate_roles_incomplete_pagination_and_count_mismatch_block(tmp_path):
    result = _dup_run(
        tmp_path,
        lambda parts: [_entry(parts[0], pagination_complete=False), _entry(parts[1], collected=2)],
    )
    assert result["status"] == "blocked"
    assert any("Pagination incomplete" in b for b in result["blockers"])
    assert any("Collected count" in b for b in result["blockers"])


def test_audit_without_output_binding_blocks(tmp_path):
    evidence, plan, source, receipt = setup(tmp_path)
    plan_step(evidence, CUTOFF, plan, receipt)
    outputs = fresh_outputs(tmp_path, plan, source)
    audit = json.loads(outputs[3].read_text())
    del audit["output"]
    outputs[3].write_text(json.dumps(audit), encoding="utf-8")
    result = check_step(evidence, CUTOFF, plan, receipt, *outputs)
    assert result["status"] == "blocked"
    assert any("output binding" in b for b in result["blockers"])


def test_audit_with_missing_output_file_blocks(tmp_path):
    evidence, plan, source, receipt = setup(tmp_path)
    plan_step(evidence, CUTOFF, plan, receipt)
    outputs = fresh_outputs(tmp_path, plan, source)
    audit = json.loads(outputs[3].read_text())
    audit["output"] = str(tmp_path / "missing.csv")
    outputs[3].write_text(json.dumps(audit), encoding="utf-8")
    result = check_step(evidence, CUTOFF, plan, receipt, *outputs)
    assert result["status"] == "blocked"


def _ready(tmp_path):
    evidence, plan, source, receipt = setup(tmp_path)
    plan_step(evidence, CUTOFF, plan, receipt)
    outputs = fresh_outputs(tmp_path, plan, source)
    assert check_step(evidence, CUTOFF, plan, receipt, *outputs)["status"] == "ready"
    return evidence, plan, receipt, outputs


def test_receipt_rejects_changed_plan(tmp_path):
    _, plan, receipt, outputs = _ready(tmp_path)
    plan.write_text(plan.read_text() + " ", encoding="utf-8")
    with pytest.raises(DashboardError, match="plan changed"):
        require_ready_receipt(receipt, outputs[3], utc(CUTOFF))


def test_receipt_rejects_changed_retained_evidence(tmp_path):
    evidence, _, receipt, outputs = _ready(tmp_path)
    (evidence / "late.json").write_text("{}", encoding="utf-8")
    with pytest.raises(DashboardError, match="Retained evidence changed"):
        require_ready_receipt(receipt, outputs[3], utc(CUTOFF))


def test_receipt_requires_reconciled_output_binding(tmp_path):
    _, _, receipt, outputs = _ready(tmp_path)
    data = json.loads(receipt.read_text())
    del data["fresh_outputs"]["reconciled_output"]
    receipt.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(DashboardError, match="reconciled output binding"):
        require_ready_receipt(receipt, outputs[3], utc(CUTOFF))


def test_receipt_rejects_audit_not_bound_to_reconciled_output(tmp_path):
    _, _, receipt, outputs = _ready(tmp_path)
    data = json.loads(receipt.read_text())
    data["fresh_outputs"]["reconciled_output"]["sha256"] = "0" * 64
    receipt.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(DashboardError, match="changed after the gate"):
        require_ready_receipt(receipt, outputs[3], utc(CUTOFF))


def test_missing_pagination_complete_blocks_gate(tmp_path):
    evidence, plan, source, receipt = setup(tmp_path)
    plan_step(evidence, CUTOFF, plan, receipt)
    outputs = fresh_outputs(tmp_path, plan, source)
    _set_counts(outputs[1], [{"name": "changes", "expected": 5, "collected": 5}])
    result = check_step(evidence, CUTOFF, plan, receipt, *outputs)
    assert result["status"] == "blocked"
    assert any("Pagination incomplete" in b for b in result["blockers"])
