"""Read-only MCP client (streamable HTTP) with OAuth 2.1 authorization-code + PKCE.

Standard library only. The user signs in with their own browser; the console receives the
redirect on its localhost callback. Tokens live in memory only: they are never written to
disk, logs, evidence or outputs, and ``repr`` of every object that holds them is redacted.

Discovery follows the MCP authorization specification: a 401 challenge or the well-known
protected-resource metadata (RFC 9728) names the authorization server, whose metadata
(RFC 8414 / OIDC) gives the endpoints; a public client is registered dynamically
(RFC 7591) when the server offers it. Only the MCP tools ``discover`` and ``execute`` are
ever called, and ``execute`` only for read-only operations (see ``policy``).
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import json
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from .context import McpCallError, ReconnectRequired
from .policy import check_discover, check_execute, check_mcp_tool

DEFAULT_MCP_URL = "https://mcp.app.wiz.io"
PROTOCOL_VERSION = "2025-06-18"
MAX_BODY = 32 * 1024 * 1024
AUTH_MARKERS = ("401", "unauthorized", "invalid_token", "www-authenticate", "oauth")
PENDING_SECONDS = 600
CLIENT_NAME = "WizExpert Workflow Console"
# OAuth public client: no client secret is used or stored.
PUBLIC_CLIENT = "none"
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


class OAuthError(Exception):
    """Sign-in could not be completed (message is safe to show)."""


@dataclass
class HttpResponse:
    status: int
    headers: dict[str, str]
    body: bytes


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


class UrllibTransport:
    """HTTPS-only transport (plain HTTP only to loopback, for local test servers)."""

    def __init__(self, *, allow_loopback_http: bool = False, timeout: float = 120.0) -> None:
        self._allow_loopback_http = allow_loopback_http
        self._timeout = timeout
        self._opener = urllib.request.build_opener(_NoRedirect)

    def check_url(self, url: str) -> None:
        parts = urllib.parse.urlsplit(url)
        if parts.scheme == "https" and parts.hostname:
            return
        if (
            parts.scheme == "http"
            and self._allow_loopback_http
            and parts.hostname in LOOPBACK_HOSTS
        ):
            return
        raise OAuthError("Only https URLs are allowed for Wiz sign-in and MCP traffic.")

    def request(
        self, method: str, url: str, headers: dict[str, str], body: bytes | None
    ) -> HttpResponse:
        self.check_url(url)
        request = urllib.request.Request(url, data=body, method=method, headers=headers)  # noqa: S310
        try:
            with self._opener.open(request, timeout=self._timeout) as response:  # nosec B310
                return HttpResponse(
                    response.status,
                    {k.lower(): v for k, v in response.headers.items()},
                    response.read(MAX_BODY),
                )
        except urllib.error.HTTPError as error:
            return HttpResponse(
                error.code, {k.lower(): v for k, v in error.headers.items()}, error.read(MAX_BODY)
            )
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise McpCallError(f"Network error: {type(error).__name__}") from None


def pkce_pair() -> tuple[str, str]:
    """(code_verifier, S256 code_challenge) per RFC 7636."""
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return verifier, base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


@dataclass
class _Tokens:
    access: str = ""
    refresh: str = ""
    expires_at: float = 0.0

    def __repr__(self) -> str:
        return "<tokens redacted>"


@dataclass
class _Pending:
    verifier: str
    created: float
    meta: dict[str, Any] = field(repr=False, default_factory=dict)


class OAuthConnection:
    """OAuth 2.1 public-client session for one MCP server (in-memory only)."""

    def __init__(
        self,
        server_url: str,
        redirect_uri: str,
        transport: UrllibTransport | None = None,
        *,
        client_id: str | None = None,
        clock: Any = time.time,
    ) -> None:
        self.server_url = server_url.rstrip("/")
        self.redirect_uri = redirect_uri
        self._transport = transport or UrllibTransport()
        self._client_id = client_id
        self._clock = clock
        self._tokens = _Tokens()
        self._pending: dict[str, _Pending] = {}
        self._lock = threading.Lock()
        self._metadata: dict[str, Any] | None = None

    def __repr__(self) -> str:
        return f"<OAuthConnection connected={self.connected}>"

    # -- state -------------------------------------------------------------------
    @property
    def connected(self) -> bool:
        with self._lock:
            t = self._tokens
            return bool(t.access) and (
                t.expires_at == 0 or t.expires_at > self._clock() or bool(t.refresh)
            )

    def disconnect(self) -> None:
        with self._lock:
            self._tokens = _Tokens()
            self._pending.clear()

    def mark_unauthorized(self) -> None:
        """The server rejected the token: drop the access token, keep nothing usable."""
        with self._lock:
            self._tokens = _Tokens()

    def bearer(self) -> str:
        """A currently valid access token (refreshing early if needed) or ReconnectRequired."""
        with self._lock:
            t = self._tokens
            if not t.access:
                raise ReconnectRequired("Wiz is not connected.")
            fresh = t.expires_at == 0 or t.expires_at - 60 > self._clock()
            refresh = t.refresh
        if fresh:
            return t.access
        if not refresh:
            self.mark_unauthorized()
            raise ReconnectRequired("The Wiz sign-in expired.")
        self._refresh(refresh)
        with self._lock:
            return self._tokens.access

    # -- discovery -----------------------------------------------------------------
    def _get_json(self, url: str) -> dict[str, Any] | None:
        try:
            response = self._transport.request("GET", url, {"Accept": "application/json"}, None)
        except McpCallError:
            return None
        if response.status != 200:
            return None
        try:
            value = json.loads(response.body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return None
        return value if isinstance(value, dict) else None

    def discover(self) -> dict[str, Any]:
        if self._metadata is not None:
            return self._metadata
        server = urllib.parse.urlsplit(self.server_url)
        origin = f"{server.scheme}://{server.netloc}"
        candidates: list[str] = []
        probe = self._transport.request(
            "POST",
            self.server_url,
            {
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
            },
            json.dumps({"jsonrpc": "2.0", "id": 0, "method": "ping"}).encode(),
        )
        challenge = probe.headers.get("www-authenticate", "")
        marker = 'resource_metadata="'
        if marker in challenge:
            candidates.append(challenge.split(marker, 1)[1].split('"', 1)[0])
        path = server.path.rstrip("/")
        if path:
            candidates.append(f"{origin}/.well-known/oauth-protected-resource{path}")
        candidates.append(f"{origin}/.well-known/oauth-protected-resource")
        resource: dict[str, Any] = {}
        for url in candidates:
            try:
                self._transport.check_url(url)
            except OAuthError:
                continue
            found = self._get_json(url)
            if found:
                resource = found
                break
        servers = resource.get("authorization_servers")
        issuer = servers[0] if isinstance(servers, list) and servers else origin
        if not isinstance(issuer, str):
            raise OAuthError("The MCP server advertised an invalid authorization server.")
        auth = urllib.parse.urlsplit(issuer)
        base = f"{auth.scheme}://{auth.netloc}"
        suffix = auth.path.rstrip("/")
        meta = None
        for url in (
            f"{base}/.well-known/oauth-authorization-server{suffix}",
            f"{base}{suffix}/.well-known/openid-configuration",
            f"{base}/.well-known/openid-configuration",
        ):
            try:
                self._transport.check_url(url)
            except OAuthError:
                continue
            meta = self._get_json(url)
            if meta:
                break
        if not meta:
            raise OAuthError("Could not read the authorization server metadata.")
        for key in ("authorization_endpoint", "token_endpoint"):
            value = meta.get(key)
            if not isinstance(value, str):
                raise OAuthError(f"Authorization server metadata lacks {key}.")
            self._transport.check_url(value)
        methods = meta.get("code_challenge_methods_supported")
        if isinstance(methods, list) and "S256" not in methods:
            raise OAuthError("The authorization server does not support PKCE S256.")
        scopes = resource.get("scopes_supported")
        meta["_scope"] = " ".join(scopes) if isinstance(scopes, list) else ""
        self._metadata = meta
        return meta

    def _register_client(self, meta: dict[str, Any]) -> str:
        if self._client_id:
            return self._client_id
        endpoint = meta.get("registration_endpoint")
        if not isinstance(endpoint, str):
            raise OAuthError(
                "The server offers no dynamic client registration; "
                "start the console with --client-id."
            )
        self._transport.check_url(endpoint)
        payload = {
            "client_name": CLIENT_NAME,
            "redirect_uris": [self.redirect_uri],
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": PUBLIC_CLIENT,
        }
        if meta.get("_scope"):
            payload["scope"] = meta["_scope"]
        response = self._transport.request(
            "POST",
            endpoint,
            {"Content-Type": "application/json", "Accept": "application/json"},
            json.dumps(payload).encode(),
        )
        try:
            registered = json.loads(response.body.decode("utf-8"))
            client_id = registered["client_id"]
        except (ValueError, KeyError, TypeError, UnicodeDecodeError):
            raise OAuthError("Dynamic client registration failed.") from None
        if response.status not in (200, 201) or not isinstance(client_id, str) or not client_id:
            raise OAuthError("Dynamic client registration was refused.")
        self._client_id = client_id
        return client_id

    # -- authorization-code + PKCE ----------------------------------------------------
    def begin(self) -> str:
        """Return the URL the user opens in their own browser to sign in."""
        meta = self.discover()
        client_id = self._register_client(meta)
        verifier, challenge = pkce_pair()
        state = secrets.token_urlsafe(32)
        with self._lock:
            now = self._clock()
            self._pending = {
                k: v for k, v in self._pending.items() if now - v.created < PENDING_SECONDS
            }
            self._pending[state] = _Pending(verifier, now)
        query = {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": self.redirect_uri,
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "resource": self.server_url,
        }
        if meta.get("_scope"):
            query["scope"] = meta["_scope"]
        return (
            meta["authorization_endpoint"]
            + ("&" if "?" in meta["authorization_endpoint"] else "?")
            + urllib.parse.urlencode(query)
        )

    def complete(self, code: str, state: str) -> None:
        """Exchange the redirect's code for tokens (state is single-use and time-limited)."""
        with self._lock:
            pending = self._pending.pop(state, None)
        if pending is None or self._clock() - pending.created > PENDING_SECONDS:
            raise OAuthError("Unknown or expired sign-in attempt. Start again.")
        if not code or len(code) > 4096:
            raise OAuthError("Missing authorization code.")
        meta = self.discover()
        self._token_request(
            meta,
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self.redirect_uri,
                "client_id": self._client_id or "",
                "code_verifier": pending.verifier,
                "resource": self.server_url,
            },
        )

    def _refresh(self, refresh_token: str) -> None:
        meta = self.discover()
        try:
            self._token_request(
                meta,
                {
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "client_id": self._client_id or "",
                    "resource": self.server_url,
                },
            )
        except OAuthError:
            self.mark_unauthorized()
            raise ReconnectRequired("The Wiz sign-in expired.") from None

    def _token_request(self, meta: dict[str, Any], form: dict[str, str]) -> None:
        response = self._transport.request(
            "POST",
            meta["token_endpoint"],
            {"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
            urllib.parse.urlencode(form).encode(),
        )
        try:
            data = json.loads(response.body.decode("utf-8"))
            access = data["access_token"]
        except (ValueError, KeyError, TypeError, UnicodeDecodeError):
            raise OAuthError("The token request was refused.") from None
        if response.status != 200 or not isinstance(access, str) or not access:
            raise OAuthError("The token request was refused.")
        lifetime = data.get("expires_in")
        expires = self._clock() + float(lifetime) if isinstance(lifetime, int | float) else 0.0
        refresh = data.get("refresh_token") if isinstance(data.get("refresh_token"), str) else ""
        with self._lock:
            self._tokens = _Tokens(access, refresh or self._tokens.refresh, expires)


class McpClient:
    """JSON-RPC over streamable HTTP; exposes only ``execute`` and ``discover``."""

    def __init__(self, oauth: OAuthConnection, transport: UrllibTransport | None = None) -> None:
        self._oauth = oauth
        self._transport = transport or oauth._transport  # noqa: SLF001
        self._url = oauth.server_url
        self._session = ""
        self._ready = False
        self._ids = iter(range(1, 1 << 30))
        self._lock = threading.Lock()

    def __repr__(self) -> str:
        return f"<McpClient {self._url}>"

    @property
    def connected(self) -> bool:
        return self._oauth.connected

    # -- public, read-only surface ---------------------------------------------------
    def execute(self, tool_name: str, parameters: dict[str, Any] | None = None) -> Any:
        parameters = parameters or {}
        check_execute(tool_name, parameters)
        return self._call_tool("execute", {"tool_name": tool_name, "parameters": parameters})

    def discover(self, domain: str | None = None) -> Any:
        check_discover(domain)
        return self._call_tool("discover", {"domain": domain} if domain else {})

    # -- internals ---------------------------------------------------------------------
    def _call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        check_mcp_tool(name)
        self._ensure_ready()
        result = self._rpc("tools/call", {"name": name, "arguments": arguments})
        return self._unwrap(result)

    def _ensure_ready(self) -> None:
        with self._lock:
            if self._ready:
                return
            self._session = ""
            init = self._rpc(
                "initialize",
                {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "wizexpert-console", "version": "1"},
                },
                ready_check=False,
            )
            if not isinstance(init, dict):
                raise McpCallError("MCP initialize failed.")
            self._post(
                {"jsonrpc": "2.0", "method": "notifications/initialized"}, expect_reply=False
            )
            listed = self._rpc("tools/list", {}, ready_check=False)
            names = {t.get("name") for t in listed.get("tools", []) if isinstance(t, dict)}
            if not {"discover", "execute"} <= names:
                raise McpCallError("The MCP server does not offer the discover/execute tools.")
            self._ready = True

    def _headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": PROTOCOL_VERSION,
            "Authorization": "Bearer " + self._oauth.bearer(),
        }
        if self._session:
            headers["Mcp-Session-Id"] = self._session
        return headers

    def _post(self, message: dict[str, Any], *, expect_reply: bool = True) -> HttpResponse:
        response = self._transport.request(
            "POST", self._url, self._headers(), json.dumps(message).encode("utf-8")
        )
        if response.status == 401:
            self._oauth.mark_unauthorized()
            self._ready = False
            raise ReconnectRequired("Wiz asked to reconnect (401 / OAuth challenge).")
        if response.status == 404 and self._session:
            self._ready = False
            self._session = ""
            raise McpCallError("The MCP session expired; retry.")
        if response.status >= 400:
            raise McpCallError(f"MCP server returned HTTP {response.status}.")
        sid = response.headers.get("mcp-session-id")
        if sid:
            self._session = sid
        return response

    def _rpc(self, method: str, params: dict[str, Any], *, ready_check: bool = True) -> Any:
        ident = next(self._ids)
        response = self._post({"jsonrpc": "2.0", "id": ident, "method": method, "params": params})
        message = _pick_message(response, ident)
        if "error" in message:
            text = json.dumps(message["error"])[:300]
            if any(marker in text.lower() for marker in AUTH_MARKERS):
                self._oauth.mark_unauthorized()
                raise ReconnectRequired("Wiz asked to reconnect (OAuth challenge).")
            raise McpCallError("MCP error: " + text)
        return message.get("result")

    def _unwrap(self, result: Any) -> Any:
        if not isinstance(result, dict):
            raise McpCallError("Unexpected MCP result.")
        text = "".join(
            c.get("text", "")
            for c in result.get("content", [])
            if isinstance(c, dict) and c.get("type") == "text"
        )
        if result.get("isError"):
            lowered = text.lower()
            if any(marker in lowered for marker in AUTH_MARKERS):
                self._oauth.mark_unauthorized()
                raise ReconnectRequired("Wiz asked to reconnect (OAuth challenge).")
            raise McpCallError("Wiz tool error: " + text[:300])
        structured = result.get("structuredContent")
        if isinstance(structured, dict):
            return structured
        try:
            return json.loads(text)
        except ValueError:
            return {"text": text}


def _pick_message(response: HttpResponse, ident: int) -> dict[str, Any]:
    ctype = response.headers.get("content-type", "")
    body = response.body.decode("utf-8", "replace")
    messages: list[Any] = []
    if "text/event-stream" in ctype:
        for block in body.replace("\r\n", "\n").split("\n\n"):
            data = "\n".join(
                line[5:].lstrip() for line in block.split("\n") if line.startswith("data:")
            )
            if data:
                try:
                    messages.append(json.loads(data))
                except ValueError:
                    continue
    else:
        with contextlib.suppress(ValueError):
            messages.append(json.loads(body))
    for message in messages:
        if isinstance(message, dict) and message.get("id") == ident:
            return message
    raise McpCallError("The MCP server returned no matching response.")
