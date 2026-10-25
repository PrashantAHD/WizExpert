"""Backward-compatible module entry point for WizExpert."""

import sys

from wizexpert import __main__ as implementation

if __name__ == "__main__":
    raise SystemExit(implementation.main())

sys.modules[__name__] = implementation
