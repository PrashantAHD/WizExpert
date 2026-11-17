import json
import subprocess
import sys
from pathlib import Path

import pytest

from wizexpert.governance.collection_gate import partition_coverage_blockers, require_ready_receipt
from wizexpert.governance.dashboard_data import DashboardError
from wizexpert.governance.pagination import paginate

GUARD = Path.home() / ".copilot" / "hooks" / "wiz_readonly_guard.py"


def _page(nodes, total, cursor, more):
    return {
        "issues": {
            "nodes": nodes,
            "pageInfo": {"endCursor": cursor, "hasNextPage": more},
            "totalCount": total,
        }
    }


def test_repeated_issue_id_across_pages_fails_closed(tmp_path):
    pages = {
        None: _page([{"id": "a"}], 2, "c1", True),
        "c1": _page([{"id": "a"}], 2, None, False),
    }
    with pytest.raises(DashboardError, match="repeated an issue ID"):
        paginate(lambda p: pages[p.get("after")], {"s": 1}, tmp_path)


def test_completed_manifest_is_returned_without_refetch(tmp_path):
    paginate(lambda p: _page([{"id": "a"}], 1, None, False), {"s": 1}, tmp_path)

    def boom(params):
        raise AssertionError("must not refetch")

    assert paginate(boom, {"s": 1}, tmp_path)["complete"] is True


def test_non_true_pagination_complete_blocks():
    plan = {"partitions": [{"role": "active", "expected_count": 1, "query": {"a": 1}}]}
    for value in ("false", 0, None):
        manifest = {
            "counts": [
                {"role": "active", "expected": 1, "collected": 1, "pagination_complete": value}
            ]
        }
        blockers = partition_coverage_blockers(plan, manifest)
        assert any("Pagination incomplete" in b for b in blockers)


def test_missing_pagination_complete_and_unclaimed_count_block():
    plan = {"partitions": [{"role": "active", "expected_count": 3, "query": {"a": 1}}]}
    manifest = {
        "counts": [
            {"role": "active", "expected": 3, "collected": 2},
            {"role": "extra", "expected": 1, "collected": 1, "pagination_complete": True},
        ]
    }
    blockers = partition_coverage_blockers(plan, manifest)
    assert any("Pagination incomplete" in b for b in blockers)
    assert any("drift" in b and "collected 2" in b and "planned 3" in b for b in blockers)
    assert any("'extra'" in b and "not covered" in b for b in blockers)


@pytest.mark.parametrize(
    "page,message",
    [
        (_page([{"x": 1}], 1, None, False), "no issue ID"),
        (_page([], 1, "c1", True), "empty page"),
        (_page([{"id": "a"}], 1, "c1", "true"), "not a boolean"),
    ],
)
def test_malformed_pages_fail_closed(tmp_path, page, message):
    with pytest.raises(DashboardError, match=message):
        paginate(lambda p: page, {"s": 1}, tmp_path)


def test_terminal_saved_manifest_marked_incomplete_fails(tmp_path):
    paginate(lambda p: _page([{"id": "a"}], 1, None, False), {"s": 1}, tmp_path)
    path = tmp_path / "collection-manifest.json"
    data = json.loads(path.read_text())
    data["complete"] = False
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(DashboardError, match="terminal but incomplete"):
        paginate(lambda p: _page([{"id": "a"}], 1, None, False), {"s": 1}, tmp_path)


def test_receipt_without_audit_binding_raises_dashboard_error(tmp_path):
    receipt = tmp_path / "r.json"
    receipt.write_text(
        json.dumps(
            {
                "status": "ready",
                "generation_allowed": True,
                "cutoff": "2026-11-01T00:00:00Z",
                "mode": "delta_collection",
                "fresh_outputs": {},
            }
        )
    )
    from datetime import UTC, datetime

    with pytest.raises(DashboardError, match="audit binding"):
        require_ready_receipt(receipt, tmp_path / "x", datetime(2026, 11, 1, tzinfo=UTC))


def _run_guard(payload: str) -> dict:
    out = subprocess.run(
        [sys.executable, str(GUARD)], input=payload, capture_output=True, text=True, check=True
    ).stdout
    return json.loads(out)


@pytest.mark.skipif(not GUARD.is_file(), reason="user-level guard not installed")
@pytest.mark.parametrize(
    "payload",
    [
        json.dumps([{"toolName": "wiz-execute"}]),
        "[ wiz-execute",
    ],
)
def test_guard_denies_non_object_wiz_payloads(payload):
    assert _run_guard(payload)["permissionDecision"] == "deny"


@pytest.mark.skipif(not GUARD.is_file(), reason="user-level guard not installed")
def test_guard_keeps_read_allowed_and_mutation_denied():
    def call(op):
        args = {"tool_name": op, "parameters": {}}
        return json.dumps({"toolCalls": [{"name": "wiz-execute", "args": args}]})

    assert _run_guard(call("list_issues")) == {}
    assert _run_guard(call("update_issue"))["permissionDecision"] == "deny"
    assert _run_guard(json.dumps({"toolName": "other"})) == {}
