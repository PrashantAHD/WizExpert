"""VS Code native prompts: read-only detection, the awaiting-consent MCP state, bring-to-front and
the start-up MCP prewarm. All windows are fakes; nothing here looks at or clicks a real dialog."""

from __future__ import annotations

import json
import sys

import pytest
from console_fakes import FakeHelper
from test_console_core import env  # noqa: F401  (fixture)
from test_console_server import api, request, token_of

from wizexpert.console import vscode_prompts
from wizexpert.console.bridge import Bridge
from wizexpert.console.config import ConsoleConfig
from wizexpert.console.runs import RunError, RunManager
from wizexpert.console.server import build_server
from wizexpert.console.vscode_prompts import PromptWatcher, Window, classify, parse_texts

AUTH_TEXT = "The MCP Server Definition 'wiz-demo' wants to authenticate to MCP.Example.Invalid."


class FakeScreen:
    """Stands in for EnumWindows / UI Automation / SetForegroundWindow."""

    def __init__(self, windows=(), texts=None, raises=False):
        self.windows = list(windows)
        self.texts = dict(texts or {})
        self.reads: list[int] = []
        self.raised: list[int] = []
        self.raises = raises

    def enumerate(self):
        return list(self.windows)

    def read(self, hwnd):
        self.reads.append(hwnd)
        return self.texts.get(hwnd, ())

    def bring(self, hwnd):
        self.raised.append(hwnd)
        return self.raises

    def watcher(self):
        return PromptWatcher(self.enumerate, self.read, self.bring)


AUTH_WINDOW = Window(101, "Visual Studio Code", ("Allow", "Cancel"))
OTHER_WINDOW = Window(202, "Visual Studio Code", ("Save", "Don't Save", "Cancel"))


def _mcp_config(workspace, name="wiz-demo"):
    path = workspace / ".vscode" / "mcp.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"servers": {name: {"url": "https://example.invalid", "headers": {"k": "s"}}}}),
        encoding="utf-8",
    )


def _manager(config, screen, calls=None):
    bridge = Bridge("t" * 64)
    cli = (lambda argv: calls.append(argv) or 0) if calls is not None else None
    manager = RunManager(
        config,
        bridge,
        run_async=False,
        sleep=lambda _s: None,
        cli=cli,
        prompts=screen.watcher(),
    )
    return manager, bridge


# -- classification and parsing --------------------------------------------------------------


def test_classify_mcp_sign_in_prompt():
    prompt = classify(AUTH_WINDOW, ("ignored", AUTH_TEXT))
    assert (prompt.kind, prompt.server, prompt.host) == (
        "mcp_auth",
        "wiz-demo",
        "mcp.example.invalid",
    )
    assert prompt.public() == {
        "id": "101",
        "kind": "mcp_auth",
        "title": "Visual Studio Code",
        "buttons": ["Allow", "Cancel"],
        "server": "wiz-demo",
        "host": "mcp.example.invalid",
    }


@pytest.mark.parametrize(
    "text",
    [
        "Do you want to save the changes you made to notes.md?",
        "The MCP Server Definition 'x' wants to authenticate to bad host/path.",
        "The MCP Server Definition 'x' wants to authenticate to ",
        "Prefix: The MCP Server Definition 'x' wants to authenticate to h.io.",
    ],
)
def test_other_text_stays_a_generic_dialog_without_its_text(text):
    prompt = classify(OTHER_WINDOW, (text,))
    assert prompt.kind == "dialog" and prompt.server == prompt.host == ""
    assert text not in json.dumps(prompt.public())  # raw dialog text never reaches the browser


@pytest.mark.parametrize(
    ("output", "expected"),
    [
        ('["a", "  b  c ", "", 3]', ("a", "b c")),
        ('"only one"', ("only one",)),
        ("", ()),
        ("null", ()),
        ("not json", ()),
    ],
)
def test_parse_texts(output, expected):
    assert parse_texts(output) == expected


def test_parse_texts_is_bounded():
    texts = parse_texts(json.dumps(["x" * 1000] * 20))
    assert len(texts) == vscode_prompts.MAX_TEXTS and all(
        len(t) == vscode_prompts.MAX_TEXT for t in texts
    )


def test_platform_functions_do_nothing_off_windows(monkeypatch):
    monkeypatch.undo()  # the autouse fixture replaced enumerate_windows; test the real one
    monkeypatch.setattr(sys, "platform", "linux")
    assert vscode_prompts.enumerate_windows() == []
    assert vscode_prompts.read_texts(123) == ()
    assert vscode_prompts.raise_window(123) is False


def test_read_texts_rejects_bad_handles(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(vscode_prompts.subprocess, "run", lambda *a, **k: pytest.fail("ran"))
    assert vscode_prompts.read_texts(0) == () and vscode_prompts.read_texts("1; x") == ()


def test_read_texts_runs_a_fixed_script_with_only_the_handle(monkeypatch):
    seen = {}

    class Done:
        returncode, stdout = 0, json.dumps([AUTH_TEXT])

    def fake_run(argv, **kwargs):
        seen["argv"], seen["kwargs"] = argv, kwargs
        return Done()

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(vscode_prompts.subprocess, "run", fake_run)
    assert vscode_prompts.read_texts(4242) == (AUTH_TEXT,)
    argv = seen["argv"]
    assert argv[0].lower().endswith("powershell.exe") and argv[1:4] == [
        "-NoProfile",
        "-NonInteractive",
        "-Command",
    ]
    assert "[IntPtr]4242" in argv[4] and "Invoke" not in argv[4]
    assert seen["kwargs"]["timeout"] and seen["kwargs"]["check"] is False


# -- watcher ---------------------------------------------------------------------------------


def test_watcher_reads_each_dialog_once_sorts_sign_in_first_and_forgets_closed_ones():
    screen = FakeScreen([OTHER_WINDOW, AUTH_WINDOW], {101: (AUTH_TEXT,)})
    watcher = screen.watcher()
    assert [p.kind for p in watcher.prompts()] == ["mcp_auth", "dialog"]
    watcher.prompts()
    assert sorted(screen.reads) == [101, 202]  # cached: no second UI Automation read
    screen.windows = [OTHER_WINDOW]
    assert [p.id for p in watcher.prompts()] == ["202"]
    screen.windows = [OTHER_WINDOW, AUTH_WINDOW]  # a new dialog may reuse an old handle
    watcher.prompts()
    assert screen.reads.count(101) == 2


def test_watcher_survives_enumeration_errors():
    def broken():
        raise OSError("no desktop")

    assert PromptWatcher(broken, lambda _h: ()).prompts() == []


def test_a_failed_read_is_cached_so_each_dialog_is_read_once():
    reads = []

    def failing(hwnd):
        reads.append(hwnd)
        raise UnicodeDecodeError("cp1252", b"\x81", 0, 1, "undefined")

    watcher = PromptWatcher(lambda: [OTHER_WINDOW], failing)
    assert [p.kind for p in watcher.prompts()] == ["dialog"]
    watcher.prompts()
    assert reads == [202]


def test_a_slow_read_never_blocks_other_requests():
    import threading

    started, release = threading.Event(), threading.Event()
    reads = []

    def slow(hwnd):
        reads.append(hwnd)
        started.set()
        release.wait(5)
        return (AUTH_TEXT,)

    watcher = PromptWatcher(lambda: [AUTH_WINDOW], slow)
    first: list = []
    worker = threading.Thread(target=lambda: first.extend(watcher.prompts()))
    worker.start()
    assert started.wait(5)
    # While the first read is still running, a second request answers at once and does not
    # start a duplicate read; the dialog is generic until its text is cached.
    assert [p.kind for p in watcher.prompts()] == ["dialog"]
    release.set()
    worker.join(5)
    assert [p.kind for p in first] == ["mcp_auth"] and reads == [101]
    assert [p.kind for p in watcher.prompts()] == ["mcp_auth"]


def test_read_texts_forces_utf8_and_survives_decode_errors(monkeypatch):
    seen = {}

    def boom(argv, **kwargs):
        seen.update(kwargs, script=argv[4])
        raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "bad")

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(vscode_prompts.subprocess, "run", boom)
    assert vscode_prompts.read_texts(77) == ()
    assert seen["encoding"] == "utf-8" and seen["errors"] == "replace"
    assert seen["script"].startswith("[Console]::OutputEncoding=[Text.Encoding]::UTF8;")


# -- run manager -----------------------------------------------------------------------------


def test_mcp_status_reports_the_sign_in_prompt_even_without_the_helper(env):  # noqa: F811
    config, workspace, _home = env
    _mcp_config(workspace)
    screen = FakeScreen([AUTH_WINDOW], {101: (AUTH_TEXT,)})
    manager, _bridge = _manager(config, screen)
    status = manager.mcp_status()
    assert status["state"] == "awaiting_consent"
    assert status["prompt"]["host"] == "mcp.example.invalid"
    assert "Allow" in status["detail"] and "secret" not in json.dumps(status)


def test_mcp_status_ignores_prompts_for_other_servers(env):  # noqa: F811
    config, workspace, _home = env
    _mcp_config(workspace)
    other = "The MCP Server Definition 'github' wants to authenticate to api.example.invalid."
    manager, _bridge = _manager(config, FakeScreen([AUTH_WINDOW], {101: (other,)}))
    assert manager.mcp_status()["state"] == "unknown"  # helper not connected; no Wiz prompt
    assert manager.vscode_prompts()[0]["server"] == "github"


def test_focus_prompt_raises_vscode_and_the_dialog_but_never_answers(env):  # noqa: F811
    config, _workspace, _home = env
    calls: list[list[str]] = []
    screen = FakeScreen([AUTH_WINDOW], {101: (AUTH_TEXT,)}, raises=True)
    manager, _bridge = _manager(config, screen, calls)
    assert "front" in manager.focus_prompt("101")
    assert calls and "--reuse-window" in calls[0] and screen.raised == [101]
    screen.raises = False
    assert "taskbar" in manager.focus_prompt("101")
    with pytest.raises(RunError, match="no longer open"):
        manager.focus_prompt("999")


def test_prewarm_starts_a_stopped_server_once(env):  # noqa: F811
    config, workspace, home = env
    _mcp_config(workspace)
    manager, bridge = _manager(config, FakeScreen())
    assert manager.prewarm_mcp()["state"] == "unknown"  # helper not connected yet: retry later
    with FakeHelper(bridge, workspace, home) as helper:
        helper.infos["mcp_status"] = {"toolCount": 0}
        assert manager.prewarm_mcp() == {"started": True, "state": "starting"}
        assert manager.prewarm_mcp()["state"] == "done"
        starts = [j for j in helper.jobs if j["kind"] == "mcp_action"]
        assert [j["action"] for j in starts] == ["start"]
        assert starts[0]["server"] == "mcp.config.ws0.wiz-demo"


def test_prewarm_leaves_a_connected_server_alone(env):  # noqa: F811
    config, workspace, home = env
    _mcp_config(workspace)
    manager, bridge = _manager(config, FakeScreen())
    with FakeHelper(bridge, workspace, home) as helper:
        helper.infos["mcp_status"] = {"toolCount": 3}
        assert manager.prewarm_mcp() == {"started": False, "state": "connected"}
        assert not [j for j in helper.jobs if j["kind"] == "mcp_action"]


def test_prewarm_can_be_disabled_and_skips_when_not_configured(env):  # noqa: F811
    config, _workspace, _home = env
    manager, _bridge = _manager(config, FakeScreen())
    assert manager.prewarm_mcp()["state"] == "not_configured"
    config.mcp_prewarm = False
    manager, _bridge = _manager(config, FakeScreen())
    assert manager.prewarm_mcp() == {"started": False, "state": "disabled"}


# -- server routes ---------------------------------------------------------------------------


@pytest.fixture
def prompt_console(tmp_path):
    import threading

    workspace = tmp_path / "ws"
    (workspace / "deliverables").mkdir(parents=True)
    config = ConsoleConfig(
        workspace=workspace,
        copilot_home=tmp_path / "copilot",
        state_dir=tmp_path / "state",
        vscode_user_dir=tmp_path / "vscode",
    )
    screen = FakeScreen([AUTH_WINDOW], {101: (AUTH_TEXT,)}, raises=True)
    calls: list[list[str]] = []

    def factory(cfg, bridge):
        return RunManager(
            cfg,
            bridge,
            run_async=False,
            cli=lambda a: calls.append(a) or 0,
            prompts=screen.watcher(),
        )

    server = build_server(config, port=0, manager_factory=factory)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server, screen, calls
    server.shutdown()
    server.server_close()


def test_prompt_routes(prompt_console):
    server, screen, calls = prompt_console
    token = token_of(server)
    status, _h, body = api(server, token, "GET", "/api/vscode/prompts")
    assert status == 200 and json.loads(body)["prompts"][0]["kind"] == "mcp_auth"
    status, _h, body = api(server, token, "POST", "/api/vscode/prompts/focus", {"id": "101"})
    assert status == 200 and json.loads(body)["ok"] and screen.raised == [101] and calls
    for bad in ({"id": "1; calc"}, {"id": 101}, {}):
        status, _h, _b = api(server, token, "POST", "/api/vscode/prompts/focus", bad)
        assert status == 400
    status, _h, body = api(server, token, "POST", "/api/helper/mcp/prewarm", {})
    assert status == 200 and json.loads(body)["state"] == "not_configured"


def test_prompt_routes_need_the_csrf_token(prompt_console):
    server, screen, _calls = prompt_console
    assert request(server, "GET", "/api/vscode/prompts")[0] == 403
    headers = {"Content-Type": "application/json", "Origin": f"http://127.0.0.1:{server.port}"}
    status, _h, _b = request(
        server, "POST", "/api/vscode/prompts/focus", headers=headers, body={"id": "101"}
    )
    assert status == 403 and screen.raised == []
