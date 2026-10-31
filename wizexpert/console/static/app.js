"use strict";
// Every value from the server is rendered with textContent / value only (never as raw markup).
const csrf = document.querySelector('meta[name="csrf-token"]').content;
const $ = (id) => document.getElementById(id);
const state = { categories: [], wiz: { connected: false }, category: null, runId: null, since: 0, timer: null, form: null };
const STATUS_TEXT = {
  created: "Created", collecting: "Collecting", awaiting_input: "Waiting for your input",
  generating: "Generating", awaiting_review: "Awaiting reviewer approval", finalizing: "Finalizing",
  complete: "Complete", failed: "Failed", blocked: "Blocked", cancelled: "Cancelled",
  rejected: "Rejected", reconnect_required: "Reconnect Wiz",
};
const TERMINAL = new Set(["complete", "failed", "blocked", "cancelled", "rejected", "reconnect_required"]);

function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (k === "class") el.className = v;
    else if (k === "onclick") el.addEventListener("click", v);
    else if (k === "onchange") el.addEventListener("change", v);
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
  try { data = await response.json(); } catch (_e) { /* non-JSON */ }
  if (!response.ok) throw new Error(data.error || ("HTTP " + response.status));
  return data;
}
function banner(text, kind) {
  const b = $("banner");
  if (!text) { b.hidden = true; return; }
  b.hidden = false; clear(b); b.append(text);
  b.style.borderColor = kind === "ok" ? "#15803d" : "#b35d12";
}

// ---- Wiz connection ----------------------------------------------------------------------
function renderWiz() {
  const box = $("wiz-status"); clear(box);
  box.append(h("span", {}, h("span", { class: "dot" + (state.wiz.connected ? " on" : "") }), state.wiz.connected ? "Wiz connected" : "Wiz not connected"));
  if (state.wiz.connected) box.append(h("button", { class: "secondary", onclick: async () => { state.wiz = await api("POST", "/api/wiz/disconnect"); renderWiz(); } }, "Disconnect"));
  else box.append(h("button", { class: "secondary", onclick: connectWiz }, "Connect Wiz"));
}
async function connectWiz() {
  try {
    const { authorize_url: url } = await api("POST", "/api/wiz/connect");
    if (!url.startsWith("https://")) throw new Error("Unexpected sign-in URL.");
    banner(h("span", {}, "Sign in with Wiz in the browser tab that opened. If nothing opened, ", h("a", { href: url, target: "_blank", rel: "noopener noreferrer" }, "open the sign-in page"), ". Then return here."));
  } catch (e) { banner("Could not start Wiz sign-in: " + e.message); }
}

// ---- category picker + start form ----------------------------------------------------------
function renderPicker() {
  const root = $("picker"); clear(root);
  root.append(h("h2", {}, "1. Pick a category"));
  const cards = h("div", { class: "cards" });
  for (const c of state.categories) {
    cards.append(h("div", { class: "card" + (state.category && state.category.id === c.id ? " selected" : "") },
      h("strong", {}, c.title), h("p", {}, c.description),
      h("div", { class: "help" }, c.slots.map((s) => s.title).join(" · ")),
      h("p", {}, h("button", { onclick: () => selectCategory(c) }, "Select"))));
  }
  root.append(cards);
}
function selectCategory(category) {
  state.category = category; renderPicker();
  const root = $("start"); root.hidden = false; clear(root);
  root.append(h("h2", {}, "2. Enter the required inputs"));
  const panel = h("div", { class: "panel" });
  const inputs = {};
  for (const f of category.fields) { const el = fieldInput(f, f.default); inputs[f.name] = el; panel.append(fieldBlock(f, el.node)); }
  const preparer = h("input", { type: "text", maxlength: 80, placeholder: "Your name (recorded as preparer)" });
  panel.append(h("label", {}, "Preparer ", h("span", { class: "help" }, "(optional; recorded in the run record)")), preparer);
  let dry = null;
  if (category.dry_run) { dry = h("input", { type: "checkbox" }); panel.append(h("label", {}, dry, " Dry run (replay retained evidence offline; writes only inside the private run folder)")); }
  const message = h("p", { class: "bad" });
  panel.append(h("p", {}, h("button", { onclick: async () => {
    message.textContent = "";
    try {
      const values = {}; for (const [k, v] of Object.entries(inputs)) values[k] = v.get();
      const res = await api("POST", "/api/runs", { category_id: category.id, inputs: values, dry_run: !!(dry && dry.checked), preparer: preparer.value });
      openRun(res.run_id);
    } catch (e) { message.textContent = e.message; }
  } }, "Start run")), message);
  root.append(panel);
}

// ---- generic field rendering -----------------------------------------------------------------
function fieldBlock(f, node) {
  return h("div", {}, h("label", {}, f.label + (f.required ? " *" : ""), f.help ? h("div", { class: "help" }, f.help) : null), node);
}
function fieldInput(f, value) {
  if (f.kind === "textarea") { const t = h("textarea", {}); t.value = value || ""; return { node: t, get: () => t.value }; }
  if (f.kind === "select") {
    const s = h("select", {}, h("option", { value: "" }, ""), f.options.map((o) => h("option", { value: o }, o)));
    s.value = value || ""; return { node: s, get: () => s.value };
  }
  if (f.kind === "bool") { const c = h("input", { type: "checkbox" }); c.checked = !!value; return { node: c, get: () => c.checked }; }
  if (f.kind === "list") return listInput(f, Array.isArray(value) ? value : []);
  const t = h("input", { type: f.kind === "date" ? "date" : "text" }); t.value = value || ""; return { node: t, get: () => t.value };
}
function listInput(f, rows) {
  const box = h("div", { class: "rows" });
  const getters = [];
  function addRow(values) {
    const cells = {}; const row = h("div", { class: "row" });
    for (const key of f.item_keys) {
      const input = h("input", { type: "text", placeholder: key }); input.value = (values && values[key]) || ""; cells[key] = input; row.append(input);
    }
    const entry = { cells };
    row.append(h("button", { class: "secondary", onclick: () => { row.remove(); getters.splice(getters.indexOf(entry), 1); } }, "Remove"));
    getters.push(entry); box.insertBefore(row, add);
  }
  const add = h("button", { class: "secondary", onclick: () => addRow({}) }, "Add row");
  box.append(add); rows.forEach(addRow);
  return { node: box, get: () => getters.map((g) => Object.fromEntries(Object.entries(g.cells).map(([k, v]) => [k, v.value]))) };
}

// ---- run view -----------------------------------------------------------------------------------
function openRun(runId) {
  state.runId = runId; state.since = 0; state.form = null; logLines.length = 0; state.shownStatus = null;
  $("start").hidden = true; $("run").hidden = false; $("picker").hidden = true; clear($("run"));
  poll();
}
async function poll() {
  clearTimeout(state.timer);
  try {
    const run = await api("GET", "/api/runs/" + state.runId + "?since=" + state.since);
    state.since = run.log_next;
    renderRun(run);
    if (!TERMINAL.has(run.status)) state.timer = setTimeout(poll, 1500);
    else refreshBootstrap(false);
  } catch (e) { banner("Lost contact with the console: " + e.message); }
}
const logLines = [];
function renderRun(run) {
  logLines.push(...run.log);
  const root = $("run");
  // Rebuild only when the status changes, so typed names, form values and messages survive polling.
  if (state.shownStatus === run.status && state.shownRun === run.id) { updateLog(); return; }
  state.shownStatus = run.status; state.shownRun = run.id;
  clear(root);
  root.append(h("h2", {}, "3. " + run.title + (run.dry_run ? " (dry run)" : "")),
    h("p", {}, h("span", { class: "badge " + run.status }, STATUS_TEXT[run.status] || run.status), " ", run.message));
  if (run.status === "reconnect_required") root.append(h("p", {}, h("button", { onclick: connectWiz }, "Reconnect Wiz")));
  if (run.collection && run.collection.status) root.append(collectionBlock(run.collection));
  if (run.problems.length) root.append(h("div", { class: "problems" }, h("strong", {}, "Problems"), h("ul", {}, run.problems.map((p) => h("li", {}, p)))));
  if (run.status === "awaiting_input" && run.form) root.append(narrativeForm(run));
  if (run.outputs && Object.keys(run.outputs).length) root.append(outputsBlock(run));
  if (run.status === "awaiting_review") root.append(reviewBlock(run));
  if (run.status === "complete") banner("Run complete. Deliverables are in: " + run.output_dir, "ok");
  if (!TERMINAL.has(run.status)) root.append(h("p", {}, h("button", { class: "danger", onclick: async () => { await api("POST", "/api/runs/" + run.id + "/cancel"); } }, "Cancel run")));
  else root.append(h("p", {}, h("button", { class: "secondary", onclick: resetAll }, "Start another run")));
  root.append(h("h3", {}, "Activity log"), h("div", { class: "log", id: "log" }));
  updateLog();
}
function updateLog() { const el = $("log"); if (el) { el.textContent = logLines.join("\n"); el.scrollTop = el.scrollHeight; } }
function resetAll() { logLines.length = 0; state.shownStatus = null; banner(""); $("run").hidden = true; $("start").hidden = true; $("picker").hidden = false; state.category = null; renderPicker(); }
function collectionBlock(c) {
  const b = h("div", { class: "panel" }, h("strong", {}, "Post-collection check (wizexpert workflow-qa collection-check): "),
    h("span", { class: c.status === "pass" ? "ok" : "bad" }, c.status));
  if (c.counts && c.counts.length) b.append(h("table", {}, h("tr", {}, h("th", {}, "Count"), h("th", {}, "Expected"), h("th", {}, "Collected")),
    c.counts.map((n) => h("tr", {}, h("td", {}, n.name), h("td", {}, n.expected), h("td", {}, n.collected)))));
  if (c.flags && c.flags.length) b.append(h("ul", { class: "bad" }, c.flags.map((f) => h("li", {}, f))));
  return b;
}
function narrativeForm(run) {
  const panel = h("div", { class: "panel" }, h("h3", {}, "Pre-filled from collected data (editable) and narrative fields (type them)"));
  for (const block of run.form.reference) panel.append(h("div", {}, h("strong", {}, block.title), h("div", { class: "ref" }, block.text)));
  const inputs = {};
  for (const f of run.form.fields) { const el = fieldInput(f, run.field_values[f.name]); inputs[f.name] = el; panel.append(fieldBlock(f, el.node)); }
  const message = h("p", { class: "bad" });
  panel.append(h("p", {}, h("button", { onclick: async () => {
    message.textContent = "";
    try {
      const values = {}; for (const [k, v] of Object.entries(inputs)) values[k] = v.get();
      await api("POST", "/api/runs/" + run.id + "/fields", { fields: values });
      state.shownStatus = null; poll();
    } catch (e) { message.textContent = e.message; }
  } }, "Generate deliverables")), message);
  return panel;
}
async function download(run, slot, name) {
  const response = await fetch("/api/runs/" + run.id + "/download/" + slot, { headers: { "X-CSRF-Token": csrf } });
  if (!response.ok) { banner("Download failed."); return; }
  const url = URL.createObjectURL(await response.blob());
  const a = h("a", { href: url, download: name }); document.body.append(a); a.click(); a.remove(); URL.revokeObjectURL(url);
}
function outputsBlock(run) {
  const table = h("table", {}, h("tr", {}, h("th", {}, "Slot"), h("th", {}, "File"), h("th", {}, "SHA-256"), h("th", {}, "")));
  for (const [slot, o] of Object.entries(run.outputs)) table.append(h("tr", {}, h("td", {}, slot), h("td", {}, o.name), h("td", { class: "mono" }, (o.sha256 || "").slice(0, 16)),
    h("td", {}, h("button", { class: "secondary", onclick: () => download(run, slot, o.name) }, "Download"))));
  const panel = h("div", { class: "panel" }, h("h3", {}, "Deliverables"), h("p", { class: "help" }, "Saved under: " + run.output_dir), table);
  if (run.validation && run.validation.slots) panel.append(h("p", {}, "Validators: ", Object.entries(run.validation.slots).map(([s, v]) => h("span", { class: v === "passed" ? "ok" : "bad" }, s + ": " + (v === "passed" ? "passed" : "FAILED") + "  ")), h("br"), "Extra checks: " + (run.validation.extra === "passed" ? "passed" : "see problems")));
  if (run.archived_previous.length) panel.append(h("p", { class: "help" }, "Previous deliverables archived: " + run.archived_previous.length));
  return panel;
}
function reviewBlock(run) {
  const name = h("input", { type: "text", maxlength: 80, placeholder: "Reviewer's full name" });
  const confirm = h("input", { type: "checkbox" });
  const message = h("p", { class: "bad" });
  const act = (kind) => async () => {
    message.textContent = "";
    try { await api("POST", "/api/runs/" + run.id + "/" + kind, { reviewer: name.value, confirm: confirm.checked, reason: "" }); state.shownStatus = null; poll(); }
    catch (e) { message.textContent = e.message; }
  };
  return h("div", { class: "panel" }, h("h3", {}, "Human review (required for completion)"),
    h("p", { class: "help" }, "Open the files in the folder above and review them. Your name and the UTC time are recorded in the private run record."),
    h("label", {}, "Reviewer name"), name,
    h("label", {}, confirm, " I reviewed the deliverables and approve them as drafts (nothing is sent)."),
    h("p", {}, h("button", { onclick: act("approve") }, "Approve"), " ", h("button", { class: "danger", onclick: act("reject") }, "Reject")), message);
}

// ---- history + bootstrap ---------------------------------------------------------------------------------
function renderHistory(items) {
  const root = $("history"); clear(root);
  if (!items.length) return;
  root.append(h("h2", {}, "Recent runs"), h("table", {}, h("tr", {}, h("th", {}, "Run"), h("th", {}, "Category"), h("th", {}, "Status"), h("th", {}, "")),
    items.map((r) => h("tr", {}, h("td", { class: "mono" }, r.id + (r.dry_run ? " (dry)" : "")), h("td", {}, r.category_id), h("td", {}, r.status),
      h("td", {}, h("button", { class: "secondary", onclick: () => { logLines.length = 0; state.shownStatus = null; openRun(r.id); } }, "Open"))))));
}
async function refreshBootstrap(showPicker) {
  const data = await api("GET", "/api/bootstrap");
  state.categories = data.categories; state.wiz = data.wiz; renderWiz(); renderHistory(data.history);
  if (showPicker) renderPicker();
}
window.addEventListener("hashchange", () => {
  if (location.hash === "#wiz-connected") { banner("Wiz connected.", "ok"); refreshBootstrap(false); }
  else if (location.hash === "#wiz-error") banner("Wiz sign-in did not complete. Try Connect Wiz again.");
});
refreshBootstrap(true).then(() => window.dispatchEvent(new Event("hashchange"))).catch((e) => banner("Could not load: " + e.message));
