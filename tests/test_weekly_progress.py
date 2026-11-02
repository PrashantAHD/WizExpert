"""Synthetic tests for the weekly progress rules (no client data, no network)."""

from datetime import date

import pytest

from wizexpert.governance import weekly_progress as wp

MONDAY = date(2026, 11, 2)
DEPS = {"risk-issues": "[ri]", "daily-progress-reporting": "[dp]"}


def row(i, status="IN_PROGRESS", owner="Syed A", **kw):
    return {"item_id": i, "title": f"[t {i}]", "severity": "[s]", "owner": owner,
            "status": status, **kw}


def prev(*items, end="2026-10-25"):
    return {"period_end": end, "items": list(items)}


def build(previous, rows, deps=DEPS):
    return wp.build_weekly_dataset(MONDAY, previous, rows, deps)


def states(data):
    return {i["item_id"]: i["state"] for i in data["items"]}


def test_period_is_prior_monday_to_sunday():
    p = wp.period_for(MONDAY)
    assert (p.start, p.end) == (date(2026, 10, 26), date(2026, 11, 1))


@pytest.mark.parametrize("day", [date(2026, 11, 3), date(2026, 11, 1), date(2026, 11, 8)])
def test_non_monday_rejected(day):
    with pytest.raises(wp.WeeklyDataError):
        wp.period_for(day)


def test_carry_forward_and_new():
    data = build(prev({"item_id": "a", "state": "carried"}), [row("a"), row("b")])
    assert states(data) == {"a": "carried", "b": "new"}
    assert wp.validate_weekly_dataset(data) == []


def test_owner_scope_filters_others():
    assert states(build(prev(), [row("a", owner="Someone Else")])) == {}


def test_resolved_in_period_stays_then_drops_next_period():
    r = row("a", "RESOLVED", resolved_at="2026-10-30", resolution_evidence="[evidence]")
    data = build(prev({"item_id": "a", "state": "carried"}), [r])
    assert states(data) == {"a": "resolved"}
    baseline = {"period_end": "2026-11-01", "items": data["items"]}
    nxt = wp.build_weekly_dataset(date(2026, 11, 9), baseline, [r], DEPS)
    assert states(nxt) == {"a": "dropped"}
    assert nxt["counts"]["resolved"] == 0


def test_prior_resolved_not_in_current_rows_is_historical_only():
    data = build(prev({"item_id": "a", "state": "resolved"}), [])
    assert data["items"] == []


def test_resolved_requires_evidence():
    with pytest.raises(wp.WeeklyDataError):
        build(prev(), [row("a", "RESOLVED", resolved_at="2026-10-30")])


def test_owner_message_never_closes():
    data = build(prev({"item_id": "a", "state": "carried"}), [row("a", owner_claims_closed=True)])
    assert states(data) == {"a": "carried"}
    assert "not closed" in data["items"][0]["note"]


def test_missing_current_status_needs_status_not_closed():
    data = build(prev({"item_id": "a", "state": "carried"}), [])
    assert states(data) == {"a": "needs-status"}


def test_non_in_progress_status_is_not_closed():
    data = build(prev({"item_id": "a", "state": "carried"}), [row("a", "OPEN")])
    assert states(data) == {"a": "needs-status"}


def test_dependencies_and_baseline_required():
    with pytest.raises(wp.WeeklyDataError):
        build(prev(), [], {"risk-issues": "[ri]"})
    with pytest.raises(wp.WeeklyDataError):
        build({"items": []}, [])
    with pytest.raises(wp.WeeklyDataError):
        build(prev(end="2026-10-18"), [])


def test_validator_flags_rule_breaks():
    data = build(prev(), [row("a")])
    data["items"][0]["state"] = "resolved"
    data["dependencies"]["risk-issues"] = ""
    data["items"][0]["note"] = "Assessment basis and limitations"
    errs = wp.validate_weekly_dataset(data)
    assert len(errs) == 3


def test_placeholder_dataset_is_valid_and_bracketed():
    data = wp.placeholder_dataset()
    assert wp.validate_weekly_dataset(data, placeholder=True) == []
    assert wp.validate_weekly_dataset(data)  # real dates required
