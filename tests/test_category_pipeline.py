from __future__ import annotations

import hashlib

import pytest

from wizexpert.governance import categories as cat
from wizexpert.governance.category_pipeline import (
    PipelineError,
    SlotBinding,
    run_category_pipeline,
)

PLACEHOLDER_SHA = hashlib.sha256(b"placeholder").hexdigest()


def make(category, calls, fail=None):
    def builder_for(slot_id):
        def build(out_dir):
            calls.append(slot_id)
            path = out_dir / f"{slot_id}.txt"
            path.write_text("placeholder")
            return path

        return build

    def validator_for(slot_id):
        return lambda path: ["bad"] if slot_id == fail else []

    return {
        s.slot_id: SlotBinding("a" * 64, builder_for(s.slot_id), validator_for(s.slot_id))
        for s in category.slots
    }


def qa(category):
    return {
        "workflow_qa": "passed",
        "review": "passed",
        "category_id": category.category_id,
        "version": category.version,
        "slots": [s.slot_id for s in category.slots],
        "template_sha256": {s.slot_id: "a" * 64 for s in category.slots},
        "outputs_sha256": {s.slot_id: PLACEHOLDER_SHA for s in category.slots},
    }


@pytest.mark.parametrize("category", list(cat.CATEGORIES.values()))
def test_success(category, tmp_path):
    calls: list[str] = []
    res = run_category_pipeline(
        category.category_id, category.version, make(category, calls), tmp_path, qa(category)
    )
    assert res.complete and calls == [s.slot_id for s in category.slots]


def test_wrong_version_runs_no_builder(tmp_path):
    calls: list[str] = []
    c = cat.RISK_ISSUES
    with pytest.raises(PipelineError, match="version"):
        run_category_pipeline(c.category_id, c.version + 1, make(c, calls), tmp_path, qa(c))
    assert calls == []


def test_missing_and_extra_slot(tmp_path):
    calls: list[str] = []
    c = cat.DAILY_PROGRESS
    b = make(c, calls)
    b.pop("vm-and-cve-details")
    with pytest.raises(PipelineError, match="missing template"):
        run_category_pipeline(c.category_id, c.version, b, tmp_path, qa(c))
    b = make(c, calls)
    b["custom"] = b["day-to-day-movements"]
    with pytest.raises(PipelineError, match="bespoke"):
        run_category_pipeline(c.category_id, c.version, b, tmp_path, qa(c))
    assert calls == []


def test_unknown_category(tmp_path):
    with pytest.raises(PipelineError, match="unknown"):
        run_category_pipeline("nope", 1, {}, tmp_path, None)


def test_validator_failure_stops(tmp_path):
    calls: list[str] = []
    c = cat.RISK_ISSUES
    with pytest.raises(PipelineError, match="validator failed"):
        run_category_pipeline(
            c.category_id, c.version, make(c, calls, fail="client-assessment"), tmp_path, qa(c)
        )
    assert calls == ["internal-analysis", "client-assessment"]


def _evidence(change):
    evidence = qa(cat.RISK_ISSUES)
    evidence.update(change)
    return evidence


@pytest.mark.parametrize(
    "evidence",
    [
        None,
        {},
        _evidence({"review": "failed"}),
        _evidence({"workflow_qa": "pending"}),
        _evidence({"version": 1}),
        _evidence({"category_id": "daily-progress-reporting"}),
        _evidence({"slots": ["internal-analysis"]}),
        _evidence({"outputs_sha256": {"internal-analysis": "0" * 64}}),
        _evidence({"template_sha256": {"internal-analysis": "b" * 64}}),
    ],
)
def test_qa_review_required(evidence, tmp_path):
    c = cat.RISK_ISSUES
    with pytest.raises(PipelineError, match="QA and review"):
        run_category_pipeline(c.category_id, c.version, make(c, []), tmp_path, evidence)

def test_template_file_must_match_pin(tmp_path):
    c = cat.RISK_ISSUES
    template = tmp_path / "t.html"
    template.write_text("x")
    b = make(c, [])
    first = c.slots[0].slot_id
    old = b[first]
    b[first] = SlotBinding("a" * 64, old.builder, old.validator, template)
    with pytest.raises(PipelineError, match="does not match"):
        run_category_pipeline(c.category_id, c.version, b, tmp_path, qa(c))
