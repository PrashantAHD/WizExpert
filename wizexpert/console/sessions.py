"""Read-only access to VS Code agent-host sessions (never writes to session-state).

Sessions live in ``<copilot home>/session-state/<id>/`` (``events.jsonl``, ``workspace.yaml``);
the agent-host database maps a session to the id VS Code uses to open its chat. This module
finds the session created for a start request, tails its event log incrementally and reduces
it to what the page shows. Only event types the page needs are parsed, and tool output is
never read or exposed.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
import time
import urllib.parse
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import MAX_DOWNLOAD_BYTES, ConsoleConfig

UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
TYPE_PREFIX = re.compile(rb'^\{\s*"type"\s*:\s*"([A-Za-z0-9_.]+)"')
INTERESTING = {
    "user.message",
    "assistant.message",
    "assistant.turn_start",
    "assistant.turn_end",
    "tool.execution_start",
    "tool.execution_complete",
    "permission.requested",
    "permission.completed",
    "abort",
    "session.error",
    "hook.end",
    "session.shutdown",
}
WRITE_TOOLS = {
    "edit",
    "create",
    "apply_patch",
    "write",
    "insert",
    "str_replace_editor",
    "str_replace_based_edit_tool",
    "write_file",
    "create_file",
    "edit_file",
}
PATH_KEYS = ("path", "file_path", "filePath", "filename", "file")
PATCH_FILE = re.compile(r"^\*\*\* (?:Add|Update|Delete|Move to) File: (.+)$", re.MULTILINE)
MAX_LINE = 4 * 1024 * 1024
MAX_PROGRESS = 400
MAX_TEXT = 1500
PERMISSION_FLICKER_SECONDS = 2.5  # auto-approved prompts resolve at once; do not flash them
IDLE_COMPLETE_SECONDS = 45.0
SCAN_LIMIT = 500


def short(text: Any, limit: int = 200) -> str:
    value = " ".join(str(text or "").split())
    return value if len(value) <= limit else value[: limit - 1] + "\u2026"


def norm(path: str | Path) -> str:
    return os.path.normcase(os.path.realpath(str(path))).rstrip("\\/")


def read_workspace_yaml(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            key, sep, value = line.partition(":")
            if sep and key in {"cwd", "created_at", "client_name", "id"}:
                out[key] = value.strip().strip("'\"")
    except OSError:
        pass
    return out


def parse_time(value: Any) -> float:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


class SessionFinder:
    """Identify the session a start request created (never a pre-existing one)."""

    def __init__(self, config: ConsoleConfig) -> None:
        self.config = config

    def find(self, prompt: str, started_at: float, exclude: set[str]) -> str | None:
        root = self.config.session_state
        want = norm(self.config.resolved_workspace())
        try:
            dirs = [d for d in root.iterdir() if d.is_dir() and UUID.fullmatch(d.name)]
        except OSError:
            return None
        dirs.sort(key=lambda d: _mtime(d / "events.jsonl"), reverse=True)
        for folder in dirs[:60]:
            if folder.name in exclude:
                continue
            info = read_workspace_yaml(folder / "workspace.yaml")
            if not info or norm(info.get("cwd", "")) != want:
                continue
            if info.get("client_name") not in (None, "", "vscode-agent-host"):
                continue
            if parse_time(info.get("created_at")) < started_at - 5:
                continue
            if self._first_user_message(folder / "events.jsonl") == prompt:
                return folder.name
        return None

    @staticmethod
    def _first_user_message(path: Path) -> str | None:
        try:
            with path.open("rb") as stream:
                for index, raw in enumerate(stream):
                    if index > 300:
                        break
                    match = TYPE_PREFIX.match(raw)
                    if match and match.group(1) == b"user.message" and len(raw) < MAX_LINE:
                        data = json.loads(raw).get("data") or {}
                        return str(data.get("content") or "").strip()
        except (OSError, ValueError):
            pass
        return None

    def ahp_id(self, sdk_session_id: str) -> str | None:
        """The id VS Code uses to open this session's chat (via the agent-host database)."""
        if not UUID.fullmatch(sdk_session_id):
            return None
        try:
            con = sqlite3.connect(f"file:{self.config.agent_host_db}?mode=ro", uri=True, timeout=2)
        except sqlite3.Error:
            return None
        try:
            rows = con.execute(
                "select owner_session_uri from chats_v2 where provider_data like ?",
                (f'%"sdkSessionId":"{sdk_session_id}"%',),
            ).fetchall()
        except sqlite3.Error:
            return None
        finally:
            con.close()
        for (uri,) in rows:
            candidate = str(uri).split(":/", 1)[-1]
            if UUID.fullmatch(candidate):
                return candidate
        return None


def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


@dataclass
class Pending:
    kind: str  # "permission" | "question"
    key: str
    text: str
    since: float


@dataclass
class SessionView:
    """Incremental reducer over one session's events.jsonl."""

    path: Path
    offset: int = 0
    rest: bytes = b""
    head: bytes = b""
    seq: int = 0
    progress: deque = field(default_factory=lambda: deque(maxlen=MAX_PROGRESS))
    permissions: dict[str, Pending] = field(default_factory=dict)
    questions: dict[str, Pending] = field(default_factory=dict)
    open_tools: dict[str, str] = field(default_factory=dict)
    written: dict[str, str] = field(default_factory=dict)
    final: str = ""
    last_has_tools: bool = False
    finished: bool = False
    aborted: bool = False
    saw_user: bool = False
    last_event: float = 0.0
    last_type: str = ""
    _sub: bool = False
    lock: threading.Lock = field(default_factory=threading.Lock)

    # -- reading ---
    def poll(self) -> None:
        with self.lock:
            try:
                size = self.path.stat().st_size
                with self.path.open("rb") as stream:
                    head = stream.read(64)
                    if (self.head and head[: len(self.head)] != self.head) or size < self.offset:
                        self._reset()
                    self.head = head
                    if size <= self.offset:
                        return
                    stream.seek(self.offset)
                    chunk = stream.read(size - self.offset)
            except OSError:
                return
            self.offset += len(chunk)
            lines = (self.rest + chunk).split(b"\n")
            self.rest = lines.pop()
            if len(self.rest) > MAX_LINE:
                self.rest = b""  # a giant partial line (tool output) is skipped, not buffered
            for raw in lines:
                self._line(raw)

    def _reset(self) -> None:
        self.offset, self.rest = 0, b""
        self.progress.clear()
        self.permissions.clear()
        self.questions.clear()
        self.open_tools.clear()
        self.written.clear()
        self.final, self.finished, self.saw_user = "", False, False

    def _line(self, raw: bytes) -> None:
        match = TYPE_PREFIX.match(raw)
        if not match or match.group(1).decode() not in INTERESTING or len(raw) > MAX_LINE:
            return
        try:
            event = json.loads(raw)
        except ValueError:
            return
        etype, data = event["type"], event.get("data") or {}
        stamp = parse_time(event.get("timestamp"))
        self.last_event, self.last_type = stamp or time.time(), etype
        # Events carrying an agentId belong to a subagent: they never set the chat's final text
        # or its prompt, but their tool calls and approval prompts still show.
        self._sub = bool(event.get("agentId"))
        handler = getattr(self, "_on_" + etype.replace(".", "_"), None)
        if handler:
            handler(data, stamp)

    def _add(self, kind: str, text: str, stamp: float, **extra: Any) -> dict[str, Any]:
        self.seq += 1
        item = {
            "seq": self.seq,
            "kind": kind,
            "text": short(text, MAX_TEXT),
            "time": stamp,
            **extra,
        }
        self.progress.append(item)
        return item

    # -- event handlers ---
    def _on_user_message(self, data: dict, stamp: float) -> None:
        if self._sub:
            return
        self.saw_user, self.finished, self.aborted, self.final = True, False, False, ""
        self._add("user", data.get("content") or "", stamp)

    def _on_assistant_message(self, data: dict, stamp: float) -> None:
        if self._sub:
            return
        text = str(data.get("content") or "").strip()
        self.last_has_tools = bool(data.get("toolRequests"))
        if self.last_has_tools:
            self.final = ""
        if text:
            self._add("assistant", text, stamp)
            if not self.last_has_tools:
                self.final = text[:20000]

    def _on_assistant_turn_start(self, data: dict, stamp: float) -> None:
        if not self._sub:
            self.finished = False

    def _on_session_error(self, data: dict, stamp: float) -> None:
        if not self._sub:
            self._add("error", str(data.get("message") or "The session reported an error."), stamp)

    def _on_tool_execution_start(self, data: dict, stamp: float) -> None:
        name, call_id = str(data.get("toolName") or "tool"), str(data.get("toolCallId") or "")
        args = data.get("arguments")
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except ValueError:
                args = {"text": args}
        args = args if isinstance(args, dict) else {}
        self.open_tools[call_id] = name
        if name == "ask_user":
            question = short(
                args.get("question") or args.get("message") or "The agent has a question.", 600
            )
            self.questions[call_id] = Pending("question", call_id, question, time.time())
        self._add(
            "tool",
            f"{name}: {tool_summary(name, args)}",
            stamp,
            tool=name,
            call_id=call_id,
            sub=self._sub,
        )
        if name in WRITE_TOOLS:
            for path in written_paths(args):
                self.written[path] = name

    def _on_tool_execution_complete(self, data: dict, stamp: float) -> None:
        call_id = str(data.get("toolCallId") or "")
        self.open_tools.pop(call_id, None)
        self.questions.pop(call_id, None)
        if data.get("success") is False:
            for item in reversed(self.progress):
                if item.get("call_id") == call_id:
                    item["failed"] = True
                    break

    def _on_permission_requested(self, data: dict, stamp: float) -> None:
        request = data.get("permissionRequest") or {}
        key = str(data.get("requestId") or "")
        self.permissions[key] = Pending(
            "permission", key, permission_summary(request), stamp or time.time()
        )

    def _on_permission_completed(self, data: dict, stamp: float) -> None:
        self.permissions.pop(str(data.get("requestId") or ""), None)

    def _on_abort(self, data: dict, stamp: float) -> None:
        self.permissions.clear()
        self.questions.clear()
        self.open_tools.clear()
        self.finished = self.aborted = True

    def _on_hook_end(self, data: dict, stamp: float) -> None:
        if not self._sub and data.get("hookType") in ("agentStop", "sessionEnd"):
            self.finished = True

    def _on_session_shutdown(self, data: dict, stamp: float) -> None:
        self.finished = True

    # -- derived state ---
    def pending(self, now: float | None = None) -> Pending | None:
        now = now or time.time()
        for question in self.questions.values():
            return question
        for permission in self.permissions.values():
            if now - permission.since >= PERMISSION_FLICKER_SECONDS:
                return permission
        return None

    def status(self, now: float | None = None) -> str:
        now = now or time.time()
        if self.pending(now):
            return "input_needed"
        if self.finished:
            return "stopped" if self.aborted else "completed"
        idle = now - max(self.last_event, _mtime(self.path))
        if (
            self.saw_user
            and self.final
            and not self.last_has_tools
            and not self.open_tools
            and idle >= IDLE_COMPLETE_SECONDS
        ):
            return "completed"
        return "running"


def tool_summary(name: str, args: dict[str, Any]) -> str:
    """A short, safe description of a tool call (never the command text or file contents)."""
    for key in (
        "description",
        "tool_name",
        "path",
        "file_path",
        "pattern",
        "query",
        "url",
        "skill",
        "title",
    ):
        if args.get(key):
            return short(args[key], 160)
    if name == "apply_patch":
        return short(
            ", ".join(PATCH_FILE.findall(str(args.get("text") or args.get("input") or ""))), 160
        )
    return ""


def permission_summary(request: dict[str, Any]) -> str:
    kind = str(request.get("kind") or "permission")
    detail = ""
    for key in (
        "toolName",
        "tool",
        "serverName",
        "intention",
        "fileName",
        "path",
        "url",
        "fullCommandText",
    ):
        if request.get(key):
            detail = short(request[key], 200)
            break
    return f"{kind}: {detail}" if detail else kind


def written_paths(args: dict[str, Any]) -> list[str]:
    paths = [str(args[k]) for k in PATH_KEYS if isinstance(args.get(k), str)]
    for key in ("text", "input", "patch"):
        if isinstance(args.get(key), str):
            paths += PATCH_FILE.findall(args[key])
    return paths[:20]


# -- output files ---


def is_denied(path: Path, config: ConsoleConfig) -> bool:
    if path.name in config.deny_names or path.suffix.lower() in {
        ".pem",
        ".key",
        ".pfx",
        ".p12",
        ".db",
        ".sqlite",
    }:
        return True
    return path.name.lower().startswith(".env") or any(p in config.exclude_dirs for p in path.parts)


def confine(path: str | Path, root: Path) -> Path | None:
    """Resolve ``path`` and return it only if it stays inside ``root``."""
    try:
        resolved = Path(path).resolve()
    except (OSError, ValueError):
        return None
    root = root.resolve()
    return resolved if resolved == root or root in resolved.parents else None


def vscode_file_url(path: Path) -> str:
    return "vscode://file/" + urllib.parse.quote(str(path).replace("\\", "/"), safe="/:")


def collect_files(
    config: ConsoleConfig, written: dict[str, str], since: float, *, scan: bool = True
) -> list[dict[str, Any]]:
    """Files the session wrote (tool calls) plus files changed under the output roots."""
    workspace = config.resolved_workspace()
    found: dict[str, dict[str, Any]] = {}

    def add(path: Path, how: str) -> None:
        resolved = confine(path, workspace)
        if (
            resolved is None
            or not resolved.is_file()
            or is_denied(resolved.relative_to(workspace), config)
        ):
            return
        try:
            stat = resolved.stat()
        except OSError:
            return
        key = norm(resolved)
        if key not in found:
            found[key] = {
                "path": resolved.relative_to(workspace).as_posix(),
                "how": how,
                "size": stat.st_size,
                "modified": stat.st_mtime,
                "download": stat.st_size <= MAX_DOWNLOAD_BYTES,
                "vscode": vscode_file_url(resolved),
            }

    for raw, tool in written.items():
        candidate = Path(raw)
        add(candidate if candidate.is_absolute() else workspace / candidate, f"{tool} tool")
    if scan:
        for rel in config.output_roots:
            base = confine(workspace / rel, workspace)
            if base is None or not base.is_dir():
                continue
            count = 0
            for folder, dirs, files in os.walk(base):
                dirs[:] = [d for d in dirs if d not in config.exclude_dirs]
                for name in files:
                    path = Path(folder) / name
                    if _mtime(path) >= since - 2:
                        add(path, "changed during the run")
                        count += 1
                        if count >= SCAN_LIMIT:
                            break
                if count >= SCAN_LIMIT:
                    break
    return sorted(found.values(), key=lambda f: f["modified"], reverse=True)[:SCAN_LIMIT]
