"""Preflight collection cost and reconcile retained history with fresh issue evidence."""

from __future__ import annotations

import argparse
import csv
import json
import math
from datetime import UTC, datetime
from pathlib import Path

from wizexpert.governance.dashboard_data import DashboardError, require
from wizexpert.governance.monthly import validate_rows
from wizexpert.governance.monthly_files import check_unchanged, digest
from wizexpert.governance.wiz_report import REQUIRED_COLUMNS, _parse_dt, merge_issue_rows

SEVERITIES = ("CRITICAL", "HIGH", "MEDIUM", "LOW")
ACTIVE = {"OPEN", "IN_PROGRESS"}
FIELDS = [*sorted(REQUIRED_COLUMNS), "Status Changed At"]
COVERAGE = ("new_findings", "closures", "accepted_risk", "historical_closed_changes")


def utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    require(
        parsed.utcoffset() is not None and parsed.utcoffset().total_seconds() == 0,
        "Collection dates must be UTC.",
    )
    return parsed


def check_plan(path: Path) -> dict:
    plan = json.loads(path.read_text(encoding="utf-8"))
    require(plan.get("schema_version") == 1, "Unsupported collection plan version.")
    require(
        plan.get("strategy") in {"reuse_history", "full_refresh"},
        "Choose reuse_history or a justified full_refresh.",
    )
    require(
        utc(plan["previous_collected_at"]) < utc(plan["collected_through"]),
        "Collection must advance the previous actual watermark.",
    )
    require(
        utc(plan["changes_since"]) <= utc(plan["previous_collected_at"]),
        "Changes must cover the previous actual collection, not just the scheduled cutoff.",
    )
    sources = plan.get("approved_sources")
    require(isinstance(sources, dict) and bool(sources), "Approved source hashes are required.")
    for source, expected in sources.items():
        require(
            isinstance(expected, str) and len(expected) == 64 and digest(Path(source)) == expected,
            f"Approved source is missing or changed: {source}",
        )
    partitions = plan.get("partitions")
    require(
        isinstance(partitions, list) and bool(partitions), "Collection partitions are required."
    )
    pages = 0
    roles = set()
    for partition in partitions:
        role = partition.get("role")
        require(
            role in {"active", "new", "closures", "accepted", "changes", "full_history"},
            "Each partition needs a supported collection role.",
        )
        roles.add(role)
        expected, limit = partition["expected_count"], partition["page_size"]
        require(
            type(expected) is int and expected >= 0 and type(limit) is int and limit > 0,
            "Partition counts/page sizes must be nonnegative/positive integers.",
        )
        require(bool(partition.get("query")), "Each partition needs its actual planned query.")
        pages += max(1, math.ceil(expected / limit))
    require(
        plan["strategy"] == "full_refresh" or "full_history" not in roles,
        "Historical inventory pagination cannot be labelled reuse_history.",
    )
    if plan["strategy"] == "full_refresh":
        require(
            bool(str(plan.get("reason", "")).strip())
            and bool(str(plan.get("approved_by", "")).strip()),
            "Full historical refresh needs a reason and report-owner agreement.",
        )
    return {"plan": plan, "estimated_page_requests": pages, "share_ready": False}


def read_rows(paths: list[Path]) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for path in paths:
        with path.open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            require(
                set(reader.fieldnames or []) >= REQUIRED_COLUMNS, f"Invalid CSV headers: {path}"
            )
            rows = list(reader)
        validate_rows(rows, path)
        for row in rows:
            require(row["Severity"] in SEVERITIES, f"Unsupported reporting severity: {path}")
            row = {field: row.get(field, "") or "" for field in FIELDS}
            issue_id = row["Issue ID"] = row["Issue ID"].strip()
            require(
                issue_id not in result or result[issue_id] == row,
                f"Conflicting duplicate Issue ID {issue_id}; reconcile observations first.",
            )
            result[issue_id] = row
    return result


def reconcile_rows(previous: dict, fresh: dict, active: dict, expected: dict) -> tuple[list, dict]:
    require(set(expected) == set(SEVERITIES), "Active counts must cover exactly four severities.")
    for severity in SEVERITIES:
        counts = expected[severity]
        require(
            set(counts) == ACTIVE and all(type(n) is int and n >= 0 for n in counts.values()),
            "Active counts require nonnegative integer OPEN and IN_PROGRESS values.",
        )
        for status in ACTIVE:
            require(
                sum(r["Severity"] == severity and r["Status"] == status for r in active.values())
                == counts[status],
                f"Active census does not reconcile: {severity} {status}.",
            )
    require(
        all(r["Status"] in ACTIVE for r in active.values()), "Active census contains closed rows."
    )
    observations = dict(fresh)
    for issue_id, row in active.items():
        require(
            issue_id not in observations or observations[issue_id] == row,
            f"Active/delta conflict for {issue_id}; recapture, do not choose by file order.",
        )
        observations[issue_id] = row
    require(
        all(r["Status"] not in ACTIVE or i in active for i, r in observations.items()),
        "Fresh active findings are missing from the active census.",
    )
    unexplained = [
        i for i, r in previous.items() if r["Status"] in ACTIVE and i not in observations
    ]
    require(not unexplained, f"Prior active issues disappeared without evidence: {unexplained}")
    changes = []
    for issue_id, row in observations.items():
        prior = previous.get(issue_id)
        if prior is None:
            changes.append({"issue_id": issue_id, "kind": "newly_observed"})
            continue
        require(
            _parse_dt(prior["Created At"]) == _parse_dt(row["Created At"]),
            f"Creation date changed for {issue_id}; review identity/lifecycle evidence.",
        )
        changed = [field for field in FIELDS if prior.get(field, "") != row.get(field, "")]
        if changed:
            kind = "changed"
            if prior["Status"] not in ACTIVE and row["Status"] in ACTIVE:
                kind = "reopened"
            elif prior["Status"] not in ACTIVE and row["Status"] not in ACTIVE:
                kind = "closed_record_changed"
            changes.append(
                {
                    "issue_id": issue_id,
                    "kind": kind,
                    "fields": changed,
                    "before": prior,
                    "after": row,
                }
            )
    merged, retained = merge_issue_rows(list(previous.values()), list(observations.values()))
    return sorted(merged, key=lambda row: row["Issue ID"]), {
        "changes": changes,
        "retained_ids": sorted(r["Issue ID"] for r in retained),
        "fresh_ids": sorted(observations),
        "active_counts": expected,
    }


def reconcile(
    plan_path: Path,
    previous_inputs: list[Path],
    inputs: list[Path],
    active_inputs: list[Path],
    output: Path,
    audit: Path,
) -> dict:
    checked = check_plan(plan_path)
    plan = checked["plan"]
    require(output.resolve() != audit.resolve(), "CSV and audit must be different files.")
    require(not output.exists() and not audit.exists(), "Reconciliation outputs must be new files.")
    require(output.parent.is_dir() and audit.parent.is_dir(), "Output directories must exist.")
    require(not plan.get("unresolved_gaps"), "Collection coverage gaps remain unresolved.")
    evidence = []
    for category in COVERAGE:
        check = plan.get("coverage", {}).get(category, {})
        require(
            check.get("complete") is True and bool(str(check.get("basis", "")).strip()),
            f"Coverage is not established for {category}.",
        )
        source = Path(check["evidence"])
        require(source.is_file(), f"Missing coverage evidence: {source}")
        evidence.append(source)
    require(
        plan.get("active_pagination_complete") is True,
        "Active inventory pagination must be complete.",
    )
    for source in previous_inputs:
        require(
            str(source) in plan["approved_sources"],
            f"Previous issue archive must be bound to the plan: {source}",
        )
    sources = [
        plan_path,
        *previous_inputs,
        *inputs,
        *active_inputs,
        *evidence,
        *(Path(p) for p in plan["approved_sources"]),
    ]
    hashes = {p: digest(p) for p in sources}
    require(all(hashes.values()), "A reconciliation source is missing.")
    previous, fresh, active = (
        read_rows(paths) for paths in (previous_inputs, inputs, active_inputs)
    )
    cutoff = utc(plan["collected_through"]).replace(tzinfo=None)
    require(cutoff <= datetime.now(UTC).replace(tzinfo=None), "Collection cannot be in the future.")
    for row in [*previous.values(), *fresh.values(), *active.values()]:
        require(
            _parse_dt(row["Created At"]) <= cutoff
            and (not row["Resolved Time"] or _parse_dt(row["Resolved Time"]) <= cutoff),
            f"Event after collection cutoff: {row['Issue ID']}",
        )
    rows, result = reconcile_rows(previous, fresh, active, plan["active_counts"])
    result.update(
        {
            "schema_version": 1,
            "status": "reconciled",
            "share_ready": False,
            "collection_plan": str(plan_path),
            "estimated_page_requests": checked["estimated_page_requests"],
            "collected_through": plan["collected_through"],
            "source_sha256": {str(p): h for p, h in hashes.items()},
            "output": str(output),
            "unique_issues": len(rows),
            "coverage_basis": plan["coverage"],
            "limitations": [
                "Coverage declarations require operator review; this command does not query Wiz.",
                "A closed-record change is not proof of a reopen/reclose or technical remediation.",
                "Retained history is not a fresh export; approved snapshots remain unchanged.",
            ],
        }
    )
    check_unchanged(hashes)
    with output.open("x", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    result["output_sha256"] = digest(output)
    with audit.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")
    return result


def verify_reconciliation(path: Path, inputs: list[Path], collected_through: datetime) -> None:
    result = json.loads(path.read_text(encoding="utf-8"))
    require(
        result.get("schema_version") == 1 and result.get("status") == "reconciled",
        "Unsupported or incomplete reconciliation audit.",
    )
    require(
        [p.resolve() for p in inputs] == [Path(result["output"]).resolve()],
        "Verification input must be the reconciled CSV.",
    )
    require(digest(inputs[0]) == result["output_sha256"], "Reconciled CSV changed after QA.")
    require(
        utc(result["collected_through"]) == collected_through,
        "Reconciliation and report observation cutoffs differ.",
    )
    check_unchanged({Path(p): value for p, value in result["source_sha256"].items()})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--plan-only", action="store_true")
    for name in ("previous-input", "input", "active-input"):
        parser.add_argument(f"--{name}", type=Path, nargs="+")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--audit", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.plan_only:
            checked = check_plan(args.plan)
            result = {
                "status": "collection_plan_checked",
                "estimated_page_requests": checked["estimated_page_requests"],
                "share_ready": False,
                "collection_complete": False,
            }
        else:
            require(
                all((args.previous_input, args.input, args.active_input, args.output, args.audit)),
                "Reconciliation requires previous/input/active CSVs, output and audit paths.",
            )
            result = reconcile(
                args.plan,
                args.previous_input,
                args.input,
                args.active_input,
                args.output,
                args.audit,
            )
            result = {k: result[k] for k in ("status", "unique_issues", "output", "share_ready")}
        print(json.dumps(result, indent=2))
    except (DashboardError, OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(1, f"Governance reconciliation failed: {error}\n")
    return 0
