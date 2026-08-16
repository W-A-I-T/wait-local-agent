"""Governed read-only access to the Microsoft Work IQ MCP surface.

Work IQ is a preview service and its tool surface is intentionally generic:
paths are data, while MCP tools provide the operation. This adapter exposes
only bounded read and schema-discovery operations. It does not execute
create/update/delete/action tools and it does not acquire OAuth credentials.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, Protocol, cast
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
WorkIqOperation = Literal["read", "write", "action", "function", "unknown"]
WorkIqClassification = Literal["read", "write", "action", "high-risk", "blocked", "unknown"]


@dataclass(frozen=True)
class WorkIqPolicyDecision:
    """Deterministic local decision for one Work IQ request.

    The remote MCP catalog is never treated as an authorization source.  The
    decision records the local classification and a bounded reason so callers
    can distinguish malformed/unknown requests from policy-denied requests.
    """

    classification: WorkIqClassification
    reason: str


@dataclass(frozen=True)
class WorkIqReadResponse:
    status: WorkIqStatus
    message: str
    data: dict[str, Any]
    classification: WorkIqClassification = "unknown"


class WorkIqMcpClient(Protocol):
    @property
    def session_id(self) -> str | None: ...

    def initialize(self, *, client_name: str) -> str: ...

    def call_tool(self, name: str, arguments: dict[str, object]) -> McpToolCallResult: ...


def classify_work_iq_operation(
    tool_name: object,
    *,
    resource_paths: object = None,
    operation: object = None,
) -> WorkIqOperation:
    """Classify a Work IQ request using the tool, path, and operation together.

    The remote catalog is untrusted. Only the explicitly supported read
    subset is returned as ``read``; generic mutation, action, function, and
    unknown requests fail closed for this adapter.
    """

    normalized = tool_name.strip().casefold() if isinstance(tool_name, str) else ""
    if normalized in {"create_entity", "update_entity", "delete_entity"}:
        return "write"
    if normalized == "do_action":
        return "action"
    if normalized == "call_function":
        return "function"
    decision = classify_work_iq_request(
        tool_name,
        resource_paths=resource_paths,
        operation=operation,
    )
    if decision.classification == "read":
        return "read"
    return "unknown"


def classify_work_iq_request(
    tool_name: object,
    *,
    resource_paths: object = None,
    operation: object = None,
    arguments: object = None,
    tenant: object = None,
    identity: object = None,
    local_policy: object = None,
) -> WorkIqPolicyDecision:
    """Classify a request using all local policy inputs and fail closed.

    Work IQ's generic tools intentionally make the resource path and request
    body part of the security decision.  ``arguments`` is preferred when it
    is supplied because it preserves the official tool-specific path names
    (``entityUrl``, ``actionUrl``, and so on).  ``tenant`` and ``identity``
    are local context only; they are not forwarded to the MCP server.
    """

    if not isinstance(tool_name, str) or not tool_name.strip():
        return WorkIqPolicyDecision("unknown", "Work IQ tool name is missing")
    normalized = tool_name.strip().casefold()
    if not _valid_context_value(tenant) or not _valid_context_value(identity):
        return WorkIqPolicyDecision("unknown", "Work IQ tenant and identity context must be bounded text")
    policy = _normalized_policy(local_policy)
    if policy is None:
        return WorkIqPolicyDecision("unknown", "Work IQ local policy is malformed")
    policy_tenant = policy.get("tenant_id", policy.get("tenant"))
    if policy_tenant is not None and (
        not isinstance(policy_tenant, str)
        or not _valid_context_value(tenant)
        or tenant != policy_tenant
    ):
        return WorkIqPolicyDecision("blocked", "Work IQ tenant is denied by local policy")
    if policy.get("require_identity") is True and identity is None:
        return WorkIqPolicyDecision("blocked", "Work IQ identity is required by local policy")
    allowed_identities = policy.get("allowed_identities")
    if isinstance(allowed_identities, (list, tuple)):
        allowed = {value for value in allowed_identities if isinstance(value, str)}
        if not isinstance(identity, str) or identity not in allowed:
            return WorkIqPolicyDecision("blocked", "Work IQ identity is denied by local policy")
    if policy.get("offline") is True or policy.get("allow_work_iq") is False:
        return WorkIqPolicyDecision("blocked", "Work IQ is blocked by local policy")

    expected_classification: WorkIqClassification
    expected_operation: str
    path_values = _request_paths(normalized, arguments, resource_paths)
    if normalized in {"create_entity", "update_entity", "delete_entity"}:
        expected_classification = "write"
        expected_operation = normalized
    elif normalized == "do_action":
        expected_classification = "action"
        expected_operation = normalized
    elif normalized == "call_function":
        expected_classification = "high-risk"
        expected_operation = normalized
    elif normalized in {"fetch", "search_paths", "get_schema"}:
        expected_classification = "read"
        expected_operation = normalized
    else:
        return WorkIqPolicyDecision("unknown", "Work IQ tool is outside the supported local contract")

    if not _operation_matches(operation, normalized, expected_operation):
        return WorkIqPolicyDecision("unknown", "Work IQ operation does not match the selected tool")
    allowed_operations = policy.get("allowed_operations")
    if isinstance(allowed_operations, (list, tuple)):
        allowed = {str(value).strip().casefold() for value in allowed_operations if isinstance(value, str)}
        accepted_names = {expected_operation}
        if expected_classification == "read":
            accepted_names.add("read")
        if expected_classification == "write":
            accepted_names.add("write")
        if expected_classification == "action":
            accepted_names.add("action")
        if not accepted_names & allowed:
            return WorkIqPolicyDecision("blocked", "Work IQ operation is denied by local policy")

    if normalized == "fetch":
        if not isinstance(path_values, list) or any(not isinstance(path, str) for path in path_values):
            return WorkIqPolicyDecision("unknown", "Work IQ fetch paths are malformed")
        try:
            paths = _validate_entity_paths(cast(list[str], path_values))
        except WorkIqValidationError as exc:
            return WorkIqPolicyDecision("blocked", str(exc))
        if not _paths_allowed(paths, policy):
            return WorkIqPolicyDecision("blocked", "Work IQ path is denied by local policy")
    elif normalized in {"get_schema", "create_entity", "update_entity", "delete_entity", "do_action", "call_function"}:
        if not isinstance(path_values, str):
            return WorkIqPolicyDecision("unknown", "Work IQ request path is missing")
        try:
            path = _validate_entity_path(path_values)
        except WorkIqValidationError as exc:
            return WorkIqPolicyDecision("blocked", str(exc))
        if not _paths_allowed([path], policy):
            return WorkIqPolicyDecision("blocked", "Work IQ path is denied by local policy")
    elif normalized == "search_paths":
        if not isinstance(path_values, str) or not path_values.strip():
            return WorkIqPolicyDecision("unknown", "Work IQ path search filter is missing")

    if expected_classification != "read":
        return WorkIqPolicyDecision(expected_classification, "Work IQ operation is not read-only")
    return WorkIqPolicyDecision("read", "Work IQ request is allowed by local policy")


def _valid_context_value(value: object) -> bool:
    return value is None or (
        isinstance(value, str)
        and bool(value.strip())
        and len(value.strip()) <= 120
        and all(ord(character) >= 32 for character in value)
    )


def _normalized_policy(value: object) -> dict[str, object] | None:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        return None
    result = dict(value)
    allowed_prefixes = result.get("allowed_path_prefixes")
    if allowed_prefixes is not None and not isinstance(allowed_prefixes, (list, tuple)):
        return None
    if isinstance(allowed_prefixes, (list, tuple)) and any(
        not isinstance(prefix, str) or not prefix.startswith("/") for prefix in allowed_prefixes
    ):
        return None
    allowed_operations = result.get("allowed_operations")
    if allowed_operations is not None and not isinstance(allowed_operations, (list, tuple)):
        return None
    allowed_identities = result.get("allowed_identities")
    if allowed_identities is not None and (
        not isinstance(allowed_identities, (list, tuple))
        or any(not isinstance(identity, str) for identity in allowed_identities)
    ):
        return None
    for boolean_key in ("offline", "allow_work_iq", "require_identity"):
        if boolean_key in result and not isinstance(result[boolean_key], bool):
            return None
    return result


def _operation_matches(operation: object, tool_name: str, expected_operation: str) -> bool:
    if operation is None:
        return True
    return isinstance(operation, str) and operation.strip().casefold() in {
        tool_name,
        expected_operation,
        "read" if expected_operation in {"fetch", "search_paths", "get_schema"} else expected_operation,
    }


def _request_paths(tool_name: str, arguments: object, resource_paths: object) -> object:
    if arguments is None:
        return resource_paths
    if not isinstance(arguments, Mapping):
        return None
    field_by_tool = {
        "fetch": "entityUrls",
        "get_schema": "path",
        "create_entity": "parentUrl",
        "update_entity": "entityUrl",
        "delete_entity": "entityUrl",
        "do_action": "actionUrl",
        "call_function": "functionUrl",
    }
    field = field_by_tool.get(tool_name)
    if field is None:
        return arguments.get("filter")
    return arguments.get(field)


def _paths_allowed(paths: list[str], policy: Mapping[str, object]) -> bool:
    prefixes = policy.get("allowed_path_prefixes")
    if not isinstance(prefixes, (list, tuple)):
        return True
    normalized = tuple(str(prefix).casefold() for prefix in prefixes)
    return all(any(path.casefold().startswith(prefix) for prefix in normalized) for path in paths)


class WorkIqClient:
    """Use the configured Work IQ MCP server without exposing mutations."""

    def __init__(self, settings: Settings, *, mcp_client: WorkIqMcpClient | None = None) -> None:
        self.settings = settings
        self._mcp_client = mcp_client
        if (
            self._mcp_client is None
            and settings.work_iq_mcp_endpoint
            and settings.work_iq_mcp_access_token.strip()
        ):
            self._mcp_client = McpClient(
                McpClientConfig(
                    settings.work_iq_mcp_endpoint,
                    bearer_token=settings.work_iq_mcp_access_token,
                    timeout_seconds=settings.work_iq_mcp_timeout_seconds,
                    allowed_hosts=settings.mcp_client_allowed_hosts,
                )
            )

    def fetch(
        self,
        entity_urls: list[str],
        *,
        tenant_id: str | None = None,
        identity: str | None = None,
        local_policy: Mapping[str, object] | None = None,
    ) -> WorkIqReadResponse:
        try:
            paths = _validate_entity_paths(entity_urls)
        except WorkIqValidationError as exc:
            return _failed(str(exc), classification="blocked")
        return self._read(
            "fetch",
            {"entityUrls": paths},
            tenant_id=tenant_id,
            identity=identity,
            local_policy=local_policy,
        )

    def search_paths(
        self,
        filter_text: str,
        *,
        tenant_id: str | None = None,
        identity: str | None = None,
        local_policy: Mapping[str, object] | None = None,
    ) -> WorkIqReadResponse:
        if not isinstance(filter_text, str) or not filter_text.strip():
            return _failed("Work IQ path filter must be non-empty text", classification="blocked")
        normalized = filter_text.strip()
        if len(normalized) > MAX_WORKIQ_FILTER_LENGTH or any(ord(character) < 32 for character in normalized):
            return _failed("Work IQ path filter is outside the bounded input limit", classification="blocked")
        return self._read(
            "search_paths",
            {"filter": normalized},
            tenant_id=tenant_id,
            identity=identity,
            local_policy=local_policy,
        )

    def get_fetch_schema(
        self,
        path: str,
        *,
        tenant_id: str | None = None,
        identity: str | None = None,
        local_policy: Mapping[str, object] | None = None,
    ) -> WorkIqReadResponse:
        try:
            normalized = _validate_entity_path(path)
        except WorkIqValidationError as exc:
            return _failed(str(exc), classification="blocked")
        return self._read(
            "get_schema",
            {"path": normalized, "operationType": "fetch", "format": "jsonschema"},
            tenant_id=tenant_id,
            identity=identity,
            local_policy=local_policy,
        )

    def _read(
        self,
        tool_name: str,
        arguments: dict[str, object],
        *,
        tenant_id: str | None = None,
        identity: str | None = None,
        local_policy: Mapping[str, object] | None = None,
    ) -> WorkIqReadResponse:
        decision = classify_work_iq_request(
            tool_name,
            arguments=arguments,
            tenant=tenant_id,
            identity=identity,
            local_policy=local_policy,
        )
        if decision.classification != "read":
            return _failed(decision.reason, classification=decision.classification)
        if self._mcp_client is None:
            return WorkIqReadResponse(
                "not_configured",
                "Work IQ MCP access is not configured",
                {},
                "read",
            )
        try:
            if self._mcp_client.session_id is None:
                self._mcp_client.initialize(client_name="wait-local-agent-workiq")
            result = self._mcp_client.call_tool(tool_name, arguments)
        except McpClientError:
            return _failed("Work IQ MCP request failed", classification="read")
        if result.is_error:
            return _failed(_tool_error_message(result), classification="read")
        payload = _result_payload(result)
        encoded = json.dumps(payload, separators=(",", ":"), default=str)
        if len(encoded) > MAX_WORKIQ_RESULT_BYTES:
            return _failed("Work IQ response exceeded the bounded result size", classification="read")
        return WorkIqReadResponse("ready", "Work IQ MCP read succeeded", payload, "read")


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


def _result_payload(result: McpToolCallResult) -> dict[str, Any]:
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


def _failed(message: str, *, classification: WorkIqClassification = "blocked") -> WorkIqReadResponse:
    return WorkIqReadResponse("failed", redact_text(message), {}, classification)
