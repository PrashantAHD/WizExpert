"use strict";
// Every value from the server is rendered with textContent only (never as raw markup).
const csrf = document.querySelector('meta[name="csrf-token"]').content;
const $ = (id) => document.getElementById(id);
const state = { categories: [], helper: {}, runId: null, timer: null, since: 0, progress: [], shown: "", view: "" };
const STATUS_TEXT = {
  starting: "Starting the chat in VS Code", running: "Running", input_needed: "Input needed in VS Code",
  completed: "Finished", stopped: "Stopped", not_started: "Did not start", interrupted: "Interrupted",
  handed_off: "Handed off \u2013 waiting for new chat",
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
  if (response.status === 403 && /csrf token/i.test(String(data.error || ""))) {
    window.location.reload();
    throw new Error("The console restarted; reloading the page to refresh its security token.");
  }
  if (!response.ok) throw new Error(data.error || ("HTTP " + response.status));
  return data;
}
function banner(text) { const b = $("banner"); b.hidden = !text; clear(b); if (text) b.append(text); }
function helperRecoveryMessage(error) {
  const text = String(error && error.message || error);
  if (!/helper|reconnect|chat|trust|permission/i.test(text)) return;
  banner("VS Code helper problem: " + text);
}
function when(t) { return t ? new Date(t * 1000).toLocaleTimeString() : ""; }

function renderHelper() {
  const box = $("helper");
  if (!box) return;
  clear(box);
  const ok = state.helper.connected;
  const details = ok
    ? "Connected · " + (state.helper.agent || "WizExpert") + " · " + (state.helper.workspace || "workspace")
    : state.helper.connecting ? "Connecting the VS Code helper: a standard VS Code window for the workspace is opened automatically..."
      : "VS Code helper not connected" + (state.helper.problem ? " - " + state.helper.problem : " - a standard VS Code window for the workspace is opened automatically");
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
function showPicker(dismiss) {
  clearTimeout(state.timer); state.runId = null; banner("");
  if (dismiss) state.dismissed = true;
  try { sessionStorage.removeItem("wizexpert.run"); } catch (_e) { /* storage unavailable */ }
  if (location.hash) history.replaceState(null, "", location.pathname + location.search);
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
  if (category.id === "risk-issues" || category.id === "weekly-progress-reporting") {
    root.append(h("img", {
      class: "category-visual",
      src: category.id === "risk-issues"
        ? "/static/assets/workflow-risk-issues.svg"
        : "/static/assets/workflow-weekly-progress.svg",
      alt: category.id === "risk-issues"
        ? "Risk Issues workflow: collect, draft, communicate, approve, remediate or accept risk, validate, and update."
        : "Weekly Progress workflow: use the previous report, reuse Risk Issues and Daily Progress records, refresh Wiz status, update deliverables, and carry active work forward.",
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
    for (const [id, button] of Object.entries(stageButtons)) {
      const selected = id === stage.id;
      button.classList.toggle("active", selected);
      if (selected) button.setAttribute("aria-current", "page");
      else button.removeAttribute("aria-current");
    }
    clear(detail);
    detail.append(h("p", { class: "stage-help" }, STAGE_HELP[stage.id] || ""));
    const actions = category.actions.filter((a) => a.stage === stage.id);
    if (stage.id === "in-progress" && category.work_items && category.work_items.length) {
      detail.append(h("p", { class: "work-item-label" }, "Existing work items"));
      const workItems = h("div", { class: "work-item-list" });
      for (const item of category.work_items) {
        const message = h("p", { class: "bad", role: "alert" });
        let refreshButton;
        const refresh = async () => {
          message.textContent = "";
          refreshButton.disabled = true;
          refreshButton.textContent = "Refreshing...";
          try {
            const res = await api("POST", "/api/runs", {
              category_id: category.id,
              action_id: actions[0].id,
              inputs: { work_item: item },
            });
            openRun(res.run_id);
          } catch (e) {
            message.textContent = e.message;
            helperRecoveryMessage(e);
            refreshButton.disabled = false;
            refreshButton.textContent = "Refresh";
          }
        };
        refreshButton = h("button", { class: "secondary work-item-refresh", onclick: refresh }, "Refresh");
        workItems.append(
          h("div", { class: "work-item-entry" },
            h("div", { class: "work-item-card" },
              h("div", { class: "work-item-copy" },
                h("strong", {}, item),
                h("span", {}, "Refresh today's progress"),
              ),
              refreshButton,
            ),
            message,
          ),
        );
      }
      detail.append(workItems);
      return;
    }
    if (actions.length === 1) { detail.append(formPanel(category, actions[0], actions[0].id, null)); return; }
    const bar = h("div", { class: "action-grid" });
    const form = h("div", {});
    const actionButtons = {};
    for (const a of actions) {
      const actionButton = h("button", {
        class: "secondary action-card",
        onclick: () => {
          for (const [id, button] of Object.entries(actionButtons)) {
            const selected = id === a.id;
            button.classList.toggle("active", selected);
            if (selected) button.setAttribute("aria-current", "page");
            else button.removeAttribute("aria-current");
          }
          clear(form);
          form.append(h("p", { class: "help" }, a.description), formPanel(category, a, a.id, null));
        },
      }, h("strong", {}, a.title), h("span", { class: "action-description" }, a.description));
      actionButtons[a.id] = actionButton;
      bar.append(actionButton);
    }
    detail.append(bar, form);
  };
  for (const s of category.stages) {
    const button = h(
      "button",
      { class: "stage-button", "data-title": s.title, onclick: () => showStage(s) },
      s.title,
    );
    stageButtons[s.id] = button;
    stageBar.append(button, " ");
  }
  stageBar.append(
    h("button", { class: "secondary", onclick: showPicker }, "Back"),
    h("span", { class: "nav-help" }, "Return to workflows"),
  );
  root.append(stageBar, detail);
}
function previousReportPicker() {
  // Options come from a local, read-only listing of weekly-progress folders (names only).
  const FIRST = "", MANUAL = "__manual__";
  const select = h("select", {}, h("option", { value: FIRST }, "None: this is the first report"));
  const manual = h("input", { type: "text", maxlength: 120, autocomplete: "off", placeholder: "folder name under deliverables", hidden: true });
  const note = h("div", { class: "help" }, "Loading previous reports...");
  const manualOption = () => h("option", { value: MANUAL }, "Enter a folder name manually");
  select.append(manualOption());
  select.addEventListener("change", () => { manual.hidden = select.value !== MANUAL; });
  api("GET", "/api/weekly-progress/previous-reports").then((res) => {
    clear(select);
    select.append(h("option", { value: FIRST }, "None: this is the first report"));
    for (const r of res.reports) select.append(h("option", { value: r.reference }, r.reference));
    select.append(manualOption());
    note.textContent = res.empty ? res.message : res.reports.length + " previous report folder(s) found.";
  }).catch(() => {
    select.value = MANUAL; manual.hidden = false;
    note.textContent = "Could not list previous reports; leave empty for the first report or enter a folder name.";
  });
  const field = { get value() { return select.value === MANUAL ? manual.value : select.value; } };
  return { field, node: h("div", {}, select, manual, note) };
}
function formPanel(category, spec, actionId, onBack, initialValues = {}) {
  const panel = h("div", { class: "panel" });
  const fields = {};
  for (const f of spec.fields) {
    const multiline = f.name === "email_text";
    const input = multiline
      ? h("textarea", { rows: 8, maxlength: f.max_length || 200, placeholder: f.placeholder || "", autocomplete: "off" })
      : h("input", { type: "text", maxlength: f.max_length || 200, placeholder: f.placeholder || "", autocomplete: "off" });
    if (category.id === "weekly-progress-reporting" && f.name === "previous_report") {
      const picker = previousReportPicker();
      fields[f.name] = picker.field;
      panel.append(h("label", {}, f.label, h("div", { class: "help" }, f.help)), picker.node);
      continue;
    }
    if (f.options && f.options.length) {
      const id = "opts-" + f.name;
      input.setAttribute("list", id);
      panel.append(h("datalist", { id }, ...f.options.map((o) => h("option", { value: o }))));
    }
    fields[f.name] = input;
    if (initialValues[f.name]) input.value = initialValues[f.name];
    panel.append(h("label", {}, f.label + (f.required ? " *" : ""), h("div", { class: "help" }, f.help)), input);
  }
  const message = h("p", { class: "bad", role: "alert" });
  const startLabel = actionId === "continue-work-item"
    ? "Refresh"
    : actionId === "new" || !actionId
      ? (category.stages && category.stages.length ? "Proceed" : "Start")
      : "Proceed";
  const start = h("button", {}, startLabel);
  start.addEventListener("click", async () => {
    message.textContent = ""; start.disabled = true;
    try {
      const inputs = {}; for (const [k, v] of Object.entries(fields)) inputs[k] = v.value;
      const body = { category_id: category.id, inputs };
      if (actionId) body.action_id = actionId;
      const res = await api("POST", "/api/runs", body);
      openRun(res.run_id);
    } catch (e) {
      message.textContent = e.message;
      helperRecoveryMessage(e);
      start.disabled = false;
    }
  });
  panel.append(h("p", {}, start, onBack ? " " : null, onBack ? h("button", { class: "secondary", onclick: onBack }, "Back") : null), message);
  return panel;
}

// ---- page 3: results ---------------------------------------------------------------------------------
function openRun(runId) {
  clearTimeout(state.timer);
  state.runId = runId; state.since = 0; state.progress = []; state.shown = ""; state.dismissed = false; state.view = "run";
  try { sessionStorage.setItem("wizexpert.run", runId); } catch (_e) { /* storage unavailable */ }
  if (location.hash !== "#run=" + runId) history.replaceState(null, "", "#run=" + runId);
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
  } catch (e) {
    if (/unknown run/i.test(e.message)) { showPicker(true); refresh().catch(() => {}); return; } // stale id from an old tab/link
    banner("Lost contact with the console: " + e.message); state.timer = setTimeout(poll, 4000);
  }
}
function renderRun(run) {
  // Rebuild only when something changed, so button messages and scroll position survive polling.
  const sig = JSON.stringify([run.status, run.message, run.pending, run.summary, run.files.map((f) => [f.path]), state.since, run.can_open_chat, run.can_stop, run.can_open_output]);
  if (sig === state.shown) return;
  state.shown = sig;
  const root = $("run"); clear(root);
  root.append(h("h2", {}, run.category),
    h("p", {}, h("span", { class: "badge " + run.status }, STATUS_TEXT[run.status] || run.status), " ", run.message));
  root.append(h("p", { class: "help" }, "Request: " + run.prompt));
  if (run.can_open_chat) root.append(h("p", {}, h("button", { class: "secondary", onclick: openChat }, "Open this chat in VS Code")));
  if (run.can_stop) root.append(stopButton(run));
  if (run.pending) root.append(pendingBlock(run));
  if (run.status === "completed" || run.status === "stopped") {
    root.append(h("h3", {}, "Final summary"), h("div", { class: "ref" }, run.summary || "(the agent gave no final text)"));
  }
  root.append(h("h3", {}, "Output files (" + run.files.length + ")"), filesBlock(run));
  if (run.can_open_output) root.append(h("p", {}, h("button", { class: "secondary", onclick: openLatestOutput }, "View latest output")));
  root.append(h("h3", {}, "Progress"), activityBlock());
  root.append(rawProgressBlock());
  root.append(h("p", {}, h("button", { class: "secondary", onclick: () => { showPicker(true); refresh(); } }, "Start another")));
}
function stopButton(run) {
  const button = h("button", { class: "danger", onclick: async () => {
    button.disabled = true;
    button.textContent = "Stopping...";
    try {
      await api("POST", "/api/runs/" + run.id + "/stop");
      banner("Stop requested for the live VS Code chat.");
    } catch (e) {
      button.disabled = false;
      button.textContent = "Stop";
      banner(e.message);
    }
  } }, "Stop");
  return h("p", {}, button);
}
async function openLatestOutput() {
  try {
    await api("POST", "/api/runs/" + state.runId + "/open-output");
    banner("Opened the latest local output in VS Code.");
  } catch (e) { banner(e.message); }
}
function pendingBlock(run) {
  const p = run.pending;
  const handoff = p.kind === "permission" && p.text.startsWith("Spend-Guard handoff");
  const box = h("div", { class: "panel pending" }, h("strong", {}, p.kind === "question" ? "The agent is asking a question" : handoff ? "Approve handoff to a new chat" : "Waiting for tool approval"), h("div", { class: "ref" }, p.text));
  if (p.detail) box.append(h("div", { class: "help" }, "Handoff prompt"), h("div", { class: "ref" }, p.detail));
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
function activityBlock() {
  const box = h("div", { class: "activity", "aria-live": "polite" });
  const relevant = state.progress.filter((i) => i.kind === "tool" || i.kind === "assistant" || i.kind === "error" || i.kind === "handoff");
  const recent = relevant.slice(-14);
  const important = relevant.filter((i) => i.kind === "error" || i.failed || i.aborted);
  const items = [...important, ...recent].filter((item, index, all) => all.indexOf(item) === index);
  if (!items.length) return h("div", { class: "activity empty" }, "Waiting for the agent to start...");
  for (const i of items) {
    const active = i.kind === "tool" && !i.completed && !i.failed && !i.aborted;
    const label = i.kind === "tool"
      ? (i.sub ? (active ? "Running subagent task" : i.failed ? "Subagent task failed" : i.aborted ? "Subagent task stopped" : "Subagent task complete")
        : (active ? "Running task" : i.failed ? "Task failed" : i.aborted ? "Task stopped" : "Task complete"))
      : i.kind === "error" ? "Error" : i.kind === "handoff" ? "Handed off to a new chat" : i.sub ? "Subagent update" : "Agent update";
    const bad = i.kind === "error" || i.failed || i.aborted;
    box.append(h("div", { class: "activity-item " + i.kind + (active ? " active" : "") + (bad ? " failed" : "") },
      h("span", { class: "activity-marker", "aria-hidden": "true" }, active ? "●" : bad ? "!" : "✓"),
      h("div", { class: "activity-copy" },
        h("strong", {}, label),
        h("span", {}, i.text),
      ),
      h("time", {}, when(i.time)),
    ));
  }
  return box;
}
function rawProgressBlock() {
  const details = h("details", { class: "raw-progress" });
  details.append(h("summary", {}, "Show raw event log"));
  const box = h("div", { class: "log" });
  for (const i of state.progress.slice(-120)) {
    const label = i.sub ? "subagent" : i.kind === "tool" ? "tool" : i.kind === "user" ? "you" : i.kind === "error" ? "error" : "agent";
    box.append(h("div", { class: "line " + i.kind + (i.failed ? " failed" : "") }, when(i.time) + "  [" + label + "] " + i.text));
  }
  if (!state.progress.length) box.append("Waiting for the first messages...");
  details.append(box);
  return details;
}

let lastConnect = 0;
async function autoConnect() {
  // The console opens a standard VS Code window for the workspace itself; one recovery at a time.
  if (state.helper.connected || Date.now() - lastConnect < 30000) return;
  lastConnect = Date.now();
  try { Object.assign(state.helper, await api("POST", "/api/helper/connect")); renderHelper(); } catch (_e) { /* shown by the next status */ }
}
function wantedRun(data) {
  // Deep link or this tab's last run first (it may have finished: the run view shows the final
  // state), then the newest active run reported by the backend.
  const fromHash = /^#run=([\w-]+)$/.exec(location.hash);
  let saved = "";
  try { saved = sessionStorage.getItem("wizexpert.run") || ""; } catch (_e) { /* storage unavailable */ }
  return (fromHash && fromHash[1]) || saved || (data.active && data.active.length ? data.active[0].id : "");
}
async function refresh() {
  const data = await api("GET", "/api/bootstrap");
  state.categories = data.categories; state.helper = data.helper; renderHelper();
  autoConnect();
  state.active = data.active || [];
  if (!state.runId && state.view !== "inputs") {
    if (!state.booted) {
      const id = wantedRun(data);
      if (id) openRun(id);
    } else if (!state.dismissed && state.active.length) {
      openRun(state.active[0].id);
    }
  }
  state.booted = true;
  const root = $("history"); clear(root);
  if (state.active.length) {
    root.append(h("div", { class: "panel pending" }, h("strong", {}, "A task is still running: "),
      state.active.map((r) => h("button", { class: "secondary", onclick: () => openRun(r.id) }, "Open " + r.category_id + " (" + (STATUS_TEXT[r.status] || r.status) + ")"))));
  }
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
refresh().then(() => { if (state.view !== "inputs" && !state.runId) showPicker(); }).catch((e) => banner("Could not load: " + e.message));
window.addEventListener("hashchange", () => {
  const m = /^#run=([\w-]+)$/.exec(location.hash);
  if (m && m[1] !== state.runId) openRun(m[1]);
});
setInterval(() => { if (!state.runId) refresh().catch(() => {}); }, 10000);
