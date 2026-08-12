"""A bounded, credential-safe MCP client for optional external servers.

The client is deliberately transport-injected so protocol behavior can be
tested without network access. It owns only MCP lifecycle and tool discovery;
WAIT's existing agent and approval runtime remains the authority for local
execution.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import httpx

from wait_local_agent.reports.renderers import redact_text

MCP_CLIENT_PROTOCOL_VERSION = "2025-11-25"
MCP_CLIENT_MAX_REQUEST_BYTES = 256 * 1024
MCP_CLIENT_MAX_RESPONSE_BYTES = 128 * 1024
MCP_CLIENT_MAX_TOOL_PAGES = 100
MCP_CLIENT_MAX_CURSOR = 10_000
_SUPPORTED_PROTOCOL_VERSIONS = frozenset({MCP_CLIENT_PROTOCOL_VERSION, "2025-03-26"})


class McpClientError(RuntimeError):
    """A safe, operator-facing MCP client failure."""


@dataclass(frozen=True)
class McpClientConfig:
    endpoint: str
    bearer_token: str = ""
    timeout_seconds: float = 20.0
    verify_tls: bool = True
    allowed_hosts: tuple[str, ...] = ()

    def validate(self) -> None:
        endpoint = self.endpoint.strip()
        if not endpoint or len(endpoint) > 2_048:
            raise McpClientError("MCP endpoint must be bounded URL text")
        parsed = urlsplit(endpoint)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise McpClientError("MCP endpoint must use an HTTP(S) URL")
        if parsed.username or parsed.password:
            raise McpClientError("MCP endpoint must not contain embedded credentials")
        if parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise McpClientError("non-local MCP endpoints must use HTTPS")
        host = parsed.hostname.casefold().rstrip(".")
        if host not in {"localhost", "127.0.0.1", "::1"} and host not in {
            value.strip().casefold().rstrip(".")
            for value in self.allowed_hosts
            if value.strip()
        }:
            raise McpClientError("MCP endpoint host is not allowlisted")
        if self.timeout_seconds <= 0 or self.timeout_seconds > 120:
            raise McpClientError("MCP timeout must be between 0 and 120 seconds")
        if any(ord(character) < 32 for character in self.bearer_token):
            raise McpClientError("MCP bearer token contains control characters")


@dataclass(frozen=True)
class McpToolDescriptor:
    name: str
    title: str
    description: str
    input_schema: dict[str, object]
    output_schema: dict[str, object]
    annotations: dict[str, object]


@dataclass(frozen=True)
class McpToolCallResult:
    content: list[object]
    structured_content: dict[str, Any] | None
    is_error: bool


class McpClient:
    """Call one MCP server using the Streamable HTTP JSON response mode."""

    def __init__(self, config: McpClientConfig, *, transport: httpx.BaseTransport | None = None) -> None:
        config.validate()
        self.config = config
        self._transport = transport
        self._session_id: str | None = None
        self._protocol_version: str | None = None
        self._last_session_id: str | None = None

    @property
    def session_id(self) -> str | None:
        return self._session_id

    @property
    def protocol_version(self) -> str | None:
        return self._protocol_version

    def initialize(self, *, client_name: str = "wait-local-agent") -> str:
        if self._session_id is not None:
            raise McpClientError("MCP client session is already initialized")
        if not client_name.strip() or len(client_name) > 120:
            raise McpClientError("MCP client name must be bounded text")
        response = self._request(
            "initialize",
            {
                "protocolVersion": MCP_CLIENT_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": client_name.strip(), "version": "1.0"},
            },
            request_id=1,
        )
        result = _result_object(response)
        version = result.get("protocolVersion")
        if not isinstance(version, str) or version not in _SUPPORTED_PROTOCOL_VERSIONS:
            raise McpClientError("MCP server negotiated an unsupported protocol version")
        session_id = self._last_session_id
        if not session_id:
            raise McpClientError("MCP server did not return a session identifier")
        self._session_id = session_id
        self._protocol_version = version
        try:
            self._request("notifications/initialized", {}, request_id=None)
        except Exception:
            self._session_id = None
            self._protocol_version = None
            raise
        return session_id

    def list_tools(self) -> list[McpToolDescriptor]:
        self._require_session()
        tools: list[McpToolDescriptor] = []
        cursor: str | None = None
        for _ in range(MCP_CLIENT_MAX_TOOL_PAGES):
            params: dict[str, object] = {}
            if cursor is not None:
                params["cursor"] = cursor
            response = self._request("tools/list", params, request_id=2)
            result = _result_object(response)
            raw_tools = result.get("tools")
            if not isinstance(raw_tools, list):
                raise McpClientError("MCP server returned an invalid tool catalog")
            for raw_tool in raw_tools:
                tools.append(_tool_descriptor(raw_tool))
            next_cursor = result.get("nextCursor")
            if next_cursor is None:
                return tools
            if not isinstance(next_cursor, str) or not next_cursor.isdigit():
                raise McpClientError("MCP server returned an invalid tool cursor")
            if int(next_cursor) > MCP_CLIENT_MAX_CURSOR or next_cursor == cursor:
                raise McpClientError("MCP server returned an unbounded tool cursor")
            cursor = next_cursor
        raise McpClientError("MCP server returned too many tool pages")

    def call_tool(self, name: str, arguments: dict[str, object] | None = None) -> McpToolCallResult:
        self._require_session()
        if not name.strip() or len(name) > 200:
            raise McpClientError("MCP tool name must be bounded text")
        payload = {} if arguments is None else arguments
        if not isinstance(payload, dict) or len(payload) > 64:
            raise McpClientError("MCP tool arguments are too large")
        response = self._request(
            "tools/call",
            {"name": name, "arguments": payload},
            request_id=3,
        )
        result = _result_object(response)
        content = result.get("content")
        if not isinstance(content, list):
            raise McpClientError("MCP server returned an invalid tool result")
        structured = result.get("structuredContent")
        if structured is not None and not isinstance(structured, dict):
            raise McpClientError("MCP server returned invalid structured tool content")
        is_error = result.get("isError", False)
        if not isinstance(is_error, bool):
            raise McpClientError("MCP server returned an invalid tool error flag")
        return McpToolCallResult(content, structured, is_error)

    def _require_session(self) -> None:
        if self._session_id is None:
            raise McpClientError("MCP client must initialize before use")

    def _request(
        self,
        method: str,
        params: dict[str, object],
        *,
        request_id: int | None,
    ) -> dict[str, object] | None:
        payload: dict[str, object] = {"jsonrpc": "2.0", "method": method, "params": params}
        if request_id is not None:
            payload["id"] = request_id
        encoded = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        if len(encoded) > MCP_CLIENT_MAX_REQUEST_BYTES:
            raise McpClientError("MCP request exceeds the bounded size")
        headers = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            "MCP-Protocol-Version": self._protocol_version or MCP_CLIENT_PROTOCOL_VERSION,
        }
        if self._session_id:
            headers["MCP-Session-Id"] = self._session_id
        if self.config.bearer_token:
            headers["Authorization"] = f"Bearer {self.config.bearer_token}"
        self._last_session_id = None
        try:
            with httpx.Client(
                timeout=self.config.timeout_seconds,
                follow_redirects=False,
                verify=self.config.verify_tls,
                transport=self._transport,
            ) as client:
                response = client.post(self.config.endpoint.strip(), content=encoded, headers=headers)
        except httpx.TimeoutException as exc:
            raise McpClientError("MCP server request timed out") from exc
        except httpx.HTTPError as exc:
            raise McpClientError("MCP server request failed") from exc
        if response.status_code not in {200, 202}:
            raise McpClientError(f"MCP server returned HTTP {response.status_code}")
        if len(response.content) > MCP_CLIENT_MAX_RESPONSE_BYTES:
            raise McpClientError("MCP server response exceeds the bounded size")
        session_id = response.headers.get("MCP-Session-Id")
        if session_id:
            if len(session_id) > 256 or any(ord(character) < 33 for character in session_id):
                raise McpClientError("MCP server returned an invalid session identifier")
            self._last_session_id = session_id
        if not response.content:
            return None
        try:
            decoded = response.json()
        except (ValueError, json.JSONDecodeError) as exc:
            raise McpClientError("MCP server returned invalid JSON") from exc
        if not isinstance(decoded, dict) or decoded.get("jsonrpc") != "2.0":
            raise McpClientError("MCP server returned an invalid JSON-RPC response")
        error = decoded.get("error")
        if isinstance(error, dict):
            message = error.get("message", "MCP server returned an error")
            raise McpClientError(redact_text(str(message)))
        result = decoded.get("result")
        if not isinstance(result, dict):
            raise McpClientError("MCP server returned no JSON-RPC result")
        return result


def _result_object(response: dict[str, object] | None) -> dict[str, object]:
    if not isinstance(response, dict):
        raise McpClientError("MCP server returned no result")
    return response


def _tool_descriptor(value: object) -> McpToolDescriptor:
    if not isinstance(value, dict):
        raise McpClientError("MCP server returned an invalid tool descriptor")
    name = value.get("name")
    if not isinstance(name, str) or not name.strip() or len(name) > 200:
        raise McpClientError("MCP server returned an invalid tool name")
    title = value.get("title", name)
    description = value.get("description", "")
    if not isinstance(title, str) or not isinstance(description, str):
        raise McpClientError("MCP server returned invalid tool metadata")
    input_schema = value.get("inputSchema", {})
    output_schema = value.get("outputSchema", {})
    annotations = value.get("annotations", {})
    if not isinstance(input_schema, dict) or not isinstance(output_schema, dict) or not isinstance(annotations, dict):
        raise McpClientError("MCP server returned invalid tool schemas")
    return McpToolDescriptor(name, title, description, input_schema, output_schema, annotations)
