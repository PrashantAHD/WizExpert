import unittest
from datetime import datetime

from wizexpert.governance.dashboard_data import DashboardError
from wizexpert.governance.governance import RISK_BOX_TITLE, risk_box
from wizexpert.governance.governance_data import (
    open_top_rules,
    validate_open_top_rules,
)

CUTOFF = datetime(2026, 11, 15, 23, 59, 59)


def row(issue, severity, status, title):
    return {
        "Issue ID": issue,
        "Severity": severity,
        "Status": status,
        "Title": title,
        "Created At": "2026-01-01T00:00:00Z",
        "Resolved Time": "",
        "Status Changed At": "2026-02-01T00:00:00Z",
    }


def rule(severity, title, open_=0, progress=0):
    return {
        "severity": severity,
        "title": title,
        "status_counts": {"OPEN": open_, "IN_PROGRESS": progress},
        "count": open_ + progress,
    }


class RiskBoxTests(unittest.TestCase):
    def test_payload_field_from_rows_reconciles(self):
        rows = [
            row("1", "CRITICAL", "IN_PROGRESS", "Synthetic critical A"),
            row("2", "HIGH", "OPEN", "Synthetic high B"),
            row("3", "HIGH", "OPEN", "Synthetic high B"),
            row("4", "HIGH", "OPEN", "Synthetic high A"),
            row("5", "MEDIUM", "OPEN", "Synthetic medium"),
            row("6", "HIGH", "RESOLVED", "Synthetic closed"),
        ]
        rows[5]["Resolved Time"] = "2026-03-01T00:00:00Z"
        rules = open_top_rules(rows, CUTOFF)
        self.assertEqual(
            [(r["severity"], r["title"], r["count"]) for r in rules],
            [
                ("CRITICAL", "Synthetic critical A", 1),
                ("HIGH", "Synthetic high B", 2),
                ("HIGH", "Synthetic high A", 1),
            ],
        )
        payload = {
            "open_top_rules": rules,
            "open": {"CRITICAL": 1, "HIGH": 3},
            "in_progress": {"CRITICAL": 1, "HIGH": 0},
        }
        validate_open_top_rules(payload)
        payload["open"]["HIGH"] = 4
        with self.assertRaisesRegex(DashboardError, "HIGH sum 3 != open HIGH 4"):
            validate_open_top_rules(payload)

    def test_box_text_levels_and_caps(self):
        rules = [
            rule("CRITICAL", "Crit one", progress=1),
            rule("CRITICAL", "Crit two", progress=1),
            rule("HIGH", "High a", open_=12),
            rule("HIGH", "High b", open_=9),
            rule("HIGH", "High c", open_=1),
            rule("HIGH", "High d", open_=1),
            rule("HIGH", "High e", open_=1),
        ]
        lines = risk_box({"open_top_rules": rules})
        self.assertEqual(lines[0], (RISK_BOX_TITLE, 0))
        self.assertEqual(lines[1], ("2 Critical findings across 2 rules, both in progress:", 1))
        self.assertEqual(lines[2], ("Crit one (1)", 2))
        self.assertEqual(lines[4], ("24 High findings across 5 rules:", 1))
        self.assertEqual(lines[5], ("High a (12)", 2))
        self.assertEqual(lines[-1], ("+2 more rules (2 findings)", 2))

    def test_single_and_mixed_wording_and_zero(self):
        lines = risk_box({"open_top_rules": [rule("CRITICAL", "Solo", progress=1)]})
        self.assertEqual(lines[1][0], "1 Critical finding on 1 rule, in progress:")
        lines = risk_box({"open_top_rules": [rule("HIGH", "Mix", open_=2, progress=1)]})
        self.assertEqual(lines[1][0], "3 High findings on 1 rule, 1 in progress, 2 open:")
        self.assertEqual(lines[2][0], "Mix (3, 1 in progress)")
        self.assertEqual(
            risk_box({"open_top_rules": []})[1],
            ("No open Critical or High findings at the cutoff.", 1),
        )

    def test_missing_field_fails_closed(self):
        with self.assertRaisesRegex(DashboardError, "open_top_rules"):
            risk_box({})
