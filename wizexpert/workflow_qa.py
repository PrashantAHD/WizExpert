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


WIZ_BULK_TOOLS = {"list_issues", "list_issues_grouped", "execute_graph_query"}
PARALLEL_TOOLS = {"multi_tool_use.parallel", "parallel"}
WIZ_EXECUTE_SUFFIXES = ("wiz-execute", "mcp__wiz__execute", "mcp_wiz_execute")


def normalize_tool_name(name: object) -> str | None:
    return name.strip().lower() if isinstance(name, str) else None


def is_wiz_execute(name: object) -> bool:
    normalized = normalize_tool_name(name)
    return normalized is not None and normalized.endswith(WIZ_EXECUTE_SUFFIXES)


def is_bulk(arguments: dict) -> bool:
    tool = arguments.get("tool_name", "")
    require(isinstance(tool, str), "Invalid Wiz tool name.")
    if tool.strip().lower() not in WIZ_BULK_TOOLS:
        return False
    parameters = arguments.get("parameters", {})
    require(isinstance(parameters, dict), "Invalid Wiz parameters.")
    first = parameters.get("first", 10)
    require(type(first) is int and first > 0, "Invalid Wiz page size.")
    cursor = parameters.get("after")
    require(cursor is None or (isinstance(cursor, str) and cursor != ""), "Invalid Wiz cursor.")
    return first > 1 or cursor is not None


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
            if not is_wiz_execute(tool):
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


NAME_KEYS = ("name", "tool", "toolName", "tool_name", "recipient_name")
ARG_KEYS = ("args", "arguments", "input", "parameters", "toolArgs", "tool_input")
BATCH_KEYS = ("toolCalls", "tool_calls", "calls")
WIZ_NAME_MARKERS = ("wiz-execute", "mcp__wiz__execute", "mcp_wiz_execute")


def hook_args(args: object) -> object:
    """Tool args may be an object or a JSON-encoded string; only called for Wiz calls."""
    if isinstance(args, str):
        return json.loads(args, object_pairs_hook=unique_object)
    return args


def all_args(element: dict) -> list:
    """Every present args value (args, arguments, input, ...), so none can hide a query."""
    return [element[key] for key in ARG_KEYS if element.get(key) is not None]


def hook_wiz_check(args: object, review_path: Path | None) -> None:
    require(args is not None, "Wiz call has no readable query arguments.")
    args = hook_args(args)
    require(isinstance(args, dict), "Invalid tool input.")
    inner = args.get("tool_name")
    require(isinstance(inner, str) and inner.strip() != "", "Wiz call has no inner tool name.")
    if not is_bulk(args):
        return
    require(
        review_path is not None, "Bulk Wiz collection requires a workflow QA collection review."
    )
    review = validate_review(review_path, "collection")
    require(
        normalized_query(args) in review["allowed_wiz_queries"],
        "Bulk Wiz query is outside the reviewed plan; stop and obtain a new review.",
    )


class BatchDeny(ValueError):
    """Deny for one call in a batch; the message is already path-free."""


def safe_call_id(call: object) -> str:
    value = call.get("id") if isinstance(call, dict) else None
    return re.sub(r"[^A-Za-z0-9_.-]", "", value)[:64] if isinstance(value, str) else "unknown"


def scan_text(text: str, markers: tuple[str, ...]) -> bool:
    """Case-insensitive marker scan that also sees JSON \\uXXXX escapes."""
    text = text.lower()
    unescaped = re.sub(r"\\u([0-9a-f]{4})", lambda m: chr(int(m.group(1), 16)), text)
    return any(marker in candidate for candidate in (text, unescaped) for marker in markers)


def unreadable_may_be_wiz(value: object) -> bool:
    """Scan a whole decoded element for Wiz names or the bulk inner tool names."""
    try:
        text = value if isinstance(value, str) else json.dumps(value, default=str)
        return scan_text(text, (*WIZ_NAME_MARKERS, *WIZ_BULK_TOOLS))
    except Exception:  # noqa: BLE001 - cannot inspect it, so cannot prove it is not Wiz
        return True


def call_names(element: dict) -> tuple[list[str], bool]:
    """Normalised names from every name key, and whether any name key is non-string."""
    names, odd = [], False
    for key in NAME_KEYS:
        value = element.get(key)
        if isinstance(value, str):
            names.append(value.strip().lower())
        elif value is not None:
            odd = True
    return names, odd


def wrapper_inner(element: dict) -> tuple[list, bool]:
    """Inner calls from every args value of a parallel wrapper, and whether all were readable."""
    calls: list = []
    values = all_args(element)
    readable = bool(values)
    for value in values:
        try:
            args = hook_args(value)
        except ValueError:
            readable = False
            continue
        if isinstance(args, dict) and isinstance(args.get("tool_uses"), list):
            calls += args["tool_uses"]
        else:
            readable = False
    return calls, readable


def classify(element: object) -> list[tuple[str, object]]:
    """Findings for one call: ("wiz", call) or ("unreadable", call) that may be Wiz."""
    if not isinstance(element, dict):
        return [("unreadable", element)] if unreadable_may_be_wiz(element) else []
    found: list[tuple[str, object]] = []
    names, odd = call_names(element)
    if (not names or odd) and unreadable_may_be_wiz(element):
        found.append(("unreadable", element))
    if any(name in PARALLEL_TOOLS for name in names):
        inner, readable = wrapper_inner(element)
        if not readable and unreadable_may_be_wiz(element):
            found.append(("unreadable", element))
        for call in inner:
            found += classify(call)
    if any(is_wiz_execute(name) for name in names):
        found.append(("wiz", element))
    return found


def payload_calls(payload: dict) -> list[tuple[object, bool]]:
    """(call, is_batch_member) for every call the payload may carry, in any known shape."""
    calls: list[tuple[object, bool]] = []
    for key in BATCH_KEYS:
        if key in payload:
            batch = payload[key]
            calls += [(call, True) for call in (batch if isinstance(batch, list) else [batch])]
    if "toolName" in payload or "tool_name" in payload:
        calls.append((payload, False))
    return calls


def hook(payload: dict, review_path: Path | None) -> dict:
    """Raise ValueError to deny; only Wiz execute calls or malformed input that may be one."""
    require(isinstance(payload, dict), "Hook input must be an object.")
    for call, in_batch in payload_calls(payload):
        try:
            for kind, element in classify(call):
                require(kind != "unreadable", "Unreadable tool call may be a Wiz call.")
                queries = all_args(element)
                require(bool(queries), "Wiz call has no readable query arguments.")
                for query in queries:
                    hook_wiz_check(query, review_path)
        except Exception as error:  # noqa: BLE001 - any failure denies
            if not in_batch:
                raise
            raise BatchDeny(
                f"call {safe_call_id(call)} denied ({describe_error(error)})"
            ) from error
    return {}


def may_involve_wiz(payload: dict) -> bool:
    """Decide from decoded data whether any call is, or may hide, a Wiz execute call."""
    try:
        return any(classify(call) for call, _ in payload_calls(payload))
    except Exception:  # noqa: BLE001 - unreadable: cannot prove it is not Wiz
        return True


def mentions_wiz(raw: bytes) -> bool:
    """Fallback for input that is not valid JSON: scan raw text, including JSON escapes."""
    return scan_text(raw.decode("utf-8", errors="replace"), WIZ_NAME_MARKERS)


def describe_error(error: BaseException) -> str:
    """Deny reason without absolute paths: error type plus a basename or a path-free message."""
    kind = type(error).__name__
    if isinstance(error, BatchDeny):
        return str(error)
    if isinstance(error, OSError):
        name = Path(str(error.filename)).name if error.filename else ""
        return f"{kind}: review file unavailable" + (f" ({name})" if name else "")
    message = str(error)
    if isinstance(error, ValueError) and not re.search(r"[\\/]|\b[A-Za-z]:", message):
        return f"{kind}: {message}"
    return kind


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


def hook_deny(reason: str) -> dict:
    return {
        "permissionDecision": "deny",
        "permissionDecisionReason": reason,
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        },
    }


def hook_main(argv: list[str]) -> int:
    """Command hook entry point: always exit 0 with exactly one JSON object.

    Command preToolUse hooks fail closed, so any crash would block every tool.
    Only Wiz execute calls (or unreadable input that mentions them) are denied.
    """
    raw = b""
    payload: object = None
    try:
        review: Path | None = None
        if "--review" in argv and argv.index("--review") + 1 < len(argv):
            review = Path(argv[argv.index("--review") + 1])
        raw = sys.stdin.buffer.read()
        configured = os.environ.get("WIZEXPERT_QA_REVIEW")
        path = review or (Path(configured) if configured else None)
        try:
            payload = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=unique_object)
        except (ValueError, RecursionError):
            payload = None
        if isinstance(payload, dict):
            result = hook(payload, path)
        elif mentions_wiz(raw):
            result = hook_deny("Workflow QA blocked this action: unreadable Wiz hook input.")
        else:
            result = {}
    except Exception as error:  # noqa: BLE001 - hook must never crash
        involved = may_involve_wiz(payload) if isinstance(payload, dict) else mentions_wiz(raw)
        result = hook_deny(f"Workflow QA blocked this action: {describe_error(error)}")
        if not involved:
            result = {}
    sys.stdout.write(json.dumps(result) + "\n")
    sys.stdout.flush()
    return 0


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    if argv and argv[0] == "hook":
        return hook_main(list(argv[1:]))
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
        else:  # pragma: no cover - hook is dispatched before parsing
            return hook_main([])
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
        parser.exit(1, f"Workflow QA blocked: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
