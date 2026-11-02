# Workflow console

A local web page that is **only a frontend** for the VS Code agent-mode workflow. You pick a
category, enter its input and press Start; the console opens a **new VS Code agent-mode chat**
with your custom agent and the prompt you would have typed, then mirrors that chat.

Everything else is the real agent session: model/subagent routing, `.github/hooks`, skills,
instructions, the Wiz MCP server from your VS Code `mcp.json`, the workflow QA gates and
VS Code's own tool approvals. The console adds **no workflow rules** of its own: no time
windows, no Wiz calls, no validators, no review gates.

| Category | Input | Prompt typed into the chat (default) |
|---|---|---|
| Risk Issues | Wiz issue/rule ID(s) | `Risk Issues category: prepare the deliverables for Wiz issue <ids>` |
| Daily Progress Reporting | none, or a short note | `Daily Progress Reporting category: prepare the daily progress report for today` |
| Weekly Progress Reporting | required Reporting Monday (`YYYY-MM-DD`, must be a real Monday), optional SNOW ticket/reference (empty: agent fetches/maps it from Wiz read-only), optional latest SNOW response (up to 1500 characters, folded, sent as quoted data between BEGIN/END SNOW RESPONSE, never instructions), optional previous-report folder (empty = first report), optional note | `Weekly Progress Reporting category: prepare the Monday report for the previous week ... SNOW reference <ref>`; states local-only, no Wiz/SNOW/cloud change, no email sent; initial deliverables Excel, slide deck, HTML, PDF, email draft |
| Monthly Governance Reporting | snapshot period `YYYY-MM` | `Monthly Governance Reporting category: prepare the monthly governance reporting for <YYYY-MM>` |

Input is allow-listed (characters and length) so a form value cannot add instructions:
issue IDs `[A-Za-z0-9._-]`, 2 to 64 characters, up to 10; month `YYYY-MM`; note
`[A-Za-z0-9 ._-]`, up to 80. The final prompt may only contain letters, digits, space and
`. , ; : ( ) / _ -`. A private JSON file (`--config`) may override the prompt templates.

### Risk Issues actions

After selecting Risk Issues, two buttons appear:

- **New work-item**: Wiz issue/rule ID(s) and **Proceed** (the original prompt, unchanged).
- **In-progress**: choose one operation. All of them only build a prompt for a new agent chat;
  the console itself makes no Wiz, ServiceNow, cloud or email call.
  - **Risk Accepted**: issue ID(s) plus **exactly one** of pasted item/finding IDs (up to 20,
    `[A-Za-z0-9._-]`) or the name of an existing local workbook/output folder (relative, under
    the deliverables folder, up to 3 levels, no `..`, no drive or absolute path). The console
    does not browse the disk; the agent confirms the folder exists. Both modes share one form,
    so a later folder picker needs no model change.
  - **Email Response**: issue ID(s) plus the received email text (up to 1500 characters, line
    breaks folded, only letters, digits, spaces and `. , ; : ( ) / _ - ' ? ! @ %`). The text is
    wrapped in `BEGIN EMAIL TEXT` / `END EMAIL TEXT` and labelled quoted data, not instructions;
    text containing those words is rejected. The agent drafts a follow-up email file; it is not sent.
  - **Update Status**: issue ID(s). The agent refreshes status read-only and updates a local
    copy of the detailed report Excel, leaving the original unchanged.

Model: a category may declare `stages` (button groups) and `actions` (fields, template,
optional `exactly_one_of`). The API takes an optional `action_id` next to `category_id`; omitting
it keeps the old behavior. Template overrides use `risk-issues` (New) or
`risk-issues/<action-id>` (`risk-accepted`, `email-response`, `update-status`). Daily Progress
also has `new-work-item` and `continue-work-item` actions: a new item requires a work-item
name plus either Wiz issue IDs or CVE details, while In-Progress starts from the local
work-item list and uses a single **Refresh** button for the selected item. Monthly Governance
remains a single-form category.

### Weekly Progress Reporting inputs

The category depends on Risk Issues and Daily Progress Reporting: the prompt tells the agent to
update the previous weekly report, reuse their latest local records/outputs (status, remediation
progress, SNOW and email responses), fetch only current read-only Wiz status, reconcile new
responses and never infer closure from an owner message. Items resolved during the covered period stay in that
period's report with resolution/current-status evidence and drop off the next period's active
carry-forward list unless they return to IN_PROGRESS; the prior report stays as the historical
record. No external mutation, no email sent.

The prompt states the reporting Monday and derives the covered prior week (the preceding
Monday to Sunday) from it. The previous-report selector is filled from `GET /api/weekly-progress/previous-reports`
(CSRF-protected, read-only, local only; no Wiz, SNOW or cloud call). It lists names and
root-relative folder references only, never file contents: folders under the configured output
roots whose path contains "weekly progress" and that directly hold a recognized deliverable
file. Paths are confined to the workspace, excluded/denied locations and symlinks are skipped,
depth is at most 3 levels and the list holds at most 50 newest folders. When nothing is found
the response says so explicitly and the selector offers "None: this is the first report"
(the prompt then states it is the first report). "Enter a folder name manually" remains as a
fallback, also used when the listing fails; the agent confirms a typed folder exists.

## Install and run

```powershell
# once: install the helper extension (an unpacked copy lands in %USERPROFILE%\.vscode\extensions)
wizexpert console install-helper --code "<path to VS Code>\bin\code.cmd"
# then run Developer: Reload Window once in the VS Code window that has the workspace open

wizexpert console --workspace <workspace folder> [--agent WizExpert] [--port 8765]
```

To build and install or update the helper as part of console startup, add
`--install-helper` (using the `code` launcher or the path supplied with `--code`):

```powershell
wizexpert console --workspace <workspace folder> --install-helper
```

The command does not reload VS Code, because that could interrupt active work.
After the first installation, use **Developer: Reload Window** once; later launches can
omit `--install-helper` unless the helper source changes.
If VS Code asks whether the helper may create a chat in this workspace, choose **Allow
Always**. This is a one-time workspace permission for the local helper; it prevents each
refresh from stopping at the chat-creation prompt.

By default, submitting a run first allows a short normal reconnect window, then checks the
workspace helper connection and installs the helper only if it is
still missing, then waits up to about 20 seconds for it to connect. VS Code offers no
supported way to reload a window from outside, so if the helper does not connect the console
asks you to run **Developer: Reload Window** once in VS Code and try again. Use `--no-auto-helper` only when you want submissions
to fail immediately instead of changing the local VS Code setup.

On the live run screen, **Stop** requests that the active VS Code chat stop. After a successful
run, **View latest output** opens only the newest output file already validated and listed by
the console. The work-item card remains available for another **Refresh** after the run ends or
fails.

### Canonical local setup (one console, one backend)

Chrome shows the console UI; the VS Code helper extension runs in the VS Code window
that has the **same workspace** open. Both must use one workspace identity, so launch from
the private outer root (the folder holding `deliverables/`, `AGENTS.md` and `.vscode/`),
never from this repository:

- Outer root (canonical `--workspace`): `<outer root>` (example `C:\Users\<you>\WizExpert`)
- Package, tests and `.venv`: `<outer root>\WizExpert` (this public repository)
- Launch: in VS Code opened on `<outer root>`, run **Tasks: Run Task** →
  **WizExpert: Workflow console (auto-reload)**. It runs
  `<outer root>\WizExpert\.venv\Scripts\python.exe -m wizexpert.console.dev --workspace <outer root> --port 8765`
  in a fresh terminal. The task first stops an existing console belonging to the
  same canonical workspace, so there is a single backend on port 8765.
- Stop: **WizExpert: Stop workflow console** (outer root) stops that process.

The task in this repository's `.vscode/tasks.json` deliberately does not start a console;
it only explains this setup, so a second backend with a mismatched workspace cannot be
launched by accident. The helper still refuses a workspace mismatch; that check is
unchanged.
### Auto-reload during development

Use the VS Code command palette and choose **Tasks: Run Task** →
**WizExpert: Workflow console (auto-reload)**. This starts the console in a fresh
VS Code terminal and opens the browser once. Changes to console Python, JavaScript, HTML,
CSS, JSON or SVG files automatically restart the backend without requiring a second
terminal or manual process management. Refresh the browser after the restart; the
per-process CSRF token is intentionally regenerated.

The normal `wizexpert console` command remains available when auto-reload is not needed.
Changes to the helper extension still require reinstalling it and reloading the VS Code
window.

Options: `--agent` (custom agent name, default `WizExpert`), `--config` (private JSON:
`agent`, `output_roots`, `exclude_dirs`, `deny_names`, `prompts`, `start_timeout`),
`--state-dir`, `--copilot-home`, `--cli-fallback` and `--code` (see below), `--no-browser`.
No workspace path or agent is built into the public code.

## How the chat is started

The helper extension (plain JavaScript, no dependencies, `local.wizexpert-console-helper`)
long-polls the console on `127.0.0.1` with HMAC-signed requests (same pattern as other local
helper extensions): the shared token is never sent, a request needs a fresh timestamp, nonce
and valid signature, and the helper trusts only answers the console signed. It runs only
allow-listed commands, only for the workspace folder open in its window:

1. `workbench.action.chat.newChat` (so the prompt never lands in a conversation you already
   have), then
2. `workbench.action.chat.open` with `{mode: <agent>, query: <prompt>, isPartialQuery: false}`.

Optional fallback (`--cli-fallback`): `code chat --mode <agent> --reuse-window "<prompt>"`. It targets the
last active VS Code window, so use it only if the helper path fails.

The session is identified read-only: a new `session-state/<id>` folder whose `cwd` is the
workspace, created after Start, whose first user message equals the prompt. The console
never writes to `session-state`.

## What the results page shows

- live progress from the session log: assistant messages, tool calls (names and short
  descriptions, not tool output or file contents), subagent tool calls;
- **input needed** when the agent asks a question or waits for a tool approval, with a button
  to open the chat in VS Code and (for approvals) optional **Allow / Skip**, which presses
  `workbench.action.chat.acceptTool` / `skipTool` only if that exact prompt is still the one
  waiting;
- the final assistant summary once the agent stops;
- the main deliverable files only: files the session wrote (tool calls) or changed under the
  output roots (default `deliverables`) with a recognized deliverable extension (`.docx`,
  `.xlsx`, `.pptx`, `.pdf`, `.csv`, `.md`, `.html`, `.eml`, `.msg`), shown as file name and
  location only. There are no open or download links and no file-serving endpoint; evidence,
  archive, log, JSON and secret-like files are never listed.

## Safety properties

- Binds `127.0.0.1` only; the `Host` header must be the loopback name and port served.
- Per-process CSRF token on every `/api` request; POSTs also need a matching `Origin` and a
  JSON content type. Strict CSP (no inline script), no caching, no framing, no referrer.
- Helper endpoints accept only signed, fresh, non-replayed requests.
- All text from the session is rendered with `textContent`; the page never builds markup.
- File contents are never served; listed paths are confined to the workspace output roots.
- Nothing is sent or changed by the console: no email, no Wiz, ticketing or cloud changes.

## Limitations

- Needs the helper installed and the window reloaded once.
- Which custom agent the new chat uses depends on VS Code applying `mode` in
  `workbench.action.chat.open`; the session log does not record the main agent, so the
  console cannot confirm it. Check the agent shown in the chat on the first run.
- A tool-approval prompt is recognised from the session log; if several are waiting, Allow/Skip
  refuses and you answer in VS Code.

## Tests

`python -m pytest tests/test_console_*.py` uses fake session-state folders, a fake helper
poll and a loopback HTTP server; no VS Code, Wiz or agent run is needed.
