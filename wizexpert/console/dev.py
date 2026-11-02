"""Development launcher that restarts the workflow console when its code changes."""

from __future__ import annotations

import argparse
import subprocess  # nosec B404
import sys
import time
from collections.abc import Iterable
from pathlib import Path

WATCH_SUFFIXES = frozenset({".py", ".js", ".html", ".css", ".json", ".svg"})
POLL_SECONDS = 0.5


def watched_files(root: Path) -> Iterable[Path]:
    for path in root.rglob("*"):
        if (
            path.is_file()
            and path.suffix.lower() in WATCH_SUFFIXES
            and "__pycache__" not in path.parts
        ):
            yield path


def snapshot(root: Path) -> dict[str, tuple[int, int]]:
    result: dict[str, tuple[int, int]] = {}
    for path in watched_files(root):
        try:
            stat = path.stat()
        except OSError:
            continue
        result[str(path)] = (stat.st_mtime_ns, stat.st_size)
    return result


def _stop(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def run(console_args: list[str], watch_root: Path, poll_seconds: float = POLL_SECONDS) -> int:
    """Run the console and restart it after a watched file changes."""
    baseline = snapshot(watch_root)
    first = True
    process: subprocess.Popen[bytes] | None = None
    try:
        while True:
            command = [sys.executable, "-m", "wizexpert", "console", *console_args]
            if not first and "--no-browser" not in command:
                command.append("--no-browser")
            process = subprocess.Popen(command)  # nosec B603
            first = False
            while process.poll() is None:
                time.sleep(poll_seconds)
                current = snapshot(watch_root)
                if current != baseline:
                    _stop(process)
                    baseline = current
                    break
            else:
                # A crash or an ordinary exit should not create a restart loop.
                return int(process.returncode or 0)
    except KeyboardInterrupt:
        if process is not None:
            _stop(process)
        return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m wizexpert.console.dev",
        description="Run the workflow console and restart it when console files change.",
    )
    parser.add_argument(
        "--watch-root",
        type=Path,
        default=Path(__file__).resolve().parent,
        help="Directory to watch (default: the console package).",
    )
    args, console_args = parser.parse_known_args(argv)
    if not console_args or console_args[0] != "--workspace":
        parser.error("pass the console arguments, including --workspace")
    if not Path(console_args[1]).is_dir():
        parser.error("--workspace must be an existing folder")
    return run(console_args, args.watch_root.resolve())


if __name__ == "__main__":
    raise SystemExit(main())
