"""Deterministic operational-deck snapshot builder (``wizexpert governance snapshot``).

Builds the schema-version-1 ``*.governance.json`` from reviewed evidence only: the reviewed
CSV (counts via ``cutoff_counts``), complete grouped Wiz responses (``capture_groups``),
the prior snapshot (scope and prior-period block), optional reviewed decisions and the
metrics input. Nothing is collected from Wiz here and no value is defaulted or inferred.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import tempfile
from pathlib import Path

from wizexpert.governance.dashboard_data import DashboardError, require
from wizexpert.governance.governance_data import (
    DISPLAY_SEVERITIES,
    capture_groups,
    cutoff_counts,
    load_snapshot,
    open_top_rules,
    timestamp,
)
from wizexpert.governance.monthly import validate_rows
from wizexpert.governance.wiz_report import load_wiz_csv

METRICS = ("security_score", "hipaa", "hitrust")
COMPUTED = {
    "schema_version",
    "scope",
    "period",
    "prior",
    "open",
    "open_top_rules",
    "in_progress",
    "resolved",
    "accepted",
    "resolved_groups",
    "in_progress_groups",
    *METRICS,
}
_SHA = re.compile(r"[0-9a-f]{64}")


def _read_json(path: Path, label: str) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise DashboardError(f"Cannot read {label} {path}: {error}") from error
    require(isinstance(value, dict), f"{label} must be a JSON object.")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def merge_groups(responses: list[dict], label: str) -> dict:
    """Merge grouped responses by source-rule id; identical repeats collapse, conflicts fail."""
    merged: dict[str, dict] = {}
    for response in responses:
        if "issuesGroupedByValue" not in response and isinstance(response.get("data"), dict):
            response = response["data"]
        for group in capture_groups(response)["groups"]:
            known = merged.get(group["id"])
            require(
                known is None or known == group,
                f"{label}: conflicting duplicate source rule {group['id']} across files.",
            )
            merged[group["id"]] = group
    groups = list(merged.values())
    return {"total_groups": len(groups), "groups": groups}


def validate_metrics(metrics: dict) -> dict:
    """Return the three score metrics with provenance; never zero, never defaulted."""
    out = {}
    for name in METRICS:
        item = metrics.get(name)
        require(isinstance(item, dict), f"metrics.{name} is required (value or unavailable).")
        item = dict(item)
        require(
            isinstance(item.get("source"), str) and item["source"].strip(),
            f"metrics.{name}.source is required.",
        )
        digest = item.get("screenshot_sha256")
        if digest is not None:
            require(
                isinstance(digest, str) and _SHA.fullmatch(digest) is not None,
                f"metrics.{name}.screenshot_sha256 must be a 64-character lowercase sha256.",
            )
        if item.get("value") is None:
            item["value"] = None
            require(
                isinstance(item.get("unavailable_reason"), str)
                and item["unavailable_reason"].strip(),
                f"metrics.{name} needs a value or an unavailable_reason; never zero.",
            )
        else:
            require(
                type(item["value"]) in (int, float) and 0 < item["value"] <= 100,
                f"metrics.{name}.value must be above 0 and at most 100; "
                "use unavailable_reason when Wiz cannot return it.",
            )
            timestamp(item.get("observed_at"), f"metrics.{name}.observed_at")
            if name != "security_score":
                require(
                    isinstance(item.get("framework_version"), str)
                    and item["framework_version"].strip(),
                    f"metrics.{name}.framework_version is required.",
                )
            require(
                "screenshot" not in item["source"].lower() or digest is not None,
                f"metrics.{name} from a screenshot needs screenshot_sha256.",
            )
        out[name] = item
    return out


def build_snapshot(
    *,
    reviewed: list[Path],
    resolved_raw: list[Path],
    in_progress_raw: list[Path],
    prior_snapshot: Path,
    cutoff: str,
    collected_through: str,
    metrics: Path,
    collected_from: str | None = None,
    backlog_as_of: str | None = None,
    decisions: Path | None = None,
) -> dict:
    require(bool(reviewed), "At least one reviewed CSV is required.")
    require(bool(resolved_raw), "At least one grouped RESOLVED response is required.")
    require(bool(in_progress_raw), "At least one grouped IN_PROGRESS response is required.")
    end = timestamp(cutoff, "cutoff")
    if backlog_as_of is not None:
        backlog = timestamp(backlog_as_of, "backlog_as_of")
        require(
            backlog <= end,
            f"backlog_as_of {backlog_as_of} is later than the period end {cutoff}; "
            "changes after the cutoff belong to the next report.",
        )
        require(backlog == end, "backlog_as_of must equal the cutoff (MG-CUT-04).")
    timestamp(collected_through, "collected_through")
    prior = _read_json(prior_snapshot, "prior snapshot")
    prior_period = prior.get("period", {})
    start = timestamp(prior_period.get("end_inclusive"), "prior period.end_inclusive")
    require(start < end, "cutoff must be after the prior snapshot period end.")
    rows, ids = [], set()
    for source in reviewed:
        current = load_wiz_csv(str(source))
        validate_rows(current, source)
        for row in current:
            require(row["Issue ID"] not in ids, f"Duplicate reviewed Issue ID: {row['Issue ID']}.")
            ids.add(row["Issue ID"])
        rows.extend(current)
    counted = cutoff_counts(rows, start.replace(tzinfo=None), end.replace(tzinfo=None))
    prior_metrics = {}
    for name in METRICS:
        old = prior.get(name, {})
        prior_metrics[name] = {
            key: old[key] for key in ("value", "source", "unavailable_reason") if key in old
        }
    payload: dict = {
        "schema_version": 1,
        "scope": prior["scope"],
        "period": {
            "start_exclusive": start.isoformat().replace("+00:00", "Z"),
            "end_inclusive": cutoff,
            "resolved_through": cutoff,
            "backlog_as_of": cutoff,
            "collected_from": collected_from or collected_through,
            "collected_through": collected_through,
        },
        "prior": {
            "date": start.date().isoformat(),
            "source": f"Prior governance snapshot {prior_snapshot.name}",
            "source_sha256": _sha256(prior_snapshot),
            "open": {s: prior["open"][s] for s in DISPLAY_SEVERITIES},
            **prior_metrics,
        },
        "open": counted["open"],
        "open_top_rules": open_top_rules(rows, end.replace(tzinfo=None)),
        "in_progress": counted["in_progress"],
        "resolved": counted["resolved"],
        "accepted": counted["accepted"],
        **validate_metrics(_read_json(metrics, "metrics input")),
        "resolved_groups": merge_groups(
            [_read_json(p, "resolved response") for p in resolved_raw], "resolved_groups"
        ),
        "in_progress_groups": merge_groups(
            [_read_json(p, "in-progress response") for p in in_progress_raw], "in_progress_groups"
        ),
        "limitations": ["Built by wizexpert governance snapshot from reviewed evidence."],
    }
    if decisions is not None:
        extra = _read_json(decisions, "decisions")
        clash = sorted(set(extra) & COMPUTED)
        require(not clash, f"decisions may not override computed fields: {', '.join(clash)}.")
        payload.update(extra)
    return payload


def write_snapshot(payload: dict, output: Path, refresh: bool = False) -> Path:
    """Validate with the deck loader, then publish without overwriting unless refreshing."""
    require(refresh or not output.exists(), f"{output} exists; use --refresh to replace it.")
    with tempfile.TemporaryDirectory(prefix="wizexpert-snapshot-") as folder:
        probe = Path(folder) / "snapshot.json"
        probe.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        load_snapshot(probe)
        output.write_text(probe.read_text(encoding="utf-8"), encoding="utf-8")
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="wizexpert governance snapshot", description=__doc__)
    parser.add_argument("--reviewed", nargs="+", type=Path, required=True, help="Reviewed CSV(s).")
    parser.add_argument(
        "--resolved-raw",
        nargs="+",
        type=Path,
        required=True,
        help="Grouped RESOLVED responses (for example split by severity); merged by rule id.",
    )
    parser.add_argument("--in-progress-raw", nargs="+", type=Path, required=True)
    parser.add_argument("--prior-snapshot", type=Path, required=True)
    parser.add_argument("--cutoff", required=True, help="UTC cutoff, e.g. 2026-11-15T23:59:59Z.")
    parser.add_argument("--collected-through", required=True)
    parser.add_argument("--collected-from")
    parser.add_argument("--backlog-as-of", help="Must equal the cutoff; later is rejected.")
    parser.add_argument("--metrics", type=Path, required=True)
    parser.add_argument("--decisions", type=Path, help="Reviewed decisions JSON to merge.")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args(argv)
    try:
        payload = build_snapshot(
            reviewed=args.reviewed,
            resolved_raw=args.resolved_raw,
            in_progress_raw=args.in_progress_raw,
            prior_snapshot=args.prior_snapshot,
            cutoff=args.cutoff,
            collected_through=args.collected_through,
            metrics=args.metrics,
            collected_from=args.collected_from,
            backlog_as_of=args.backlog_as_of,
            decisions=args.decisions,
        )
        print(f"Created {write_snapshot(payload, args.output, args.refresh)}")
        return 0
    except (DashboardError, OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(1, f"Snapshot build failed: {error}\n")
