"""Signed long-poll bridge between the console server and the VS Code helper extension.

The helper (a tiny extension inside the VS Code window) polls ``/vscode/jobs``; the server
queues structured jobs for it. Requests are signed with a shared token (HMAC-SHA256 over method,
path, time, nonce and body digest) and the helper only trusts answers the server signed back, so
another local program cannot learn the token or hand out jobs. The token is never sent.
"""

from __future__ import annotations

import contextlib
import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from collections import OrderedDict, deque
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .sessions import norm

CLOCK_SKEW = 60
LONG_POLL = 25.0
HELPER_ALIVE = 45.0
MAX_JOBS = 100


def mac(token: str, *parts: str) -> str:
    return hmac.new(token.encode(), "\n".join(parts).encode(), hashlib.sha256).hexdigest()


def digest(body: bytes) -> str:
    return hashlib.sha256(body or b"").hexdigest()


def load_or_create_token(path: Path, port: int) -> str:
    """Persist the shared token (created once) and the current port for the helper to read."""
    path = Path(path)
    token = ""  # nosec B105 - empty placeholder, not a credential
    with contextlib.suppress(OSError, ValueError):
        token = str(json.loads(path.read_text(encoding="utf-8")).get("token") or "")
    if len(token) < 32:
        token = secrets.token_hex(32)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"port": port, "token": token}), encoding="utf-8")
    with contextlib.suppress(OSError):
        os.chmod(path, 0o600)
    return token


class Bridge:
    def __init__(self, token: str, clock: Callable[[], float] = time.time) -> None:
        self.token = token
        self._clock = clock
        self._cond = threading.Condition()
        self._jobs: deque[dict[str, Any]] = deque(maxlen=MAX_JOBS)
        self._results: dict[int, dict[str, Any]] = {}
        self._guards: dict[int, Callable[[], tuple[bool, str]]] = {}
        self._next = 1
        self._nonces: OrderedDict[str, float] = OrderedDict()
        self.instances: dict[str, dict[str, Any]] = {}

    # -- request signing ---
    def verify(self, method: str, path: str, headers: Any, body: bytes) -> str | None:
        """Return the nonce when the request is correctly signed, fresh and not replayed."""
        nonce = headers.get("X-Console-Nonce", "")
        stamp = headers.get("X-Console-Time", "")
        auth = headers.get("X-Console-Auth", "")
        if not nonce or not stamp.isdigit() or not auth or len(nonce) > 64:
            return None
        now = self._clock()
        if abs(now - int(stamp)) > CLOCK_SKEW:
            return None
        want = mac(self.token, "req", method, path, stamp, nonce, digest(body))
        if not hmac.compare_digest(auth, want):
            return None
        with self._cond:
            for key in [k for k, t in self._nonces.items() if now - t > 2 * CLOCK_SKEW]:
                del self._nonces[key]
            if nonce in self._nonces:
                return None
            self._nonces[nonce] = now
        return nonce

    def proof(self, nonce: str, body: bytes) -> str:
        return mac(self.token, "resp", nonce, digest(body))

    # -- helper side ---
    def poll(
        self, after: int, instance: str, folders: list[str], wait: float = LONG_POLL
    ) -> dict[str, Any]:
        deadline = self._clock() + wait
        with self._cond:
            self.instances[instance] = {"seen": self._clock(), "folders": folders}
            while True:
                last = self._jobs[-1]["id"] if self._jobs else 0
                jobs = [j for j in self._jobs if j["id"] > after]
                if after < 0 or jobs or self._clock() >= deadline:
                    break
                self._cond.wait(timeout=min(1.0, max(0.05, deadline - self._clock())))
            self.instances[instance]["seen"] = self._clock()
            return {"jobs": [] if after < 0 else jobs, "last": last}

    def record_result(self, job_id: int, result: dict[str, Any]) -> None:
        with self._cond:
            self._results[job_id] = result
            self._cond.notify_all()

    def guard(self, job_id: int) -> tuple[bool, str]:
        check = self._guards.get(job_id)
        if check is None:
            return False, "unknown job"
        return check()

    # -- server side ---
    def post_job(
        self, job: dict[str, Any], guard: Callable[[], tuple[bool, str]] | None = None
    ) -> int:
        with self._cond:
            job_id = self._next
            self._next += 1
            self._jobs.append({**job, "id": job_id})
            if guard:
                self._guards[job_id] = guard
            self._cond.notify_all()
        return job_id

    def wait_result(self, job_id: int, timeout: float) -> dict[str, Any] | None:
        end = self._clock() + timeout
        with self._cond:
            while job_id not in self._results:
                remaining = end - self._clock()
                if remaining <= 0:
                    return None
                self._cond.wait(timeout=min(1.0, remaining))
            return self._results.pop(job_id)

    def helper_connected(self, workspace: str | None = None) -> bool:
        """A helper window polled recently (and, if given, has this workspace folder open)."""
        return self.helper_seen_within(workspace, HELPER_ALIVE)

    def helper_seen_within(self, workspace: str | None, seconds: float) -> bool:
        """A helper for this workspace polled within ``seconds`` (longer than the alive limit)."""
        now = self._clock()
        with self._cond:
            for info in self.instances.values():
                if now - info["seen"] > seconds:
                    continue
                if workspace is None or any(norm(f) == norm(workspace) for f in info["folders"]):
                    return True
        return False
