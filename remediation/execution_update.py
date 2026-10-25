"""Backward-compatible alias for WizExpert execution updates."""

import sys

from wizexpert import execution_update as implementation

if __name__ == "__main__":
    raise SystemExit(implementation.main())

sys.modules[__name__] = implementation
