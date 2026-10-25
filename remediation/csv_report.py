"""Backward-compatible alias for WizExpert CSV reporting."""

import sys

from wizexpert import csv_report as implementation

if __name__ == "__main__":
    raise SystemExit(implementation.main())

sys.modules[__name__] = implementation
