"""A small, governed MCP server over the existing WAIT tool catalog.

This module deliberately implements only the MCP lifecycle and tools surface
needed to expose WAIT's existing smart actions. It does not introduce a second
execution engine: every call is routed through ``SmartActionService`` so the
existing tenant, RBAC, approval, provider, audit, and redaction controls stay
authoritative.
"""

from __future__ import annotations

import json
import secrets
from dataclasses import asdict
from urllib.parse import urlparse

from wait_local_agent.agents import AgentService, ToolDefinition
from wait_local_agent.rbac import AuthContext, Role
from wait_local_agent.reports.renderers import redact_text, redact_value
from wait_local_agent.smart_actions import SmartActionService

MCP_PROTOCOL_VERSION = "2025-11-25"
MCP_SERVER_NAME = "wait-local-agent"
MCP_SERVER_VERSION = "1.1.1"
MAX_MCP_REQUEST_BYTES = 256 * 1024
MAX_MCP_RESULT_BYTES = 128 * 1024
MAX_MCP_TOOLS_PAGE = 100
MAX_MCP_SESSIONS = 256
_SUPPORTED_PROTOCOL_VERSIONS = frozenset({MCP_PROTOCOL_VERSION, "2025-03-26"})
_MCP_TOOL_PREFIX = "wait."


class McpProtocolError(ValueError):
    """An error that belongs in the JSON-RPC protocol error object."""

    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class WaitMcpServer:
    """Serve the MCP initialize, tools/list, and tools/call methods."""

    def __init__(self, agent_service: AgentService, smart_action_service: SmartActionService) -> None:
        self.agent_service = agent_service
        self.smart_action_service = smart_action_service
        self._sessions: dict[str, bool] = {}

    def handle(
        self,
        message: object,
        *,
        context: AuthContext,
        session_id: str | None,
    ) -> tuple[dict[str, object] | None, str | None]:
        """Handle one decoded JSON-RPC message.

        The second return value is a newly-issued session ID for initialize.
        Notifications intentionally return no response object.
        """

        if not isinstance(message, dict):
            raise McpProtocolError(-32600, "invalid request")
        request_id = message.get("id")
        method = message.get("method")
        if message.get("jsonrpc") != "2.0" or not isinstance(method, str) or not method.strip():
            return _error_response(request_id, -32600, "invalid request"), None
        if "id" in message and (
            request_id is None
            or isinstance(request_id, bool)
            or not isinstance(request_id, (str, int))
        ):
            return _error_response(None, -32600, "invalid request"), None
        params = message.get("params", {})
        if not isinstance(params, dict):
            return _error_response(request_id, -32602, "params must be an object"), None

        if method == "initialize":
            if session_id is not None:
                return _error_response(request_id, -32600, "initialize must start a new session"), None
            return self._initialize(request_id, params)
        if session_id is None or session_id not in self._sessions:
            return _error_response(request_id, -32000, "MCP session is missing or expired"), None
        if method == "notifications/initialized":
            self._sessions[session_id] = True
            return None, None
        if not self._sessions[session_id]:
            return _error_response(request_id, -32001, "MCP session is not initialized"), None
        if method == "ping":
            return _success_response(request_id, {}), None
        if method == "tools/list":
            return _success_response(request_id, self._list_tools(params)), None
        if method == "tools/call":
            return _success_response(request_id, self._call_tool(params, context)), None
        if "id" not in message:
            return None, None
        return _error_response(request_id, -32601, f"method not found: {method}"), None

    def _initialize(
        self,
        request_id: object,
        params: dict[str, object],
    ) -> tuple[dict[str, object], str]:
        requested_version = params.get("protocolVersion")
        if not isinstance(requested_version, str) or not requested_version.strip():
            return _error_response(request_id, -32602, "protocolVersion is required"), ""
        negotiated_version = (
            requested_version if requested_version in _SUPPORTED_PROTOCOL_VERSIONS else MCP_PROTOCOL_VERSION
        )
        session_id = secrets.token_urlsafe(32)
        self._sessions[session_id] = False
        while len(self._sessions) > MAX_MCP_SESSIONS:
            self._sessions.pop(next(iter(self._sessions)))
        return (
            _success_response(
                request_id,
                {
                    "protocolVersion": negotiated_version,
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {
                        "name": MCP_SERVER_NAME,
                        "version": MCP_SERVER_VERSION,
                        "description": "WAIT's tenant-scoped, approval-aware local agent tool server",
                    },
                    "instructions": (
                        "Tool calls remain subject to WAIT tenant scope, RBAC, provider readiness, "
                        "approval gates, audit logging, and output redaction."
                    ),
                },
            ),
            session_id,
        )

    def _list_tools(self, params: dict[str, object]) -> dict[str, object]:
        cursor = params.get("cursor")
        offset = _cursor_offset(cursor)
        tools = self.agent_service.list_tools()
        page = tools[offset : offset + MAX_MCP_TOOLS_PAGE]
        result: dict[str, object] = {"tools": [_mcp_tool(tool) for tool in page]}
        if offset + len(page) < len(tools):
            result["nextCursor"] = str(offset + len(page))
        return result

    def _call_tool(self, params: dict[str, object], context: AuthContext) -> dict[str, object]:
        name = params.get("name")
        arguments = params.get("arguments", {})
        if not isinstance(name, str) or not name.startswith(_MCP_TOOL_PREFIX):
            raise McpProtocolError(-32602, "tool name must use the wait. namespace")
        if not isinstance(arguments, dict):
            raise McpProtocolError(-32602, "tool arguments must be an object")
        if len(arguments) > 64 or len(json.dumps(arguments, default=str)) > MAX_MCP_REQUEST_BYTES:
            raise McpProtocolError(-32602, "tool arguments exceed the bounded request size")
        action_id = name[len(_MCP_TOOL_PREFIX) :]
        try:
            manifest = self.smart_action_service.describe(action_id)
        except KeyError as exc:
            raise McpProtocolError(-32602, "unknown WAIT tool") from exc
        if context.role < Role.TECHNICIAN:
            return _tool_error("technician authority is required to invoke WAIT tools")
        if manifest.required_role.strip().lower() == "admin" and context.role < Role.ADMIN:
            return _tool_error("administrator authority is required for this WAIT tool")
        scoped_client_id, scope_error = _mcp_client_scope(context, arguments)
        if scope_error:
            return _tool_error(scope_error)
        try:
            result = self.smart_action_service.invoke(
                action_id,
                dict(arguments),
                context.approver_id or "mcp",
                confirm=False,
                client_id=scoped_client_id,
            )
        except (KeyError, ValueError) as exc:
            return _tool_error(redact_text(str(exc)))
        except Exception:
            return _tool_error("WAIT tool execution failed")
        payload = cast_dict(redact_value(asdict(result)))
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        if len(encoded) > MAX_MCP_RESULT_BYTES:
            payload = {
                "status": payload.get("status", "failed"),
                "run_id": payload.get("run_id"),
                "error_detail": "WAIT tool result exceeded the bounded MCP response size",
            }
            encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        failed = payload.get("status") in {"failed", "provider_not_configured", "not_authorized", "rejected"}
        return {
            "content": [{"type": "text", "text": encoded}],
            "structuredContent": payload,
            "isError": failed,
        }


def _mcp_tool(tool: ToolDefinition) -> dict[str, object]:
    return {
        "name": f"{_MCP_TOOL_PREFIX}{tool.id}",
        "title": tool.name,
        "description": tool.description,
        "inputSchema": _input_schema(tool.input_schema),
        "outputSchema": _output_schema(tool.output_schema),
        "annotations": {
            "readOnlyHint": tool.access_mode == "read",
            "destructiveHint": tool.access_mode == "write",
            "idempotentHint": tool.access_mode == "read",
            "openWorldHint": tool.access_mode == "write",
        },
    }


def _input_schema(schema: dict[str, object]) -> dict[str, object]:
    normalized = dict(schema)
    normalized.setdefault("type", "object")
    properties = normalized.get("properties")
    if isinstance(properties, dict):
        normalized["properties"] = {
            str(key): _property_schema(value) for key, value in properties.items()
        }
    return normalized


def _output_schema(schema: dict[str, object]) -> dict[str, object]:
    if schema.get("type"):
        return _input_schema(schema)
    return {
        "type": "object",
        "properties": {str(key): _property_schema(value) for key, value in schema.items()},
        "additionalProperties": True,
    }


def _property_schema(value: object) -> dict[str, object]:
    if isinstance(value, dict):
        return _input_schema(value)
    if not isinstance(value, str):
        return {"type": "string"}
    types = [item.strip() for item in value.split("|") if item.strip()]
    mapped = [item for item in types if item in {"array", "boolean", "integer", "number", "object", "string", "null"}]
    if not mapped:
        mapped = ["string"]
    return {"type": mapped[0] if len(mapped) == 1 else mapped}


def _cursor_offset(cursor: object) -> int:
    if cursor is None:
        return 0
    if not isinstance(cursor, str) or not cursor.isdigit():
        raise McpProtocolError(-32602, "cursor must be a non-negative integer string")
    offset = int(cursor)
    if offset > 10_000:
        raise McpProtocolError(-32602, "cursor is outside the bounded tool catalog")
    return offset


def _mcp_client_scope(context: AuthContext, arguments: dict[str, object]) -> tuple[str | None, str | None]:
    requested = arguments.get("client_id")
    if requested is not None and (not isinstance(requested, str) or not requested.strip()):
        return None, "client_id must be non-empty text when supplied"
    requested_id = requested.strip() if isinstance(requested, str) else None
    if context.role < Role.ADMIN:
        if not context.client_id:
            return None, "authenticated principal has no tenant"
        if requested_id and requested_id != context.client_id:
            return None, "requested tenant is outside authenticated scope"
        return context.client_id, None
    return requested_id or context.client_id, None


def _tool_error(message: str) -> dict[str, object]:
    safe_message = redact_text(message)
    payload = {"status": "failed", "error_detail": safe_message}
    return {
        "content": [{"type": "text", "text": json.dumps(payload, sort_keys=True)}],
        "structuredContent": payload,
        "isError": True,
    }


def cast_dict(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {"status": "failed", "error_detail": "invalid result"}


def origin_allowed(
    origin: str | None,
    request_origin: str,
    configured_origins: tuple[str, ...] = (),
) -> bool:
    """Apply a small DNS-rebinding-safe Origin policy for Streamable HTTP."""

    if not origin:
        return True
    normalized = origin.strip().rstrip("/")
    configured = {item.strip().rstrip("/") for item in configured_origins if item.strip()}
    if normalized == request_origin.rstrip("/") or normalized in configured:
        return True
    parsed = urlparse(normalized)
    return parsed.scheme in {"http", "https"} and parsed.hostname in {
        "localhost",
        "127.0.0.1",
        "::1",
    }


def protocol_error_response(request_id: object, error: McpProtocolError) -> dict[str, object]:
    return _error_response(request_id, error.code, error.message)


def _success_response(request_id: object, result: dict[str, object]) -> dict[str, object]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error_response(request_id: object, code: int, message: str) -> dict[str, object]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}
