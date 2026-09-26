# CSV-first finding coordination

This is a human-reviewed consulting workflow supported by CSV report
automation. ServiceNow is authoritative for approvals, changes, exceptions and
evidence. The CLI does not store approvals, send messages or execute cloud
changes. Use approved internal channels; keep operational evidence outside
the public repository.

## 1. Discover, validate and explain

Start with Wiz discovery and the supported graph CSV evidence. Optionally
enrich it with matching issue exports for the same finding. Do not infer
issue counts from graph relationships or join by resource display names.
See the README for the strict import contract; other finding categories
require human review rather than pretending the importer supports them.

Collect the finding title/control, reported severity, observation times, exact
resource and cloud scope, ownership, permissions, exposure, dependencies,
existing safeguards and evidence of impact. Mark missing details unknown.
Keep native identifiers in approved private evidence, not public examples.
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

## 2. Security ticket and stakeholder email

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

Interpretation and email drafting happen through human or approved chat
review, not an automated general-purpose analysis feature. Send only through
approved communication channels. Retain the email and response references
in ServiceNow.

## 3. Translate the response into exact decisions

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

## 4. Authorized plan, dependency tests and rollback

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

## 5. Implement, validate and close

Only an approved operator implements the authorized plan. Retain before/after
evidence, timestamps, operator details, test outcomes and deviations in
ServiceNow. Obtain application-owner validation and independent technical
review, then a fresh Wiz rescan/reassessment covering the changed scope.

Keep these states distinct:

**Desired approach agreed → change authorized → change applied →
independently validated → closure evidence confirmed.**

An email approval alone is not an applied fix. A successful change alone is
not independently verified closure. A suppression, retained-risk decision or
accepted exception is not technical remediation. Record accepted risk using
the applicable process and distinguish it from resolved resources. Do not
claim a whole mixed-outcome finding was technically fixed when only a subset
was changed. Reappearing findings require fresh evidence and review.

## Report maintenance

Keep source CSVs and approved decisions outside the workbook. Explicit
`--update --output` regenerates an existing tool-generated report in place
from CSVs, replacing manual edits rather than merging arbitrary Excel notes
or statuses. Close Excel before updating. Reports have exactly Cover,
AWS Data, Azure Data and Remediation; notes belong in the Remediation title
comment, not extra tabs. The report is consolidated evidence, not an embedded
archive of complete original CSVs.
