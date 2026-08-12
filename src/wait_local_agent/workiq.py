"""Governed read-only access to the Microsoft Work IQ MCP surface.

Work IQ is a preview service and its tool surface is intentionally generic:
paths are data, while MCP tools provide the operation. This adapter exposes
only bounded read and schema-discovery operations. It does not execute
create/update/delete/action tools and it does not acquire OAuth credentials.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal, cast
from urllib.parse import urlsplit

from wait_local_agent.config import Settings
from wait_local_agent.mcp_client import McpClient, McpClientConfig, McpClientError, McpToolCallResult
from wait_local_agent.reports.renderers import redact_text, redact_value

MAX_WORKIQ_ENTITY_PATHS = 10
MAX_WORKIQ_PATH_LENGTH = 500
MAX_WORKIQ_FILTER_LENGTH = 200
MAX_WORKIQ_RESULT_BYTES = 100 * 1024
_ALLOWED_PATH_PREFIXES = ("/me/", "/users/", "/sites/")
_BLOCKED_PATH_SEGMENTS = ("/authentication/", "/serviceprincipals/")


class WorkIqValidationError(ValueError):
    """Raised when a Work IQ path or request is outside the read boundary."""


WorkIqStatus = Literal["ready", "not_configured", "failed"]


@dataclass(frozen=True)
class WorkIqReadResponse:
    status: WorkIqStatus
    message: str
    data: dict[str, object]


class WorkIqClient:
    """Use the configured Work IQ MCP server without exposing mutations."""

    def __init__(self, settings: Settings, *, mcp_client: McpClient | None = None) -> None:
        self.settings = settings
        self._mcp_client = mcp_client
        if self._mcp_client is None and settings.work_iq_mcp_endpoint:
            self._mcp_client = McpClient(
                McpClientConfig(
                    settings.work_iq_mcp_endpoint,
                    bearer_token=settings.work_iq_mcp_access_token,
                    timeout_seconds=settings.work_iq_mcp_timeout_seconds,
                )
            )

    def fetch(self, entity_urls: list[str]) -> WorkIqReadResponse:
        try:
            paths = _validate_entity_paths(entity_urls)
        except WorkIqValidationError as exc:
            return _failed(str(exc))
        return self._read("fetch", {"entityUrls": paths})

    def search_paths(self, filter_text: str) -> WorkIqReadResponse:
        if not isinstance(filter_text, str) or not filter_text.strip():
            return _failed("Work IQ path filter must be non-empty text")
        normalized = filter_text.strip()
        if len(normalized) > MAX_WORKIQ_FILTER_LENGTH or any(ord(character) < 32 for character in normalized):
            return _failed("Work IQ path filter is outside the bounded input limit")
        return self._read("search_paths", {"filter": normalized})

    def get_fetch_schema(self, path: str) -> WorkIqReadResponse:
        try:
            normalized = _validate_entity_path(path)
        except WorkIqValidationError as exc:
            return _failed(str(exc))
        return self._read(
            "get_schema",
            {"path": normalized, "operationType": "fetch", "format": "jsonschema"},
        )

    def _read(self, tool_name: str, arguments: dict[str, object]) -> WorkIqReadResponse:
        if self._mcp_client is None:
            return WorkIqReadResponse(
                "not_configured",
                "Work IQ MCP access is not configured",
                {},
            )
        try:
            if self._mcp_client.session_id is None:
                self._mcp_client.initialize(client_name="wait-local-agent-workiq")
            result = self._mcp_client.call_tool(tool_name, arguments)
        except McpClientError:
            return _failed("Work IQ MCP request failed")
        if result.is_error:
            return _failed(_tool_error_message(result))
        payload = _result_payload(result)
        encoded = json.dumps(payload, separators=(",", ":"), default=str)
        if len(encoded) > MAX_WORKIQ_RESULT_BYTES:
            return _failed("Work IQ response exceeded the bounded result size")
        return WorkIqReadResponse("ready", "Work IQ MCP read succeeded", payload)


def _validate_entity_paths(entity_urls: list[str]) -> list[str]:
    if not isinstance(entity_urls, list) or not entity_urls:
        raise WorkIqValidationError("entity_urls must contain at least one path")
    if len(entity_urls) > MAX_WORKIQ_ENTITY_PATHS:
        raise WorkIqValidationError("entity_urls exceeds the bounded path count")
    return [_validate_entity_path(path) for path in entity_urls]


def _validate_entity_path(path: str) -> str:
    if not isinstance(path, str) or not path.strip() or len(path.strip()) > MAX_WORKIQ_PATH_LENGTH:
        raise WorkIqValidationError("Work IQ entity path must be bounded text")
    normalized = path.strip()
    parsed = urlsplit(normalized)
    lowered = normalized.lower()
    if parsed.scheme or parsed.netloc or not normalized.startswith("/"):
        raise WorkIqValidationError("Work IQ entity path must be relative")
    if any(ord(character) < 32 for character in normalized):
        raise WorkIqValidationError("Work IQ entity path contains control characters")
    if any(segment in lowered for segment in _BLOCKED_PATH_SEGMENTS):
        raise WorkIqValidationError("Work IQ entity path is blocked by policy")
    if not any(lowered.startswith(prefix) for prefix in _ALLOWED_PATH_PREFIXES):
        raise WorkIqValidationError("Work IQ entity path is outside the allowed tenant paths")
    if "$skip" in lowered or "$skiptoken" in lowered:
        raise WorkIqValidationError("Work IQ pagination parameters are blocked")
    return normalized


def _result_payload(result: McpToolCallResult) -> dict[str, object]:
    if result.structured_content is not None:
        safe = redact_value(result.structured_content)
        return cast(dict[str, object], safe) if isinstance(safe, dict) else {}
    for item in result.content:
        if not isinstance(item, dict) or item.get("type") != "text":
            continue
        text = item.get("text")
        if not isinstance(text, str):
            continue
        try:
            decoded = json.loads(text)
        except json.JSONDecodeError:
            return {"text": redact_text(text)}
        safe = redact_value(decoded)
        if isinstance(safe, dict):
            return cast(dict[str, object], safe)
        return {"value": safe}
    return {}


def _tool_error_message(result: McpToolCallResult) -> str:
    payload = result.structured_content or {}
    detail = payload.get("error_detail")
    if isinstance(detail, str) and detail.strip():
        return redact_text(detail)
    return "Work IQ MCP tool call failed"


def _failed(message: str) -> WorkIqReadResponse:
    return WorkIqReadResponse("failed", redact_text(message), {})
