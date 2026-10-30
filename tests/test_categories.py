from __future__ import annotations

from wizexpert.governance import categories as cat


def good_binding(category: cat.Category) -> dict:
    return {
        "version": category.version,
        "slots": {s.slot_id: {"template_sha256": "a" * 64} for s in category.slots},
    }


def test_slot_counts():
    assert len(cat.RISK_ISSUES.slots) == 6
    assert len(cat.DAILY_PROGRESS.slots) == 4


def test_manifest_is_placeholder_only_and_stable():
    for category in cat.CATEGORIES.values():
        text = str(category.manifest())
        assert "<private-template:" in text and "<pinned-at-binding>" in text
        assert category.fingerprint() == category.fingerprint()
        assert any("legacy bespoke" in rule for rule in category.manifest()["rules"])


def test_valid_binding_passes():
    for category in cat.CATEGORIES.values():
        assert cat.validate_binding(category.category_id, good_binding(category)) == []


def test_drift_is_reported():
    binding = good_binding(cat.RISK_ISSUES)
    binding["slots"].pop("internal-analysis")
    binding["slots"]["custom"] = {"template_sha256": "xyz"}
    binding["version"] = 99
    problems = " ".join(cat.validate_binding("risk-issues", binding))
    assert "missing template" in problems and "bespoke" in problems
    assert "version" in problems and "SHA-256" in problems


def test_unknown_category():
    assert cat.validate_binding("nope", {})


def test_exact_slot_ids():
    assert [s.slot_id for s in cat.RISK_ISSUES.slots] == [
        "internal-analysis", "client-assessment", "stakeholder-email",
        "detailed-report", "internal-follow-up-email", "updated-detailed-report",
    ]
    assert [s.slot_id for s in cat.DAILY_PROGRESS.slots] == [
        "daily-progress-report", "day-to-day-movements",
        "vm-and-cve-details", "stakeholder-reply-email",
    ]
