"use strict";
// Every value from the server is rendered with textContent only (never as raw markup).
const csrf = document.querySelector('meta[name="csrf-token"]').content;
const $ = (id) => document.getElementById(id);
const state = { categories: [], helper: {}, runId: null, timer: null, since: 0, progress: [], shown: "", view: "" };
const STATUS_TEXT = {
  starting: "Starting the chat in VS Code", running: "Running", input_needed: "Input needed in VS Code",
  completed: "Finished", stopped: "Stopped", not_started: "Did not start", interrupted: "Interrupted",
};
const TERMINAL = new Set(["completed", "stopped", "not_started", "interrupted"]);
const STAGE_HELP = {
  new: "Start a fresh review and prepare the initial local deliverables.",
  "in-progress": "Continue existing work with an acceptance, email, or status action.",
};

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
function when(t) { return t ? new Date(t * 1000).toLocaleTimeString() : ""; }

function renderHelper() {
  const box = $("helper");
  if (!box) return;
  clear(box);
  const ok = state.helper.connected;
  const details = ok
    ? "Connected · " + (state.helper.agent || "WizExpert") + " · " + (state.helper.workspace || "workspace")
    : "VS Code helper not connected";
  box.append(h("span", {}, h("span", { class: "dot" + (ok ? " on" : "") }), details));
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
  state.view = "picker";
  $("home").hidden = false; $("inputs").hidden = true; $("run").hidden = true;
  const root = $("picker"); clear(root);
  root.append(h("h2", {}, "Select your workstream"));
}

// ---- page 2: inputs ---------------------------------------------------------------------------------
function showInputs(category) {
  state.view = "inputs";
  $("home").hidden = true; $("run").hidden = true; $("inputs").hidden = false; banner("");
  const root = $("inputs"); clear(root);
  root.append(h("button", { class: "secondary back-home", onclick: showPicker }, "Back to workflows"));
  if (category.id === "risk-issues") {
    root.append(h("img", {
      class: "category-visual",
      src: "/static/assets/workflow-risk-issues.svg",
      alt: "Risk Issues workflow: collect, draft, communicate, approve, remediate or accept risk, validate, and update.",
    }));
  }
  root.append(
    h("div", { class: "detail-heading" },
      h("p", { class: "breadcrumb" }, "Workflows / ", h("strong", {}, category.title)),
    ),
    h("h2", {}, category.title),
    h("p", { class: "page-intro" }, category.description),
    h("div", { class: "next-panel" },
      h("strong", {}, "What happens next?"),
      h("span", {}, "Your input opens a new VS Code WizExpert chat. This page only mirrors progress and local output files."),
    ),
  );
  if (!(category.stages || []).length) { root.append(formPanel(category, category, null, showPicker)); return; }
  // Staged category (e.g. Risk Issues): stage buttons, then one operation form at a time.
  const detail = h("div", {});
  const stageBar = h("p", {});
  const stageButtons = {};
  const showStage = (stage) => {
    clear(detail);
    detail.append(h("p", { class: "stage-help" }, STAGE_HELP[stage.id] || ""));
    const actions = category.actions.filter((a) => a.stage === stage.id);
    if (stage.id === "in-progress" && category.work_items && category.work_items.length) {
      detail.append(h("p", { class: "work-item-label" }, "Existing work items"));
      const workItems = h("div", { class: "work-item-list" });
      const form = h("div", {});
      for (const item of category.work_items) {
        workItems.append(h("button", {
          class: "secondary work-item-button",
          onclick: () => {
            clear(form);
            form.append(formPanel(category, actions[0], actions[0].id, null, { work_item: item }));
          },
        }, h("strong", {}, item), h("span", {}, "Continue progress")));
      }
      detail.append(workItems, form);
      return;
    }
    if (actions.length === 1) { detail.append(formPanel(category, actions[0], actions[0].id, null)); return; }
    const bar = h("div", { class: "action-grid" });
    const form = h("div", {});
    for (const a of actions) {
      bar.append(h("button", {
        class: "secondary action-card",
        onclick: () => { clear(form); form.append(h("p", { class: "help" }, a.description), formPanel(category, a, a.id, null)); },
      }, h("strong", {}, a.title), h("span", { class: "action-description" }, a.description)));
    }
    detail.append(bar, form);
  };
  for (const s of category.stages) {
    const button = h("button", { onclick: () => showStage(s) }, s.title);
    stageButtons[s.id] = button;
    stageBar.append(button, " ");
  }
  stageBar.append(h("button", { class: "secondary", onclick: showPicker }, "Back"), h("span", { class: "nav-help" }, "Return to workflows"));
  root.append(stageBar, detail);
}
function formPanel(category, spec, actionId, onBack, initialValues = {}) {
  const panel = h("div", { class: "panel" });
  const fields = {};
  for (const f of spec.fields) {
    const multiline = f.name === "email_text";
    const input = multiline
      ? h("textarea", { rows: 8, maxlength: f.max_length || 200, placeholder: f.placeholder || "", autocomplete: "off" })
      : h("input", { type: "text", maxlength: f.max_length || 200, placeholder: f.placeholder || "", autocomplete: "off" });
    fields[f.name] = input;
    if (initialValues[f.name]) input.value = initialValues[f.name];
    panel.append(h("label", {}, f.label + (f.required ? " *" : ""), h("div", { class: "help" }, f.help)), input);
  }
  const message = h("p", { class: "bad", role: "alert" });
  const start = h("button", {}, actionId === "new" || !actionId ? (category.stages && category.stages.length ? "Proceed" : "Start") : "Proceed");
  start.addEventListener("click", async () => {
    message.textContent = ""; start.disabled = true;
    try {
      const inputs = {}; for (const [k, v] of Object.entries(fields)) inputs[k] = v.value;
      const body = { category_id: category.id, inputs };
      if (actionId) body.action_id = actionId;
      const res = await api("POST", "/api/runs", body);
      openRun(res.run_id);
    } catch (e) { message.textContent = e.message; start.disabled = false; }
  });
  panel.append(h("p", {}, start, onBack ? " " : null, onBack ? h("button", { class: "secondary", onclick: onBack }, "Back") : null), message);
  return panel;
}

// ---- page 3: results ---------------------------------------------------------------------------------
function openRun(runId) {
  state.runId = runId; state.since = 0; state.progress = []; state.shown = "";
  $("home").hidden = true; $("inputs").hidden = true; $("run").hidden = false; clear($("run"));
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
  const sig = JSON.stringify([run.status, run.message, run.pending, run.summary, run.files.map((f) => [f.path]), state.since, run.can_open_chat]);
  if (sig === state.shown) return;
  state.shown = sig;
  const root = $("run"); clear(root);
  root.append(h("h2", {}, run.category),
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
  if (!run.files.length) return h("p", { class: "help" }, "No deliverable files yet.");
  const table = h("table", {}, h("tr", {}, h("th", {}, "File"), h("th", {}, "Location")));
  for (const f of run.files) table.append(h("tr", {}, h("td", { class: "mono" }, f.name), h("td", { class: "mono" }, f.location)));
  return table;
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
    root.append(h("h2", {}, "Recent activity"), h("table", {}, h("tr", {}, h("th", {}, "Run"), h("th", {}, "Category"), h("th", {}, "Status"), h("th", {}, "")),
      data.history.map((r) => h("tr", {}, h("td", { class: "mono" }, r.id), h("td", {}, r.category_id), h("td", {}, r.status),
        h("td", {}, h("button", { class: "secondary", onclick: () => openRun(r.id) }, "Open"))))));
  }
}
document.querySelectorAll("[data-category]").forEach((link) => {
  link.addEventListener("click", async () => {
    let category = state.categories.find((c) => c.id === link.dataset.category);
    if (!category) {
      try {
        await refresh();
        category = state.categories.find((c) => c.id === link.dataset.category);
      } catch (e) {
        banner("Could not load workflows: " + e.message);
        return;
      }
    }
    if (!category) {
      banner("This workflow is not available yet. Try again after the console finishes loading.");
      return;
    }
    showInputs(category);
  });
});
refresh().then(() => { if (state.view !== "inputs") showPicker(); }).catch((e) => banner("Could not load: " + e.message));
setInterval(() => { if (!state.runId) refresh().catch(() => {}); }, 10000);
