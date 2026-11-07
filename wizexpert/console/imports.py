"""Read-only scans of existing local deliverable folders for the console.

The console only *lists* what already exists under the workspace's deliverables folder
(Risk Issues cases, Weekly Progress reports, Monthly Governance months) so it can offer View /
Resume / Update / Compare. Nothing here writes, moves or deletes a file; no Wiz, ServiceNow,
cloud or email call is made. Paths are confined to the workspace, symlinks and excluded or
denied locations are skipped, and only names, timestamps and small counts are returned (the
only file contents read are the small ``*.governance.json`` / ``weekly-progress-data.json``
snapshots used for the comparison views).
"""

from __future__ import annotations

import contextlib
import json
import os
import re
from pathlib import Path
from typing import Any

from .config import ConsoleConfig
from .sessions import DELIVERABLE_EXTENSIONS, confine, is_denied

RISK_DIR = "Risk-Issues"
WEEKLY_DIR = "Weekly-Progress-Reporting"
MONTHLY_DIR = "Monthly-Governance-Reporting"
MAX_ITEMS = 100
MAX_JSON_BYTES = 5 * 1024 * 1024
VIEWABLE = frozenset({*DELIVERABLE_EXTENSIONS, ".txt"})
SAFE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}")
ISSUE_TOKEN = re.compile(r"(?i)\b(wc-id)-(\d+(?:-\d+)*)")
MONTHS = {
    m: i + 1
    for i, m in enumerate(
        [
            "january",
            "february",
            "march",
            "april",
            "may",
            "june",
            "july",
            "august",
            "september",
            "october",
            "november",
            "december",
        ]
    )
}


def _base(config: ConsoleConfig, *parts: str) -> Path | None:
    """The (confined, existing) folder deliverables/<parts> or None."""
    workspace = config.resolved_workspace()
    for root in config.output_roots[:1]:
        path = workspace / root
        for part in parts:
            path = path / part
        found = confine(path, workspace)
        if found is not None and found.is_dir() and not found.is_symlink():
            return found
    return None


def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _children(folder: Path, config: ConsoleConfig) -> list[Path]:
    """Direct, non-symlink, non-denied children (names only are ever returned from these)."""
    workspace = config.resolved_workspace()
    out: list[Path] = []
    try:
        entries = sorted(folder.iterdir())
    except OSError:
        return out
    for entry in entries:
        if entry.is_symlink() or entry.name.startswith("."):
            continue
        try:
            if is_denied(entry.relative_to(workspace), config) and entry.is_file():
                continue
        except ValueError:
            continue
        out.append(entry)
    return out


def _rel(path: Path, config: ConsoleConfig) -> str:
    return path.relative_to(config.resolved_workspace()).as_posix()


def _file_entry(path: Path, config: ConsoleConfig) -> dict[str, Any]:
    return {"name": path.name, "path": _rel(path, config), "modified": _mtime(path)}


# -- Risk Issues -------------------------------------------------------------------------------


def issue_ids_from_name(name: str) -> list[str]:
    """Rule/issue IDs from a case folder name such as ``Case-wc-id-12-13`` -> wc-id-12, wc-id-13."""
    found: list[str] = []
    for match in ISSUE_TOKEN.finditer(name):
        for number in match.group(2).split("-"):
            ident = f"{match.group(1).lower()}-{number}"
            if ident not in found:
                found.append(ident)
    return found


def _metadata_ids(folder: Path) -> list[str]:
    """Optional ``*.workflow.json`` / ``case-metadata.json`` ``issue_ids`` (small files only)."""
    candidates = [*sorted(folder.glob("*.workflow.json")), folder / "case-metadata.json"]
    for candidate in candidates:
        data = _load_json(candidate)
        if isinstance(data, dict):
            for key in ("issue_ids", "rule_ids", "issue_id", "rule_id"):
                value = data.get(key)
                if isinstance(value, str):
                    value = [value]
                if isinstance(value, list):
                    ids = [
                        str(v)
                        for v in value
                        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{1,63}", str(v))
                    ]
                    if ids:
                        return ids[:10]
    return []


def _artifacts(folder: Path, config: ConsoleConfig) -> dict[str, Any]:
    """Which artifact kinds exist (by file/folder names; evidence contents are never read)."""
    kinds: dict[str, bool] = {
        "analysis": False,
        "client_assessment": False,
        "stakeholder_email": False,
        "follow_up_email": False,
        "report": False,
        "evidence": False,
        "archives": False,
        "workflow_record": False,
    }
    files: list[dict[str, Any]] = []
    for entry in _children(folder, config):
        low = entry.name.lower()
        if entry.is_dir():
            # Legacy "evidence" or the "<case/rule-id>-evidence" convention (direct child only;
            # symlinks are already excluded by _children).
            if low == "evidence" or re.fullmatch(r"[a-z0-9][a-z0-9._-]*-evidence", low):
                kinds["evidence"] = True
            elif low in ("archive", "archives"):
                kinds["archives"] = True
            continue
        if low.endswith(".workflow.json") or low.startswith("case-gate-plan"):
            kinds["workflow_record"] = True
        if entry.suffix.lower() not in DELIVERABLE_EXTENSIONS:
            continue
        if "analysis" in low:
            kinds["analysis"] = True
        if "client_assessment" in low or "client-assessment" in low:
            kinds["client_assessment"] = True
        if "stakeholder" in low and "email" in low:
            kinds["stakeholder_email"] = True
        if (
            "followup" in low
            or "follow_up" in low
            or "acknowledgement" in low
            or "progress_update" in low
        ) and entry.suffix.lower() in (".html", ".eml", ".msg"):
            kinds["follow_up_email"] = True
        if entry.suffix.lower() == ".xlsx":
            kinds["report"] = True
        if len(files) < 30:
            files.append(_file_entry(entry, config))
    return {"present": [k for k, v in kinds.items() if v], "kinds": kinds, "files": files}


_NEGATION = re.compile(
    r"(?i)\b(no|not|never|without|unsent|none|nor|pending|awaiting|unconfirmed|before|until|"
    r"if|draft|drafts|cannot|unable|n't)\b|n't"
)
_RESUME_PHRASE = re.compile(r"(?i)\bresume (collection|case)\b")
MAX_SUMMARY = 240


def _clauses(text: str) -> list[str]:
    return [
        c.strip()
        for c in re.split(r"(?i)[.;]\s|\s+but\s+|\s+and then\s+|[.;]$", text)
        if c and c.strip()
    ]


_CLIENT_RESPONSE = re.compile(
    r"\b(client|customer)\s+response\b.*\b(received|logged|recorded)\b|"
    r"\b(received|logged|recorded)\b.*\b(client|customer)\s+response\b|"
    r"\bclient\s+response\s*:"
)


def _workflow_status(folder: Path, art: dict[str, Any]) -> dict[str, Any]:
    """Status/milestones from the small ``*.workflow.json`` event text plus artifact presence.

    A milestone is asserted only when a non-negated clause of an event summary says so;
    otherwise neutral labels ("Reports present", "Email draft present") are used. Evidence
    contents are never read and malformed or missing records fall back to a neutral label.
    """
    out: dict[str, Any] = {
        "resumed": False,
        "summary": "",
        "current_status": "",
        "milestones": [],
        "client_response": False,
        "record": "missing",
    }
    labels: list[str] = []
    records = sorted(folder.glob("*.workflow.json"))
    data = _load_json(records[0]) if records else None
    out["manual"] = _manual_milestones(data)
    events = data.get("events") if isinstance(data, dict) else None
    if isinstance(events, list) and all(isinstance(e, dict) for e in events):
        out["record"] = "ok"
        for event in events:
            summary = event.get("summary") if isinstance(event.get("summary"), str) else ""
            stage = event.get("stage")
            if (isinstance(stage, int) and not isinstance(stage, bool) and stage >= 2) or (
                _RESUME_PHRASE.search(summary)
            ):
                out["resumed"] = True
            for clause in _clauses(summary):
                if _NEGATION.search(clause):
                    continue
                low = clause.lower()
                if _CLIENT_RESPONSE.search(low):
                    out["client_response"] = True
                if re.search(r"\bticket\b.*\b(created|opened|raised|logged)\b|"
                             r"\b(created|opened|raised|logged)\b.*\bticket\b", low):
                    labels.append("Ticket created")
                if re.search(r"\bemail\b.*\b(sent|delivered)\b", low):
                    labels.append("Email sent")
                if re.search(r"\b(reports?|workbook|deliverables?)\b.*\b(sent|delivered)\b", low):
                    labels.append("Reports sent")
                elif re.search(
                    r"\b(reports?|workbook|deliverables?)\b.*\b(prepared|generated|updated)\b",
                    low,
                ):
                    labels.append("Reports prepared")
        if events:
            last = events[-1]
            text = last.get("summary") if isinstance(last.get("summary"), str) else ""
            status = last.get("status") if isinstance(last.get("status"), str) else ""
            out["summary"] = " ".join(text.split())[:MAX_SUMMARY]
            out["current_status"] = re.sub(r"[^A-Za-z0-9 _-]", "", status)[:30].replace("_", " ")
    kinds = art["kinds"]
    if "Reports prepared" not in labels and "Reports sent" not in labels and kinds["report"]:
        labels.append("Reports present")
    if "Email sent" not in labels and (kinds["stakeholder_email"] or kinds["follow_up_email"]):
        labels.append("Email draft present")
    if out["record"] != "ok":
        out["summary"] = "Workflow record missing or unreadable; status not available."
    out["milestones"] = list(dict.fromkeys(labels))
    return out


MANUAL_MILESTONES = ("ticket_created", "email_sent", "reports_sent", "follow_up_sent")


def _manual_milestones(data: Any) -> dict[str, bool]:
    """User-confirmed milestones from the workflow record; unchecked when absent/malformed."""
    raw = data.get("manual_milestones") if isinstance(data, dict) else None
    raw = raw if isinstance(raw, dict) else {}
    return {key: raw.get(key) is True for key in MANUAL_MILESTONES}


def set_manual_milestone(
    config: ConsoleConfig, name: Any, milestone: Any, checked: Any
) -> dict[str, bool]:
    """Persist one user-confirmed milestone in the case's existing ``*.workflow.json``.

    Local file edit only: other fields (events, issue ids, ...) are preserved; the write is
    atomic (temp file + replace), UTF-8 without BOM. Raises ValueError for every problem.
    """
    if not isinstance(name, str) or not SAFE_NAME.fullmatch(name):
        raise ValueError("Invalid case folder name.")
    if not isinstance(milestone, str) or milestone not in MANUAL_MILESTONES:
        raise ValueError("Unknown milestone; allowed: " + ", ".join(MANUAL_MILESTONES) + ".")
    if not isinstance(checked, bool):
        raise ValueError("checked must be true or false.")
    if checked is not True:
        raise ValueError("A saved confirmation is one-time and cannot be unticked.")
    base = _base(config, RISK_DIR)
    folder = confine(base / name, config.resolved_workspace()) if base is not None else None
    if folder is None or not folder.is_dir() or folder.is_symlink() or folder.parent != base:
        raise ValueError("No such Risk Issues case folder under the deliverables folder.")
    records = sorted(folder.glob("*.workflow.json"))
    if not records:
        raise ValueError("This case has no workflow record; milestones cannot be saved.")
    record = records[0]
    data = _load_json(record)
    if not isinstance(data, dict):
        raise ValueError("The workflow record is unreadable; milestones cannot be saved.")
    current = data.get("manual_milestones")
    current = dict(current) if isinstance(current, dict) else {}
    if current.get(milestone) is True:
        raise ValueError("This confirmation is already saved and cannot be changed.")
    current[milestone] = True
    data["manual_milestones"] = current
    payload = (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    tmp = record.with_name(record.name + ".tmp")
    try:
        tmp.write_bytes(payload)
        os.replace(tmp, record)
    except OSError as exc:
        with contextlib.suppress(OSError):
            tmp.unlink()
        reason = exc.strerror or "I/O error"
        raise ValueError(f"Could not save the workflow record: {reason}") from None
    return _manual_milestones(data)


def scan_risk_cases(config: ConsoleConfig) -> list[dict[str, Any]]:
    """Existing Risk Issues case folders as dashboard cards (newest first, at most 100)."""
    base = _base(config, RISK_DIR)
    if base is None:
        return []
    cases: list[dict[str, Any]] = []
    for folder in _children(base, config):
        if not folder.is_dir() or not SAFE_NAME.fullmatch(folder.name):
            continue
        art = _artifacts(folder, config)
        ids = _metadata_ids(folder) or issue_ids_from_name(folder.name)
        modified = max([_mtime(folder), *[f["modified"] for f in art["files"]]])
        # "Legacy": created before the rebuilt case workflow, i.e. no workflow record / gate
        # plan and no retained evidence folder to resume from.
        legacy = not art["kinds"]["workflow_record"]
        wf = _workflow_status(folder, art)
        has_evidence = art["kinds"]["evidence"]
        has_deliverables = any(
            art["kinds"][k]
            for k in ("report", "analysis", "client_assessment", "stakeholder_email")
        )
        cases.append(
            {
                "name": folder.name,
                "reference": _rel(folder, config),
                "issue_ids": ids,
                "status": "In-Progress",
                "legacy": legacy,
                "modified": modified,
                "artifacts": art["present"],
                "files": art["files"][:12],
                "can_refresh": has_evidence,
                "can_resume": has_evidence,  # legacy alias of can_refresh
                "can_update": has_deliverables,
                "can_update_deliverables": has_deliverables,
                "resumed": wf["resumed"],
                "milestones": wf["milestones"],
                "manual_milestones": wf["manual"],
                "manual_editable": wf["record"] == "ok",
                "workflow_summary": wf["summary"],
                "client_response": wf["client_response"],
                "workflow_status": wf["current_status"],
            }
        )
    cases.sort(key=lambda c: (-c["modified"], c["name"]))
    return cases[:MAX_ITEMS]


def require_case(config: ConsoleConfig, name: str, mode: str = "refresh") -> dict[str, Any]:
    """The scanned case with this folder name, or ValueError.

    ``mode``: ``refresh`` (repeatable; needs a retained evidence folder, no one-time gate)
    or ``any`` (the case merely has to exist, e.g. for local email drafts).
    """
    for case in scan_risk_cases(config):
        if case["name"] == name:
            if mode == "deliverables" and not case["can_update_deliverables"]:
                raise ValueError("This case has no prepared deliverables to update.")
            if mode in ("refresh", "resume") and not case["can_refresh"]:
                raise ValueError("This case has no retained evidence folder to refresh from.")
            return case
    raise ValueError("No such Risk Issues case folder under the deliverables folder.")


# -- Weekly Progress ---------------------------------------------------------------------------


def _weekly_files(folder: Path, config: ConsoleConfig) -> dict[str, Any]:
    out: dict[str, Any] = {
        "pptx": None,
        "pdf": None,
        "email": None,
        "data": False,
        "template": False,
    }
    for entry in _children(folder, config):
        low = entry.name.lower()
        if entry.is_dir():
            continue
        if low == "weekly-progress-data.json":
            out["data"] = True
        if entry.suffix.lower() not in {".pptx", ".pdf", ".html", ".eml", ".msg"}:
            continue
        if ".template." in low:
            out["template"] = True
        key = {".pptx": "pptx", ".pdf": "pdf"}.get(entry.suffix.lower(), "email")
        if out[key] is None:
            out[key] = _file_entry(entry, config)
    return out


def scan_weekly(config: ConsoleConfig) -> list[dict[str, Any]]:
    """Previous weekly reports (newest report date first); only the first is updatable."""
    base = _base(config, WEEKLY_DIR)
    if base is None:
        return []
    reports: list[dict[str, Any]] = []
    for folder in _children(base, config):
        if not folder.is_dir() or not SAFE_NAME.fullmatch(folder.name):
            continue
        files = _weekly_files(folder, config)
        if not (files["pptx"] or files["pdf"] or files["email"]):
            continue
        reports.append(
            {
                "name": folder.name,
                "reference": _rel(folder, config),
                "modified": max(
                    [
                        _mtime(folder),
                        *[f["modified"] for f in files.values() if isinstance(f, dict)],
                    ]
                ),
                "files": {k: v for k, v in files.items() if isinstance(v, dict)},
                "has_data": files["data"],
                "template_only": files["template"]
                and not any(
                    isinstance(v, dict) and ".template." not in v["name"].lower()
                    for v in files.values()
                ),
            }
        )
    reports.sort(key=lambda r: r["name"], reverse=True)
    reports = reports[:MAX_ITEMS]
    for index, report in enumerate(reports):
        report["latest"] = index == 0
    return reports


def latest_weekly(config: ConsoleConfig) -> dict[str, Any] | None:
    reports = scan_weekly(config)
    return reports[0] if reports else None


def _load_json(path: Path) -> Any:
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_JSON_BYTES:
            return None
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def weekly_diff(config: ConsoleConfig, current: str, previous: str) -> dict[str, Any]:
    """Week-over-week difference between two retained ``weekly-progress-data.json`` files."""
    base = _base(config, WEEKLY_DIR)
    if base is None or not (SAFE_NAME.fullmatch(current) and SAFE_NAME.fullmatch(previous)):
        raise ValueError("Unknown weekly report.")
    data = []
    for name in (current, previous):
        folder = confine(base / name, base)
        loaded = _load_json(folder / "weekly-progress-data.json") if folder else None
        if not isinstance(loaded, dict):
            raise ValueError(f"No retained weekly data for {name}.")
        data.append(loaded)
    now, before = data

    def items(d: dict[str, Any]) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for item in d.get("items") or []:
            if isinstance(item, dict) and item.get("item_id") is not None:
                out[str(item["item_id"])] = item
        return out

    a, b = items(now), items(before)
    changed = []
    for key in sorted(set(a) & set(b)):
        delta = {
            f: {"from": str(b[key].get(f, "")), "to": str(a[key].get(f, ""))}
            for f in ("status", "owner", "state", "severity")
            if str(a[key].get(f, "")) != str(b[key].get(f, ""))
        }
        if delta:
            changed.append(
                {"item_id": key, "title": str(a[key].get("title", ""))[:120], "changes": delta}
            )

    def brief(d: dict[str, Any], key: str) -> dict[str, Any]:
        return {
            "item_id": key,
            "title": str(d[key].get("title", ""))[:120],
            "status": str(d[key].get("status", "")),
        }

    return {
        "current": current,
        "previous": previous,
        "counts": _numeric_diff(now.get("counts"), before.get("counts")),
        "added": [brief(a, k) for k in sorted(set(a) - set(b))][:200],
        "removed": [brief(b, k) for k in sorted(set(b) - set(a))][:200],
        "changed": changed[:200],
    }


def _numeric_diff(now: Any, before: Any, prefix: str = "") -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    now = now if isinstance(now, dict) else {}
    before = before if isinstance(before, dict) else {}
    for key in sorted(set(now) | set(before)):
        a, b = now.get(key), before.get(key)
        label = f"{prefix}{key}"
        if isinstance(a, dict) or isinstance(b, dict):
            rows.extend(_numeric_diff(a, b, label + "."))
        elif isinstance(a, (int, float)) or isinstance(b, (int, float)):
            if isinstance(a, bool) or isinstance(b, bool):
                continue
            av = a if isinstance(a, (int, float)) else None
            bv = b if isinstance(b, (int, float)) else None
            rows.append(
                {
                    "field": label,
                    "current": av,
                    "previous": bv,
                    "delta": (av - bv) if av is not None and bv is not None else None,
                }
            )
    return rows[:300]


# -- Monthly Governance ------------------------------------------------------------------------

_MONTH_NAME = re.compile(r"(?i)\b(" + "|".join(MONTHS) + r")[ _-]?(20\d\d)")
_MONTH_ABBR = re.compile(r"(?i)^(" + "|".join(m[:3] for m in MONTHS) + r")(\d\d)_")
_DATE_DOTTED = re.compile(r"(?<!\d)(\d{1,2})\.(\d{1,2})\.(\d\d)(?!\d)")


def month_of(name: str) -> str:
    """Snapshot month ``YYYY-MM`` from a governance artifact name, or ''."""
    m = _MONTH_NAME.search(name)
    if m:
        return f"{m.group(2)}-{MONTHS[m.group(1).lower()]:02d}"
    m = _MONTH_ABBR.match(name)
    if m:
        number = [x[:3] for x in MONTHS].index(m.group(1).lower()) + 1
        return f"20{m.group(2)}-{number:02d}"
    m = _DATE_DOTTED.search(name)
    if m and 1 <= int(m.group(1)) <= 12:
        return f"20{m.group(3)}-{int(m.group(1)):02d}"
    return ""


def _kind_of(name: str) -> str:
    low = name.lower()
    if low.endswith(".governance.json"):
        return "governance_json"
    if low.endswith(".xlsx") and "governance" in low:
        return "workbook"
    if low.endswith(".pptx") and "dashboard" in low:
        return "dashboard"
    if low.endswith(".pptx"):
        return "deck"
    return ""


def scan_monthly(config: ConsoleConfig) -> list[dict[str, Any]]:
    """Previous governance months (newest first); PRELIMINARY unless a final artifact exists."""
    base = _base(config, MONTHLY_DIR)
    if base is None:
        return []
    months: dict[str, dict[str, Any]] = {}
    for entry in _children(base, config):
        if not entry.is_file():
            continue
        kind = _kind_of(entry.name)
        month = month_of(entry.name)
        if not kind or not month:
            continue
        info = months.setdefault(month, {"month": month, "files": [], "kinds": {}})
        item = {
            **_file_entry(entry, config),
            "kind": kind,
            "preliminary": "preliminary" in entry.name.lower(),
        }
        info["files"].append(item)
    out = []
    for month, info in months.items():
        files = info["files"]
        final = [
            f
            for f in files
            if not f["preliminary"] and f["kind"] in ("workbook", "dashboard", "deck")
        ]
        out.append(
            {
                "month": month,
                "status": "final" if final else "PRELIMINARY",
                "files": sorted(files, key=lambda f: (f["kind"], f["name"])),
                "has_json": any(f["kind"] == "governance_json" for f in files),
                "modified": max(f["modified"] for f in files),
            }
        )
    out.sort(key=lambda m: m["month"], reverse=True)
    return out[:MAX_ITEMS]


def previous_month(month: str) -> str:
    year, number = int(month[:4]), int(month[5:7])
    return f"{year - 1}-12" if number == 1 else f"{year}-{number - 1:02d}"


def _month_json(config: ConsoleConfig, month: str) -> tuple[Any, str]:
    for entry in scan_monthly(config):
        if entry["month"] != month:
            continue
        for f in entry["files"]:
            if f["kind"] == "governance_json":
                path = config.resolved_workspace() / f["path"]
                return _load_json(path), f["name"]
    return None, ""


def compare_months(config: ConsoleConfig, month: str, other: str | None = None) -> dict[str, Any]:
    """Parity of a month against the previous one: artifact presence and snapshot count deltas."""
    if not re.fullmatch(r"20\d\d-(0[1-9]|1[0-2])", month):
        raise ValueError("Month must be YYYY-MM.")
    other = other or previous_month(month)
    if not re.fullmatch(r"20\d\d-(0[1-9]|1[0-2])", other):
        raise ValueError("Month must be YYYY-MM.")
    scanned = {m["month"]: m for m in scan_monthly(config)}
    if month not in scanned:
        raise ValueError(f"No governance artifacts found for {month}.")

    def kinds(m: str) -> set[str]:
        return {f["kind"] for f in scanned.get(m, {}).get("files", [])}

    cur_k, prev_k = kinds(month), kinds(other)
    checks = [
        {
            "check": f"{kind} present in both months",
            "ok": kind in cur_k and kind in prev_k,
            "current": kind in cur_k,
            "previous": kind in prev_k,
        }
        for kind in ("workbook", "dashboard", "governance_json")
    ]
    cur, _ = _month_json(config, month)
    prev, _ = _month_json(config, other)
    sections = ("open", "in_progress", "resolved", "accepted", "security_score", "hipaa", "hitrust")
    rows: list[dict[str, Any]] = []
    if isinstance(cur, dict) and isinstance(prev, dict):
        for key in sections:
            rows.extend(_numeric_diff(cur.get(key), prev.get(key), key + "."))
    return {
        "month": month,
        "previous": other,
        "month_status": scanned[month]["status"],
        "previous_status": scanned.get(other, {}).get("status", "missing"),
        "checks": checks,
        "rows": rows[:300],
        "note": "" if rows else "Snapshot counts need a governance.json for both months.",
    }


# -- View --------------------------------------------------------------------------------------


def resolve_viewable(config: ConsoleConfig, relative: str) -> Path:
    """A deliverable under the output root the user may open (never evidence/archives/secrets)."""
    if (
        not isinstance(relative, str)
        or not relative
        or "\\" in relative
        or ".." in relative.split("/")
    ):
        raise ValueError("Unsupported path.")
    workspace = config.resolved_workspace()
    path = confine(workspace / relative, workspace)
    if path is None or not path.is_file() or (workspace / relative).is_symlink():
        raise ValueError("That file is not available.")
    rel = path.relative_to(workspace)
    root = Path(config.output_roots[0])
    if root not in rel.parents or is_denied(rel, config):
        raise ValueError("That file is not available.")
    if path.suffix.lower() not in VIEWABLE:
        raise ValueError("That file type cannot be opened from the console.")
    return path
