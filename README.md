# Cloud Security Remediations

Turn Wiz CSV exports into clear Excel reports for cloud security reviews.
Provide your CSV paths, generate a report, and use it to discuss remediation
with resource owners.

**CSV report generation:** AWS and Azure privileged-credential graph exports.
Other Wiz export formats and finding types are not supported yet.

**Execution follow-up:** update an existing approved local-account report from
supported Run Command results, record blockers and next actions, and generate a
stakeholder email draft. This is a separate command, not a new Wiz CSV importer.

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

## Eight-stage remediation workflow

These stages describe the end-to-end, human-reviewed workflow, not eight
automated CLI features. The current CLI supports the CSV schemas and execution
follow-up described above. Direct Wiz MCP collection and general-purpose
cross-source reconciliation are not implemented in the CLI; authorized
read-only MCP collection is an approved-chat activity when the required tools
are available. Existing CSV inputs remain supported.

| Stage | Work and required outcome |
| --- | --- |
| **1. Collect and reconcile evidence** | Obtain both issue-dashboard details and the associated Security Graph relationships through authorized read-only access, including the equivalent of selected custom columns. Use paired exports when direct retrieval is unavailable. Complete pagination; record filters, scope and observation times; match stable cloud, graph and native identifiers; deduplicate relationships; reconcile issue, unique-resource and graph-row counts. Flag missing fields, truncation, conflicting facts and unexplained differences before proceeding. |
| **2. Explain and analyze** | Explain the validated finding in plain language, distinguish confirmed causes from hypotheses, assess permissions and access paths, and develop practical remediation options with dependencies and trade-offs. Do not infer compromise from a risk finding alone. |
| **3. Prepare the report and stakeholder email** | Generate a separate finding report from validated evidence using a supported schema or a reviewed case-specific process. Draft a concise email covering risk, affected scope and feasible options, with the report attached. Security creates and assigns the ticket before outreach; review and send through approved channels. |
| **4. Obtain stakeholder decisions and approval** | Record owners' responses: approve remediation, request changes, defer, or accept risk. Establish exact resources, permitted actions, exclusions, business dependencies and conditions. Approach agreement is not production change authorization; silence is not approval. |
| **5. Prepare remediation** | Recheck current configuration against approved scope. Prepare steps or tightly scoped scripts, least-privilege operator access, prechecks, backups, tested recovery/rollback arrangements, stop criteria and success criteria. Check shared identities and policies for impacts on other workloads. |
| **6. Execute approved changes** | An authorized operator applies only the approved changes. Start with a representative workload where feasible, validate before expanding, retain execution evidence privately and stop on unexpected failures or scope differences. |
| **7. Verify and reconcile results** | Verify that intended configuration changes took effect; obtain application-owner functionality checks and independent technical validation. Reconcile fresh Wiz evidence when available. Keep change execution, functionality validation and finding resolution distinct; missing reassessment evidence remains outstanding. |
| **8. Report outcomes and close** | Update the report and draft a concise completion/blocker summary. Close the ticket only when agreed closure criteria are met. Keep deferred work, unresolved exceptions and authorized risk acceptance explicit; partial remediation is not whole-finding closure. |

Stage 1 must not silently substitute issue summaries for granular graph
evidence. Saved UI column selections may not be exposed by an API; verify
field coverage and document gaps rather than claiming an equivalent export.
Graph relationship counts need not equal issue counts. Unresolved material
evidence gaps block validated analysis and final reporting, not just execution.

Follow your organization's change and risk-management processes. ServiceNow
remains authoritative for approvals, changes and closure. The CLI does not
send emails, create tickets, execute cloud changes or track Wiz closure.
The later stages are operator responsibilities supported by reviewed reports
and local drafts. Keep source evidence, identifiers, screenshots, credentials
and generated outputs outside this public repository; use synthetic examples
in code and tests.

See [workflow and communication guidance](docs/WORKFLOW.md) for the stage
details and stakeholder email template.

## Update completed work and blockers

For an existing local-account workbook with **AWS Data**, **Azure Data**,
**Pending Review** and **Pending Remediation** tabs:

```powershell
.\.venv\Scripts\python.exe -m remediation update-remediation `
  --report "C:\Reports\local-account-report.xlsx" `
  --result "C:\Evidence\run-result.txt" `
  --email-output "C:\Reports\stakeholder-update.txt"
```

Repeat `--result` for more files. Only supported marker-based local-account
removal output is accepted, not arbitrary scripts or Azure's "Enable succeeded"
message alone. The report must already contain explicit approved usernames.

- Excel shows completed work, blocker reasons and next actions in the existing
  tabs. Columns are found by header, so reordered or removed optional columns
  do not break updates.
- Raw output and deduplication history stay in a private
  `local-account-report.remediation-memory.json` file beside the workbook,
  **not in Excel**. Keep this file with the report for future updates.
- The stakeholder draft summarizes recorded removals, exclusions, blockers and
  remaining work. Review it and attach the report before sending.
- No Wiz scan, reassessment or finding-closure tracking is added.
- Close Excel first. Each update keeps a uniquely named pre-update workbook
  backup and refuses to overwrite an existing email draft.

For a manual blocker or an explicit return to its original pending status, use
`--blockers "C:\Evidence\blockers.csv"` instead of, or alongside, result files.
To draft an email from the current report without changing it, use `--email-only`
instead of result/blocker inputs.
See the [execution follow-up guide](docs/EXECUTION.md) for the exact CSV schema,
supported workbook format and partial-result safeguards.

## Documentation

- [Workflow and communication guidance](docs/WORKFLOW.md)
- [Execution results, blockers and stakeholder drafts](docs/EXECUTION.md)
- [Development checks and publication safety](docs/PUBLICATION.md)

Keep operational data, credentials and generated reports out of this public
repository. CSV processing is local; generated workbooks are not encrypted.
