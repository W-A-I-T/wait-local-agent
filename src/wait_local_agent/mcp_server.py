"""Stateless Streamable HTTP MCP adapter over the existing WAIT tool runtime.

This module deliberately owns protocol translation only. Tool discovery comes
from ``AgentService`` and calls are delegated to ``SmartActionService`` so the
existing tenant, role, approval, audit, redaction, and execution controls stay
authoritative.
"""

from __future__ import annotations

import copy
import json
from dataclasses import asdict
from typing import cast

from wait_local_agent.agents import AgentService, ToolDefinition
from wait_local_agent.rbac import AuthContext, Role
from wait_local_agent.reports.renderers import redact_text, redact_value
from wait_local_agent.smart_actions import ActionResult, SmartActionService

MCP_PROTOCOL_VERSION = "2025-06-18"
SUPPORTED_MCP_PROTOCOL_VERSIONS = frozenset({MCP_PROTOCOL_VERSION, "2025-03-26"})
MCP_SERVER_NAME = "WAIT Local Agent"
MCP_SERVER_VERSION = "1.1.1"
MCP_MAX_REQUEST_BYTES = 128 * 1024
MCP_PAGE_SIZE = 50


class McpProtocolError(ValueError):
    """A JSON-RPC/MCP error safe to return to an MCP client."""

    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def validate_transport_headers(
    message: dict[str, object],
    *,
    protocol_version: str | None,
    mcp_method: str | None,
    mcp_name: str | None,
) -> None:
    """Validate optional Streamable HTTP routing headers when supplied."""

    method = message.get("method")
    if mcp_method is not None and mcp_method != method:
        raise McpProtocolError(-32600, "Mcp-Method does not match the JSON-RPC method")
    if method != "initialize" and protocol_version not in SUPPORTED_MCP_PROTOCOL_VERSIONS:
        raise McpProtocolError(-32600, "unsupported or missing MCP-Protocol-Version")
    if method == "tools/call":
        params = message.get("params")
        name = params.get("name") if isinstance(params, dict) else None
        if mcp_name is not None and mcp_name != name:
            raise McpProtocolError(-32600, "Mcp-Name does not match the tool name")


def handle_message(
    message: object,
    *,
    context: AuthContext,
    agent_service: AgentService,
    smart_action_service: SmartActionService,
) -> dict[str, object] | None:
    """Handle one JSON-RPC message, returning ``None`` for notifications."""

    if not isinstance(message, dict):
        raise McpProtocolError(-32600, "MCP requests must be JSON objects")
    if message.get("jsonrpc") != "2.0" or not isinstance(message.get("method"), str):
        raise McpProtocolError(-32600, "invalid JSON-RPC request")
    method = cast(str, message["method"])
    request_id = message.get("id")
    notification = "id" not in message
    if not notification and not _valid_request_id(request_id):
        raise McpProtocolError(-32600, "request id must be a string or integer")

    try:
        if method == "initialize":
            result = _initialize(message.get("params"))
        elif method == "notifications/initialized":
            return None
        elif method == "ping":
            result = {}
        elif method == "tools/list":
            _require_tenant_for_non_admin(context)
            result = _list_tools(message.get("params"), context, agent_service)
        elif method == "tools/call":
            _require_tenant_for_non_admin(context)
            result = _call_tool(message.get("params"), context, agent_service, smart_action_service)
        else:
            if notification:
                return None
            raise McpProtocolError(-32601, "method not found")
    except McpProtocolError:
        if notification:
            return None
        raise
    if notification:
        return None
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def error_response(message: object, error: McpProtocolError) -> dict[str, object]:
    """Build a JSON-RPC error without reflecting arbitrary request content."""

    request_id: object | None = None
    if isinstance(message, dict) and _valid_request_id(message.get("id")):
        request_id = message.get("id")
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": error.code, "message": error.message},
    }


def _initialize(params: object) -> dict[str, object]:
    values = params if isinstance(params, dict) else {}
    requested = values.get("protocolVersion")
    if requested is not None and (not isinstance(requested, str) or requested not in SUPPORTED_MCP_PROTOCOL_VERSIONS):
        raise McpProtocolError(-32602, "unsupported MCP protocol version")
    return {
        "protocolVersion": requested or MCP_PROTOCOL_VERSION,
        "capabilities": {"tools": {"listChanged": False}},
        "serverInfo": {"name": MCP_SERVER_NAME, "version": MCP_SERVER_VERSION},
        "instructions": (
            "WAIT Local Agent exposes only the authenticated caller's permitted tools. "
            "Tenant scope, role checks, human approval, redaction, and audit history "
            "remain enforced by WAIT."
        ),
    }


def _list_tools(
    params: object,
    context: AuthContext,
    agent_service: AgentService,
) -> dict[str, object]:
    values = params if isinstance(params, dict) else {}
    start = _cursor_start(values.get("cursor"))
    tools = [_mcp_tool(tool) for tool in agent_service.list_tools() if _role_allows(context.role, tool)]
    page = tools[start : start + MCP_PAGE_SIZE]
    result: dict[str, object] = {"tools": page}
    if start + MCP_PAGE_SIZE < len(tools):
        result["nextCursor"] = str(start + MCP_PAGE_SIZE)
    return result


def _call_tool(
    params: object,
    context: AuthContext,
    agent_service: AgentService,
    smart_action_service: SmartActionService,
) -> dict[str, object]:
    if not isinstance(params, dict) or not isinstance(params.get("name"), str):
        raise McpProtocolError(-32602, "tools/call requires a tool name")
    name = cast(str, params["name"])
    arguments = params.get("arguments", {})
    if not isinstance(arguments, dict):
        raise McpProtocolError(-32602, "tool arguments must be an object")
    tool = next((candidate for candidate in agent_service.list_tools() if candidate.id == name), None)
    if tool is None:
        raise McpProtocolError(-32602, "tool is not available")
    if not _role_allows(context.role, tool):
        raise McpProtocolError(-32001, "caller is not authorized for this tool")
    try:
        smart_action_service.describe(name)
    except KeyError as exc:
        raise McpProtocolError(-32602, "tool is not available") from exc

    normalized_arguments = dict(arguments)
    requested_client_id = normalized_arguments.get("client_id")
    if requested_client_id is not None and not isinstance(requested_client_id, str):
        raise McpProtocolError(-32602, "client_id must be a string")
    scoped_client_id = _client_scope(context, requested_client_id)
    properties = tool.input_schema.get("properties")
    if isinstance(properties, dict) and "client_id" in properties and "client_id" not in normalized_arguments:
        if scoped_client_id is None:
            raise McpProtocolError(-32602, "client_id is required for this tool")
        normalized_arguments["client_id"] = scoped_client_id

    try:
        result = smart_action_service.invoke(
            name,
            normalized_arguments,
            context.approver_id or "mcp",
            client_id=scoped_client_id,
            confirm=False,
        )
    except Exception as exc:
        raise McpProtocolError(-32000, "tool invocation failed") from exc
    return _call_result(result)


def _call_result(result: ActionResult) -> dict[str, object]:
    safe = cast(dict[str, object], redact_value(asdict(result)))
    status = result.status
    structured = {
        "status": status,
        "output": safe.get("output", {}),
        "evidence": safe.get("evidence", []),
        "run_id": safe.get("run_id"),
        "approval_id": safe.get("approval_id"),
    }
    if status not in {"success", "pending_approval"}:
        structured["error"] = _safe_error_message(status)
    return {
        "content": [{"type": "text", "text": json.dumps(structured, sort_keys=True, default=str)}],
        "structuredContent": structured,
        "isError": status not in {"success", "pending_approval"},
    }


def _mcp_tool(tool: ToolDefinition) -> dict[str, object]:
    input_schema = _object_schema(tool.input_schema)
    output_schema = _object_schema(tool.output_schema)
    approval_note = " WAIT creates a human approval request before execution." if tool.approval_required else ""
    return {
        "name": tool.id,
        "title": tool.name,
        "description": f"{redact_text(tool.description)}{approval_note}",
        "inputSchema": input_schema,
        "outputSchema": output_schema,
        "annotations": {
            "title": tool.name,
            "readOnlyHint": tool.access_mode == "read",
            "destructiveHint": tool.access_mode == "write",
            "idempotentHint": tool.access_mode == "read",
            "openWorldHint": tool.access_mode != "read",
        },
        "_meta": {
            "wait.local-agent/requiredRole": tool.required_role,
            "wait.local-agent/riskLevel": tool.risk_level,
            "wait.local-agent/approvalRequired": tool.approval_required,
        },
    }


def _object_schema(schema: dict[str, object]) -> dict[str, object]:
    """Convert WAIT's compact output schemas to MCP object JSON Schema."""

    copied = copy.deepcopy(schema)
    if copied.get("type") == "object":
        raw_properties = copied.get("properties")
        object_properties: dict[str, object] = {}
        if isinstance(raw_properties, dict):
            for key, value in raw_properties.items():
                if isinstance(value, dict):
                    object_properties[str(key)] = value
                elif isinstance(value, str):
                    object_properties[str(key)] = _property_schema(value)
        required = copied.get("required")
        if isinstance(required, list):
            for key in required:
                if isinstance(key, str) and key not in object_properties:
                    object_properties[key] = {"type": "string"}
        copied["properties"] = object_properties
        return copied
    compact_properties: dict[str, object] = {}
    for key, value in copied.items():
        if isinstance(value, str) and value in {"array", "boolean", "integer", "number", "object", "string"}:
            compact_properties[key] = {"type": value}
        elif isinstance(value, str):
            compact_properties[key] = _property_schema(value)
    return {"type": "object", "properties": compact_properties}


def _property_schema(description: str) -> dict[str, str]:
    normalized = description.strip().lower()
    if normalized in {"array", "boolean", "integer", "number", "object", "string"}:
        return {"type": normalized}
    return {"type": "string", "description": description}


def _role_allows(role: Role, tool: ToolDefinition) -> bool:
    required = tool.required_role.strip().lower()
    minimum = {
        "admin": Role.ADMIN,
        "technician": Role.TECHNICIAN,
        "viewer": Role.VIEWER,
    }.get(required, Role.ADMIN)
    return role >= minimum


def _client_scope(context: AuthContext, requested: str | None) -> str | None:
    normalized = requested.strip() if isinstance(requested, str) and requested.strip() else None
    bound = context.client_id.strip() if isinstance(context.client_id, str) and context.client_id.strip() else None
    if context.role >= Role.ADMIN:
        return normalized or bound
    if bound is None:
        raise McpProtocolError(-32001, "authenticated caller has no tenant")
    if normalized is not None and normalized != bound:
        raise McpProtocolError(-32001, "requested tenant is outside authenticated scope")
    return bound


def _require_tenant_for_non_admin(context: AuthContext) -> None:
    if context.role < Role.ADMIN and not context.client_id:
        raise McpProtocolError(-32001, "authenticated caller has no tenant")


def _cursor_start(value: object) -> int:
    if value is None:
        return 0
    if not isinstance(value, str) or not value.isdigit():
        raise McpProtocolError(-32602, "cursor must be a non-negative integer string")
    return int(value)


def _valid_request_id(value: object) -> bool:
    return isinstance(value, (str, int)) and not isinstance(value, bool)


def _safe_error_message(status: str) -> str:
    return {
        "failed": "tool execution failed",
        "provider_not_configured": "tool provider is not configured",
        "not_authorized": "tool invocation was not authorized",
        "rejected": "tool request was rejected",
    }.get(status, "tool request did not complete")
