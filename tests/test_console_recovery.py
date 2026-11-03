"""A run never fails because of a stale/unresponsive VS Code window or helper."""

from __future__ import annotations

from console_fakes import FakeHelper

from wizexpert.console import runs
from wizexpert.console.bridge import Bridge
from wizexpert.console.config import ConsoleConfig
from wizexpert.console.runs import RunManager


def _setup(tmp_path, monkeypatch):
    workspace = tmp_path / "ws"
    (workspace / "deliverables").mkdir(parents=True)
    config = ConsoleConfig(
        workspace=workspace,
        copilot_home=tmp_path / "copilot",
        state_dir=tmp_path / "state",
        vscode_user_dir=tmp_path / "vscode",
    )
    monkeypatch.setattr(runs, "PROBE_SECONDS", 0.5)
    monkeypatch.setattr(runs, "START_SECONDS", 0.5)
    monkeypatch.setattr(runs, "ATTEMPT_SECONDS", 0.2)
    bridge = Bridge("t" * 64)
    manager = RunManager(config, bridge, run_async=False, sleep=lambda _s: None)
    return config, workspace, bridge, manager


def test_stale_connected_helper_triggers_new_window_and_run_starts(tmp_path, monkeypatch):
    config, workspace, bridge, manager = _setup(tmp_path, monkeypatch)
    stale = FakeHelper(bridge, workspace, tmp_path / "copilot", name="stale", answer=False)
    fresh = FakeHelper(bridge, workspace, tmp_path / "copilot", name="fresh")
    opened = []

    def ensure():
        opened.append(1)
        fresh.thread.start()  # "code -n" opened a new window whose helper polls
        return True

    with stale:
        assert bridge.helper_connected(str(workspace))
        run = manager.start("daily-progress-reporting", {}, ensure_helper=ensure)
        fresh._stop.set()
        fresh.thread.join(timeout=3)
    assert opened == [1]
    assert run.status == "running"
    assert [j["kind"] for j in fresh.jobs] == ["start_chat"]
    assert fresh.jobs[0]["target"] == "fresh"
    assert not any(j["kind"] == "start_chat" for j in stale.jobs)  # stale one never got the job
    assert any("marked unhealthy" in a for a in run.attempts)


def test_healthy_helper_needs_no_new_window(tmp_path, monkeypatch):
    config, workspace, bridge, manager = _setup(tmp_path, monkeypatch)
    opened = []
    with FakeHelper(bridge, workspace, tmp_path / "copilot") as helper:
        run = manager.start(
            "daily-progress-reporting", {}, ensure_helper=lambda: opened.append(1) or True
        )
    assert opened == []
    assert run.status == "running"
    assert [j["kind"] for j in helper.jobs] == ["probe", "start_chat"]


def test_start_chat_unanswered_but_session_appeared_does_not_retry(tmp_path, monkeypatch):
    config, workspace, bridge, manager = _setup(tmp_path, monkeypatch)
    opened = []

    class Slow(FakeHelper):
        """Answers probes, creates the chat for start_chat but never reports a result."""

        def _run(self):
            after = -1
            while not self._stop.is_set():
                res = self.bridge.poll(after, self.name, [str(self.workspace)], wait=0.1)
                if after < 0:
                    after = res["last"]
                    continue
                for job in res["jobs"]:
                    after = job["id"]
                    self.jobs.append(job)
                    if job["kind"] == "start_chat":
                        from console_fakes import make_session

                        make_session(self.home, self.workspace, prompt=job["prompt"])
                    else:
                        self.bridge.record_result(job["id"], {"errors": [], "info": {}})

    with Slow(bridge, workspace, tmp_path / "copilot") as helper:
        run = manager.start(
            "daily-progress-reporting", {}, ensure_helper=lambda: opened.append(1) or True
        )
    assert run.status == "running"
    assert opened == []
    assert [j["kind"] for j in helper.jobs].count("start_chat") == 1


def test_unhealthy_instance_is_excluded_until_it_answers(tmp_path):
    bridge = Bridge("t" * 64)
    bridge.poll(0, "old", ["/w"], wait=0)
    assert bridge.helper_connected("/w")
    bridge.mark_unhealthy("old")
    assert not bridge.helper_connected("/w")
    job = bridge.post_job({"kind": "probe", "workspace": "/w", "target": "old"})
    bridge.record_result(job, {"errors": [], "info": {}})
    assert bridge.helper_connected("/w")


def test_targeted_job_is_only_delivered_to_its_instance():
    bridge = Bridge("t" * 64)
    bridge.poll(-1, "a", ["/w"], wait=0)
    bridge.poll(-1, "b", ["/w"], wait=0)
    bridge.post_job({"kind": "probe", "workspace": "/w", "target": "b"})
    assert bridge.poll(0, "a", ["/w"], wait=0)["jobs"] == []
    assert len(bridge.poll(0, "b", ["/w"], wait=0)["jobs"]) == 1


def test_run_fails_clearly_when_recovery_is_impossible(tmp_path, monkeypatch):
    config, workspace, bridge, manager = _setup(tmp_path, monkeypatch)
    config.allow_cli_fallback = False
    with FakeHelper(bridge, workspace, tmp_path / "copilot", answer=False):
        run = manager.start("daily-progress-reporting", {}, ensure_helper=lambda: False)
    assert run.status == "not_started"
    assert "marked unhealthy" in run.message


class _Legacy016:
    """Real 0.1.6 behaviour: random hex id, ignores 'target', skips jobs by workspace only."""

    def __init__(self, bridge, workspace, after):
        import secrets
        import threading

        self.bridge, self.workspace, self.after = bridge, str(workspace), after
        self.name = secrets.token_hex(8)
        self.jobs = []
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        after = self.after  # None: first poll (after=-1) adopts 'last'
        if after is None:
            after = self.bridge.poll(-1, self.name, [self.workspace], wait=0.1)["last"]
        while not self.stop.is_set():
            res = self.bridge.poll(after, self.name, [self.workspace], wait=0.1)
            for job in res["jobs"]:
                after = job["id"]
                if job["workspace"] != self.workspace:
                    continue
                self.jobs.append(job)
                self.bridge.record_result(job["id"], {"errors": [], "info": {"version": "0.1.6"}})

    def __enter__(self):
        self.bridge.poll(-1, self.name, [self.workspace], wait=0.0)
        self.thread.start()
        return self

    def __exit__(self, *_a):
        self.stop.set()
        self.thread.join(timeout=3)


def test_legacy_helper_with_cursor_from_previous_console_still_answers_probe(
    tmp_path, monkeypatch
):
    config, workspace, bridge, manager = _setup(tmp_path, monkeypatch)
    monkeypatch.setattr(manager, "_clock", manager._clock)
    # the helper kept cursor 50 from the console process that ran before the restart
    with _Legacy016(bridge, workspace, after=50) as helper:
        info = manager.probe()
    assert info["version"] == "0.1.6"
    assert [j["kind"] for j in helper.jobs] == ["probe"]


def test_legacy_helper_ignoring_target_answers_targeted_start(tmp_path, monkeypatch):
    config, workspace, bridge, manager = _setup(tmp_path, monkeypatch)
    with _Legacy016(bridge, workspace, after=None) as helper:
        run = manager.start("daily-progress-reporting", {}, ensure_helper=lambda: True)
    assert [j["kind"] for j in helper.jobs][:1] == ["probe"]
    assert run.attempts


def test_failed_probe_marks_unhealthy_so_connect_recovery_opens_window(tmp_path, monkeypatch):
    import pytest

    config, workspace, bridge, manager = _setup(tmp_path, monkeypatch)
    monkeypatch.setattr(runs, "PROBE_SECONDS", 0.3)
    wedged = FakeHelper(bridge, workspace, tmp_path / "copilot", name="wedged", answer=False)
    with wedged:
        monkeypatch.setattr(type(manager), "probe", type(manager).probe)
        # shorten the probe wait: patch wait_result timeout via bridge wrapper
        real = bridge.wait_result
        monkeypatch.setattr(bridge, "wait_result", lambda j, t: real(j, min(t, 0.3)))
        with pytest.raises(runs.RunError):
            manager.probe()
        assert not bridge.helper_connected(str(workspace))  # recovery now sees it as down
        assert bridge.healthy_instance(str(workspace)) is None
