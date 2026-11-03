"""Console routing, drafts and accessibility contracts (static checks, no browser needed)."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

import wizexpert.console as pkg
from tests.test_console_server import console, request  # noqa: F401

STATIC = Path(pkg.__file__).parent / "static"


def _js() -> str:
    return (STATIC / "app.js").read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "path",
    [
        "/workflow/risk-issues",
        "/workflow/risk-issues/new",
        "/workflow/risk-issues/new/x-y",
        "/run/abc-123",
        "/history",
        "/history/",
        "/in-progress",
        "/dashboard",
        "/dashboard/",
    ],
)
def test_shareable_routes_serve_the_app(console, path):  # noqa: F811
    server, *_ = console
    status, headers, body = request(server, "GET", path)
    assert status == 200 and b"csrf-token" in body


@pytest.mark.parametrize(
    "path",
    [
        "/workflow/", "/workflow/a/b/c/d", "/run/", "/run/a/b", "/workflow/%2e%2e",
        "/runs/1", "/history/x", "/in-progress/x", "/dashboard/x",
    ],
)
def test_other_paths_stay_not_found(console, path):  # noqa: F811
    server, *_ = console
    assert request(server, "GET", path)[0] == 404


def test_frontend_uses_history_routing_and_keeps_secrets_out_of_drafts():
    js = _js()
    needles = (
        "history.pushState", 'addEventListener("popstate"', "sessionStorage", "SECRET_NAME",
        "SECRET_VALUE", "ROUTE_RUN", "ROUTE_WF", "scrollRestoration", "updateIndicator",
        "arrowNav", "stateBox(", "renderCategoryActivity", "Previous runs",
        "showHistory", "showProgress",
        "readCache", "pickRun",
        "makeDataBar", "buildHome",
    )
    for needle in needles:
        assert needle in js, needle
    assert "location.hash !==" not in js
    assert "showPicker(true)" not in js  # no automatic jumps away from a stale run


def test_frontend_accessibility_hooks_in_markup_and_css():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    css = (STATIC / "style.css").read_text(encoding="utf-8")
    for needle in ('class="skip-link"', 'id="active-run"', 'id="route-status"', "aria-live"):
        assert needle in html, needle
    for needle in ('id="v-home"', 'id="v-history"', 'id="v-progress"',
                   'id="v-dashboard"', 'href="/dashboard"',
                       'id="nav-toggle"', 'class="nav"',
                   'href="/in-progress"', 'href="/history"'):
        assert needle in html, needle
    assert re.search(r"\.state-box\b", css) and ".hero" in css and "nav-collapsed" in css
    assert "prefers-reduced-motion" in css and "max-width: 760px" in css


def test_ux_pass_shortcuts_summary_and_page_label():
    js, html = _js(), (STATIC / "index.html").read_text(encoding="utf-8")
    css = (STATIC / "style.css").read_text(encoding="utf-8")
    for needle in ("renderSummary", "pendingG", 'e.key === "/"', "isContentEditable"):
        assert needle in js, needle
    for needle in ('id="page-label"', 'class="shortcuts"', "<kbd>g</kbd>"):
        assert needle in html, needle
    assert ".stats" in css and ".stat.attention" in css and "body.nav-collapsed .shortcuts" in css