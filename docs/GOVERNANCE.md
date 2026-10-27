# Governance reporting

Monthly cloud security governance reporting for any client: an Excel governance
workbook, a three-slide executive dashboard and a ten-slide operational
governance deck, all built from reviewed Wiz evidence and the client's
approved templates.

For preparation, use the [governance runbook](GOVERNANCE-RUNBOOK.md). It separates
source reconciliation, generation, automated verification and release approval;
an ordinary successful build is not evidence that those gates were completed.

> [!IMPORTANT]
> Client exports, workbooks, decks, profiles, evidence and backups are private.
> Keep them in approved storage **outside this repository**. Relative output
> paths resolve from your current working folder, never from the source checkout.

## Install

```powershell
python -m pip install -e ".[governance]"
```

The `governance` extra adds `python-pptx`, `Pillow`, `rich` and `questionary`.
The core WizExpert tools do not need them. `python-pptx` brings `lxml`;
WizExpert pins `openpyxl` to its `defusedxml` parser so installing the extra
does not change how workbooks are read.

## Commands

| What you need | Command | Result |
|:--|:--|:--|
| Create the client profile | `wizexpert governance setup` | Client rules used by every command |
| **Prepare or refresh the monthly report pair** | **`wizexpert governance monthly`** | Excel + executive dashboard, with backups before replacement |
| Generate or modify a workbook on its own | `wizexpert governance workbook` | Governance workbook with severity and scope tabs |
| Build a dashboard from a reviewed workbook | `wizexpert governance dashboard` | New PowerPoint from the approved template |
| Prepare the governance-call presentation | `wizexpert governance deck` | Ten-slide operational deck from a dated Wiz snapshot |
| Verify the prepared four-severity report set | `wizexpert governance verify` | Read-only replay, count reconciliation and file-hash record; not release approval |
| Plan collection and reconcile historical/fresh evidence | `wizexpert governance reconcile` | Request estimate, issue-level changes and a hash-bound reconciliation audit |

Every command accepts `--help`. Reporting commands accept `--profile PATH`;
`reconcile` instead uses an explicit collection plan. `verify` also requires a
generation-phase `--workflow-review` from [workflow QA](WORKFLOW-QA.md).
The two presentation
workflows are distinct: the executive dashboard is derived from the Excel
workbook; the operational deck is derived from a reviewed Wiz snapshot. Neither
silently substitutes its historical figures for the other.

## Client profile

Each client's business rules live in a small JSON profile. The first time you
run any command without one, the setup wizard starts; you can also run it
yourself:

```powershell
wizexpert governance setup          # interactive
wizexpert governance setup --show   # print the active profile
```

| Setting | Used for | Example |
|:--|:--|:--|
| Client name | Workbook title, dashboard titles, deck properties | `Example Health` |
| File name prefix | `Oct26_<prefix>_Governance_Report.xlsx`, `<prefix>_Remediation_Executive_Dashboard_M.D.YY.pptx`, `<Month><Year>_<prefix>_Monthly_Cloud_Security_Governance.pptx` | `ExampleHealth` |
| Monthly snapshot day (1-28) | Each reporting month closes on this day at 23:59:59 | `15` |
| Baseline month | Fixed first snapshot that progress is measured from | `2026-03` |
| Baseline open Critical / High (optional) | Executive dashboard baseline; if omitted, read from the workbook's baseline column | `12` / `90` |
| Your organisation | Governance deck footer, "Proprietary to ..." | `Example Provider` |
| Excel watermark | Workbook print header (`--org` still overrides) | `PROPRIETARY TO EXAMPLE PROVIDER` |
| Client logo (optional, .png/.jpg) | Top-right of the workbook Summary tab | `D:\Clients\example\logo.png` |

The profile is found in this order: `--profile PATH`, the `WIZEXPERT_PROFILE`
environment variable, `wizexpert-profile.json` in the current folder, then the
per-user profile (`%APPDATA%\WizExpert\governance-profile.json`). Profiles from
the former standalone reporter (`WIZGOV_PROFILE`, `wizgov-profile.json`) still
load.
The old per-user location (`%APPDATA%\wizgov\profile.json`, or
`$XDG_CONFIG_HOME/wizgov/profile.json`) is also read as a last fallback without
moving or rewriting it. An invalid selected profile fails; it is not silently
replaced with another client's profile.

For several clients keep one private profile per client:

```powershell
wizexpert governance setup --client-name "Example Health" --file-prefix ExampleHealth `
  --snapshot-day 15 --baseline-month 2026-03 --provider-name "Example Provider" `
  --baseline-critical 12 --baseline-high 90 --logo D:\Clients\example\logo.png `
  --output D:\Clients\example\profile.json
wizexpert governance monthly --profile D:\Clients\example\profile.json --month 2026-10 ...
```

Executive dashboard templates must use the client's slide titles
(`<Client> Executive Dashboard`, `<Client> Remediation Progress`). Decks carry
their own branding, so the logo setting affects only the workbook.

## CSV input

The workbook commands read standard **Wiz Issues CSV exports**:

| Column | Description |
|--------|-------------|
| `Issue ID` | Unique identifier for the issue |
| `Title` | Issue title / finding name |
| `Severity` | `CRITICAL`, `HIGH`, `MEDIUM`, `LOW`, or `INFO` |
| `Status` | `OPEN`, `IN_PROGRESS`, `RESOLVED`, or `REJECTED` (displayed as Ignored / Accepted Risk) |
| `Created At` | Timestamp the issue was first detected |
| `Resolved Time` | Timestamp the issue was resolved (blank if still open) |

Supported timestamps: `2026-01-15T10:30:00Z`, `2026-01-15 10:30:00.000 +0000 UTC`,
`2026-01-15 10:30:00 +0000 UTC`, `2026-01-15 10:30:00`, `2026-01-15 10:30` and
`2026-01-15`. CSV values are always written to Excel as literal text, never as
formulas.

> [!WARNING]
> Wiz exports are limited to **5,000 data rows per export**. Check each file
> against its matching dashboard count. `workbook` warns when a severity's
> combined, deduplicated count is exactly 5,000; `monthly` warns when an
> individual CSV contains exactly 5,000 rows. Neither warning proves an export
> is complete.

## Monthly preparation

| Risk | What can be missing | Required action |
|:--|:--|:--|
| **Export truncation** | Current findings beyond the 5,000-row limit | Split exports and reconcile each partition |
| **Wiz retention** | Older findings removed from later exports | Retain and reconcile issue-level history |

These are separate risks: splitting exports does not recover retained history,
and carrying history forward does not prove current exports are complete.

For repeat-month collection, **reuse the approved history before requesting
bulk data**. Follow the runbook's
[collection strategy](GOVERNANCE-RUNBOOK.md#2-plan-collection-from-retained-evidence-then-reconcile):
estimate requests, prefer complete change evidence, and reconcile older issues
that reopened or changed. A complete historical re-fetch is an escalation,
not the default. The CLI merges supplied inputs; it does not select or execute
MCP queries or certify that a delta is exhaustive.

### Exporting more than 5,000 issues

1. Confirm the client/project, severity and other scope filters. Record the
   export time, filters and matching dashboard counts.
2. Export a severity above 5,000 issues separately by status (`OPEN`,
   `IN_PROGRESS`, `RESOLVED`, `REJECTED`). Split a status above 5,000 further
   using non-overlapping date ranges or another exhaustive partition, and check
   boundaries for gaps or overlaps.
3. Count data rows excluding the header and reconcile unique Issue IDs against
   the dashboard counts. Export close together in time.
4. Supply every split file to `--input`. Never add dashboard counts as anonymous
   rows or duplicate records to make totals match.

Rows are deduplicated by Issue ID with the **last input occurrence winning**.
Review conflicting statuses, dates or severities rather than relying on file
order.

### Preserving issues dropped by Wiz retention

- Archive original exports and published workbooks privately every month; never
  modify a published workbook in place.
- Compare prior reports oldest to newest by **Issue ID**. Retain valid
  historical records missing from current exports; a current record with the
  same ID takes precedence after reviewing conflicts.
- Preserve creation date, closure date, status and severity. Count an issue in a
  snapshot only as its dates support.
- Document recovered IDs, their source reports and remaining gaps. Carry-forward
  can make governance totals higher than the live dashboard; explain the
  difference with records and dates.

`workbook --mode append` reads closed-issue details from the single workbook
given as `--output`; new mode imports no prior history. Reconcile older reports
into a reviewed historical CSV and supply it **before** current exports.
Reopened issues and changed closure dates need manual review: the tool does not
replay full status history.

### Baseline and monthly rollover

The profile's baseline is fixed for every later report unless a new baseline is
explicitly approved. With a March 2026 baseline and day-15 snapshots:

| Report | Explicit `--snapshots` value |
|--------|------------------------------|
| September 2026 | `"Mar 26,Aug 26,Sep 26"` |
| October 2026 | `"Mar 26,Sep 26,Oct 26"` |

For every severity, the **progress baseline is the Open / In Progress backlog at
the baseline snapshot**, not all issues created by then.

- **Summary backlog reduction:** `(baseline open - current open) / baseline open`.
- **Monthly Scope View net closure progress:**
  `((current resolved + ignored) - (baseline resolved + ignored)) / baseline open`.
  It excludes pre-baseline closures and can exceed 100% because it also counts
  issues created and closed after the baseline.

Reconstruct the baseline snapshot from issue-level dates. Export timestamps are
not snapshot dates: an export taken on the 21st describes a different
population from a report cut off on the 15th.

### Pre-publication checklist

- [ ] Every severity/status and export partition is covered; each CSV
      reconciles with its dashboard filters and export time.
- [ ] Duplicate IDs, changed statuses/severities, reopened issues and changed
      dates have been reviewed.
- [ ] Historical carry-forward is traceable by Issue ID and source report.
- [ ] Baseline, previous and current snapshot dates are correct; no stale
      severity figures are labelled as current.
- [ ] At each snapshot `Total = Open/In Progress + Resolved + Ignored`;
      `Previous Open + Newly Created = Monthly Scope` and
      `Monthly Scope - Closed in Month = Current Open`.
- [ ] Summary and Monthly Scope View agree with the severity tables.
- [ ] Differences from published snapshots and the live dashboard are explained.
- [ ] Gaps are disclosed and the report stays a draft until reviewed. A
      successful run is not a completeness or accuracy certification.

## Workbook output

| Tab | Contents |
|-----|----------|
| **Summary** | Totals, open, resolved, ignored and resolution % for every severity; optional client logo |
| **Severity Issues** | Month-on-month snapshots and the closed-issue detail list (Issue ID, Title, Severity, Status, Created At, Resolved Time, Snapshot Month) up to the latest cutoff. Snapshot Month is the report that counted the closure; closures on or before the baseline read `Baseline (<Mon YYYY>)` |
| **Monthly Scope View** | Baseline backlog, prior/current backlog, monthly scope, cumulative closures and net closure progress |

Every tab has the profile's confidentiality watermark in the print header and
page numbers in the footer.

## Combined monthly workflow

One command creates or refreshes a matching workbook and executive dashboard.
It runs when you run it; it is not a file watcher.

| When you run it | What happens |
|:--|:--|
| First run for a month | Creates a new workbook and dashboard |
| Further runs for that month | Backs up and refreshes those same files |
| First run for the next month | Creates a new pair; earlier months are untouched |

```powershell
wizexpert governance monthly --month 2026-10 `
  --input "D:\Reports\critical.csv" "D:\Reports\high.csv" "D:\Reports\medium open.csv" `
  --previous-report "D:\Reports\Sep26_ExampleHealth_Governance_Report.xlsx" `
  --template "D:\Reports\ExampleHealth_Remediation_Executive_Dashboard_9.15.26.pptx" `
  --output-dir "D:\Reports"
```

`--month YYYY-MM` fixes the report month and its snapshot-day cutoff,
independent of today's date. The approved prior report's baseline and
previous-month figures are preserved for every severity; only the current
snapshot is recomputed. Historical closed details missing from current exports
are carried forward. Missing approved snapshots fail rather than becoming an
invented zero.

**Corrected the workbook by hand?** Use `--workbook` instead of `--input` so a
CSV rebuild does not undo your corrections; the workbook is validated and used
as-is to regenerate the dashboard.

Safeguards:

- Both files are built and validated in a staging folder before publishing; an
  error leaves existing outputs untouched.
- Earlier versions are copied and hash-verified under
  `report-backups\YYYY-MM-<UTC timestamp>-<id>\` with a `pair.monthly-run.json`
  record. If replacing the second file fails, the first is rolled back.
- A per-month lock blocks simultaneous runs, and input/output hashes detect
  edits made during generation.
- After a crash during publication, confirm no run is active, reconcile both
  files with the backup record, mark it `recovered`, remove the stale
  `.wiz-monthly-YYYY-MM.lock`, then rerun. Never remove a live process's lock.

For an early, workbook-only review, the Python helper
`build_monthly_workbook(..., collected_at=<UTC datetime>)` labels every tab
PRELIMINARY with the collection time and scheduled cutoff, and
`build_deck(..., allow_preliminary=True)` creates a matching `_PRELIMINARY`
dashboard. A preliminary dashboard cannot be the next month's template.
Collection must be strictly after the previous scheduled cutoff and before the
current cutoff, not necessarily in the report's calendar month. For example, an
October 27 collection can preview a November 15 period: retain the approved
October 15 trend point, add October 27 as the actual observation, and label the
dashboard November PRELIMINARY. Never relabel that observation as November 15.

## Executive dashboard

`wizexpert governance dashboard --workbook <xlsx> --template <pptx>` updates the
client's approved **three-slide** 16:9 template. It keeps the cover, logos,
masters, shape positions and typography; it changes dates, metrics, narrative
text and the two chart pictures. Unrecognised titles, shapes or slide counts
are rejected. Charts need licensed `calibri.ttf` / `calibrib.ttf` (Windows
fonts by default, or `--font-dir`). The output is new and never overwrites a
source; use the monthly workflow for backed-up replacement.

**First run with an image-only template.** Charts in an original deck are
pictures; numbers are never guessed. Verify each historical point and supply a
private `*.dashboard-history.json` bound to the template's SHA-256:

```json
{
  "schema_version": 1,
  "scope": ["CRITICAL", "HIGH"],
  "template_sha256": "<lowercase SHA-256 of the approved template>",
  "points": [{"date": "2026-03-15", "open": 102}]
}
```

Each point needs a unique snapshot-day date. Generated decks embed their trend
history in the chart's alt text, so later months need no history file; keep the
trend picture and its metadata when preparing the next template.

Dashboard rules:

- Only **Critical and High** findings are included, read from the
  `CRITICAL Issues` / `HIGH Issues` snapshot rows and cross-checked against
  Summary and the detail tables.
- The **baseline is fixed** (profile counts, or the workbook's baseline column)
  and never rolls forward. The trend runs from the baseline to the latest
  snapshot; missing months fail rather than being interpolated.
- Open backlog = Critical + High Open / In Progress. Resolved / accepted is
  cumulative and can exceed the baseline as new findings enter scope.
- Final snapshots must be consecutive months. A preliminary observation must
  follow the prior approved cutoff and fall no later than the next scheduled
  cutoff. Flat or rising backlog is never presented as improvement.
- Exposure examples use only RESOLVED findings on or before the cutoff; ignored
  findings are never described as eliminated exposure.

Review all three rendered slides before sharing: baseline, continuity of
history, card/chart figures, clipping and exposure wording. This is a reviewed
monthly workflow, not unattended publication.

## Operational governance deck

`wizexpert governance deck --snapshot <governance.json> --template <pptx>`
rebuilds the approved ten-slide monthly call deck (cover, agenda, executive
summary, posture, three resolved-highlight slides, two in-progress slides and
takeaways) from a reviewed local snapshot. The command does not call Wiz:
the assistant collects read-only evidence through Wiz MCP and prepares the
snapshot. See the [snapshot guide](GOVERNANCE-SNAPSHOT.md) for queries, schema
and approval checks.

- Writes the deck and a `.governance.json` companion with all groups, sample
  IDs, provenance and limitations. `--refresh` backs up and replaces the month.
- `--actions-csv PATH` saves the list of issues missing a Wiz assignee.
- `--import-edits <deck> --editor <name>` records team wording edits from a
  generated deck into the snapshot before regeneration.
- Nothing after the period end (snapshot day, 23:59:59 UTC) is counted; early
  collections are marked PRELIMINARY on every slide.
- Without reviewed `team_resolved` evidence, resolved slides show tenant closure
  statistics labelled **Attribution Pending**, not credited team work. With that
  evidence, highlights use only the supported team subset, including separately
  labelled Accepted Risk where approved. REJECTED is not technical remediation,
  and resolution status alone never proves a resource was secured.

Speaker notes and companion JSON contain confidential evidence; review them as
well as the visible slides before sharing.
