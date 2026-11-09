from wizexpert.console.runs import (
    Run,
    _brief,
    _is_settled,
    build_checklist,
    outcome_reason,
    run_subject,
)


def states(steps):
    return {s["id"]: s["state"] for s in steps}


def test_checklist_four_states_plain_run():
    steps, outcome = build_checklist("completed", [], False, None, "")
    assert outcome == "completed"
    assert states(steps) == {
        "run": "completed",
        "gates": "not_applicable",
        "outputs": "not_applicable",
    }
    steps, outcome = build_checklist(
        "completed", [{"state": "approved"}, {"state": "skipped"}], True, None, ""
    )
    assert states(steps)["gates"] == "skipped" and states(steps)["outputs"] == "completed"
    steps, outcome = build_checklist("rejected", [{"state": "rejected"}], False, None, "")
    assert outcome == "rejected"
    assert states(steps) == {"run": "blocked", "gates": "blocked", "outputs": "skipped"}
    steps, _ = build_checklist("completed", [{"state": "approved"}], True, None, "")
    assert states(steps)["gates"] == "completed"


def _sync(**kw):
    base = {"phase": "done", "changed": ["CaseA"], "queued": [], "skipped": []}
    base.update(kw)
    return base


def test_status_check_changed_case_queued_is_completed():
    sync = _sync(queued=[{"case": "CaseA", "run_id": "r"}])
    steps, outcome = build_checklist("completed", [], False, sync, "status-check")
    assert outcome == "completed"
    assert states(steps)["refresh:CaseA"] == "completed"
    assert states(steps)["readonly"] == "completed"
    assert [s["label"] for s in steps if s["id"] == "refresh:CaseA"] == ["Refresh queued: CaseA"]


def test_status_check_unqueued_or_skipped_is_incomplete():
    steps, outcome = build_checklist(
        "completed", [], False, _sync(phase="refreshing"), "status-check"
    )
    assert outcome == "incomplete" and states(steps)["refresh:CaseA"] == "blocked"
    sync = _sync(skipped=[{"case": "CaseA", "reason": "refused"}])
    steps, outcome = build_checklist("completed", [], False, sync, "status-check")
    assert outcome == "incomplete"
    step = [s for s in steps if s["id"] == "refresh:CaseA"][0]
    assert step["state"] == "skipped" and step["detail"] == "refused"


def test_status_check_no_changes_and_other_phases():
    steps, outcome = build_checklist("completed", [], False, _sync(changed=[]), "status-check")
    assert outcome == "completed" and states(steps)["refresh"] == "not_applicable"
    steps, outcome = build_checklist("completed", [], False, None, "status-check")
    assert outcome == "completed" and states(steps)["refresh"] == "not_applicable"
    steps, outcome = build_checklist("completed", [], False, {"phase": "checking"}, "status-check")
    assert outcome == "incomplete" and states(steps)["refresh"] == "blocked"
    steps, outcome = build_checklist("stopped", [], False, {"phase": "checking"}, "status-check")
    assert outcome == "stopped"
    steps, outcome = build_checklist("completed", [], False, {"phase": "failed"}, "status-check")
    assert outcome == "incomplete"
    steps, outcome = build_checklist("stopped", [], False, None, "status-check")
    assert outcome == "stopped" and states(steps)["readonly"] == "blocked"


def test_reason_is_preserved_per_cause():
    steps, _ = build_checklist(
        "completed",
        [],
        False,
        {"phase": "failed", "error": "check did not produce a result"},
        "status-check",
    )
    assert outcome_reason(steps) == "check did not produce a result"
    sync = _sync(skipped=[{"case": "CaseA", "reason": "refused: not eligible"}])
    steps, _ = build_checklist("completed", [], False, sync, "status-check")
    assert outcome_reason(steps) == "CaseA: refused: not eligible"
    steps, outcome = build_checklist(
        "stopped", [], False, {"phase": "failed", "error": "boom"}, "status-check"
    )
    assert outcome == "incomplete" and outcome_reason(steps) == "Run ended as stopped; boom"
    steps, _ = build_checklist("completed", [], False, _sync(phase="refreshing"), "status-check")
    assert "one-active-run guard" in outcome_reason(steps)
    steps, _ = build_checklist("completed", [], False, None, "")
    assert outcome_reason(steps) == ""


def test_settled_only_when_sync_can_no_longer_change():
    assert _is_settled("completed", None, "")
    assert not _is_settled("completed", None, "status-check")
    assert not _is_settled("completed", {"phase": "checking"}, "status-check")
    assert not _is_settled("completed", {"phase": "refreshing"}, "status-check")
    assert _is_settled("completed", {"phase": "done"}, "status-check")
    assert _is_settled("stopped", None, "status-check")


def _run(values, **kw):
    return Run(id="r", category_id="risk-issues", values=values, prompt="", created=0.0, **kw)


def test_subject_caps_long_case_lists_and_keeps_titles():
    cases = [f"Synthetic-Case-Number-{i}-" + "long-title-words-" * 6 for i in range(8)]
    subject = run_subject(_run({"case_list": ", ".join(cases)}))
    assert len(subject) <= 160
    assert subject.startswith("Synthetic Case Number 0 long title")
    assert "Synthetic Case Number 1" in subject
    assert "(+6 more)" in subject and "Synthetic Case Number 2" not in subject
    assert run_subject(_run({"case_list": "A-b, C-d"})) == "A b; C d"
    assert len(run_subject(_run({"case_folder": "Synthetic-" + "word-" * 80}))) <= 160


def test_brief_exposes_outcome():
    assert _brief(_run({}, status="completed"))["outcome"] == "completed"
    assert _brief(_run({}, status="completed"), "incomplete")["outcome"] == "incomplete"
