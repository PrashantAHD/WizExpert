<div align="center">

<img src="docs/assets/logo.svg" alt="WizExpert" width="380">

**Evidence-led Wiz investigation, client reporting and approval-controlled remediation.**

Analyze. Report. Validate. Coordinate. Remediate.

![Python](https://img.shields.io/badge/python-3.12%2B-3776AB?logo=python&logoColor=white)
![Wiz MCP](https://img.shields.io/badge/Wiz-MCP%20read--only-1D4ED8)
![Cloud](https://img.shields.io/badge/cloud-AWS%20%2B%20Azure-0EA5E9)
![Tests](https://img.shields.io/badge/tests-600%2B-2EA44F)
![License](https://img.shields.io/badge/license-MIT-yellow)

<img src="docs/assets/how-it-works.svg" alt="Animated diagram: collect Wiz evidence, wait for a person to send the report, then remediate and verify" width="920">

<sub>Open the SVG in a browser if GitHub shows a still frame. It loops: collect → human send → verify.</sub>

</div>

WizExpert is an **independent** reporting assistant for Wiz, not an official Wiz product.
You describe a finding or reporting scope; authorized **Wiz MCP** tools collect evidence;
local tools turn that into reviewed reports.

**Nothing is changed, sent or published without a person approving it.**

> [!IMPORTANT]
> Wiz MCP runs in your assistant environment, not in this repository. Installing
> WizExpert does not create a Wiz connection or an unattended remediation service.

## The idea in four beats

1. **Collect.** Read-only MCP queries. Risk explanation, affected resources, gaps.
2. **Draft.** Excel, stakeholder email, progress notes — in a **private folder outside this repo**.
3. **You send.** WizExpert prepares the package (with the ServiceNow ticket). A person approves and sends it outside the tool.
4. **Remediate only after change auth.** Close only when **fresh Wiz evidence** meets the closure criteria.

ServiceNow stays authoritative for approvals, changes and exceptions.

## What you get

| Deliverable | Purpose |
|---|---|
| Risk explanation | What Wiz found, why it matters, what the evidence supports |
| Scoped assessment | Resources, access paths, safeguards, gaps |
| Remediation plan | Options, prerequisites, approval needs |
| Excel + stakeholder drafts | Findings, recommendations, a clear decision request |
| Progress / verification history | Cutoffs, decisions, blockers, retained evidence |
| Monthly governance | Per-client workbook, executive dashboard, call deck |
| Workflow QA | Coverage checks — not a substitute for review |

Campaigns (repeated fixed-scope work): [docs/CAMPAIGNS.md](docs/CAMPAIGNS.md). Workflow QA: [docs/WORKFLOW-QA.md](docs/WORKFLOW-QA.md).

## Setup

1. Connect your approved assistant to **Wiz MCP** with read-only permissions — [setup guide](docs/SETUP.md).
2. Install local tools (Python 3.12+):

```powershell
git clone https://github.com/PrashantAHD/WizExpert.git
Set-Location .\WizExpert
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[governance]"   # omit [governance] if you don't need it
.\.venv\Scripts\wizexpert.exe --help
```

3. Ask the assistant to list read-only Wiz tools and run a small scoped query.
4. Pick a **private output folder** outside this repository.

## Use it

These are assistant requests, not CLI commands. Recurring reports run on demand; nothing is scheduled automatically.

> Investigate Wiz issue `<issue-id>` using read-only MCP tools. Explain the risk,
> identify affected resources and causes, and recommend remediation options.
> Prepare an Excel report and a stakeholder email draft in my private folder.
> Do not make changes or send the email.

> Prepare today's progress report for `<CVE-list>` in `<approved-scope>`. Use
> fresh Wiz evidence, keep previous observations and separate remaining from
> resolved findings. Do not send it.

## Monthly governance

**One tool, any client: each client's rules live in a private profile.**

```powershell
wizexpert governance setup      # once per client
wizexpert governance monthly --month 2026-10 --input <csv...> `
  --previous-report <last workbook> --template <last dashboard> --output-dir <private folder>
```

| Command | Builds |
|---|---|
| `governance monthly` | Workbook + executive dashboard |
| `governance workbook` / `dashboard` / `deck` | Pieces on their own |
| `governance verify` | Read-only replay of the four-severity set |

Runbook: [docs/GOVERNANCE-RUNBOOK.md](docs/GOVERNANCE-RUNBOOK.md). Automated verification does not replace release review.

## Guardrails worth knowing

- Client names, evidence and reports **never live in this repository**.
- Hostile files: `defusedxml`; Excel values as text; no silent overwrites; SHA-256 on templates.
- CI: publication guard, 600+ tests, Bandit, Ruff, `pip-audit`. `main` is PR-only.
- Review every deliverable before sharing. AI analysis is not proof of compromise; a Wiz resolution is not proof of a successful fix.
- Found a security issue? Report it privately to the maintainer.

## Guides

| Guide | Covers |
|---|---|
| [Setup](docs/SETUP.md) | Wiz MCP, install, migration |
| [Workflow](docs/WORKFLOW.md) | Evidence, analysis, approval gates |
| [Execution](docs/EXECUTION.md) | Local-account evidence, blockers |
| [Campaigns](docs/CAMPAIGNS.md) | Repeated fixed-scope collection |
| [Governance](docs/GOVERNANCE.md) | Profiles, workbook, dashboard, deck |
| [Publication](docs/PUBLICATION.md) | Verification and pre-push checks |

## License

[MIT](LICENSE) © 2026 Prashant Kumar

---

<div align="center">

**[Prashant Kumar](https://github.com/PrashantAHD)** · Cloud Security Engineer @AHEAD

**Evidence before conclusions. Approval before changes. Verification before closure.**

<sub>WizExpert is independent and isn't affiliated with Wiz, AWS or Microsoft.</sub>

</div>
