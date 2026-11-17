"""Sync (Risk Issues status sync) canonical rules ``SY-`` and their code-level enforcement.

Synthetic data only. Behaviour tests for the sync itself live in test_console_features.py.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from test_console_core import env  # noqa: F401  (fixture)
from test_console_features import _manager, _risk
from test_console_server import api, console, token_of  # noqa: F401  (fixtures/helpers)

from wizexpert.__main__ import main
from wizexpert.category_rules import WORKFLOW_MODULES, module_for, sync
from wizexpert.console import categories, imports
from wizexpert.console.runs import RunError

ROOT = Path(__file__).resolve().parents[1]


def test_sync_rules_registry_cli_and_payload(capsys):
    assert set(WORKFLOW_MODULES) == {"sync"} and module_for("sync") is sync
    assert "sync" not in categories.CATEGORIES  # a workflow page, not a deliverable category
    assert main(["rules", "sync"]) == 0
    out = capsys.readouterr().out
    assert "SY-REF-02" in out and "enforced by: wizexpert.console.imports:approve_refresh" in out
    assert main(["rules", "sync", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["category"] == "sync" and all(r["id"].startswith("SY-") for r in data["rules"])
    assert main(["rules"]) == 0 and "sync:" in capsys.readouterr().out
    payload = sync.workflow_payload()
    assert payload["kind"] == "workflow" and payload["id"] == "sync"
    assert "actions" not in payload and "stages" not in payload  # no Collect/Generate/Start
    assert payload["rule_count"] == len(sync.RULES) and len(payload["steps"]) >= 6


def test_bootstrap_lists_sync_workflow_beside_categories(console):  # noqa: F811
    server, _config, _home = console
    token = token_of(server)
    _s, _h, body = api(server, token, "GET", "/api/bootstrap")
    data = json.loads(body)
    assert [w["id"] for w in data["workflows"]] == ["sync"]
    assert "sync" not in [c["id"] for c in data["categories"]]


def test_sync_actions_exist_only_in_risk_issues():  # SY-SCP-01
    for category in ("daily-progress-reporting", "weekly-progress-reporting",
                     "monthly-governance-reporting"):
        for action in imports.SYNC_ACTIONS:
            with pytest.raises(categories.InputError):
                categories.validate(category, {"case_folder": "Case-wc-id-1"}, action)


def test_sync_may_only_start_status_check_or_sync_refresh():  # SY-REF-01
    started = []
    with pytest.raises(ValueError):
        imports._start_sync_run(lambda a, i: started.append(a), "refresh-case", {})
    assert started == []
    imports._start_sync_run(lambda a, i: started.append(a), "sync-refresh", {})
    assert started == ["sync-refresh"]


def test_invalid_assignee_refuses_and_starts_nothing(env):  # noqa: F811  SY-SCP-03
    config, workspace, _ = env
    _risk(workspace)
    calls = []
    config.status_sync_assignee = "bad value!"
    with pytest.raises(ValueError, match="status_sync_assignee"):
        imports.run_status_sync(config, lambda a, i: calls.append(a))
    assert calls == [] and imports.status_sync_state(config) == {}
    config.status_sync_assignee = "owner" + "@" + "example.invalid"  # '@' is accepted
    imports.run_status_sync(config, lambda a, i: type("R", (), {"id": "r1", "status": "running"}))
    assert imports.status_sync_state(config)["phase"] == "checking"


def test_get_sync_endpoint_is_side_effect_free(console):  # noqa: F811  SY-CHK-03
    server, config, _home = console
    token = token_of(server)
    imports._write_sync_state(config, {"last_started": 1.0, "phase": "checking",
                                       "check_run_id": "chk", "cases": ["A"]})
    path = config.state_dir / "status-sync.json"
    before = path.read_bytes()
    status, _h, body = api(server, token, "GET", "/api/imports/risk-issues/sync")
    assert status == 200 and json.loads(body)["queued"] == []
    assert path.read_bytes() == before
    assert not list((config.state_dir).glob("runs*"))


def test_sync_refresh_needs_an_existing_case_folder(env):  # noqa: F811  SY-SCP-02
    config, workspace, _ = env
    _risk(workspace)
    with pytest.raises(RunError):
        _manager(config).start("risk-issues", {"case_folder": "Missing-wc-id-99"}, "sync-refresh")
    assert not list((workspace / "deliverables" / "Risk-Issues").glob("Missing*"))


def test_sync_page_and_topbar_in_client():  # SY-STA-03
    js = (ROOT / "wizexpert/console/static/app.js").read_text("utf-8")
    assert "function showSyncWorkflow(" in js and "state.workflows" in js
    # The topbar control is unchanged and still Risk Issues-only (see test_console_features).
    assert "function syncAllowedHere()" in js and "Risk Issues only" in js
    # The Sync page has no generic run/Collect/Generate controls; only the dedicated status sync.
    page = js.split("function showSyncWorkflow(")[1].split("function rulesPanel(")[0]
    assert "formPanel(" not in page and "/api/runs" not in page
    assert "Collect" not in page and "Generate" not in page
    assert page.count('"POST"') == 1
    assert '"POST", "/api/imports/risk-issues/approve-refresh"' in page
    assert "runStatusSync(" in page and "innerHTML" not in page


def test_sync_page_has_sync_now_button_and_renders_result():
    js = (ROOT / "wizexpert/console/static/app.js").read_text("utf-8")
    page = js.split("function showSyncWorkflow(")[1].split("function rulesPanel(")[0]
    assert '"Sync now"' in page and 'id: "sync-page-btn"' in page
    assert "syncBtn.disabled = true" in page and "Syncing" in page and "aria-busy" in page
    assert "runStatusSync((res) =>" in page and "renderLast(" in page
    assert "res.started" in page and "res.busy" in page and "res.skipped" in page
    assert "check_run_id" in page and "result_name" in page and "s.report" in page
    assert "Approve refresh" in page and "s.changed" in page
    # The topbar flow is unchanged and shares the same helper.
    assert "async function syncFromTopbar(" in js and "runStatusSync(null, !silent)" in js


def test_status_sync_post_endpoint_refuses_without_assignee(console):  # noqa: F811
    server, config, _home = console
    token = token_of(server)
    status, _h, body = api(server, token, "POST", "/api/imports/risk-issues/sync", {"force": False})
    # The dedicated endpoint the page button posts to; without an owner assignee it starts nothing.
    assert status == 400 and b"assignee" in (body if isinstance(body, bytes) else body.encode())
    assert not list(config.state_dir.glob("runs*"))


def test_sync_diagram_is_generated_from_steps_and_self_contained():
    js = (ROOT / "wizexpert/console/static/app.js").read_text("utf-8")
    css = (ROOT / "wizexpert/console/static/style.css").read_text("utf-8")
    diagram = js.split("const SVG_NS")[1].split("function showSyncWorkflow(")[0]
    assert "wf.steps" in diagram and "steps.forEach" in diagram and 'role: "img"' in diagram
    assert "aria-label" in diagram and 'sv("title"' in diagram and "figcaption" in diagram
    assert "prefers-reduced-motion" in diagram and "animateMotion" in diagram
    assert "syncRuleLabel(wf" in diagram and "READ-ONLY WIZ" in diagram
    page = js.split("function showSyncWorkflow(")[1].split("function rulesPanel(")[0]
    assert "syncDiagram(wf)" in page
    block = css.split("Sync design diagram")[1]
    assert "@keyframes sx-flow" in block and "prefers-reduced-motion: reduce" in block
    assert "style:" not in diagram and ".style." not in diagram  # CSP style-src 'self'
    for text in (diagram, block):
        assert "http://" not in text.replace("http://www.w3.org/2000/svg", "")
        assert "https://" not in text and "url(" not in text and "@import" not in text
    for t, _ in sync.STEPS:
        assert t  # the diagram nodes come from these steps via the payload


def test_docs_list_sync_rules():
    for name in ("CONSOLE.md", "WORKFLOW-QA.md"):
        text = (ROOT / "docs" / name).read_text("utf-8")
        assert "SY-" in text and "wizexpert rules sync" in text, name


def test_home_sync_card_asset_and_about_content():
    js = (ROOT / "wizexpert/console/static/app.js").read_text("utf-8")
    svg = (ROOT / "wizexpert/console/static/assets/workflow-sync.svg").read_text("utf-8")
    home = js.split("function renderHome(")[1].split("function showHome(")[0]
    assert "state.workflows" in home and "[...state.categories, ...(state.workflows || [])]" in home
    assert "wfPath(c.id)" in home and 'sync: "workflow-sync.svg"' in js
    assert '["sync", "Sync"' in js.split("const ABOUT_CASES")[1].split("function aboutSection(")[0]
    for text in (
        "NOTHING LEAVES WITHOUT A PERSON",
        "Approve refresh",
        "Sync Refresh",
        "prefers-reduced-motion",
        "forced-colors",
    ):
        assert text in svg
    assert "http://" not in svg.replace("http://www.w3.org/2000/svg", "") and "https://" not in svg
    assert "<script" not in svg and "style=" not in svg
