"""Synthetic fakes for the console tests: a fake MCP+OAuth server and a fake adapter."""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from wizexpert.console.adapters import Field
from wizexpert.governance.categories import CATEGORIES
from wizexpert.governance.category_pipeline import SlotBinding


class FakeMcpServer:
    """Loopback MCP server with OAuth metadata, dynamic registration, PKCE and tools."""

    def __init__(self, *, sse: bool = False) -> None:
        self.sse = sse
        self.tokens: set[str] = set()
        self.refresh: dict[str, str] = {}
        self.codes: dict[str, dict[str, str]] = {}
        self.clients: set[str] = set()
        self.calls: list[tuple[str, dict[str, Any]]] = []  # (mcp tool, arguments)
        self.pkce_checked = 0
        self.expires_in = 3600
        self.tool_result: Any = lambda tool, params: {"echo": tool, "parameters": params}
        self.tool_error: str | None = None
        self.require_auth = True
        outer = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *_a: Any) -> None:
                return

            def _send(
                self,
                status: int,
                body: bytes,
                ctype: str = "application/json",
                headers: dict[str, str] | None = None,
            ) -> None:
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                for k, v in (headers or {}).items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(body)

            def _body(self) -> bytes:
                return self.rfile.read(int(self.headers.get("Content-Length", "0")))

            def do_GET(self) -> None:  # noqa: N802
                base = outer.base
                if self.path.startswith("/.well-known/oauth-protected-resource"):
                    doc = {"resource": base + "/mcp", "authorization_servers": [base]}
                elif self.path.startswith("/.well-known/oauth-authorization-server"):
                    doc = {
                        "issuer": base,
                        "authorization_endpoint": base + "/authorize",
                        "token_endpoint": base + "/token",
                        "registration_endpoint": base + "/register",
                        "code_challenge_methods_supported": ["S256"],
                    }
                else:
                    return self._send(404, b"{}")
                self._send(200, json.dumps(doc).encode())

            def do_POST(self) -> None:  # noqa: N802
                body = self._body()
                if self.path == "/register":
                    client = "client-" + secrets.token_hex(4)
                    outer.clients.add(client)
                    return self._send(201, json.dumps({"client_id": client}).encode())
                if self.path == "/token":
                    return self._token(urllib.parse.parse_qs(body.decode()))
                if self.path == "/mcp":
                    return self._mcp(json.loads(body.decode() or "{}"))
                self._send(404, b"{}")

            def _token(self, form: dict[str, list[str]]) -> None:
                grant = form["grant_type"][0]
                if grant == "authorization_code":
                    record = outer.codes.pop(form["code"][0], None)
                    verifier = form["code_verifier"][0]
                    digest = hashlib.sha256(verifier.encode()).digest()
                    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
                    if record is None or record["challenge"] != challenge:
                        return self._send(400, b'{"error":"invalid_grant"}')
                    outer.pkce_checked += 1
                elif grant == "refresh_token":
                    if form["refresh_token"][0] not in outer.refresh:
                        return self._send(400, b'{"error":"invalid_grant"}')
                else:
                    return self._send(400, b"{}")
                access = "at-" + secrets.token_hex(8)
                refresh = "rt-" + secrets.token_hex(8)
                outer.tokens.add(access)
                outer.refresh[refresh] = access
                doc = {
                    "access_token": access,
                    "refresh_token": refresh,
                    "expires_in": outer.expires_in,
                    "token_type": "Bearer",
                }
                self._send(200, json.dumps(doc).encode())

            def _mcp(self, message: dict[str, Any]) -> None:
                auth = self.headers.get("Authorization", "")
                if outer.require_auth and auth.removeprefix("Bearer ") not in outer.tokens:
                    meta = f"{outer.base}/.well-known/oauth-protected-resource"
                    challenge = "Bear" + 'er resource_metadata="' + meta + '"'
                    return self._send(401, b"{}", headers={"WWW-Authenticate": challenge})
                method, ident = message.get("method"), message.get("id")
                if ident is None:
                    return self._send(202, b"")
                params = message.get("params", {})
                if method == "initialize":
                    result: Any = {
                        "protocolVersion": "2025-06-18",
                        "capabilities": {},
                        "serverInfo": {"name": "fake"},
                    }
                    extra = {"Mcp-Session-Id": "sess-1"}
                elif method == "tools/list":
                    result = {"tools": [{"name": "discover"}, {"name": "execute"}]}
                    extra = {}
                elif method == "tools/call":
                    outer.calls.append((params["name"], params.get("arguments", {})))
                    if outer.tool_error:
                        result = {
                            "isError": True,
                            "content": [{"type": "text", "text": outer.tool_error}],
                        }
                    else:
                        args = params.get("arguments", {})
                        value = outer.tool_result(
                            args.get("tool_name", params["name"]), args.get("parameters", {})
                        )
                        result = {"content": [{"type": "text", "text": json.dumps(value)}]}
                    extra = {}
                else:
                    result, extra = {}, {}
                payload = json.dumps({"jsonrpc": "2.0", "id": ident, "result": result})
                if outer.sse:
                    body = f"event: message\ndata: {payload}\n\n".encode()
                    return self._send(200, body, "text/event-stream", extra)
                self._send(200, payload.encode(), headers=extra)

        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.base = f"http://127.0.0.1:{self._httpd.server_address[1]}"
        self.url = self.base + "/mcp"
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()

    def approve(self, authorize_url: str) -> tuple[str, str]:
        """Play the user's browser: validate the request and return (code, state)."""
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(authorize_url).query)
        assert query["response_type"] == ["code"]
        assert query["code_challenge_method"] == ["S256"]
        assert query["client_id"][0] in self.clients
        code = "code-" + secrets.token_hex(6)
        self.codes[code] = {"challenge": query["code_challenge"][0]}
        return code, query["state"][0]

    def revoke_all(self) -> None:
        self.tokens.clear()

    def close(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()


# ---- fake adapter ---------------------------------------------------------------------------

SLOT_HASH = "a" * 64


class FakeAdapter:
    """Implements the adapter contract for the daily category with synthetic content."""

    category_id = "daily-progress-reporting"
    title = "Fake Category"
    description = "Synthetic adapter for tests."
    qa_workflow = None
    observation_window_seconds: int | None = None

    def __init__(
        self,
        root: Path,
        *,
        counts_ok: bool = True,
        validator_ok: bool = True,
        calls: list[tuple[str, dict[str, Any]]] | None = None,
    ) -> None:
        self.root = Path(root)
        self.counts_ok = counts_ok
        self.validator_ok = validator_ok
        self.calls = calls or [("list_things", {"first": 1})]
        self.client: Any = None
        self.last_qa: dict[str, Any] | None = None
        self.out_override: Path | None = None
        self.collect_hook: Any = None
        self.generate_error: Exception | None = None
        self.no_fields = False

    def start_fields(self) -> list[Field]:
        return [Field("subject", "Subject", required=True)]

    def validate_inputs(self, raw: Any) -> dict[str, Any]:
        return dict(raw)

    def supports_dry_run(self) -> bool:
        return True

    def output_dir(self, inputs: Any) -> Path:
        return self.out_override or (self.root / "case-folder")

    def replay_client(self, inputs: Any) -> Any:
        return self.client or _EchoClient()

    def collect(self, ctx: Any) -> dict[str, Any]:
        if self.collect_hook:
            self.collect_hook(ctx)
        for tool, params in self.calls:
            ctx.call(tool, params)
        ctx.save_evidence("page-01.json", {"ok": True})
        expected, got = (3, 3) if self.counts_ok else (3, 2)
        return {
            "no_prior_evidence_reason": "synthetic",
            "counts": [{"name": "things", "expected": expected, "collected": got}],
        }

    def narrative_fields(self, ctx: Any) -> list[Field]:
        if self.no_fields:
            return []
        return [
            Field("summary", "Summary", kind="textarea", required=True),
            Field("rows", "Rows", kind="list", item_keys=("a", "b")),
        ]

    def prefill(self, ctx: Any) -> dict[str, Any]:
        return {"summary": "pre-filled"}

    def reference(self, ctx: Any) -> list[dict[str, str]]:
        return [{"title": "Ref <b>", "text": "<script>alert(1)</script>"}]

    def _paths(self, ctx: Any) -> dict[str, Path]:
        return {
            s.slot_id: ctx.output_dir / f"{s.slot_id}.out"
            for s in CATEGORIES[self.category_id].slots
        }

    def expected_outputs(self, ctx: Any, fields: Any) -> list[Path]:
        return list(self._paths(ctx).values())

    def generate(self, ctx: Any, fields: Any) -> dict[str, Path]:
        if self.generate_error:
            raise self.generate_error
        paths = self._paths(ctx)
        for slot, path in paths.items():
            path.write_text(f"{slot}:{fields.get('summary', '')}", encoding="utf-8")
        return paths

    def bindings(self, ctx: Any, outputs: Any) -> dict[str, SlotBinding]:
        def validator(path: Path) -> list[str]:
            return [] if self.validator_ok and path.is_file() else ["synthetic validator failure"]

        return {
            slot: SlotBinding(SLOT_HASH, lambda _out, p=outputs[slot]: p, validator)
            for slot in outputs
        }

    def extra_checks(self, ctx: Any, outputs: Any) -> list[str]:
        return []

    def qa_extras(self, ctx: Any) -> dict[str, Any]:
        return {}


class _EchoClient:
    def execute(self, tool_name: str, parameters: dict[str, Any]) -> Any:
        return {"tool": tool_name}

    def discover(self, domain: str | None = None) -> Any:
        return {}
