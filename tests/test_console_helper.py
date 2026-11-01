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
    assert package["activationEvents"] == ["onStartupFinished"]
    assert not package.get("dependencies") and not package.get("extensionDependencies")
    assert "require('vscode')" in source


def test_extension_runs_only_allow_listed_commands():
    source = helper.SOURCE.read_text(encoding="utf-8")
    called = set(__import__("re").findall(r"executeCommand\(([^,)]+)", source))
    assert called <= {"COMMANDS.newChat", "COMMANDS.open", "'vscode.open'", "command"}
    for command in (
        "workbench.action.chat.newChat",
        "workbench.action.chat.open",
        "workbench.action.chat.acceptTool",
        "workbench.action.chat.skipTool",
    ):
        assert command in source
    assert "child_process" not in source and "eval(" not in source


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_extension_source_parses():
    result = subprocess.run(
        ["node", "--check", str(helper.SOURCE)], capture_output=True, timeout=30, check=False
    )  # nosec B603 B607
    assert result.returncode == 0, result.stderr.decode()
