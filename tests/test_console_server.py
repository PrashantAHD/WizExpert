"""Server security tests: loopback bind, Host/Origin/CSRF checks, headers, confinement."""

from __future__ import annotations

import http.client
import json
import re
import threading

import pytest
from console_fakes import FakeAdapter, FakeMcpServer

from wizexpert.console.mcp_client import UrllibTransport
from wizexpert.console.server import build_server


@pytest.fixture
def console(tmp_path):
    fake_mcp = FakeMcpServer()
    adapter = FakeAdapter(tmp_path / "deliverables")
    server = build_server(
        tmp_path,
        port=0,
        wiz_url=fake_mcp.url,
        transport=UrllibTransport(allow_loopback_http=True, timeout=5),
        adapters={adapter.category_id: adapter},
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server, adapter, fake_mcp
    server.shutdown()
    server.server_close()
    fake_mcp.close()


def request(server, method, path, *, headers=None, body=None, host=None):
    conn = http.client.HTTPConnection("127.0.0.1", server.port, timeout=5)
    sent = dict(headers or {})
    conn.putrequest(method, path, skip_host=True)
    conn.putheader("Host", f"127.0.0.1:{server.port}" if host is None else host)
    for key, value in sent.items():
        conn.putheader(key, value)
    data = (
        body
        if isinstance(body, bytes)
        else (json.dumps(body).encode() if body is not None else None)
    )
    if data is not None:
        conn.putheader("Content-Length", str(len(data)))
    conn.endheaders(data)
    response = conn.getresponse()
    payload = response.read()
    result = (response.status, dict(response.getheaders()), payload)
    conn.close()
    return result


def token_of(server):
    status, _h, body = request(server, "GET", "/")
    assert status == 200
    return re.search(rb'name="csrf-token" content="([^"]+)"', body).group(1).decode()


def post_headers(server, token, **extra):
    return {
        "X-CSRF-Token": token,
        "Content-Type": "application/json",
        "Origin": f"http://127.0.0.1:{server.port}",
        **extra,
    }


def test_binds_loopback_only(console):
    server, *_ = console
    assert server.server_address[0] == "127.0.0.1"


def test_index_serves_token_and_strict_headers(console):
    server, *_ = console
    status, headers, body = request(server, "GET", "/")
    assert status == 200 and b"__CSRF_TOKEN__" not in body
    assert "script-src 'self'" in headers["Content-Security-Policy"]
    assert "'unsafe-inline'" not in headers["Content-Security-Policy"]
    assert headers["X-Frame-Options"] == "DENY"
    assert headers["Cache-Control"] == "no-store"
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert b"<script>" not in body and b"onclick=" not in body  # no inline script


@pytest.mark.parametrize(
    "host", ["evil.example", "evil.example:80", "127.0.0.1", "localhost:1", ""]
)
def test_bad_host_header_is_refused(console, host):
    server, *_ = console
    assert request(server, "GET", "/", host=host)[0] == 421
    assert (
        request(
            server, "GET", "/api/bootstrap", host=host, headers={"X-CSRF-Token": token_of(server)}
        )[0]
        == 421
    )


def test_localhost_name_with_our_port_is_allowed(console):
    server, *_ = console
    assert request(server, "GET", "/", host=f"localhost:{server.port}")[0] == 200


def test_api_requires_csrf_token(console):
    server, *_ = console
    assert request(server, "GET", "/api/bootstrap")[0] == 403
    assert request(server, "GET", "/api/bootstrap", headers={"X-CSRF-Token": "wrong"})[0] == 403
    status, _h, body = request(
        server, "GET", "/api/bootstrap", headers={"X-CSRF-Token": token_of(server)}
    )
    data = json.loads(body)
    assert status == 200 and data["categories"][0]["id"] == "daily-progress-reporting"
    assert data["wiz"]["connected"] is False


def test_post_needs_origin_csrf_and_json(console):
    server, *_ = console
    token = token_of(server)
    good = post_headers(server, token)
    path = "/api/wiz/disconnect"
    assert request(server, "POST", path, headers=good, body={})[0] == 200
    no_origin = {k: v for k, v in good.items() if k != "Origin"}
    assert request(server, "POST", path, headers=no_origin, body={})[0] == 403
    assert (
        request(server, "POST", path, headers={**good, "Origin": "http://evil.example"}, body={})[0]
        == 403
    )
    assert request(server, "POST", path, headers={**good, "X-CSRF-Token": "x"}, body={})[0] == 403
    assert (
        request(server, "POST", path, headers={**good, "Content-Type": "text/plain"}, body=b"{}")[0]
        == 415
    )
    assert request(server, "POST", path, headers=good, body=b"not json")[0] == 400
    assert request(server, "POST", path, headers=good, body=b"[1]")[0] == 400


def test_oversized_body_is_refused(console):
    server, *_ = console
    token = token_of(server)
    headers = post_headers(server, token)
    conn = http.client.HTTPConnection("127.0.0.1", server.port, timeout=5)
    conn.putrequest("POST", "/api/runs", skip_host=True)
    conn.putheader("Host", f"127.0.0.1:{server.port}")
    for k, v in {**headers, "Content-Length": str(50 * 1024 * 1024)}.items():
        conn.putheader(k, v)
    conn.endheaders()
    assert conn.getresponse().status == 413
    conn.close()


@pytest.mark.parametrize("method", ["PUT", "DELETE", "PATCH"])
def test_other_verbs_are_refused(console, method):
    server, *_ = console
    assert request(server, method, "/api/bootstrap")[0] == 405


@pytest.mark.parametrize(
    "path",
    [
        "/static/../server.py",
        "/static/%2e%2e/server.py",
        "/static/index.html",
        "/static/..%5cserver.py",
        "/static/adapters.py",
        "/server.py",
        "//etc/passwd",
    ],
)
def test_static_files_are_whitelisted_and_confined(console, path):
    server, *_ = console
    assert request(server, "GET", path)[0] in (404, 421)


def test_static_assets_are_served(console):
    server, *_ = console
    status, headers, body = request(server, "GET", "/static/app.js")
    assert status == 200 and headers["Content-Type"].startswith("text/javascript")
    assert b"innerHTML" not in body  # server data is only ever rendered as text
    assert request(server, "GET", "/static/style.css")[0] == 200


def test_download_is_confined_to_recorded_deliverables(console):
    server, *_ = console
    token = token_of(server)
    h = {"X-CSRF-Token": token}
    assert (
        request(
            server,
            "GET",
            "/api/runs/20260101T000000Z-abcdef/download/daily-progress-report",
            headers=h,
        )[0]
        == 404
    )
    assert request(server, "GET", "/api/runs/..%2f..%2fx/download/y", headers=h)[0] == 404
    assert request(server, "GET", "/api/runs/%2e%2e", headers=h)[0] == 404


def test_oauth_callback_rejects_unknown_state_and_never_connects(console):
    server, _adapter, _mcp = console
    status, headers, _b = request(server, "GET", "/oauth/callback?code=abc&state=nope")
    assert status == 303 and headers["Location"] == "/#wiz-error"
    status, headers, _b = request(server, "GET", "/oauth/callback?error=access_denied")
    assert headers["Location"] == "/#wiz-error"
    assert server.app.oauth.connected is False
    assert request(server, "GET", "/oauth/callback?code=a&state=b", host="evil.example")[0] == 421


def test_wiz_connect_then_callback_connects_in_memory(console):
    server, _adapter, mcp = console
    token = token_of(server)
    status, _h, body = request(
        server, "POST", "/api/wiz/connect", headers=post_headers(server, token), body={}
    )
    assert status == 200
    code, state = mcp.approve(json.loads(body)["authorize_url"])
    status, headers, _b = request(server, "GET", f"/oauth/callback?code={code}&state={state}")
    assert headers["Location"] == "/#wiz-connected"
    status, _h, body = request(server, "GET", "/api/bootstrap", headers={"X-CSRF-Token": token})
    assert json.loads(body)["wiz"]["connected"] is True


def test_live_run_requires_wiz_connection(console):
    server, *_ = console
    token = token_of(server)
    status, _h, body = request(
        server,
        "POST",
        "/api/runs",
        headers=post_headers(server, token),
        body={"category_id": "daily-progress-reporting", "inputs": {"subject": "x"}},
    )
    assert status == 400 and "Connect Wiz" in json.loads(body)["error"]


def test_run_ids_in_urls_are_validated(console):
    server, *_ = console
    token = token_of(server)
    status, *_rest = request(
        server, "POST", "/api/runs/not-a-run/approve", headers=post_headers(server, token), body={}
    )
    assert status == 404
