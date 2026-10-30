"""Enforced category pipeline: select -> fixed slots -> build -> validate -> QA/review.

The caller binds each fixed slot to a private builder and validator (plain
callables supplied from private storage). This module only orchestrates: it
never collects from Wiz, sends email or touches any system. Completion is
reported only after every slot was built by its bound builder, passed its bound
validator, and workflow-QA plus review evidence was supplied.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .categories import CATEGORIES, validate_binding


class PipelineError(RuntimeError):
    """Raised when the pipeline is bypassed or a stage fails."""


@dataclass(frozen=True)
class SlotBinding:
    template_sha256: str
    builder: Callable[[Path], Path]  # builds the slot deliverable into out_dir
    validator: Callable[[Path], list[str]]  # returns problems; empty means valid
    template_path: Path | None = None  # when given, its bytes must hash to template_sha256


@dataclass
class PipelineResult:
    category_id: str
    version: int
    outputs: dict[str, Path] = field(default_factory=dict)
    complete: bool = False


def run_category_pipeline(
    category_id: str,
    version: int,
    bindings: Mapping[str, SlotBinding],
    out_dir: Path,
    qa_review: Mapping[str, Any] | None,
) -> PipelineResult:
    category = CATEGORIES.get(category_id)
    if category is None:
        raise PipelineError(f"unknown category {category_id!r}")
    binding_doc = {
        "version": version,
        "slots": {k: {"template_sha256": b.template_sha256} for k, b in bindings.items()},
    }
    problems = validate_binding(category_id, binding_doc)
    for slot_id, bound in bindings.items():
        if bound.template_path is not None:
            actual = _sha256(Path(bound.template_path))
            if actual is None or actual != bound.template_sha256:
                problems.append(f"slot {slot_id!r} template does not match its pinned SHA-256")
    if problems:
        raise PipelineError("binding rejected: " + "; ".join(problems))
    result = PipelineResult(category_id, category.version)
    for slot in category.slots:  # fixed order; only the bound builder runs
        bound = bindings[slot.slot_id]
        out = Path(bound.builder(Path(out_dir)))
        failures = list(bound.validator(out))
        if failures:
            raise PipelineError(f"validator failed for {slot.slot_id!r}: " + "; ".join(failures))
        result.outputs[slot.slot_id] = out
    qa = qa_review or {}
    expected_outputs = {k: _sha256(v) for k, v in result.outputs.items()}
    expected_templates = {k: b.template_sha256 for k, b in bindings.items()}
    if not (
        qa.get("workflow_qa") == "passed"
        and qa.get("review") == "passed"
        and qa.get("category_id") == category_id
        and qa.get("version") == category.version
        and sorted(qa.get("slots", [])) == sorted(result.outputs)
        and qa.get("template_sha256") == expected_templates
        and qa.get("outputs_sha256") == expected_outputs
    ):
        raise PipelineError("workflow-QA and review evidence missing or not matching this run")
    result.complete = True
    return result


def _sha256(path: Path) -> str | None:
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return None
