# Campaigns: repeated fixed-scope collection

A campaign is a temporary, repeated report on a fixed set of vulnerability IDs
(you supply them; there are no defaults) until every target is fully patched and
the closure gate in the campaign state file is met. `wizexpert campaign` plans
and validates the collection. It never calls Wiz, sends email or changes Wiz,
ServiceNow or cloud resources. Keep campaign state, evidence and reports in
private storage, never in this repository.

## Collection rules

1. **There is no elapsed-time limit on a collection.** A run is abandoned only
   when it has an explicit fetch or authentication failure:
   - *Unable to fetch:* the same call failed three times (`wizexpert campaign fail`
     and refused saves count them; a completely empty resource batch is the one
     exception, see step 3.4). `next` returns `abort_unable_to_fetch`.
   - *Authentication:* HTTP 401 or an OAuth challenge means stop and ask the
     operator to reconnect Wiz. Do this before collection starts; do not begin
     or continue until a catalog call succeeds.
   - The first abort or stop is recorded in `aborted.json`. From then on `next`,
     `save` and `assemble` refuse that directory; only a new `start` resumes.
2. **One staging directory per run.** After an abort, run `start` for a new
   directory. Never stitch pages from an aborted run (each record carries its run
   ID and a foreign record blocks) and never rebuild from a previous day's
   inventory. `assemble` records `observed_from` / `observed_to` from the real
   observation times of that single run.
3. **Collection order** (`wizexpert campaign plan`):
   1. one catalog record per vulnerability ID, in parallel;
   2. grouped queries per status group (all, remaining, resolved, rejected), in
      parallel;
   3. ONE finding stream over OPEN, IN_PROGRESS, RESOLVED and REJECTED at page
      size 20 (the Wiz maximum). Never split remaining and resolved streams;
   4. exact-ID resource lookups in parallel batches of 40 with
      `include_deleted=true`. A resource response may contain a strict subset
      of the requested IDs: preserve those findings, exclude unreturned assets
      from returned-resource counts, and label them `Not returned by Wiz /
      requires reconciliation`. Never treat an unreturned resource as resolved
      or closed.
      A completely empty batch for a non-empty ID set is refused and counted as
      a failed attempt (as is any other refused response). After two refusals the
      third identical empty batch is retained, never aborting the run, and every
      asset in it is labelled unreturned / `requires_reconciliation`. The assembled manifest reports
      `returned_resource_count`, `unreturned_resource_count`,
      `unreturned_resource_ids` and `collection_qa.status`, which is
      `requires_reconciliation` whenever any resource is unreturned; collection QA
      re-derives this from the retained evidence and flags the pack.
      `start` and `assemble` refuse output inside the public repository
      (`WIZEXPERT_ALLOW_REPO_OUTPUT=1` only for synthetic fixtures). A save is
      refused once a call has used all its attempts, even before the abort marker
      is written. `fail` shares the save lock and refuses a directory inside the
      public repository. Collection QA flags malformed or unreadable resource
      evidence instead of passing it. `stall_seconds` / `--stall-seconds` is a
      legacy setting that is accepted and ignored; it never limits a collection.
4. **Reconciliation stays.** Grouped totals must equal the finding stream per
   status group, every finding asset must have its resource record, finding IDs
   must be unique, and the scope must not change. A mismatch means recollect in
   a new directory. A finding stream must advance: an empty or repeated cursor
   is refused.
5. **Helper JSON** (params and responses) is written UTF-8 *without* a BOM,
   outside the staging directory; readers tolerate a BOM. Use `write_json`.
   `save` refuses helper files older than the run's start (do not replay old
   responses). `observed_at` is the time the record was *saved*, not a Wiz
   response time, so it proves when evidence was retained here, not when Wiz
   produced it. Saves are serialised with an exclusive `save.lock`; remove a
   stale lock only if no save is running. `assemble --out` never overwrites.
6. **Model availability:** if the AI model is degraded, switch model and continue.
   Never publish a partial pack or an interim status-only draft instead of the
   validated one.

```powershell
wizexpert campaign start --config C:\Private\campaign.json --base C:\Private\staging
wizexpert campaign next  --config C:\Private\campaign.json --dir <staging>
wizexpert campaign save  --config C:\Private\campaign.json --dir <staging> --tool <tool> --params-file <p.json> --response-file <r.json>
wizexpert campaign fail  --config C:\Private\campaign.json --dir <staging> --tool <tool> --params-file <p.json> --status 500
wizexpert campaign assemble --config C:\Private\campaign.json --dir <staging> --out C:\Private\manifest.json
```

`campaign.json` holds `vulnerability_ids` and optionally `group_by` (default
`CLOUD_PLATFORM`). `--vuln-id` may be repeated instead.

## Lifecycle and scheduling

Refresh every day until all target IDs are fully patched **and** the closure gate
is met. The state file has `status` (`active` or `closed`), `vulnerability_ids`,
`fully_patched_ids` and `closure_gate` (`met`, `confirmed_by`, `evidence`).
`wizexpert campaign lifecycle --state <file> --mode scheduled|manual` answers
`refresh` or `stop`. A gate marked met without every target patched and a named
confirmation is rejected.

- A scheduled run prepares drafts and reports only. It never sends email and
  never mutates Wiz, ServiceNow or cloud resources.
- A closed campaign, or one whose gate is met, stops: prepare the final closure
  update if not yet done, then tell the owner to disable the scheduled automation.
- Manual on-request refreshes stay allowed for an active campaign.

## Workbooks

- The remaining sheet ends with a blank row and the exact note
  `Total Remaining Un-Resolved Findings = N`; the resolved sheet ends with
  `Total Resolved Findings = N` (`finding_count_note`).
- No separate per-group (team, owner, cloud) sheets or workbooks for a campaign.

Declare these in the workbook artifact contract with `campaign_workbook`:
`count_sheets` (sheet to `remaining`/`resolved`), optional `other_sheets` and
`group_names`. `wizexpert workflow-qa` artifact checks then enforce them.

## Update emails and reports

- Owner-requested additions to campaign reports are approved scope changes; see
  [owner-requested scope changes](WORKFLOW-QA.md#owner-requested-scope-changes).
- Campaign update and closure emails (`"campaign": true` in the email contract,
  any kind) must not mention Rejected findings at all. Non-campaign progress
  emails are not subject to these wording checks.
- "Resolved" means the Wiz lifecycle status, not independently verified patch
  completion. Write "Resolved in Wiz" (or state the lifecycle meaning) and never
  claim verified patching from it.
- Reconstructed data points and partial-day observations must name the UTC
  cutoff time (for example `as of 15:40 UTC`). Set `partial_day` or
  `reconstructed` in the contract to require it even if the wording is missing.
- `wizexpert email-qa` checks all three. A campaign review's collection manifest
  must carry a `campaign_collection` block that points at the hash-linked
  `wizexpert campaign assemble` manifest (`assemble_manifest`,
  `assemble_manifest_sha256`); `wizexpert workflow-qa collection-check` re-derives
  from it that the pack is single-run, complete, unaborted and not stitched.
  Use `collection-check --workflow campaign` to require it.

These are wording and structure checks, not proof that the facts are correct.
