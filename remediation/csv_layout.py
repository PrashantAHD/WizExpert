"""Backward-compatible alias for WizExpert workbook layouts."""

import sys

from wizexpert import csv_layout as implementation

sys.modules[__name__] = implementation
