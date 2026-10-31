# Category definitions: Reusable reporting categories

Reusable, drift-resistant definitions for three completed work types. The
machine-readable source is `wizexpert/governance/categories.py`; this page is
the public-safe skill and instruction text. It holds placeholders only: no
client names, evidence, identifiers, counts, accounts, CVEs or private
deliverables. Private templates, bindings and outputs stay in private storage.

## Categories

| Category | Deliverable slots |
|---|---|
| `risk-issues` (6) | internal-analysis, client-assessment, stakeholder-email (draft, not sent), detailed-report, internal-follow-up-email (draft, not sent), updated-detailed-report |
| `daily-progress-reporting` (4) | daily-progress-report, day-to-day-movements, vm-and-cve-details, stakeholder-reply-email (draft, not sent) |
| `monthly-governance-reporting` (3) | monthly-governance-workbook, monthly-governance-slide-deck, executive-dashboard |

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
