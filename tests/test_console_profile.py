"""Display-only signed-in profile: storage, validation, API and the no-filter guarantee."""

from __future__ import annotations

import contextlib
import json
import socket
import threading

import pytest
from test_console_server import api, request, token_of

from wizexpert.console import imports
from wizexpert.console import server as console_server
from wizexpert.console.config import ConsoleConfig, load_profile, save_profile
from wizexpert.console.server import build_server, main


def test_save_and_load(tmp_path):
    save_profile(tmp_path / "s", "Jo O'Neil-Smith", "USER123")
    assert load_profile(tmp_path / "s") == {
        "configured": True, "name": "Jo O'Neil-Smith", "user_id": "USER123", "has_photo": False
    }


@pytest.mark.parametrize(
    "name,uid",
    [("", "USER123"), ("x" * 61, "USER123"), ("<b>", "USER123"), ("Ann", ""),
     ("Ann", "a" * 65), ("Ann", "bad id"), ("Ann", "u/1")],
)
def test_validation_rejects(tmp_path, name, uid):
    with pytest.raises(ValueError):
        save_profile(tmp_path, name, uid)
    assert not load_profile(tmp_path)["configured"]


def test_missing_and_corrupt_never_raise(tmp_path):
    assert load_profile(tmp_path / "none")["configured"] is False
    (tmp_path / "profile.json").write_text("{not json", encoding="utf-8")
    assert load_profile(tmp_path)["configured"] is False
    (tmp_path / "profile.json").write_text(json.dumps({"name": 5}), encoding="utf-8")
    assert load_profile(tmp_path)["configured"] is False
    (tmp_path / "profile.json").write_text("[]", encoding="utf-8")
    assert load_profile(tmp_path)["configured"] is False


def test_setup_cli_non_interactive(tmp_path):
    assert main(["setup", "--name", "Ann", "--id", "USER123", "--state-dir", str(tmp_path)]) == 0
    assert load_profile(tmp_path)["user_id"] == "USER123"
    assert main(["setup", "--name", "Ann", "--id", "bad id", "--state-dir", str(tmp_path)]) == 2


def test_profile_api(tmp_path):
    ws = tmp_path / "ws"
    (ws / "deliverables").mkdir(parents=True)
    config = ConsoleConfig(
        workspace=ws, copilot_home=tmp_path / "c", state_dir=tmp_path / "state",
        vscode_user_dir=tmp_path / "v",
    )
    server = build_server(config, port=0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        token = token_of(server)
        _s, _h, body = api(server, token, "GET", "/api/profile")
        assert json.loads(body)["configured"] is False
        save_profile(config.state_dir, "Ann", "USER123")
        _s, _h, body = api(server, token, "GET", "/api/profile")
        assert json.loads(body) == {
            "configured": True, "name": "Ann", "user_id": "USER123", "has_photo": False
        }
        status, _h, _b = api(server, "wrong", "GET", "/api/profile")
        assert status == 403
    finally:
        server.shutdown()
        server.server_close()


def test_profile_does_not_filter_scan(tmp_path):
    ws = tmp_path / "ws"
    case = ws / "deliverables" / "Risk-Issues" / "Some-Rule" / "wc-id-1-USER123"
    case.mkdir(parents=True)
    (case / "note.md").write_text("x", encoding="utf-8")
    config = ConsoleConfig(
        workspace=ws, copilot_home=tmp_path / "c", state_dir=tmp_path / "state",
        vscode_user_dir=tmp_path / "v",
    )
    before = imports.scan_risk_cases(config)
    save_profile(config.state_dir, "Ann", "USER123")
    assert imports.scan_risk_cases(config) == before


PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
PHOTO = "/api/profile/photo"


@pytest.fixture
def photo_server(tmp_path):
    ws = tmp_path / "ws"
    (ws / "deliverables").mkdir(parents=True)
    config = ConsoleConfig(
        workspace=ws, copilot_home=tmp_path / "c", state_dir=tmp_path / "state",
        vscode_user_dir=tmp_path / "v",
    )
    server = build_server(config, port=0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server, config, token_of(server)
    server.shutdown()
    server.server_close()


def _headers(server, token, origin=True):
    headers = {"Content-Type": "application/octet-stream"}
    if token is not None:
        headers["X-CSRF-Token"] = token
    if origin:
        headers["Origin"] = f"http://127.0.0.1:{server.port}"
    return headers


def _post(server, token, body, **kw):
    return request(server, "POST", PHOTO, headers=_headers(server, token, **kw), body=body)


def test_photo_upload_rejects_missing_csrf_origin_profile(photo_server):
    server, config, token = photo_server
    save_profile(config.state_dir, "Ann", "USER123")
    assert _post(server, None, PNG)[0] == 403
    assert _post(server, "wrong", PNG)[0] == 403
    assert _post(server, token, PNG, origin=False)[0] == 403
    assert not load_profile(config.state_dir)["has_photo"]
    (config.state_dir / "profile.json").unlink()
    assert _post(server, token, PNG)[0] == 409


def test_photo_upload_invalid_and_oversize(photo_server):
    server, config, token = photo_server
    save_profile(config.state_dir, "Ann", "USER123")
    status, _h, body = _post(server, token, b"GIF89a not an image")
    assert status == 400 and "PNG or JPEG" in json.loads(body)["error"]
    # the server may reject on Content-Length and close before the body is fully sent
    with contextlib.suppress(BrokenPipeError, ConnectionResetError):
        assert _post(server, token, b"x" * (1024 * 1024 + 1))[0] == 413
    assert _post(server, token, b"")[0] == 413
    assert not load_profile(config.state_dir)["has_photo"]


def test_photo_get_and_delete(photo_server):
    server, config, token = photo_server
    assert api(server, token, "GET", PHOTO)[0] == 404  # no profile
    save_profile(config.state_dir, "Ann", "USER123")
    assert api(server, token, "GET", PHOTO)[0] == 404  # no photo
    assert api(server, "wrong", "GET", PHOTO)[0] == 403
    status, _h, body = _post(server, token, PNG)
    assert status == 200 and json.loads(body)["has_photo"] is True
    status, headers, body = api(server, token, "GET", PHOTO)
    assert status == 200 and body == PNG
    assert headers["Content-Type"] == "image/png"
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["Cache-Control"] == "no-store"
    delete = request(server, "DELETE", PHOTO, headers={"X-CSRF-Token": token})
    assert delete[0] == 403  # missing Origin
    origin = {"X-CSRF-Token": token, "Origin": f"http://127.0.0.1:{server.port}"}
    assert request(server, "DELETE", PHOTO, headers={"Origin": origin["Origin"]})[0] == 403
    status, _h, body = request(server, "DELETE", PHOTO, headers=origin)
    assert status == 200 and json.loads(body)["has_photo"] is False
    assert api(server, token, "GET", PHOTO)[0] == 404


def test_photo_save_oserror_is_generic(photo_server, monkeypatch):
    server, config, token = photo_server
    save_profile(config.state_dir, "Ann", "USER123")

    def boom(*_a, **_k):
        raise OSError(13, "denied", r"C:\secret\path\profile-photo.png")

    monkeypatch.setattr(console_server, "save_photo", boom)
    status, _h, body = _post(server, token, PNG)
    assert status == 400
    assert json.loads(body)["error"] == "Photo could not be saved."
    assert b"secret" not in body


def test_slow_photo_upload_times_out_without_blocking_others(photo_server, monkeypatch):
    server, config, token = photo_server
    save_profile(config.state_dir, "Ann", "USER123")
    monkeypatch.setattr(console_server, "PHOTO_UPLOAD_TIMEOUT", 0.5)
    sock = socket.create_connection(("127.0.0.1", server.port), timeout=10)
    try:
        head = (
            f"POST {PHOTO} HTTP/1.1\r\nHost: 127.0.0.1:{server.port}\r\n"
            f"Origin: http://127.0.0.1:{server.port}\r\nX-CSRF-Token: {token}\r\n"
            f"Content-Length: {len(PNG) + 100}\r\n\r\n"
        ).encode()
        sock.sendall(head + PNG)  # then stall
        assert api(server, token, "GET", "/api/profile")[0] == 200  # others unaffected
        data = b""
        while b"\r\n\r\n" not in data:
            chunk = sock.recv(4096)
            if not chunk:
                break
            data += chunk
        assert data.startswith(b"HTTP/1.1 408")
    finally:
        sock.close()
    assert not load_profile(config.state_dir)["has_photo"]
