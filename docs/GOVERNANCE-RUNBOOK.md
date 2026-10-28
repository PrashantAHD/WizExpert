# Governance preparation and release gates

This is the repeatable preparation workflow for the four-severity monthly report
set. It uses the existing generators, not a replacement reporting algorithm.
The optional `verify` command checks prepared files without overwriting them.
Neither a passing test suite nor replay proves that an upstream export is complete.
Replay uses the current generators: it catches preparation/output drift, not a
bug shared by both generation and replay. Before adopting changed reporting logic,
run `python -m pytest tests/governance` and compare an isolated retained-input
replay with the approved reference outputs. Keep independent expected-count,
date-boundary, attribution and template assertions in the regression suite.

## Workflow-compliance QA is separate from report QA

Follow [workflow QA](WORKFLOW-QA.md) at collection, generation and handoff.
An independent evidence-backed review checks whether the process and documented
reasoning were followed. A mathematically correct report does not excuse a
skipped reuse decision, unauthorized template change or misleading progress
statement. Collection is reuse-first and not pre-approved; the post-collection
check (`wizexpert workflow-qa collection-check`) confirms reuse-first and count
reconciliation from the activity log before generation.

## 1. Fix the reporting contract before collection

Confirm and retain the client profile, tenant/project scope, baseline, previous
cutoff, current cutoff and timezone. Use explicit `--profile` paths for production
runs. Do not infer a reporting date from today's date or a filename.

Identify and hash these **separate** approved sources:

| Artifact | Authoritative comparison/template |
|---|---|
| Governance workbook | Approved previous workbook, including the fixed baseline |
| Three-slide executive dashboard | Workbook Critical/High figures plus its own approved executive template/history |
| Ten-slide operational deck | Reviewed issue snapshot plus its own approved operational template and prior figures |

Prior workbook and operational figures can legitimately differ. Retain and
explain their approved bases; never force one to match the other by substitution.
Workbook month-to-month net closure changes can also differ from operational
in-period closure counts because of reopens, reclassification and preserved
approved history. Reconcile those differences by issue and status, not padding.
Keep all sources, outputs, profiles and audit evidence outside the public repository.

## 2. Plan collection from retained evidence, then reconcile

**Default to historical reuse, not a full historical re-fetch.** The workbook
already carries forward prior closed details and preserves approved snapshot
columns. Collection is performed through approved chat tools, not by the CLI:
the collector must use this capability deliberately.

Before bulk pagination, record a short private collection plan (no approval needed) containing:

- The approved prior workbook/decks, raw issue archive and decision records,
  their hashes, scope and actual collection timestamps.
- The history to reuse, the changes needing fresh evidence and the endpoint
  capabilities that can establish coverage.
- Matching count queries, documented page limits and estimated requests for
  each partition. Compare a supported change feed, focused reconciliation and
  full inventory before choosing. Do not equate complete evidence with fetching
  every historical row again.
- The selected strategy, known gaps and escalation conditions. A full historical
  refresh needs a recorded reason and report-owner agreement on the extra cost;
  agreement alone does not establish evidence completeness.

### Preferred: complete change feed plus reconciliation

If an authorized endpoint supports an exhaustive updated-since feed or issue
change history, use it from the previous **actual collection time**, with a
small documented overlap. Confirm that it covers reopens, status and severity
changes, closure-date changes, deletions and reporting-relevant metadata.
Deduplicate locally by Issue ID and event/version evidence. A creation-date
filter or latest status-change timestamp is not an equivalent change feed.
Keep the reporting-period boundary separate from the collection watermark:
overlap must not double-count prior-period closures.

### Fallback when no complete change feed exists

Reuse approved history and collect these fresh populations:

1. The complete current OPEN and IN_PROGRESS inventory across tracked severities.
   This catches currently reopened historical findings, regardless of creation
   date, and refreshes current severity and backlog status.
2. Newly created findings since the collection watermark, including findings
   already closed, plus findings closed in the reporting interval regardless of
   creation date. Include the overlap needed to bridge the prior actual collection.
3. Accepted-risk changes and expiring exceptions. Verify how the endpoint filters
   REJECTED dates; do not assume `resolvedAt` means acceptance time. If changed
   acceptances cannot be enumerated, reconcile the complete current REJECTED
   population and inspect supported issue-level evidence.
4. Prior active IDs missing from the new active inventory and not explained by
   captured closures/acceptances. Check those IDs explicitly; absence or a lookup
   error does not prove resolution, deletion or a scope change.
5. Fresh counts by severity/status, current scores and the ownership/resolution
   evidence needed for this period. Reuse historical rule descriptions locally;
   refresh changed rules and do not infer fresh assignments from old records.

Compare and merge locally, preserving raw evidence separately from reporting
adjustments. Send compact differences and exceptions for model review instead
of repeatedly placing unchanged issue payloads in model context.

**Limits of the fallback:** matching counts do not prove unchanged issue identities
or metadata. A historically closed issue that changes severity or moves between
closed states without a discoverable event can escape these queries; a reopen
and reclose between observations can also be missed. Document the coverage
actually achieved. If such a gap affects required figures, use supported
targeted checks or a scoped/full refresh with approval, or keep the affected
report blocked. Never call this fallback a complete fresh tenant export or
promise exact historical lifecycle reconstruction.

### Reconciliation and handoff

Record each actual request/export, filters, timestamp, expected total, retrieved
rows, unique IDs and pagination completion. Cover all approved severities/statuses
and all supported issue types. Split truncated exports exhaustively; a 5,000-row
warning is not a completeness check. Failed/denied queries remain explicit gaps,
never zeros. Preserve raw inputs and their hashes.

Review conflicting duplicate IDs, reopened issues, status changes and closure dates.
Create a reviewed, non-duplicated CSV set for the reporting calculation. If it
combines retained records and fresh observations, retain an external provenance
manifest identifying each basis and timestamp; do not label it a fresh export.
Trace historical carry-forward
to issue IDs and approved prior reports; current records take precedence only
after conflict review. Do not replace missing live open findings with closed history.

Apply **only documented, still-applicable** exception decisions. Keep raw Wiz
status unchanged in evidence and record each reporting adjustment with the issue,
original value, approved value/date and approval source. An accepted-risk finding
later auto-resolved without remediation must not gain technical-remediation credit.
Never copy last month's exception list without review.

For this report-set workflow, exclude informational findings. The lower-level
standalone workbook command retains its generic severity capabilities.

Retain page cursors, failures, unique counts and collection timestamps so an
interruption resumes rather than restarts. Reconcile live count drift before
generation. Never claim background collection continues after a task has stopped.
The verification CLI checks supplied inputs and replay, not the completeness of
a change feed or this collection plan; source-completeness remains a separate gate.

The local `governance reconcile --plan PLAN.json --plan-only` checks approved
source hashes, collection watermark coverage and partition request estimates.
After collection, add `--previous-input PRIOR.csv --input CHANGES.csv
--active-input ACTIVE.csv --output REVIEWED.csv --audit AUDIT.json`.
It rejects conflicting observations, unreconciled active counts and unexplained
missing prior active IDs; a reopened issue updates the same ID, not a new finding.
Closed-record changes are flagged, not automatically credited as new remediation.
The approved workbook snapshot remains unchanged.

The plan uses schema version 1, strategy `reuse_history` or `full_refresh`,
UTC `previous_collected_at`, `changes_since`, `collected_through`,
`approved_sources` (absolute paths to SHA256, including prior CSVs), and
`partitions` (each with role, expected_count, page_size, query).
Supported roles: active, new, closures, accepted, changes, full_history.
Full refresh requires reason and approved_by. After collection, supply
`active_pagination_complete: true`, four-severity `active_counts` with separate
OPEN/IN_PROGRESS integers, and an empty `unresolved_gaps` list.
Each `coverage` entry (new_findings, closures, accepted_risk,
historical_closed_changes) needs complete=true, a reviewed basis and an absolute
evidence path. These coverage declarations still need independent review; files
and matching totals do not prove an exhaustive upstream feed.
Mark the operational snapshot `collection_strategy: "reuse_history"` and supply
`--reconciliation AUDIT.json` to verification. Changed sources, CSV or observation
cutoff invalidate that audit.

## 3. Build the reviewed snapshot and decisions

- Use UTC cutoffs exactly. Counts stop at the configured snapshot day, 23:59:59.
  Later events belong to the following reporting period.
- Use actual coverage timestamps for early collections and label drafts
  PRELIMINARY. A prior `final_approval` is a period-specific exception, not proof
  that a collection covers later hours. Never inherit it. Any new approved early
  final must disclose actual coverage and retain its approval separately.
- Reconcile `open`, `in_progress`, `resolved` and `accepted` against the reviewed
  current CSV using `cutoff_counts`. Open includes In Progress.
- Keep baseline/previous **approved workbook** figures fixed. Summary and Monthly
  Scope View must agree with the severity sheets and use their distinct documented
  backlog-reduction versus net-closure formulas.
- Record metric observation dates and exact compliance framework versions.
  A newly generated deck does not make old security/HIPAA/HITRUST values fresh.
  Unavailable metrics are qualified, never zero; technical posture is not certification.
- Tenant closures and credited team work are different populations. Retain the
  approved attribution basis with issue-level support. Current assignee, history
  evidence and approved overrides are distinct evidence, not interchangeable proof.
  Do not infer credit from a rule owner or sample.
- Keep Resolved and Accepted Risk separately labelled. Acceptance counts as
  progress when approved but never as eliminated exposure or technical risk reduction.
- Preserve reviewed `closure_wording`, rule-level next steps/status, owner status,
  and deferred work. Rule-specific statements take precedence over owner defaults.
  Refresh these decisions for the new month; do not reuse stale names, ETAs or text.
- Deferred groups remain in tenant backlog counts even when omitted from highlights.
  Record missing assignees in the operator action list, not invented ownership.

Use the [snapshot schema and attribution guide](GOVERNANCE-SNAPSHOT.md). Retain a
private decision record naming sources, review date and unresolved questions.

## 4. Generate in an isolated review directory

Use `governance monthly` for the workbook/executive pair and `governance deck`
for the operational presentation. Use only approved templates. Preserve workbook
column order, the no-Assignee detail layout, snapshot-month column, KPI splits,
watermarks and counts. Retain real editable slide text, team wording, approved
fonts and the correct three-/ten-slide structures.

After team edits, use `deck --import-edits --editor ...` and review the updated
snapshot before rebuilding. A manual workbook correction must be preserved via
the documented `--workbook` adoption path, not overwritten with old CSVs.
For the replay gate below, reconcile those corrections back to reviewed inputs;
otherwise the file remains blocked for this gate.

Never replace approved files during an audit. Normal same-month publication uses
the existing hash-checked backups, per-month locks and pair rollback. Do not remove
a live lock or close a user's Office session to force publication.

## 5. Run the automated replay gate

```powershell
wizexpert governance verify `
  --workflow-review D:\PrivateReports\generation-review.json `
  --profile D:\PrivateReports\client-profile.json `
  --input D:\PrivateReports\current-reviewed.csv `
  --previous-report D:\PrivateReports\approved-previous.xlsx `
  --workbook D:\PrivateReports\review\current.xlsx `
  --executive-template D:\PrivateReports\approved-executive.pptx `
  --executive D:\PrivateReports\review\executive.pptx `
  --snapshot D:\PrivateReports\current.governance.json `
  --operational-template D:\PrivateReports\approved-operational.pptx `
  --operational D:\PrivateReports\review\operational.pptx `
  --actions-csv D:\PrivateReports\review\assignee-actions.csv
```

Supply `--history` for an approved image-only executive template and `--font-dir`
when required. The operational `.governance.json` companion must match the
reviewed snapshot exactly. The actions CSV is required when assignment gaps exist.

The command reconciles current counts, checks cutoffs/profile/previous period,
replays all three outputs using the existing generators and compares every Office
package part. Only ZIP metadata, equivalent XML namespace/attribute serialization,
and core creation/modification timestamps are excluded. It verifies the original
source/output hashes again before returning. Missing inputs, count discrepancies,
unrecorded edits, mismatched layouts/text or source changes fail with a nonzero exit.
It does not modify the supplied files, approve evidence, contact Wiz or publish.

Retain the returned JSON privately. `automated_checks_passed` deliberately includes
`share_ready: false` and the remaining manual gates. A new edit invalidates the
recorded hashes and requires another run. Office saving/restructuring a package
can require review and regeneration; do not weaken comparison to force a pass.

## 6. Native/visual review and release

Open Excel read-only without repair, inspect every sheet and count/footer/filter
boundary, and render **all 13 slides**. Check fonts, clipping, chart labels,
client-facing language, editable text, accepted-risk distinctions and team wording.
Keep the client report clean; internal audit qualifications belong in private
evidence, except material limitations needed to interpret the figures honestly.

Retain the reviewer, time, reviewed output hashes and actual render evidence.
Confirm source completeness, current-period decisions and the release approval.
Only then identify the approved attachment set and draft the stakeholder message
using the standard private HTML email wrapper and established email sections.
No auto-send, no TXT companions, no Wiz/cloud mutation. Wiz tracking stays with
the operator. Report preparation is not authorization to remediate.

**Stop on any unresolved gate.** Describe the blocker and preserve the draft.
This workflow makes deviations detectable; it is not a guarantee against
incorrect source data or a substitute for accountable review.
