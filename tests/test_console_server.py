"""Console server over real HTTP: security properties, helper bridge and the full page flow."""

from __future__ import annotations

import contextlib
import http.client
import json
import re
import threading
import time

import pytest
from console_fakes import FakeHelper, append, event, tool_done, tool_start

from wizexpert.console.bridge import digest, mac
from wizexpert.console.config import ConsoleConfig
from wizexpert.console.server import build_server


@pytest.fixture
def console(tmp_path):
    workspace = tmp_path / "ws"
    (workspace / "deliverables").mkdir(parents=True)
    home = tmp_path / "copilot"
    config = ConsoleConfig(
        workspace=workspace,
        copilot_home=home,
        state_dir=tmp_path / "state",
        vscode_user_dir=tmp_path / "vscode",
    )
    server = build_server(config, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server, config, home
    server.shutdown()
    server.server_close()


def request(server, method, path, *, headers=None, body=None, host=None):
    conn = http.client.HTTPConnection("127.0.0.1", server.port, timeout=10)
    conn.putrequest(method, path, skip_host=True)
    conn.putheader("Host", f"127.0.0.1:{server.port}" if host is None else host)
    for key, value in (headers or {}).items():
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


def api(server, token, method, path, body=None):
    headers = {"X-CSRF-Token": token}
    if method == "POST":
        headers.update(
            {"Content-Type": "application/json", "Origin": f"http://127.0.0.1:{server.port}"}
        )
    status, hdrs, payload = request(
        server, method, path, headers=headers, body=body if method == "POST" else None
    )
    return status, hdrs, payload


def test_binds_loopback_only_and_headers(console):
    server, *_ = console
    assert server.server_address[0] == "127.0.0.1"
    status, headers, body = request(server, "GET", "/")
    assert status == 200 and b"__CSRF_TOKEN__" not in body
    assert "script-src 'self'" in headers["Content-Security-Policy"]
    assert "frame-ancestors 'none'" in headers["Content-Security-Policy"]
    assert headers["X-Content-Type-Options"] == "nosniff" and headers["Cache-Control"] == "no-store"


@pytest.mark.parametrize("host", ["evil.example", "127.0.0.1", "127.0.0.1:1", "localhost", ""])
def test_bad_host_header_is_refused(console, host):
    server, *_ = console
    assert request(server, "GET", "/", host=host)[0] == 421


def test_localhost_name_with_our_port_is_allowed(console):
    server, *_ = console
    assert request(server, "GET", "/", host=f"localhost:{server.port}")[0] == 200


def test_api_needs_csrf_and_post_needs_origin_and_json(console):
    server, *_ = console
    token = token_of(server)
    assert request(server, "GET", "/api/bootstrap")[0] == 403
    assert request(server, "GET", "/api/bootstrap", headers={"X-CSRF-Token": "wrong"})[0] == 403
    assert api(server, token, "GET", "/api/bootstrap")[0] == 200
    body = {"category_id": "daily-progress-reporting", "inputs": {}}
    base = {"X-CSRF-Token": token, "Content-Type": "application/json"}
    origin = {"Origin": f"http://127.0.0.1:{server.port}"}
    assert (
        request(
            server,
            "POST",
            "/api/runs",
            headers={**base, "Origin": "http://evil.example"},
            body=body,
        )[0]
        == 403
    )
    assert request(server, "POST", "/api/runs", headers=base, body=body)[0] == 403  # no Origin
    assert (
        request(
            server,
            "POST",
            "/api/runs",
            headers={**origin, "X-CSRF-Token": "x", "Content-Type": "application/json"},
            body=body,
        )[0]
        == 403
    )
    assert (
        request(
            server,
            "POST",
            "/api/runs",
            headers={**origin, "X-CSRF-Token": token, "Content-Type": "text/plain"},
            body=body,
        )[0]
        == 415
    )
    assert (
        request(server, "POST", "/api/runs", headers={**base, **origin}, body=b"not json")[0] == 400
    )
    assert request(server, "POST", "/api/runs", headers={**base, **origin}, body=b"[1]")[0] == 400


def test_oversized_body_and_other_verbs_refused(console):
    server, *_ = console
    token = token_of(server)
    headers = {
        "X-CSRF-Token": token,
        "Content-Type": "application/json",
        "Origin": f"http://127.0.0.1:{server.port}",
    }
    conn = http.client.HTTPConnection("127.0.0.1", server.port, timeout=10)
    conn.putrequest("POST", "/api/runs", skip_host=True)
    conn.putheader("Host", f"127.0.0.1:{server.port}")
    for key, value in {**headers, "Content-Length": str(300 * 1024 * 1024)}.items():
        conn.putheader(key, value)
    conn.endheaders()  # the oversized body is advertised, never sent
    assert conn.getresponse().status == 413
    conn.close()
    for method in ("PUT", "DELETE", "PATCH", "OPTIONS"):
        assert request(server, method, "/api/bootstrap")[0] == 405


@pytest.mark.parametrize(
    "path",
    [
        "/static/../server.py",
        "/static/..%2fserver.py",
        "/static/index.html",
        "/static/%2e%2e/config.py",
        "/nope",
        "/static/",
    ],
)
def test_static_files_are_whitelisted(console, path):
    server, *_ = console
    assert request(server, "GET", path)[0] == 404


def test_static_assets_are_served(console):
    server, *_ = console
    for name, kind in (
        ("app.js", "javascript"),
        ("style.css", "css"),
        ("assets/logo.svg", "svg"),
        ("assets/workflow-risk-issues.svg", "svg"),
        ("assets/workflow-daily-progress.svg", "svg"),
        ("assets/workflow-weekly-progress.svg", "svg"),
        ("assets/workflow-monthly-governance.svg", "svg"),
    ):
        status, headers, _b = request(server, "GET", f"/static/{name}")
        assert status == 200 and kind in headers["Content-Type"]


def test_invalid_input_is_rejected_over_http_and_not_started(console):
    server, *_ = console
    token = token_of(server)
    status, _h, body = api(
        server,
        token,
        "POST",
        "/api/runs",
        {"category_id": "risk-issues", "inputs": {"issue_ids": "wc-1; do bad things"}},
    )
    assert status == 400 and b"letters, digits" in body
    status, _h, body = api(
        server,
        token,
        "POST",
        "/api/runs",
        {"category_id": "risk-issues", "inputs": {"issue_ids": "wc-1"}},
    )
    assert status == 400 and b"helper is not connected" in body


def test_run_ids_are_validated_and_no_file_endpoint(console):
    server, *_ = console
    token = token_of(server)
    for path in (
        "/api/runs/../x",
        "/api/runs/abc",
        "/api/runs/20260101T000000Z-aaaaaa",
        "/api/runs/20260101T000000Z-aaaaaa/file/0",
    ):
        assert api(server, token, "GET", path)[0] == 404


def helper_headers(server, method, path, body=b"", nonce="abc"):
    token = server.app.bridge.token
    stamp = str(int(time.time()))
    return {
        "X-Console-Nonce": nonce,
        "X-Console-Time": stamp,
        "X-Console-Auth": mac(token, "req", method, path, stamp, nonce, digest(body)),
    }


def test_helper_endpoints_need_valid_signature_and_sign_answers(console):
    server, *_ = console
    path = "/vscode/jobs?after=-1&instance=ab&folders=%5B%5D"
    assert request(server, "GET", path)[0] == 403
    assert (
        request(
            server,
            "GET",
            path,
            headers={
                "X-Console-Nonce": "n",
                "X-Console-Time": str(int(time.time())),
                "X-Console-Auth": "00",
            },
        )[0]
        == 403
    )
    headers = helper_headers(server, "GET", path)
    status, response_headers, body = request(server, "GET", path, headers=headers)
    assert status == 200
    want = mac(server.app.bridge.token, "resp", "abc", digest(body))
    assert response_headers["X-Console-Proof"] == want
    assert request(server, "GET", path, headers=headers)[0] == 403  # replayed nonce
    assert request(server, "POST", "/vscode/result", body=b'{"id": 1}')[0] == 403
    payload = json.dumps({"id": 1}).encode()
    signed = helper_headers(server, "POST", "/vscode/guard", payload, nonce="g1")
    status, _h, body = request(server, "POST", "/vscode/guard", headers=signed, body=payload)
    assert status == 200 and json.loads(body)["ok"] is False  # unknown job


def test_full_flow_progress_input_needed_summary_and_files(console):
    server, config, home = console
    workspace = config.resolved_workspace()
    token = token_of(server)
    with FakeHelper(server.app.bridge, workspace, home) as helper:
        status, _h, body = api(server, token, "GET", "/api/bootstrap")
        assert json.loads(body)["helper"]["connected"] is True
        status, _h, body = api(
            server,
            token,
            "POST",
            "/api/runs",
            {"category_id": "risk-issues", "inputs": {"issue_ids": "wc-id-5"}},
        )
        assert status == 200
        run_id = json.loads(body)["run_id"]
        deadline = time.time() + 10
        view = {}
        while time.time() < deadline:
            view = json.loads(api(server, token, "GET", f"/api/runs/{run_id}")[2])
            if view["status"] == "running":
                break
            time.sleep(0.1)
        assert view["status"] == "running"
        assert (
            helper.jobs[0]["prompt"]
            == "Risk Issues category: prepare the deliverables for Wiz issue wc-id-5"
        )

        case = workspace / "deliverables" / "Case"
        case.mkdir()
        (case / "report.docx").write_text("<script>alert(1)</script>", encoding="utf-8")
        append(
            helper.events_path,
            event(
                "assistant.message",
                {"content": "<img src=x onerror=1> Collecting", "toolRequests": [{}]},
            ),
            tool_start("create", {"path": str(case / "report.docx"), "file_text": "x"}, "c1"),
            tool_done("c1"),
        )
        view = json.loads(api(server, token, "GET", f"/api/runs/{run_id}?since=0")[2])
        assert (
            view["status"] == "running"
            and view["files"][0]["path"] == "deliverables/Case/report.docx"
        )
        assert any("Collecting" in i["text"] for i in view["progress"])

        append(helper.events_path, tool_start("ask_user", {"message": "Which tenant?"}, "q1"))
        view = json.loads(api(server, token, "GET", f"/api/runs/{run_id}?since={view['next']}")[2])
        assert view["status"] == "input_needed" and "Which tenant" in view["pending"]["text"]

        append(
            helper.events_path,
            tool_done("q1"),
            event("assistant.message", {"content": "Done. Deliverables are ready."}),
            event("hook.end", {"hookType": "agentStop"}),
        )
        view = json.loads(api(server, token, "GET", f"/api/runs/{run_id}")[2])
        assert view["status"] == "completed" and view["summary"] == "Done. Deliverables are ready."
        assert api(server, token, "GET", f"/api/runs/{run_id}/file/0")[0] == 404
        assert set(view["files"][0]) >= {"name", "location"}
        assert not {"vscode", "download", "size"} & set(view["files"][0])
        history = json.loads(api(server, token, "GET", "/api/bootstrap")[2])["history"]
        assert history[0]["id"] == run_id and history[0]["status"] == "completed"


def _previous(server, token):
    status, _h, body = api(server, token, "GET", "/api/weekly-progress/previous-reports")
    assert status == 200
    return json.loads(body)


def test_previous_reports_empty_is_explicit_and_needs_csrf(console):
    server, *_ = console
    assert request(server, "GET", "/api/weekly-progress/previous-reports")[0] == 403
    data = _previous(server, token_of(server))
    assert data["reports"] == [] and data["empty"] is True
    assert "first report" in data["message"]


def test_previous_reports_lists_only_safe_weekly_folders(console, tmp_path):
    server, config, _home = console
    root = config.workspace / "deliverables"
    good = root / "Weekly-Progress" / "2026-10-26"
    good.mkdir(parents=True)
    (good / "report.xlsx").write_text("SECRET-CONTENT")
    other = root / "Daily-Progress"
    other.mkdir()
    (other / "report.xlsx").write_text("x")
    (root / "Weekly-Progress" / "empty").mkdir()
    (root / "Weekly-Progress" / "notes.tmp").write_text("x")
    evidence = root / "Weekly-Progress" / "evidence"
    evidence.mkdir()
    (evidence / "a.xlsx").write_text("x")
    outside = tmp_path / "outside" / "weekly-progress-x"
    outside.mkdir(parents=True)
    (outside / "a.xlsx").write_text("x")
    with contextlib.suppress(OSError):
        (root / "weekly-progress-link").symlink_to(outside, target_is_directory=True)
    status, _h, body = api(server, token_of(server), "GET", "/api/weekly-progress/previous-reports")
    data = json.loads(body)
    assert status == 200 and data["empty"] is False
    assert data["reports"] == [{"name": "2026-10-26", "reference": "Weekly-Progress/2026-10-26"}]
    assert b"SECRET-CONTENT" not in body and str(tmp_path).encode() not in body


def test_weekly_ui_uses_listing_with_manual_fallback(console):
    server, *_ = console
    status, _h, body = request(server, "GET", "/static/app.js")
    assert status == 200
    assert b"/api/weekly-progress/previous-reports" in body
    assert b"None: this is the first report" in body and b"__manual__" in body
