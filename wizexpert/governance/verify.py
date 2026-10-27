"""Read-only replay gate for the four-severity governance report set."""

from __future__ import annotations

import argparse
import json
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
from wizexpert.governance.governance_data import DISPLAY_SEVERITIES, cutoff_counts, load_snapshot
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
    workflow_review: Path | None = None,
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
        *([workflow_review] if workflow_review else []),
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
    workflow_result = None
    if workflow_review is not None:
        from wizexpert.workflow_qa import require_generation_review

        workflow_result = require_generation_review(
            workflow_review,
            [
                *inputs,
                previous_report,
                executive_template,
                operational_template,
                snapshot,
                *([profile_path] if profile_path else []),
            ],
        )
    require(
        data.payload.get("collection_strategy") != "reuse_history" or reconciliation is not None,
        "History-reuse preparation requires its reconciliation audit.",
    )
    if reconciliation is not None:
        from wizexpert.governance.reconcile import verify_reconciliation

        verify_reconciliation(reconciliation, inputs, data.backlog_as_of)
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
        "workflow_qa": workflow_result,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workflow-review", type=Path, required=True)
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
    for name in ("history", "actions-csv", "font-dir", "profile", "reconciliation"):
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
