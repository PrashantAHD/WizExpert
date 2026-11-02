"""Spend-Guard handoffs: readable approval, and the run follows the new chat."""

from __future__ import annotations

import json
import sqlite3
import time

import pytest
from console_fakes import FakeHelper, append, event, make_session, tool_start
from test_console_core import env  # noqa: F401  (fixture)

from wizexpert.console.bridge import Bridge
from wizexpert.console.runs import RunError, RunManager
from wizexpert.console.sessions import SessionView, permission_summary

NEW_AHP = "55021e03-1412-4ada-8e38-acc3494cd9af"
NEW_SID = "eeeeeeee-1111-4222-8333-ffffffffffff"
THIRD_AHP = "66021e03-1412-4ada-8e38-acc3494cd9af"
THIRD_SID = "dddddddd-2222-4222-8333-aaaaaaaaaaaa"
PROMPT = "Handoff: continue the daily report from step 3."
ARGS = {
    "relationship": "independent",
    "title": "Improve progress activity",
    "model": "gpt-5.6-luna",
    "prompt": PROMPT,
}


def _manager(config, bridge=None):
    return RunManager(config, bridge or Bridge("t" * 64), run_async=False, sleep=lambda _s: None)


def _request():
    return event(
        "permission.requested",
        {
            "requestId": "r1",
            "permissionRequest": {
                "kind": "custom-tool",
                "toolName": "create_session",
                "args": ARGS,
            },
        },
        ts=time.time() - 10,
    )


def _handoff(path, ahp, call="h1", prompt=PROMPT):
    args = {**ARGS, "prompt": prompt}
    append(
        path,
        tool_start("create_session", args, call),
        event(
            "tool.execution_complete",
            {
                "toolCallId": call,
                "success": True,
                "result": {"content": f"New session created (agent-host-session://ahp-session/{ahp})."},
            },
        ),
        event("hook.end", {"hookType": "agentStop"}),
    )


def _start(manager, bridge, workspace, home):
    with FakeHelper(bridge, workspace, home) as helper:
        run = manager.start("risk-issues", {"issue_ids": "wc-id-7"})
    return run, helper.events_path


def test_create_session_permission_has_readable_summary(tmp_path):
    path = make_session(tmp_path, tmp_path, prompt="x")
    append(path, _request())
    sv = SessionView(path)
    sv.poll()
    pending = sv.pending(time.time())
    assert pending.text == (
        "Spend-Guard handoff: continue this run in a new chat 'Improve progress activity' "
        "(model gpt-5.6-luna)"
    )
    assert pending.detail == PROMPT


def test_other_custom_tool_summary_is_bounded_and_hides_secrets():
    text = permission_summary(
        {
            "kind": "custom-tool",
            "toolName": "lookup",
            "args": {"query": "q" * 500, "api_key": "SECRET", "token": "T", "n": 3},
        }
    )
    assert text.startswith("custom tool lookup (query=") and "SECRET" not in text
    assert "token" not in text and len(text) <= 300


def test_decide_works_for_custom_tool_permission(env, monkeypatch):  # noqa: F811
    config, workspace, home = env
    bridge = Bridge("t" * 64)
    manager = _manager(config, bridge)
    run, path = _start(manager, bridge, workspace, home)
    run.ahp_id = "99999999-1111-4222-8333-bbbbbbbbbbbb"
    append(path, _request())
    view = manager.view(run.id)
    assert view["pending"]["can_decide"] and view["pending"]["detail"] == PROMPT
    jobs = []
    real = bridge.post_job

    def post(job, guard=None):
        made = real(job, guard=guard)
        jobs.append((made, job))
        return made

    monkeypatch.setattr(bridge, "post_job", post)
    monkeypatch.setattr(bridge, "wait_result", lambda _j, _t: {"errors": [], "info": {}})
    manager.decide(run.id, "accept")
    job_id, job = jobs[-1]
    assert job["kind"] == "tool" and job["action"] == "accept"
    assert bridge.guard(job_id) == (True, "")


def test_handoff_rebinds_run_and_is_not_completed(env):  # noqa: F811
    config, workspace, home = env
    bridge = Bridge("t" * 64)
    manager = _manager(config, bridge)
    run, path = _start(manager, bridge, workspace, home)
    first = run.session_id
    _handoff(path, NEW_AHP)
    view = manager.view(run.id)  # session not created yet
    assert view["status"] == "handed_off" and "waiting" in view["message"]
    assert any(i["kind"] == "handoff" for i in view["progress"])
    assert view["can_open_chat"] and not view["can_open_output"]
    assert [r["id"] for r in manager.active()] == [run.id]
    assert run.ahp_id == NEW_AHP

    make_session(home, workspace, NEW_SID, prompt=PROMPT)
    run.handoff_try = 0.0
    seen = view["next"]
    view = manager.view(run.id, since=seen)
    assert run.session_id == NEW_SID and view["status"] == "running"
    assert run.chain[0]["session_id"] == first and run.chain[0]["next_ahp"] == NEW_AHP
    assert run.handoff is None and view["message"] == ""
    append(
        home / "session-state" / NEW_SID / "events.jsonl",
        tool_start("ask_user", {"message": "Which tenant?"}, "q1"),
    )
    view = manager.view(run.id, since=seen)
    assert view["status"] == "input_needed" and "Which tenant" in view["pending"]["text"]
    assert any(i.get("tool") == "ask_user" for i in view["progress"]), "seq continues"


def test_new_chat_found_through_agent_host_db(env):  # noqa: F811
    config, workspace, home = env
    bridge = Bridge("t" * 64)
    manager = _manager(config, bridge)
    run, path = _start(manager, bridge, workspace, home)
    _handoff(path, NEW_AHP, prompt="short")
    db = config.agent_host_db
    db.parent.mkdir(parents=True)
    con = sqlite3.connect(db)
    con.execute("create table chats_v2 (owner_session_uri text, provider_data text)")
    con.execute(
        "insert into chats_v2 values (?, ?)",
        (f"ahp-session:/{NEW_AHP}", json.dumps({"sdkSessionId": NEW_SID})),
    )
    con.commit()
    con.close()
    make_session(home, workspace, NEW_SID, prompt="something else entirely")
    manager.view(run.id)
    assert run.session_id == NEW_SID and run.ahp_id == NEW_AHP


def test_handoff_chain_survives_restart_and_multiple_handoffs(env):  # noqa: F811
    config, workspace, home = env
    bridge = Bridge("t" * 64)
    manager = _manager(config, bridge)
    run, path = _start(manager, bridge, workspace, home)
    first = run.session_id
    _handoff(path, NEW_AHP)
    second = make_session(home, workspace, NEW_SID, prompt=PROMPT)
    manager.view(run.id)
    assert run.session_id == NEW_SID

    again = _manager(config)  # backend restart
    restored = again.get(run.id)
    assert restored.session_id == NEW_SID and restored.status == "running"
    assert [c["session_id"] for c in restored.chain] == [first]
    view = again.view(run.id)
    assert any(i["kind"] == "handoff" for i in view["progress"])

    _handoff(second, THIRD_AHP, call="h2", prompt="Handoff two")
    make_session(home, workspace, THIRD_SID, prompt="Handoff two")
    view = again.view(run.id)
    assert restored.session_id == THIRD_SID and view["status"] == "running"
    assert [c["session_id"] for c in restored.chain] == [first, NEW_SID]
    append(
        home / "session-state" / THIRD_SID / "events.jsonl",
        event("assistant.message", {"content": "All done."}),
        event("hook.end", {"hookType": "agentStop"}),
    )
    assert again.view(run.id)["status"] == "completed"
    assert _manager(config).get(run.id).chain[1]["session_id"] == NEW_SID


def test_pending_handoff_survives_restart(env):  # noqa: F811
    config, workspace, home = env
    bridge = Bridge("t" * 64)
    manager = _manager(config, bridge)
    run, path = _start(manager, bridge, workspace, home)
    _handoff(path, NEW_AHP)
    assert manager.view(run.id)["status"] == "handed_off"
    again = _manager(config)
    assert again.get(run.id).status == "handed_off" and again.active()
    make_session(home, workspace, NEW_SID, prompt=PROMPT)
    again.get(run.id).handoff_try = 0.0
    assert again.view(run.id)["status"] == "running"
    assert again.get(run.id).session_id == NEW_SID


def test_unresolved_handoff_times_out_as_interrupted_not_completed(env):  # noqa: F811
    config, workspace, home = env
    bridge = Bridge("t" * 64)
    clock = {"t": time.time()}
    manager = RunManager(
        config, bridge, run_async=False, sleep=lambda _s: None, clock=lambda: clock["t"]
    )
    run, path = _start(manager, bridge, workspace, home)
    _handoff(path, NEW_AHP)
    assert manager.view(run.id)["status"] == "handed_off"
    clock["t"] += 4000
    assert manager.view(run.id)["status"] == "interrupted"
    with pytest.raises(RunError):
        manager.stop(run.id)
