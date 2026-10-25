---
description: "Use when investigating Wiz findings, preparing analysis, Excel reports and stakeholder emails, tracking approvals or performing safe production remediation"
applyTo: '**'
---

# Durable project working rules

These instructions preserve reusable project conventions, not operational
case records or a guarantee of global cross-session memory. Keep all examples
generic. Never put private evidence, personal identifiers, credential material
or real operational identifiers into public source, tests or documentation.
Use synthetic fixtures and approved external locations such as
`C:\PrivateEvidence\graph.csv` and `C:\PrivateReports\finding.xlsx`.

## Product boundaries

- Preserve a local CSV-first CLI: `python -m wizexpert`,
  `python -m wizexpert.csv_report` and installed `wizexpert` must
  reach the same reporting interface. Runtime dependencies: openpyxl and
  defusedxml for hardened workbook XML reads;
  Python minimum: 3.12.
- Governance reporting (`wizexpert governance ...`, source in
  `wizexpert/governance`) is an optional extra (`.[governance]`: python-pptx,
  Pillow, rich, questionary); core commands must never import it. Client rules
  come from a private client profile, never from source. Keep `openpyxl` pinned
  to defusedxml (`OPENPYXL_LXML=False` in `wizexpert/__init__.py`) because the
  extra installs lxml.
- Preserve the legacy `remediation` module aliases, `cloud-remediations`
  command and support for pre-rename workbooks. New source belongs in
  `wizexpert`; aliases must delegate rather than duplicate implementation.
- Do not restore a browser app, Flask/Waitress, routes, templates, SQLite
  case history or approval tracking. Leave existing external private artifacts
  untouched. No email sending, ServiceNow/Wiz API calls or cloud execution
  in the current CLI. Authorized read-only Wiz MCP collection may be performed
  through approved chat tools; do not claim it is implemented in the CLI.
- Describe interpretation, stakeholder email drafting and response translation
  as human/approved-chat work, not automated general AI capabilities.
  ServiceNow is authoritative for approvals, changes, exceptions and evidence.

## Preparation continuity and completion

- For an authorized end-to-end finding assessment, continue through available
  read-only investigation, internal analysis HTML, client-facing assessment HTML,
  Excel report and stakeholder email HTML, with the required text companions.
  Do not stop at an initial analysis
  or a "next steps" list while actionable preparation remains. Respect narrower
  requests, explicit pauses and changes of scope; a question alone does not
  authorize new work.
- Unfinished checks are work to perform, not automatically blockers. Resolve
  them using authorized tools and evidence. If access, evidence or a material
  user decision genuinely prevents progress, identify the exact dependency,
  affected deliverable and required input. Continue independent preparation
  where safe; never invent facts or substitute unsupported final conclusions.
- Keep incomplete outputs explicitly draft. A request for stakeholder
  confirmation may be prepared with visible unknowns, but cannot satisfy missing
  evidence gates or become a validated final assessment. Follow
  `docs/WORKFLOW.md` for the preparation completion check.
- Cloud-change approval gates execution, not already-authorized read-only
  analysis or draft preparation. Drafting does not authorize sending an email,
  creating a ticket, mutating Wiz or changing cloud resources.
- Keep holds tied to the specific case and scope. Do not apply one case's
  approval wait to another active case. Preserve tracker gates; output creation
  is not stage completion, stakeholder approval or finding resolution.
- Before ending a preparation task, verify each requested deliverable exists,
  opens successfully and agrees on scope, counts, status observation dates,
  findings and recommendations. Provide links and draft/final status, or state
  the genuine blocker for each missing output. Evidence files are not substitutes
  for the requested deliverables.
- After a side question or correction, resume outstanding authorized work unless
  the user pauses or redirects it. Persist current progress and blockers before
  a necessary handoff; do not imply work continues in the background unless an
  actual task is running. These are assistant guidance, not runtime enforcement.

## Evidence contract

- For each control, review its actual rule configuration when available and
  initially open one or two representative underlying issues for the summary,
  investigation/attack path, linked evidence and remediation best practices.
  Expand for materially different configurations; this interpretation sample
  never replaces full inventory reconciliation or authorizes generalization.
- Preserve private source references, observation times and sample rationale;
  distinguish rule text, graph/configuration observations, AI-generated
  investigation and recommendations. Supplied UI evidence is not a live fetch,
  and a newly observed sample status does not refresh all report counts.
- Accept one or more UTF-8/BOM graph CSV paths only for the supported AWS/Azure
  privileged-credential schema. Do not claim arbitrary Wiz CSV support.
- Optional `--issues` is a repeatable path flag. Issue CSV alone is unsupported.
  Enrichment requires one nonempty Control ID and exactly one matching issue
  per graph identity, verified using cloud, vertex ID and native identity
  ID. Names are never join keys.
- Derive verified title/control/severity/status/links from matched issues;
  reject contradictory explicit overrides. Without issue evidence, title,
  severity and rule ID are supplied context, not verified issue metadata.
- Group by cloud + principal ID + credential ID + scope ID. Separate graph
  row, identity, credential, credential-scope and issue counts. Deduplicate
  permission/access-array members; reject conflicting facts.
- UTC `--as-of` controls date calculations, defaulting to today, not evidence
  freshness. Newer issue `UpdatedAt` cannot refresh older graph observations.
- Graph `ACCESS_KEY.ID` need not be a native key ID. Azure names do not
  establish secret versus certificate. Tenant does not mean subscription.
  Active does not mean in use. Inactive does not mean approved for deletion.
  `iam:*` does not automatically mean all-service administrator access.

Correct: "Several graph relationships describe one credential; issue count
comes from verified issue evidence."

Incorrect: "Every CSV row is a separate issue and matching names prove identity."

## Report contract and validation

- Include a point-wise Risk Description covering the observed exposure, misuse
  conditions, affected data/services and potential business impact. Qualify impact
  by effective permissions and existing controls; severity and approval caveats
  alone are not a risk description. Never invent exploitation or a breach.
- Use natural, stakeholder-facing wording across the cover, tables, recommendations
  and empty-state messages. Put matching, pagination, API mappings and collection
  mechanics in evidence notes, not the executive summary. Keep material risk qualifications,
  draft status and approval requirements visible in plain language. Do not imply
  manual authorship, live verification or confirmed facts that the evidence does
  not support.
- Write as the reporting security team addressing stakeholders, not as an
  assistant advising the report preparer. Present findings, our proposed
  remediation and the review or decision requested from owners. Keep internal
  stage numbers and ticket-routing reminders in private tracking/evidence notes,
  not the stakeholder narrative. Do not invent recipients, approvals or completed
  outreach.
- Initial reports omit Blocker and Next Action/Next Step columns. Remediation
  status starts at Pending review; source Wiz lifecycle status stays separate.
  Add follow-up columns only after an operator-reviewed stakeholder approval
  response, not merely a ticket reference or stage change. Use
  `csv_layout.follow_up_columns` in case-specific builders. It validates a
  reference's presence, not the underlying authority or permitted actions.
- For a user-approved case-specific layout, move a uniformly nonblank role name
  from repeated rows to a cover highlight. Preserve distinct role/native IDs in
  resource notes and explicitly distinguish same-name roles across accounts.
  Mixed/missing role names retain the column.
- Preserve exactly Cover, AWS Data, Azure Data and Remediation, with
  nine-column cloud tables and complete literal permission values. No extra
  Analysis, archive, hidden-detail or status tabs. Notes use a comment on the
  Remediation title. Keep valid Wiz hyperlinks without formulas or external
  workbook links. Do not embed complete original CSVs.
- Preserve input evidence read-only. Output must be an absolute `.xlsx`
  outside the checkout; the Windows default is
  `%LOCALAPPDATA%\WizExpert\reports` with dated unique names.
- Group private deliverables by issue/campaign, keeping reports, analysis, email
  drafts, trackers and evidence together; keep shared client context separate.
  Update active path references on moves, verify hashes, and retain a relocation
  map for historical paths without rewriting original audit evidence.
- Never overwrite by default. `--update` requires an explicit existing
  tool-generated workbook path. Regenerate all four tabs from validated CSVs;
  warn that manual edits are replaced, not merged. Keep approved decisions
  outside Excel. Close Excel first; report locked-file failures clearly.
  Validate before atomic replacement, preserve the existing file on failure
  and do not create versioned reports for explicit in-place updates.
- Match the generic design specification independently of private workbooks.
  For an A2 freeze pane, reset the selection to `pane="bottomLeft"`,
  `activeCell="A2"` and `sqref="A2"`; a stale selection can break Excel display.
  An openpyxl reload alone is insufficient to validate layout changes.
  Include actual Excel rendering/opening checks and disclose when unavailable.

Correct: "Regenerate the existing report from source CSVs after preserving
approved decisions in ServiceNow; manual workbook edits will be replaced."

Incorrect: "Update silently preserves every handwritten status and adds
supporting tabs or another versioned workbook."

## Consulting sequence and email

Use the user's confirmed cloud-to-team routing from private client context.
Do not infer the primary coordination team from a finding's technical subject:
an IAM-related finding does not automatically make IAM the primary recipient.
Include supporting owners as needed; keep client-specific routing outside the
public repository, and distinguish coordination from change authorization.

Follow the eight stages in README and `docs/WORKFLOW.md`:

1. Collect both issue-dashboard and Security Graph evidence, through authorized
   read-only MCP tools or paired exports. Verify selected-column equivalents,
   pagination, scope and timestamps; join stable identifiers, deduplicate
   relationships and reconcile counts. Missing or conflicting evidence blocks
   validated analysis and final reporting. Do not imply the CLI has MCP support.
2. Explain validated findings and analyze actual causes and practical options.
3. Prepare the finding report and concise stakeholder email. Security creates
   and assigns the ServiceNow ticket before outreach.
4. Record stakeholder decisions, exact scope, exclusions and authorization.
5. Prepare current-state prechecks, dependency tests, recovery and rollback.
6. An approved operator executes only authorized changes with stop criteria.
7. Verify technical results, owner functionality checks and fresh Wiz evidence
   when available; execution, validation and finding resolution are distinct.
8. Update reporting and close only against agreed criteria; retain blockers,
   deferrals and authorized risk acceptance explicitly.

These are consulting stages, not eight automated product features. The CSV
importer's optional issue enrichment remains backward compatible; it does not
waive the two-source evidence requirement for the complete consulting workflow.

Use `python -m wizexpert workflow` for an optional external private JSON
progress tracker, not a new approval system. Read its persisted state before
showing progress at a stage transition or on request; do not repeatedly display
it after routine messages. Include current stage, completion/blocker information,
last-updated time and next action. Write reviewed progress before announcing it.
Complete a stage only after checking all required evidence/approval references;
the CLI validates their presence, not their truth or authority. Never advance
because a later stage was discussed or a report was generated. Keep separate
trackers for distinct scopes of the same control. Tracker records and report
cover cell-note snapshots are not technical remediation or live Wiz closure evidence.
The optional CSV report `--workflow` flag must match the control; also review
scope manually. Store snapshots in cell notes, never visible workflow banners;
local-account execution evidence memory remains separate.

The email must include "Hi Team," or the confirmed coordinating team's greeting,
Issue Description, Issue Details, the Security-owned ticket reference (or an
unresolved placeholder in drafts), the attached Excel report, concise
Recommended Remediation options and the user's approved signature. Use
first-person plural and request the review/approval appropriate to the phase:

Please review the attached report and confirm the desired remediation approach. Let us know if you need any assistance.

When scoped approval is requested, ask which changes are approved and which
access must remain unchanged. Do not assign implementation/testing to the
reviewing team when the user is the expected authorized operator. Keep detailed
testing and rollback in post-approval planning, and account for user-confirmed
existing safeguards rather than requesting duplicate implementation.
Never ask stakeholders to create/provide the ticket, promise remediation dates
or invent SLAs/deadlines. Technical expiry dates are facts, not SLAs.
Use the complete template in `docs/WORKFLOW.md`.

## Learnings

- Keep stakeholder update replies brief: acknowledge confirmed active use and
  reported controls, then state the review or decision awaited without repeating
  the initial assessment or recommending duplicate safeguards.
  Use "We will await your further permission review," not "remediation on hold"
  when no such issue-status option exists; private work pauses are separate
  from tool lifecycle statuses.
  Where the confirmed client process uses Accepted Risk / Ignored, make that
  outcome conditional on authorized risk acceptance for the applicable scope,
  never on active use or a promised review alone.
  For example: "If the current access needs to be retained, we will mark the
  applicable issues as Accepted Risk / Ignored once risk acceptance is approved";
  drafting this reply does not authorize a status mutation or establish a fix.
- Keep detailed, numbered remediation options and material prerequisites on the
  workbook Cover; retain concise, resource-relevant actions in inventory and
  pending-status rows rather than copying every option into every record.
  For example, expand the Cover's recommendation section while preserving the
  existing short row action unless the user explicitly requests row-level detail.
  Keep both levels consistent and validate wrapping, row heights and native
  Excel rendering without changing evidence, statuses or unrelated formatting.
- Prepare a separate client-facing assessment HTML/text pair alongside the
  internal analysis, concise email and detailed workbook; do not replace or
  expose the internal learning page as the client attachment.
  Include an executive summary, dated scope, verified finding and qualified
  risk, practical options, operational safeguards and requested decisions,
  retaining material evidence limitations in stakeholder language.
  Exclude debugging, workflow-stage labels, raw evidence dumps and internal
  links; use self-contained, print-friendly HTML and verify desktop/mobile,
  print rendering, text parity and any workbook link.
  "Client-ready" means suitable for stakeholder review, not final validation,
  approved remediation or permission to send; preserve draft and outreach gates.
- Name each new private case folder `<Short-Descriptive-Topic>-<Control-ID>`
  once the rule's purpose is verified, replacing a temporary generic folder
  before delivering links without waiting for a separate naming request.
  For example, use the synthetic `Model-Guardrails-wc-id-0000`, not
  `Rule-wc-id-0000`: the topic makes the case recognizable and the ID keeps it
  traceable; preserve existing user-chosen descriptive names.
  On rename, refuse destination collisions, update active generators,
  validators, tracker references and local links, retain a private relocation
  map for historical paths, and verify hashes and link targets.
  If Excel or another application locks the folder, ask the user to save and
  close the affected file before retrying; never force-close their application
  or bypass the lock by copying and deleting the folder.
- Ground analysis in Wiz's configured rule and representative issue guidance,
  then refine it using verified permissions, cloud-service behavior and operating
  constraints rather than copying AI-generated attack claims as facts.
  Privately classify relevant recommendations as adopt/adapt/omit/defer with a
  reason; for example, omit duplicate logging setup when confirmed present,
  without claiming full coverage or that logging fixes excessive permissions.
  Keep the resulting HTML analysis, report and email aligned, removing irrelevant
  advice but retaining material caveats and scoped approval requirements.
- Produce private analysis companions and initial, progress, blocker and closure
  email drafts as standalone local HTML pages, retaining plain-text companions.
  Analysis is an internal learning channel: use evidence-backed diagrams,
  labeled counts, explanations and expandable details; emails remain concise,
  first-person and copyable with consistent inline formatting.
  Preserve historical facts/dates on format-only conversions and label them
  historical rather than implying a new assessment or status update.
- Keep HTML free of remote assets, analytics and scripts by default; escape
  source text and validate content parity, local links and desktop/mobile
  rendering. For example, an access diagram must distinguish an observed
  relationship from a hypothetical attack, and HTML preparation dates must
  never silently replace evidence dates.
- Use first-person plural for the sender's recommendations in emails and reports:
  "We recommend..." and "our review," not "Security recommends..." or "the security
  team recommends..." as though describing a third party. Keep attribution to
  Wiz for Wiz observations, and do not claim verification or actions not performed.
- Stakeholder narrative and internal evidence review are separate output channels:
  findings explain the resource/access relationship and impact, while requested
  responses address the coordinating team. Correct: "Please confirm required
  access"; incorrect in an issue summary: "Ownership enrichment is incomplete;
  do not sum repeated rows." Keep counting guidance and review reminders in
  cell notes, dates in the header, and conditional risk qualifications visible;
  regression-test this separation after rendering and regeneration.

Correct: "Security has created and assigned the ticket; please confirm the
desired option for the listed scope."

Incorrect: "Please create a ticket and promise all resources will be fixed
by our assumed deadline."

## Authorization and mixed outcomes

- Approach agreement is not change authorization, authorization is not an
  applied fix, and an applied fix is not independently verified closure.
  Silence is not approval. Confirm authority, source references and conditions.
- One finding may authorize selected accounts/VMs only, retain legacy
  application or FTP identities as accepted business risk, and leave others
  unchanged. Record each outcome separately; retained risk is not a fix.
- Capture the source business rationale and authorized risk owner under the
  applicable process. Include review/expiry dates only if required or supplied.
- Account removal is account-specific. VM password-authentication disablement
  affects all SSH users. Verify key/certificate alternatives and recovery
  access before proposing that separately authorized VM-wide change.
- Confirm native targets, dependencies, least-privilege operator access,
  baseline, tests, stop criteria and rollback before implementation. AWS
  staged rotation must respect the two-key maximum and verify free capacity.
  Cut over dependent consumers before deletion. Distinguish reversible
  disablement from irreversible deletion and replacement-based recovery.
- Managed identity/role federation are longer-term options, not mandatory
  immediate redesigns. Never infer compromise without evidence.

Correct: "Only selected accounts are authorized for removal; retained
integration identities follow accepted-risk records; other resources stay unchanged."

Incorrect: "Approval to remove some accounts permits disabling password
authentication across every VM, and accepted risk means technically fixed."

## Publication and verification

- Keep all evidence and reports outside the public checkout. Never weaken
  the guard for private data or secret-shaped examples. Construct synthetic
  sensitive test patterns at runtime instead of storing complete patterns.
- Before every push, inspect new/untracked files, staged changes and outgoing
  history, then run offline guard, pytest, Ruff and Bandit through
  `python scripts\verify.py`. The default guard excludes untracked files;
  do not claim they were scanned. Run verification again after staging.
- The dependency metadata audit is outbound and opt-in; enabling the local
  push hook opts normal pushes into it. Follow `docs/PUBLICATION.md`.
  Do not bypass PowerShell execution policy: use the Python gate.
- Do not commit or push unless explicitly requested. Verification and
  instructions cannot guarantee absence of private data or enforce approvals.
- Prioritize future validated finding adapters, an approved-decision CSV
  sidecar without new tabs, evidence deltas and broader layout regressions.
  Document these as roadmap items until implemented.
