from __future__ import annotations

import json
from dataclasses import dataclass

from wait_local_agent.config import Settings
from wait_local_agent.halopsa import HaloPSAClient
from wait_local_agent.hudu import HuduClient
from wait_local_agent.models import (
    ApprovalRequest,
    ConnectorStatus,
    ConnectorStatusValue,
    HaloTicketDraft,
    HaloWriteRequest,
    HaloWriteResult,
    SecretRecord,
)
from wait_local_agent.store import Store

HALOPSA_ACTION_TYPES = {
    "add_note",
    "draft_response",
    "update_status",
    "assign_technician",
    "update_ticket_fields",
}


@dataclass(frozen=True)
class ConnectorValidationResult:
    connector: str
    passed: bool
    layer: str
    message: str


def list_connector_statuses(settings: Settings) -> list[ConnectorStatus]:
    halopsa_configured = bool(
        settings.halopsa_base_url
        and settings.halopsa_client_id
        and settings.halopsa_client_secret
        and settings.halopsa_tenant
    )
    halopsa_status: ConnectorStatusValue = "not_configured"
    if halopsa_configured:
        halopsa_status = "configured" if settings.allow_http_probing else "blocked"
    hudu_configured = bool(settings.hudu_base_url and settings.hudu_api_key)
    hudu_status: ConnectorStatusValue = "not_configured"
    if hudu_configured:
        hudu_status = "configured" if settings.allow_http_probing else "blocked"
    return [
        ConnectorStatus(
            id="halopsa",
            kind="psa",
            name="HaloPSA",
            status=halopsa_status,
            message=(
                "HaloPSA credentials are configured; live writes still require approval."
                if halopsa_status == "configured"
                else (
                    "HaloPSA credentials are configured; live reads require "
                    "WAIT_ALLOW_HTTP_PROBING."
                )
                if halopsa_status == "blocked"
                else "Set WAIT_HALOPSA_* values to enable the first PSA read path."
            ),
            write_actions_enabled=settings.allow_write_actions,
            http_probing_enabled=settings.allow_http_probing,
        ),
        ConnectorStatus(
            id="hudu",
            kind="documentation",
            name="Hudu",
            status=hudu_status,
            message=(
                "Hudu credentials are configured for read-only documentation lookup."
                if hudu_status == "configured"
                else "Hudu credentials are configured; live reads require WAIT_ALLOW_HTTP_PROBING."
                if hudu_status == "blocked"
                else "Set WAIT_HUDU_BASE_URL and WAIT_HUDU_API_KEY to enable documentation reads."
            ),
            http_probing_enabled=settings.allow_http_probing,
        ),
        ConnectorStatus(
            id="m365",
            kind="m365",
            name="Microsoft 365 / Entra",
            status="not_configured",
            message="Planned read-only identity, group, license, and mailbox lookup connector.",
        ),
        ConnectorStatus(
            id="rmm",
            kind="rmm",
            name="RMM inventory",
            status="not_configured",
            message="Planned read-only device inventory before approved script execution.",
        ),
    ]


def list_secret_records(settings: Settings) -> list[SecretRecord]:
    return [
        SecretRecord("WAIT_HALOPSA_BASE_URL", bool(settings.halopsa_base_url), "halopsa"),
        SecretRecord("WAIT_HALOPSA_CLIENT_ID", bool(settings.halopsa_client_id), "halopsa"),
        SecretRecord(
            "WAIT_HALOPSA_CLIENT_SECRET",
            bool(settings.halopsa_client_secret),
            "halopsa",
        ),
        SecretRecord("WAIT_HALOPSA_TENANT", bool(settings.halopsa_tenant), "halopsa"),
        SecretRecord("WAIT_HALOPSA_TOKEN_URL", bool(settings.halopsa_token_url), "halopsa"),
        SecretRecord(
            "WAIT_HALOPSA_TICKET_WRITE_ENDPOINT",
            bool(settings.halopsa_ticket_write_endpoint),
            "halopsa",
        ),
        SecretRecord(
            "WAIT_HALOPSA_ACTION_WRITE_ENDPOINT",
            bool(settings.halopsa_action_write_endpoint),
            "halopsa",
        ),
        SecretRecord("WAIT_HUDU_BASE_URL", bool(settings.hudu_base_url), "hudu"),
        SecretRecord("WAIT_HUDU_API_KEY", bool(settings.hudu_api_key), "hudu"),
        SecretRecord("WAIT_HUDU_PAGE_SIZE", bool(settings.hudu_page_size), "hudu"),
    ]


def validate_connector_credentials(
    connector: str,
    settings: Settings,
    *,
    halopsa_client: HaloPSAClient | None = None,
    hudu_client: HuduClient | None = None,
) -> ConnectorValidationResult:
    if connector == "halopsa":
        missing = [
            key
            for key, value in {
                "WAIT_HALOPSA_BASE_URL": settings.halopsa_base_url,
                "WAIT_HALOPSA_CLIENT_ID": settings.halopsa_client_id,
                "WAIT_HALOPSA_CLIENT_SECRET": settings.halopsa_client_secret,
                "WAIT_HALOPSA_TENANT": settings.halopsa_tenant,
            }.items()
            if not value
        ]
        if missing:
            return ConnectorValidationResult(
                connector,
                False,
                "config",
                f"HaloPSA credentials are incomplete: {', '.join(missing)}.",
            )
        result = (halopsa_client or HaloPSAClient(settings)).health()
    elif connector == "hudu":
        missing = [
            key
            for key, value in {
                "WAIT_HUDU_BASE_URL": settings.hudu_base_url,
                "WAIT_HUDU_API_KEY": settings.hudu_api_key,
            }.items()
            if not value
        ]
        if missing:
            return ConnectorValidationResult(
                connector,
                False,
                "config",
                f"Hudu credentials are incomplete: {', '.join(missing)}.",
            )
        result = (hudu_client or HuduClient(settings)).health()
    else:
        raise ValueError(f"unsupported connector: {connector}")
    return _classify_validation_result(connector, result.status, result.message)


def draft_halopsa_ticket_action(
    store: Store,
    ticket_id: str,
    action_type: str,
    fields: dict[str, object],
    *,
    client_id: str | None = None,
) -> HaloTicketDraft:
    if action_type not in HALOPSA_ACTION_TYPES:
        raise ValueError(f"unsupported HaloPSA action type: {action_type}")
    payload: dict[str, object] = {
        "connector": "halopsa",
        "ticket_id": ticket_id,
        "action_type": action_type,
        "fields": fields,
    }
    approval = store.create_approval_request(
        ticket_id,
        f"halopsa.{action_type}",
        payload,
        client_id=client_id,
    )
    return HaloTicketDraft(
        ticket_id=ticket_id,
        action_type=action_type,
        payload_json=json.dumps(payload, sort_keys=True),
        approval_required=True,
        status="pending",
        approval_request_id=approval.id,
    )


def execute_halopsa_approval_request(
    store: Store,
    client: HaloPSAClient,
    request_id: int,
) -> ApprovalRequest:
    approval = store.get_approval_request(request_id)
    if approval is None:
        raise KeyError(request_id)
    if not approval.action_type.startswith("halopsa."):
        raise ValueError("approval request is not a HaloPSA action")
    if approval.status != "approved":
        raise PermissionError("HaloPSA writes require approved approval requests")
    if approval.execution_status == "succeeded":
        raise RuntimeError("HaloPSA approval request has already executed successfully")

    payload = json.loads(approval.payload_json)
    if not isinstance(payload, dict):
        raise ValueError("approval payload is malformed")
    if payload.get("connector") != "halopsa":
        raise ValueError("approval payload connector does not match HaloPSA")
    action_type = str(payload.get("action_type") or approval.action_type.removeprefix("halopsa."))
    if action_type not in HALOPSA_ACTION_TYPES:
        raise ValueError(f"unsupported HaloPSA action type: {action_type}")
    if approval.action_type != f"halopsa.{action_type}":
        raise ValueError("approval payload action does not match approval request")
    ticket_id = str(payload.get("ticket_id") or approval.subject_id)
    if ticket_id != approval.subject_id:
        raise ValueError("approval payload ticket does not match approval request")
    fields = payload.get("fields")
    if not isinstance(fields, dict):
        fields = {}
    result = client.execute_write(
        HaloWriteRequest(
            ticket_id=ticket_id,
            action_type=action_type,
            fields=fields,
            approval_request_id=approval.id,
        )
    )
    return store.record_approval_execution(
        request_id,
        status=result.status,
        message=result.message,
        result=sanitize_halopsa_write_result(result),
    )


def sanitize_halopsa_write_result(result: HaloWriteResult) -> dict[str, object]:
    return {
        "action_type": result.action_type,
        "ticket_id": result.ticket_id,
        "endpoint": result.endpoint,
        "status": result.status,
        "status_code": result.status_code,
        "remote_id": result.remote_id,
    }


def update_halopsa_approval_fields(
    store: Store,
    request_id: int,
    fields: dict[str, object],
    comment: str = "Draft edited before approval",
) -> ApprovalRequest:
    approval = store.get_approval_request(request_id)
    if approval is None:
        raise KeyError(request_id)
    if not approval.action_type.startswith("halopsa."):
        raise ValueError("approval request is not a HaloPSA action")
    payload = json.loads(approval.payload_json)
    if not isinstance(payload, dict):
        raise ValueError("approval payload is malformed")
    action_type = str(payload.get("action_type") or approval.action_type.removeprefix("halopsa."))
    validate_halopsa_action_fields(action_type, fields)
    payload["fields"] = fields
    return store.update_approval_request_payload(request_id, payload, comment)


def validate_halopsa_action_fields(action_type: str, fields: dict[str, object]) -> None:
    if action_type not in HALOPSA_ACTION_TYPES:
        raise ValueError(f"unsupported HaloPSA action type: {action_type}")
    if action_type in {"add_note", "draft_response"}:
        if not _first_present(fields, "note", "body", "message", "response"):
            raise ValueError(f"HaloPSA {action_type} requires a note or response")
        return
    if action_type == "update_status" and not _first_present(fields, "status", "status_id"):
        raise ValueError("HaloPSA update_status requires status or status_id")
    if action_type == "assign_technician" and not _first_present(
        fields,
        "technician_id",
        "agent_id",
        "assigned_agent_id",
        "team_id",
    ):
        raise ValueError("HaloPSA assign_technician requires technician, agent, or team id")
    has_ticket_field = any(value not in (None, "") for value in fields.values())
    if action_type == "update_ticket_fields" and not has_ticket_field:
        raise ValueError("HaloPSA update_ticket_fields requires at least one field")


def _first_present(fields: dict[str, object], *keys: str) -> object:
    for key in keys:
        value = fields.get(key)
        if value not in (None, ""):
            return value
    return ""


def _classify_validation_result(
    connector: str,
    status: str,
    message: str,
) -> ConnectorValidationResult:
    if status == "ready":
        return ConnectorValidationResult(connector, True, "connector", message)
    if status == "not_configured":
        return ConnectorValidationResult(connector, False, "config", message)
    if status == "blocked":
        return ConnectorValidationResult(connector, False, "safety", message)
    lowered = message.lower()
    if "http 401" in lowered or "http 403" in lowered or "unauthor" in lowered or "forbidden" in lowered:
        layer = "auth"
    elif (
        "before receiving a response" in lowered
        or "request failed" in lowered
        or "timed out" in lowered
        or "timeout" in lowered
        or "connect" in lowered
    ):
        layer = "connectivity"
    else:
        layer = "connector"
    return ConnectorValidationResult(connector, False, layer, message)
