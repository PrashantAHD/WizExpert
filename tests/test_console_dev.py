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
