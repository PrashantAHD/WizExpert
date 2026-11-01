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
| Monthly Governance Reporting | snapshot period `YYYY-MM` | `Monthly Governance Reporting category: prepare the monthly governance reporting for <YYYY-MM>` |

Input is allow-listed (characters and length) so a form value cannot add instructions:
issue IDs `[A-Za-z0-9._-]`, 2 to 64 characters, up to 10; month `YYYY-MM`; note
`[A-Za-z0-9 ._-]`, up to 80. The final prompt may only contain letters, digits, space and
`. , ; : ( ) / _ -`. A private JSON file (`--config`) may override the prompt templates.

## Install and run

```powershell
# once: install the helper extension (an unpacked copy lands in %USERPROFILE%\.vscode\extensions)
wizexpert console install-helper --code "<path to VS Code>\bin\code.cmd"
# then reload the VS Code window that has the workspace open (Developer: Reload Window)

wizexpert console --workspace <workspace folder> [--agent WizExpert] [--port 8765]
```

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
