"""Development launcher that restarts the workflow console when its code changes."""

from __future__ import annotations

import argparse
import subprocess  # nosec B404
import sys
import time
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

WATCH_SUFFIXES = frozenset({".py", ".js", ".html", ".css", ".json", ".svg"})
POLL_SECONDS = 0.5
DEBOUNCE_SECONDS = 1.0


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


def check_sources(root: Path) -> str | None:
    """Compile (never execute) the watched .py files; return the first problem, if any."""
    for path in sorted(watched_files(root)):
        if path.suffix.lower() != ".py":
            continue
        try:
            compile(path.read_bytes(), str(path), "exec", dont_inherit=True)
        except SyntaxError as exc:
            return f"{path.name} line {exc.lineno or '?'}: {exc.msg}"
        except (ValueError, OSError) as exc:
            return f"{path.name}: {exc}"
    return None


def _log(message: str) -> None:
    print(f"[console-dev] {message}", flush=True)


def run(
    console_args: list[str],
    watch_root: Path,
    poll_seconds: float = POLL_SECONDS,
    *,
    debounce_seconds: float = DEBOUNCE_SECONDS,
    popen: Callable[[list[str]], Any] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
    snapshot_fn: Callable[[Path], dict[str, tuple[int, int]]] = snapshot,
    check_fn: Callable[[Path], str | None] = check_sources,
) -> int:
    """Run the console and restart it after watched files change.

    A child crash never ends the watcher: it keeps watching and restarts on the
    next change. Changes are debounced, and a restart is skipped (keeping any
    running child) while the watched Python files do not compile.
    """
    start = popen or (lambda command: subprocess.Popen(command))  # nosec B603
    baseline = snapshot_fn(watch_root)
    handled = baseline
    changed_at: float | None = None
    first = True
    process: Any = None

    def launch() -> Any:
        nonlocal first
        command = [sys.executable, "-m", "wizexpert", "console", *console_args]
        if not first and "--no-browser" not in command:
            command.append("--no-browser")
        first = False
        return start(command)

    try:
        process = launch()
        while True:
            sleep(poll_seconds)
            if process is not None:
                code = process.poll()
                if code is not None:
                    if code == 0:
                        return 0  # an ordinary exit should not create a restart loop
                    _log(f"backend crashed (exit {code}); waiting for the next source change")
                    process = None
            current = snapshot_fn(watch_root)
            if current != baseline:
                baseline = current
                changed_at = clock()
            if changed_at is None or clock() - changed_at < debounce_seconds:
                continue
            changed_at = None
            if current == handled:
                continue
            handled = current
            problem = check_fn(watch_root)
            if problem:
                kept = " keeping the running backend;" if process is not None else ""
                _log(f"source does not compile ({problem});{kept} waiting for the next change")
                continue
            if process is not None:
                _stop(process)
            process = launch()
    except KeyboardInterrupt:
        return 0
    finally:
        if process is not None:
            _stop(process)


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
