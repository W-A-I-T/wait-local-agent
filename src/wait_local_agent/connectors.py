from __future__ import annotations

import json

from wait_local_agent.config import Settings
from wait_local_agent.models import (
    ConnectorStatus,
    ConnectorStatusValue,
    HaloTicketDraft,
    SecretRecord,
)
from wait_local_agent.store import Store


def list_connector_statuses(settings: Settings) -> list[ConnectorStatus]:
    halopsa_configured = bool(
        settings.halopsa_base_url
        and settings.halopsa_client_id
        and settings.halopsa_client_secret
        and settings.halopsa_tenant
    )
    halopsa_status: ConnectorStatusValue = "configured" if halopsa_configured else "not_configured"
    return [
        ConnectorStatus(
            id="halopsa",
            kind="psa",
            name="HaloPSA",
            status=halopsa_status,
            message=(
                "HaloPSA credentials are configured; live writes still require approval."
                if halopsa_configured
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
    ]


def draft_halopsa_ticket_action(
    store: Store,
    ticket_id: str,
    action_type: str,
    fields: dict[str, object],
) -> HaloTicketDraft:
    if store.get_ticket(ticket_id) is None:
        raise KeyError(ticket_id)
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
