"""Every generated-file location must have a Deliverables mapping and a UI button."""

from __future__ import annotations

from pathlib import Path

import pytest
from test_console_core import env  # noqa: F401  (fixture)

from wizexpert.console import imports, launcher

APP_JS = Path(launcher.__file__).parent / "static" / "app.js"

GENERATED = {
    imports.RISK_DIR: "risk-issues",  # case files, email drafts, change summaries, updates
    imports.WEEKLY_DIR: "weekly",
    imports.MONTHLY_DIR: "monthly",
    imports.DAILY_DIR: "daily",
}


@pytest.mark.parametrize(("directory", "category"), GENERATED.items())
def test_generated_location_has_mapping_and_button(directory, category):
    assert launcher.CATEGORY_DIRS.get(category) == directory
    assert f'deliverablesButton("{category}"' in APP_JS.read_text(encoding="utf-8")


def test_status_check_results_stay_backend_only(env):  # noqa: F811
    config, workspace, _ = env
    base = workspace / "deliverables" / "Status-Check"
    base.mkdir(parents=True)
    (base / "abc12345.json").write_text("{}", encoding="utf-8")
    assert "status-check" not in launcher.CATEGORY_DIRS
    with pytest.raises(ValueError):
        launcher.list_files(config, "status-check", "results")
    with pytest.raises(ValueError):
        launcher.open_relative(config, "deliverables/Status-Check/abc12345.json")
    case = workspace / "deliverables" / "Risk-Issues" / "Case-1"
    case.mkdir(parents=True)
    (case / "e.json").write_text("{}", encoding="utf-8")
    assert launcher.list_files(config, "risk-issues", "Case-1") == []
