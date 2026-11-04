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
| Weekly Progress Reporting | required Reporting Tuesday (`YYYY-MM-DD`, must be a real Tuesday), optional SNOW ticket/reference (empty: agent fetches/maps it from Wiz read-only), optional latest SNOW response (up to 1500 characters, folded, sent as quoted data between BEGIN/END SNOW RESPONSE, never instructions), optional previous-report folder (empty = first report), optional note | `Weekly Progress Reporting category: prepare the Tuesday report (current IN_PROGRESS plus items resolved from the previous Monday to the report-week Monday) ... SNOW reference <ref>`; follows retain-first evidence reuse (inspect the previous weekly folder and retained Risk Issues/Daily Progress evidence before any Wiz fetch; fetch only missing or conflicting details); for a rule with multiple IN_PROGRESS issues and absent/conflicting assignee evidence, inspects one representative issue and applies its assignee to grouped rows only when clearly rule-consistent, otherwise keeps the ambiguity; states local-only, no Wiz/SNOW/cloud change, no email sent; primary output is one editable branded slide deck, with optional PDF export and private email draft; Excel and standalone report HTML are retired |
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
`risk-issues/<action-id>` (`risk-accepted`, `email-response`, `update-status`, `follow-up-email`, `reply-response`, `update-case`). Daily Progress
also has `new-work-item` and `continue-work-item` actions: a new item requires a work-item
name plus either Wiz issue IDs or CVE details, while In-Progress starts from the local
work-item list and uses a single **Refresh** button for the selected item. Monthly Governance
remains a single-form category.

### Weekly Progress Reporting inputs

The category depends on Risk Issues and Daily Progress Reporting: the prompt tells the agent to
update the previous weekly report, reuse their latest local records/outputs (status, remediation
progress, SNOW and email responses), fetch the complete current read-only Wiz IN_PROGRESS
inventory, including historical items absent from the previous report, reconcile new responses
and never infer closure from an owner message. Items resolved during the covered period stay in that
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

## Approvals, imports, Wiz MCP and reporting views

All of these only read local files or ask the helper to run an allow-listed VS Code command.
The console sends no email, changes nothing in Wiz, ServiceNow or cloud, and never handles
passwords, MFA codes or tokens.

### Approvals

- **Settings template.** `scripts/console-workspace/settings.template.json` is a workspace
  `.vscode/settings.json` template that auto-approves only read-only terminal commands
  (`git status/diff/log/show` and read-only listing cmdlets) and keeps prompting for anything
  that runs workspace code (any Python script, pytest, `verify.py`, `python -m wizexpert`),
  redirects or chains commands, mentions `--output`, uses network-share paths, pushes, resets,
  deletes, moves, writes files from the shell, sends
  mail, calls the network or runs cloud CLIs. Edits to Python and build-config files, `.env`,
  keys, `.vscode` and `.github` also keep prompting, so the agent cannot write code and run it
  unprompted. Copy it into `<outer root>\.vscode\settings.json` (merge the
  keys if the file exists). VS Code has no per-tool setting for MCP tools, so approve the
  read-only Wiz MCP `discover` tool with **Always Allow** in VS Code once. Pre-approve `execute`
  (**Chat: Manage Tool Approval**) only together with a user-level `preToolUse` hook in
  `~/.copilot/hooks/` that denies any `execute` call whose `tool_name` is not a known read
  operation, because `execute` can run mutations in principle. Otherwise leave it prompting.
  In Copilot harness sessions only *user* terminal approvals reach the Agent Host; workspace
  `chat.tools.terminal.autoApprove` rules are not copied.
- **Waiting for approval in VS Code.** The run page shows the banner *Waiting for approval in
  VS Code* with a **Focus VS Code** button when a tool-approval prompt is read from the session
  log, or (heuristic) when a tool call has been open and the log silent for 60 seconds, because
  VS Code does not log every prompt. **Focus VS Code** (`POST /api/helper/focus`) reveals the run's
  chat through the helper and runs `code --reuse-window <workspace>` to raise the window, since
  an extension cannot raise the OS window itself. Approving inside VS Code stays the only way to
  answer prompts the console cannot press (see Allow / Skip above).
- **Approval gates.** Weekly and Monthly runs, Weekly *Update* and Risk Issues *Resume* are created
  *waiting for your approval*: nothing is handed to the agent yet. The run page shows the gates
  *Collection plan* then *Generation* (the catalog also defines *Push*, for flows that publish;
  no current flow uses it, and the console never pushes itself). **Approve** hands that stage's
  prompt (the request plus a short stage instruction) to a new VS Code chat; **Reject** ends the
  flow. Stage 1 runs in the same run; later gates start a follow-up run (`parent` / `child`) once
  the earlier stage finished, so each chat has its own log. Every decision (gate, decision, time)
  is saved in `runs.json` with the run (`gates`, `decisions`). API: `POST /api/runs` accepts
  `"gated": true` (always on for actions flagged gated), `POST /api/runs/<id>/gate` with
  `{"gate", "decision": "approve"|"reject"}`.

### Wiz MCP status

The sidebar shows **Wiz MCP connected / needs sign-in / stopped / not configured** with Start,
Stop, Authenticate and Refresh. The server finds MCP server *names* containing "wiz" in the
workspace `.vscode/mcp.json` and the user `mcp.json` (names only; settings, headers and
environment are never read into a response or job). The helper reports whether Wiz tools are
registered in `vscode.lm.tools` (connected) and runs VS Code's own `workbench.mcp.startServer` /
`stopServer` / `restartServer` commands for the buttons. Authenticate restarts the server so
VS Code opens the SSO page in your browser; finish sign-in there. `GET /api/helper/mcp`,
`POST /api/helper/mcp {"action": "start|stop|auth|list"}`.
Limitation: VS Code exposes no public API for MCP server state, so *needs sign-in* is inferred
(no tools yet within 10 minutes of a Start/Authenticate from the console) and the MCP command
arguments may differ between VS Code versions; if a button has no effect, use the `list`
action (MCP: List Servers) in VS Code.

### Imported work and previous reports

Read-only scans of local folders under the workspace's `deliverables\` folder (configured with
`--workspace`); source files are never modified, evidence and archive folders are not listed, and
only names, dates and counts are returned (plus the small `weekly-progress-data.json` and
`*.governance.json` snapshots for the comparisons). **View** opens the file in the system
viewer through the helper (`open_external`; `.pdf .pptx .docx .xlsx .html .eml .msg .md .csv .txt`
only, confined to `deliverables`).

- **Risk Issues** (*In-progress* stage): each folder under `deliverables\Risk-Issues` is a card
  with status *In-Progress*, rule/issue IDs (from `issue_ids` in the case record, else from the
  folder name such as `...-wc-id-11-12`), last modified, the artifacts present (analysis,
  client assessment, stakeholder / follow-up emails, report workbook, evidence, archives) and a
  **legacy** tag when the case has no rebuilt-workflow record (`*.workflow.json` or
  `case-gate-plan*`). **Resume** (action `resume-case`, gated) starts from the retained evidence
  using the `templates/risk-issues` logic; it is disabled when the case has no `evidence` folder and is
  **one-time**: once the workflow record has a stage 2+ event (or a "Resume collection" summary) the
  card offers **Update** instead (`update-case`, gated): reuse retained evidence, incremental
  read-only Wiz delta refresh only (status changes, new detections/resources, changed counts), no
  full historical recollection, archive before replacing, no Wiz/SNOW/cloud change, no email.
  Cards also offer **Follow-up Email** (`follow-up-email`: paste the email you sent; a concise
  status-update follow-up is drafted locally) and **Reply to Response** (`reply-response`: paste the
  assigned team's response; a reply is drafted locally). Both use the quoted `BEGIN/END EMAIL TEXT`
  delimiters and the same input limits, and never send. `email-response` (issue-ID form) remains as
  the legacy equivalent of Reply to Response. Cards show a bounded status line and milestones
  derived only from the small workflow JSON (latest event status/summary) and artifact names:
  *Ticket created*, *Email sent*, *Reports prepared/sent* appear only when a non-negated event
  clause says so; otherwise neutral *Reports present* / *Email draft present*. Malformed or missing
  records show a neutral fallback; evidence contents are never read. These automatic milestones
  are read-only and never imply external delivery. Each card also has three checkboxes you
  confirm yourself: *Ticket created*, *Email sent*, *Reports sent*. A change is saved at once to
  `manual_milestones` (`ticket_created` / `email_sent` / `reports_sent`, booleans) in the case's
  existing `*.workflow.json` via `POST /api/imports/risk-issues/milestone`
  (`{"case", "milestone", "checked"}`; same-origin + CSRF, local file edit only, no Wiz/SNOW/cloud
  call). Only those three keys and true/false are accepted, the case folder must exist under
  `deliverables\Risk-Issues` and have a readable workflow record, the write is atomic UTF-8 without
  BOM, and events and other fields are preserved. Errors are shown on the card list; a missing
  or malformed field shows the boxes unchecked, and the boxes are disabled without a record.
  `GET /api/imports/risk-issues`.
- **Weekly Progress** (*Previous reports* and *New report*): lists `deliverables\Weekly-Progress-Reporting`
  (newest first) with Open PDF / PPTX / email draft. **Update** exists for the latest report only
  (enforced by the backend): paste the internal and/or client response (quoted data between
  BEGIN/END RESPONSES, up to 1500 characters each) or name a local file under `deliverables`;
  the agent archives the prior version first, regenerates from retained evidence, writes a change
  log and runs the validators; the email stays a draft. **New report** is the existing form
  behind the approval gates: the previous report is the baseline, collection is reuse-first, then
  the post-collection check, generation and validators. **Compare with <previous week>** (and the
  *Week-over-week diff* button on a finished run) shows count changes and added / removed /
  changed items from the retained `weekly-progress-data.json` files
  (`GET /api/imports/weekly-diff?current=&previous=`).
- **Monthly Governance** (*Previous months* and *New month*): lists months from the workbook,
  executive dashboard / deck and `*.governance.json` names; a month is **PRELIMINARY** unless a
  non-preliminary workbook, dashboard or deck exists, otherwise *final*. **Compare vs previous
  month** shows parity (workbook, dashboard and governance.json present in both) and snapshot
  count deltas (`GET /api/imports/monthly-compare?month=YYYY-MM`). **New month** is gated and its
  stage prompts follow the governance runbook (`docs/GOVERNANCE-RUNBOOK.md`).

## Navigation, drafts and accessibility

- Real, shareable URLs (`history.pushState`): `/`, `/workflow/<id>[/<stage>[/<action>]]`, `/run/<id>`. Back and Forward work; old `#workflow=` / `#run=` links are upgraded in place.
- The page never jumps by itself: only a click, Back/Forward or the first page load changes the view. A stale run link shows an explanation with a button instead of redirecting.
- Unsaved form values are remembered per workflow in `sessionStorage` (this tab only) and cleared once a run starts. Secret-looking fields and values (tokens, passwords, keys) are never stored.
- Scroll position is restored on Back/Forward and reload; the stage and action selection live in the URL.
- Layout: a left sidebar (Home, Dashboard, In progress with a live count, History, workflows, helper status) that a top-bar button collapses to an icon rail with tooltips (the choice is remembered in `localStorage`, key `wizexpert.sidebar`; on narrow screens it starts collapsed and becomes a compact top bar under 960px); content views are Home, Dashboard, In progress, History, Workflow and Run, built from shared cards, tables, status badges and loading/empty/error boxes.
- Pages: Home (a dark hero with the WizExpert logo and principles and workflow cards with their illustrations; no operational details), `/dashboard` (run summary tiles, current activity and recent runs, with refresh; shortcut `g` `d`), `/in-progress` (needs-attention and running tasks with refresh), `/history` (filter by status, workflow and text; filters live in the URL query so a view can be shared) and `/run/<id>` (status, progress, log, output files, Open chat / Stop / View output; unchanged helper actions).
- Data comes from the existing `/api/bootstrap` (recent runs, active runs); the backend keeps its most recent 20 runs. A snapshot of run id, workflow, status and start time is cached in `sessionStorage` and shown immediately, then refreshed in the background with a visible Updated / Refreshing / error bar and a Refresh button. No secrets, helper details or form values enter this cache.
- Each workflow page lists its own previous runs (status, start time, Open button) and any running task, with an empty state; it never opens a run by itself.
- A header indicator shows running tasks on every page and links to the run.
- Loading, empty and error states share one look; keyboard users get a skip link, arrow-key movement in stage/action groups, focus on the new heading after navigation, and reduced-motion support.

## Install and run

```powershell
# once: install the helper extension (an unpacked copy lands in %USERPROFILE%\.vscode\extensions)
wizexpert console install-helper --code "<path to VS Code>\bin\code.cmd"
# the console then opens a standard VS Code window for the workspace itself when needed

wizexpert console --workspace <workspace folder> [--agent WizExpert] [--port 8765]
```

To build and install or update the helper as part of console startup, add
`--install-helper` (using the `code` launcher or the path supplied with `--code`):

```powershell
wizexpert console --workspace <workspace folder> --install-helper
```

The command does not reload VS Code, because that could interrupt active work. The helper
activates only in a **standard VS Code window**: the VS Code "Agents" window loads built-in
extensions and Copilot Chat only, so the helper can never run there. When the helper is not
connected, the console opens a standard window for the workspace itself (see below).
Before creating a chat the helper checks that the workspace is trusted (opening the
Workspace Trust editor if not) and that the chat commands exist, and it reports a concrete
error in the console banner, the status bar and the "WizExpert Console Helper" output channel
if either fails or VS Code does not answer. Extensions cannot trigger or pre-approve any other
VS Code permission prompt; if one is waiting, choose **Allow Always** there.

Automatic helper recovery: the rule is that a console run never fails because of the state of a
VS Code window or helper. If a standard window for the workspace with a working helper is open,
the chat starts there; if none is open, or the open one is unresponsive, a new standard window is
opened and the chat starts there. "Connected" only means the helper polls, so before `start_chat`
the console sends a quick targeted `probe` job (10 s). A helper that does not answer (or answers
with an error) is marked unhealthy and excluded from "connected" until it answers a job, recovery
(below) opens a new window, and `start_chat` is sent only to the healthy instance (jobs carry an
optional `target` instance; other helpers skip them, so the old window cannot also run it). If
`start_chat` itself gets no answer the console first checks whether a chat for that prompt
appeared; only if none did it recovers and retries once, so no duplicate chat is created. The
run fails only when recovery is impossible, with the reason recorded. The helper bounds every
VS Code call (including `getCommands`) and the whole job by a time limit, always posts a result,
and logs each job and outcome to the "WizExpert Console Helper" output channel.

The console page asks the server to connect the helper whenever it
is not connected (`POST /api/helper/connect`, one recovery at a time, retried every 30 s), and a
submitted run does the same. Recovery installs the helper only when its version is not already
registered (`code --list-extensions --show-versions`; a forced re-install re-extracts the folder
under running windows, so it is never repeated), then opens a standard VS Code window for the
configured workspace with `code -n <workspace>` (argument list, no shell; at most one launch per
90 s; a helper for the workspace seen within the last 120 s but gone first gets an 8 s grace to
reconnect, e.g. during a window reload, before the window is opened), then waits up to
45 seconds. The slow work never holds the run lock, and a second request
joins the recovery instead of starting another install, window or run. If the helper still cannot
connect, the concrete reason (the helper must run in a standard window, not the Agents window) is
shown in the banner and recorded with the run, and the run falls back to
`code chat` (below) exactly once, so no duplicate chat or job is created. With
`--no-cli-fallback` the run fails with that reason instead. Use
`--no-auto-helper` only when you want submissions to fail immediately instead of changing the
local VS Code setup.

On the live run screen, **Stop** requests that the active VS Code chat stop. The helper cancels
with `workbench.action.chat.cancel` (older VS Code: `workbench.action.chat.stop`), picking the
first allow-listed command that exists (`vscode.commands.getCommands`) after the guard check, and
reports an error if none exists. After a successful
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
- Launch: the task **WizExpert: Workflow console (auto-reload)** in `<outer root>\.vscode\tasks.json`
  runs on folder open (`"runOptions": {"runOn": "folderOpen"}`; set
  `"task.allowAutomaticTasks": "on"` in workspace and user settings so it is not blocked; the user
  setting is machine-wide, so every trusted workspace's folder-open tasks then run too), or
  manually via **Tasks: Run Task**. It runs `<outer root>\.vscode\start-console.ps1`, which starts
  `<outer root>\WizExpert\.venv\Scripts\python.exe -m wizexpert.console.dev --workspace <outer root> --port 8765`
  and stops that whole process tree once the owning VS Code process exits (checked every 3 s), so
  the console lives exactly as long as the standard VS Code window session. The task first stops an
  existing console belonging to the same canonical workspace, so there is a single backend on port 8765.
  Tasks run only in a standard window; the Agents window starts neither the task nor the helper.
  Versioned copies of `tasks.json`, `start-console.ps1` and `stop-console.ps1` live in
  `scripts/console-workspace/`; copy them into `<outer root>\.vscode\` (the scripts resolve the
  workspace as the parent of their own folder).
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
window. The console requires helper version 0.2.1 or newer for Wiz MCP actions. If the MCP
buttons report that the current helper is not connected, reload the standard VS Code window
(not the Agents window) so it unloads any older installed helper copy.

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

Fallback (on by default; `--no-cli-fallback` disables it; `--cli-fallback` is accepted for compatibility): `code chat --mode <agent> --reuse-window "<prompt>"`. It targets the
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

## Running tasks survive refreshes and restarts

The backend is the source of truth. Runs (category, prompt, chat/session binding, status) are
saved atomically to `runs.json` in the console state directory and reloaded at startup; a run
that was active stays active and re-reads its session log (which also holds any pending
approval or question), so it is only ended when the log shows the chat ended. A run caught
mid-start is re-matched to its new chat instead of being marked lost.

- `GET /api/runs/active` (also `active` in `/api/bootstrap`) lists non-terminal runs.
- The address decides the page: `#run=<id>` reopens that run (a run that finished meanwhile
  shows its final state, and pending Allow / Skip / question prompts reappear),
  `#workflow=<id>` reopens that workflow's input page, and the plain address is always the
  homepage. The homepage never jumps into a run on its own; it shows an **Open** button for
  each active run.
- Starting a second run of a workflow that already has an active run is refused by the
  backend, not only the UI.
- Backend code changes still need a restart; do it when no task needs a button press, as
  running chats continue in VS Code and are picked up again afterwards.

## Resetting Dashboard and History

To start with an empty Dashboard and History (for example after moving to new runs), POST
`{"confirm": "reset-console-history"}` to `/api/history/reset` (normal CSRF/Origin rules apply).
Only the console's own `runs.json` index is touched: it is moved aside to
`runs.json.reset-<timestamp>-<id>.bak` in the state directory (nothing is deleted). Deliverable
files, work-item folders, VS Code session logs and workflow configuration are not changed.
The reset is refused while any run is active. Prior risk issues can be re-added through
Existing / In-progress. The browser's per-tab cache key was bumped so stale history is not shown.

The Home page has an **About WizExpert** section describing the four workflows.

## Spend-Guard handoffs

When a chat calls `create_session` to continue in a fresh chat, the pending approval reads
"Spend-Guard handoff: continue this run in a new chat '<title>' (model ...)" with the handoff
prompt in a scrollable box; Allow / Skip work from the page like any approval (the same
`acceptTool` / `skipTool` command, which VS Code applies to custom-tool prompts too). Other
custom-tool approvals show the tool name and a few bounded, non-secret arguments.

After an allowed handoff the run is not marked finished: it shows "Handed off to a new chat",
status "Handed off - waiting for new chat", and is re-bound to the new chat (found through the
agent-host database, else by the handoff prompt as the first message of a session created after
the handoff). Status, progress, approvals, Stop, Open chat and output files then follow the new
chat; successive handoffs chain. The chain (and an unresolved handoff) is saved in `runs.json`.
If the new chat never appears within 30 minutes the run becomes "Interrupted".

## Safety properties

- Binds `127.0.0.1` only; the `Host` header must be the loopback name and port served.
- Per-process CSRF token on every `/api` request; POSTs also need a matching `Origin` and a
  JSON content type. Strict CSP (no inline script), no caching, no framing, no referrer.
- Helper endpoints accept only signed, fresh, non-replayed requests.
- All text from the session is rendered with `textContent`; the page never builds markup.
- File contents are never served; listed paths are confined to the workspace output roots.
- Nothing is sent or changed by the console: no email, no Wiz, ticketing or cloud changes.

## Limitations

- Needs the helper installed and a standard VS Code window for the workspace (opened
  automatically; the Agents window cannot run the helper).
- Which custom agent the new chat uses depends on VS Code applying `mode` in
  `workbench.action.chat.open`; the session log does not record the main agent, so the
  console cannot confirm it. Check the agent shown in the chat on the first run.
- A tool-approval prompt is recognised from the session log; if several are waiting, Allow/Skip
  refuses and you answer in VS Code.

## Tests

`python -m pytest tests/test_console_*.py` uses fake session-state folders, a fake helper
poll and a loopback HTTP server; no VS Code, Wiz or agent run is needed.
