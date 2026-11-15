"""Synthetic tests for the desktop shortcut scripts (no VS Code or desktop launch)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "scripts" / "console-workspace"
PS = shutil.which("powershell")
pytestmark = pytest.mark.skipif(PS is None, reason="Windows PowerShell required")


def _ps(command: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [PS, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
        capture_output=True,
        text=True,
        timeout=120,
    )


def _launcher_run(body: str, tmp_path: Path) -> subprocess.CompletedProcess:
    script = SRC / "open-console.ps1"
    return _ps(
        f". '{script}' -NoDialog; {body}; "
        f"$r = Open-WizExpertConsole -Workspace '{tmp_path}' -Port 8765 -TimeoutSeconds 1; "
        'Write-Host "rc=$r"'
    )


def test_command_line_match_is_exact(tmp_path):
    ws = str(tmp_path / "My Outer")
    good = f'python.exe -m wizexpert.console.dev --workspace "{ws}" --port 8765'
    other = f'python.exe -m wizexpert.console.dev --workspace "{ws}2" --port 8765'
    unrelated = f'node.exe server.js --workspace "{ws}"'
    script = SRC / "open-console.ps1"
    out = _ps(
        f". '{script}'; "
        f"Test-ConsoleCommandLine '{good}' '{ws}'; "
        f"Test-ConsoleCommandLine '{other}' '{ws}'; "
        f"Test-ConsoleCommandLine '{unrelated}' '{ws}'; "
        f"Test-ConsoleCommandLine '' '{ws}'"
    )
    assert out.stdout.split() == ["True", "False", "False", "False"], out.stderr


def test_command_line_match_real_backend_shapes(tmp_path):
    ws = str(tmp_path / "My Outer")
    py = r"C:\Py 3\python.exe"
    ok = [
        f'"{py}" -m wizexpert console --workspace "{ws}" --port 8765',
        f'{py} -m wizexpert console --workspace "{ws}" --port 8765 --config x.json',
        f"{py} -m wizexpert.console.dev --workspace {ws} --port 8765",
    ]
    bad = [
        f'{py} -m wizexpert console --workspace "{ws}x" --port 8765',
        f'{py} -m wizexpert console --workspace "x{ws}" --port 8765',
        f'{py} -m wizexpert consolex --workspace "{ws}" --port 8765',
        f'{py} -m wizexpert.console.devx --workspace "{ws}" --port 8765',
        f'{py} -m other wizexpert.console --workspace "{ws}"',
    ]
    script = SRC / "open-console.ps1"
    cmds = "; ".join(f"Test-ConsoleCommandLine '{x}' '{ws}'" for x in ok + bad)
    out = _ps(f". '{script}'; {cmds}")
    assert out.stdout.split() == ["True"] * len(ok) + ["False"] * len(bad), out.stderr


def test_error_path_not_blocked_by_stop_preference():
    script = SRC / "open-console.ps1"
    out = _ps(
        f"$ErrorActionPreference='Stop'; . '{script}' -NoDialog; "
        "Show-ConsoleError 'boom'; Write-Host done"
    )
    assert "done" in out.stdout and "boom" in out.stderr


def test_launcher_occupied_port_fails_without_starting(tmp_path):
    out = _launcher_run(
        "function Get-ConsoleState { 'occupied' }; "
        "function Start-Process { throw 'must not start' }",
        tmp_path,
    )
    assert "rc=2" in out.stdout


def test_launcher_ready_opens_browser_only(tmp_path):
    out = _launcher_run(
        "function Get-ConsoleState { 'ready' }; "
        'function Start-Process { param($FilePath) Write-Host "open=$FilePath" }',
        tmp_path,
    )
    assert "open=http://127.0.0.1:8765/" in out.stdout and "rc=0" in out.stdout


def test_launcher_stopped_without_code_reports_error(tmp_path):
    out = _launcher_run(
        "function Get-ConsoleState { 'stopped' }; function Find-CodeExe { $null }", tmp_path
    )
    assert "rc=3" in out.stdout


def test_launcher_stopped_opens_code_with_quoted_workspace(tmp_path):
    ws = tmp_path / "My Outer"
    ws.mkdir()
    script = SRC / "open-console.ps1"
    out = _ps(
        f". '{script}' -NoDialog; "
        "function Get-ConsoleState { if ($global:n++) { 'ready' } else { 'stopped' } }; "
        "function Find-CodeExe { 'C:\\fake\\Code.exe' }; "
        "function Start-Process { param($FilePath,$ArgumentList) "
        "Write-Host \"$FilePath|$($ArgumentList -join ' ')\" }; "
        f"$r = Open-WizExpertConsole -Workspace '{ws}' -Port 8765 -TimeoutSeconds 10; "
        'Write-Host "rc=$r"'
    )
    assert f'C:\\fake\\Code.exe|--new-window "{ws}"' in out.stdout and "rc=0" in out.stdout


def test_launcher_starting_waits_without_opening_code(tmp_path):
    out = _launcher_run(
        "function Get-ConsoleState { if ($global:n++) { 'ready' } else { 'starting' } }; "
        "function Start-Process { throw 'must not start' }",
        tmp_path,
    ).stdout
    assert "rc=0" in out


def test_install_create_noop_and_conflict(tmp_path):
    d = tmp_path / "My Outer" / "WizExpert" / "scripts" / "console-workspace"
    d.mkdir(parents=True)
    for name in ("open-console.ps1", "install-shortcut.ps1"):
        shutil.copy(SRC / name, d / name)
    desktop = tmp_path / "Desk top"
    desktop.mkdir()
    script = d / "install-shortcut.ps1"
    run = f"& '{script}' -Desktop '{desktop}'; exit $LASTEXITCODE"
    first = _ps(run)
    assert first.returncode == 0, first.stderr
    lnk = desktop / "WizExpert.lnk"
    assert lnk.exists()
    stamp = lnk.stat().st_mtime_ns
    again = _ps(run)
    assert again.returncode == 0 and "up to date" in again.stdout
    assert lnk.stat().st_mtime_ns == stamp
    other = (
        f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{lnk}');"
        '$s.TargetPath="$env:SystemRoot\\notepad.exe";$s.Save()'
    )
    assert _ps(other).returncode == 0
    stamp = lnk.stat().st_mtime_ns
    assert _ps(run).returncode == 1
    assert lnk.stat().st_mtime_ns == stamp
