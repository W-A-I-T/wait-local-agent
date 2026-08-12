from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from fastapi.testclient import TestClient

from wait_local_agent.agents import AgentService, ToolDefinition
from wait_local_agent.api.app import create_app
from wait_local_agent.config import Settings
from wait_local_agent.mcp_server import (
    McpProtocolError,
    _call_result,
    _client_scope,
    _cursor_start,
    _object_schema,
    error_response,
    handle_message,
    validate_transport_headers,
)
from wait_local_agent.rbac import AuthContext, Role
from wait_local_agent.smart_actions import ActionResult, SmartActionService
from wait_local_agent.store import Store


def _secure_settings(
    settings: Settings,
    *,
    admin_token: str = "admin-token",
    tech_token: str = "tech-token",
    viewer_token: str = "viewer-token",
    mcp_allowed_origins: tuple[str, ...] = (),
) -> Settings:
    return replace(
        settings,
        demo_mode=False,
        mcp_enabled=True,
        client_id="acme",
        admin_token=admin_token,
        tech_token=tech_token,
        viewer_token=viewer_token,
        mcp_allowed_origins=mcp_allowed_origins,
    )


def _seed(store: Store) -> None:
    store.ingest_ticket_file(Path("examples/sample_tickets/tickets.json"))
    with store._connect() as connection:  # noqa: SLF001
        connection.execute("update tickets set client_id = ?", ("acme",))


def _headers(token: str = "tech-token", *, protocol: bool = True) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    if protocol:
        headers["MCP-Protocol-Version"] = "2025-06-18"
    return headers


def _message(method: str, request_id: int = 1, **params: object) -> dict[str, object]:
    return {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}


def test_mcp_is_opt_in_and_requires_real_authentication(settings) -> None:
    disabled = TestClient(create_app(settings))
    assert disabled.post("/mcp", headers=_headers(), json=_message("ping")).status_code == 404

    no_tokens = _secure_settings(settings, admin_token="", tech_token="", viewer_token="")
    unavailable = TestClient(create_app(no_tokens))
    response = unavailable.post("/mcp", headers=_headers(), json=_message("ping"))
    assert response.status_code == 503
    assert "bearer tokens" in response.json()["detail"]


def test_mcp_initialize_tools_and_stateless_headers(settings) -> None:
    secure = _secure_settings(settings)
    client = TestClient(create_app(secure))

    initialized = client.post(
        "/mcp",
        headers=_headers(protocol=False),
        json=_message(
            "initialize",
            protocolVersion="2025-06-18",
            capabilities={},
            clientInfo={"name": "test-client", "version": "1"},
        ),
    )
    assert initialized.status_code == 200
    assert initialized.json()["result"]["protocolVersion"] == "2025-06-18"
    assert initialized.json()["result"]["capabilities"]["tools"]["listChanged"] is False

    tools = client.post("/mcp", headers=_headers(), json=_message("tools/list"))
    assert tools.status_code == 200
    tool_list = tools.json()["result"]["tools"]
    tool_ids = {tool["name"] for tool in tool_list}
    assert "m365-mail-message-delete" not in tool_ids
    for tool in tool_list:
        assert tool["inputSchema"]["type"] == "object"
        assert isinstance(tool["inputSchema"]["properties"], dict)
        assert all(isinstance(value, dict) for value in tool["inputSchema"]["properties"].values())
        assert "wait.local-agent/requiredRole" in tool["_meta"]
    assert tools.json()["result"]["nextCursor"]
    next_page = client.post(
        "/mcp",
        headers=_headers(),
        json=_message("tools/list", cursor=tools.json()["result"]["nextCursor"]),
    )
    assert next_page.status_code == 200
    assert "ticket-triage" in {tool["name"] for tool in next_page.json()["result"]["tools"]}

    missing_header = client.post(
        "/mcp",
        headers=_headers(protocol=False),
        json=_message("tools/list"),
    )
    assert missing_header.status_code == 400
    assert missing_header.json()["error"]["code"] == -32600

    viewer = TestClient(create_app(secure))
    viewer_tools = viewer.post(
        "/mcp",
        headers=_headers("viewer-token"),
        json=_message("tools/list"),
    )
    assert viewer_tools.status_code == 200
    assert viewer_tools.json()["result"]["tools"]
    assert all(
        tool["_meta"]["wait.local-agent/requiredRole"] == "viewer"
        for tool in viewer_tools.json()["result"]["tools"]
    )


def test_mcp_call_preserves_tenant_scope_and_approval_gate(settings) -> None:
    secure = _secure_settings(settings)
    _seed(Store(secure.data_path))
    client = TestClient(create_app(secure))

    read_result = client.post(
        "/mcp",
        headers=_headers(),
        json=_message(
            "tools/call",
            name="ticket-triage",
            arguments={"ticket_id": "TCK-1001"},
        ),
    )
    assert read_result.status_code == 200
    read_payload = read_result.json()["result"]
    assert read_payload["isError"] is False
    assert read_payload["structuredContent"]["status"] == "success"
    assert read_payload["structuredContent"]["output"]["ticket_id"] == "TCK-1001"

    foreign = client.post(
        "/mcp",
        headers=_headers(),
        json=_message(
            "tools/call",
            name="ticket-triage",
            arguments={"ticket_id": "TCK-1001", "client_id": "other"},
        ),
    )
    assert foreign.status_code == 400
    assert foreign.json()["error"]["code"] == -32001

    pending = client.post(
        "/mcp",
        headers=_headers(),
        json=_message(
            "tools/call",
            name="communication-draft",
            arguments={
                "channel": "ticket_note",
                "recipient": "TCK-1001",
                "body": "Please confirm the approved next step.",
                "ticket_id": "TCK-1001",
            },
        ),
    )
    assert pending.status_code == 200
    pending_payload = pending.json()["result"]
    assert pending_payload["isError"] is False
    assert pending_payload["structuredContent"]["status"] == "pending_approval"
    assert pending_payload["structuredContent"]["approval_id"] is not None


def test_mcp_rejects_bad_origin_and_sanitizes_protocol_errors(settings) -> None:
    secure = _secure_settings(settings, mcp_allowed_origins=("https://trusted.example",))
    client = TestClient(create_app(secure))

    bad_origin = client.post(
        "/mcp",
        headers={**_headers(), "Origin": "https://attacker.example"},
        json=_message("ping"),
    )
    assert bad_origin.status_code == 403
    assert "attacker" not in bad_origin.text

    unknown = client.post(
        "/mcp",
        headers=_headers(),
        json=_message("tools/call", name="not-a-real-tool", arguments={}),
    )
    assert unknown.status_code == 400
    assert unknown.json()["error"]["message"] == "tool is not available"
    assert "not-a-real-tool" not in json.dumps(unknown.json())

    assert client.get("/mcp", headers=_headers()).status_code == 405
    notification = client.post(
        "/mcp",
        headers=_headers(),
        json={"jsonrpc": "2.0", "method": "notifications/initialized"},
    )
    assert notification.status_code == 202


def test_mcp_result_redaction_and_generic_failure_message() -> None:
    result = _call_result(
        ActionResult(
            status="failed",
            output={"access_token": "secret-token", "nested": {"password": "secret-password"}},
            error_detail="internal provider response with secret-token",
        )
    )
    encoded = json.dumps(result)
    assert "secret-token" not in encoded
    assert "secret-password" not in encoded
    assert "internal provider response" not in encoded
    structured = cast(dict[str, object], result["structuredContent"])
    assert structured["error"] == "tool execution failed"


def test_mcp_protocol_and_boundary_helpers_cover_failure_paths() -> None:
    context = AuthContext(Role.TECHNICIAN, "token", "acme")
    tool = ToolDefinition(
        id="test-tool",
        name="Test tool",
        description="A test tool",
        input_schema={"type": "object", "properties": {"client_id": {"type": "string"}}},
        output_schema={"value": "string", "note": "free-form text"},
        risk_level="low",
        required_role="technician",
        approval_required=False,
        access_mode="read",
        approval_expiry_seconds=3600,
    )
    calls: list[dict[str, object]] = []

    def invoke(*args: object, **kwargs: object) -> ActionResult:
        calls.append({"args": args, "kwargs": kwargs})
        return ActionResult(status="success", output={"ok": True})

    agent_service = cast(AgentService, SimpleNamespace(list_tools=lambda: [tool]))
    smart_actions = cast(
        SmartActionService,
        SimpleNamespace(describe=lambda _: SimpleNamespace(), invoke=invoke),
    )

    response = handle_message(
        {"jsonrpc": "2.0", "id": "x", "method": "ping"},
        context=context,
        agent_service=agent_service,
        smart_action_service=smart_actions,
    )
    assert response == {"jsonrpc": "2.0", "id": "x", "result": {}}
    assert handle_message(
        {"jsonrpc": "2.0", "method": "ping"},
        context=context,
        agent_service=agent_service,
        smart_action_service=smart_actions,
    ) is None
    assert handle_message(
        {"jsonrpc": "2.0", "method": "unknown"},
        context=context,
        agent_service=agent_service,
        smart_action_service=smart_actions,
    ) is None

    call = handle_message(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "test-tool", "arguments": {}},
        },
        context=context,
        agent_service=agent_service,
        smart_action_service=smart_actions,
    )
    assert call is not None
    call_kwargs = cast(dict[str, object], calls[0]["kwargs"])
    assert call_kwargs["client_id"] == "acme"

    with pytest.raises(McpProtocolError, match="method not found"):
        handle_message(
            {"jsonrpc": "2.0", "id": 8, "method": "unknown"},
            context=context,
            agent_service=agent_service,
            smart_action_service=smart_actions,
        )
    assert handle_message(
        {"jsonrpc": "2.0", "method": "tools/list"},
        context=AuthContext(Role.TECHNICIAN, "token", None),
        agent_service=agent_service,
        smart_action_service=smart_actions,
    ) is None

    missing_action = cast(
        SmartActionService,
        SimpleNamespace(describe=lambda _: (_ for _ in ()).throw(KeyError("missing")), invoke=invoke),
    )
    with pytest.raises(McpProtocolError, match="not available"):
        handle_message(
            {
                "jsonrpc": "2.0",
                "id": 9,
                "method": "tools/call",
                "params": {"name": "test-tool"},
            },
            context=context,
            agent_service=agent_service,
            smart_action_service=missing_action,
        )

    no_tenant_admin = AuthContext(Role.ADMIN, "token", None)
    with pytest.raises(McpProtocolError, match="client_id is required"):
        handle_message(
            {
                "jsonrpc": "2.0",
                "id": 10,
                "method": "tools/call",
                "params": {"name": "test-tool"},
            },
            context=no_tenant_admin,
            agent_service=agent_service,
            smart_action_service=smart_actions,
        )

    failing_actions = cast(
        SmartActionService,
        SimpleNamespace(
            describe=lambda _: SimpleNamespace(),
            invoke=lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("internal")),
        ),
    )
    with pytest.raises(McpProtocolError, match="invocation failed"):
        handle_message(
            {
                "jsonrpc": "2.0",
                "id": 11,
                "method": "tools/call",
                "params": {"name": "test-tool"},
            },
            context=context,
            agent_service=agent_service,
            smart_action_service=failing_actions,
        )

    with pytest.raises(McpProtocolError, match="Mcp-Method"):
        validate_transport_headers(
            {"method": "ping"}, protocol_version="2025-06-18", mcp_method="tools/list", mcp_name=None
        )
    with pytest.raises(McpProtocolError, match="Mcp-Name"):
        validate_transport_headers(
            {"method": "tools/call", "params": {"name": "test-tool"}},
            protocol_version="2025-06-18",
            mcp_method=None,
            mcp_name="other-tool",
        )
    with pytest.raises(McpProtocolError, match="unsupported MCP protocol"):
        handle_message(
            {"jsonrpc": "2.0", "id": 3, "method": "initialize", "params": {"protocolVersion": "old"}},
            context=context,
            agent_service=agent_service,
            smart_action_service=smart_actions,
        )
    for invalid in (None, {"jsonrpc": "1.0", "method": "ping"}, {"jsonrpc": "2.0", "method": "ping", "id": True}):
        with pytest.raises(McpProtocolError):
            handle_message(
                invalid,
                context=context,
                agent_service=agent_service,
                smart_action_service=smart_actions,
            )

    with pytest.raises(McpProtocolError, match="requires a tool name"):
        handle_message(
            {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {}},
            context=context,
            agent_service=agent_service,
            smart_action_service=smart_actions,
        )
    with pytest.raises(McpProtocolError, match="arguments must be an object"):
        handle_message(
            {"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "test-tool", "arguments": []}},
            context=context,
            agent_service=agent_service,
            smart_action_service=smart_actions,
        )
    with pytest.raises(McpProtocolError, match="client_id must be a string"):
        handle_message(
            {
                "jsonrpc": "2.0",
                "id": 6,
                "method": "tools/call",
                "params": {"name": "test-tool", "arguments": {"client_id": 1}},
            },
            context=context,
            agent_service=agent_service,
            smart_action_service=smart_actions,
        )

    admin_tool = replace(tool, required_role="admin")
    admin_agent = cast(AgentService, SimpleNamespace(list_tools=lambda: [admin_tool]))
    with pytest.raises(McpProtocolError, match="not authorized"):
        handle_message(
            {"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": {"name": "test-tool"}},
            context=context,
            agent_service=admin_agent,
            smart_action_service=smart_actions,
        )
    with pytest.raises(McpProtocolError, match="no tenant"):
        _client_scope(AuthContext(Role.TECHNICIAN, "token", None), None)
    assert _client_scope(AuthContext(Role.ADMIN, "token", "default"), None) == "default"
    assert _cursor_start(None) == 0
    with pytest.raises(McpProtocolError, match="cursor"):
        _cursor_start("bad")
    object_schema = _object_schema(
        {
            "type": "object",
            "properties": {"note": "string", "count": {"type": "integer"}},
            "required": ["missing"],
        }
    )
    schema_properties = cast(dict[str, object], object_schema["properties"])
    assert schema_properties["missing"] == {"type": "string"}
    assert error_response({}, McpProtocolError(-1, "safe"))["id"] is None
