"""Strict, local-only enrichment of graph principals from Wiz issue CSV exports.

Lifecycle status is source metadata, not approval, risk acceptance, or verification.
Graph names and scopes are never replaced. ``source_rows`` retains every original
CSV row (including duplicate evidence); parallel ``source_locations`` supplies
provenance without risking collisions with arbitrary source column names. Large
source-only fields such as original JSON and Evidence are not report metadata.
"""

import csv
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlsplit

_IDENTIFIERS = (
    "Issue ID",
    "Control ID",
    "Resource vertex ID",
    "Resource external ID",
    "Resource Platform",
)
_REQUIRED_HEADERS = (*_IDENTIFIERS, "Title", "Severity", "Status")
_FIELDS = {
    "issue_id": "Issue ID",
    "issue_control_id": "Control ID",
    "issue_resource_vertex_id": "Resource vertex ID",
    "issue_title": "Title",
    "issue_resource_type": "Resource Type",
    "issue_resource_name": "Resource Name",
    "issue_native_id": "Resource external ID",
    "issue_created_at": "Created At",
    "issue_updated_at": "Updated At",
    "issue_status_changed_at": "Status Changed At",
    "issue_reopened_at": "Reopened At",
    "issue_assignee": "Assignee Name",
    "issue_due_at": "Due At",
    "issue_subscription_id": "Subscription ID",
    "issue_subscription_name": "Subscription Name",
    "issue_recommendation": "Remediation Recommendation",
    "issue_description": "Description",
}
_SEVERITIES = {
    value.casefold(): value for value in ("Critical", "High", "Medium", "Low", "Informational")
}
_SEVERITIES["info"] = "Informational"
_STATUSES = {
    "open": "Open",
    "in_progress": "In Progress",
    "in progress": "In Progress",
    "resolved": "Resolved",
    "rejected": "Rejected",
}
_CLOUDS = {"aws": "AWS", "azure": "Azure", "gcp": "GCP"}


@dataclass
class Enrichment:
    """Unique normalized issues, enriched graph rows, and lossless CSV evidence.

    ``source_locations[i]`` describes ``source_rows[i]`` using ``source_file``
    (supplied path), ``source_input`` (one-based input ordinal), and ``source_row``
    (one-based logical CSV row, with the header at row 1). All values are strings.
    Source rows may contain sensitive/large text: retain in an evidence sidecar,
    not automatically in report notes. Formula-like text is deliberately literal.
    """

    records: list[dict[str, str]]
    issues: list[dict[str, str]]
    source_rows: list[dict[str, str]]
    source_locations: list[dict[str, str]]


def _fail(reason: str, location: str) -> ValueError:
    # Never interpolate source cells, file paths, URLs, or parser exception text.
    return ValueError(f"Issue enrichment: {reason} ({location}).")


def _valid_text(value: str, location: str) -> None:
    if not isinstance(value, str):
        raise _fail("expected text", location)
    if any(
        not (
            char in "\t\n\r"
            or "\x20" <= char <= "\ud7ff"
            or "\ue000" <= char <= "\ufffd"
            or "\U00010000" <= char <= "\U0010ffff"
        )
        for char in value
    ):
        raise _fail("invalid XML characters", location)


def _cloud(value: str, location: str) -> str:
    cloud = _CLOUDS.get(value.strip().casefold())
    if cloud is None:
        raise _fail("unknown cloud", location)
    return cloud


def _display(value: str) -> str:
    return value if value.strip() else "Not supplied"


def validate_wiz_url(value: str, issue_id: str, location: str = "report row") -> str:
    """Accept only source issue links on the supported Wiz application host."""
    if not value.strip():
        return ""
    try:
        parsed = urlsplit(value)
        valid = (
            value == value.strip()
            and not any(char.isspace() or ord(char) < 32 for char in value)
            and parsed.scheme == "https"
            and parsed.hostname == "app.wiz.io"
            and parsed.netloc.casefold() == "app.wiz.io"
            and parsed.username is None
            and parsed.password is None
            and parsed.port is None
            and bool(issue_id.strip())
            and issue_id not in (".", "..")
            and "/" not in issue_id
            and "\\" not in value
        )
        fragment = unquote(parsed.fragment, errors="strict")
        # IDs must be a complete fragment token, not a prefix of another ID.
        fragment_link = parsed.path == "/issues" and bool(
            re.search(r"(?<![\w-])" + re.escape(issue_id) + r"(?![\w-])", fragment)
        )
        direct_link = (
            unquote(parsed.path, errors="strict") == f"/issues/{issue_id}"
            and not parsed.query and not parsed.fragment
        )
        valid = valid and (fragment_link or direct_link)
    except (ValueError, UnicodeError):
        valid = False
    if not valid:
        raise _fail("untrusted Wiz URL", location)
    return value


def _normalize(row: dict[str, str], location: str) -> dict[str, str]:
    result = {key: _display(row.get(header, "")) for key, header in _FIELDS.items()}
    severity = row["Severity"]
    status = row["Status"]
    result.update(
        issue_cloud=_cloud(row["Resource Platform"], location),
        issue_severity=_SEVERITIES.get(severity.strip().casefold(), severity)
        if severity.strip()
        else "Unknown",
        issue_status=_STATUSES.get(status.strip().casefold(), status)
        if status.strip()
        else "Unknown",
        issue_status_raw=status,
        issue_url=validate_wiz_url(row.get("Wiz URL", ""), row["Issue ID"], location),
        issue_ticket_references=_display(
            "\n".join(
                f"{header}: {row[header]}"
                for header in ("Ticket URLs", "Ticket Names", "Ticket External IDs")
                if row.get(header, "").strip()
            )
        ),
    )
    return result


def _read_source(path: Path, input_number: int) -> list[dict[str, str]]:
    location = f"input {input_number}, row 1"
    original_limit = csv.field_size_limit()
    try:
        # Wiz original JSON/Evidence may exceed csv's small default field limit.
        csv.field_size_limit(max(original_limit, 2**31 - 1))
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.reader(handle, strict=True)
            headers = next(reader, None)
            if not headers:
                raise _fail("empty CSV", location)
            for header in headers:
                _valid_text(header, location)
            if any(not header.strip() for header in headers):
                raise _fail("blank header", location)
            if len(set(headers)) != len(headers):
                raise _fail("duplicate headers", location)
            if not set(_REQUIRED_HEADERS).issubset(headers):
                raise _fail("missing required headers", location)
            rows = []
            number = 2
            while True:
                location = f"input {input_number}, row {number}"
                values = next(reader, None)
                if values is None:
                    break
                if len(values) != len(headers):
                    raise _fail("ragged CSV row", location)
                for value in values:
                    _valid_text(value, location)
                row = dict(zip(headers, values, strict=True))
                if any(not row[header].strip() for header in _IDENTIFIERS):
                    raise _fail("blank required identifier", location)
                rows.append(row)
                number += 1
            if not rows:
                raise _fail("header-only CSV", f"input {input_number}, row 1")
            return rows
    except (OSError, UnicodeError, csv.Error):
        raise _fail("cannot read valid UTF-8 CSV", location) from None
    finally:
        csv.field_size_limit(original_limit)


def enrich_records(
    records: Sequence[Mapping[str, str]], paths: Sequence[str | Path]
) -> Enrichment:
    """Require complete, unambiguous principal coverage within one control.

    Join only by normalized cloud and exact vertex ID, then check the native ID
    exactly. Multiple credentials/scopes reuse one issue. Identical Issue IDs
    deduplicate only when *all* source facts agree, including unreported columns.
    Blank optional metadata uses ``Not supplied`` (severity/status: ``Unknown``);
    missing URLs and raw status stay blank. Dates are not inferred or enforced.

    Subscription metadata is separate from the graph scope: a nonblank
    discrepancy adds ``issue_scope_note`` without rejecting legitimate
    tenant/subscription-scoped evidence or overwriting either value.
    """
    if not records:
        raise _fail("no graph records", "graph")
    if not paths:
        raise _fail("no issue inputs", "inputs")

    graph_keys: list[tuple[str, str]] = []
    principals: dict[tuple[str, str], str] = {}
    for number, record in enumerate(records, start=1):
        location = f"graph row {number}"
        for key, value in record.items():
            _valid_text(key, location)
            _valid_text(value, location)
        if any(
            not record.get(key, "").strip()
            for key in ("cloud", "principal_id", "principal_native_id")
        ):
            raise _fail("blank graph identifier", location)
        key = (_cloud(record["cloud"], location), record["principal_id"])
        native = record["principal_native_id"]
        if key in principals and principals[key] != native:
            raise _fail("inconsistent graph native ID", location)
        principals[key] = native
        graph_keys.append(key)

    sources: list[dict[str, str]] = []
    locations: list[dict[str, str]] = []
    raw_by_id: dict[str, dict[str, str]] = {}
    issue_by_principal: dict[tuple[str, str], dict[str, str]] = {}
    issues: list[dict[str, str]] = []
    control_id: str | None = None
    for input_number, supplied_path in enumerate(paths, start=1):
        path = Path(supplied_path)
        for row_number, row in enumerate(_read_source(path, input_number), start=2):
            location = f"input {input_number}, row {row_number}"
            sources.append(row.copy())
            locations.append(
                {
                    "source_file": str(path),
                    "source_input": str(input_number),
                    "source_row": str(row_number),
                }
            )
            issue_id = row["Issue ID"]
            if issue_id in raw_by_id:
                if raw_by_id[issue_id] != row:
                    raise _fail("conflicting facts for repeated Issue ID", location)
                continue
            issue = _normalize(row, location)
            if control_id is not None and control_id != row["Control ID"]:
                raise _fail("multiple control IDs", location)
            control_id = row["Control ID"]
            key = (issue["issue_cloud"], row["Resource vertex ID"])
            if key not in principals:
                raise _fail("issue has no matching graph principal", location)
            if principals[key] != row["Resource external ID"]:
                raise _fail("native ID mismatch", location)
            if key in issue_by_principal:
                raise _fail("multiple issues for one graph principal", location)
            raw_by_id[issue_id] = row
            issue_by_principal[key] = issue
            issues.append(issue)

    enriched = []
    for number, (record, key) in enumerate(zip(records, graph_keys, strict=True), start=1):
        if key not in issue_by_principal:
            raise _fail("graph principal has no matching issue", f"graph row {number}")
        issue = issue_by_principal[key]
        row = dict(record)
        row.update(issue)
        subscription = raw_by_id[issue["issue_id"]].get("Subscription ID", "")
        scope = record.get("scope_external_id", "")
        row["issue_scope_note"] = (
            "Issue subscription differs from graph scope; both source values are preserved. "
            "Tenant and subscription scopes may legitimately differ."
            if subscription.strip()
            and scope.strip()
            and scope != "Not supplied"
            and subscription != scope
            else ""
        )
        enriched.append(row)
    return Enrichment(enriched, issues, sources, locations)
