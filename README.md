# Cloud Security Remediations

**Investigate Wiz findings, prepare clear reports and coordinate remediation
through an assistant-led Wiz MCP workflow.**

Describe the finding or reporting scope in your approved assistant environment.
The assistant uses authorized Wiz tools to collect evidence, explain the risk
and prepare deliverables for review.

**Request → Collect from Wiz → Analyze → Report → Approve → Remediate → Verify**

[Setup](#setup) · [Start an investigation](#start-an-investigation) ·
[What gets automated](#what-gets-automated) · [Safety](#safety-and-privacy)

> **Where the automation runs:** Wiz MCP operates in your configured assistant
> environment, not inside this repository's Python CLI. This repository provides
> supporting local tooling and documented review practices; cloning or installing
> it does not create a Wiz connection or an unattended remediation service.

## What you get

- **Plain-language explanations:** what Wiz found, why it matters and what the
  evidence actually supports.
- **Scoped investigation:** affected resources, permissions, exposure and
  relevant dependencies, where available through the authorized tools.
- **Practical recommendations:** remediation options tailored to the environment,
  with prerequisites, limitations and approval requirements.
- **Review-ready deliverables:** requested Excel reports, assessments and
  stakeholder email drafts, prepared and checked by the assistant/operator.
- **Traceable follow-up:** retained evidence, reporting cutoffs, decisions,
  blockers and verification results.

Deliverables depend on the available evidence, local tools and requested scope.
There is no universal report generator for every finding type.

## Setup

### 1. Prepare your assistant environment

Use an organization-approved assistant host with MCP support, such as an approved
VS Code setup. Confirm that your organization's policies permit access to Wiz
and local report generation.

MCP (Model Context Protocol) lets the assistant call tools exposed by a connected
server. It does not itself grant Wiz permissions or authorize remediation.

### 2. Connect the approved Wiz MCP server

Obtain the server connection details and authentication instructions from your
Wiz/platform administrator, then:

1. Add the approved server through your assistant host's MCP configuration.
2. Authenticate using your organization's supported method.
3. Request only the permissions needed for read-only investigation.
4. Enable the relevant tools and review the host's tool-approval settings.

The endpoint, configuration format and authentication method depend on your
deployment and assistant host. This repository does **not** supply a server,
credentials or a connection installer. Do not copy authentication values into
source files, prompts or reports.

### 3. Open this project

With [Git](https://git-scm.com/downloads) installed, run in PowerShell:

```powershell
git clone https://github.com/PrashantAHD/Cloud-Security-Remediations.git
Set-Location .\Cloud-Security-Remediations
```

Open the folder in your approved assistant environment. If you already have the
project, open the existing checkout instead.

**Optional local Python setup:** if you will use the repository's supporting
Python tools, install [Python 3.12+](https://www.python.org/downloads/) and run:

```powershell
python --version
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
```

Stop if a command fails. Virtual-environment activation and PowerShell
execution-policy changes are not required. This installs local dependencies
only; it does not configure MCP or add report-format capabilities to the assistant.

### 4. Verify access before investigating

Ask the assistant:

> Check which read-only Wiz MCP tools are available. Confirm the account/project
> scope I can access with a small read-only query. Report any permission or
> connection limitations. Do not change resources or finding statuses.

Tool discovery alone is not proof of working authentication. Proceed only after
an authorized read-only query succeeds. Available fields and tools vary by
server and permissions; UI features may not have API equivalents.

### 5. Choose private output storage

Tell the assistant where to keep reports and evidence, for example:

```text
C:\PrivateReports\example-investigation
```

Use approved storage **outside this public repository**. Keep evidence, reports
and drafts together for the investigation, with access controls appropriate to
their sensitivity.

## Start an investigation

Give the assistant an issue/control identifier or a precise reporting scope.
Include accounts/projects, statuses, severities and the deliverables you need.

### Investigate a finding

> Investigate Wiz issue `<issue-id>` using read-only MCP tools. Explain the risk
> in plain language, identify affected resources and supported causes, and
> recommend practical remediation options. Prepare an Excel report and a
> stakeholder email draft. Save evidence and outputs in my approved private
> folder. Do not make changes or send the email.

### Prepare a scoped report

> Retrieve unresolved malware findings with Critical, High, Medium and Low
> severity in `<approved-project-scope>`. Confirm the status filters, collect all
> pages and reconcile the counts. Prepare an Excel report with a separate
> summary tab and record the actual observation cutoff.

### Refresh campaign progress

> Prepare today's progress report for `<CVE-list>` in `<approved-scope>`.
> Use fresh Wiz evidence, preserve previous observations and distinguish
> remaining findings from resolved findings. Prepare the report and reply draft
> for review; do not send them.

These are assistant requests, not built-in CLI commands. Case-specific report
layouts and recurrence rules must be agreed and retained privately. A daily
report request does not install a scheduler.

## What gets automated

| Activity | How it works | Review boundary |
| --- | --- | --- |
| **Evidence collection** | Assistant invokes available read-only Wiz MCP tools | Confirm scope, permissions, pagination and observation times |
| **Analysis** | Assistant combines findings, rule details and related resource evidence | Distinguish observed facts from hypotheses and missing information |
| **Report preparation** | Assistant uses available local tooling for the agreed deliverables | Reconcile counts, inspect output and confirm sharing suitability |
| **Stakeholder communication** | Assistant prepares recommendations and email/ticket drafts | An authorized person reviews and sends/submits them |
| **Remediation planning** | Assistant prepares scoped steps, prechecks and rollback guidance | Explicit approval is required before execution |
| **Verification** | Assistant reviews execution evidence and fresh Wiz observations | Execution success or scanner resolution alone does not prove closure |

**Not provided out of the box:** a hosted Wiz connector, universal report
generation, scheduled collection, automatic email/ticket delivery or autonomous
cloud remediation.

## Eight-stage remediation workflow

1. **Collect and reconcile** the complete in-scope evidence.
2. **Explain and analyze** the risk and practical options.
3. **Prepare reports and outreach**; Security creates the required ticket through
   the approved process before stakeholder outreach.
4. **Obtain scoped approval**, including exclusions and access to retain.
5. **Prepare the change**, with current-state checks, recovery and rollback.
6. **Execute approved changes** through an authorized operator and tooling.
7. **Verify results**, including owner checks and fresh Wiz evidence.
8. **Report outcomes and close** only when the agreed criteria are met.

These are human-reviewed stages, not eight autonomous product features.
ServiceNow remains authoritative for approvals, changes, exceptions and closure.
See the [workflow guide](docs/WORKFLOW.md) for detailed evidence and approval gates.

## Troubleshooting

| Problem | Next step |
| --- | --- |
| Wiz tools are not visible | Check server configuration and tool enablement in the assistant host |
| Authentication or permission failure | Follow the approved authentication process and confirm access with the administrator; do not broaden permissions without approval |
| Counts differ from Wiz | Compare accounts/projects, statuses, timestamps and pagination; distinguish findings from unique resources |
| Required fields are unavailable | Record the evidence gap and request an approved way to obtain it; do not infer missing values |
| A report cannot be generated | Identify the missing local dependency or unsupported layout; do not claim a completed deliverable |
| An output workbook is locked | Close it after saving your work, then retry; never discard user edits automatically |
| A daily update did not run | This workflow is on demand unless a separate approved scheduler has actually been configured |

## Safety and privacy

### Public code, private data

**The public repository is for reusable code, documentation and synthetic tests,
not client data.** In this workflow, collected Wiz evidence, generated reports
and stakeholder drafts are saved in your designated private folder outside the
repository. Report preparation does not automatically commit, push or publish
these files to GitHub.

| Public repository | Approved private storage |
| --- | --- |
| Reusable tools, generic documentation and synthetic tests | Wiz findings, resource identifiers and raw responses |
| Client-neutral examples and verification scripts | Excel/PDF reports, assessments and email drafts |
| No operational client evidence | Screenshots, approvals, execution logs and reporting history |

Choose the private destination before collection and keep generated files out
of the checkout. MCP queries and returned evidence are processed by the
configured Wiz server and assistant environment under your organization's
approved access, data-handling and retention policies; **private storage does
not mean the entire workflow is offline**.

Before any public push, follow the [publication checks](docs/PUBLICATION.md)
and manually review what will be shared. Ignore rules and local hooks help
reduce accidental disclosure, but they are not an absolute guarantee: they can
be bypassed or misconfigured.

### Review and access controls

- Keep read-only investigation separate from change authorization.
- Never send credentials, secret values or unnecessary sensitive samples to the
  assistant to enrich a report.
- Keep client identifiers, reports, raw responses, screenshots, approval records
  and execution logs out of this public repository.
- Preserve query scope, observation times and source evidence privately. Complete
  pagination and reconciliation before claiming complete coverage.
- Do not treat AI-generated investigation as proof of compromise or Wiz resolution
  as proof of successful patching.
- Local workbooks and tracking files are not encrypted by the tooling. Use
  approved storage, access controls and retention.
- Review every deliverable before sharing. Preparation does not authorize sending,
  ticket creation, finding-status changes or cloud actions.

## Guides

| Guide | Covers |
| --- | --- |
| [Workflow](docs/WORKFLOW.md) | Evidence collection, analysis, stakeholder communication and approval gates |
| [Execution follow-up](docs/EXECUTION.md) | Supported local-account evidence imports and blocker tracking |
| [Development and publication](docs/PUBLICATION.md) | Local verification, development dependencies and pre-push checks |

## Maintainer

**[Prashant Kumar](https://github.com/PrashantAHD)**

Cloud Security Engineer @AHEAD

[GitHub](https://github.com/PrashantAHD) · [LinkedIn](https://www.linkedin.com/in/iprashantkr)
