"""Run the local publication gate without relying on PowerShell policies."""

from __future__ import annotations

import argparse
import subprocess  # nosec B404
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def run_check(arguments: list[str]) -> int:
    # Arguments are fixed tool names and local paths, never shell commands.
    result = subprocess.run(  # nosec B603
        [sys.executable, *arguments], cwd=ROOT, check=False
    )
    if result.returncode:
        print(f"Verification failed: {' '.join(arguments)}", file=sys.stderr)
    return result.returncode


def audit_dependencies() -> int:
    print(
        "Opt-in audit: sends installed dependency names/versions, NOT source or client files.",
        flush=True,
    )
    inventory = subprocess.run(  # nosec B603
        [sys.executable, "scripts/public_check.py", "--dependency-inventory"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if inventory.returncode:
        print(inventory.stderr, file=sys.stderr)
        return inventory.returncode
    if not inventory.stdout.strip():
        print("Empty dependency inventory; audit blocked.", file=sys.stderr)
        return 2
    cache = ROOT / ".pytest_cache"
    cache.mkdir(exist_ok=True)
    requirements = cache / f"audit-{uuid.uuid4().hex}.txt"
    try:
        requirements.write_text(inventory.stdout, encoding="utf-8")
        return run_check(
            [
                "-m",
                "pip_audit",
                "--requirement",
                str(requirements),
                "--disable-pip",
                "--no-deps",
                "--strict",
                "--progress-spinner",
                "off",
            ]
        )
    finally:
        requirements.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit-dependencies", action="store_true")
    parser.add_argument(
        "--pre-push", action="store_true", help="Read Git update records from stdin"
    )
    args = parser.parse_args(argv)
    guard = ["scripts/public_check.py"]
    if args.pre_push:
        guard.append("--pre-push")
    checks = [
        guard,
        ["-m", "pytest", "-q"],
        ["-m", "ruff", "check", "."],
        ["-m", "bandit", "-q", "-r", "remediation", "scripts"],
    ]
    try:
        for arguments in checks:
            status = run_check(arguments)
            if status:
                return status
        if args.audit_dependencies:
            status = audit_dependencies()
            if status:
                return status
    except (OSError, UnicodeError) as error:
        print(f"Verification could not complete: {error}", file=sys.stderr)
        return 2
    print("Verification passed. No commit or push was performed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
