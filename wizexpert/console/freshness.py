"""Freshness gate for the Daily Progress Reporting Refresh (PHP2Shell campaign).

The console has no Wiz credentials: a Refresh is an agent chat that runs the campaign skill
(Wiz MCP calls, collect_refresh.py, update_dashboard.py). The chat ending is NOT proof the work
happened, so the run only counts as completed when this gate finds outputs newer than the click.
Only file names and modification times are read; no evidence content is opened.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

from . import imports
from .config import ConsoleConfig

CAMPAIGN_FOLDER = "PHP2Shell-Campaign"
RECONNECT_MESSAGE = "Reconnect Wiz MCP in VS Code; verify access with a read-only catalog call."
SLACK = 2.0  # seconds of filesystem timestamp tolerance


def is_php2shell(work_item: str) -> bool:
    return "php2shell" in re.sub(r"[^a-z0-9]", "", (work_item or "").lower())


def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def missing_outputs(config: ConsoleConfig, since: float, now: datetime | None = None) -> list[str]:
    """Names of required outputs that are absent or older than ``since`` (epoch seconds)."""
    now = now or datetime.now(UTC)
    base = imports._base(config, imports.DAILY_DIR)
    folder = base / CAMPAIGN_FOLDER if base is not None else None
    if folder is None or not folder.is_dir():
        return ["campaign folder"]
    floor = since - SLACK
    utc_day = now.astimezone(UTC).strftime("%Y-%m-%d")
    days = {utc_day, now.astimezone().strftime("%Y-%m-%d")}
    missing: list[str] = []

    def newest(sub: str) -> list[Path]:
        d = folder / sub
        if not d.is_dir():
            return []
        return [p for p in d.glob(f"{utc_day}T*.json") if _mtime(p) >= floor]

    snaps = {p.name for p in newest("snapshots")}
    invs = {p.name for p in newest("inventories")}
    if not snaps:
        missing.append(f"Wiz snapshot for {utc_day} (UTC)")
    if not (snaps & invs):
        missing.append(f"matching inventory for {utc_day} (UTC)")
    fixed = [
        "report-validation.json",
        "PHP2Shell-Daily-Progress-Report.pdf",
        "PHP2Shell-Day-over-Day-Movements.pdf",
        "PHP2Shell-VM-and-CVE-Details.xlsx",
    ]
    for name in fixed:
        if _mtime(folder / name) < floor:
            missing.append(name)
    for label, pattern in (
        ("Inactive-Assets-Findings workbook", "Inactive-Assets-Findings-{d}.xlsx"),
        ("Stakeholder reply draft", "PHP2Shell-Stakeholder-Reply-{d}.html"),
    ):
        if not any(_mtime(folder / pattern.format(d=d)) >= floor for d in days):
            missing.append(label)
    return missing


def gate(
    config: ConsoleConfig, since: float, *, auth_failed: bool = False
) -> tuple[bool, str]:
    """(fresh, reason). ``reason`` is the exact owner-facing explanation when not fresh."""
    missing = missing_outputs(config, since)
    if not missing:
        return True, ""
    collection_missing = any(
        name == "campaign folder" or name.startswith(("Wiz snapshot", "matching inventory"))
        for name in missing
    )
    if not collection_missing:
        reason = (
            "Local generation incomplete. Reuse the reconciled snapshot and matching inventory "
            "to repair outputs; do not automatically recollect Wiz data."
        )
    elif auth_failed:
        reason = RECONNECT_MESSAGE + " A failed Wiz call reported an authentication error."
    else:
        reason = "Refresh did not produce fresh outputs."
    return False, reason + " Missing or stale: " + "; ".join(missing)
