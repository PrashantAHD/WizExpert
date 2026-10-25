"""Backward-compatible alias for WizExpert issue metadata."""

import sys

from wizexpert import issue_metadata as implementation

sys.modules[__name__] = implementation
