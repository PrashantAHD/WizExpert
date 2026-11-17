"""Canonical end-to-end rules for Weekly Progress Reporting (rule ids ``WP-``).

Authored only from existing documented rules (categories/README.md, WORKFLOW-QA.md and the
category pipeline notes). Any change needs explicit owner approval and is made here; docs
and skills only point to this list.
"""

from __future__ import annotations

import re
from typing import Any

from wizexpert.category_rules.base import (
    INSTRUCTION,
    Rule,
    group_rules,
    render_rules,
    rules_json,
)

TITLE = "Weekly Progress Reporting end-to-end rules"
RULE_ID = re.compile(r"WP-[A-Z]{3}-\d{2}")

_WK = "wizexpert.governance.weekly_progress"

PHASES: tuple[tuple[str, str], ...] = (
    ("scope", "Scope, period and dependencies"),
    ("collection", "Collection"),
    ("inclusion", "Item inclusion"),
    ("outputs", "Deliverables, footer and email draft"),
    ("boundary", "No-send and no-mutate"),
)
PHASE_CODES = {"scope": "SCP", "collection": "COL", "inclusion": "INC", "outputs": "OUT",
               "boundary": "BND"}

RULES: tuple[Rule, ...] = (
    Rule(
        "WP-SCP-01", "scope",
        "Reports are issued on Tuesday. The covered window runs from the previous Monday to "
        "the report-week Monday boundary (date-only: report day - 8 days to report day - 1 "
        "day, both inclusive), so a resolution on the boundary Monday can appear in two "
        "consecutive reports.",
        f"{_WK}:period_for",
    ),
    Rule(
        "WP-SCP-02", "scope",
        "The category depends on Risk Issues and Daily Progress Reporting. Each run updates "
        "the previous weekly report instead of recreating the inventory, and reuses the "
        "latest local Risk Issues and Daily Progress records for status, remediation "
        "progress, SNOW and email responses without re-collecting them unnecessarily.",
    ),
    Rule(
        "WP-SCP-03", "scope",
        "Exactly three slots, each built from the template bound to it through the category "
        "pipeline: the editable slide deck (primary), the optional PDF export and the email "
        "draft. The weekly workbook and standalone report HTML are retired.",
        "wizexpert.governance.category_pipeline:run_category_pipeline",
    ),
    Rule(
        "WP-COL-01", "collection",
        "Always perform a fresh read-only Wiz status fetch for the current scope; retained "
        "evidence is reused for history only, and sync state alone is never enough.",
    ),
    Rule(
        "WP-COL-02", "collection",
        "Collection is reuse-first and not pre-approved; the post-collection "
        "`collection-check` gates generation.",
        "wizexpert.workflow_qa:collection_check",
    ),
    Rule(
        "WP-COL-03", "collection",
        "An owner message never closes an item; new responses are reconciled against the "
        "fresh Wiz status.",
        f"{_WK}:build_weekly_dataset",
    ),
    Rule(
        "WP-INC-01", "inclusion",
        "Include the complete current owner-scoped IN_PROGRESS population as of report day, "
        "not only items in the previous report: an item absent from it is `new`.",
        f"{_WK}:build_weekly_dataset",
    ),
    Rule(
        "WP-INC-02", "inclusion",
        "In-progress tables list only rows whose fresh Wiz status is In Progress; rows whose "
        "issues are all Open are left out.",
        f"{_WK}:validate_weekly_dataset",
    ),
    Rule(
        "WP-INC-03", "inclusion",
        "Items resolved inside the covered window appear once with resolution and "
        "current-status evidence. Items resolved before the period are excluded entirely "
        "(rows and summary text). The next period drops resolved items unless they return to "
        "IN_PROGRESS; the prior report stays unchanged as history.",
        f"{_WK}:validate_weekly_dataset",
    ),
    Rule(
        "WP-OUT-01", "outputs",
        "The deck keeps the approved branding and footer text with only the cover, executive "
        "summary, editable in-progress tables and thank-you slides; Key Messages and Current "
        "Status stay blank until explicitly populated, and ticket and Assigned Team cells "
        "follow the owner-approved mapping rules with no inference from counts.",
    ),
    Rule(
        "WP-OUT-02", "outputs",
        "Outputs never contain an \"Assessment basis and limitations\" section, internal Wiz "
        "tracking instructions, monthly leftover text, pictures, scripts or external content.",
        f"{_WK}:validate_weekly_dataset",
    ),
    Rule(
        "WP-OUT-03", "outputs",
        "The email is a private HTML wrapper draft with the approved confidentiality line in "
        "the wrapper only, attaching the deck and PDF. The footer text never enters the "
        "public repository.",
    ),
    Rule(
        "WP-OUT-04", "outputs",
        "Sync never triggers Weekly Progress and Weekly is never a target of it (SY-SCP-01).",
        "wizexpert.console.categories:validate",
    ),
    Rule(
        "WP-OUT-05", "outputs",
        "Collection, generation and handoff workflow QA gates apply; archive existing "
        "deliverables before regenerating them.",
        "wizexpert.workflow_qa:validate_review",
    ),
    Rule(
        "WP-BND-01", "boundary",
        "Wiz and cloud access are read-only: mutate no Wiz issue, ServiceNow record or cloud "
        "resource.",
    ),
    Rule(
        "WP-BND-02", "boundary",
        "Send nothing: the email is a draft and the user sends it.",
    ),
    Rule(
        "WP-BND-03", "boundary",
        "Retained evidence is immutable, and no client data goes in the public repository.",
    ),
)


def rules() -> list[dict[str, str]]:
    return rules_json(RULES)


def grouped() -> list[dict[str, Any]]:
    return group_rules(RULES, PHASES)


def render_text() -> str:
    return render_rules(TITLE, RULES, PHASES)


__all__ = ["INSTRUCTION", "PHASES", "RULES", "RULE_ID", "TITLE", "grouped", "render_text", "rules"]
