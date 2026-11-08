"""Localhost-only HTTP server for the workflow console (standard library only).

The console is a frontend: it starts a normal VS Code agent-mode chat (through the helper
extension) and shows that session's progress. Safety properties (each covered by tests):
- binds 127.0.0.1 only; the Host header must be the loopback name and port we serve;
- every /api request needs the per-process CSRF token header; POSTs also need a matching
  Origin and a JSON content type;
- the helper endpoints (/vscode/*) accept only HMAC-signed requests and sign their answers;
- strict CSP (no inline script), no caching, no framing, no referrer;
- the results list shows only deliverable file names and locations; no file content is served.
"""

from __future__ import annotations

import argparse
import contextlib
import hmac
import json
import re
import secrets
import subprocess  # nosec B404
import sys
import threading
import time
import webbrowser
from collections.abc import Sequence
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

from . import imports, launcher, sessions, stakeholder
from .bridge import Bridge, load_or_create_token
from .config import (
    MAX_PHOTO_BYTES,
    PHOTO_TYPES,
    ConsoleConfig,
    default_state_dir,
    find_photo,
    load_overrides,
    load_profile,
    photo_extension,
    remove_photo,
    save_photo,
    save_profile,
)
from .runs import RunError, RunManager

STATIC_DIR = Path(__file__).resolve().parent / "static"
STATIC_FILES = {
    "index.html": "text/html; charset=utf-8",
    "app.js": "text/javascript; charset=utf-8",
    "style.css": "text/css; charset=utf-8",
    "assets/logo.svg": "image/svg+xml",
    "assets/workflow-risk-issues.svg": "image/svg+xml",
    "assets/workflow-daily-progress.svg": "image/svg+xml",
    "assets/workflow-weekly-progress.svg": "image/svg+xml",
    "assets/workflow-monthly-governance.svg": "image/svg+xml",
}
MAX_BODY = 256 * 1024
PHOTO_UPLOAD_TIMEOUT = 15.0  # seconds, overall deadline for one photo upload body
WINDOW_WAIT_SECONDS = 45.0  # time for a freshly opened window to start the helper
WINDOW_COOLDOWN_SECONDS = 90.0  # at most one window launch per cooldown
RECENT_CONNECT_SECONDS = 120.0  # a helper seen this recently gets a reconnect grace first
RECONNECT_GRACE_SECONDS = 8.0  # wait for a reconnect (e.g. window reload) before launching
RUN_ID = re.compile(r"\d{8}T\d{6}Z-[0-9a-f]{6}")
AGENT_NAME = re.compile(r"[A-Za-z0-9 ._-]{1,60}")
CSP = (
    "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; "
    "img-src 'self' data: blob:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
)
SECURITY_HEADERS = {
    "Content-Security-Policy": CSP,
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Cross-Origin-Opener-Policy": "same-origin",
}


# Shareable client-side routes (history.pushState): the page itself renders the right view.
APP_ROUTE = re.compile(
    r"^/(workflow/[\w-]+(/[\w-]+){0,2}|run/[\w-]+|dashboard|history|in-progress)/?$"
)


class ConsoleApp:
    def __init__(
        self,
        manager: RunManager,
        bridge: Bridge,
        csrf_token: str,
        port: int,
        config: ConsoleConfig,
    ) -> None:
        self.manager = manager
        self.bridge = bridge
        self.csrf_token = csrf_token
        self.port = port
        self.config = config
        self.allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
        self.allowed_origins = {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}
        self._ensure_lock = threading.Lock()
        self._connecting = False
        self._clock = time.monotonic
        self._last_launch: float | None = None
        self.helper_problem = ""

    def ensure_helper(self) -> bool:
        """Get a helper connected for this workspace without manual steps; single-flight.

        Order: already connected -> install only when this version is not registered -> open a
        standard VS Code window for the workspace (``code -n``; the Agents window never loads
        user extensions), at most one per cooldown; a helper seen within the last 120 s first gets
        a short reconnect grace (window reload) -> wait. When everything fails the concrete reason
        is kept in ``manager.helper_note``;
        with the ``code chat`` fallback allowed the run goes on through it (False), otherwise a
        RunError names the reason.
        """
        workspace = str(self.config.resolved_workspace())
        if self._wait_for_helper(workspace, 3.0):
            return True
        if not self._ensure_lock.acquire(blocking=False):
            # Another request is already recovering the helper: wait for it, never start a second.
            if self._wait_for_helper(workspace, 25.0):
                return True
            return self._helper_failed("The helper recovery already in progress did not connect.")
        self._connecting = True
        try:
            if self._wait_for_helper(workspace, 0.0):
                return True
            from . import helper

            out = Path.home() / ".wizexpert-console" / "wizexpert-console-helper.vsix"
            launched = False
            skipped = ""
            try:
                if helper.install(out, self.config.code_command) != 0:
                    return self._helper_failed("The VS Code helper could not be installed.")
                if self.bridge.helper_seen_within(
                    workspace, RECENT_CONNECT_SECONDS
                ) and self._wait_for_helper(workspace, RECONNECT_GRACE_SECONDS):
                    return True  # e.g. a window reload: the helper came back on its own
                skipped = self._launch_skip_reason(workspace)
                if not skipped:
                    self._last_launch = self._clock()
                    code = helper.open_workspace_window(self.config.code_command, workspace)
                    if code != 0:
                        return self._helper_failed(
                            f"The VS Code CLI could not open a standard window for the workspace "
                            f"(exit {code})."
                        )
                    launched = True
            except (OSError, subprocess.SubprocessError) as error:
                return self._helper_failed(f"Could not automate the VS Code helper setup: {error}")
            if self._wait_for_helper(workspace, WINDOW_WAIT_SECONDS if launched else 20.0):
                return True
            if launched:
                return self._helper_failed(
                    "A standard VS Code window for this workspace was opened automatically, but "
                    "the helper did not connect. The helper must run in a standard VS Code "
                    "window, not the Agents window; check that the helper extension is enabled "
                    "and the workspace is trusted there."
                )
            return self._helper_failed(
                "The VS Code helper did not connect (" + skipped + "). The helper must run in "
                "a standard VS Code window for this workspace, not the Agents window."
            )
        finally:
            self._connecting = False
            self._ensure_lock.release()

    def _launch_skip_reason(self, workspace: str) -> str:
        """Why a new window must not be opened now ('' when one may be opened)."""
        if (
            self._last_launch is not None
            and self._clock() - self._last_launch < WINDOW_COOLDOWN_SECONDS
        ):
            return "a standard window was already opened a moment ago, so none was opened again"
        return ""

    def _helper_failed(self, reason: str) -> bool:
        self.manager_note(reason)
        if self.config.allow_cli_fallback:
            return False
        raise RunError(reason + " Open the workspace in a standard VS Code window, then retry.")

    def manager_note(self, text: str) -> None:
        self.helper_problem = text
        with contextlib.suppress(AttributeError):
            self.manager.helper_note = text

    def connect_async(self) -> dict[str, Any]:
        """Start recovery in the background unless it is already running (page auto-connect)."""
        workspace = str(self.config.resolved_workspace())
        if not self.bridge.helper_connected(workspace) and not self._connecting:

            def work() -> None:
                with contextlib.suppress(RunError):
                    self.ensure_helper()

            threading.Thread(target=work, daemon=True).start()
        return {
            "connected": self.bridge.helper_connected(workspace),
            "connecting": self._connecting,
            "problem": self.helper_problem,
        }

    def _wait_for_helper(self, workspace: str, seconds: float) -> bool:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if self.bridge.helper_connected(workspace):
                return True
            time.sleep(0.25)
        return self.bridge.helper_connected(workspace)


class ConsoleServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def __init__(self, port: int, app_factory: Any) -> None:
        super().__init__(("127.0.0.1", port), ConsoleHandler)  # loopback only, by construction
        self.port = self.server_address[1]
        self.app: ConsoleApp = app_factory(self.port)

    def handle_error(self, request: Any, client_address: Any) -> None:
        """Dropped connections are routine; never print request details."""
        return


class ConsoleHandler(BaseHTTPRequestHandler):
    server: ConsoleServer
    protocol_version = "HTTP/1.1"
    server_version = "WizExpertConsole"
    sys_version = ""
    _body_read = False

    def log_message(self, *_args: Any) -> None:
        return

    @property
    def app(self) -> ConsoleApp:
        return self.server.app

    # -- plumbing ---
    def _drain(self) -> None:
        """Consume a small unread request body so the client sees our answer, not a reset."""
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return
        if 0 < length <= MAX_BODY and not self._body_read:
            self._body_read = True
            try:
                self.rfile.read(length)
            except OSError:
                return

    def _send(
        self, status: int, body: bytes, ctype: str, extra: dict[str, str] | None = None
    ) -> None:
        if status >= 400 and self.command == "POST":
            self._drain()
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for key, value in {**SECURITY_HEADERS, **(extra or {})}.items():
            self.send_header(key, value)
        if status >= 400 and self.command == "POST":  # the body may be unread: do not reuse
            self.send_header("Connection", "close")
            self.close_connection = True
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, status: int, value: Any, extra: dict[str, str] | None = None) -> None:
        self._send(
            status, json.dumps(value).encode("utf-8"), "application/json; charset=utf-8", extra
        )

    def _error(self, status: int, message: str) -> None:
        self._json(status, {"error": message})

    def _host_ok(self) -> bool:
        return self.headers.get("Host", "") in self.app.allowed_hosts

    def _csrf_ok(self) -> bool:
        return hmac.compare_digest(
            self.headers.get("X-CSRF-Token", "").encode(), self.app.csrf_token.encode()
        )

    def _origin_ok(self) -> bool:
        return self.headers.get("Origin") in self.app.allowed_origins

    def _body(self) -> bytes | None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = -1
        if length < 0 or length > MAX_BODY:
            self._error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "Request body too large.")
            return None
        self._body_read = True
        return self.rfile.read(length)

    def _json_body(self) -> dict[str, Any] | None:
        if not self.headers.get("Content-Type", "").lower().startswith("application/json"):
            self._error(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "JSON body required.")
            return None
        raw = self._body()
        if raw is None:
            return None
        try:
            value = json.loads(raw.decode("utf-8") or "{}")
        except (ValueError, UnicodeDecodeError):
            self._error(HTTPStatus.BAD_REQUEST, "Invalid JSON.")
            return None
        if not isinstance(value, dict):
            self._error(HTTPStatus.BAD_REQUEST, "A JSON object is required.")
            return None
        return value

    # -- verbs ---
    def do_GET(self) -> None:  # noqa: N802
        if not self._host_ok():
            return self._error(HTTPStatus.MISDIRECTED_REQUEST, "Unexpected Host header.")
        parts = urlsplit(self.path)
        path = parts.path
        if path in ("/", "/index.html") or APP_ROUTE.match(path):
            return self._index()
        if path.startswith("/static/"):
            return self._static(path[len("/static/") :])
        if path == "/vscode/jobs":
            return self._bridge_jobs(parts)
        if path.startswith("/api/"):
            if not self._csrf_ok():
                return self._error(HTTPStatus.FORBIDDEN, "Missing or invalid CSRF token.")
            return self._api_get(path, parse_qs(parts.query))
        self._error(HTTPStatus.NOT_FOUND, "Not found.")

    do_HEAD = do_GET  # noqa: N815

    def do_POST(self) -> None:  # noqa: N802
        self._body_read = False
        if not self._host_ok():
            return self._error(HTTPStatus.MISDIRECTED_REQUEST, "Unexpected Host header.")
        path = urlsplit(self.path).path
        if path in ("/vscode/result", "/vscode/guard"):
            return self._bridge_post(path)
        if not path.startswith("/api/"):
            return self._error(HTTPStatus.NOT_FOUND, "Not found.")
        if not self._origin_ok():
            return self._error(HTTPStatus.FORBIDDEN, "Cross-origin request refused.")
        if not self._csrf_ok():
            return self._error(HTTPStatus.FORBIDDEN, "Missing or invalid CSRF token.")
        if path == "/api/profile/photo":
            return self._photo_upload()
        body = self._json_body()
        if body is None:
            return None
        try:
            return self._api_post(path, body)
        except RunError as error:
            return self._error(HTTPStatus.BAD_REQUEST, str(error))

    def _photo_upload(self) -> None:
        if not load_profile(self.app.config.state_dir)["configured"]:
            return self._error(HTTPStatus.CONFLICT, "Set up a profile first.")
        raw_length = self.headers.get("Content-Length")
        try:
            length = int(raw_length) if raw_length is not None else -1
        except ValueError:
            length = -1
        if length < 0:
            return self._error(HTTPStatus.LENGTH_REQUIRED, "Content-Length required.")
        if length == 0 or length > MAX_PHOTO_BYTES:
            return self._error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "Photo must be at most 1 MB.")
        self._body_read = True
        data = self._read_photo_body(length)
        if data is None:
            self.close_connection = True
            return self._error(HTTPStatus.REQUEST_TIMEOUT, "Photo upload timed out.")
        try:
            save_photo(self.app.config.state_dir, data)
        except ValueError as error:  # fixed validation messages, safe to show
            return self._error(HTTPStatus.BAD_REQUEST, str(error))
        except OSError:  # never expose filesystem paths
            return self._error(HTTPStatus.BAD_REQUEST, "Photo could not be saved.")
        self._json(HTTPStatus.OK, load_profile(self.app.config.state_dir))

    def _read_photo_body(self, length: int) -> bytes | None:
        """Read the upload under an overall deadline; None if it is too slow.

        Only this connection's socket is affected (one thread per connection), so other
        console requests are never delayed.
        """
        deadline = time.monotonic() + PHOTO_UPLOAD_TIMEOUT
        chunks: list[bytes] = []
        remaining = length
        try:
            while remaining > 0:
                left = deadline - time.monotonic()
                if left <= 0:
                    return None
                self.connection.settimeout(left)
                chunk = self.rfile.read1(min(remaining, 65536))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
        except OSError:  # includes socket timeouts and resets
            return None
        finally:
            with contextlib.suppress(OSError):
                self.connection.settimeout(None)
        return b"".join(chunks)

    def do_DELETE(self) -> None:  # noqa: N802
        if not self._host_ok():
            return self._error(HTTPStatus.MISDIRECTED_REQUEST, "Unexpected Host header.")
        if urlsplit(self.path).path != "/api/profile/photo":
            return self._method_not_allowed()
        if not self._origin_ok():
            return self._error(HTTPStatus.FORBIDDEN, "Cross-origin request refused.")
        if not self._csrf_ok():
            return self._error(HTTPStatus.FORBIDDEN, "Missing or invalid CSRF token.")
        if not load_profile(self.app.config.state_dir)["configured"]:
            return self._error(HTTPStatus.CONFLICT, "Set up a profile first.")
        remove_photo(self.app.config.state_dir)
        self._json(HTTPStatus.OK, load_profile(self.app.config.state_dir))

    def _method_not_allowed(self) -> None:
        self._error(HTTPStatus.METHOD_NOT_ALLOWED, "Method not allowed.")

    do_PUT = do_PATCH = do_OPTIONS = _method_not_allowed  # noqa: N815

    # -- static ---
    def _index(self) -> None:
        html = (
            (STATIC_DIR / "index.html")
            .read_text(encoding="utf-8")
            .replace("__CSRF_TOKEN__", self.app.csrf_token)
        )
        self._send(HTTPStatus.OK, html.encode("utf-8"), STATIC_FILES["index.html"])

    def _static(self, name: str) -> None:
        if name not in STATIC_FILES or name == "index.html":
            return self._error(HTTPStatus.NOT_FOUND, "Not found.")
        self._send(HTTPStatus.OK, (STATIC_DIR / name).read_bytes(), STATIC_FILES[name])

    # -- helper bridge (HMAC-signed) ---
    def _signed_json(self, nonce: str, value: Any) -> None:
        body = json.dumps(value).encode("utf-8")
        self._send(
            HTTPStatus.OK,
            body,
            "application/json; charset=utf-8",
            {"X-Console-Proof": self.app.bridge.proof(nonce, body)},
        )

    def _bridge_jobs(self, parts: Any) -> None:
        bridge = self.app.bridge
        nonce = bridge.verify("GET", self.path, self.headers, b"")
        if nonce is None:
            return self._error(HTTPStatus.FORBIDDEN, "Bad signature.")
        query = parse_qs(parts.query)
        try:
            after = int((query.get("after") or ["-1"])[0])
            instance = re.sub(r"[^0-9a-f]", "", (query.get("instance") or [""])[0])[:32]
            folders = json.loads(unquote((query.get("folders") or ["[]"])[0]))
            folders = [str(f) for f in folders][:10] if isinstance(folders, list) else []
            version = str((query.get("version") or [""])[0])[:20] or None
        except (ValueError, TypeError):
            return self._error(HTTPStatus.BAD_REQUEST, "Bad query.")
        self._signed_json(nonce, bridge.poll(after, instance or "x", folders, version=version))

    def _bridge_post(self, path: str) -> None:
        bridge = self.app.bridge
        raw = self._body()
        if raw is None:
            return None
        nonce = bridge.verify("POST", self.path, self.headers, raw)
        if nonce is None:
            return self._error(HTTPStatus.FORBIDDEN, "Bad signature.")
        try:
            data = json.loads(raw.decode("utf-8") or "{}")
            job_id = int(data["id"])
        except (ValueError, KeyError, TypeError):
            return self._error(HTTPStatus.BAD_REQUEST, "Bad request.")
        if path == "/vscode/guard":
            ok, reason = bridge.guard(job_id)
            return self._signed_json(nonce, {"ok": ok, "reason": reason})
        errors = [str(e)[:200] for e in (data.get("errors") or [])][:5]
        info = data.get("info") if isinstance(data.get("info"), dict) else {}
        bridge.record_result(job_id, {"errors": errors, "info": info})
        self._signed_json(nonce, {"ok": True})

    # -- API ---
    def _api_get(self, path: str, query: dict[str, list[str]]) -> None:
        manager = self.app.manager
        if path == "/api/bootstrap":
            return self._json(
                HTTPStatus.OK,
                {
                    "categories": manager.categories(),
                    "helper": manager.helper_state(),
                    "history": manager.history(),
                    "active": manager.active(),
                },
            )
        if path == "/api/profile/photo":
            photo = find_photo(self.app.config.state_dir)
            if photo is None or not load_profile(self.app.config.state_dir)["configured"]:
                return self._error(HTTPStatus.NOT_FOUND, "No photo.")
            try:
                data = photo.read_bytes()
            except OSError:
                return self._error(HTTPStatus.NOT_FOUND, "No photo.")
            return self._send(
                HTTPStatus.OK, data, PHOTO_TYPES[photo.suffix],
                {"X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"},
            )
        if path == "/api/profile":
            return self._json(HTTPStatus.OK, load_profile(self.app.config.state_dir))
        if path == "/api/weekly-progress/previous-reports":
            reports = sessions.list_previous_weekly_reports(self.app.config)
            return self._json(
                HTTPStatus.OK,
                {
                    "reports": reports,
                    "empty": not reports,
                    "message": ""
                    if reports
                    else "No previous weekly progress reports were found in the local "
                    "deliverables folders; choose first report or enter a folder name.",
                },
            )
        if path.startswith("/api/imports/") or path == "/api/helper/mcp":
            return self._api_imports(path, query)
        if path == "/api/runs/active":
            return self._json(HTTPStatus.OK, {"runs": manager.active()})
        match = re.fullmatch(r"/api/runs/([^/]+)", path)
        if match and RUN_ID.fullmatch(match.group(1)):
            try:
                since = max(0, int((query.get("since") or ["0"])[0]))
                return self._json(HTTPStatus.OK, manager.view(match.group(1), since))
            except (RunError, ValueError):
                return self._error(HTTPStatus.NOT_FOUND, "Unknown run.")
        self._error(HTTPStatus.NOT_FOUND, "Not found.")

    def _api_imports(self, path: str, query: dict[str, list[str]]) -> None:
        """Read-only listings of existing local deliverables plus the Wiz MCP status."""
        config = self.app.config
        arg = lambda name: (query.get(name) or [""])[0]  # noqa: E731
        try:
            if path == "/api/helper/mcp":
                return self._json(HTTPStatus.OK, self.app.manager.mcp_status())
            if path == "/api/imports/risk-issues":
                return self._json(HTTPStatus.OK, {"cases": imports.scan_risk_cases(config)})
            if path == "/api/imports/risk-issues/sync":
                # Side-effect free: only POST may start or advance runs.
                return self._json(
                    HTTPStatus.OK,
                    {
                        "due": imports.status_sync_due(config),
                        "state": imports.status_sync_state(config),
                        "queued": [],
                        "hours": config.status_sync_hours,
                        "assignee_configured": bool(config.status_sync_assignee),
                    },
                )
            if path == "/api/imports/files":
                return self._json(
                    HTTPStatus.OK,
                    {"files": launcher.list_files(config, arg("category"), arg("folder"))},
                )
            if path == "/api/imports/case-files":
                return self._json(
                    HTTPStatus.OK, {"files": launcher.list_case_files(config, arg("case"))}
                )
            if path == "/api/imports/stakeholder-response":
                return self._json(
                    HTTPStatus.OK,
                    {"responses": stakeholder.list_responses(config, arg("work_item"))},
                )
            if path == "/api/imports/weekly":
                return self._json(HTTPStatus.OK, {"reports": imports.scan_weekly(config)})
            if path == "/api/imports/monthly":
                return self._json(HTTPStatus.OK, {"months": imports.scan_monthly(config)})
            if path == "/api/imports/weekly-diff":
                reports = imports.scan_weekly(config)
                current = arg("current") or (reports[0]["name"] if reports else "")
                previous = arg("previous")
                if not previous:
                    names = [r["name"] for r in reports]
                    older = names[names.index(current) + 1 :] if current in names else []
                    previous = older[0] if older else ""
                if not previous:
                    raise ValueError("There is no earlier weekly report to compare with.")
                return self._json(HTTPStatus.OK, imports.weekly_diff(config, current, previous))
            if path == "/api/imports/monthly-compare":
                return self._json(
                    HTTPStatus.OK,
                    imports.compare_months(config, arg("month"), arg("other") or None),
                )
        except ValueError as error:
            return self._error(HTTPStatus.BAD_REQUEST, str(error))
        self._error(HTTPStatus.NOT_FOUND, "Not found.")

    def _api_post(self, path: str, body: dict[str, Any]) -> None:
        manager = self.app.manager
        if path == "/api/runs":
            category, inputs = body.get("category_id"), body.get("inputs", {})
            if not isinstance(category, str) or not isinstance(inputs, dict):
                raise RunError("category_id and inputs are required.")
            action = body.get("action_id")
            if action is not None and not isinstance(action, str):
                raise RunError("action_id must be text.")
            ensure_helper = self.app.ensure_helper if self.app.config.auto_install_helper else None
            run = manager.start(
                category,
                inputs,
                action,
                ensure_helper=ensure_helper,
                gated=body.get("gated") is True,
            )
            return self._json(HTTPStatus.OK, {"run_id": run.id})
        if path == "/api/imports/risk-issues/sync":
            force = body.get("force") is True
            try:
                result = imports.run_status_sync(
                    manager.config,
                    lambda action, inputs: manager.start("risk-issues", inputs, action),
                    force=force,
                    run_status=lambda run_id: manager.view(run_id)["status"],
                    on_settled=manager.settle_status_check,
                )
            except ValueError as exc:
                raise RunError(str(exc)) from None
            return self._json(HTTPStatus.OK, result)
        if path == "/api/imports/risk-issues/milestone":
            try:
                saved = imports.set_manual_milestone(
                    self.app.config, body.get("case"), body.get("milestone"), body.get("checked")
                )
            except ValueError as exc:
                raise RunError(str(exc)) from None
            return self._json(HTTPStatus.OK, {"ok": True, "manual_milestones": saved})
        if path == "/api/imports/stakeholder-response":
            try:
                saved = stakeholder.save_response(self.app.config, body)
            except ValueError as exc:
                raise RunError(str(exc)) from None
            return self._json(HTTPStatus.OK, {"ok": True, "response": saved})
        if path == "/api/imports/case-files/open":
            try:
                used = launcher.open_case_file(
                    self.app.config,
                    body.get("case"),
                    body.get("name"),
                    body.get("with"),
                )
            except ValueError as exc:
                raise RunError(str(exc)) from None
            return self._json(HTTPStatus.OK, {"ok": True, "app": used})
        if path == "/api/imports/files/open":
            try:
                used = launcher.open_file(
                    self.app.config,
                    body.get("category"),
                    body.get("folder"),
                    body.get("name"),
                    body.get("with"),
                )
            except ValueError as exc:
                raise RunError(str(exc)) from None
            return self._json(HTTPStatus.OK, {"ok": True, "app": used})
        if path == "/api/imports/open":
            try:
                launcher.open_relative(self.app.config, str(body.get("path", "")))
            except ValueError as exc:
                raise RunError(str(exc)) from None
            return self._json(HTTPStatus.OK, {"ok": True})
        if path == "/api/helper/mcp":
            return self._json(
                HTTPStatus.OK, manager.mcp_action(str(body.get("action", "")), body.get("server"))
            )
        if path == "/api/helper/focus":
            run_id = body.get("run_id")
            if run_id is not None and not (isinstance(run_id, str) and RUN_ID.fullmatch(run_id)):
                raise RunError("Unknown run.")
            return self._json(HTTPStatus.OK, {"ok": True, "note": manager.focus(run_id)})
        match = re.fullmatch(r"/api/runs/([^/]+)/gate", path)
        if match and RUN_ID.fullmatch(match.group(1)):
            ensure_helper = self.app.ensure_helper if self.app.config.auto_install_helper else None
            result = manager.decide_gate(
                match.group(1),
                str(body.get("gate", "")),
                str(body.get("decision", "")),
                ensure_helper,
            )
            return self._json(HTTPStatus.OK, result)
        if path == "/api/history/reset":
            if body.get("confirm") != "reset-console-history":
                raise RunError('Send {"confirm": "reset-console-history"} to reset history.')
            return self._json(HTTPStatus.OK, manager.reset_history())
        if path == "/api/helper/connect":
            return self._json(HTTPStatus.OK, self.app.connect_async())
        if path == "/api/helper/probe":
            return self._json(HTTPStatus.OK, manager.probe())
        match = re.fullmatch(r"/api/runs/([^/]+)/(decide|open|stop|open-output)", path)
        if match and RUN_ID.fullmatch(match.group(1)):
            run_id, action = match.groups()
            if action == "open":
                manager.open_chat(run_id)
            elif action == "stop":
                manager.stop(run_id)
            elif action == "open-output":
                manager.open_output(run_id)
            else:
                manager.decide(run_id, str(body.get("action", "")))
            return self._json(HTTPStatus.OK, {"ok": True})
        self._error(HTTPStatus.NOT_FOUND, "Not found.")


def build_server(
    config: ConsoleConfig, *, port: int = 8765, manager_factory: Any = None
) -> ConsoleServer:
    """Create (but do not start) the console server."""

    def factory(bound_port: int) -> ConsoleApp:
        token = load_or_create_token(config.bridge_config, bound_port)
        bridge = Bridge(token)
        manager = manager_factory(config, bridge) if manager_factory else RunManager(config, bridge)
        return ConsoleApp(manager, bridge, secrets.token_urlsafe(32), bound_port, config)

    return ConsoleServer(port, factory)


def main(argv: Sequence[str] | None = None) -> int:
    args_list = list(argv) if argv is not None else []
    if args_list[:1] == ["install-helper"]:
        return install_helper(args_list[1:])
    if args_list[:1] == ["setup"]:
        return setup_profile(args_list[1:])
    parser = argparse.ArgumentParser(
        prog="wizexpert console",
        description="Local frontend for the reporting categories (127.0.0.1). The work runs in a "
        "normal VS Code agent-mode chat; see docs/CONSOLE.md. Use 'install-helper' once.",
    )
    parser.add_argument(
        "--workspace", type=Path, required=True, help="Workspace folder the chats open in."
    )
    parser.add_argument("--port", type=int, default=8765, help="Local port (0 = any free port).")
    parser.add_argument("--agent", default=None, help="Custom agent name (default WizExpert).")
    parser.add_argument(
        "--config", type=Path, default=None, help="Private JSON overrides (prompts, deny_names...)."
    )
    parser.add_argument(
        "--state-dir",
        type=Path,
        default=None,
        help="Where the console keeps its token and run index.",
    )
    parser.add_argument(
        "--copilot-home", type=Path, default=None, help="Copilot home holding session-state."
    )
    parser.add_argument(
        "--cli-fallback",
        action="store_true",
        help="Accepted for compatibility; the `code chat` fallback is on by default.",
    )
    parser.add_argument(
        "--no-cli-fallback",
        action="store_true",
        help="Never fall back to `code chat -m <agent> -r <prompt>` when the helper is down.",
    )
    parser.add_argument(
        "--code", default="code", help="VS Code command-line launcher (for --cli-fallback)."
    )
    parser.add_argument(
        "--install-helper",
        action="store_true",
        help="Install or update the local VS Code helper before starting the console.",
    )
    parser.add_argument(
        "--no-auto-helper",
        action="store_true",
        help="Do not install and reconnect the helper automatically when a run is submitted.",
    )
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args(args_list)
    if not 0 <= args.port <= 65535:
        parser.error("--port must be between 0 and 65535")
    if not args.workspace.is_dir():
        parser.error("--workspace must be an existing folder")
    config = ConsoleConfig(
        workspace=args.workspace,
        allow_cli_fallback=not args.no_cli_fallback,
        code_command=args.code,
        auto_install_helper=not args.no_auto_helper,
    )
    if args.agent:
        config.agent = args.agent
    if args.state_dir:
        config.state_dir = args.state_dir
    if args.copilot_home:
        config.copilot_home = args.copilot_home
    if args.config:
        try:
            load_overrides(config, args.config)
        except (OSError, ValueError) as error:
            parser.error(f"--config: {error}")
    if not AGENT_NAME.fullmatch(config.agent):
        parser.error(
            "the agent name may contain only letters, digits, space, dot, dash and underscore"
        )
    if args.install_helper:
        from . import helper

        helper_result = helper.install(
            Path.home() / ".wizexpert-console" / "wizexpert-console-helper.vsix", args.code
        )
        if helper_result != 0:
            parser.exit(
                helper_result,
                "Could not install the VS Code helper. "
                "Run with --no-browser after resolving the VS Code CLI issue.\n",
            )
        print(
            "VS Code helper installed. The console opens a standard VS Code window for the "
            "workspace automatically when the helper is not connected.",
            flush=True,
        )
    if not load_profile(config.state_dir)["configured"]:
        print("Not signed in (display only). Run: wizexpert console setup", flush=True)
    try:
        server = build_server(config, port=args.port)
    except OSError as error:
        parser.exit(1, f"Console could not start: {error}\n")
    url = f"http://127.0.0.1:{server.port}/"
    print(f"WizExpert Workflow Console: {url}  (Ctrl+C to stop)", flush=True)
    if not args.no_browser:
        threading.Thread(target=webbrowser.open, args=(url,), daemon=True).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


def setup_profile(argv: list[str]) -> int:
    """Save the display-only signed-in profile (name and user ID) to the console state dir."""
    parser = argparse.ArgumentParser(prog="wizexpert console setup")
    parser.add_argument("--name", default=None, help="Display name.")
    parser.add_argument("--id", dest="user_id", default=None, help="User ID.")
    parser.add_argument("--photo", type=Path, default=None, help="Optional PNG/JPEG photo.")
    parser.add_argument("--state-dir", type=Path, default=None)
    args = parser.parse_args(argv)
    name = args.name if args.name is not None else input("Display name: ")
    user_id = args.user_id if args.user_id is not None else input("User ID: ")
    state_dir = args.state_dir or default_state_dir()
    try:
        photo_bytes = None
        if args.photo is not None:
            if args.photo.stat().st_size > MAX_PHOTO_BYTES:
                raise ValueError("Photo must be at most 1 MB.")
            photo_bytes = args.photo.read_bytes()
            photo_extension(photo_bytes)
        save_profile(state_dir, name, user_id)
        if photo_bytes is not None:
            save_photo(state_dir, photo_bytes)
    except (ValueError, OSError) as error:
        print(f"Setup failed: {error}", file=sys.stderr)
        return 2
    print(f"Saved profile for {name.strip()} (display only).")
    return 0


def install_helper(argv: list[str]) -> int:
    from . import helper

    parser = argparse.ArgumentParser(prog="wizexpert console install-helper")
    parser.add_argument(
        "--out",
        type=Path,
        default=Path.home() / ".wizexpert-console" / "wizexpert-console-helper.vsix",
    )
    parser.add_argument("--code", default="code", help="VS Code command-line launcher.")
    parser.add_argument("--force", action="store_true", help="Reinstall even if up to date.")
    parser.add_argument(
        "--build-only", action="store_true", help="Only write the .vsix; do not install it."
    )
    args = parser.parse_args(argv)
    if args.build_only:
        print(helper.build_vsix(args.out))
        return 0
    code = helper.install(args.out, args.code, force=args.force)
    print(
        "Installed. The console opens a standard VS Code window for the workspace "
        "automatically when the helper is not connected."
        if code == 0
        else f"Install failed (exit {code}). Try --build-only and install the .vsix manually."
    )
    return code
