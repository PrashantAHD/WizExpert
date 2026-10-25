#!/usr/bin/env python3
"""wiz_report — Generate a month-on-month governance Excel report from a Wiz CSV export.

Usage (non-interactive):
    wizexpert governance workbook -i issues.csv -o report.xlsx --mode new
    wizexpert governance workbook -i issues.csv -o report.xlsx --mode append
    wizexpert governance workbook -i issues.csv -o report.xlsx --snapshots "Mar 26,Apr 26,May 26"

Usage (interactive):
    wizexpert governance workbook
    wizexpert governance workbook                     # after pip install
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

import questionary
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from questionary import Style as QStyle
from rich.console import Console
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn
from rich.prompt import Prompt
from rich.table import Table
from rich.theme import Theme

from wizexpert.governance.excel_cells import write_literal_cell
from wizexpert.governance.profile import active as active_profile
from wizexpert.governance.profile import add_profile_argument
from wizexpert.governance.profile import ensure as ensure_profile

_q_style = QStyle(
    [
        ("qmark", "fg:#1F4E79 bold"),
        ("question", "bold"),
        ("answer", "fg:#27AE60 bold"),
        ("pointer", "fg:#1F4E79 bold"),
        ("highlighted", "fg:#1F4E79 bold"),
        ("selected", "fg:#27AE60"),
        ("instruction", "fg:#888888"),
    ]
)

_theme = Theme(
    {
        "info": "bold cyan",
        "success": "bold green",
        "warning": "bold yellow",
        "error": "bold red",
        "step": "bold white on #1F4E79",
        "label": "bold bright_white",
        "muted": "dim white",
    }
)
console = Console(theme=_theme, highlight=False)
# Reports are private; relative paths resolve from the working folder, never this checkout.
OUTPUT_ROOT = Path.cwd

# ── Constants ──────────────────────────────────────────────────────────────────

DATE_FORMATS = [
    "%Y-%m-%dT%H:%M:%SZ",
    "%Y-%m-%d %H:%M:%S.%f +0000 UTC",
    "%Y-%m-%d %H:%M:%S +0000 UTC",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d",
]

REQUIRED_COLUMNS = {"Issue ID", "Title", "Severity", "Status", "Created At", "Resolved Time"}

SEVERITY_COLORS = {
    "CRITICAL": "C00000",
    "HIGH": "C55A11",
    "MEDIUM": "7030A0",
    "LOW": "2E75B6",
    "INFO": "595959",
}
SEVERITY_ORDER = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]

# ── Shared style constants ─────────────────────────────────────────────────────


def _thin_border() -> Border:
    s = Side(style="thin", color="BDD7EE")
    return Border(top=s, bottom=s, left=s, right=s)


HDR_DARK = PatternFill("solid", fgColor="1F4E79")
HDR_GREEN = PatternFill("solid", fgColor="375623")
ZEBRA = PatternFill("solid", fgColor="EBF3FB")
CTR_WRAP = Alignment(horizontal="center", vertical="center", wrap_text=True)
CTR = Alignment(horizontal="center", vertical="center")
LEFT_PAD = Alignment(horizontal="left", vertical="center", indent=1)
WHITE_BOLD = Font(name="Calibri", bold=True, size=11, color="FFFFFF")
DARK_BOLD = Font(name="Calibri", bold=True, size=11, color="1F4E79")
REG = Font(name="Calibri", size=11)


def _wc(ws, row: int, col: int, val=None, fill=None, font=None, align=None, border=None):
    """Write a cell with optional formatting."""
    c = write_literal_cell(ws, row, col, val)
    if fill:
        c.fill = fill
    if font:
        c.font = font
    if align:
        c.alignment = align
    if border:
        c.border = border
    return c


# ── Date helpers ───────────────────────────────────────────────────────────────


def _parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    s = s.strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def snapshot_label(dt: datetime) -> str:
    return f"{dt:%b} {dt.day}, {dt.year}"


def default_title(report_month: str) -> str:
    return f"{active_profile().client_name} Cloud Security Governance Report - {report_month}"


def default_snapshots(today: datetime | None = None) -> list[tuple[str, datetime]]:
    """Use the client's fixed baseline and the last two reporting months."""
    today = today or datetime.today()
    profile = active_profile()

    # Previous month (handles year roll-over)
    prev_month = today.month - 1
    prev_year = today.year
    if prev_month == 0:
        prev_month = 12
        prev_year -= 1

    baseline = profile.snapshot(profile.baseline.year, profile.baseline.month)
    previous = profile.snapshot(prev_year, prev_month)
    current = profile.snapshot(today.year, today.month)

    if current < baseline:
        raise ValueError(
            f"Reporting month precedes the {baseline:%B} {baseline.day}, {baseline.year} "
            f"{profile.client_name} baseline."
        )
    snaps = sorted({baseline, current, *([previous] if previous >= baseline else [])})
    return [(snapshot_label(dt), dt) for dt in snaps]


def _resolve_output_path(output_value: str) -> str:
    """Resolve output path to an absolute path.

    Relative paths are anchored to the current working folder so private reports
    are never written into the public source checkout.
    """
    p = Path(output_value)
    if not p.is_absolute():
        p = OUTPUT_ROOT() / p
    return str(p.resolve())


def parse_snapshots(text: str) -> list[tuple[str, datetime]]:
    """Parse 'Mar 26,Apr 26,May 26' into [(label, datetime), ...].
    Labels always include the profile's snapshot day, e.g. 'Mar 15, 2026'.
    """
    profile = active_profile()
    result: list[tuple[str, datetime]] = []
    for token in text.split(","):
        token = token.strip()
        try:
            dt = datetime.strptime(token, "%b %y")
            dt = profile.snapshot(dt.year, dt.month)
            result.append((snapshot_label(dt), dt))
        except ValueError:
            print(f"  Warning: could not parse snapshot date '{token}' — skipped.")
    return result


# ── Metrics ────────────────────────────────────────────────────────────────────


def status_at(row: dict, cutoff: datetime) -> str | None:
    """Issue status at ``cutoff`` (None if created later); later changes belong to the next report.

    Issues closed after the cutoff were OPEN or IN_PROGRESS then; without status history
    they count as OPEN. An IN_PROGRESS issue whose status changed after the cutoff was OPEN.
    """
    created = _parse_dt(row.get("Created At"))
    if created is None or created > cutoff:
        return None
    status = row.get("Status", "").strip().upper()
    closed = _parse_dt(row.get("Resolved Time"))
    if status in ("RESOLVED", "REJECTED") and closed is not None and closed <= cutoff:
        return status
    if status == "IN_PROGRESS":
        changed = _parse_dt(row.get("Status Changed At"))
        return "OPEN" if changed is not None and changed > cutoff else "IN_PROGRESS"
    return "OPEN"


def compute_metrics(
    rows: list[dict],
    snapshots: list[tuple[str, datetime]],
) -> dict:
    """Compute open / resolved / ignored counts and resolution % at each snapshot."""
    out: dict = {
        "labels": [s[0] for s in snapshots],
        "total": [],
        "open": [],
        "resolved": [],
        "ignored": [],
        "pct": [],
    }
    for _, sd in snapshots:
        total = sum(1 for r in rows if (c := _parse_dt(r.get("Created At"))) and c <= sd)
        open_ = sum(
            1
            for r in rows
            if (c := _parse_dt(r.get("Created At")))
            and c <= sd
            and ((rv := _parse_dt(r.get("Resolved Time"))) is None or rv > sd)
        )
        resolved = sum(
            1
            for r in rows
            if r.get("Status", "").strip() == "RESOLVED"
            and (rv := _parse_dt(r.get("Resolved Time")))
            and rv <= sd
        )
        ignored = sum(
            1
            for r in rows
            if r.get("Status", "").strip() == "REJECTED"
            and (rv := _parse_dt(r.get("Resolved Time")))
            and rv <= sd
        )
        ri = resolved + ignored
        out["total"].append(total)
        out["open"].append(open_)
        out["resolved"].append(resolved)
        out["ignored"].append(ignored)
        out["pct"].append(f"{ri / total * 100:.1f}%" if total else "0%")
    return out


def merge_issue_rows(
    historical_rows: list[dict],
    current_rows: list[dict],
) -> tuple[list[dict], list[dict]]:
    """Deduplicate issues by ID, preferring current export data.

    Existing closed issues are retained because Wiz can remove historical
    findings from later exports even though they still belong in the baseline.
    """
    merged: dict[str, dict] = {}
    anonymous_rows: list[dict] = []
    current_ids = {
        str(row.get("Issue ID", "")).strip()
        for row in current_rows
        if str(row.get("Issue ID", "")).strip()
    }

    for row in [*historical_rows, *current_rows]:
        issue_id = str(row.get("Issue ID", "")).strip()
        if issue_id:
            merged[issue_id] = row
        else:
            anonymous_rows.append(row)

    supplemented = [
        row for row in historical_rows if str(row.get("Issue ID", "")).strip() not in current_ids
    ]
    return [*merged.values(), *anonymous_rows], supplemented


def _diff(a, b) -> str:
    """Format the signed change between two values (numeric or pct string)."""
    try:
        fa = float(str(a).rstrip("%"))
        fb = float(str(b).rstrip("%"))
        d = fb - fa
        is_pct = isinstance(a, str) and "%" in a
        s = "+" if d >= 0 else ""
        return f"{s}{d:.1f}%" if is_pct else f"{s}{int(d)}"
    except (ValueError, TypeError):
        return "-"


def read_metrics_from_existing_tab(
    wb: Workbook,
    severity: str,
    n_snapshots: int = 3,
) -> dict | None:
    """Read back metrics from an already-built severity tab in the workbook.
    Used in append mode so severities not in the new CSV still appear in Summary.
    """
    tab_name = f"{severity} Issues"
    if tab_name not in wb.sheetnames:
        return None
    ws = wb[tab_name]

    # Read snapshot labels from row 4, cols 2..(1+n_snapshots)
    labels = []
    for ci in range(2, 2 + n_snapshots):
        raw = str(ws.cell(row=4, column=ci).value or "")
        label = raw.replace("\n(Baseline)", "").replace("\n(Latest)", "").strip()
        labels.append(label)

    # Metric rows 5-9: Total | Open | Resolved | Ignored | Resolution%
    keys = ["total", "open", "resolved", "ignored", "pct"]
    result: dict = {
        "labels": labels,
        "total": [],
        "open": [],
        "resolved": [],
        "ignored": [],
        "pct": [],
    }
    for offset, key in enumerate(keys):
        row_vals = []
        for ci in range(2, 2 + n_snapshots):
            val = ws.cell(row=5 + offset, column=ci).value
            row_vals.append(val if val is not None else ("0%" if key == "pct" else 0))
        result[key] = row_vals
    return result


def read_issue_rows_from_existing_tab(wb: Workbook, severity: str) -> list[dict]:
    """Read the closed-issue detail table from a previously generated tab."""
    tab_name = f"{severity} Issues"
    if tab_name not in wb.sheetnames:
        return []

    ws = wb[tab_name]
    header_row = next(
        (
            row
            for row in range(1, min(ws.max_row, 100) + 1)
            if str(ws.cell(row=row, column=1).value or "").strip() == "Issue ID"
        ),
        None,
    )
    if header_row is None:
        return []

    rows: list[dict] = []
    columns = {
        str(ws.cell(row=header_row, column=c).value or "").strip(): c
        for c in range(1, ws.max_column + 1)
        if ws.cell(row=header_row, column=c).value
    }
    # Column positions are read by header name so workbooks from earlier layouts still load.
    col = {
        name: columns.get(name, default)
        for name, default in (("Title", 2), ("Status", 4), ("Created At", 5), ("Resolved Time", 6))
    }
    for row_index in range(header_row + 1, ws.max_row + 1):
        issue_id = str(ws.cell(row=row_index, column=1).value or "").strip()
        if not issue_id or issue_id.startswith("Total:"):
            break

        status = str(ws.cell(row=row_index, column=col["Status"]).value or "").strip().upper()
        if status == "IGNORED":
            status = "REJECTED"
        rows.append(
            {
                "Issue ID": issue_id,
                "Title": str(ws.cell(row=row_index, column=col["Title"]).value or "").strip(),
                "Severity": severity,
                "Status": status,
                "Created At": str(
                    ws.cell(row=row_index, column=col["Created At"]).value or ""
                ).strip(),
                "Resolved Time": str(
                    ws.cell(row=row_index, column=col["Resolved Time"]).value or ""
                ).strip(),
            }
        )
    return rows


# ── Severity tab ───────────────────────────────────────────────────────────────


def build_severity_tab(
    wb: Workbook,
    severity: str,
    rows: list[dict],
    snapshots: list[tuple[str, datetime]],
    supplemented_rows: list[dict] | None = None,
    snapshot_metrics: dict | None = None,
) -> None:
    tab_name = f"{severity} Issues"
    if tab_name in wb.sheetnames:
        del wb[tab_name]
    ws = wb.create_sheet(tab_name)

    color = SEVERITY_COLORS.get(severity, "595959")
    ws.sheet_properties.tabColor = color
    sev_fill = PatternFill("solid", fgColor=color)
    n = len(snapshots)
    labels = [s[0] for s in snapshots]

    # Column layout (template): Metric | snap×n | vs Baseline | Monthly(last -> current)
    # Keep 7-column visual layout for compatibility with existing workbook design.
    effective_cols = 1 + n + 1 + (1 if n > 1 else 0)
    ncols = max(7, min(effective_cols, 7))

    # ── Title rows ─────────────────────────────────────────────────────────
    ws.merge_cells(f"A1:{get_column_letter(ncols)}1")
    _wc(
        ws,
        1,
        1,
        f"{severity} Severity — Resolution Progress (Month-on-Month)",
        fill=sev_fill,
        font=Font(name="Calibri", bold=True, size=14, color="FFFFFF"),
        align=CTR_WRAP,
    )
    ws.row_dimensions[1].height = 32

    ws.merge_cells(f"A2:{get_column_letter(ncols)}2")
    _wc(
        ws,
        2,
        1,
        f"Exec Summary  |  Severity: {severity}  |  As of {labels[-1]}",
        fill=PatternFill("solid", fgColor="3C3C3C"),
        font=Font(name="Calibri", italic=True, size=10, color="FFFFFF"),
        align=LEFT_PAD,
    )
    ws.row_dimensions[2].height = 18

    # ── Section label row ──────────────────────────────────────────────────
    snap_end = 1 + n  # last snapshot column index
    prog_start = snap_end + 1
    ws.merge_cells(f"A3:{get_column_letter(snap_end)}3")
    _wc(
        ws,
        3,
        1,
        "SNAPSHOT DATA",
        fill=PatternFill("solid", fgColor="2E75B6"),
        font=WHITE_BOLD,
        align=CTR,
    )
    for ci in range(2, snap_end + 1):
        ws.cell(row=3, column=ci).fill = PatternFill("solid", fgColor="2E75B6")
    ws.merge_cells(f"{get_column_letter(prog_start)}3:{get_column_letter(ncols)}3")
    _wc(ws, 3, prog_start, "PROGRESS TRACKING", fill=HDR_GREEN, font=WHITE_BOLD, align=CTR)
    for ci in range(prog_start + 1, ncols + 1):
        ws.cell(row=3, column=ci).fill = HDR_GREEN
    ws.row_dimensions[3].height = 22

    # ── Column headers ─────────────────────────────────────────────────────
    snap_labels = (
        [f"{labels[0]}\n(Baseline)"] + labels[1:-1] + ([f"{labels[-1]}\n(Latest)"] if n > 1 else [])
    )
    progress_headers = [f"vs Baseline\n({labels[0]} → {labels[-1]})"]
    if n > 1:
        progress_headers.append(f"Monthly\n{labels[-2]} → {labels[-1]}")
    progress_headers.append("Monthly Scope\nSummary")

    all_headers = ["Metric"] + snap_labels + progress_headers
    if len(all_headers) < ncols:
        all_headers.extend([""] * (ncols - len(all_headers)))
    else:
        all_headers = all_headers[:ncols]

    for ci, ch in enumerate(all_headers, 1):
        fill = HDR_DARK if ci <= snap_end else HDR_GREEN
        _wc(ws, 4, ci, ch, fill=fill, font=WHITE_BOLD, align=CTR_WRAP, border=_thin_border())
    ws.row_dimensions[4].height = 40

    # ── Metrics rows ───────────────────────────────────────────────────────
    m = snapshot_metrics if snapshot_metrics is not None else compute_metrics(rows, snapshots)
    new_in_month = m["total"][-1] - m["total"][-2] if n > 1 else m["total"][-1]
    start_open = m["open"][-2] if n > 1 else 0
    monthly_scope = start_open + new_in_month
    closed_in_month = monthly_scope - m["open"][-1]
    closure_rate = closed_in_month / monthly_scope * 100 if monthly_scope else 0.0
    metric_defs = [
        (
            "Total Issues Created",
            m["total"],
            PatternFill("solid", fgColor="F2F2F2"),
            f"New in month: {_diff(0, new_in_month)}",
        ),
        (
            "Open / In Progress",
            m["open"],
            PatternFill("solid", fgColor="FCE4D6"),
            f"Scope: {monthly_scope} | Closed: {closed_in_month} | Remaining: {m['open'][-1]}",
        ),
        (
            "Resolved  (Cumulative)",
            m["resolved"],
            None,
            f"Resolved in month: {_diff(m['resolved'][-2], m['resolved'][-1])}" if n > 1 else "",
        ),
        (
            "Ignored / Accepted Risk  (Cumulative)",
            m["ignored"],
            None,
            f"Ignored in month: {_diff(m['ignored'][-2], m['ignored'][-1])}" if n > 1 else "",
        ),
        (
            "Resolution %  (Resolved + Ignored)",
            m["pct"],
            PatternFill("solid", fgColor="FFF2CC"),
            f"Closure rate: {closure_rate:.1f}%",
        ),
    ]

    for ri, (label, vals, row_fill, scope_summary) in enumerate(metric_defs, 5):
        is_pct = "Resolution %" in label
        vs_base = "" if is_pct else _diff(vals[0], vals[-1])
        monthly_latest = "" if is_pct else (_diff(vals[-2], vals[-1]) if n > 1 else "-")
        all_vals = (
            [label] + list(vals) + [vs_base] + ([monthly_latest] if n > 1 else []) + [scope_summary]
        )
        if len(all_vals) < ncols:
            all_vals.extend([""] * (ncols - len(all_vals)))
        else:
            all_vals = all_vals[:ncols]
        for ci, val in enumerate(all_vals, 1):
            ff = row_fill or (ZEBRA if ri % 2 == 0 else None)
            fn = (
                Font(name="Calibri", bold=True, size=11, color="7F6000")
                if is_pct
                else (DARK_BOLD if ci == 1 else REG)
            )
            _wc(
                ws,
                ri,
                ci,
                val,
                fill=ff,
                font=fn,
                align=LEFT_PAD if ci == 1 else CTR,
                border=_thin_border(),
            )
        ws.row_dimensions[ri].height = 20

    # ── Footnote ───────────────────────────────────────────────────────────
    fn_row = 5 + len(metric_defs)
    ws.merge_cells(f"A{fn_row}:{get_column_letter(ncols)}{fn_row}")
    _wc(
        ws,
        fn_row,
        1,
        "* Snapshots taken as of End-of-Day (23:59:59) on each date.",
        font=Font(name="Calibri", italic=True, size=9, color="808080"),
        align=LEFT_PAD,
    )
    ws.row_dimensions[fn_row].height = 16

    kpi_row = fn_row + 1
    cutoff = snapshots[-1][1]
    in_progress_now = min(
        m["open"][-1], sum(1 for r in rows if status_at(r, cutoff) == "IN_PROGRESS")
    )
    ws.merge_cells(f"A{kpi_row}:{get_column_letter(ncols)}{kpi_row}")
    _wc(
        ws,
        kpi_row,
        1,
        f"KPI: Monthly scope = {monthly_scope} | Closed = {closed_in_month}"
        f" | Remaining = {m['open'][-1]} (In progress = {in_progress_now}"
        f" | Open = {m['open'][-1] - in_progress_now})",
        fill=PatternFill("solid", fgColor="E2F0D9"),
        font=Font(name="Calibri", bold=True, size=10, color="375623"),
        align=LEFT_PAD,
    )

    flow_row = fn_row + 2
    ws.merge_cells(f"A{flow_row}:{get_column_letter(ncols)}{flow_row}")
    _wc(
        ws,
        flow_row,
        1,
        f"Monthly flow: Start Open ({labels[-2] if n > 1 else labels[-1]}) {start_open}"
        f" + New {_diff(0, new_in_month)} - Closed {closed_in_month}"
        f" = End Open ({labels[-1]}) {m['open'][-1]}",
        font=Font(name="Calibri", italic=True, size=9, color="595959"),
        align=LEFT_PAD,
    )

    # ── Resolved / ignored issue detail list ──────────────────────────────
    # Only closures on or before the latest snapshot; later ones belong to the next report.
    ri_issues = sorted(
        [r for r in rows if status_at(r, cutoff) in ("RESOLVED", "REJECTED")],
        key=lambda r: _parse_dt(r.get("Resolved Time")) or datetime.max,
    )

    snapshot_day = active_profile().snapshot_day

    def snap_month(dt: datetime | None) -> str:
        """Reporting month that counted the closure: periods end on the snapshot day at EOD."""
        if dt is None:
            return "-"
        baseline = snapshots[0][1]
        if dt <= baseline:
            return f"Baseline ({baseline:%b %Y})"
        if dt.day <= snapshot_day:
            return dt.strftime("%B %Y")
        return (dt.replace(day=1) + timedelta(days=32)).strftime("%B %Y")

    section_row = fn_row + 3
    ws.merge_cells(f"A{section_row}:{get_column_letter(ncols)}{section_row}")
    _wc(
        ws,
        section_row,
        1,
        "Resolved Issues Detail  (Resolved + Ignored)",
        fill=PatternFill("solid", fgColor="3C3C3C"),
        font=Font(name="Calibri", bold=True, size=11, color="FFFFFF"),
        align=LEFT_PAD,
    )
    ws.row_dimensions[section_row].height = 22

    ws.merge_cells(f"A{section_row + 1}:{get_column_letter(ncols)}{section_row + 1}")
    _wc(
        ws,
        section_row + 1,
        1,
        "IGNORED = team has accepted the risk and committed to a fix-by date",
        fill=PatternFill("solid", fgColor="595959"),
        font=Font(name="Calibri", italic=True, size=9, color="FFFFFF"),
        align=LEFT_PAD,
    )
    ws.row_dimensions[section_row + 1].height = 16

    list_hdr_row = section_row + 2
    list_headers = [
        "Issue ID",
        "Title",
        "Severity",
        "Status",
        "Created At",
        "Resolved Time",
        "Snapshot Month",
    ]
    for ci, ch in enumerate(list_headers, 1):
        _wc(
            ws,
            list_hdr_row,
            ci,
            ch,
            fill=HDR_DARK,
            font=WHITE_BOLD,
            align=CTR_WRAP,
            border=_thin_border(),
        )
    ws.row_dimensions[list_hdr_row].height = 28

    status_colors = {"RESOLVED": "375623", "REJECTED": "BF8F00"}
    for ri, r in enumerate(ri_issues, list_hdr_row + 1):
        zfill = ZEBRA if ri % 2 == 0 else None
        status = r.get("Status", "").strip()
        display_status = "IGNORED" if status == "REJECTED" else status
        s_fill = PatternFill("solid", fgColor=status_colors.get(status, "666666"))
        created_dt = _parse_dt(r.get("Created At"))
        resolved_dt = _parse_dt(r.get("Resolved Time"))
        vals = [
            r.get("Issue ID", "").strip(),
            r.get("Title", "").strip(),
            severity,
            display_status,
            created_dt.strftime("%Y-%m-%d") if created_dt else "",
            resolved_dt.strftime("%Y-%m-%d %H:%M") if resolved_dt else "",
            snap_month(resolved_dt),
        ]
        status_col = list_headers.index("Status") + 1
        for ci, val in enumerate(vals, 1):
            ff = s_fill if ci == status_col else zfill
            if ci == 3:
                fn = Font(name="Calibri", bold=True, size=10, color=color)
            elif ci == status_col:
                fn = Font(name="Calibri", bold=True, size=10, color="FFFFFF")
            else:
                fn = Font(name="Calibri", size=10)
            _wc(
                ws,
                ri,
                ci,
                val,
                fill=ff,
                font=fn,
                align=LEFT_PAD if ci in (1, 2) else CTR,
                border=_thin_border(),
            )
        ws.row_dimensions[ri].height = 18

    footer_row = list_hdr_row + 1 + len(ri_issues)
    res_all = sum(1 for r in ri_issues if r.get("Status", "").strip() == "RESOLVED")
    ign_all = len(ri_issues) - res_all
    ws.merge_cells(f"A{footer_row}:{get_column_letter(len(list_headers))}{footer_row}")
    _wc(
        ws,
        footer_row,
        1,
        f"Total: {len(ri_issues)}  |  Resolved: {res_all}  |  Ignored: {ign_all}"
        f"  |  {m['open'][-1]} issue(s) still Open / In-Progress (not listed)",
        fill=HDR_DARK,
        font=Font(name="Calibri", bold=True, size=10, color="FFFFFF"),
        align=LEFT_PAD,
    )
    ws.row_dimensions[footer_row].height = 20

    supplemented_rows = supplemented_rows or []
    if supplemented_rows:
        note_row = footer_row + 2
        ws.merge_cells(f"A{note_row}:{get_column_letter(len(list_headers))}{note_row}")
        _wc(
            ws,
            note_row,
            1,
            f"DATA CONTINUITY: {len(supplemented_rows)} closed issue(s) were retained from the"
            " prior report because they were absent from the latest Wiz export.",
            fill=PatternFill("solid", fgColor="FFF2CC"),
            font=Font(name="Calibri", bold=True, size=10, color="7F6000"),
            align=LEFT_PAD,
        )

    # Columns are shared with the snapshot table above; G (Snapshot Month) also holds the
    # Monthly Scope Summary.
    for ci, w in enumerate([38, 42, 10, 14, 16, 22, 40], 1):
        ws.column_dimensions[get_column_letter(ci)].width = w
    ws.freeze_panes = "A5"


# ── Summary tab ────────────────────────────────────────────────────────────────


def add_logo(ws, anchor: str, height_px: int = 48) -> None:
    """Place the profile's client logo, scaled to the title row height."""
    logo = active_profile().logo
    if logo is None:
        return
    if not logo.is_file():
        console.print(
            f"  [warning]⚠[/warning]  Client logo not found, skipped: [muted]{logo}[/muted]"
        )
        return
    from openpyxl.drawing.image import Image as XLImage

    image = XLImage(str(logo))
    if image.height:
        image.width = round(image.width * height_px / image.height)
        image.height = height_px
    ws.add_image(image, anchor)


def build_summary_tab(
    wb: Workbook,
    severity_metrics: dict[str, dict],
    snapshots: list[tuple[str, datetime]],
    title: str | None = None,
) -> None:
    if "Summary" in wb.sheetnames:
        del wb["Summary"]
    ws = wb.create_sheet("Summary", 0)
    ws.sheet_properties.tabColor = "1F4E79"

    labels = [s[0] for s in snapshots]
    latest = labels[-1]
    baseline = labels[0]
    if not title:
        try:
            report_month = datetime.strptime(latest, "%b %d, %Y").strftime("%B %Y")
        except ValueError:
            report_month = latest
        title = default_title(report_month)

    ws.merge_cells("A1:H1")
    _wc(
        ws,
        1,
        1,
        title,
        fill=HDR_DARK,
        font=Font(name="Calibri", bold=True, size=16, color="FFFFFF"),
        align=CTR_WRAP,
    )
    ws.row_dimensions[1].height = 36
    add_logo(ws, "I1")

    ws.merge_cells("A2:H2")
    _wc(
        ws,
        2,
        1,
        f"Exec Summary  |  Snapshot: {latest}  |  All Severities",
        fill=PatternFill("solid", fgColor="3C3C3C"),
        font=Font(name="Calibri", italic=True, size=10, color="FFFFFF"),
        align=LEFT_PAD,
    )
    ws.row_dimensions[2].height = 18

    ws.merge_cells("A3:F3")
    _wc(
        ws,
        3,
        1,
        f"LATEST SNAPSHOT  ({latest})",
        fill=PatternFill("solid", fgColor="2E75B6"),
        font=WHITE_BOLD,
        align=CTR,
    )
    for ci in range(2, 7):
        ws.cell(row=3, column=ci).fill = PatternFill("solid", fgColor="2E75B6")
    ws.merge_cells("G3:H3")
    _wc(ws, 3, 7, f"PROGRESS vs BASELINE  ({baseline})", fill=HDR_GREEN, font=WHITE_BOLD, align=CTR)
    for ci in range(8, 9):
        ws.cell(row=3, column=ci).fill = HDR_GREEN
    ws.row_dimensions[3].height = 22

    col_headers = [
        "Severity",
        "Total\nIssues",
        "Open /\nIn Progress",
        "Resolved\n(Cumulative)",
        "Ignored /\nAccepted Risk",
        "Resolution %\n(Resolved + Ignored)",
        f"vs Baseline\n(Open backlog {baseline} → {latest})",
        "Trend",
    ]
    for ci, ch in enumerate(col_headers, 1):
        fill = HDR_DARK if ci <= 5 else HDR_GREEN
        _wc(ws, 4, ci, ch, fill=fill, font=WHITE_BOLD, align=CTR_WRAP, border=_thin_border())
    ws.row_dimensions[4].height = 44

    row = 5
    for sev in SEVERITY_ORDER:
        if sev not in severity_metrics:
            continue
        m = severity_metrics[sev]
        color = SEVERITY_COLORS.get(sev, "595959")
        sev_fill = PatternFill("solid", fgColor=color)
        zfill = ZEBRA if row % 2 == 0 else None

        baseline_open = m["open"][0]
        latest_open = m["open"][-1]
        backlog_progress = (
            (baseline_open - latest_open) / baseline_open * 100 if baseline_open else 0.0
        )
        vs_base = f"{'+' if backlog_progress >= 0 else ''}{backlog_progress:.1f}%"
        if latest_open < baseline_open:
            trend = "↓ Open issues declining"
        elif latest_open > baseline_open:
            trend = "↑ Open issues rising"
        else:
            trend = "→ Open issues unchanged"

        vals = [
            sev,
            m["total"][-1],
            m["open"][-1],
            m["resolved"][-1],
            m["ignored"][-1],
            m["pct"][-1],
            vs_base,
            trend,
        ]
        for ci, val in enumerate(vals, 1):
            if ci == 1:
                _wc(
                    ws,
                    row,
                    ci,
                    val,
                    fill=sev_fill,
                    font=Font(name="Calibri", bold=True, size=12, color="FFFFFF"),
                    align=CTR,
                    border=_thin_border(),
                )
            elif ci == 6:
                _wc(
                    ws,
                    row,
                    ci,
                    val,
                    fill=PatternFill("solid", fgColor="FFF2CC"),
                    font=Font(name="Calibri", bold=True, size=12, color="7F6000"),
                    align=CTR,
                    border=_thin_border(),
                )
            elif ci == 7:
                _wc(
                    ws,
                    row,
                    ci,
                    val,
                    fill=HDR_GREEN,
                    font=Font(name="Calibri", bold=True, size=12, color="FFFFFF"),
                    align=CTR,
                    border=_thin_border(),
                )
            elif ci == 3:
                _wc(
                    ws,
                    row,
                    ci,
                    val,
                    fill=PatternFill("solid", fgColor="FCE4D6"),
                    font=Font(name="Calibri", bold=True, size=12, color="C00000"),
                    align=CTR,
                    border=_thin_border(),
                )
            elif ci == 8:
                _wc(
                    ws,
                    row,
                    ci,
                    val,
                    fill=PatternFill("solid", fgColor="E2EFDA"),
                    font=Font(name="Calibri", italic=True, size=10, color="375623"),
                    align=CTR,
                    border=_thin_border(),
                )
            else:
                _wc(
                    ws,
                    row,
                    ci,
                    val,
                    fill=zfill,
                    font=Font(name="Calibri", bold=True, size=12),
                    align=CTR,
                    border=_thin_border(),
                )
        ws.row_dimensions[row].height = 28
        row += 1

    note_row = row + 1
    ws.merge_cells(f"A{note_row}:H{note_row}")
    _wc(
        ws,
        note_row,
        1,
        "* Snapshots taken as of End-of-Day (23:59:59) on each date."
        "  |  See individual severity tabs for month-on-month breakdown.",
        font=Font(name="Calibri", italic=True, size=9, color="808080"),
        align=LEFT_PAD,
    )
    ws.row_dimensions[note_row].height = 16

    for ci, w in enumerate([14, 10, 14, 14, 16, 24, 18, 26], 1):
        ws.column_dimensions[get_column_letter(ci)].width = w
    ws.freeze_panes = "A5"


def build_monthly_scope_tab(
    wb: Workbook,
    severity_metrics: dict[str, dict],
    snapshots: list[tuple[str, datetime]],
    supplemented_by_severity: dict[str, list[dict]] | None = None,
) -> None:
    """Build the management view used for monthly scope and closure reporting."""
    tab_name = "Monthly Scope View"
    if tab_name in wb.sheetnames:
        del wb[tab_name]
    ws = wb.create_sheet(tab_name)
    ws.sheet_properties.tabColor = "375623"

    labels = [snapshot[0] for snapshot in snapshots]
    baseline = labels[0]
    previous = labels[-2] if len(labels) > 1 else labels[-1]
    current = labels[-1]
    try:
        previous_short = datetime.strptime(previous, "%b %d, %Y").strftime("%b %d")
    except ValueError:
        previous_short = previous

    ws.merge_cells("A1:J1")
    _wc(
        ws,
        1,
        1,
        "Monthly Scope and Closure vs Baseline",
        fill=HDR_DARK,
        font=Font(name="Calibri", bold=True, size=16, color="FFFFFF"),
        align=CTR,
    )
    ws.merge_cells("A2:J2")
    _wc(
        ws,
        2,
        1,
        f"Baseline: {baseline}  |  Previous: {previous}  |  Current: {current}",
        fill=PatternFill("solid", fgColor="3C3C3C"),
        font=Font(name="Calibri", italic=True, size=10, color="FFFFFF"),
        align=LEFT_PAD,
    )

    headers = [
        "Severity",
        f"Baseline\nOpen Backlog\n({baseline})",
        f"Total Issues\nCreated till\n{current}",
        f"Backlogs till\n{previous}",
        f"Total Closed till\n{current}\n(Resolved+Ignored)",
        "Net Closure Progress\nSince Baseline %",
        f"Total Open Issues\nDuring \n({previous_short}- {current})",
        "Closed\nin Month",
        f"Current Backlogs till\n({current})",
        "Monthly\nProgress %",
    ]
    for column, header in enumerate(headers, 1):
        _wc(
            ws,
            3,
            column,
            header,
            fill=HDR_DARK,
            font=WHITE_BOLD,
            align=CTR_WRAP,
            border=_thin_border(),
        )
    ws.row_dimensions[3].height = 58

    row_index = 4
    for severity in SEVERITY_ORDER:
        if severity not in severity_metrics:
            continue
        metrics = severity_metrics[severity]
        baseline_open = metrics["open"][0]
        baseline_closed = metrics["resolved"][0] + metrics["ignored"][0]
        latest_total = metrics["total"][-1]
        previous_open = metrics["open"][-2] if len(metrics["open"]) > 1 else 0
        latest_open = metrics["open"][-1]
        latest_closed = metrics["resolved"][-1] + metrics["ignored"][-1]
        new_in_month = (
            metrics["total"][-1] - metrics["total"][-2]
            if len(metrics["total"]) > 1
            else metrics["total"][-1]
        )
        monthly_scope = previous_open + new_in_month
        closed_in_month = monthly_scope - latest_open
        net_closed_since_baseline = latest_closed - baseline_closed
        overall_progress = net_closed_since_baseline / baseline_open * 100 if baseline_open else 0.0
        monthly_progress = closed_in_month / monthly_scope * 100 if monthly_scope else 0.0
        values = [
            severity,
            baseline_open,
            latest_total,
            previous_open,
            latest_closed,
            f"{overall_progress:.1f}%",
            monthly_scope,
            closed_in_month,
            latest_open,
            f"{monthly_progress:.1f}%",
        ]
        color = SEVERITY_COLORS.get(severity, "595959")
        for column, value in enumerate(values, 1):
            fill = (
                PatternFill("solid", fgColor=color)
                if column == 1
                else (ZEBRA if row_index % 2 == 0 else None)
            )
            font = Font(name="Calibri", bold=True, size=11, color="FFFFFF") if column == 1 else REG
            _wc(
                ws, row_index, column, value, fill=fill, font=font, align=CTR, border=_thin_border()
            )
        row_index += 1

    note_row = row_index + 1
    ws.merge_cells(f"A{note_row}:J{note_row}")
    _wc(
        ws,
        note_row,
        1,
        "Net closure progress = (Closed now - Closed at baseline) / baseline Open backlog."
        " Closed = Resolved + Ignored. Cumulative totals retain pre-baseline closures.",
        font=Font(name="Calibri", italic=True, size=9, color="595959"),
        align=Alignment(horizontal="left", vertical="center", wrap_text=True, indent=1),
    )
    ws.row_dimensions[note_row].height = 32

    supplemented_by_severity = supplemented_by_severity or {}
    supplemented_count = sum(len(rows) for rows in supplemented_by_severity.values())
    if supplemented_count:
        continuity_row = note_row + 2
        ws.merge_cells(f"A{continuity_row}:J{continuity_row}")
        _wc(
            ws,
            continuity_row,
            1,
            f"DATA CONTINUITY: {supplemented_count} historical closed issue(s) absent from"
            " the latest Wiz export were retained from the prior report to preserve"
            " baseline and cumulative closure counts.",
            fill=PatternFill("solid", fgColor="FFF2CC"),
            font=Font(name="Calibri", bold=True, size=10, color="7F6000"),
            align=LEFT_PAD,
        )

    for column, width in enumerate([14, 15, 14, 15, 18, 18, 14, 12, 12, 14], 1):
        ws.column_dimensions[get_column_letter(column)].width = width
    ws.freeze_panes = "A4"


# ── Watermark ──────────────────────────────────────────────────────────────────


def apply_watermark(wb: Workbook, org: str = "PROPRIETARY") -> None:
    header = f'&"Calibri,Bold"&10&KA6A6A6CONFIDENTIAL \u2014 {org}'
    footer_l = '&"Calibri,Regular"&9&K808080Confidential \u2014 Proprietary'
    footer_r = '&"Calibri,Regular"&9&K808080Page &P of &N'
    for ws in wb.worksheets:
        ws.oddHeader.center.text = header
        ws.oddFooter.left.text = footer_l
        ws.oddFooter.right.text = footer_r


# ── CSV loading & validation ───────────────────────────────────────────────────


def _configure_csv_field_limit() -> None:
    """Raise CSV field-size limit to handle large Wiz export columns safely."""
    limit = sys.maxsize
    while True:
        try:
            csv.field_size_limit(limit)
            return
        except OverflowError:
            limit //= 10


def load_wiz_csv(path: str) -> list[dict]:
    _configure_csv_field_limit()
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    if not rows:
        print("Error: CSV file is empty.")
        sys.exit(1)
    missing = REQUIRED_COLUMNS - set(rows[0].keys())
    if missing:
        print(f"Error: CSV is missing required columns: {', '.join(sorted(missing))}")
        print(f"  Found columns: {', '.join(rows[0].keys())}")
        sys.exit(1)
    return rows


def _parse_csv_text(text: str) -> list[dict]:
    """Parse raw CSV text (with header row) into validated row dicts."""
    _configure_csv_field_limit()
    reader = csv.DictReader(text.splitlines())
    rows = list(reader)
    if not rows:
        print("Error: CSV text is empty.")
        sys.exit(1)
    missing = REQUIRED_COLUMNS - set(rows[0].keys())
    if missing:
        print(f"Error: CSV is missing required columns: {', '.join(sorted(missing))}")
        print(f"  Found columns: {', '.join(rows[0].keys())}")
        sys.exit(1)
    return rows


# ── Interactive prompts ────────────────────────────────────────────────────────


def _step(n: int, total: int, title: str) -> None:
    console.print(f"\n[step]  Step {n}/{total} — {title}  [/step]")


def _show_confirm_table(
    args: argparse.Namespace,
    rows: list[dict] | None,
    snapshots: list[tuple[str, datetime]] | None,
) -> None:
    t = Table(show_header=False, box=None, padding=(0, 3))
    t.add_column(style="bold dim", no_wrap=True)
    t.add_column(style="bold white")
    t.add_row("Mode", args.mode.upper())
    t.add_row("Output", str(args.output))
    if rows is not None:
        t.add_row("Issues loaded", str(len(rows)))
    if snapshots:
        t.add_row("Snapshots", ", ".join(s[0] for s in snapshots))
    if getattr(args, "remove", None):
        t.add_row("Removing", ", ".join(args.remove))
    console.print(t)


def _prompt_inputs(args: argparse.Namespace):
    """Collect any missing inputs interactively."""
    console.print(
        Panel(
            "[bold white]"
            f"{args.title or active_profile().client_name + ' Cloud Security Governance Report'}"
            "[/bold white]\n"
            "[muted]Generate a month-on-month Excel report from Wiz CSV exports.[/muted]",
            style="bold #1F4E79",
            expand=False,
            padding=(1, 4),
        )
    )

    # ── Step 1: Report Type ───────────────────────────────────────────────────
    _step(1, 4, "Report Type")
    if not args.mode:
        action = questionary.select(
            "What would you like to do?",
            choices=[
                questionary.Choice("Create a new report", value="new"),
                questionary.Choice("Modify an existing report", value="modify"),
            ],
            style=_q_style,
        ).ask()
        if action is None:
            sys.exit(0)

        if action == "modify":
            modify_type = questionary.select(
                "What kind of modification?",
                choices=[
                    questionary.Choice("Add / update severity tabs", value="append"),
                    questionary.Choice("Remove severity tabs", value="remove"),
                ],
                style=_q_style,
            ).ask()
            if modify_type is None:
                sys.exit(0)
            args.mode = modify_type
        else:
            args.mode = "new"

    # Output file
    if args.mode == "new":
        if not args.output or args.output == "report.xlsx":
            default_name = f"{active_profile().file_prefix}_Governance_Report.xlsx"
            out = questionary.text(
                "Output file name:",
                default=default_name,
                style=_q_style,
            ).ask()
            args.output = _resolve_output_path((out or default_name).strip().strip('"'))
    else:
        if not args.output or args.output == "report.xlsx":
            _default_path = str(OUTPUT_ROOT())
            path_choice = questionary.select(
                "Path to existing Excel workbook:",
                choices=[
                    questionary.Choice(
                        title=f"Current path  ({_default_path})",
                        value="default",
                    ),
                    questionary.Choice(
                        title="Custom path",
                        value="custom",
                    ),
                ],
                style=_q_style,
            ).ask()
            if path_choice is None:
                sys.exit(0)
            while True:
                if path_choice == "default":
                    xlsx_files = list(Path(_default_path).glob("*.xlsx"))
                    if xlsx_files:
                        choices = [
                            questionary.Choice(title=f.name, value=str(f)) for f in xlsx_files
                        ]
                        out = questionary.select(
                            "Select workbook:",
                            choices=choices,
                            style=_q_style,
                        ).ask()
                    else:
                        console.print(
                            "  [warning]⚠[/warning]  No .xlsx files found in "
                            f"[muted]{_default_path}[/muted]"
                        )
                        out = None
                else:
                    out = questionary.path(
                        "Enter full path to Excel workbook:",
                        style=_q_style,
                    ).ask()
                if out is None:
                    sys.exit(0)
                out = out.strip().strip('"')
                if out and Path(out).is_file():
                    args.output = _resolve_output_path(out)
                    break
                console.print(
                    f"  [error]✗[/error]  File not found: [muted]{out or '(empty)'}[/muted]"
                )
                path_choice = "custom"

    console.print(
        f"  [success]✔[/success]  {'Output' if args.mode == 'new' else 'File'}: "
        f"[info]{args.output}[/info]"
    )

    # ── Remove mode: pick severities then verify ──────────────────────────────
    if args.mode == "remove":
        _step(2, 3, "Severities to Remove")
        if not args.remove:
            selected = questionary.checkbox(
                "Select severities to remove:",
                choices=SEVERITY_ORDER,
                style=_q_style,
            ).ask()
            if not selected:
                console.print("  [error]✗[/error]  No severities selected.")
                sys.exit(1)
            args.remove = selected
        console.print(f"  [warning]⚠[/warning]  Will remove: [bold]{', '.join(args.remove)}[/bold]")

        _step(3, 3, "Verify & Confirm")
        _show_confirm_table(args, rows=None, snapshots=None)
        if not questionary.confirm("Proceed?", default=True, style=_q_style).ask():
            console.print("  [muted]Cancelled.[/muted]")
            sys.exit(0)
        console.print()
        return args

    # ── Step 2: CSV Data ──────────────────────────────────────────────────────
    _step(2, 4, "Wiz CSV Export")
    collected_rows: list[dict] = []

    def _ask_csv(index: int) -> list[dict]:
        console.print(f"\n  [info]CSV file #{index}[/info]")
        while True:
            source = questionary.select(
                "How would you like to provide the CSV?",
                choices=[
                    questionary.Choice("Provide file path", value="file"),
                    questionary.Choice("Paste CSV data inline", value="paste"),
                ],
                style=_q_style,
            ).ask()
            if source is None:
                sys.exit(0)

            if source == "paste":
                console.print(
                    "\n  [muted]Paste CSV rows below (include the header line). "
                    "Enter a blank line to finish.[/muted]\n"
                )
                lines: list[str] = []
                while True:
                    line = input("  ")
                    if not line:
                        break
                    lines.append(line)
                if not lines:
                    console.print("  [error]✗[/error]  Nothing entered — please try again.")
                    continue
                return _parse_csv_text("\n".join(lines))
            else:
                p = questionary.path(
                    "File path to Wiz CSV export:",
                    style=_q_style,
                ).ask()
                if p is None:
                    sys.exit(0)
                p = p.strip().strip('"')
                if Path(p).is_file():
                    return load_wiz_csv(p)
                console.print(
                    f"  [error]✗[/error]  File not found: [muted]{p or '(empty)'}[/muted]"
                )

    collected_rows.extend(_ask_csv(1))
    csv_count = 1
    while questionary.confirm(
        "Add another CSV file? (e.g. separate export per severity)",
        default=False,
        style=_q_style,
    ).ask():
        csv_count += 1
        collected_rows.extend(_ask_csv(csv_count))

    console.print(f"\n  [success]✔[/success]  [bold]{len(collected_rows)}[/bold] issues loaded.")
    args._pre_loaded_rows = collected_rows  # type: ignore[attr-defined]
    args.input = ["<inline>"]

    # ── Step 3: Snapshot Dates ────────────────────────────────────────────────
    _step(3, 4, "Snapshot Dates")
    if not args.snapshots:
        default_snaps = default_snapshots()
        default_label = ", ".join(s[0] for s in default_snaps)
        snap_choice = questionary.select(
            "Which snapshot dates should be used?",
            choices=[
                questionary.Choice(f"Use default — {default_label}", value="default"),
                questionary.Choice("Enter custom dates", value="custom"),
            ],
            style=_q_style,
        ).ask()
        if snap_choice is None:
            sys.exit(0)

        if snap_choice == "custom":
            console.print(
                "  [muted]Format: 'Mon YY' comma-separated — e.g.  Mar 25, Apr 25, May 25[/muted]"
            )
            raw = questionary.text(
                "Snapshot months:",
                style=_q_style,
            ).ask()
            args.snapshots = (raw or "").strip() if raw else None
        else:
            args.snapshots = None  # main() will call default_snapshots()

    snaps_resolved = parse_snapshots(args.snapshots) if args.snapshots else default_snapshots()
    console.print(
        "  [success]✔[/success]  Snapshots → "
        f"[info]{', '.join(s[0] for s in snaps_resolved)}[/info]"
    )

    # ── Step 4: Verify & Confirm ──────────────────────────────────────────────
    _step(4, 4, "Verify & Confirm")
    _show_confirm_table(args, rows=collected_rows, snapshots=snaps_resolved)
    if not questionary.confirm(
        "Proceed with report generation?", default=True, style=_q_style
    ).ask():
        console.print("  [muted]Cancelled.[/muted]")
        sys.exit(0)

    console.print()
    return args


# ── Entry point ────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="wizexpert governance workbook",
        description="Generate a month-on-month governance Excel report from a Wiz CSV export.",
    )
    parser.add_argument(
        "--input",
        "-i",
        nargs="+",
        default=None,
        metavar="CSV",
        help="One or more Wiz CSV export files (e.g. one per severity).",
    )
    parser.add_argument(
        "--output",
        "-o",
        default="report.xlsx",
        help="Output Excel file path (default: report.xlsx).",
    )
    parser.add_argument(
        "--mode",
        "-m",
        choices=["new", "append", "remove"],
        default=None,
        help="'new' creates a fresh workbook; 'append' updates an existing one; "
        "'remove' deletes severity tab(s) and rebuilds Summary. "
        "Prompted if omitted.",
    )
    parser.add_argument(
        "--remove",
        "-r",
        nargs="+",
        metavar="SEVERITY",
        help="Severities to remove when --mode remove is used "
        "(e.g. --remove MEDIUM  or  --remove MEDIUM LOW).",
    )
    parser.add_argument(
        "--snapshots",
        "-s",
        default=None,
        help="Comma-separated snapshot months, e.g. 'Mar 26,Apr 26,May 26'. "
        "Defaults to the profile's baseline + previous month + current month,"
        " each on the profile's snapshot day.",
    )
    parser.add_argument(
        "--title",
        default=None,
        help="Title shown on the Summary tab. Defaults to the client's report title"
        " using the latest snapshot month.",
    )
    parser.add_argument(
        "--org",
        default=None,
        help="Confidentiality watermark text (default: the profile's watermark).",
    )
    add_profile_argument(parser)
    args = parser.parse_args()
    profile = ensure_profile(args.profile)
    args.org = args.org or profile.watermark

    # Collect missing inputs
    if not args.mode or (args.mode != "remove" and not args.input):
        args = _prompt_inputs(args)
    elif not args.mode:
        if Path(args.output).is_file():
            choice = (
                input(
                    f"'{args.output}' already exists.\n"
                    "  (A) Append / update tabs   (N) Create new file\n"
                    "Choice [A]: "
                )
                .strip()
                .upper()
                or "A"
            )
            args.mode = "append" if choice.startswith("A") else "new"
        else:
            args.mode = "new"

    # Resolve output path consistently so relative names land in repo root.
    args.output = _resolve_output_path(args.output)

    # ── Remove mode ────────────────────────────────────────────────────────────
    if args.mode == "remove":
        if not Path(args.output).is_file():
            print(f"Error: workbook not found: {args.output}")
            sys.exit(1)

        to_remove = [s.strip().upper() for s in (args.remove or [])]
        if not to_remove:
            console.print(
                "[error]Error: no severities specified for removal. "
                "Use --remove or the interactive prompt.[/error]"
            )
            sys.exit(1)

        console.print(f"\n  [info]Loading {args.output} ...[/info]")
        wb = load_workbook(args.output)

        for sev in to_remove:
            tab_name = f"{sev} Issues"
            if tab_name in wb.sheetnames:
                del wb[tab_name]
                console.print(f"  [success]✔[/success]  Removed [bold]'{tab_name}'[/bold].")
            else:
                console.print(
                    f"  [warning]⚠[/warning]  Tab [bold]'{tab_name}'[/bold] not found — skipped."
                )

        severity_metrics: dict[str, dict] = {}
        for sev in SEVERITY_ORDER:
            existing = read_metrics_from_existing_tab(wb, sev)
            if existing:
                severity_metrics[sev] = existing

        if severity_metrics:
            snap_labels = next(iter(severity_metrics.values()))["labels"]
            fake_snapshots = [(lbl, datetime(2000, 1, 1)) for lbl in snap_labels]
            console.print("  [info]Rebuilding Summary and Monthly Scope tabs ...[/info]")
            build_summary_tab(wb, severity_metrics, fake_snapshots, title=args.title)
            build_monthly_scope_tab(wb, severity_metrics, fake_snapshots)
        else:
            if "Summary" in wb.sheetnames:
                del wb["Summary"]
                console.print("  [warning]⚠[/warning]  No severity tabs remain — Summary removed.")
            if "Monthly Scope View" in wb.sheetnames:
                del wb["Monthly Scope View"]
                console.print(
                    "  [warning]⚠[/warning]  No severity tabs remain — Monthly Scope View removed."
                )

        apply_watermark(wb, org=args.org)
        while True:
            try:
                wb.save(args.output)
                console.print(
                    "\n  [success]✔  Report saved →[/success] "
                    f"[bold cyan]{Path(args.output).resolve()}[/bold cyan]\n"
                )
                break
            except PermissionError:
                console.print(
                    f"\n  [error]✗  Cannot save '{args.output}' "
                    "— the file is open in Excel.[/error]"
                )
                Prompt.ask("  Close the file and press Enter to retry")
        return

    # ── New / Append mode ──────────────────────────────────────────────────────

    # Resolve snapshots
    snapshots = parse_snapshots(args.snapshots) if args.snapshots else default_snapshots()
    if not snapshots:
        console.print("[error]Error: no valid snapshot dates.[/error]")
        sys.exit(1)

    # Load CSV(s) — either pre-loaded (inline paste) or from files
    all_rows: list[dict] = []
    pre = getattr(args, "_pre_loaded_rows", None)
    if pre:
        all_rows = pre
        console.print(f"  [success]✔[/success]  [bold]{len(all_rows)}[/bold] issues loaded.")
    else:
        for csv_path in args.input:
            with Progress(
                SpinnerColumn(),
                TextColumn("[info]Loading {task.description}[/info]"),
                console=console,
                transient=True,
            ) as prog:
                prog.add_task(str(csv_path))
            file_rows = load_wiz_csv(csv_path)
            all_rows.extend(file_rows)
            console.print(
                f"  [success]✔[/success]  [bold]{csv_path}[/bold] — {len(file_rows)} issues loaded."
            )
        if len(args.input) > 1:
            console.print(
                f"  [info]Total: {len(all_rows)} issues across {len(args.input)} files.[/info]"
            )

    all_rows, _ = merge_issue_rows([], all_rows)

    # Group by severity
    by_severity: dict[str, list[dict]] = defaultdict(list)
    for r in all_rows:
        sev = r.get("Severity", "").strip().upper()
        if sev:
            by_severity[sev].append(r)

    found = sorted(
        by_severity, key=lambda s: SEVERITY_ORDER.index(s) if s in SEVERITY_ORDER else 99
    )

    # Common Wiz export cap symptom: exactly 5000 rows for a severity.
    cap_hits = [f"{sev}:{len(by_severity[sev])}" for sev in found if len(by_severity[sev]) == 5000]
    if cap_hits:
        console.print(
            "[warning]⚠ Possible export cap detected for severity row count(s): "
            f"{', '.join(cap_hits)}. "
            "If totals look low in Wiz, export by status and merge files.[/warning]"
        )

    summary_table = Table(show_header=False, box=None, padding=(0, 2))
    summary_table.add_column(style="muted")
    summary_table.add_column(style="bold white")
    summary_table.add_row("Severities detected", ", ".join(found) or "—")
    summary_table.add_row("Snapshot dates", ", ".join(s[0] for s in snapshots))
    summary_table.add_row("Mode", args.mode.upper())
    console.print(summary_table)

    # Open or create workbook
    if args.mode == "append" and Path(args.output).is_file():
        wb = load_workbook(args.output)
    else:
        wb = Workbook()
        if "Sheet" in wb.sheetnames:
            del wb["Sheet"]

    severity_metrics: dict[str, dict] = {}
    supplemented_by_severity: dict[str, list[dict]] = {}

    with Progress(
        SpinnerColumn(),
        TextColumn("[info]{task.description}[/info]"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as prog:
        total_tasks = len([s for s in SEVERITY_ORDER if s in by_severity]) + 3
        task = prog.add_task("Initialising ...", total=total_tasks)

        if args.mode == "append" and Path(args.output).is_file():
            for sev in SEVERITY_ORDER:
                if sev not in by_severity:
                    existing = read_metrics_from_existing_tab(wb, sev, len(snapshots))
                    if existing:
                        severity_metrics[sev] = existing
                        prog.console.print(f"  [muted]Preserving existing {sev} tab.[/muted]")

        for sev in SEVERITY_ORDER:
            if sev not in by_severity:
                continue
            current_rows = by_severity[sev]
            historical_rows = (
                read_issue_rows_from_existing_tab(wb, sev)
                if args.mode == "append" and Path(args.output).is_file()
                else []
            )
            rows, supplemented_rows = merge_issue_rows(historical_rows, current_rows)
            supplemented_by_severity[sev] = supplemented_rows
            prog.update(
                task, description=f"Building [bold]{sev}[/bold] tab ({len(rows)} issues) ..."
            )
            if supplemented_rows:
                prog.console.print(
                    f"  [muted]Retaining {len(supplemented_rows)} historical {sev}"
                    " closed issue(s) missing from the latest export.[/muted]"
                )
            build_severity_tab(wb, sev, rows, snapshots, supplemented_rows)
            severity_metrics[sev] = compute_metrics(rows, snapshots)
            prog.advance(task)

        prog.update(task, description="Building Summary tab ...")
        build_summary_tab(wb, severity_metrics, snapshots, title=args.title)
        prog.advance(task)

        prog.update(task, description="Building Monthly Scope View ...")
        build_monthly_scope_tab(
            wb,
            severity_metrics,
            snapshots,
            supplemented_by_severity=supplemented_by_severity,
        )
        prog.advance(task)

        prog.update(task, description="Applying watermark ...")
        apply_watermark(wb, org=args.org)
        prog.advance(task)

    while True:
        try:
            wb.save(args.output)
            console.print(
                "\n  [success]✔  Report saved →[/success] "
                f"[bold cyan]{Path(args.output).resolve()}[/bold cyan]\n"
            )
            break
        except PermissionError:
            console.print(
                f"\n  [error]✗  Cannot save '{args.output}' — the file is open in Excel.[/error]"
            )
            Prompt.ask("  Close the file and press Enter to retry")


if __name__ == "__main__":
    main()
