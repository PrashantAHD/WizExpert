"use strict";
// Every value from the server is rendered with textContent only (never as raw markup).
const csrf = document.querySelector('meta[name="csrf-token"]').content;
const $ = (id) => document.getElementById(id);
const state = { categories: [], helper: {}, runId: null, timer: null, since: 0, progress: [], shown: "" };
const STATUS_TEXT = {
  starting: "Starting the chat in VS Code", running: "Running", input_needed: "Input needed in VS Code",
  completed: "Finished", stopped: "Stopped", not_started: "Did not start", interrupted: "Interrupted",
};
const TERMINAL = new Set(["completed", "stopped", "not_started", "interrupted"]);

function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (k === "class") el.className = v;
    else if (k === "onclick") el.addEventListener("click", v);
    else if (v === true) el.setAttribute(k, "");
    else if (v !== false && v != null) el.setAttribute(k, String(v));
  }
  for (const kid of kids.flat()) {
    if (kid == null || kid === false) continue;
    el.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
  }
  return el;
}
function clear(el) { while (el.firstChild) el.removeChild(el.firstChild); }
async function api(method, path, body) {
  const options = { method, headers: { "X-CSRF-Token": csrf } };
  if (method === "POST") { options.headers["Content-Type"] = "application/json"; options.body = JSON.stringify(body || {}); }
  const response = await fetch(path, options);
  let data = {};
  try { data = await response.json(); } catch (_e) { /* not JSON */ }
  if (!response.ok) throw new Error(data.error || ("HTTP " + response.status));
  return data;
}
function banner(text) { const b = $("banner"); b.hidden = !text; clear(b); if (text) b.append(text); }
function bytes(n) { return n < 1024 ? n + " B" : n < 1048576 ? (n / 1024).toFixed(1) + " KB" : (n / 1048576).toFixed(1) + " MB"; }
function when(t) { return t ? new Date(t * 1000).toLocaleTimeString() : ""; }

function renderHelper() {
  const box = $("helper"); clear(box);
  const ok = state.helper.connected;
  box.append(h("span", {}, h("span", { class: "dot" + (ok ? " on" : "") }), ok ? "VS Code helper connected" : "VS Code helper not connected"));
  box.append(h("button", { class: "secondary", onclick: checkHelper }, "Check"));
}
async function checkHelper() {
  try {
    const r = await api("POST", "/api/helper/probe");
    const chat = r.commands.filter((c) => /newChat|chat\.open$|acceptTool|skipTool/.test(c));
    banner("Helper OK. VS Code " + r.version + ", workspace window: " + r.folders.join(", ") + ". Chat commands seen: " + (chat.join(", ") || "none"));
  } catch (e) { banner("Helper check failed: " + e.message); }
}

// ---- page 1: category ---------------------------------------------------------------------------
function showPicker() {
  clearInterval(state.timer); state.runId = null; banner("");
  $("inputs").hidden = true; $("run").hidden = true; $("picker").hidden = false;
  const root = $("picker"); clear(root);
  root.append(h("h2", {}, "1. Pick a category"));
  const cards = h("div", { class: "cards" });
  for (const c of state.categories) {
    cards.append(h("div", { class: "card" }, h("strong", {}, c.title), h("p", {}, c.description),
      h("p", {}, h("button", { onclick: () => showInputs(c) }, "Select"))));
  }
  root.append(cards);
}

// ---- page 2: inputs ---------------------------------------------------------------------------------
function showInputs(category) {
  $("picker").hidden = true; $("run").hidden = true; $("inputs").hidden = false; banner("");
  const root = $("inputs"); clear(root);
  root.append(h("h2", {}, "2. " + category.title));
  const panel = h("div", { class: "panel" });
  const fields = {};
  for (const f of category.fields) {
    const input = h("input", { type: "text", maxlength: f.max_length || 200, placeholder: f.placeholder || "", autocomplete: "off" });
    fields[f.name] = input;
    panel.append(h("label", {}, f.label + (f.required ? " *" : ""), h("div", { class: "help" }, f.help)), input);
  }
  const message = h("p", { class: "bad" });
  const start = h("button", {}, "Start");
  start.addEventListener("click", async () => {
    message.textContent = ""; start.disabled = true;
    try {
      const inputs = {}; for (const [k, v] of Object.entries(fields)) inputs[k] = v.value;
      const res = await api("POST", "/api/runs", { category_id: category.id, inputs });
      openRun(res.run_id);
    } catch (e) { message.textContent = e.message; start.disabled = false; }
  });
  panel.append(h("p", {}, start, " ", h("button", { class: "secondary", onclick: showPicker }, "Back")), message);
  if (!state.helper.connected) panel.append(h("p", { class: "help" }, "The VS Code helper is not connected yet; see docs/CONSOLE.md (install the helper and reload the window)."));
  root.append(panel);
}

// ---- page 3: results ---------------------------------------------------------------------------------
function openRun(runId) {
  state.runId = runId; state.since = 0; state.progress = []; state.shown = "";
  $("picker").hidden = true; $("inputs").hidden = true; $("run").hidden = false; clear($("run"));
  poll();
}
async function poll() {
  clearTimeout(state.timer);
  const id = state.runId;
  try {
    const run = await api("GET", "/api/runs/" + id + "?since=" + state.since);
    if (id !== state.runId) return;
    state.since = run.next;
    state.progress.push(...run.progress); if (state.progress.length > 400) state.progress.splice(0, state.progress.length - 400);
    renderRun(run);
    state.timer = setTimeout(poll, TERMINAL.has(run.status) ? 8000 : 1500); // keep files fresh after the chat ends
  } catch (e) { banner("Lost contact with the console: " + e.message); state.timer = setTimeout(poll, 4000); }
}
function renderRun(run) {
  // Rebuild only when something changed, so button messages and scroll position survive polling.
  const sig = JSON.stringify([run.status, run.message, run.pending, run.summary, run.files.map((f) => [f.path, f.size]), state.since, run.can_open_chat]);
  if (sig === state.shown) return;
  state.shown = sig;
  const root = $("run"); clear(root);
  root.append(h("h2", {}, "3. " + run.category),
    h("p", {}, h("span", { class: "badge " + run.status }, STATUS_TEXT[run.status] || run.status), " ", run.message));
  root.append(h("p", { class: "help" }, "Request: " + run.prompt));
  if (run.can_open_chat) root.append(h("p", {}, h("button", { class: "secondary", onclick: openChat }, "Open this chat in VS Code")));
  if (run.pending) root.append(pendingBlock(run));
  if (run.status === "completed" || run.status === "stopped") {
    root.append(h("h3", {}, "Final summary"), h("div", { class: "ref" }, run.summary || "(the agent gave no final text)"));
  }
  root.append(h("h3", {}, "Output files (" + run.files.length + ")"), filesBlock(run));
  root.append(h("h3", {}, "Progress"), progressBlock());
  root.append(h("p", {}, h("button", { class: "secondary", onclick: () => { showPicker(); refresh(); } }, "Start another")));
}
function pendingBlock(run) {
  const p = run.pending;
  const box = h("div", { class: "panel pending" }, h("strong", {}, p.kind === "question" ? "The agent is asking a question" : "Waiting for tool approval"), h("div", { class: "ref" }, p.text));
  const msg = h("span", { class: "bad" });
  const act = (a) => async () => { msg.textContent = ""; try { await api("POST", "/api/runs/" + run.id + "/decide", { action: a }); } catch (e) { msg.textContent = e.message; } };
  if (p.can_decide) box.append(h("button", { onclick: act("accept") }, "Allow"), " ", h("button", { class: "danger", onclick: act("skip") }, "Skip"), " ");
  box.append(h("span", { class: "help" }, "Answer questions and review approvals in the VS Code chat."), " ", msg);
  return box;
}
async function openChat() { try { await api("POST", "/api/runs/" + state.runId + "/open"); } catch (e) { banner(e.message); } }
function filesBlock(run) {
  if (!run.files.length) return h("p", { class: "help" }, "No output files yet.");
  const table = h("table", {}, h("tr", {}, h("th", {}, "File"), h("th", {}, "How"), h("th", {}, "Size"), h("th", {}, "")));
  for (const f of run.files) {
    const links = h("td", {});
    if (f.vscode.startsWith("vscode://file/")) links.append(h("a", { href: f.vscode }, "Open in VS Code"), " ");
    if (f.download) links.append(h("button", { class: "secondary", onclick: () => download(run.id, f) }, "Download"));
    table.append(h("tr", {}, h("td", { class: "mono" }, f.path), h("td", {}, f.how), h("td", {}, bytes(f.size)), links));
  }
  return table;
}
async function download(id, f) {
  const r = await fetch("/api/runs/" + id + "/file/" + f.index, { headers: { "X-CSRF-Token": csrf } });
  if (!r.ok) { banner("Download failed."); return; }
  const url = URL.createObjectURL(await r.blob());
  const a = h("a", { href: url, download: f.path.split("/").pop() }); document.body.append(a); a.click(); a.remove(); URL.revokeObjectURL(url);
}
function progressBlock() {
  const box = h("div", { class: "log" });
  for (const i of state.progress.slice(-120)) {
    const label = i.sub ? "subagent" : i.kind === "tool" ? "tool" : i.kind === "user" ? "you" : i.kind === "error" ? "error" : "agent";
    box.append(h("div", { class: "line " + i.kind + (i.failed ? " failed" : "") }, when(i.time) + "  [" + label + "] " + i.text));
  }
  if (!state.progress.length) box.append("Waiting for the first messages...");
  return box;
}

async function refresh() {
  const data = await api("GET", "/api/bootstrap");
  state.categories = data.categories; state.helper = data.helper; renderHelper();
  const root = $("history"); clear(root);
  if (data.history.length) {
    root.append(h("h2", {}, "Recent runs"), h("table", {}, h("tr", {}, h("th", {}, "Run"), h("th", {}, "Category"), h("th", {}, "Status"), h("th", {}, "")),
      data.history.map((r) => h("tr", {}, h("td", { class: "mono" }, r.id), h("td", {}, r.category_id), h("td", {}, r.status),
        h("td", {}, h("button", { class: "secondary", onclick: () => openRun(r.id) }, "Open"))))));
  }
}
refresh().then(showPicker).catch((e) => banner("Could not load: " + e.message));
setInterval(() => { if (!state.runId) refresh().catch(() => {}); }, 10000);
