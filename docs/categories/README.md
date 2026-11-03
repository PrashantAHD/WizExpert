# Category definitions: Reusable reporting categories

Reusable, drift-resistant definitions for four work types. The
machine-readable source is `wizexpert/governance/categories.py`; this page is
the public-safe skill and instruction text. It holds placeholders only: no
client names, evidence, identifiers, counts, accounts, CVEs or private
deliverables. Private templates, bindings and outputs stay in private storage.

## Categories

| Category | Deliverable slots |
|---|---|
| `risk-issues` (6) | internal-analysis, client-assessment, stakeholder-email (draft, not sent), detailed-report, internal-follow-up-email (draft, not sent), updated-detailed-report |
| `daily-progress-reporting` (4) | daily-progress-report, day-to-day-movements, vm-and-cve-details, stakeholder-reply-email (draft, not sent) |
| `weekly-progress-reporting` (3, v3) | weekly-progress-slide-deck (primary: approved branded editable 16:9 deck - cover, executive summary with carried-forward/new/resolved counts and key messages, editable in-progress item tables with issue, severity, SNOW ticket, Assigned Team, current status and blockers, thank-you; monthly operational slides removed by an owner-requested redesign), weekly-progress-pdf (optional deck export), weekly-progress-email (private HTML wrapper draft, not sent); the workbook and standalone report HTML are retired; delivered Tuesdays: all current in-progress Wiz items assigned to Prashant, Syed or Kimrah plus items resolved from the previous Monday to the report-week Monday boundary; the owner may change slots later via a recorded owner change; `depends_on` `risk-issues` and `daily-progress-reporting` |
| `monthly-governance-reporting` (3) | monthly-governance-workbook, monthly-governance-slide-deck, executive-dashboard |

### Weekly progress reporting dependencies

`weekly-progress-reporting` declares `depends_on` (`risk-issues`,
`daily-progress-reporting`; shown in its manifest). Each Tuesday run updates the previous
weekly report instead of recreating the inventory, because items often remain IN_PROGRESS
across weeks. It reuses the latest local Risk Issues and Daily Progress records and outputs
for status, remediation progress, SNOW ticket responses and email responses, without
duplicating or re-collecting them unnecessarily, and fetches only the current read-only Wiz
status, reconciling new responses. Closure is never inferred from an owner message.

Weekly rule (owner-requested): reports are issued Tuesday. The complete current owner-scoped
IN_PROGRESS population as of report day is always included, plus RESOLVED issues whose
`resolved_at` falls (for the same approved owners Prashant, Syed or Kimrah only) from the preceding Monday 00:00 through the report-week Monday 00:00
boundary (date-only values: previous Monday = report day - 8 days and report-week Monday =
report day - 1 day, both inclusive; timestamps on the report-week Monday are included, matching resolved_at_before
<report day>T00:00:00Z, so a resolution on the boundary Monday can appear in two consecutive reports).

Resolved-item lifecycle: items resolved inside that window stay in that
report with resolution and current-status evidence. The next period drops them from
the active carry-forward list unless they return to IN_PROGRESS; the prior report is kept
unchanged as the historical record.

### Monthly governance reporting rules (high level)

- Preserve the previous snapshot period's report data as retained history and
  input for the next month's snapshot-period reporting, so Wiz offloading cannot
  cause historical data loss (category version 2).
- Retain the prior snapshot period's data unchanged; amend only the current
  snapshot period's data.
- Each deliverable has its own approved comparison source; never share one
  across deliverables.
- Fix the baseline and snapshot cutoff before collection; apply them to all
  three deliverables.
- The workbook and operational slide deck cover Critical, High, Medium and Low;
  the executive dashboard is intentionally scoped to Critical and High.
- Preserve the approved six-tab workbook and three-slide executive / ten-slide
  operational deck structures.
- Use separate approved comparison sources: prior workbook for workbook history,
  reviewed operational snapshot/deck for operational history, and workbook
  Critical/High figures plus executive template/history for the dashboard.
- Accepted-risk and attribution stay distinct.
- Read-only and no-send; drafts only.
- Collection, generation and handoff gates plus workflow-QA/review evidence
  are required. No client data in this repository.

## Mandatory rules

1. **Follow the template.** Build every deliverable from the private template
   bound to its slot. The binding lists each slot with a pinned SHA-256; a
   missing slot, an extra slot or an unpinned hash blocks
   (`validate_binding`).
2. **No legacy bespoke logic.** The category definition is the sole source of
   truth. Do not recreate or reintroduce one-off generators, hand-built
   layouts or per-case scripts for these categories, including retired
   surfaces (asset/finding detail report, progress image and standalone
   progress validation). Fix the template or shared module instead.
3. **Controlled modification on demand.** The owner may ask to change a
   template, slot or rule. Record the request as an `owner_changes` entry
   (see WORKFLOW-QA.md), change the template, bump the category `version`,
   re-pin hashes, re-run QA and update this page and the private skill. Never
   edit a template silently or for one run only.
4. **Gates.** Collection, generation and handoff QA apply
   (`wizexpert workflow-qa requirements`).
5. **Safety.** Wiz and cloud access are read-only; drafts are never sent;
   retained evidence is immutable; archive existing deliverables before
   regenerating them.

## Private binding shape (kept outside this repository)

```json
{"version": 2, "slots": {"<slot_id>": {"template_sha256": "<64 hex chars>"}}}
```

## Verification

`python -m pytest tests/test_categories.py -q`, then `python scripts/verify.py`.

## Enforced pipeline

`wizexpert/governance/category_pipeline.py` (`run_category_pipeline`) enforces
category selection -> fixed slots -> deliverable builder -> deliverable
validator -> workflow QA/review. It rejects an unknown category, a version
mismatch, a missing or extra slot or an unpinned hash before any builder runs;
invokes only the builder bound to each slot; stops on any validator problem;
and reports `complete` only when matching workflow-QA and review evidence
(`workflow_qa` and `review` both `passed`, same category, version and slot set)
is supplied. Builders and validators are private callables passed in by the
caller. The module never collects from Wiz or sends email.

Production runs use the private binding layer, which maps every slot to its real
builder/validator or fails closed for a slot with none; synthetic callables are
for tests only. QA/review evidence is mandatory (see above).

The private production binding layer runs Monthly Governance Reporting through
the same enforced path: all three slots (workbook, operational ten-slide deck,
executive dashboard) must be bound to private pinned templates and builders. If
a private template or builder is unavailable, the binding is rejected before
any builder runs and the run cannot complete. The public repository exposes
the category contract and generic pipeline tests only; it holds no templates,
private hashes or client data. Direct low-level governance commands remain
separate from this private category orchestration layer.

## Public structural templates

`wizexpert/governance/monthly_templates.py` provides public, placeholder-only
structural templates for the three Monthly Governance Reporting slots
(`monthly-governance-workbook`, `monthly-governance-slide-deck`,
`executive-dashboard`). The schema is generic: six placeholder workbook tabs of
eight columns with `{{name}}` scalars, repeat rows (`{{.colN}}` plus a
`<!-- repeat:tab_k_rows -->` marker) and empty-state messages; a ten-slide
operational deck and a three-slide executive dashboard, each slide with title,
two fields and a `{{footer_text}}` footer. `schema()` returns the contract,
including severities (operational Critical/High/Medium/Low, executive
Critical/High).

`BUILDERS` / `build_all(out_dir)` generate the files on demand into a
caller-chosen directory, and `VALIDATORS` / `validate_all(paths)` return a list
of problems (empty means valid): exact structure, required placeholders, only
placeholder text, no pictures, generic creator metadata, and privacy checks
(account-like numbers, CVE ids, case ids, emails, private paths, URLs, restricted
names). Generated `.xlsx`/`.pptx` outputs are gitignored and must never be kept
in the repository tree.

These builders are structure-only and are not the production binding. Private
templates, the private binding layer and pinned hashes remain private.

### Weekly progress reporting data model

`wizexpert.governance.weekly_progress` is the public-safe, placeholder-only
model for the weekly category: `period_for` (Tuesday reporting date -> previous
Monday .. report-week Monday window), `build_weekly_dataset` (previous report baseline + current
read-only status rows + required Risk Issues / Daily Progress record references
-> carried, new, resolved, dropped or needs-status items), `validate_weekly_dataset`
and `placeholder_dataset`. Rules: every currently IN_PROGRESS item in the supplied historical Wiz rows is
included, not only items in the previous report (absent from it -> `new`; counted
in `counts.in_progress`); items resolved
in the covered period stay in that period with resolution evidence and drop the
next period; an owner message never closes an item; no "Assessment basis and
limitations" section and no internal Wiz tracking instructions in outputs. It
makes no Wiz/SNOW call and sends no email. The five slot renderers, validators
and the client confidentiality footer live in the private workspace
(`templates/weekly-progress/`), not in this repository.

Owner-approved client-output rules, enforced fail-closed by the private deck validator: the Key Messages heading stays but its body and bullets are blank until explicitly populated; verified assignee names appear only for Medium IN_PROGRESS rule groups covered by the owner-provided export and an explicit private account-to-owner mapping, each rule showing exactly its mapped name on its own line under the issue title; unknown, mis-mapped, inline, aggregate or other-cell names and assignee totals are rejected, and High/Critical groups outside the export scope stay unattributed (no inference); the Assigned Team cell is `CloudOps` for verified Prashant rows and remains blank for verified Kimrah/Syed rows or unattributed rows; Current Status cells are blank (reserved for responses from the assigned client team); ticket cells use rule-level semantics (distinct mapped INC numbers without Pending(count) suffixes, plain Pending for an in-scope rule with no INC, Unknown (unavailable) for rules outside the export scope; no INC coverage is inferred from issue counts); the confidentiality footer and existing output QA are unchanged. The private output filenames are `Weekly-Progress-Report.pptx`, `Weekly-Progress-Report.pdf`, and `Weekly-Progress-Report-Email.html`; the last is the email wrapper draft, not the retired standalone report HTML.
