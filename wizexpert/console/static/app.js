"use strict";
// Every value from the server is rendered with textContent only (never as raw markup).
const csrf = document.querySelector('meta[name="csrf-token"]').content;
const $ = (id) => document.getElementById(id);
const state = {
  categories: [], helper: {}, runId: null, timer: null, since: 0, progress: [], shown: "", view: "",
  active: [], history: [], updated: 0, stale: false, refreshing: false, refreshError: "", loaded: false, dataBars: [],
  hf: { status: "", category: "", q: "" }, hvResults: null, hvCategory: null, hvClear: null, pvResults: null,
  activityBox: null, activityCategory: "", wfId: "", runStatus: "", runCategory: "", focusNext: "", restoreY: null, routeSeq: 0,
};
const STATUS_TEXT = {
  starting: "Starting the chat in VS Code", running: "Running", input_needed: "Input needed in VS Code",
  completed: "Finished", stopped: "Stopped", not_started: "Did not start", interrupted: "Interrupted",
  handed_off: "Handed off \u2013 waiting for new chat",
};
const TERMINAL = new Set(["completed", "stopped", "not_started", "interrupted"]);
const NEEDS_ATTENTION = new Set(["input_needed", "handed_off"]);
const STAGE_HELP = {
  new: "Start a fresh review and prepare the initial local deliverables.",
  "in-progress": "Continue existing work with an acceptance, email, or status action.",
};
const VIEWS = ["home", "dashboard", "progress", "history", "workflow", "run"];

// ---- small DOM helpers ------------------------------------------------------------------------------
function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (k === "class") el.className = v;
    else if (k === "onclick") el.addEventListener("click", v);
    else if (k === "onsubmit") el.addEventListener("submit", v);
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
function banner(text) { const b = $("banner"); if (!b) return; b.hidden = !text; clear(b); if (text) b.append(text); }
function helperRecoveryMessage(error) {
  const text = String(error && error.message || error);
  if (!/helper|reconnect|chat|trust|permission/i.test(text)) return;
  banner("VS Code helper problem: " + text);
}
function when(t) { return t ? new Date(t * 1000).toLocaleTimeString() : ""; }
const catTitle = (id) => { const c = state.categories.find((x) => x.id === id); return c ? c.title : id; };
const fmtDate = (t) => (t ? new Date(t * 1000).toLocaleString() : "");
function badge(status) { return h("span", { class: "badge " + status }, STATUS_TEXT[status] || status); }

// ---- VS Code helper (sidebar) -----------------------------------------------------------------------
function renderHelper() {
  const box = $("helper");
  if (!box) return;
  clear(box);
  const ok = state.helper.connected;
  const details = ok
    ? "Connected \u00b7 " + (state.helper.agent || "WizExpert") + " \u00b7 " + (state.helper.workspace || "workspace")
    : state.helper.connecting ? "Connecting the VS Code helper: a standard VS Code window for the workspace is opened automatically..."
      : "VS Code helper not connected" + (state.helper.problem ? " - " + state.helper.problem : " - a standard VS Code window for the workspace is opened automatically");
  box.append(h("p", { class: "helper-line" }, h("span", { class: "dot" + (ok ? " on" : ""), "aria-hidden": "true" }), h("span", {}, details)));
  box.append(h("button", { class: "secondary small", type: "button", onclick: checkHelper }, "Check helper"));
}
async function checkHelper() {
  try {
    const r = await api("POST", "/api/helper/probe");
    const chat = r.commands.filter((c) => /newChat|chat\.open$|acceptTool|skipTool/.test(c));
    banner("Helper OK. VS Code " + r.version + ", workspace window: " + r.folders.join(", ") + ". Chat commands seen: " + (chat.join(", ") || "none"));
  } catch (e) { banner("Helper check failed: " + e.message); }
}
let lastConnect = 0;
async function autoConnect() {
  // The console opens a standard VS Code window for the workspace itself; one recovery at a time.
  if (state.helper.connected || Date.now() - lastConnect < 30000) return;
  lastConnect = Date.now();
  try { Object.assign(state.helper, await api("POST", "/api/helper/connect")); renderHelper(); } catch (_e) { /* shown by the next status */ }
}

// ---- routing, drafts and shared UI states -------------------------------------------------------
// Real URLs: /  /in-progress  /history  /workflow/<id>[/<stage>[/<action>]]  /run/<id>.
// Navigation happens only on user action, Back/Forward or the first page load; background refreshes
// never move the user.
const ROUTE_RUN = /^\/run\/([\w-]+)\/?$/;
const ROUTE_WF = /^\/workflow\/([\w-]+)(?:\/([\w-]+))?(?:\/([\w-]+))?\/?$/;
const runPath = (id) => "/run/" + encodeURIComponent(id);
function wfPath(...parts) { return "/workflow/" + parts.filter(Boolean).map(encodeURIComponent).join("/"); }
function plainClick(e) { return e.button === 0 && !(e.metaKey || e.ctrlKey || e.shiftKey || e.altKey); }
function bindLink(a) {
  a.addEventListener("click", (e) => { if (plainClick(e)) { e.preventDefault(); go(a.getAttribute("href")); } });
  return a;
}
function link(href, cls, ...kids) { return bindLink(h("a", { href, class: cls }, ...kids)); }
function showView(name) {
  state.view = name;
  for (const v of VIEWS) { const el = $("v-" + v); if (el) el.hidden = v !== name; }
}
function saveScroll() {
  try { history.replaceState(Object.assign({}, history.state, { y: window.scrollY }), ""); } catch (_e) { /* ignore */ }
}
function restoreScroll() { if (state.restoreY != null) window.scrollTo(0, state.restoreY); }
let settleTimer = 0;
function holdScroll() {
  clearTimeout(settleTimer);
  settleTimer = setTimeout(() => { state.restoreY = null; }, 1500);
}
function announce(text) { const el = $("route-status"); if (el) el.textContent = text || ""; }
function setTitle(text) {
  const label = $("page-label"); if (label) label.textContent = text || "Home";
  document.title = text ? text + " \u00b7 WizExpert Workflow Console" : "WizExpert Workflow Console";
  announce(text);
}
function go(url, opts = {}) {
  saveScroll();
  state.focusNext = opts.focus || "heading";
  const same = url === location.pathname + location.search;
  if (!same) history.pushState({ y: 0 }, "", url);
  state.restoreY = same ? window.scrollY : 0;
  route();
}
function applyFocus() {
  const kind = state.focusNext; state.focusNext = "";
  if (!kind) return;
  const root = $("v-" + state.view);
  let target = null;
  if (kind === "stage") target = root.querySelector(".seg.active");
  else if (kind === "action") target = root.querySelector(".option.active");
  if (!target) target = root.querySelector(".route-heading") || root;
  target.focus({ preventScroll: true });
}
function stateBox(kind, title, detail, actionLabel, action) {
  return h("div", { class: "state-box " + kind, role: kind === "error" ? "alert" : "status" },
    kind === "loading" ? h("span", { class: "spinner", "aria-hidden": "true" }) : null,
    h("div", { class: "state-copy" }, h("strong", {}, title), detail ? h("span", {}, detail) : null),
    action ? h("button", { class: "secondary", type: "button", onclick: action }, actionLabel) : null);
}
function arrowNav(container) {
  container.addEventListener("keydown", (e) => {
    if (!["ArrowRight", "ArrowDown", "ArrowLeft", "ArrowUp", "Home", "End"].includes(e.key)) return;
    const items = [...container.querySelectorAll("button:not([disabled])")];
    const i = items.indexOf(document.activeElement);
    if (i < 0) return;
    const step = e.key === "ArrowRight" || e.key === "ArrowDown" ? 1 : -1;
    const next = e.key === "Home" ? 0 : e.key === "End" ? items.length - 1 : (i + step + items.length) % items.length;
    e.preventDefault(); items[next].focus();
  });
}
// Drafts: unsaved form values per workflow, kept in sessionStorage only. Secret-looking fields and
// values are never stored.
const DRAFT_PREFIX = "wizexpert.draft.v1.";
const SECRET_NAME = /token|secret|passw|credential|api[-_]?key|authorization|cookie|private/i;
const SECRET_VALUE = /(bearer\s+[\w.~+\/-]{8,}|gh[pousr]_\w{16,}|eyJ[\w-]{20,}\.|-----BEGIN [A-Z ]*KEY|sk-[A-Za-z0-9]{16,}|AKIA[0-9A-Z]{12,})/i;
function loadDraft(categoryId) {
  try {
    const value = JSON.parse(sessionStorage.getItem(DRAFT_PREFIX + categoryId) || "{}");
    return value && typeof value === "object" ? value : {};
  } catch (_e) { return {}; }
}
function saveDraft(categoryId, key, values) {
  const clean = {};
  for (const [name, value] of Object.entries(values)) {
    const text = String(value == null ? "" : value);
    if (!text || SECRET_NAME.test(name) || SECRET_VALUE.test(text) || text.length > 5000) continue;
    clean[name] = text;
  }
  try {
    const all = loadDraft(categoryId);
    if (Object.keys(clean).length) all[key] = clean; else delete all[key];
    if (Object.keys(all).length) sessionStorage.setItem(DRAFT_PREFIX + categoryId, JSON.stringify(all));
    else sessionStorage.removeItem(DRAFT_PREFIX + categoryId);
  } catch (_e) { /* storage unavailable: drafts are best effort */ }
}
function clearDraft(categoryId, key) { saveDraft(categoryId, key, {}); }

// Header indicator for runs that are still working (visible on every page).
function activeRuns() {
  const list = (state.active || []).filter((r) => !TERMINAL.has(r.status) && r.id !== state.runId);
  if (state.runId && state.runStatus && !TERMINAL.has(state.runStatus)) {
    list.unshift({ id: state.runId, status: state.runStatus, category_id: state.runCategory });
  }
  return list;
}
function updateIndicator() {
  const navCount = $("nav-count");
  if (navCount) {
    const n = state.active.length, a = state.active.filter((r) => NEEDS_ATTENTION.has(r.status)).length;
    navCount.textContent = n ? String(n) : "";
    navCount.classList.toggle("attention", a > 0);
    if (n) navCount.setAttribute("aria-label", n + " in progress" + (a ? ", " + a + " need attention" : "")); else navCount.removeAttribute("aria-label");
  }
  const el = $("active-run");
  if (!el) return;
  const list = activeRuns();
  el.hidden = !list.length;
  clear(el);
  if (!list.length) return;
  const label = list.length === 1 ? "1 task running" : list.length + " tasks running";
  el.append(h("span", { class: "pulse", "aria-hidden": "true" }), label);
  el.setAttribute("href", runPath(list[0].id));
  el.setAttribute("aria-label", label + ". Open " + (catTitle(list[0].category_id) || "the run") + " (" + (STATUS_TEXT[list[0].status] || list[0].status) + ")");
}
function updateNav() {
  const here = state.view === "home" ? "/" : state.view === "dashboard" ? "/dashboard" : state.view === "progress" ? "/in-progress" : state.view === "history" ? "/history"
    : state.view === "workflow" ? wfPath(state.wfId) : "";
  document.querySelectorAll(".nav a").forEach((a) => {
    if (a.getAttribute("href") === here) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
  });
}
function renderNavWorkflows() {
  mount($("nav-workflows"), JSON.stringify(state.categories.map((c) => [c.id, c.title])), (box) => {
    for (const c of state.categories) box.append(bindLink(h("a", { href: wfPath(c.id), class: "nav-link sub", title: c.title }, h("span", { class: "ico", "aria-hidden": "true" }, (c.title || "?").charAt(0)), h("span", { class: "nav-label" }, c.title))));
    updateNav();
  });
}
function showStatusPage(kind, title, detail, actionLabel, action) {
  showView("workflow");
  const root = $("v-workflow"); clear(root);
  root.append(h("h1", { class: "route-heading", tabindex: "-1" }, title), stateBox(kind, title, detail, actionLabel, action),
    h("p", {}, h("button", { class: "secondary", type: "button", onclick: () => go("/") }, "Back to Home")));
  setTitle(title);
}
async function route() {
  const seq = ++state.routeSeq;
  clearTimeout(state.timer); state.runId = null; state.runStatus = ""; state.shown = "";
  holdScroll();
  const path = location.pathname;
  const bare = path.length > 1 ? path.replace(/\/$/, "") : path;
  let m;
  if (bare === "/dashboard") {
    showDashboard(); loadData();
  } else if (bare === "/history") {
    showHistory(); loadData();
  } else if (bare === "/in-progress") {
    showProgress(); loadData();
  } else if ((m = ROUTE_RUN.exec(path))) {
    openRun(m[1]);
  } else if ((m = ROUTE_WF.exec(path))) {
    let category = state.categories.find((c) => c.id === m[1]);
    if (!category) {
      showStatusPage("loading", "Loading workflow", "Fetching the available workflows.");
      try { await refresh(); } catch (e) {
        if (seq !== state.routeSeq) return;
        showStatusPage("error", "Could not load workflows", e.message, "Retry", () => route());
        return;
      }
      if (seq !== state.routeSeq) return;
      category = state.categories.find((c) => c.id === m[1]);
    }
    if (!category) showStatusPage("error", "Workflow not found", "No workflow named \u201c" + m[1] + "\u201d is available.");
    else showWorkflow(category, m[2], m[3]);
  } else {
    if (path !== "/") history.replaceState(history.state, "", "/");
    showHome();
    loadData();
  }
  renderAll();
  updateNav();
  restoreScroll();
  applyFocus();
}

// ---- data layer: saved snapshot (stale-while-refresh) --------------------------------------------------
// Only run id, workflow id, status and start time are cached, in sessionStorage (this tab). Nothing
// else from the server, no helper details and no form values ever enter this cache.
const CACHE_KEY = "wizexpert.cache.v2";
const CACHE_MAX_AGE = 24 * 3600 * 1000;
const pickRun = (r) => ({ id: String(r.id), category_id: String(r.category_id), status: String(r.status), created: Number(r.created) || 0 });
function readCache() {
  try {
    const c = JSON.parse(sessionStorage.getItem(CACHE_KEY) || "null");
    if (c && Date.now() - c.t < CACHE_MAX_AGE && Array.isArray(c.history) && Array.isArray(c.active)) {
      state.history = c.history.map(pickRun); state.active = c.active.map(pickRun);
      state.updated = c.t; state.stale = true; state.loaded = true;
    }
  } catch (_e) { /* ignore a damaged cache */ }
}
function writeCache() {
  try {
    sessionStorage.setItem(CACHE_KEY, JSON.stringify({ t: state.updated, history: state.history.map(pickRun), active: state.active.map(pickRun) }));
  } catch (_e) { /* best effort */ }
}
let inflight = null;
function refresh() {
  if (inflight) return inflight;
  state.refreshing = true; updateDataBars();
  inflight = (async () => {
    try {
      const data = await api("GET", "/api/bootstrap");
      state.categories = data.categories; state.helper = data.helper; renderHelper();
      autoConnect();
      state.active = data.active || []; state.history = data.history || [];
      state.updated = Date.now(); state.stale = false; state.loaded = true; state.refreshError = "";
      writeCache();
    } catch (e) {
      state.refreshError = e.message; throw e;
    } finally {
      state.refreshing = false; inflight = null; renderAll();
    }
  })();
  return inflight;
}
function loadData() { refresh().catch(() => {}); }
function makeDataBar() {
  state.dataBars = state.dataBars.filter((b) => b.node.isConnected);
  const text = h("span", { class: "databar-text", role: "status", "aria-live": "polite" });
  const button = h("button", { class: "secondary small", type: "button", onclick: () => loadData() }, "Refresh");
  const node = h("div", { class: "databar" }, text, button);
  const bar = {
    node,
    update() {
      node.classList.toggle("error", !!state.refreshError);
      node.classList.toggle("busy", state.refreshing);
      button.disabled = state.refreshing;
      button.textContent = state.refreshing ? "Refreshing..." : "Refresh";
      const at = state.updated ? new Date(state.updated).toLocaleTimeString() : "";
      if (state.refreshError) text.textContent = "Could not refresh (" + state.refreshError + ")." + (at ? " Showing saved data from " + at + "." : "");
      else if (state.refreshing) text.textContent = state.loaded ? "Showing " + (state.stale ? "saved" : "current") + " data from " + at + " \u00b7 refreshing..." : "Loading...";
      else text.textContent = at ? "Updated " + at : "Not loaded yet";
    },
  };
  state.dataBars.push(bar); bar.update();
  return node;
}
function updateDataBars() { for (const b of state.dataBars) b.update(); }
function mount(el, sig, build) {
  if (!el || el.dataset.sig === sig) return false;
  el.dataset.sig = sig; clear(el); build(el);
  return true;
}
function dataGate(box) {
  // Shared loading/error state while there is nothing to show yet; returns true when data is usable.
  if (state.loaded) return true;
  box.append(state.refreshError
    ? stateBox("error", "Could not load runs", state.refreshError, "Retry", () => loadData())
    : stateBox("loading", "Loading runs...", "Reading the local run records."));
  return false;
}

// ---- reusable components ------------------------------------------------------------------------------
function pageHead(title, lede) {
  return h("header", { class: "page-head" }, h("h1", { class: "route-heading", tabindex: "-1" }, title), lede ? h("p", { class: "lede" }, lede) : null);
}
function breadcrumb(...items) {
  const kids = [];
  items.forEach((it, i) => {
    if (i) kids.push(h("span", { class: "sep", "aria-hidden": "true" }, "/"));
    kids.push(it.href ? link(it.href, "", it.label) : h("span", { "aria-current": "page" }, it.label));
  });
  return h("nav", { class: "breadcrumb", "aria-label": "Breadcrumb" }, kids);
}
function runCard(r) {
  const attention = NEEDS_ATTENTION.has(r.status);
  return h("article", { class: "run-card" + (attention ? " attention" : "") },
    h("div", { class: "run-card-main" }, h("strong", {}, catTitle(r.category_id)), h("span", { class: "mono meta" }, r.id), h("span", { class: "meta" }, "Started " + fmtDate(r.created))),
    badge(r.status),
    h("button", { type: "button", "aria-label": "Open run " + r.id, onclick: () => go(runPath(r.id)) }, "Open"));
}
function runTable(rows) {
  return h("div", { class: "table-wrap" }, h("table", { class: "data-table" },
    h("caption", { class: "sr-only" }, "Runs"),
    h("thead", {}, h("tr", {}, h("th", { scope: "col" }, "Workflow"), h("th", { scope: "col" }, "Run"), h("th", { scope: "col" }, "Status"), h("th", { scope: "col" }, "Started"), h("th", { scope: "col" }, h("span", { class: "sr-only" }, "Open")))),
    h("tbody", {}, rows.map((r) => h("tr", {}, h("td", {}, catTitle(r.category_id)), h("td", { class: "mono" }, r.id),
      h("td", {}, badge(r.status)), h("td", {}, fmtDate(r.created)),
      h("td", { class: "right" }, h("button", { class: "secondary small", type: "button", "aria-label": "Open run " + r.id, onclick: () => go(runPath(r.id)) }, "Open")))))));
}

// ---- home --------------------------------------------------------------------------------------------
let home = null;
const WF_ART = {
  "risk-issues": "workflow-risk-issues.svg",
  "daily-progress-reporting": "workflow-daily-progress.svg",
  "weekly-progress-reporting": "workflow-weekly-progress.svg",
  "monthly-governance-reporting": "workflow-monthly-governance.svg",
};
const WF_BLURB = {
  "risk-issues": "Prepare deliverables for Wiz issue IDs.",
  "daily-progress-reporting": "Prepare today's progress report.",
  "weekly-progress-reporting": "Prepare Weekly report of AHEAD team work-items.",
  "monthly-governance-reporting": "Prepare the monthly governance reporting.",
};
const ABOUT_JOURNEY = [
  ["Collect", "Read-only Wiz MCP queries gather fresh evidence and note any gaps."],
  ["Draft", "Analysis, workbooks and email drafts are prepared in a private local folder."],
  ["Review", "Workflow QA checks coverage; a person reviews every output."],
  ["Approve", "A person approves and sends. WizExpert never sends or publishes."],
  ["Act", "Remediation is coordinated by people; WizExpert changes nothing in cloud."],
  ["Validate", "Fresh evidence confirms the result before reports are updated."],
  ["Update", "Reports and history are refreshed. This stage is always last."],
];
const ABOUT_PRINCIPLES = [
  ["Evidence first", "Every statement traces back to retained, read-only Wiz evidence."],
  ["Read-only access", "Wiz and cloud access are read-only. No issue, ticket or resource is modified."],
  ["Human approval", "Nothing is sent, changed or published until a person approves it."],
];
const ABOUT_CASES = [
  ["risk-issues", "Risk Issues", "Investigate Wiz issue IDs end to end.",
    "Collect the issues and their evidence, draft an internal analysis, client assessment and stakeholder email, then follow the response through remediation or risk acceptance, validation and a final updated report.",
    ["Internal analysis", "Client assessment", "Stakeholder email", "Updated detailed report"]],
  ["daily-progress-reporting", "Daily Progress Reporting", "A fresh progress view, every day.",
    "Refresh evidence for a fixed-scope campaign and compare it with the previous day to show what moved, what is blocked and what remains.",
    ["Daily progress report", "Day-to-day movements", "VM/CVE details", "Stakeholder reply"]],
  ["weekly-progress-reporting", "Weekly Progress Reporting", "The week's AHEAD team work-items.",
    "Summarise the previous week's in-progress Wiz work-items into a report pack that is ready for Monday review.",
    ["Excel workbook", "Slide deck", "HTML and PDF report", "Email draft"]],
  ["monthly-governance-reporting", "Monthly Governance Reporting", "A consistent monthly governance pack.",
    "Roll the month forward, keep prior reporting decisions and check the workbook, dashboard and deck agree with each other.",
    ["Governance workbook", "Executive dashboard", "Call slide deck"]],
];
function aboutSection() {
  return h("section", { class: "block about", "aria-labelledby": "h-about" },
    h("div", { class: "about-intro" },
      h("p", { class: "eyebrow" }, "README"),
      h("h2", { id: "h-about" }, "About WizExpert"),
      h("p", { class: "about-lede" }, "WizExpert is an independent, evidence-led reporting assistant for Wiz (not an official Wiz product). You describe a reporting scope, a VS Code WizExpert chat collects evidence through authorized read-only Wiz MCP tools, and local tools turn it into reviewed, traceable deliverables you can open from this console.")),
    h("h3", { id: "h-journey", class: "about-sub" }, "The journey"),
    h("ol", { class: "journey", "aria-labelledby": "h-journey" }, ABOUT_JOURNEY.map(([t, d], i) =>
      h("li", { class: "journey-step" },
        h("span", { class: "journey-node", "aria-hidden": "true" }, String(i + 1)),
        h("strong", {}, t), h("span", { class: "journey-desc" }, d)))),
    h("h3", { id: "h-principles", class: "about-sub" }, "Principles"),
    h("ul", { class: "about-principles", "aria-labelledby": "h-principles" }, ABOUT_PRINCIPLES.map(([t, d], i) =>
      h("li", {}, h("strong", {}, t), h("span", {}, d)))),
    h("h3", { id: "h-cases", class: "about-sub" }, "What each workflow does"),
    h("div", { class: "about-cases" }, ABOUT_CASES.map(([id, title, tag, body, outs], i) =>
      h("article", { class: "about-case", "aria-labelledby": "case-" + id },
        h("h4", { id: "case-" + id }, title),
        h("p", { class: "case-tag" }, tag),
        h("p", {}, body),
        h("ul", { class: "case-outputs", "aria-label": title + " deliverables" }, outs.map((o) => h("li", {}, o)))))));
}
function buildHome() {
  const root = $("v-home");
  home = { summary: h("div", { class: "summary" }), active: h("div", {}), workflows: h("div", {}), recent: h("div", {}) };
  const dash = $("v-dashboard");
  const principles = ["Evidence first", "Approval stays human", "Outputs stay traceable"];
  root.append(
    h("section", { class: "hero", "aria-labelledby": "hero-title" },
      h("div", { class: "hero-copy" },
        h("p", { class: "eyebrow" }, "WizExpert Workflow Console"),
        h("h1", { id: "hero-title", class: "route-heading", tabindex: "-1" }, "Turn Wiz findings into reviewed deliverables."),
        h("p", { class: "hero-lede" }, "Start a workflow, hand the request to a VS Code WizExpert chat, and follow progress and local output files here. Nothing is sent, changed or approved without you."),
        h("ul", { class: "principles" }, principles.map((x) => h("li", {}, x)))),
      h("div", { class: "hero-art", "aria-hidden": "true" },
        h("img", { src: "/static/assets/logo.svg", alt: "", width: "320" }))),
    h("section", { class: "block", "aria-labelledby": "h-wf" }, h("h2", { id: "h-wf" }, "Start a workflow"), home.workflows),
    aboutSection(),
    h("p", {}, link("/dashboard", "secondary", "Open Dashboard for runs and activity")));
  dash.append(pageHead("Dashboard", "Run summary, current activity and recent runs."),
    makeDataBar(),
    home.summary,
    h("section", { class: "block", "aria-labelledby": "h-active" }, h("h2", { id: "h-active" }, "Current activity"), home.active),
    h("section", { class: "block", "aria-labelledby": "h-recent" }, h("h2", { id: "h-recent" }, "Recent runs"), home.recent));
}
function renderSummary() {
  mount(home.summary, JSON.stringify([state.active, state.history.length, state.loaded, state.categories.length]), (box) => {
    if (!state.loaded) return;
    const attention = state.active.filter((r) => NEEDS_ATTENTION.has(r.status)).length;
    const running = state.active.length - attention;
    const tile = (href, cls, n, label) => link(href, "stat " + cls, h("strong", {}, String(n)), h("span", {}, label));
    box.append(h("nav", { class: "stats", "aria-label": "Run summary" },
      tile("/in-progress", attention ? "attention" : "", attention, attention === 1 ? "needs attention" : "need attention"),
      tile("/in-progress", "", running, "running"),
      tile("/history", "", state.history.length, "recent runs"),
      tile("/", "", state.categories.length, "workflows")));
  });
}
function renderHome() {
  if (!home) return;
  renderSummary();
  mount(home.active, JSON.stringify([state.active, state.loaded, state.refreshError, state.categories.length]), (box) => {
    if (!dataGate(box)) return;
    if (!state.active.length) box.append(stateBox("empty", "Nothing is running", "Running tasks appear here. See In progress in the sidebar for the full list."));
    else box.append(h("div", { class: "run-cards" }, state.active.map(runCard)));
  });
  mount(home.workflows, JSON.stringify([state.categories.map((c) => c.id), state.refreshError]), (box) => {
    if (!state.categories.length) {
      box.append(state.refreshError ? stateBox("error", "Could not load workflows", state.refreshError, "Retry", () => loadData()) : stateBox("loading", "Loading workflows..."));
      return;
    }
    box.append(h("div", { class: "wf-grid" }, state.categories.map((c) => {
      const art = WF_ART[c.id];
      const card = link(wfPath(c.id), "wf-card",
        art ? h("img", { class: "wf-art", src: "/static/assets/" + art, alt: "", decoding: "async" }) : null,
        h("span", { class: "wf-body" }, h("strong", {}, c.title), h("span", {}, WF_BLURB[c.id] || c.description)),
        h("span", { class: "wf-btn" }, "Open workflow \u2192"));
      return card;
    })));
  });
  mount(home.recent, JSON.stringify([state.history, state.loaded, state.refreshError, state.categories.length]), (box) => {
    if (!dataGate(box)) return;
    if (!state.history.length) { box.append(stateBox("empty", "No recent activity yet", "Runs you start appear here.")); return; }
    box.append(runTable(state.history.slice(0, 5)), h("p", {}, h("button", { class: "secondary", type: "button", onclick: () => go("/history") }, "View all history")));
  });
}
function showHome() {
  clearTimeout(state.timer); state.runId = null; banner("");
  try { sessionStorage.removeItem("wizexpert.run"); } catch (_e) { /* clear the old saved run */ }
  showView("home"); state.runStatus = "";
  setTitle("Home");
}
function showDashboard() {
  clearTimeout(state.timer); state.runId = null; banner("");
  try { sessionStorage.removeItem("wizexpert.run"); } catch (_e) { /* clear the old saved run */ }
  showView("dashboard"); state.runStatus = "";
  setTitle("Dashboard");
}

// ---- in-progress view -------------------------------------------------------------------------------------
function showProgress() {
  state.runStatus = ""; banner("");
  showView("progress");
  const root = $("v-progress"); clear(root);
  state.pvResults = h("div", {});
  root.append(pageHead("In progress", "Runs that are still working, waiting for your input in VS Code, or handed off to a new chat. Nothing opens automatically."),
    makeDataBar(), state.pvResults);
  setTitle("In progress");
}
function renderProgressResults() {
  const box = state.pvResults;
  if (!box || !box.isConnected || state.view !== "progress") return;
  mount(box, JSON.stringify([state.active, state.loaded, state.refreshError, state.categories.length]), (b) => {
    if (!dataGate(b)) return;
    if (!state.active.length) {
      b.append(stateBox("empty", "Nothing is in progress", "Start a workflow or review earlier runs in History."),
        h("p", { class: "row" }, h("button", { type: "button", onclick: () => go("/") }, "Browse workflows"), h("button", { class: "secondary", type: "button", onclick: () => go("/history") }, "View history")));
      return;
    }
    const attention = state.active.filter((r) => NEEDS_ATTENTION.has(r.status));
    const running = state.active.filter((r) => !NEEDS_ATTENTION.has(r.status));
    if (attention.length) b.append(h("h2", {}, "Needs attention (" + attention.length + ")"), h("div", { class: "run-cards" }, attention.map(runCard)));
    if (running.length) b.append(h("h2", {}, "Running (" + running.length + ")"), h("div", { class: "run-cards" }, running.map(runCard)));
  });
}

// ---- history view (filters live in the URL query so a filtered view can be shared) ----------------------
function syncOptions(select, entries) {
  const key = entries.map((e) => e[0]).join("|");
  if (select.dataset.opts === key) return;
  select.dataset.opts = key; clear(select);
  for (const [value, label] of entries) select.append(h("option", { value }, label));
}
function showHistory() {
  state.runStatus = ""; banner("");
  showView("history");
  const q = new URLSearchParams(location.search);
  state.hf = { status: q.get("status") || "", category: q.get("category") || "", q: (q.get("q") || "").slice(0, 80) };
  const root = $("v-history"); clear(root);
  const status = h("select", { id: "hf-status" });
  syncOptions(status, [["", "All statuses"], ["active", "Active (not finished)"], ...Object.entries(STATUS_TEXT)]);
  status.value = state.hf.status;
  const category = h("select", { id: "hf-category" });
  state.hvCategory = category;
  const search = h("input", { id: "hf-q", type: "search", maxlength: 80, autocomplete: "off", placeholder: "Run id or workflow" });
  search.value = state.hf.q;
  state.hvResults = h("div", {});
  const apply = () => {
    state.hf = { status: status.value, category: category.value, q: search.value.trim() };
    const p = new URLSearchParams();
    for (const [k, v] of Object.entries(state.hf)) if (v) p.set(k, v);
    history.replaceState(history.state, "", "/history" + (p.toString() ? "?" + p : ""));
    renderHistoryResults();
  };
  for (const el of [status, category]) el.addEventListener("change", apply);
  search.addEventListener("input", apply);
  const clearBtn = h("button", { class: "secondary", type: "button", onclick: () => { status.value = ""; category.value = ""; search.value = ""; apply(); status.focus(); } }, "Clear filters");
  state.hvClear = () => clearBtn.click();
  root.append(pageHead("History", "Every run the console remembers, newest first. Filter by status or workflow, then open a run to see its progress, log and output files."),
    makeDataBar(),
    h("form", { class: "filters", role: "search", "aria-label": "Filter runs", onsubmit: (e) => e.preventDefault() },
      h("label", { for: "hf-status" }, "Status", status), h("label", { for: "hf-category" }, "Workflow", category),
      h("label", { for: "hf-q" }, "Search", search), clearBtn),
    state.hvResults);
  renderHistoryResults();
  setTitle("History");
}
function renderHistoryResults() {
  const box = state.hvResults;
  if (!box || !box.isConnected || state.view !== "history") return;
  const known = new Map(state.categories.map((c) => [c.id, c.title]));
  for (const r of state.history) if (!known.has(r.category_id)) known.set(r.category_id, r.category_id);
  if (state.hf.category && !known.has(state.hf.category)) known.set(state.hf.category, state.hf.category);
  syncOptions(state.hvCategory, [["", "All workflows"], ...known.entries()]);
  state.hvCategory.value = state.hf.category;
  const f = state.hf;
  const needle = f.q.toLowerCase();
  const rows = state.history.filter((r) =>
    (!f.category || r.category_id === f.category)
    && (!f.status || (f.status === "active" ? !TERMINAL.has(r.status) : r.status === f.status))
    && (!needle || (r.id + " " + catTitle(r.category_id)).toLowerCase().includes(needle)));
  mount(box, JSON.stringify([rows, state.history.length, f, state.loaded, state.refreshError, state.categories.length]), (b) => {
    if (!dataGate(b)) return;
    if (!state.history.length) {
      b.append(stateBox("empty", "No runs yet", "Runs you start appear here.", "Browse workflows", () => go("/")));
      return;
    }
    if (!rows.length) {
      b.append(stateBox("empty", "No runs match these filters", "Try a different status or workflow.", "Clear filters", () => state.hvClear()));
      return;
    }
    b.append(h("p", { class: "meta", role: "status" }, "Showing " + rows.length + " of " + state.history.length + " recent runs."), runTable(rows));
  });
}

// ---- workflow page ----------------------------------------------------------------------------------------
function renderCategoryActivity() {
  // Previous runs of the open workflow; read-only, never opens a run by itself.
  const box = state.activityBox;
  if (!box || !box.isConnected || state.view !== "workflow") return;
  const id = state.activityCategory;
  const runs = (state.history || []).filter((r) => r.category_id === id);
  const live = (state.active || []).filter((r) => r.category_id === id && !TERMINAL.has(r.status));
  mount(box, JSON.stringify([id, runs, live, state.loaded, state.refreshError]), (b) => {
    b.append(h("h2", {}, "Previous runs"));
    for (const r of live) {
      b.append(h("div", { class: "live-card", role: "status" }, h("strong", {}, "Running now"), badge(r.status),
        h("button", { type: "button", onclick: () => go(runPath(r.id)) }, "Open running task")));
    }
    if (!state.loaded && !live.length) { dataGate(b); return; }
    if (!runs.length) {
      b.append(stateBox("empty", "No previous runs", "Runs you start here will be listed with their status."));
      return;
    }
    b.append(h("ul", { class: "run-list" }, runs.map((r) => h("li", {},
      h("div", {}, badge(r.status), h("span", { class: "meta" }, fmtDate(r.created))),
      h("button", { class: "secondary small", type: "button", "aria-label": "Open run " + r.id, onclick: () => go(runPath(r.id)) }, "Open")))));
  });
}
function showWorkflow(category, stageId, actionId) {
  clearTimeout(state.timer); state.runId = null; state.runStatus = ""; banner("");
  showView("workflow"); state.wfId = category.id;
  setTitle(category.title);
  const root = $("v-workflow"); clear(root);
  state.activityCategory = category.id;
  state.activityBox = h("section", { class: "card", "aria-label": "Previous runs for " + category.title });
  const main = h("div", { class: "split-main" });
  root.append(breadcrumb({ label: "Home", href: "/" }, { label: category.title }),
    h("div", { class: "wf-head" }, pageHead(category.title, category.description),
      h("button", { class: "secondary back-btn", type: "button", onclick: () => go("/") }, "Back to workflows")),
    h("div", { class: "split" }, main,
      h("aside", { class: "split-side" }, state.activityBox,
        h("div", { class: "card callout" }, h("h2", {}, "What happens next?"),
          h("p", {}, "Your input opens a new VS Code WizExpert chat. This page only mirrors progress and local output files.")))));
  renderCategoryActivity();
  if (!(category.stages || []).length) {
    main.append(h("div", { class: "card" }, formPanel(category, category, null, () => go("/"))));
    return;
  }
  // Staged workflow: pick a stage, then one operation form at a time.
  const detail = h("div", { class: "card" });
  const stageBar = h("div", { class: "segmented", role: "group", "aria-label": "Stages" });
  const stageButtons = {};
  const showStage = (stage, chosenAction) => {
    for (const [id, button] of Object.entries(stageButtons)) {
      const selected = id === stage.id;
      button.classList.toggle("active", selected);
      if (selected) button.setAttribute("aria-current", "page"); else button.removeAttribute("aria-current");
    }
    clear(detail);
    detail.append(h("p", { class: "lede" }, STAGE_HELP[stage.id] || ""));
    const actions = category.actions.filter((a) => a.stage === stage.id);
    if (stage.id === "in-progress" && category.work_items && category.work_items.length) {
      detail.append(h("h2", {}, "Existing work items"));
      const workItems = h("div", { class: "item-list" });
      for (const item of category.work_items) {
        const message = h("p", { class: "bad", role: "alert" });
        let refreshButton;
        const refreshItem = async () => {
          message.textContent = "";
          refreshButton.disabled = true;
          refreshButton.textContent = "Refreshing...";
          try {
            const res = await api("POST", "/api/runs", { category_id: category.id, action_id: actions[0].id, inputs: { work_item: item } });
            go(runPath(res.run_id));
          } catch (e) {
            message.textContent = e.message;
            helperRecoveryMessage(e);
            refreshButton.disabled = false;
            refreshButton.textContent = "Refresh";
          }
        };
        refreshButton = h("button", { class: "secondary", type: "button", onclick: refreshItem }, "Refresh");
        workItems.append(h("div", { class: "item-row" }, h("div", {}, h("strong", {}, item), h("span", { class: "meta" }, "Refresh today's progress")), refreshButton), message);
      }
      detail.append(workItems);
      return;
    }
    if (actions.length === 1) { detail.append(formPanel(category, actions[0], actions[0].id, null)); return; }
    const bar = h("div", { class: "options", role: "group", "aria-label": stage.title + " actions" });
    const form = h("div", { class: "options-form" });
    const actionButtons = {};
    for (const a of actions) {
      actionButtons[a.id] = h("button", { class: "option", type: "button", onclick: () => go(wfPath(category.id, stage.id, a.id), { focus: "action" }) },
        h("strong", {}, a.title), h("span", {}, a.description));
      bar.append(actionButtons[a.id]);
    }
    arrowNav(bar);
    detail.append(bar, form);
    const chosen = chosenAction ? actions.find((x) => x.id === chosenAction) : null;
    if (chosen) {
      for (const [id, button] of Object.entries(actionButtons)) {
        const selected = id === chosen.id;
        button.classList.toggle("active", selected);
        if (selected) button.setAttribute("aria-current", "page"); else button.removeAttribute("aria-current");
      }
      form.append(formPanel(category, chosen, chosen.id, null));
    } else if (chosenAction) {
      form.append(stateBox("error", "Unknown action", "This action is not available for " + stage.title + ".", "Back to " + stage.title, () => go(wfPath(category.id, stage.id))));
    } else {
      form.append(stateBox("empty", "Choose an action", "Select an action above to open its form."));
    }
  };
  for (const s of category.stages) {
    stageButtons[s.id] = h("button", { class: "seg", type: "button", onclick: () => go(wfPath(category.id, s.id), { focus: "stage" }) }, s.title);
    stageBar.append(stageButtons[s.id]);
  }
  arrowNav(stageBar);
  main.append(stageBar, detail);
  const stage = stageId ? category.stages.find((s) => s.id === stageId) : null;
  if (stage) showStage(stage, actionId);
  else if (stageId) detail.append(stateBox("error", "Unknown stage", "This stage is not available for " + category.title + ".", "Back to workflow", () => go(wfPath(category.id))));
  else detail.append(stateBox("empty", "Choose a stage", "Select a stage above to continue."));
}
function previousReportPicker(id) {
  // Options come from a local, read-only listing of weekly-progress folders (names only).
  const FIRST = "", MANUAL = "__manual__";
  const select = h("select", { id }, h("option", { value: FIRST }, "None: this is the first report"));
  const manual = h("input", { type: "text", maxlength: 120, autocomplete: "off", placeholder: "folder name under deliverables", "aria-label": "Previous report folder name", hidden: true });
  const note = h("div", { class: "help", role: "status" }, "Loading previous reports...");
  const manualOption = () => h("option", { value: MANUAL }, "Enter a folder name manually");
  let pending = null, loaded = false;
  const apply = () => {
    if (pending == null || !loaded) return;
    const want = pending; pending = null;
    if ([...select.options].some((o) => o.value === want)) select.value = want;
    else { select.value = MANUAL; manual.value = want; }
    manual.hidden = select.value !== MANUAL;
  };
  select.append(manualOption());
  select.addEventListener("change", () => { manual.hidden = select.value !== MANUAL; });
  api("GET", "/api/weekly-progress/previous-reports").then((res) => {
    clear(select);
    select.append(h("option", { value: FIRST }, "None: this is the first report"));
    for (const r of res.reports) select.append(h("option", { value: r.reference }, r.reference));
    select.append(manualOption());
    note.textContent = res.empty ? res.message : res.reports.length + " previous report folder(s) found.";
    loaded = true; apply();
  }).catch(() => {
    select.value = MANUAL; manual.hidden = false;
    note.textContent = "Could not list previous reports; leave empty for the first report or enter a folder name.";
    loaded = true; apply();
  });
  const field = {
    get value() {
      if (pending != null && !loaded) return pending;
      return select.value === MANUAL ? manual.value : select.value;
    },
    set value(v) { pending = String(v); apply(); },
  };
  return { field, node: h("div", {}, select, manual, note) };
}
function formPanel(category, spec, actionId, onBack, initialValues = {}) {
  const panel = h("div", { class: "form panel" });
  const fields = {};
  const draftKey = actionId || "_default";
  const draft = Object.assign({}, loadDraft(category.id)[draftKey] || {}, initialValues);
  if (spec.description && actionId) panel.append(h("p", { class: "lede" }, spec.description));
  for (const f of spec.fields) {
    const multiline = f.name === "email_text";
    const id = "f-" + category.id + "-" + draftKey + "-" + f.name;
    const input = multiline
      ? h("textarea", { id, rows: 8, maxlength: f.max_length || 200, placeholder: f.placeholder || "", autocomplete: "off" })
      : h("input", { id, type: "text", maxlength: f.max_length || 200, placeholder: f.placeholder || "", autocomplete: "off" });
    if (category.id === "weekly-progress-reporting" && f.name === "previous_report") {
      const picker = previousReportPicker(id);
      fields[f.name] = picker.field;
      if (draft[f.name] != null && draft[f.name] !== "") picker.field.value = draft[f.name];
      panel.append(h("div", { class: "field" }, h("label", { for: id }, f.label), h("div", { class: "help" }, f.help), picker.node));
      continue;
    }
    if (f.options && f.options.length) {
      const listId = "opts-" + f.name;
      input.setAttribute("list", listId);
      panel.append(h("datalist", { id: listId }, ...f.options.map((o) => h("option", { value: o }))));
    }
    fields[f.name] = input;
    if (draft[f.name]) input.value = draft[f.name];
    panel.append(h("div", { class: "field" }, h("label", { for: id }, f.label + (f.required ? " *" : "")), h("div", { class: "help" }, f.help), input));
  }
  const persist = () => {
    const values = {};
    for (const [k, v] of Object.entries(fields)) values[k] = v.value;
    saveDraft(category.id, draftKey, values);
  };
  panel.addEventListener("input", persist);
  panel.addEventListener("change", persist);
  const message = h("p", { class: "bad", role: "alert" });
  const startLabel = actionId === "continue-work-item"
    ? "Refresh"
    : actionId === "new" || !actionId
      ? (category.stages && category.stages.length ? "Proceed" : "Start")
      : "Proceed";
  const start = h("button", { type: "button" }, startLabel);
  start.addEventListener("click", async () => {
    message.textContent = ""; start.disabled = true; start.setAttribute("aria-busy", "true");
    try {
      const inputs = {}; for (const [k, v] of Object.entries(fields)) inputs[k] = v.value;
      const body = { category_id: category.id, inputs };
      if (actionId) body.action_id = actionId;
      const res = await api("POST", "/api/runs", body);
      clearDraft(category.id, draftKey);
      go(runPath(res.run_id));
    } catch (e) {
      message.textContent = e.message;
      helperRecoveryMessage(e);
      start.disabled = false; start.removeAttribute("aria-busy");
    }
  });
  panel.append(h("div", { class: "form-actions" }, start, onBack ? h("button", { class: "secondary", type: "button", onclick: onBack }, "Back") : null), message);
  return panel;
}

// ---- run page ----------------------------------------------------------------------------------------------
function openRun(runId) {
  clearTimeout(state.timer);
  state.runId = runId; state.since = 0; state.progress = []; state.shown = ""; state.runStatus = ""; state.runCategory = "";
  showView("run");
  const root = $("v-run"); clear(root);
  root.append(runCrumbs(null, runId), h("h1", { class: "route-heading", tabindex: "-1" }, "Run " + runId),
    stateBox("loading", "Loading run...", "Fetching progress and output files."));
  setTitle("Run " + runId);
  poll();
}
function runCrumbs(run, runId) {
  const items = [{ label: "Home", href: "/" }];
  if (run && run.category_id) items.push({ label: run.category, href: wfPath(run.category_id) });
  items.push({ label: "Run " + (run ? run.id : runId) });
  return breadcrumb(...items);
}
async function poll() {
  clearTimeout(state.timer);
  const id = state.runId;
  try {
    const run = await api("GET", "/api/runs/" + id + "?since=" + state.since);
    if (id !== state.runId) return;
    banner("");
    state.since = run.next;
    state.progress.push(...run.progress); if (state.progress.length > 400) state.progress.splice(0, state.progress.length - 400);
    renderRun(run);
    state.timer = setTimeout(poll, TERMINAL.has(run.status) ? 8000 : 1500); // keep files fresh after the chat ends
  } catch (e) {
    if (id !== state.runId) return;
    if (/unknown run|not found/i.test(e.message)) { // stale id from an old tab/link: explain, never jump away
      state.runId = null; state.runStatus = ""; updateIndicator();
      const root = $("v-run"); clear(root);
      root.append(h("h1", { class: "route-heading", tabindex: "-1" }, "Run not found"),
        stateBox("error", "This run is no longer available", "It may belong to an earlier console session.", "Back to Home", () => go("/")));
      return;
    }
    banner("Lost contact with the console: " + e.message); state.timer = setTimeout(poll, 4000);
  }
}
function renderRun(run) {
  state.runStatus = run.status; state.runCategory = run.category_id || run.category;
  updateIndicator();
  // Rebuild only when something changed, so button messages and scroll position survive polling.
  const sig = JSON.stringify([run.status, run.message, run.pending, run.summary, run.files.map((f) => [f.path]), state.since, run.can_open_chat, run.can_stop, run.can_open_output]);
  if (sig === state.shown) return;
  const first = !state.shown;
  state.shown = sig;
  const root = $("v-run");
  const y = window.scrollY;
  const oldLog = root.querySelector(".raw-progress");
  const logOpen = !!(oldLog && oldLog.open);
  clear(root);
  const toolbar = h("div", { class: "toolbar" });
  if (run.can_open_chat) toolbar.append(h("button", { type: "button", onclick: openChat }, "Open this chat in VS Code"));
  if (run.can_stop) toolbar.append(stopButton(run));
  if (run.can_open_output) toolbar.append(h("button", { class: "secondary", type: "button", onclick: openLatestOutput }, "View latest output"));
  if (run.category_id) toolbar.append(h("button", { class: "secondary", type: "button", onclick: () => go(wfPath(run.category_id)) }, "Open workflow page"));
  toolbar.append(h("button", { class: "secondary", type: "button", onclick: () => go("/history") }, "All history"));
  root.append(runCrumbs(run), h("header", { class: "page-head" },
    h("h1", { class: "route-heading", tabindex: "-1" }, run.category),
    h("p", { class: "status-line", role: "status" }, badge(run.status), h("span", {}, run.message))), toolbar);
  if (run.pending) root.append(pendingBlock(run));
  const log = rawProgressBlock();
  if (logOpen) log.open = true;
  const main = h("div", { class: "split-main" },
    h("section", { class: "card" }, h("h2", {}, "Progress"), activityBlock(), log));
  if (run.status === "completed" || run.status === "stopped") {
    main.append(h("section", { class: "card" }, h("h2", {}, "Final summary"), h("div", { class: "ref" }, run.summary || "(the agent gave no final text)")));
  }
  root.append(h("div", { class: "split run-split" }, main,
    h("aside", { class: "split-side" },
      h("section", { class: "card" }, h("h2", {}, "Request"), h("p", { class: "request" }, run.prompt)),
      h("section", { class: "card" }, h("h2", {}, "Output files (" + run.files.length + ")"), filesBlock(run)))));
  if (first && state.restoreY != null) restoreScroll(); else window.scrollTo(0, y);
  if (first && state.focusNext) applyFocus();
}
function stopButton(run) {
  const button = h("button", { class: "danger", type: "button", onclick: async () => {
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
  return button;
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
  const box = h("section", { class: "card pending", role: "group", "aria-label": "Waiting for you" },
    h("h2", {}, p.kind === "question" ? "The agent is asking a question" : handoff ? "Approve handoff to a new chat" : "Waiting for tool approval"),
    h("div", { class: "ref" }, p.text));
  if (p.detail) box.append(h("p", { class: "help" }, "Handoff prompt"), h("div", { class: "ref" }, p.detail));
  const msg = h("span", { class: "bad" });
  const act = (a) => async () => { msg.textContent = ""; try { await api("POST", "/api/runs/" + run.id + "/decide", { action: a }); } catch (e) { msg.textContent = e.message; } };
  const row = h("div", { class: "toolbar" });
  if (p.can_decide) row.append(h("button", { type: "button", onclick: act("accept") }, "Allow"), h("button", { class: "danger", type: "button", onclick: act("skip") }, "Skip"));
  row.append(h("span", { class: "help" }, "Answer questions and review approvals in the VS Code chat."), msg);
  box.append(row);
  return box;
}
async function openChat() { try { await api("POST", "/api/runs/" + state.runId + "/open"); } catch (e) { banner(e.message); } }
function filesBlock(run) {
  if (!run.files.length) return stateBox("empty", "No deliverable files yet", "Files appear here as the workflow produces them.");
  return h("div", { class: "table-wrap" }, h("table", { class: "data-table" },
    h("thead", {}, h("tr", {}, h("th", { scope: "col" }, "File"), h("th", { scope: "col" }, "Location"))),
    h("tbody", {}, run.files.map((f) => h("tr", {}, h("td", { class: "mono" }, f.name), h("td", { class: "mono" }, f.location))))));
}
function activityBlock() {
  const box = h("div", { class: "timeline", "aria-live": "polite" });
  const relevant = state.progress.filter((i) => i.kind === "tool" || i.kind === "assistant" || i.kind === "error" || i.kind === "handoff");
  const recent = relevant.slice(-14);
  const important = relevant.filter((i) => i.kind === "error" || i.failed || i.aborted);
  const items = [...important, ...recent].filter((item, index, all) => all.indexOf(item) === index);
  if (!items.length) return h("div", { class: "timeline empty", role: "status" }, "Waiting for the agent to start...");
  for (const i of items) {
    const active = i.kind === "tool" && !i.completed && !i.failed && !i.aborted;
    const label = i.kind === "tool"
      ? (i.sub ? (active ? "Running subagent task" : i.failed ? "Subagent task failed" : i.aborted ? "Subagent task stopped" : "Subagent task complete")
        : (active ? "Running task" : i.failed ? "Task failed" : i.aborted ? "Task stopped" : "Task complete"))
      : i.kind === "error" ? "Error" : i.kind === "handoff" ? "Handed off to a new chat" : i.sub ? "Subagent update" : "Agent update";
    const bad = i.kind === "error" || i.failed || i.aborted;
    box.append(h("div", { class: "tl-item " + i.kind + (active ? " active" : "") + (bad ? " failed" : "") },
      h("span", { class: "tl-marker", "aria-hidden": "true" }, active ? "\u25cf" : bad ? "!" : "\u2713"),
      h("div", { class: "tl-copy" }, h("strong", {}, label), h("span", {}, i.text)),
      h("time", {}, when(i.time))));
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

// ---- boot --------------------------------------------------------------------------------------------------
function renderAll() {
  renderHome(); renderHistoryResults(); renderProgressResults(); renderCategoryActivity(); renderNavWorkflows();
  updateIndicator(); updateDataBars();
}
function migrateLegacyHash() {
  let m = /^#run=([\w-]+)$/.exec(location.hash);
  if (m) { history.replaceState(history.state, "", runPath(m[1])); return true; }
  m = /^#workflow=([\w-]+)$/.exec(location.hash);
  if (m) { history.replaceState(history.state, "", wfPath(m[1])); return true; }
  return false;
}
// ---- collapsible sidebar (state kept in localStorage; no secrets) -------------------------------------------
const NAV_KEY = "wizexpert.sidebar";
function setSidebar(collapsed, persist) {
  document.body.classList.toggle("nav-collapsed", collapsed);
  const btn = $("nav-toggle");
  if (btn) {
    const label = collapsed ? "Expand sidebar" : "Collapse sidebar";
    btn.setAttribute("aria-expanded", String(!collapsed));
    btn.setAttribute("aria-label", label);
    btn.title = label;
  }
  if (persist) { try { localStorage.setItem(NAV_KEY, collapsed ? "collapsed" : "expanded"); } catch (_e) { /* ignore */ } }
}
(function initSidebar() {
  let saved = null;
  try { saved = localStorage.getItem(NAV_KEY); } catch (_e) { /* ignore */ }
  const small = window.matchMedia && window.matchMedia("(max-width: 960px)").matches;
  setSidebar(saved ? saved === "collapsed" : small, false);
  const btn = $("nav-toggle");
  if (btn) btn.addEventListener("click", () => setSidebar(!document.body.classList.contains("nav-collapsed"), true));
  // Desktop shortcuts: g then h/d/p/y (Home, Dashboard, In progress, History), "/" search history, "[" sidebar.
  let pendingG = 0;
  window.addEventListener("keydown", (e) => {
    if (e.defaultPrevented || e.metaKey || e.ctrlKey || e.altKey) return;
    const t = e.target;
    if (t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName))) return;
    if (pendingG && Date.now() - pendingG < 1200) {
      pendingG = 0;
      const dest = { h: "/", d: "/dashboard", p: "/in-progress", y: "/history" }[e.key.toLowerCase()];
      if (dest) { e.preventDefault(); go(dest); return; }
    }
    if (e.key === "g") { pendingG = Date.now(); return; }
    if (e.key === "[") { e.preventDefault(); setSidebar(!document.body.classList.contains("nav-collapsed"), true); return; }
    if (e.key === "/") {
      e.preventDefault();
      const focusSearch = () => { const q = $("hf-q"); if (q) { q.focus(); q.select(); } };
      if (state.view === "history") focusSearch(); else { go("/history", { focus: "" }); setTimeout(focusSearch, 0); }
    }
  });
  window.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && small && !document.body.classList.contains("nav-collapsed") && document.activeElement && document.activeElement.closest && document.activeElement.closest("#sidebar")) {
      setSidebar(true, false); if (btn) btn.focus();
    }
  });
})();
document.querySelectorAll(".nav a, .brand").forEach(bindLink);
const indicator = $("active-run");
if (indicator) bindLink(indicator);
const skip = document.querySelector(".skip-link");
if (skip) skip.addEventListener("click", (e) => { e.preventDefault(); $("main").focus({ preventScroll: false }); });
try { history.scrollRestoration = "manual"; } catch (_e) { /* ignore */ }
let scrollTimer = 0;
window.addEventListener("scroll", () => { clearTimeout(scrollTimer); scrollTimer = setTimeout(saveScroll, 150); }, { passive: true });
window.addEventListener("pagehide", saveScroll);
for (const name of ["wheel", "touchstart", "keydown"]) {
  window.addEventListener(name, () => { state.restoreY = null; }, { passive: true });
}
window.addEventListener("popstate", () => {
  state.focusNext = "heading";
  state.restoreY = (history.state && history.state.y) || 0;
  route();
});
window.addEventListener("hashchange", () => { if (migrateLegacyHash()) { state.focusNext = "heading"; state.restoreY = 0; route(); } });
buildHome(); readCache(); renderAll();
migrateLegacyHash();
state.restoreY = (history.state && history.state.y) || 0;
route();
setInterval(() => { refresh().catch(() => {}); }, 10000);
