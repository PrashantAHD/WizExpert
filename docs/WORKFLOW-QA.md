# Workflow compliance QA

Workflow QA asks **whether the preparer followed the prescribed process**.
It is separate from report arithmetic, Office replay, security review and
publication approval. It checks recorded actions and artifacts, not hidden
reasoning. Zero mistakes cannot be guaranteed.

## Gates

| Phase | Before proceeding | Required review |
|---|---|---|
| Collection | Nothing is pre-approved or blocked; reuse prior evidence first | Self-attested scope, prior evidence reuse and lifecycle coverage, then the post-collection check below |
| Generation | Building the reviewed report set | Collection coverage, conflicts, exceptions, dates, historical preservation and attribution |
| Handoff | Claiming completion or readiness | Actual output checks, rendering, templates, wording, identifiers and truthful status |

Run `wizexpert workflow-qa requirements --workflow governance --phase collection`
to obtain mandatory check IDs, current rule hashes and the documented-section
inventory. Later phases include all earlier requirements.
Unknown, missing, failed and unsupported checks block; there is no blanket
"all good" bypass. Generation and handoff reviews need a separate reviewer;
collection needs none. Different names alone do not authenticate an independent
review.

## Owner-requested scope changes

An owner-requested addition to a report or workflow is an approved scope
decision, not a process failure. Reviewers must verify that the previously
applicable rules were followed and that the addition is accurate and safe; they
must not block it solely because it was absent from the earlier plan. An
explicit owner request to update, add or replace logic must be recorded in the
applicable persistent instructions, skill, template or QA contract for later
runs. This does not waive evidence integrity, privacy, approval, no-send or
no-mutate controls, or a concrete Critical/High security finding. Conflicts with
those gates are surfaced with the smallest safe alternative, never silently
dropped.

Record each such request in the optional top-level review field `owner_changes`
(missing means none). Values below are illustrative only:

```json
"owner_changes": [
  {
    "id": "change-1",
    "kind": "addition",
    "request": "C:\\PrivateEvidence\\owner-request.txt",
    "summary": "Owner asked for an extra summary workbook.",
    "prior_logic_verified": true,
    "deliverables": ["summary-workbook"],
    "persisted_in": []
  }
]
```

- `id` is a unique nonempty string; `kind` is `addition` or `rule_update`.
- `request` and every `persisted_in` path must be absolute keys in
  `evidence_sha256`, so the owner request is hash-bound.
- `prior_logic_verified` must be literally `true`: the reviewer confirmed the
  previously applicable logic was still followed.
- `deliverables` (optional for an addition) lists requested deliverable IDs;
  `persisted_in` is required and nonempty for `rule_update` and names the
  instruction, skill, template or QA contract that now carries the logic.
- Superset rule: a later phase may request more deliverables than the previous
  phase only if every added deliverable ID appears in an `addition` entry's
  `deliverables`. Removing or altering an existing requested deliverable is
  still rejected. Owner changes recorded in an earlier phase must remain,
  unchanged, in later phases. An added deliverable must then be produced and
  checked like any other (the handoff artifacts must equal the requested IDs).
- A `rule_update` never bypasses `rule_sha256` binding: when the persisted rules
  change, the new rules apply to the next run and need a fresh review.
- Malformed entries fail closed.

## Post-collection check (one gate before generation)

Reuse-first stays the default: start from retained evidence and collect only
what is missing. Collection itself is **not** pre-approved, allow-listed or
independently reviewed, and no tool call is ever blocked. After collection and
before generating, run one check against the recorded activity log:

```powershell
wizexpert workflow-qa collection-check --activity-log C:\PrivateEvidence\activity.jsonl --manifest C:\PrivateEvidence\collection-manifest.json
```

The manifest (private, outside Git) holds `started_at`, `ended_at`,
`reused_sources` (or `no_prior_evidence_reason`), optional `full_refresh_reason`
and `counts`: `[{"name", "expected", "collected"}]` (integers that must equal).
It flags the report (exit 1, `status: flagged`) when: no reused sources or reason
are named; the log shows an unbounded historical `list_issues` query with no
`full_refresh_reason`; a Wiz call has unreadable arguments; the log has no events
in the interval; or any count is missing or does not reconcile. A flagged check
blocks generation, not collection. Generation reviews must carry hash-bound
`activity_log` and `collection_manifest`, and `validate_review` re-runs the check.
A campaign review must carry a `campaign_collection` block in that manifest. It is
not a self-reported claim: it names the assemble manifest written by
`wizexpert campaign assemble` (`assemble_manifest`, absolute path, and its
`assemble_manifest_sha256`), and the check re-derives from that manifest and the
retained staging evidence that the run is single, complete, not aborted,
unchanged, and not stitched or built from old data. Anything else flags the
report. Collection has no fixed time limit: only an authentication stop or
repeatedly failing call abandons a run (see [campaigns](CAMPAIGNS.md)).

## Whole-workflow coverage

| Profile | Required subject matter, in addition to the common gates |
|---|---|
| `setup` | Approved tenant/access/storage, installation reuse, credentials, actual read-only readiness and honest capability claims |
| `governance` | Historical reuse and cost, reopened/changed findings, cutoffs, approved prior sources, exceptions, attribution, workbook/deck contracts and current observations |
| `campaign` | Private campaign rules/state, failure-based abort (no collection time limit), auth/availability, findings versus assets, new detections, ownership, daily history, qualified wording and verified closure criteria; see [campaigns](CAMPAIGNS.md) |
| `publication` | Public-only scope, privacy/history/untracked review, tests/lint/security/dependency gates and exact approved outgoing refs |

This is **not a claim that every rule is machine-provable**. Requirements have
three complementary checks:

1. **Documented-rule coverage:** every section of applicable public documents,
   workspace instructions and declared private rules needs an evidence-backed
   disposition. Heading-only requirements are included; headings inside code
   examples are not treated as new sections. This is section coverage, not an
   automatic translation of every sentence into executable assertions.
2. **Actual-file/action checks:** requested outputs, current hashes, recorded
   bulk queries, supported artifact adapters, cross-format parity and existing
   validator checks. A reviewer saying "pass" cannot override a failure.
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
  }
}
```

Include private profile/instruction hashes in `evidence_sha256` as well as the
public rule hashes, and declare private rule documents in `private_rule_sources`.
`request_evidence` must retain the actual request/scope decision, not just an
assistant's rewritten task. Version-1 process reviews must be reviewed again;
they cannot satisfy the expanded version-2 coverage.
Do not copy example verdicts or manufacture reviews from
the preparer's assertions.

Generation/handoff records also require:

- `previous_review`: the hash-bound preceding phase's review, same run/workflow/scope.
- `activity_log`: a hash-bound, retained JSONL copy of the actual tool event log.
  Preserve the complete relevant interval and failures, not just selected good
  calls. Each event needs `timestamp`, `type`, and its original `data`. A flagged
  post-collection check blocks QA even when the review's checkboxes say pass.
- `collection_manifest`: the hash-bound manifest for the post-collection check.
- Generation reviews must bind actual input/template/profile/snapshot files.
- Handoffs require `artifacts` with exactly the requested IDs and kinds.
  Each entry has `id`, `kind`, absolute `path` and absolute `contract`; rendered
  outputs also need `native_review`. All these files must be hash-bound.
  Requested deliverables, parity groups, request reference and private rules
  cannot silently change between phases. An email is checked only when requested.
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

## Real-time hook (retired)

There is no real-time gate on Wiz calls. `python -m wizexpert.workflow_qa hook`
remains only as a compatibility no-op that reads stdin and prints `{}`, so an
old registration cannot block tools. Remove any `preToolUse` registration; use
the post-collection check instead.

## Actual email template check

`wizexpert email-qa --html C:\PrivateReports\email.html --contract C:\PrivateEvidence\email-contract.json`
checks a drafted message against its reviewed contract, not an AI assertion:

- Greeting, approved signature and the independently reviewed subject and body.
- Selected attachment names and file hashes.
- Separate private header, dated draft badge and exact preparation notice.
- CSS and wrapper classes/inline styles against the hash-bound approved HTML.
- Known disallowed stakeholder wording, scripts/external assets and hidden regions.

The private contract has `schema_version: 1`, `kind` (`reply`, `progress`,
`blocker` or `closure`), `signature`, `title`, `draft_date`, `approved_subject`,
`approved_body` (the independently reviewed full wording) and IDs for
`body_id`, `subject_id`, `header_id`, `badge_id`, `notice_id`. Also supply
`approved_template`, `approved_template_sha256` and optional `attachments`
(absolute file paths to SHA256). These element IDs identify existing regions; they
do not prescribe a new visual template. The approved template must be an
independently approved reference, not a copy of the new draft presented as its
own approval. The checker compares actual subject/body to the approved values
(normalizing body whitespace). Unsupported kinds block. An approved body string
is a review record, not evidence that the facts or approval it describes are true.

Every email contract also records `confidentiality`: the exact private-wrapper
confidentiality line, or `null` when none is required. When set,
`confidentiality_id` must identify one visible wrapper element outside the
copyable body, with that exact text and the approved template's styling. The
line must not appear in the body that is sent. A missing decision blocks.

Browser/native review remains necessary for actual colors, layout, visibility,
clipping and responsiveness. Factual accuracy also needs evidence-backed review.
Keyword checks cannot prove every paraphrase compliant.

Campaign update and closure emails (`"campaign": true` in the contract) are also checked
for wording: any mention of Rejected findings is flagged; "Resolved" must be
qualified as the Wiz lifecycle status (not verified patching); and reconstructed
or partial-day values (or `partial_day`/`reconstructed` set in the contract) must
name the UTC cutoff time. See [campaigns](CAMPAIGNS.md).

## Trust boundary

This local validator does not authenticate reviewer identities, cryptographically
attest tool logs, or prove that a supplied log is complete. It prevents missing
checks and detects observable deviations in the supplied evidence; it does not
make invented approvals trustworthy. Retain the real review and authoritative
approval records. If evidence cannot establish compliance, stop the affected
stage, report the gap and correct it rather than backdating approval.
