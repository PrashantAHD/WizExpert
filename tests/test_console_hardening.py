"""Prompt-charset parity, SNOW marker rejection, BOM guard, helper setup and stop safety."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest
from console_fakes import FakeHelper

from wizexpert.console import categories, helper
from wizexpert.console.bridge import Bridge
from wizexpert.console.config import ConsoleConfig
from wizexpert.console.runs import RunError, RunManager
from wizexpert.console.server import build_server

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import public_check  # noqa: E402


def _js_prompt() -> tuple[str, int]:
    source = (ROOT / "wizexpert/console/extension/extension.js").read_text(encoding="utf-8")
    match = re.search(r"const PROMPT = /\^\[(.+?)\]\{1,(\d+)\}\$/;", source)
    assert match, "PROMPT regex not found"
    return match.group(1), int(match.group(2))


def _max_prompt() -> int:
    limits = []
    for category in categories.CATEGORIES.values():
        limits.append(category.max_prompt)
        limits.extend(a.max_prompt for a in category.actions)
    return max(limits)


def test_js_prompt_regex_matches_python_limits_and_charset():
    chars, limit = _js_prompt()
    assert limit == _max_prompt()
    assert chars == categories.ACTION_SAFE.pattern[1:].rsplit("]", 1)[0]
    assert re.fullmatch(f"[{chars}]{{1,{limit}}}", "It's 100% ok? yes! a@b")


def test_weekly_prompt_with_max_snow_response_passes_python_and_js():
    chars, limit = _js_prompt()
    text = ("Owner said it's 100% fine? yes! a@b. " * 60)[: categories.MAX_EMAIL]
    values = categories.validate(
        "weekly-progress-reporting",
        {"reporting_monday": "2026-11-02", "snow_response": text},
    )
    prompt = categories.build_prompt("weekly-progress-reporting", values)
    assert len(prompt) <= limit
    assert re.fullmatch(f"[{chars}]{{1,{limit}}}", prompt)


@pytest.mark.parametrize(
    "text",
    [
        "snow response",
        "snow_response",
        "snow-response",
        "SNOW  _ - RESPONSE",
        "BEGIN SNOW-RESPONSE",
        "END_SNOW_RESPONSE",
    ],
)
def test_snow_response_markers_are_rejected(text):
    with pytest.raises(categories.InputError):
        categories._snow_response(text)


def test_snow_response_normal_text_is_accepted():
    assert categories._snow_response("Owner replied: patched on Friday.")


def test_public_check_rejects_bom():
    assert "UTF-8 BOM is not allowed" in public_check.content_issues(b"\xef\xbb\xbfx = 1\n")
    assert public_check.content_issues(b"x = 1\n") == []


def test_public_text_files_have_no_bom():
    bad = []
    for folder in ("wizexpert", "tests", "scripts", "docs"):
        for path in (ROOT / folder).rglob("*"):
            text_file = path.is_file() and path.suffix in {".py", ".js", ".html", ".css", ".md"}
            if text_file and path.read_bytes().startswith(b"\xef\xbb\xbf"):
                bad.append(str(path.relative_to(ROOT)))
    assert not bad


def test_weekly_svg_is_public_and_html_apostrophe_is_clean():
    assert "wizexpert/console/static/assets/workflow-weekly-progress.svg" in (
        public_check.PUBLIC_FILES
    )
    html = (ROOT / "wizexpert/console/static/index.html").read_text(encoding="utf-8")
    assert "week?s" not in html


def _config(tmp_path):
    workspace = tmp_path / "ws"
    (workspace / "deliverables").mkdir(parents=True)
    config = ConsoleConfig(
        workspace=workspace,
        copilot_home=tmp_path / "copilot",
        state_dir=tmp_path / "state",
        vscode_user_dir=tmp_path / "vscode",
    )
    return config, workspace


def test_ensure_helper_opens_one_standard_window_then_waits(tmp_path, monkeypatch):
    assert not hasattr(helper, "reload_window") and not hasattr(helper, "wake")
    config, ws = _config(tmp_path)
    config.allow_cli_fallback = False
    server = build_server(config, port=0)
    try:
        app = server.app
        launches = []
        monkeypatch.setattr(helper, "install", lambda *_a, **_k: 0)
        monkeypatch.setattr(
            helper, "open_workspace_window", lambda *a, **_k: launches.append(a) or 0
        )
        waits = []
        monkeypatch.setattr(
            type(app), "_wait_for_helper", lambda _s, _w, secs: waits.append(secs) or False
        )
        with pytest.raises(RunError, match="standard VS Code window") as caught:
            app.ensure_helper()
        assert "Reload Window" not in str(caught.value)
        assert "not the Agents window" in str(caught.value)
        assert launches == [(config.code_command, str(ws.resolve()))]
        assert waits == [3.0, 0.0, 45.0]
        # rate limit: a second recovery right away must not open another window
        with pytest.raises(RunError, match="already opened"):
            app.ensure_helper()
        assert len(launches) == 1
        # after the cooldown a new window may be opened again
        app._last_launch -= 91.0
        with pytest.raises(RunError):
            app.ensure_helper()
        assert len(launches) == 2
        monkeypatch.setattr(type(app), "_wait_for_helper", lambda _s, _w, secs: secs == 45.0)
        app._last_launch -= 91.0
        assert app.ensure_helper() is True
    finally:
        server.server_close()


def test_no_window_launch_when_connected(tmp_path, monkeypatch):
    config, ws = _config(tmp_path)
    config.allow_cli_fallback = True
    server = build_server(config, port=0)
    try:
        app = server.app
        launches = []
        monkeypatch.setattr(helper, "install", lambda *_a, **_k: 0)
        monkeypatch.setattr(helper, "open_workspace_window", lambda *a, **_k: launches.append(a))
        monkeypatch.setattr(app.bridge, "helper_connected", lambda *_a: True)
        assert app.ensure_helper() is True
        assert launches == []
    finally:
        server.server_close()


def test_helper_seen_recently_but_gone_waits_grace_then_launches(tmp_path, monkeypatch):
    config, ws = _config(tmp_path)
    config.allow_cli_fallback = True
    server = build_server(config, port=0)
    try:
        app = server.app
        launches = []
        waits = []
        monkeypatch.setattr(helper, "install", lambda *_a, **_k: 0)
        monkeypatch.setattr(
            helper, "open_workspace_window", lambda *a, **_k: launches.append(a) or 0
        )
        monkeypatch.setattr(app.bridge, "helper_connected", lambda *_a: False)
        monkeypatch.setattr(app.bridge, "helper_seen_within", lambda *_a: True)
        monkeypatch.setattr(
            type(app), "_wait_for_helper", lambda _s, _w, secs: waits.append(secs) or False
        )
        assert app.ensure_helper() is False
        assert waits == [3.0, 0.0, 8.0, 45.0]  # grace for a reload, then the window launch
        assert launches == [(config.code_command, str(ws.resolve()))]
        assert "opened automatically" in app.manager.helper_note
        # the helper reconnecting within the grace period means no window at all
        launches.clear()
        app._last_launch = None
        monkeypatch.setattr(type(app), "_wait_for_helper", lambda _s, _w, secs: secs == 8.0)
        assert app.ensure_helper() is True
        assert launches == []
    finally:
        server.server_close()


def test_window_launch_failure_is_a_concrete_problem(tmp_path, monkeypatch):
    config, _ws = _config(tmp_path)
    config.allow_cli_fallback = True
    server = build_server(config, port=0)
    try:
        app = server.app
        monkeypatch.setattr(helper, "install", lambda *_a, **_k: 0)
        monkeypatch.setattr(helper, "open_workspace_window", lambda *_a, **_k: 3)
        monkeypatch.setattr(type(app), "_wait_for_helper", lambda *_a: False)
        assert app.ensure_helper() is False
        assert "could not open a standard window" in app.manager.helper_note
        assert "exit 3" in app.manager.helper_note
    finally:
        server.server_close()


def test_stop_is_guarded_and_reports_refusal(tmp_path, monkeypatch):
    config, workspace = _config(tmp_path)
    bridge = Bridge("t" * 64)
    manager = RunManager(config, bridge, run_async=False, sleep=lambda _s: None)
    with FakeHelper(bridge, workspace, tmp_path / "copilot"):
        run = manager.start("daily-progress-reporting", {})
        run.ahp_id = "99999999-1111-4222-8333-bbbbbbbbbbbb"
        jobs = []
        real_post = bridge.post_job

        def post(job, guard=None):
            made = real_post(job, guard=guard)
            jobs.append((made, job))
            return made

        monkeypatch.setattr(bridge, "post_job", post)
        monkeypatch.setattr(bridge, "wait_result", lambda _j, _t: {"errors": [], "info": {}})
        manager.stop(run.id)
        job_id, job = jobs[-1]
        assert job["kind"] == "stop_chat"
        assert bridge.guard(job_id) == (True, "")
        run.status = "completed"
        assert bridge.guard(job_id) == (False, "this chat is no longer running")

        run.status = "running"
        refusal = {"info": {"guard": "this chat is no longer running"}}
        monkeypatch.setattr(bridge, "wait_result", lambda _j, _t: refusal)
        with pytest.raises(RunError, match="Not stopped: this chat is no longer running"):
            manager.stop(run.id)


def test_extension_stop_chat_checks_guard_first():
    source = (ROOT / "wizexpert/console/extension/extension.js").read_text(encoding="utf-8")
    branch = source.split("job.kind === 'stop_chat'", 1)[1].split("job.kind === 'open_file'", 1)[0]
    assert branch.index("/vscode/guard") < branch.index("stopCandidates")
    assert "g.ok !== true" in branch and "info.guard" in branch


def test_extension_stop_picks_first_available_allow_listed_cancel_command():
    source = (ROOT / "wizexpert/console/extension/extension.js").read_text(encoding="utf-8")
    candidates = re.search(r"stopCandidates: \[(.+?)\]", source).group(1)
    assert re.findall(r"'([^']+)'", candidates)[0] == "workbench.action.chat.cancel"
    assert "workbench.action.chat.stop" in candidates  # older VS Code
    branch = source.split("job.kind === 'stop_chat'", 1)[1].split("job.kind === 'open_file'", 1)[0]
    assert "getCommands(true)" in branch
    assert "COMMANDS.stopCandidates.find((c) => available.includes(c))" in branch
    assert "if (!stopCommand) throw new Error(" in branch
    assert "executeCommand(stopCommand)" in branch
    assert "executeCommand(COMMANDS.stop)" not in source


def test_helper_recovery_falls_back_to_cli_records_reason_and_is_single_flight(
    tmp_path, monkeypatch
):
    config, _ws = _config(tmp_path)
    config.allow_cli_fallback = True
    server = build_server(config, port=0)
    try:
        app = server.app
        calls = []
        monkeypatch.setattr(helper, "install", lambda *_a, **_k: calls.append("install") or 0)
        monkeypatch.setattr(
            helper, "open_workspace_window", lambda *_a, **_k: calls.append("window") or 0
        )
        monkeypatch.setattr(type(app), "_wait_for_helper", lambda *_a: False)
        assert app.ensure_helper() is False  # fallback path, no exception
        assert calls == ["install", "window"]
        assert "did not connect" in app.manager.helper_note
        assert "not the Agents window" in app.manager.helper_note
        assert app.manager.helper_state()["problem"] == app.manager.helper_note
        # a second request while recovery is running must not install/open a window again
        calls.clear()
        assert app._ensure_lock.acquire(blocking=False)
        try:
            assert app.ensure_helper() is False
        finally:
            app._ensure_lock.release()
        assert calls == []
    finally:
        server.server_close()


def test_install_is_idempotent_and_window_launch_uses_an_argument_list(monkeypatch, tmp_path):
    runs = []
    kwargs = []

    class Done:
        returncode = 0
        stdout = f"other.ext@1.0.0\n{helper.EXTENSION_ID}@{helper.VERSION}\n"

    def fake_run(argv, **kw):
        runs.append(argv)
        kwargs.append(kw)
        return Done()

    monkeypatch.setattr(helper.subprocess, "run", fake_run)
    assert helper.installed_version("code") == helper.VERSION
    assert helper.install(tmp_path / "h.vsix", "code") == 0
    assert not any("--install-extension" in argv for argv in runs)  # no churn when current
    helper.install(tmp_path / "h.vsix", "code", force=True)
    assert any("--install-extension" in argv for argv in runs)
    assert helper.open_workspace_window("code", tmp_path) == 0
    assert runs[-1][-2:] == ["-n", str(tmp_path)]
    assert isinstance(runs[-1], list) and not kwargs[-1].get("shell")
    assert helper.open_workspace_window("code", tmp_path / "missing") == 1  # not a folder
    assert len(runs) == len(kwargs)


def test_start_runs_helper_recovery_outside_the_manager_lock(tmp_path):
    config, _ws = _config(tmp_path)
    manager = RunManager(config, Bridge("t" * 64), run_async=False, sleep=lambda _s: None)
    seen = []

    def ensure():
        seen.append(manager._lock.acquire(blocking=False))  # free: recovery holds no lock
        manager._lock.release()
        raise RunError("recovery failed: concrete reason")

    with pytest.raises(RunError, match="concrete reason"):
        manager.start("daily-progress-reporting", {}, ensure_helper=ensure)
    assert seen == [True]


def test_page_auto_connects_the_helper_without_a_manual_reload():
    js = (ROOT / "wizexpert/console/static/app.js").read_text(encoding="utf-8")
    assert "/api/helper/connect" in js and "autoConnect()" in js
    assert "Run Developer: Reload Window" not in js
    assert "standard VS Code window" in js
