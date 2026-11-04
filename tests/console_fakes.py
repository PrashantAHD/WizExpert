"""Synthetic fakes for the console tests: a fake session-state folder and a fake helper poll."""

from __future__ import annotations

import json
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SESSION_ID = "aaaaaaaa-1111-4222-8333-bbbbbbbbbbbb"
OTHER_ID = "cccccccc-1111-4222-8333-dddddddddddd"


def iso(ts: float | None = None) -> str:
    return (
        datetime.fromtimestamp(ts or time.time(), UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    )


def event(
    kind: str,
    data: dict[str, Any] | None = None,
    *,
    agent: str | None = None,
    ts: float | None = None,
) -> str:
    body: dict[str, Any] = {
        "type": kind,
        "data": data or {},
        "id": "e",
        "parentId": None,
        "timestamp": iso(ts),
    }
    if agent:
        body["agentId"] = agent
    return json.dumps(body, separators=(",", ":")) + "\n"


def tool_start(name: str, args: dict[str, Any], call: str, **kw: Any) -> str:
    return event(
        "tool.execution_start", {"toolName": name, "toolCallId": call, "arguments": args}, **kw
    )


def tool_done(call: str, ok: bool = True) -> str:
    return event("tool.execution_complete", {"toolCallId": call, "success": ok})


def make_session(
    home: Path,
    workspace: Path,
    session_id: str = SESSION_ID,
    *,
    prompt: str | None = None,
    created: float | None = None,
    client: str = "vscode-agent-host",
) -> Path:
    folder = home / "session-state" / session_id
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "workspace.yaml").write_text(
        f"id: {session_id}\ncwd: {workspace}\nclient_name: {client}\nname: x\n"
        f"created_at: {iso(created)}\n",
        encoding="utf-8",
    )
    lines = [event("session.start", {"sessionId": session_id})]
    if prompt is not None:
        lines.append(
            event("user.message", {"content": prompt, "transformedContent": "ctx " + prompt})
        )
    (folder / "events.jsonl").write_text("".join(lines), encoding="utf-8")
    return folder / "events.jsonl"


def append(path: Path, *lines: str) -> None:
    with path.open("a", encoding="utf-8") as stream:
        stream.writelines(lines)


class FakeHelper:
    """Stands in for the VS Code helper: polls the bridge and 'creates' the chat for a start job."""

    def __init__(
        self,
        bridge: Any,
        workspace: Path,
        home: Path,
        *,
        create: bool = True,
        name: str = "fakehelper",
        answer: bool = True,
    ) -> None:
        self.bridge, self.workspace, self.home, self.create = bridge, workspace, home, create
        self.name, self.answer = name, answer
        self.infos: dict[str, dict[str, Any]] = {}
        self.jobs: list[dict[str, Any]] = []
        self._stop = threading.Event()
        self.events_path: Path | None = None
        self.thread = threading.Thread(target=self._run, daemon=True)

    def __enter__(self) -> FakeHelper:
        self.thread.start()
        deadline = time.time() + 3
        while not self.bridge.helper_connected(str(self.workspace)) and time.time() < deadline:
            time.sleep(0.02)
        return self

    def __exit__(self, *_a: Any) -> None:
        self._stop.set()
        self.thread.join(timeout=3)

    def _run(self) -> None:
        after = -1
        while not self._stop.is_set():
            res = self.bridge.poll(after, self.name, [str(self.workspace)], wait=0.1)
            if after < 0:
                after = res["last"]
                continue
            for job in res["jobs"]:
                after = job["id"]
                self.jobs.append(job)
                if not self.answer:
                    continue  # a wedged window: still polling, never answers
                info: dict[str, Any] = {"note": "sent", **self.infos.get(job["kind"], {})}
                if job["kind"] == "start_chat" and self.create:
                    self.events_path = make_session(self.home, self.workspace, prompt=job["prompt"])
                self.bridge.record_result(job["id"], {"errors": [], "info": info})
