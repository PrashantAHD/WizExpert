# Workflow console

A local, click-driven page for the three reporting categories (Risk Issues, Daily
Progress Reporting, Monthly Governance Reporting). It replaces typing commands, not the
gates: each run still goes through the category contract, the post-collection check, the
bound validators and a named human review.

```powershell
wizexpert console --private-root <private workspace> [--port 8765] [--no-browser]
```

The console is generic. Everything client-specific (collection plan, data fill, builders,
validators, output folder) is a **private adapter** loaded from
`<private-root>/templates/console_adapters/adapters.py`, which must define
`get_adapters(private_root) -> list[CategoryAdapter]` (see `wizexpert/console/adapters.py`).
Deliverables are written under `<private-root>/deliverables/`; run records, evidence copies
and the activity log live in `<private-root>/deliverables/_console-runs/<run-id>/`.
Nothing client-specific belongs in this repository.

## What a run does

1. **Pick a category, enter inputs** (issue-rule ID, reporting month, paths) and choose a
   live run or, where the adapter supports it, an offline *dry run* that replays retained
   evidence and writes only inside the private run folder.
2. **Collect** through the Wiz MCP server (read-only; see below). Every call is recorded in
   an activity log, parallel where the plan allows, retried up to three times per call.
3. **Post-collection check**: `workflow-qa collection-check` runs on the real activity log
   and a manifest (reused sources, expected vs collected counts). A flagged check blocks
   generation exactly as it does on the command line.
4. **Narrative**: values the generators can derive from collected data are pre-filled and
   editable; narrative fields are typed by you. There is no text generation.
5. **Generate**: existing deliverables are archived first (moved to `archives/<UTC>/`; they
   are restored if generation fails or validates badly). Outputs are validated with each
   slot's bound validator plus the adapter's actual-file checks.
6. **Review**: the run stops at *awaiting reviewer approval*. A named human enters their
   name and clicks **Approve** (or Reject). The name and UTC time go into the run's private
   record (`run.json`); a placeholder name is refused and the record notes whether the
   reviewer differs from the preparer. Only then does the enforced category pipeline
   (`run_category_pipeline`) run with
   `{workflow_qa, review, category_id, version, slots, template_sha256, outputs_sha256}`.
   `workflow_qa` is `passed` only when the recorded collection check passed and every
   validator passed on the actual files; the console never self-certifies review.

The console does not run the evidence-bound `workflow-qa check` handoff review (rule
coverage, native rendering review, independent reviewer attestations). That remains a
separate gate and the console never fabricates it.

## Wiz sign-in (MCP, OAuth 2.1 + PKCE)

The console is an MCP client for the remote Wiz MCP server (`--wiz-url`, default
`https://mcp.app.wiz.io`, streamable HTTP, tools `discover` and `execute`).

- **Connect Wiz** discovers the authorization server (MCP protected-resource metadata,
  RFC 8414/OIDC metadata), registers a public client dynamically when offered (else pass
  `--client-id`), and opens the sign-in page in **your** browser with an S256 PKCE challenge
  and a single-use `state`. The redirect returns to `http://127.0.0.1:<port>/oauth/callback`.
- Tokens are kept **in memory only**: never written to disk, logs, evidence or outputs.
  They are discarded on Disconnect, on a 401, or when the process ends.
- A 401 / OAuth challenge (or an authentication error from the tool) mid-run **stops the run**
  with "Reconnect Wiz"; no observation window continues and nothing is published. Start a
  new run after reconnecting.
- **Read-only policy** (before any network traffic): only `discover` and `execute` are ever
  called; `execute` accepts only read-verb tools (`get_*`, `list_*`, `search_*`, plus
  `execute_graph_query` and `graph_search`), refuses any tool name containing a write verb
  and any argument containing a GraphQL `mutation`.
- The console adds no rules of its own: it runs the enforced workflow. Collection has no
  elapsed-time limit unless an adapter's enforced workflow defines one
  (`--observation-window-minutes` overrides; `0` disables). If a window applies and runs
  out, the run is blocked and evidence from different runs is never stitched.

## Safety properties

- Binds `127.0.0.1` only; the `Host` header must be the loopback name and port served.
- Per-process CSRF token on every `/api` request; POSTs also need a matching `Origin` and a
  JSON content type. Strict CSP (no inline script, no third-party resources), no caching,
  no framing, no referrer. Request logging is disabled (the redirect carries a code).
- All values from the server are rendered as text; the UI never builds markup from data.
- Output paths are resolved and must stay inside the deliverables root; downloads are limited
  to a run's recorded deliverables and are sent as attachments.
- One active run at a time. Retained evidence is written exclusively (never overwritten).
- Email is never sent (drafts only); Wiz, ticketing and cloud systems are never changed.

## Tests

`python -m pytest tests/test_console_*.py` covers the server security (CSRF, Host/Origin,
loopback bind, confinement), the MCP client against a fake MCP/OAuth server (PKCE, in-memory
tokens, 401 reconnect, mutation refusal), run orchestration (collection gate, review gate,
archive/rollback, window) with synthetic adapters. Live sign-in needs your browser and MFA
and cannot be automated; test it manually with the steps above.
