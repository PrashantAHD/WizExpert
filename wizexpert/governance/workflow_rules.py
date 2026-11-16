"""Canonical, machine-readable end-to-end rules for the Monthly governance workflow.

This list is the single source of truth. It is loaded at the start of every monthly run
(``wizexpert governance rules``) and exposed in the console. Any change to a rule needs
explicit owner approval and must be made here; the docs and the skill only point to it.

``enforced_by`` is either ``"agent-instruction"`` (the rule is enforced by instruction and
review only) or ``"module:function"`` naming a code gate under the ``wizexpert`` package
(for example ``"wizexpert.governance.reconcile:check_plan"``). Drift tests verify that every
named gate still exists.

This module imports nothing optional so core commands stay free of governance extras.
"""

from __future__ import annotations

import json
import re
from typing import Any, NamedTuple

INSTRUCTION = "agent-instruction"
RULE_ID = re.compile(r"MG-[A-Z]{3}-\d{2}")

_COL = "wizexpert.governance.collection_gate"
_REC = "wizexpert.governance.reconcile"
_VER = "wizexpert.governance.verify"
_DATA = "wizexpert.governance.governance_data"


class Rule(NamedTuple):
    rule_id: str
    phase: str
    text: str
    enforced_by: str = INSTRUCTION

    def to_json(self) -> dict[str, str]:
        return {
            "id": self.rule_id,
            "phase": self.phase,
            "text": self.text,
            "enforced_by": self.enforced_by,
        }


PHASES: tuple[tuple[str, str], ...] = (
    ("run", "Run and Proceed flow"),
    ("collection", "Collection method"),
    ("ledger", "Post-cutoff ledger"),
    ("plan", "Plan revision, approval and collection gate"),
    ("tracking", "Resolved/Ignored tracking"),
    ("cutoff", "Cutoffs and early observation"),
    ("integrity", "Reconciliation and evidence integrity"),
    ("release", "Generation, validation, replay and release gates"),
    ("boundary", "No-send and no-mutate"),
)

RULES: tuple[Rule, ...] = (
    # -- Run and Proceed flow ---------------------------------------------------------------
    Rule(
        "MG-RUN-01", "run",
        "Monthly Governance uses a single end-to-end Proceed action. It removes the separate "
        "console approval click between collection and generation but not the collection "
        "receipt, source-completeness, validation, replay or release gates; a failed gate "
        "stops the run.",
        "wizexpert.console.categories:gate_ids",
    ),
    Rule(
        "MG-RUN-02", "run",
        "Load this list with `wizexpert governance rules` at the start of every monthly run, "
        "follow every rule, and stop fail-closed on any rule that cannot be satisfied, citing "
        "its rule id.",
    ),
    Rule(
        "MG-RUN-03", "run",
        "This list is the source of truth. Any rule change requires explicit owner approval "
        "and must be made in workflow_rules.py; docs and the skill only reference it.",
    ),
    # -- Collection method ------------------------------------------------------------------
    Rule(
        "MG-COL-01", "collection",
        "Every monthly run uses the proven October partition design unchanged: separate "
        "OPEN+IN_PROGRESS active censuses for each severity; a new-findings partition "
        "covering all four statuses in the creation window; RESOLVED in the reporting "
        "window; REJECTED in the reporting window; a current REJECTED census; a "
        "STATUS_CHANGED_AT DESC RESOLVED/REJECTED sweep through the watermark boundary; "
        "planned get_issue lookups; and residual lookups.",
    ),
    Rule(
        "MG-COL-02", "collection",
        "Every list_issues page, including cursor continuations, must use first=500; "
        "first=20 is not permitted.",
        f"{_REC}:check_plan",
    ),
    Rule(
        "MG-COL-03", "collection",
        "Any change to the partition design, query method or page size requires explicit "
        "owner approval recorded in the current plan; never choose an alternative because "
        "it is easier or faster.",
    ),
    Rule(
        "MG-COL-04", "collection",
        "Use the events-log collector for every paginated query: read exact arguments and "
        "structuredContent from the session events.jsonl; never hand-type a cursor or "
        "payload.",
    ),
    Rule(
        "MG-COL-05", "collection",
        "Before accepting a page verify that after equals the saved endCursor "
        "byte-for-byte, ordering advances, issue IDs have no duplicates, totalCount stays "
        "stable, terminal rows equal totalCount, and the saved tool output cross-checks "
        "with the collected response. Any failed check is a collection blocker, not a "
        "reason to infer or substitute data.",
        "wizexpert.governance.pagination:paginate",
    ),
    Rule(
        "MG-COL-06", "collection",
        "Default to historical reuse, not a full historical re-fetch. A full refresh needs "
        "a recorded reason and report-owner agreement.",
        f"{_REC}:check_plan",
    ),
    Rule(
        "MG-COL-07", "collection",
        "The collection plan also includes the operational-deck grouped partitions: "
        "list_issues_grouped by SOURCE_RULE with status RESOLVED in the reporting window and "
        "status IN_PROGRESS, all supported issue types. When a response would exceed the "
        "50-group limit, split it by severity and merge the groups by source-rule id. Persist "
        "each raw grouped response with the other evidence before the collect check; never "
        "reuse grouped evidence from an earlier observation.",
    ),
    # -- Post-cutoff ledger -----------------------------------------------------------------
    Rule(
        "MG-LED-01", "ledger",
        "Apply the post-cutoff ledger in build_cutoff_state.py: hold out findings created "
        "after the cutoff.",
    ),
    Rule(
        "MG-LED-02", "ledger",
        "Keep a prior-active row when its closure occurs after the cutoff.",
    ),
    Rule(
        "MG-LED-03", "ledger",
        "Keep a prior-closed row when its reopening occurs after the cutoff and confirm "
        "reopenedAt with get_issue.",
    ),
    Rule(
        "MG-LED-04", "ledger",
        "Represent an in-window reopen that is closed after the cutoff as OPEN at cutoff.",
    ),
    Rule(
        "MG-LED-05", "ledger",
        "Retain the observed status for active-to-active changes.",
    ),
    # -- Plan revision, approval and collection gate ----------------------------------------
    Rule(
        "MG-PLN-01", "plan",
        "After execution, create a plan revision recording every executed query and "
        "observed count using the make_plan_r4.py pattern.",
    ),
    Rule(
        "MG-PLN-02", "plan",
        "Obtain owner approval of the plan revision before reconciliation.",
        f"{_COL}:bind_console_approval",
    ),
    Rule(
        "MG-PLN-03", "plan",
        "Run governance reconcile, then governance collect check.",
        f"{_REC}:reconcile",
    ),
    Rule(
        "MG-PLN-04", "plan",
        "The collect check must be READY before any generation step. No partial, inferred, "
        "stale, hand-typed or method-drifted evidence may pass this gate.",
        f"{_COL}:require_ready_receipt",
    ),
    Rule(
        "MG-PLN-05", "plan",
        "An approved plan newer than the retained collection, or covering a later cutoff, "
        "must be executed: run its read-only partitions and write a fresh activity log, "
        "manifest, raw evidence and reconciliation output. Never substitute an older "
        "collection check, retained snapshot or generation-approved label; if the plan "
        "cannot be executed, stop with the specific capability or authentication blocker.",
        f"{_REC}:require_current_delta",
    ),
    # -- Resolved/Ignored tracking ----------------------------------------------------------
    Rule(
        "MG-TRK-01", "tracking",
        "Statuses are OPEN, IN_PROGRESS, RESOLVED and REJECTED. Wiz REJECTED is reported as "
        "Ignored in the workbook and Accepted Risk in the decks; an IGNORED input row is "
        "normalized to REJECTED. Raw evidence keeps the Wiz status unchanged.",
    ),
    Rule(
        "MG-TRK-02", "tracking",
        "Status at a cutoff: findings created after it are excluded; a finding is closed "
        "only if RESOLVED/REJECTED with Resolved Time at or before the cutoff; a finding "
        "closed after the cutoff counts as OPEN; IN_PROGRESS whose status changed after the "
        "cutoff counts as OPEN.",
        f"{_DATA}:cutoff_counts",
    ),
    Rule(
        "MG-TRK-03", "tracking",
        "Workbook, per severity and snapshot (cumulative): Total = findings created by the "
        "snapshot; Open = no Resolved Time or resolved after it (includes In Progress); "
        "Resolved = RESOLVED by it; Ignored = REJECTED by it. Total = Open + Resolved + "
        "Ignored must reconcile; Resolution % and Total Closed use (Resolved + Ignored).",
        "wizexpert.governance.dashboard_data:read_snapshots",
    ),
    Rule(
        "MG-TRK-04", "tracking",
        "Decks: Open includes In Progress; period closures have Resolved Time after the "
        "previous cutoff and at or before the current cutoff, split into resolved and "
        "accepted. Team-credited accepted never exceeds tenant accepted.",
        f"{_DATA}:validate_team_resolved",
    ),
    Rule(
        "MG-TRK-05", "tracking",
        "Resolved and Ignored are always collected, counted and shown separately. Ignored "
        "is closed progress, never technical remediation or eliminated exposure, and is "
        "never merged into Resolved or dropped.",
    ),
    # -- Cutoffs and early observation ------------------------------------------------------
    Rule(
        "MG-CUT-01", "cutoff",
        "Use UTC cutoffs exactly. Counts stop at the configured snapshot day, 23:59:59; "
        "later events belong to the following reporting period.",
        f"{_VER}:verify_preparation",
    ),
    Rule(
        "MG-CUT-02", "cutoff",
        "Use actual coverage timestamps for early collections and label them EARLY "
        "OBSERVATION - NOT FINAL. A prior final_approval is a period-specific exception and "
        "is never inherited; any new early final discloses actual coverage and retains its "
        "approval separately.",
        "wizexpert.governance.governance:render_deck",
    ),
    Rule(
        "MG-CUT-03", "cutoff",
        "Keep baseline and previous approved workbook figures fixed. Summary and Monthly "
        "Scope View must agree with the severity sheets and use their distinct documented "
        "backlog-reduction and net-closure formulas.",
    ),
    Rule(
        "MG-CUT-04", "cutoff",
        "The snapshot period end_inclusive, backlog_as_of and resolved_through, and every "
        "deliverable 'As of' date, title and filename date, equal the reporting cutoff (for "
        "example 2026-11-15T23:59:59Z). collected_through records the actual collection time; "
        "an evidence or source watermark is never used as the report date.",
        f"{_VER}:check_cutoff",
    ),
    # -- Reconciliation and evidence integrity ----------------------------------------------
    Rule(
        "MG-INT-01", "integrity",
        "Record each request/export with filters, timestamp, expected total, retrieved "
        "rows, unique IDs and pagination completion. Split truncated exports exhaustively; "
        "a 5,000-row warning is not a completeness check.",
    ),
    Rule(
        "MG-INT-02", "integrity",
        "Failed or denied queries remain explicit gaps, never zeros. Unavailable metrics "
        "are qualified, never zero.",
    ),
    Rule(
        "MG-INT-03", "integrity",
        "Keep raw Wiz status unchanged in evidence. Apply only documented, still-applicable "
        "exception decisions and record each reporting adjustment with the issue, original "
        "value, approved value/date and approval source.",
    ),
    Rule(
        "MG-INT-04", "integrity",
        "No inferred, partial, stale or hand-typed evidence. Absence from a fresh inventory "
        "or a lookup error does not prove resolution, deletion or a scope change; prior "
        "active IDs missing and unexplained block reconciliation.",
        f"{_REC}:reconcile_rows",
    ),
    Rule(
        "MG-INT-05", "integrity",
        "Preserve raw inputs and their hashes, and reconcile live count drift before "
        "generation.",
        f"{_REC}:check_plan",
    ),
    Rule(
        "MG-INT-06", "integrity",
        "Record metric observation dates and exact compliance framework versions; a newly "
        "generated deck does not make old security/HIPAA/HITRUST values fresh.",
    ),
    Rule(
        "MG-INT-07", "integrity",
        "Team credit requires the approved, supported issue-level attribution basis; do not "
        "infer credit from a rule owner or sample.",
    ),
    Rule(
        "MG-INT-08", "integrity",
        "Exclude informational findings from the report set.",
    ),
    Rule(
        "MG-INT-09", "integrity",
        "Fetch the Wiz Security Score, HIPAA and HITRUST CSF values read-only from Wiz during "
        "the run. If Wiz cannot return a value, an owner-supplied Wiz dashboard screenshot is "
        "an approved source: retain it privately with its sha256 and disclose its observation "
        "date and exact framework version. Otherwise mark the metric unavailable with the "
        "reason; never zero and never carried over from an earlier period.",
    ),
    # -- Generation, validation, replay and release gates -----------------------------------
    Rule(
        "MG-REL-01", "release",
        "Generate only after the collect check is READY, directly in the canonical "
        "period report directory (for example deliverables/Monthly-Governance-Reporting/"
        "November2026-report) with approved templates. Keep one canonical filename per "
        "deliverable; archive the prior version before replacement and do not create a "
        "separate review directory or duplicate .generated copy.",
    ),
    Rule(
        "MG-REL-02", "release",
        "Pass the collect check receipt to governance verify with the collection-gate "
        "option; the replay gate compares every output with its reviewed inputs and any "
        "failure stops the run.",
        f"{_VER}:verify_preparation",
    ),
    Rule(
        "MG-REL-04", "release",
        "Build the operational snapshot only with `wizexpert governance snapshot`; no ad-hoc "
        "scripts.",
        "wizexpert.governance.snapshot_build:build_snapshot",
    ),
    Rule(
        "MG-REL-03", "release",
        "Run the validators and workflow QA gates; native/visual review of every sheet and "
        "slide and the release approval remain manual gates before any attachment is "
        "identified.",
    ),
    # -- No-send and no-mutate --------------------------------------------------------------
    Rule(
        "MG-BND-01", "boundary",
        "Wiz and cloud access are read-only: mutate no Wiz issue, ServiceNow record or "
        "cloud resource.",
    ),
    Rule(
        "MG-BND-02", "boundary",
        "Send nothing: no email or message is sent by a monthly run.",
    ),
    Rule(
        "MG-BND-03", "boundary",
        "Retained evidence is immutable, and no client data goes in the public repository.",
    ),
)


def rules() -> list[dict[str, str]]:
    return [r.to_json() for r in RULES]


def grouped() -> list[dict[str, Any]]:
    """Rules grouped by phase, in display order."""
    return [
        {
            "phase": phase_id,
            "title": title,
            "rules": [r.to_json() for r in RULES if r.phase == phase_id],
        }
        for phase_id, title in PHASES
    ]


def render_text() -> str:
    lines = [f"Monthly governance end-to-end rules ({len(RULES)})", ""]
    for phase_id, title in PHASES:
        lines.append(title)
        for r in (x for x in RULES if x.phase == phase_id):
            lines.append(f"  {r.rule_id}  {r.text}")
            lines.append(f"      enforced by: {r.enforced_by}")
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    arguments = list(argv or [])
    if arguments == ["--json"]:
        print(json.dumps({"rules": rules(), "phases": grouped()}, indent=2))
        return 0
    if arguments:
        print("usage: wizexpert governance rules [--json]")
        return 2
    print(render_text())
    return 0
