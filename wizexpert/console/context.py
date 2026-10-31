"""Per-run context handed to adapters: read-only Wiz calls, immutable evidence, activity log."""

from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .policy import ReadOnlyViolation, check_discover, check_execute

# The exact tool name `workflow-qa collection-check` recognises as a Wiz execute call.
ACTIVITY_TOOL_NAME = "mcp__wiz__execute"
EVIDENCE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,120}\.(?:json|csv)")
MAX_ATTEMPTS = 3


class ReconnectRequired(Exception):
    """Wiz returned 401 / an OAuth challenge. Stop; the user must reconnect Wiz."""


class McpCallError(Exception):
    """A Wiz call failed (network, server or tool error)."""


class CollectionAborted(Exception):
    """The same call failed three times, or the run was cancelled: do not publish."""


class WindowExceeded(CollectionAborted):
    """The observation window ran out. Abandon the run; evidence is never stitched."""


def utc_now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def iso(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


class ActivityLog:
    """JSONL record of Wiz calls in the shape `workflow-qa collection-check` reads."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch()

    def record(self, event_type: str, data: dict[str, Any]) -> None:
        line = json.dumps(
            {"timestamp": iso(utc_now()), "type": event_type, "data": data}, ensure_ascii=True
        )
        with self._lock, self.path.open("a", encoding="utf-8") as stream:
            stream.write(line + "\n")

    def note(self, message: str) -> None:
        self.record("console.note", {"message": message})


class RunContext:
    """Everything an adapter may use during a run. Wiz access is read-only and logged."""

    def __init__(
        self,
        *,
        run_id: str,
        category_id: str,
        inputs: dict[str, Any],
        dry_run: bool,
        run_dir: Path,
        output_dir: Path,
        client: Any,
        activity: ActivityLog,
        log: Callable[[str], None],
        cancelled: Callable[[], bool] = lambda: False,
        max_attempts: int = MAX_ATTEMPTS,
        workers: int = 4,
        retry_delay: float = 1.0,
    ) -> None:
        self.run_id = run_id
        self.category_id = category_id
        self.inputs = inputs
        self.dry_run = dry_run
        self.run_dir = Path(run_dir)
        self.evidence_dir = self.run_dir / "evidence"
        self.output_dir = Path(output_dir)
        self.data: dict[str, Any] = {}  # adapter scratch space between phases
        self.evidence_hashes: dict[str, str] = {}
        self._client = client
        self._activity = activity
        self._log = log
        self._cancelled = cancelled
        self._max_attempts = max_attempts
        self._workers = workers
        self._retry_delay = retry_delay
        self._deadline: float | None = None
        self._monotonic: Callable[[], float] = time.monotonic

    # -- logging / cancellation ------------------------------------------------------
    def log(self, message: str) -> None:
        self._log(str(message))

    def check_cancelled(self) -> None:
        if self._cancelled():
            raise CollectionAborted("The run was cancelled.")
        if self._deadline is not None and self._monotonic() > self._deadline:
            raise WindowExceeded(
                "The observation window was exceeded. Start a new run; evidence from "
                "different runs is never stitched."
            )

    def set_window(self, seconds: float | None) -> None:
        """Start the observation window now (None or 0 disables it)."""
        self._deadline = self._monotonic() + seconds if seconds else None

    # -- Wiz access (read-only) --------------------------------------------------------
    def call(self, tool_name: str, parameters: dict[str, Any] | None = None) -> Any:
        """One read-only Wiz ``execute``; up to three attempts, never retrying auth failures."""
        parameters = parameters or {}
        check_execute(tool_name, parameters)  # refuses anything but a plain read
        last: Exception | None = None
        for attempt in range(1, self._max_attempts + 1):
            self.check_cancelled()
            self._activity.record(
                "tool.execution_start",
                {
                    "toolName": ACTIVITY_TOOL_NAME,
                    "arguments": {"tool_name": tool_name, "parameters": parameters},
                    "attempt": attempt,
                },
            )
            try:
                result = self._client.execute(tool_name, parameters)
            except ReconnectRequired:
                self._activity.record("tool.execution_complete", {"success": False, "auth": True})
                raise
            except ReadOnlyViolation:
                raise
            except Exception as error:  # noqa: BLE001 - any transport/tool failure is retried
                last = error
                self._activity.record(
                    "tool.execution_complete",
                    {"success": False, "error": type(error).__name__},
                )
                self.log(f"Wiz call {tool_name} failed (attempt {attempt}/{self._max_attempts}).")
                if attempt < self._max_attempts:
                    time.sleep(self._retry_delay)
                continue
            self._activity.record("tool.execution_complete", {"success": True})
            return result
        raise CollectionAborted(
            f"Unable to fetch: {tool_name} failed {self._max_attempts} times "
            f"({type(last).__name__}). Start a new run; nothing was published."
        )

    def call_many(self, calls: list[tuple[str, dict[str, Any]]]) -> list[Any]:
        """Run independent read-only calls in parallel; results keep the input order."""
        for tool_name, parameters in calls:  # refuse the whole batch before any traffic
            check_execute(tool_name, parameters)
        if len(calls) <= 1:
            return [self.call(t, p) for t, p in calls]
        with ThreadPoolExecutor(max_workers=min(self._workers, len(calls))) as pool:
            futures = [pool.submit(self.call, t, p) for t, p in calls]
            outcomes: list[Any] = []
            errors: list[Exception] = []
            for future in futures:
                try:
                    outcomes.append(future.result())
                except Exception as error:  # noqa: BLE001
                    errors.append(error)
        for error in errors:
            if isinstance(error, ReconnectRequired):
                raise error
        if errors:
            raise errors[0]
        return outcomes

    def discover(self, domain: str | None = None) -> Any:
        check_discover(domain)
        self._activity.record("console.discover", {"domain": domain})
        return self._client.discover(domain)

    # -- immutable evidence --------------------------------------------------------------
    def save_evidence(self, name: str, content: Any) -> Path:
        """Write a new evidence file (JSON or CSV text). Existing evidence is never replaced."""
        if not EVIDENCE_NAME.fullmatch(name):
            raise ValueError(f"Unsafe evidence file name: {name!r}")
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        target = self.evidence_dir / name
        if name.endswith(".csv") and isinstance(content, str):
            payload = content.encode("utf-8")
        else:
            payload = (json.dumps(content, indent=2, ensure_ascii=True) + "\n").encode("utf-8")
        with target.open("xb") as stream:  # 'x': refuses to overwrite retained evidence
            stream.write(payload)
        self.evidence_hashes[name] = hashlib.sha256(payload).hexdigest()
        return target

    def read_evidence(self, name: str) -> Any:
        if not EVIDENCE_NAME.fullmatch(name):
            raise ValueError(f"Unsafe evidence file name: {name!r}")
        return json.loads((self.evidence_dir / name).read_text(encoding="utf-8"))
