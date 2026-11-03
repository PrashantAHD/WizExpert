"""Helper extension packaging and static checks (no VS Code needed)."""

from __future__ import annotations

import json
import shutil
import subprocess
import zipfile

import pytest

from wizexpert.console import helper


def test_vsix_has_manifest_without_dependencies(tmp_path):
    vsix = helper.build_vsix(tmp_path / "h.vsix")
    with zipfile.ZipFile(vsix) as bundle:
        names = set(bundle.namelist())
        package = json.loads(bundle.read("extension/package.json"))
        source = bundle.read("extension/extension.js").decode()
    assert {
        "[Content_Types].xml",
        "extension.vsixmanifest",
        "extension/package.json",
        "extension/extension.js",
    } <= names
    assert package["publisher"] == "local" and package["name"] == "wizexpert-console-helper"
    assert "onStartupFinished" in package["activationEvents"]
    assert not package.get("dependencies") and not package.get("extensionDependencies")
    assert "require('vscode')" in source


def test_extension_runs_only_allow_listed_commands():
    source = helper.SOURCE.read_text(encoding="utf-8")
    called = set(__import__("re").findall(r"executeCommand\(([^,)]+)", source))
    assert called <= {
        "COMMANDS.newChat",
        "COMMANDS.open",
        "stopCommand",  # first available entry of COMMANDS.stopCandidates (allow-list)
        "COMMANDS.trust",
        "'vscode.open'",
        "command",
    }
    for command in (
        "workbench.action.chat.newChat",
        "workbench.action.chat.open",
        "workbench.action.chat.acceptTool",
        "workbench.action.chat.skipTool",
        "workbench.action.chat.cancel",
    ):
        assert command in source
    assert "child_process" not in source and "eval(" not in source


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_extension_source_parses():
    result = subprocess.run(
        ["node", "--check", str(helper.SOURCE)], capture_output=True, timeout=30, check=False
    )  # nosec B603 B607
    assert result.returncode == 0, result.stderr.decode()


def test_start_chat_never_waits_forever_on_chat_commands():
    source = helper.SOURCE.read_text(encoding="utf-8")
    assert "function settleWithin(" in source
    assert "settleWithin(vscode.commands.executeCommand(COMMANDS.newChat)" in source
    assert "settleWithin(vscode.commands.executeCommand(COMMANDS.open," in source


def test_helper_reports_connection_state_and_chat_permission_errors():
    source = helper.SOURCE.read_text(encoding="utf-8")
    assert "createOutputChannel('WizExpert Console Helper')" in source
    assert "createStatusBarItem(" in source
    assert "report('waiting'" in source and "report('connected'" in source
    assert "loop().catch(" in source
    assert "VS Code refused to create a chat" in source
    assert helper.VERSION != "0.1.1"


def test_chat_creation_checks_permission_and_reports_concrete_errors():
    source = helper.SOURCE.read_text(encoding="utf-8")
    assert "async function chatGate(" in source and "isTrusted" in source
    assert "const gate = await chatGate(true)" in source
    assert "nc.timedOut" in source and "report('blocked'" in source
    assert helper.VERSION == "0.1.9"


def test_helper_activates_on_startup_and_logs_activation():
    events = helper.PACKAGE["activationEvents"]
    assert "onStartupFinished" in events and "*" not in events
    source = helper.SOURCE.read_text(encoding="utf-8")
    assert "' activated v'" in source and "wizexpertConsoleHelper.status" in source
