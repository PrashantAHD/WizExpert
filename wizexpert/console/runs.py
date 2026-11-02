"""Runs: a start request becomes a new VS Code agent-mode chat; the page only watches it.

The console owns no workflow rules. ``start`` types one validated prompt into a new chat of the
configured agent (through the helper extension) and then follows the real session's event log.
"""

from __future__ import annotations

import json
import secrets
import shutil
import subprocess  # nosec B404
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import categories
from .bridge import Bridge
from .categories import InputError
from .config import ConsoleConfig
from .sessions import (
    SessionFinder,
    SessionView,
    collect_files,
    short,
)

ATTEMPT_SECONDS = 30.0
FILES_REFRESH = 6.0
MAX_RUNS = 50


class RunError(Exception):
    """A request the manager refuses (message is safe to show)."""


@dataclass
class Run:
    id: str
    category_id: str
    values: dict[str, str]
    prompt: str
    created: float
    status: str = "starting"
    message: str = ""
    session_id: str = ""
    ahp_id: str = ""
    attempts: list[str] = field(default_factory=list)
    view: SessionView | None = None
    files: list[dict[str, Any]] = field(default_factory=list)
    files_at: float = 0.0
    files_n: int = -1
    lock: threading.RLock = field(default_factory=threading.RLock)


class RunManager:
    def __init__(
        self,
        config: ConsoleConfig,
        bridge: Bridge,
        *,
        finder: SessionFinder | None = None,
        run_async: bool = True,
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], None] = time.sleep,
        cli: Callable[[list[str]], int] | None = None,
    ) -> None:
        self.config = config
        self.bridge = bridge
        self.finder = finder or SessionFinder(config)
        self._async = run_async
        self._clock = clock
        self._sleep = sleep
        self._cli = cli or _run_cli
        self._runs: dict[str, Run] = {}
        self._lock = threading.Lock()
        self._load()

    # -- persistence (prompt and ids only) ---
    @property
    def _index(self) -> Path:
        return self.config.state_dir / "runs.json"

    def _load(self) -> None:
        try:
            for item in json.loads(self._index.read_text(encoding="utf-8")):
                run = Run(
                    item["id"],
                    item["category_id"],
                    item.get("values", {}),
                    item["prompt"],
                    float(item["created"]),
                    item.get("status", "running"),
                    item.get("message", ""),
                    item.get("session_id", ""),
                    item.get("ahp_id", ""),
                )
                if run.status == "starting":
                    run.status, run.message = (
                        "not_started",
                        "The console stopped before this run started.",
                    )
                self._runs[run.id] = run
        except (OSError, ValueError, KeyError, TypeError):
            pass

    def _save(self) -> None:
        items = sorted(self._runs.values(), key=lambda r: r.created)[-MAX_RUNS:]
        data = [
            {
                "id": r.id,
                "category_id": r.category_id,
                "values": r.values,
                "prompt": r.prompt,
                "created": r.created,
                "status": r.status,
                "message": r.message,
                "session_id": r.session_id,
                "ahp_id": r.ahp_id,
            }
            for r in items
        ]
        try:
            self.config.state_dir.mkdir(parents=True, exist_ok=True)
            self._index.write_text(json.dumps(data), encoding="utf-8")
        except OSError:
            pass

    # -- start ---
    def categories(self) -> list[dict[str, Any]]:
        return [c.to_json() for c in categories.CATEGORIES.values()]

    def helper_state(self) -> dict[str, Any]:
        workspace = str(self.config.resolved_workspace())
        return {
            "connected": self.bridge.helper_connected(workspace),
            "any": self.bridge.helper_connected(None),
            "workspace": Path(workspace).name,
            "agent": self.config.agent,
        }

    def start(
        self,
        category_id: str,
        raw: dict[str, Any],
        action_id: str | None = None,
        ensure_helper: Callable[[], bool] | None = None,
    ) -> Run:
        try:
            values = categories.validate(category_id, raw, action_id)
            prompt = categories.build_prompt(category_id, values, self.config.prompts, action_id)
        except InputError as error:
            raise RunError(str(error)) from None
        with self._lock:
            if any(r.status == "starting" for r in self._runs.values()):
                raise RunError("Another run is still starting; wait for it to appear first.")
            helper_ready = self.bridge.helper_connected(str(self.config.resolved_workspace()))
            if not helper_ready and ensure_helper is not None:
                helper_ready = ensure_helper()
            if not helper_ready and not self.config.allow_cli_fallback:
                raise RunError(
                    "The VS Code helper is not connected for this workspace. Install it "
                    "(wizexpert console install-helper), reload the VS Code window with the "
                    "workspace open, and try again."
                )
            run_id = (
                time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(self._clock()))
                + "-"
                + secrets.token_hex(3)
            )
            run = Run(run_id, category_id, values, prompt, self._clock())
            self._runs[run_id] = run
            self._save()
        if self._async:
            threading.Thread(target=self._launch, args=(run,), daemon=True).start()
        else:
            self._launch(run)
        return run

    def _claimed(self) -> set[str]:
        return {r.session_id for r in self._runs.values() if r.session_id}

    def _launch(self, run: Run) -> None:
        workspace = str(self.config.resolved_workspace())
        job = {
            "kind": "start_chat",
            "workspace": workspace,
            "agent": self.config.agent,
            "prompt": run.prompt,
            "newChatWait": self.config.new_chat_wait_ms,
        }
        try:
            if self.bridge.helper_connected(workspace):
                # One helper attempt only: a second "start" could create a duplicate chat (and run).
                result = self.bridge.wait_result(self.bridge.post_job(job), 40.0)
                run.attempts.append("helper: " + _result_text(result))
                if self._await_session(run, ATTEMPT_SECONDS):
                    return
            if self.config.allow_cli_fallback:
                run.attempts.append("code chat fallback")
                command = shutil.which(self.config.code_command) or self.config.code_command
                code = self._cli(
                    [command, "chat", "--mode", self.config.agent, "--reuse-window", run.prompt]
                )
                if code == 0 and self._await_session(run, self.config.start_timeout):
                    return
            with run.lock:
                run.status = "not_started"
                run.message = (
                    "VS Code did not start the chat. Check that the workspace window has the "
                    "helper "
                    "active (reload the window after installing it). Attempts: "
                    + "; ".join(run.attempts)
                )
        finally:
            self._save()

    def _await_session(self, run: Run, seconds: float) -> bool:
        end = self._clock() + seconds
        while True:
            sid = self.finder.find(run.prompt, run.created, self._claimed())
            if sid:
                with run.lock:
                    run.session_id, run.status, run.message = sid, "running", ""
                    run.view = SessionView(self.config.session_state / sid / "events.jsonl")
                self._save()
                return True
            if self._clock() >= end:
                return False
            self._sleep(1.0)

    # -- watching ---
    def get(self, run_id: str) -> Run:
        with self._lock:
            run = self._runs.get(run_id)
        if run is None:
            raise RunError("Unknown run.")
        return run

    def history(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock:
            runs = sorted(self._runs.values(), key=lambda r: r.created, reverse=True)[:limit]
        return [
            {"id": r.id, "category_id": r.category_id, "status": r.status, "created": r.created}
            for r in runs
        ]

    def view(self, run_id: str, since: int = 0) -> dict[str, Any]:
        run = self.get(run_id)
        with run.lock:
            if run.session_id and run.view is None:
                run.view = SessionView(self.config.session_state / run.session_id / "events.jsonl")
            sv, status = run.view, run.status
        data: dict[str, Any] = {
            "id": run.id,
            "category": categories.CATEGORIES[run.category_id].title,
            "prompt": run.prompt,
            "created": run.created,
            "message": run.message,
            "helper": self.helper_state(),
            "progress": [],
            "next": since,
            "pending": None,
            "summary": "",
            "files": [],
            "can_open_chat": False,
        }
        if sv is not None:
            sv.poll()
            now = self._clock()
            state = sv.status(now)
            with run.lock:
                if run.status in ("running", "input_needed", "completed", "stopped"):
                    changed = run.status != state
                    run.status = state
                    if changed:
                        self._save()
                status = run.status
                if not run.ahp_id:
                    run.ahp_id = self.finder.ahp_id(run.session_id) or ""
                ahp = run.ahp_id
            pending = sv.pending(now)
            with sv.lock:
                items = [i for i in sv.progress if i["seq"] > since]
                data["next"] = sv.seq
                summary = sv.final if status in ("completed", "stopped") else ""
            data["progress"] = items
            data["summary"] = summary
            data["pending"] = (
                {
                    "kind": pending.kind,
                    "text": pending.text,
                    "key": pending.key,
                    "can_decide": pending.kind == "permission" and bool(ahp),
                }
                if pending
                else None
            )
            data["files"] = self._files(run, sv, status)
            data["can_open_chat"] = bool(ahp)
        data["status"] = status
        return data

    def _files(self, run: Run, sv: SessionView, status: str) -> list[dict[str, Any]]:
        now = self._clock()
        with run.lock:
            stale = now - run.files_at >= FILES_REFRESH or run.files_n != len(sv.written)
            if stale or status in ("completed", "stopped") and not run.files:
                run.files = collect_files(self.config, dict(sv.written), run.created)
                run.files_at, run.files_n = now, len(sv.written)
            files = list(run.files)
        return [{**{k: v for k, v in f.items()}, "index": i} for i, f in enumerate(files)]

    # -- VS Code actions ---
    def probe(self) -> dict[str, Any]:
        """Ask the helper which chat-related commands this VS Code exposes (names only)."""
        workspace = str(self.config.resolved_workspace())
        if not self.bridge.helper_connected(workspace):
            raise RunError("The VS Code helper is not connected for this workspace.")
        result = self.bridge.wait_result(
            self.bridge.post_job({"kind": "probe", "workspace": workspace}), 20.0
        )
        if result is None or result.get("errors"):
            raise RunError("The probe failed: " + _result_text(result))
        info = result.get("info") or {}
        names = [str(c) for c in info.get("commands", [])][:400]
        return {
            "version": str(info.get("version", "")),
            "folders": [str(f) for f in info.get("folders", [])][:5],
            "commands": names,
        }

    def open_chat(self, run_id: str) -> None:
        run = self.get(run_id)
        if not run.ahp_id:
            raise RunError("VS Code has not registered this chat yet.")
        job = self.bridge.post_job(
            {
                "kind": "open_chat",
                "workspace": str(self.config.resolved_workspace()),
                "ahp": run.ahp_id,
                "openWait": self.config.open_wait_ms,
            }
        )
        result = self.bridge.wait_result(job, 20.0)
        if result is None or result.get("errors"):
            raise RunError("VS Code did not open the chat: " + _result_text(result))

    def decide(self, run_id: str, action: str) -> None:
        if action not in ("accept", "skip"):
            raise RunError("Unknown action.")
        run = self.get(run_id)
        sv = run.view
        if sv is None or not run.ahp_id:
            raise RunError("The chat is not ready for this action.")
        sv.poll()
        pending = sv.pending(self._clock())
        if pending is None or pending.kind != "permission":
            raise RunError("Nothing is waiting for approval right now.")
        key = pending.key

        def guard() -> tuple[bool, str]:
            sv.poll()
            now = self._clock()
            current = sv.pending(now)
            if current is None or current.key != key:
                return False, "that prompt is no longer waiting"
            if len(sv.permissions) + len(sv.questions) > 1:
                return False, "several prompts are waiting, so it is unclear which to press"
            return True, ""

        resources = [
            f"ahp-session:/{run.ahp_id}",
            f"agent-host-copilotcli:/{run.ahp_id}",
            f"copilotcli:/{run.ahp_id}",
        ]
        job = self.bridge.post_job(
            {
                "kind": "tool",
                "action": action,
                "workspace": str(self.config.resolved_workspace()),
                "ahp": run.ahp_id,
                "resources": resources,
                "openWait": self.config.open_wait_ms,
            },
            guard=guard,
        )
        result = self.bridge.wait_result(job, 30.0)
        if result is None:
            raise RunError("VS Code did not respond.")
        if result.get("info", {}).get("guard"):
            raise RunError("Not pressed: " + short(result["info"]["guard"], 120))
        if result.get("errors"):
            raise RunError("VS Code could not press the button: " + _result_text(result))


def _result_text(result: dict[str, Any] | None) -> str:
    if result is None:
        return "no answer from the VS Code helper"
    errors = [short(e, 120) for e in result.get("errors", [])][:3]
    info = result.get("info") or {}
    if errors:
        return "; ".join(errors)
    return short(info.get("note") or "sent", 120)


def _run_cli(argv: list[str]) -> int:
    try:
        return subprocess.run(argv, check=False, timeout=30, capture_output=True).returncode  # nosec B603
    except (OSError, subprocess.SubprocessError):
        return 1
