"""Evidence-bound workflow compliance QA; not cloud authorization or proof of reasoning."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

# Exception type only; untrusted XML is parsed with defusedxml.
from xml.etree.ElementTree import ParseError  # nosec B405
from zipfile import BadZipFile

from defusedxml.common import DefusedXmlException

ROOT = Path(__file__).resolve().parents[1]
PHASES = ("collection", "generation", "handoff")
COMMON = {
    "collection": (
        "scope-and-authorization",
        "applicable-rules-and-private-decisions",
        "prior-evidence-reuse",
        "collection-plan-and-cost",
    ),
    "generation": ("source-completeness", "conflicts-and-failures", "decisions-and-exceptions"),
    "handoff": ("output-validation", "native-visual-review", "honest-status-and-deliverables"),
}
SPECIFIC = {
    "governance": {
        "collection": ("lifecycle-and-reopening-coverage", "separate-approved-prior-sources"),
        "generation": ("cutoffs-and-historical-preservation", "accepted-risk-and-team-attribution"),
        "handoff": ("six-three-ten-layout", "reviewed-wording-and-no-assignee-column"),
    },
    "finding": {
        "collection": ("issue-and-graph-coverage", "rule-and-representative-issue-review"),
        "generation": ("configuration-aware-risk", "practical-remediation-and-approval-boundaries"),
        "handoff": (
            "email-template-and-identifiers",
            "html-pdf-parity-and-no-txt",
            "operator-versus-client-responsibilities",
        ),
    },
    "campaign": {
        "collection": ("campaign-active-and-fixed-scope", "snapshot-inventory-window-and-identity"),
        "generation": (
            "finding-versus-asset-metrics",
            "new-detection-versus-count-delta",
            "owner-team-provenance-and-history",
        ),
        "handoff": (
            "campaign-layout-and-removed-columns",
            "scanner-status-versus-patching",
            "campaign-closure-criteria",
        ),
    },
    "remediation": {
        "collection": ("authorized-approver-and-exact-scope", "native-targets-and-dependencies"),
        "generation": (
            "change-authorization-not-approach-only",
            "prechecks-recovery-and-stop-criteria",
            "least-privilege-and-exclusions",
        ),
        "handoff": (
            "execution-evidence-and-partial-outcomes",
            "owner-technical-and-wiz-validation",
            "acceptance-versus-remediation-versus-closure",
        ),
    },
    "publication": {
        "collection": (
            "public-only-scope-and-human-authorization",
            "outgoing-history-and-untracked-review",
        ),
        "generation": (
            "privacy-secrets-and-synthetic-fixtures",
            "tests-lint-security-dependency-gates",
        ),
        "handoff": ("exact-reviewed-outgoing-refs", "no-private-data-or-unapproved-push"),
    },
    "setup": {
        "collection": ("approved-tenant-sso-and-storage", "existing-installation-and-path-reuse"),
        "generation": ("read-only-access-and-dependency-validation", "no-embedded-credentials"),
        "handoff": ("actual-tool-readiness", "honest-capability-and-automation-status"),
    },
}
RULES = {
    "governance": (
        "docs/GOVERNANCE-RUNBOOK.md",
        "docs/GOVERNANCE.md",
        "docs/GOVERNANCE-SNAPSHOT.md",
    ),
    "finding": ("docs/WORKFLOW.md",),
    "campaign": ("docs/WORKFLOW.md",),
    "remediation": ("docs/WORKFLOW.md", "docs/EXECUTION.md"),
    "publication": ("docs/PUBLICATION.md",),
    "setup": ("docs/SETUP.md",),
}
MAX_REVIEW_BYTES = 2_000_000


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def unique_object(pairs: list) -> dict:
    result = {}
    for key, value in pairs:
        require(key not in result, f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def load(path: Path) -> dict:
    with path.open("rb") as stream:
        content = stream.read(MAX_REVIEW_BYTES + 1)
    require(len(content) <= MAX_REVIEW_BYTES, "QA review exceeds size limit.")
    value = json.loads(content, object_pairs_hook=unique_object)
    require(isinstance(value, dict), "QA review must be an object.")
    return value


def timestamp(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    require(
        result.utcoffset() is not None and result.utcoffset().total_seconds() == 0,
        "QA timestamps must be UTC.",
    )
    return result


def text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def rule_hashes(workflow: str) -> dict:
    paths = (
        *RULES[workflow],
        "docs/WORKFLOW-QA.md",
        ".github/instructions/production-workflow.instructions.md",
        "wizexpert/workflow_qa.py",
        "wizexpert/email_qa.py",
        "wizexpert/artifact_qa.py",
        "wizexpert/office_qa.py",
    )
    if workflow == "governance":
        paths += tuple(
            path.relative_to(ROOT).as_posix()
            for path in sorted((ROOT / "wizexpert" / "governance").glob("*.py"))
        )
    else:
        paths += (
            "wizexpert/workflow.py",
            "wizexpert/csv_report.py",
            "wizexpert/execution_update.py",
        )
    return {name: digest(ROOT.joinpath(*name.split("/"))) for name in paths}


def required_checks(workflow: str, phase: str) -> list[str]:
    return [
        check
        for stage in PHASES[: PHASES.index(phase) + 1]
        for check in (*COMMON[stage], *SPECIFIC[workflow][stage])
    ]


def rule_inventory(workflow: str, private_sources: dict | None = None) -> dict:
    """Include every documented section, not just checks implemented in Python."""
    sources = {
        name: ROOT.joinpath(*name.split("/"))
        for name in (
            *RULES[workflow],
            "docs/WORKFLOW-QA.md",
            ".github/instructions/production-workflow.instructions.md",
        )
    }
    sources.update({name: Path(name) for name in (private_sources or {})})
    inventory = {}
    for name, path in sources.items():
        section, lines, fenced = "Preamble", [], False
        sections = []
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            if re.match(r"^\s*(```|~~~)", line):
                fenced = not fenced
            match = re.match(r"^(#{1,6})\s+(.+)$", line) if not fenced else None
            if match:
                if section != "Preamble" or any(value.strip() for value in lines):
                    sections.append((section, "\n".join(lines)))
                section, lines = match[2], []
            else:
                lines.append(line)
        if section != "Preamble" or any(value.strip() for value in lines):
            sections.append((section, "\n".join(lines)))
        for index, (heading, content) in enumerate(sections):
            inventory[f"{name}::{index}:{heading}"] = hashlib.sha256(content.encode()).hexdigest()
    return inventory


def validate_coverage(review: dict, evidence: dict) -> dict:
    private = review.get("private_rule_sources")
    require(isinstance(private, dict), "Private rule sources must be a hash mapping.")
    if review["workflow"] == "campaign":
        require(
            bool(private), "Campaign QA requires its private campaign rules; no generic substitute."
        )
    for path, value in private.items():
        require(evidence.get(path) == value, "Private rules must be included in hashed evidence.")
    inventory = rule_inventory(review["workflow"], private)
    coverage = review.get("rule_coverage", {})
    require(
        isinstance(coverage, dict) and set(coverage) == set(inventory),
        "Workflow coverage is incomplete: every rule section needs an explicit disposition.",
    )
    for name, expected in inventory.items():
        item = coverage[name]
        require(
            isinstance(item, dict) and item.get("source_sha256") == expected,
            f"Rule-section coverage is stale: {name}",
        )
        require(
            item.get("verdict") in {"pass", "out_of_scope"},
            f"Rule section remains unverified: {name}",
        )
        require(text(item.get("rationale")), f"Rule section lacks reasoning: {name}")
        references = item.get("evidence")
        require(
            isinstance(references, list)
            and bool(references)
            and all(isinstance(p, str) and p in evidence for p in references),
            f"Rule section lacks supporting evidence: {name}",
        )
        if item["verdict"] == "out_of_scope":
            require(
                item.get("scope_approval") in evidence,
                f"Excluding a rule requires a recorded scope decision: {name}",
            )
    return coverage


def validate_remediation(review: dict, evidence: dict) -> None:
    if review["workflow"] != "remediation":
        return
    stage = review.get("target_stage")
    require(
        type(stage) is int and 4 <= stage <= 8,
        "Remediation QA must specify the intended workflow stage (4-8).",
    )
    if review["phase"] == "collection":
        return
    from wizexpert.workflow import load_tracker

    path = review.get("tracker")
    require(isinstance(path, str) and path in evidence, "Reviewed remediation tracker is required.")
    tracker = load_tracker(path)
    require(tracker.scope == review["scope"], "Remediation tracker has a different scope.")
    prerequisite = stage if review["phase"] == "handoff" else stage - 1
    require(
        tracker.stage_status(prerequisite) == "complete",
        "Remediation prerequisites/authorization/verification are incomplete.",
    )
    bindings = review.get("tracker_evidence_bindings", {})
    require(isinstance(bindings, dict), "Tracker evidence bindings must be a mapping.")
    for event in tracker.events:
        for ref in event.evidence.values():
            require(
                bindings.get(ref, ref) in evidence,
                "Tracker references need actual retained evidence, not reference text alone.",
            )
    for item in review.get("local_account_results", []):
        from wizexpert.execution_update import parse_result

        require(item["path"] in evidence, "Execution result must be hash-bound.")
        parsed = parse_result(Path(item["path"]).read_text(encoding="utf-8-sig"))
        require(
            parsed.vm == item["vm"]
            and parsed.outcome == item["outcome"]
            and list(parsed.verified) == item["verified_accounts"],
            "Local-account execution claim differs from parsed evidence.",
        )


def normalized_query(arguments: dict) -> dict:
    require(isinstance(arguments, dict), "Wiz arguments must be an object.")
    parameters = arguments.get("parameters")
    require(isinstance(parameters, dict), "Wiz query parameters must be an object.")
    return {
        "tool_name": arguments.get("tool_name"),
        "parameters": {k: v for k, v in parameters.items() if k != "after"},
    }


def is_bulk(arguments: dict) -> bool:
    tool = arguments.get("tool_name", "")
    if tool not in {"list_issues", "list_issues_grouped", "execute_graph_query"}:
        return False
    parameters = arguments.get("parameters", {})
    require(isinstance(parameters, dict), "Invalid Wiz parameters.")
    first = parameters.get("first", 10)
    require(type(first) is int and first > 0, "Invalid Wiz page size.")
    return first > 1 or bool(parameters.get("after"))


def is_full_history(query: dict) -> bool:
    if query["tool_name"] != "list_issues":
        return False
    p = query["parameters"]
    statuses = p.get("status", [])
    return (not statuses or bool(set(statuses) & {"RESOLVED", "REJECTED"})) and not any(
        p.get(field)
        for field in (
            "created_after",
            "resolved_at_after",
            "assignee_ids",
            "source_rule_id",
            "search",
        )
    )


def validate_review(path: Path, phase: str | None = None, *, now: datetime | None = None) -> dict:
    review = load(path)
    now = now or datetime.now(UTC)
    require(
        type(review.get("schema_version")) is int and review["schema_version"] == 2,
        "Unsupported workflow QA schema.",
    )
    workflow = review.get("workflow")
    require(workflow in SPECIFIC, "Unsupported QA workflow.")
    actual_phase = review.get("phase")
    require(actual_phase in PHASES, "Unsupported QA phase.")
    require(phase is None or actual_phase == phase, f"Expected {phase} QA review.")
    require(text(review.get("run_id")) and text(review.get("scope")), "QA run ID/scope required.")
    require(text(review.get("preparer")) and text(review.get("reviewer")), "Named review required.")
    require(
        review["preparer"].strip().casefold() != review["reviewer"].strip().casefold(),
        "The preparer cannot self-certify workflow compliance.",
    )
    reviewed = timestamp(review["reviewed_at"])
    require(
        timestamp(review["started_at"]) <= reviewed <= now < timestamp(review["expires_at"]),
        "QA review is future-dated, expired or out of sequence.",
    )
    require(
        review.get("rule_sha256") == rule_hashes(workflow),
        "Workflow rules changed or were not bound to the review; review again.",
    )
    evidence = review.get("evidence_sha256")
    require(isinstance(evidence, dict) and bool(evidence), "Hashed QA evidence is required.")
    for name, expected in evidence.items():
        source = Path(name)
        require(
            source.is_absolute() and source.resolve() != path.resolve(),
            "Evidence must be absolute and cannot be the review itself.",
        )
        require(
            isinstance(expected, str) and len(expected) == 64 and digest(source) == expected,
            f"QA evidence changed: {name}",
        )
    validate_coverage(review, evidence)
    require(
        review.get("unresolved_conflicts") == [],
        "Missing conflict review or unresolved rule/evidence conflicts block QA.",
    )
    require(
        review.get("request_evidence") in evidence,
        "The original request/scope decision must be retained as hashed evidence.",
    )
    from wizexpert.artifact_qa import validate_deliverables

    validate_deliverables(review, evidence)
    validate_remediation(review, evidence)
    checks = review.get("checks", {})
    require(isinstance(checks, dict), "QA checks must be an object.")
    require(
        set(checks) == set(required_checks(workflow, actual_phase)),
        "Missing or unexpected workflow checks; omissions cannot pass.",
    )
    for name, check in checks.items():
        require(
            isinstance(check, dict) and check.get("verdict") == "pass",
            f"Workflow requirement is not verified: {name}",
        )
        require(text(check.get("rationale")), f"Missing documented reasoning: {name}")
        references = check.get("evidence")
        require(
            isinstance(references, list)
            and bool(references)
            and all(isinstance(p, str) and p in evidence for p in references),
            f"Missing hashed supporting evidence: {name}",
        )
    queries = review.get("allowed_wiz_queries", [])
    require(isinstance(queries, list), "Allowed Wiz queries must be a list.")
    for query in queries:
        require(query == normalized_query(query), "Approved queries must omit pagination cursors.")
        require(is_bulk(query), "Allowlist entries must be explicit bulk queries.")
        limit = {"list_issues": 20, "list_issues_grouped": 50, "execute_graph_query": 50}
        require(
            query["parameters"].get("first", 10) <= limit[query["tool_name"]],
            "Query exceeds documented page limit.",
        )
        if is_full_history(query):
            approval = review.get("full_refresh_approval", {})
            require(isinstance(approval, dict), "Full-refresh approval must be an object.")
            require(
                text(approval.get("reason"))
                and text(approval.get("approved_by"))
                and approval.get("evidence") in evidence,
                "Full historical collection lacks a justified, evidence-backed approval.",
            )
    if actual_phase != "collection":
        previous_path = Path(review["previous_review"])
        require(str(previous_path) in evidence, "Previous phase review must be hash-bound.")
        previous_phase = PHASES[PHASES.index(actual_phase) - 1]
        previous = validate_review(previous_path, previous_phase, now=reviewed)
        require(
            previous["run_id"] == review["run_id"]
            and previous["workflow"] == workflow
            and previous["scope"] == review["scope"]
            and previous["started_at"] == review["started_at"]
            and previous["requested_deliverables"] == review["requested_deliverables"]
            and previous["request_evidence"] == review["request_evidence"]
            and previous["private_rule_sources"] == review["private_rule_sources"]
            and previous["parity_groups"] == review["parity_groups"]
            and previous.get("target_stage") == review.get("target_stage"),
            "Previous QA review belongs to another run or scope; deliverables cannot disappear.",
        )
        require(timestamp(previous["reviewed_at"]) <= reviewed, "QA phases are out of sequence.")
        log_path = Path(review["activity_log"])
        require(str(log_path) in evidence, "Actual activity log must be hash-bound.")
        audit_activity(log_path, review, previous)
    for name, expected in evidence.items():
        require(digest(Path(name)) == expected, f"QA evidence changed during validation: {name}")
    return review


def audit_activity(path: Path, review: dict, previous: dict) -> None:
    """Audit recorded tool requests, not the preparer's summary of those requests."""
    collection = previous
    while collection["phase"] != "collection":
        collection = load(Path(collection["previous_review"]))
    start, end = timestamp(review["started_at"]), timestamp(review["reviewed_at"])
    approved_at = timestamp(collection["reviewed_at"])
    seen = False
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            event = json.loads(line, object_pairs_hook=unique_object)
            at = timestamp(event["timestamp"])
            if not start <= at <= end:
                continue
            seen = True
            if event.get("type") != "tool.execution_start":
                continue
            data = event.get("data", {})
            tool = data.get("toolName", "")
            if not tool.endswith("wiz-execute"):
                continue
            args = data.get("arguments", {})
            if is_bulk(args):
                require(at >= approved_at, "Bulk collection occurred before workflow QA approval.")
                require(
                    normalized_query(args) in collection["allowed_wiz_queries"],
                    "Actual bulk query deviated from the reviewed collection plan.",
                )
    require(seen, "Activity log has no events in the reviewed interval.")


def receipt(path: Path, phase: str | None = None) -> dict:
    before = digest(path)
    review = validate_review(path, phase)
    require(digest(path) == before, "QA review changed during validation.")
    return {
        "status": "workflow_checks_passed",
        "phase": review["phase"],
        "workflow": review["workflow"],
        "run_id": review["run_id"],
        "review_sha256": before,
        "checked_at": datetime.now(UTC).isoformat(),
        "share_ready": False,
        "checks": list(review["checks"]),
        "documented_sections": len(review["rule_coverage"]),
        "out_of_scope_sections": [
            name
            for name, check in review["rule_coverage"].items()
            if check["verdict"] == "out_of_scope"
        ],
        "requested_deliverables": review["requested_deliverables"],
        "checked_artifacts": review.get("artifacts", []) if review["phase"] == "handoff" else [],
        "limitations": [
            "Semantic checks are reviewer attestations, not proof of hidden reasoning.",
            "Reviewer identity and log completeness are not authenticated by this local validator.",
            "Passing does not authorize publication, sending or cloud changes.",
        ],
    }


def hook(payload: dict, review_path: Path | None) -> dict:
    require(isinstance(payload, dict), "Hook input must be an object.")
    tool = payload.get("tool_name", "")
    args = payload.get("tool_input", {})
    if tool in {"multi_tool_use.parallel", "parallel"}:
        require(
            isinstance(args, dict) and isinstance(args.get("tool_uses"), list),
            "Invalid parallel tool input.",
        )
        for call in args["tool_uses"]:
            hook(
                {"tool_name": call["recipient_name"], "tool_input": call["parameters"]}, review_path
            )
        return {}
    if not isinstance(tool, str) or not tool.endswith("wiz-execute"):
        return {}
    require(isinstance(args, dict), "Invalid tool input.")
    if not is_bulk(args):
        return {}
    require(
        review_path is not None, "Bulk Wiz collection requires a workflow QA collection review."
    )
    review = validate_review(review_path, "collection")
    require(
        normalized_query(args) in review["allowed_wiz_queries"],
        "Bulk Wiz query is outside the reviewed plan; stop and obtain a new review.",
    )
    return {}


def require_generation_review(
    path: Path, sources: list[Path], workflow: str = "governance"
) -> dict:
    result = receipt(path, "generation")
    review = load(path)
    require(review["workflow"] == workflow, "Wrong workflow QA review.")
    for source in sources:
        require(
            str(source.resolve()) in review["evidence_sha256"],
            f"Generation source was not reviewed: {source}",
        )
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    contract = commands.add_parser("requirements")
    contract.add_argument("--workflow", choices=SPECIFIC, required=True)
    contract.add_argument("--phase", choices=PHASES, required=True)
    contract.add_argument("--private-rules", type=Path, nargs="*", default=[])
    check = commands.add_parser("check")
    check.add_argument("--review", type=Path, required=True)
    check.add_argument("--phase", choices=PHASES)
    guard = commands.add_parser("hook")
    guard.add_argument("--review", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "requirements":
            result = {
                "schema_version": 2,
                "workflow": args.workflow,
                "phase": args.phase,
                "required_checks": required_checks(args.workflow, args.phase),
                "rule_sha256": rule_hashes(args.workflow),
                "private_rule_sources": {str(p.resolve()): digest(p) for p in args.private_rules},
                "rule_sections": rule_inventory(
                    args.workflow, {str(p.resolve()): digest(p) for p in args.private_rules}
                ),
            }
        elif args.command == "check":
            result = receipt(args.review, args.phase)
        else:
            configured = os.environ.get("WIZEXPERT_QA_REVIEW")
            path = args.review or (Path(configured) if configured else None)
            payload = json.load(sys.stdin, object_pairs_hook=unique_object)
            result = hook(payload, path)
        print(json.dumps(result, indent=2))
        return 0
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        RecursionError,
        BadZipFile,
        DefusedXmlException,
        ParseError,
    ) as error:
        if args.command == "hook":
            print(
                json.dumps(
                    {
                        "hookSpecificOutput": {
                            "hookEventName": "PreToolUse",
                            "permissionDecision": "deny",
                            "permissionDecisionReason": f"Workflow QA blocked this action: {error}",
                        }
                    }
                )
            )
            return 0
        parser.exit(1, f"Workflow QA blocked: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
