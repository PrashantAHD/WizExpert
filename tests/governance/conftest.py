"""Run every test with a neutral, fully specified client profile."""

import pytest

from wizexpert.governance import profile

TEST_PROFILE = profile.from_json(
    {
        "schema_version": 1,
        "client_name": "Example Health",
        "file_prefix": "ExampleHealth",
        "baseline_month": "2026-03",
        "snapshot_day": 15,
        "provider_name": "Example Provider",
        "watermark": "PROPRIETARY TO EXAMPLE PROVIDER",
        "baseline_open": {"CRITICAL": 6, "HIGH": 96},
    }
)
profile.use(TEST_PROFILE)  # some test modules build snapshots at import time


@pytest.fixture(autouse=True)
def client_profile():
    profile.use(TEST_PROFILE)
    yield TEST_PROFILE
    profile.use(TEST_PROFILE)
