"""Shared test setup.

Import the package before any test module imports openpyxl, so openpyxl uses the
defusedxml parser pinned in ``wizexpert/__init__.py`` regardless of test order.
"""

import wizexpert  # noqa: F401
