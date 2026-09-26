"""Synthetic-only issue enrichment tests; no client exports or workbooks are read."""

import csv
import shutil
from pathlib import Path
from uuid import uuid4

import pytest

from remediation.issue_metadata import Enrichment, enrich_records


@pytest.fixture
def workspace():
    root = Path(__file__).resolve().parents[1] / f".issue-metadata-test-{uuid4().hex}"
    root.mkdir()
    try:
        yield root
    finally:
        shutil.rmtree(root)


def graph(number=1, **overrides):
    return {
        "cloud": "AWS",
        "principal_id": f"vertex-{number}",
        "principal_native_id": f"native-{number}",
        "principal": f"Graph name {number}",
        "credential_id": f"credential-{number}",
        "credential_name": f"Credential {number}",
        "scope_id": "scope-1",
        "scope_external_id": "subscription-1",
        "scope_name": "Graph scope",
        "scope_type": "SUBSCRIPTION",
        **overrides,
    }


def issue(number=1, **overrides):
    return {
        "Issue ID": f"issue-{number}",
        "Control ID": "control-1",
        "Resource vertex ID": f"vertex-{number}",
        "Resource external ID": f"native-{number}",
        "Resource Platform": "AWS",
        "Title": "Synthetic finding",
        "Severity": "HIGH",
        "Status": "OPEN",
        "Resource Name": f"Issue name {number}",
        "Resource Type": "SERVICE_ACCOUNT",
        "Subscription ID": "subscription-1",
        "Subscription Name": "Issue subscription",
        "Wiz URL": f"https://app.wiz.io/issues#~(issue~'issue-{number})",
        **overrides,
    }


def export(workspace, rows, name="issues.csv", encoding="utf-8-sig", headers=None):
    path = workspace / name
    fields = list(rows[0]) if headers is None else headers
    with path.open("w", encoding=encoding, newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(fields)
        writer.writerows([row.get(field, "") for field in fields] for row in rows)
    return path


def test_eight_principals_nine_credentials_and_multiple_scopes(workspace):
    records = [graph(number) for number in range(1, 9)]
    records.append(graph(1, credential_id="credential-extra"))
    records.append(graph(1, scope_id="scope-2", scope_external_id="subscription-2"))
    original = [row.copy() for row in records]
    source = export(workspace, [issue(number) for number in range(1, 9)])
    result = enrich_records(records, [source])
    assert isinstance(result, Enrichment)
    assert len(result.issues) == 8
    assert len(result.records) == 10
    assert len({row["credential_id"] for row in result.records}) == 9
    assert records == original
    assert result.records[0] is not records[0]
    assert result.records[0]["issue_id"] == result.records[-1]["issue_id"] == "issue-1"
    assert result.records[0]["issue_scope_note"] == ""
    assert "Tenant and subscription" in result.records[-1]["issue_scope_note"]
    for record in result.records:
        assert record["principal"].startswith("Graph name")
        assert record["issue_resource_name"].startswith("Issue name")
    for key, value in result.issues[0].items():
        assert result.records[0][key] == result.records[-1][key] == value


def test_deduplicate_rows_and_files_with_lossless_separate_provenance(workspace):
    raw = issue(
        **{
            "Resource original JSON": '{"synthetic": true}',
            "Evidence": "synthetic evidence\nsecond line",
            "source_file": "original column",
            "source_row": "original row text",
            "source_input": "original input text",
        }
    )
    first = export(workspace, [raw, raw])
    second = export(workspace, [raw], name="second.csv", headers=list(reversed(raw)))
    result = enrich_records([graph()], [str(first), second, first])
    assert len(result.issues) == 1
    assert len(result.source_rows) == 5
    assert result.source_rows == [raw] * 5
    assert result.source_locations == [
        {"source_file": str(path), "source_input": str(number), "source_row": str(row)}
        for path, number, row in (
            (first, 1, 2),
            (first, 1, 3),
            (second, 2, 2),
            (first, 3, 2),
            (first, 3, 3),
        )
    ]
    assert "Resource original JSON" not in result.records[0]
    assert "Evidence" not in result.issues[0]


@pytest.mark.parametrize("column", ["Severity", "Resource original JSON", "Note", "Status"])
@pytest.mark.parametrize("same_file", [True, False])
def test_conflicting_issue_source_facts_are_safe_errors(workspace, column, same_file):
    first = issue(**{column: "private-original"})
    changed = issue(**{column: "private-changed"})
    if same_file:
        paths = [export(workspace, [first, changed])]
        expected_location = "input 1, row 3"
    else:
        paths = [
            export(workspace, [first]),
            export(workspace, [changed], name="private-file.csv"),
        ]
        expected_location = "input 2, row 2"
    with pytest.raises(ValueError, match="conflicting facts") as caught:
        enrich_records([graph()], paths)
    assert expected_location in str(caught.value)
    assert "private" not in str(caught.value)


def test_changed_column_presence_is_conflicting_fact(workspace):
    paths = [
        export(workspace, [issue()]),
        export(workspace, [issue(Note="")], name="more-columns.csv"),
    ]
    with pytest.raises(ValueError, match="conflicting facts"):
        enrich_records([graph()], paths)


def test_large_source_json_remains_lossless_sidecar_only(workspace):
    source_json = '{"synthetic": "' + "a" * 200_000 + '"}'
    raw = issue(**{"Resource original JSON": source_json})
    original_limit = csv.field_size_limit()
    result = enrich_records([graph()], [export(workspace, [raw])])
    assert csv.field_size_limit() == original_limit
    assert result.source_rows[0]["Resource original JSON"] == source_json
    assert source_json not in result.records[0].values()
    assert source_json not in result.issues[0].values()


def test_optional_fields_are_not_invented(workspace):
    raw = issue(**{"Title": "", "Severity": "", "Status": "", "Wiz URL": ""})
    result = enrich_records([graph()], [export(workspace, [raw])])
    metadata = result.issues[0]
    assert metadata["issue_title"] == "Not supplied"
    assert metadata["issue_severity"] == metadata["issue_status"] == "Unknown"
    assert metadata["issue_status_raw"] == metadata["issue_url"] == ""
    for field in (
        "created_at",
        "updated_at",
        "status_changed_at",
        "reopened_at",
        "due_at",
        "assignee",
        "recommendation",
        "description",
        "ticket_references",
    ):
        assert metadata[f"issue_{field}"] == "Not supplied"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("OPEN", "Open"),
        ("IN_PROGRESS", "In Progress"),
        ("in progress", "In Progress"),
        ("Resolved", "Resolved"),
        ("REJECTED", "Rejected"),
        ("future-state", "future-state"),
        ("approved", "approved"),
        (" ", "Unknown"),
    ],
)
def test_status_is_display_metadata_with_raw_preserved(workspace, raw, expected):
    result = enrich_records([graph()], [export(workspace, [issue(Status=raw)])])
    assert result.issues[0]["issue_status"] == expected
    assert result.issues[0]["issue_status_raw"] == raw
    assert not any("approval" in key or "verified" in key for key in result.issues[0])


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("CRITICAL", "Critical"),
        (" high ", "High"),
        ("medium", "Medium"),
        ("LOW", "Low"),
        ("INFO", "Informational"),
        ("Informational", "Informational"),
        ("Future severity ", "Future severity "),
        (" ", "Unknown"),
    ],
)
def test_severity_normalization(workspace, raw, expected):
    result = enrich_records([graph()], [export(workspace, [issue(Severity=raw)])])
    assert result.issues[0]["issue_severity"] == expected


def test_optional_metadata_formula_like_text_and_dates_stay_literal(workspace):
    raw = issue(
        **{
            "Description": "=SUM(1,2)",
            "Remediation Recommendation": "+literal recommendation",
            "Assignee Name": "@literal assignee",
            "Created At": "source-date-not-parsed",
            "Updated At": "2026-01-02",
            "Status Changed At": "2026-01-03",
            "Reopened At": "2026-01-04",
            "Due At": "2020-01-01",
            "Ticket URLs": "https://tickets.invalid/synthetic",
            "Ticket Names": "Synthetic ticket",
            "Ticket External IDs": "-literal ticket id",
        }
    )
    metadata = enrich_records([graph()], [export(workspace, [raw])]).issues[0]
    assert metadata["issue_description"] == "=SUM(1,2)"
    assert metadata["issue_recommendation"] == "+literal recommendation"
    assert metadata["issue_assignee"] == "@literal assignee"
    assert metadata["issue_created_at"] == "source-date-not-parsed"
    assert metadata["issue_due_at"] == "2020-01-01"
    assert metadata["issue_updated_at"] == "2026-01-02"
    assert metadata["issue_status_changed_at"] == "2026-01-03"
    assert metadata["issue_reopened_at"] == "2026-01-04"
    assert metadata["issue_ticket_references"] == (
        "Ticket URLs: https://tickets.invalid/synthetic\n"
        "Ticket Names: Synthetic ticket\nTicket External IDs: -literal ticket id"
    )


@pytest.mark.parametrize("cloud", ["AWS", "Azure", "GCP"])
def test_cloud_case_normalization_and_exact_vertex_join(workspace, cloud):
    result = enrich_records(
        [graph(cloud=cloud)],
        [export(workspace, [issue(**{"Resource Platform": cloud.upper()})])],
    )
    assert result.issues[0]["issue_cloud"] == cloud


@pytest.mark.parametrize("subscription", ["", "tenant-subscription", "subscription-1"])
def test_azure_subscription_never_overwrites_graph_scope(workspace, subscription):
    raw = issue(**{"Resource Platform": "AZURE", "Subscription ID": subscription})
    row = enrich_records(
        [graph(cloud="Azure")], [export(workspace, [raw])]
    ).records[0]
    assert row["scope_id"] == "scope-1"
    assert row["scope_name"] == "Graph scope"
    assert row["scope_external_id"] == "subscription-1"
    assert row["issue_subscription_id"] == (subscription or "Not supplied")
    assert bool(row["issue_scope_note"]) == (subscription == "tenant-subscription")


@pytest.mark.parametrize(
    "url",
    [
        "https://app.wiz.io/issues#issue-1",
        "https://app.wiz.io/issues#~(issue~'issue-1)",
        "https://app.wiz.io/issues#%7B%22issueId%22%3A%22issue-1%22%7D",
        "https://app.wiz.io/issues?view=all#issue-1",
        "",
        " ",
    ],
)
def test_valid_wiz_urls_and_missing_url(workspace, url):
    result = enrich_records([graph()], [export(workspace, [issue(**{"Wiz URL": url})])])
    assert result.issues[0]["issue_url"] == (url if url.strip() else "")


@pytest.mark.parametrize(
    "url",
    [
        "http://app.wiz.io/issues#issue-1",
        "javascript:alert('issue-1')",
        "file:///issues#issue-1",
        "https://evil.invalid/issues#issue-1",
        "https://app.wiz.io.evil.invalid/issues#issue-1",
        "https://eu.app.wiz.io/issues#issue-1",
        "https://user" + "@app.wiz.io/issues#issue-1",
        "https://user:password" + "@app.wiz.io/issues#issue-1",
        "https://app.wiz.io:443/issues#issue-1",
        "https://app.wiz.io:/issues#issue-1",
        "https://app.wiz.io:invalid/issues#issue-1",
        "https://app.wiz.io./issues#issue-1",
        "https://app.wiz.io/other#issue-1",
        "https://app.wiz.io/issues/",
        "https://app.wiz.io/issues?issue=issue-1",
        "https://app.wiz.io/issues#issue-10",
        "https://app.wiz.io/issues#prefix-issue-1",
        "https://app.wiz.io/issues#issue-1-suffix",
        "https://app.wiz.io/issues#another-issue",
        "https://app.wiz.io/issues#%FFissue-1",
        " https://app.wiz.io/issues#issue-1",
        "https://app.wiz.io/issues#issue-1\n",
        "https://app.wiz.io\\@evil.invalid/issues#issue-1",
        "https://[invalid/issues#issue-1",
    ],
)
def test_reject_untrusted_wiz_url_without_leaking_it(workspace, url):
    with pytest.raises(ValueError, match="untrusted Wiz URL") as caught:
        enrich_records([graph()], [export(workspace, [issue(**{"Wiz URL": url})])])
    assert "input 1, row 2" in str(caught.value)
    assert url not in str(caught.value)


@pytest.mark.parametrize(
    ("payload", "error"),
    [
        ("", "empty CSV"),
        ("\ufeff", "empty CSV"),
        ("\n", "empty CSV"),
        ("Title,Title\none,two\n", "duplicate headers"),
        ("Title,\none,two\n", "blank header"),
        ("Title,Status\none,two\n", "missing required headers"),
    ],
)
def test_invalid_csv_headers(workspace, payload, error):
    path = workspace / "invalid.csv"
    path.write_text(payload, encoding="utf-8")
    with pytest.raises(ValueError, match=error):
        enrich_records([graph()], [path])


def test_header_only_export(workspace):
    path = export(workspace, [], headers=list(issue()))
    with pytest.raises(ValueError, match="header-only CSV"):
        enrich_records([graph()], [path])


@pytest.mark.parametrize("missing", ["Title", "Severity", "Status", "Issue ID", "Control ID"])
def test_missing_required_schema(workspace, missing):
    row = issue()
    del row[missing]
    with pytest.raises(ValueError, match="missing required headers"):
        enrich_records([graph()], [export(workspace, [row])])


@pytest.mark.parametrize(
    "missing",
    ["Issue ID", "Control ID", "Resource vertex ID", "Resource external ID", "Resource Platform"],
)
@pytest.mark.parametrize("blank", ["", " \t"])
def test_blank_required_identifiers(workspace, missing, blank):
    with pytest.raises(ValueError, match="blank required identifier"):
        enrich_records([graph()], [export(workspace, [issue(**{missing: blank})])])


@pytest.mark.parametrize("extra", ["\n", "one,two\n", ",".join(["x"] * 30) + "\n"])
def test_ragged_csv_rows(workspace, extra):
    path = export(workspace, [issue()])
    with path.open("a", encoding="utf-8", newline="") as handle:
        handle.write(extra)
    with pytest.raises(ValueError, match="ragged CSV row"):
        enrich_records([graph()], [path])


@pytest.mark.parametrize("payload", [b"\xff", b'"unterminated'])
def test_decode_and_csv_parser_errors_are_safe(workspace, payload):
    path = export(workspace, [issue()])
    with path.open("ab") as handle:
        handle.write(payload)
    with pytest.raises(ValueError, match="cannot read valid UTF-8 CSV") as caught:
        enrich_records([graph()], [path])
    assert str(path) not in str(caught.value)
    if payload == b'"unterminated':
        assert "row 3" in str(caught.value)


@pytest.mark.parametrize("value", ["bad\x00text", "bad\x0btext", "bad\ufffetext", "bad\ufffftext"])
@pytest.mark.parametrize("in_header", [True, False])
def test_invalid_xml_characters(workspace, value, in_header):
    raw = issue(**{value: "text"} if in_header else {"Evidence": value})
    with pytest.raises(ValueError, match="invalid XML characters"):
        enrich_records([graph()], [export(workspace, [raw])])


def test_valid_xml_unicode_and_line_breaks(workspace):
    value = "Synthetic \t\n\r \u00e9 \U0001f600"
    result = enrich_records(
        [graph()], [export(workspace, [issue(Description=value)], encoding="utf-8")]
    )
    assert result.issues[0]["issue_description"] == value


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"Resource Platform": "UNKNOWN"}, "unknown cloud"),
        ({"Resource Platform": "Azure"}, "no matching graph principal"),
        ({"Resource vertex ID": "Vertex-1"}, "no matching graph principal"),
        ({"Resource vertex ID": " vertex-1"}, "no matching graph principal"),
        ({"Resource external ID": "Native-1"}, "native ID mismatch"),
        ({"Resource external ID": "native-1 "}, "native ID mismatch"),
    ],
)
def test_no_fuzzy_or_name_join(workspace, overrides, message):
    raw = issue(**{"Resource Name": "Graph name 1", **overrides})
    with pytest.raises(ValueError, match=message):
        enrich_records([graph()], [export(workspace, [raw])])


def test_same_vertex_ids_in_different_clouds_remain_distinct(workspace):
    rows = [issue(), issue(**{"Issue ID": "issue-2", "Resource Platform": "Azure", "Wiz URL": ""})]
    result = enrich_records([graph(), graph(cloud="Azure")], [export(workspace, rows)])
    assert len(result.issues) == 2


@pytest.mark.parametrize("graph_side", [True, False])
def test_complete_bidirectional_coverage(workspace, graph_side):
    records = [graph(), graph(2)] if graph_side else [graph()]
    rows = [issue()] if graph_side else [issue(), issue(2)]
    with pytest.raises(ValueError, match="no matching"):
        enrich_records(records, [export(workspace, rows)])


def test_multiple_issues_per_principal_are_ambiguous(workspace):
    rows = [issue(), issue(**{"Issue ID": "other-issue", "Wiz URL": ""})]
    with pytest.raises(ValueError, match="multiple issues for one graph principal"):
        enrich_records([graph()], [export(workspace, rows)])


def test_multiple_controls_rejected(workspace):
    rows = [issue(), issue(2, **{"Control ID": "control-2"})]
    with pytest.raises(ValueError, match="multiple control IDs"):
        enrich_records([graph(), graph(2)], [export(workspace, rows)])


@pytest.mark.parametrize(
    ("records", "message"),
    [
        ([], "no graph records"),
        ([graph(cloud="unsupported")], "unknown cloud"),
        ([graph(principal_id="")], "blank graph identifier"),
        ([graph(principal_native_id="")], "blank graph identifier"),
        ([graph(principal="\ud800")], "invalid XML characters"),
        ([graph(principal=42)], "expected text"),
        ([graph(), graph(principal_native_id="other-native")], "inconsistent graph native ID"),
    ],
)
def test_invalid_graph_records(workspace, records, message):
    with pytest.raises(ValueError, match=message):
        enrich_records(records, [export(workspace, [issue()])])


def test_no_issue_inputs():
    with pytest.raises(ValueError, match="no issue inputs"):
        enrich_records([graph()], [])


def test_unreadable_source_has_safe_ordinal_error(workspace):
    path = workspace / "private-name-does-not-exist.csv"
    with pytest.raises(ValueError, match="input 1, row 1") as caught:
        enrich_records([graph()], [path])
    assert "private-name" not in str(caught.value)
