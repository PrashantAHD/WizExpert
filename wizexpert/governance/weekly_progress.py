"""Public-safe, normalized data model and rules for weekly progress reporting.

Pure functions over already-collected, normalized rows. Nothing here calls Wiz or
ServiceNow, sends email or reads client data; private builders (kept outside this
repository) render the five weekly slots from the dataset this module produces.

Rules enforced here:
* Reporting day is a Monday; the covered period is the prior Monday-Sunday.
* The previous weekly report is the baseline; the inventory is updated, not rebuilt.
* Items whose current Wiz status is IN_PROGRESS carry forward.
* Items resolved inside the covered period stay in that period's report with
  resolution evidence, then drop from the next period's active list.
* Closure is never inferred from an owner message; only current Wiz status counts.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

IN_PROGRESS = "IN_PROGRESS"
RESOLVED = "RESOLVED"
DEFAULT_OWNERS = ("Prashant", "Syed", "Kimrah")
DEPENDENCIES = ("risk-issues", "daily-progress-reporting")
SECTIONS = (
    "Executive Summary",
    "Reporting Period and Baseline",
    "Active Carry-Forward Items",
    "Newly In Progress",
    "Resolved During Period",
    "Remediation Progress",
    "SNOW and Email Responses",
    "Next Steps",
)
FORBIDDEN_PHRASES = (
    "assessment basis and limitations",
    "wiz verify and track",
    "refresh wiz",
    "close wiz",
    "update wiz issue",
)
ITEM_STATES = ("carried", "new", "resolved", "dropped", "needs-status")


class WeeklyDataError(ValueError):
    """Normalized weekly input is incomplete or breaks a weekly rule."""


@dataclass(frozen=True)
class WeeklyPeriod:
    reporting_date: date
    start: date  # prior Monday
    end: date  # prior Sunday

    def label(self) -> str:
        return f"{self.start.isoformat()} to {self.end.isoformat()}"


def period_for(reporting_date: date) -> WeeklyPeriod:
    """Reporting Monday -> prior Monday-Sunday period."""
    if reporting_date.weekday() != 0:
        raise WeeklyDataError("reporting date must be a Monday")
    return WeeklyPeriod(
        reporting_date, reporting_date - timedelta(days=7), reporting_date - timedelta(days=1)
    )


def _day(value: Any) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _owner_ok(owner: str, allowed: Iterable[str]) -> bool:
    first = str(owner).strip().split(" ")[0].casefold()
    return first in {a.casefold() for a in allowed}


def build_weekly_dataset(
    reporting_date: date,
    previous_report: Mapping[str, Any],
    current_status: Iterable[Mapping[str, Any]],
    dependencies: Mapping[str, str],
    allowed_owners: Iterable[str] = DEFAULT_OWNERS,
) -> dict[str, Any]:
    """Combine the previous report baseline with current read-only status rows.

    previous_report: {"period_end": iso, "items": [{"item_id", "state", ...}]}; the
        baseline inventory (active items and prior-period resolved items).
    current_status: rows {"item_id","title","severity","owner","status",
        "resolved_at"?,"resolution_evidence"?,"snow_status"?,"response"?,
        "owner_claims_closed"?} from current Wiz status plus reused local records.
    dependencies: {"risk-issues": ref, "daily-progress-reporting": ref}; both required.
    """
    period = period_for(reporting_date)
    missing = [d for d in DEPENDENCIES if not dependencies.get(d)]
    if missing:
        raise WeeklyDataError(f"missing dependency records: {', '.join(missing)}")
    if "items" not in previous_report or not previous_report.get("period_end"):
        raise WeeklyDataError("previous weekly report baseline is required")
    if _day(previous_report["period_end"]) != period.start - timedelta(days=1):
        raise WeeklyDataError("previous report must cover the Monday-Sunday period before this one")
    rows = {str(r["item_id"]): dict(r) for r in current_status}
    baseline = {str(i["item_id"]): dict(i) for i in previous_report["items"]}
    allowed = tuple(allowed_owners)
    items: list[dict[str, Any]] = []
    for item_id in sorted(set(rows) | set(baseline)):
        row, prior = rows.get(item_id), baseline.get(item_id)
        if row is None:
            if prior and prior.get("state") in ("resolved", "dropped"):
                continue  # historical only; the prior report keeps the record unchanged
            items.append({
                **(prior or {}), "state": "needs-status",
                "note": "No current Wiz status supplied; remains active until confirmed",
            })
            continue
        status = str(row.get("status", "")).upper()
        entry = {**(prior or {}), **row, "status": status}
        if status == IN_PROGRESS:
            if not _owner_ok(row.get("owner", ""), allowed):
                continue  # out-of-scope owner
            entry["state"] = "carried" if prior else "new"
        elif status == RESOLVED:
            resolved = _day(row.get("resolved_at"))
            if resolved is None or not row.get("resolution_evidence"):
                raise WeeklyDataError(f"{item_id}: resolved needs resolved_at and evidence")
            if period.start <= resolved <= period.end:
                entry["state"] = "resolved"
            elif resolved < period.start:
                entry["state"] = "dropped"
            else:
                raise WeeklyDataError(f"{item_id}: resolution date after the covered period")
        elif prior:
            entry["state"] = "needs-status"
            entry["note"] = f"Current Wiz status {status or 'unknown'}; not closed"
        else:
            continue
        if status != RESOLVED and row.get("owner_claims_closed"):
            entry["note"] = "Owner message reports completion; not closed until Wiz status confirms"
        items.append(entry)
    return {
        "reporting_date": reporting_date.isoformat(),
        "period": {"start": period.start.isoformat(), "end": period.end.isoformat()},
        "baseline_period_end": str(previous_report["period_end"])[:10],
        "dependencies": dict(dependencies),
        "items": items,
        "counts": {s: sum(1 for i in items if i["state"] == s) for s in ITEM_STATES},
    }


def validate_weekly_dataset(data: Mapping[str, Any], *, placeholder: bool = False) -> list[str]:
    """Return problems; empty means the dataset obeys the weekly rules.

    placeholder=True accepts the bracketed synthetic template dataset (dates unchecked).
    """
    errs: list[str] = []
    if not placeholder:
        try:
            period = period_for(date.fromisoformat(data["reporting_date"]))
        except (KeyError, TypeError, ValueError):
            return ["reporting_date must be a Monday ISO date"]
        if data.get("period") != {"start": period.start.isoformat(), "end": period.end.isoformat()}:
            errs.append("period must be the prior Monday-Sunday")
    if not data.get("baseline_period_end"):
        errs.append("previous report baseline missing")
    for dep in DEPENDENCIES:
        if not (data.get("dependencies") or {}).get(dep):
            errs.append(f"dependency record missing: {dep}")
    for item in data.get("items", []):
        iid = item.get("item_id", "?")
        state = item.get("state")
        if state not in ITEM_STATES:
            errs.append(f"{iid}: unknown state")
        if state in ("carried", "new") and item.get("status") != IN_PROGRESS:
            errs.append(f"{iid}: carried/new items must be IN_PROGRESS in current Wiz status")
        if state == "resolved" and not (
            item.get("status") == RESOLVED and item.get("resolution_evidence")
        ):
            errs.append(f"{iid}: resolved item lacks current-status resolution evidence")
    text = repr(data).casefold()
    errs += [f"forbidden text: {p}" for p in FORBIDDEN_PHRASES if p in text]
    return errs


def placeholder_dataset() -> dict[str, Any]:
    """Synthetic bracketed values only; used by structural templates and tests."""

    def item(n: int, state: str, status: str) -> dict[str, Any]:
        return {
            "item_id": f"[item {n} id]", "title": f"[item {n} title]", "severity": "[severity]",
            "owner": "[owner]", "status": status, "state": state, "snow_status": "Pending",
            "response": f"[item {n} response]",
            "resolution_evidence": "[resolution evidence]" if state == "resolved" else "",
        }

    items = [
        item(1, "carried", IN_PROGRESS),
        item(2, "new", IN_PROGRESS),
        item(3, "resolved", RESOLVED),
    ]
    return {
        "reporting_date": "[reporting Monday]",
        "period": {"start": "[period start]", "end": "[period end]"},
        "baseline_period_end": "[previous period end]",
        "dependencies": {d: f"[{d} record]" for d in DEPENDENCIES},
        "items": items,
        "counts": {s: sum(1 for i in items if i["state"] == s) for s in ITEM_STATES},
    }
