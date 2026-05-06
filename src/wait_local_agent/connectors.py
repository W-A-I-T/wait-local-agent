from __future__ import annotations

import json

from wait_local_agent.config import Settings
from wait_local_agent.halopsa import HaloPSAClient
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
            status="not_configured",
            message="Planned documentation connector after the HaloPSA wedge.",
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
    ]


def draft_halopsa_ticket_action(
    store: Store,
    ticket_id: str,
    action_type: str,
    fields: dict[str, object],
) -> HaloTicketDraft:
    if action_type not in HALOPSA_ACTION_TYPES:
        raise ValueError(f"unsupported HaloPSA action type: {action_type}")
    payload: dict[str, object] = {
        "connector": "halopsa",
        "ticket_id": ticket_id,
        "action_type": action_type,
        "fields": fields,
    }
    approval = store.create_approval_request(ticket_id, f"halopsa.{action_type}", payload)
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
    action_type = str(payload.get("action_type") or approval.action_type.removeprefix("halopsa."))
    ticket_id = str(payload.get("ticket_id") or approval.subject_id)
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
