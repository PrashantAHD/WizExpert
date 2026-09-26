# Cloud Security Remediations

Turn Wiz CSV exports into clear Excel reports for cloud security reviews.
Provide your CSV paths, generate a report, and use it to discuss remediation
with resource owners.

**Currently supported:** AWS and Azure privileged-credential graph exports.
Other Wiz export formats and finding types are not supported yet.

## What you get

- Duplicate relationships consolidated without inflating identity or credential counts.
- Optional issue details, severity, status and Wiz links from a matching issue CSV.
- One Excel workbook with four tabs: **Cover**, **AWS Data**, **Azure Data**
  and **Remediation**.
- Remediation guidance for review, not automatic changes to your cloud environment.

## Quick start

Requires **Python 3.12 or newer**. Run these commands from the project folder
in PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m remediation "C:\Exports\graph.csv" --output "C:\Reports\finding.xlsx"
```

Replace the example paths with your own. Keep inputs and reports outside the
project folder. The output path must be absolute.

To include matching issue details:

```powershell
.\.venv\Scripts\python.exe -m remediation "C:\Exports\graph.csv" `
  --issues "C:\Exports\issues.csv" --output "C:\Reports\finding.xlsx"
```

The issue CSV supplements the graph export; it cannot replace it. Supply
exports for the same finding. Mismatched or conflicting evidence is rejected.

## Useful options

| Option | Purpose |
| --- | --- |
| `--issues PATH` | Add matching issue metadata. Repeat for multiple issue files. |
| `--as-of YYYY-MM-DD` | Set the UTC date used for age and expiry calculations; defaults to today. |
| `--notes PATH` | Include a local text file as a comment on the Remediation title. |
| `--update` | Regenerate an existing tool-created workbook at the same `--output` path. |
| `--help` | Show all available options. |

**Updating a report:** close it in Excel, then rerun your command with
`--update`. This rebuilds all four tabs and **replaces manual workbook edits**.
Keep original CSVs and decision records separately. Reuse `--as-of` if you
want to preserve the calculation date.

## From report to remediation

Review the evidence, agree on an approach with the owners, obtain the required
authorization, then implement and validate the approved changes.
Follow your organization's change and risk-management processes.

The tool generates reports only. It does not send emails, create tickets or
execute cloud changes. A reported issue status is not approval to make a change.

## Documentation

- [Workflow and communication guidance](docs/WORKFLOW.md)
- [Development checks and publication safety](docs/PUBLICATION.md)

Keep operational data, credentials and generated reports out of this public
repository. CSV processing is local; generated workbooks are not encrypted.
