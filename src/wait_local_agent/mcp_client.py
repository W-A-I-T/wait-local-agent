"""Bounded outbound MCP client for explicitly configured remote servers.

The client is deliberately a discovery-and-explicit-call adapter, not an
automatic remote-tool registry. Remote metadata is treated as untrusted, the
target host must be allowlisted, and HTTP probing must be enabled explicitly.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Literal, cast
from urllib.parse import SplitResult, urlsplit
from uuid import uuid4

import httpx

from wait_local_agent.config import Settings
from wait_local_agent.reports.renderers import redact_text, redact_value

MCP_CLIENT_MAX_RESPONSE_BYTES = 512 * 1024
MCP_CLIENT_MAX_REQUEST_BYTES = 128 * 1024
MCP_CLIENT_MAX_TOOLS = 500
MCP_CLIENT_MAX_PAGES = 20
MCP_CLIENT_MAX_TOOL_NAME_LENGTH = 200
MCP_CLIENT_MAX_DESCRIPTION_LENGTH = 2_000
MCP_CLIENT_MAX_ARGUMENTS_LENGTH = 64 * 1024
MCP_CLIENT_PROTOCOL_VERSION = "2025-06-18"

McpClientStatus = Literal["ready", "blocked", "not_configured", "failed", "error"]


@dataclass(frozen=True)
class McpClientResponse:
    status: McpClientStatus
    message: str
    result: dict[str, object] = field(default_factory=dict)


class McpClientError(ValueError):
    """Internal configuration or protocol error with a safe public message."""


class McpClient:
    """Call one explicitly configured Streamable HTTP MCP server."""

    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.settings = settings
        self.transport = transport
        self._protocol_version: str | None = None
        self._server_info: dict[str, object] = {}

    def initialize(self) -> McpClientResponse:
        response = self._request(
            "initialize",
            {
                "protocolVersion": MCP_CLIENT_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": self.settings.mcp_client_name, "version": "1.1.1"},
            },
            initialize=True,
        )
        if response.status == "ready":
            protocol_version = response.result.get("protocolVersion")
            if not isinstance(protocol_version, str) or not protocol_version.strip():
                return McpClientResponse("failed", "remote MCP returned an invalid protocol version")
            server_info = response.result.get("serverInfo")
            if not isinstance(server_info, dict):
                return McpClientResponse("failed", "remote MCP returned invalid server metadata")
            self._protocol_version = protocol_version
            self._server_info = cast(dict[str, object], redact_value(server_info))
        return response

    def list_tools(self) -> McpClientResponse:
        initialized = self._ensure_initialized()
        if initialized.status != "ready":
            return initialized
        tools: list[dict[str, object]] = []
        cursor: str | None = None
        seen_cursors: set[str] = set()
        for _ in range(MCP_CLIENT_MAX_PAGES):
            params: dict[str, object] = {} if cursor is None else {"cursor": cursor}
            response = self._request("tools/list", params)
            if response.status != "ready":
                return response
            page = response.result.get("tools")
            if not isinstance(page, list):
                return McpClientResponse("failed", "remote MCP returned an invalid tool page")
            for raw_tool in page:
                if len(tools) >= MCP_CLIENT_MAX_TOOLS:
                    break
                normalized = _normalize_remote_tool(raw_tool)
                if normalized is not None:
                    tools.append(normalized)
            if len(tools) >= MCP_CLIENT_MAX_TOOLS:
                break
            next_cursor = response.result.get("nextCursor")
            if next_cursor is None:
                break
            if not isinstance(next_cursor, str) or not next_cursor or next_cursor in seen_cursors:
                return McpClientResponse("failed", "remote MCP returned an invalid pagination cursor")
            seen_cursors.add(next_cursor)
            cursor = next_cursor
        else:
            return McpClientResponse("failed", "remote MCP pagination exceeded the safety bound")
        return McpClientResponse(
            "ready",
            "remote MCP tools discovered",
            {
                "server": self._server_info,
                "tools": tools,
                "untrusted_remote_metadata": True,
            },
        )

    def call_tool(self, name: str, arguments: dict[str, object] | None = None) -> McpClientResponse:
        normalized_name = _tool_name(name)
        if normalized_name is None:
            return McpClientResponse("failed", "remote MCP tool name is invalid")
        if arguments is not None and not isinstance(arguments, dict):
            return McpClientResponse("failed", "remote MCP tool arguments must be an object")
        payload = arguments or {}
        try:
            encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        except (TypeError, ValueError):
            return McpClientResponse("failed", "remote MCP tool arguments are not serializable")
        if len(encoded.encode("utf-8")) > MCP_CLIENT_MAX_ARGUMENTS_LENGTH:
            return McpClientResponse("failed", "remote MCP tool arguments are too large")
        initialized = self._ensure_initialized()
        if initialized.status != "ready":
            return initialized
        return self._request("tools/call", {"name": normalized_name, "arguments": payload})

    def _ensure_initialized(self) -> McpClientResponse:
        if self._protocol_version is not None:
            return McpClientResponse("ready", "remote MCP client is initialized")
        return self.initialize()

    def _request(
        self,
        method: str,
        params: dict[str, object],
        *,
        initialize: bool = False,
    ) -> McpClientResponse:
        if not self.settings.mcp_client_enabled:
            return McpClientResponse("blocked", "remote MCP client is disabled")
        if not self.settings.allow_http_probing:
            return McpClientResponse("blocked", "remote MCP calls are blocked until HTTP probing is enabled")
        if not self.settings.mcp_client_token.strip():
            return McpClientResponse("not_configured", "remote MCP bearer token is not configured")
        try:
            endpoint = _safe_endpoint(self.settings)
        except McpClientError as exc:
            return McpClientResponse("not_configured", str(exc))
        request_id = uuid4().hex
        payload = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
        try:
            encoded_payload = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        except (TypeError, ValueError):
            return McpClientResponse("failed", "remote MCP request could not be encoded")
        if len(encoded_payload.encode("utf-8")) > MCP_CLIENT_MAX_REQUEST_BYTES:
            return McpClientResponse("failed", "remote MCP request is too large")
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.settings.mcp_client_token}",
        }
        if not initialize:
            headers["MCP-Protocol-Version"] = self._protocol_version or MCP_CLIENT_PROTOCOL_VERSION
        try:
            with httpx.Client(
                timeout=self.settings.mcp_client_timeout_seconds,
                transport=self.transport,
                follow_redirects=False,
            ) as client:
                response = client.post(endpoint, headers=headers, content=encoded_payload)
        except (httpx.TimeoutException, httpx.ConnectError):
            return McpClientResponse("failed", "remote MCP request failed before receiving a response")
        except httpx.HTTPError:
            return McpClientResponse("failed", "remote MCP request failed")
        if response.status_code >= 400:
            if response.status_code in {401, 403}:
                return McpClientResponse("error", "remote MCP authentication failed")
            return McpClientResponse("error", "remote MCP request failed")
        if not _response_within_limit(response):
            return McpClientResponse("failed", "remote MCP response is too large")
        try:
            decoded = response.json()
        except ValueError:
            return McpClientResponse("failed", "remote MCP returned malformed JSON")
        if not isinstance(decoded, dict) or decoded.get("jsonrpc") != "2.0" or decoded.get("id") != request_id:
            return McpClientResponse("failed", "remote MCP returned an invalid JSON-RPC response")
        error = decoded.get("error")
        if isinstance(error, dict):
            code = error.get("code")
            safe_code = code if isinstance(code, int) and not isinstance(code, bool) else None
            result: dict[str, object] = {"error": {"code": safe_code}} if safe_code is not None else {}
            return McpClientResponse("error", "remote MCP request was rejected", result)
        decoded_result = decoded.get("result")
        if not isinstance(decoded_result, dict):
            return McpClientResponse("failed", "remote MCP returned an invalid result")
        return McpClientResponse(
            "ready",
            "remote MCP request completed",
            cast(dict[str, object], redact_value(decoded_result)),
        )


def _safe_endpoint(settings: Settings) -> str:
    raw = settings.mcp_client_url.strip()
    if not raw:
        raise McpClientError("remote MCP endpoint is not configured")
    try:
        parsed = urlsplit(raw)
        host = parsed.hostname
    except ValueError as exc:
        raise McpClientError("remote MCP endpoint is malformed") from exc
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password or parsed.fragment:
        raise McpClientError("remote MCP endpoint must be an HTTPS URL without embedded credentials")
    if host is None or host.lower() not in {item.strip().lower() for item in settings.mcp_client_allowed_hosts}:
        raise McpClientError("remote MCP endpoint host is not allowlisted")
    return _normalized_url(parsed)


def _normalized_url(parsed: SplitResult) -> str:
    path = parsed.path or "/mcp"
    return parsed._replace(path=path, fragment="").geturl()


def _response_within_limit(response: httpx.Response) -> bool:
    content_length = response.headers.get("content-length")
    if content_length is not None:
        try:
            if int(content_length) > MCP_CLIENT_MAX_RESPONSE_BYTES:
                return False
        except ValueError:
            return False
    return len(response.content) <= MCP_CLIENT_MAX_RESPONSE_BYTES


def _tool_name(value: str) -> str | None:
    normalized = value.strip()
    if (
        not normalized
        or len(normalized) > MCP_CLIENT_MAX_TOOL_NAME_LENGTH
        or any(ord(char) < 32 for char in normalized)
    ):
        return None
    return normalized


def _normalize_remote_tool(value: object) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None
    name = value.get("name")
    if not isinstance(name, str):
        return None
    normalized_name = _tool_name(name)
    if normalized_name is None:
        return None
    description = value.get("description", "")
    safe_description = redact_text(description if isinstance(description, str) else "")
    safe_description = safe_description[:MCP_CLIENT_MAX_DESCRIPTION_LENGTH]
    input_schema = value.get("inputSchema")
    if not isinstance(input_schema, dict):
        input_schema = {"type": "object", "properties": {}}
    annotations = value.get("annotations")
    safe_annotations: dict[str, object] = {}
    if isinstance(annotations, dict):
        for key in ("readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint"):
            if isinstance(annotations.get(key), bool):
                safe_annotations[key] = annotations[key]
    return {
        "name": normalized_name,
        "title": redact_text(str(value.get("title", normalized_name)))[:200],
        "description": safe_description,
        "inputSchema": cast(dict[str, object], redact_value(input_schema)),
        "annotations": safe_annotations,
        "untrusted_remote_metadata": True,
    }
