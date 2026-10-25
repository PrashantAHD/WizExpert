import unittest

from wizexpert.governance.resolution_evidence import (
    change_keys,
    changed_text,
    describe,
    noun,
    risk_text,
    summarize,
)


def issue(status, reason, changes=None, risks=("UNPROTECTED_PRINCIPAL",)):
    return {
        "status": status,
        "resolutionReason": reason,
        "risks": list(risks),
        "resolutionEvidence": {"emptyReason": None, "changes": changes},
    }


class ResolutionEvidenceTests(unittest.TestCase):
    def test_change_keys_use_types_and_skip_bookkeeping(self):
        keys = change_keys(
            {
                "deletedResources": [
                    {"type": "SERVICE_ACCOUNT", "name": "secret-name"},
                    {"type": "SECRET_DATA"},
                ],
                "modifiedResources": [
                    {
                        "entity": {"type": "SERVICE_ACCOUNT", "name": "x"},
                        "modifiedProperties": [
                            {
                                "propertyKey": "hasHighPrivileges",
                                "oldValue": True,
                                "newValue": False,
                            }
                        ],
                    }
                ],
                "deletedRelationships": [
                    {"from": {"type": "IAM_BINDING"}, "to": {"type": "SERVICE_ACCOUNT"}}
                ],
            }
        )
        self.assertEqual(
            keys,
            {
                ("deleted", "SERVICE_ACCOUNT"): 1,
                ("modified", "SERVICE_ACCOUNT", "hasHighPrivileges", False): 1,
            },
        )
        self.assertEqual(
            change_keys(
                {
                    "deletedRelationships": [
                        {"from": {"type": "IAM_BINDING"}, "to": {"type": "USER_ACCOUNT"}}
                    ]
                }
            ),
            {("unlinked", "IAM_BINDING"): 1},
        )

    def test_descriptions_say_what_changed(self):
        self.assertEqual(
            describe(("deleted", "IAM_BINDING"), 7), "7 IAM role bindings removed (access revoked)"
        )
        self.assertEqual(
            describe(("modified", "SERVICE_ACCOUNT", "hasHighPrivileges", False), 6),
            "high privileges removed from 6 service accounts",
        )
        self.assertEqual(
            describe(("modified", "ACCESS_KEY", "active", False), 1), "1 access key deactivated"
        )
        self.assertEqual(describe(("deleted", "WIDGET_POLICY"), 2), "2 widget policies removed")
        self.assertEqual(
            describe(("modified", "BUCKET", "isPublic", "private"), 1),
            "1 bucket is public set to private",
        )
        self.assertEqual(noun("IAM_BINDING", 2), "IAM bindings")
        self.assertEqual(
            change_keys({"deletedResources": [{"type": "SUBSCRIPTION"}, {"type": "SUBSCRIPTION"}]}),
            {("deleted", "SUBSCRIPTION"): 1},
        )

    def test_closure_and_risk_text_for_mixed_resolved_and_accepted(self):
        deleted = {"deletedResources": [{"type": "SERVICE_ACCOUNT"}, {"type": "IAM_BINDING"}]}
        summary = summarize(
            [
                issue("RESOLVED", "OBJECT_DELETED", deleted),
                issue("RESOLVED", "ISSUE_FIXED", deleted),
                issue(
                    "REJECTED", "WONT_FIX", deleted, ("UNPROTECTED_PRINCIPAL", "UNPROTECTED_DATA")
                ),
            ],
            "2026-10-14T05:09:18Z",
        )
        self.assertEqual(summary["reasons"], {"ISSUE_FIXED": 1, "OBJECT_DELETED": 1, "WONT_FIX": 1})
        self.assertEqual(
            changed_text(summary, 2),
            "Service accounts removed. IAM role bindings removed (access revoked).",
        )
        self.assertEqual(
            risk_text(summary, 2, 1), "Reduced unprotected identity, sensitive data exposure risk."
        )
        summary["changes"] = [
            {"text": "high privileges removed from 6 service accounts", "count": 6}
        ]
        self.assertEqual(changed_text(summary, 6), "High privileges removed from service accounts.")

    def test_accepted_only_and_missing_change_detail(self):
        summary = summarize([issue("REJECTED", "EXCEPTION")], "2026-10-14T05:09:18Z")
        self.assertEqual(changed_text(summary, 0), "Risk reviewed and accepted by the team.")
        self.assertEqual(risk_text(summary, 0, 1), "Accepted risk documented in Wiz.")
        summary = summarize([issue("RESOLVED", "ISSUE_FIXED")], "2026-10-14T05:09:18Z")
        self.assertEqual(changed_text(summary, 1), "Change detail not recorded by Wiz.")


if __name__ == "__main__":
    unittest.main()
