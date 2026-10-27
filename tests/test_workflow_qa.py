import json
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest

from wizexpert.__main__ import main
from wizexpert.workflow_qa import (
    digest,
    hook,
    receipt,
    required_checks,
    rule_hashes,
    rule_inventory,
    validate_review,
)

NOW = datetime(2026, 10, 27, 8, tzinfo=UTC)
QUERY = {
    "tool_name": "list_issues",
    "parameters": {
        "first": 20,
        "severity": ["HIGH"],
        "status": ["OPEN", "IN_PROGRESS"],
    },
}


def save(path, data):
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def review_payload(tmp_path, phase="collection", workflow="governance"):
    evidence = tmp_path / "reviewed-evidence.json"
    evidence.write_text('{"synthetic": true}', encoding="utf-8")
    return {
        "schema_version": 2,
        "workflow": workflow,
        "phase": phase,
        "run_id": "synthetic-run",
        "scope": "Synthetic approved tenant",
        "preparer": "report-preparer",
        "reviewer": "separate-reviewer",
        "started_at": (NOW - timedelta(hours=2)).isoformat(),
        "reviewed_at": (NOW - timedelta(hours=1)).isoformat(),
        "expires_at": (NOW + timedelta(hours=1)).isoformat(),
        "rule_sha256": rule_hashes(workflow),
        "evidence_sha256": {str(evidence): digest(evidence)},
        "request_evidence": str(evidence),
        "requested_deliverables": [],
        "private_rule_sources": {},
        "parity_groups": [],
        "unresolved_conflicts": [],
        "rule_coverage": {
            name: {
                "source_sha256": value,
                "verdict": "pass",
                "rationale": "Synthetic section review.",
                "evidence": [str(evidence)],
            }
            for name, value in rule_inventory(workflow).items()
        },
        "checks": {
            name: {
                "verdict": "pass",
                "rationale": "Reviewed against synthetic evidence.",
                "evidence": [str(evidence)],
            }
            for name in required_checks(workflow, phase)
        },
        "allowed_wiz_queries": [QUERY],
    }


@pytest.fixture
def reviewed(tmp_path):
    return save(tmp_path / "review.json", review_payload(tmp_path))


@pytest.mark.parametrize(
    "mutation,message",
    [
        ("self", "self-certify"),
        ("missing", "Missing or unexpected"),
        ("pending", "not verified"),
        ("evidence", "evidence changed"),
        ("rules", "rules changed"),
        ("expired", "expired"),
        ("rationale", "reasoning"),
        ("future", "future-dated"),
    ],
)
def test_qa_fails_closed(reviewed, mutation, message):
    data = json.loads(reviewed.read_text())
    first = next(iter(data["checks"]))
    if mutation == "self":
        data["reviewer"] = " REPORT-PREPARER "
    elif mutation == "missing":
        del data["checks"][first]
    elif mutation == "pending":
        data["checks"][first]["verdict"] = "not_verified"
    elif mutation == "evidence":
        Path = type(reviewed)
        Path(next(iter(data["evidence_sha256"]))).write_text("changed")
    elif mutation == "rules":
        data["rule_sha256"][next(iter(data["rule_sha256"]))] = "0" * 64
    elif mutation == "expired":
        data["expires_at"] = NOW.isoformat()
    elif mutation == "rationale":
        data["checks"][first]["rationale"] = ""
    else:
        data["reviewed_at"] = (NOW + timedelta(minutes=1)).isoformat()
    save(reviewed, data)
    with pytest.raises(ValueError, match=message):
        validate_review(reviewed, now=NOW)


def run_hook(monkeypatch, capsys, raw, *extra):
    import io
    import sys
    from types import SimpleNamespace

    from wizexpert.workflow_qa import main as qa_main

    monkeypatch.setattr(sys, "stdin", SimpleNamespace(buffer=io.BytesIO(raw)))
    code = qa_main(["hook", *extra])
    assert code == 0
    out = capsys.readouterr().out
    assert len(out.strip().splitlines()) == 1
    return json.loads(out)


def camel(tool, args):
    return json.dumps(
        {"sessionId": "s", "timestamp": 1, "cwd": "C:/x", "toolName": tool, "toolArgs": args}
    ).encode()


def test_hook_command_camel_case_never_blocks_other_tools(monkeypatch, capsys):
    monkeypatch.delenv("WIZEXPERT_QA_REVIEW", raising=False)
    assert run_hook(monkeypatch, capsys, camel("bash", {"command": "ls"})) == {}
    assert run_hook(monkeypatch, capsys, camel("wiz-discover", {"query": "x"})) == {}
    count = {"tool_name": "list_issues", "parameters": {"first": 1}}
    assert run_hook(monkeypatch, capsys, camel("wiz-execute", count)) == {}
    assert run_hook(monkeypatch, capsys, b"not json at all") == {}
    assert run_hook(monkeypatch, capsys, b"") == {}
    payload = {"toolName": "bash", "toolArgs": {"command": "echo caf\u00e9 \u2713"}}
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    assert run_hook(monkeypatch, capsys, b"\xef\xbb\xbf" + raw) == {}
    assert run_hook(monkeypatch, capsys, raw) == {}


def test_hook_command_denies_bulk_wiz_execute(monkeypatch, capsys):
    monkeypatch.delenv("WIZEXPERT_QA_REVIEW", raising=False)
    for tool in ("wiz-execute", "functions.wiz-execute"):
        for args in (QUERY, json.dumps(QUERY)):
            result = run_hook(monkeypatch, capsys, camel(tool, args))
            assert result["permissionDecision"] == "deny"
            assert "requires" in result["permissionDecisionReason"]
            assert result["hookSpecificOutput"]["permissionDecision"] == "deny"
    snake = json.dumps({"tool_name": "wiz-execute", "tool_input": QUERY}).encode()
    assert run_hook(monkeypatch, capsys, snake)["permissionDecision"] == "deny"
    garbage = run_hook(monkeypatch, capsys, b"{broken wiz-execute")
    assert garbage["permissionDecision"] == "deny"
    bad_args = run_hook(monkeypatch, capsys, camel("wiz-execute", "not json"))
    assert bad_args["permissionDecision"] == "deny"


def test_hook_command_allows_reviewed_query_via_string_args(reviewed, monkeypatch, capsys):
    with patch("wizexpert.workflow_qa.datetime") as clock:
        clock.now.return_value = NOW
        clock.fromisoformat = datetime.fromisoformat
        result = run_hook(
            monkeypatch, capsys, camel("wiz-execute", json.dumps(QUERY)), "--review", str(reviewed)
        )
    assert result == {}


def test_hook_command_unexpected_error_is_contained(monkeypatch, capsys):
    def boom(*_):
        raise RuntimeError("boom")

    monkeypatch.setattr("wizexpert.workflow_qa.hook", boom)
    assert run_hook(monkeypatch, capsys, camel("bash", {})) == {}
    denied = run_hook(monkeypatch, capsys, camel("wiz-execute", QUERY))
    assert denied["permissionDecision"] == "deny"
    assert "RuntimeError" in denied["permissionDecisionReason"]


COUNT = {"tool_name": "list_issues", "parameters": {"first": 1}}


def batch(*calls):
    return json.dumps(
        {
            "sessionId": "s",
            "cwd": "c:\\Users\\Someone\\WizExpert",
            "toolCalls": [
                {"id": f"call_{index}", "name": name, "args": args}
                for index, (name, args) in enumerate(calls, 1)
            ],
        }
    ).encode()


def test_hook_batch_shape_is_primary(monkeypatch, capsys):
    monkeypatch.delenv("WIZEXPERT_QA_REVIEW", raising=False)
    assert run_hook(monkeypatch, capsys, batch(("view", {"path": "C:\\x"}))) == {}
    assert run_hook(monkeypatch, capsys, batch(("wiz-discover", {"q": "x"}), ("rg", {}))) == {}
    assert run_hook(monkeypatch, capsys, batch(("wiz-execute", COUNT))) == {}
    assert run_hook(monkeypatch, capsys, batch()) == {}
    assert run_hook(monkeypatch, capsys, b'{"sessionId":"s","cwd":"c:\\\\x"}') == {}
    denied = run_hook(monkeypatch, capsys, batch(("wiz-execute", QUERY)))
    assert denied["permissionDecision"] == "deny"
    assert "call_1" in denied["permissionDecisionReason"]
    mixed = run_hook(monkeypatch, capsys, batch(("view", {}), ("wiz-execute", QUERY)))
    assert mixed["permissionDecision"] == "deny"
    assert "call_2" in mixed["permissionDecisionReason"]
    assert "Someone" not in mixed["permissionDecisionReason"]


def test_hook_batch_escaped_name_and_name_variants_are_denied(monkeypatch, capsys):
    monkeypatch.delenv("WIZEXPERT_QA_REVIEW", raising=False)
    query = json.dumps(QUERY)
    escaped = (
        '{"toolCalls":[{"id":"call_x","name":"wiz\\u002dexecute","args":' + query + "}]}"
    ).encode()
    assert "wiz-execute" not in escaped.decode()
    assert run_hook(monkeypatch, capsys, escaped)["permissionDecision"] == "deny"
    for name in (" Wiz-Execute ", "functions.WIZ-EXECUTE", "mcp__wiz__execute", "MCP_wiz_execute"):
        result = run_hook(monkeypatch, capsys, batch((name, QUERY)))
        assert result["permissionDecision"] == "deny", name
    wrapper = {"tool_uses": [{"recipient_name": "functions.wiz\u002dexecute", "parameters": QUERY}]}
    for form in (
        json.dumps({"toolName": "multi_tool_use.parallel", "toolArgs": wrapper}),
        json.dumps({"tool_name": "parallel", "tool_input": json.dumps(wrapper)}),
        batch(("parallel", wrapper)).decode(),
    ):
        assert run_hook(monkeypatch, capsys, form.encode())["permissionDecision"] == "deny"


def test_hook_malformed_input_denied_only_when_it_may_be_wiz(monkeypatch, capsys):
    monkeypatch.delenv("WIZEXPERT_QA_REVIEW", raising=False)
    bash = {"command": "echo wiz-execute"}
    # Readable non-Wiz names are never denied, whatever their args say.
    assert run_hook(monkeypatch, capsys, batch(("bash", bash), ("view", "not json"))) == {}
    wrapper = {"tool_uses": [{"recipient_name": "bash", "parameters": bash}, {"junk": 1}, 7]}
    assert run_hook(monkeypatch, capsys, batch(("parallel", wrapper))) == {}
    assert run_hook(monkeypatch, capsys, camel("parallel", wrapper)) == {}
    assert run_hook(monkeypatch, capsys, camel("parallel", "not json")) == {}
    assert run_hook(monkeypatch, capsys, b'{"toolCalls":"nope"}') == {}
    assert run_hook(monkeypatch, capsys, b'{"toolCalls":[5,{"id":"a"}]}') == {}
    # Unreadable pieces that mention Wiz are denied.
    bad = {"tool_uses": [{"parameters": {"tool": "wiz\u002dexecute"}}]}
    assert run_hook(monkeypatch, capsys, batch(("parallel", bad)))["permissionDecision"] == "deny"
    unnamed = b'{"toolCalls":[{"id":"a","args":{"x":"wiz\\u002dexecute"}}]}'
    assert run_hook(monkeypatch, capsys, unnamed)["permissionDecision"] == "deny"
    assert run_hook(monkeypatch, capsys, b'{"toolCalls":"wiz-execute"}')["permissionDecision"]
    assert run_hook(monkeypatch, capsys, camel("wiz-execute", "not json"))["permissionDecision"]
    assert run_hook(monkeypatch, capsys, batch(("wiz-execute", [1])))["permissionDecision"]


def test_hook_non_json_and_non_utf8_input(monkeypatch, capsys):
    monkeypatch.delenv("WIZEXPERT_QA_REVIEW", raising=False)
    assert run_hook(monkeypatch, capsys, b"\xff\xfe\x00bad") == {}
    assert run_hook(monkeypatch, capsys, b"[1, 2]") == {}
    assert run_hook(monkeypatch, capsys, b"[" * 200000) == {}
    assert run_hook(monkeypatch, capsys, b"\xff wiz-execute")["permissionDecision"] == "deny"
    escaped = b"{broken wiz\\u002dexecute"
    assert run_hook(monkeypatch, capsys, escaped)["permissionDecision"] == "deny"
    duplicate = b'{"toolName":"bash","toolName":"wiz-execute"}'
    assert run_hook(monkeypatch, capsys, duplicate)["permissionDecision"] == "deny"


def test_hook_wiz_call_without_readable_query_is_denied(monkeypatch, capsys):
    monkeypatch.delenv("WIZEXPERT_QA_REVIEW", raising=False)

    def run(*elements):
        raw = json.dumps({"toolCalls": list(elements)}).encode()
        return run_hook(monkeypatch, capsys, raw)

    wiz = {"id": "call_9", "name": "wiz-execute"}
    assert run(wiz)["permissionDecision"] == "deny"
    assert run(wiz | {"args": None})["permissionDecision"] == "deny"
    assert "call_9" in run(wiz)["permissionDecisionReason"]
    for key in ("args", "arguments", "input", "parameters"):
        assert run(wiz | {key: QUERY})["permissionDecision"] == "deny", key
        assert run(wiz | {key: json.dumps(QUERY)})["permissionDecision"] == "deny", key
        assert run(wiz | {key: COUNT}) == {}, key
        assert run(wiz | {key: json.dumps(COUNT)}) == {}, key
    # A harmless-looking args value cannot hide a bulk query held under another key.
    assert run(wiz | {"args": COUNT, "input": QUERY})["permissionDecision"] == "deny"
    for bad in ({"parameters": {"first": 50}}, {"tool_name": "", "parameters": {"first": 50}}):
        assert run(wiz | {"args": bad})["permissionDecision"] == "deny"
        assert run(wiz | {"args": {"tool_name": "  ", **bad}})["permissionDecision"] == "deny"


def test_hook_name_under_other_keys_or_unreadable(monkeypatch, capsys):
    monkeypatch.delenv("WIZEXPERT_QA_REVIEW", raising=False)

    def run(*elements, key="toolCalls"):
        return run_hook(monkeypatch, capsys, json.dumps({key: list(elements)}).encode())

    for key in ("tool", "toolName", "tool_name", "recipient_name"):
        denied = run({"id": "c1", key: "wiz-execute", "args": QUERY})
        assert denied["permissionDecision"] == "deny", key
        assert run({"id": "c1", key: "wiz-execute", "args": COUNT}) == {}, key
        assert run({"id": "c1", key: "view", "args": QUERY}) == {}, key
    for name in (None, 5, ["wiz-execute"], {"n": 1}):
        element = {"id": "c2", "name": name, "args": QUERY}
        assert run(element)["permissionDecision"] == "deny", name
    assert run({"id": "c3", "args": QUERY})["permissionDecision"] == "deny"
    assert run({"id": "c3", "name": None, "args": {"tool_name": "Execute_Graph_Query"}})
    escaped = b'{"toolCalls":[{"id":"c4","args":{"x":"wiz\\u002dexecute"}}]}'
    assert run_hook(monkeypatch, capsys, escaped)["permissionDecision"] == "deny"
    # Unreadable names with nothing Wiz-like inside are allowed.
    assert run({"id": "c5", "args": {"command": "ls"}}) == {}
    assert run({"id": "c5", "name": None, "args": {"command": "ls"}}, 7, "text") == {}
    assert run({"id": "c5", "name": 12, "args": {}}) == {}
    # Other batch key spellings are evaluated like toolCalls.
    for key in ("tool_calls", "calls"):
        assert run({"id": "c6", "name": "view", "args": {}}, key=key) == {}
        denied = run({"id": "c6", "name": "wiz-execute", "args": QUERY}, key=key)
        assert denied["permissionDecision"] == "deny", key
        assert "c6" in denied["permissionDecisionReason"]
        assert run({"id": "c7", "args": QUERY}, key=key)["permissionDecision"] == "deny"
    assert run_hook(monkeypatch, capsys, b'{"foo":1,"bar":[1,2]}') == {}
    assert run_hook(monkeypatch, capsys, b'{"calls":"wiz-execute"}')["permissionDecision"]


def test_hook_parallel_wrapper_reads_every_args_key(monkeypatch, capsys):
    monkeypatch.delenv("WIZEXPERT_QA_REVIEW", raising=False)
    harmless = {"tool_uses": [{"recipient_name": "view", "parameters": {}}]}
    wiz = {"tool_uses": [{"recipient_name": "functions.wiz-execute", "parameters": QUERY}]}

    def run(element):
        raw = json.dumps({"toolCalls": [element]}).encode()
        return run_hook(monkeypatch, capsys, raw)

    wrapper = {"id": "call_p", "name": "parallel"}
    # (a) harmless args, bulk Wiz call under another key.
    for key in ("arguments", "input", "parameters"):
        denied = run(wrapper | {"args": harmless, key: wiz})
        assert denied["permissionDecision"] == "deny", key
        assert "call_p" in denied["permissionDecisionReason"]
        assert run(wrapper | {"args": harmless, key: json.dumps(wiz)})["permissionDecision"]
    # (b) nested wrapper: harmless args, Wiz call under parameters.
    nested = {"recipient_name": "parallel", "args": harmless, "parameters": wiz}
    assert run(wrapper | {"args": {"tool_uses": [nested]}})["permissionDecision"] == "deny"
    # An unreadable second value falls back to scanning the whole element.
    unreadable = wrapper | {"args": harmless, "arguments": "not json wiz-execute"}
    assert run(unreadable)["permissionDecision"] == "deny"
    assert run(wrapper | {"args": harmless, "arguments": "not json"}) == {}
    assert run(wrapper | {"args": harmless, "input": harmless}) == {}
    assert run(wrapper | {"args": harmless, "arguments": {"tool_uses": []}}) == {}


def test_hook_batch_with_reviewed_query_is_allowed(reviewed, monkeypatch, capsys):
    with patch("wizexpert.workflow_qa.datetime") as clock:
        clock.now.return_value = NOW
        clock.fromisoformat = datetime.fromisoformat
        raw = batch(("view", {}), ("wiz-execute", QUERY))
        assert run_hook(monkeypatch, capsys, raw, "--review", str(reviewed)) == {}
        other = json.loads(json.dumps(QUERY))
        other["parameters"]["status"] = ["RESOLVED"]
        raw = batch(("wiz-execute", other))
        denied = run_hook(monkeypatch, capsys, raw, "--review", str(reviewed))
        assert denied["permissionDecision"] == "deny"


def test_hook_deny_reason_has_no_absolute_paths(tmp_path, monkeypatch, capsys):
    missing = tmp_path / "private-dir" / "missing-review.json"
    for raw in (batch(("wiz-execute", QUERY)), camel("wiz-execute", QUERY)):
        denied = run_hook(monkeypatch, capsys, raw, "--review", str(missing))
        reason = denied["permissionDecisionReason"]
        assert str(tmp_path) not in reason
        assert "private-dir" not in reason
        assert "FileNotFoundError" in reason or "OSError" in reason
        assert "missing-review.json" in reason


@pytest.mark.parametrize(
    "parameters",
    [
        {"first": 1, "after": ""},
        {"first": 1, "after": 0},
        {"first": 1, "after": 5},
        {"first": 1, "after": ["c"]},
        {"first": 1, "after": False},
    ],
)
def test_is_bulk_rejects_odd_cursor_values(parameters):
    from wizexpert.workflow_qa import is_bulk

    with pytest.raises(ValueError, match="cursor"):
        is_bulk({"tool_name": "list_issues", "parameters": parameters})
    for args in ({"first": 1}, {"first": 1, "after": None}):
        assert is_bulk({"tool_name": "list_issues", "parameters": args}) is False
    assert is_bulk({"tool_name": "list_issues", "parameters": {"first": 1, "after": "c"}}) is True
    assert is_bulk({"tool_name": " LIST_ISSUES ", "parameters": {"first": 20}}) is True
    assert is_bulk({"tool_name": "Execute_Graph_Query", "parameters": {"first": 9}}) is True
    assert is_bulk({"tool_name": "get_issue", "parameters": {"first": 50}}) is False
    with pytest.raises(ValueError, match="tool name"):
        is_bulk({"tool_name": ["list_issues"], "parameters": {"first": 50}})


def test_hook_blocks_unreviewed_bulk_and_allows_count_probe():
    with pytest.raises(ValueError, match="requires a workflow QA"):
        hook({"tool_name": "wiz-execute", "tool_input": QUERY}, None)
    count = {"tool_name": "list_issues", "parameters": {"first": 1}}
    assert hook({"tool_name": "wiz-execute", "tool_input": count}, None) == {}
    with pytest.raises(ValueError, match="requires"):
        hook(
            {
                "tool_name": "multi_tool_use.parallel",
                "tool_input": {
                    "tool_uses": [{"recipient_name": "functions.wiz-execute", "parameters": QUERY}]
                },
            },
            None,
        )


def test_hook_exact_query_and_pagination(reviewed):
    with patch("wizexpert.workflow_qa.datetime") as clock:
        clock.now.return_value = NOW
        clock.fromisoformat = datetime.fromisoformat
        page = json.loads(json.dumps(QUERY))
        page["parameters"]["after"] = "returned-cursor"
        assert hook({"tool_name": "functions.wiz-execute", "tool_input": page}, reviewed) == {}
        page["parameters"]["status"] = ["RESOLVED"]
        with pytest.raises(ValueError, match="outside the reviewed plan"):
            hook({"tool_name": "wiz-execute", "tool_input": page}, reviewed)


def test_full_history_needs_evidence_backed_approval(reviewed):
    data = json.loads(reviewed.read_text())
    data["allowed_wiz_queries"][0]["parameters"]["status"] = ["OPEN", "IN_PROGRESS", "RESOLVED"]
    save(reviewed, data)
    with pytest.raises(ValueError, match="historical collection"):
        validate_review(reviewed, now=NOW)
    data["full_refresh_approval"] = {
        "reason": "Documented coverage gap",
        "approved_by": "report-owner",
        "evidence": next(iter(data["evidence_sha256"])),
    }
    save(reviewed, data)
    assert validate_review(reviewed, now=NOW)["phase"] == "collection"


@pytest.mark.parametrize("premature", [True, False])
def test_actual_calls_detect_deviation_even_when_all_checkboxes_pass(tmp_path, premature):
    collection = save(tmp_path / "collection.json", review_payload(tmp_path))
    data = review_payload(tmp_path, "generation")
    data["reviewed_at"] = (NOW - timedelta(minutes=1)).isoformat()
    data["previous_review"] = str(collection)
    args = json.loads(json.dumps(QUERY))
    if not premature:
        args["parameters"]["severity"] = ["LOW"]
    event_time = NOW - timedelta(minutes=90 if premature else 30)
    log = tmp_path / "activity.jsonl"
    log.write_text(
        json.dumps(
            {
                "timestamp": event_time.isoformat(),
                "type": "tool.execution_start",
                "data": {"toolName": "wiz-execute", "arguments": args},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    data["activity_log"] = str(log)
    data["evidence_sha256"].update({str(collection): digest(collection), str(log): digest(log)})
    generation = save(tmp_path / "generation.json", data)
    with pytest.raises(ValueError, match="before workflow QA|deviated"):
        validate_review(generation, now=NOW)


def test_qa_receipt_never_claims_release_approval(reviewed):
    with patch("wizexpert.workflow_qa.datetime") as clock:
        clock.now.return_value = NOW
        clock.fromisoformat = datetime.fromisoformat
        result = receipt(reviewed, "collection")
    assert result["status"] == "workflow_checks_passed"
    assert result["share_ready"] is False
    assert len(result["limitations"]) == 3


def test_requirements_cli_and_invalid_review_exit(capsys, tmp_path):
    assert main(["workflow-qa", "requirements", "--workflow", "finding", "--phase", "handoff"]) == 0
    assert (
        "email-template-and-identifiers" in json.loads(capsys.readouterr().out)["required_checks"]
    )
    with pytest.raises(SystemExit) as exc:
        main(["workflow-qa", "check", "--review", str(tmp_path / "missing.json")])
    assert exc.value.code == 1


@pytest.mark.parametrize(
    "workflow", ["governance", "finding", "setup", "publication", "remediation"]
)
def test_broad_profiles_are_explicit_and_evidence_bound(tmp_path, workflow):
    data = review_payload(tmp_path, workflow=workflow)
    if workflow == "remediation":
        data["target_stage"] = 5
    path = save(tmp_path / "review.json", data)
    assert validate_review(path, now=NOW)["workflow"] == workflow
    data["rule_coverage"].pop(next(iter(data["rule_coverage"])))
    save(path, data)
    with pytest.raises(ValueError, match="coverage is incomplete"):
        validate_review(path, now=NOW)


def test_campaign_requires_current_private_rules(tmp_path):
    data = review_payload(tmp_path, workflow="campaign")
    path = save(tmp_path / "review.json", data)
    with pytest.raises(ValueError, match="private campaign rules"):
        validate_review(path, now=NOW)
    private = tmp_path / "private-rules.md"
    private.write_text("# Metrics\nFinding counts are not asset counts.\n", encoding="utf-8")
    data["private_rule_sources"] = {str(private): digest(private)}
    data["evidence_sha256"].update(data["private_rule_sources"])
    for name, value in rule_inventory("campaign", data["private_rule_sources"]).items():
        if name not in data["rule_coverage"]:
            data["rule_coverage"][name] = {
                "source_sha256": value,
                "verdict": "pass",
                "rationale": "Synthetic private rules checked.",
                "evidence": [str(private)],
            }
    save(path, data)
    assert validate_review(path, now=NOW)["workflow"] == "campaign"
    private.write_text("# Changed metrics\nReview again.", encoding="utf-8")
    with pytest.raises(ValueError, match="evidence changed"):
        validate_review(path, now=NOW)


@pytest.mark.parametrize(
    "mutation,message",
    [
        ("unverified", "unverified"),
        ("stale", "stale"),
        ("out_of_scope", "scope decision"),
        ("conflict", "conflicts"),
        ("request", "original request"),
        ("missing_manifest", "requested-deliverable"),
    ],
)
def test_rule_coverage_and_original_request_cannot_be_skipped(tmp_path, mutation, message):
    data = review_payload(tmp_path)
    section = next(iter(data["rule_coverage"].values()))
    if mutation == "unverified":
        section["verdict"] = "unsupported"
    elif mutation == "stale":
        section["source_sha256"] = "0" * 64
    elif mutation == "out_of_scope":
        section["verdict"] = "out_of_scope"
    elif mutation == "conflict":
        data["unresolved_conflicts"] = ["Unresolved instruction conflict"]
    elif mutation == "request":
        del data["request_evidence"]
    else:
        del data["requested_deliverables"]
    path = save(tmp_path / "review.json", data)
    with pytest.raises(ValueError, match=message):
        validate_review(path, now=NOW)


def test_heading_only_rules_are_included_and_code_examples_are_not(tmp_path):
    private = tmp_path / "rules.md"
    private.write_text(
        "# Never skip approval\n## Evidence\n```text\n# Example\n```\n", encoding="utf-8"
    )
    inventory = rule_inventory("setup", {str(private): digest(private)})
    assert any("Never skip approval" in name for name in inventory)
    assert not any(name.endswith(":Example") for name in inventory)


def test_stage_tracker_cannot_certify_unapproved_remediation(tmp_path):
    from wizexpert.workflow import create_tracker
    from wizexpert.workflow_qa import validate_remediation

    data = review_payload(tmp_path, phase="generation", workflow="remediation")
    data["target_stage"] = 6
    tracker = tmp_path / "tracker.json"
    create_tracker(
        tracker,
        finding_id="synthetic",
        control_id="rule",
        scope=data["scope"],
        summary="Starting",
        next_action="Collect evidence",
    )
    data["tracker"] = str(tracker)
    data["evidence_sha256"][str(tracker)] = digest(tracker)
    with pytest.raises(ValueError, match="authorization/verification"):
        validate_remediation(data, data["evidence_sha256"])


def test_complete_finding_review_checks_requested_html_without_forcing_email(tmp_path):
    from test_artifact_qa import artifact, native_review

    item, evidence = artifact(tmp_path, "html")
    native_review(tmp_path, item, evidence)
    log = tmp_path / "activity.jsonl"
    log.write_text(
        json.dumps(
            {
                "timestamp": (NOW - timedelta(minutes=30)).isoformat(),
                "type": "tool.execution_start",
                "data": {"toolName": "view", "arguments": {}},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    previous = None
    for phase, minutes in (("collection", 60), ("generation", 20), ("handoff", 1)):
        data = review_payload(tmp_path, phase, workflow="finding")
        data["reviewer"] = "reviewer"
        data["requested_deliverables"] = [{"id": "html", "kind": "html"}]
        data["reviewed_at"] = (NOW - timedelta(minutes=minutes)).isoformat()
        if previous:
            data["previous_review"], data["activity_log"] = str(previous), str(log)
            data["evidence_sha256"].update({str(previous): digest(previous), str(log): digest(log)})
        if phase == "handoff":
            data["artifacts"] = [item]
            data["evidence_sha256"].update(evidence)
        previous = save(tmp_path / f"{phase}.json", data)
    assert validate_review(previous, now=NOW)["phase"] == "handoff"


def test_deliverables_cannot_be_removed_between_phases(tmp_path):
    data = review_payload(tmp_path)
    data["requested_deliverables"] = [{"id": "report", "kind": "xlsx"}]
    collection = save(tmp_path / "collection.json", data)
    generation = review_payload(tmp_path, "generation")
    generation["previous_review"] = str(collection)
    generation["evidence_sha256"][str(collection)] = digest(collection)
    path = save(tmp_path / "generation.json", generation)
    with pytest.raises(ValueError, match="deliverables cannot disappear"):
        validate_review(path, now=NOW)
