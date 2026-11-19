"""Canonical end-to-end rules for the Sync workflow (rule ids ``SY-``).

Sync is the Risk Issues status sync (topbar Sync control), not a deliverable category, so it
is registered in ``WORKFLOW_MODULES`` rather than ``CATEGORY_MODULES``. Authored only from the
behaviour the console already has and the documented rules (CONSOLE.md, WORKFLOW-QA.md); every
rule names its enforcing function. Any change needs explicit owner approval and is made here;
docs and the other rule lists only point to these ids.
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

TITLE = "Sync (Risk Issues status sync) end-to-end rules"
RULE_ID = re.compile(r"SY-[A-Z]{3}-\d{2}")

_CON = "wizexpert.console.imports"
_CAT = "wizexpert.console.categories"
_RUN = "wizexpert.console.runs"
_JS = "wizexpert/console/static/app.js"

PHASES: tuple[tuple[str, str], ...] = (
    ("scope", "Scope and eligibility"),
    ("check", "Due check and read-only status check"),
    ("refresh", "Owner-approved refresh"),
    ("state", "State, report, notification and settlement"),
    ("boundary", "No-send and no-mutate"),
)
PHASE_CODES = {"scope": "SCP", "check": "CHK", "refresh": "REF", "state": "STA",
               "boundary": "BND"}

# Console steps, in order, for the Sync workflow page.
STEPS: tuple[tuple[str, str], ...] = (
    ("Trigger", "The topbar Sync button (manual, forced) or, once per IST day when due and an "
                "assignee is configured, the console opening (automatic)."),
    ("Due check", "Automatic: at most one check per IST calendar day. Manual: always runs, "
                  "unless a check is already running."),
    ("Read-only status check", "One `status-check` run in the VS Code WizExpert chat compares "
                               "the latest Wiz status of the owner's eligible open cases with "
                               "their retained evidence and saves only "
                               "`deliverables/Status-Check/<token>.json`."),
    ("Result and daily change report", "The console reads the result, writes one daily change "
                                       "report and shows a notification: Sync completed > No "
                                       "change detected, or Changes detected, click to view."),
    ("Approve refresh (owner)", "Nothing is refreshed automatically. The owner clicks Approve "
                                "refresh per changed case, once per case per day."),
    ("Sync Refresh (per case)", "The approved case gets one ungated, read-only, no-send "
                                "`sync-refresh` run: new evidence snapshot, regenerated "
                                "deliverables, PDF change summary and local email drafts."),
    ("Settle", "The run result is frozen once the sync settles; the sync icon hint and the "
               "Status-Check outputs show the last result."),
)

RULES: tuple[Rule, ...] = (
    Rule(
        "SY-SCP-01", "scope",
        "Sync is Risk Issues-only: the `status-check` and `sync-refresh` actions exist only in "
        "Risk Issues, other categories reject them, and Weekly Progress and Monthly Governance "
        "never trigger Sync or are targets of it (the topbar control is hidden on their pages).",
        f"{_CAT}:validate",
    ),
    Rule(
        "SY-SCP-02", "scope",
        "Eligible cases are open (not Resolved), non-legacy, have a retained evidence folder "
        "and issue IDs. Resolved cases are not rechecked. Sync only works on existing case "
        "folders and never creates one; one folder per rule stays governed by RI-SCP-01.",
        f"{_CON}:eligible_sync_cases",
    ),
    Rule(
        "SY-SCP-03", "scope",
        "The owner assignee comes only from private console config (`status_sync_assignee`), "
        "is validated (letters, digits, `.`, `_`, `@`, `-`) and is required: if unset or "
        "invalid, Sync refuses and starts nothing. It never enters the public repository.",
        f"{_CON}:run_status_sync",
    ),
    Rule(
        "SY-CHK-01", "check",
        "The automatic check runs at most once per IST calendar day (persisted "
        "`last_started`); a failed or refused check also counts as that day's attempt; "
        "`status_sync_hours` of 0 disables automatic checks.",
        f"{_CON}:status_sync_due",
    ),
    Rule(
        "SY-CHK-02", "check",
        "A manual Sync forces the check, bypassing the due check, but is ignored (reported "
        "busy, no duplicate run) while a check is running. Reloads and polls never rerun it.",
        f"{_CON}:run_status_sync",
    ),
    Rule(
        "SY-CHK-03", "check",
        "GET of the sync endpoint is side-effect free (it only reports state); only POST may "
        "start or advance a run, serialized by one lock.",
        "wizexpert.console.server:ConsoleHandler._api_imports",
    ),
    Rule(
        "SY-CHK-04", "check",
        "Sync starts ONE read-only `status-check` run for the whole check. Its only output is "
        "`deliverables/Status-Check/<token>.json`; the console accepts the result only with a "
        "valid token, no symlink, a size cap and only the cases that were asked for.",
        f"{_CON}:_read_status_result",
    ),
    Rule(
        "SY-CHK-05", "check",
        "A check that ends without a valid result marks the sync failed and refreshes nothing "
        "(the next due or manual sync retries); a start refused by the one-active-run guard "
        "is recorded as a failed attempt with its reason.",
        f"{_CON}:finish_status_check",
    ),
    Rule(
        "SY-REF-01", "refresh",
        "Sync never queues a Refresh directly: the status check always comes first, and the "
        "only runs Sync may start are `status-check` and the owner-approved `sync-refresh`.",
        f"{_CON}:_start_sync_run",
    ),
    Rule(
        "SY-REF-02", "refresh",
        "A Refresh follows a check only for a changed case after the owner clicks \"Approve "
        "refresh\" for that case; it is never auto-approved, runs once per case per day, and "
        "Collection plan and Generation gates are never auto-approved.",
        f"{_CON}:approve_refresh",
    ),
    Rule(
        "SY-REF-03", "refresh",
        "The `sync-refresh` action has no console approval gate (the owner's Approve refresh "
        "click is the approval); manual per-case Refresh also has no console approval gate "
        "(Approval gates not_applicable), while Update stays gated. A stale or no-change "
        "result never blocks either manual action.",
        f"{_CAT}:gate_ids",
    ),
    Rule(
        "SY-REF-04", "refresh",
        "Every sync Refresh fetches Wiz status read-only, saves a new evidence snapshot and "
        "change summary, regenerates deliverables from `templates/risk-issues/` (archiving "
        "first), saves a PDF change summary (what changed, INC created and emailed dates, risk "
        "descriptions, recommended remediation approach; never \"Wiz detected\" wording), puts "
        "the private confidentiality footer on every printed page and drafts the lifecycle "
        "emails locally.",
        f"{_CAT}:build_prompt",
    ),
    Rule(
        "SY-STA-01", "state",
        "Sync state lives in the console state directory (`status-sync.json`, written "
        "atomically under the sync lock) with `phase1` (status check) and `phase2` (Refresh); "
        "phase 2 reads `awaiting_approval`, never failed, until a refresh is approved, and "
        "only approved runs can fail it.",
        f"{_CON}:_write_sync_state",
    ),
    Rule(
        "SY-STA-02", "state",
        "A completed check writes one daily change report per IST day under "
        "`deliverables/Status-Check` (backend-only, no Deliverables button) and nothing into "
        "case deliverables or evidence.",
        f"{_CON}:_write_daily_report",
    ),
    Rule(
        "SY-STA-03", "state",
        "The result is a notification, exactly \"Sync completed > No change detected\" or "
        "\"Sync completed > Changes detected, click to view\" (the latter opens the daily "
        "change report with the Approve refresh buttons); the topbar control says \"Risk "
        "Issues only\" and the browser polls (POST) only while a check is running.",
        f"{_JS}:notificationBar",
    ),
    Rule(
        "SY-STA-04", "state",
        "An ended status-check run is frozen only once its sync is settled (done or failed) so "
        "a later sync cannot change it. Its checklist is incomplete only while the result is "
        "unread or the check failed; a changed case still waiting for the owner shows "
        "\"Refresh not approved yet\", not a failure.",
        f"{_RUN}:_is_settled",
    ),
    Rule(
        "SY-BND-01", "boundary",
        "Wiz and cloud access are read-only: Sync changes no Wiz issue, ServiceNow record or "
        "cloud resource and sends no email; emails are local drafts only.",
        f"{_CAT}:build_prompt",
    ),
    Rule(
        "SY-BND-02", "boundary",
        "Retained evidence is immutable and the status check writes nothing into any case "
        "folder; archive before regenerating. No client data, evidence or private paths go in "
        "the public repository.",
        INSTRUCTION,
    ),
)


def rules() -> list[dict[str, str]]:
    return rules_json(RULES)


def grouped() -> list[dict[str, Any]]:
    return group_rules(RULES, PHASES)


def render_text() -> str:
    return render_rules(TITLE, RULES, PHASES)


def workflow_payload() -> dict[str, Any]:
    """Console payload for the Sync workflow page (kind ``workflow``: no actions or stages)."""
    return {
        "id": "sync",
        "kind": "workflow",
        "title": "Sync",
        "description": "Risk Issues status sync: a read-only Wiz status check, then an "
                       "owner-approved Refresh per changed case.",
        "steps": [{"title": t, "text": x} for t, x in STEPS],
        "rules": grouped(),
        "rule_count": len(RULES),
    }


__all__ = ["INSTRUCTION", "PHASES", "RULES", "RULE_ID", "TITLE", "grouped", "render_text",
           "rules", "workflow_payload"]
