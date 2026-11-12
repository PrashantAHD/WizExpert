"""Daily Refresh freshness gate: a finished chat is not success unless outputs are fresh."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

import pytest
from console_fakes import event, tool_start
from test_console_core import env  # noqa: F401 (fixture)

from wizexpert.console import freshness
from wizexpert.console.bridge import Bridge
from wizexpert.console.config import ConsoleConfig
from wizexpert.console.runs import Run, RunManager
from wizexpert.console.sessions import SessionView

NOW = datetime(2026, 11, 12, 13, 0, tzinfo=UTC)
DAY = "2026-11-12"


def _cfg(tmp_path: Path) -> ConsoleConfig:
    return ConsoleConfig(workspace=tmp_path)


def _touch(path: Path, when: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x", encoding="utf-8")
    os.utime(path, (when, when))


def _campaign(tmp_path: Path) -> Path:
    return tmp_path / "deliverables" / "Daily-Progress-Reporting" / "PHP2Shell-Campaign"


def _build(tmp_path: Path, when: float, skip: str = "") -> None:
    c = _campaign(tmp_path)
    stem = f"{DAY}T12-58-14Z.json"
    names = [
        f"snapshots/{stem}", f"inventories/{stem}", "report-validation.json",
        "PHP2Shell-Daily-Progress-Report.pdf", "PHP2Shell-Day-over-Day-Movements.pdf",
        "PHP2Shell-VM-and-CVE-Details.xlsx", f"Inactive-Assets-Findings-{DAY}.xlsx",
        f"PHP2Shell-Stakeholder-Reply-{DAY}.html",
    ]
    for n in names:
        if n != skip:
            _touch(c / n, when)


def _missing(tmp_path: Path, since: float) -> list[str]:
    return freshness.missing_outputs(_cfg(tmp_path), since, NOW)


def test_fresh_outputs_pass(tmp_path: Path) -> None:
    _build(tmp_path, 2000.0)
    assert _missing(tmp_path, 1000.0) == []


def test_stale_outputs_block(tmp_path: Path) -> None:
    _build(tmp_path, 500.0)
    missing = _missing(tmp_path, 1000.0)
    assert any("snapshot" in m for m in missing)
    assert "report-validation.json" in missing


def test_missing_workbook_is_named(tmp_path: Path) -> None:
    _build(tmp_path, 2000.0, skip=f"Inactive-Assets-Findings-{DAY}.xlsx")
    assert _missing(tmp_path, 1000.0) == ["Inactive-Assets-Findings workbook"]


def test_gate_reports_reconnect_on_auth_failure(tmp_path: Path) -> None:
    _build(tmp_path, 500.0)
    ok, why = freshness.gate(_cfg(tmp_path), 1000.0, auth_failed=True)
    assert not ok and why.startswith(freshness.RECONNECT_MESSAGE)
    assert "Missing or stale:" in why and "report-validation.json" in why


def test_gate_names_missing_without_auth_text(tmp_path: Path) -> None:
    ok, why = freshness.gate(_cfg(tmp_path), 1000.0)
    assert not ok and "did not produce fresh outputs" in why


def test_work_item_match() -> None:
    assert freshness.is_php2shell("PHP2SHELL Campaign")
    assert not freshness.is_php2shell("Other campaign")


def _feed(view, *events):
    for line in events:
        view._line(line.encode())


def _result(call, success=True, **extra):
    return event("tool.execution_complete", {"toolCallId": call, "success": success, **extra})


def test_conditional_prose_and_successful_payloads_are_not_auth_failures(tmp_path):
    view = SessionView(tmp_path / "events.jsonl")
    _feed(view, event("assistant.message", {"content":
        "I'm starting and will stop immediately if Wiz returns 401 or a sign-in challenge."}))
    _feed(view, event("assistant.message", {"content": "OAuth is configured."}))
    _feed(view, tool_start("powershell", {"command": "print('401 Unauthorized')"}, "shell"),
          _result("shell", False, error={"message": "401 Unauthorized"}))
    for index in range(18):
        call = str(index)
        _feed(view, tool_start("wiz-execute", {"tool_name": "get_vulnerability_catalog"}, call),
              _result(call, result={"content": "An asset named 401 OAuth"}))
    _feed(view, tool_start("wiz-discover", {"domain": "resource"}, "bad-domain"),
          _result("bad-domain", False, error={"message": "Unknown domain 401; OAuth docs"}))
    assert not view.wiz_auth_failed


@pytest.mark.parametrize("name", ["wiz-execute", "mcp__wiz__execute", "wiz.discover"])
@pytest.mark.parametrize("failure", [
    {"success": False, "error": {"message": "HTTP 401 Unauthorized"}},
    {"success": False, "error": {"statusCode": 401}},
    {"success": False, "result": "HTTP 401 Unauthorized"},
    {"success": True, "result": {"isError": True, "content": [
        {"type": "text", "text": "OAuth challenge: authentication required"}]}},
])
def test_real_auth_and_ordered_recovery(tmp_path, name, failure):
    view = SessionView(tmp_path / "events.jsonl")
    _feed(view, tool_start(name, {}, "auth"), _result("auth", **failure))
    assert view.wiz_auth_failed
    # Non-Wiz success and an unrelated discovery error do not prove recovery.
    _feed(view, tool_start("powershell", {}, "local"), _result("local"),
          tool_start("wiz-discover", {}, "domain"),
          _result("domain", False, error={"message": "Unknown domain"}))
    assert view.wiz_auth_failed
    # Classification survives progress truncation and is ordered by completion, not start.
    _feed(view, tool_start("wiz-execute", {}, "recovered"))
    for _ in range(405):
        _feed(view, event("assistant.message", {"content": "progress"}))
    _feed(view, _result("recovered"))
    assert not view.wiz_auth_failed
    _feed(view, tool_start(name, {}, "terminal"), _result("terminal", **failure))
    assert view.wiz_auth_failed
    view._reset()
    assert not view.wiz_auth_failed and not view.wiz_calls


def test_stale_draft_is_local_repair_and_complete_pack_passes(tmp_path, monkeypatch):
    original = freshness.missing_outputs
    monkeypatch.setattr(freshness, "missing_outputs", lambda c, s: original(c, s, NOW))
    _build(tmp_path, 2000.0)
    draft = _campaign(tmp_path) / f"PHP2Shell-Stakeholder-Reply-{DAY}.html"
    _touch(draft, 500.0)
    ok, why = freshness.gate(_cfg(tmp_path), 1000.0, auth_failed=True)
    assert not ok and why.startswith("Local generation incomplete")
    assert "Stakeholder reply draft" in why and "Reconnect" not in why
    _touch(draft, 2000.0)
    assert freshness.gate(_cfg(tmp_path), 1000.0) == (True, "")


def test_later_outputs_do_not_rewrite_frozen_history(env, monkeypatch):  # noqa: F811
    config, workspace, _ = env
    _build(workspace, 500.0)
    original = freshness.missing_outputs
    monkeypatch.setattr(freshness, "missing_outputs", lambda c, s: original(c, s, NOW))
    manager = RunManager(config, Bridge("t" * 64), run_async=False)
    run = Run(id="old", category_id="daily-progress-reporting", action_id="continue-work-item",
              values={"work_item": "PHP2Shell"}, prompt="", created=1000.0, status="completed")
    manager._runs[run.id] = run
    first = manager.view(run.id)
    assert first["outcome"] == "incomplete"
    restored = RunManager(config, Bridge("t" * 64), run_async=False)
    assert restored.view(run.id)["message"] == first["message"]
    assert "Stakeholder reply draft" in restored.get(run.id).final["checklist"][-1]["detail"]
    _build(workspace, 2000.0)
    assert manager.view(run.id)["message"] == first["message"]
    new = Run(id="new", category_id=run.category_id, action_id=run.action_id,
              values=run.values, prompt="", created=1500.0, status="completed")
    manager._runs[new.id] = new
    assert manager.view(new.id)["outcome"] == "completed"
