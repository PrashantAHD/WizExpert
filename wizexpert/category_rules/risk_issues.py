"""Canonical end-to-end rules for the Risk Issues category (rule ids ``RI-``).

Authored only from existing documented rules (AGENTS.md, WORKFLOW-QA.md, CONSOLE.md,
categories/README.md and the category pipeline notes). Any change needs explicit owner
approval and is made here; docs and skills only point to this list.
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

TITLE = "Risk Issues end-to-end rules"
RULE_ID = re.compile(r"RI-[A-Z]{3}-\d{2}")

_QA = "wizexpert.workflow_qa"
_CON = "wizexpert.console.imports"
_CAT = "wizexpert.console.categories"
_RUN = "wizexpert.console.runs"

PHASES: tuple[tuple[str, str], ...] = (
    ("scope", "Scope, folders and templates"),
    ("collection", "Collection"),
    ("refresh", "Refresh, Update and status check"),
    ("outputs", "Deliverables, footer and emails"),
    ("boundary", "No-send and no-mutate"),
)
PHASE_CODES = {"scope": "SCP", "collection": "COL", "refresh": "REF", "outputs": "OUT",
               "boundary": "BND"}

RULES: tuple[Rule, ...] = (
    Rule(
        "RI-SCP-01", "scope",
        "One folder per rule under the Risk Issues deliverables root: never create a "
        "`-<assignee>-assigned` or other duplicate case folder. Merge assignee/tracker "
        "metadata into the existing case's `*.workflow.json`.",
    ),
    Rule(
        "RI-SCP-02", "scope",
        "Use only the owner-approved templates in `templates/risk-issues/` and references the "
        "owner supplies. Every slot is bound to a pinned template hash; a missing, extra or "
        "unpinned slot blocks.",
        "wizexpert.governance.categories:validate_binding",
    ),
    Rule(
        "RI-SCP-03", "scope",
        "Earlier issue/rule-ID logic, reference patterns, case gates and generators are "
        "retired: do not use earlier case folders or generators as references, and do not "
        "reintroduce bespoke per-case scripts.",
    ),
    Rule(
        "RI-COL-01", "collection",
        "Collection is reuse-first: start from retained evidence and collect only what is "
        "missing. Collection is not pre-approved or blocked; the post-collection "
        "`collection-check` gates generation.",
        f"{_QA}:collection_check",
    ),
    Rule(
        "RI-COL-02", "collection",
        "Verify Wiz access with a cheap read-only catalog call before collecting; registered "
        "tools alone do not prove authentication. Stop and ask for reconnection on an "
        "authentication failure.",
    ),
    Rule(
        "RI-REF-01", "refresh",
        "Each Refresh must: require the case's retained evidence folder; fetch the latest Wiz "
        "status read-only; compute the delta against retained evidence; save a new evidence "
        "snapshot and change summary without altering retained evidence; regenerate "
        "deliverables from `templates/risk-issues/`, archiving existing files first.",
    ),
    Rule(
        "RI-REF-02", "refresh",
        "Update takes owner free text, requires existing deliverables and non-empty "
        "length-capped input, does no Wiz fetch, saves the input verbatim, archives current "
        "deliverables, regenerates from the templates and records a change summary. It is "
        "gated and sends nothing.",
    ),
    Rule(
        "RI-REF-03", "refresh",
        "The status check (Sync) follows the Sync rules: once per IST day (SY-CHK-01), "
        "owner-assigned eligible cases only (SY-SCP-02, SY-SCP-03), one daily change report "
        "and nothing written to case deliverables or evidence (SY-STA-02).",
        f"{_CON}:status_sync_due",
    ),
    Rule(
        "RI-REF-04", "refresh",
        "Sync scope and the owner assignee are defined by SY-SCP-01..03; the check is "
        "refused if the private assignee is unset.",
        f"{_CON}:eligible_sync_cases",
    ),
    Rule(
        "RI-REF-05", "refresh",
        "A Refresh after a status check needs the owner's per-case \"Approve refresh\" click "
        "and is never auto-approved (SY-REF-02, SY-REF-03). The Collection plan and "
        "Generation gates of a manual Refresh are never auto-approved.",
        f"{_CON}:approve_refresh",
    ),
    Rule(
        "RI-REF-06", "refresh",
        "Sync is Risk Issues-only; see SY-SCP-01.",
        f"{_CAT}:validate",
    ),
    Rule(
        "RI-REF-07", "refresh",
        "Closure: Ignored (Wiz REJECTED) and Risk Accepted count as Resolved. A case is "
        "Resolved when its latest refresh counts are all Resolved/Ignored/Risk Accepted with "
        "at least one such issue; any Open or In Progress issue keeps it In-Progress.",
    ),
    Rule(
        "RI-REF-08", "refresh",
        "Every console run ends with a checklist of completed, skipped, blocked or "
        "not_applicable steps; a status check that is unread or failed is incomplete, never a "
        "successful completed run (SY-STA-04).",
        f"{_RUN}:build_checklist",
    ),
    Rule(
        "RI-OUT-01", "outputs",
        "Build every deliverable from the template bound to its slot through the category "
        "pipeline (template -> builder -> validator -> workflow QA/review); a validator "
        "problem stops the run.",
        "wizexpert.governance.category_pipeline:run_category_pipeline",
    ),
    Rule(
        "RI-OUT-02", "outputs",
        "Excel workbooks use dark navy text for populated data rows on light blue, yellow or "
        "white fills; white text is reserved for headers on dark navy fills. Set the data-row "
        "font explicitly rather than inheriting the header style.",
    ),
    Rule(
        "RI-OUT-03", "outputs",
        "The approved confidentiality footer comes from private configuration or templates: "
        "visible in HTML, on every PDF page via print CSS (in-page footer hidden in print), "
        "in the Excel left page footer and in the email wrapper only, never in a sent email "
        "body. It never enters the public repository.",
    ),
    Rule(
        "RI-OUT-04", "outputs",
        "Email lifecycle uses one slot and file name per stage: (1) initial stakeholder, "
        "(2) status update request, (3) refresh for newly identified findings, (4) follow-up "
        "response. Each is a local HTML draft checked by its slot validator; wording never "
        "says \"Wiz detected\".",
        "wizexpert.email_qa:validate_email",
    ),
    Rule(
        "RI-OUT-05", "outputs",
        "Every sync Refresh also saves a PDF change summary; see SY-REF-04.",
        f"{_CAT}:build_prompt",
    ),
    Rule(
        "RI-OUT-06", "outputs",
        "Collection, generation and handoff workflow QA gates apply; unknown, missing, failed "
        "or unsupported checks block and there is no blanket \"all good\" bypass.",
        f"{_QA}:validate_review",
    ),
    Rule(
        "RI-BND-01", "boundary",
        "Wiz and cloud access are read-only: mutate no Wiz issue, ServiceNow record or cloud "
        "resource.",
    ),
    Rule(
        "RI-BND-02", "boundary",
        "Send nothing: emails are local drafts only and the user sends them.",
    ),
    Rule(
        "RI-BND-03", "boundary",
        "Retained evidence is immutable: archive existing deliverables before regenerating "
        "them. No client data, evidence or private paths go in the public repository.",
    ),
)


def rules() -> list[dict[str, str]]:
    return rules_json(RULES)


def grouped() -> list[dict[str, Any]]:
    return group_rules(RULES, PHASES)


def render_text() -> str:
    return render_rules(TITLE, RULES, PHASES)


__all__ = ["INSTRUCTION", "PHASES", "RULES", "RULE_ID", "TITLE", "grouped", "render_text", "rules"]
