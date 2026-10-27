# Workflow compliance QA

Workflow QA asks **whether the preparer followed the prescribed process**.
It is separate from report arithmetic, Office replay, security review and
publication approval. It checks recorded actions and artifacts, not hidden
reasoning. Zero mistakes cannot be guaranteed.

## Gates

| Phase | Before proceeding | Required review |
|---|---|---|
| Collection | Bulk Wiz pagination | Scope/authorization, prior evidence reuse, query plan/cost, lifecycle coverage and approved prior sources |
| Generation | Building the reviewed report set | Collection coverage, conflicts, exceptions, dates, historical preservation and attribution |
| Handoff | Claiming completion or readiness | Actual output checks, rendering, templates, wording, identifiers and truthful status |

Finding reviews use their own rule/graph, risk, remediation, email and
operator/client responsibility checks rather than the governance template.
Run `wizexpert workflow-qa requirements --workflow governance --phase collection`
to obtain mandatory check IDs, current rule hashes and the documented-section
inventory. Later phases include all earlier requirements.
Unknown, missing, failed and unsupported checks block; there is no blanket
"all good" bypass. A separate reviewer must examine the evidence and recorded
decision rationale. Different names alone do not authenticate an independent
review.

## Whole-workflow coverage

| Profile | Required subject matter, in addition to the common gates |
|---|---|
| `setup` | Approved tenant/access/storage, installation reuse, credentials, actual read-only readiness and honest capability claims |
| `finding` | Rule/configuration and representative issues, complete inventory, identity joins, plain-language risk, practical remediation, requested reports and communications |
| `governance` | Historical reuse and cost, reopened/changed findings, cutoffs, approved prior sources, exceptions, attribution, workbook/deck contracts and current observations |
| `campaign` | Private campaign rules/state, observation windows, findings versus assets, new detections, ownership, daily history and verified closure criteria |
| `remediation` | Exact approval scope, dependencies, recovery, execution evidence, partial outcomes, technical/owner/Wiz validation and closure |
| `publication` | Public-only scope, privacy/history/untracked review, tests/lint/security/dependency gates and exact approved outgoing refs |

This is **not a claim that every rule is machine-provable**. Requirements have
three complementary checks:

1. **Documented-rule coverage:** every section of applicable public documents,
   production instructions and declared private rules needs an evidence-backed
   disposition. Heading-only requirements are included; headings inside code
   examples are not treated as new sections. This is section coverage, not an
   automatic translation of every sentence into executable assertions.
2. **Actual-file/action checks:** requested outputs, current hashes, recorded
   bulk queries, supported artifact adapters, cross-format parity and existing
   tracker/validator checks. A reviewer saying "pass" cannot override a failure.
3. **Independent review:** environment-specific reasoning, approval authority,
   source completeness, attribution, visual/native behavior and the mapping
   from the original user request to the deliverable manifest.

Use `--private-rules C:\PrivateEvidence\workflow-rules.md ...` when printing
requirements. Include active workspace instructions, the matching workflow
skill, approved client rules and applicable decision records. A campaign review
without private rules is blocked. Other profiles require an explicit mapping
(possibly empty for a genuinely public-only task) and an
`applicable-rules-and-private-decisions` check; absence is not evidence that no
private rules apply. Code cannot discover or authenticate every external policy.

Every `rule_coverage` entry uses the exact key/hash returned in `rule_sections`,
with `source_sha256`, `verdict`, `rationale` and `evidence`. Allowed verdicts are
`pass` or `out_of_scope`; the latter also requires `scope_approval` naming a
hash-bound scope decision. Future stages and genuinely unrequested work can be
excluded for this phase, not silently dropped. Fixed phase checks cannot be
waived. New/missing/stale sections, unknown verdicts or nonempty
`unresolved_conflicts` block. An unresolved legacy/new-rule conflict must not be
papered over with a passing attestation.

## Private review record

Keep reviews, approved client template contracts and activity logs outside Git.
A review uses this shape (illustrative values, not an actual approval):

```json
{
  "schema_version": 2,
  "workflow": "governance",
  "phase": "collection",
  "run_id": "private-run-id",
  "scope": "Explicit approved tenant and reporting period",
  "preparer": "preparer identity",
  "reviewer": "separate reviewer identity",
  "started_at": "2026-10-27T06:00:00Z",
  "reviewed_at": "2026-10-27T06:05:00Z",
  "expires_at": "2026-10-28T06:05:00Z",
  "rule_sha256": {"use every path/hash returned by requirements": "<sha256>"},
  "evidence_sha256": {"C:\\PrivateEvidence\\collection-plan.json": "<sha256>"},
  "request_evidence": "C:\\PrivateEvidence\\collection-plan.json",
  "private_rule_sources": {},
  "unresolved_conflicts": [],
  "requested_deliverables": [
    {"id": "workbook", "kind": "xlsx"},
    {"id": "executive", "kind": "pptx"},
    {"id": "operational", "kind": "pptx"}
  ],
  "parity_groups": [],
  "rule_coverage": {
    "use every exact documented-section key from requirements": {
      "source_sha256": "<section hash>",
      "verdict": "pass",
      "rationale": "Evidence-backed review of this entire section.",
      "evidence": ["C:\\PrivateEvidence\\collection-plan.json"]
    }
  },
  "checks": {
    "use every required check ID": {
      "verdict": "pass",
      "rationale": "Specific evidence and explanation of how this requirement was satisfied.",
      "evidence": ["C:\\PrivateEvidence\\collection-plan.json"]
    }
  },
  "allowed_wiz_queries": [{
    "tool_name": "list_issues",
    "parameters": {"first": 20, "severity": ["HIGH"], "status": ["OPEN", "IN_PROGRESS"]}
  }]
}
```

Include private profile/instruction hashes in `evidence_sha256` as well as the
public rule hashes, and declare private rule documents in `private_rule_sources`.
`request_evidence` must retain the actual request/scope decision, not just an
assistant's rewritten task. Version-1 process reviews must be reviewed again;
they cannot satisfy the expanded version-2 coverage.
Do not copy example verdicts or manufacture reviews from
the preparer's assertions. Approved queries match exactly except for `after`,
which permits cursor pagination. A changed filter needs renewed review.
Unbounded historical closed-issue queries require `full_refresh_approval` with
`reason`, `approved_by` and `evidence` naming a hashed approval file.

Generation/handoff records also require:

- `previous_review`: the hash-bound preceding phase's review, same run/workflow/scope.
- `activity_log`: a hash-bound, retained JSONL copy of the actual tool event log.
  Preserve the complete relevant interval and failures, not just selected good
  calls. Each event needs `timestamp`, `type`, and its original `data`. Bulk Wiz
  requests before collection approval or outside its allowlist block QA even
  when the review's checkboxes say pass.
- Generation reviews must bind actual input/template/profile/snapshot files.
- Handoffs require `artifacts` with exactly the requested IDs and kinds.
  Each entry has `id`, `kind`, absolute `path` and absolute `contract`; rendered
  outputs also need `native_review`. All these files must be hash-bound.
  Requested deliverables, parity groups, request reference, private rules and
  remediation target stage cannot silently change between phases.
  An email is checked when requested, not forced into every finding task.
  Scope changes need a new reviewed plan; missing formats/checkers block.

```powershell
wizexpert workflow-qa check --review C:\PrivateEvidence\collection-review.json --phase collection
wizexpert governance verify --workflow-review C:\PrivateEvidence\generation-review.json ...
wizexpert workflow-qa check --review C:\PrivateEvidence\handoff-review.json --phase handoff
```

The governance verification CLI now requires a generation review. Existing
low-level Python builders remain available for tests and isolated development;
they are not a workflow-QA bypass for production preparation. Do not use a
successful low-level call as a claim of process compliance.

Rule or evidence changes invalidate the review. The command recomputes hashes
instead of trusting an old pass receipt. All successful results still say
`share_ready: false`. Approval to send, publish or remediate remains separate.

## Actual deliverable checks

Supported `kind` values are `email`, `html`, `pdf`, `xlsx`, `pptx` and
`validation_receipt`. Contracts stay private and use `schema_version: 1`.

- **HTML:** `body_id`, complete `expected_text`, exact ordered `headings`
  (`[["h1", "Title"], ...]`) and an independently hash-bound `approved_template`.
  CSS and element styling must match the template. Hidden bodies, malformed
  markup, active content and unreviewed external references fail. Explicit
  HTTPS hyperlinks can be listed in `allowed_links`; this is not permission
  to load remote assets. Browser rendering is still required.
- **PDF:** actual PyMuPDF extraction checks `page_count` and full
  `expected_text`; encrypted/unreadable content and unreviewed links
  block. Install the optional `.[qa]` extra for this adapter.
  Scanned/image-only content cannot pass as checked text. Visual review must
  still inspect charts, positioning and clipping.
- **XLSX/PPTX:** `reference_artifact`, `reference_basis`, `reference_sources`
  and respectively exact `sheet_names` or `slide_count`. Compare **every**
  Office ZIP part using the shared hardened XML canonicalizer; only ZIP
  metadata and core save timestamps are ignored. Content, layout, fonts,
  images, embedded parts and metadata changes therefore fail against the
  reviewed reference/replay. XLSX also rejects hidden sheets/rows/columns and
  external workbook links; formulas require explicit `allow_formulas: true`.
  `forbid_hyperlinks: true` supports stricter workbook contracts. Macros fail.
  The reference must be a separately reviewed current-input replay or approved
  expected artifact, not the previous month's output blindly reused and not
  the candidate copied to fabricate approval. Inputs/templates must be bound.
- **Existing-validator receipts:** `success_status` is restricted to `passed`,
  `automated_checks_passed` or `validated`; `hash_field`, nonempty
  `required_sources`, `validator_source` and `execution_evidence` identify
  the actual check. Required source/output hashes must still match. This checks
  the receipt's nonempty `implementation_sha256` mapping against all current,
  hash-bound validator implementation/rule files, including `validator_source`.
  Changing the validator invalidates an old result. This checks
  the retained result; it does not rerun arbitrary scripts or authenticate a
  supplied log. Existing governance replay uses
  `source_and_output_sha256` and `automated_checks_passed`. Private campaign
  validators need a real retained execution result in this shape, not an
  invented receipt or a generic check substituted for campaign validation.

Declare `parity_groups`, for example `[["analysis-html", "analysis-pdf"]]`,
for corresponding HTML/PDF outputs. Actual full text is checked against each
contract before the contracts are compared; individually passing but
inconsistent companions fail. The reviewer must ensure all required companion
pairs were declared. Dates, identity joins and counts across unlike formats
remain the responsibility of the specialized domain validator and section
review, not naive text equality.

`audience` defaults to `client`; use `internal` only for an explicitly reviewed
internal analysis. Full-text checks reject local workstation paths in client
content. Optional `forbidden_text` enforces additional exact wording exclusions.
Office references and semantic review cover the corresponding Office content.

HTML, PDF and XLSX contracts must record `confidentiality_footer`: the exact
required line, or `null` when the applicable conventions explicitly require
none. A missing decision blocks rather than silently passing.

- HTML needs exactly one visible `<footer>` with that exact text.
- **Every** PDF page must contain it. PDF `expected_text` describes the content
  once, without those per-page footers (one occurrence per page is removed
  before comparison). Links must be in the reviewed HTTPS `allowed_links`.
- Every worksheet's odd footer, plus even/first-page footers when enabled,
  must contain it in the left, center or right section.
- PPTX contracts may set it; each slide then must contain the line. Approved
  presentation templates with their own footer remain governed by the
  reference comparison instead.

HTML/PDF parity ignores the footer's per-page repetition but requires the
companions to use the same footer decision.

Every rendered artifact also requires its own retained native/visual record:
`schema_version: 1`, `status: "passed"`, `kind`, `artifact_sha256`, `reviewer`
matching the independent process reviewer, `application`, UTC `reviewed_at`
inside the reviewed interval, and `evidence` referencing hashed renderings or
application evidence. Its `checks` must explicitly pass `all_content_reviewed`,
`readable`, `no_clipping`, `no_hidden_or_unexpected_content`, and for Office
files `opened_without_repair`. A changed output invalidates that review.
This is evidence-backed human review, **not an automated native Office test**.

## Remediation and closure checks

The `remediation` profile requires `target_stage` from 4 through 8, following
the existing eight-stage tracker. Generation/handoff also bind an immutable
`tracker` snapshot with exactly the reviewed scope. Generation requires the
preceding stage complete; handoff requires the requested stage complete.
References in all tracker events must resolve to hashed retained evidence,
directly or through `tracker_evidence_bindings` (reference text to evidence path).
This adds real evidence binding to the existing sequence/reference-presence
validator, without treating a tracker as cloud-change authorization.

For the supported local-account protocol, `local_account_results` entries
(`path`, `vm`, `outcome`, `verified_accounts`) rerun the existing strict parser
and compare the reported result. Other execution protocols need appropriate
domain validation and evidence-backed review; they are not silently interpreted
as this protocol. Partial outcomes, owner confirmation, technical validation,
Wiz reassessment and genuine patching versus scanner disappearance still need
the independent checks. Completing a report does not mean closing a finding.

## Blocking unreviewed bulk collection

`python -m wizexpert.workflow_qa hook` reads the `preToolUse` payload from stdin
as UTF-8 bytes. Accepted shapes, in order of precedence:

1. **`toolCalls` batch (primary).** This is the payload shape observed on the
   VS Code Copilot SDK host (taken from the session event log): `{"sessionId":...,
   "cwd":..., "toolCalls":[{"id":"call_...","name":"wiz-execute","args":
   {"tool_name":"list_issues","parameters":{...}}}]}`, with no `timestamp`.
   Every other tool (`view`, `powershell`, `rg`, `wiz-discover`) arrives in the
   same batch shape. Each element is evaluated independently on its decoded
   name; if any call must be denied the whole batch is denied and the reason
   names the call id. The keys `tool_calls` and `calls` are evaluated the same
   way, in any payload.
2. **camelCase `toolName`/`toolArgs` (fallback).** The shape in the GitHub
   Copilot hooks reference; `toolArgs` may be an object or a JSON string.
3. **`tool_name`/`tool_input` (fallback).** VS Code/Claude `PreToolUse` shape.
   Neither fallback has been verified on a live host here. A payload with none
   of these fields is allowed with `{}`.

A call's name is read from `name`, `tool`, `toolName`, `tool_name` or
`recipient_name`. For a Wiz execute call the query is read from `args`,
`arguments`, `input` (also `parameters`, `toolArgs`, `tool_input`), as an object
or a JSON string; every present value is checked, and the call is denied if
none is present, if it is not an object, or if its inner `tool_name` is missing
or empty. If an element's name is missing, null or not a string, the whole
decoded element is scanned (JSON escapes included) for Wiz execute names and
for the bulk inner tool names `list_issues`, `list_issues_grouped` and
`execute_graph_query`; a match is denied, otherwise the element is allowed.

Set `WIZEXPERT_QA_REVIEW` to the current private collection review, or supply
`--review PATH`. Tool names are trimmed and lower-cased; any name ending in
`wiz-execute`, `mcp__wiz__execute` or `mcp_wiz_execute` is Wiz execute. Every
other tool (including `wiz-discover`) is allowed with `{}` without parsing its
arguments or reading the review. The hook denies bulk `list_issues`,
`list_issues_grouped` and `execute_graph_query` calls (inner `tool_name` is
matched case-insensitively) without a valid matching review, including calls
inside a parallel wrapper. Count probes (`first=1`, no cursor), schema
discovery and individual issue lookups remain available for planning. `after`
is a cursor only when it is missing/`null` (no cursor) or a non-empty string
(bulk); any other value is denied.

Hook mode always exits 0 and prints exactly one JSON object: `{}` to allow, or
a top-level `permissionDecision: "deny"` with `permissionDecisionReason` (plus
a `hookSpecificOutput` copy for PascalCase hosts). Command `preToolUse` hooks
fail closed, so a crash or non-zero exit would block every tool. Decisions use
decoded JSON, never raw text, so JSON escapes such as `wiz\u002dexecute` cannot
hide a call. A malformed call or wrapper is denied only if it is, or may be,
Wiz; malformed input with readable non-Wiz names is allowed. Only input that is
not valid JSON (including invalid UTF-8 or excessive nesting) falls back to a
scan of the raw text for Wiz execute names. Any unexpected error is contained
the same way. Deny reasons contain the error type and at most a file
basename, never an absolute path.

Example hook registration (`.github/hooks/*.json`), adapted to the installed
interpreter and workspace; use the project venv interpreter in both commands:

```json
{"version":1,"hooks":{"preToolUse":[{"type":"command",
  "powershell":"& 'C:\\path\\to\\WizExpert\\.venv\\Scripts\\python.exe' -m wizexpert.workflow_qa hook",
  "bash":"/path/to/WizExpert/.venv/bin/python -m wizexpert.workflow_qa hook",
  "timeoutSec":15}]}}
```

Registration requirements: `version` 1, the camelCase `preToolUse` event,
`powershell`/`bash` keys and `timeoutSec`. On PowerShell a quoted executable
path followed by arguments must use the call operator (`& 'path\python.exe'
-m ...`); without `&` it is a parse error, which crashed the hook and blocked
every tool on the host (the original outage). The interpreter must be the one
that has `wizexpert` installed: a missing interpreter or module is a non-zero
exit before the hook code runs, which fails closed and blocks every tool.

**Live enforcement is not yet confirmed.** The payload shape above was
observed, and the unit and subprocess tests exercise the hook, but a live
retest still allowed a bulk call and the evidence showed the host did not run
the command hook at all. Hook files appear to be loaded only when the
agent-host process starts, so a hook written mid-session does nothing until the
host reloads. Do not claim runtime enforcement until, after the host has
reloaded its hook files, a denied synthetic/unreviewed bulk request is observed
through the host itself, and confirm this per host.
The hook governs these exposed MCP calls, not arbitrary scripts, direct SDK/API
calls or unknown tool aliases. A tool/transport change requires updating and
testing the adapter. Do not switch interfaces to evade a gate.

## Actual email template check

`wizexpert email-qa --html C:\PrivateReports\email.html --contract C:\PrivateEvidence\email-contract.json`
checks initial outreach against the established template, not an AI assertion:

- `Review requested: ... | SNOW: ...`, greeting, exact ordered `<h3>` headings
  with colons, review/assistance closing and approved signature.
- Control-to-issue mappings, selected attachment names and file hashes.
- Separate private header, dated draft badge and exact preparation notice.
- CSS and wrapper classes/inline styles against the hash-bound approved HTML.
- Known disallowed stakeholder wording, scripts/external assets and hidden headings.

The private contract has `schema_version: 1`, `kind: "initial"`, `signature`, `title`,
`ticket` (or null for an explicitly pending draft), `draft_date`, and IDs for
`body_id`, `subject_id`, `header_id`, `badge_id`, `notice_id`. Also supply
`approved_template`, `approved_template_sha256`, `attachments` (absolute file
paths to SHA256), and `issue_mappings` (objects with `control_id`, `issue_id`).
These element IDs identify existing regions; they do not prescribe a new visual
template. The approved template must be an independently approved reference,
not a copy of the new draft presented as its own approval.

Every email contract also records `confidentiality`: the exact private-wrapper
confidentiality line, or `null` when none is required. When set,
`confidentiality_id` must identify one visible wrapper element outside the
copyable body, with that exact text and the approved template's styling. The
line must not appear in the body that is sent. A missing decision blocks.

For `kind` reply, progress, blocker or closure, supply `approved_subject` and
`approved_body` containing the independently reviewed full wording. The checker
compares actual subject/body to those values (normalizing body whitespace) and
applies the same wrapper/style/signature safeguards. It does not force the
initial email's three sections or attachment paragraph onto concise replies.
Issue mappings and attachments are checked when declared. Unsupported kinds
block. An approved body string is a review record, not evidence that the facts
or approval it describes are true.
Browser/native review remains necessary for actual colors, layout, visibility,
clipping and responsiveness. Factual accuracy and whether recommendations fit
the environment also need evidence-backed review. Keyword checks cannot prove
every paraphrase compliant. Ticket-pending drafts never imply outreach readiness.

## Trust boundary

This local validator does not authenticate reviewer identities, cryptographically
attest tool logs, or prove that a supplied log is complete. It prevents missing
checks and detects observable deviations in the supplied evidence; it does not
make invented approvals trustworthy. Retain the real review and authoritative
approval records. If evidence cannot establish compliance, stop the affected
stage, report the gap and correct it rather than backdating approval.
