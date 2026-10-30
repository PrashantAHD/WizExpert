# WizExpert setup

Connect an approved assistant to Wiz MCP, open the project and verify read-only
access before investigating. Back to the [README](../README.md).

**Five steps to a verified, read-only connection.**

| 1 | 2 | 3 | 4 | 5 |
| :--- | :--- | :--- | :--- | :--- |
| Approved assistant | Wiz MCP connection | Open the project | Verify access | Private output folder |

## 1. Prepare your assistant environment

Use an organization-approved assistant host with MCP support, such as an approved
VS Code setup. Confirm that your organization's policies permit access to Wiz
and local report generation.

MCP (Model Context Protocol) lets the assistant call tools exposed by a connected
server. It does not itself grant Wiz permissions or authorize cloud changes.

## 2. Connect the approved Wiz MCP server

Obtain the approved server endpoint or launch command and authentication
instructions from your Wiz/platform administrator. Request only the permissions
needed for read-only investigation.

### Before authentication: sign in to the client's SSO

> [!IMPORTANT]
> **For client SSO-based access, sign in to the client's SSO in Chrome before
> starting Wiz MCP authentication.** Use your authorized client identity and
> complete any required MFA, then launch Wiz through the approved SSO portal
> to confirm you can access the intended organization.

When VS Code opens the authentication page, make sure it opens in that same
signed-in Chrome profile, not a personal profile or an incognito window. If it
opens in another browser/profile, use the organization-approved browser session
and restart authentication as needed. A signed-in SSO session does not grant
Wiz access by itself: your identity still needs the required Wiz permissions.
Follow your client's policy if a different browser or authentication method is
required.

### First-time connection in VS Code

1. Press **Ctrl+Shift+P** to open the Command Palette.
2. Run **MCP: Add Server**.
3. Select the connection type supplied by your administrator:
   **HTTP (HTTP or Server-Sent Events)** for an endpoint, or **Command (stdio)**
   for an approved local launch command. Do not guess a Wiz endpoint.
4. Enter the approved connection details and a server name such as `wiz`.
5. Choose an approved user/global configuration outside this public checkout.
   In current Copilot setups this can appear as **Global → Copilot Global**;
   the destination depends on your VS Code version and selected agent harness.
6. Review the server trust prompt and complete the approved sign-in flow.
   Enable the needed tools in your assistant session and review tool approvals.

### Start, stop and authenticate an existing server

**Ctrl+Shift+P → MCP: List Servers → select your Wiz server → choose an action**

| Action | What to do |
| :--- | :--- |
| **Start Server** | Start the configured connection and respond to any trust or sign-in prompts |
| **Authenticate / sign in, when offered** | Complete the organization's supported authentication flow; this may be prompted during startup rather than shown as a separate menu action |
| **Stop Server** | Stop the current connection; a later tool request may start it again |
| **Restart Server** | Restart after an approved configuration change or troubleshooting; if unavailable, stop and start |
| **Enable / Disable** | Control whether the server is available to the assistant; disable it when stopping alone is not sufficient |

Available actions depend on server state, authentication method, VS Code version
and agent harness. If there is no separate **Authenticate** option, follow the
startup sign-in prompt or your administrator's instructions; do not paste
tokens into chat. If startup fails, inspect the server output before retrying
and redact sensitive details before sharing logs.

**A running server is not proof of working Wiz access.** Complete the read-only
verification in step 4 below before starting an investigation.

The endpoint, configuration format and authentication method depend on your
deployment and assistant host. This repository does **not** supply a server,
credentials or a connection installer. Do not copy authentication values into
source files, prompts or reports.

Official VS Code guidance:
[Add MCP servers](https://code.visualstudio.com/docs/agent-customization/mcp-servers)
and [Manage MCP servers](https://code.visualstudio.com/docs/agents/run/manage-mcp-servers).

## 3. Open this project

With [Git](https://git-scm.com/downloads) installed, run in PowerShell:

```powershell
git clone https://github.com/PrashantAHD/WizExpert.git
Set-Location .\WizExpert
```

Open the folder in your approved assistant environment. If you already have the
project, open the existing checkout instead.

<details>
<summary><strong>Optional: install the supporting Python tools</strong></summary>

If you will use the repository's supporting
Python tools, install [Python 3.12+](https://www.python.org/downloads/) and run:

```powershell
python --version
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\wizexpert.exe --help
```

Stop if a command fails. Virtual-environment activation and PowerShell
execution-policy changes are not required. This installs local dependencies
only; it does not configure MCP or add report-format capabilities to the assistant.

</details>

### Existing installations

The repository, Python distribution and canonical module are **WizExpert**,
`wizexpert` and `python -m wizexpert`. The installed command is `wizexpert`.
The legacy command and module aliases from before the rename were removed.

For an existing editable installation, remove the old distribution before
installing the current one so the packages do not compete:

```powershell
git remote set-url origin https://github.com/PrashantAHD/WizExpert.git
.\.venv\Scripts\python.exe -m pip uninstall cloud-security-remediations
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\wizexpert.exe --help
```

Developers should use `-e '.[dev]'` for the install step. If moving a checkout,
recreate its virtual environment at the new location; Windows console launchers
and editable installations can contain absolute paths. Keep private output
folders outside the checkout and preserve existing files during migration.

## 4. Verify access before investigating

Ask the assistant:

> Check which read-only Wiz MCP tools are available. Confirm the account/project
> scope I can access with a small read-only query. Report any permission or
> connection limitations. Do not change resources or finding statuses.

Tool discovery alone is not proof of working authentication. Proceed only after
an authorized read-only query succeeds. Available fields and tools vary by
server and permissions; UI features may not have API equivalents.

## 5. Choose private output storage

Tell the assistant where to keep reports and evidence, for example:

```text
C:\PrivateReports\example-investigation
```

Use approved storage **outside this public repository**. Keep evidence, reports
and drafts together for the investigation, with access controls appropriate to
their sensitivity.

