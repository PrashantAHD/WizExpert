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
