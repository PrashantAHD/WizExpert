"""Canonical end-to-end rules for Daily Progress Reporting (campaigns; rule ids ``DP-``).

Authored only from existing documented rules (CAMPAIGNS.md, WORKFLOW-QA.md,
categories/README.md and the daily-report skill and instructions). No campaign identifiers,
client names or evidence appear here. Any change needs explicit owner approval and is made
here; docs and skills only point to this list.
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

TITLE = "Daily Progress Reporting end-to-end rules"
RULE_ID = re.compile(r"DP-[A-Z]{3}-\d{2}")

_CAMP = "wizexpert.campaign"

PHASES: tuple[tuple[str, str], ...] = (
    ("lifecycle", "Campaign lifecycle and scheduling"),
    ("collection", "Collection and reconciliation"),
    ("metrics", "Metric definitions"),
    ("outputs", "Deliverables, footer and email draft"),
    ("boundary", "No-send and no-mutate"),
)
PHASE_CODES = {"lifecycle": "LIF", "collection": "COL", "metrics": "MET", "outputs": "OUT",
               "boundary": "BND"}

RULES: tuple[Rule, ...] = (
    Rule(
        "DP-LIF-01", "lifecycle",
        "A campaign is a temporary, repeated report on a fixed set of vulnerability IDs the "
        "owner supplies (no defaults). Refresh every day until every target is fully patched "
        "and the closure gate is met; then stop and tell the owner to disable the scheduled "
        "automation.",
        f"{_CAMP}:lifecycle",
    ),
    Rule(
        "DP-LIF-02", "lifecycle",
        "Stop routine reporting only after evidence of completed vendor-supported "
        "remediation for every target, a fresh reconciled assessment with no remaining "
        "in-scope findings and operator confirmation. A lower count, rejected finding, "
        "exception, deleted resource or lost scanner visibility never establishes complete "
        "patching. A closure gate marked met without every target patched and a named "
        "confirmation is rejected.",
        f"{_CAMP}:lifecycle",
    ),
    Rule(
        "DP-LIF-03", "lifecycle",
        "A scheduled run prepares drafts and reports only. A request to save or restyle a "
        "report does not call for fresh collection; a daily-update request, \"refresh now\" "
        "or \"send like yesterday\" does. Do not substitute an interim status-only draft for "
        "the validated pack.",
    ),
    Rule(
        "DP-COL-01", "collection",
        "There is no elapsed-time limit on a collection. A run is abandoned only on an "
        "explicit failure: the same call failed three times, or an authentication failure "
        "(HTTP 401 or OAuth challenge) that needs reconnection.",
        f"{_CAMP}:next_call",
    ),
    Rule(
        "DP-COL-02", "collection",
        "Collection order is fixed: catalog records in parallel; grouped queries per status "
        "group (all, remaining, resolved, rejected); ONE finding stream over OPEN, "
        "IN_PROGRESS, RESOLVED and REJECTED; then exact-ID resource lookups with deleted "
        "resources included. Never split remaining and resolved into separate streams, and "
        "never raise the Wiz page-size maxima (findings and grouped 20, resources 40).",
        f"{_CAMP}:next_call",
    ),
    Rule(
        "DP-COL-03", "collection",
        "One staging directory per run. After an abort start a new directory; never stitch "
        "pages from an aborted run and never rebuild from a previous day's inventory. A "
        "snapshot and matching inventory for the reporting UTC date are required.",
        f"{_CAMP}:assemble",
    ),
    Rule(
        "DP-COL-04", "collection",
        "A resource lookup that returns fewer IDs than requested keeps the findings, excludes "
        "the unreturned assets from returned-resource counts and labels them `Not returned by "
        "Wiz / requires reconciliation`; an unreturned resource is never treated as resolved "
        "or closed.",
        f"{_CAMP}:assemble",
    ),
    Rule(
        "DP-COL-05", "collection",
        "Reconcile before publishing: grouped totals equal the finding stream per status "
        "group, finding IDs are unique, scope is unchanged and cursors advance. Incomplete "
        "pagination, changed scope, mismatched counts or stale inventories block publication "
        "as a fresh report.",
        f"{_CAMP}:save",
    ),
    Rule(
        "DP-COL-06", "collection",
        "Keep raw arguments, responses and observation timestamps in private evidence; never "
        "overwrite a historical observation. Keep every intraday observation and display the "
        "latest validated one per UTC date.",
    ),
    Rule(
        "DP-COL-07", "collection",
        "Collection is reuse-first and not pre-approved; the post-collection "
        "`collection-check` (with the campaign collection block) gates generation.",
        "wizexpert.workflow_qa:collection_check",
    ),
    Rule(
        "DP-COL-08", "collection",
        "Fresh-evidence gate: a report is built only from a collection observed on the current "
        "UTC date. Assembly rejects a stale or future snapshot, and the console Refresh counts "
        "as completed only when a same-day snapshot, its matching inventory and every "
        "deliverable are newer than the click; the end of the chat is never proof.",
        "wizexpert.console.freshness:gate",
    ),
    Rule(
        "DP-MET-01", "metrics",
        "Charts count vulnerability findings, not risk issues, posture issues, packages or "
        "VMs. Track assets separately by unique Wiz asset ID; names are not identity keys. "
        "Remaining and resolved asset sets can overlap, so never add them.",
    ),
    Rule(
        "DP-MET-02", "metrics",
        "Remaining = OPEN + IN_PROGRESS. Resolved means resolved in Wiz, not verified "
        "patching. REJECTED is separate and is not successful remediation.",
    ),
    Rule(
        "DP-MET-03", "metrics",
        "New daily findings come from `firstDetectedAt` on the reporting UTC date, not from "
        "changes in aggregate totals. Missing daily evidence is \"Not available\", never 0; "
        "a missing, timezone-less or post-cutoff timestamp is rejected.",
    ),
    Rule(
        "DP-MET-04", "metrics",
        "Reconstructed data points and partial-day observations must name the UTC cutoff; "
        "reconstructions never enter the observed history.",
        f"{_CAMP}:campaign_wording_errors",
    ),
    Rule(
        "DP-MET-05", "metrics",
        "Findings on self-hosted cloud / network-appliance assets are excluded from every "
        "aggregate and report until the owner or client confirms scope; raw evidence is "
        "retained unchanged and each draft email carries a concise scope note while the "
        "exclusion exists.",
    ),
    Rule(
        "DP-MET-06", "metrics",
        "The VM/CVE Excel keeps its detail tabs first and appends one worksheet per day that "
        "has new detections, listing that day's new assets and findings, so a daily refresh "
        "adds rather than rewrites history. An owner's addition request is a persistent rule, "
        "not a one-off edit.",
    ),
    Rule(
        "DP-OUT-01", "outputs",
        "Exactly four deliverables, each built from the template bound to its slot through the "
        "category pipeline: daily progress report PDF, day-to-day movements PDF, VM/CVE "
        "Excel and stakeholder reply email draft. Legacy bespoke outputs (asset/finding "
        "detail report, progress image) are retired; fix the template or shared module "
        "instead.",
        "wizexpert.governance.category_pipeline:run_category_pipeline",
    ),
    Rule(
        "DP-OUT-02", "outputs",
        "The stakeholder email is a reply in the existing thread with the PDF and Excel "
        "attached, stating the actual UTC cutoff and counts only (detected, resolved, "
        "remaining, newly detected today). No movement, reconstruction, partial-day, "
        "resolved-versus-patched, closure or rejected-finding paragraphs; derive every "
        "number from the same snapshot.",
        "wizexpert.email_qa:validate_email",
    ),
    Rule(
        "DP-OUT-03", "outputs",
        "Campaign update and closure emails never mention Rejected findings, and write "
        "\"Resolved in Wiz\" rather than claiming verified patching.",
        f"{_CAMP}:campaign_wording_errors",
    ),
    Rule(
        "DP-OUT-04", "outputs",
        "Archive the old pack, draft and state before replacing; a failed replacement rolls "
        "the pack back and a validation error fails the build before publication. Mark "
        "native Excel/visual review pending until actually done.",
    ),
    Rule(
        "DP-OUT-05", "outputs",
        "The approved confidentiality footer comes from private configuration or templates: "
        "PDF every page, Excel page footer, email wrapper only. It never enters the public "
        "repository.",
    ),
    Rule(
        "DP-BND-01", "boundary",
        "Wiz and cloud access are read-only: mutate no Wiz issue, ServiceNow record or cloud "
        "resource.",
    ),
    Rule(
        "DP-BND-02", "boundary",
        "Send nothing: the stakeholder email is a draft and the user sends it.",
    ),
    Rule(
        "DP-BND-03", "boundary",
        "Retained evidence is immutable. Campaign state, evidence and reports stay in private "
        "storage and never enter the public repository.",
        f"{_CAMP}:refuse_public_repo_path",
    ),
    Rule(
        "DP-BND-04", "boundary",
        "Campaign-specific decisions (scope, exclusions, wording) live in the private campaign "
        "rule registry beside the campaign state, are enforced by its collection and build "
        "gates, and never enter this public list.",
    ),
)


def rules() -> list[dict[str, str]]:
    return rules_json(RULES)


def grouped() -> list[dict[str, Any]]:
    return group_rules(RULES, PHASES)


def render_text() -> str:
    return render_rules(TITLE, RULES, PHASES)


__all__ = ["INSTRUCTION", "PHASES", "RULES", "RULE_ID", "TITLE", "grouped", "render_text", "rules"]
