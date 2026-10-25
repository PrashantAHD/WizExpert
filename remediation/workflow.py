"""Backward-compatible alias for WizExpert workflow tracking."""

import sys

from wizexpert import workflow as implementation

if __name__ == "__main__":
    raise SystemExit(implementation.main())

sys.modules[__name__] = implementation
