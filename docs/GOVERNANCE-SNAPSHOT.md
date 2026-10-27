# Operational governance: collecting a reusable snapshot

Use the approved ten-slide **operational governance deck**, not the three-slide
executive dashboard, as the template. Confirm the connected Wiz tenant and the
prior comparison source with the report owner. This workflow currently supports
explicitly approved **tenant-wide** scope; it does not imply project filtering.

## Read-only collection through Copilot

Before bulk issue collection, follow the runbook's
[retained-evidence collection plan](GOVERNANCE-RUNBOOK.md#2-plan-collection-from-retained-evidence-then-reconcile).
Reuse approved prior snapshots and archived issue history. The queries below
collect current operational evidence; they do not require re-fetching all
historical closed findings. Prefer a verified complete change feed; otherwise
reconcile current active findings, new findings, interval closures and accepted
risk, with explicit checks for unexplained prior IDs. Creation-date filtering
alone misses changes to older issues. Record unsupported change coverage rather
than treating unchanged aggregate counts as proof of unchanged records.

1. Record a UTC collection start. Agree the prior cutoff and scheduled end,
   including timezone. The generator currently requires UTC timestamps.
2. Through Wiz `discover`, inspect the current tool schemas, then use `execute`:
   - `get_security_score(metric_id="wm-security-score")`.
   - `list_compliance_frameworks(search="HIPAA")` and the corresponding HITRUST
     search; retain the exact framework IDs/names/version, then call
     `get_compliance_ratings(framework_ids=[...])`.
   - `list_issues(status=["OPEN","IN_PROGRESS"], severity=[severity], first=1)`
     for each of Critical, High, Medium and Low; use `totalCount`, never the
     number of sampled nodes. Do not collect informational issues for this workflow.
   - Repeat individual severity totals for `status=["IN_PROGRESS"]`.
   - Repeat for `status=["RESOLVED"]` with `resolved_at_after` equal to the
     prior cutoff and `resolved_at_before` equal to the actual coverage cutoff
     (no later than the scheduled end or collection).
   - `list_issues_grouped(group_by="SOURCE_RULE", fetchIssues=true,
     fetchSecurityScoreImpact=false, first=50, status=["RESOLVED"], ...)`
     using those same resolution bounds.
   - Repeat grouped collection with `status=["IN_PROGRESS"]` and **no
     resolution-date filter**.
3. Both grouped queries must include all supported issue types:
   `CLOUD_CONFIGURATION`, `TOXIC_COMBINATION`, `THREAT_DETECTION`,
   `ATTACK_SURFACE`, `RISK_TOXIC_COMBINATION`. If the endpoint returns fewer
   groups than `totalCount`, split by severity, then paginate/split as supported
   by the discovered schema. Do not add overlapping groups twice. If the full
   collection cannot be obtained, stop rather than representing it as complete.
4. For resolved highlights, request `get_issue_resolution_evidence(rule_name=...)`.
   This tool may not support dates: match evidence to captured IDs **and**
   in-period resolution timestamps. Status alone is not evidence of the action.
   Preserve errors as limitations. For team notes, record a dated, approved
   source, affected IDs and the actual update. Do not invent owners or ETAs.
5. Record UTC collection completion and all query parameters. Queries are not
   atomic: reconcile counts and groups, and recapture if they disagree.
   Keep raw responses in a local `governance-evidence/` folder.
6. Manually verify prior values from the approved deck. Record its SHA256.
   If its compliance framework version differs or is unspecified, disclose that
   limitation rather than asserting a like-for-like improvement.
7. Build the JSON below, validate/generate, render every slide, and review
   evidence gaps before customer publication.

The CLI consumes this snapshot; it does **not** independently collect Wiz data.
All actual client inputs, API responses and generated files stay out of Git.

## Snapshot schema (version 1)

The following **synthetic** example documents every required top-level field.
Replace values with evidence; never use the example as actual customer data.
`<sha256>` must be the 64-character digest of the supplied approved template.
Dates are examples in the past so they can be validated at any later refresh.

```json
{
  "schema_version": 1,
  "scope": {
    "kind": "TENANT",
    "name": "Approved dedicated tenant",
    "tenant_id": "tenant-identifier",
    "issue_types": ["CLOUD_CONFIGURATION", "TOXIC_COMBINATION", "THREAT_DETECTION",
                    "ATTACK_SURFACE", "RISK_TOXIC_COMBINATION"]
  },
  "period": {
    "start_exclusive": "2025-09-15T23:59:59Z",
    "end_inclusive": "2025-10-15T23:59:59Z",
    "resolved_through": "2025-10-13T09:00:00Z",
    "collected_from": "2025-10-13T09:00:00Z",
    "collected_through": "2025-10-13T10:00:00Z"
  },
  "prior": {
    "date": "2025-09-15",
    "source": "Approved September operational deck",
    "source_sha256": "<sha256>",
    "open": {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 5, "LOW": 2},
    "security_score": {"value": 95, "source": "Prior slide 3"},
    "hipaa": {"value": 90, "source": "Prior slide 3"},
    "hitrust": {"value": 85, "source": "Prior slide 3"}
  },
  "open": {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 3, "LOW": 2},
  "in_progress": {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0},
  "resolved": {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0},
  "security_score": {"value": 96, "source": "wm-security-score, collection timestamp"},
  "hipaa": {"value": 91, "source": "Framework ID/name/version, collection timestamp"},
  "hitrust": {"value": null, "source": "Wiz framework query", "unavailable_reason": "HTTP 504"},
  "resolved_groups": {"total_groups": 0, "groups": []},
  "in_progress_groups": {"total_groups": 0, "groups": []},
  "limitations": ["Synthetic example; resolution evidence not collected."]
}
```

- `open` means OPEN **plus** IN_PROGRESS. IN_PROGRESS must not exceed it.
- All counts are nonnegative integers (not booleans, floats or numeric strings).
- Metrics are 0-100 or `null` with an explicit `unavailable_reason`.
- Prior and current count dictionaries use the four tracked severities. Legacy
  informational keys remain load-compatible but are excluded from displayed totals.
- Resolution bounds are exclusive/inclusive as named. Collection cannot be in
  the future. The cover preserves scheduled dates but never labels early data
  as the later scheduled snapshot.
- Include collection/source caveats in `limitations` (an explicit list, even
  when empty). Additional provenance, such as a `queries` object with exact
  requests, is retained in the companion JSON.

### Group records

Both group collections use the same shape. For each complete grouped response,
the helper below strips resource details while preserving counts, rule names,
recommendations and dated samples:

```python
import json
from pathlib import Path
from wizexpert.governance.governance_data import capture_groups

response = json.loads(Path("resolved-raw.json").read_text(encoding="utf-8"))
snapshot["resolved_groups"] = capture_groups(response)
```

The resulting `groups` array contains objects like:

```json
{
  "id": "rule-id",
  "name": "Example risk rule",
  "counts": {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 12, "LOW": 0, "INFORMATIONAL": 0},
  "recommendation": "* Apply least privilege to the service account.",
  "samples": [
    {"id": "issue-id", "created_at": "2025-08-01T00:00:00Z", "resolved_at": "2025-10-02T01:00:00Z"}
  ]
}
```

`total_groups` must equal the number of captured groups. Aggregated severity
counts must match independent status totals. Samples are explicitly **not** an
exhaustive ID export; sample size does not replace the issue count. Duplicate
groups/sample IDs are rejected to prevent double-counting.

In-progress samples can have a null `resolved_at`. Resolved samples must be
within the stated reporting bounds. Each group requires at least one sample.
If a raw sample has multiple source rules, reconcile the mapping rather than
arbitrarily choosing one.

### Optional reviewed evidence

Attach an `annotation` to a group only when supported:

```json
{
  "change": "Resource owner confirmed removal of the exposed credential.",
  "risk": "Exposure reduced for the cited finding; other group members not verified.",
  "source": "Dated Wiz evidence or approved owner update",
  "issue_ids": ["issue-id"]
}
```

Every ID must be a unique captured sample in that group. The deck displays
**evidence covers X of N**, not a group-wide assertion. Record severity
reclassification, resource removal, accepted risk and genuine remediation
accurately; they are not interchangeable.

For in-progress groups, `annotation.change` is the current team status update;
the other evidence fields remain required for provenance. Suggested next steps
come from the captured Wiz recommendation, not stale prior-month narrative.
Full annotations/recommendations stay in the JSON/notes; visible excerpts may
end in `...` for layout.

### Verified assignees in issue titles

Optionally attach `assignments` to each group:

```json
{
  "verified_at": "2025-10-13T11:00:00Z",
  "source": "Wiz full-group assignment verification; retained query/ID evidence",
  "entries": [
    {"id": "wiz-user-id-a", "name": "Alex", "count": 8},
    {"id": "wiz-user-id-b", "name": "Blair", "count": 3},
    {"id": null, "name": "Unassigned", "count": 1}
  ]
}
```

On an in-progress row, this example covers 12 findings and produces `Example risk rule
(Alex/Blair)`. Use the report owner's approved login-to-display-name
mapping, matched against actual Wiz user IDs. Never infer ownership from the
rule title, a note author or assignee suggestions. A verified assignment on
one qualifying finding is enough to include that name, but not to assert
group-wide ownership.

Entry counts may cover **some or all** of the qualifying findings, but must
not exceed the group count. Use unique user IDs and positive integer counts.
The slide count always remains the entire status/period group count, independent
of assignment coverage. Verify deduplicated qualifying issue details,
or assignee-filtered `list_issues.totalCount` values using the same source rule,
status and resolution bounds as the group. A single user's count equalling the
whole group count proves full coverage, but full coverage is not required to
display a verified name. Retain query parameters and results locally. Do not
use assignees from OPEN findings to label a RESOLVED or IN_PROGRESS row, or
from resolutions outside the stated period.

`list_issues` responses may omit the assignee field; `get_issue` supplies it.
No exhaustive unassigned census is needed when a qualifying assignee is already
verified. Mixed groups display only the verified names, not `/Unassigned`.
Only an explicit null assignee on **every** qualifying finding establishes the
standalone `Unassigned` label. If no names have been verified and some findings
are unchecked, display `Assignee not verified`, not `Unassigned`.

The assignment verification time may be later than the posture snapshot and is
recorded separately. These are **current assignees**, not historical assignees
at closure or proof of who remediated the finding. Missing assignment evidence
is visibly labelled `Assignee not verified`. Names cover one or more findings,
not necessarily all; detailed coverage stays in JSON/notes.
Keep real identities and assignment evidence in the ignored local snapshot,
not in repository source or examples.

## Repeat-month operation

### Sharing names across rule statuses

Set top-level `"assignment_scope": "RULE"` only when the report owner approves
rule-level ownership. The default `"STATUS"` retains status-specific labels.
RULE mode combines verified named assignees from all captured groups with the
same exact rule ID, not similar titles; names are deduplicated and sorted.
In-progress rows show that union, while counts and resolution cutoffs remain
unchanged. Resolved rows never show current-assignee labels as work attribution.
A null assignee in one status cannot
override positive named evidence in another. With no named evidence, the label
is `Assignee not verified`, not a claim that the entire rule is unassigned.

Additional assignee checks, including OPEN findings, can be retained separately:

```json
{
  "assignment_scope": "RULE",
  "rule_assignment_evidence": [{
    "id": "rule-id",
    "status": "OPEN",
    "total_count": 10,
    "assignments": {
      "verified_at": "2025-10-13T11:00:00Z",
      "source": "Same-rule OPEN assignee-filtered Wiz query; retained response",
      "entries": [{"id": "wiz-user-id-a", "name": "Alex", "count": 1}]
    }
  }]
}
```

These records supply names only; they never add to, subtract from or reclassify
the report's finding totals. Preserve the actual status-specific assignment
evidence rather than copying fictitious assignment counts across groups.
Speaker notes disclose rule-level label sharing. This does not change
Wiz assignments or establish who performed remediation.

### Resolved closures versus credited work

Without the optional reviewed `team_resolved` object, resolved slides retain
tenant-wide closure totals but omit personal assignee
labels, regardless of `assignment_scope`. They explicitly display **Attribution
Pending** and **not credited team work**. Even a current assignee on every
resolved finding does not establish ownership before the resolution date.

Before attributing work, verify the issue/rule's assignment/activity timeline,
the person's ownership start, and the resolution event. Findings resolved
before ownership began, or lacking evidence of assignment/contribution, must
not be credited to that person. The current snapshot's assignment fields are
not historical evidence, and no personal-work count is generated from them.
Retain earlier closures in overall tenant statistics without claiming them as
team achievements. An authentication or history-retention gap remains explicitly
unverified; do not substitute current owners or note authors.

#### Approved team-closure rule (`team_resolved`)

The team approved a simpler operating rule (October 2026): a closure counts as
team work when the issue is currently `RESOLVED`, its `resolvedAt` falls in the
reporting interval, and the **issue itself** is currently assigned in Wiz to a
listed team member. Unassigned closures are excluded. When the optional
`team_resolved` object is present, resolved slides are titled **Resolved by
Team**, and show only those groups with assignee names. Tenant totals remain on the
summary slides.

The approved workflow can also use retained **issue-level history** to support a
team attribution when the current assignee is empty. Record this distinct basis
in `team_resolved.basis`, the assignment source and private audit, and retain the
missing-assignee action. This is not permission to infer work from a rule owner,
sample or Wiz automatic event. Validate the chosen policy for each reporting
period rather than silently switching between current-assignee and history rules.

```json
"team_resolved": {
  "basis": "Resolved in the interval and currently assigned to a team member.",
  "team": [{"id": "<user UUID>", "name": "Alex"}],
  "total_groups": 1,
  "groups": [{"id": "<rule id from resolved_groups>", "name": "...",
              "counts": {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 4, "LOW": 0},
              "samples": [{"id": "...", "created_at": "...Z", "resolved_at": "...Z"}],
              "assignments": {"verified_at": "...Z", "source": "...",
                              "entries": [{"id": "<user UUID>", "name": "Alex", "count": 4}]}}]
}
```

Validation requires every group to exist in `resolved_groups` with counts no
larger than the tenant group, every finding to have a listed team assignee, and
samples resolved inside the interval.

**Accepted risk.** The progress report counts Wiz `REJECTED` (ignored / accepted
risk) closures together with `RESOLVED`, as the Excel workbook does. Add the
tenant's in-period accepted-risk totals as top-level `accepted` (same severity
keys as `resolved`) and, per team group, an optional `accepted` count object.
Group findings and assignee counts then cover resolved + accepted. The issue
column carries the counts once, for example `(Alex) (8 resolved, 2 accepted
risk)`; the other columns are plain text without numbers. The
slides are titled **Resolved / Risk Accepted by Team**, and a rule with only
accepted-risk findings may be absent from `resolved_groups`. Team accepted
counts may not exceed the tenant `accepted` totals.

**How it was closed and risk reduction (`resolution`).** Each team group may
carry a `resolution` object built by `wizexpert/governance/resolution_evidence.py`
from the same fields a resolved issue page shows: `resolutionReason`
(fixed / resource deleted / won't fix / exception), `resolutionEvidence.changes`
(resource **types** only, never names) and the rule's `risks`. `summarize()`
stores `reasons` (counts that must add up to the group's findings), the top
`changes` and the `risks`. The slides then show, for example:

- Issue: `Service account with high privileges is inactive for over 90 days`
  / `(Blair) (18 resolved, 108 accepted risk)`
- Closure evidence: `IAM role bindings removed (access revoked). High
  privileges removed from service accounts. Service accounts removed.` (what
  actually changed, from Wiz's resolution evidence, without counts;
  accepted-only rows read `Risk reviewed and accepted by the team.`)
- Risk reduction: `Reduced unprotected identity risk.` (accepted-only rows read
  `Accepted risk documented in Wiz.`)

Change descriptions come from deleted/added resource types and modified
properties (for example `hasHighPrivileges` true to false). Wiz bookkeeping
records that duplicate a real change (secret data, hosted technology,
excessive-access findings) are skipped; extend the tables in
`resolution_evidence.py` when a new resource type appears.

Groups without `resolution` keep the "team to confirm" wording. The accepted-risk
count is shown only in the issue column; accepted-risk findings are never
described as risk reduced.

**Team wording (`closure_wording`).** The owner can replace the generated text
for a team-resolved rule with their own description of the fix:
`{"id": "<rule id>", "changed": "Query logging configuration enabled. Removed
default VPCs.", "risk": "Improved DNS query visibility and detection
coverage.", "source": "...", "as_of": "...Z"}` (either text optional, each at
most 200 characters, no counts). Team text wins over the generated text.
Refresh the entries every month; they are team statements, not Wiz data.
Edits the team makes directly on a generated deck can be recorded with
`wizexpert governance deck --snapshot <snapshot> --import-edits <deck> --editor <name>`
(see the [governance guide](GOVERNANCE.md#operational-governance-deck)); it writes `closure_wording` and `rule_status` entries.

Collect assignees for **every** resolved
issue in the interval (complete pagination), not a per-user sample, so excluded
closures are counted exactly. Wiz does not expose when an assignment was made
without audit access; the rule relies on the closed issue's current assignee.

#### Team status updates (`owner_status`)

Wiz has no "pending review" style sub-status for IN_PROGRESS issues. Record team
updates as `owner_status` entries: `{"name": "Alex", "status": "Pending review",
"source": "...", "as_of": "...Z"}` (one short line per owner). In-progress
rows owned only by that person show `Status: Pending review.` instead of "ETA and
blockers need team confirmation"; shared rows list each owner's status. The
count stays in the issue column, so the status column is text only. Refresh
the entries every month; they are team statements, not Wiz data.

#### Rule-level status and deferred rules (`rule_status`, `deferred_in_progress`)

`rule_status` entries (`{"id": "<rule id>", "status": "...", "next_step": "...", "source": "..."}`,
status at most 220 characters, optional `next_step` at most 200; at least one of the two) replace
the Current status text (and, with `next_step`, the Wiz-derived next step) for that in-progress
rule only, taking
precedence over `owner_status`. `deferred_in_progress` entries (`{"id": "<rule id>", "source":
"..."}`) leave a rule off the Work in Progress slides when the owner is not actively working it
this period; its findings stay in the in-progress counts as reported by Wiz. Both are team
statements, recorded in speaker notes, and must name an in-progress rule group.

#### Period cutoff (`backlog_as_of`)

Only changes up to the period end (the profile's snapshot day, 23:59:59 UTC) are
counted; anything later belongs to the next report. When collecting on or after
the snapshot day, build
`open`, `in_progress`, `resolved` and `accepted` with
`governance_data.cutoff_counts(rows, start, end)` from the complete issue export
(the same CSV used for the workbook, ideally with `Status Changed At`), build
groups only from issues counted that way, and set `period.backlog_as_of` and
`period.resolved_through` to the period end. `backlog_as_of` defaults to
`collected_through` and may never be later than the period end; snapshots that
break this rule are rejected. Issues closed after the cutoff count as open (their
earlier status is not in the export), and an issue moved to IN_PROGRESS after the
cutoff counts as open. Assignees are still the current Wiz assignees.

#### Informational findings

Informational findings are not tracked. Count objects may contain only
`CRITICAL`, `HIGH`, `MEDIUM` and `LOW`; collection does not need to query
Informational issues, and slides never mention them.

#### Missing assignees: history check and Wiz action list (`assignment_gaps`)

During approved read-only collection, check issue history for issues whose Wiz
**assignee field is empty** (`wizexpert/governance/assignment_history.py`).
The CLI consumes the prepared evidence; it does not perform this Wiz query:

1. Query the Issue > History data (portal GraphQL `issueHistoryEvents`, filter
   `issue: [ids]`, `dateTime.inLast` 730 days; up to 50 issue IDs per request) for
   every unassigned IN_PROGRESS issue and every unassigned in-period closure.
2. `suggest_owner()` returns the team member who most recently moved the issue
   to IN_PROGRESS or RESOLVED. Wiz system events (automatic resolve/reopen) are
   ignored, so automatic closures with no team activity remain excluded.
3. `find_gaps()` lists every unassigned IN_PROGRESS issue (with a suggested owner
   when history shows one) and every unassigned closure that history shows the
   team worked. The deck uses the history owner for those rows and records the
   basis; the gap list tells the team which assignees to correct in Wiz.

Store the result in the snapshot as `assignment_gaps` (`issue_id`, `rule_id`,
`rule_name`, `status`, `suggested_owner`, `suggested_owner_id`, `basis`,
`event_at`). `wizexpert governance deck` prints the actions after generation, and
`--actions-csv PATH` writes them as a CSV. After the assignees are fixed in Wiz,
recapture; the gap list should then be empty.

### Refreshing outputs

- Same month: capture fresh evidence, retain approved prior values and template,
  run with `--refresh`. Verify the archived prior deck and JSON.
- Next month: use the approved completed month's deck as template; copy its
  reviewed current metrics into the new snapshot's `prior` object and bind its
  new hash. If the previous deck was preliminary, do not treat it as EOD data.
- A template hash binds provenance, not approval of every number. Human review
  of prior values and narrative evidence remains mandatory.
- A `period.final_approval` records a specific approved early-final exception
  (`approved_by`, UTC `approved_at`, `reason`). It must never be inherited into a
  new month or used as evidence that later hours were collected. Retain the
  actual collection window and disclose the gap during release review.
- Inspect speaker notes and the companion JSON before sending externally;
  they contain confidential IDs and evidence.
- Test implementation changes with
  `python -m pytest tests/governance/test_governance.py -v`.
- Verify the complete prepared set with `wizexpert governance verify`, then
  complete the [runbook's manual release gates](GOVERNANCE-RUNBOOK.md).
