from __future__ import annotations

import shutil
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

from scripts import verify


@pytest.fixture
def audit_root(monkeypatch):
    root = Path.cwd() / ".pytest_cache" / "verification-tests" / uuid.uuid4().hex
    root.mkdir(parents=True)
    monkeypatch.setattr(verify, "ROOT", root)
    try:
        yield root
    finally:
        shutil.rmtree(root)


def test_default_verification_runs_all_offline_checks(monkeypatch):
    calls = []
    monkeypatch.setattr(verify, "run_check", lambda args: calls.append(args) or 0)
    monkeypatch.setattr(
        verify, "audit_dependencies", lambda: pytest.fail("Unexpected outbound audit")
    )
    assert verify.main([]) == 0
    assert calls == [
        ["scripts/public_check.py"],
        ["-m", "pytest", "-q"],
        ["-m", "ruff", "check", "."],
        ["-m", "bandit", "-q", "-r", "remediation", "scripts"],
    ]


@pytest.mark.parametrize("failing_check", range(4))
def test_check_failure_stops_before_further_checks_and_audit(monkeypatch, failing_check):
    calls = []

    def run(args):
        calls.append(args)
        return 7 if len(calls) == failing_check + 1 else 0

    monkeypatch.setattr(verify, "run_check", run)
    monkeypatch.setattr(verify, "audit_dependencies", lambda: pytest.fail("Audit after failure"))
    assert verify.main(["--audit-dependencies"]) == 7
    assert len(calls) == failing_check + 1


def test_pre_push_and_opt_in_audit_are_forwarded(monkeypatch):
    calls = []
    monkeypatch.setattr(verify, "run_check", lambda args: calls.append(args) or 0)
    monkeypatch.setattr(verify, "audit_dependencies", lambda: calls.append("audit") or 1)
    assert verify.main(["--pre-push", "--audit-dependencies"]) == 1
    assert calls[0] == ["scripts/public_check.py", "--pre-push"]
    assert calls[-1] == "audit"


def test_missing_tool_fails_closed(monkeypatch):
    def missing(_args):
        raise FileNotFoundError("Missing verification tool")

    monkeypatch.setattr(verify, "run_check", missing)
    assert verify.main([]) == 2


def test_subprocess_uses_current_python_without_shell_and_inherits_stdin(monkeypatch):
    def run(command, **kwargs):
        assert command == [sys.executable, "scripts/public_check.py", "--pre-push"]
        assert kwargs == {"cwd": verify.ROOT, "check": False}
        return subprocess.CompletedProcess(command, 3)

    monkeypatch.setattr(verify.subprocess, "run", run)
    assert verify.run_check(["scripts/public_check.py", "--pre-push"]) == 3


@pytest.mark.parametrize("audit_status", [0, 1])
def test_audit_uses_metadata_only_inventory_and_always_cleans_up(
    monkeypatch, audit_root, audit_status
):
    def inventory(command, **kwargs):
        assert command == [
            sys.executable,
            "scripts/public_check.py",
            "--dependency-inventory",
        ]
        assert kwargs == {
            "cwd": audit_root, "capture_output": True, "text": True, "check": False,
        }
        return subprocess.CompletedProcess(command, 0, stdout="public-package==1.2\n", stderr="")

    def audit(arguments):
        assert arguments[:3] == ["-m", "pip_audit", "--requirement"]
        path = Path(arguments[3])
        assert path.parent == audit_root / ".pytest_cache"
        assert path.read_text(encoding="utf-8") == "public-package==1.2\n"
        assert arguments[4:] == [
            "--disable-pip", "--no-deps", "--strict", "--progress-spinner", "off",
        ]
        return audit_status

    monkeypatch.setattr(verify.subprocess, "run", inventory)
    monkeypatch.setattr(verify, "run_check", audit)
    assert verify.audit_dependencies() == audit_status
    assert list((audit_root / ".pytest_cache").iterdir()) == []


@pytest.mark.parametrize(("returncode", "stdout"), [(2, ""), (0, "")])
def test_inventory_failure_or_empty_output_prevents_audit(
    monkeypatch, audit_root, returncode, stdout
):
    monkeypatch.setattr(
        verify.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess([], returncode, stdout, "blocked"),
    )
    monkeypatch.setattr(verify, "run_check", lambda args: pytest.fail("Unexpected audit"))
    assert verify.audit_dependencies() == 2
    assert not (audit_root / ".pytest_cache").exists()
