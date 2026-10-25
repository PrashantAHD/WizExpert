import json
import os

import pytest

from wizexpert.__main__ import main
from wizexpert.governance import profile


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    for variable in (profile.ENV_VAR, profile.LEGACY_ENV_VAR):
        monkeypatch.delenv(variable, raising=False)
    profile.use(None)
    yield tmp_path
    profile.use(None)


def test_governance_usage_lists_commands(capsys):
    assert main(["governance"]) == 0
    assert "setup" in capsys.readouterr().out
    assert main(["governance", "unknown"]) == 2


def test_governance_setup_runs_through_wizexpert_cli(isolated):
    target = isolated / "client.json"
    assert main(["governance", "setup", "--client-name", "Example Health",
                 "--snapshot-day", "15", "--baseline-month", "2026-03",
                 "--provider-name", "Example Provider", "--output", str(target)]) == 0
    saved = json.loads(target.read_text(encoding="utf-8"))
    assert saved["file_prefix"] == "Example_Health"
    assert saved["snapshot_day"] == 15


def test_legacy_profile_names_still_load(isolated):
    legacy = isolated / profile.LEGACY_LOCAL_NAME
    profile.save(profile.from_json({
        "schema_version": 1, "client_name": "Legacy", "file_prefix": "Legacy",
        "baseline_month": "2026-01", "snapshot_day": 5,
        "provider_name": "Example Provider", "watermark": "PROPRIETARY",
    }), legacy)
    assert profile.find_profile() == legacy
    os.environ[profile.LEGACY_ENV_VAR] = str(legacy)
    try:
        assert profile.ensure().client_name == "Legacy"
    finally:
        del os.environ[profile.LEGACY_ENV_VAR]


def test_new_profile_names_take_precedence(isolated):
    for name, path in (("Legacy", isolated / profile.LEGACY_LOCAL_NAME),
                       ("Current", isolated / profile.LOCAL_NAME)):
        profile.save(profile.from_json({
            "schema_version": 1, "client_name": name, "file_prefix": name,
            "baseline_month": "2026-01", "snapshot_day": 5,
            "provider_name": "Example Provider", "watermark": "PROPRIETARY",
        }), path)
    assert profile.active().client_name == "Current"
    assert profile.user_profile_path().parent.name.lower() == "wizexpert"
