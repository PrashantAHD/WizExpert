import json
from pathlib import Path

import pytest
from test_governance import snapshot as prior_payload
from test_monthly import save_csv, synthetic_rows

from wizexpert.__main__ import main
from wizexpert.governance.dashboard_data import DashboardError
from wizexpert.governance.governance_data import load_snapshot
from wizexpert.governance.snapshot_build import build_snapshot, write_snapshot

CUTOFF = "2026-10-15T23:59:59Z"
SHA = "a" * 64


def raw(rule_id, severity="MEDIUM", count=1):
    keys = {
        s: f"{s.lower()}SeverityCount"
        for s in ("CRITICAL", "HIGH", "MEDIUM", "LOW", "INFORMATIONAL")
    }
    issues = {key: 0 for key in keys.values()}
    issues[keys[severity]] = count
    issues["totalCount"] = count
    issues["nodes"] = [
        {
            "id": f"issue-{rule_id}",
            "createdAt": "2026-01-01T00:00:00Z",
            "resolvedAt": "2026-10-01T00:00:00Z",
            "sourceRules": [{"name": f"Rule {rule_id}", "resolutionRecommendation": "Fix it."}],
        }
    ]
    return {
        "issuesGroupedByValue": {
            "totalCount": 1,
            "nodes": [{"id": rule_id, "issues": issues}],
        }
    }


EMPTY = {"issuesGroupedByValue": {"totalCount": 0, "nodes": []}}


def metrics_payload():
    seen = "2026-10-16T09:00:00Z"
    return {
        "security_score": {"value": 96, "source": "Wiz", "observed_at": seen},
        "hipaa": {
            "value": 91,
            "source": "Owner screenshot",
            "observed_at": seen,
            "framework_version": "HIPAA v1",
            "screenshot_sha256": SHA,
        },
        "hitrust": {"value": None, "source": "Wiz", "unavailable_reason": "HTTP 504"},
    }


@pytest.fixture
def parts(tmp_path):
    rows = synthetic_rows()
    medium = next(r for r in rows if r["Severity"] == "MEDIUM")
    medium.update(Status="RESOLVED", **{"Resolved Time": "2026-10-01T00:00:00Z"})
    csv = tmp_path / "reviewed-20261015.csv"
    save_csv(csv, rows)
    template = tmp_path / "t.pptx"
    template.write_bytes(b"template")
    prior = prior_payload(template)
    prior["period"]["end_inclusive"] = "2026-09-15T23:59:59Z"
    prior_path = tmp_path / "prior.governance.json"
    prior_path.write_text(json.dumps(prior), encoding="utf-8")

    def write(name, value):
        path = tmp_path / name
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    return {
        "reviewed": [csv],
        "resolved_raw": [write("resolved-medium.json", raw("r1"))],
        "in_progress_raw": [write("progress.json", EMPTY)],
        "prior_snapshot": prior_path,
        "cutoff": CUTOFF,
        "collected_through": "2026-10-16T00:01:00Z",
        "metrics": write("metrics.json", metrics_payload()),
        "write": write,
        "tmp": tmp_path,
    }


def build(parts, **changes):
    args = {k: v for k, v in parts.items() if k not in ("write", "tmp")}
    return build_snapshot(**{**args, **changes})


def test_snapshot_dates_equal_cutoff_and_output_loads(parts):
    payload = build(parts)
    period = payload["period"]
    assert (
        period["end_inclusive"] == period["backlog_as_of"] == period["resolved_through"] == CUTOFF
    )
    assert period["start_exclusive"] == "2026-09-15T23:59:59Z"
    assert payload["resolved"]["MEDIUM"] == 1 and payload["hitrust"]["value"] is None
    out = write_snapshot(payload, parts["tmp"] / "out.governance.json")
    assert load_snapshot(Path(out)).backlog_as_of.isoformat().startswith("2026-10-15T23:59:59")
    with pytest.raises(DashboardError, match="--refresh"):
        write_snapshot(payload, out)


def test_resolved_files_merge_by_rule_and_reject_conflicts(parts):
    high = parts["write"]("resolved-high.json", raw("r1"))  # identical repeat collapses
    assert (
        build(parts, resolved_raw=[*parts["resolved_raw"], high])["resolved_groups"]["total_groups"]
        == 1
    )
    other = parts["write"]("resolved-other.json", raw("r1", count=2))
    with pytest.raises(DashboardError, match="conflicting duplicate source rule r1"):
        build(parts, resolved_raw=[*parts["resolved_raw"], other])


def test_backlog_as_of_after_period_end_is_rejected(parts):
    with pytest.raises(DashboardError, match="later than the period end"):
        build(parts, backlog_as_of="2026-10-16T09:00:00Z")


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda m: m["security_score"].update(value=0), "never zero|above 0"),
        (lambda m: m["hitrust"].pop("unavailable_reason"), "unavailable_reason"),
        (lambda m: m["hipaa"].pop("screenshot_sha256"), "screenshot_sha256"),
        (lambda m: m["hipaa"].pop("framework_version"), "framework_version"),
        (lambda m: m.pop("hipaa"), "hipaa is required"),
    ],
)
def test_metrics_are_never_zero_or_guessed(parts, change, message):
    metrics = metrics_payload()
    change(metrics)
    with pytest.raises(DashboardError, match=message):
        build(parts, metrics=parts["write"]("bad.json", metrics))


def test_decisions_cannot_override_computed_fields(parts):
    decisions = parts["write"]("decisions.json", {"open": {}})
    with pytest.raises(DashboardError, match="computed fields"):
        build(parts, decisions=decisions)


def test_cli_builds_the_snapshot(parts, capsys):
    out = parts["tmp"] / "cli.governance.json"
    code = main(
        [
            "governance",
            "snapshot",
            "--reviewed",
            str(parts["reviewed"][0]),
            "--resolved-raw",
            str(parts["resolved_raw"][0]),
            "--in-progress-raw",
            str(parts["in_progress_raw"][0]),
            "--prior-snapshot",
            str(parts["prior_snapshot"]),
            "--cutoff",
            CUTOFF,
            "--collected-through",
            parts["collected_through"],
            "--metrics",
            str(parts["metrics"]),
            "--output",
            str(out),
        ]
    )
    assert code == 0 and out.is_file() and "Created" in capsys.readouterr().out
