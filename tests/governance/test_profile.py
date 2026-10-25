import json
import os
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest import mock

from openpyxl import Workbook
from PIL import Image

from wizexpert.governance import profile
from wizexpert.governance.dashboard_data import (
    DashboardError,
    Snapshot,
    WorkbookData,
    baseline_open,
    combine_trend,
)
from wizexpert.governance.wiz_report import build_summary_tab, default_snapshots, parse_snapshots

BASE = {
    "schema_version": 1,
    "client_name": "Acme Bank",
    "file_prefix": "Acme",
    "baseline_month": "2026-01",
    "snapshot_day": 5,
    "provider_name": "Example Provider",
    "watermark": "CONFIDENTIAL TO ACME",
}


def make(**changes) -> profile.ClientProfile:
    return profile.from_json({**BASE, **changes})


class ProfileValidationTests(unittest.TestCase):
    def test_valid_profile_round_trips(self):
        acme = make(baseline_open={"CRITICAL": 2, "HIGH": 30})
        self.assertEqual(acme.baseline, date(2026, 1, 5))
        self.assertEqual(acme.snapshot_day, 5)
        self.assertEqual(acme.baseline_total, 32)
        self.assertEqual(profile.from_json(acme.to_json()), acme)

    def test_invalid_values_rejected(self):
        for changes, message in (
            ({"snapshot_day": 29}, "snapshot_day"),
            ({"snapshot_day": 0}, "snapshot_day"),
            ({"baseline_month": "Jan 2026"}, "baseline_month"),
            ({"client_name": " "}, "client_name"),
            ({"file_prefix": "Acme Bank"}, "file_prefix"),
            ({"baseline_open": {"CRITICAL": 1}}, "baseline_open"),
            ({"baseline_open": {"CRITICAL": -1, "HIGH": 2}}, "baseline_open"),
            ({"logo": "logo.gif"}, "logo"),
            ({"schema_version": 2}, "schema_version"),
        ):
            with (
                self.subTest(changes=changes),
                self.assertRaisesRegex(profile.ProfileError, message),
            ):
                make(**changes)


class ProfileLookupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.cwd = os.getcwd()
        os.chdir(self.root)
        self.env = mock.patch.dict(
            os.environ,
            {"APPDATA": str(self.root / "appdata"), "XDG_CONFIG_HOME": str(self.root / "config")},
        )
        self.env.start()
        os.environ.pop(profile.ENV_VAR, None)
        profile.use(None)

    def tearDown(self):
        profile.use(None)
        self.env.stop()
        os.chdir(self.cwd)
        self.temp.cleanup()

    def test_lookup_order_explicit_env_local_user(self):
        user, local, env, explicit = (
            profile.save(make(client_name=name), path)
            for name, path in (
                ("User", profile.user_profile_path()),
                ("Local", self.root / profile.LOCAL_NAME),
                ("Env", self.root / "env.json"),
                ("Explicit", self.root / "explicit.json"),
            )
        )
        self.assertEqual(profile.find_profile(explicit), explicit)
        os.environ[profile.ENV_VAR] = str(env)
        self.assertEqual(profile.find_profile(), env)
        del os.environ[profile.ENV_VAR]
        self.assertEqual(profile.find_profile(), local)
        local.unlink()
        self.assertEqual(profile.find_profile(), user)
        self.assertEqual(profile.active().client_name, "User")

    def test_missing_profile_stops_non_interactive_runs(self):
        with self.assertRaisesRegex(SystemExit, "wizexpert governance setup"):
            profile.ensure(interactive=False)
        with self.assertRaisesRegex(profile.ProfileError, "wizexpert governance setup"):
            profile.active()

    def test_scripted_setup_writes_profile_and_show_reads_it(self):
        logo = self.root / "logo.png"
        Image.new("RGB", (40, 20), "navy").save(logo)
        target = self.root / "acme.json"
        self.assertEqual(
            profile.main(
                [
                    "--client-name",
                    "Acme Bank",
                    "--snapshot-day",
                    "5",
                    "--baseline-month",
                    "2026-01",
                    "--provider-name",
                    "Example Provider",
                    "--baseline-critical",
                    "2",
                    "--baseline-high",
                    "30",
                    "--logo",
                    str(logo),
                    "--output",
                    str(target),
                ]
            ),
            0,
        )
        saved = json.loads(target.read_text(encoding="utf-8"))
        self.assertEqual(saved["file_prefix"], "Acme_Bank")
        self.assertEqual(saved["watermark"], "PROPRIETARY TO EXAMPLE PROVIDER")
        self.assertEqual(saved["baseline_open"], {"CRITICAL": 2, "HIGH": 30})
        self.assertEqual(profile.load(target).logo, logo.resolve())
        self.assertEqual(profile.main(["--show", "--profile", str(target)]), 0)

    def test_scripted_setup_requires_core_answers(self):
        with self.assertRaises(SystemExit):
            profile.main(["--client-name", "Acme Bank"])


class ProfileRulesTests(unittest.TestCase):
    def setUp(self):
        profile.use(make(baseline_open={"CRITICAL": 2, "HIGH": 30}))

    def test_snapshot_day_and_baseline_drive_default_snapshots(self):
        self.assertEqual(
            [label for label, _ in default_snapshots(datetime(2026, 4, 20))],
            ["Jan 5, 2026", "Mar 5, 2026", "Apr 5, 2026"],
        )
        self.assertEqual(parse_snapshots("Feb 26")[0][1], datetime(2026, 2, 5, 23, 59, 59))
        with self.assertRaisesRegex(ValueError, "Acme Bank baseline"):
            default_snapshots(datetime(2025, 12, 20))

    def test_summary_title_and_logo_come_from_profile(self):
        with tempfile.TemporaryDirectory() as folder:
            logo = Path(folder) / "logo.png"
            Image.new("RGB", (200, 100), "navy").save(logo)
            profile.use(make(logo=str(logo)))
            wb = Workbook()
            metrics = {
                "CRITICAL": {
                    "total": [1, 1],
                    "open": [1, 0],
                    "resolved": [0, 1],
                    "ignored": [0, 0],
                    "pct": ["0.0%", "100.0%"],
                }
            }
            build_summary_tab(wb, metrics, parse_snapshots("Jan 26,Feb 26"))
            ws = wb["Summary"]
            self.assertEqual(
                ws["A1"].value, "Acme Bank Cloud Security Governance Report - February 2026"
            )
            self.assertEqual(len(ws._images), 1)
            self.assertEqual((ws._images[0].width, ws._images[0].height), (96, 48))

    def test_baseline_counts_fall_back_to_workbook_baseline_column(self):
        profile.use(make())
        days = [date(2026, 1, 5), date(2026, 2, 5), date(2026, 3, 5)]
        data = WorkbookData(
            {
                day: {"CRITICAL": Snapshot(3, 3 - i, i, 0), "HIGH": Snapshot(9, 9 - i, i, 0)}
                for i, day in enumerate(days)
            },
            (),
            True,
        )
        self.assertEqual(baseline_open(data), {"CRITICAL": 3, "HIGH": 9})
        self.assertEqual(combine_trend(data, {})[days[0]], 12)
        rolled = WorkbookData(
            {day: values for day, values in data.snapshots.items() if day != days[0]}, (), True
        )
        with self.assertRaisesRegex(DashboardError, "wizexpert governance setup"):
            baseline_open(rolled)


if __name__ == "__main__":
    unittest.main()
