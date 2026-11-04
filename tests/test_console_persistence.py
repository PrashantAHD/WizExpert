"""A running task is never lost by a page refresh, a new tab or a backend restart."""

from __future__ import annotations

import json

import pytest
from console_fakes import FakeHelper, append, event, tool_done, tool_start
from test_console_core import env  # noqa: F401  (fixture)

from wizexpert.console.bridge import Bridge
from wizexpert.console.runs import RunError, RunManager


def _manager(config):
    return RunManager(config, Bridge("t" * 64), run_async=False, sleep=lambda _s: None)


def _manager_with(config, bridge):
    return RunManager(config, bridge, run_async=False, sleep=lambda _s: None)


def test_active_runs_api_data_and_duplicate_start_rejected(env):  # noqa: F811
    config, workspace, home = env
    bridge = Bridge("t" * 64)
    manager = _manager_with(config, bridge)
    with FakeHelper(bridge, workspace, home):
        run = manager.start("risk-issues", {"issue_ids": "wc-id-7"})
        assert [r["id"] for r in manager.active()] == [run.id]
        with pytest.raises(RunError, match="already active"):
            manager.start("risk-issues", {"issue_ids": "wc-id-8"})


def test_finished_run_is_not_active_and_allows_a_new_start(env):  # noqa: F811
    config, workspace, home = env
    bridge = Bridge("t" * 64)
    manager = _manager_with(config, bridge)
    with FakeHelper(bridge, workspace, home) as helper:
        run = manager.start("risk-issues", {"issue_ids": "wc-id-7"})
        append(
            helper.events_path,
            event("assistant.message", {"content": "Done."}),
            event("hook.end", {"hookType": "agentStop"}),
        )
        assert manager.active() == []  # finished while no page was watching
        assert manager.view(run.id)["status"] == "completed"


def test_restart_restores_active_run_and_pending_state(env, monkeypatch):  # noqa: F811
    config, workspace, home = env
    bridge = Bridge("t" * 64)
    manager = _manager_with(config, bridge)
    with FakeHelper(bridge, workspace, home) as helper:
        run = manager.start("risk-issues", {"issue_ids": "wc-id-7"})
        append(helper.events_path, tool_start("ask_user", {"message": "Which tenant?"}, "q1"))
        assert manager.view(run.id)["status"] == "input_needed"
        # "Backend restart": a brand-new manager reads the same state directory.
        again = _manager_with(config, Bridge("t" * 64))
        assert [r["id"] for r in again.active()] == [run.id]
        view = again.view(run.id)
        assert view["status"] == "input_needed"
        assert view["pending"]["kind"] == "question" and "Which tenant" in view["pending"]["text"]
        assert view["progress"], "progress replays from the session log"
        with pytest.raises(RunError, match="already active"):
            again.start("risk-issues", {"issue_ids": "wc-id-9"})
        # The chat finishes while the backend is down: the restored run shows the final state.
        append(
            helper.events_path,
            tool_done("q1"),
            event("assistant.message", {"content": "All done."}),
            event("hook.end", {"hookType": "agentStop"}),
        )
        final = _manager_with(config, Bridge("t" * 64))
        assert final.active() == []
        assert final.view(run.id)["status"] == "completed"


def test_run_index_is_atomic_utf8_without_bom(env):  # noqa: F811
    config, workspace, home = env
    bridge = Bridge("t" * 64)
    manager = _manager_with(config, bridge)
    with FakeHelper(bridge, workspace, home):
        manager.start("risk-issues", {"issue_ids": "wc-id-7"})
    raw = (config.state_dir / "runs.json").read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf") and json.loads(raw.decode("utf-8"))
    assert list(config.state_dir.glob("runs.json.*.tmp")) == []


def test_run_caught_mid_start_is_rematched_not_lost(env):  # noqa: F811
    config, workspace, home = env
    bridge = Bridge("t" * 64)
    manager = _manager_with(config, bridge)
    with FakeHelper(bridge, workspace, home):
        run = manager.start("risk-issues", {"issue_ids": "wc-id-7"})
        # Simulate a restart that happened before the session was bound.
        run.status, run.session_id = "starting", ""
        manager._save()
        again = _manager_with(config, Bridge("t" * 64))
        assert again.get(run.id).status == "running"
        assert again.get(run.id).session_id


def test_run_with_no_chat_found_after_restart_is_not_started(env):  # noqa: F811
    config, _workspace, _home = env
    config.state_dir.mkdir(parents=True)
    (config.state_dir / "runs.json").write_text(
        json.dumps(
            [
                {
                    "id": "20260101T000000Z-aaaaaa",
                    "category_id": "risk-issues",
                    "values": {},
                    "prompt": "x",
                    "created": 1.0,
                    "status": "starting",
                }
            ]
        ),
        encoding="utf-8",
    )
    manager = _manager(config)
    assert manager.active() == []
    assert manager.get("20260101T000000Z-aaaaaa").status == "not_started"


def test_not_started_run_is_rebound_when_its_session_appears_late(env):  # noqa: F811
    config, workspace, home = env
    bridge = Bridge("t" * 64)
    manager = _manager_with(config, bridge)
    with FakeHelper(bridge, workspace, home):
        run = manager.start("risk-issues", {"issue_ids": "wc-id-7"})
        sid = run.session_id
        # Persisted by an earlier restart that did not see the session yet.
        run.status, run.session_id = "not_started", ""
        run.message = "The console stopped before this run started."
        manager._save()
        again = _manager_with(config, Bridge("t" * 64))
        assert again.get(run.id).status == "running"
        assert again.get(run.id).session_id == sid
        assert _manager_with(config, Bridge("t" * 64)).get(run.id).session_id == sid


def test_other_not_started_runs_are_not_revived(env):  # noqa: F811
    config, workspace, home = env
    bridge = Bridge("t" * 64)
    manager = _manager_with(config, bridge)
    with FakeHelper(bridge, workspace, home):
        run = manager.start("risk-issues", {"issue_ids": "wc-id-7"})
        run.status, run.session_id = "not_started", ""
        run.message = "VS Code did not start the chat."
        assert manager.get(run.id).status == "not_started"
        run.status, run.message = "stopped", "The console stopped before this run started."
        assert manager.get(run.id).status == "stopped"
