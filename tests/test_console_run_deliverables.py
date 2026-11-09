"""Run page: server-resolved ``deliverables`` {category, folder, reason} for every category."""

from __future__ import annotations

from test_console_core import env  # noqa: F401  (fixture)

from wizexpert.console import launcher, runs


def _run(category_id, **values):
    return runs.Run(id="r1", category_id=category_id, values=values, prompt="p", created=0.0)


def _mk(workspace, directory, name):
    folder = workspace / "deliverables" / directory / name
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def test_risk_case_from_input(env):  # noqa: F811
    config, workspace, _ = env
    _mk(workspace, launcher.CATEGORY_DIRS["risk-issues"], "Synthetic-Case-1")
    out = runs.run_deliverables(config, _run("risk-issues", case_folder="Synthetic-Case-1"), [])
    assert out == {"category": "risk-issues", "folder": "Synthetic-Case-1", "reason": ""}


def test_folder_from_written_files_weekly(env):  # noqa: F811
    config, workspace, _ = env
    d = launcher.CATEGORY_DIRS["weekly"]
    _mk(workspace, d, "2026-W45")
    files = [{"name": "r.html", "location": f"deliverables/{d}/2026-W45"}]
    out = runs.run_deliverables(config, _run("weekly-progress-reporting"), files)
    assert (out["category"], out["folder"]) == ("weekly", "2026-W45")


def test_monthly_from_month_input(env):  # noqa: F811
    config, workspace, _ = env
    _mk(workspace, launcher.CATEGORY_DIRS["monthly"], "x")
    out = runs.run_deliverables(config, _run("monthly-governance-reporting", month="2026-10"), [])
    assert (out["category"], out["folder"]) == ("monthly", "2026-10")


def test_daily_without_folder_is_disabled_with_reason(env):  # noqa: F811
    config, _, _ = env
    out = runs.run_deliverables(config, _run("daily-progress-reporting"), [])
    assert out["folder"] == "" and out["reason"] == "No files generated yet"


def test_no_files_and_traversal_are_rejected(env):  # noqa: F811
    config, _, _ = env
    assert runs.run_deliverables(config, _run("risk-issues"), [])["folder"] == ""
    bad = _run("risk-issues", case_folder="..")
    assert runs.run_deliverables(config, bad, [])["folder"] == ""


def test_frontend_button_is_wired():
    from pathlib import Path

    js = (Path(launcher.__file__).parent / "static" / "app.js").read_text(encoding="utf-8")
    assert "deliverablesButton(dl.category, dl.folder" in js
    assert "No files generated yet" in js
