# Category definitions: Risk Issues and Daily Progress Reporting

Reusable, drift-resistant definitions for two completed work types. The
machine-readable source is `wizexpert/governance/categories.py`; this page is
the public-safe skill and instruction text. It holds placeholders only: no
client names, evidence, identifiers, counts, accounts, CVEs or private
deliverables. Private templates, bindings and outputs stay in private storage.

## Categories

| Category | Deliverable slots |
|---|---|
| `risk-issues` (6) | internal-analysis, client-assessment, stakeholder-email (draft, not sent), detailed-report, internal-follow-up-email (draft, not sent), updated-detailed-report |
| `daily-progress-reporting` (4) | daily-progress-report, day-to-day-movements, vm-and-cve-details, stakeholder-reply-email (draft, not sent) |

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
