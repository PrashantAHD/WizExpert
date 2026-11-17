"""Registry of the canonical end-to-end rule lists, one per console category.

Every category in ``wizexpert.console.categories.CATEGORIES`` must have an entry here (drift
test) so the console shows an "End-to-end workflow rules" section for it. Rule modules share
one shape: ``RULES``, ``PHASES``, ``RULE_ID``, ``grouped()``, ``rules()`` and ``render_text()``.
Monthly Governance keeps its list in ``wizexpert.governance.workflow_rules`` (ids ``MG-``).

Imports nothing optional, so core commands stay free of governance extras.
"""

from __future__ import annotations

import json
from importlib import import_module
from types import ModuleType
from typing import Any

CATEGORY_MODULES: dict[str, str] = {
    "risk-issues": "wizexpert.category_rules.risk_issues",
    "daily-progress-reporting": "wizexpert.category_rules.daily_progress",
    "weekly-progress-reporting": "wizexpert.category_rules.weekly_progress",
    "monthly-governance-reporting": "wizexpert.governance.workflow_rules",
}
# Workflows that are not deliverable categories (no Collect/Generate/Start actions).
WORKFLOW_MODULES: dict[str, str] = {
    "sync": "wizexpert.category_rules.sync",
}
ALIASES = {"risk": "risk-issues", "daily": "daily-progress-reporting",
           "weekly": "weekly-progress-reporting", "monthly": "monthly-governance-reporting"}

USAGE = "usage: wizexpert rules [<category>|sync] [--json]\n  categories: " + ", ".join(
    f"{alias} ({cid})" for alias, cid in ALIASES.items()
) + "\n  workflows: sync"


def resolve(name: str) -> str | None:
    name = name.strip().lower()
    name = ALIASES.get(name, name)
    return name if name in CATEGORY_MODULES or name in WORKFLOW_MODULES else None


def module_for(category_id: str) -> ModuleType | None:
    path = CATEGORY_MODULES.get(category_id) or WORKFLOW_MODULES.get(category_id)
    return import_module(path) if path else None


def workflow_payloads() -> list[dict[str, Any]]:
    """Console payloads of the non-category workflows (currently Sync)."""
    return [module_for(wid).workflow_payload() for wid in WORKFLOW_MODULES]


def rule_payload(category_id: str) -> dict[str, Any]:
    """Console payload fragment (``rules`` grouped by phase and ``rule_count``)."""
    module = module_for(category_id)
    if module is None:
        return {"rules": [], "rule_count": 0}
    return {"rules": module.grouped(), "rule_count": len(module.RULES)}


def main(argv: list[str] | None = None) -> int:
    """``wizexpert rules [<category>] [--json]``."""
    arguments = list(argv or [])
    as_json = "--json" in arguments
    rest = [a for a in arguments if a != "--json"]
    if len(rest) > 1 or any(a.startswith("-") for a in rest):
        print(USAGE)
        return 2
    if not rest:
        counts = {cid: len(module_for(cid).RULES)
                  for cid in (*CATEGORY_MODULES, *WORKFLOW_MODULES)}
        if as_json:
            print(json.dumps(counts, indent=2))
            return 0
        print("End-to-end workflow rules per category:")
        for cid, count in counts.items():
            print(f"  {cid}: {count}")
        print("\n" + USAGE)
        return 0
    category_id = resolve(rest[0])
    if category_id is None:
        print(USAGE)
        return 2
    module = module_for(category_id)
    if as_json:
        print(json.dumps({"category": category_id, "rules": module.rules(),
                          "phases": module.grouped()}, indent=2))
    else:
        print(module.render_text())
    return 0
