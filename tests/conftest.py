"""Shared test setup.

Import the package before any test module imports openpyxl, so openpyxl uses the
defusedxml parser pinned in ``wizexpert/__init__.py`` regardless of test order.
"""

import pytest

import wizexpert  # noqa: F401
from wizexpert.console import vscode_prompts


@pytest.fixture(autouse=True)
def _no_real_vscode_prompts(monkeypatch):
    """Console tests never look at real windows: a VS Code dialog open on a developer's
    Windows machine must not change results. Tests that need prompts inject fakes."""
    monkeypatch.setattr(vscode_prompts, "enumerate_windows", lambda: [])
