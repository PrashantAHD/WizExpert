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
const PROMPT = /^[A-Za-z0-9 .,;:()/_'?!@%-]{1,3400}$/;
// The only commands this helper will ever execute.
const COMMANDS = {
  newChat: 'workbench.action.chat.newChat',
  open: 'workbench.action.chat.open',
  stop: 'workbench.action.chat.stop',
  accept: 'workbench.action.chat.acceptTool',
  skip: 'workbench.action.chat.skipTool',
};
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

async function openChat(ahp, wait) {
  if (!UUID.test(String(ahp))) throw new Error('bad session id');
  await vscode.commands.executeCommand('vscode.open', vscode.Uri.parse('agent-host-session://ahp-session/' + ahp));
  await sleep(Math.min(Number(wait) || 2500, 15000));
}

async function runJob(job) {
  const errors = [];
  const info = {};
  try {
    if (job.kind === 'probe') {
      const all = await vscode.commands.getCommands(true);
      info.version = vscode.version;
      info.folders = folders().map((f) => path.basename(f));
      info.commands = all.filter((c) => /chat|agent/i.test(c)).slice(0, 400);
    } else if (job.kind === 'start_chat') {
      if (!AGENT.test(String(job.agent)) || !PROMPT.test(String(job.prompt))) throw new Error('rejected input');
      // A fresh chat first (so the prompt never lands in a conversation you already have open),
      // then submit the prompt in the requested custom agent mode.
      // A chat command promise can stay pending, so never wait on it indefinitely: the
      // result must always reach the console.
      const nc = await settleWithin(vscode.commands.executeCommand(COMMANDS.newChat), 8000);
      if (nc.error) throw new Error('VS Code refused to create a chat (allow the one-time prompt, then reload): ' + String(nc.error.message || nc.error));
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
        await vscode.commands.executeCommand(COMMANDS.stop);
        info.note = 'stopped';
      }
    } else if (job.kind === 'open_file') {
      const target = String(job.path || '');
      const allowed = folders().some((folder) => {
        const base = norm(folder);
        const candidate = norm(target);
        return candidate === base || candidate.startsWith(base + '/');
      });
      if (!allowed) throw new Error('rejected file path');
      await vscode.commands.executeCommand('vscode.open', vscode.Uri.file(target));
      info.note = 'opened';
    } else if (job.kind === 'tool') {
      const command = job.action === 'accept' ? COMMANDS.accept : job.action === 'skip' ? COMMANDS.skip : null;
      if (!command) throw new Error('bad action');
      await openChat(job.ahp, job.openWait);
      const g = await call('POST', '/vscode/guard', { id: job.id }, 5000).catch((e) => ({ ok: false, reason: e.message }));
      if (!g || g.ok !== true) {
        info.guard = (g && g.reason) || 'refused';
      } else {
        for (const r of job.resources || []) {
          if (!RESOURCE.test(String(r))) continue;
          // A session without a waiting prompt ignores this, so trying every URI form is safe.
          try { await vscode.commands.executeCommand(command, { sessionResource: vscode.Uri.parse(r) }); } catch (e) { errors.push(String(e.message).slice(0, 120)); }
        }
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
        const { errors, info } = await runJob(job);
        call('POST', '/vscode/result', { id: job.id, errors, info }, 5000).catch(() => {});
      }
    } catch (e) {
      report('waiting', String(e && e.message).slice(0, 120));
      await sleep(5000); // console not running
    }
  }
}

function activate(context) {
  stopped = false;
  output = vscode.window.createOutputChannel('WizExpert Console Helper');
  status = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 0);
  context.subscriptions.push(output, status);
  report('starting', folders().join(', ') || 'no workspace folder open');
  loop().catch((e) => report('stopped', String(e && e.message).slice(0, 120)));
  context.subscriptions.push({ dispose: () => { stopped = true; } });
}

function deactivate() { stopped = true; }

module.exports = { activate, deactivate };
