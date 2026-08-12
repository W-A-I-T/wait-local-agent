from __future__ import annotations

import asyncio
import json

import pytest
from starlette.requests import Request
from starlette.responses import Response

from wait_local_agent.agents import ToolDefinition
from wait_local_agent.api.app import create_app
from wait_local_agent.mcp import (
    MAX_MCP_RESULT_BYTES,
    MAX_MCP_SESSIONS,
    McpProtocolError,
    WaitMcpServer,
    _cursor_offset,
    _input_schema,
    _mcp_client_scope,
    _output_schema,
    _property_schema,
    cast_dict,
    origin_allowed,
    protocol_error_response,
)
from wait_local_agent.rbac import AuthContext, Role
from wait_local_agent.smart_actions import ActionResult, SmartActionManifest
from wait_local_agent.store import Store


def _secure_settings(settings):
    return settings.__class__(
        **{
            **settings.__dict__,
            "demo_mode": False,
            "client_id": "acme",
            "tech_token": "tech-token",
            "viewer_token": "viewer-token",
        }
    )


def _seed_tickets(settings) -> None:
    store = Store(settings.data_path)
    with store._connect() as connection:  # noqa: SLF001
        connection.executemany(
            """
            insert into tickets (id, client, subject, body, priority, status, client_id)
            values (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                ("TCK-ACME", "Acme", "MFA reset", "Sign-in blocked", "High", "Open", "acme"),
                ("TCK-BETA", "Beta", "MFA reset", "Sign-in blocked", "High", "Open", "beta"),
            ],
        )


def _fake_server(mode: str = "success") -> WaitMcpServer:
    read_manifest = SmartActionManifest(
        action_id="fake-read",
        title="Fake read",
        description="A bounded fake read action.",
        kind="deterministic",
        input_schema={"properties": {"value": "string|integer", "metadata": {"type": "object"}}},
        output_schema={"value": "string", "count": "integer|null"},
        requires_approval=False,
        estimated_minutes_saved=1,
    )
    admin_manifest = SmartActionManifest(
        action_id="fake-admin",
        title="Fake admin",
        description="A bounded fake admin action.",
        kind="deterministic",
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        requires_approval=False,
        estimated_minutes_saved=1,
        required_role="admin",
        access_mode="write",
    )

    class FakeAgent:
        def list_tools(self):
            return [
                ToolDefinition(
                    id=read_manifest.action_id,
                    name=read_manifest.title,
                    description=read_manifest.description,
                    input_schema=read_manifest.input_schema,
                    output_schema=read_manifest.output_schema,
                    risk_level=read_manifest.risk_level,
                    required_role=read_manifest.required_role,
                    approval_required=read_manifest.requires_approval,
                    access_mode=read_manifest.access_mode,
                    approval_expiry_seconds=read_manifest.approval_expiry_seconds,
                ),
                ToolDefinition(
                    id=admin_manifest.action_id,
                    name=admin_manifest.title,
                    description=admin_manifest.description,
                    input_schema=admin_manifest.input_schema,
                    output_schema=admin_manifest.output_schema,
                    risk_level=admin_manifest.risk_level,
                    required_role=admin_manifest.required_role,
                    approval_required=admin_manifest.requires_approval,
                    access_mode=admin_manifest.access_mode,
                    approval_expiry_seconds=admin_manifest.approval_expiry_seconds,
                ),
            ]

    class FakeActions:
        def describe(self, action_id):
            if action_id == read_manifest.action_id:
                return read_manifest
            if action_id == admin_manifest.action_id:
                return admin_manifest
            raise KeyError(action_id)

        def invoke(self, *args, **kwargs):
            if mode == "key":
                raise KeyError("secret token should be redacted")
            if mode == "value":
                raise ValueError("invalid secret token")
            if mode == "exception":
                raise RuntimeError("internal detail")
            if mode == "large":
                return ActionResult(status="success", output={"value": "x" * (MAX_MCP_RESULT_BYTES + 1)})
            if mode == "invalid":
                return object()
            return ActionResult(status="success", output={"value": "ok"})

    return WaitMcpServer(FakeAgent(), FakeActions())


def _call_mcp(
    app,
    payload: object,
    *,
    token: str | None = None,
    session_id: str | None = None,
    origin: str | None = None,
):
    return _call_mcp_raw(
        app,
        json.dumps(payload).encode(),
        token=token,
        session_id=session_id,
        origin=origin,
    )


def _call_mcp_raw(
    app,
    body: bytes,
    *,
    token: str | None = None,
    session_id: str | None = None,
    origin: str | None = None,
    extra_headers: tuple[tuple[bytes, bytes], ...] = (),
):
    route = next(
        route
        for route in app.routes
        if getattr(route, "path", None) == "/mcp" and "POST" in (route.methods or set())
    )
    headers = [(b"host", b"test")]
    if token:
        headers.append((b"authorization", f"Bearer {token}".encode()))
    if session_id:
        headers.append((b"mcp-session-id", session_id.encode()))
        headers.append((b"mcp-protocol-version", b"2025-11-25"))
    if origin:
        headers.append((b"origin", origin.encode()))
    headers.extend(extra_headers)

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/mcp",
            "raw_path": b"/mcp",
            "root_path": "",
            "scheme": "http",
            "query_string": b"",
            "headers": headers,
            "server": ("test", 80),
            "client": ("test", 1),
            "http_version": "1.1",
        },
        receive,
    )
    response = asyncio.run(route.endpoint(request))
    assert isinstance(response, Response)
    return response, json.loads(response.body) if response.body else None


def test_mcp_lifecycle_lists_and_calls_existing_tools_with_tenant_scope(settings) -> None:
    secure = _secure_settings(settings)
    _seed_tickets(secure)
    app = create_app(secure)

    initialized_response, initialized = _call_mcp(
        app,
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "test"}},
        },
        token="tech-token",
    )
    session_id = dict(initialized_response.headers).get("mcp-session-id")
    assert initialized_response.status_code == 200
    assert session_id
    assert initialized["result"]["capabilities"]["tools"]["listChanged"] is False

    ready_response, _ = _call_mcp(
        app,
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        token="tech-token",
        session_id=session_id,
    )
    listed_response, listed = _call_mcp(
        app,
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        token="tech-token",
        session_id=session_id,
    )
    assert ready_response.status_code == 202
    assert listed_response.status_code == 200
    tools = list(listed["result"]["tools"])
    next_cursor = listed["result"].get("nextCursor")
    while next_cursor:
        page_response, page = _call_mcp(
            app,
            {
                "jsonrpc": "2.0",
                "id": 20,
                "method": "tools/list",
                "params": {"cursor": next_cursor},
            },
            token="tech-token",
            session_id=session_id,
        )
        assert page_response.status_code == 200
        tools.extend(page["result"]["tools"])
        next_cursor = page["result"].get("nextCursor")
    ticket_tool = next(tool for tool in tools if tool["name"] == "wait.ticket-triage")
    assert ticket_tool["inputSchema"]["required"] == ["ticket_id"]
    assert ticket_tool["outputSchema"]["type"] == "object"
    assert ticket_tool["annotations"]["readOnlyHint"] is True

    called_response, called = _call_mcp(
        app,
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "wait.ticket-triage", "arguments": {"ticket_id": "TCK-ACME"}},
        },
        token="tech-token",
        session_id=session_id,
    )
    foreign_response, foreign = _call_mcp(
        app,
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {
                "name": "wait.ticket-triage",
                "arguments": {"ticket_id": "TCK-BETA", "client_id": "beta"},
            },
        },
        token="tech-token",
        session_id=session_id,
    )
    assert called_response.status_code == 200
    assert called["result"]["isError"] is False
    assert called["result"]["structuredContent"]["status"] == "success"
    assert foreign_response.status_code == 200
    assert foreign["result"]["isError"] is True
    assert "outside authenticated scope" in foreign["result"]["structuredContent"]["error_detail"]

    approval_response, approval = _call_mcp(
        app,
        {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {
                "name": "wait.communication-send",
                "arguments": {
                    "channel": "ticket_note",
                    "ticket_id": "TCK-ACME",
                    "body": "MCP approval boundary test",
                },
            },
        },
        token="tech-token",
        session_id=session_id,
    )
    assert approval_response.status_code == 200
    assert approval["result"]["structuredContent"]["status"] == "pending_approval"
    assert approval["result"]["structuredContent"]["approval_id"]


def test_mcp_requires_auth_session_and_uses_origin_allowlist(settings) -> None:
    secure = _secure_settings(settings)
    app = create_app(secure)
    body = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-11-25"}}

    missing_auth_response, _ = _call_mcp(app, body)
    invalid_origin_response, _ = _call_mcp(
        app,
        body,
        token="tech-token",
        origin="https://evil.example",
    )
    get_route = next(
        route
        for route in app.routes
        if getattr(route, "path", None) == "/mcp" and "GET" in (route.methods or set())
    )
    get = get_route.endpoint()

    assert missing_auth_response.status_code == 401
    assert invalid_origin_response.status_code == 403
    assert get.status_code == 405


def test_mcp_http_input_limits_and_protocol_header(settings) -> None:
    secure = _secure_settings(settings)
    app = create_app(secure)
    body = json.dumps(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-11-25"}}
    ).encode()

    invalid_json, _ = _call_mcp_raw(app, b"not-json", token="tech-token")
    invalid_length, _ = _call_mcp_raw(
        app,
        body,
        token="tech-token",
        extra_headers=((b"content-length", b"not-a-number"),),
    )
    too_large, _ = _call_mcp_raw(
        app,
        body,
        token="tech-token",
        extra_headers=((b"content-length", b"262145"),),
    )
    unsupported_header, unsupported_payload = _call_mcp_raw(
        app,
        body,
        token="tech-token",
        extra_headers=((b"mcp-protocol-version", b"2099-01-01"),),
    )

    assert invalid_json.status_code == 400
    assert invalid_length.status_code == 400
    assert too_large.status_code == 413
    assert unsupported_header.status_code == 200
    assert unsupported_payload["error"]["code"] == -32600


def test_mcp_rejects_preinitialization_calls_and_viewer_invocations(settings) -> None:
    secure = _secure_settings(settings)
    app = create_app(secure)
    pre_init_response, pre_init = _call_mcp(
        app,
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
        token="tech-token",
        session_id="missing-session",
    )
    initialized_response, initialized = _call_mcp(
        app,
        {"jsonrpc": "2.0", "id": 2, "method": "initialize", "params": {"protocolVersion": "2025-11-25"}},
        token="tech-token",
    )
    session_id = dict(initialized_response.headers)["mcp-session-id"]
    _call_mcp(
        app,
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        token="tech-token",
        session_id=session_id,
    )
    viewer_response, viewer_call = _call_mcp(
        app,
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "wait.ticket-triage", "arguments": {}},
        },
        token="viewer-token",
        session_id=session_id,
    )

    assert pre_init_response.status_code == 200
    assert pre_init["error"]["code"] == -32000
    assert viewer_response.status_code == 200
    assert viewer_call["result"]["isError"] is True
    assert "technician authority" in viewer_call["result"]["structuredContent"]["error_detail"]


def test_mcp_protocol_validation_and_session_bounds() -> None:
    server = _fake_server()
    context = AuthContext(Role.TECHNICIAN, "token", "acme")

    with pytest.raises(McpProtocolError):
        server.handle([], context=context, session_id=None)
    for message in (
        {},
        {"jsonrpc": "1.0", "method": "ping"},
        {"jsonrpc": "2.0", "method": "ping", "id": True},
        {"jsonrpc": "2.0", "method": "ping", "params": []},
    ):
        response, _ = server.handle(message, context=context, session_id=None)
        assert response["error"]["code"] in {-32600, -32602}

    response, _ = server.handle(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        context=context,
        session_id=None,
    )
    assert response["error"]["code"] == -32602
    response, session_id = server.handle(
        {"jsonrpc": "2.0", "id": 2, "method": "initialize", "params": {"protocolVersion": "future"}},
        context=context,
        session_id=None,
    )
    assert response["result"]["protocolVersion"] == "2025-11-25"
    assert session_id
    response, _ = server.handle(
        {"jsonrpc": "2.0", "id": 3, "method": "initialize", "params": {"protocolVersion": "2025-11-25"}},
        context=context,
        session_id=session_id,
    )
    assert response["error"]["code"] == -32600

    response, _ = server.handle(
        {"jsonrpc": "2.0", "id": 4, "method": "ping"},
        context=context,
        session_id=session_id,
    )
    assert response["error"]["code"] == -32001
    server._sessions[session_id] = True  # noqa: SLF001
    response, _ = server.handle(
        {"jsonrpc": "2.0", "id": 5, "method": "ping"},
        context=context,
        session_id=session_id,
    )
    assert response["result"] == {}
    response, _ = server.handle(
        {"jsonrpc": "2.0", "method": "unknown"},
        context=context,
        session_id=session_id,
    )
    assert response is None
    response, _ = server.handle(
        {"jsonrpc": "2.0", "id": 6, "method": "unknown"},
        context=context,
        session_id=session_id,
    )
    assert response["error"]["code"] == -32601

    server._sessions = {str(index): False for index in range(MAX_MCP_SESSIONS)}  # noqa: SLF001
    _, new_session = server.handle(
        {"jsonrpc": "2.0", "id": 7, "method": "initialize", "params": {"protocolVersion": "2025-03-26"}},
        context=context,
        session_id=None,
    )
    assert len(server._sessions) == MAX_MCP_SESSIONS  # noqa: SLF001
    assert new_session not in {str(index) for index in range(MAX_MCP_SESSIONS)}


@pytest.mark.parametrize("mode", ["key", "value", "exception", "large"])
def test_mcp_tool_validation_errors_are_bounded(mode: str) -> None:
    server = _fake_server(mode)
    context = AuthContext(Role.TECHNICIAN, "token", "acme")
    server._sessions["s"] = True  # noqa: SLF001

    invalid_cases = [
        {"name": "fake-read"},
        {"name": "wait.fake-read", "arguments": []},
        {"name": "wait.unknown"},
        {"name": "wait.fake-read", "arguments": {str(index): index for index in range(65)}},
    ]
    for arguments in invalid_cases:
        with pytest.raises(McpProtocolError):
            server.handle(
                {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": arguments},
                context=context,
                session_id="s",
            )

    response, _ = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "wait.fake-read", "arguments": {"client_id": "beta"}},
        },
        context=context,
        session_id="s",
    )
    assert response["result"]["isError"] is True
    if mode == "large":
        assert response["result"]["structuredContent"]["error_detail"]
    response, _ = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "wait.fake-read", "arguments": {}},
        },
        context=context,
        session_id="s",
    )
    assert response["result"]["isError"] is (mode != "large")


def test_mcp_role_scope_schema_and_origin_helpers() -> None:
    server = _fake_server()
    server._sessions["s"] = True  # noqa: SLF001
    viewer = AuthContext(Role.VIEWER, "token", "acme")
    response, _ = server.handle(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "wait.fake-read"}},
        context=viewer,
        session_id="s",
    )
    assert "technician authority" in response["result"]["structuredContent"]["error_detail"]
    technician = AuthContext(Role.TECHNICIAN, "token", "acme")
    response, _ = server.handle(
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "wait.fake-admin"}},
        context=technician,
        session_id="s",
    )
    assert "administrator authority" in response["result"]["structuredContent"]["error_detail"]
    response, _ = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "wait.fake-read", "arguments": {"client_id": 4}},
        },
        context=technician,
        session_id="s",
    )
    assert "non-empty text" in response["result"]["structuredContent"]["error_detail"]
    no_tenant = AuthContext(Role.TECHNICIAN, "token", None)
    response, _ = server.handle(
        {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "wait.fake-read"}},
        context=no_tenant,
        session_id="s",
    )
    assert "no tenant" in response["result"]["structuredContent"]["error_detail"]
    admin = AuthContext(Role.ADMIN, "token", "acme")
    response, _ = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {"name": "wait.fake-read", "arguments": {"client_id": "beta"}},
        },
        context=admin,
        session_id="s",
    )
    assert response["result"]["isError"] is False

    input_schema = _input_schema({"properties": {"flag": "boolean|garbage", "raw": 3}})
    assert input_schema["properties"]["flag"] == {"type": "boolean"}
    assert _output_schema({"type": "array"})["type"] == "array"
    assert _property_schema({"type": "number"})["type"] == "number"
    assert _property_schema(3)["type"] == "string"
    assert _property_schema("unknown") == {"type": "string"}
    assert _cursor_offset(None) == 0
    with pytest.raises(McpProtocolError):
        _cursor_offset("not-a-cursor")
    with pytest.raises(McpProtocolError):
        _cursor_offset("10001")
    assert _mcp_client_scope(admin, {}) == ("acme", None)
    assert cast_dict([])["status"] == "failed"
    assert origin_allowed(None, "http://test")
    assert origin_allowed("http://test/", "http://test")
    assert origin_allowed("https://allowed.example", "http://test", ("https://allowed.example/",))
    assert origin_allowed("http://localhost:3000", "http://test")
    assert not origin_allowed("ftp://localhost", "http://test")
    error = McpProtocolError(-1, "bad")
    assert protocol_error_response(1, error)["error"]["message"] == "bad"
