# Cloud Security Remediations

Local, CSV-first Excel reporting for cloud security consultants coordinating
Wiz findings with CloudOps, Engineering, IAM, application/integration owners
and SecOps. The current importer supports **AWS and Azure privileged-credential
graph exports**, not arbitrary Wiz CSVs or every finding category.

## What is automated

The CLI validates supported CSV evidence, consolidates repeated relationships
and generates a four-sheet Excel report. An optional matching issue export
adds verified finding context. Runtime requirements are Python 3.12+ and
`openpyxl` plus `defusedxml` for hardened workbook XML reads.

Plain-English interpretation, stakeholder email drafting and translating
responses into scoped change plans require human or approved chat review;
they are not general AI features of this CLI. There is no browser app, case
history, approval database, runbook tracker, email sending, ServiceNow/Wiz API
integration or cloud execution. ServiceNow remains the authoritative record
for approvals, changes, exceptions and closure evidence.

## Install and run

From the repository in PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m remediation "C:\PrivateEvidence\graph.csv"
```

`python -m remediation`, `python -m remediation.csv_report` and the installed
`cloud-remediations` command use the same CSV CLI. No server is required.

```powershell
.\.venv\Scripts\python.exe -m remediation.csv_report `
  "C:\PrivateEvidence\graph.csv" `
  --issues "C:\PrivateEvidence\issues.csv" `
  --as-of 2026-09-25 `
  --notes "C:\PrivateEvidence\review-notes.txt" `
  --output "C:\PrivateReports\finding.xlsx"
```

### Input contract

- Supply one or more local UTF-8 graph CSV paths; UTF-8 BOM is supported.
  The supported schema connects `SERVICE_ACCOUNT | USER_ACCOUNT`,
  `ACCESS_KEY`, `ACCESS_ROLE_PERMISSION` and cloud scope objects.
  Unsupported schemas fail rather than being guessed into a mapping.
- `--issues` is an optional **repeatable path flag** for issue exports of the
  same finding. Issue CSV alone is unsupported. Issue enrichment requires
  one nonempty Control ID and exactly one matching issue for every graph
  identity, verified by cloud, vertex ID and native identity ID.
  Display names are never join keys. Split unrelated findings before reporting.
- Without issue evidence, optional `--title`, `--severity` and `--rule-id`
  are supplied context, not verified Wiz facts. Use `--help` for severity
  choices. With issue evidence, title, control, severity, status and links are
  derived from validated matches; contradictory explicit overrides fail.
- `--as-of YYYY-MM-DD` controls UTC date calculations; the default is UTC
  today. It does not refresh evidence. A newer issue `UpdatedAt` does not make
  older graph observations current.
- `--notes` reads a local UTF-8 text file into a comment on the Remediation
  title, not an additional Analysis sheet. Keep approved decisions in
  ServiceNow and approved source records, not only in workbook comments.

### Evidence and counting

Graph consolidation uses cloud + principal ID + credential ID + scope ID.
Graph rows, unique identities, unique credentials, credential-scope records
and matched issues are distinct counts; relationship rows are not issue counts.
Permissions and access-array members are deduplicated, while conflicting
facts fail validation.

Missing facts stay unknown. A graph `ACCESS_KEY.ID` is not necessarily the
native key ID. Azure display names do not establish secret versus certificate,
and tenants are not subscriptions. Active does not mean in use; inactivity
does not authorize deletion. `iam:*` is broad IAM access, not automatically
administrator access to every cloud service. Do not infer compromise from a
credential-age finding.

## Excel output and safe updates

Reports contain exactly **Cover**, **AWS Data**, **Azure Data** and
**Remediation**. The cloud data tables have nine columns, full permissions
as literal text, readable wrapping, filters and frozen headers. Verified Wiz
links are hyperlinks, not formulas or external-workbook links. Context and
details use the existing four sheets and comments, not extra tabs.

The report is consolidated evidence, **not a raw CSV archive**: complete
original CSVs are not embedded. Input files remain read-only source evidence.
Layout follows a generic design specification and does not depend on access
to private reference workbooks. Date summaries support review without changing
the consistent row stripes or inventing an SLA, severity or completed fix.
Text that cannot fit Excel's cell or row-height limits is rejected explicitly,
not silently truncated or moved to another tab.

- Output must be an absolute `.xlsx` path outside the source checkout.
  By default, Windows output uses
  `%LOCALAPPDATA%\CloudSecurityRemediations\reports` with a dated unique name.
- Existing files are not overwritten by default. To regenerate an existing
  tool-generated report at the same path, **close it in Excel first**, then:

```powershell
.\.venv\Scripts\python.exe -m remediation `
  "C:\PrivateEvidence\graph.csv" `
  --issues "C:\PrivateEvidence\issues.csv" `
  --update --output "C:\PrivateReports\finding.xlsx"
```

`--update` requires an explicit existing absolute workbook path and a
tool-generated workbook; it is not an arbitrary Excel editor. It regenerates
all four sheets from CSVs, **replacing manual workbook edits**, rather than
merging handwritten statuses or notes. Keep original evidence and approved
decisions outside the workbook. The update validates before atomically
replacing the same file; parsing, validation or publication failure leaves
the existing report untouched. A locked workbook produces an error.
Explicit updates do not create another versioned Excel file.
Avoid concurrent writers: the CLI checks for changes during generation but is
not a multi-user workbook editor. Repeat `--as-of` when revising an older report
without intentionally recalculating its age and expiry figures.

## Consulting workflow

1. Discover in Wiz, validate the evidence and explain the risk in plain English.
2. The security team creates and assigns the ServiceNow ticket.
3. Send a concise reviewed stakeholder email with the ticket placeholder,
   risk, summary, attached Excel report and practical recommended options.
4. Translate the response into exact resources, selected approach and conditions.
5. Obtain change authorization; prepare dependency tests, stop conditions and
   rollback. Only the approved operator implements the authorized scope.
6. Independently validate, obtain a fresh Wiz reassessment and retain closure
   evidence in ServiceNow.

Agreement on an approach is not change authorization; authorization is not an
applied fix; an applied fix is not independently verified closure. A finding
can contain approved changes, retained business risk and unchanged resources.
Do not impose deadlines or promise remediation dates.

See [the workflow and email template](docs/WORKFLOW.md) for decision boundaries
and [publication safety](docs/PUBLICATION.md) before sharing any source.

## Privacy and verification

Keep operational CSVs, reports, notes, screenshots and existing private
databases outside this public repository. The CLI does not migrate or delete
external legacy artifacts. Use approved encrypted storage and access controls;
Excel output is not encrypted by this tool. Do not supply credential material.
Only share evidence with an assistant when its data handling is approved.

For development, install the development extra and run the Python gate:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe scripts\verify.py
```

The gate runs the offline public guard, pytest, Ruff and Bandit. No PowerShell
execution-policy bypass is needed. Before every push, manually review staged
files and outgoing history, then rerun verification after staging. The default
guard does **not** scan untracked files; explicitly inspect new files before
staging. The optional dependency metadata audit is outbound and opt-in:
`scripts\verify.py --audit-dependencies`. See publication documentation for
the hook's audit opt-in and limitations. Verification does not commit or push.

## Prioritized roadmap

1. Additional validated finding-specific CSV adapters, not heuristic universal
   import of unrelated schemas.
2. A structured approved-decision CSV sidecar linked to authoritative
   ServiceNow records, without extra report tabs or a local approval database.
3. Evidence comparison and deltas with explicit observation dates and scope.
4. Broader workbook layout regressions, including actual Excel rendering.

These are planned improvements, not current capabilities. Repository workflow
instructions provide durable project guidance, not guaranteed global or
cross-session memory.
