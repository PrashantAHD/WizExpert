"""The three reporting categories: form fields, strict validation and the prompt typed for you.

The prompt is the whole interface to the agent session: the console adds no workflow rules.
Input is allow-listed (characters and length) so a form value cannot add instructions.
Templates may be overridden from the private console config (``prompts``).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

MAX_PROMPT = 600
ISSUE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{1,63}")
MONTH = re.compile(r"(20[2-9][0-9])-(0[1-9]|1[0-2])")
NOTE_CHARS = re.compile(r"[A-Za-z0-9 ._-]{1,80}")
SAFE_PROMPT = re.compile(r"[A-Za-z0-9 .,;:()/_-]{1,600}")
MAX_ISSUES = 10


class InputError(ValueError):
    """A form value was rejected (message is safe to show)."""


@dataclass(frozen=True)
class FieldSpec:
    name: str
    label: str
    help: str
    required: bool = False
    pattern: str = ""
    max_length: int = 0
    placeholder: str = ""

    def to_json(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "label": self.label,
            "help": self.help,
            "required": self.required,
            "max_length": self.max_length,
            "placeholder": self.placeholder,
        }


@dataclass(frozen=True)
class Category:
    category_id: str
    title: str
    description: str
    fields: tuple[FieldSpec, ...]
    template: str

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.category_id,
            "title": self.title,
            "description": self.description,
            "fields": [f.to_json() for f in self.fields],
        }


CATEGORIES: dict[str, Category] = {
    "risk-issues": Category(
        "risk-issues",
        "Risk Issues",
        "Prepare the Risk Issues deliverables for one or more Wiz issue (rule) IDs.",
        (
            FieldSpec(
                "issue_ids",
                "Wiz issue ID(s)",
                f"One or more IDs separated by commas or spaces (up to {MAX_ISSUES}); "
                "letters, digits, dot, dash, underscore.",
                required=True,
                max_length=400,
                placeholder="example: wc-id-1234",
            ),
        ),
        "Risk Issues category: prepare the deliverables for Wiz issue {issue_ids}",
    ),
    "daily-progress-reporting": Category(
        "daily-progress-reporting",
        "Daily Progress Reporting",
        "Prepare the Daily Progress Reporting pack for today.",
        (
            FieldSpec(
                "note",
                "Optional note",
                "Short plain text appended to the request "
                "(letters, digits, spaces, dot, dash, underscore).",
                max_length=80,
            ),
        ),
        "Daily Progress Reporting category: prepare the daily progress report for today{note}",
    ),
    "monthly-governance-reporting": Category(
        "monthly-governance-reporting",
        "Monthly Governance Reporting",
        "Prepare the monthly governance reporting for a snapshot period.",
        (
            FieldSpec(
                "month",
                "Snapshot period (YYYY-MM)",
                "The reporting month, for example 2026-10.",
                required=True,
                max_length=7,
                placeholder="YYYY-MM",
            ),
        ),
        "Monthly Governance Reporting category: "
        "prepare the monthly governance reporting for {month}",
    ),
}


def _issue_ids(raw: Any) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise InputError("Enter at least one Wiz issue ID.")
    if len(raw) > 400:
        raise InputError("The issue ID list is too long.")
    parts = [p for p in re.split(r"[,\s]+", raw.strip()) if p]
    if not parts or len(parts) > MAX_ISSUES:
        raise InputError(f"Enter between 1 and {MAX_ISSUES} issue IDs.")
    seen: list[str] = []
    for part in parts:
        if not ISSUE_ID.fullmatch(part):
            raise InputError(
                "Issue IDs may contain only letters, digits, dot, dash and underscore "
                "(2 to 64 characters each)."
            )
        if part not in seen:
            seen.append(part)
    return ", ".join(seen)


def _month(raw: Any) -> str:
    if not isinstance(raw, str) or not MONTH.fullmatch(raw.strip()):
        raise InputError("Enter the snapshot period as YYYY-MM, for example 2026-10.")
    return raw.strip()


def _note(raw: Any) -> str:
    if raw is None or raw == "":
        return ""
    if not isinstance(raw, str):
        raise InputError("The note must be text.")
    text = " ".join(raw.split())
    if not text:
        return ""
    if not NOTE_CHARS.fullmatch(text):
        raise InputError(
            "The note may be at most 80 characters: letters, digits, spaces, dot, dash, underscore."
        )
    return text


def validate(category_id: str, raw: Mapping[str, Any]) -> dict[str, str]:
    """Return cleaned values for a category or raise InputError."""
    category = CATEGORIES.get(category_id)
    if category is None:
        raise InputError("Unknown category.")
    allowed = {f.name for f in category.fields}
    extra = sorted(set(raw) - allowed)
    if extra:
        raise InputError("Unexpected field(s): " + ", ".join(extra))
    cleaners = {"issue_ids": _issue_ids, "month": _month, "note": _note}
    return {f.name: cleaners[f.name](raw.get(f.name)) for f in category.fields}


def build_prompt(
    category_id: str, values: Mapping[str, str], overrides: Mapping[str, str] | None = None
) -> str:
    """The exact text typed into the new chat. Values are already validated."""
    category = CATEGORIES[category_id]
    template = (overrides or {}).get(category_id, category.template)
    note = values.get("note", "")
    mapping = {
        "issue_ids": values.get("issue_ids", ""),
        "month": values.get("month", ""),
        "note": f". Note: {note}" if note else "",
    }
    prompt = re.sub(r"\{(\w+)\}", lambda m: mapping.get(m.group(1), m.group(0)), template)
    if len(prompt) > MAX_PROMPT or not SAFE_PROMPT.fullmatch(prompt):
        raise InputError("The prompt is too long or contains unsupported characters.")
    return prompt
