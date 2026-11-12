"""Shared test setup.

Import the package before any test module imports openpyxl, so openpyxl uses the
defusedxml parser pinned in ``wizexpert/__init__.py`` regardless of test order.
"""

import datetime

import pytest

import wizexpert  # noqa: F401
from wizexpert.console import imports


@pytest.fixture(autouse=True)
def _weekly_window_today(monkeypatch):
    """Pin 'today' inside the 2026-11-03 weekly report's update window."""
    monkeypatch.setattr(imports, "_today", lambda: datetime.date(2026, 11, 4))
