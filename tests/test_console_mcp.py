"""MCP client tests: OAuth 2.1 + PKCE, in-memory tokens, 401 handling, read-only policy."""

from __future__ import annotations

import base64
import hashlib
import urllib.parse

import pytest
from console_fakes import FakeMcpServer

from wizexpert.console.context import McpCallError, ReconnectRequired
from wizexpert.console.mcp_client import (
    McpClient,
    OAuthConnection,
    OAuthError,
    UrllibTransport,
    pkce_pair,
)
from wizexpert.console.policy import ReadOnlyViolation, check_execute

REDIRECT = "http://127.0.0.1:1/oauth/callback"


@pytest.fixture
def fake():
    server = FakeMcpServer()
    yield server
    server.close()


def connect(fake, *, clock=None):
    transport = UrllibTransport(allow_loopback_http=True, timeout=5)
    kwargs = {"clock": clock} if clock else {}
    oauth = OAuthConnection(fake.url, REDIRECT, transport, **kwargs)
    code, state = fake.approve(oauth.begin())
    oauth.complete(code, state)
    return oauth, McpClient(oauth, transport)


def test_pkce_pair_is_s256_and_random():
    verifier, challenge = pkce_pair()
    digest = hashlib.sha256(verifier.encode()).digest()
    assert challenge == base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    assert len(verifier) >= 43 and pkce_pair()[0] != verifier


def test_authorization_request_has_pkce_state_resource_and_registered_client(fake):
    transport = UrllibTransport(allow_loopback_http=True, timeout=5)
    oauth = OAuthConnection(fake.url, REDIRECT, transport)
    url = oauth.begin()
    query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
    assert query["code_challenge_method"] == ["S256"]
    assert query["redirect_uri"] == [REDIRECT]
    assert query["resource"] == [fake.url]
    assert len(query["state"][0]) >= 32 and query["client_id"][0] in fake.clients


def test_full_flow_checks_pkce_and_reads_through_execute(fake):
    oauth, client = connect(fake)
    assert oauth.connected and fake.pkce_checked == 1
    result = client.execute("list_issues", {"first": 20})
    assert result == {"echo": "list_issues", "parameters": {"first": 20}}
    assert fake.calls == [("execute", {"tool_name": "list_issues", "parameters": {"first": 20}})]


def test_sse_responses_are_parsed():
    server = FakeMcpServer(sse=True)
    try:
        _oauth, client = connect(server)
        assert client.execute("get_issue", {"id": "x"})["echo"] == "get_issue"
    finally:
        server.close()


def test_state_is_single_use_and_unknown_state_rejected(fake):
    transport = UrllibTransport(allow_loopback_http=True, timeout=5)
    oauth = OAuthConnection(fake.url, REDIRECT, transport)
    code, state = fake.approve(oauth.begin())
    with pytest.raises(OAuthError):
        oauth.complete(code, "not-the-state")
    oauth.complete(code, state)
    assert oauth.connected
    with pytest.raises(OAuthError):
        oauth.complete(code, state)


def test_pending_state_expires(fake):
    now = [1000.0]
    transport = UrllibTransport(allow_loopback_http=True, timeout=5)
    oauth = OAuthConnection(fake.url, REDIRECT, transport, clock=lambda: now[0])
    code, state = fake.approve(oauth.begin())
    now[0] += 601
    with pytest.raises(OAuthError):
        oauth.complete(code, state)


def test_wrong_verifier_is_refused_by_server(fake):
    transport = UrllibTransport(allow_loopback_http=True, timeout=5)
    oauth = OAuthConnection(fake.url, REDIRECT, transport)
    code, state = fake.approve(oauth.begin())
    fake.codes[code]["challenge"] = "tampered"
    with pytest.raises(OAuthError):
        oauth.complete(code, state)
    assert not oauth.connected


def test_401_mid_run_stops_and_requires_reconnect(fake):
    oauth, client = connect(fake)
    client.execute("list_issues", {})
    fake.revoke_all()
    with pytest.raises(ReconnectRequired):
        client.execute("list_issues", {})
    assert not oauth.connected
    with pytest.raises(ReconnectRequired):  # no silent retry without a new sign-in
        client.execute("list_issues", {})


def test_tool_error_with_oauth_marker_requires_reconnect_other_errors_do_not(fake):
    oauth, client = connect(fake)
    fake.tool_error = "invalid_token: expired"
    with pytest.raises(ReconnectRequired):
        client.execute("list_issues", {})
    assert not oauth.connected
    oauth, client = connect(fake)
    fake.tool_error = "bad filter"
    with pytest.raises(McpCallError):
        client.execute("list_issues", {})
    assert oauth.connected


def test_refresh_token_is_used_before_expiry_in_memory_only(fake):
    now = [1000.0]
    fake.expires_in = 100
    oauth, client = connect(fake, clock=lambda: now[0])
    first = oauth.bearer()
    now[0] += 80  # inside the 60s early-refresh margin
    second = oauth.bearer()
    assert first != second and oauth.connected


def test_expired_without_refresh_requires_reconnect(fake):
    now = [1000.0]
    fake.expires_in = 10
    oauth, _client = connect(fake, clock=lambda: now[0])
    oauth._tokens.refresh = ""  # noqa: SLF001
    now[0] += 100
    with pytest.raises(ReconnectRequired):
        oauth.bearer()


def test_tokens_are_redacted_and_never_written_to_disk(fake, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    oauth, client = connect(fake)
    token = oauth.bearer()
    client.execute("list_issues", {})
    assert (
        token not in repr(oauth) and token not in repr(client) and token not in repr(oauth._tokens)
    )  # noqa: SLF001
    assert list(tmp_path.rglob("*")) == []


def test_https_only_and_no_redirect_following():
    transport = UrllibTransport()
    with pytest.raises(OAuthError):
        transport.check_url("http://example.invalid/mcp")
    with pytest.raises(OAuthError):
        transport.check_url("http://127.0.0.1/mcp")  # loopback http only when explicitly allowed
    UrllibTransport(allow_loopback_http=True).check_url("http://127.0.0.1:9/mcp")


@pytest.mark.parametrize(
    "tool",
    [
        "update_issue",
        "delete_issue",
        "create_ticket",
        "set_status",
        "assign_issue",
        "resolve_issue",
        "send_email",
        "run_remediation",
        "mutate_x",
        "execute_action",
        "list_and_delete_all",
        "Get_Issue",
        "../get_issue",
        "",
        None,
        5,
    ],
)
def test_write_style_tools_are_refused_before_any_traffic(fake, tool):
    _oauth, client = connect(fake)
    with pytest.raises(ReadOnlyViolation):
        client.execute(tool, {})
    assert fake.calls == []


@pytest.mark.parametrize(
    "params",
    [
        {"query": "mutation { deleteIssue(id: 1) { id } }"},
        {"nested": {"deep": ["x", "MUTATION { a }"]}},
        {"mutation": 1},
        {"q": object()},
    ],
)
def test_graphql_mutations_and_odd_values_are_refused(fake, params):
    _oauth, client = connect(fake)
    with pytest.raises(ReadOnlyViolation):
        client.execute("execute_graph_query", params)
    assert fake.calls == []


@pytest.mark.parametrize(
    "tool",
    [
        "list_issues",
        "get_issue",
        "get_control",
        "list_vulnerability_findings_grouped",
        "get_issue_remediation_strategies",
        "list_cloud_resources",
        "execute_graph_query",
        "graph_search",
        "get_graph_entity_raw_data",
        "list_posture_issues",
    ],
)
def test_read_tools_used_by_reporting_are_allowed(tool):
    check_execute(tool, {"status": ["RESOLVED"], "first": 20})


def test_only_discover_and_execute_mcp_tools_exist(fake):
    _oauth, client = connect(fake)
    with pytest.raises(ReadOnlyViolation):
        client._call_tool("delete_everything", {})  # noqa: SLF001
    client.discover("issues")
    assert fake.calls[-1][0] == "discover"
    with pytest.raises(ReadOnlyViolation):
        client.discover("../../x;rm")


def test_not_connected_client_requires_reconnect(fake):
    transport = UrllibTransport(allow_loopback_http=True, timeout=5)
    client = McpClient(OAuthConnection(fake.url, REDIRECT, transport), transport)
    with pytest.raises(ReconnectRequired):
        client.execute("list_issues", {})
