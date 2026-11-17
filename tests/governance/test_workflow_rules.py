"""Drift guards for the canonical Monthly workflow rules."""

import ast
import json
import re
from pathlib import Path

from wizexpert.__main__ import main
from wizexpert.console import categories
from wizexpert.governance import workflow_rules as wr

ROOT = Path(__file__).resolve().parents[2]


def flat(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("`", ""))


def test_ids_unique_and_well_formed():
    ids = [r.rule_id for r in wr.RULES]
    assert len(ids) == len(set(ids))
    assert all(wr.RULE_ID.fullmatch(i) for i in ids)
    phases = {p for p, _ in wr.PHASES}
    assert {r.phase for r in wr.RULES} == phases
    assert all(r.text.strip() for r in wr.RULES)


def test_each_id_matches_its_phase_prefix():
    prefix = {
        "run": "RUN",
        "collection": "COL",
        "ledger": "LED",
        "plan": "PLN",
        "tracking": "TRK",
        "cutoff": "CUT",
        "integrity": "INT",
        "release": "REL",
        "boundary": "BND",
    }
    for r in wr.RULES:
        assert r.rule_id.split("-")[1] == prefix[r.phase]


def test_enforced_by_names_existing_gates():
    for r in wr.RULES:
        if r.enforced_by == wr.INSTRUCTION:
            continue
        module, _, function = r.enforced_by.partition(":")
        assert module.startswith("wizexpert.") and function, r.rule_id
        source = ROOT.joinpath(*module.split(".")).with_suffix(".py")
        assert source.is_file(), (r.rule_id, source)
        tree = ast.parse(source.read_text(encoding="utf-8"))
        names = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
        assert function in names, (r.rule_id, r.enforced_by)


def test_monthly_prompt_loads_rules_and_stays_safe():
    note = categories.MONTHLY_END_TO_END_NOTE
    assert "wizexpert governance rules" in note
    assert "fail-closed" in note and "rule id" in note
    assert categories.ACTION_SAFE.fullmatch(note)
    longest = max(len(p) for p in categories.STAGE_PROMPTS.values())
    assert 600 + len(note) + longest < 4800


def test_console_payload_includes_rules():
    monthly = categories.CATEGORIES["monthly-governance-reporting"].to_json()
    assert monthly["rule_count"] == len(wr.RULES)
    listed = [r["id"] for g in monthly["rules"] for r in g["rules"]]
    assert listed == [r.rule_id for r in wr.RULES]


def test_cli_text_and_json(capsys):
    assert main(["governance", "rules"]) == 0
    out = capsys.readouterr().out
    assert "MG-COL-02" in out and "first=500" in out
    assert main(["governance", "rules", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert len(data["rules"]) == len(wr.RULES)
    assert main(["governance", "rules", "--bogus"]) == 2


def test_key_invariants_in_canonical_list_and_docs():
    canonical = flat(" ".join(r.text for r in wr.RULES))
    runbook = flat((ROOT / "docs" / "GOVERNANCE-RUNBOOK.md").read_text(encoding="utf-8"))
    qa = flat((ROOT / "docs" / "WORKFLOW-QA.md").read_text(encoding="utf-8"))
    invariants = [
        ("first=500", "first=500", "first=500"),
        (
            "Total = Open + Resolved + Ignored",
            "Total = Open + Resolved + Ignored",
            "Total = Open + Resolved + Ignored",
        ),
        (
            "REJECTED is reported as Ignored",
            "REJECTED is reported as Ignored",
            "REJECTED = Ignored",
        ),
        (
            "collect check must be READY",
            "collection gate must be READY",
            "collection gate is READY",
        ),
    ]
    for rule_text, runbook_text, qa_text in invariants:
        assert rule_text in canonical, rule_text
        assert runbook_text in runbook, runbook_text
        assert qa_text in qa, qa_text
    for doc in (runbook, qa):
        assert "workflow_rules.py" in doc
