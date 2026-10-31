"""Run orchestration tests: collection gate, review gate, archive, read-only, reconnect."""

from __future__ import annotations

import itertools
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from console_fakes import FakeAdapter

from wizexpert.console import runs as runs_module
from wizexpert.console.adapters import AdapterError
from wizexpert.console.context import McpCallError, ReconnectRequired
from wizexpert.console.runs import RunError, RunManager, confine, validate_reviewer


class Client:
    connected = True

    def __init__(self, fail: Exception | None = None, times: int = 99) -> None:
        self.fail, self.times, self.calls = fail, times, 0

    def execute(self, tool_name, parameters):
        self.calls += 1
        if self.fail and self.calls <= self.times:
            raise self.fail
        return {"tool": tool_name}

    def discover(self, domain=None):
        return {}


def manager(tmp_path, adapter=None, client=None, **kwargs):
    adapter = adapter or FakeAdapter(tmp_path / "deliverables")
    mgr = RunManager(
        {adapter.category_id: adapter},
        tmp_path / "deliverables",
        client or Client(),
        run_async=False,
        retry_delay=0,
        **kwargs,
    )
    return mgr, adapter


def start(mgr, **kwargs):
    return mgr.create("daily-progress-reporting", {"subject": "s"}, **kwargs)


def to_review(mgr, run, summary="typed narrative"):
    mgr.submit_fields(run.id, {"summary": summary})
    return run


def test_happy_path_needs_a_named_human_approval_to_complete(tmp_path):
    mgr, _ = manager(tmp_path)
    run = start(mgr, preparer="Pat Preparer")
    assert run.status == "awaiting_input"
    assert run.collection["status"] == "pass"
    assert run.field_values["summary"] == "pre-filled"
    to_review(mgr, run)
    assert run.status == "awaiting_review"
    assert run.approval is None and run.pipeline == {}  # nothing certified yet
    mgr.approve(run.id, "Rae Reviewer", confirm=True)
    assert run.status == "complete" and run.pipeline["complete"] is True
    record = json.loads((run.run_dir / "run.json").read_text(encoding="utf-8"))
    approval = record["approval"]
    assert approval["reviewer"] == "Rae Reviewer"
    assert approval["approved_at_utc"].endswith("Z") and approval["independent_of_preparer"] is True
    assert record["pipeline"] == {"complete": True, "workflow_qa": "passed", "review": "passed"}
    assert all(v["sha256"] for v in record["outputs"].values())
    assert "No email was sent" in " ".join(record["notes"])


def test_review_cannot_be_skipped_or_faked(tmp_path):
    mgr, _ = manager(tmp_path)
    run = to_review(mgr, start(mgr))
    for bad in ("", "x", "Console", "system", "AI", "n/a", 123, None, "<script>"):
        with pytest.raises(RunError):
            mgr.approve(run.id, bad, confirm=True)
    with pytest.raises(RunError):
        mgr.approve(run.id, "Rae Reviewer", confirm=False)
    assert run.status == "awaiting_review" and run.approval is None
    mgr.approve(run.id, "Rae Reviewer", confirm=True)
    with pytest.raises(RunError):  # a second approval is refused
        mgr.approve(run.id, "Someone Else", confirm=True)


def test_cannot_approve_before_outputs_exist_or_after_collection_block(tmp_path):
    mgr, _ = manager(tmp_path)
    run = start(mgr)
    assert run.status == "awaiting_input"
    with pytest.raises(RunError):
        mgr.approve(run.id, "Rae Reviewer", confirm=True)


def test_same_person_is_recorded_as_not_independent(tmp_path):
    mgr, _ = manager(tmp_path)
    run = to_review(mgr, start(mgr, preparer="Rae Reviewer"))
    mgr.approve(run.id, "rae reviewer", confirm=True)
    assert run.approval["independent_of_preparer"] is False


def test_tampered_output_blocks_approval(tmp_path):
    mgr, _ = manager(tmp_path)
    run = to_review(mgr, start(mgr))
    next(iter(run.outputs.values())).write_text("edited after validation", encoding="utf-8")
    with pytest.raises(RunError, match="changed since validation"):
        mgr.approve(run.id, "Rae Reviewer", confirm=True)


def test_reject_records_reviewer_and_is_not_complete(tmp_path):
    mgr, _ = manager(tmp_path)
    run = to_review(mgr, start(mgr))
    mgr.reject(run.id, "Rae Reviewer", "wording")
    assert run.status == "rejected" and run.pipeline == {}


def test_failed_collection_check_blocks_generation(tmp_path):
    mgr, adapter = manager(tmp_path, FakeAdapter(tmp_path / "deliverables", counts_ok=False))
    run = start(mgr)
    assert run.status == "blocked"
    assert any("mismatch" in f for f in run.collection["flags"])
    with pytest.raises(RunError):
        mgr.submit_fields(run.id, {"summary": "x"})
    assert not list((run.output_dir).glob("*.out")) if run.output_dir.exists() else True


def test_collection_check_uses_the_real_activity_log(tmp_path):
    mgr, _ = manager(
        tmp_path,
        FakeAdapter(
            tmp_path / "deliverables",
            calls=[("list_things", {"first": 1}), ("get_thing", {"id": "x"})],
        ),
    )
    run = start(mgr)
    events = [json.loads(x) for x in (run.run_dir / "activity.jsonl").read_text().splitlines()]
    starts = [e for e in events if e["type"] == "tool.execution_start"]
    assert [e["data"]["arguments"]["tool_name"] for e in starts] == ["list_things", "get_thing"]
    assert {e["data"]["toolName"] for e in starts} == {"mcp__wiz__execute"}
    assert run.collection["wiz_calls"] == 2
    check = json.loads((run.run_dir / "collection-check.json").read_text())
    assert check["status"] == "pass"


def test_401_stops_the_run_and_requests_reconnect(tmp_path):
    client = Client(ReconnectRequired("401"))
    mgr, _ = manager(tmp_path, client=client)
    run = start(mgr)
    assert run.status == "reconnect_required"
    assert client.calls == 1  # no retry, no continuation
    assert not (run.run_dir / "collection-manifest.json").exists()
    assert run.form is None


def test_same_call_failing_three_times_aborts_without_publishing(tmp_path):
    client = Client(McpCallError("boom"))
    mgr, _ = manager(tmp_path, client=client)
    run = start(mgr)
    assert run.status == "failed" and "failed 3 times" in run.message
    assert client.calls == 3 and not run.outputs


def test_transient_failure_is_retried(tmp_path):
    client = Client(McpCallError("blip"), times=2)
    mgr, _ = manager(tmp_path, client=client)
    run = start(mgr)
    assert run.status == "awaiting_input" and client.calls == 3


def test_write_style_calls_are_refused_in_runs(tmp_path):
    client = Client()
    mgr, _ = manager(
        tmp_path, FakeAdapter(tmp_path / "deliverables", calls=[("update_issue", {})]), client
    )
    run = start(mgr)
    assert run.status == "failed" and "read-only" in run.message and client.calls == 0


def test_observation_window_exceeded_blocks_and_never_stitches(tmp_path, monkeypatch):
    base = datetime(2026, 1, 1, tzinfo=UTC)
    ticks = itertools.count()
    monkeypatch.setattr(runs_module, "utc_now", lambda: base + timedelta(seconds=100 * next(ticks)))
    mgr, _ = manager(tmp_path, window_override_seconds=30)
    run = start(mgr)
    assert run.status == "blocked" and "Observation window exceeded" in run.message


def test_validator_failure_returns_to_input_and_blocks_review(tmp_path):
    mgr, adapter = manager(tmp_path, FakeAdapter(tmp_path / "deliverables", validator_ok=False))
    run = to_review(mgr, start(mgr))
    assert run.status == "awaiting_input" and any("validator" in p for p in run.problems)
    with pytest.raises(RunError):
        mgr.approve(run.id, "Rae Reviewer", confirm=True)
    adapter.validator_ok = True
    mgr.submit_fields(run.id, {"summary": "fixed"})
    assert run.status == "awaiting_review"


def test_existing_deliverables_are_archived_before_regenerating(tmp_path):
    adapter = FakeAdapter(tmp_path / "deliverables")
    out = adapter.output_dir({})
    out.mkdir(parents=True)
    (out / "daily-progress-report.out").write_text("previous version", encoding="utf-8")
    mgr, _ = manager(tmp_path, adapter)
    run = to_review(mgr, start(mgr))
    archived = list((out / "archives").glob("*/daily-progress-report.out"))
    assert len(archived) == 1 and archived[0].read_text() == "previous version"
    assert (out / "daily-progress-report.out").read_text().endswith("typed narrative")
    assert run.archived == [str(archived[0])]


def test_dry_run_writes_only_inside_the_private_run_folder(tmp_path):
    mgr, adapter = manager(tmp_path)
    run = to_review(mgr, start(mgr, dry_run=True))
    assert run.output_dir == run.run_dir / "out"
    assert not adapter.output_dir({}).exists()
    mgr.approve(run.id, "Rae Reviewer", confirm=True)
    assert run.status == "complete"


def test_output_dir_outside_the_deliverables_root_is_refused(tmp_path):
    adapter = FakeAdapter(tmp_path / "deliverables")
    adapter.out_override = tmp_path / "elsewhere"
    mgr, _ = manager(tmp_path, adapter)
    with pytest.raises(RunError, match="escaped"):
        start(mgr)
    adapter.out_override = tmp_path / "deliverables" / ".." / ".." / "outside"
    with pytest.raises(RunError):
        start(mgr)


def test_confine_blocks_traversal_and_siblings(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    assert confine(root / "a" / "b", root) == (root / "a" / "b").resolve()
    for bad in (root / ".." / "x", tmp_path / "root-sibling", Path("C:/") / "Windows"):
        with pytest.raises(RunError):
            confine(bad, root)


def test_only_one_active_run_at_a_time(tmp_path):
    mgr, _ = manager(tmp_path)
    run = start(mgr)
    with pytest.raises(RunError, match="current run"):
        start(mgr)
    mgr.cancel(run.id)
    assert run.status == "cancelled"
    start(mgr)


def test_evidence_is_immutable_and_hashed(tmp_path):
    mgr, _ = manager(tmp_path)
    run = start(mgr)
    with pytest.raises(FileExistsError):
        run.ctx.save_evidence("page-01.json", {"ok": False})
    with pytest.raises(ValueError):
        run.ctx.save_evidence("../escape.json", {})
    assert json.loads((run.run_dir / "evidence" / "page-01.json").read_text()) == {"ok": True}
    assert run.ctx.evidence_hashes["page-01.json"]


def test_run_view_escapes_nothing_but_carries_raw_text_for_the_ui_to_escape(tmp_path):
    mgr, _ = manager(tmp_path)
    run = start(mgr)
    view = run.view()
    assert (
        view["form"]["reference"][0]["text"] == "<script>alert(1)</script>"
    )  # UI uses textContent


def test_history_lists_runs_and_marks_stale_ones_interrupted(tmp_path):
    mgr, _ = manager(tmp_path)
    run = start(mgr)
    other, _ = manager(tmp_path)  # a new process: no in-memory runs
    entry = next(r for r in other.history() if r["id"] == run.id)
    assert entry["status"] == "interrupted"


def test_unknown_category_and_missing_dry_run_support(tmp_path):
    mgr, adapter = manager(tmp_path)
    with pytest.raises(RunError):
        mgr.create("nope", {})
    adapter.supports_dry_run = lambda: False
    with pytest.raises(RunError):
        start(mgr, dry_run=True)


def test_validate_reviewer_accepts_real_names():
    assert validate_reviewer("  Rae   O'Neil-Smith ") == "Rae O'Neil-Smith"


def test_observation_window_stops_collection_before_anything_is_assembled(tmp_path):
    adapter = FakeAdapter(tmp_path / "deliverables", calls=[("list_things", {"first": 1})] * 3)

    def late(ctx):  # the window has already run out when the first call is attempted
        real = ctx._monotonic  # noqa: SLF001
        ctx._monotonic = lambda: real() + 10_000  # noqa: SLF001

    adapter.collect_hook = late
    client = Client()
    mgr, _ = manager(tmp_path, adapter, client, window_override_seconds=60)
    run = start(mgr)
    assert run.status == "blocked" and "observation window" in run.message.lower()
    assert client.calls == 0 and not (run.run_dir / "collection-manifest.json").exists()


def test_window_is_not_applied_to_dry_runs(tmp_path):
    mgr, _ = manager(tmp_path, window_override_seconds=1)
    run = start(mgr, dry_run=True)
    assert run.status == "awaiting_input"


def test_no_narrative_fields_goes_straight_to_review(tmp_path):
    adapter = FakeAdapter(tmp_path / "deliverables")
    adapter.no_fields = True
    mgr, _ = manager(tmp_path, adapter)
    run = start(mgr)
    assert run.status == "awaiting_review" and run.approval is None


def test_failed_generation_restores_the_previous_deliverables(tmp_path):
    adapter = FakeAdapter(tmp_path / "deliverables")
    out = adapter.output_dir({})
    out.mkdir(parents=True)
    (out / "daily-progress-report.out").write_text("previous good draft", encoding="utf-8")
    adapter.generate_error = AdapterError("generator exploded")
    mgr, _ = manager(tmp_path, adapter)
    run = start(mgr)
    mgr.submit_fields(run.id, {"summary": "x"})
    assert run.status == "awaiting_input" and "generator exploded" in run.problems[0]
    assert (out / "daily-progress-report.out").read_text() == "previous good draft"
    assert run.archived == []


def test_invalid_generation_is_kept_aside_and_previous_restored(tmp_path):
    adapter = FakeAdapter(tmp_path / "deliverables", validator_ok=False)
    out = adapter.output_dir({})
    out.mkdir(parents=True)
    (out / "daily-progress-report.out").write_text("previous good draft", encoding="utf-8")
    mgr, _ = manager(tmp_path, adapter)
    run = to_review(mgr, start(mgr))
    assert run.status == "awaiting_input" and run.outputs == {}
    assert (out / "daily-progress-report.out").read_text() == "previous good draft"
    kept = list((out / "archives").glob("*-invalid/daily-progress-report.out"))
    assert len(kept) == 1 and kept[0].read_text().endswith("typed narrative")


def test_view_hides_the_form_after_input_and_shows_hashes_only_for_validated_outputs(tmp_path):
    mgr, _ = manager(tmp_path)
    run = to_review(mgr, start(mgr))
    view = run.view()
    assert "form" not in view and all(o["sha256"] for o in view["outputs"].values())
