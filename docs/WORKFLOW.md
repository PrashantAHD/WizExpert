# CSV-first finding coordination

This is a human-reviewed consulting workflow supported by CSV report
automation. ServiceNow is authoritative for approvals, changes, exceptions and
evidence. The CLI's local execution memory is not an authoritative approval
system. It does not send messages or execute cloud changes. Use approved internal
channels; keep operational evidence outside
the public repository.

## Preparation continuity and completion check

For an authorized end-to-end assessment, continue through the available
read-only investigation and the requested deliverable set: internal analysis HTML,
client-facing assessment HTML, PDF versions of the analyses, Excel when useful,
and stakeholder email HTML. Do not generate duplicate `.txt` report or email
companions. An initial analysis or a list of next steps is a progress update,
not completion while actionable preparation remains. Respect narrower requests,
explicit pauses and scope changes. After a side question or factual correction,
resume the outstanding authorized work unless the user redirects it.

Unfinished policy, scope or dependency checks are tasks to pursue. Stop the
affected work only when a genuine access/evidence limitation, material decision,
explicit hold or approval requirement prevents safe progress. Explain exactly
what is missing, which output it blocks and what input is needed; continue
independent preparation where safe. Do not fill gaps with assumptions.

Incomplete evidence may support a clearly labeled draft requesting confirmation,
with material unknowns visible. It does not support validated analysis, final
reporting or completion of unmet tracker gates. Cloud-change approval is not
needed merely to continue already-authorized read-only preparation; preparing
an email or ticket draft does not authorize sending or creating it. Keep holds
specific to their case and scope, not global across unrelated active work.

Before ending the preparation task:

- Verify the requested files exist and open successfully. Validate HTML links,
  desktop/mobile presentation and text parity, and check workbook structure
  and content using the supported schema or reviewed case-specific process.
- Reconcile scope, counts, status observation dates, findings and recommendations
  across the outputs. Retain historical evidence unchanged; label later refreshes.
- Distinguish draft readiness from final assessment and approval. Do not advance
  tracker stages merely because later-stage drafts exist.
- Provide links to the actual deliverables with their draft/final status. For
  each missing output, identify the genuine blocker rather than presenting raw
  evidence files or an unexplained "not created yet" as the deliverable set.
- Persist reviewed progress, limitations and the next action before a necessary
  handoff. Do not imply background continuation unless a task is actually running.

Use [workflow-compliance QA](WORKFLOW-QA.md) to review these process requirements
against actual evidence and artifacts. The initial-email checker validates the
real HTML template, not just the preparer's claim. Semantic conclusions still
require an independent evidence-backed reviewer; this is not a guarantee that
an assistant cannot make a mistake or end a response early.

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
sample page. The local CLI supports only UTF-8 AWS/Azure privileged-credential
Security Graph CSVs, optionally enriched with matching issue exports. An issue
export alone is not supported. Use `python -m wizexpert --help` for local
options; other finding categories require a reviewed case-specific process.

Collect the finding title/control, reported severity, observation times, exact
resource and cloud scope, ownership, permissions, exposure, dependencies,
existing safeguards and evidence of impact. Mark missing details unknown.
Keep native identifiers in approved private evidence, not public examples.

### Read the rule and representative issue details

For each control, use Wiz's own explanation as a starting point rather than
reasoning only from its title or inventing a generic remediation narrative:

1. Retrieve the source rule definition/configuration where authorized and
   available. Identify the actual matching conditions, AND/OR branches, severity
   thresholds, relationship filters and optional enrichment. A title is not a
   substitute for the configured query; record unavailable configuration as unknown.
2. Initially select one or two underlying issues from the scoped inventory and
   open their details through approved read-only tools or review supplied UI
   evidence. Prefer meaningful differences in roles, accounts, services or access
   paths over two arbitrary first results. If only one issue exists, review it.
3. Collect the issue summary/description, investigation or attack-path narrative,
   linked resource/policy evidence and remediation recommendations/best practices.
   Keep source-rule text, observed graph/configuration data, AI-generated
   investigation and recommendations distinguishable. Record the issue ID,
   source reference, observation time and reason for sample selection privately.
4. Expand the sample when it reveals materially different policy causes,
   deployments, safeguards or remediation needs. One or two issues is an initial
   interpretation sample, not a fixed coverage limit or proof about all resources.
   Do not apply a sampled recommendation to an unreviewed configuration group.
5. Record unavailable sections and use approved exports or user-provided
   screenshots when necessary. Never invent API field equivalence or claim that
   a supplied screenshot was retrieved live.

Sampling enriches interpretation; it never replaces complete scoped inventory,
pagination, stable-ID matching or count reconciliation. A newer sampled issue
status/assignee is a dated observation for that issue, not an automatic refresh
of the whole report. Reconcile source differences before revising aggregate
counts or claiming current configuration.

This is an approved-chat/operator collection strategy, not a new Wiz API feature
in the CSV CLI.

## 2. Explain and analyze

Separate observations, hypotheses and confirmed causes in the explanation.
Do not invent compromise, data loss or compliance breach.

Explain in plain English what is exposed, under which conditions it matters,
the plausible impact, and what remains unverified. An issue update timestamp
is not proof that older resource evidence was refreshed. Credential expiry
dates are factual technological constraints, not remediation SLAs.

### Combine Wiz guidance with configuration-aware reasoning

Use the rule intent and sampled issue content to focus the analysis, then test
each material claim against the reconciled evidence and applicable cloud-service
behavior. Wiz AI-generated investigation is a hypothesis to evaluate, not
independent proof of exploitation, effective access, business criticality or
legal obligations. For example, adversarial model inputs alone do not establish
AWS access, `iam:PassRole` is not `sts:AssumeRole`, and a production-like name
does not establish business impact.

For each relevant Wiz recommendation, record a concise private disposition:
**adopt**, **adapt**, **omit** or **defer**, with the evidence/condition and reason.
Adopt applicable guidance; adapt it to supported service operations, shared
dependencies, required access and change controls. Omit duplicate safeguards or
irrelevant generic advice only when justified. Defer recommendations requiring
unconfirmed dependencies or a separate approved change. Existing logging may
remove a duplicate "enable logging" action, but does not prove complete event/
alert coverage or resolve excessive permissions.

The resulting recommendation must explain the observed cause it addresses and
preserve business-required operations, not blindly repeat a generic "inference
only" or "remove permissions" instruction. Consult current official documentation
when service behavior or implementation details need verification. Do not add
unrelated best practices merely to lengthen the assessment.

Carry the same reviewed findings and decisions into the internal analysis,
client-facing assessment, workbook and email. The learning page may explain why guidance was adapted; stakeholder
outputs receive the concise applicable recommendation and requested decision,
not the internal disposition checklist. Cutting noise must never remove material
uncertainty, draft status, risk qualifications or approval requirements.

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

Wiz monitoring, issue tracking, rechecks, status reconciliation and security
closure verification belong to the reporting operator. Keep those tasks in
internal analysis, private trackers and evidence checklists, not client-facing
recommendations, Excel action/closure requests or stakeholder emails. Do not
include a "verify and track in Wiz" step or narrate the internal responsibility
assignment to clients. Client owners supply remediation decisions, authorized
implementation, functional validation and completion/change evidence. Their
completion message does not replace the operator's independent verification.
Preserve factual Wiz findings, source status and material risk qualifications.
Case-specific generators must separate these audiences consistently across
HTML, PDF and Excel.

Present **Recommended Remediation Approaches**, not a staged plan or internal
execution checklist. Explain when each approach applies and which controls are
complementary rather than alternatives. Request confirmation of the chosen
approach and whether stakeholders will implement it through their approved
process or explicitly authorize the reporting team to implement the agreed
scope. Selecting an approach alone does not authorize execution.

Keep detailed evidence qualifications, collection limitations, scanner
discrepancies and open investigation questions in internal analysis/private
evidence. Do not include a lengthy "Evidence qualifications and open questions"
section in client reports. Preserve material uncertainty in concise natural
wording beside the relevant finding or recommendation, including unverified
exploitability or configuration freshness where they affect the decision.

The cover has distinct purposes: the issue description explains the affected
resource/access relationship; the risk description explains conditional impact;
the recommendation proposes a change; the requested response addresses the
responsible stakeholders. Place collection dates in the header and counting
guidance, missing-enrichment reminders and workflow snapshots in cell notes.
Do not add those internal reminders back to the finding narrative during audits.
Express unconfirmed ownership or dependencies as a stakeholder review request,
not as coaching for the preparer; never claim they have been verified.
Use point-wise cover observations, risks and requested responses rather than
dense paragraphs. Give each numbered remediation option enough detail to explain
its practical approach and material prerequisites; keep resource-row actions concise.
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
or provide the ticket. Name the actual selected report attachment (PDF for a
PDF-only case; Excel only when included) and keep the message concise
and professional. Request the desired approach, not a promised completion
date. Do not invent remediation deadlines or SLAs.

Replace bracketed placeholders using approved internal information. Use the
exact closing below; select only practical options applicable to the finding.

```text
Subject: Review requested: [Finding summary] | SNOW: [Ticket number]

Hi Team,

### Issue Description:
[Plain-English summary and risk, without an unsupported compromise claim.]

### Issue Details:
SNOW: [Ticket number]
[Brief affected scope and validated observation; note material uncertainty.]
[Wiz control ID | Actual Wiz issue ID, for each in-scope issue when available.]
The attached [assessment PDF / Excel report, as selected] contains the findings for your review.

### Recommended Remediation Approaches:
1. [Preferred practical option and key dependency or access precheck.]
2. [Feasible alternative, including any material trade-off.]

Please review the attached report and confirm the desired remediation approach. Let us know if you need any assistance.

Best Regards,
[Security team]
```

Render the three section titles as level-three headings with trailing colons
(`<h3>` in HTML, not literal `###` text).
Control IDs identify rules, not individual issue instances. Preserve that
distinction in the email. Keep unresolved ticket references visibly pending in
drafts; obtain the Security-owned reference before outreach rather than inventing
one. Case-specific generators must retain these headings and the approved
closing while honoring the selected attachment and execution-approval wording.

Initial risk interpretation and outreach require human or approved chat review,
not an automated general-purpose analysis feature. For post-approval local-account
work, the [execution follow-up command](EXECUTION.md) can draft a factual update
from recorded completion, exclusions and blockers. It does not send the draft.
Send only through approved communication channels. Retain the email and response
references in ServiceNow.

### Concise stakeholder update replies

For an acknowledgement of a stakeholder response, do not repeat the initial
email's full issue description, risk explanation, attachment list and remediation
options. Acknowledge active use and reported safeguards, then briefly state the
review or decision awaited. Do not request duplicate controls or treat reported
controls as independently verified.

Use "We will await your further permission review" rather than "remediation on
hold" when the issue system has no such status. A private pause in execution is
not a lifecycle-status change. Follow the confirmed client process for accepted
risk; do not assume that every system exposes the same labels or API values.
Where the process uses Accepted Risk / Ignored, a suitable reply is:

> Thank you for confirming active use and the existing security controls.
>
> We will await your further permission review. If the current access needs to
> be retained, we will mark the applicable issues as Accepted Risk / Ignored once
> risk acceptance is approved.

Active use, existing safeguards or a promise to review permissions does not
constitute risk acceptance. Retain the rationale, authorized decision and exact
scope under the approval process below. Drafting or approving email wording
does not authorize sending, changing issue statuses or declaring remediation.
Keep the email HTML aligned with the reviewed findings and decisions.

### Internal analysis, client assessment and email companions

Use the same private preview wrapper for every email draft, including initial,
progress, blocker and closure messages:

- Dark navy header with the uppercase label **PRIVATE COMMUNICATION DRAFT**.
- Descriptive communication title and a pale gold badge:
  **Draft - not sent | \<draft date\>**.
- A pale gold notice below the header:
  **Internal preparation note - do not copy into email:** Confirm named
  recipients and the Security-owned ServiceNow reference before outreach.
  Attachment identities must be confirmed when sending.
- A separate copyable email body containing the greeting, applicable template
  sections and approved signature. The header and preparation notice are local
  preview content, not part of the stakeholder email.

The badge date identifies draft preparation, not a new evidence observation.
Never use it to relabel old findings as freshly verified. Keep the wrapper
self-contained, responsive and free of external assets.

Prepare internal analysis, a separate client-facing assessment, and all initial,
progress, blocker and closure email drafts as standalone private HTML pages.
Provide PDF versions of the analyses; do not create duplicate `.txt` companions.
Validate PDF content directly against visible HTML extracted in memory.
Preserve raw evidence, logs and historical archives rather than broadly deleting
text files. This is an operator/approved-chat deliverable convention; the CLI's
execution follow-up command still produces plain text on stdout, not automatic
HTML. Console output is not a requirement to save a `.txt` attachment.

Analysis pages are an internal learning channel, distinct from stakeholder
communications. Explain the finding with a short overview, clearly labeled
metrics, resource/access diagrams, observed-versus-hypothetical distinctions,
practical options and expandable evidence or knowledge checks. Preserve the full
source analysis and material caveats. Visuals must not imply a proven attack,
live usage, additive relationship counts or authorization.

The client-facing assessment is a separate, concise decision document, not a
renamed internal analysis. Include the executive summary, affected scope and
observation date, verified finding, qualified business risk, practical remediation
options, compatibility/testing/rollback considerations and requested stakeholder
decisions. Link the actual workbook by a relative path and keep it alongside the
HTML when sharing, or refer clearly to the separately attached report. Do not
link internal analysis, raw evidence or workflow trackers from the client page.
Keep material limitations visible in stakeholder language, such as "Enforcement
selection depends on the workload's API path and model compatibility," rather
than exposing collection/debugging notes or removing the uncertainty altogether.
Preserve the internal analysis unchanged when preparing the client version.
Use self-contained, print-friendly HTML; verify print layout as well as screen
rendering. Client-ready means suitable for stakeholder review, not completed
effective-access validation, change authorization or permission to send.
Incomplete assessments remain review drafts and existing outreach gates apply.

Email pages keep the concise stakeholder body separate from internal review
instructions, subject and routing metadata. Use consistent inline font, spacing
and alignment for copying into an HTML email. Retain the approved sender voice
and signature in new drafts. For historical format conversions, preserve original
wording, figures, signatures and dates, label the snapshot historical and do not
silently update its status. Flag unavailable attachments rather than linking
nonexistent files.

Keep pages in the relevant private issue folder, with no remote assets, analytics
or scripts by default. Escape source content; verify text parity and local links,
and check desktop/mobile browser rendering. Distinguish presentation dates from
evidence dates. This adds companion pages, not workbook tabs or a web application.

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
.\.venv\Scripts\python.exe -m wizexpert workflow record `
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

`--footer "<line>"` sets the left page footer on every workbook tab (default
`Confidential - internal review`), for example an organization's required
confidentiality line. Keep organization-specific wording in private
instructions and pass it explicitly; it must be one plain line without `&`.
Apply the same line to HTML footers and every PDF page (for example print CSS
`@page{@bottom-center{content:"<line>"}}`) when your conventions require it.

## Report maintenance

Place detailed, numbered remediation options and material prerequisites on the
Cover. Keep inventory and pending-status row actions concise and relevant to
each resource; expanding the Cover does not authorize repeating all options in
every row. Preserve existing concise wording unless row-level detail is
requested. Keep the Cover, row actions, client assessment and email consistent
without requiring identical length. On content changes, verify wrapped text,
row heights and native Excel rendering; preserve evidence notes, links, statuses
and unrelated formatting.

Organize private deliverables into one folder per issue or campaign. For a
control-specific case, use `<Short-Descriptive-Topic>-<Control-ID>` once the rule's
purpose is verified; replace a temporary generic name before delivering links,
without waiting for a separate naming request. For example, the synthetic
`Model-Guardrails-wc-id-0000` is recognizable and traceable, unlike
`Rule-wc-id-0000`. Preserve existing user-chosen descriptive names. Keep the
report, analysis, email drafts, workflow tracker and evidence together; store
shared client context separately. This is an operator/assistant workflow
convention, not automatic CLI routing.

On relocation, refuse destination collisions, verify file hashes and link
targets, and update active generators, validators, current tracker/sidecar paths
and local deliverable links. Retain historical evidence paths with an explicit
private relocation map rather than rewriting audit history. If an open workbook
or another application locks the folder, ask the user to save and close the
affected file before retrying; do not force-close applications or bypass the
lock through copy-and-delete. Never run remediation scripts while organizing
files. Keep all these folders outside the public checkout.

Keep source CSVs and approved decisions outside the workbook. Explicit
`--update --output` regenerates an existing tool-generated report in place
from CSVs, replacing manual edits rather than merging arbitrary Excel notes
or statuses. Close Excel before updating. Reports have exactly Cover,
AWS Data, Azure Data and Remediation; notes belong in the Remediation title
comment, not extra tabs. The report is consolidated evidence, not an embedded
archive of complete original CSVs.
