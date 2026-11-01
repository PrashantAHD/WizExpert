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
import hmac
import json
import re
import secrets
import threading
import webbrowser
from collections.abc import Sequence
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

from .bridge import Bridge, load_or_create_token
from .config import ConsoleConfig, load_overrides
from .runs import RunError, RunManager

STATIC_DIR = Path(__file__).resolve().parent / "static"
STATIC_FILES = {
    "index.html": "text/html; charset=utf-8",
    "app.js": "text/javascript; charset=utf-8",
    "style.css": "text/css; charset=utf-8",
}
MAX_BODY = 256 * 1024
RUN_ID = re.compile(r"\d{8}T\d{6}Z-[0-9a-f]{6}")
AGENT_NAME = re.compile(r"[A-Za-z0-9 ._-]{1,60}")
CSP = (
    "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; "
    "img-src 'self' data:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
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


class ConsoleApp:
    def __init__(self, manager: RunManager, bridge: Bridge, csrf_token: str, port: int) -> None:
        self.manager = manager
        self.bridge = bridge
        self.csrf_token = csrf_token
        self.port = port
        self.allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
        self.allowed_origins = {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}


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
        if path in ("/", "/index.html"):
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
        body = self._json_body()
        if body is None:
            return None
        try:
            return self._api_post(path, body)
        except RunError as error:
            return self._error(HTTPStatus.BAD_REQUEST, str(error))

    def _method_not_allowed(self) -> None:
        self._error(HTTPStatus.METHOD_NOT_ALLOWED, "Method not allowed.")

    do_PUT = do_DELETE = do_PATCH = do_OPTIONS = _method_not_allowed  # noqa: N815

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
        except (ValueError, TypeError):
            return self._error(HTTPStatus.BAD_REQUEST, "Bad query.")
        self._signed_json(nonce, bridge.poll(after, instance or "x", folders))

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
                },
            )
        match = re.fullmatch(r"/api/runs/([^/]+)", path)
        if match and RUN_ID.fullmatch(match.group(1)):
            try:
                since = max(0, int((query.get("since") or ["0"])[0]))
                return self._json(HTTPStatus.OK, manager.view(match.group(1), since))
            except (RunError, ValueError):
                return self._error(HTTPStatus.NOT_FOUND, "Unknown run.")
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
            run = manager.start(category, inputs, action)
            return self._json(HTTPStatus.OK, {"run_id": run.id})
        if path == "/api/helper/probe":
            return self._json(HTTPStatus.OK, manager.probe())
        match = re.fullmatch(r"/api/runs/([^/]+)/(decide|open)", path)
        if match and RUN_ID.fullmatch(match.group(1)):
            run_id, action = match.groups()
            if action == "open":
                manager.open_chat(run_id)
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
        return ConsoleApp(manager, bridge, secrets.token_urlsafe(32), bound_port)

    return ConsoleServer(port, factory)


def main(argv: Sequence[str] | None = None) -> int:
    args_list = list(argv) if argv is not None else []
    if args_list[:1] == ["install-helper"]:
        return install_helper(args_list[1:])
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
        help="If the helper cannot start the chat, try `code chat -m <agent> -r <prompt>`.",
    )
    parser.add_argument(
        "--code", default="code", help="VS Code command-line launcher (for --cli-fallback)."
    )
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args(args_list)
    if not 0 <= args.port <= 65535:
        parser.error("--port must be between 0 and 65535")
    if not args.workspace.is_dir():
        parser.error("--workspace must be an existing folder")
    config = ConsoleConfig(
        workspace=args.workspace, allow_cli_fallback=args.cli_fallback, code_command=args.code
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


def install_helper(argv: list[str]) -> int:
    from . import helper

    parser = argparse.ArgumentParser(prog="wizexpert console install-helper")
    parser.add_argument(
        "--out",
        type=Path,
        default=Path.home() / ".wizexpert-console" / "wizexpert-console-helper.vsix",
    )
    parser.add_argument("--code", default="code", help="VS Code command-line launcher.")
    parser.add_argument(
        "--build-only", action="store_true", help="Only write the .vsix; do not install it."
    )
    args = parser.parse_args(argv)
    if args.build_only:
        print(helper.build_vsix(args.out))
        return 0
    code = helper.install(args.out, args.code)
    print(
        "Installed. Reload the VS Code window (Developer: Reload Window) to activate it."
        if code == 0
        else f"Install failed (exit {code}). Try --build-only and install the .vsix manually."
    )
    return code
