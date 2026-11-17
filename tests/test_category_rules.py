"""Drift guards for the per-category end-to-end rule lists (every console category)."""

import ast
import json
import re
from pathlib import Path

import pytest

from wizexpert.__main__ import main
from wizexpert.category_rules import CATEGORY_MODULES, module_for
from wizexpert.console import categories

ROOT = Path(__file__).resolve().parents[1]
PREFIX = {"risk-issues": "RI", "daily-progress-reporting": "DP",
          "weekly-progress-reporting": "WP", "monthly-governance-reporting": "MG"}
PRIVATE = re.compile(r"CVE-\d{4}-\d+|C:\\\\Users", re.IGNORECASE)


def test_every_console_category_has_rules():
    assert set(CATEGORY_MODULES) == set(categories.CATEGORIES)
    assert set(PREFIX) == set(categories.CATEGORIES)


@pytest.mark.parametrize("category_id", sorted({*CATEGORY_MODULES, "sync"}))
def test_rule_list_shape(category_id):
    module = module_for(category_id)
    rules = module.RULES
    ids = [r.rule_id for r in rules]
    assert ids and len(ids) == len(set(ids))
    assert all(module.RULE_ID.fullmatch(i) for i in ids)
    assert all(i.startswith({**PREFIX, "sync": "SY"}[category_id] + "-") for i in ids)
    phases = {p for p, _ in module.PHASES}
    assert {r.phase for r in rules} == phases
    assert all(r.text.strip() for r in rules)
    # Every id appears in display order (grouped output covers all rules exactly once).
    grouped = [r["id"] for g in module.grouped() for r in g["rules"]]
    assert sorted(grouped) == sorted(ids)
    if hasattr(module, "PHASE_CODES"):
        for r in rules:
            assert r.rule_id.split("-")[1] == module.PHASE_CODES[r.phase]
    # Nothing in the public repo may carry client or campaign identifiers.
    assert not PRIVATE.search(" ".join(r.text for r in rules))


@pytest.mark.parametrize("category_id", sorted({*CATEGORY_MODULES, "sync"}))
def test_enforced_by_names_existing_gates(category_id):
    for r in module_for(category_id).RULES:
        if r.enforced_by == "agent-instruction":
            continue
        module, _, function = r.enforced_by.partition(":")
        assert function, r.rule_id
        if module.endswith(".js"):  # console client gate: `path/to/file.js:functionName`
            text = (ROOT / module).read_text(encoding="utf-8")
            assert f"function {function}(" in text, (r.rule_id, r.enforced_by)
            continue
        assert module.startswith("wizexpert."), r.rule_id
        source = ROOT.joinpath(*module.split(".")).with_suffix(".py")
        assert source.is_file(), (r.rule_id, source)
        tree = ast.parse(source.read_text(encoding="utf-8"))
        names = {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}
        for cls in (n for n in tree.body if isinstance(n, ast.ClassDef)):
            names |= {f"{cls.name}.{n.name}" for n in cls.body if isinstance(n, ast.FunctionDef)}
        assert function in names, (r.rule_id, r.enforced_by)


@pytest.mark.parametrize("category_id", sorted(CATEGORY_MODULES))
def test_console_payload_includes_rules(category_id):
    module = module_for(category_id)
    payload = categories.CATEGORIES[category_id].to_json()
    assert payload["rule_count"] == len(module.RULES) > 0
    assert [r["id"] for g in payload["rules"] for r in g["rules"]] == [
        r.rule_id for r in module.RULES
    ] or sorted(r["id"] for g in payload["rules"] for r in g["rules"]) == sorted(
        r.rule_id for r in module.RULES
    )


def test_cli_per_category(capsys):
    assert main(["rules", "risk"]) == 0
    assert "RI-SCP-01" in capsys.readouterr().out
    assert main(["rules", "weekly-progress-reporting", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["category"] == "weekly-progress-reporting"
    assert all(r["id"].startswith("WP-") for r in data["rules"])
    assert main(["rules", "monthly"]) == 0
    assert "MG-COL-02" in capsys.readouterr().out
    assert main(["rules"]) == 0
    assert "daily-progress-reporting" in capsys.readouterr().out
    assert main(["rules", "nope"]) == 2
    assert main(["rules", "--bogus"]) == 2
    assert main(["governance", "rules"]) == 0


def test_docs_point_to_canonical_lists():
    qa = (ROOT / "docs" / "WORKFLOW-QA.md").read_text(encoding="utf-8")
    console = (ROOT / "docs" / "CONSOLE.md").read_text(encoding="utf-8")
    assert "wizexpert/category_rules" in qa and "wizexpert rules" in qa
    assert "wizexpert/category_rules" in console


def test_daily_rules_cover_fresh_evidence_and_no_send_boundaries():
    rules = {r.rule_id: r for r in module_for("daily-progress-reporting").RULES}
    assert rules["DP-COL-08"].enforced_by == "wizexpert.console.freshness:gate"
    assert "DP-MET-06" in rules and "DP-BND-04" in rules
    assert {"DP-BND-01", "DP-BND-02", "DP-BND-03"} <= set(rules)
    text = " ".join(r.text for r in rules.values())
    assert "never proof" in text and "current UTC date" in text
    console = (ROOT / "docs" / "CONSOLE.md").read_text(encoding="utf-8")
    assert "DP-COL-08" in console