"""Daily Progress Reporting Deliverables: scan, listing and category enforcement."""

from __future__ import annotations

import pytest
from test_console_core import env  # noqa: F401  (fixture)

from wizexpert.console import categories, imports, launcher

CAMPAIGN = "Example-Campaign"


@pytest.fixture
def daily(env):  # noqa: F811
    config, workspace, _ = env
    base = workspace / "deliverables" / "Daily-Progress-Reporting"
    folder = base / CAMPAIGN
    for sub in ("evidence", "archives", "snapshots"):
        (folder / sub).mkdir(parents=True)
        (folder / sub / "x.html").write_text("x", encoding="utf-8")
    (base / ".hidden").mkdir()
    for name in ("report.html", "report.pdf", "vm.xlsx", "cves.csv", "reply.html", "tool.py"):
        (folder / name).write_text("x", encoding="utf-8")
    return config


def test_scan_daily_skips_dot_folders(daily):
    assert [c["name"] for c in imports.scan_daily(daily)] == [CAMPAIGN]


def test_daily_listing_top_level_only(daily):
    names = {f["name"] for f in launcher.list_files(daily, "daily", CAMPAIGN)}
    assert names == {"report.html", "report.pdf", "vm.xlsx", "cves.csv", "reply.html"}


def test_daily_unknown_folder_rejected(daily):
    with pytest.raises(ValueError):
        launcher.list_files(daily, "daily", "../x")


def test_every_file_category_has_launcher_dir():
    for category in categories.CATEGORIES.values():
        if category.imports:
            assert category.imports in launcher.CATEGORY_DIRS, category.category_id


def _age(path, days):
    import os
    import time

    stamp = time.time() - days * 86400
    os.utime(path, (stamp, stamp))


def test_daily_by_date_hides_expired_and_groups_newest_first(daily):
    folder = daily.resolved_workspace() / "deliverables" / "Daily-Progress-Reporting" / CAMPAIGN
    _age(folder / "report.html", 1)
    _age(folder / "report.pdf", 1)
    _age(folder / "vm.xlsx", 3)
    for name in ("cves.csv", "reply.html"):
        _age(folder / name, 9)
    groups = imports.scan_daily_by_date(daily)
    assert [len(g["files"]) for g in groups] == [2, 1]
    assert groups[0]["date"] > groups[1]["date"]
    shown = {f["name"] for g in groups for f in g["files"]}
    assert shown == {"report.html", "report.pdf", "vm.xlsx"}


def test_daily_cleanup_dry_run_then_apply_keeps_subfolders(daily):
    folder = daily.resolved_workspace() / "deliverables" / "Daily-Progress-Reporting" / CAMPAIGN
    other = daily.resolved_workspace() / "deliverables" / "Weekly-Progress-Reporting"
    other.mkdir(parents=True)
    (other / "old.html").write_text("x", encoding="utf-8")
    _age(other / "old.html", 30)
    for sub in ("evidence", "archives", "snapshots"):
        _age(folder / sub / "x.html", 30)
    _age(folder / "report.html", 30)
    assert imports.cleanup_daily(daily) == [f"{CAMPAIGN}/report.html"]
    assert (folder / "report.html").exists()
    imports.cleanup_daily(daily, apply=True)
    assert not (folder / "report.html").exists()
    assert (folder / "report.pdf").exists()
    for sub in ("evidence", "archives", "snapshots"):
        assert (folder / sub / "x.html").exists()
    assert (other / "old.html").exists()


def test_daily_category_has_deliverables_stage_after_in_progress():
    stages = [s for s, _ in categories.CATEGORIES["daily-progress-reporting"].stages]
    assert stages == ["new", "in-progress", "deliverables"]
