from __future__ import annotations

from pathlib import Path

from wizexpert.console.dev import check_sources, run, snapshot, watched_files


def test_watched_files_include_console_assets_but_skip_cache(tmp_path: Path):
    (tmp_path / "server.py").write_text("x", encoding="utf-8")
    (tmp_path / "static").mkdir()
    (tmp_path / "static" / "app.js").write_text("x", encoding="utf-8")
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "server.pyc").write_bytes(b"x")
    (tmp_path / "notes.txt").write_text("x", encoding="utf-8")

    files = {path.relative_to(tmp_path).as_posix() for path in watched_files(tmp_path)}

    assert files == {"server.py", "static/app.js"}


def test_snapshot_changes_when_a_watched_file_changes(tmp_path: Path):
    target = tmp_path / "server.py"
    target.write_text("before", encoding="utf-8")
    before = snapshot(tmp_path)
    target.write_text("after", encoding="utf-8")

    assert snapshot(tmp_path) != before


class FakeProcess:
    def __init__(self, command: list[str]) -> None:
        self.command = command
        self.returncode: int | None = None
        self.stopped = False

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self) -> None:
        self.stopped = True
        self.returncode = -15

    def wait(self, timeout: float | None = None) -> int | None:
        return self.returncode

    def kill(self) -> None:
        self.stopped = True
        self.returncode = -9


class World:
    """Scripted fake clock, file state, compile check and processes (no sleeping)."""

    def __init__(self, tmp_path: Path) -> None:
        self.root = tmp_path
        self.now = 0.0
        self.version = 0
        self.broken = False
        self.processes: list[FakeProcess] = []
        self.steps: list = []

    def popen(self, command: list[str]) -> FakeProcess:
        alive = [p for p in self.processes if p.returncode is None]
        assert not alive, "a second child was started while one was still running"
        process = FakeProcess(command)
        self.processes.append(process)
        return process

    def sleep(self, seconds: float) -> None:
        self.now += seconds
        if not self.steps:
            raise KeyboardInterrupt
        self.steps.pop(0)()

    def run(self, steps: list) -> int:
        self.steps = list(steps)
        return run(
            ["--workspace", str(self.root)],
            self.root,
            poll_seconds=0.5,
            debounce_seconds=1.0,
            popen=self.popen,
            sleep=self.sleep,
            clock=lambda: self.now,
            snapshot_fn=lambda _root: {"f": (self.version, 0)},
            check_fn=lambda _root: "x.py line 3: invalid syntax" if self.broken else None,
        )

    def edit(self) -> None:
        self.version += 1


def idle(ticks: int) -> list:
    return [lambda: None] * ticks


def test_crashed_child_does_not_end_watcher_and_restarts_on_next_change(tmp_path: Path):
    world = World(tmp_path)

    def crash() -> None:
        world.processes[-1].returncode = 1

    code = world.run([crash, *idle(3), world.edit, *idle(4)])

    assert code == 0
    assert len(world.processes) == 2
    assert "--no-browser" not in world.processes[0].command
    assert "--no-browser" in world.processes[1].command
    assert world.processes[1].returncode == -15  # cleaned up when the watcher exited


def test_clean_child_exit_ends_watcher_with_its_code(tmp_path: Path):
    world = World(tmp_path)

    def finish() -> None:
        world.processes[-1].returncode = 0

    assert world.run([finish, *idle(5)]) == 0
    assert len(world.processes) == 1


def test_broken_syntax_change_keeps_running_child(tmp_path: Path):
    world = World(tmp_path)

    def break_it() -> None:
        world.broken = True
        world.edit()

    world.run([break_it, *idle(6)])

    assert len(world.processes) == 1
    # Only the watcher's final cleanup stopped it.
    assert world.processes[0].returncode == -15


def test_valid_change_after_crash_and_broken_edit_restarts_once(tmp_path: Path):
    world = World(tmp_path)

    def crash_and_break() -> None:
        world.processes[-1].returncode = 1
        world.broken = True
        world.edit()

    def fix() -> None:
        world.broken = False
        world.edit()

    world.run([crash_and_break, *idle(4), fix, *idle(6)])

    assert len(world.processes) == 2
    assert world.processes[1].returncode == -15


def test_debounce_coalesces_a_burst_of_saves_into_one_restart(tmp_path: Path):
    world = World(tmp_path)

    world.run([world.edit, world.edit, world.edit, world.edit, *idle(6)])

    assert len(world.processes) == 2
    assert world.processes[0].stopped
    assert world.processes[0].returncode == -15


def test_no_restart_before_quiet_period_elapses(tmp_path: Path):
    world = World(tmp_path)

    world.run([world.edit, *idle(1)])

    assert len(world.processes) == 1


def test_check_sources_reports_syntax_errors_without_executing(tmp_path: Path):
    marker = tmp_path / "ran.txt"
    (tmp_path / "ok.py").write_text(f"open({str(marker)!r}, 'w').write('x')\n", encoding="utf-8")
    assert check_sources(tmp_path) is None
    assert not marker.exists()

    (tmp_path / "bad.py").write_text("x = (\n", encoding="utf-8")
    problem = check_sources(tmp_path)

    assert problem is not None and problem.startswith("bad.py line")


def test_repo_launch_task_does_not_start_a_console():
    import json

    tasks = json.loads(
        (Path(__file__).resolve().parents[1] / ".vscode" / "tasks.json").read_text(encoding="utf-8")
    )["tasks"]
    launch = next(t for t in tasks if "console (auto-reload)" in t["label"])
    text = json.dumps(launch)

    assert "wizexpert.console" not in text
    assert "--workspace ${workspaceFolder}" not in text
    assert "outer workspace root" in text
