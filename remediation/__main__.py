"""Expose the CSV reporting command without a web server."""

import sys
from collections.abc import Sequence

from remediation.csv_report import main as report_main


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments and arguments[0] == "update-remediation":
        from remediation.execution_update import main as update_main

        return update_main(arguments[1:])
    return report_main(arguments)

if __name__ == "__main__":
    raise SystemExit(main())
