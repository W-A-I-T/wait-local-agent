from __future__ import annotations

import json
from dataclasses import dataclass

from wait_local_agent.autotask import AutotaskClient, PsaClient
from wait_local_agent.config import Settings
from wait_local_agent.connectwise import ConnectWiseClient
from wait_local_agent.halopsa import HaloPSAClient
from wait_local_agent.hudu import HuduClient
from wait_local_agent.itglue import ItGlueClient
from wait_local_agent.models import (
    ApprovalRequest,
    ConnectorStatus,
    ConnectorStatusValue,
    HaloTicketDraft,
    HaloWriteRequest,
    HaloWriteResult,
    SecretRecord,
)
from wait_local_agent.reports.renderers import redact_value
from wait_local_agent.rmm import DattoRmmClient, NinjaOneClient, RmmClient, RmmExecutionClient, RmmExecutionResult
from wait_local_agent.servicenow import ServiceNowClient
from wait_local_agent.store import Store
from wait_local_agent.syncro import SyncroClient

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
    itglue_configured = bool(settings.itglue_base_url and settings.itglue_api_key)
    itglue_status: ConnectorStatusValue = "not_configured"
    if itglue_configured:
        itglue_status = "configured" if settings.allow_http_probing else "blocked"
    ninjaone_configured = bool(
        settings.ninjaone_base_url and settings.ninjaone_client_id and settings.ninjaone_client_secret
    )
    ninjaone_status: ConnectorStatusValue = "not_configured"
    if ninjaone_configured:
        ninjaone_status = "configured" if settings.allow_http_probing else "blocked"
    dattormm_configured = bool(
        settings.dattormm_base_url and settings.dattormm_api_key and settings.dattormm_api_secret
    )
    dattormm_status: ConnectorStatusValue = "not_configured"
    if dattormm_configured:
        dattormm_status = "configured" if settings.allow_http_probing else "blocked"
    autotask_configured = bool(
        settings.autotask_base_url
        and settings.autotask_username
        and settings.autotask_secret
        and settings.autotask_integration_code
    )
    autotask_status: ConnectorStatusValue = "not_configured"
    if autotask_configured:
        autotask_status = "configured" if settings.allow_http_probing else "blocked"
    connectwise_configured = bool(
        settings.connectwise_base_url
        and settings.connectwise_company_id
        and settings.connectwise_public_key
        and settings.connectwise_private_key
        and settings.connectwise_client_id
    )
    connectwise_status: ConnectorStatusValue = "not_configured"
    if connectwise_configured:
        connectwise_status = "configured" if settings.allow_http_probing else "blocked"
    syncro_configured = bool(settings.syncro_base_url and settings.syncro_api_key)
    syncro_status: ConnectorStatusValue = "not_configured"
    if syncro_configured:
        syncro_status = "configured" if settings.allow_http_probing else "blocked"
    servicenow_configured = bool(
        settings.servicenow_base_url and settings.servicenow_username and settings.servicenow_password
    )
    servicenow_status: ConnectorStatusValue = "not_configured"
    if servicenow_configured:
        servicenow_status = "configured" if settings.allow_http_probing else "blocked"
    return [
        ConnectorStatus(
            id="halopsa",
            kind="psa",
            name="HaloPSA",
            status=halopsa_status,
            message=(
                "HaloPSA credentials are configured; live writes still require approval."
                if halopsa_status == "configured"
                else ("HaloPSA credentials are configured; live reads require WAIT_ALLOW_HTTP_PROBING.")
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
            id="itglue",
            kind="documentation",
            name="IT Glue",
            status=itglue_status,
            message=(
                "IT Glue read-only organization and documentation lookup is configured."
                if itglue_status == "configured"
                else (
                    "IT Glue credentials are configured; live reads require WAIT_ALLOW_HTTP_PROBING."
                    if itglue_status == "blocked"
                    else "Set WAIT_ITGLUE_API_KEY to enable read-only documentation lookup."
                )
            ),
            http_probing_enabled=settings.allow_http_probing,
        ),
        ConnectorStatus(
            id="ninjaone",
            kind="rmm",
            name="NinjaOne RMM",
            status=ninjaone_status,
            message=(
                "NinjaOne read-only inventory is configured; script execution remains disabled."
                if ninjaone_status == "configured"
                else (
                    "NinjaOne credentials are configured; live reads require WAIT_ALLOW_HTTP_PROBING."
                    if ninjaone_status == "blocked"
                    else "Set WAIT_NINJAONE_* values to enable read-only RMM inventory."
                )
            ),
            http_probing_enabled=settings.allow_http_probing,
        ),
        ConnectorStatus(
            id="dattormm",
            kind="rmm",
            name="Datto RMM",
            status=dattormm_status,
            message=(
                "Datto RMM read-only device, alert, and component inventory is configured."
                if dattormm_status == "configured"
                else (
                    "Datto RMM credentials are configured; live reads require WAIT_ALLOW_HTTP_PROBING."
                    if dattormm_status == "blocked"
                    else "Set WAIT_DATTORMM_* values to enable read-only RMM inventory."
                )
            ),
            http_probing_enabled=settings.allow_http_probing,
        ),
        ConnectorStatus(
            id="autotask",
            kind="psa",
            name="Autotask PSA",
            status=autotask_status,
            message=(
                "Autotask read-only ticket and company inventory is configured."
                if autotask_status == "configured"
                else (
                    "Autotask credentials are configured; live reads require WAIT_ALLOW_HTTP_PROBING."
                    if autotask_status == "blocked"
                    else "Set WAIT_AUTOTASK_* values to enable read-only PSA inventory."
                )
            ),
            http_probing_enabled=settings.allow_http_probing,
        ),
        ConnectorStatus(
            id="connectwise",
            kind="psa",
            name="ConnectWise PSA",
            status=connectwise_status,
            message=(
                "ConnectWise read-only ticket and company inventory is configured."
                if connectwise_status == "configured"
                else (
                    "ConnectWise credentials are configured; live reads require WAIT_ALLOW_HTTP_PROBING."
                    if connectwise_status == "blocked"
                    else "Set WAIT_CONNECTWISE_* values to enable read-only PSA inventory."
                )
            ),
            http_probing_enabled=settings.allow_http_probing,
        ),
        ConnectorStatus(
            id="syncro",
            kind="psa",
            name="SyncroMSP",
            status=syncro_status,
            message=(
                "Syncro read-only ticket and customer inventory is configured."
                if syncro_status == "configured"
                else (
                    "Syncro credentials are configured; live reads require WAIT_ALLOW_HTTP_PROBING."
                    if syncro_status == "blocked"
                    else "Set WAIT_SYNCRO_BASE_URL and WAIT_SYNCRO_API_KEY to enable read-only PSA inventory."
                )
            ),
            http_probing_enabled=settings.allow_http_probing,
        ),
        ConnectorStatus(
            id="servicenow",
            kind="psa",
            name="ServiceNow",
            status=servicenow_status,
            message=(
                "ServiceNow read-only incident and company inventory is configured."
                if servicenow_status == "configured"
                else (
                    "ServiceNow credentials are configured; live reads require WAIT_ALLOW_HTTP_PROBING."
                    if servicenow_status == "blocked"
                    else (
                        "Set WAIT_SERVICENOW_BASE_URL, WAIT_SERVICENOW_USERNAME, and "
                        "WAIT_SERVICENOW_PASSWORD to enable read-only PSA inventory."
                    )
                )
            ),
            http_probing_enabled=settings.allow_http_probing,
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
        SecretRecord("WAIT_ITGLUE_BASE_URL", bool(settings.itglue_base_url), "itglue"),
        SecretRecord("WAIT_ITGLUE_API_KEY", bool(settings.itglue_api_key), "itglue"),
        SecretRecord("WAIT_ITGLUE_PAGE_SIZE", bool(settings.itglue_page_size), "itglue"),
        SecretRecord("WAIT_NINJAONE_BASE_URL", bool(settings.ninjaone_base_url), "ninjaone"),
        SecretRecord("WAIT_NINJAONE_CLIENT_ID", bool(settings.ninjaone_client_id), "ninjaone"),
        SecretRecord("WAIT_NINJAONE_CLIENT_SECRET", bool(settings.ninjaone_client_secret), "ninjaone"),
        SecretRecord("WAIT_NINJAONE_SCOPE", bool(settings.ninjaone_scope), "ninjaone"),
        SecretRecord("WAIT_NINJAONE_PAGE_SIZE", bool(settings.ninjaone_page_size), "ninjaone"),
        SecretRecord("WAIT_DATTORMM_BASE_URL", bool(settings.dattormm_base_url), "dattormm"),
        SecretRecord("WAIT_DATTORMM_API_KEY", bool(settings.dattormm_api_key), "dattormm"),
        SecretRecord("WAIT_DATTORMM_API_SECRET", bool(settings.dattormm_api_secret), "dattormm"),
        SecretRecord("WAIT_DATTORMM_PAGE_SIZE", bool(settings.dattormm_page_size), "dattormm"),
        SecretRecord("WAIT_AUTOTASK_BASE_URL", bool(settings.autotask_base_url), "autotask"),
        SecretRecord("WAIT_AUTOTASK_USERNAME", bool(settings.autotask_username), "autotask"),
        SecretRecord("WAIT_AUTOTASK_SECRET", bool(settings.autotask_secret), "autotask"),
        SecretRecord(
            "WAIT_AUTOTASK_INTEGRATION_CODE",
            bool(settings.autotask_integration_code),
            "autotask",
        ),
        SecretRecord("WAIT_AUTOTASK_PAGE_SIZE", bool(settings.autotask_page_size), "autotask"),
        SecretRecord("WAIT_CONNECTWISE_BASE_URL", bool(settings.connectwise_base_url), "connectwise"),
        SecretRecord("WAIT_CONNECTWISE_COMPANY_ID", bool(settings.connectwise_company_id), "connectwise"),
        SecretRecord("WAIT_CONNECTWISE_PUBLIC_KEY", bool(settings.connectwise_public_key), "connectwise"),
        SecretRecord("WAIT_CONNECTWISE_PRIVATE_KEY", bool(settings.connectwise_private_key), "connectwise"),
        SecretRecord("WAIT_CONNECTWISE_CLIENT_ID", bool(settings.connectwise_client_id), "connectwise"),
        SecretRecord("WAIT_CONNECTWISE_PAGE_SIZE", bool(settings.connectwise_page_size), "connectwise"),
        SecretRecord("WAIT_SYNCRO_BASE_URL", bool(settings.syncro_base_url), "syncro"),
        SecretRecord("WAIT_SYNCRO_API_KEY", bool(settings.syncro_api_key), "syncro"),
        SecretRecord("WAIT_SYNCRO_PAGE_SIZE", bool(settings.syncro_page_size), "syncro"),
        SecretRecord("WAIT_SERVICENOW_BASE_URL", bool(settings.servicenow_base_url), "servicenow"),
        SecretRecord("WAIT_SERVICENOW_USERNAME", bool(settings.servicenow_username), "servicenow"),
        SecretRecord("WAIT_SERVICENOW_PASSWORD", bool(settings.servicenow_password), "servicenow"),
        SecretRecord("WAIT_SERVICENOW_PAGE_SIZE", bool(settings.servicenow_page_size), "servicenow"),
    ]


def validate_connector_credentials(
    connector: str,
    settings: Settings,
    *,
    halopsa_client: HaloPSAClient | None = None,
    hudu_client: HuduClient | None = None,
    itglue_client: ItGlueClient | None = None,
    ninjaone_client: RmmClient | None = None,
    dattormm_client: RmmClient | None = None,
    autotask_client: PsaClient | None = None,
    connectwise_client: PsaClient | None = None,
    syncro_client: PsaClient | None = None,
    servicenow_client: PsaClient | None = None,
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
    elif connector == "itglue":
        missing = [
            key
            for key, value in {
                "WAIT_ITGLUE_BASE_URL": settings.itglue_base_url,
                "WAIT_ITGLUE_API_KEY": settings.itglue_api_key,
            }.items()
            if not value
        ]
        if missing:
            return ConnectorValidationResult(
                connector,
                False,
                "config",
                f"IT Glue credentials are incomplete: {', '.join(missing)}.",
            )
        result = (itglue_client or ItGlueClient(settings)).health()
    elif connector == "ninjaone":
        missing = [
            key
            for key, value in {
                "WAIT_NINJAONE_BASE_URL": settings.ninjaone_base_url,
                "WAIT_NINJAONE_CLIENT_ID": settings.ninjaone_client_id,
                "WAIT_NINJAONE_CLIENT_SECRET": settings.ninjaone_client_secret,
            }.items()
            if not value
        ]
        if missing:
            return ConnectorValidationResult(
                connector,
                False,
                "config",
                f"NinjaOne credentials are incomplete: {', '.join(missing)}.",
            )
        result = (ninjaone_client or NinjaOneClient(settings)).health()
    elif connector == "dattormm":
        missing = [
            key
            for key, value in {
                "WAIT_DATTORMM_BASE_URL": settings.dattormm_base_url,
                "WAIT_DATTORMM_API_KEY": settings.dattormm_api_key,
                "WAIT_DATTORMM_API_SECRET": settings.dattormm_api_secret,
            }.items()
            if not value
        ]
        if missing:
            return ConnectorValidationResult(
                connector,
                False,
                "config",
                f"Datto RMM credentials are incomplete: {', '.join(missing)}.",
            )
        result = (dattormm_client or DattoRmmClient(settings)).health()
    elif connector == "autotask":
        missing = [
            key
            for key, value in {
                "WAIT_AUTOTASK_BASE_URL": settings.autotask_base_url,
                "WAIT_AUTOTASK_USERNAME": settings.autotask_username,
                "WAIT_AUTOTASK_SECRET": settings.autotask_secret,
                "WAIT_AUTOTASK_INTEGRATION_CODE": settings.autotask_integration_code,
            }.items()
            if not value
        ]
        if missing:
            return ConnectorValidationResult(
                connector,
                False,
                "config",
                f"Autotask credentials are incomplete: {', '.join(missing)}.",
            )
        result = (autotask_client or AutotaskClient(settings)).health()
    elif connector == "connectwise":
        missing = [
            key
            for key, value in {
                "WAIT_CONNECTWISE_BASE_URL": settings.connectwise_base_url,
                "WAIT_CONNECTWISE_COMPANY_ID": settings.connectwise_company_id,
                "WAIT_CONNECTWISE_PUBLIC_KEY": settings.connectwise_public_key,
                "WAIT_CONNECTWISE_PRIVATE_KEY": settings.connectwise_private_key,
                "WAIT_CONNECTWISE_CLIENT_ID": settings.connectwise_client_id,
            }.items()
            if not value
        ]
        if missing:
            return ConnectorValidationResult(
                connector,
                False,
                "config",
                f"ConnectWise credentials are incomplete: {', '.join(missing)}.",
            )
        result = (connectwise_client or ConnectWiseClient(settings)).health()
    elif connector == "syncro":
        missing = [
            key
            for key, value in {
                "WAIT_SYNCRO_BASE_URL": settings.syncro_base_url,
                "WAIT_SYNCRO_API_KEY": settings.syncro_api_key,
            }.items()
            if not value
        ]
        if missing:
            return ConnectorValidationResult(
                connector,
                False,
                "config",
                f"Syncro credentials are incomplete: {', '.join(missing)}.",
            )
        result = (syncro_client or SyncroClient(settings)).health()
    elif connector == "servicenow":
        missing = [
            key
            for key, value in {
                "WAIT_SERVICENOW_BASE_URL": settings.servicenow_base_url,
                "WAIT_SERVICENOW_USERNAME": settings.servicenow_username,
                "WAIT_SERVICENOW_PASSWORD": settings.servicenow_password,
            }.items()
            if not value
        ]
        if missing:
            return ConnectorValidationResult(
                connector,
                False,
                "config",
                f"ServiceNow credentials are incomplete: {', '.join(missing)}.",
            )
        result = (servicenow_client or ServiceNowClient(settings)).health()
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
        payload_json=json.dumps(redact_value(payload), sort_keys=True),
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


def draft_ninjaone_script_execution(
    store: Store,
    device_id: str,
    script_id: str,
    variables: dict[str, object] | None = None,
    *,
    run_as: str = "",
    client_id: str | None = None,
) -> ApprovalRequest:
    normalized_device_id = _validate_ninjaone_device_id(device_id)
    normalized_script_id = _validate_ninjaone_script_id(script_id)
    normalized_variables = _validate_ninjaone_variables(variables)
    if len(run_as) > 200 or any(character in run_as for character in "\r\n"):
        raise ValueError("NinjaOne run_as must be a bounded single-line value")
    payload: dict[str, object] = {
        "connector": "ninjaone",
        "device_id": normalized_device_id,
        "script_id": normalized_script_id,
        "variables": normalized_variables,
        "run_as": run_as.strip(),
    }
    return store.create_approval_request(
        normalized_device_id,
        "ninjaone.script.run",
        payload,
        client_id=client_id,
    )


def execute_ninjaone_approval_request(
    store: Store,
    client: RmmExecutionClient,
    request_id: int,
) -> ApprovalRequest:
    approval = store.get_approval_request(request_id)
    if approval is None:
        raise KeyError(request_id)
    if approval.action_type != "ninjaone.script.run":
        raise ValueError("approval request is not a NinjaOne script action")
    if approval.status != "approved":
        raise PermissionError("NinjaOne script execution requires an approved approval request")
    if approval.execution_status == "succeeded":
        raise RuntimeError("NinjaOne approval request has already executed successfully")
    try:
        payload = json.loads(approval.payload_json)
    except json.JSONDecodeError as exc:
        raise ValueError("approval payload is malformed") from exc
    if not isinstance(payload, dict):
        raise ValueError("approval payload is malformed")
    if payload.get("connector") != "ninjaone":
        raise ValueError("approval payload connector does not match NinjaOne")
    device_id = _validate_ninjaone_device_id(str(payload.get("device_id") or ""))
    if device_id != approval.subject_id:
        raise ValueError("approval payload device does not match approval request")
    script_id = _validate_ninjaone_script_id(str(payload.get("script_id") or ""))
    variables = _validate_ninjaone_variables(payload.get("variables"))
    run_as = payload.get("run_as", "")
    if not isinstance(run_as, str):
        raise ValueError("NinjaOne approval run_as must be a string")
    result = client.execute_script(device_id, script_id, variables, run_as)
    return store.record_approval_execution(
        request_id,
        status=result.status,
        message=result.message,
        result=sanitize_ninjaone_execution_result(result),
        event_type="rmm.write",
    )


def sanitize_ninjaone_execution_result(result: RmmExecutionResult) -> dict[str, object]:
    return {
        "connector": "ninjaone",
        "operation": "script.run",
        "device_id": result.device_id,
        "script_id": result.script_id,
        "status": result.status,
        "status_code": result.status_code,
        "remote_id": result.remote_id,
    }


def _validate_ninjaone_device_id(value: str) -> str:
    normalized = value.strip()
    if not normalized or any(character in normalized for character in "/?#"):
        raise ValueError("NinjaOne device identifiers must be single path segments")
    return normalized


def _validate_ninjaone_script_id(value: str) -> str:
    normalized = value.strip()
    if not normalized.isdecimal() or int(normalized) <= 0:
        raise ValueError("NinjaOne script identifiers must be positive numeric IDs")
    return str(int(normalized))


def _validate_ninjaone_variables(value: object) -> dict[str, object]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("NinjaOne script variables must be an object")
    sensitive_tokens = (
        "secret",
        "token",
        "password",
        "credential",
        "authorization",
        "bearer",
        "api_key",
    )
    for key in value:
        if not isinstance(key, str) or not key.strip():
            raise ValueError("NinjaOne script variable names must be non-empty strings")
        if any(token in key.lower() for token in sensitive_tokens):
            raise ValueError("NinjaOne script variables must not contain secret-like names")
    try:
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise ValueError("NinjaOne script variables must be JSON serializable") from exc
    if len(value) > 50 or len(encoded.encode("utf-8")) > 16_384:
        raise ValueError("NinjaOne script variables exceed the bounded request limit")
    return dict(value)


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
