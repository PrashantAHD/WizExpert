"""Current-period collection gate for read-only governance collection."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path

from wizexpert.governance.dashboard_data import DashboardError, require
from wizexpert.governance.monthly_files import digest
from wizexpert.governance.reconcile import (
    require_current_delta,
    retained_watermark,
    utc,
    verify_reconciliation,
)

BLOCKED, READY = "blocked", "ready"
ERRORS = (DashboardError, OSError, ValueError, KeyError, TypeError)


def _hashes(folder: Path) -> dict[str, str]:
    return {str(path): digest(path) for path in sorted(folder.rglob("*")) if path.is_file()}


def _fingerprint(path: Path):
    return _hashes(path) if path.is_dir() else digest(path)


def _outside(path: Path, folder: Path) -> bool:
    resolved, root = path.resolve(), folder.resolve()
    return resolved != root and root not in resolved.parents


def _load(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(data, dict), f"Not a JSON object: {path}")
    return data


def _write(receipt: Path, evidence_dir: Path, data: dict) -> None:
    require(_outside(receipt, evidence_dir), "Gate receipt must be outside retained evidence.")
    receipt.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


GOVERNANCE_CATEGORY, PLAN_GATE = "monthly-governance-reporting", "collection-plan"


def default_console_runs() -> Path:
    home = os.environ.get("WIZEXPERT_CONSOLE_HOME") or Path.home() / ".wizexpert-console"
    return Path(home) / "runs.json"


def bind_console_approval(plan_path: Path, cutoff: str, runs_path: Path | None = None) -> bool:
    """Fill a drafted delta plan's empty approval from the console's collection-plan approval.

    Binds only an unapproved plan that already lists its own sources and partitions (nothing is
    invented), and only from the latest manual, approved ``collection-plan`` gate of a monthly
    governance run for the cutoff's month. Returns True when the plan was updated.
    """
    runs_path = runs_path or default_console_runs()
    if not plan_path.is_file() or not runs_path.is_file():
        return False
    plan = _load(plan_path)
    if str(plan.get("approved_by", "")).strip() or str(plan.get("approved_at", "")).strip():
        return False
    if not plan.get("approved_sources") or not plan.get("partitions"):
        return False
    try:
        retained = utc(plan["retained_watermark"]).timestamp()
    except (DashboardError, KeyError, TypeError, ValueError):
        return False
    try:
        runs = json.loads(runs_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    runs = runs.get("runs") if isinstance(runs, dict) else runs
    month = utc(cutoff).strftime("%Y-%m")
    found = None
    for run in runs if isinstance(runs, list) else []:
        if not isinstance(run, dict) or run.get("category_id") != GOVERNANCE_CATEGORY:
            continue
        if run.get("parent") or (run.get("values") or {}).get("month") != month:
            continue
        gate = next((g for g in run.get("gates") or [] if g.get("id") == PLAN_GATE), None)
        decided = [
            d
            for d in run.get("decisions") or []
            if d.get("gate") == PLAN_GATE and d.get("decision") == "approve" and not d.get("auto")
        ]
        if gate and gate.get("state") == "approved" and decided:
            try:
                at = float(decided[-1]["at"])
            except (TypeError, ValueError):
                continue
            if at <= retained:
                continue
            if found is None or at > found[1]:
                found = (run.get("id"), at)
    if not found or not found[0]:
        return False
    stamp = datetime.fromtimestamp(found[1], UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    plan["approved_by"] = f"user (console approval; run {found[0]})"
    plan["approved_at"] = stamp
    plan_path.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
    return True


def plan_step(
    evidence_dir: Path,
    cutoff: str,
    plan_path: Path,
    receipt: Path,
    console_runs: Path | None = None,
) -> dict:
    """Derive or require the delta plan and leave collection blocked until it runs."""
    baseline = _hashes(evidence_dir)
    data = {
        "schema_version": 1,
        "cutoff": cutoff,
        "retained_sha256": baseline,
        "generation_allowed": False,
        "blockers": [],
    }
    if receipt.is_file():
        old = _load(receipt).get("retained_sha256")
        if isinstance(old, dict):
            data["retained_sha256"] = old
            if old != baseline:
                data["blockers"].append("Retained evidence changed since it was baselined.")
    try:
        if retained_watermark(evidence_dir) < utc(cutoff):
            bind_console_approval(plan_path, cutoff, console_runs)
        info = require_current_delta(evidence_dir, cutoff, plan_path)
    except ERRORS as error:
        data["blockers"].append(str(error))
        data["mode"] = "delta_collection"
    else:
        if info["status"] == "retained_evidence_current":
            data["mode"] = "retained_current"
        else:
            data["mode"] = "delta_collection"
            data["blockers"].append(
                "Delta plan approved: execute its read-only Wiz partitions, then run "
                "'governance collect check' on the fresh outputs."
            )
    ready = data["mode"] == "retained_current" and not data["blockers"]
    data["status"] = READY if ready else BLOCKED
    data["generation_allowed"] = ready
    _write(receipt, evidence_dir, data)
    return data


def partition_id(partition: dict) -> str:
    """Stable identity of a planned partition: its exact planned query."""
    query = json.dumps(partition.get("query"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(query.encode("utf-8")).hexdigest()


def partition_coverage_blockers(plan: dict, manifest: dict) -> list[str]:
    """Match each planned partition to exactly one manifest count by role + query identity.

    A manifest count names its partition with ``role`` (or ``name``) and ``query_sha256``
    (see ``partition_id``). A role planned once may be matched by role alone; a role planned
    several times requires the query identity so duplicate roles never collide. Count
    mismatches and incomplete pagination remain blocking.
    """
    blockers: list[str] = []
    entries = [i for i in manifest.get("counts", []) if isinstance(i, dict)]
    planned = plan["partitions"]
    per_role: dict[str, int] = {}
    for partition in planned:
        per_role[partition["role"]] = per_role.get(partition["role"], 0) + 1
    claimed: set[int] = set()
    for partition in planned:
        role, pid = partition["role"], partition_id(partition)
        label = f"{role} [{pid[:12]}]"
        matches = [
            n
            for n, item in enumerate(entries)
            if item.get("role", item.get("name")) == role
            and (
                item.get("query_sha256") == pid
                or (item.get("query_sha256") is None and per_role[role] == 1)
            )
        ]
        if len(matches) != 1 or matches[0] in claimed:
            blockers.append(f"Manifest does not uniquely cover planned partition {label}.")
            continue
        claimed.add(matches[0])
        item = entries[matches[0]]
        if item.get("expected") != partition["expected_count"]:
            blockers.append(
                f"Count drift for {label}: manifest expected {item.get('expected')!r}, plan "
                f"expects {partition['expected_count']}; re-plan and re-approve."
            )
        collected = item.get("collected")
        if type(collected) is not int or collected != partition["expected_count"]:
            blockers.append(
                f"Collected count drift for {label}: collected {collected!r}, planned "
                f"{partition['expected_count']}; re-plan and re-approve."
            )
        if item.get("pagination_complete") is not True:
            blockers.append(f"Pagination incomplete or unconfirmed for {label}.")
    for n, item in enumerate(entries):
        if n not in claimed:
            name = item.get("role", item.get("name"))
            blockers.append(f"Manifest count {name!r} is not covered by any planned partition.")
    return blockers


def check_step(
    evidence_dir: Path,
    cutoff: str,
    plan_path: Path,
    receipt: Path,
    activity_log: Path | None,
    manifest: Path | None,
    raw_evidence: Path | None,
    audit: Path | None,
    console_runs: Path | None = None,
) -> dict:
    """Verify fresh collection outputs; ready only when every local check passes."""
    from wizexpert.workflow_qa import collection_check
    from wizexpert.workflow_qa import load as load_manifest

    blockers: list[str] = []
    prior = _load(receipt) if receipt.is_file() else {}
    if "retained_sha256" not in prior:
        blockers.append("Run 'governance collect plan' first to baseline retained evidence.")
    elif prior["retained_sha256"] != _hashes(evidence_dir):
        blockers.append("Retained evidence changed; archive it and restart collection.")
    elif prior.get("cutoff") != cutoff:
        blockers.append("Receipt cutoff differs from the requested cutoff; rerun the plan step.")
    outputs: dict = {}
    mode = "delta_collection"
    try:
        target = utc(cutoff)
        watermark = retained_watermark(evidence_dir)
        if watermark >= target:
            mode = "retained_current"
        elif not plan_path.is_file():
            blockers.append(f"Delta plan missing: {plan_path}. Run 'governance collect plan'.")
        else:
            bind_console_approval(plan_path, cutoff, console_runs)
            require_current_delta(evidence_dir, cutoff, plan_path)
            plan = _load(plan_path)
            fresh = {
                "activity_log": activity_log,
                "manifest": manifest,
                "raw_evidence": raw_evidence,
                "audit": audit,
            }
            for label, path in fresh.items():
                if path is None or not path.exists():
                    blockers.append(f"Missing fresh {label}.")
                elif not _outside(path, evidence_dir):
                    blockers.append(f"Fresh {label} must be a new file outside retained evidence.")
                else:
                    outputs[label] = {"path": str(path.resolve()), "sha256": _fingerprint(path)}
            if len(outputs) == len(fresh):
                manifest_data = load_manifest(manifest)
                if utc(manifest_data["started_at"]) <= watermark:
                    blockers.append("Collection started before the retained watermark.")
                result = collection_check(activity_log, manifest_data, "governance")
                blockers.extend(result["flags"])
                blockers.extend(partition_coverage_blockers(plan, manifest_data))
                summary = _load(audit)
                if Path(summary.get("collection_plan", "")).resolve() != plan_path.resolve():
                    blockers.append("Reconciliation audit is not bound to this delta plan.")
                recon, recon_hash = summary.get("output"), summary.get("output_sha256")
                if not (isinstance(recon, str) and recon.strip()):
                    blockers.append("Reconciliation audit lacks the required output binding.")
                elif not (isinstance(recon_hash, str) and len(recon_hash) == 64):
                    blockers.append("Reconciliation audit lacks the required output_sha256.")
                elif not Path(recon).is_file() or not _outside(Path(recon), evidence_dir):
                    blockers.append(
                        "Reconciliation output must be an existing file outside retained evidence."
                    )
                else:
                    verify_reconciliation(audit, [Path(recon)], target)
                    outputs["reconciled_output"] = {
                        "path": str(Path(recon).resolve()),
                        "sha256": _fingerprint(Path(recon)),
                    }
    except ERRORS as error:
        blockers.append(str(error))
    if mode == "delta_collection" and "reconciled_output" not in outputs:
        blockers.append("Delta collection requires a bound reconciled output.")
    ready = not blockers
    data = {
        "schema_version": 1,
        "status": READY if ready else BLOCKED,
        "generation_allowed": ready,
        "mode": mode,
        "cutoff": cutoff,
        "retained_sha256": prior.get("retained_sha256"),
        "retained_evidence": str(evidence_dir.resolve()),
        "fresh_outputs": outputs,
        "blockers": blockers,
        "limitations": [
            "Local checks only; Wiz partitions are run by the agent, read-only.",
            "Ready does not authorize publication or sending.",
        ],
    }
    if mode == "delta_collection" and plan_path.is_file():
        data["plan"] = {"path": str(plan_path.resolve()), "sha256": _fingerprint(plan_path)}
    if "retained_sha256" in prior:
        _write(receipt, evidence_dir, data)
    return data


def require_ready_receipt(receipt: Path, reconciliation: Path | None, collected_through) -> dict:
    """Refuse governance verification unless the collection gate is ready and unchanged."""
    data = _load(receipt)
    require(
        data.get("status") == READY and data.get("generation_allowed") is True,
        f"Collection gate is blocked: {data.get('blockers')}",
    )
    require(utc(data["cutoff"]) == collected_through, "Collection gate cutoff differs from report.")
    if data.get("mode") == "delta_collection":
        outputs = data.get("fresh_outputs", {})
        audit_output = outputs.get("audit")
        require(
            isinstance(audit_output, dict) and "path" in audit_output,
            "Collection gate receipt lacks the reconciliation audit binding.",
        )
        require(
            reconciliation is not None
            and Path(audit_output["path"]).resolve() == reconciliation.resolve(),
            "Verification must use the reconciliation audit approved by the collection gate.",
        )
        for label, item in outputs.items():
            require(
                _fingerprint(Path(item["path"])) == item["sha256"],
                f"Fresh collection output changed after the gate: {label}",
            )
        plan = data.get("plan")
        require(
            isinstance(plan, dict) and "path" in plan and "sha256" in plan,
            "Collection gate receipt lacks the approved delta plan binding.",
        )
        require(
            _fingerprint(Path(plan["path"])) == plan["sha256"],
            "Approved delta plan changed after the gate.",
        )
        recon = outputs.get("reconciled_output")
        require(
            isinstance(recon, dict) and "path" in recon,
            "Collection gate receipt lacks the reconciled output binding.",
        )
        audit = _load(Path(audit_output["path"]))
        require(
            Path(str(audit.get("output", ""))).resolve() == Path(recon["path"]).resolve()
            and audit.get("output_sha256") == recon["sha256"],
            "Reconciliation audit is not bound to the gated reconciled output.",
        )
        require(
            Path(str(audit.get("collection_plan", ""))).resolve() == Path(plan["path"]).resolve(),
            "Reconciliation audit is not bound to the gated delta plan.",
        )
    retained = data.get("retained_evidence")
    baseline = data.get("retained_sha256")
    require(
        isinstance(retained, str) and isinstance(baseline, dict) and Path(retained).is_dir(),
        "Collection gate receipt lacks the retained evidence binding.",
    )
    now = {str(Path(k).resolve()): v for k, v in _hashes(Path(retained)).items()}
    then = {str(Path(k).resolve()): v for k, v in baseline.items()}
    require(now == then, "Retained evidence changed after the gate.")
    return data


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    steps = parser.add_subparsers(dest="step", required=True)
    for name in ("plan", "check"):
        step = steps.add_parser(name)
        step.add_argument("--retained-evidence", type=Path, required=True)
        step.add_argument("--cutoff", required=True)
        step.add_argument("--plan", type=Path, required=True)
        step.add_argument("--receipt", type=Path, required=True)
        step.add_argument(
            "--console-runs", type=Path, help="Console runs.json (default: state dir)"
        )
        if name == "check":
            for option in ("activity-log", "manifest", "raw-evidence", "audit"):
                step.add_argument(f"--{option}", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.step == "plan":
            result = plan_step(
                args.retained_evidence, args.cutoff, args.plan, args.receipt, args.console_runs
            )
        else:
            result = check_step(
                args.retained_evidence,
                args.cutoff,
                args.plan,
                args.receipt,
                args.activity_log,
                args.manifest,
                args.raw_evidence,
                args.audit,
                args.console_runs,
            )
    except ERRORS as error:
        parser.exit(1, f"Collection gate failed: {error}\n")
    print(
        json.dumps(
            {k: result[k] for k in ("status", "mode", "generation_allowed", "blockers")},
            indent=2,
        )
    )
    return 0 if result["status"] == READY else 1
