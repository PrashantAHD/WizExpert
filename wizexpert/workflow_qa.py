"""Evidence-bound workflow compliance QA; not cloud authorization or proof of reasoning."""

from __future__ import annotations

import argparse
import hashlib
import json
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
    "campaign": {
        "collection": (
            "campaign-active-and-fixed-scope",
            "snapshot-inventory-stall-and-identity",
            "wiz-auth-and-model-availability",
        ),
        "generation": (
            "finding-versus-asset-metrics",
            "new-detection-versus-count-delta",
            "owner-team-provenance-and-history",
        ),
        "handoff": (
            "campaign-layout-and-removed-columns",
            "scanner-status-versus-patching",
            "campaign-closure-criteria",
            "no-partial-pack-and-qualified-wording",
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
    "campaign": ("docs/CAMPAIGNS.md",),
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
        "wizexpert/workflow_qa.py",
        "wizexpert/email_qa.py",
        "wizexpert/artifact_qa.py",
        "wizexpert/office_qa.py",
        "wizexpert/campaign.py",
    )
    if workflow == "governance":
        paths += tuple(
            path.relative_to(ROOT).as_posix()
            for path in sorted((ROOT / "wizexpert" / "governance").glob("*.py"))
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


def normalized_query(arguments: dict) -> dict:
    require(isinstance(arguments, dict), "Wiz arguments must be an object.")
    parameters = arguments.get("parameters")
    require(isinstance(parameters, dict), "Wiz query parameters must be an object.")
    return {
        "tool_name": arguments.get("tool_name"),
        "parameters": {k: v for k, v in parameters.items() if k != "after"},
    }


WIZ_BULK_TOOLS = {"list_issues", "list_issues_grouped", "execute_graph_query"}
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


OWNER_CHANGE_KINDS = ("addition", "rule_update")


def owner_changes_of(review: dict) -> list:
    """Owner-requested scope changes; a missing field means none."""
    changes = review.get("owner_changes", [])
    require(isinstance(changes, list), "owner_changes must be a list.")
    return changes


def validate_owner_changes(review: dict, evidence: dict) -> None:
    """Fail closed on malformed owner-requested scope changes.

    Owner requests are approved scope changes, not review failures, but each one must be
    hash-bound to the retained request and must show the earlier logic was still verified.
    A rule update never bypasses rule_sha256 binding: changed rules need a fresh review.
    """
    requested = {r["id"] for r in review["requested_deliverables"]}
    seen: set[str] = set()
    for entry in owner_changes_of(review):
        require(isinstance(entry, dict), "Each owner change must be an object.")
        change_id = entry.get("id")
        require(text(change_id), "Owner change ID must be a nonempty string.")
        require(change_id not in seen, f"Duplicate owner change ID: {change_id}")
        seen.add(change_id)
        require(
            entry.get("kind") in OWNER_CHANGE_KINDS,
            f"Owner change {change_id} kind must be addition or rule_update.",
        )
        request = entry.get("request")
        require(
            isinstance(request, str) and Path(request).is_absolute() and request in evidence,
            f"Owner change {change_id} request must be an absolute hash-bound evidence path.",
        )
        require(text(entry.get("summary")), f"Owner change {change_id} needs a summary.")
        require(
            entry.get("prior_logic_verified") is True,
            f"Owner change {change_id} must verify the previously applicable logic was followed.",
        )
        deliverables = entry.get("deliverables", [])
        require(
            isinstance(deliverables, list)
            and all(isinstance(d, str) and d in requested for d in deliverables)
            and len(set(deliverables)) == len(deliverables),
            f"Owner change {change_id} deliverables must be unique requested deliverable IDs.",
        )
        persisted = entry.get("persisted_in", [])
        require(
            isinstance(persisted, list)
            and all(
                isinstance(p, str) and Path(p).is_absolute() and p in evidence for p in persisted
            ),
            f"Owner change {change_id} persisted_in must be absolute hash-bound evidence paths.",
        )
        if entry["kind"] == "rule_update":
            require(
                bool(persisted),
                f"Owner change {change_id} rule_update must record where it was persisted.",
            )


def validate_scope_continuity(previous: dict, review: dict) -> None:
    """Later phases may only add owner-approved deliverables and never drop owner changes."""
    before = {r["id"]: r for r in previous["requested_deliverables"]}
    after = {r["id"]: r for r in review["requested_deliverables"]}
    require(
        all(after.get(name) == row for name, row in before.items()),
        "Previous QA review belongs to another run or scope; deliverables cannot disappear.",
    )
    approved = {
        d
        for entry in owner_changes_of(review)
        if entry["kind"] == "addition"
        for d in entry.get("deliverables", [])
    }
    added = set(after) - set(before)
    require(
        added <= approved,
        "Added deliverables need an owner-requested addition entry: " + ", ".join(sorted(added)),
    )
    current = {entry["id"]: entry for entry in owner_changes_of(review)}
    for entry in owner_changes_of(previous):
        require(
            current.get(entry["id"]) == entry,
            f"Owner change {entry['id']} cannot disappear or change in a later phase.",
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
    require(text(review.get("preparer")), "Named preparer required.")
    if actual_phase != "collection":  # collection needs no independent reviewer
        require(text(review.get("reviewer")), "Named review required.")
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
    validate_owner_changes(review, evidence)
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
            and previous["request_evidence"] == review["request_evidence"]
            and previous["private_rule_sources"] == review["private_rule_sources"]
            and previous["parity_groups"] == review["parity_groups"],
            "Previous QA review belongs to another run or scope; deliverables cannot disappear.",
        )
        validate_scope_continuity(previous, review)
        require(timestamp(previous["reviewed_at"]) <= reviewed, "QA phases are out of sequence.")
        log_path = Path(review["activity_log"])
        require(str(log_path) in evidence, "Actual activity log must be hash-bound.")
        audit_activity(log_path, review, previous)
    for name, expected in evidence.items():
        require(digest(Path(name)) == expected, f"QA evidence changed during validation: {name}")
    return review


def audit_activity(path: Path, review: dict, previous: dict) -> None:
    """Post-collection check from the recorded activity log; it blocks the report only."""
    manifest_path = Path(review["collection_manifest"])
    require(str(manifest_path) in review["evidence_sha256"], "Manifest must be hash-bound.")
    result = collection_check(path, load(manifest_path), review["workflow"])
    require(
        result["status"] == "pass", "Post-collection check flagged: " + "; ".join(result["flags"])
    )


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
        "owner_changes": [
            {
                "id": entry["id"],
                "kind": entry["kind"],
                "summary": entry["summary"],
                "deliverables": entry.get("deliverables", []),
            }
            for entry in owner_changes_of(review)
        ],
        "checked_artifacts": review.get("artifacts", []) if review["phase"] == "handoff" else [],
        "limitations": [
            "Semantic checks are reviewer attestations, not proof of hidden reasoning.",
            "Reviewer identity and log completeness are not authenticated by this local validator.",
            "Passing does not authorize publication, sending or cloud changes.",
        ],
    }


def collection_check(log_path: Path, manifest: dict, workflow: str | None = None) -> dict:
    """Post-collection check from the activity log; it flags a report, never blocks a tool call.

    Confirms reuse-first (prior sources named; any full-history Wiz query justified) and
    that every manifest count reconciles. A campaign review must also carry a
    `campaign_collection` block bound to the hash-linked assemble manifest.
    Returns {"status": "pass"|"flagged", "flags": [...]}.
    """
    flags: list[str] = []
    try:
        start, end = timestamp(manifest["started_at"]), timestamp(manifest["ended_at"])
    except (KeyError, TypeError, ValueError):
        return {"status": "flagged", "flags": ["Manifest needs started_at and ended_at."]}
    reused = manifest.get("reused_sources")
    named = isinstance(reused, list) and reused and all(text(item) for item in reused)
    if not named and not text(manifest.get("no_prior_evidence_reason")):
        flags.append("Reuse-first: name the reused prior sources or why none exist.")
    justified = text(manifest.get("full_refresh_reason"))
    seen = wiz_calls = 0
    with log_path.open(encoding="utf-8") as stream:
        for line in stream:
            event = json.loads(line, object_pairs_hook=unique_object)
            if not start <= timestamp(event["timestamp"]) <= end:
                continue
            seen += 1
            data = event.get("data", {})
            if event.get("type") != "tool.execution_start" or not is_wiz_execute(
                data.get("toolName", "")
            ):
                continue
            wiz_calls += 1
            try:
                arguments = data.get("arguments", {})
                full = is_bulk(arguments) and is_full_history(normalized_query(arguments))
            except ValueError:
                flags.append("A Wiz call in the log has unreadable arguments.")
                continue
            if full and not justified:
                flags.append("Reuse-first: full-history Wiz query without full_refresh_reason.")
    if not seen:
        flags.append("Activity log has no events in the collection interval.")
    counts = manifest.get("counts")
    if "campaign_collection" in manifest or workflow == "campaign":
        from wizexpert.campaign import campaign_collection_flags

        flags.extend(campaign_collection_flags(manifest.get("campaign_collection")))
    if not (isinstance(counts, list) and counts):
        flags.append("Count reconciliation: no counts supplied.")
        counts = []
    for item in counts:
        ok = (
            isinstance(item, dict)
            and text(item.get("name"))
            and type(item.get("expected")) is int
            and type(item.get("collected")) is int
            and item["expected"] == item["collected"]
        )
        if not ok:
            name = item.get("name") if isinstance(item, dict) else None
            flags.append(f"Count reconciliation: mismatch or invalid entry ({name}).")
    status = "flagged" if flags else "pass"
    return {"status": status, "flags": sorted(set(flags)), "wiz_calls": wiz_calls}


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


def hook_main(argv: list[str]) -> int:
    """Compatibility no-op: tool calls are never blocked; use collection-check afterwards."""
    sys.stdin.buffer.read()
    sys.stdout.write("{}\n")
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
    post = commands.add_parser("collection-check")
    post.add_argument("--activity-log", type=Path, required=True)
    post.add_argument("--manifest", type=Path, required=True)
    post.add_argument("--workflow", choices=SPECIFIC)
    args = parser.parse_args(argv)
    try:
        if args.command == "requirements":
            result = {
                "schema_version": 2,
                "workflow": args.workflow,
                "phase": args.phase,
                "required_checks": required_checks(args.workflow, args.phase),
                "optional_fields": {
                    "owner_changes": [
                        {
                            "id": "unique nonempty string",
                            "kind": "addition | rule_update",
                            "request": "absolute path that is a key in evidence_sha256",
                            "summary": "nonempty string",
                            "prior_logic_verified": True,
                            "deliverables": ["requested deliverable IDs added (addition)"],
                            "persisted_in": ["absolute evidence paths (required: rule_update)"],
                        }
                    ]
                },
                "rule_sha256": rule_hashes(args.workflow),
                "private_rule_sources": {str(p.resolve()): digest(p) for p in args.private_rules},
                "rule_sections": rule_inventory(
                    args.workflow, {str(p.resolve()): digest(p) for p in args.private_rules}
                ),
            }
        elif args.command == "check":
            result = receipt(args.review, args.phase)
        elif args.command == "collection-check":
            result = collection_check(args.activity_log, load(args.manifest), args.workflow)
            if result["status"] != "pass":
                print(json.dumps(result, indent=2))
                return 1
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
