"""Expose the CSV reporting command without a web server."""

from remediation.csv_report import main

if __name__ == "__main__":
    raise SystemExit(main())
