from __future__ import annotations

from pathlib import Path

from wizexpert.console.dev import snapshot, watched_files


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


def test_outer_launch_task_stops_prior_canonical_console_first():
    import json

    tasks = json.loads(
        (Path(__file__).resolve().parents[2] / ".vscode" / "tasks.json").read_text(
            encoding="utf-8-sig"
        )
    )["tasks"]
    launch = next(t for t in tasks if "console (auto-reload)" in t["label"])

    assert launch["dependsOn"] == "WizExpert: Stop workflow console"
    assert launch["dependsOrder"] == "sequence"
    assert launch["runOptions"]["instanceLimit"] == 1
