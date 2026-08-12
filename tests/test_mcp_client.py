from __future__ import annotations

import json
from typing import cast

import httpx
import pytest

from wait_local_agent.mcp_client import (
    MCP_CLIENT_MAX_CURSOR,
    MCP_CLIENT_MAX_RESPONSE_BYTES,
    McpClient,
    McpClientConfig,
    McpClientError,
)


def _response(result: dict[str, object], *, session_id: str | None = None) -> httpx.Response:
    headers = {"Content-Type": "application/json"}
    if session_id:
        headers["MCP-Session-Id"] = session_id
    return httpx.Response(200, headers=headers, json={"jsonrpc": "2.0", "id": 1, "result": result})


def _initialized_client(handler) -> McpClient:
    client = McpClient(
        McpClientConfig("http://localhost:8791"),
        transport=httpx.MockTransport(handler),
    )
    client.initialize()
    assert client.session_id == "session-1"
    return client


def test_mcp_client_lifecycle_catalog_pagination_and_call() -> None:
    calls: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        calls.append(payload)
        method = payload["method"]
        if method == "initialize":
            return _response({"protocolVersion": "2025-11-25", "capabilities": {}}, session_id="session-1")
        if method == "notifications/initialized":
            return httpx.Response(202)
        if method == "tools/list" and payload["params"].get("cursor") is None:
            return _response(
                {
                    "tools": [
                        {
                            "name": "workiq.search",
                            "description": "Search bounded context",
                            "inputSchema": {"type": "object"},
                        }
                    ],
                    "nextCursor": "1",
                }
            )
        if method == "tools/list":
            return _response({"tools": [{"name": "workiq.get", "title": "Get"}]})
        return _response(
            {
                "content": [{"type": "text", "text": "ok"}],
                "structuredContent": {"status": "success"},
                "isError": False,
            }
        )

    client = McpClient(
        McpClientConfig("https://mcp.example.test", bearer_token="secret"),
        transport=httpx.MockTransport(handler),
    )
    assert client.initialize() == "session-1"
    tools = client.list_tools()
    result = client.call_tool("workiq.search", {"query": "onboarding"})

    assert client.protocol_version == "2025-11-25"
    assert [tool.name for tool in tools] == ["workiq.search", "workiq.get"]
    assert result.structured_content == {"status": "success"}
    assert result.is_error is False
    assert calls[1]["method"] == "notifications/initialized"
    assert calls[-1]["method"] == "tools/call"


def test_mcp_client_rejects_invalid_config_and_lifecycle_use() -> None:
    invalid = [
        "",
        "ftp://mcp.example.test",
        "http://mcp.example.test",
        "https://user:password@mcp.example.test",
    ]
    for endpoint in invalid:
        with pytest.raises(McpClientError):
            McpClient(McpClientConfig(endpoint))
    with pytest.raises(McpClientError):
        McpClient(McpClientConfig("https://mcp.example.test", timeout_seconds=0))
    with pytest.raises(McpClientError):
        McpClient(McpClientConfig("https://mcp.example.test", bearer_token="bad\nvalue"))

    client = McpClient(
        McpClientConfig("http://127.0.0.1:8791"),
        transport=httpx.MockTransport(lambda _: httpx.Response(500)),
    )
    with pytest.raises(McpClientError, match="initialize before use"):
        client.list_tools()
    with pytest.raises(McpClientError, match="initialize before use"):
        client.call_tool("tool")
    with pytest.raises(McpClientError, match="bounded text"):
        McpClient(McpClientConfig("https://mcp.example.test")).initialize(client_name=" ")
    assert McpClient(McpClientConfig("http://localhost:8791")).session_id is None


def test_mcp_client_maps_remote_protocol_and_transport_failures() -> None:
    def error_handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "error": {"message": "secret token leaked"}})

    client = McpClient(
        McpClientConfig("http://localhost:8791"),
        transport=httpx.MockTransport(error_handler),
    )
    with pytest.raises(McpClientError, match="secret token leaked"):
        client.initialize()

    def timeout_handler(_: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timeout")

    timeout_client = McpClient(
        McpClientConfig("http://localhost:8791"),
        transport=httpx.MockTransport(timeout_handler),
    )
    with pytest.raises(McpClientError, match="timed out"):
        timeout_client.initialize()


@pytest.mark.parametrize(
    "payload",
    [
        {"jsonrpc": "2.0", "id": 1, "result": []},
        {"jsonrpc": "1.0", "id": 1, "result": {}},
        {"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": "invalid"}},
    ],
)
def test_mcp_client_rejects_malformed_server_responses(payload: dict[str, object]) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload, headers={"MCP-Session-Id": "session-1"})

    client = McpClient(
        McpClientConfig("http://localhost:8791"),
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(McpClientError):
        client.initialize()


def test_mcp_client_bounds_payloads_and_tool_results() -> None:
    client = McpClient(
        McpClientConfig("http://localhost:8791"),
        transport=httpx.MockTransport(
            lambda _: _response({"protocolVersion": "2025-11-25"}, session_id="session-1")
        ),
    )
    assert client.initialize() == "session-1"  # notification gets the same mock response and is ignored
    with pytest.raises(McpClientError, match="already initialized"):
        client.initialize()
    with pytest.raises(McpClientError, match="bounded size"):
        client.call_tool("tool", {"value": "x" * MCP_CLIENT_MAX_RESPONSE_BYTES * 3})

    def oversized(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x" * (MCP_CLIENT_MAX_RESPONSE_BYTES + 1))

    oversized_client = McpClient(
        McpClientConfig("http://localhost:8791"),
        transport=httpx.MockTransport(oversized),
    )
    with pytest.raises(McpClientError, match="response exceeds"):
        oversized_client.initialize()


def test_mcp_client_rejects_tool_catalog_and_call_shapes() -> None:
    def init_and_list(request: httpx.Request) -> httpx.Response:
        method = json.loads(request.content)["method"]
        if method == "initialize":
            return _response({"protocolVersion": "2025-11-25"}, session_id="session-1")
        if method == "notifications/initialized":
            return httpx.Response(202)
        return _response({"tools": "not-a-list"})

    client = _initialized_client(init_and_list)
    with pytest.raises(McpClientError, match="invalid tool catalog"):
        client.list_tools()
    with pytest.raises(McpClientError, match="bounded text"):
        client.call_tool(" ")
    with pytest.raises(McpClientError, match="bounded text"):
        client.call_tool("x" * 201)
    with pytest.raises(McpClientError, match="too large"):
        client.call_tool("tool", cast(dict[str, object], []))

    def invalid_result(request: httpx.Request) -> httpx.Response:
        method = json.loads(request.content)["method"]
        if method == "initialize":
            return _response({"protocolVersion": "2025-11-25"}, session_id="session-1")
        if method == "notifications/initialized":
            return httpx.Response(202)
        return _response({"content": "invalid"})

    invalid_client = _initialized_client(invalid_result)
    with pytest.raises(McpClientError, match="invalid tool result"):
        invalid_client.call_tool("tool")

    def bad_structured(request: httpx.Request) -> httpx.Response:
        method = json.loads(request.content)["method"]
        if method == "initialize":
            return _response({"protocolVersion": "2025-11-25"}, session_id="session-1")
        if method == "notifications/initialized":
            return httpx.Response(202)
        return _response({"content": [], "structuredContent": [], "isError": "yes"})

    bad_client = _initialized_client(bad_structured)
    with pytest.raises(McpClientError, match="structured tool content"):
        bad_client.call_tool("tool")

    def bad_error_flag(request: httpx.Request) -> httpx.Response:
        method = json.loads(request.content)["method"]
        if method == "initialize":
            return _response({"protocolVersion": "2025-11-25"}, session_id="session-1")
        if method == "notifications/initialized":
            return httpx.Response(202)
        return _response({"content": [], "isError": 1})

    flag_client = _initialized_client(bad_error_flag)
    with pytest.raises(McpClientError, match="error flag"):
        flag_client.call_tool("tool")


@pytest.mark.parametrize(
    "catalog_result",
    [
        {"tools": [{"name": ""}]},
        {"tools": [{"name": 4}]},
        {"tools": [{"name": "tool", "title": 4}]},
        {"tools": [{"name": "tool", "inputSchema": []}]},
        {"tools": [4]},
        {"tools": [], "nextCursor": "not-numeric"},
        {"tools": [], "nextCursor": str(MCP_CLIENT_MAX_CURSOR + 1)},
        {"tools": [], "nextCursor": "1"},
    ],
)
def test_mcp_client_rejects_malformed_tool_descriptors_and_cursors(catalog_result: dict[str, object]) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        method = json.loads(request.content)["method"]
        if method == "initialize":
            return _response({"protocolVersion": "2025-11-25"}, session_id="session-1")
        if method == "notifications/initialized":
            return httpx.Response(202)
        return _response(catalog_result)

    client = _initialized_client(handler)
    with pytest.raises(McpClientError):
        client.list_tools()


def test_mcp_client_rejects_repeated_cursor_and_too_many_pages() -> None:
    def repeated(request: httpx.Request) -> httpx.Response:
        method = json.loads(request.content)["method"]
        if method == "initialize":
            return _response({"protocolVersion": "2025-11-25"}, session_id="session-1")
        if method == "notifications/initialized":
            return httpx.Response(202)
        return _response({"tools": [], "nextCursor": "1"})

    with pytest.raises(McpClientError, match="unbounded tool cursor"):
        _initialized_client(repeated).list_tools()

    def many_pages(request: httpx.Request) -> httpx.Response:
        method = json.loads(request.content)["method"]
        if method == "initialize":
            return _response({"protocolVersion": "2025-11-25"}, session_id="session-1")
        if method == "notifications/initialized":
            return httpx.Response(202)
        cursor = json.loads(request.content)["params"].get("cursor", "0")
        return _response({"tools": [], "nextCursor": str(int(cursor) + 1)})

    with pytest.raises(McpClientError, match="too many tool pages"):
        _initialized_client(many_pages).list_tools()


def test_mcp_client_rejects_http_and_json_response_failures() -> None:
    def http_error(_: httpx.Request) -> httpx.Response:
        raise httpx.NetworkError("network")

    with pytest.raises(McpClientError, match="request failed"):
        McpClient(
            McpClientConfig("http://localhost:8791"),
            transport=httpx.MockTransport(http_error),
        ).initialize()

    with pytest.raises(McpClientError, match="HTTP 500"):
        McpClient(
            McpClientConfig("http://localhost:8791"),
            transport=httpx.MockTransport(lambda _: httpx.Response(500)),
        ).initialize()

    def invalid_json(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not-json")

    with pytest.raises(McpClientError, match="invalid JSON"):
        McpClient(
            McpClientConfig("http://localhost:8791"),
            transport=httpx.MockTransport(invalid_json),
        ).initialize()

    def invalid_session(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"{}", headers={"MCP-Session-Id": "bad\x00session"})

    with pytest.raises(McpClientError, match="session identifier"):
        McpClient(
            McpClientConfig("http://localhost:8791"),
            transport=httpx.MockTransport(invalid_session),
        ).initialize()


def test_mcp_client_resets_after_notification_failure_and_requires_session_id() -> None:
    def no_session(_: httpx.Request) -> httpx.Response:
        return _response({"protocolVersion": "2025-11-25"})

    with pytest.raises(McpClientError, match="session identifier"):
        McpClient(
            McpClientConfig("http://localhost:8791"),
            transport=httpx.MockTransport(no_session),
        ).initialize()

    calls = 0

    def notification_failure(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return _response({"protocolVersion": "2025-11-25"}, session_id="session-1")
        return httpx.Response(500)

    client = McpClient(
        McpClientConfig("http://localhost:8791"),
        transport=httpx.MockTransport(notification_failure),
    )
    with pytest.raises(McpClientError, match="HTTP 500"):
        client.initialize()
    assert client.session_id is None

    with pytest.raises(McpClientError, match="no result"):
        McpClient(
            McpClientConfig("http://localhost:8791"),
            transport=httpx.MockTransport(lambda _: httpx.Response(202)),
        ).initialize()
