"""Find Wiz issues missing an assignee and suggest the team member shown in issue history.

Wiz issue history (Issue > History, GraphQL ``issueHistoryEvents``) records who set an
issue In Progress or resolved it. When the assignee field is empty, that actor is the
best available owner. Gaps are reported so the team can correct the assignee in Wiz;
the next capture then reads the real assignee.
"""

from __future__ import annotations

import csv
from pathlib import Path

WORK_STATUSES = {"IN_PROGRESS", "RESOLVED", "REJECTED"}
WORK_EVENTS = {
    "SERVICE_TICKET_ADDED_MANUALLY",
    "MANUAL_INTEGRATION_ACTION_RAN_SUCCESS",
    "NOTE_CREATED",
}
GAP_FIELDS = (
    "issue_id",
    "rule_id",
    "rule_name",
    "status",
    "suggested_owner",
    "suggested_owner_id",
    "basis",
    "event_at",
)


def team_index(team: list[dict]) -> dict[str, dict]:
    """Map lower-case Wiz logins (their sign-in addresses) to team members."""
    index = {}
    for member in team:
        for login in member["logins"]:
            index[login.strip().lower()] = {"id": member["id"], "name": member["name"]}
    return index


def suggest_owner(events: list[dict], team: dict[str, dict]) -> dict | None:
    """Return the team member who most recently moved the issue to IN_PROGRESS, RESOLVED or REJECTED
    (accepted risk / ignored).

    ``events`` items: ``{"type", "at", "actor", "new_status"}`` where ``actor`` is the
    triggering user's login or ``None`` for Wiz system events.
    """
    best = None
    for event in sorted(events, key=lambda e: e["at"]):
        member = team.get((event.get("actor") or "").strip().lower())
        if member and event.get("new_status") in WORK_STATUSES:
            best = {**member, "basis": f"{event['type']} by {event['actor']}", "at": event["at"]}
    return best


def best_owner(events: list[dict], team: dict[str, dict]) -> dict | None:
    """Strongest team-ownership signal in issue history, in priority order:

    1. the team member the issue was last assigned to (and not later unassigned),
    2. the team member who last moved it to IN_PROGRESS, RESOLVED or REJECTED,
    3. the team member who last raised a ticket, added a note or ran an integration action.

    Events may also carry ``old_assignee`` / ``new_assignee`` logins for assignment changes.
    Viewing an AI remediation suggestion alone is not treated as work.
    """
    ordered = sorted(events, key=lambda e: e["at"])
    assigned = None
    for event in ordered:
        if event.get("type") == "ASSIGNEE_ADDED" or event.get("new_assignee"):
            member = team.get((event.get("new_assignee") or "").strip().lower())
            assigned = (
                {
                    **member,
                    "basis": f"assigned to {event['new_assignee']} in Wiz history",
                    "at": event["at"],
                }
                if member
                else None
            )
        elif event.get("type") == "ASSIGNEE_REMOVED":
            assigned = None
    if assigned:
        return assigned
    owner = suggest_owner(ordered, team)
    if owner:
        return owner
    for event in reversed(ordered):
        member = team.get((event.get("actor") or "").strip().lower())
        if member and event.get("type") in WORK_EVENTS:
            return {**member, "basis": f"{event['type']} by {event['actor']}", "at": event["at"]}
    return None


def find_gaps(
    issues: list[dict], history: dict[str, list[dict]], team: dict[str, dict]
) -> list[dict]:
    """Issues without a Wiz assignee that the team should assign.

    IN_PROGRESS issues are always listed (owner suggested when history shows one).
    RESOLVED and REJECTED (accepted risk) issues are listed only when history shows team
    work; automatic closures with no team activity are not team work and need no action.
    """
    gaps = []
    for issue in issues:
        if issue.get("assignee_id"):
            continue
        owner = best_owner(history.get(issue["issue_id"], []), team)
        if owner is None and issue["status"] != "IN_PROGRESS":
            continue
        gaps.append(
            {
                "issue_id": issue["issue_id"],
                "rule_id": issue["rule_id"],
                "rule_name": issue["rule_name"],
                "status": issue["status"],
                "suggested_owner": owner["name"] if owner else None,
                "suggested_owner_id": owner["id"] if owner else None,
                "basis": owner["basis"]
                if owner
                else "No team activity in Wiz history; confirm the owner.",
                "event_at": owner["at"] if owner else None,
            }
        )
    return sorted(
        gaps,
        key=lambda g: (g["status"], g["suggested_owner"] or "~", g["rule_name"], g["issue_id"]),
    )


def write_actions_csv(gaps: list[dict], path: Path) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=GAP_FIELDS)
        writer.writeheader()
        writer.writerows({key: gap.get(key) or "" for key in GAP_FIELDS} for gap in gaps)


def action_lines(gaps: list[dict]) -> list[str]:
    return [
        f"Assign {gap['suggested_owner'] or 'an owner'} to {gap['issue_id']} [{gap['status']}] "
        f"{gap['rule_name']} - {gap['basis']}"
        for gap in gaps
    ]
