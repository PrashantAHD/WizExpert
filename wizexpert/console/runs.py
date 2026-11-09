"""Runs: a start request becomes a new VS Code agent-mode chat; the page only watches it.

The console owns no workflow rules. ``start`` types one validated prompt into a new chat of the
configured agent (through the helper extension) and then follows the real session's event log.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import subprocess  # nosec B404
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import categories, imports
from .bridge import MIN_HELPER_VERSION, Bridge
from .categories import InputError
from .config import ConsoleConfig
from .sessions import (
    SessionFinder,
    SessionView,
    collect_files,
    short,
)

ATTEMPT_SECONDS = 30.0
PROBE_SECONDS = 10.0  # quick liveness probe before a start_chat job
START_SECONDS = 40.0  # wait for the helper's answer to start_chat
FILES_REFRESH = 6.0
MAX_RUNS = 50
ACTIVE = ("starting", "running", "input_needed", "handed_off", "awaiting_gate")
HANDOFF_WAIT_SECONDS = 1800.0
LATE_START_MESSAGE = "The console stopped before this run started."
INACTIVE = ("completed", "stopped", "interrupted", "not_started", "rejected")
MCP_HINT_SECONDS = 600.0
MCP_ACTIONS = ("start", "stop", "auth", "list")
ACTION_CASE_MODES = {
    "refresh-case": "refresh",
    "sync-refresh": "refresh",
    "update-deliverables": "deliverables",
    "follow-up-email": "any",
    "reply-response": "any",
}
MCP_SERVER = re.compile(r"[A-Za-z0-9 ._-]{1,60}")


class RunError(imports.StartRefused):
    """A request the manager refuses (message is safe to show)."""


class RunBusyError(RunError, imports.StartBlocked):
    """A start refused only for a transient reason (active-run guard, helper not connected);
    queued work that hits it is retried later."""


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
    chain: list[dict[str, Any]] = field(default_factory=list)  # earlier chats of this run
    handoff: dict[str, Any] | None = None  # handed off, new chat not resolved yet
    handoff_try: float = 0.0
    carried: dict[str, str] = field(default_factory=dict)  # files written by earlier chats
    gates: list[dict[str, Any]] = field(default_factory=list)  # console approval gates
    decisions: list[dict[str, Any]] = field(default_factory=list)  # recorded gate decisions
    parent: str = ""  # earlier run of the same gated flow
    child: str = ""  # run started by the last approved gate
    action_id: str = ""  # canonical action id ("" for runs saved before this field existed)
    final: dict[str, Any] | None = None  # frozen end-of-run checklist/outcome (None = not frozen)
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
        self.helper_note = ""  # why the helper could not connect (set by the server)
        self._lock = threading.RLock()
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
                run.chain = [c for c in item.get("chain", []) if isinstance(c, dict)][:50]
                handoff = item.get("handoff")
                run.handoff = handoff if isinstance(handoff, dict) else None
                run.action_id = str(item.get("action_id") or "")
                carried = item.get("carried")
                run.carried = (
                    {str(k): str(v) for k, v in carried.items()}
                    if isinstance(carried, dict)
                    else {}
                )
                run.gates = [g for g in item.get("gates", []) if isinstance(g, dict)][:5]
                run.decisions = [d for d in item.get("decisions", []) if isinstance(d, dict)][:20]
                run.parent = str(item.get("parent") or "")
                run.child = str(item.get("child") or "")
                final = item.get("final")
                if (
                    isinstance(final, dict)
                    and isinstance(final.get("checklist"), list)
                    and final.get("outcome") in FINAL_OUTCOMES
                    and run.status in INACTIVE
                ):
                    reason = final.get("reason")
                    run.final = {
                        "checklist": clean_checklist(final["checklist"]),
                        "outcome": final["outcome"],
                        "reason": reason[:FINAL_REASON_MAX] if isinstance(reason, str) else "",
                    }
                self._runs[run.id] = run
        except (OSError, ValueError, KeyError, TypeError):
            return
        # A restart is not evidence that a chat ended: runs that were active stay active and are
        # re-bound to their session log (the log is the source of pending approvals/questions).
        for run in list(self._runs.values()):
            if run.status == "starting" and not run.session_id:
                try:
                    sid = self.finder.find(run.prompt, run.created, self._claimed())
                except Exception:  # noqa: BLE001 - recovery is best effort
                    sid = None
                if sid:
                    run.session_id, run.status, run.message = sid, "running", ""
                else:
                    run.status, run.message = ("not_started", LATE_START_MESSAGE)
            if run.status in ACTIVE and run.session_id:
                run.view = self._make_view(run, seed=True)

    def _make_view(self, run: Run, *, seed: bool = False, base_seq: int = 0) -> SessionView:
        """A log reader for the run's current chat; after a restart it replays the chain."""
        view = SessionView(self.config.session_state / run.session_id / "events.jsonl")
        if seed:
            for link in run.chain:
                view._add(
                    "handoff",
                    "Handed off to a new chat"
                    + (f": {link['title']}" if link.get("title") else "")
                    + ".",
                    float(link.get("time") or 0.0),
                )
        else:
            view.seq = base_seq
        return view

    def _recover_orphan_handoff(self, run: Run) -> None:
        """A handed_off run with no pending handoff can never resolve: mark it interrupted."""
        with run.lock:
            if run.status != "handed_off" or run.handoff is not None:
                return
            run.status = "interrupted"
            run.message = "The handoff chat was not recorded; open VS Code to continue."
            self._save()

    def _follow(self, run: Run) -> None:
        """Re-bind the run to the new chat once the current chat handed off to it."""
        sv = run.view
        if run.status in INACTIVE:
            return
        if sv is None:
            self._recover_orphan_handoff(run)
            return
        sv.poll()
        found = sv.handoff
        with run.lock:
            if found is None and run.handoff is None and run.status == "handed_off":
                self._recover_orphan_handoff(run)
                return
            # Invariant: a handoff seen in the log always becomes a pending handoff, so the run
            # is either rebound to the new chat or times out; it can never wait silently.
            if found is not None and run.handoff is None:
                run.handoff = {**found, "from": run.session_id, "from_ahp": run.ahp_id}
                run.ahp_id = found["ahp"]  # Open chat / Stop already point at the new chat
                run.status = "handed_off"
                self._save()
            pending = run.handoff
            if pending is None:
                return
            now = self._clock()
            if now - run.handoff_try < 2.0:
                return
            run.handoff_try = now
        # A peer chat shares the ahp id with the old chat, so only its prompt identifies it.
        by_ahp = None if pending.get("chat") else self.finder.sdk_session(pending["ahp"])
        if by_ahp == pending.get("from"):
            by_ahp = None
        sid = by_ahp or self.finder.find_handoff(
            str(pending.get("prompt") or ""),
            float(pending.get("since") or 0.0),
            self._claimed() | {str(pending.get("from") or "")},
        )
        if (
            not sid
            or sid == pending.get("from")
            or not (self.config.session_state / sid / "events.jsonl").exists()
        ):
            if now - float(pending.get("since") or now) > HANDOFF_WAIT_SECONDS:
                with run.lock:
                    run.status, run.handoff = "interrupted", None
                    run.message = "The handoff chat never appeared; open VS Code to continue."
                    self._save()
            return
        with run.lock:
            run.carried.update(sv.written)
            run.chain.append(
                {
                    "session_id": pending.get("from", ""),
                    "ahp_id": pending.get("from_ahp", ""),
                    "next_ahp": pending["ahp"],
                    "title": pending.get("title", ""),
                    "time": pending.get("since", now),
                }
            )
            del run.chain[:-50]
            run.session_id, run.ahp_id, run.handoff = sid, pending["ahp"], None
            run.status, run.message = "running", ""
            run.view = self._make_view(run, base_seq=sv.seq)
            run.files_n = -1
            self._save()

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
                "chain": r.chain,
                "handoff": r.handoff,
                "carried": dict(list(r.carried.items())[:200]),
                "gates": r.gates,
                "decisions": r.decisions,
                "parent": r.parent,
                "child": r.child,
                "action_id": r.action_id,
                "final": r.final,
            }
            for r in items
        ]
        try:
            self.config.state_dir.mkdir(parents=True, exist_ok=True)
            tmp = self._index.with_name(f"runs.json.{secrets.token_hex(3)}.tmp")
            tmp.write_text(json.dumps(data), encoding="utf-8")
            os.replace(tmp, self._index)  # atomic: a crash never leaves a half-written index
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
            "problem": self.helper_note,
        }

    def _refuse_if_starting(self, category_id: str | None = None) -> None:
        with self._lock:
            runs = list(self._runs.values())
        if any(r.status == "starting" for r in runs):
            raise RunBusyError("Another run is still starting; wait for it to appear first.")
        for r in runs:
            if category_id and r.category_id == category_id and self._still_active(r):
                raise RunBusyError(
                    "A run of this workflow is already active (run "
                    + r.id
                    + "). Open it from Recent activity instead of starting a duplicate."
                )

    def _still_active(self, run: Run) -> bool:
        """True while the run is non-terminal, after re-reading its session log."""
        if run.status not in ACTIVE:
            return False
        self._follow(run)
        sv = run.view
        if sv is not None:
            sv.poll()
            state = sv.status(self._clock())
            with run.lock:
                if run.status in ("running", "input_needed", "handed_off") and run.status != state:
                    run.status = state
                    self._save()
        return run.status in ACTIVE

    def active(self) -> list[dict[str, Any]]:
        """Non-terminal runs (newest first) so a refreshed page or new tab can re-attach."""
        with self._lock:
            runs = sorted(self._runs.values(), key=lambda r: r.created, reverse=True)
        for r in runs:
            self._rebind_late_session(r)
        return [
            _brief(r, self._outcome(r))
            for r in runs
            if self._still_active(r)
        ]

    def start(
        self,
        category_id: str,
        raw: dict[str, Any],
        action_id: str | None = None,
        ensure_helper: Callable[[], bool] | None = None,
        gated: bool = False,
    ) -> Run:
        action_id = categories.canonical_action(action_id)
        try:
            values = categories.validate(category_id, raw, action_id)
            prompt = categories.build_prompt(category_id, values, self.config.prompts, action_id)
            gate_list = categories.gate_ids(category_id, action_id, gated)
            if gate_list:
                prompt = categories.stage_prompt(category_id, prompt, gate_list[0])
        except InputError as error:
            raise RunError(str(error)) from None
        self._check_sources(values, action_id)
        if gate_list:
            self._refuse_if_starting(category_id)
            with self._lock:
                self._refuse_if_starting(category_id)
                run = Run(self._new_id(), category_id, values, prompt, self._clock())
                run.action_id = action_id or categories.CATEGORIES[category_id].default_action
                run.status = "awaiting_gate"
                run.message = "Waiting for your approval of the collection plan."
                labels = dict(categories.GATES)
                run.gates = [
                    {"id": g, "label": labels[g], "state": "pending", "at": 0.0} for g in gate_list
                ]
                self._runs[run.id] = run
                self._save()
            return run
        workspace = str(self.config.resolved_workspace())
        self._refuse_if_starting(category_id)
        helper_ready = self.bridge.helper_connected(workspace)
        if not helper_ready and ensure_helper is not None:
            # Slow (install / wake / wait): never hold the manager lock, so status polling and
            # other requests keep answering; the starting check is repeated below.
            helper_ready = ensure_helper()
        with self._lock:
            self._refuse_if_starting(category_id)
            helper_ready = helper_ready or self.bridge.helper_connected(workspace)
            if not helper_ready and not self.config.allow_cli_fallback:
                raise RunBusyError(
                    "The VS Code helper is not connected for this workspace. Install it "
                    "(wizexpert console install-helper); the console opens a standard VS Code "
                    "window for the workspace automatically, or open one yourself (the Agents "
                    "window cannot run the helper), and try again."
                )
            run_id = self._new_id()
            run = Run(run_id, category_id, values, prompt, self._clock())
            run.action_id = action_id or categories.CATEGORIES[category_id].default_action
            self._runs[run_id] = run
            self._save()
        if self._async:
            threading.Thread(target=self._launch, args=(run, ensure_helper), daemon=True).start()
        else:
            self._launch(run, ensure_helper)
        return run

    def _new_id(self) -> str:
        return (
            time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(self._clock())) + "-" + secrets.token_hex(3)
        )

    def _check_sources(self, values: dict[str, str], action_id: str | None = None) -> None:
        """Existing-source checks for imported items (read-only; the console never writes)."""
        try:
            if values.get("case_folder"):
                imports.require_case(
                    self.config,
                    values["case_folder"],
                    ACTION_CASE_MODES.get(
                        categories.canonical_action(action_id) or "", "refresh"
                    ),
                )
            if values.get("report_folder"):
                latest = imports.latest_weekly(self.config)
                if latest is None or latest["name"] != values["report_folder"]:
                    raise ValueError(
                        "Only the latest weekly report can be updated"
                        + (f" ({latest['name']})." if latest else "; none was found.")
                    )
            if values.get("attachment"):
                imports.resolve_viewable(
                    self.config, self.config.output_roots[0] + "/" + values["attachment"]
                )
        except ValueError as error:
            raise RunError(str(error)) from None

    def _rebind_late_session(self, run: Run) -> None:
        """A chat can appear shortly after a restart; rebind only the exact restart-orphan case."""
        if run.status != "not_started" or run.message != LATE_START_MESSAGE or run.session_id:
            return
        try:
            sid = self.finder.find(run.prompt, run.created, self._claimed())
        except Exception:  # noqa: BLE001 - recovery is best effort
            return
        if sid:
            with run.lock:
                run.session_id, run.status, run.message = sid, "running", ""
                run.view = self._make_view(run, seed=True)
            self._save()

    def _claimed(self) -> set[str]:
        return {r.session_id for r in self._runs.values() if r.session_id}

    def _healthy_target(
        self, run: Run, workspace: str, ensure_helper: Callable[[], bool] | None
    ) -> str | None:
        """An instance that just answered a quick probe, recovering (new window) when needed."""
        instance = self.bridge.healthy_instance(workspace)
        if instance:
            probe = self.bridge.wait_result(
                self.bridge.post_job({"kind": "probe", "workspace": workspace, "target": instance}),
                PROBE_SECONDS,
            )
            if probe is not None and not probe.get("errors"):
                return instance
            run.attempts.append("helper probe: " + _result_text(probe) + " (marked unhealthy)")
            self.bridge.mark_unhealthy(instance)
        return self._recover_helper(run, workspace, ensure_helper)

    def _recover_helper(
        self, run: Run, workspace: str, ensure_helper: Callable[[], bool] | None
    ) -> str | None:
        if ensure_helper is not None:
            try:
                ensure_helper()
            except RunError as error:
                run.attempts.append("helper recovery: " + short(str(error), 200))
        return self.bridge.healthy_instance(workspace)

    def _launch(self, run: Run, ensure_helper: Callable[[], bool] | None = None) -> None:
        workspace = str(self.config.resolved_workspace())
        job = {
            "kind": "start_chat",
            "workspace": workspace,
            "agent": self.config.agent,
            "prompt": run.prompt,
            "newChatWait": self.config.new_chat_wait_ms,
        }
        try:
            target = self._healthy_target(run, workspace, ensure_helper)
            for attempt in range(2 if target else 0):
                # The retry only happens after a recovery and only when no chat for this prompt
                # appeared (_await_session), so a duplicate chat (and run) cannot be created.
                result = self.bridge.wait_result(
                    self.bridge.post_job({**job, "target": target}), START_SECONDS
                )
                run.attempts.append("helper: " + _result_text(result))
                if self._await_session(run, ATTEMPT_SECONDS):
                    return
                if result is not None and not result.get("errors"):
                    break  # the helper reported success: do not start another chat
                self.bridge.mark_unhealthy(target)
                target = None if attempt else self._recover_helper(run, workspace, ensure_helper)
                if target is None:
                    break
            if self.config.allow_cli_fallback:
                if self.helper_note and not self.bridge.helper_connected(workspace):
                    run.attempts.append("helper unavailable: " + short(self.helper_note, 160))
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
                    "VS Code did not start the chat. The helper must run in a standard VS Code "
                    "window for the workspace (not the Agents window). Attempts: "
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
        self._rebind_late_session(run)
        return run

    def history(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock:
            runs = sorted(self._runs.values(), key=lambda r: r.created, reverse=True)[:limit]
        return [
            _brief(r, self._outcome(r))
            for r in runs
        ]

    def reset_history(self) -> dict[str, Any]:
        """Forget the console's own run index so Dashboard/History start empty.

        Only runs.json (the website's index) is touched: it is moved aside to a timestamped
        backup next to it, never deleted. Deliverables, work-item folders, VS Code session logs
        and workflow configuration are not read or changed. Refused while any run is active.
        """
        with self._lock:
            runs = list(self._runs.values())
            if any(r.status in ACTIVE or r.status == "starting" for r in runs):
                raise RunError("A run is still active; stop or finish it before resetting history.")
            backup = ""
            if self._index.is_file():
                stamp = time.strftime("%Y%m%d-%H%M%S")
                name = f"runs.json.reset-{stamp}-{secrets.token_hex(2)}.bak"
                try:
                    os.replace(self._index, self._index.with_name(name))
                except OSError:
                    raise RunError("Could not back up the run index; nothing was reset.") from None
                backup = name
            self._runs.clear()
        return {"cleared": len(runs), "backup": backup}

    def view(self, run_id: str, since: int = 0) -> dict[str, Any]:
        run = self.get(run_id)
        self._follow(run)
        with run.lock:
            if run.session_id and run.view is None:
                run.view = self._make_view(run, seed=True)
            sv, status = run.view, run.status
        data: dict[str, Any] = {
            "id": run.id,
            "category": categories.CATEGORIES[run.category_id].title,
            "subject": run_subject(run),
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
            "can_stop": False,
            "can_open_output": False,
            "gates": [dict(g) for g in run.gates],
            "decisions": [dict(d) for d in run.decisions],
            "parent": run.parent,
            "child": run.child,
            "waiting_approval": False,
            "waiting_reason": "",
            "can_focus": False,
        }
        if sv is not None:
            sv.poll()
            now = self._clock()
            state = sv.status(now)
            with run.lock:
                if run.status in ("completed", "stopped") and state == "handed_off":
                    state = run.status  # a stale handoff in an old log never reopens a finished run
                if run.status in ("running", "input_needed", "handed_off", "completed", "stopped"):
                    changed = run.status != state
                    run.status = state
                    if state in ACTIVE and run.final is not None:
                        run.final = None  # resumed chat: the old frozen result no longer applies
                        changed = True
                    if changed:
                        self._save()
                status = run.status
                if status == "handed_off" and run.handoff:
                    run.message = (
                        "Handed off to a new chat"
                        + (f" '{run.handoff.get('title')}'" if run.handoff.get("title") else "")
                        + " \u2013 waiting for it to appear."
                    )
                if not run.ahp_id:
                    run.ahp_id = self.finder.ahp_id(run.session_id) or ""
                ahp = run.ahp_id
            data["message"] = run.message
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
                    "detail": pending.detail,
                    "key": pending.key,
                    "can_decide": pending.kind == "permission" and bool(ahp),
                }
                if pending
                else None
            )
            data["files"] = self._files(run, sv, status)
            data["can_open_chat"] = bool(ahp)
            data["can_stop"] = status not in INACTIVE
            data["can_open_output"] = status == "completed" and bool(data["files"])
            if status not in INACTIVE:
                if pending is not None and pending.kind == "permission":
                    data["waiting_approval"], data["waiting_reason"] = True, "approval"
                elif pending is None and sv.stalled(now):
                    data["waiting_approval"], data["waiting_reason"] = True, "stalled"
                data["can_focus"] = True
        data["status"] = status
        sync = self._sync_for(run)
        frozen = run.final if status in INACTIVE else None
        if frozen is not None:  # an ended run keeps the result it finished with
            data["checklist"] = [dict(s) for s in frozen["checklist"]]
            data["outcome"], reason = frozen["outcome"], frozen.get("reason", "")
        else:
            data["checklist"], data["outcome"] = build_checklist(
                status, data["gates"], bool(data["files"]), sync, run.action_id
            )
            reason = outcome_reason(data["checklist"])
            if status in INACTIVE and _is_settled(status, sync, run.action_id):
                with run.lock:
                    run.final = {"checklist": data["checklist"], "outcome": data["outcome"],
                                 "reason": reason}
                    self._save()
        if data["outcome"] == "incomplete":
            data["message"] = "Incomplete: " + (
                reason or "changed cases have no queued Refresh yet (see checklist)."
            )
        return data

    def settle_status_check(self, sync: dict[str, Any]) -> None:
        """Freeze an ended status-check run's result as soon as its sync settles, so a later
        sync overwriting the shared state cannot change it even if nobody viewed the run."""
        try:
            run = self.get(str(sync.get("check_run_id") or ""))
        except (RunError, KeyError):
            return
        if run.action_id != "status-check":
            return
        if run.final is not None or run.status not in INACTIVE:
            return
        if not _is_settled(run.status, sync, run.action_id):
            return
        try:  # the run may never have been viewed: compute outputs the same way view() does
            with run.lock:
                if run.session_id and run.view is None:
                    run.view = self._make_view(run, seed=True)
                sv = run.view
            if sv is not None:
                sv.poll()
                has_files = bool(self._files(run, sv, run.status))
            else:
                has_files = bool(run.files)
        except Exception:  # noqa: BLE001 - fall back to what is already known
            has_files = bool(run.files)
        with run.lock:
            if run.final is not None or run.status not in INACTIVE:
                return
            checklist, outcome = build_checklist(
                run.status, run.gates, has_files, sync, run.action_id
            )
            run.final = {"checklist": checklist, "outcome": outcome,
                         "reason": outcome_reason(checklist)}
            self._save()

    def _sync_for(self, run: Run) -> dict[str, Any] | None:
        if run.action_id != "status-check":
            return None
        state = imports.status_sync_state(self.config)
        return state if state.get("check_run_id") == run.id else None

    def _outcome(self, run: Run) -> str:
        """Outcome for lists (history/active/notifications); frozen once the run has ended."""
        if run.final is not None:
            return str(run.final["outcome"])
        return build_checklist(run.status, run.gates, False, self._sync_for(run), run.action_id)[1]

    def _files(self, run: Run, sv: SessionView, status: str) -> list[dict[str, Any]]:
        now = self._clock()
        with run.lock:
            stale = now - run.files_at >= FILES_REFRESH or run.files_n != len(sv.written)
            if stale or status in ("completed", "stopped") and not run.files:
                run.files = collect_files(
                    self.config, {**run.carried, **dict(sv.written)}, run.created
                )
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
            if result is None:
                self.bridge.mark_workspace_unhealthy(workspace)  # lets connect recovery open one
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

    def stop(self, run_id: str) -> None:
        run = self.get(run_id)
        if not run.ahp_id:
            raise RunError("The live chat is not ready to stop yet.")
        if run.status in INACTIVE:
            raise RunError("This run is no longer active.")
        sv = run.view
        inactive = ("completed", "stopped", "interrupted", "not_started")

        def guard() -> tuple[bool, str]:
            if run.status in inactive:
                return False, "this chat is no longer running"
            if sv is not None:
                sv.poll()
                if sv.status(self._clock()) in inactive:
                    return False, "this chat is no longer running"
            return True, ""

        job = self.bridge.post_job(
            {
                "kind": "stop_chat",
                "workspace": str(self.config.resolved_workspace()),
                "ahp": run.ahp_id,
                "openWait": self.config.open_wait_ms,
            },
            guard=guard,
        )
        result = self.bridge.wait_result(job, 20.0)
        if result is not None and result.get("info", {}).get("guard"):
            raise RunError("Not stopped: " + short(result["info"]["guard"], 120))
        if result is None or result.get("errors"):
            raise RunError("VS Code did not stop the chat: " + _result_text(result))

    def open_output(self, run_id: str) -> None:
        run = self.get(run_id)
        if run.status != "completed":
            raise RunError("Latest output is available after a successful refresh.")
        if run.view is None:
            raise RunError("No output is available for this run.")
        files = self._files(run, run.view, run.status)
        if not files:
            raise RunError("No safe local output was found for this run.")
        latest = files[0]
        path = (self.config.resolved_workspace() / latest["path"]).resolve()
        if not path.is_file() or self.config.resolved_workspace() not in path.parents:
            raise RunError("The latest output path is no longer available.")
        workspace = str(self.config.resolved_workspace())
        job = self.bridge.post_job({"kind": "open_file", "workspace": workspace, "path": str(path)})
        result = self.bridge.wait_result(job, 20.0)
        if result is None or result.get("errors"):
            raise RunError("VS Code did not open the latest output: " + _result_text(result))

    # -- console-owned approval gates ---
    def decide_gate(
        self,
        run_id: str,
        gate: str,
        decision: str,
        ensure_helper: Callable[[], bool] | None = None,
    ) -> dict[str, Any]:
        """Approve or reject the next gate; approval hands that stage's prompt to the agent.

        The decision is recorded in the run record. The first gate approves the run itself (it
        starts its chat); later gates start a follow-up run (a new chat) once the earlier stage
        finished. Rejecting ends the flow. The console never pushes, sends or deletes itself.
        """
        if decision not in ("approve", "reject"):
            raise RunError("Unknown decision.")
        run = self.get(run_id)
        with self._lock, run.lock:
            if run.child:
                raise RunError("A later stage of this flow was already started.")
            pending = [g for g in run.gates if g["state"] == "pending"]
            target = next((g for g in run.gates if g["id"] == gate), None)
            if target is None or target["state"] != "pending":
                raise RunError("That gate is not waiting for a decision.")
            if target is not pending[0]:
                raise RunError("Decide the earlier gate first.")
            first = run.gates.index(target) == 0
            if first and run.status != "awaiting_gate":
                raise RunError("This run is not waiting for approval.")
            if not first and run.status != "completed":
                raise RunError("The previous stage has not finished yet.")
            now = self._clock()
            target["state"] = "approved" if decision == "approve" else "rejected"
            target["at"] = now
            run.decisions.append({"gate": gate, "decision": decision, "at": now})
            if decision == "reject":
                for g in pending[1:]:
                    g["state"] = "skipped"
                if first:
                    run.status, run.message = "rejected", f"Rejected at the {target['label']} gate."
                self._save()
                return {"run_id": run.id, "status": run.status}
            self._save()
        try:
            if first:
                self._start_registered(run, ensure_helper)
                return {"run_id": run.id, "status": run.status}
            base = categories.strip_stage(run.prompt)
            prompt = categories.stage_prompt(run.category_id, base, gate)
        except (InputError, KeyError) as error:
            self._undo_gate(run, target)
            raise RunError(str(error)) from None
        except RunError:
            self._undo_gate(run, target)
            raise
        child = Run(self._new_id(), run.category_id, dict(run.values), prompt, self._clock())
        child.gates = [dict(g) for g in run.gates]
        child.decisions = [dict(d) for d in run.decisions]
        child.parent = run.id
        child.action_id = run.action_id
        with self._lock:
            self._runs[child.id] = child
            run.child = child.id
        try:
            self._start_registered(child, ensure_helper)
        except RunError:
            with self._lock:
                self._runs.pop(child.id, None)
                run.child = ""
            self._undo_gate(run, target)
            raise
        return {"run_id": child.id, "status": child.status}

    def _undo_gate(self, run: Run, gate: dict[str, Any]) -> None:
        with run.lock:
            gate["state"], gate["at"] = "pending", 0.0
            if run.decisions:
                run.decisions.pop()
            self._save()

    def _start_registered(self, run: Run, ensure_helper: Callable[[], bool] | None) -> None:
        """Hand an already registered run's prompt to the agent (helper readiness first)."""
        workspace = str(self.config.resolved_workspace())
        ready = self.bridge.helper_connected(workspace)
        if not ready and ensure_helper is not None:
            ready = ensure_helper()
        ready = ready or self.bridge.helper_connected(workspace)
        if not ready and not self.config.allow_cli_fallback:
            raise RunError(
                "The VS Code helper is not connected for this workspace; open a standard "
                "VS Code window for it and approve again."
            )
        with run.lock:
            run.status, run.message, run.created = "starting", "", self._clock()
            self._save()
        if self._async:
            threading.Thread(target=self._launch, args=(run, ensure_helper), daemon=True).start()
        else:
            self._launch(run, ensure_helper)

    # -- focus, MCP and local files ---
    def focus(self, run_id: str | None = None) -> str:
        """Bring the workspace's VS Code window (and the run's chat) to the front."""
        workspace = str(self.config.resolved_workspace())
        ahp = ""
        if run_id:
            ahp = self.get(run_id).ahp_id
        note = ""
        if self.bridge.helper_connected(workspace):
            job = self.bridge.post_job(
                {
                    "kind": "focus",
                    "workspace": workspace,
                    "ahp": ahp,
                    "openWait": self.config.open_wait_ms,
                }
            )
            result = self.bridge.wait_result(job, 20.0)
            if result is not None and not result.get("errors"):
                note = "chat revealed in VS Code"
            else:
                note = "helper: " + _result_text(result)
        # The extension API cannot raise the OS window; `code --reuse-window <workspace>` can.
        command = shutil.which(self.config.code_command) or self.config.code_command
        code = self._cli([command, "--reuse-window", workspace])
        if code != 0 and not note.startswith("chat revealed"):
            raise RunError("Could not focus VS Code (" + note + ").")
        return note or "window raised"

    def mcp_servers(self) -> list[str]:
        """Names of configured MCP servers that look like Wiz (names only, never settings)."""
        return list(self._mcp_definitions())

    def _mcp_definitions(self) -> dict[str, str]:
        """Wiz server name -> VS Code MCP definition ID (what the MCP commands match on)."""
        found: dict[str, str] = {}
        for path, collection in (
            (self.config.resolved_workspace() / ".vscode" / "mcp.json", "mcp.config.ws0"),
            (self.config.vscode_user_dir / "mcp.json", "mcp.config.usrlocal"),
        ):
            try:
                text = path.read_text(encoding="utf-8")
                data = json.loads(re.sub(r"(?m)^\s*//.*$", "", text))
            except (OSError, ValueError):
                continue
            servers = (
                data.get("servers") or data.get("mcpServers") if isinstance(data, dict) else None
            )
            if isinstance(servers, dict):
                for name in servers:
                    if (
                        "wiz" in str(name).lower()
                        and MCP_SERVER.fullmatch(str(name))
                        and name not in found
                    ):
                        found[str(name)] = f"{collection}.{name}"
        return dict(list(found.items())[:5])

    _mcp_hint: dict[str, Any] | None = None

    def mcp_status(self) -> dict[str, Any]:
        """connected / needs_auth / stopped for the Wiz MCP server (via the helper)."""
        servers = self.mcp_servers()
        workspace = str(self.config.resolved_workspace())
        out: dict[str, Any] = {
            "servers": servers,
            "state": "unknown",
            "helper": False,
            "detail": "",
        }
        if not servers:
            out.update(state="not_configured", detail="No Wiz MCP server found in mcp.json.")
            return out
        if not self.bridge.helper_connected(workspace, min_version=True):
            out["detail"] = (
                "The current VS Code helper is not connected. Reload the standard VS Code "
                f"window so helper {'.'.join(map(str, MIN_HELPER_VERSION))} or newer is active."
            )
            return out
        out["helper"] = True
        job = self.bridge.post_job(
            {"kind": "mcp_status", "workspace": workspace, "servers": servers}
        )
        result = self.bridge.wait_result(job, 15.0)
        if result is None or result.get("errors"):
            out["detail"] = "Status unavailable: " + _result_text(result)
            return out
        info = result.get("info") or {}
        tools = int(info.get("toolCount") or 0)
        hint = self._mcp_hint
        now = self._clock()
        if tools > 0:
            out.update(state="connected", detail="")
            self._mcp_hint = None
        elif hint and hint["action"] in ("start", "auth") and now - hint["at"] < MCP_HINT_SECONDS:
            out.update(
                state="needs_auth",
                detail="No tools yet: finish the SSO sign-in in the browser window, then refresh.",
            )
        else:
            out.update(state="stopped", detail="No Wiz tools are available (server stopped).")
        out["tools"] = tools
        return out

    def mcp_action(self, action: str, server: str | None = None) -> dict[str, Any]:
        """Start, stop or authenticate via VS Code MCP commands (sign-in is in the browser)."""
        if action not in MCP_ACTIONS:
            raise RunError("Unknown MCP action.")
        definitions = self._mcp_definitions()
        if not definitions:
            raise RunError("No Wiz MCP server found in mcp.json.")
        name = server or next(iter(definitions))
        if name not in definitions:
            raise RunError("Unknown MCP server.")
        workspace = str(self.config.resolved_workspace())
        if not self.bridge.helper_connected(workspace, min_version=True):
            raise RunError(
                "The current VS Code helper is not connected for this workspace. Reload the "
                "standard VS Code window so the latest helper is active."
            )
        job = self.bridge.post_job(
            {
                "kind": "mcp_action",
                "workspace": workspace,
                "action": action,
                "server": definitions[name],
            }
        )
        result = self.bridge.wait_result(job, 30.0)
        if result is None or result.get("errors"):
            raise RunError("VS Code could not run the MCP command: " + _result_text(result))
        if action in ("start", "auth"):
            self._mcp_hint = {"action": action, "at": self._clock()}
        elif action == "stop":
            self._mcp_hint = {"action": "stop", "at": self._clock()}
        return {"ok": True, "note": _result_text(result)}

    def open_deliverable(self, relative: str) -> None:
        """Open an existing deliverable (PDF/PPTX/HTML/...) with the system viewer, read-only."""
        try:
            path = imports.resolve_viewable(self.config, relative)
        except ValueError as error:
            raise RunError(str(error)) from None
        workspace = str(self.config.resolved_workspace())
        if not self.bridge.helper_connected(workspace):
            raise RunError("The VS Code helper is not connected for this workspace.")
        job = self.bridge.post_job(
            {"kind": "open_external", "workspace": workspace, "path": str(path)}
        )
        result = self.bridge.wait_result(job, 20.0)
        if result is None or result.get("errors"):
            raise RunError("VS Code did not open the file: " + _result_text(result))

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


def _step(id: str, label: str, state: str, detail: str = "") -> dict[str, str]:
    return {"id": id, "label": label, "state": state, "detail": detail}


def build_checklist(
    status: str,
    gates: list[dict[str, Any]],
    has_files: bool,
    sync: dict[str, Any] | None,
    action_id: str,
) -> tuple[list[dict[str, str]], str]:
    """End-of-run checklist (completed / skipped / blocked / not_applicable) and the outcome.

    A status check whose changed cases have no queued Refresh is 'incomplete', never a success.
    """
    done = status == "completed"
    steps = [_step("run", "Run finished", "completed" if done else "blocked",
                   "" if done else f"Run ended as {status}")]
    states = [g.get("state") for g in gates]
    if not gates:
        gate_state = "not_applicable"
    elif any(s in ("rejected", "pending") for s in states):
        gate_state = "blocked"
    elif any(s == "skipped" for s in states):
        gate_state = "skipped"
    else:
        gate_state = "completed"
    steps.append(_step("gates", "Approval gates", gate_state))
    if has_files:
        out = "completed"
    elif done:
        out = "not_applicable"
    else:
        out = "skipped"
    steps.append(_step("outputs", "Outputs produced", out))
    outcome = "completed" if done else status
    if action_id == "status-check":
        steps.append(
            _step("readonly", "Read-only status check", "completed" if done else "blocked")
        )
        label0 = "Refresh for changed cases"
        if sync is None:
            steps.append(_step("refresh", label0, "not_applicable"))
        elif sync.get("phase") == "checking":
            steps.append(_step("refresh", label0, "blocked",
                               "Status check result not read yet; sync again to read it"))
            if done:
                outcome = "incomplete"
        elif sync.get("phase") == "failed":
            steps.append(_step("refresh", label0, "blocked",
                               str(sync.get("error") or "Status check failed")))
            outcome = "incomplete"
        else:
            changed = [str(c) for c in sync.get("changed") or []]
            queued = {str(i.get("case")) for i in sync.get("queued") or [] if isinstance(i, dict)}
            skipped = {str(i.get("case")): str(i.get("reason", ""))
                       for i in sync.get("skipped") or [] if isinstance(i, dict)}
            if not changed:
                steps.append(_step("refresh", label0, "not_applicable", "No changed cases"))
            for case in changed:
                label = f"Refresh queued: {case}"
                if case in queued:
                    steps.append(_step(f"refresh:{case}", label, "completed"))
                elif case in skipped:
                    steps.append(_step(f"refresh:{case}", label, "skipped", skipped[case]))
                else:
                    steps.append(_step(f"refresh:{case}", label, "blocked",
                                       "Waiting for the one-active-run guard"))
            if done and any(c not in queued for c in changed):
                outcome = "incomplete"
    return steps, outcome


FINAL_OUTCOMES = frozenset((*INACTIVE, "incomplete"))
FINAL_REASON_MAX = 300
CHECKLIST_STATES = frozenset(("completed", "skipped", "blocked", "not_applicable"))
CHECKLIST_MAX = 60
CHECKLIST_FIELD_MAX = 80
CHECKLIST_DETAIL_MAX = 300


def clean_checklist(items: Any) -> list[dict[str, str]]:
    """Loaded checklist entries: only dicts with string id/label/state, bounded detail."""
    out: list[dict[str, str]] = []
    if not isinstance(items, list):
        return out
    for s in items:
        if not (isinstance(s, dict) and all(isinstance(s.get(k), str) and s[k]
                                            for k in ("id", "label", "state"))):
            continue
        if s["state"] not in CHECKLIST_STATES:
            continue
        detail = s.get("detail", "")
        if not isinstance(detail, str):
            continue
        out.append({"id": s["id"][:CHECKLIST_FIELD_MAX],
                    "label": s["label"][:CHECKLIST_DETAIL_MAX],
                    "state": s["state"][:CHECKLIST_FIELD_MAX],
                    "detail": detail[:CHECKLIST_DETAIL_MAX]})
        if len(out) >= CHECKLIST_MAX:
            break
    return out


def outcome_reason(steps: list[dict[str, str]]) -> str:
    """Why a run did not finish cleanly: the run's own end reason and the blocked/skipped Refresh
    details (failed check, refused or stopped start, guard wait), de-duplicated and capped."""
    parts: list[str] = []
    for s in steps:
        relevant = s["id"] == "run" or s["id"].startswith("refresh")
        if relevant and s["state"] in ("blocked", "skipped") and s.get("detail"):
            label = s["label"].replace("Refresh queued: ", "")
            text = s["detail"] if s["id"] in ("run", "refresh") else f"{label}: {s['detail']}"
            if text not in parts:
                parts.append(text)
    return short("; ".join(parts), 300)


def _is_settled(status: str, sync: dict[str, Any] | None, action_id: str) -> bool:
    """True when later syncs can no longer change this ended run's result."""
    if action_id != "status-check" or status != "completed":
        return True
    return sync is not None and sync.get("phase") in ("done", "failed")


SUBJECT_TITLE_MAX = 60
SUBJECT_TITLES_SHOWN = 2
SUBJECT_MAX = 160


def _title(slug: str, limit: int = SUBJECT_TITLE_MAX) -> str:
    text = re.sub(r"[-_]+", " ", slug).strip()
    return text if len(text) <= limit else text[: limit - 3].rstrip() + "..."


def run_subject(r: Run) -> str:
    """Issue/rule title a run applies to, from its case folder name (the issue title slug) or
    issue IDs; no evidence is read. Empty when the run has no specific subject."""
    values = r.values or {}
    folder = (values.get("case_folder") or "").strip()
    if folder:
        return _title(folder, SUBJECT_MAX)
    ids = (values.get("issue_ids") or "").strip()
    if ids:
        text = "Wiz issue(s) " + ids
        return text if len(text) <= SUBJECT_MAX else text[: SUBJECT_MAX - 3].rstrip() + "..."
    cases = [c for c in re.split(r"[,\s]+", values.get("case_list") or "") if c]
    if cases:
        shown = "; ".join(_title(c) for c in cases[:SUBJECT_TITLES_SHOWN])
        more = len(cases) - SUBJECT_TITLES_SHOWN
        text = shown + (f" (+{more} more)" if more > 0 else "")
        return text if len(text) <= SUBJECT_MAX else text[: SUBJECT_MAX - 3].rstrip() + "..."
    return ""


def _brief(r: Run, outcome: str = "") -> dict[str, Any]:
    """Safe public summary of a run; older runs without an action fall back to the category."""
    action_id, title = categories.action_summary(r.category_id, r.action_id)
    return {
        "subject": run_subject(r),
        "id": r.id,
        "category_id": r.category_id,
        "status": r.status,
        "outcome": outcome or r.status,
        "created": r.created,
        "action_id": action_id,
        "action_title": title,
    }


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
