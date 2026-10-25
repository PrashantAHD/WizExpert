import tempfile
import unittest
from pathlib import Path

from synthetic import mail

from wizexpert.governance.assignment_history import (
    action_lines,
    best_owner,
    find_gaps,
    suggest_owner,
    team_index,
    write_actions_csv,
)

TEAM = team_index(
    [
        {"id": "u-blair", "name": "Blair", "logins": [mail("user-b", "example")]},
        {"id": "u-casey", "name": "Casey", "logins": [mail("user-c", "example")]},
    ]
)


def event(kind, at, actor=None, status=None):
    return {"type": kind, "at": at, "actor": actor, "new_status": status}


class AssignmentHistoryTests(unittest.TestCase):
    def test_latest_team_work_event_wins_and_system_events_are_ignored(self):
        events = [
            event("ISSUE_CREATED", "2026-01-01T00:00:00Z", status="OPEN"),
            event(
                "ISSUE_IN_PROGRESS",
                "2026-06-09T15:41:55Z",
                mail("USER-B", "Example"),
                "IN_PROGRESS",
            ),
            event(
                "ISSUE_IN_PROGRESS",
                "2026-06-10T10:00:00Z",
                mail("user-c", "example"),
                "IN_PROGRESS",
            ),
            event("NOTE_CREATED", "2026-06-11T10:00:00Z", mail("user-b", "example")),
            event("ISSUE_RESOLVED_AUTOMATICALLY", "2026-09-20T00:00:00Z", status="RESOLVED"),
        ]
        owner = suggest_owner(events, TEAM)
        self.assertEqual(
            (owner["name"], owner["id"], owner["at"]), ("Casey", "u-casey", "2026-06-10T10:00:00Z")
        )
        self.assertIn("ISSUE_IN_PROGRESS by " + mail("user-c") + "", owner["basis"])
        self.assertIsNone(
            suggest_owner(
                [
                    event(
                        "ISSUE_IN_PROGRESS",
                        "2026-06-09T00:00:00Z",
                        mail("someone", "else"),
                        "IN_PROGRESS",
                    )
                ],
                TEAM,
            )
        )

    def test_best_owner_prefers_assignment_then_status_then_work(self):
        def added(login, at):
            return {
                "type": "ASSIGNEE_ADDED",
                "at": at,
                "actor": login,
                "new_assignee": login,
            }

        def removed(login, at):
            return {
                "type": "ASSIGNEE_REMOVED",
                "at": at,
                "actor": login,
                "old_assignee": login,
            }

        events = [
            added(mail("user-c", "example"), "2026-01-01"),
            removed(mail("user-c", "example"), "2026-01-02"),
            added(mail("user-b", "example"), "2026-01-03"),
            event("ISSUE_IN_PROGRESS", "2026-01-04", mail("user-c", "example"), "IN_PROGRESS"),
        ]
        self.assertEqual(best_owner(events, TEAM)["name"], "Blair")
        self.assertIsNone(
            best_owner(
                [
                    added(mail("user-c", "example"), "2026-01-01"),
                    removed(mail("user-c", "example"), "2026-01-02"),
                ],
                TEAM,
            )
        )
        self.assertEqual(
            best_owner(
                [
                    event("SERVICE_TICKET_ADDED_MANUALLY", "2026-01-01", mail("user-c", "example")),
                    event("NOTE_CREATED", "2026-01-02", mail("someone", "else")),
                ],
                TEAM,
            )["name"],
            "Casey",
        )
        self.assertIsNone(
            best_owner(
                [
                    event(
                        "AI_REMEDIATION_RECOMMENDATION_GENERATED",
                        "2026-01-01",
                        mail("user-b", "example"),
                    )
                ],
                TEAM,
            )
        )

    def test_gaps_cover_unassigned_in_progress_and_team_worked_closures_only(self):
        issues = [
            {
                "issue_id": "a",
                "rule_id": "r1",
                "rule_name": "Rule 1",
                "status": "IN_PROGRESS",
                "assignee_id": None,
            },
            {
                "issue_id": "b",
                "rule_id": "r1",
                "rule_name": "Rule 1",
                "status": "IN_PROGRESS",
                "assignee_id": "u-blair",
            },
            {
                "issue_id": "c",
                "rule_id": "r2",
                "rule_name": "Rule 2",
                "status": "RESOLVED",
                "assignee_id": None,
            },
            {
                "issue_id": "d",
                "rule_id": "r2",
                "rule_name": "Rule 2",
                "status": "RESOLVED",
                "assignee_id": None,
            },
            {
                "issue_id": "e",
                "rule_id": "r3",
                "rule_name": "Rule 3",
                "status": "IN_PROGRESS",
                "assignee_id": None,
            },
        ]
        history = {
            "a": [
                event(
                    "ISSUE_IN_PROGRESS",
                    "2026-06-09T00:00:00Z",
                    mail("user-b", "example"),
                    "IN_PROGRESS",
                )
            ],
            "c": [
                event(
                    "ISSUE_IN_PROGRESS",
                    "2026-06-09T00:00:00Z",
                    mail("user-b", "example"),
                    "IN_PROGRESS",
                ),
                event("ISSUE_RESOLVED_AUTOMATICALLY", "2026-09-20T00:00:00Z", status="RESOLVED"),
            ],
            "d": [event("ISSUE_RESOLVED_AUTOMATICALLY", "2026-09-20T00:00:00Z", status="RESOLVED")],
        }
        gaps = find_gaps(issues, history, TEAM)
        self.assertEqual(
            [(g["issue_id"], g["suggested_owner"]) for g in gaps],
            [("a", "Blair"), ("e", None), ("c", "Blair")],
        )
        self.assertIn("confirm the owner", gaps[1]["basis"])
        self.assertTrue(action_lines(gaps)[0].startswith("Assign Blair to a [IN_PROGRESS] Rule 1"))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "actions.csv"
            write_actions_csv(gaps, path)
            lines = path.read_text(encoding="utf-8").splitlines()
        self.assertEqual(
            lines[0],
            "issue_id,rule_id,rule_name,status,suggested_owner,suggested_owner_id,basis,event_at",
        )
        self.assertEqual(len(lines), 4)


if __name__ == "__main__":
    unittest.main()
