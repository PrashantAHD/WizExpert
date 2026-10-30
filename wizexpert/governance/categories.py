"""Public-safe, placeholder-only category definitions for repeatable work types.

A category fixes the deliverable slots, required gates and drift rules of a work
type. It contains no client names, evidence, identifiers or counts. Private
templates live in private storage and are bound to a slot by a pinned hash.
Nothing here calls Wiz, sends email or changes any system.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

SCHEMA_VERSION = 1

COMMON_RULES = (
    "Build every deliverable from the category template bound to its slot.",
    "Never recreate or reintroduce legacy bespoke generation logic.",
    "Change a template or rule only through a recorded, owner-requested "
    "modification, then bump the category version and re-pin template hashes.",
    "Wiz and cloud access stay read-only; never send email or mutate records.",
    "Keep client names, evidence and identifiers in private storage only.",
)


@dataclass(frozen=True)
class Slot:
    slot_id: str
    title: str
    kind: str


@dataclass(frozen=True)
class Category:
    category_id: str
    version: int
    title: str
    slots: tuple[Slot, ...]
    gates: tuple[str, ...]
    category_rules: tuple[str, ...] = ()

    def manifest(self) -> dict[str, Any]:
        extra = {"category_rules": list(self.category_rules)} if self.category_rules else {}
        return {
            **extra,
            "schema_version": SCHEMA_VERSION,
            "category_id": self.category_id,
            "version": self.version,
            "title": self.title,
            "rules": list(COMMON_RULES),
            "gates": list(self.gates),
            "slots": [
                {
                    "slot_id": s.slot_id,
                    "title": s.title,
                    "kind": s.kind,
                    "template": f"<private-template:{self.category_id}/{s.slot_id}>",
                    "template_sha256": "<pinned-at-binding>",
                }
                for s in self.slots
            ],
        }

    def fingerprint(self) -> str:
        payload = json.dumps(self.manifest(), sort_keys=True).encode()
        return hashlib.sha256(payload).hexdigest()


RISK_ISSUES = Category(
    "risk-issues",
    2,
    "Risk Issues",
    (
        Slot("internal-analysis", "Internal analysis", "document"),
        Slot("client-assessment", "Client assessment", "document"),
        Slot("stakeholder-email", "Stakeholder email draft (not sent)", "email-draft"),
        Slot("detailed-report", "Detailed report", "document"),
        Slot(
            "internal-follow-up-email", "Internal follow-up email draft (not sent)", "email-draft"
        ),
        Slot("updated-detailed-report", "Updated detailed report", "document"),
    ),
    ("collection", "generation", "handoff"),
)

DAILY_PROGRESS = Category(
    "daily-progress-reporting",
    2,
    "Daily Progress Reporting",
    (
        Slot("daily-progress-report", "Daily progress report", "document"),
        Slot("day-to-day-movements", "Day-to-day movements", "workbook"),
        Slot("vm-and-cve-details", "VM and CVE details", "workbook"),
        Slot("stakeholder-reply-email", "Stakeholder reply email draft (not sent)", "email-draft"),
    ),
    ("collection", "generation", "handoff"),
)
MONTHLY_GOVERNANCE = Category(
    "monthly-governance-reporting",
    2,
    "Monthly Governance Reporting",
    (
        Slot("monthly-governance-workbook", "Monthly governance workbook", "workbook"),
        Slot("monthly-governance-slide-deck", "Monthly governance slide deck", "deck"),
        Slot("executive-dashboard", "Executive dashboard", "dashboard"),
    ),
    ("collection", "generation", "handoff"),
    (
        "Retain the prior snapshot period's data unchanged; amend only the "
        "current snapshot period's data.",
        "Preserve the previous snapshot period's report data as retained history "
        "and input for the next month's snapshot-period reporting, so Wiz "
        "offloading cannot cause historical data loss.",
        "Each deliverable has its own approved comparison source; never reuse "
        "one deliverable's comparison source for another.",
        "Fix the baseline and snapshot cutoff before collection and apply them "
        "consistently across all three deliverables.",
        "The workbook and operational slide deck cover the four severities "
        "(Critical, High, Medium and Low); the executive dashboard is intentionally "
        "scoped to Critical and High.",
        "The workbook has six approved tabs and the decks retain their approved "
        "three-slide executive and ten-slide operational structures.",
        "Use the approved previous workbook for workbook history, the reviewed "
        "operational snapshot/deck for operational history, and the workbook "
        "Critical/High figures plus the executive template/history for the dashboard.",
        "Keep accepted-risk and attribution distinct; never merge or infer one "
        "from the other.",
        "Read-only and no-send: drafts only, never send email or change Wiz, "
        "ticketing or cloud records.",
        "Collection, generation and handoff gates must pass, with workflow-QA "
        "and review evidence, before the run is complete.",
        "Keep client names, evidence and identifiers out of this repository.",
    ),
)
CATEGORIES = {c.category_id: c for c in (RISK_ISSUES, DAILY_PROGRESS, MONTHLY_GOVERNANCE)}


def validate_binding(category_id: str, binding: dict[str, Any]) -> list[str]:
    """Check a private slot-to-template binding against its category."""
    category = CATEGORIES.get(category_id)
    if category is None:
        return [f"unknown category {category_id!r}"]
    problems: list[str] = []
    if binding.get("version") != category.version:
        problems.append("binding version does not match the category version")
    slots = binding.get("slots")
    if not isinstance(slots, dict):
        return [*problems, "binding must contain a 'slots' object"]
    expected = {s.slot_id for s in category.slots}
    for missing in sorted(expected - set(slots)):
        problems.append(f"missing template for slot {missing!r}")
    for extra in sorted(set(slots) - expected):
        problems.append(f"unexpected slot {extra!r} (bespoke deliverable)")
    for slot_id, entry in slots.items():
        digest = entry.get("template_sha256") if isinstance(entry, dict) else None
        if not isinstance(digest, str) or len(digest) != 64 or any(
            ch not in "0123456789abcdef" for ch in digest
        ):
            problems.append(f"slot {slot_id!r} needs a pinned lowercase SHA-256")
    return problems

