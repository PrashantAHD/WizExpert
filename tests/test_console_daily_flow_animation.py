"""Workflow animation (all categories): presence, placement, accessibility (static)."""
from __future__ import annotations

from pathlib import Path

import wizexpert.console as pkg

STATIC = Path(pkg.__file__).parent / "static"
JS = (STATIC / "app.js").read_text(encoding="utf-8")
CSS = (STATIC / "style.css").read_text(encoding="utf-8")


CATEGORY_IDS = (
    "daily-progress-reporting",
    "risk-issues",
    "weekly-progress-reporting",
    "monthly-governance-reporting",
)


def _block() -> str:
    return JS.split("function workflowAnimation(")[1].split("function rulesPanel(")[0]


def _flows() -> str:
    return JS.split("const WORKFLOW_FLOWS")[1].split("const WORKFLOW_FLOW_GLYPHS")[0]


def test_animation_placed_directly_after_rules_for_every_category():
    guard = "if (flowAnimation) main.append(flowAnimation);"
    assert "const flowAnimation = workflowAnimation(category);" in JS and guard in JS
    rules = "main.append(rulesPanel(category));"
    assert JS.index(rules) < JS.index(guard) < JS.index("main.append(detail);", JS.index(guard))
    assert "dailyWorkflowAnimation" not in JS


def test_every_category_has_data_driven_flow_with_distinct_stages():
    flows = _flows()
    import re
    for cid in CATEGORY_IDS:
        assert f'"{cid}": {{' in flows
    keys = re.findall(r'key: "([a-z-]+)"', flows)
    assert len(keys) == len(set(keys)) == len(CATEGORY_IDS)
    for s in ("Fresh read-only collection", "Grouped and reconciled findings", "Exact-ID inventory",
              "Snapshot and inventory validation", "Report pack and inactive workbook",
              "Draft-only human review"):
        assert s in flows
    assert "Risk analysis" in flows and "Week-over-week comparison" in flows
    assert "Prior-month baseline" in flows and "READ \\u2192 VERIFY \\u2192 REVIEW" in flows


def test_flow_data_has_no_client_specific_or_unsafe_content():
    flows = _flows().lower()
    for bad in ("http", "@", "password", "token", "php2shell"):
        assert bad not in flows


def test_animation_accessible_labels_and_safe_dom():
    block = _block()
    assert 'aria-labelledby": "flow-anim-title"' in block and 'h("ol"' in block
    assert (
        '"flow-live"' in block
        and '"flow-signal"' in block
        and "flow-orbit" in block
        and '"flow-rail"' in block
    )
    assert '"flow-packet flow-packet-b"' in block and "WORKFLOW_FLOW_HUES" in block
    assert '"flow-kicker"' in block and "flow.kicker" in block and "category.title" in block
    assert 'aria-hidden": "true"' in block and "innerHTML" not in block
    assert "if (!flow) return null;" in block

def test_animation_css_is_css_only_and_respects_reduced_motion():
    assert "@keyframes flow-pulse" in CSS
    tail = CSS.split("@keyframes flow-bar")[1]
    assert "prefers-reduced-motion: reduce" in tail and "animation: none" in tail
    assert "@keyframes flow-signal" in CSS and "@keyframes flow-sheen" in CSS
    assert "grid-template-columns: repeat(3" in CSS
    assert "@media (max-width: 560px)" in CSS

def test_flow_track_wraps_rail_and_steps_once_and_is_styled():
    block = _block()
    assert block.count("const rail =") == 1 and block.count("const list =") == 1
    assert 'h("div", { class: "flow-track" }, rail, list)' in block
    assert ".flow-track {" in CSS and "--hue" in block and "@keyframes flow-ring" in CSS
    assert "@media (forced-colors: active)" in CSS
