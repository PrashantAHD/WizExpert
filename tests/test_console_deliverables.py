"""Case "Deliverables" panel: listing, containment, extension->app mapping, mocked launches."""

from __future__ import annotations

import json

import pytest
from test_console_core import env  # noqa: F401  (fixture)
from test_console_server import api, console, token_of  # noqa: F401  (fixtures/helpers)

from wizexpert.console import launcher

CASE = "Synthetic-Case-wc-id-1"


@pytest.fixture
def case(env):  # noqa: F811
    config, workspace, _ = env
    folder = workspace / "deliverables" / "Risk-Issues" / CASE
    (folder / "evidence").mkdir(parents=True)
    for name in ("a.html", "b.pdf", "c.xlsx", "d.pptx", "e.docx", "f.png", "g.zip", "h.csv"):
        (folder / name).write_text("x", encoding="utf-8")
    (folder / "evidence" / "raw.json").write_text("secret", encoding="utf-8")
    (folder / ".env").write_text("k=v", encoding="utf-8")
    (workspace / "deliverables" / "outside.html").write_text("x", encoding="utf-8")
    return config, folder


@pytest.fixture
def launches(monkeypatch):
    calls = []
    monkeypatch.setattr(launcher.subprocess, "Popen", lambda args, **kw: calls.append(args))
    monkeypatch.setattr(
        launcher.os, "startfile", lambda p: calls.append(["startfile", p]), raising=False
    )
    monkeypatch.setattr(launcher, "_find_exe", lambda app: f"C:/apps/{app}.exe")
    return calls


def test_listing_is_allow_listed_and_top_level(case):
    config, _ = case
    files = {f["name"]: f for f in launcher.list_case_files(config, CASE)}
    assert set(files) == {"a.html", "b.pdf", "c.xlsx", "d.pptx", "e.docx", "f.png", "h.csv"}
    assert files["f.png"]["can_open_in_chrome"] and not files["a.html"]["can_open_in_chrome"]
    assert files["a.html"]["type"] == "html" and files["a.html"]["modified"] > 0


@pytest.mark.parametrize(
    ("name", "app"),
    [
        ("a.html", "chrome"),
        ("b.PDF", "chrome"),
        ("c.xlsx", "excel"),
        ("c.xls", "excel"),
        ("h.csv", "excel"),
        ("d.pptx", "powerpoint"),
        ("d.ppt", "powerpoint"),
        ("e.docx", "word"),
        ("f.png", "default"),
        ("f.svg", "default"),
        ("x.md", "default"),
    ],
)
def test_extension_app_mapping(name, app):
    assert launcher.app_for(name) == app


def test_open_uses_argument_list_and_mapped_app(case, launches):
    config, folder = case
    assert launcher.open_case_file(config, CASE, "c.xlsx") == "excel"
    assert launches == [["C:/apps/excel.exe", str(folder / "c.xlsx")]]


def test_image_default_and_chrome_alternate(case, launches):
    config, folder = case
    assert launcher.open_case_file(config, CASE, "f.png") == "default"
    assert launches[-1] == ["startfile", str(folder / "f.png")]
    assert launcher.open_case_file(config, CASE, "f.png", "chrome") == "chrome"
    assert launches[-1][0] == "C:/apps/chrome.exe"
    with pytest.raises(ValueError):
        launcher.open_case_file(config, CASE, "f.png", "cmd")


def test_falls_back_to_startfile_when_app_missing(case, launches, monkeypatch):
    config, folder = case
    monkeypatch.setattr(launcher, "_find_exe", lambda app: None)
    assert launcher.open_case_file(config, CASE, "b.pdf") == "default"
    assert launches == [["startfile", str(folder / "b.pdf")]]


@pytest.mark.parametrize(
    "name",
    [
        "../outside.html",
        "..\\x.html",
        "/etc/passwd",
        "evidence/raw.json",
        "g.zip",
        ".env",
        "nope.pdf",
        "",
    ],
)
def test_containment_and_allow_list(case, launches, name):
    config, _ = case
    with pytest.raises(ValueError):
        launcher.open_case_file(config, CASE, name)
    assert launches == []


@pytest.mark.parametrize("bad", ["..", "../Risk-Issues", "a/b", "", "Missing-Case"])
def test_bad_case_names_are_refused(case, bad):
    config, _ = case
    with pytest.raises(ValueError):
        launcher.list_case_files(config, bad)


def test_http_listing_and_open(console, monkeypatch):  # noqa: F811
    server, config, _ = console
    folder = config.resolved_workspace() / "deliverables" / "Risk-Issues" / CASE
    folder.mkdir(parents=True)
    (folder / "r.xlsx").write_text("x", encoding="utf-8")
    calls = []
    monkeypatch.setattr(launcher.subprocess, "Popen", lambda args, **kw: calls.append(args))
    monkeypatch.setattr(launcher, "_find_exe", lambda app: f"{app}.exe")
    token = token_of(server)
    status, _h, body = api(server, token, "GET", f"/api/imports/case-files?case={CASE}")
    assert status == 200 and [f["name"] for f in json.loads(body)["files"]] == ["r.xlsx"]
    payload = json.dumps({"case": CASE, "name": "r.xlsx"}).encode()
    status, _h, body = api(server, token, "POST", "/api/imports/case-files/open", payload)
    assert status == 200 and json.loads(body)["app"] == "excel"
    assert calls and calls[0][0] == "excel.exe"
    bad = json.dumps({"case": CASE, "name": "../x.xlsx"}).encode()
    status, *_ = api(server, token, "POST", "/api/imports/case-files/open", bad)
    assert status >= 400 and len(calls) == 1


# -- every category uses the shared endpoint --------------------------------------------------


@pytest.fixture
def categories(console, monkeypatch):  # noqa: F811
    server, config, _ = console
    root = config.resolved_workspace() / "deliverables"
    (root / "Risk-Issues" / CASE).mkdir(parents=True)
    (root / "Risk-Issues" / CASE / "r.xlsx").write_text("x", encoding="utf-8")
    (root / "Weekly-Progress-Reporting" / "2026-11-03").mkdir(parents=True)
    (root / "Weekly-Progress-Reporting" / "2026-11-03" / "w.pdf").write_text("x", encoding="utf-8")
    monthly = root / "Monthly-Governance-Reporting"
    monthly.mkdir(parents=True)
    (monthly / "Governance-Workbook-October-2026.xlsx").write_text("x", encoding="utf-8")
    (monthly / "Governance-Workbook-September-2026.xlsx").write_text("x", encoding="utf-8")
    calls = []
    monkeypatch.setattr(launcher.subprocess, "Popen", lambda args, **kw: calls.append(args))
    monkeypatch.setattr(launcher, "_find_exe", lambda app: f"{app}.exe")
    return server, calls


@pytest.mark.parametrize(
    ("category", "folder", "name"),
    [
        ("risk-issues", CASE, "r.xlsx"),
        ("weekly", "2026-11-03", "w.pdf"),
        ("monthly", "2026-10", "Governance-Workbook-October-2026.xlsx"),
    ],
)
def test_every_category_lists_and_opens_via_shared_endpoint(categories, category, folder, name):
    server, calls = categories
    token = token_of(server)
    status, _h, body = api(
        server, token, "GET", f"/api/imports/files?category={category}&folder={folder}"
    )
    assert status == 200 and [f["name"] for f in json.loads(body)["files"]] == [name]
    payload = json.dumps({"category": category, "folder": folder, "name": name}).encode()
    assert api(server, token, "POST", "/api/imports/files/open", payload)[0] == 200
    assert len(calls) == 1
    bad = json.dumps({"category": category, "folder": folder, "name": "../x.pdf"}).encode()
    assert api(server, token, "POST", "/api/imports/files/open", bad)[0] >= 400
    assert len(calls) == 1


@pytest.mark.parametrize(
    ("category", "folder"),
    [("nope", "x"), ("weekly", "../Risk-Issues"), ("monthly", "bad"), ("weekly", "")],
)
def test_shared_endpoint_refuses_bad_category_or_folder(categories, category, folder):
    server, _ = categories
    status, *_ = api(
        server, token_of(server), "GET", f"/api/imports/files?category={category}&folder={folder}"
    )
    assert status == 400


def test_legacy_open_routes_through_launcher_checks(categories):
    server, calls = categories
    token = token_of(server)
    good = "deliverables/Weekly-Progress-Reporting/2026-11-03/w.pdf"
    assert api(server, token, "POST", "/api/imports/open", {"path": good})[0] == 200
    assert len(calls) == 1
    for bad in (
        "deliverables/Weekly-Progress-Reporting/2026-11-03/../../x.pdf",
        "deliverables/Weekly-Progress-Reporting/w.pdf",
        "outside.pdf",
        "",
    ):
        assert api(server, token, "POST", "/api/imports/open", {"path": bad})[0] >= 400
    assert len(calls) == 1


def test_app_js_has_no_per_file_view_buttons():
    from pathlib import Path

    js = (Path(launcher.__file__).parent / "static" / "app.js").read_text(encoding="utf-8")
    for token in ("fileButton", "viewFile", "FILE_KIND", "/api/imports/open", "case-files"):
        assert token not in js
    assert js.count("function deliverablesButton(") == 1  # the single shared button
    for category in ("risk-issues", "weekly", "monthly"):
        assert f'deliverablesButton("{category}"' in js
