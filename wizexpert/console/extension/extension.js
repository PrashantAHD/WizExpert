// WizExpert console helper: runs a few allow-listed VS Code commands for the local console.
// It long-polls the console server (127.0.0.1) with signed requests, accepts only structured
// jobs for the workspace folder open in this window, and never runs a command it was not
// built to run. No dependencies; the signing token is never sent over the wire.
'use strict';
const vscode = require('vscode');
const http = require('http');
const fs = require('fs');
const os = require('os');
const path = require('path');
const crypto = require('crypto');

const HOME = process.env.WIZEXPERT_CONSOLE_HOME || path.join(os.homedir(), '.wizexpert-console');
const CONFIG_PATH = process.env.WIZEXPERT_CONSOLE_BRIDGE || path.join(HOME, 'bridge.json');
const INSTANCE = crypto.randomBytes(8).toString('hex'); // one per VS Code window
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const RESOURCE = /^(ahp-session|agent-host-copilotcli|copilotcli):\/[0-9a-f-]{36}$/;
const AGENT = /^[A-Za-z0-9 ._-]{1,60}$/;
const PROMPT = /^[A-Za-z0-9 .,;:()/_'?!@%-]{1,4200}$/;
// The only commands this helper will ever execute.
const COMMANDS = {
  newChat: 'workbench.action.chat.newChat',
  open: 'workbench.action.chat.open',
  // Cancel command for the current chat request: 'cancel' in current VS Code (1.144 has no
  // '...chat.stop'); the first candidate that exists at runtime is used.
  stopCandidates: ['workbench.action.chat.cancel', 'workbench.action.chat.stop'],
  accept: 'workbench.action.chat.acceptTool',
  skip: 'workbench.action.chat.skipTool',
  trust: 'workbench.trust.manage',
  // Revealing the chat view (first that exists is used).
  focusCandidates: ['workbench.panel.chat.view.copilot.focus', 'workbench.action.chat.focusInput'],
  // VS Code's own MCP commands; they take the configured server name.
  mcp: {
    start: 'workbench.mcp.startServer',
    stop: 'workbench.mcp.stopServer',
    auth: 'workbench.mcp.restartServer',
    list: 'workbench.mcp.listServer',
  },
};
const EXTERNAL_EXT = ['.pdf', '.pptx', '.docx', '.xlsx', '.html', '.eml', '.msg', '.md', '.csv', '.txt'];
let stopped = false;
let output = null;
let status = null;
let lastState = '';

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const mac = (token, ...parts) => crypto.createHmac('sha256', token).update(parts.join('\n')).digest('hex');
const digest = (buf) => crypto.createHash('sha256').update(buf || Buffer.alloc(0)).digest('hex');
const norm = (p) => String(p || '').replace(/\\/g, '/').replace(/\/+$/, '').toLowerCase();
function report(state, detail) {
  // Show connection state in the status bar and log changes, so a failure is never silent.
  const text = state + (detail ? ': ' + detail : '');
  if (text === lastState) return;
  lastState = text;
  if (status) {
    status.text = 'WizExpert helper ' + state;
    status.tooltip = detail || 'WizExpert console helper';
    status.show();
  }
  if (output) output.appendLine(new Date().toISOString() + ' ' + text);
}
const folders = () => (vscode.workspace.workspaceFolders || []).map((f) => f.uri.fsPath);

// Signed request; an answer is trusted only if the console signed it back.
function call(method, reqPath, body, timeoutMs) {
  return new Promise((resolve, reject) => {
    let cfg;
    try { cfg = JSON.parse(fs.readFileSync(CONFIG_PATH, 'utf8')); } catch (e) { return reject(e); }
    const token = String(cfg.token || '');
    if (!token || !cfg.port) return reject(new Error('console not configured'));
    const data = body ? Buffer.from(JSON.stringify(body)) : Buffer.alloc(0);
    const nonce = crypto.randomBytes(16).toString('hex');
    const ts = String(Math.floor(Date.now() / 1000));
    const headers = {
      'Content-Type': 'application/json',
      'X-Console-Nonce': nonce,
      'X-Console-Time': ts,
      'X-Console-Auth': mac(token, 'req', method, reqPath, ts, nonce, digest(data)),
    };
    if (body) headers['Content-Length'] = data.length;
    const req = http.request({ host: '127.0.0.1', port: cfg.port, path: reqPath, method, timeout: timeoutMs, headers }, (res) => {
      const chunks = [];
      res.on('data', (c) => chunks.push(c));
      res.on('end', () => {
        const buf = Buffer.concat(chunks);
        const proof = String(res.headers['x-console-proof'] || '');
        const want = mac(token, 'resp', nonce, digest(buf));
        if (!proof || proof.length !== want.length || !crypto.timingSafeEqual(Buffer.from(proof), Buffer.from(want))) {
          return reject(new Error('answer not signed by the console'));
        }
        try { resolve(JSON.parse(buf.toString('utf8') || '{}')); } catch { resolve({}); }
      });
    });
    req.on('timeout', () => req.destroy(new Error('timeout')));
    req.on('error', reject);
    if (body) req.write(data);
    req.end();
  });
}

// Resolves within ms no matter what and never rejects (a late rejection is swallowed).
function settleWithin(thenable, ms) {
  return new Promise((resolve) => {
    const timer = setTimeout(() => resolve({ timedOut: true }), ms);
    Promise.resolve(thenable).then(
      () => { clearTimeout(timer); resolve({}); },
      (error) => { clearTimeout(timer); resolve({ error }); },
    );
  });
}

function log(text) {
  if (output) output.appendLine(new Date().toISOString() + ' ' + text);
}

// getCommands(true) can hang in a wedged window: always bound it.
async function commandsWithin(ms) {
  const r = await new Promise((resolve) => {
    const timer = setTimeout(() => resolve({ timedOut: true }), ms);
    Promise.resolve(vscode.commands.getCommands(true)).then(
      (list) => { clearTimeout(timer); resolve({ list }); },
      (error) => { clearTimeout(timer); resolve({ error }); },
    );
  });
  if (r.timedOut) throw new Error('VS Code did not list its commands within ' + Math.round(ms / 1000) + ' seconds; this window is unresponsive.');
  if (r.error) throw new Error('VS Code could not list its commands: ' + String(r.error.message || r.error));
  return r.list;
}

// Explicit permission check: the workspace must be trusted and the chat commands present.
// Returns a concrete problem text, or '' when chat creation can proceed. With request=true an
// untrusted workspace opens VS Code's Workspace Trust editor so the user can grant it.
async function chatGate(request) {
  if (vscode.workspace.isTrusted === false) {
    if (request) await settleWithin(vscode.commands.executeCommand(COMMANDS.trust), 3000);
    return 'This workspace is not trusted, so VS Code blocks chat creation. Trust the workspace (Workspace Trust editor), then retry.';
  }
  const all = await commandsWithin(5000);
  const missing = [COMMANDS.newChat, COMMANDS.open].filter((c) => !all.includes(c));
  return missing.length ? 'VS Code chat commands unavailable: ' + missing.join(', ') + '. Enable Copilot Chat and reload the window.' : '';
}

async function openChat(ahp, wait) {
  if (!UUID.test(String(ahp))) throw new Error('bad session id');
  const o = await settleWithin(vscode.commands.executeCommand('vscode.open', vscode.Uri.parse('agent-host-session://ahp-session/' + ahp)), 8000);
  if (o.error) throw new Error('VS Code could not open the chat: ' + String(o.error.message || o.error));
  await sleep(Math.min(Number(wait) || 2500, 15000));
}

const JOB_LIMIT_MS = 60000;

// Never hangs: the whole job is bounded, so a result is always produced.
async function runJob(job) {
  let timer;
  const limit = new Promise((resolve) => {
    timer = setTimeout(() => resolve({ errors: ['job ' + job.kind + ' did not finish within ' + JOB_LIMIT_MS / 1000 + ' seconds'], info: {} }), JOB_LIMIT_MS);
  });
  try {
    return await Promise.race([runJobUnbounded(job), limit]);
  } finally {
    clearTimeout(timer);
  }
}

async function runJobUnbounded(job) {
  const errors = [];
  const info = {};
  try {
    if (job.kind === 'probe') {
      const all = await commandsWithin(5000);
      info.version = vscode.version;
      info.folders = folders().map((f) => path.basename(f));
      info.trusted = vscode.workspace.isTrusted !== false;
      info.chatGate = await chatGate(false);
      info.commands = all.filter((c) => /chat|agent/i.test(c)).slice(0, 400);
    } else if (job.kind === 'start_chat') {
      if (!AGENT.test(String(job.agent)) || !PROMPT.test(String(job.prompt))) throw new Error('rejected input');
      // A fresh chat first (so the prompt never lands in a conversation you already have open),
      // then submit the prompt in the requested custom agent mode.
      // A chat command promise can stay pending, so never wait on it indefinitely: the
      // result must always reach the console.
      const gate = await chatGate(true);
      if (gate) throw new Error(gate);
      const nc = await settleWithin(vscode.commands.executeCommand(COMMANDS.newChat), 8000);
      if (nc.error) throw new Error('VS Code refused to create a chat: ' + String(nc.error.message || nc.error));
      if (nc.timedOut) throw new Error('VS Code did not answer the new-chat request within 8 seconds; a permission prompt may be waiting in this window. Check VS Code notifications, then reload the window.');
      await sleep(Math.min(Number(job.newChatWait) || 1500, 10000));
      const op = await settleWithin(vscode.commands.executeCommand(COMMANDS.open, { mode: String(job.agent), query: String(job.prompt), isPartialQuery: false }), 8000);
      if (op.error) throw new Error('VS Code refused to open the chat prompt: ' + String(op.error.message || op.error));
      info.note = op.timedOut ? 'sent (command still pending)' : 'sent';
    } else if (job.kind === 'open_chat') {
      await openChat(job.ahp, job.openWait);
      info.note = 'opened';
    } else if (job.kind === 'stop_chat') {
      await openChat(job.ahp, job.openWait);
      const g = await call('POST', '/vscode/guard', { id: job.id }, 5000).catch((e) => ({ ok: false, reason: e.message }));
      if (!g || g.ok !== true) {
        info.guard = (g && g.reason) || 'refused';
      } else {
        const available = await commandsWithin(5000);
        const stopCommand = COMMANDS.stopCandidates.find((c) => available.includes(c));
        if (!stopCommand) throw new Error('No VS Code chat cancel command is available (looked for ' + COMMANDS.stopCandidates.join(', ') + ').');
        const st = await settleWithin(vscode.commands.executeCommand(stopCommand), 8000);
        if (st.error) throw new Error('VS Code refused to stop the chat: ' + String(st.error.message || st.error));
        info.note = 'stopped';
        info.command = stopCommand;
      }
    } else if (job.kind === 'open_file') {
      const target = String(job.path || '');
      const allowed = folders().some((folder) => {
        const base = norm(folder);
        const candidate = norm(target);
        return candidate === base || candidate.startsWith(base + '/');
      });
      if (!allowed) throw new Error('rejected file path');
      const o = await settleWithin(vscode.commands.executeCommand('vscode.open', vscode.Uri.file(target)), 8000);
      if (o.error) throw new Error('VS Code could not open the file: ' + String(o.error.message || o.error));
      info.note = 'opened';
    } else if (job.kind === 'focus') {
      // Reveal the run's chat (when known) and the chat view in this window. The extension API
      // cannot raise the OS window itself; the console also runs `code --reuse-window` for that.
      if (job.ahp) await openChat(job.ahp, job.openWait);
      const all = await commandsWithin(5000);
      const cmd = COMMANDS.focusCandidates.find((c) => all.includes(c));
      if (cmd) await settleWithin(vscode.commands.executeCommand(cmd), 5000);
      info.note = 'focused';
    } else if (job.kind === 'mcp_status') {
      // Wiz MCP tools registered in this window mean the server is running and signed in.
      const tools = (vscode.lm && vscode.lm.tools) || [];
      const re = /wiz/i;
      info.toolCount = tools.filter((t) => re.test(String(t.name || ''))).length;
      info.commands = (await commandsWithin(5000)).filter((c) => /^workbench\.mcp\./.test(c)).slice(0, 40);
    } else if (job.kind === 'mcp_action') {
      const server = String(job.server || '');
      if (!AGENT.test(server)) throw new Error('rejected server name');
      const all = await commandsWithin(5000);
      const wanted = COMMANDS.mcp[job.action];
      if (!wanted) throw new Error('bad MCP action');
      const cmd = [wanted].concat(job.action === 'auth' ? [COMMANDS.mcp.start] : []).find((c) => all.includes(c));
      if (!cmd) throw new Error('VS Code has no MCP command ' + wanted + ' (update VS Code or use the MCP: List Servers command).');
      // Authentication happens in the user's SSO browser window; no credential passes through here.
      const r = await settleWithin(job.action === 'list' ? vscode.commands.executeCommand(cmd) : vscode.commands.executeCommand(cmd, server), 8000);
      if (r.error) throw new Error('VS Code refused the MCP command: ' + String(r.error.message || r.error));
      info.note = job.action + ' sent' + (r.timedOut ? ' (command still pending)' : '');
      info.command = cmd;
    } else if (job.kind === 'open_external') {
      const target = String(job.path || '');
      const ext = path.extname(target).toLowerCase();
      const allowed = folders().some((folder) => {
        const base = norm(folder);
        const candidate = norm(target);
        return candidate.startsWith(base + '/');
      });
      if (!allowed || !EXTERNAL_EXT.includes(ext)) throw new Error('rejected file path');
      const ok = await vscode.env.openExternal(vscode.Uri.file(target));
      if (!ok) throw new Error('The system viewer did not open the file.');
      info.note = 'opened';
    } else if (job.kind === 'tool') {
      const command = job.action === 'accept' ? COMMANDS.accept : job.action === 'skip' ? COMMANDS.skip : null;
      if (!command) throw new Error('bad action');
      await openChat(job.ahp, job.openWait);
      const g = await call('POST', '/vscode/guard', { id: job.id }, 5000).catch((e) => ({ ok: false, reason: e.message }));
      if (!g || g.ok !== true) {
        info.guard = (g && g.reason) || 'refused';
      } else {
        // Some URI forms are expected to fail; report failures only if no form succeeded.
        const attempts = [];
        let succeeded = false;
        for (const r of job.resources || []) {
          if (!RESOURCE.test(String(r))) continue;
          // A session without a waiting prompt ignores this, so trying every URI form is safe.
          try {
            const t = await settleWithin(vscode.commands.executeCommand(command, { sessionResource: vscode.Uri.parse(r) }), 5000);
            if (t.error) attempts.push(String(t.error.message || t.error).slice(0, 120));
            else if (t.timedOut) attempts.push('timed out');
            else succeeded = true;
          } catch (e) { attempts.push(String(e.message).slice(0, 120)); }
        }
        if (!succeeded) errors.push(...attempts);
      }
    } else {
      errors.push('unknown job kind');
    }
  } catch (e) {
    errors.push(String(e && e.message).slice(0, 200));
  }
  return { errors, info };
}

async function loop() {
  let after = -1;
  while (!stopped) {
    try {
      const f = encodeURIComponent(JSON.stringify(folders()));
      const res = await call('GET', `/vscode/jobs?after=${after}&instance=${INSTANCE}&folders=${f}`, undefined, 40000);
      report('connected', folders().map((x) => path.basename(x)).join(', '));
      if (after < 0) { after = typeof res.last === 'number' ? res.last : 0; continue; } // skip jobs from before we connected
      for (const job of res.jobs || []) {
        if (job.id <= after) continue;
        after = job.id;
        if (!folders().some((x) => norm(x) === norm(job.workspace))) continue; // another window's job
        if (job.target && job.target !== INSTANCE) continue; // targeted at another window's helper
        log('job ' + job.id + ' ' + job.kind + ' start');
        const { errors, info } = await runJob(job);
        log('job ' + job.id + ' ' + job.kind + (errors.length ? ' failed: ' + errors.join('; ') : ' ok'));
        call('POST', '/vscode/result', { id: job.id, errors, info }, 5000).catch((e) => log('job ' + job.id + ' result not delivered: ' + String(e && e.message).slice(0, 100)));
      }
    } catch (e) {
      report('waiting', String(e && e.message).slice(0, 120));
      await sleep(5000); // console not running
    }
  }
}

function activate(context) {
  if (output) return; // already active in this window
  stopped = false;
  output = vscode.window.createOutputChannel('WizExpert Console Helper');
  status = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 0);
  context.subscriptions.push(output, status);
  context.subscriptions.push(vscode.commands.registerCommand('wizexpertConsoleHelper.status', () => {
    output.show(true);
    vscode.window.showInformationMessage('WizExpert helper ' + lastState);
  }));
  // The console opens a standard VS Code window for the workspace (`code -n`), where this helper
  // activates (the Agents window never loads user extensions). The URI handler is only a no-op
  // activation hook kept for manual use.
  if (vscode.window.registerUriHandler) {
    context.subscriptions.push(vscode.window.registerUriHandler({
      handleUri(uri) { output.appendLine(new Date().toISOString() + ' woken by console (' + String(uri.path).slice(0, 20) + ')'); },
    }));
  }
  output.appendLine(new Date().toISOString() + ' activated v' + (context.extension && context.extension.packageJSON.version) + ' instance ' + INSTANCE);
  report('starting', folders().join(', ') || 'no workspace folder open');
  chatGate(false).then((g) => { if (g) report('blocked', g); }, () => {});
  loop().catch((e) => report('stopped', String(e && e.message).slice(0, 120)));
  context.subscriptions.push({ dispose: () => { stopped = true; } });
}

function deactivate() { stopped = true; }

module.exports = { activate, deactivate };
