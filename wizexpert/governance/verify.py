"""Read-only replay gate for the four-severity governance report set."""

from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from contextlib import redirect_stdout
from datetime import UTC, datetime
from pathlib import Path

# Exception type only; untrusted XML is parsed with defusedxml.
from xml.etree.ElementTree import ParseError  # nosec B405
from zipfile import BadZipFile

from defusedxml.common import DefusedXmlException

from wizexpert.governance.assignment_history import write_actions_csv
from wizexpert.governance.dashboard import build_deck
from wizexpert.governance.dashboard_data import DashboardError, read_workbook, require
from wizexpert.governance.governance import render_deck
from wizexpert.governance.governance_data import (
    DISPLAY_SEVERITIES,
    cutoff_counts,
    load_snapshot,
    timestamp,
)
from wizexpert.governance.monthly import build_monthly_workbook, validate_rows
from wizexpert.governance.monthly_files import check_unchanged, digest
from wizexpert.governance.profile import active, ensure, find_profile, load
from wizexpert.governance.wiz_report import load_wiz_csv
from wizexpert.office_qa import package_signature as office_signature

MANUAL_GATES = [
    "Reconcile complete Wiz partitions and unique IDs to retained source counts.",
    "Review lifecycle conflicts, approved exceptions and issue-level carry-forward.",
    "Review metric observation dates, framework versions and any early-final exception.",
    "Confirm this period's team attribution, wording, statuses and deferred rules.",
    "Open Excel without repair and render every slide; check clipping and readability.",
    "Confirm the approved recipients, attachments and release decision before sharing.",
]


def package_signature(path: Path) -> dict[str, bytes]:
    """Compare every package part, excluding only ZIP metadata and core save timestamps."""
    try:
        return office_signature(path)
    except DefusedXmlException:
        raise
    except ValueError as error:
        raise DashboardError(str(error)) from error


def require_matching_package(expected: Path, actual: Path, label: str) -> None:
    first, second = package_signature(expected), package_signature(actual)
    different = sorted(
        name for name in first.keys() | second.keys() if first.get(name) != second.get(name)
    )
    require(
        not different,
        f"{label} differs from its reviewed-input replay: {', '.join(different[:6])}. "
        "Reconcile edits with the input evidence or import team deck edits before regenerating. "
        "No existing report was changed.",
    )


def _slide_paragraphs(path: Path) -> list[str]:
    """Visible paragraph text of every slide (parsed from the package XML; no XML parser)."""
    import html
    import re
    from zipfile import ZipFile

    out: list[str] = []
    with ZipFile(path) as package:
        for name in sorted(
            n for n in package.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)
        ):
            xml = package.read(name).decode("utf-8", "replace")
            for para in re.findall(r"<a:p[ >].*?</a:p>", xml, flags=re.S):
                out.append(html.unescape("".join(re.findall(r"<a:t[^>]*>(.*?)</a:t>", para, re.S))))
    return out


_AS_OF = re.compile(
    r"(?:\bAs of|\bData as of|\bData collected through)\s+"
    r"([A-Z][a-z]{2,8}\.? \d{1,2})(?:st|nd|rd|th)?,? (\d{4})"
)


def check_cutoff(data, *, workbook: Path, decks: dict[str, Path]) -> str:
    """MG-CUT-04: period bounds, workbook date and deck "As of" text all equal the cutoff."""
    period = data.payload["period"]
    if data.preliminary:  # early observation: dated by its actual, labelled coverage
        cutoff = data.backlog_as_of
    else:
        cutoff = data.end
        require(
            period.get("backlog_as_of") is not None,
            "MG-CUT-04: period.backlog_as_of must be set to the cutoff.",
        )
        for field in ("end_inclusive", "backlog_as_of", "resolved_through"):
            require(
                timestamp(period[field], field) == cutoff,
                f"MG-CUT-04: period.{field} differs from the cutoff {cutoff:%Y-%m-%d}.",
            )
    require(
        read_workbook(workbook, allow_preliminary=data.preliminary).latest == cutoff.date(),
        f"MG-CUT-04: workbook latest snapshot date differs from the cutoff {cutoff:%Y-%m-%d}.",
    )
    for label, path in decks.items():
        found = 0
        for text in _slide_paragraphs(path):
            for match in _AS_OF.finditer(text):
                found += 1
                day = f"{match.group(1).rstrip('.')} {match.group(2)}"
                shown = None
                for fmt in ("%B %d %Y", "%b %d %Y"):
                    try:
                        shown = datetime.strptime(day, fmt).date()
                        break
                    except ValueError:
                        continue
                require(
                    shown == cutoff.date(),
                    f"MG-CUT-04: {label} says 'As of {day}', not the cutoff "
                    f"{cutoff:%Y-%m-%d}; an evidence watermark is not the report date.",
                )
        require(
            found > 0 or label != "Operational deck",
            f"MG-CUT-04: {label} has no 'As of' date to check.",
        )
    return cutoff.date().isoformat()


def verify_preparation(
    *,
    inputs: list[Path],
    previous_report: Path,
    workbook: Path,
    executive_template: Path,
    executive: Path,
    snapshot: Path,
    operational_template: Path,
    operational: Path,
    history: Path | None = None,
    actions_csv: Path | None = None,
    font_dir: Path | None = None,
    profile_path: Path | None = None,
    reconciliation: Path | None = None,
    collection_gate: Path | None = None,
) -> dict:
    from wizexpert.workflow_qa import ROOT, rule_hashes

    implementation = {
        ROOT.joinpath(*name.split("/")): value for name, value in rule_hashes("governance").items()
    }
    companion = operational.with_suffix(".governance.json")
    sources = [
        *inputs,
        previous_report,
        workbook,
        executive_template,
        executive,
        snapshot,
        operational_template,
        operational,
        companion,
        *([history] if history else []),
        *([actions_csv] if actions_csv else []),
        *([profile_path] if profile_path else []),
        *([reconciliation] if reconciliation else []),
        *([collection_gate] if collection_gate else []),
    ]
    require(bool(inputs), "At least one complete, reviewed current CSV is required.")
    hashes = {}
    for path in sources:
        value = digest(path)
        if value is None:
            raise DashboardError(
                f"Required source, output or operational companion not found: {path}"
            )
        hashes[path] = value
    profile = active()
    if profile_path is not None:
        require(
            load(profile_path).to_json() == profile.to_json(),
            "The active profile differs from the hashed preparation profile.",
        )
    data = load_snapshot(snapshot)
    require(
        data.payload.get("collection_strategy") != "reuse_history" or reconciliation is not None,
        "History-reuse preparation requires its reconciliation audit.",
    )
    if reconciliation is not None:
        from wizexpert.governance.reconcile import verify_reconciliation

        verify_reconciliation(reconciliation, inputs, data.backlog_as_of)
    if data.payload.get("collection_strategy") == "reuse_history":
        require(
            collection_gate is not None,
            "History-reuse preparation requires its collection gate receipt.",
        )
    if collection_gate is not None:
        from wizexpert.governance.collection_gate import require_ready_receipt

        require_ready_receipt(collection_gate, reconciliation, data.backlog_as_of)
    require(
        data.end.day == profile.snapshot_day and data.end.strftime("%H:%M:%S") == "23:59:59",
        "Snapshot period end must use the configured UTC snapshot-day EOD.",
    )
    require(
        data.start.day == profile.snapshot_day
        and data.start.strftime("%H:%M:%S") == "23:59:59"
        and data.end.year * 12 + data.end.month - data.start.year * 12 - data.start.month == 1,
        "The reporting interval must run between consecutive monthly UTC cutoffs.",
    )
    require(
        read_workbook(previous_report).latest == data.start.date(),
        "The approved workbook must be from the immediately preceding snapshot.",
    )
    require(
        hashes[companion] == hashes[snapshot],
        "Operational companion differs from the reviewed snapshot.",
    )
    rows, ids = [], set()
    check_cutoff(
        data,
        workbook=workbook,
        decks={"Executive dashboard": executive, "Operational deck": operational},
    )
    for source in inputs:
        current = load_wiz_csv(str(source))
        validate_rows(current, source)
        for row in current:
            require(
                row["Severity"] in DISPLAY_SEVERITIES,
                "This report-set workflow tracks Critical, High, Medium and Low only; "
                "remove informational findings from the reviewed scope.",
            )
            require(
                row["Issue ID"] not in ids,
                f"Duplicate current Issue ID: {row['Issue ID']}. Reconcile partitions explicitly.",
            )
            ids.add(row["Issue ID"])
        rows.extend(current)
    counted = cutoff_counts(
        rows, data.start.replace(tzinfo=None), data.backlog_as_of.replace(tzinfo=None)
    )
    require(
        data.resolved_through == data.backlog_as_of,
        "Workbook and operational counts must use the same actual coverage cutoff.",
    )
    for category, values in counted.items():
        expected = {
            severity: data.payload.get(category, {}).get(severity, 0)
            for severity in DISPLAY_SEVERITIES
        }
        require(
            values == expected,
            f"Current CSV and operational snapshot disagree on {category}: "
            f"CSV={values}, snapshot={expected}. Do not substitute either prior comparison source.",
        )
    gaps = data.payload.get("assignment_gaps", [])
    require(not gaps or actions_csv is not None, "Missing-assignee actions CSV is required.")
    month = data.end.replace(day=1, hour=0, minute=0, second=0, microsecond=0, tzinfo=None)
    with tempfile.TemporaryDirectory(prefix="wizexpert-governance-verify-") as folder:
        stage = Path(folder)
        expected_book = stage / "expected.xlsx"
        build_monthly_workbook(
            inputs,
            [previous_report],
            expected_book,
            month,
            profile.watermark,
            collected_at=data.backlog_as_of if data.preliminary else None,
        )
        require_matching_package(expected_book, workbook, "Workbook")
        expected_executive = stage / "executive.pptx"
        build_deck(
            workbook,
            executive_template,
            expected_executive,
            history,
            font_dir,
            allow_preliminary=data.preliminary,
        )
        require_matching_package(expected_executive, executive, "Executive dashboard")
        expected_operational = stage / "operational.pptx"
        render_deck(data, operational_template, expected_operational, hashes[snapshot])
        require_matching_package(expected_operational, operational, "Operational deck")
        if actions_csv is not None:
            expected_actions = stage / "actions.csv"
            write_actions_csv(gaps, expected_actions)
            require(
                expected_actions.read_bytes() == actions_csv.read_bytes(),
                "Missing-assignee actions do not match the reviewed snapshot.",
            )
    check_unchanged(hashes)
    check_unchanged(implementation)
    return {
        "status": "automated_checks_passed",
        "share_ready": False,
        "verified_at": datetime.now(UTC).isoformat(),
        "profile": profile.to_json(),
        "period": data.payload["period"],
        "current_unique_issues": len(ids),
        "counts": counted,
        "source_and_output_sha256": {str(path): value for path, value in hashes.items()},
        "implementation_sha256": {str(path): value for path, value in implementation.items()},
        "early_final_exception": data.payload["period"].get("final_approval"),
        "manual_gates_required": MANUAL_GATES,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", nargs="+", type=Path, required=True, dest="inputs")
    for name in (
        "previous-report",
        "workbook",
        "executive-template",
        "executive",
        "snapshot",
        "operational-template",
        "operational",
    ):
        parser.add_argument(f"--{name}", type=Path, required=True)
    for name in (
        "history",
        "actions-csv",
        "font-dir",
        "profile",
        "reconciliation",
        "collection-gate",
    ):
        parser.add_argument(f"--{name}", type=Path)
    args = vars(parser.parse_args(argv))
    explicit_profile = args.pop("profile")
    args["profile_path"] = find_profile(explicit_profile)
    ensure(args["profile_path"], interactive=False)
    try:
        with redirect_stdout(sys.stderr):
            result = verify_preparation(**args)
    except (
        DashboardError,
        OSError,
        ValueError,
        BadZipFile,
        ParseError,
        DefusedXmlException,
    ) as error:
        parser.exit(1, f"Governance verification failed: {error}\n")
    print(json.dumps(result, indent=2))
    return 0
