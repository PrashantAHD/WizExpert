"""Localhost-only HTTP server for the workflow console (standard library only).

Safety properties (each covered by tests):
- binds 127.0.0.1 only; the Host header must be the loopback name and port we serve;
- every /api request needs the per-process CSRF token header; POSTs also need a matching
  Origin and a JSON content type;
- strict CSP (no inline script), no caching, no framing, no referrer;
- downloads are confined to a run's recorded deliverables and sent as attachments;
- the OAuth redirect is accepted only with a single-use ``state`` issued by this process;
- request logging is disabled (the redirect URL carries an authorization code).
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
from urllib.parse import parse_qs, quote, urlsplit

from .adapters import AdapterError, load_adapters
from .mcp_client import DEFAULT_MCP_URL, McpClient, OAuthConnection, OAuthError, UrllibTransport
from .runs import RunError, RunManager

STATIC_DIR = Path(__file__).resolve().parent / "static"
STATIC_FILES = {
    "index.html": "text/html; charset=utf-8",
    "app.js": "text/javascript; charset=utf-8",
    "style.css": "text/css; charset=utf-8",
}
MAX_BODY = 2 * 1024 * 1024
RUN_ID = re.compile(r"\d{8}T\d{6}Z-[0-9a-f]{6}")
SLOT_ID = re.compile(r"[a-z0-9][a-z0-9-]{0,80}")
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
    """Shared state for one console process."""

    def __init__(
        self,
        manager: RunManager,
        oauth: OAuthConnection | None,
        csrf_token: str,
        port: int,
        wiz_url: str,
        *,
        open_browser: bool = False,
    ) -> None:
        self.manager = manager
        self.oauth = oauth
        self.csrf_token = csrf_token
        self.port = port
        self.wiz_url = wiz_url
        self.open_browser = open_browser
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
        """Dropped connections are routine; never print request details to the console."""
        return


class ConsoleHandler(BaseHTTPRequestHandler):
    server: ConsoleServer
    protocol_version = "HTTP/1.1"
    server_version = "WizExpertConsole"
    sys_version = ""

    # -- plumbing -------------------------------------------------------------------------
    def log_message(self, *_args: Any) -> None:  # never log URLs: the redirect holds a code
        return

    @property
    def app(self) -> ConsoleApp:
        return self.server.app

    def _send(
        self, status: int, body: bytes, ctype: str, extra: dict[str, str] | None = None
    ) -> None:
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

    def _json(self, status: int, value: Any) -> None:
        self._send(status, json.dumps(value).encode("utf-8"), "application/json; charset=utf-8")

    def _error(self, status: int, message: str) -> None:
        self._json(status, {"error": message})

    def _host_ok(self) -> bool:
        return self.headers.get("Host", "") in self.app.allowed_hosts

    def _csrf_ok(self) -> bool:
        sent = self.headers.get("X-CSRF-Token", "")
        return hmac.compare_digest(sent.encode(), self.app.csrf_token.encode())

    def _origin_ok(self) -> bool:
        origin = self.headers.get("Origin")
        return origin is not None and origin in self.app.allowed_origins

    def _read_json(self) -> dict[str, Any] | None:
        if not self.headers.get("Content-Type", "").lower().startswith("application/json"):
            self._error(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "JSON body required.")
            return None
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = -1
        if length < 0 or length > MAX_BODY:
            self._error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "Request body too large.")
            return None
        try:
            value = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        except (ValueError, UnicodeDecodeError):
            self._error(HTTPStatus.BAD_REQUEST, "Invalid JSON.")
            return None
        if not isinstance(value, dict):
            self._error(HTTPStatus.BAD_REQUEST, "A JSON object is required.")
            return None
        return value

    # -- verbs ------------------------------------------------------------------------------
    def do_GET(self) -> None:  # noqa: N802
        if not self._host_ok():
            return self._error(HTTPStatus.MISDIRECTED_REQUEST, "Unexpected Host header.")
        parts = urlsplit(self.path)
        path = parts.path
        if path in ("/", "/index.html"):
            return self._index()
        if path.startswith("/static/"):
            return self._static(path[len("/static/") :])
        if path == "/oauth/callback":
            return self._oauth_callback(parse_qs(parts.query))
        if path.startswith("/api/"):
            if not self._csrf_ok():
                return self._error(HTTPStatus.FORBIDDEN, "Missing or invalid CSRF token.")
            return self._api_get(path, parse_qs(parts.query))
        self._error(HTTPStatus.NOT_FOUND, "Not found.")

    do_HEAD = do_GET  # noqa: N815

    def do_POST(self) -> None:  # noqa: N802
        if not self._host_ok():
            return self._error(HTTPStatus.MISDIRECTED_REQUEST, "Unexpected Host header.")
        path = urlsplit(self.path).path
        if not path.startswith("/api/"):
            return self._error(HTTPStatus.NOT_FOUND, "Not found.")
        if not self._origin_ok():
            return self._error(HTTPStatus.FORBIDDEN, "Cross-origin request refused.")
        if not self._csrf_ok():
            return self._error(HTTPStatus.FORBIDDEN, "Missing or invalid CSRF token.")
        body = self._read_json()
        if body is None:
            return None
        try:
            return self._api_post(path, body)
        except RunError as error:
            return self._error(HTTPStatus.BAD_REQUEST, str(error))
        except OAuthError as error:
            return self._error(HTTPStatus.BAD_GATEWAY, str(error))
        except AdapterError as error:
            return self._error(HTTPStatus.BAD_REQUEST, str(error))

    def _method_not_allowed(self) -> None:
        self._error(HTTPStatus.METHOD_NOT_ALLOWED, "Method not allowed.")

    do_PUT = do_DELETE = do_PATCH = do_OPTIONS = _method_not_allowed  # noqa: N815

    # -- static ----------------------------------------------------------------------------------
    def _index(self) -> None:
        html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
        html = html.replace("__CSRF_TOKEN__", self.app.csrf_token)
        self._send(HTTPStatus.OK, html.encode("utf-8"), STATIC_FILES["index.html"])

    def _static(self, name: str) -> None:
        if name not in STATIC_FILES or name == "index.html":
            return self._error(HTTPStatus.NOT_FOUND, "Not found.")
        self._send(HTTPStatus.OK, (STATIC_DIR / name).read_bytes(), STATIC_FILES[name])

    # -- OAuth redirect --------------------------------------------------------------------------
    def _oauth_callback(self, query: dict[str, list[str]]) -> None:
        oauth = self.app.oauth
        target = "/#wiz-error"
        if oauth is not None and "error" not in query:
            code = (query.get("code") or [""])[0]
            state = (query.get("state") or [""])[0]
            try:
                oauth.complete(code, state)
                target = "/#wiz-connected"
            except Exception:  # noqa: BLE001 - never echo provider detail
                target = "/#wiz-error"
        self._send(HTTPStatus.SEE_OTHER, b"", "text/plain", {"Location": target})

    # -- API --------------------------------------------------------------------------
    def _wiz_state(self) -> dict[str, Any]:
        oauth = self.app.oauth
        return {"connected": bool(oauth and oauth.connected), "url": self.app.wiz_url}

    def _api_get(self, path: str, query: dict[str, list[str]]) -> None:
        manager = self.app.manager
        if path == "/api/bootstrap":
            return self._json(
                HTTPStatus.OK,
                {
                    "categories": manager.categories(),
                    "wiz": self._wiz_state(),
                    "history": manager.history(),
                },
            )
        match = re.fullmatch(r"/api/runs/([^/]+)", path)
        if match and RUN_ID.fullmatch(match.group(1)):
            try:
                since = max(0, int((query.get("since") or ["0"])[0]))
                return self._json(HTTPStatus.OK, manager.get(match.group(1)).view(since))
            except (RunError, ValueError):
                return self._error(HTTPStatus.NOT_FOUND, "Unknown run.")
        match = re.fullmatch(r"/api/runs/([^/]+)/download/([^/]+)", path)
        if match and RUN_ID.fullmatch(match.group(1)) and SLOT_ID.fullmatch(match.group(2)):
            try:
                file = manager.output_file(match.group(1), match.group(2))
                data = file.read_bytes()
            except (RunError, OSError):
                return self._error(HTTPStatus.NOT_FOUND, "Unknown deliverable.")
            disposition = f"attachment; filename*=UTF-8''{quote(file.name)}"
            return self._send(
                HTTPStatus.OK,
                data,
                "application/octet-stream",
                {"Content-Disposition": disposition},
            )
        self._error(HTTPStatus.NOT_FOUND, "Not found.")

    def _api_post(self, path: str, body: dict[str, Any]) -> None:
        app = self.app
        manager = app.manager
        if path == "/api/wiz/connect":
            if app.oauth is None:
                raise RunError("Wiz sign-in is not configured.")
            url = app.oauth.begin()
            if app.open_browser:
                threading.Thread(target=webbrowser.open, args=(url,), daemon=True).start()
            return self._json(HTTPStatus.OK, {"authorize_url": url})
        if path == "/api/wiz/disconnect":
            if app.oauth is not None:
                app.oauth.disconnect()
            return self._json(HTTPStatus.OK, self._wiz_state())
        if path == "/api/runs":
            category = body.get("category_id")
            inputs = body.get("inputs", {})
            if not isinstance(category, str) or not isinstance(inputs, dict):
                raise RunError("category_id and inputs are required.")
            run = manager.create(
                category,
                inputs,
                dry_run=body.get("dry_run") is True,
                preparer=str(body.get("preparer", "")),
            )
            return self._json(HTTPStatus.OK, {"run_id": run.id})
        match = re.fullmatch(r"/api/runs/([^/]+)/(fields|approve|reject|cancel)", path)
        if match and RUN_ID.fullmatch(match.group(1)):
            run_id, action = match.groups()
            if action == "fields":
                values = body.get("fields", {})
                if not isinstance(values, dict):
                    raise RunError("fields must be an object.")
                manager.submit_fields(run_id, values)
            elif action == "approve":
                manager.approve(run_id, body.get("reviewer"), confirm=body.get("confirm") is True)
            elif action == "reject":
                manager.reject(run_id, body.get("reviewer"), str(body.get("reason", "")))
            else:
                manager.cancel(run_id)
            return self._json(HTTPStatus.OK, manager.get(run_id).view())
        self._error(HTTPStatus.NOT_FOUND, "Not found.")


def build_server(
    private_root: Path,
    *,
    port: int = 8765,
    wiz_url: str = DEFAULT_MCP_URL,
    client_id: str | None = None,
    window_minutes: int | None = None,
    open_browser: bool = False,
    transport: UrllibTransport | None = None,
    adapters: dict[str, Any] | None = None,
) -> ConsoleServer:
    """Create (but do not start) the console server for ``private_root``."""
    private_root = Path(private_root).resolve()
    adapters = adapters if adapters is not None else load_adapters(private_root)
    deliverables = private_root / "deliverables"
    deliverables.mkdir(parents=True, exist_ok=True)

    def factory(bound_port: int) -> ConsoleApp:
        redirect = f"http://127.0.0.1:{bound_port}/oauth/callback"
        oauth = OAuthConnection(wiz_url, redirect, transport, client_id=client_id)
        client = McpClient(oauth, transport)
        manager = RunManager(
            adapters,
            deliverables,
            client,
            window_override_seconds=None if window_minutes is None else window_minutes * 60,
            connected=lambda: oauth.connected,
        )
        return ConsoleApp(
            manager,
            oauth,
            secrets.token_urlsafe(32),
            bound_port,
            wiz_url,
            open_browser=open_browser,
        )

    return ConsoleServer(port, factory)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="wizexpert console", description="Local click-driven workflow console (127.0.0.1)."
    )
    parser.add_argument(
        "--private-root",
        type=Path,
        required=True,
        help="Private workspace holding deliverables/ and the adapters.",
    )
    parser.add_argument("--port", type=int, default=8765, help="Local port (0 = any free port).")
    parser.add_argument("--wiz-url", default=DEFAULT_MCP_URL, help="Remote Wiz MCP server URL.")
    parser.add_argument(
        "--client-id",
        default=None,
        help="Pre-registered OAuth client ID (when dynamic registration is off).",
    )
    parser.add_argument(
        "--observation-window-minutes",
        type=int,
        default=None,
        help="Override the collection observation window (0 disables).",
    )
    parser.add_argument("--no-browser", action="store_true", help="Do not open the browser.")
    args = parser.parse_args(list(argv) if argv is not None else None)
    if not 0 <= args.port <= 65535:
        parser.error("--port must be between 0 and 65535")
    try:
        server = build_server(
            args.private_root,
            port=args.port,
            wiz_url=args.wiz_url,
            client_id=args.client_id,
            window_minutes=args.observation_window_minutes,
            open_browser=not args.no_browser,
        )
    except (AdapterError, OSError) as error:
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
