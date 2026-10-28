"""Generic campaign rules: collection planner, stall detection, lifecycle and wording checks.

Never calls Wiz and never sends or changes anything. A campaign is a repeated, fixed-scope
collection of vulnerability findings for a configurable set of vulnerability IDs. Nothing
client-specific lives here: IDs, thresholds and group labels are supplied by the operator.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

ALL_STATUSES = ["OPEN", "IN_PROGRESS", "RESOLVED", "REJECTED"]
GROUPED_KINDS = {
    "all": ALL_STATUSES,
    "remaining": ["OPEN", "IN_PROGRESS"],
    "resolved": ["RESOLVED"],
    "rejected": ["REJECTED"],
}
FINDING_PAGE_SIZE = 20  # Wiz maximum; never raise.
GROUPED_PAGE_SIZE = 20
RESOURCE_BATCH_SIZE = 40
# No total time limit while data keeps arriving. A run is abandoned only when it is stuck.
DEFAULT_STALL_SECONDS = 15 * 60
MAX_CALL_ATTEMPTS = 3
EVIDENCE_PREFIXES = ("catalog-", "grouped-", "findings-", "resources-")
RESPONSE_KEYS = {
    "list_vulnerability_findings_grouped": "vulnerabilityFindingsGroupedByValues",
    "list_vulnerability_findings": "vulnerabilityFindings",
    "list_cloud_resources": "cloudResourcesV2",
    "get_vulnerability_catalog": "vulnerabilityByExternalId",
}
AUTH_MARKERS = ("401", "unauthorized", "oauth", "www-authenticate", "invalid_token")
COUNT_SCOPES = {
    "remaining": "Total Remaining Un-Resolved Findings",
    "resolved": "Total Resolved Findings",
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


@dataclass(frozen=True)
class CampaignConfig:
    """Operator-supplied scope. There are deliberately no default vulnerability IDs."""

    vulnerability_ids: tuple[str, ...]
    stall_seconds: int = DEFAULT_STALL_SECONDS
    group_by: tuple[str, ...] = ("CLOUD_PLATFORM",)

    def __post_init__(self) -> None:
        ids = self.vulnerability_ids
        require(bool(ids), "Campaign needs at least one vulnerability ID; there are no defaults.")
        require(
            all(isinstance(i, str) and i.strip() for i in ids) and len(set(ids)) == len(ids),
            "Vulnerability IDs must be unique nonempty strings.",
        )
        require(
            type(self.stall_seconds) is int and self.stall_seconds > 0,
            "Stall threshold must be a positive integer number of seconds.",
        )
        require(
            bool(self.group_by) and all(isinstance(g, str) and g for g in self.group_by),
            "group_by must name at least one field.",
        )


def load_config(
    path: Path | None = None,
    vulnerability_ids: Sequence[str] = (),
    stall_seconds: int | None = None,
) -> CampaignConfig:
    data = read_json(path) if path else {}
    require(isinstance(data, dict), "Campaign config must be a JSON object.")
    ids = list(vulnerability_ids) or data.get("vulnerability_ids", [])
    return CampaignConfig(
        tuple(ids),
        stall_seconds
        if stall_seconds is not None
        else data.get("stall_seconds", DEFAULT_STALL_SECONDS),
        tuple(data.get("group_by", ("CLOUD_PLATFORM",))),
    )


# --- JSON helpers: UTF-8 without BOM out; BOM tolerated in ---------------------------------


def read_json(path: Path | str):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def _inside(path: Path, directory: Path) -> bool:
    return directory.resolve() == path.resolve() or directory.resolve() in path.resolve().parents


def write_json(path: Path | str, value, *, staging: Path | str | None = None) -> None:
    """Write UTF-8 JSON with no BOM. Helper/param/response files must live outside staging."""
    path = Path(path)
    if staging is not None:
        require(
            not _inside(path, Path(staging)),
            "Helper/param/response JSON must be written outside the staging directory.",
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(value, indent=2, ensure_ascii=True) + "\n").encode("utf-8"))


def utc_now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def parse_utc(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    require(
        result.utcoffset() is not None and result.utcoffset().total_seconds() == 0,
        "Campaign timestamps must be UTC.",
    )
    return result


def iso(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


# --- Auth and failure rules ---------------------------------------------------------------


def classify_failure(status: int | str | None = None, message: str = "") -> str:
    """HTTP 401 / OAuth challenge means stop and ask the operator to reconnect."""
    haystack = f"{status or ''} {message}".casefold()
    if any(marker in haystack for marker in AUTH_MARKERS):
        return "stop_reconnect"
    return "retry"


RECONNECT_REASON = (
    "Wiz returned HTTP 401 / an OAuth challenge. Stop and ask the operator to reconnect the Wiz "
    "connection. Do not start or continue collection until a catalog call succeeds."
)


def _call_key(tool: str, params: dict) -> str:
    return tool + ":" + hashlib.sha256(json.dumps(params, sort_keys=True).encode()).hexdigest()[:16]


def record_failure(
    directory: Path | str,
    tool: str,
    params: dict,
    *,
    status: int | str | None = None,
    message: str = "",
) -> dict:
    """Count a failed call. 401/OAuth stops; the same call failing 3 times aborts the run."""
    directory = Path(directory)
    if classify_failure(status, message) == "stop_reconnect":
        return {"action": "stop_reconnect", "reason": RECONNECT_REASON}
    path = directory / "attempts.json"
    attempts = read_json(path) if path.is_file() else {}
    key = _call_key(tool, params)
    attempts[key] = attempts.get(key, 0) + 1
    write_json(path, attempts)
    if attempts[key] >= MAX_CALL_ATTEMPTS:
        return {
            "action": "abort_unable_to_fetch",
            "attempts": attempts[key],
            "reason": _unable(tool),
        }
    return {"action": "retry", "attempts": attempts[key], "max_attempts": MAX_CALL_ATTEMPTS}


def _unable(tool: str) -> str:
    return (
        f"{tool} failed {MAX_CALL_ATTEMPTS} times: unable to fetch. Abort this run, report it, "
        "never publish a partial pack, and retry only in a new staging directory."
    )


def _clear_failure(directory: Path, tool: str, params: dict) -> None:
    path = directory / "attempts.json"
    if path.is_file():
        attempts = read_json(path)
        if attempts.pop(_call_key(tool, params), None) is not None:
            write_json(path, attempts)


# --- Staging ------------------------------------------------------------------------------


def start(config: CampaignConfig, base: Path | str, now: datetime | None = None) -> dict:
    """Begin a new run in a fresh directory. Each run has its own directory; never reuse one."""
    now = now or utc_now()
    stamp = now.strftime("%Y-%m-%dT%H-%M-%SZ")
    directory = Path(base) / f"staging-{stamp}"
    directory.mkdir(parents=True, exist_ok=False)
    write_json(
        directory / "meta.json",
        {
            "schema_version": 1,
            "run_id": stamp,
            "created_at": iso(now),
            "vulnerability_ids": list(config.vulnerability_ids),
            "note": "One staging directory per run. Never stitch runs or reuse old inventory.",
        },
    )
    return {"dir": str(directory), "next": next_call(config, directory, now=now)}


def load_staging(config: CampaignConfig, directory: Path | str) -> tuple[Path, dict, dict]:
    directory = Path(directory)
    require(directory.is_dir(), "Collection directory does not exist.")
    meta_path = directory / "meta.json"
    require(meta_path.is_file(), "Not a campaign staging directory (meta.json missing).")
    meta = read_json(meta_path)
    require(
        set(meta["vulnerability_ids"]) == set(config.vulnerability_ids),
        "Vulnerability scope differs from this staging directory.",
    )
    files = {}
    for path in sorted(directory.glob("*.json")):
        if path.name.startswith(EVIDENCE_PREFIXES):
            record = read_json(path)
            require(
                record.get("run_id") == meta["run_id"],
                f"{path.name} belongs to another run; never stitch pages across runs.",
            )
            files[path.name] = record
    return directory, meta, files


def _grouped_kind(status: list[str]) -> str:
    for name, values in GROUPED_KINDS.items():
        if set(status) == set(values):
            return name
    raise ValueError("Grouped query statuses must be all, remaining, resolved or rejected only.")


def _by_tool(files: dict, tool: str) -> list[tuple[str, dict]]:
    return [(n, r) for n, r in files.items() if r["request"]["tool_name"] == tool]


def _pages(files: dict, prefix: str) -> list[tuple[str, dict]]:
    return [(n, files[n]) for n in sorted(files) if n.startswith(prefix)]


def _asset_ids(pages: list) -> list[str]:
    seen: dict[str, None] = {}
    for _, record in pages:
        for node in record["response"]["vulnerabilityFindings"]["nodes"]:
            seen.setdefault(node["vulnerableAsset"]["id"], None)
    return list(seen)


def _batches(values: list, size: int) -> list[list]:
    return [values[i : i + size] for i in range(0, len(values), size)]


def seconds_since_last_save(meta: dict, files: dict, now: datetime | None = None) -> int:
    times = [parse_utc(r["observed_at"]) for r in files.values()] or [parse_utc(meta["created_at"])]
    return max(0, int(((now or utc_now()) - max(times)).total_seconds()))


def next_call(config: CampaignConfig, directory: Path | str, now: datetime | None = None) -> dict:
    """Return the next read-only call to make. Order: catalogs, grouped, one finding stream,
    then exact-ID resource batches. A run is aborted only when stuck or failing."""
    directory, meta, files = load_staging(config, directory)
    attempts_path = directory / "attempts.json"
    if attempts_path.is_file():
        for key, count in read_json(attempts_path).items():
            if count >= MAX_CALL_ATTEMPTS:
                return {
                    "action": "abort_unable_to_fetch",
                    "reason": _unable(key.split(":")[0]),
                }
    idle = seconds_since_last_save(meta, files, now)
    result = _plan(config, directory, files, idle)
    if result["action"] != "assemble" and idle > config.stall_seconds:
        return {
            "action": "abort_stalled",
            "seconds_since_last_save": idle,
            "stall_threshold_seconds": config.stall_seconds,
            "reason": (
                f"No evidence saved for {idle} seconds (limit {config.stall_seconds}) and the "
                "collection is incomplete: fetching is stuck. Abandon this directory, start a "
                "new staging directory, do not stitch pages from this run and do not reuse a "
                "previous day's inventory."
            ),
        }
    return result


def _plan(config: CampaignConfig, directory: Path, files: dict, idle: int) -> dict:
    ids = list(config.vulnerability_ids)
    common = {"seconds_since_last_save": idle, "stall_threshold_seconds": config.stall_seconds}

    def call(tool: str, params: dict) -> dict:
        return {"tool_name": tool, "parameters": params}

    def batch(calls: list, reason: str) -> dict:
        return {
            "action": "wiz-execute-batch",
            "calls": calls,
            "reason": reason,
            "save_note": (
                "Run the calls in parallel. Write params/response JSON as UTF-8 without BOM "
                "OUTSIDE the staging directory, then save each one."
            ),
            **common,
        }

    have = {
        r["request"]["parameters"]["external_id"]
        for _, r in _by_tool(files, "get_vulnerability_catalog")
    }
    missing = [i for i in ids if i not in have]
    if missing:
        return batch(
            [call("get_vulnerability_catalog", {"external_id": i}) for i in missing],
            "Retain every catalog record first, in parallel.",
        )
    saved = {
        _grouped_kind(r["request"]["parameters"]["status"])
        for _, r in _by_tool(files, "list_vulnerability_findings_grouped")
    }
    grouped = [
        call(
            "list_vulnerability_findings_grouped",
            {
                "vulnerability_external_ids": ids,
                "status": status,
                "group_by": list(config.group_by),
                "first": GROUPED_PAGE_SIZE,
            },
        )
        for kind, status in GROUPED_KINDS.items()
        if kind not in saved
    ]
    if grouped:
        return batch(grouped, "Run the per-status grouped queries in parallel.")
    pages = _pages(files, "findings-")
    last = pages[-1][1]["response"]["vulnerabilityFindings"]["pageInfo"] if pages else None
    if last is None or last["hasNextPage"]:
        params = {
            "vulnerability_external_ids": ids,
            "status": ALL_STATUSES,
            "first": FINDING_PAGE_SIZE,
        }
        if last:
            params["after"] = last["endCursor"]
        return {
            "action": "wiz-execute",
            "tool_name": "list_vulnerability_findings",
            "parameters": params,
            "reason": "ONE finding stream over all statuses; never split remaining and resolved.",
            **common,
        }
    planned = _batches(_asset_ids(pages), RESOURCE_BATCH_SIZE)
    done = {n for n, _ in _pages(files, "resources-")}
    todo = [
        call(
            "list_cloud_resources",
            {"resource_id": batch_ids, "include_deleted": True, "first": RESOURCE_BATCH_SIZE},
        )
        for index, batch_ids in enumerate(planned)
        if f"resources-{index:02d}.json" not in done
    ]
    if todo:
        return batch(
            todo, "Exact-ID resource lookups in parallel batches, including deleted resources."
        )
    return {
        "action": "assemble",
        "reason": f"Evidence is complete. Run: wizexpert campaign assemble --dir {directory}",
        **common,
    }


def _response_body(raw: dict, tool: str) -> dict:
    key = RESPONSE_KEYS[tool]
    if "request" in raw and "response" in raw:
        raw = raw["response"]
    return {key: raw.get(key, raw)}


def save(
    config: CampaignConfig,
    directory: Path | str,
    tool: str,
    params: dict,
    response: dict,
    now: datetime | None = None,
) -> dict:
    directory, meta, files = load_staging(config, directory)
    current = next_call(config, directory, now=now)
    require(
        current["action"] not in {"abort_stalled", "abort_unable_to_fetch"},
        current.get("reason", ""),
    )
    ids = list(config.vulnerability_ids)
    if tool == "get_vulnerability_catalog":
        require(
            set(params) == {"external_id"} and params["external_id"] in ids,
            "Catalog vulnerability scope changed.",
        )
        name = f"catalog-{params['external_id']}.json"
    elif tool == "list_vulnerability_findings_grouped":
        require(
            set(params) == {"vulnerability_external_ids", "status", "group_by", "first"}
            and params["vulnerability_external_ids"] == ids
            and params["group_by"] == list(config.group_by)
            and params["first"] == GROUPED_PAGE_SIZE,
            "Unexpected grouped query scope.",
        )
        name = f"grouped-{_grouped_kind(params['status'])}.json"
    elif tool == "list_vulnerability_findings":
        pages = _pages(files, "findings-")
        after = None
        if pages:
            page_info = pages[-1][1]["response"]["vulnerabilityFindings"]["pageInfo"]
            require(page_info["hasNextPage"], "Finding stream already complete.")
            after = page_info["endCursor"]
        require(
            set(params) <= {"vulnerability_external_ids", "status", "first", "after"}
            and params["vulnerability_external_ids"] == ids,
            "Finding scope changed.",
        )
        require(
            set(params["status"]) == set(ALL_STATUSES),
            "Paginate every status in one stream; do not split remaining/resolved streams.",
        )
        require(params["first"] == FINDING_PAGE_SIZE, "Finding page size must be 20 (Wiz maximum).")
        require(params.get("after") == after, "Broken finding pagination cursor.")
        name = f"findings-{len(pages):02d}.json"
    elif tool == "list_cloud_resources":
        pages = _pages(files, "findings-")
        require(
            pages
            and not pages[-1][1]["response"]["vulnerabilityFindings"]["pageInfo"]["hasNextPage"],
            "Finish finding pagination before resource lookups.",
        )
        planned = _batches(_asset_ids(pages), RESOURCE_BATCH_SIZE)
        index = next((i for i, b in enumerate(planned) if b == params.get("resource_id")), None)
        require(index is not None, "Resource batch IDs differ from the planned exact-ID set.")
        require(
            set(params) == {"resource_id", "include_deleted", "first"}
            and params["include_deleted"] is True
            and params["first"] == RESOURCE_BATCH_SIZE,
            "Resource lookups need include_deleted=true and a batch size of 40.",
        )
        name = f"resources-{index:02d}.json"
    else:
        raise ValueError("Unsupported evidence tool: " + tool)
    require(name not in files, f"Already saved: {name}")
    body = _response_body(response, tool)
    _validate_response(tool, params, body)
    record = {
        "run_id": meta["run_id"],
        "observed_at": iso(now or utc_now()),
        "request": {"tool_name": tool, "parameters": params},
        "response": body,
    }
    write_json(directory / name, record)
    _clear_failure(directory, tool, params)
    return {"saved": name, "next": next_call(config, directory, now=now)}


def _validate_response(tool: str, params: dict, body: dict) -> None:
    data = body[RESPONSE_KEYS[tool]]
    if tool == "get_vulnerability_catalog":
        require(
            bool(data) and data.get("externalId") == params["external_id"],
            "Missing or mismatched catalog record.",
        )
        return
    require("nodes" in data and "pageInfo" in data and "totalCount" in data, "Response incomplete.")
    if tool == "list_vulnerability_findings":
        require(len(data["nodes"]) <= FINDING_PAGE_SIZE, "Oversized finding page.")
        return
    require(not data["pageInfo"]["hasNextPage"], "Incomplete pagination.")
    if tool == "list_cloud_resources":
        require(
            {n["id"] for n in data["nodes"]} == set(params["resource_id"]),
            "Resource lookup incomplete.",
        )
    else:
        require(data["totalCount"] == len(data["nodes"]), "Incomplete grouped pagination.")


def assemble(config: CampaignConfig, directory: Path | str, out: Path | str) -> dict:
    """Verify a complete single-run collection and write a manifest outside staging."""
    directory, meta, files = load_staging(config, directory)
    plan = next_call(config, directory)
    require(plan["action"] == "assemble", plan.get("reason") or json.dumps(plan))
    findings = [
        n
        for _, r in _pages(files, "findings-")
        for n in r["response"]["vulnerabilityFindings"]["nodes"]
    ]
    for kind, statuses in GROUPED_KINDS.items():
        record = files[f"grouped-{kind}.json"]
        nodes = record["response"]["vulnerabilityFindingsGroupedByValues"]["nodes"]
        expected = sum(n["analytics"]["totalFindingCount"] for n in nodes)
        collected = sum(1 for f in findings if f["status"] in statuses)
        require(
            expected == collected,
            f"{kind}: finding totals changed between queries; recollect in a new directory.",
        )
    times = [parse_utc(r["observed_at"]) for r in files.values()]
    manifest = {
        "schema_version": 1,
        "run_id": meta["run_id"],
        "vulnerability_ids": list(config.vulnerability_ids),
        "observed_from": iso(min(times)),
        "observed_to": iso(max(times)),
        "reporting_timezone": "UTC",
        "finding_count": len(findings),
        "asset_count": len(_asset_ids(_pages(files, "findings-"))),
        "files": {
            name: hashlib.sha256((directory / name).read_bytes()).hexdigest()
            for name in sorted(files)
        },
    }
    write_json(out, manifest, staging=directory)
    return manifest


# --- Lifecycle ----------------------------------------------------------------------------


def lifecycle(state: dict, mode: str = "manual") -> dict:
    """Decide whether a (scheduled or manual) run should refresh or stop. Never sends or mutates."""
    require(mode in {"manual", "scheduled"}, "Mode must be manual or scheduled.")
    require(
        state.get("status") in {"active", "closed"},
        "Campaign state status must be active or closed.",
    )
    targets = state.get("vulnerability_ids")
    require(
        isinstance(targets, list) and bool(targets),
        "Campaign state needs its target vulnerability IDs.",
    )
    patched = state.get("fully_patched_ids", [])
    gate = state.get("closure_gate", {})
    gate_met = isinstance(gate, dict) and gate.get("met") is True
    all_patched = set(targets) <= set(patched)
    if gate_met:
        require(
            all_patched
            and isinstance(gate.get("confirmed_by"), str)
            and bool(gate["confirmed_by"].strip()),
            "Closure gate marked met without every target fully patched and a named confirmation.",
        )
    safety = {"send_email": False, "mutate_wiz_or_cloud": False}
    if state["status"] == "closed" or gate_met:
        return {
            "action": "stop",
            "reason": "Campaign is closed or its closure gate is met. Do not refresh or restart.",
            "prepare_final_closure_update": state["status"] != "closed",
            "disable_automation": True,
            "tell_owner": "Disable the scheduled refresh automation for this campaign.",
            **safety,
        }
    return {
        "action": "refresh",
        "reason": "Campaign is active: refresh daily until all targets are fully patched and the "
        "closure gate is met.",
        "prepare_drafts_only": mode == "scheduled",
        "disable_automation": False,
        **safety,
    }


# --- Workbook count notes and sheet rules -------------------------------------------------


def finding_count_note(rows: Sequence | int, scope: str) -> str:
    require(scope in COUNT_SCOPES, "Count note is remaining or resolved only.")
    count = rows if isinstance(rows, int) else len(rows)
    return f"{COUNT_SCOPES[scope]} = {count}"


def check_campaign_workbook(book, spec: dict, path: Path | None = None) -> None:
    """Count notes under the finding tables; no per-group sheets or workbooks.

    spec = {"count_sheets": {"<sheet>": "remaining"|"resolved"}, "other_sheets": [...],
            "group_names": [...]}
    """
    counts = spec.get("count_sheets")
    require(isinstance(counts, dict) and bool(counts), "Campaign workbook spec needs count_sheets.")
    allowed = set(counts) | set(spec.get("other_sheets", []))
    require(
        set(book.sheetnames) <= allowed,
        "Campaign workbooks must not contain extra or per-group sheets.",
    )
    groups = [g.casefold() for g in spec.get("group_names", []) if g]
    for title in book.sheetnames:
        require(
            not any(g in title.casefold() for g in groups),
            "Per-group sheets are not allowed in a campaign workbook.",
        )
    if path is not None:
        require(
            not any(g in path.name.casefold() for g in groups),
            "Per-group campaign workbooks are not allowed.",
        )
    for title, scope in counts.items():
        require(title in book.sheetnames, f"Missing count sheet: {title}")
        sheet = book[title]
        last = sheet.max_row
        require(last >= 3, f"{title}: finding table with count note is missing.")
        blank_above = all(c.value is None for c in sheet[last - 1])
        require(blank_above, f"{title}: a blank row must precede the count note.")
        rows = sum(
            1
            for r in sheet.iter_rows(min_row=2, max_row=last - 2, values_only=True)
            if any(v is not None for v in r)
        )
        require(
            sheet.cell(last, 1).value == finding_count_note(rows, scope),
            f"{title}: bottom note must read exactly {finding_count_note(rows, scope)!r}.",
        )


# --- Wording ------------------------------------------------------------------------------

_UTC_CUTOFF = re.compile(r"\b\d{1,2}:\d{2}(?::\d{2})?\s*UTC\b|\b\d{1,2}:\d{2}(?::\d{2})?Z\b")
_RESOLVED_QUALIFIER = re.compile(r"resolved in wiz|wiz lifecycle|wiz[- ]resolved|wiz status", re.I)
_PARTIAL = re.compile(r"\b(?:reconstructed|partial[- ]day|partial observation|intraday)\b", re.I)
_VERIFIED_PATCH = re.compile(r"(?<!not )(?<!no )\bverified (?:patch\w*|remediat\w+|fix\w*)", re.I)


def campaign_wording_errors(
    text: str, *, partial_day: bool = False, reconstructed: bool = False
) -> list[str]:
    errors = []
    if re.search(r"\brejected\b", text, re.I):
        errors.append("Campaign updates must not mention Rejected findings.")
    if re.search(r"\bresolved\b", text, re.I) and not _RESOLVED_QUALIFIER.search(text):
        errors.append(
            "Resolved must be qualified as the Wiz lifecycle status (for example 'Resolved in "
            "Wiz'), not as independently verified patch completion."
        )
    if _VERIFIED_PATCH.search(text):
        errors.append("Do not claim verified patching/remediation from Wiz lifecycle status.")
    if (partial_day or reconstructed or _PARTIAL.search(text)) and not _UTC_CUTOFF.search(text):
        errors.append(
            "Reconstructed data points and partial-day observations must be qualified with the "
            "UTC cutoff time."
        )
    return errors


def campaign_collection_flags(info: object) -> list[str]:
    """Flags for a collection manifest's optional `campaign_collection` block."""
    if not isinstance(info, dict):
        return ["Campaign collection block is missing or invalid."]
    flags = []
    dirs = info.get("staging_dirs")
    if not (isinstance(dirs, list) and len(dirs) == 1):
        flags.append("Campaign pack must come from exactly one staging directory (never stitched).")
    if info.get("complete") is not True:
        flags.append(
            "Partial pack: collection is incomplete. Never publish; restart or switch model."
        )
    if info.get("reused_previous_inventory") is not False:
        flags.append("A previous day's inventory must never be reused for new counts.")
    if info.get("auth_ok") is not True:
        flags.append("Wiz authentication was not confirmed before collection started.")
    return flags


# --- CLI ----------------------------------------------------------------------------------

PLAN_ORDER = [
    "1. Catalog record for every configured vulnerability ID (parallel).",
    "2. Grouped queries per status group: all, remaining, resolved, rejected (parallel).",
    "3. ONE finding stream over OPEN, IN_PROGRESS, RESOLVED, REJECTED at page size 20.",
    "4. Exact-ID resource lookups in parallel batches of 40, include_deleted=true.",
    "5. Assemble, validate, then generate drafts. Never send or change anything.",
]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="wizexpert campaign", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    def scoped(name: str, with_dir: bool = True):
        command = sub.add_parser(name)
        command.add_argument("--config", type=Path)
        command.add_argument("--vuln-id", action="append", default=[], dest="vuln_ids")
        command.add_argument("--stall-seconds", type=int)
        if with_dir:
            command.add_argument("--dir", type=Path, required=True)
        return command

    sub.add_parser("plan")
    scoped("start", with_dir=False).add_argument("--base", type=Path, required=True)
    scoped("next")
    saver = scoped("save")
    saver.add_argument("--tool", required=True)
    saver.add_argument("--params-file", type=Path, required=True)
    saver.add_argument("--response-file", type=Path, required=True)
    failer = scoped("fail")
    failer.add_argument("--tool", required=True)
    failer.add_argument("--params-file", type=Path, required=True)
    failer.add_argument("--status")
    failer.add_argument("--message", default="")
    scoped("assemble").add_argument("--out", type=Path, required=True)
    life = sub.add_parser("lifecycle")
    life.add_argument("--state", type=Path, required=True)
    life.add_argument("--mode", choices=("manual", "scheduled"), default="manual")
    args = parser.parse_args(argv)
    try:
        if args.command == "plan":
            result = {"order": PLAN_ORDER, "stall_seconds_default": DEFAULT_STALL_SECONDS}
        elif args.command == "lifecycle":
            result = lifecycle(read_json(args.state), args.mode)
        else:
            config = load_config(args.config, args.vuln_ids, args.stall_seconds)
            if args.command == "start":
                result = start(config, args.base)
            elif args.command == "next":
                result = next_call(config, args.dir)
            elif args.command == "save":
                for helper in (args.params_file, args.response_file):
                    require(
                        not _inside(helper, args.dir),
                        "Helper/param/response JSON must be outside the staging directory.",
                    )
                result = save(
                    config,
                    args.dir,
                    args.tool,
                    read_json(args.params_file),
                    read_json(args.response_file),
                )
            elif args.command == "fail":
                result = record_failure(
                    args.dir,
                    args.tool,
                    read_json(args.params_file),
                    status=args.status,
                    message=args.message,
                )
            else:
                result = assemble(config, args.dir, args.out)
        print(json.dumps(result, indent=2))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"Campaign check blocked: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
