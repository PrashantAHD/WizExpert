# CSV-first finding coordination

This is a human-reviewed consulting workflow supported by CSV report
automation. ServiceNow is authoritative for approvals, changes, exceptions and
evidence. The CLI's local execution memory is not an authoritative approval
system. It does not send messages or execute cloud changes. Use approved internal
channels; keep operational evidence outside
the public repository.

## 1. Collect and reconcile evidence

Collect both issue-dashboard details and the associated Security Graph
relationships for the same finding. Use authorized read-only Wiz MCP tools
in an approved chat when available, or paired issue and graph exports.
Direct MCP retrieval is not implemented in the CLI. The existing CSV importer
still accepts optional issue enrichment for its supported schema; that alone
does not constitute completion of the two-source workflow.

Retrieve the equivalent of the selected custom columns, including relevant
identity, permission, resource and finding metadata. Verify whether saved UI
selections are available through the API; never assume they are. Do not retrieve
secret values or sensitive record samples merely to enrich a report.

Complete pagination and check for export limits or truncation. Retain query,
filters, status/project/account scope, observation times and selected fields
with private evidence. Preserve optional graph relationships. Match stable
cloud, graph and native identifiers, never display names. Deduplicate
relationships without discarding distinct access paths; distinguish issue,
unique-resource and graph-row counts. Explain count differences through scope
and relationship multiplicity rather than forcing the totals to match.

Missing fields, incomplete retrieval, ambiguous matches, conflicting facts and
unexplained differences must be recorded and resolved before validated analysis
or final reporting. Do not claim error-free collection or full coverage from a
sample page. See the README for the strict CLI import contract; other finding
categories require a reviewed case-specific process.

Collect the finding title/control, reported severity, observation times, exact
resource and cloud scope, ownership, permissions, exposure, dependencies,
existing safeguards and evidence of impact. Mark missing details unknown.
Keep native identifiers in approved private evidence, not public examples.

## 2. Explain and analyze

Separate observations, hypotheses and confirmed causes in the explanation.
Do not invent compromise, data loss or compliance breach.

Explain in plain English what is exposed, under which conditions it matters,
the plausible impact, and what remains unverified. An issue update timestamp
is not proof that older resource evidence was refreshed. Credential expiry
dates are factual technological constraints, not remediation SLAs.

Route review to the actual owners: CloudOps/Engineering for infrastructure,
IAM for identity controls, application/integration owners for usage and
dependency testing, and SecOps for risk, monitoring and incident response.
Team names do not establish individual authority. Follow incident response
and preserve evidence if active compromise is suspected.

## 3. Prepare the report and stakeholder email

Prepare a separate finding report from the reconciled evidence using the
supported report schema or a reviewed case-specific process. Do not force
unrelated finding types into the privileged-credential importer. Present
practical remediation options, dependencies and material trade-offs.

Write the visible report for stakeholders: use concise labels such as
`Wiz severity: Medium | Open issues: 10`, clear risk descriptions and specific
recommended actions. Avoid collection jargon such as "matched to model IDs",
"source rows" or "pagination" in the executive summary. Retain reconciliation,
field mappings, count caps and provenance in evidence notes. Keep material
qualifications on risk, pending approvals and draft status visible in plain language;
natural wording must not imply verified ownership, live checks or completed work.

Write in the reporting security team's voice, addressed to stakeholder recipients,
not as coaching for the report preparer. State findings, risk and a proposed
remediation, then request the owners' review or decision: for example,
"We recommend workload-specific permissions. Please confirm the preferred
approach and any business constraints." Keep internal stage numbers, evidence
collection tasks and ticket-routing reminders out of the stakeholder narrative;
retain them in the private tracker or evidence notes. A draft may still be written
for stakeholders without implying that it is approved or has been sent.
The cover has distinct purposes: the issue description explains the affected
resource/access relationship; the risk description explains conditional impact;
the recommendation proposes a change; the requested response addresses the
responsible stakeholders. Place collection dates in the header and counting
guidance, missing-enrichment reminders and workflow snapshots in cell notes.
Do not add those internal reminders back to the finding narrative during audits.
Express unconfirmed ownership or dependencies as a stakeholder review request,
not as coaching for the preparer; never claim they have been verified.
Use short, point-wise notes for cover observations, risks, recommendations and
requested responses, with one point per line rather than dense paragraphs.
Keep summary metrics compact and preserve full technical evidence in notes.
Verify wrapped text fits the row heights without unnecessary blank space.
Include an explicit **Risk Description**, not only a severity label or approval
caveats. Explain the observed exposure, the condition under which it could be
misused, the affected data or services and potential business impact. Distinguish
read, write and delete consequences where supported; qualify unverified effective
access and existing controls. Do not imply exploitation or a compliance breach
without evidence.

Initial reports omit **Blocker** and **Next Action/Next Step** columns. Use
**Pending review** in the remediation decision/status field until a stakeholder
response has been reviewed; keep the source Wiz lifecycle status separately.
Retain evidence limitations in notes and the cover rather than execution-tracking
columns. After a reviewed approval response, add those follow-up columns and
populate them only from the applicable scoped decisions. A ticket number, report
generation or workflow stage alone does not establish an approval response.
The `follow_up_columns` layout helper accepts an operator-reviewed response
reference for case-specific builders; it does not authenticate or grant approval.
The post-execution updater remains a separate follow-up process.

In case-specific reports, a role-name column may move to a cover highlight only
when every scoped resource has the same nonblank role name. Retain each distinct
role's stable/native IDs in resource notes; equal names across accounts do not
mean the same identity or permissions. Preserve the column for mixed or missing
names. Do not copy unrelated execution statuses from a reference template.

The **security team creates and assigns the ServiceNow ticket before outreach**.
Include its reference in the reviewed email; never ask stakeholders to create
or provide the ticket. Attach the Excel report and keep the message concise
and professional. Request the desired approach, not a promised completion
date. Do not invent remediation deadlines or SLAs.

Replace bracketed placeholders using approved internal information. Use the
exact closing below; select only practical options applicable to the finding.

```text
Subject: Review requested: [Finding summary] | SNOW: [Ticket number]

Hi Team,

Issue Description
[Plain-English summary and risk, without an unsupported compromise claim.]

Issue Details
SNOW: [Ticket number]
[Brief affected scope and validated observation; note material uncertainty.]
The attached Excel report contains the consolidated evidence for your review.

Recommended Remediation
1. [Preferred practical option and key dependency or access precheck.]
2. [Feasible alternative, including any material trade-off.]

Please review the attached report and confirm the desired remediation approach. Let us know if you need any assistance.

Best Regards,
[Security team]
```

Initial risk interpretation and outreach require human or approved chat review,
not an automated general-purpose analysis feature. For post-approval local-account
work, the [execution follow-up command](EXECUTION.md) can draft a factual update
from recorded completion, exclusions and blockers. It does not send the draft.
Send only through approved communication channels. Retain the email and response
references in ServiceNow.

## 4. Obtain stakeholder decisions and approval

Do not treat silence, a general preference or agreement on an approach as
authorization to change production. Record:

- The responding person, evidence of their authority and source reference.
- Exact accounts, credentials, VMs or integrations covered by each decision.
- Selected approach, permitted actions, exclusions and conditions.
- Dependencies, implementation owner and applicable change-control references.
- Unresolved questions that block action.

One finding may have mixed outcomes. For example, an authorized decision
may allow removal of selected unused accounts on specified VMs, retain a
legacy application identity and an FTP integration identity as accepted
business risk, and require no change to all other resources. These are separate
scope decisions, not blanket authorization to delete every reported identity.

For retained risk, record the source business rationale, authorized risk
owner and applicable exception process. Record process review/expiry dates
only when required by that process or explicitly supplied; do not invent
them. Where authorization is missing, acceptance remains proposed, not
approved. Retained risk is **not a technical fix**.

Correct: "Only the explicitly listed accounts are authorized for removal;
the remaining accounts are unchanged."

Incorrect: "The owner agreed to cleanup, so remove all inactive accounts."

## 5. Prepare remediation

Before implementation, obtain the applicable change authorization separately
from agreement on the desired approach. Use the actual configuration and
current official service documentation to prepare:

1. Exact resource scope and execution context, authorized operator and
   least-privilege access.
2. Current baseline, dependency inventory, health checks and recovery access.
3. Ordered changes, approved conditions/windows where supplied, stop criteria
   and application/integration testing.
4. Rollback steps, limitations and recovery for irreversible actions.
5. Post-change technical checks, monitoring and fresh Wiz reassessment.

Do not provide or execute a broad destructive command from a generic finding.
Resolve unknown native identifiers and dependencies first. Pause for renewed
authorization if scope or conditions change.
Check whether execution roles, identities or policies are shared so that
changing one finding's permissions does not unexpectedly affect other workloads.

### Account removal versus VM-wide SSH policy

Removing a specific account is account-scoped. Disabling password
authentication on a VM affects **all SSH users** on that VM; approval for
selected account removal does not authorize that VM-wide policy change.
Before any authentication-policy change, verify working key/certificate
alternatives, affected integrations, emergency access and a tested rollback.
Keep a verified recovery session or other approved recovery route available.

Correct: "Remove only approved accounts after dependency checks; evaluate
VM-wide password authentication separately with alternative access verified."

Incorrect: "Selected unused accounts can be removed, so disable password
authentication on every reported VM."

### Credential-specific cautions

- A graph `ACCESS_KEY.ID` is not necessarily the native cloud key ID.
  Verify the native target before preparing any operational command.
- Azure credential display names do not prove certificate versus secret.
  Verify the type, application dependencies and native credential reference.
  Tenant scope is not subscription scope.
- Active does not prove use; inactivity does not authorize deletion.
  `iam:*` represents broad IAM permissions, not all-service administration.
- AWS identities can have at most two access keys. Confirm free capacity
  before staging a replacement; do not delete a live key merely to make room.
  Cut over and test every dependent consumer before disabling/deleting the old
  key. Deletion is irreversible; a replacement and consumer reconfiguration
  are recovery, not restoration of the deleted key.
- Managed identity, workload identity or role federation can be longer-term
  improvements. Do not mandate an immediate redesign when a safe staged
  rotation or narrower scoped change addresses the approved need.

## 6. Execute approved changes

Only an approved operator implements the authorized plan. Retain before/after
evidence, timestamps, operator details, test outcomes and deviations in
ServiceNow. Start with a representative workload where feasible and validate
before expanding within the approved scope. Stop on unexpected failures or
scope differences; do not silently retry destructive operations.

## 7. Verify and reconcile results

Confirm the intended changes took effect. Obtain application-owner validation
and independent technical review, then reconcile a fresh Wiz rescan/reassessment
covering the changed scope when available. Missing reassessment evidence remains
outstanding, not proof of closure. The CLI does not perform or track Wiz scans.

Keep these states distinct:

**Desired approach agreed → change authorized → change applied →
independently validated → closure evidence confirmed.**

## 8. Report outcomes and close

Update the report and draft a concise completion/blocker summary. Close the
ticket only when the agreed closure criteria are met. Track deferred work,
unresolved exceptions and authorized risk acceptance explicitly.

An email approval alone is not an applied fix. A successful change alone is
not independently verified closure. A suppression, retained-risk decision or
accepted exception is not technical remediation. Record accepted risk using
the applicable process and distinguish it from resolved resources. Do not
claim a whole mixed-outcome finding was technically fixed when only a subset
was changed. Reappearing findings require fresh evidence and review.

## Tracker completion references

The optional `workflow` CLI stores a private, append-only sequence of progress
events in an external JSON file. It does not fetch evidence, inspect the
referenced files, verify approval authority, send notifications or close tickets.
Only record completion after human review of the applicable criteria above.
The local history is not tamper-proof and does not replace an authoritative
audit trail.

| Stage | Required `--evidence` keys | Reviewed evidence |
| --- | --- | --- |
| 1 | `issues`, `graph`, `field-coverage`, `pagination`, `reconciliation` | Both complete sources, selected-field equivalence, retrieval limits and stable-ID/count reconciliation. |
| 2 | `analysis`, `options` | Validated explanation, actual causes, practical options and dependencies. |
| 3 | `report`, `email-draft`, `ticket` | Reviewed report/draft and existing assigned security ticket. |
| 4 | `decisions`, `authorization` | Exact actions, scope, exclusions, conditions and applicable change authority. |
| 5 | `prechecks`, `dependencies`, `recovery`, `plan` | Current-state checks and reviewed implementation, test, stop and recovery arrangements. |
| 6 | `execution` | Operator results covering the approved scope, including failures and partial outcomes. |
| 7 | `technical-validation`, `owner-validation`, `wiz-reassessment` | Separate technical, functional and fresh Wiz evidence; missing evidence remains outstanding. |
| 8 | `closure` | Updated reporting and authoritative disposition against agreed closure criteria. |

For example, after actually completing and reviewing Stage 1:

```powershell
.\.venv\Scripts\python.exe -m remediation workflow record `
  --tracker "C:\PrivateReports\finding.workflow.json" --stage 1 --status complete `
  --summary "Both sources reconciled for the agreed scope." `
  --next-action "Explain the validated finding and remediation options." `
  --evidence "issues=C:\PrivateEvidence\issues.csv" `
  --evidence "graph=C:\PrivateEvidence\graph.csv" `
  --evidence "field-coverage=C:\PrivateEvidence\collection-review.txt" `
  --evidence "pagination=C:\PrivateEvidence\collection-review.txt" `
  --evidence "reconciliation=C:\PrivateEvidence\collection-review.txt"
```

References may be private file paths or authoritative ticket/evidence references;
do not use credential-bearing URLs. Each completion command supplies all gates
for that stage, even if an earlier progress entry recorded some of them.
The command requires the current stage number and advances exactly one stage.
Blocked entries need a blocker; resuming/completing requires an explicit update
without that blocker. No gate is satisfied merely by an example reference.
An authorized no-change/risk-acceptance path must have an explicit reviewed
disposition explaining non-applicable work, never fabricated execution evidence.
Workflow completion alone must not be labeled technical remediation.

Writes use atomic publication and a sibling exclusive `.json.lock` file.
Avoid concurrent writers. A stale lock after a process crash must be investigated
before removing that exact lock; never delete another writer's active lock.
Do not edit history to hide errors. Completed stages cannot be reopened by this
CLI; record a new reviewed follow-up scope/case linked to the prior record when
new evidence invalidates completed work. Keep authoritative decisions in ServiceNow.

Show the saved tracker in chat at stage changes or on request. It is not a
continuously updating UI widget. Record progress first and re-read the file
after restarting a session. The optional `--workflow` snapshot retains stage/status,
update time, case/scope and status detail in the Cover A21 cell note only, not
the visible stakeholder response request. Verify scope manually as well as the
enforced control-ID match.
Generating a report never advances the tracker. Stages 1-2 produce a draft
snapshot, not a claim of final validated analysis.

## Report maintenance

Organize private deliverables into one folder per issue or campaign, using a
control ID and short descriptive name where available. Keep its report, analysis,
email drafts, workflow tracker and evidence together; store shared client context
separately. This is an operator workflow convention, not automatic CLI routing.
On relocation, verify file hashes, update active generators and current sidecar
paths, and retain historical evidence paths with an explicit relocation map
rather than rewriting audit history. Never run remediation scripts while
organizing files. Keep all these folders outside the public checkout.

Keep source CSVs and approved decisions outside the workbook. Explicit
`--update --output` regenerates an existing tool-generated report in place
from CSVs, replacing manual edits rather than merging arbitrary Excel notes
or statuses. Close Excel before updating. Reports have exactly Cover,
AWS Data, Azure Data and Remediation; notes belong in the Remediation title
comment, not extra tabs. The report is consolidated evidence, not an embedded
archive of complete original CSVs.
