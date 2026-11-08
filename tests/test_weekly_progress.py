"""Synthetic tests for the weekly progress rules (no client data, no network)."""

from datetime import date

import pytest

from wizexpert.governance import weekly_progress as wp

TUESDAY = date(2026, 11, 3)
DEPS = {"risk-issues": "[ri]", "daily-progress-reporting": "[dp]"}


def row(i, status="IN_PROGRESS", owner="Syed A", **kw):
    return {"item_id": i, "title": f"[t {i}]", "severity": "[s]", "owner": owner,
            "status": status, **kw}


def prev(*items, end="2026-10-26"):
    return {"period_end": end, "items": list(items)}


def build(previous, rows, deps=DEPS):
    return wp.build_weekly_dataset(TUESDAY, previous, rows, deps)


def states(data):
    return {i["item_id"]: i["state"] for i in data["items"]}


def test_window_is_previous_monday_to_report_week_monday():
    p = wp.period_for(TUESDAY)
    assert (p.start, p.end) == (date(2026, 10, 26), date(2026, 11, 2))


@pytest.mark.parametrize("day", [date(2026, 11, 2), date(2026, 11, 4), date(2026, 11, 8)])
def test_non_tuesday_rejected(day):
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
    baseline = {"period_end": "2026-11-02", "items": data["items"]}
    nxt = wp.build_weekly_dataset(date(2026, 11, 10), baseline, [r], DEPS)
    assert states(nxt) == {"a": "dropped"}
    assert nxt["counts"]["resolved"] == 0


@pytest.mark.parametrize("stamp,state", [
    ("2026-10-26", "resolved"),
    ("2026-11-02", "resolved"),  # date-only, both ends inclusive
    ("2026-10-25", "dropped"),
    ("2026-10-26T00:00:00Z", "resolved"), ("2026-11-01T23:59:59Z", "resolved"),
    ("2026-10-25T23:59:59Z", "dropped"), ("2026-11-02T00:00:00Z", "resolved"),
    ("2026-11-02T23:59:59Z", "resolved"), ("2026-11-03T00:00:00Z", "needs-status"),
])
def test_resolved_window_boundaries(stamp, state):
    r = row("a", "RESOLVED", resolved_at=stamp, resolution_evidence="[evidence]")
    data = build(prev({"item_id": "a", "state": "carried"}), [r])
    assert states(data) == {"a": state}
    assert wp.validate_weekly_dataset(data) == []


def test_resolved_in_scope_owner_included_out_of_scope_excluded():
    ok = row("a", "RESOLVED", owner="Kimrah B", resolved_at="2026-10-30", resolution_evidence="[e]")
    other = row("b", "RESOLVED", owner="Someone Else", resolved_at="2026-10-30",
                resolution_evidence="[e]")
    # out of scope: ignored
    no_ev = row("c", "RESOLVED", owner="Someone Else", resolved_at="2026-10-30")
    data = build(prev({"item_id": "b", "state": "carried"}), [ok, other, no_ev])
    assert states(data) == {"a": "resolved"}
    with pytest.raises(wp.WeeklyDataError):  # in-scope owner still needs evidence
        build(prev(), [row("d", "RESOLVED", owner="Prashant", resolved_at="2026-10-30")])


def test_resolved_after_window_without_prior_is_excluded_not_error():
    r = row("a", "RESOLVED", resolved_at="2026-11-03T09:00:00", resolution_evidence="[e]")
    assert states(build(prev(), [r])) == {}


def test_all_in_progress_included_regardless_of_age_and_owner_scoped():
    rows = [row("old", opened_at="2025-01-01"), row("recent"), row("x", owner="Other Person")]
    data = build(prev(), rows)
    assert states(data) == {"old": "new", "recent": "new"}
    assert data["period"] == {"start": "2026-10-26", "end": "2026-11-02"}


def test_historical_in_progress_absent_from_previous_report_is_new():
    data = build(prev({"item_id": "a", "state": "carried"}),
                 [row("a"), row("hist", opened_at="2026-01-05")])
    assert states(data) == {"a": "carried", "hist": "new"}
    assert data["counts"]["in_progress"] == 2
    assert wp.validate_weekly_dataset(data) == []


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
        build(prev(end="2026-10-19"), [])


def test_validator_flags_rule_breaks():
    data = build(prev(), [row("a")])
    data["items"][0]["state"] = "resolved"
    data["dependencies"]["risk-issues"] = ""
    data["items"][0]["note"] = "Assessment basis and limitations"
    errs = wp.validate_weekly_dataset(data)
    assert len(errs) == 3


def test_validator_rejects_item_resolved_before_period():
    r = row("a", "RESOLVED", resolved_at="2026-10-30", resolution_evidence="[e]")
    data = build(prev(), [r])
    assert wp.validate_weekly_dataset(data) == []
    data["items"][0]["resolved_at"] = "2026-10-20"
    assert any("outside the reporting period" in e for e in wp.validate_weekly_dataset(data))


def test_rule_aggregated_rows_contribute_weighted_counts():
    uuid = "0b1c2d3e-4f50-6172-8394-a5b6c7d8e9f0"
    rows = [row("r1", rule_id="wc-id-1", issue_count=2700, rule_name="[n1]"),
            row("r2", rule_id=uuid, issue_count=17, rule_name="[n2]"),
            row("p1"), row("p2")]  # plain rows weigh 1
    res = [row(f"x{n}", "RESOLVED", owner="Syed", resolved_at="2026-10-30",
               resolution_evidence="[e]")
           for n in range(30)]
    data = build(prev({"item_id": "r1", "state": "carried"}), rows + res)
    c = data["counts"]
    assert (c["in_progress"], c["carried"], c["new"]) == (2719, 2700, 19)
    assert c["resolved"] == 30 and c["rows"] == 34
    assert wp.validate_weekly_dataset(data) == []


def test_rule_aggregated_row_renders_rule_id_and_count():
    r = row("wc-id-1", rule_id="wc-id-1", rule_name="[Rule name]", issue_count=1942)
    data = build(prev(), [r, row("plain")])
    rule = next(i for i in data["items"] if i["item_id"] == "wc-id-1")
    assert rule["display_title"] == "[Rule name] (wc-id-1) (1942 issues)"
    plain = next(i for i in data["items"] if i["item_id"] == "plain")
    assert "display_title" not in plain and wp.display_title(plain) == "[t plain]"
    one = {"rule_id": "wc-id-2", "rule_name": "[R]", "issue_count": 1}
    assert wp.display_title(one) == "[R] (wc-id-2) (1 issue)"
    uid = "00000000-0000-4000-8000-00000000abcd"
    for bare in ({"rule_id": uid, "rule_name": uid},
                 {"rule_id": uid, "title": f"Wiz source rule {uid}"}):
        title = wp.display_title({**bare, "issue_count": 2})
        assert title == f"{wp.UNNAMED_RULE} (2 issues)"
    assert wp.IN_PROGRESS_COLUMNS[-2:] == ("Current Status", "Blockers")
    assert wp.validate_weekly_dataset(data) == []


@pytest.mark.parametrize("bad", [{"rule_id": "x", "issue_count": 3},
                                 {"rule_id": "wc-id-1", "issue_count": -1},
                                 {"rule_id": "wc-id-1", "issue_count": "3"},
                                 {"rule_id": "wc-id-1"}])
def test_rule_row_bad_id_or_count_rejected(bad):
    with pytest.raises(wp.WeeklyDataError):
        build(prev(), [row("a", **bad)])
    data = build(prev(), [row("a")])
    data["items"][0].update(bad)
    assert wp.validate_weekly_dataset(data)


def test_uuid_rule_id_accepted_and_preserved_exactly():
    uid = "8ae9afd1-0000-4000-8000-0123456789ab"
    data = build(prev(), [row(uid, rule_id=uid, rule_name="[Rule]", issue_count=7)])
    assert data["items"][0]["display_title"] == "[Rule] (7 issues)"
    dirty = {"rule_id": uid, "rule_name": f"Admin keys ({uid}) $wizassignee", "issue_count": 4}
    assert wp.display_title(dirty) == "Admin keys (4 issues)"
    assert wp.display_title({"title": "VM $wizassignee x"}) == "VM x"
    assert wp.validate_weekly_dataset(data) == []
    with pytest.raises(wp.WeeklyDataError):
        build(prev(), [row("a", rule_id="8ae9afd1-xyz", issue_count=7)])

def test_placeholder_dataset_is_valid_and_bracketed():
    data = wp.placeholder_dataset()
    assert wp.validate_weekly_dataset(data, placeholder=True) == []
    assert wp.validate_weekly_dataset(data)  # real dates required
