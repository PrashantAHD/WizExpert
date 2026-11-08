"""Public-safe, normalized data model and rules for weekly progress reporting.

Pure functions over already-collected, normalized rows. Nothing here calls Wiz or
ServiceNow, sends email or reads client data; private builders (kept outside this
repository) render the five weekly slots from the dataset this module produces.

Rules enforced here:
* Reporting day is a Tuesday (owner-requested rule). The window runs from the preceding
  Monday 00:00 (inclusive) to the report-week Monday 00:00 boundary. Date-only values:
  start = report day - 8 days (previous Monday, inclusive), end = report day - 1 day
  (report-week Monday, inclusive). Timestamps on the report-week Monday are also included:
  the window is [start Monday 00:00, report Tuesday 00:00), i.e. resolved_at_before
  <report day>T00:00:00Z. A resolution on the boundary Monday can appear in two consecutive reports.
* The full owner-scoped IN_PROGRESS population as of report day is always included;
  RESOLVED items are included only when resolved_at falls inside the window AND they are
  assigned to the same approved owners (Prashant, Syed, Kimrah); other owners are excluded.
  Items resolved before the window are never listed (not even as in-progress rows);
  validate_weekly_dataset fails closed on any resolved row outside the window.
* The previous weekly report is the baseline; the inventory is updated, not rebuilt.
* Items whose current Wiz status is IN_PROGRESS are included whether or not they appear
  in the previous report: those in it are 'carried'; historical IN_PROGRESS rows absent
  from it are 'new'. Both count toward counts['in_progress'].
  Counts are issue-weighted (rule-aggregated rows contribute issue_count); tables stay one
  row per rule, and counts['rows'] holds the row total.
* Items resolved inside the window stay in that report with resolution evidence, then
  drop from the next window's active list.
* Closure is never inferred from an owner message; only current Wiz status counts.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any

IN_PROGRESS = "IN_PROGRESS"
RESOLVED = "RESOLVED"
DEFAULT_OWNERS = ("Prashant", "Syed", "Kimrah")
DEPENDENCIES = ("risk-issues", "daily-progress-reporting")
SECTIONS = (  # weekly deck structure (owner-requested redesign, category version 3)
    "Cover",
    "Executive Summary",
    "In-Progress Items",
    "Thank you",
)
IN_PROGRESS_COLUMNS = (
    "Issue / title", "Severity", "SNOW ticket number", "Assigned Team", "Current Status",
    "Blockers",
)
FORBIDDEN_PHRASES = (
    "assessment basis and limitations",
    "wiz verify and track",
    "refresh wiz",
    "close wiz",
    "update wiz issue",
)
UNNAMED_RULE = "Rule name not retained in available evidence"
ITEM_STATES = ("carried", "new", "resolved", "dropped", "needs-status")


def weight(item: Mapping[str, Any]) -> int:
    """Issues an item represents: issue_count for rule-aggregated rows, else 1."""
    count = item.get("issue_count")
    if (item.get("rule_id") and isinstance(count, int)
            and not isinstance(count, bool) and count >= 0):
        return count
    return 1


def _counts(items: list[dict[str, Any]]) -> dict[str, int]:
    """Issue-weighted counts; counts['rows'] is the number of (grouped) table rows."""
    counts = {s: sum(weight(i) for i in items if i["state"] == s) for s in ITEM_STATES}
    counts["in_progress"] = counts["carried"] + counts["new"]
    counts["rows"] = len(items)
    return counts


_RULE_ID = re.compile(
    r"^(?:wc-id-\d+|[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})$"
)


_UUID = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
_NOISE = re.compile(rf"\$wiz\w*|\(\s*{_UUID}\s*\)|{_UUID}")


def clean_title(text: Any) -> str:
    """Remove only raw UUIDs and literal $wiz... template tokens (e.g. $wizassignee)."""
    return " ".join(_NOISE.sub(" ", str(text or "")).split())


def display_title(item: Mapping[str, Any]) -> str:
    """Rendered row title. Rule rows read "Rule name (K issues)", with "(wc-id-N)" after the
    name when the rule id is a wc-id; raw source UUIDs are never shown (they stay in data)."""
    if not item.get("rule_id"):
        return clean_title(item.get("title", ""))
    name = clean_title(item.get("rule_name") or item.get("title") or "")
    if not name or name.startswith("Wiz source rule"):
        name = UNNAMED_RULE
    rule_id = str(item["rule_id"])
    if rule_id.startswith("wc-id-"):
        name = f"{name} ({rule_id})"
    count = item.get("issue_count")
    noun = "issue" if count == 1 else "issues"
    return f"{name} ({count} {noun})"


class WeeklyDataError(ValueError):
    """Normalized weekly input is incomplete or breaks a weekly rule."""


@dataclass(frozen=True)
class WeeklyPeriod:
    reporting_date: date
    start: date  # preceding Monday (inclusive)
    end: date  # report-week Monday boundary (inclusive for dates and timestamps on that day)

    def label(self) -> str:
        return f"{self.start.isoformat()} to {self.end.isoformat()}"


def period_for(reporting_date: date) -> WeeklyPeriod:
    """Reporting Tuesday -> previous Monday .. report-week Monday boundary window."""
    if reporting_date.weekday() != 1:
        raise WeeklyDataError("reporting date must be a Tuesday")
    return WeeklyPeriod(
        reporting_date, reporting_date - timedelta(days=8), reporting_date - timedelta(days=1)
    )


def _day(value: Any) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _in_window(value: Any, period: WeeklyPeriod) -> str:
    """Return "in", "before" or "after" the window.

    Timestamps on the report-week Monday are included (end is Tuesday 00:00, exclusive).
    """
    text = str(value).strip()
    if len(text) > 10 and text[10] in "T ":
        stamp = datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None)
        start = datetime.combine(period.start, time.min)
        end = datetime.combine(period.end + timedelta(days=1), time.min)  # boundary Monday included
        return "before" if stamp < start else "after" if stamp >= end else "in"
    day = _day(text)
    return "before" if day < period.start else "after" if day > period.end else "in"


def _count_ok(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


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
    if _day(previous_report["period_end"]) != period.start:
        raise WeeklyDataError("previous report window must end on this window's start Monday")
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
            if not _owner_ok(row.get("owner", ""), allowed):
                continue  # out-of-scope owner (same approved owners as IN_PROGRESS)
            if _day(row.get("resolved_at")) is None or not row.get("resolution_evidence"):
                raise WeeklyDataError(f"{item_id}: resolved needs resolved_at and evidence")
            where = _in_window(row["resolved_at"], period)
            if where == "in":
                entry["state"] = "resolved"
            elif where == "before":
                entry["state"] = "dropped"
            elif prior:
                entry["state"] = "needs-status"
                entry["note"] = "Resolved after the reporting window; reported next week"
            else:
                continue  # resolved after the window and never reported
        elif prior:
            entry["state"] = "needs-status"
            entry["note"] = f"Current Wiz status {status or 'unknown'}; not closed"
        else:
            continue
        if entry.get("rule_id"):
            count = entry.get("issue_count")
            if not _RULE_ID.match(str(entry["rule_id"])) or not _count_ok(count):
                raise WeeklyDataError(
                    f"{item_id}: rule rows need a wc-id-N or UUID rule_id and issue_count >= 0")
            entry["issue_count"] = int(count)
            entry["display_title"] = display_title(entry)
        if status != RESOLVED and row.get("owner_claims_closed"):
            entry["note"] = "Owner message reports completion; not closed until Wiz status confirms"
        items.append(entry)
    return {
        "reporting_date": reporting_date.isoformat(),
        "period": {"start": period.start.isoformat(), "end": period.end.isoformat()},
        "baseline_period_end": str(previous_report["period_end"])[:10],
        "dependencies": dict(dependencies),
        "items": items,
        "counts": _counts(items),
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
            return ["reporting_date must be a Tuesday ISO date"]
        if data.get("period") != {"start": period.start.isoformat(), "end": period.end.isoformat()}:
            errs.append("period must be previous Monday to report-week Monday")
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
        if item.get("rule_id") and (
            not _RULE_ID.match(str(item["rule_id"])) or not _count_ok(item.get("issue_count"))
        ):
            errs.append(f"{iid}: rule rows need a wc-id-N or UUID rule_id and issue_count >= 0")
        if state == "resolved" and not (
            item.get("status") == RESOLVED and item.get("resolution_evidence")
        ):
            errs.append(f"{iid}: resolved item lacks current-status resolution evidence")
        if state == "resolved" and not placeholder and item.get("resolved_at"):
            try:
                where = _in_window(item["resolved_at"], period)
            except (TypeError, ValueError):
                where = "invalid"
            if where != "in":
                errs.append(f"{iid}: resolved outside the reporting period; exclude it")
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
        "reporting_date": "[reporting Tuesday]",
        "period": {"start": "[period start]", "end": "[period end]"},
        "baseline_period_end": "[previous period end]",
        "dependencies": {d: f"[{d} record]" for d in DEPENDENCIES},
        "items": items,
        "counts": _counts(items),
    }
