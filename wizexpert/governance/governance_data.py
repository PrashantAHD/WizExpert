"""Validate dated, locally captured Wiz evidence for operational governance."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from wizexpert.governance.dashboard_data import DashboardError, require
from wizexpert.governance.wiz_report import _parse_dt, status_at

SEVERITIES = ("CRITICAL", "HIGH", "MEDIUM", "LOW", "INFORMATIONAL")
DISPLAY_SEVERITIES = SEVERITIES[:4]
ISSUE_TYPES = {
    "CLOUD_CONFIGURATION",
    "TOXIC_COMBINATION",
    "THREAT_DETECTION",
    "ATTACK_SURFACE",
    "RISK_TOXIC_COMBINATION",
}
AGGREGATE_KEYS = {severity: f"{severity.lower()}SeverityCount" for severity in SEVERITIES}


def capture_groups(response: dict) -> dict:
    """Minimize a Wiz list_issues_grouped response without retaining resource names."""
    try:
        collection = response["issuesGroupedByValue"]
        groups = []
        for group in collection["nodes"]:
            issues = group["issues"]
            samples = issues["nodes"]
            require(
                bool(samples),
                "Collect groups with fetchIssues=true to include rule names and dated samples.",
            )
            rules = samples[0]["sourceRules"]
            require(
                len(rules) == 1,
                "Multiple source rules in a group sample require manual reconciliation.",
            )
            require(
                sum(issues[key] for key in AGGREGATE_KEYS.values()) == issues["totalCount"],
                "Wiz group severity counts disagree with its total.",
            )
            groups.append(
                {
                    "id": group["id"],
                    "name": rules[0]["name"],
                    "counts": {severity: issues[key] for severity, key in AGGREGATE_KEYS.items()},
                    "recommendation": rules[0].get("resolutionRecommendation")
                    or "Review the Wiz control recommendation with the resource owner.",
                    "samples": [
                        {
                            "id": sample["id"],
                            "created_at": sample["createdAt"],
                            "resolved_at": sample["resolvedAt"],
                        }
                        for sample in samples
                    ],
                }
            )
        return {"total_groups": collection["totalCount"], "groups": groups}
    except (KeyError, TypeError, IndexError) as exc:
        raise DashboardError(f"Malformed Wiz grouped response: {exc}") from exc


def text(value, label: str) -> str:
    require(isinstance(value, str) and bool(value.strip()), f"{label} must be nonempty text.")
    require(
        all(ord(c) >= 32 or c in "\n\t" for c in value), f"{label} contains control characters."
    )
    return value


def timestamp(value, label: str) -> datetime:
    try:
        result = datetime.fromisoformat(text(value, label).replace("Z", "+00:00"))
    except ValueError as exc:
        raise DashboardError(f"{label} must be an ISO timestamp.") from exc
    require(
        result.utcoffset() is not None and result.utcoffset().total_seconds() == 0,
        f"{label} must include UTC (+00:00 or Z).",
    )
    return result


def counts(value, label: str, severities=SEVERITIES) -> dict[str, int]:
    if (
        severities == SEVERITIES
        and isinstance(value, dict)
        and set(value) == set(DISPLAY_SEVERITIES)
    ):
        # Informational findings are not tracked; snapshots may omit the key entirely.
        value["INFORMATIONAL"] = 0
    require(
        isinstance(value, dict) and set(value) == set(severities),
        f"{label} must contain exactly {', '.join(DISPLAY_SEVERITIES)}.",
    )
    require(
        all(type(n) is int and n >= 0 for n in value.values()),
        f"{label} counts must be nonnegative integers.",
    )
    return value


def metric(value, label: str) -> float | None:
    require(isinstance(value, dict) and "value" in value, f"{label} must include value and source.")
    text(value.get("source"), f"{label}.source")
    number = value.get("value")
    if number is None:
        text(value.get("unavailable_reason"), f"{label}.unavailable_reason")
    else:
        require(
            type(number) in (int, float) and math.isfinite(number) and 0 <= number <= 100,
            f"{label} must be between 0 and 100, or explicitly unavailable.",
        )
    return number


def validate_assignments(value, total: int, label: str) -> None:
    require(isinstance(value, dict), f"{label} must contain verified assignment evidence.")
    text(value.get("source"), f"{label}.source")
    verified_at = timestamp(value.get("verified_at"), f"{label}.verified_at")
    require(verified_at <= datetime.now(UTC), f"{label}: verification cannot be in the future.")
    entries = value.get("entries")
    require(isinstance(entries, list) and bool(entries), f"{label}: entries are required.")
    seen, assigned = set(), 0
    for entry in entries:
        require(isinstance(entry, dict), f"{label}: invalid assignment entry.")
        identifier = entry.get("id")
        require(
            "id" in entry, f"{label}: specify the assignee ID, or null for verified unassigned."
        )
        if identifier is not None:
            text(identifier, f"{label}.id")
        require(identifier not in seen, f"{label}: duplicate assignee.")
        seen.add(identifier)
        name = text(entry.get("name"), f"{label}.name")
        require(
            name == name.strip() and not any(c in name for c in "\n\t/()"),
            f"{label}: display names must be single-line names without slashes or parentheses.",
        )
        require(
            identifier is not None or name == "Unassigned",
            f"{label}: a null assignee ID must be labelled Unassigned.",
        )
        require(
            type(entry.get("count")) is int and entry["count"] > 0,
            f"{label}: assignee counts must be positive integers.",
        )
        assigned += entry["count"]
    require(
        assigned <= total,
        f"{label}: assignee evidence covers {assigned}, exceeding the {total} qualifying findings.",
    )


def closed_counts(group: dict) -> dict[str, int]:
    """Resolved plus accepted-risk (Wiz REJECTED/ignored) counts for a group."""
    accepted = group.get("accepted") or {}
    return {s: group["counts"][s] + accepted.get(s, 0) for s in SEVERITIES}


@dataclass(frozen=True)
class GovernanceData:
    payload: dict
    start: datetime
    end: datetime
    resolved_through: datetime
    collected_from: datetime
    collected_through: datetime

    @property
    def backlog_as_of(self) -> datetime:
        """When the open/in-progress counts apply; never later than the period end."""
        value = self.payload["period"].get("backlog_as_of")
        return (
            timestamp(value, "period.backlog_as_of")
            if value is not None
            else self.collected_through
        )

    @property
    def preliminary(self) -> bool:
        return self.resolved_through < self.end or self.backlog_as_of < self.end

    def total(self, field: str) -> int:
        if field == "team_resolved":
            return sum(
                sum(closed_counts(g)[s] for s in DISPLAY_SEVERITIES)
                for g in self.payload["team_resolved"]["groups"]
            )
        if field == "accepted" and field not in self.payload:
            return 0
        return sum(self.payload[field][s] for s in DISPLAY_SEVERITIES)

    def team_accepted(self) -> int:
        return sum(
            sum((g.get("accepted") or {}).get(s, 0) for s in DISPLAY_SEVERITIES)
            for g in self.payload.get("team_resolved", {}).get("groups", [])
        )

    def owner_status(self) -> dict[str, str]:
        """Team-reported status for in-progress work, keyed by assignee display name."""
        return {entry["name"]: entry["status"] for entry in self.payload.get("owner_status", [])}

    def rule_status(self) -> dict[str, str]:
        """Team-reported status for one in-progress rule group, keyed by rule ID.

        Overrides owner_status.
        """
        return {
            entry["id"]: entry["status"]
            for entry in self.payload.get("rule_status", [])
            if "status" in entry
        }

    def rule_next_step(self) -> dict[str, str]:
        """Team-written next step for one in-progress rule group (replaces the Wiz suggestion)."""
        return {
            entry["id"]: entry["next_step"]
            for entry in self.payload.get("rule_status", [])
            if "next_step" in entry
        }

    def closure_wording(self) -> dict[str, dict[str, str]]:
        """Team-written "what changed" / "risk reduced" text for a team-resolved rule.

        Keyed by rule ID.
        """
        return {
            entry["id"]: {key: entry[key] for key in ("changed", "risk") if key in entry}
            for entry in self.payload.get("closure_wording", [])
        }

    def team_totals(self) -> dict[str, int]:
        result: dict[str, int] = {}
        for group in self.payload.get("team_resolved", {}).get("groups", []):
            for entry in group["assignments"]["entries"]:
                result[entry["name"]] = result.get(entry["name"], 0) + entry["count"]
        return dict(sorted(result.items(), key=lambda item: (-item[1], item[0].casefold())))

    def rule_assignees(self) -> dict[str, list[str]]:
        by_rule: dict[str, dict[str, str]] = {}
        records = [
            group
            for field in ("resolved_groups", "in_progress_groups")
            for group in self.payload[field]["groups"]
        ]
        records += self.payload.get("rule_assignment_evidence", [])
        for record in records:
            for entry in record.get("assignments", {}).get("entries", []):
                if entry["id"] is not None:
                    names = by_rule.setdefault(record["id"], {})
                    require(
                        entry["id"] not in names or names[entry["id"]] == entry["name"],
                        f"Conflicting display names for assignee {entry['id']}.",
                    )
                    names[entry["id"]] = entry["name"]
        return {
            rule: sorted(set(names.values()), key=str.casefold) for rule, names in by_rule.items()
        }

    def ranked(self, field: str) -> list[dict]:
        def key(group):
            closed = closed_counts(group)
            severity = min(i for i, s in enumerate(DISPLAY_SEVERITIES) if closed[s])
            return severity, -sum(closed[s] for s in DISPLAY_SEVERITIES), group["id"]

        return sorted(
            (
                g
                for g in self.payload[field]["groups"]
                if any(closed_counts(g)[s] for s in DISPLAY_SEVERITIES)
            ),
            key=key,
        )


def validate_groups(payload: dict, field: str, totals: str, data: GovernanceData) -> None:
    collection = payload[field]
    require(
        isinstance(collection, dict) and isinstance(collection.get("groups"), list),
        f"{field} requires groups and total_groups.",
    )
    groups = collection["groups"]
    require(
        type(collection.get("total_groups")) is int and collection["total_groups"] == len(groups),
        f"{field} is incomplete: paginate or split the Wiz query until all groups are captured.",
    )
    ids, sample_ids = set(), set()
    aggregate = dict.fromkeys(SEVERITIES, 0)
    for group in groups:
        require(isinstance(group, dict), f"{field}: invalid group.")
        identifier = text(group.get("id"), f"{field}.id")
        require(identifier not in ids, f"{field}: duplicate group {identifier}.")
        ids.add(identifier)
        text(group.get("name"), f"{identifier}.name")
        group_counts = counts(group.get("counts"), identifier)
        require(sum(group_counts.values()) > 0, f"{identifier}: empty group.")
        for severity in SEVERITIES:
            aggregate[severity] += group_counts[severity]
        samples = group.get("samples")
        require(
            isinstance(samples, list) and 0 < len(samples) <= sum(group_counts.values()),
            f"{identifier} needs dated issue samples; samples are not the aggregate count.",
        )
        local_ids = set()
        for sample in samples:
            sid = text(sample.get("id"), f"{identifier}.sample.id")
            require(sid not in sample_ids, f"{field}: duplicate sampled issue {sid}.")
            sample_ids.add(sid)
            local_ids.add(sid)
            created = timestamp(sample.get("created_at"), f"{sid}.created_at")
            require(
                created <= data.backlog_as_of
                if field == "in_progress_groups"
                else created <= data.collected_through,
                f"{sid}: created after the counted period.",
            )
            if field == "resolved_groups":
                resolved = timestamp(sample.get("resolved_at"), f"{sid}.resolved_at")
                require(
                    created <= resolved and data.start < resolved <= data.resolved_through,
                    f"{sid}: resolution is outside the reporting interval.",
                )
        if "recommendation" in group:
            text(group["recommendation"], f"{identifier}.recommendation")
        if "assignments" in group:
            validate_assignments(
                group["assignments"], sum(group_counts.values()), f"{identifier}.assignments"
            )
        annotation = group.get("annotation")
        if annotation is not None:
            require(isinstance(annotation, dict), f"{identifier}: invalid annotation.")
            for key in ("change", "risk", "source"):
                text(annotation.get(key), f"{identifier}.annotation.{key}")
            evidence_ids = annotation.get("issue_ids")
            require(
                isinstance(evidence_ids, list)
                and bool(evidence_ids)
                and all(isinstance(i, str) for i in evidence_ids)
                and len(set(evidence_ids)) == len(evidence_ids)
                and set(evidence_ids) <= local_ids,
                f"{identifier}: annotation must cite unique, captured issue IDs.",
            )
    require(
        aggregate == payload[totals],
        f"{field} counts disagree with independently queried {totals}; "
        "check scope, types and pagination.",
    )


def validate_team_resolved(payload: dict, data: GovernanceData) -> None:
    """Team closures are a subset of tenant closures currently assigned to named team members."""
    team = payload["team_resolved"]
    require(isinstance(team, dict), "team_resolved must be an object.")
    text(team.get("basis"), "team_resolved.basis")
    members = team.get("team")
    require(
        isinstance(members, list) and bool(members), "team_resolved.team must list team members."
    )
    ids = {
        text(m.get("id"), "team_resolved.team.id"): text(m.get("name"), "team_resolved.team.name")
        for m in members
    }
    require(
        len(ids) == len(members) and len(set(ids.values())) == len(members),
        "team_resolved.team must contain unique IDs and names.",
    )
    tenant = {g["id"]: g for g in payload["resolved_groups"]["groups"]}
    tenant_accepted = (
        counts(payload["accepted"], "accepted")
        if "accepted" in payload
        else dict.fromkeys(SEVERITIES, 0)
    )
    groups = team.get("groups")
    require(
        isinstance(groups, list) and team.get("total_groups") == len(groups),
        "team_resolved requires groups and matching total_groups.",
    )
    aggregate = dict.fromkeys(SEVERITIES, 0)
    accepted_total = dict.fromkeys(SEVERITIES, 0)
    seen = set()
    for group in groups:
        identifier = text(group.get("id"), "team_resolved.id")
        require(identifier not in seen, f"team_resolved group {identifier} must be unique.")
        seen.add(identifier)
        group_counts = counts(group.get("counts"), identifier)
        accepted = counts(
            group.get("accepted", dict.fromkeys(SEVERITIES, 0)), f"{identifier}.accepted"
        )
        if sum(group_counts.values()):
            require(
                identifier in tenant,
                f"team_resolved group {identifier} must be present in resolved_groups.",
            )
            require(
                all(group_counts[s] <= tenant[identifier]["counts"][s] for s in SEVERITIES),
                f"{identifier}: team closures exceed tenant closures for the rule.",
            )
        total = sum(group_counts.values()) + sum(accepted.values())
        require(total > 0, f"{identifier}: empty team group.")
        for severity in SEVERITIES:
            aggregate[severity] += group_counts[severity]
            accepted_total[severity] += accepted[severity]
        samples = group.get("samples")
        require(
            isinstance(samples, list) and 0 < len(samples) <= total,
            f"{identifier}: team samples required.",
        )
        for sample in samples:
            created = timestamp(sample.get("created_at"), "team sample created_at")
            resolved = timestamp(sample.get("resolved_at"), "team sample resolved_at")
            require(
                created <= resolved and data.start < resolved <= data.resolved_through,
                f"{sample.get('id')}: team closure is outside the reporting interval.",
            )
        validate_assignments(group.get("assignments"), total, f"{identifier}.team_assignments")
        entries = group["assignments"]["entries"]
        require(
            all(e["id"] in ids and ids[e["id"]] == e["name"] for e in entries),
            f"{identifier}: team closures may only list team members.",
        )
        require(
            sum(e["count"] for e in entries) == total,
            f"{identifier}: every team closure needs a team assignee.",
        )
        resolution = group.get("resolution")
        if resolution is not None:
            require(isinstance(resolution, dict), f"{identifier}: invalid resolution evidence.")
            timestamp(resolution.get("verified_at"), f"{identifier}.resolution.verified_at")
            reasons = resolution.get("reasons")
            require(
                isinstance(reasons, dict)
                and all(type(n) is int and n > 0 for n in reasons.values())
                and sum(reasons.values()) == total,
                f"{identifier}: resolution reasons must count every team closure exactly once.",
            )
            for change in resolution.get("changes", []):
                text(change.get("text"), f"{identifier}.resolution.change")
                require(
                    type(change.get("count")) is int and change["count"] > 0,
                    f"{identifier}: resolution change counts must be positive.",
                )
            require(
                isinstance(resolution.get("risks"), list)
                and all(isinstance(r, str) and r for r in resolution["risks"]),
                f"{identifier}: resolution risks must be a list of risk names.",
            )
    require(
        all(aggregate[s] <= payload["resolved"][s] for s in SEVERITIES),
        "team_resolved exceeds tenant resolved counts.",
    )
    require(
        all(accepted_total[s] <= tenant_accepted[s] for s in SEVERITIES),
        "team_resolved accepted risk exceeds tenant accepted-risk counts.",
    )


def cutoff_counts(rows: list[dict], start: datetime, cutoff: datetime) -> dict[str, dict[str, int]]:
    """Open / in-progress backlog at ``cutoff`` and closures in (start, cutoff].

    Computed from complete issue rows.

    ``rows`` use the workbook CSV columns (Issue ID, Severity, Status, Created At, Resolved Time,
    optional Status Changed At). Datetimes are naive UTC. Anything after the cutoff is ignored.
    """
    result = {
        key: dict.fromkeys(DISPLAY_SEVERITIES, 0)
        for key in ("open", "in_progress", "resolved", "accepted")
    }
    for row in rows:
        severity = row.get("Severity", "").strip().upper()
        if severity not in DISPLAY_SEVERITIES:
            continue
        status = status_at(row, cutoff)
        if status in ("OPEN", "IN_PROGRESS"):
            result["open"][severity] += 1
            if status == "IN_PROGRESS":
                result["in_progress"][severity] += 1
        elif status is not None and _parse_dt(row.get("Resolved Time")) > start:
            result["resolved" if status == "RESOLVED" else "accepted"][severity] += 1
    return result


def load_snapshot(path: Path) -> GovernanceData:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise DashboardError(f"Invalid governance JSON: {path}: {exc}") from exc
    require(
        isinstance(payload, dict)
        and type(payload.get("schema_version")) is int
        and payload["schema_version"] == 1,
        "Governance snapshot schema_version must be 1.",
    )
    try:
        require(
            payload["scope"]["kind"] == "TENANT",
            "Only explicitly approved tenant-wide scope is supported.",
        )
        text(payload["scope"]["name"], "scope.name")
        text(payload["scope"]["tenant_id"], "scope.tenant_id")
        require(
            set(payload["scope"]["issue_types"]) == ISSUE_TYPES,
            "Capture all five issue types consistently; partial type scopes are not supported.",
        )
        period = payload["period"]
        data = GovernanceData(
            payload,
            *(
                timestamp(period[k], f"period.{k}")
                for k in (
                    "start_exclusive",
                    "end_inclusive",
                    "resolved_through",
                    "collected_from",
                    "collected_through",
                )
            ),
        )
        require(
            data.start < data.resolved_through <= data.end, "Invalid resolution reporting interval."
        )
        require(
            data.start < data.collected_from <= data.collected_through,
            "Invalid live collection interval.",
        )
        require(
            data.collected_through <= datetime.now(UTC), "Collection cannot be dated in the future."
        )
        approval = period.get("final_approval")
        if approval is not None:
            # Account owner chose to publish data pulled shortly before the cutoff as the
            # final period-end report.
            require(isinstance(approval, dict), "period.final_approval must be an object.")
            text(approval.get("approved_by"), "period.final_approval.approved_by")
            text(approval.get("reason"), "period.final_approval.reason")
            timestamp(approval.get("approved_at"), "period.final_approval.approved_at")
            require(
                data.resolved_through == data.end and data.backlog_as_of == data.end,
                "An approved final report must be dated exactly at the period end.",
            )
            require(
                data.end - timedelta(days=3) <= data.collected_through <= data.end,
                "Approved early finalisation needs data collected within 3 days "
                "before the period end.",
            )
        else:
            require(
                data.resolved_through <= data.collected_through,
                "Resolution coverage cannot extend beyond collection.",
            )
            require(
                data.backlog_as_of <= data.collected_through,
                "Backlog counts cannot be dated after collection.",
            )
        require(
            data.backlog_as_of <= data.end,
            f"Counts must be as of {data.end:%b %d, %Y} EOD or earlier; "
            "changes after the period end belong to the next report. "
            "Rebuild counts with cutoff_counts() and set period.backlog_as_of.",
        )
        require(data.start.date() < data.end.date(), "Reporting dates must span different days.")
        for field in ("open", "in_progress", "resolved"):
            counts(payload[field], field)
        if "accepted" in payload:
            counts(payload["accepted"], "accepted")
        require(
            all(payload["in_progress"][s] <= payload["open"][s] for s in SEVERITIES),
            "IN_PROGRESS must be a subset of OPEN + IN_PROGRESS.",
        )
        prior = payload["prior"]
        require(
            prior["date"] == data.start.date().isoformat(), "Prior date must match period start."
        )
        text(prior["source"], "prior.source")
        require(
            isinstance(prior["source_sha256"], str) and len(prior["source_sha256"]) == 64,
            "Prior source SHA256 is required.",
        )
        counts(prior["open"], "prior.open", DISPLAY_SEVERITIES)
        for field in ("security_score", "hipaa", "hitrust"):
            metric(payload[field], field)
            metric(prior[field], f"prior.{field}")
        require(isinstance(payload["limitations"], list), "limitations must be an explicit list.")
        for item in payload["limitations"]:
            text(item, "limitation")
        validate_groups(payload, "resolved_groups", "resolved", data)
        validate_groups(payload, "in_progress_groups", "in_progress", data)
        if "team_resolved" in payload:
            validate_team_resolved(payload, data)
        gaps = payload.get("assignment_gaps", [])
        deferred = payload.get("deferred_in_progress", [])
        progress_ids = {g["id"] for g in payload["in_progress_groups"]["groups"]}
        require(isinstance(deferred, list), "deferred_in_progress must be a list.")
        for entry in deferred:
            require(
                isinstance(entry, dict) and entry.get("id") in progress_ids,
                f"deferred_in_progress entry {entry!r} must name an in-progress rule group.",
            )
            text(entry.get("source"), "deferred_in_progress.source")
        statuses_by_rule = payload.get("rule_status", [])
        require(isinstance(statuses_by_rule, list), "rule_status must be a list.")
        rule_status_ids = set()
        for entry in statuses_by_rule:
            require(
                isinstance(entry, dict) and entry.get("id") in progress_ids,
                f"rule_status entry {entry!r} must name an in-progress rule group.",
            )
            require(entry["id"] not in rule_status_ids, f"Duplicate rule_status for {entry['id']}.")
            rule_status_ids.add(entry["id"])
            require(
                "status" in entry or "next_step" in entry,
                f"{entry['id']}: rule_status needs a status and/or next_step.",
            )
            if "status" in entry:
                status = text(entry["status"], "rule_status.status")
                require(
                    len(status) <= 220,
                    f"{entry['id']}: rule status must be at most 220 characters.",
                )
            if "next_step" in entry:
                step = text(entry["next_step"], "rule_status.next_step")
                require(
                    len(step) <= 200, f"{entry['id']}: next step must be at most 200 characters."
                )
            text(entry.get("source"), "rule_status.source")
        wording = payload.get("closure_wording", [])
        team_ids = {g["id"] for g in payload.get("team_resolved", {}).get("groups", [])}
        require(isinstance(wording, list), "closure_wording must be a list.")
        seen_wording = set()
        for entry in wording:
            require(
                isinstance(entry, dict) and entry.get("id") in team_ids,
                f"closure_wording entry {entry!r} must name a team-resolved rule group.",
            )
            require(
                entry["id"] not in seen_wording, f"Duplicate closure_wording for {entry['id']}."
            )
            seen_wording.add(entry["id"])
            require(
                "changed" in entry or "risk" in entry,
                f"{entry['id']}: closure_wording needs changed and/or risk text.",
            )
            for key in ("changed", "risk"):
                if key in entry:
                    value = text(entry[key], f"closure_wording.{key}")
                    require(
                        len(value) <= 200,
                        f"{entry['id']}: closure wording must be at most 200 characters.",
                    )
            text(entry.get("source"), "closure_wording.source")
            require(
                timestamp(entry.get("as_of"), "closure_wording.as_of") <= datetime.now(UTC),
                f"{entry['id']}: closure wording cannot be dated in the future.",
            )
        statuses = payload.get("owner_status", [])
        require(isinstance(statuses, list), "owner_status must be a list.")
        status_names = set()
        for entry in statuses:
            require(isinstance(entry, dict), "owner_status entries must be objects.")
            name = text(entry.get("name"), "owner_status.name")
            require(name not in status_names, f"Duplicate owner_status for {name}.")
            status_names.add(name)
            status = text(entry.get("status"), "owner_status.status")
            require(
                "\n" not in status and len(status) <= 80,
                f"{name}: owner status must be one short line.",
            )
            text(entry.get("source"), "owner_status.source")
            require(
                timestamp(entry.get("as_of"), "owner_status.as_of") <= datetime.now(UTC),
                f"{name}: owner status cannot be dated in the future.",
            )
        require(isinstance(gaps, list), "assignment_gaps must be a list.")
        seen_gaps = set()
        for gap in gaps:
            issue_id = text(gap.get("issue_id"), "assignment_gaps.issue_id")
            require(issue_id not in seen_gaps, f"Duplicate assignment gap {issue_id}.")
            seen_gaps.add(issue_id)
            text(gap.get("rule_name"), "assignment_gaps.rule_name")
            text(gap.get("basis"), "assignment_gaps.basis")
            require(
                gap.get("status") in {"IN_PROGRESS", "RESOLVED", "REJECTED"},
                "Assignment gaps cover IN_PROGRESS, RESOLVED or REJECTED issues only.",
            )
            require(
                (gap.get("suggested_owner") is None) == (gap.get("suggested_owner_id") is None),
                f"{issue_id}: suggested owner name and ID must be given together.",
            )
        require(
            payload.get("assignment_scope", "STATUS") in {"STATUS", "RULE"},
            "assignment_scope must be STATUS or RULE.",
        )
        extra = payload.get("rule_assignment_evidence", [])
        require(isinstance(extra, list), "rule_assignment_evidence must be a list.")
        for record in extra:
            text(record["id"], "rule_assignment_evidence.id")
            require(
                record["status"] in {"OPEN", "IN_PROGRESS", "RESOLVED"},
                "Rule assignee evidence must come from OPEN, IN_PROGRESS or RESOLVED findings.",
            )
            require(
                type(record["total_count"]) is int and record["total_count"] > 0,
                "Rule evidence total_count must be a positive integer.",
            )
            validate_assignments(
                record["assignments"], record["total_count"], "rule_assignment_evidence"
            )
        data.rule_assignees()
        return data
    except (KeyError, TypeError, AttributeError) as exc:
        raise DashboardError(f"Malformed governance snapshot: {exc}") from exc
