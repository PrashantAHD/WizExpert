"""Shared shape for the canonical per-category end-to-end rule lists.

Each category module defines ``TITLE``, ``RULE_ID``, ``PHASES``, ``PHASE_CODES`` and ``RULES``
and builds its ``grouped``/``rules``/``render_text`` helpers with the functions below. The
Monthly list (``wizexpert.governance.workflow_rules``) predates this package and keeps its own
identical shape; the registry in ``wizexpert.category_rules`` treats it the same way.

``enforced_by`` is ``"agent-instruction"`` or ``"module:function"`` naming a code gate under
the ``wizexpert`` package; drift tests verify that every named gate exists.

This package imports nothing optional so core commands stay free of governance extras.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, NamedTuple

INSTRUCTION = "agent-instruction"


class Rule(NamedTuple):
    rule_id: str
    phase: str
    text: str
    enforced_by: str = INSTRUCTION

    def to_json(self) -> dict[str, str]:
        return {
            "id": self.rule_id,
            "phase": self.phase,
            "text": self.text,
            "enforced_by": self.enforced_by,
        }


def rules_json(rules: Sequence[Rule]) -> list[dict[str, str]]:
    return [r.to_json() for r in rules]


def group_rules(rules: Sequence[Rule], phases: Sequence[tuple[str, str]]) -> list[dict[str, Any]]:
    """Rules grouped by phase, in display order."""
    return [
        {
            "phase": phase_id,
            "title": title,
            "rules": [r.to_json() for r in rules if r.phase == phase_id],
        }
        for phase_id, title in phases
    ]


def render_rules(
    title: str, rules: Sequence[Rule], phases: Sequence[tuple[str, str]]
) -> str:
    lines = [f"{title} ({len(rules)})", ""]
    for phase_id, phase_title in phases:
        lines.append(phase_title)
        for r in (x for x in rules if x.phase == phase_id):
            lines.append(f"  {r.rule_id}  {r.text}")
            lines.append(f"      enforced by: {r.enforced_by}")
        lines.append("")
    return "\n".join(lines)
