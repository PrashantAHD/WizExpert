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


def test_reload_window_is_gone_and_ensure_helper_asks_for_manual_reload(tmp_path, monkeypatch):
    assert not hasattr(helper, "reload_window")
    config, _ws = _config(tmp_path)
    server = build_server(config, port=0)
    try:
        app = server.app
        monkeypatch.setattr(helper, "install", lambda *_a, **_k: 0)
        waits = []
        monkeypatch.setattr(
            type(app), "_wait_for_helper", lambda _s, _w, secs: waits.append(secs) or False
        )
        with pytest.raises(RunError, match="Developer: Reload Window"):
            app.ensure_helper()
        assert waits == [3.0, 20.0]
        monkeypatch.setattr(type(app), "_wait_for_helper", lambda _s, _w, secs: secs == 20.0)
        assert app.ensure_helper() is True
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
    assert branch.index("/vscode/guard") < branch.index("COMMANDS.stop")
    assert "g.ok !== true" in branch and "info.guard" in branch