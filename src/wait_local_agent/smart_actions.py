from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal, Protocol, cast

from wait_local_agent.autotask import AutotaskReadProvider, AutotaskWriteProvider
from wait_local_agent.communication import (
    CommunicationChannel,
    CommunicationDeliveryError,
    CommunicationMessage,
    CommunicationProvider,
    CommunicationSender,
    ConfiguredCommunicationProvider,
    PreviewCommunicationProvider,
)
from wait_local_agent.config import Settings
from wait_local_agent.confluence import ConfluenceClientProtocol
from wait_local_agent.connectwise import ConnectWiseReadProvider, ConnectWiseWriteProvider
from wait_local_agent.itglue import ItGlueClientProtocol
from wait_local_agent.m365_graph import M365GraphReadProvider
from wait_local_agent.models import (
    DEFAULT_APPROVAL_EXPIRY_SECONDS,
    MAX_APPROVAL_EXPIRY_SECONDS,
    ApprovalRequest,
    AutotaskWriteRequest,
    ConnectWiseWriteRequest,
    HaloWriteRequest,
    ServiceNowWriteRequest,
    SourceReference,
    SyncroWriteRequest,
    Ticket,
)
from wait_local_agent.notion import NotionClient, NotionClientProtocol
from wait_local_agent.nsight import PATCH_POLICY_SERVICES
from wait_local_agent.observability import ArtifactRecord, ExecutionRecorder, StepRecord
from wait_local_agent.providers import (
    DeterministicLocalProvider,
    ModelProvider,
    ProviderUnavailableError,
    provider_from_settings,
    provider_metadata,
)
from wait_local_agent.rbac import Role
from wait_local_agent.reports.renderers import redact_text, redact_value
from wait_local_agent.retrieval import retrieve_sources
from wait_local_agent.rmm import (
    LocalCollectorRmmAdapter,
    RmmInventoryProvider,
    rmm_provider_from_settings,
)
from wait_local_agent.scalepad import ScalePadClient, ScalePadReadProvider
from wait_local_agent.screenconnect import ScreenConnectRmmAdapter
from wait_local_agent.servicenow import ServiceNowReadProvider, ServiceNowWriteProvider
from wait_local_agent.services import classify_ticket
from wait_local_agent.sharepoint import SharePointClientProtocol
from wait_local_agent.store import SMART_ACTION_APPROVAL_CAPABILITY, Store
from wait_local_agent.syncro import SyncroReadProvider, SyncroWriteProvider
from wait_local_agent.timezest import TimeZestClient, TimeZestReadProvider, TimeZestWriteProvider

if TYPE_CHECKING:
    from wait_local_agent.collectors import CollectorPreview


class CollectorPreviewProvider(Protocol):
    def preview(
        self,
        module_id: str,
        config: dict[str, object],
        *,
        client_id: str | None = None,
    ) -> CollectorPreview:
        """Validate and preview an existing read-only collector."""


class M365LifecycleWriteProvider(Protocol):
    def write_health(self) -> object:
        """Return the guarded Microsoft Graph write readiness result."""

    def disable_user(self, *, user_identity: str) -> object:
        """Disable one explicitly identified Microsoft 365 user."""

    def revoke_user_sessions(self, *, user_id: str) -> object:
        """Revoke sessions for one explicitly identified Microsoft 365 user."""


class M365UserCreateProvider(Protocol):
    def write_health(self) -> object:
        """Return the guarded Microsoft Graph write readiness result."""

    def create_user(
        self,
        *,
        user_principal_name: str,
        display_name: str,
        mail_nickname: str,
        temporary_password: str,
        account_enabled: bool,
        force_change_password_next_sign_in: bool,
    ) -> object:
        """Create one explicitly approved Microsoft 365 user."""


class M365PasswordResetProvider(Protocol):
    def write_health(self) -> object:
        """Return the guarded Microsoft Graph write readiness result."""

    def reset_user_password(
        self,
        *,
        user_identity: str,
        temporary_password: str,
        force_change_password_next_sign_in: bool,
        force_change_password_next_sign_in_with_mfa: bool,
    ) -> object:
        """Reset one explicitly identified user's password."""


class M365AuthenticationMethodDeleteProvider(Protocol):
    def write_health(self) -> object:
        """Return the guarded Microsoft Graph write readiness result."""

    def delete_authentication_method(
        self,
        *,
        user_identity: str,
        method_type: str,
        method_id: str,
    ) -> object:
        """Remove one explicitly identified authentication method."""


class M365GroupMembershipWriteProvider(Protocol):
    def write_health(self) -> object:
        """Return the guarded Microsoft Graph write readiness result."""

    def change_group_membership(
        self,
        *,
        group_id: str,
        user_id: str,
        operation: str,
    ) -> object:
        """Add or remove one explicitly identified group membership."""


class M365LicenseWriteProvider(Protocol):
    def write_health(self) -> object:
        """Return the guarded Microsoft Graph write readiness result."""

    def change_user_licenses(
        self,
        *,
        user_id: str,
        sku_ids: list[str],
        operation: str,
    ) -> object:
        """Add or remove explicitly identified license SKU IDs for one user."""


class M365SessionRevocationWriteProvider(Protocol):
    def write_health(self) -> object:
        """Return the guarded Microsoft Graph write readiness result."""

    def revoke_user_sessions(self, *, user_id: str) -> object:
        """Revoke sessions for one explicitly identified user."""


class M365MailboxSettingsWriteProvider(Protocol):
    def write_health(self) -> object:
        """Return the guarded Microsoft Graph write readiness result."""

    def update_mailbox_settings(
        self,
        *,
        user_identity: str,
        settings: dict[str, str],
    ) -> object:
        """Update only the allowlisted mailbox settings for one user."""


class M365MailMessageMoveWriteProvider(Protocol):
    def write_health(self) -> object:
        """Return the guarded Microsoft Graph write readiness result."""

    def move_mail_message(
        self,
        *,
        user_identity: str,
        source_folder_id: str,
        message_id: str,
        destination_folder_id: str,
    ) -> object:
        """Move one explicitly identified message to one destination folder."""


class M365MailMessageReadStateWriteProvider(Protocol):
    def write_health(self) -> object:
        """Return the guarded Microsoft Graph write readiness result."""

    def update_mail_message_read_state(
        self,
        *,
        user_identity: str,
        source_folder_id: str,
        message_id: str,
        is_read: bool,
    ) -> object:
        """Update the read state for one explicitly identified message."""


class M365MailMessageDeleteWriteProvider(Protocol):
    def write_health(self) -> object:
        """Return the guarded Microsoft Graph write readiness result."""

    def delete_mail_message(
        self,
        *,
        user_identity: str,
        source_folder_id: str,
        message_id: str,
    ) -> object:
        """Delete one explicitly identified message."""


class M365ManagedDeviceWriteProvider(Protocol):
    def write_health(self) -> object:
        """Return the guarded Microsoft Graph write readiness result."""

    def retire_managed_device(self, *, device_id: str) -> object:
        """Retire one explicitly identified Intune managed device."""

    def sync_managed_device(self, *, device_id: str) -> object:
        """Request synchronization for one explicitly identified device."""

    def reboot_managed_device(self, *, device_id: str) -> object:
        """Request reboot for one explicitly identified device."""

    def remote_lock_managed_device(self, *, device_id: str) -> object:
        """Request remote lock for one explicitly identified device."""


ActionStatus = Literal[
    "success",
    "provider_not_configured",
    "not_authorized",
    "failed",
    "pending_approval",
    "rejected",
]

_POSITIVE_SENTIMENT_TERMS = frozenset(
    {"thanks", "thank", "great", "resolved", "working", "success", "appreciate", "helpful", "excellent", "fixed"}
)
_NEGATIVE_SENTIMENT_TERMS = frozenset(
    {
        "urgent",
        "down",
        "blocked",
        "broken",
        "failure",
        "failed",
        "error",
        "angry",
        "unhappy",
        "outage",
        "problem",
        "critical",
        "cannot",
    }
)
_SECURITY_ALERT_TERMS = frozenset(
    {
        "account takeover",
        "breach",
        "credential theft",
        "data exfiltration",
        "edr",
        "impossible travel",
        "malware",
        "mfa fatigue",
        "phishing",
        "ransomware",
        "security alert",
        "suspicious login",
        "unauthorized access",
    }
)
_CRITICAL_SECURITY_TERMS = frozenset(
    {"account takeover", "breach", "credential theft", "data exfiltration", "malware", "ransomware"}
)


@dataclass(frozen=True)
class SmartActionManifest:
    action_id: str
    title: str
    description: str
    kind: Literal["deterministic", "ai_assisted"]
    input_schema: dict[str, object]
    output_schema: dict[str, object]
    requires_approval: bool
    estimated_minutes_saved: int
    risk_level: str = "low"
    required_role: str = "technician"
    access_mode: str = "read"
    approval_expiry_seconds: int = DEFAULT_APPROVAL_EXPIRY_SECONDS


@dataclass
class ActionContext:
    store: Store
    settings: Settings
    provider: ModelProvider | None = None
    actor: str = ""
    client_id: str | None = None
    provider_available: bool = False
    collector_service: CollectorPreviewProvider | None = None
    rmm_provider: RmmInventoryProvider | None = None
    connectwise_client: ConnectWiseReadProvider | ConnectWiseWriteProvider | None = None
    syncro_client: SyncroReadProvider | SyncroWriteProvider | None = None
    servicenow_client: ServiceNowReadProvider | ServiceNowWriteProvider | None = None
    autotask_client: AutotaskReadProvider | AutotaskWriteProvider | None = None
    itglue_client: ItGlueClientProtocol | None = None
    confluence_client: ConfluenceClientProtocol | None = None
    notion_client: NotionClientProtocol | None = None
    sharepoint_client: SharePointClientProtocol | None = None
    m365_client: (
        M365GraphReadProvider
        | M365LifecycleWriteProvider
        | M365UserCreateProvider
        | M365PasswordResetProvider
        | M365AuthenticationMethodDeleteProvider
        | M365GroupMembershipWriteProvider
        | M365LicenseWriteProvider
        | M365SessionRevocationWriteProvider
        | M365MailboxSettingsWriteProvider
        | M365MailMessageMoveWriteProvider
        | M365MailMessageReadStateWriteProvider
        | M365MailMessageDeleteWriteProvider
        | M365ManagedDeviceWriteProvider
        | None
    ) = None
    halopsa_client: HaloPSAReadProvider | HaloPSAWriteProvider | None = None
    hudu_client: HuduReadProvider | None = None
    communication_provider: CommunicationProvider | None = None
    communication_sender: CommunicationSender | None = None
    timezest_client: TimeZestReadProvider | TimeZestWriteProvider | None = None
    scalepad_client: ScalePadReadProvider | None = None


class HaloPSAReadProvider(Protocol):
    def get_ticket(self, ticket_id: str) -> object:
        """Read one PSA ticket through the existing guarded client."""


class HaloPSAWriteProvider(Protocol):
    def write_health(self) -> object:
        """Return the guarded HaloPSA write readiness result."""

    def execute_write(self, request: HaloWriteRequest) -> object:
        """Execute one explicitly approved HaloPSA ticket write."""


class HuduReadProvider(Protocol):
    def list_articles(
        self,
        company_id: str | None = None,
        page: int = 1,
        page_size: int | None = None,
    ) -> object:
        """Read documentation articles through the existing guarded client."""


class TimeZestSchedulingRequestLookupAction:
    manifest = SmartActionManifest(
        action_id="timezest-scheduling-request-lookup",
        title="TimeZest scheduling-request lookup",
        description=(
            "Read tenant-mapped TimeZest scheduling requests and appointment status "
            "through the documented read-only API."
        ),
        kind="deterministic",
        input_schema={
            "type": "object",
            "required": ["client_id"],
            "properties": {
                "client_id": {"type": "string", "minLength": 1, "maxLength": 120},
                "limit": {"type": "integer", "minimum": 1, "maximum": 20},
            },
        },
        output_schema={
            "client_id": "string",
            "requests": "array",
            "count": "integer",
            "has_more": "boolean",
            "connector_status": "string",
        },
        requires_approval=False,
        estimated_minutes_saved=5,
        risk_level="low",
        required_role="technician",
        access_mode="read",
    )

    def run(self, context: ActionContext, payload: dict[str, object]) -> ActionResult:
        client_id = payload.get("client_id")
        if not isinstance(client_id, str) or not client_id.strip() or len(client_id.strip()) > 120:
            return _failed("client_id must be a non-empty string of at most 120 characters")
        scoped_client_id = client_id.strip()
        if context.client_id is not None and scoped_client_id != context.client_id:
            return _failed("client_id is outside the tenant scope")
        limit = payload.get("limit", 20)
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 20:
            return _failed("limit must be an integer between 1 and 20")
        provider = context.timezest_client or TimeZestClient(context.settings)
        try:
            response = provider.list_scheduling_requests(client_id=scoped_client_id, limit=limit)
        except Exception:
            return _failed("TimeZest scheduling-request lookup failed")
        result = getattr(response, "result", None)
        status = str(getattr(result, "status", "failed"))
        message = redact_text(str(getattr(result, "message", "TimeZest read failed")))
        items = getattr(response, "items", [])
        if not isinstance(items, list):
            return _failed("TimeZest returned malformed scheduling-request data")
        if status != "ready":
            return ActionResult(
                status="failed",
                output={
                    "client_id": scoped_client_id,
                    "connector_status": status,
                    "requests": [],
                    "count": 0,
                    "has_more": False,
                },
                error_detail=message,
            )
        requests: list[dict[str, object]] = []
        for item in items[:limit]:
            if not hasattr(item, "__dataclass_fields__"):
                return _failed("TimeZest returned malformed scheduling-request data")
            requests.append(cast(dict[str, object], redact_value(asdict(item))))
        return ActionResult(
            status="success",
            output={
                "client_id": scoped_client_id,
                "connector_status": status,
                "requests": requests,
                "count": len(requests),
                "has_more": bool(getattr(response, "has_more", False)),
            },
            evidence=[
                {
                    "type": "connector_read",
                    "connector": "timezest",
                    "operation": "scheduling_requests.list",
                    "client_id": scoped_client_id,
                }
            ],
        )


class TimeZestSchedulingRequestCreateAction:
    manifest = SmartActionManifest(
        action_id="timezest-scheduling-request-create",
        title="TimeZest create scheduling request",
        description=(
            "Prepare an approval-gated TimeZest scheduling request using the documented "
            "create API and one tenant-mapped PSA company."
        ),
        kind="deterministic",
        input_schema={
            "type": "object",
            "required": [
                "appointment_type_id",
                "trigger_mode",
                "resource_ids",
                "end_user_name",
                "end_user_email",
            ],
            "properties": {
                "client_id": {"type": "string", "minLength": 1, "maxLength": 120},
                "appointment_type_id": {"type": "string", "minLength": 1, "maxLength": 120},
                "trigger_mode": {"type": "string", "enum": ["pod", "generate_url"]},
                "resource_ids": {"type": "array", "minItems": 1, "maxItems": 20},
                "duration_mins": {"type": "integer", "minimum": 1, "maximum": 1440},
                "earliest_date": {"type": "string", "pattern": "^[0-9]{4}-[0-9]{2}-[0-9]{2}$"},
                "earliest_time": {"type": "string", "pattern": "^[0-9]{2}:[0-9]{2}:[0-9]{2}$"},
                "latest_date": {"type": "string", "pattern": "^[0-9]{4}-[0-9]{2}-[0-9]{2}$"},
                "latest_time": {"type": "string", "pattern": "^[0-9]{2}:[0-9]{2}:[0-9]{2}$"},
                "end_user_name": {"type": "string", "minLength": 1, "maxLength": 500},
                "end_user_email": {"type": "string", "minLength": 3, "maxLength": 320},
                "end_user_company": {"type": "string", "minLength": 1, "maxLength": 500},
            },
        },
        output_schema={
            "operation": "string",
            "connector_status": "string",
            "client_id": "string",
            "request": "object",
            "approval_required": "boolean",
            "approved": "boolean",
        },
        requires_approval=True,
        estimated_minutes_saved=5,
        risk_level="high",
        required_role="technician",
        access_mode="write",
    )

    def run(self, context: ActionContext, payload: dict[str, object]) -> ActionResult:
        allowed = {
            "client_id",
            "appointment_type_id",
            "trigger_mode",
            "resource_ids",
            "duration_mins",
            "earliest_date",
            "earliest_time",
            "latest_date",
            "latest_time",
            "end_user_name",
            "end_user_email",
            "end_user_company",
            "_approval_completed",
        }
        if set(payload) - allowed:
            return _failed("TimeZest scheduling-request create payload contains unsupported fields")
        client_id = payload.get("client_id", context.client_id)
        if not isinstance(client_id, str) or not client_id.strip() or len(client_id.strip()) > 120:
            return _failed("client_id must be a non-empty string of at most 120 characters")
        scoped_client_id = client_id.strip()
        if context.client_id is not None and scoped_client_id != context.client_id:
            return _failed("client_id is outside the tenant scope")
        appointment_type_id = payload.get("appointment_type_id")
        trigger_mode = payload.get("trigger_mode")
        resource_ids = payload.get("resource_ids")
        end_user_name = payload.get("end_user_name")
        end_user_email = payload.get("end_user_email")
        if not isinstance(appointment_type_id, str) or not appointment_type_id.strip():
            return _failed("appointment_type_id must be a non-empty string")
        if not isinstance(trigger_mode, str) or trigger_mode not in {"pod", "generate_url"}:
            return _failed("trigger_mode must be pod or generate_url")
        if (
            not isinstance(resource_ids, list)
            or not resource_ids
            or len(resource_ids) > 20
            or any(not isinstance(item, str) or not item.strip() for item in resource_ids)
        ):
            return _failed("resource_ids must be a non-empty array of at most 20 strings")
        if len({item.strip() for item in resource_ids}) != len(resource_ids):
            return _failed("resource_ids must not contain duplicates")
        if not isinstance(end_user_name, str) or not end_user_name.strip():
            return _failed("end_user_name must be a non-empty string")
        if (
            not isinstance(end_user_email, str)
            or end_user_email.count("@") != 1
            or any(character.isspace() for character in end_user_email)
        ):
            return _failed("end_user_email must be a valid email address")

        optional_values = {
            name: payload.get(name)
            for name in (
                "duration_mins",
                "earliest_date",
                "earliest_time",
                "latest_date",
                "latest_time",
                "end_user_company",
            )
        }
        for name, value in optional_values.items():
            if value is not None and not isinstance(value, (str, int)):
                return _failed(f"{name} has an invalid type")
        duration_mins = optional_values["duration_mins"]
        if duration_mins is not None and (
            isinstance(duration_mins, bool)
            or not isinstance(duration_mins, int)
            or not 1 <= duration_mins <= 1_440
        ):
            return _failed("duration_mins must be an integer between 1 and 1440")
        for name in ("earliest_date", "earliest_time", "latest_date", "latest_time", "end_user_company"):
            value = optional_values[name]
            if value is not None and (not isinstance(value, str) or not value.strip()):
                return _failed(f"{name} must be a non-empty string when provided")

        provider = cast(
            TimeZestWriteProvider,
            context.timezest_client or TimeZestClient(context.settings),
        )
        try:
            health = provider.write_health()
        except Exception:
            return _failed("TimeZest write readiness check failed")
        connector_status = str(getattr(health, "status", "failed"))
        connector_message = redact_text(
            str(getattr(health, "message", "TimeZest writes are unavailable"))
        )
        output: dict[str, object] = {
            "operation": "scheduling_request.create",
            "connector_status": connector_status,
            "client_id": scoped_client_id,
            "approval_required": not bool(payload.get("_approval_completed")),
            "approved": bool(payload.get("_approval_completed")),
        }
        evidence = [
            {
                "type": "connector_write_preflight",
                "connector": "timezest",
                "operation": "scheduling_requests.create",
                "client_id": scoped_client_id,
                "appointment_type_id": appointment_type_id.strip(),
                "trigger_mode": trigger_mode,
                "resource_count": len(resource_ids),
                "end_user_email_provided": True,
            }
        ]
        if connector_status != "ready":
            return ActionResult(status="failed", output=output, evidence=evidence, error_detail=connector_message)
        if not payload.get("_approval_completed"):
            return ActionResult(status="success", output=output, evidence=evidence)
        try:
            response = provider.create_scheduling_request(
                client_id=scoped_client_id,
                appointment_type_id=appointment_type_id.strip(),
                trigger_mode=trigger_mode,
                resource_ids=resource_ids,
                duration_mins=cast(int | None, duration_mins),
                earliest_date=cast(str | None, optional_values["earliest_date"]),
                earliest_time=cast(str | None, optional_values["earliest_time"]),
                latest_date=cast(str | None, optional_values["latest_date"]),
                latest_time=cast(str | None, optional_values["latest_time"]),
                end_user_name=end_user_name.strip(),
                end_user_email=end_user_email.strip(),
                end_user_company=cast(str | None, optional_values["end_user_company"]),
            )
        except Exception:
            return ActionResult(
                status="failed",
                output=output,
                evidence=evidence,
                error_detail="TimeZest scheduling-request creation failed",
            )
        response_result = getattr(response, "result", None)
        response_status = str(getattr(response_result, "status", "failed"))
        response_message = redact_text(
            str(getattr(response_result, "message", "TimeZest scheduling-request creation failed"))
        )
        request = getattr(response, "request", {})
        if response_status != "ready" or not isinstance(request, dict) or not request.get("id"):
            return ActionResult(
                status="failed",
                output=output,
                evidence=evidence,
                error_detail=response_message,
            )
        return ActionResult(
            status="success",
            output={**output, "connector_status": response_status, "request": redact_value(request)},
            evidence=evidence,
        )


class ScalePadClientLookupAction:
    manifest = SmartActionManifest(
        action_id="scalepad-client-lookup",
        title="ScalePad client lookup",
        description=(
            "Read one tenant-mapped ScalePad Core client record through the "
            "documented read-only API."
        ),
        kind="deterministic",
        input_schema={
            "type": "object",
            "required": ["client_id"],
            "properties": {
                "client_id": {"type": "string", "minLength": 1, "maxLength": 120},
            },
        },
        output_schema={
            "client_id": "string",
            "clients": "array",
            "count": "integer",
            "next_cursor": "string",
            "connector_status": "string",
        },
        requires_approval=False,
        estimated_minutes_saved=5,
        risk_level="low",
        required_role="technician",
        access_mode="read",
    )

    def run(self, context: ActionContext, payload: dict[str, object]) -> ActionResult:
        client_id = payload.get("client_id")
        if not isinstance(client_id, str) or not client_id.strip() or len(client_id.strip()) > 120:
            return _failed("client_id must be a non-empty string of at most 120 characters")
        scoped_client_id = client_id.strip()
        if context.client_id is not None and scoped_client_id != context.client_id:
            return _failed("client_id is outside the tenant scope")
        provider = context.scalepad_client or ScalePadClient(context.settings)
        try:
            response = provider.get_client(client_id=scoped_client_id)
        except Exception:
            return _failed("ScalePad client lookup failed")
        result = getattr(response, "result", None)
        status = str(getattr(result, "status", "failed"))
        message = redact_text(str(getattr(result, "message", "ScalePad read failed")))
        items = getattr(response, "items", [])
        if not isinstance(items, list):
            return _failed("ScalePad returned malformed client data")
        if status != "ready":
            return ActionResult(
                status="failed",
                output={
                    "client_id": scoped_client_id,
                    "connector_status": status,
                    "clients": [],
                    "count": 0,
                    "next_cursor": "",
                },
                error_detail=message,
            )
        clients: list[dict[str, object]] = []
        for item in items[:1]:
            if not hasattr(item, "__dataclass_fields__"):
                return _failed("ScalePad returned malformed client data")
            clients.append(cast(dict[str, object], redact_value(asdict(item))))
        return ActionResult(
            status="success",
            output={
                "client_id": scoped_client_id,
                "connector_status": status,
                "clients": clients,
                "count": len(clients),
                "next_cursor": str(getattr(response, "next_cursor", "")),
            },
            evidence=[
                {
                    "type": "connector_read",
                    "connector": "scalepad",
                    "operation": "clients.get",
                    "client_id": scoped_client_id,
                }
            ],
        )


class ScalePadRiskSummaryAction:
    manifest = SmartActionManifest(
        action_id="scalepad-risk-summary",
        title="ScalePad client risk summary",
        description=(
            "Read one explicitly mapped ScalePad ControlMap risk-summary page "
            "through the documented read-only API."
        ),
        kind="deterministic",
        input_schema={
            "type": "object",
            "required": ["client_id"],
            "properties": {
                "client_id": {"type": "string", "minLength": 1, "maxLength": 120},
            },
        },
        output_schema={
            "client_id": "string",
            "risk_summaries": "array",
            "count": "integer",
            "total_count": "integer|null",
            "next_cursor": "string",
            "connector_status": "string",
        },
        requires_approval=False,
        estimated_minutes_saved=5,
        risk_level="low",
        required_role="technician",
        access_mode="read",
    )

    def run(self, context: ActionContext, payload: dict[str, object]) -> ActionResult:
        client_id = payload.get("client_id")
        if not isinstance(client_id, str) or not client_id.strip() or len(client_id.strip()) > 120:
            return _failed("client_id must be a non-empty string of at most 120 characters")
        scoped_client_id = client_id.strip()
        if context.client_id is not None and scoped_client_id != context.client_id:
            return _failed("client_id is outside the tenant scope")
        provider = context.scalepad_client or ScalePadClient(context.settings)
        try:
            response = provider.get_risk_summary(client_id=scoped_client_id)
        except Exception:
            return _failed("ScalePad risk-summary lookup failed")
        result = getattr(response, "result", None)
        status = str(getattr(result, "status", "failed"))
        message = redact_text(str(getattr(result, "message", "ScalePad risk-summary read failed")))
        items = getattr(response, "items", [])
        if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
            return _failed("ScalePad returned malformed risk-summary data")
        output = {
            "client_id": scoped_client_id,
            "connector_status": status,
            "risk_summaries": [cast(dict[str, object], redact_value(item)) for item in items[:20]],
            "count": len(items[:20]),
            "total_count": getattr(response, "total_count", None),
            "next_cursor": str(getattr(response, "next_cursor", "")),
        }
        if status != "ready":
            output["risk_summaries"] = []
            output["count"] = 0
            output["total_count"] = None
            output["next_cursor"] = ""
            return ActionResult(status="failed", output=output, error_detail=message)
        return ActionResult(
            status="success",
            output=output,
            evidence=[
                {
                    "type": "connector_read",
                    "connector": "scalepad",
                    "operation": "clients.risks-summary",
                    "client_id": scoped_client_id,
                }
            ],
        )


class ScalePadComplianceHealthAction:
    manifest = SmartActionManifest(
        action_id="scalepad-compliance-health",
        title="ScalePad compliance health",
        description=(
            "Read one explicitly mapped ScalePad ControlMap compliance-health "
            "snapshot through the documented read-only API."
        ),
        kind="deterministic",
        input_schema={
            "type": "object",
            "required": ["client_id"],
            "properties": {
                "client_id": {"type": "string", "minLength": 1, "maxLength": 120},
            },
        },
        output_schema={
            "client_id": "string",
            "health": "object|null",
            "connector_status": "string",
        },
        requires_approval=False,
        estimated_minutes_saved=5,
        risk_level="low",
        required_role="technician",
        access_mode="read",
    )

    def run(self, context: ActionContext, payload: dict[str, object]) -> ActionResult:
        client_id = payload.get("client_id")
        if not isinstance(client_id, str) or not client_id.strip() or len(client_id.strip()) > 120:
            return _failed("client_id must be a non-empty string of at most 120 characters")
        scoped_client_id = client_id.strip()
        if context.client_id is not None and scoped_client_id != context.client_id:
            return _failed("client_id is outside the tenant scope")
        provider = context.scalepad_client or ScalePadClient(context.settings)
        try:
            response = provider.get_compliance_health(client_id=scoped_client_id)
        except Exception:
            return _failed("ScalePad compliance health lookup failed")
        result = getattr(response, "result", None)
        status = str(getattr(result, "status", "failed"))
        message = redact_text(
            str(getattr(result, "message", "ScalePad compliance health read failed"))
        )
        health = getattr(response, "item", None)
        if health is not None and not isinstance(health, dict):
            return _failed("ScalePad returned malformed compliance health data")
        output: dict[str, object]
        if status != "ready" or health is None:
            output = {
                "client_id": scoped_client_id,
                "connector_status": status,
                "health": None,
            }
            return ActionResult(status="failed", output=output, error_detail=message)
        output = {
            "client_id": scoped_client_id,
            "connector_status": status,
            "health": cast(dict[str, object], redact_value(health)),
        }
        return ActionResult(
            status="success",
            output=output,
            evidence=[
                {
                    "type": "connector_read",
                    "connector": "scalepad",
                    "operation": "clients.health",
                    "client_id": scoped_client_id,
                }
            ],
        )


class ScalePadGoalLookupAction:
    manifest = SmartActionManifest(
        action_id="scalepad-goal-lookup",
        title="ScalePad Lifecycle goal lookup",
        description=(
            "Read tenant-mapped ScalePad Lifecycle Manager goals through the "
            "documented read-only API."
        ),
        kind="deterministic",
        input_schema={
            "type": "object",
            "required": ["client_id"],
            "properties": {
                "client_id": {"type": "string", "minLength": 1, "maxLength": 120},
                "status": {
                    "type": "string",
                    "enum": ["AtRisk", "Complete", "OffTrack", "OnHold", "OnTrack"],
                },
                "title": {"type": "string", "minLength": 1, "maxLength": 200},
                "cursor": {"type": "string", "maxLength": 200},
            },
        },
        output_schema={
            "client_id": "string",
            "goals": "array",
            "count": "integer",
            "total_count": "integer|null",
            "next_cursor": "string",
            "connector_status": "string",
        },
        requires_approval=False,
        estimated_minutes_saved=5,
        risk_level="low",
        required_role="technician",
        access_mode="read",
    )

    def run(self, context: ActionContext, payload: dict[str, object]) -> ActionResult:
        client_id = payload.get("client_id")
        if not isinstance(client_id, str) or not client_id.strip() or len(client_id.strip()) > 120:
            return _failed("client_id must be a non-empty string of at most 120 characters")
        scoped_client_id = client_id.strip()
        if context.client_id is not None and scoped_client_id != context.client_id:
            return _failed("client_id is outside the tenant scope")

        filters: dict[str, str | None] = {}
        for key, limit in (("status", 32), ("title", 200), ("cursor", 200)):
            value = payload.get(key)
            if value is not None:
                if not isinstance(value, str) or not value.strip() or len(value.strip()) > limit:
                    return _failed(f"{key} must be a non-empty string of at most {limit} characters")
                filters[key] = value.strip()
            else:
                filters[key] = None
        provider = context.scalepad_client or ScalePadClient(context.settings)
        try:
            response = provider.get_goals(
                client_id=scoped_client_id,
                status=filters["status"],
                title=filters["title"],
                cursor=filters["cursor"],
            )
        except Exception:
            return _failed("ScalePad goal lookup failed")
        result = getattr(response, "result", None)
        status = str(getattr(result, "status", "failed"))
        message = redact_text(str(getattr(result, "message", "ScalePad goal read failed")))
        items = getattr(response, "items", [])
        if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
            return _failed("ScalePad returned malformed goal data")
        goals = [cast(dict[str, object], redact_value(item)) for item in items[:20]]
        total_count = getattr(response, "total_count", None)
        if not isinstance(total_count, int) or total_count < 0:
            total_count = None
        next_cursor = getattr(response, "next_cursor", "")
        if not isinstance(next_cursor, str):
            next_cursor = ""
        output = {
            "client_id": scoped_client_id,
            "connector_status": status,
            "goals": goals if status == "ready" else [],
            "count": len(goals) if status == "ready" else 0,
            "total_count": total_count if status == "ready" else None,
            "next_cursor": next_cursor if status == "ready" else "",
        }
        if status != "ready":
            return ActionResult(status="failed", output=output, error_detail=message)
        return ActionResult(
            status="success",
            output=output,
            evidence=[
                {
                    "type": "connector_read",
                    "connector": "scalepad",
                    "operation": "lifecycle-manager.goals",
                    "client_id": scoped_client_id,
                }
            ],
        )


class ScalePadAssessmentLookupAction:
    manifest = SmartActionManifest(
        action_id="scalepad-assessment-lookup",
        title="ScalePad Lifecycle assessment lookup",
        description=(
            "Read tenant-mapped ScalePad Lifecycle Manager assessments through "
            "the documented read-only API."
        ),
        kind="deterministic",
        input_schema={
            "type": "object",
            "required": ["client_id"],
            "properties": {
                "client_id": {"type": "string", "minLength": 1, "maxLength": 120},
                "status": {"type": "string", "enum": ["Completed", "InProgress"]},
                "assessment_template_id": {"type": "string", "minLength": 1, "maxLength": 200},
                "cursor": {"type": "string", "maxLength": 200},
            },
        },
        output_schema={
            "client_id": "string",
            "assessments": "array",
            "count": "integer",
            "total_count": "integer|null",
            "next_cursor": "string",
            "connector_status": "string",
        },
        requires_approval=False,
        estimated_minutes_saved=5,
        risk_level="low",
        required_role="technician",
        access_mode="read",
    )

    def run(self, context: ActionContext, payload: dict[str, object]) -> ActionResult:
        client_id = payload.get("client_id")
        if not isinstance(client_id, str) or not client_id.strip() or len(client_id.strip()) > 120:
            return _failed("client_id must be a non-empty string of at most 120 characters")
        scoped_client_id = client_id.strip()
        if context.client_id is not None and scoped_client_id != context.client_id:
            return _failed("client_id is outside the tenant scope")

        filters: dict[str, str | None] = {}
        for key, limit in (("status", 32), ("assessment_template_id", 200), ("cursor", 200)):
            value = payload.get(key)
            if value is not None:
                if not isinstance(value, str) or not value.strip() or len(value.strip()) > limit:
                    return _failed(f"{key} must be a non-empty string of at most {limit} characters")
                filters[key] = value.strip()
            else:
                filters[key] = None
        provider = context.scalepad_client or ScalePadClient(context.settings)
        try:
            response = provider.get_assessments(
                client_id=scoped_client_id,
                status=filters["status"],
                assessment_template_id=filters["assessment_template_id"],
                cursor=filters["cursor"],
            )
        except Exception:
            return _failed("ScalePad assessment lookup failed")
        result = getattr(response, "result", None)
        status = str(getattr(result, "status", "failed"))
        message = redact_text(str(getattr(result, "message", "ScalePad assessment read failed")))
        items = getattr(response, "items", [])
        if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
            return _failed("ScalePad returned malformed assessment data")
        assessments = [cast(dict[str, object], redact_value(item)) for item in items[:20]]
        total_count = getattr(response, "total_count", None)
        if not isinstance(total_count, int) or total_count < 0:
            total_count = None
        next_cursor = getattr(response, "next_cursor", "")
        if not isinstance(next_cursor, str):
            next_cursor = ""
        output = {
            "client_id": scoped_client_id,
            "connector_status": status,
            "assessments": assessments if status == "ready" else [],
            "count": len(assessments) if status == "ready" else 0,
            "total_count": total_count if status == "ready" else None,
            "next_cursor": next_cursor if status == "ready" else "",
        }
        if status != "ready":
            return ActionResult(status="failed", output=output, error_detail=message)
        return ActionResult(
            status="success",
            output=output,
            evidence=[
                {
                    "type": "connector_read",
                    "connector": "scalepad",
                    "operation": "lifecycle-manager.assessments",
                    "client_id": scoped_client_id,
                }
            ],
        )


class CommunicationPreviewAction:
    manifest = SmartActionManifest(
        action_id="communication-draft",
        title="Draft communication",
        description="Prepare an approval-gated message preview for a supported channel.",
        kind="deterministic",
        input_schema={
            "type": "object",
            "required": ["channel", "recipient", "body"],
            "properties": {
                "channel": {
                    "type": "string",
                    "enum": ["ticket_note", "email", "teams", "slack", "sms"],
                },
                "recipient": {"type": "string"},
                "subject": {"type": "string"},
                "body": {"type": "string"},
                "ticket_id": {"type": "string"},
            },
        },
        output_schema={
            "channel": "string",
            "recipient": "string",
            "subject": "string",
            "body": "string",
            "delivery_mode": "string",
            "sendable": "boolean",
        },
        requires_approval=True,
        estimated_minutes_saved=3,
        risk_level="medium",
        required_role="technician",
        access_mode="draft",
    )

    def run(self, context: ActionContext, payload: dict[str, object]) -> ActionResult:
        channel = payload.get("channel")
        recipient = payload.get("recipient")
        body = payload.get("body")
        subject = payload.get("subject", "")
        if channel not in {"ticket_note", "email", "teams", "slack", "sms"}:
            return _failed("channel must be one of ticket_note, email, teams, slack, or sms")
        if channel != "ticket_note" and (
            not isinstance(recipient, str) or not recipient.strip() or len(recipient) > 320
        ):
            return _failed("recipient must be a non-empty string of at most 320 characters")
        if not isinstance(body, str) or not body.strip() or len(body) > 10_000:
            return _failed("body must be a non-empty string of at most 10000 characters")
        if not isinstance(subject, str) or len(subject) > 500:
            return _failed("subject must be a string of at most 500 characters")
        ticket_id = payload.get("ticket_id")
        if ticket_id is not None:
            if not isinstance(ticket_id, str) or not ticket_id.strip():
                return _failed("ticket_id must be a non-empty string when provided")
            if _ticket_from_payload(context.store, payload, context.client_id) is None:
                return _failed("ticket_id must identify an existing ticket")
        elif context.client_id is None:
            return _failed("communication drafts require a tenant or ticket_id")
        if channel == "ticket_note" and not isinstance(ticket_id, str):
            return _failed("ticket_note requires ticket_id")
        if channel == "sms" and subject:
            return _failed("subject is not supported for sms")
        provider = context.communication_provider or PreviewCommunicationProvider()
        try:
            draft = provider.draft(
                CommunicationMessage(
                    channel=cast("CommunicationChannel", channel),
                    recipient=(recipient.strip() if isinstance(recipient, str) else f"ticket:{ticket_id}"),
                    subject=subject.strip(),
                    body=body.strip(),
                    client_id=context.client_id,
                    ticket_id=ticket_id.strip() if isinstance(ticket_id, str) else None,
                )
            )
        except ValueError as exc:
            return _failed(redact_text(str(exc)))
        except Exception:
            return _failed("communication preview failed")
        output = asdict(draft)
        output["approval_required"] = True
        output["estimate"] = self.manifest.estimated_minutes_saved
        evidence: list[dict[str, object]] = [
            {"type": "communication_preview", "channel": draft.channel}
        ]
        if isinstance(ticket_id, str):
            evidence.append({"type": "ticket", "ticket_id": ticket_id.strip()})
        return ActionResult(status="success", output=output, evidence=evidence)


class CommunicationSendAction:
    manifest = SmartActionManifest(
        action_id="communication-send",
        title="Send communication",
        description="Deliver an approved message through a configured communication adapter.",
        kind="deterministic",
        input_schema={
            "type": "object",
            "required": ["channel", "body"],
            "properties": {
                "channel": {
                    "type": "string",
                    "enum": ["ticket_note", "email", "teams", "slack", "sms"],
                },
                "recipient": {"type": "string"},
                "subject": {"type": "string"},
                "body": {"type": "string"},
                "ticket_id": {"type": "string"},
            },
        },
        output_schema={
            "channel": "string",
            "recipient": "string",
            "delivery_mode": "string",
            "sendable": "boolean",
            "message": "string",
            "receipt_id": "string",
            "accepted_at": "string",
            "provider_status": "string",
            "provider_status_code": "integer|null",
        },
        requires_approval=True,
        estimated_minutes_saved=2,
        risk_level="high",
        required_role="technician",
        access_mode="write",
    )

    def run(self, context: ActionContext, payload: dict[str, object]) -> ActionResult:
        message_or_error = _communication_message(context, payload)
        if isinstance(message_or_error, ActionResult):
            return message_or_error
        message = message_or_error
        if not payload.get("_approval_completed"):
            provider = context.communication_provider or PreviewCommunicationProvider()
            try:
                draft = provider.draft(message)
            except Exception:
                return _failed("communication preview failed")
            output = asdict(draft)
            output["approval_required"] = True
            output["sendable"] = False
            return ActionResult(
                status="success",
                output=output,
                evidence=[{"type": "communication_preview", "channel": message.channel}],
            )
        if message.channel == "ticket_note":
            if not context.settings.allow_write_actions:
                return _failed("ticket-note delivery is blocked until WAIT_ALLOW_WRITE_ACTIONS=true")
            if not message.ticket_id or not context.client_id:
                return _failed("ticket-note delivery requires a tenant-scoped ticket")
            try:
                note = context.store.create_ticket_note(
                    message.ticket_id,
                    client_id=context.client_id,
                    author=context.actor or "smart-action",
                    body=message.body,
                )
            except ValueError as exc:
                return _failed(str(exc))
            if note is None:
                return _failed("ticket not found")
            return ActionResult(
                status="success",
                output={
                    "channel": message.channel,
                    "recipient": message.recipient,
                    "delivery_mode": "local",
                    "sendable": True,
                    "message": "local ticket note created",
                    "note_id": note.id,
                    "receipt_id": f"ticket-note:{note.id}",
                    "accepted_at": note.created_at,
                    "provider_status": "persisted_local_note",
                    "provider_status_code": None,
                },
                evidence=[
                    {"type": "ticket_note", "ticket_id": message.ticket_id},
                    {"type": "communication_receipt", "receipt_id": f"ticket-note:{note.id}"},
                ],
            )
        sender = context.communication_sender
        if sender is None:
            return _failed("communication delivery is not configured")
        try:
            delivery = sender.send(message)
        except CommunicationDeliveryError as exc:
            return _failed(redact_text(str(exc)))
        except Exception:
            return _failed("communication delivery failed")
        if not delivery.receipt_id or not delivery.accepted_at:
            return _failed("communication delivery did not return a receipt")
        return ActionResult(
            status="success",
            output=asdict(delivery),
            evidence=[
                {"type": "communication_delivery", "channel": message.channel},
                {"type": "communication_receipt", "receipt_id": delivery.receipt_id},
            ],
        )


@dataclass(frozen=True)
class ActionResult:
    status: ActionStatus
    output: dict[str, object] = field(default_factory=dict)
    evidence: list[dict[str, object]] = field(default_factory=list)
    error_detail: str = ""
    run_id: int | None = None
    approval_id: int | None = None


class SmartAction(Protocol):
    manifest: SmartActionManifest

    def run(self, context: ActionContext, payload: dict[str, object]) -> ActionResult:
        """Run the action using only the supplied local context and payload."""


class SmartActionRegistry:
    def __init__(self) -> None:
        self._actions: dict[str, SmartAction] = {}

    def register(self, action: SmartAction) -> None:
        action_id = action.manifest.action_id.strip().lower()
        if action_id != action.manifest.action_id:
            raise ValueError("smart action id must be lowercase id text")
        if action_id in self._actions:
            raise ValueError(f"smart action {action_id} is already registered")
        if action.manifest.requires_approval and (
            isinstance(action.manifest.approval_expiry_seconds, bool)
            or not isinstance(action.manifest.approval_expiry_seconds, int)
            or action.manifest.approval_expiry_seconds < 1
            or action.manifest.approval_expiry_seconds > MAX_APPROVAL_EXPIRY_SECONDS
        ):
            raise ValueError(
                "approval expiry must be between 1 and "
                f"{MAX_APPROVAL_EXPIRY_SECONDS} seconds"
            )
        self._actions[action_id] = action

    def clear(self) -> None:
        self._actions.clear()

    def list(self) -> list[SmartAction]:
        return [self._actions[key] for key in sorted(self._actions)]

    def get(self, action_id: str) -> SmartAction:
        try:
            return self._actions[action_id.strip().lower()]
        except KeyError as exc:
            raise KeyError(f"smart action {action_id} is not registered") from exc


class TicketTriageAction:
    manifest = SmartActionManifest(
        action_id="ticket-triage",
        title="Ticket triage",
        description="Classify a ticket with deterministic service-desk heuristics.",
        kind="deterministic",
        input_schema={"type": "object", "required": ["ticket_id"]},
        output_schema={"classification": "string", "ticket_id": "string"},
        requires_approval=False,
        estimated_minutes_saved=4,
    )

    def run(self, context: ActionContext, payload: dict[str, object]) -> ActionResult:
        ticket = _ticket_from_payload(context.store, payload, context.client_id)
        if ticket is None:
            return _failed("ticket_id must identify an existing ticket")
        classification = classify_ticket(ticket.subject, ticket.body)
        evidence = [_ticket_evidence(ticket, ["subject", "body"])]
        return ActionResult(
            status="success",
            output={
                "ticket_id": ticket.id,
                "classification": classification,
                "ai_assisted": False,
                "estimate": self.manifest.estimated_minutes_saved,
            },
            evidence=evidence,
        )


class TicketSummaryAction:
    manifest = SmartActionManifest(
        action_id="ticket-summary",
        title="Ticket summary",
        description="Create a cited technician-facing summary from a ticket and local sources.",
        kind="ai_assisted",
        input_schema={"type": "object", "required": ["ticket_id"]},
        output_schema={"summary": "string", "suggested_response": "string", "citations": "array"},
        requires_approval=False,
        estimated_minutes_saved=8,
    )

    def run(self, context: ActionContext, payload: dict[str, object]) -> ActionResult:
        ticket = _ticket_from_payload(context.store, payload, context.client_id)
        if ticket is None:
            return _failed("ticket_id must identify an existing ticket")
        if not context.provider_available or context.provider is None:
            return _provider_not_configured()
        sources = _sources_for_ticket(context, ticket)
        try:
            summary = context.provider.summarize_ticket(ticket, sources)
            suggested_response = context.provider.draft_response(ticket, sources)
        except ProviderUnavailableError as exc:
            return _provider_not_configured(str(exc))
        except Exception as exc:
            return _failed(f"provider request failed: {exc}")
        citations = [
            _ticket_evidence(ticket, ["client", "subject", "body", "priority", "status"]),
            *[_source_citation(source) for source in sources],
        ]
        return ActionResult(
            status="success",
            output={
                "ticket_id": ticket.id,
                "classification": classify_ticket(ticket.subject, ticket.body),
                "summary": summary,
                "suggested_response": suggested_response,
                "citations": citations,
                "ai_assisted": _provider_is_ai_assisted(context),
                "provider_id": _provider_id(context),
                "estimate": self.manifest.estimated_minutes_saved,
            },
            evidence=citations,
        )


class SuggestResolutionAction:
    manifest = SmartActionManifest(
        action_id="suggest-resolution",
        title="Suggest resolution",
        description="Draft an advisory resolution grounded in retrieved local knowledge.",
        kind="ai_assisted",
        input_schema={"type": "object", "required": ["ticket_id"]},
        output_schema={"suggestion": "string", "citations": "array"},
        requires_approval=False,
        estimated_minutes_saved=12,
    )

    def run(self, context: ActionContext, payload: dict[str, object]) -> ActionResult:
        ticket = _ticket_from_payload(context.store, payload, context.client_id)
        if ticket is None:
            return _failed("ticket_id must identify an existing ticket")
        if not context.provider_available or context.provider is None:
            return _provider_not_configured()
        sources = _sources_for_ticket(context, ticket)
        citations = [_source_citation(source) for source in sources]
        if not citations:
            return _failed("no_relevant_sources")
        try:
            suggestion = context.provider.draft_response(ticket, sources)
        except ProviderUnavailableError as exc:
            return _provider_not_configured(str(exc))
        except Exception as exc:
            return _failed(f"provider request failed: {exc}")
        return ActionResult(
            status="success",
            output={
                "ticket_id": ticket.id,
                "suggestion": suggestion,
                "citations": citations,
                "ai_assisted": _provider_is_ai_assisted(context),
                "provider_id": _provider_id(context),
                "estimate": self.manifest.estimated_minutes_saved,
            },
            evidence=citations,
        )


class DocumentationAssistedResponseAction:
    manifest = SmartActionManifest(
        action_id="documentation-assisted-response",
        title="Documentation-assisted response",
        description=(
            "Draft a client-safe response grounded in tenant-scoped local knowledge, "
            "then deliver it only after technician approval."
        ),
        kind="ai_assisted",
        input_schema={
            "type": "object",
            "required": ["ticket_id"],
            "properties": {
                "ticket_id": {"type": "string"},
                "channel": "ticket_note, email, teams, slack, or sms (default: ticket_note)",
                "recipient": "required for non-ticket channels",
                "subject": "optional subject for email, Teams, or Slack",
                "response": "optional operator-edited response",
            },
        },
        output_schema={
            "ticket_id": "string",
            "response": "string",
            "citations": "array",
            "channel": "string",
            "recipient": "string",
            "subject": "string",
            "approval_required": "boolean",
        },
        requires_approval=True,
        estimated_minutes_saved=10,
        risk_level="medium",
        required_role="technician",
        access_mode="write",
    )

    def run(self, context: ActionContext, payload: dict[str, object]) -> ActionResult:
        allowed = {
            "ticket_id",
            "channel",
            "recipient",
            "subject",
            "response",
            "_approval_completed",
        }
        if set(payload) - allowed:
            return _failed("documentation-assisted response payload contains unsupported fields")
        ticket = _ticket_from_payload(context.store, payload, context.client_id)
        if ticket is None:
            return _failed("ticket_id must identify an existing ticket")

        sources = _sources_for_ticket(context, ticket)
        if not sources:
            return _failed("no_relevant_sources")
        citations = [
            _ticket_evidence(ticket, ["client", "subject", "body", "priority", "status"]),
            *[_source_citation(source) for source in sources],
        ]

        response = payload.get("response")
        if response is None:
            if not context.provider_available or context.provider is None:
                return _provider_not_configured()
            try:
                response = context.provider.draft_response(ticket, sources)
            except ProviderUnavailableError as exc:
                return _provider_not_configured(str(exc))
            except Exception as exc:
                return _failed(f"provider request failed: {redact_text(str(exc))}")
        if not isinstance(response, str) or not response.strip() or len(response) > 10_000:
            return _failed("response must be a non-empty string of at most 10000 characters")
        response = response.strip()

        channel = payload.get("channel", "ticket_note")
        recipient = payload.get("recipient", "")
        subject = payload.get("subject", "")
        delivery_payload: dict[str, object] = {
            "channel": channel,
            "recipient": recipient,
            "subject": subject,
            "body": response,
            "ticket_id": ticket.id,
        }
        message_or_error = _communication_message(context, delivery_payload)
        if isinstance(message_or_error, ActionResult):
            return message_or_error

        output: dict[str, object] = {
            "ticket_id": ticket.id,
            "response": response,
            "citations": citations,
            "channel": message_or_error.channel,
            "recipient": message_or_error.recipient,
            "subject": message_or_error.subject,
            "approval_required": True,
            "ai_assisted": _provider_is_ai_assisted(context),
            "provider_id": _provider_id(context),
            "estimate": self.manifest.estimated_minutes_saved,
        }
        if not payload.get("_approval_completed"):
            return ActionResult(status="success", output=output, evidence=citations)

        delivery = CommunicationSendAction().run(
            context,
            {**delivery_payload, "_approval_completed": True},
        )
        if delivery.status != "success":
            return ActionResult(
                status=delivery.status,
                output=output,
                evidence=[*citations, *delivery.evidence],
                error_detail=delivery.error_detail,
            )
        return ActionResult(
            status="success",
            output={**output, **delivery.output, "approved": True},
            evidence=[*citations, *delivery.evidence],
        )


class KnowledgeSearchAction:
    manifest = SmartActionManifest(
        action_id="knowledge-search",
        title="Search knowledge",
        description="Search permitted local documentation for evidence related to a ticket.",
        kind="deterministic",
        input_schema={"type": "object", "required": ["ticket_id"]},
        output_schema={"sources": "array", "ticket_id": "string"},
        requires_approval=False,
        estimated_minutes_saved=5,
        risk_level="low",
        access_mode="read",
    )

    def run(self, context: ActionContext, payload: dict[str, object]) -> ActionResult:
        ticket = _ticket_from_payload(context.store, payload, context.client_id)
        if ticket is None:
            return _failed("ticket_id must identify an existing ticket")
        citations = [_source_citation(source) for source in _sources_for_ticket(context, ticket)]
        return ActionResult(
            status="success",
            output={
                "ticket_id": ticket.id,
                "sources": citations,
                "count": len(citations),
                "estimate": self.manifest.estimated_minutes_saved,
            },
            evidence=citations,
        )


class M365IdentityLookupAction:
    manifest = SmartActionManifest(
        action_id="m365-identity-lookup",
        title="Microsoft 365 identity lookup",
        description="Search previously collected, read-only Microsoft 365 user inventory by identity.",
        kind="deterministic",
        input_schema={
            "type": "object",
            "required": ["identity"],
            "properties": {
                "identity": {"type": "string", "minLength": 1, "maxLength": 200},
                "limit": {"type": "integer", "minimum": 1, "maximum": 100},
            },
        },
        output_schema={"matches": "array", "count": "integer", "source": "string"},
        requires_approval=False,
        estimated_minutes_saved=3,
        risk_level="low",
        required_role="technician",
        access_mode="read",
    )

    def run(self, context: ActionContext, payload: dict[str, object]) -> ActionResult:
        identity = payload.get("identity")
        if not isinstance(identity, str) or not identity.strip() or len(identity.strip()) > 200:
            return _failed("identity must be a non-empty string of at most 200 characters")
        limit = payload.get("limit", 20)
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1 or limit > 100:
            return _failed("limit must be an integer between 1 and 100")

        query = identity.strip().casefold()
        matches: list[dict[str, object]] = []
        for asset in context.store.list_canonical_assets(client_id=context.client_id):
            if asset.asset_type != "m365-user":
                continue
            try:
                attributes = json.loads(asset.attributes_json)
            except json.JSONDecodeError:
                continue
            if not isinstance(attributes, dict):
                continue
            searchable = " ".join(
                str(attributes.get(field, ""))
                for field in ("display_name", "user_principal_name", "mail", "user_id")
            )
            if query not in searchable.casefold():
                continue
            matches.append(
                {
                    "asset_id": asset.canonical_id,
                    "display_name": attributes.get("display_name", asset.display_name),
                    "user_principal_name": attributes.get("user_principal_name", ""),
                    "mail": attributes.get("mail", ""),
                    "account_enabled": attributes.get("account_enabled", ""),
                    "job_title": attributes.get("job_title", ""),
                    "department": attributes.get("department", ""),
                    "last_seen": asset.last_seen,
                }
            )
        matches.sort(key=lambda item: (str(item.get("display_name", "")).casefold(), str(item["asset_id"])))
        return ActionResult(
            status="success",
            output={
                "matches": matches[:limit],
                "count": min(len(matches), limit),
                "source": "stored m365-user inventory",
            },
            evidence=[
                {"type": "canonical_asset", "asset_id": str(item["asset_id"])}
                for item in matches[:limit]
            ],
        )


class M365LiveContextAction:
    manifest = SmartActionManifest(
        action_id="m365-live-context",
        title="Microsoft 365 live context",
        description=(
            "Read a bounded Microsoft Graph user, group, tenant license, per-user "
            "license detail, mailbox-folder, or Intune device context."
        ),
        kind="deterministic",
        input_schema={
            "type": "object",
            "required": ["resource"],
            "properties": {
                "resource": {
                    "type": "string",
                    "enum": [
                        "user", "group", "licenses", "license_details", "mailbox_folders", "mail_messages",
                        "managed_devices",
                    ],
                },
                "identity": {"type": "string", "minLength": 1, "maxLength": 200},
                "folder_id": {"type": "string", "minLength": 1, "maxLength": 320},
                "limit": {"type": "integer", "minimum": 1, "maximum": 50},
            },
        },
        output_schema={"resource": "string", "items": "array", "count": "integer", "connector_status": "string"},
        requires_approval=False,
        estimated_minutes_saved=5,
        risk_level="low",
        required_role="technician",
        access_mode="read",
    )

    def run(self, context: ActionContext, payload: dict[str, object]) -> ActionResult:
        resource = payload.get("resource")
        resources = {
            "user",
            "group",
            "licenses",
            "license_details",
            "mailbox_folders",
            "mail_messages",
            "managed_devices",
        }
        if not isinstance(resource, str) or resource not in resources:
            return _failed(
                "resource must be one of user, group, licenses, license_details, "
                "mailbox_folders, mail_messages, or managed_devices"
            )
        identity = payload.get("identity")
        if identity is not None and (
            not isinstance(identity, str) or not identity.strip() or len(identity.strip()) > 200
        ):
            return _failed("identity must be a non-empty string of at most 200 characters")
        normalized_identity = identity.strip() if isinstance(identity, str) else None
        if (
            resource in {"user", "group", "license_details", "mailbox_folders", "mail_messages"}
            and normalized_identity is None
        ):
            return _failed(
                "identity is required for user, group, license_details, mailbox_folders, "
                "and mail_messages resources"
            )
        folder_id = payload.get("folder_id")
        if resource == "mail_messages" and (
            not isinstance(folder_id, str) or not folder_id.strip() or len(folder_id.strip()) > 320
        ):
            return _failed("folder_id is required for mail_messages and must be at most 320 characters")
        limit = payload.get("limit", 20)
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1 or limit > 50:
            return _failed("limit must be an integer between 1 and 50")
        from wait_local_agent.m365_graph import M365GraphClient

        provider = cast(M365GraphReadProvider, context.m365_client or M365GraphClient(context.settings))
        try:
            response: object
            if resource == "user":
                response = provider.list_users(identity=normalized_identity, page_size=limit)
            elif resource == "group":
                response = provider.list_groups(identity=normalized_identity, page_size=limit)
            elif resource == "licenses":
                response = provider.list_subscribed_skus()
            elif resource == "license_details":
                response = provider.list_license_details(
                    identity=normalized_identity or "",
                    page_size=limit,
                )
            elif resource == "mailbox_folders":
                response = provider.list_mail_folders(identity=normalized_identity, page_size=limit)
            elif resource == "mail_messages":
                response = provider.list_mail_messages(
                    identity=normalized_identity,
                    folder_id=folder_id.strip() if isinstance(folder_id, str) else None,
                    page_size=limit,
                )
            else:
                response = provider.list_managed_devices(page_size=limit)
        except Exception:
            return _failed("Microsoft Graph context lookup failed")
        result = getattr(response, "result", None)
        status = str(getattr(result, "status", "failed"))
        message = redact_text(str(getattr(result, "message", "Microsoft Graph read failed")))
        items = getattr(response, "items", [])
        if not isinstance(items, list):
            return _failed("Microsoft Graph returned malformed context data")
        if status != "ready":
            return ActionResult(
                status="failed",
                output={"resource": resource, "connector_status": status, "items": [], "count": 0},
                error_detail=message,
            )
        normalized = [
            cast(dict[str, object], redact_value(asdict(item)))
            for item in items[:limit]
            if hasattr(item, "__dataclass_fields__")
        ]
        return ActionResult(
            status="success",
            output={
                "resource": resource,
                "connector_status": status,
                "items": normalized,
                "count": len(normalized),
            },
            evidence=[
                {
                    "type": "connector_read",
                    "connector": "m365",
                    "operation": f"{resource}.list",
                    "client_id": context.client_id,
                }
            ],
        )


class M365MailMessageMoveAction:
    manifest = SmartActionManifest(
        action_id="m365-mail-message-move",
        title="Microsoft 365 message move",
        description=(
            "Prepare an approval-gated Microsoft Graph message move using explicit "
            "user, source-folder, message, and destination-folder identifiers."
        ),
        kind="deterministic",
        input_schema={
            "type": "object",
            "required": [
                "user_identity",
                "source_folder_id",
                "message_id",
                "destination_folder_id",
            ],
            "properties": {
                "user_identity": {"type": "string", "minLength": 1, "maxLength": 320},
                "source_folder_id": {"type": "string", "minLength": 1, "maxLength": 320},
                "message_id": {"type": "string", "minLength": 1, "maxLength": 320},
                "destination_folder_id": {"type": "string", "minLength": 1, "maxLength": 320},
            },
        },
        output_schema={
            "operation": "string",
            "connector_status": "string",
            "user_identity": "string",
            "source_folder_id": "string",
            "message_id": "string",
            "destination_folder_id": "string",
            "status_code": "number",
        },
        requires_approval=True,
        estimated_minutes_saved=2,
        risk_level="high",
        required_role="admin",
        access_mode="write",
    )

    def run(self, context: ActionContext, payload: dict[str, object]) -> ActionResult:
        allowed = {
            "user_identity",
            "source_folder_id",
            "message_id",
            "destination_folder_id",
            "_approval_completed",
        }
        if set(payload) - allowed:
            return _failed("M365 mail message move payload contains unsupported fields")
        message_payload: dict[str, object] = {
            "connector": "m365",
            "action_type": "mail-messages.move",
            "destination_folder_id": payload.get("destination_folder_id"),
            "message_id": payload.get("message_id"),
            "source_folder_id": payload.get("source_folder_id"),
            "user_identity": payload.get("user_identity"),
        }
        try:
            from wait_local_agent.connectors import validate_m365_mail_message_move_payload

            validate_m365_mail_message_move_payload(message_payload)
        except (TypeError, ValueError) as exc:
            return _failed(redact_text(str(exc)))
        user_identity = str(message_payload["user_identity"]).strip()
        source_folder_id = str(message_payload["source_folder_id"]).strip()
        message_id = str(message_payload["message_id"]).strip()
        destination_folder_id = str(message_payload["destination_folder_id"]).strip()
        from wait_local_agent.m365_graph import M365GraphClient

        provider = cast(
            M365MailMessageMoveWriteProvider,
            context.m365_client or M365GraphClient(context.settings),
        )
        try:
            health = provider.write_health()
        except Exception:
            return _failed("Microsoft Graph write readiness check failed")
        connector_status = str(getattr(health, "status", "failed"))
        connector_message = redact_text(
            str(getattr(health, "message", "Microsoft Graph writes are unavailable"))
        )
        output: dict[str, object] = {
            "operation": "mail_message_move",
            "connector_status": connector_status,
            "user_identity": user_identity,
            "source_folder_id": source_folder_id,
            "message_id": message_id,
            "destination_folder_id": destination_folder_id,
        }
        evidence: list[dict[str, object]] = [
            {
                "type": "connector_write_preflight",
                "connector": "m365",
                "operation": "mail_message_move",
                "client_id": context.client_id,
                "scope": {
                    "user_identity": user_identity,
                    "source_folder_id": source_folder_id,
                    "message_id": message_id,
                    "destination_folder_id": destination_folder_id,
                },
            }
        ]
        if connector_status != "ready":
            return ActionResult(
                status="failed",
                output=output,
                evidence=evidence,
                error_detail=connector_message,
            )
        if not payload.get("_approval_completed"):
            return ActionResult(
                status="success",
                output={**output, "approval_required": True},
                evidence=evidence,
            )
        try:
            result = provider.move_mail_message(
                user_identity=user_identity,
                source_folder_id=source_folder_id,
                message_id=message_id,
                destination_folder_id=destination_folder_id,
            )
        except Exception:
            return ActionResult(
                status="failed",
                output=output,
                evidence=evidence,
                error_detail="Microsoft Graph mail message move failed",
            )
        result_output = {
            **output,
            "status_code": getattr(result, "status_code", None),
        }
        if str(getattr(result, "status", "failed")) != "succeeded":
            return ActionResult(
                status="failed",
                output=result_output,
                evidence=evidence,
                error_detail=redact_text(
                    str(getattr(result, "message", "Microsoft Graph mail message move failed"))
                ),
            )
        return ActionResult(
            status="success",
            output={**result_output, "approved": True},
            evidence=evidence,
        )


class M365MailMessageReadStateAction:
    manifest = SmartActionManifest(
        action_id="m365-mail-message-read-state",
        title="Microsoft 365 message read state",
        description=(
            "Prepare an approval-gated Microsoft Graph message read-state update "
            "using explicit user, source-folder, and message identifiers."
        ),
        kind="deterministic",
        input_schema={
            "type": "object",
            "required": ["user_identity", "source_folder_id", "message_id", "is_read"],
            "properties": {
                "user_identity": {"type": "string", "minLength": 1, "maxLength": 320},
                "source_folder_id": {"type": "string", "minLength": 1, "maxLength": 320},
                "message_id": {"type": "string", "minLength": 1, "maxLength": 320},
                "is_read": {"type": "boolean"},
            },
        },
        output_schema={
            "operation": "string",
            "connector_status": "string",
            "user_identity": "string",
            "source_folder_id": "string",
            "message_id": "string",
            "is_read": "boolean",
            "status_code": "number",
        },
        requires_approval=True,
        estimated_minutes_saved=1,
        risk_level="high",
        required_role="admin",
        access_mode="write",
    )

    def run(self, context: ActionContext, payload: dict[str, object]) -> ActionResult:
        allowed = {
            "user_identity",
            "source_folder_id",
            "message_id",
            "is_read",
            "_approval_completed",
        }
        if set(payload) - allowed:
            return _failed("M365 mail message read-state payload contains unsupported fields")
        message_payload: dict[str, object] = {
            "connector": "m365",
            "action_type": "mail-messages.read-state",
            "is_read": payload.get("is_read"),
            "message_id": payload.get("message_id"),
            "source_folder_id": payload.get("source_folder_id"),
            "user_identity": payload.get("user_identity"),
        }
        try:
            from wait_local_agent.connectors import validate_m365_mail_message_read_state_payload

            validate_m365_mail_message_read_state_payload(message_payload)
        except (TypeError, ValueError) as exc:
            return _failed(redact_text(str(exc)))
        user_identity = str(message_payload["user_identity"]).strip()
        source_folder_id = str(message_payload["source_folder_id"]).strip()
        message_id = str(message_payload["message_id"]).strip()
        is_read = bool(message_payload["is_read"])
        from wait_local_agent.m365_graph import M365GraphClient

        provider = cast(
            M365MailMessageReadStateWriteProvider,
            context.m365_client or M365GraphClient(context.settings),
        )
        try:
            health = provider.write_health()
        except Exception:
            return _failed("Microsoft Graph write readiness check failed")
        connector_status = str(getattr(health, "status", "failed"))
        connector_message = redact_text(
            str(getattr(health, "message", "Microsoft Graph writes are unavailable"))
        )
        output: dict[str, object] = {
            "operation": "mail_message_read_state",
            "connector_status": connector_status,
            "user_identity": user_identity,
            "source_folder_id": source_folder_id,
            "message_id": message_id,
            "is_read": is_read,
        }
        evidence: list[dict[str, object]] = [
            {
                "type": "connector_write_preflight",
                "connector": "m365",
                "operation": "mail_message_read_state",
                "client_id": context.client_id,
                "scope": {
                    "user_identity": user_identity,
                    "source_folder_id": source_folder_id,
                    "message_id": message_id,
                    "is_read": is_read,
                },
            }
        ]
        if connector_status != "ready":
            return ActionResult(
                status="failed",
                output=output,
                evidence=evidence,
                error_detail=connector_message,
            )
        if not payload.get("_approval_completed"):
            return ActionResult(
                status="success",
                output={**output, "approval_required": True},
                evidence=evidence,
            )
        try:
            result = provider.update_mail_message_read_state(
                user_identity=user_identity,
                source_folder_id=source_folder_id,
                message_id=message_id,
                is_read=is_read,
            )
        except Exception:
            return ActionResult(
                status="failed",
                output=output,
                evidence=evidence,
                error_detail="Microsoft Graph mail message read-state update failed",
            )
        result_output = {
            **output,
            "status_code": getattr(result, "status_code", None),
            "is_read": getattr(result, "is_read", is_read),
        }
        if str(getattr(result, "status", "failed")) != "succeeded":
            return ActionResult(
                status="failed",
                output=result_output,
                evidence=evidence,
                error_detail=redact_text(
                    str(
                        getattr(
                            result,
                            "message",
                            "Microsoft Graph mail message read-state update failed",
                        )
                    )
                ),
            )
        return ActionResult(
            status="success",
            output={**result_output, "approved": True},
            evidence=evidence,
        )


class M365MailMessageDeleteAction:
    manifest = SmartActionManifest(
        action_id="m365-mail-message-delete",
        title="Microsoft 365 message delete",
        description=(
            "Prepare an approval-gated Microsoft Graph message deletion using "
            "explicit user, source-folder, and message identifiers."
        ),
        kind="deterministic",
        input_schema={
            "type": "object",
            "required": ["user_identity", "source_folder_id", "message_id"],
            "properties": {
                "user_identity": {"type": "string", "minLength": 1, "maxLength": 320},
                "source_folder_id": {"type": "string", "minLength": 1, "maxLength": 320},
                "message_id": {"type": "string", "minLength": 1, "maxLength": 320},
            },
        },
        output_schema={
            "operation": "string",
            "connector_status": "string",
            "user_identity": "string",
            "source_folder_id": "string",
            "message_id": "string",
            "status_code": "number",
        },
        requires_approval=True,
        estimated_minutes_saved=1,
        risk_level="high",
        required_role="admin",
        access_mode="write",
    )

    def run(self, context: ActionContext, payload: dict[str, object]) -> ActionResult:
        allowed = {
            "user_identity",
            "source_folder_id",
            "message_id",
            "_approval_completed",
        }
        if set(payload) - allowed:
            return _failed("M365 mail message delete payload contains unsupported fields")
        message_payload: dict[str, object] = {
            "connector": "m365",
            "action_type": "mail-messages.delete",
            "message_id": payload.get("message_id"),
            "source_folder_id": payload.get("source_folder_id"),
            "user_identity": payload.get("user_identity"),
        }
        try:
            from wait_local_agent.connectors import validate_m365_mail_message_delete_payload

            validate_m365_mail_message_delete_payload(message_payload)
        except (TypeError, ValueError) as exc:
            return _failed(redact_text(str(exc)))
        user_identity = str(message_payload["user_identity"]).strip()
        source_folder_id = str(message_payload["source_folder_id"]).strip()
        message_id = str(message_payload["message_id"]).strip()
        from wait_local_agent.m365_graph import M365GraphClient

        provider = cast(
            M365MailMessageDeleteWriteProvider,
            context.m365_client or M365GraphClient(context.settings),
        )
        try:
            health = provider.write_health()
        except Exception:
            return _failed("Microsoft Graph write readiness check failed")
        connector_status = str(getattr(health, "status", "failed"))
        connector_message = redact_text(
            str(getattr(health, "message", "Microsoft Graph writes are unavailable"))
        )
        output: dict[str, object] = {
            "operation": "mail_message_delete",
            "connector_status": connector_status,
            "user_identity": user_identity,
            "source_folder_id": source_folder_id,
            "message_id": message_id,
        }
        evidence: list[dict[str, object]] = [
            {
                "type": "connector_write_preflight",
                "connector": "m365",
                "operation": "mail_message_delete",
                "client_id": context.client_id,
                "scope": {
                    "user_identity": user_identity,
                    "source_folder_id": source_folder_id,
                    "message_id": message_id,
                },
            }
        ]
        if connector_status != "ready":
            return ActionResult(
                status="failed",
                output=output,
                evidence=evidence,
                error_detail=connector_message,
            )
        if not payload.get("_approval_completed"):
            return ActionResult(
                status="success",
                output={**output, "approval_required": True},
                evidence=evidence,
            )
        try:
            result = provider.delete_mail_message(
                user_identity=user_identity,
                source_folder_id=source_folder_id,
                message_id=message_id,
            )
        except Exception:
            return ActionResult(
                status="failed",
                output=output,
                evidence=evidence,
                error_detail="Microsoft Graph mail message deletion failed",
            )
        result_output = {
            **output,
            "status_code": getattr(result, "status_code", None),
        }
        if str(getattr(result, "status", "failed")) != "succeeded":
            return ActionResult(
                status="failed",
                output=result_output,
                evidence=evidence,
                error_detail=redact_text(
                    str(getattr(result, "message", "Microsoft Graph mail message deletion failed"))
                ),
            )
        return ActionResult(
            status="success",
            output={**result_output, "approved": True},
            evidence=evidence,
        )


class M365ManagedDeviceAction:
    def __init__(
        self,
        *,
        action_id: str,
        title: str,
        operation: str,
        action_type: str,
        provider_method: str,
        validator_name: str,
    ) -> None:
        self.provider_method = provider_method
        self.validator_name = validator_name
        self.action_type = action_type
        self.manifest = SmartActionManifest(
            action_id=action_id,
            title=title,
            description=(
                f"Prepare an approval-gated Microsoft Graph Intune {operation} "
                "using one explicit managed-device identifier."
            ),
            kind="deterministic",
            input_schema={
                "type": "object",
                "required": ["device_id"],
                "properties": {
                    "device_id": {"type": "string", "minLength": 1, "maxLength": 320},
                },
            },
            output_schema={
                "operation": "string",
                "connector_status": "string",
                "device_id": "string",
                "status_code": "number",
            },
            requires_approval=True,
            estimated_minutes_saved=2,
            risk_level="high",
            required_role="admin",
            access_mode="write",
        )
        self.operation = operation

    def run(self, context: ActionContext, payload: dict[str, object]) -> ActionResult:
        if set(payload) - {"device_id", "_approval_completed"}:
            return _failed(f"M365 managed-device {self.operation} payload contains unsupported fields")
        device_payload: dict[str, object] = {
            "connector": "m365",
            "action_type": self.action_type,
            "device_id": payload.get("device_id"),
        }
        try:
            import wait_local_agent.connectors as connector_module

            validator = getattr(connector_module, self.validator_name)
            validator(device_payload)
        except (TypeError, ValueError) as exc:
            return _failed(redact_text(str(exc)))
        device_id = str(device_payload["device_id"]).strip()
        from wait_local_agent.m365_graph import M365GraphClient

        provider = cast(
            M365ManagedDeviceWriteProvider,
            context.m365_client or M365GraphClient(context.settings),
        )
        try:
            health = provider.write_health()
        except Exception:
            return _failed("Microsoft Graph write readiness check failed")
        connector_status = str(getattr(health, "status", "failed"))
        connector_message = redact_text(
            str(getattr(health, "message", "Microsoft Graph writes are unavailable"))
        )
        output: dict[str, object] = {
            "operation": self.operation,
            "connector_status": connector_status,
            "device_id": device_id,
        }
        evidence: list[dict[str, object]] = [
            {
                "type": "connector_write_preflight",
                "connector": "m365",
                "operation": self.operation,
                "client_id": context.client_id,
                "scope": {"device_id": device_id},
            }
        ]
        if connector_status != "ready":
            return ActionResult(
                status="failed",
                output=output,
                evidence=evidence,
                error_detail=connector_message,
            )
        if not payload.get("_approval_completed"):
            return ActionResult(
                status="success",
                output={**output, "approval_required": True},
                evidence=evidence,
            )
        try:
            result = getattr(provider, self.provider_method)(device_id=device_id)
        except Exception:
            return ActionResult(
                status="failed",
                output=output,
                evidence=evidence,
                error_detail=f"Microsoft Graph managed-device {self.operation} failed",
            )
        result_output = {
            **output,
            "status_code": getattr(result, "status_code", None),
        }
        if str(getattr(result, "status", "failed")) != "succeeded":
            return ActionResult(
                status="failed",
                output=result_output,
                evidence=evidence,
                error_detail=redact_text(
                    str(
                        getattr(
                            result,
                            "message",
                            f"Microsoft Graph managed-device {self.operation} failed",
                        )
                    )
                ),
            )
        return ActionResult(
            status="success",
            output={**result_output, "approved": True},
            evidence=evidence,
        )


class M365MailboxSettingsAction:
    manifest = SmartActionManifest(
        action_id="m365-mailbox-settings",
        title="Microsoft 365 mailbox settings update",
        description=(
            "Prepare an approval-gated Microsoft Graph mailbox settings update using "
            "only the supported locale, time zone, date-format, and time-format fields."
        ),
        kind="deterministic",
        input_schema={
            "type": "object",
            "required": ["user_identity", "settings"],
            "properties": {
                "user_identity": {"type": "string", "minLength": 1, "maxLength": 320},
                "settings": {"type": "object", "minProperties": 1},
            },
        },
        output_schema={
            "operation": "string",
            "connector_status": "string",
            "user_identity": "string",
            "settings": "object",
            "status_code": "number",
        },
        requires_approval=True,
        estimated_minutes_saved=3,
        risk_level="high",
        required_role="admin",
        access_mode="write",
    )

    def run(self, context: ActionContext, payload: dict[str, object]) -> ActionResult:
        if set(payload) - {"user_identity", "settings", "_approval_completed"}:
            return _failed("M365 mailbox settings payload contains unsupported fields")
        raw_settings = payload.get("settings")
        settings = dict(raw_settings) if isinstance(raw_settings, dict) else raw_settings
        mailbox_payload: dict[str, object] = {
            "connector": "m365",
            "action_type": "users.mailbox-settings.update",
            "settings": settings,
            "user_identity": payload.get("user_identity"),
        }
        try:
            from wait_local_agent.connectors import validate_m365_mailbox_settings_update_payload

            validate_m365_mailbox_settings_update_payload(mailbox_payload)
        except (TypeError, ValueError) as exc:
            return _failed(redact_text(str(exc)))
        user_identity = str(mailbox_payload["user_identity"]).strip()
        validated_settings = cast(dict[str, str], mailbox_payload["settings"])
        from wait_local_agent.m365_graph import M365GraphClient

        provider = cast(
            M365MailboxSettingsWriteProvider,
            context.m365_client or M365GraphClient(context.settings),
        )
        try:
            health = provider.write_health()
        except Exception:
            return _failed("Microsoft Graph write readiness check failed")
        connector_status = str(getattr(health, "status", "failed"))
        connector_message = redact_text(
            str(getattr(health, "message", "Microsoft Graph writes are unavailable"))
        )
        output: dict[str, object] = {
            "operation": "mailbox_settings_update",
            "connector_status": connector_status,
            "user_identity": user_identity,
            "settings": validated_settings,
        }
        evidence: list[dict[str, object]] = [
            {
                "type": "connector_write_preflight",
                "connector": "m365",
                "operation": "mailbox_settings_update",
                "client_id": context.client_id,
                "scope": {"user_identity": user_identity},
                "fields": sorted(validated_settings),
            }
        ]
        if connector_status != "ready":
            return ActionResult(
                status="failed",
                output=output,
                evidence=evidence,
                error_detail=connector_message,
            )
        if not payload.get("_approval_completed"):
            return ActionResult(
                status="success",
                output={**output, "approval_required": True},
                evidence=evidence,
            )
        try:
            result = provider.update_mailbox_settings(
                user_identity=user_identity,
                settings=validated_settings,
            )
        except Exception:
            return ActionResult(
                status="failed",
                output=output,
                evidence=evidence,
                error_detail="Microsoft Graph mailbox settings update failed",
            )
        result_output = {
            **output,
            "settings": dict(getattr(result, "settings", validated_settings)),
            "status_code": getattr(result, "status_code", None),
        }
        if str(getattr(result, "status", "failed")) != "succeeded":
            return ActionResult(
                status="failed",
                output=result_output,
                evidence=evidence,
                error_detail=redact_text(
                    str(getattr(result, "message", "Microsoft Graph mailbox settings update failed"))
                ),
            )
        return ActionResult(
            status="success",
            output={**result_output, "approved": True},
            evidence=evidence,
        )


class M365SessionRevocationAction:
    manifest = SmartActionManifest(
        action_id="m365-session-revocation",
        title="Microsoft 365 session revocation",
        description=(
            "Prepare an approval-gated Microsoft Graph session revocation for one "
            "explicitly identified user."
        ),
        kind="deterministic",
        input_schema={
            "type": "object",
            "required": ["user_id"],
            "properties": {
                "user_id": {"type": "string", "minLength": 1, "maxLength": 320},
            },
        },
        output_schema={
            "operation": "string",
            "connector_status": "string",
            "user_id": "string",
            "status_code": "number",
        },
        requires_approval=True,
        estimated_minutes_saved=2,
        risk_level="high",
        required_role="admin",
        access_mode="write",
    )

    def run(self, context: ActionContext, payload: dict[str, object]) -> ActionResult:
        if set(payload) - {"user_id", "_approval_completed"}:
            return _failed("M365 session revocation payload contains unsupported fields")
        session_payload: dict[str, object] = {
            "connector": "m365",
            "action_type": "users.sessions.revoke",
            "user_id": payload.get("user_id"),
        }
        try:
            from wait_local_agent.connectors import validate_m365_session_revocation_payload

            validate_m365_session_revocation_payload(session_payload)
        except (TypeError, ValueError) as exc:
            return _failed(redact_text(str(exc)))
        user_id = str(session_payload["user_id"]).strip()
        from wait_local_agent.m365_graph import M365GraphClient

        provider = cast(
            M365SessionRevocationWriteProvider,
            context.m365_client or M365GraphClient(context.settings),
        )
        try:
            health = provider.write_health()
        except Exception:
            return _failed("Microsoft Graph write readiness check failed")
        connector_status = str(getattr(health, "status", "failed"))
        connector_message = redact_text(
            str(getattr(health, "message", "Microsoft Graph writes are unavailable"))
        )
        output: dict[str, object] = {
            "operation": "session_revocation",
            "connector_status": connector_status,
            "user_id": user_id,
        }
        evidence: list[dict[str, object]] = [
            {
                "type": "connector_write_preflight",
                "connector": "m365",
                "operation": "session_revocation",
                "client_id": context.client_id,
                "scope": {"user_id": user_id},
            }
        ]
        if connector_status != "ready":
            return ActionResult(
                status="failed",
                output=output,
                evidence=evidence,
                error_detail=connector_message,
            )
        if not payload.get("_approval_completed"):
            return ActionResult(
                status="success",
                output={**output, "approval_required": True},
                evidence=evidence,
            )
        try:
            result = provider.revoke_user_sessions(user_id=user_id)
        except Exception:
            return ActionResult(
                status="failed",
                output=output,
                evidence=evidence,
                error_detail="Microsoft Graph session revocation failed",
            )
        result_output = {
            **output,
            "status_code": getattr(result, "status_code", None),
        }
        if str(getattr(result, "status", "failed")) != "succeeded":
            return ActionResult(
                status="failed",
                output=result_output,
                evidence=evidence,
                error_detail=redact_text(
                    str(getattr(result, "message", "Microsoft Graph session revocation failed"))
                ),
            )
        return ActionResult(
            status="success",
            output={**result_output, "approved": True},
            evidence=evidence,
        )


class M365LicenseChangeAction:
    manifest = SmartActionManifest(
        action_id="m365-license-change",
        title="Microsoft 365 user license change",
        description=(
            "Prepare an approval-gated Microsoft Graph direct license add or remove "
            "operation using immutable user and SKU IDs."
        ),
        kind="deterministic",
        input_schema={
            "type": "object",
            "required": ["user_id", "sku_ids", "operation"],
            "properties": {
                "user_id": {"type": "string", "minLength": 1, "maxLength": 320},
                "sku_ids": {"type": "array", "minItems": 1, "maxItems": 50},
                "operation": {"type": "string", "enum": ["add", "remove"]},
            },
        },
        output_schema={
            "operation": "string",
            "connector_status": "string",
            "user_id": "string",
            "sku_ids": "array",
            "status_code": "number",
        },
        requires_approval=True,
        estimated_minutes_saved=3,
        risk_level="high",
        required_role="admin",
        access_mode="write",
    )

    def run(self, context: ActionContext, payload: dict[str, object]) -> ActionResult:
        if set(payload) - {"user_id", "sku_ids", "operation", "ticket_id", "_approval_completed"}:
            return _failed("M365 license payload contains unsupported fields")
        operation = payload.get("operation")
        if not isinstance(operation, str) or operation not in {"add", "remove"}:
            return _failed("M365 license operation must be add or remove")
        license_payload: dict[str, object] = {
            "connector": "m365",
            "action_type": (
                "users.licenses.add" if operation == "add" else "users.licenses.remove"
            ),
            "sku_ids": payload.get("sku_ids"),
            "user_id": payload.get("user_id"),
        }
        try:
            from wait_local_agent.connectors import validate_m365_license_change_payload

            validate_m365_license_change_payload(license_payload)
        except (TypeError, ValueError) as exc:
            return _failed(redact_text(str(exc)))
        user_id = str(license_payload["user_id"]).strip()
        sku_ids = [str(sku_id) for sku_id in cast(list[object], license_payload["sku_ids"])]
        from wait_local_agent.m365_graph import M365GraphClient

        provider = cast(
            M365LicenseWriteProvider,
            context.m365_client or M365GraphClient(context.settings),
        )
        try:
            health = provider.write_health()
        except Exception:
            return _failed("Microsoft Graph write readiness check failed")
        connector_status = str(getattr(health, "status", "failed"))
        connector_message = redact_text(
            str(getattr(health, "message", "Microsoft Graph writes are unavailable"))
        )
        output: dict[str, object] = {
            "operation": operation,
            "connector_status": connector_status,
            "user_id": user_id,
            "sku_ids": sku_ids,
        }
        evidence: list[dict[str, object]] = [
            {
                "type": "connector_write_preflight",
                "connector": "m365",
                "operation": f"license_{operation}",
                "client_id": context.client_id,
                "scope": {"user_id": user_id, "sku_ids": sku_ids},
            }
        ]
        if connector_status != "ready":
            return ActionResult(
                status="failed",
                output=output,
                evidence=evidence,
                error_detail=connector_message,
            )
        if not payload.get("_approval_completed"):
            return ActionResult(
                status="success",
                output={**output, "approval_required": True},
                evidence=evidence,
            )
        try:
            result = provider.change_user_licenses(
                user_id=user_id,
                sku_ids=sku_ids,
                operation=operation,
            )
        except Exception:
            return ActionResult(
                status="failed",
                output=output,
                evidence=evidence,
                error_detail="Microsoft Graph license change failed",
            )
        result_output = {
            **output,
            "status_code": getattr(result, "status_code", None),
        }
        if str(getattr(result, "status", "failed")) != "succeeded":
            return ActionResult(
                status="failed",
                output=result_output,
                evidence=evidence,
                error_detail=redact_text(
                    str(getattr(result, "message", "Microsoft Graph license change failed"))
                ),
            )
        return ActionResult(
            status="success",
            output={**result_output, "approved": True},
            evidence=evidence,
        )


class M365GroupMembershipAction:
    manifest = SmartActionManifest(
        action_id="m365-group-membership",
        title="Microsoft 365 group membership change",
        description=(
            "Prepare an approval-gated Microsoft Graph group membership add or remove "
            "operation using immutable directory object IDs."
        ),
        kind="deterministic",
        input_schema={
            "type": "object",
            "required": ["group_id", "user_id", "operation"],
            "properties": {
                "group_id": {"type": "string", "minLength": 1, "maxLength": 320},
                "user_id": {"type": "string", "minLength": 1, "maxLength": 320},
                "operation": {"type": "string", "enum": ["add", "remove"]},
            },
        },
        output_schema={
            "operation": "string",
            "connector_status": "string",
            "group_id": "string",
            "user_id": "string",
            "status_code": "number",
        },
        requires_approval=True,
        estimated_minutes_saved=3,
        risk_level="high",
        required_role="admin",
        access_mode="write",
    )

    def run(self, context: ActionContext, payload: dict[str, object]) -> ActionResult:
        if set(payload) - {"group_id", "user_id", "operation", "_approval_completed"}:
            return _failed("M365 group membership payload contains unsupported fields")
        operation = payload.get("operation")
        if not isinstance(operation, str) or operation not in {"add", "remove"}:
            return _failed("M365 group membership operation must be add or remove")
        membership_payload: dict[str, object] = {
            "connector": "m365",
            "action_type": (
                "groups.members.add" if operation == "add" else "groups.members.remove"
            ),
            "group_id": payload.get("group_id"),
            "user_id": payload.get("user_id"),
        }
        try:
            from wait_local_agent.connectors import validate_m365_group_membership_payload

            validate_m365_group_membership_payload(membership_payload)
        except (TypeError, ValueError) as exc:
            return _failed(redact_text(str(exc)))
        group_id = str(membership_payload["group_id"]).strip()
        user_id = str(membership_payload["user_id"]).strip()
        from wait_local_agent.m365_graph import M365GraphClient

        provider = cast(
            M365GroupMembershipWriteProvider,
            context.m365_client or M365GraphClient(context.settings),
        )
        try:
            health = provider.write_health()
        except Exception:
            return _failed("Microsoft Graph write readiness check failed")
        connector_status = str(getattr(health, "status", "failed"))
        connector_message = redact_text(
            str(getattr(health, "message", "Microsoft Graph writes are unavailable"))
        )
        output: dict[str, object] = {
            "operation": operation,
            "connector_status": connector_status,
            "group_id": group_id,
            "user_id": user_id,
        }
        evidence: list[dict[str, object]] = [
            {
                "type": "connector_write_preflight",
                "connector": "m365",
                "operation": f"group_membership_{operation}",
                "client_id": context.client_id,
                "scope": {"group_id": group_id, "user_id": user_id},
            }
        ]
        if connector_status != "ready":
            return ActionResult(
                status="failed",
                output=output,
                evidence=evidence,
                error_detail=connector_message,
            )
        if not payload.get("_approval_completed"):
            return ActionResult(
                status="success",
                output={**output, "approval_required": True},
                evidence=evidence,
            )
        try:
            result = provider.change_group_membership(
                group_id=group_id,
                user_id=user_id,
                operation=operation,
            )
        except Exception:
            return ActionResult(
                status="failed",
                output=output,
                evidence=evidence,
                error_detail="Microsoft Graph group membership change failed",
            )
        result_output = {
            **output,
            "status_code": getattr(result, "status_code", None),
        }
        if str(getattr(result, "status", "failed")) != "succeeded":
            return ActionResult(
                status="failed",
                output=result_output,
                evidence=evidence,
                error_detail=redact_text(
                    str(
                        getattr(
                            result,
                            "message",
                            "Microsoft Graph group membership change failed",
                        )
                    )
                ),
            )
        return ActionResult(
            status="success",
            output={**result_output, "approved": True},
            evidence=evidence,
        )


class M365PasswordResetAction:
    manifest = SmartActionManifest(
        action_id="m365-password-reset",
        title="Microsoft 365 password reset",
        description=(
            "Prepare an approval-gated password reset using a temporary credential "
            "held in WAIT's local encrypted vault."
        ),
        kind="deterministic",
        input_schema={
            "type": "object",
            "required": ["user_identity", "temporary_vault_name"],
            "properties": {
                "user_identity": {"type": "string", "minLength": 1, "maxLength": 320},
                "temporary_vault_name": {"type": "string", "minLength": 14, "maxLength": 128},
                "force_change_password_next_sign_in": {"type": "boolean"},
                "force_change_password_next_sign_in_with_mfa": {"type": "boolean"},
            },
        },
        output_schema={
            "operation": "string",
            "connector_status": "string",
            "user_identity": "string",
            "temporary_credential_source": "string",
            "status_code": "number",
        },
        requires_approval=True,
        estimated_minutes_saved=5,
        risk_level="high",
        required_role="admin",
        access_mode="write",
    )

    def run(self, context: ActionContext, payload: dict[str, object]) -> ActionResult:
        if set(payload) - {
            "user_identity",
            "temporary_vault_name",
            "force_change_password_next_sign_in",
            "force_change_password_next_sign_in_with_mfa",
            "ticket_id",
            "_approval_completed",
        }:
            return _failed("M365 password reset payload contains unsupported fields")
        reset_payload = {
            "connector": "m365",
            "action_type": "users.password-reset",
            "force_change_next_sign_in": payload.get(
                "force_change_password_next_sign_in", True
            ),
            "force_change_next_sign_in_with_mfa": payload.get(
                "force_change_password_next_sign_in_with_mfa", False
            ),
            "temporary_vault_name": payload.get("temporary_vault_name"),
            "user_identity": payload.get("user_identity"),
        }
        try:
            from wait_local_agent.connectors import validate_m365_password_reset_payload

            validate_m365_password_reset_payload(reset_payload)
        except (TypeError, ValueError) as exc:
            return _failed(redact_text(str(exc)))
        user_identity = str(reset_payload["user_identity"]).strip()
        vault_name = str(reset_payload["temporary_vault_name"]).strip()
        force_change = bool(reset_payload["force_change_next_sign_in"])
        force_change_mfa = bool(reset_payload["force_change_next_sign_in_with_mfa"])
        from wait_local_agent.m365_graph import M365GraphClient

        provider = cast(
            M365PasswordResetProvider,
            context.m365_client or M365GraphClient(context.settings),
        )
        try:
            health = provider.write_health()
        except Exception:
            return _failed("Microsoft Graph write readiness check failed")
        connector_status = str(getattr(health, "status", "failed"))
        connector_message = redact_text(
            str(getattr(health, "message", "Microsoft Graph writes are unavailable"))
        )
        output: dict[str, object] = {
            "operation": "password_reset",
            "connector_status": connector_status,
            "user_identity": user_identity,
            "force_change_password_next_sign_in": force_change,
            "force_change_password_next_sign_in_with_mfa": force_change_mfa,
            "temporary_credential_source": "local_encrypted_vault",
        }
        evidence: list[dict[str, object]] = [
            {
                "type": "connector_write_preflight",
                "connector": "m365",
                "operation": "password_reset",
                "client_id": context.client_id,
                "scope": {"user_identity": user_identity},
                "credential_source": "local_encrypted_vault",
            }
        ]
        if connector_status != "ready":
            return ActionResult(status="failed", output=output, evidence=evidence, error_detail=connector_message)
        if not payload.get("_approval_completed"):
            return ActionResult(
                status="success",
                output={**output, "approval_required": True},
                evidence=evidence,
            )
        try:
            from wait_local_agent.vault import SecretVault, SecretVaultError

            temporary_password = SecretVault(context.settings.vault_path).get(vault_name)
        except (SecretVaultError, ValueError):
            return ActionResult(
                status="failed",
                output=output,
                evidence=evidence,
                error_detail="M365 temporary credential could not be read from the local vault",
            )
        if not temporary_password:
            return ActionResult(
                status="failed",
                output=output,
                evidence=evidence,
                error_detail="M365 temporary credential is missing from the local vault",
            )
        try:
            result = provider.reset_user_password(
                user_identity=user_identity,
                temporary_password=temporary_password,
                force_change_password_next_sign_in=force_change,
                force_change_password_next_sign_in_with_mfa=force_change_mfa,
            )
        except Exception:
            return ActionResult(
                status="failed",
                output=output,
                evidence=evidence,
                error_detail="Microsoft Graph password reset failed",
            )
        result_output = {**output, "status_code": getattr(result, "status_code", None)}
        if str(getattr(result, "status", "failed")) != "succeeded":
            return ActionResult(
                status="failed",
                output=result_output,
                evidence=evidence,
                error_detail=redact_text(
                    str(getattr(result, "message", "Microsoft Graph password reset failed"))
                ),
            )
        return ActionResult(status="success", output={**result_output, "approved": True}, evidence=evidence)


class M365AuthenticationMethodDeleteAction:
    manifest = SmartActionManifest(
        action_id="m365-authentication-method-remove",
        title="Microsoft 365 authentication method removal",
        description=(
            "Prepare an approval-gated removal of one explicitly identified FIDO2, "
            "Microsoft Authenticator, phone, or software OATH method."
        ),
        kind="deterministic",
        input_schema={
            "type": "object",
            "required": ["user_identity", "method_type", "method_id"],
            "properties": {
                "user_identity": {"type": "string", "minLength": 1, "maxLength": 320},
                "method_type": {
                    "type": "string",
                    "enum": ["fido2", "microsoft_authenticator", "phone", "software_oath"],
                },
                "method_id": {"type": "string", "minLength": 1, "maxLength": 320},
            },
        },
        output_schema={
            "operation": "string",
            "connector_status": "string",
            "user_identity": "string",
            "method_type": "string",
            "method_id": "string",
            "status_code": "number",
        },
        requires_approval=True,
        estimated_minutes_saved=4,
        risk_level="high",
        required_role="admin",
        access_mode="write",
    )

    def run(self, context: ActionContext, payload: dict[str, object]) -> ActionResult:
        if set(payload) - {"user_identity", "method_type", "method_id", "ticket_id", "_approval_completed"}:
            return _failed("M365 authentication method payload contains unsupported fields")
        remove_payload = {
            "connector": "m365",
            "action_type": "users.authentication-methods.remove",
            "method_id": payload.get("method_id"),
            "method_type": payload.get("method_type"),
            "user_identity": payload.get("user_identity"),
        }
        try:
            from wait_local_agent.connectors import validate_m365_authentication_method_delete_payload

            validate_m365_authentication_method_delete_payload(remove_payload)
        except (TypeError, ValueError) as exc:
            return _failed(redact_text(str(exc)))
        user_identity = str(remove_payload["user_identity"]).strip()
        method_type = str(remove_payload["method_type"])
        method_id = str(remove_payload["method_id"]).strip()
        from wait_local_agent.m365_graph import M365GraphClient

        provider = cast(
            M365AuthenticationMethodDeleteProvider,
            context.m365_client or M365GraphClient(context.settings),
        )
        try:
            health = provider.write_health()
        except Exception:
            return _failed("Microsoft Graph write readiness check failed")
        connector_status = str(getattr(health, "status", "failed"))
        connector_message = redact_text(
            str(getattr(health, "message", "Microsoft Graph writes are unavailable"))
        )
        output: dict[str, object] = {
            "operation": "authentication_method_remove",
            "connector_status": connector_status,
            "user_identity": user_identity,
            "method_type": method_type,
            "method_id": method_id,
        }
        evidence: list[dict[str, object]] = [
            {
                "type": "connector_write_preflight",
                "connector": "m365",
                "operation": "authentication_method_remove",
                "client_id": context.client_id,
                "scope": {"user_identity": user_identity, "method_id": method_id},
            }
        ]
        if connector_status != "ready":
            return ActionResult(status="failed", output=output, evidence=evidence, error_detail=connector_message)
        if not payload.get("_approval_completed"):
            return ActionResult(
                status="success",
                output={**output, "approval_required": True},
                evidence=evidence,
            )
        try:
            result = provider.delete_authentication_method(
                user_identity=user_identity,
                method_type=method_type,
                method_id=method_id,
            )
        except Exception:
            return ActionResult(
                status="failed",
                output=output,
                evidence=evidence,
                error_detail="Microsoft Graph authentication method removal failed",
            )
        result_output = {**output, "status_code": getattr(result, "status_code", None)}
        if str(getattr(result, "status", "failed")) != "succeeded":
            return ActionResult(
                status="failed",
                output=result_output,
                evidence=evidence,
                error_detail=redact_text(
                    str(getattr(result, "message", "Microsoft Graph authentication method removal failed"))
                ),
            )
        return ActionResult(status="success", output={**result_output, "approved": True}, evidence=evidence)


class M365UserOnboardingAction:
    manifest = SmartActionManifest(
        action_id="m365-user-onboarding",
        title="Microsoft 365 user onboarding",
        description=(
            "Prepare an approval-gated Microsoft Graph user creation operation using a "
            "temporary password held in WAIT's local encrypted vault."
        ),
        kind="deterministic",
        input_schema={
            "type": "object",
            "required": [
                "user_principal_name",
                "display_name",
                "mail_nickname",
                "temporary_vault_name",
            ],
            "properties": {
                "user_principal_name": {"type": "string", "minLength": 3, "maxLength": 320},
                "display_name": {"type": "string", "minLength": 1, "maxLength": 256},
                "mail_nickname": {"type": "string", "minLength": 1, "maxLength": 64},
                "temporary_vault_name": {"type": "string", "minLength": 14, "maxLength": 128},
                "account_enabled": {"type": "boolean"},
                "force_change_password_next_sign_in": {"type": "boolean"},
            },
        },
        output_schema={
            "operation": "string",
            "connector_status": "string",
            "user_principal_name": "string",
            "display_name": "string",
            "remote_id": "string",
            "temporary_credential_source": "string",
        },
        requires_approval=True,
        estimated_minutes_saved=10,
        risk_level="high",
        required_role="admin",
        access_mode="write",
    )

    def run(self, context: ActionContext, payload: dict[str, object]) -> ActionResult:
        allowed = {
            "user_principal_name",
            "display_name",
            "mail_nickname",
            "temporary_vault_name",
            "account_enabled",
            "force_change_password_next_sign_in",
            "ticket_id",
            "_approval_completed",
        }
        if any(key not in allowed for key in payload):
            return _failed("M365 user onboarding payload contains unsupported fields")
        account_enabled = payload.get("account_enabled", True)
        force_change = payload.get("force_change_password_next_sign_in", True)
        if not isinstance(account_enabled, bool) or not isinstance(force_change, bool):
            return _failed("M365 user onboarding flags are invalid")
        onboarding_payload: dict[str, object] = {
            "connector": "m365",
            "action_type": "users.create",
            "account_enabled": account_enabled,
            "display_name": payload.get("display_name"),
            "force_change_next_sign_in": force_change,
            "mail_nickname": payload.get("mail_nickname"),
            "temporary_vault_name": payload.get("temporary_vault_name"),
            "user_principal_name": payload.get("user_principal_name"),
        }
        try:
            from wait_local_agent.connectors import validate_m365_user_creation_payload

            validate_m365_user_creation_payload(onboarding_payload)
        except (TypeError, ValueError) as exc:
            return _failed(redact_text(str(exc)))
        user_principal_name = str(onboarding_payload["user_principal_name"]).strip()
        display_name = str(onboarding_payload["display_name"]).strip()
        mail_nickname = str(onboarding_payload["mail_nickname"]).strip()
        vault_name = str(onboarding_payload["temporary_vault_name"]).strip()
        from wait_local_agent.m365_graph import M365GraphClient

        provider = cast(
            M365UserCreateProvider,
            context.m365_client or M365GraphClient(context.settings),
        )
        try:
            health = provider.write_health()
        except Exception:
            return _failed("Microsoft Graph write readiness check failed")
        connector_status = str(getattr(health, "status", "failed"))
        connector_message = redact_text(
            str(getattr(health, "message", "Microsoft Graph writes are unavailable"))
        )
        base_output = {
            "operation": "user_onboarding",
            "connector_status": connector_status,
            "user_principal_name": user_principal_name,
            "display_name": display_name,
            "mail_nickname": mail_nickname,
            "account_enabled": account_enabled,
            "force_change_password_next_sign_in": force_change,
            "temporary_credential_source": "local_encrypted_vault",
        }
        evidence: list[dict[str, object]] = [
            {
                "type": "connector_write_preflight",
                "connector": "m365",
                "operation": "user_onboarding",
                "client_id": context.client_id,
                "credential_source": "local_encrypted_vault",
            }
        ]
        if connector_status != "ready":
            return ActionResult(
                status="failed",
                output=base_output,
                evidence=evidence,
                error_detail=connector_message,
            )
        if not payload.get("_approval_completed"):
            return ActionResult(
                status="success",
                output={**base_output, "approval_required": True},
                evidence=evidence,
            )
        try:
            from wait_local_agent.vault import SecretVault, SecretVaultError

            temporary_password = SecretVault(context.settings.vault_path).get(vault_name)
        except (SecretVaultError, ValueError):
            return ActionResult(
                status="failed",
                output=base_output,
                evidence=evidence,
                error_detail="M365 temporary credential could not be read from the local vault",
            )
        if not temporary_password:
            return ActionResult(
                status="failed",
                output=base_output,
                evidence=evidence,
                error_detail="M365 temporary credential is missing from the local vault",
            )
        try:
            created = provider.create_user(
                user_principal_name=user_principal_name,
                display_name=display_name,
                mail_nickname=mail_nickname,
                temporary_password=temporary_password,
                account_enabled=account_enabled,
                force_change_password_next_sign_in=force_change,
            )
        except Exception:
            return ActionResult(
                status="failed",
                output=base_output,
                evidence=evidence,
                error_detail="Microsoft Graph user creation failed",
            )
        create_status = str(getattr(created, "status", "failed"))
        result_output = {
            **base_output,
            "remote_id": str(getattr(created, "remote_id", "")),
            "status_code": getattr(created, "status_code", None),
        }
        if create_status != "succeeded":
            return ActionResult(
                status="failed",
                output=result_output,
                evidence=evidence,
                error_detail=redact_text(
                    str(getattr(created, "message", "Microsoft Graph user creation failed"))
                ),
            )
        return ActionResult(
            status="success",
            output={**result_output, "approved": True},
            evidence=evidence,
        )


class M365UserOffboardingAction:
    manifest = SmartActionManifest(
        action_id="m365-user-offboarding",
        title="Microsoft 365 user offboarding",
        description=(
            "Prepare an approval-gated Microsoft Graph offboarding operation that disables "
            "one user and then revokes that user's active sessions."
        ),
        kind="deterministic",
        input_schema={
            "type": "object",
            "required": ["user_identity", "user_id"],
            "properties": {
                "user_identity": {"type": "string", "minLength": 1, "maxLength": 320},
                "user_id": {"type": "string", "minLength": 1, "maxLength": 320},
            },
        },
        output_schema={
            "operation": "string",
            "connector_status": "string",
            "completed_steps": "array",
            "remaining_steps": "array",
            "partial_failure": "boolean",
        },
        requires_approval=True,
        estimated_minutes_saved=10,
        risk_level="high",
        required_role="admin",
        access_mode="write",
    )

    def run(self, context: ActionContext, payload: dict[str, object]) -> ActionResult:
        user_identity = payload.get("user_identity")
        user_id = payload.get("user_id")
        if (
            not isinstance(user_identity, str)
            or not user_identity.strip()
            or len(user_identity.strip()) > 320
        ):
            return _failed("user_identity must be a non-empty string of at most 320 characters")
        if not isinstance(user_id, str) or not user_id.strip() or len(user_id.strip()) > 320:
            return _failed("user_id must be a non-empty string of at most 320 characters")
        safe_identity = user_identity.strip()
        safe_user_id = user_id.strip()
        from wait_local_agent.m365_graph import M365GraphClient

        provider = cast(
            M365LifecycleWriteProvider,
            context.m365_client or M365GraphClient(context.settings),
        )
        try:
            health = provider.write_health()
        except Exception:
            return _failed("Microsoft Graph write readiness check failed")
        connector_status = str(getattr(health, "status", "failed"))
        connector_message = redact_text(
            str(getattr(health, "message", "Microsoft Graph writes are unavailable"))
        )
        base_output = {
            "operation": "user_offboarding",
            "user_identity": safe_identity,
            "user_id": safe_user_id,
            "connector_status": connector_status,
            "completed_steps": [],
            "remaining_steps": ["disable_account", "revoke_sessions"],
            "partial_failure": False,
        }
        evidence: list[dict[str, object]] = [
            {
                "type": "connector_write_preflight",
                "connector": "m365",
                "operation": "user_offboarding",
                "client_id": context.client_id,
            }
        ]
        if connector_status != "ready":
            return ActionResult(status="failed", output=base_output, evidence=evidence, error_detail=connector_message)
        if not payload.get("_approval_completed"):
            return ActionResult(
                status="success",
                output={**base_output, "approval_required": True},
                evidence=evidence,
            )
        try:
            disabled = provider.disable_user(user_identity=safe_identity)
        except Exception:
            return ActionResult(
                status="failed",
                output=base_output,
                evidence=evidence,
                error_detail="Microsoft Graph account disable failed",
            )
        disable_status = str(getattr(disabled, "status", "failed"))
        if disable_status != "succeeded":
            return ActionResult(
                status="failed",
                output={**base_output, "disable_status": disable_status},
                evidence=evidence,
                error_detail=redact_text(str(getattr(disabled, "message", "Microsoft Graph account disable failed"))),
            )
        after_disable = {
            **base_output,
            "completed_steps": ["disable_account"],
            "remaining_steps": ["revoke_sessions"],
        }
        try:
            revoked = provider.revoke_user_sessions(user_id=safe_user_id)
        except Exception:
            return ActionResult(
                status="failed",
                output={**after_disable, "partial_failure": True},
                evidence=evidence,
                error_detail="Microsoft Graph session revocation failed after account disable",
            )
        revoke_status = str(getattr(revoked, "status", "failed"))
        if revoke_status != "succeeded":
            return ActionResult(
                status="failed",
                output={**after_disable, "partial_failure": True, "revoke_status": revoke_status},
                evidence=evidence,
                error_detail=redact_text(
                    str(getattr(revoked, "message", "Microsoft Graph session revocation failed"))
                ),
            )
        return ActionResult(
            status="success",
            output={
                **base_output,
                "completed_steps": ["disable_account", "revoke_sessions"],
                "remaining_steps": [],
                "approved": True,
            },
            evidence=evidence,
        )


class RmmDeviceLookupAction:
    manifest = SmartActionManifest(
        action_id="rmm-device-lookup",
        title="RMM device lookup",
        description="Search read-only endpoint-management inventory normalized through the RMM adapter boundary.",
        kind="deterministic",
        input_schema={
            "type": "object",
            "required": ["query"],
            "properties": {
                "query": {"type": "string", "minLength": 1, "maxLength": 200},
                "limit": {"type": "integer", "minimum": 1, "maximum": 100},
            },
        },
        output_schema={"devices": "array", "count": "integer", "source": "string"},
        requires_approval=False,
        estimated_minutes_saved=3,
        risk_level="low",
        required_role="technician",
        access_mode="read",
    )

    def run(self, context: ActionContext, payload: dict[str, object]) -> ActionResult:
        query = payload.get("query")
        if not isinstance(query, str) or not query.strip() or len(query.strip()) > 200:
            return _failed("query must be a non-empty string of at most 200 characters")
        limit = payload.get("limit", 20)
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1 or limit > 100:
            return _failed("limit must be an integer between 1 and 100")
        provider = context.rmm_provider or LocalCollectorRmmAdapter(context.store)
        try:
            devices = provider.list_devices(context.client_id)
        except Exception:
            return _failed("RMM inventory is unavailable")
        needle = query.strip().casefold()
        matches = [
            device
            for device in devices
            if needle
            in " ".join(
                [device.device_id, device.name, device.category]
                + [str(value) for value in device.attributes.values()]
            ).casefold()
        ]
        matches.sort(key=lambda device: (device.name.casefold(), device.device_id))
        selected = matches[:limit]
        output_devices = [
            {
                "device_id": device.device_id,
                "name": device.name,
                "category": device.category,
                "attributes": device.attributes,
            }
            for device in selected
        ]
        return ActionResult(
            status="success",
            output={
                "devices": output_devices,
                "count": len(output_devices),
                "source": provider.adapter_id,
            },
            evidence=[
                {"type": "rmm_device", "device_id": device.device_id}
                for device in selected
            ],
        )


class RmmAlertLookupAction:
    manifest = SmartActionManifest(
        action_id="rmm-alert-lookup",
        title="RMM alert lookup",
        description="List bounded tenant-scoped alerts from the configured RMM adapter.",
        kind="deterministic",
        input_schema={"type": "object"},
        output_schema={"alerts": "array", "count": "integer", "source": "string"},
        requires_approval=False,
        estimated_minutes_saved=3,
        risk_level="low",
        required_role="technician",
        access_mode="read",
    )

    def run(self, context: ActionContext, payload: dict[str, object]) -> ActionResult:
        provider = context.rmm_provider or LocalCollectorRmmAdapter(context.store)
        try:
            alerts = provider.list_alerts(context.client_id)
        except Exception:
            return _failed("RMM alerts are unavailable")
        output = [asdict(alert) for alert in alerts[:100]]
        return ActionResult(
            status="success",
            output={"alerts": output, "count": len(output), "source": provider.adapter_id},
            evidence=[{"type": "rmm_alert", "alert_id": alert.alert_id} for alert in alerts[:100]],
        )


class NSightPatchLookupAction:
    manifest = SmartActionManifest(
        action_id="nsight-patch-lookup",
        title="N-sight patch lookup",
        description=(
            "Read bounded software-patch inventory for one mapped N-sight device "
            "through the documented read-only API."
        ),
        kind="deterministic",
        input_schema={
            "type": "object",
            "required": ["device_id"],
            "properties": {
                "device_id": {"type": "string", "minLength": 1, "maxLength": 80},
            },
        },
        output_schema={"patches": "array", "count": "integer", "source": "string"},
        requires_approval=False,
        estimated_minutes_saved=4,
        risk_level="low",
        required_role="technician",
        access_mode="read",
    )

    def run(self, context: ActionContext, payload: dict[str, object]) -> ActionResult:
        device_id = payload.get("device_id")
        if not isinstance(device_id, str) or not device_id.strip() or len(device_id.strip()) > 80:
            return _failed("device_id must be a non-empty string of at most 80 characters")
        provider = context.rmm_provider or LocalCollectorRmmAdapter(context.store)
        list_patches = getattr(provider, "list_patches", None)
        if getattr(provider, "adapter_id", "") != "n-sight" or not callable(list_patches):
            return _failed("N-sight patch lookup requires the N-sight RMM adapter")
        try:
            patches = list_patches(device_id.strip(), client_id=context.client_id)
        except Exception:
            return _failed("N-sight patch lookup failed")
        if not isinstance(patches, list) or any(not isinstance(patch, dict) for patch in patches):
            return _failed("N-sight returned malformed patch data")
        output_patches = [cast(dict[str, object], redact_value(patch)) for patch in patches[:100]]
        return ActionResult(
            status="success",
            output={
                "patches": output_patches,
                "count": len(output_patches),
                "source": provider.adapter_id,
            },
            evidence=[
                {
                    "type": "rmm_patch",
                    "device_id": device_id.strip(),
                    "source": provider.adapter_id,
                }
            ],
        )


class NSightCheckInventoryAction:
    manifest = SmartActionManifest(
        action_id="nsight-check-inventory",
        title="N-sight check inventory",
        description=(
            "Read bounded documented check configuration and latest status for one "
            "mapped N-sight server or workstation."
        ),
        kind="deterministic",
        input_schema={
            "type": "object",
            "required": ["device_id"],
            "properties": {
                "device_id": {"type": "string", "minLength": 1, "maxLength": 80},
            },
        },
        output_schema={"checks": "array", "count": "integer", "source": "string"},
        requires_approval=False,
        estimated_minutes_saved=4,
        risk_level="low",
        required_role="technician",
        access_mode="read",
    )

    def run(self, context: ActionContext, payload: dict[str, object]) -> ActionResult:
        device_id = payload.get("device_id")
        if not isinstance(device_id, str) or not device_id.strip() or len(device_id.strip()) > 80:
            return _failed("device_id must be a non-empty string of at most 80 characters")
        provider = context.rmm_provider or LocalCollectorRmmAdapter(context.store)
        list_checks = getattr(provider, "list_checks", None)
        if getattr(provider, "adapter_id", "") != "n-sight" or not callable(list_checks):
            return _failed("N-sight check inventory requires the N-sight RMM adapter")
        try:
            checks = list_checks(device_id.strip(), client_id=context.client_id)
        except Exception:
            return _failed("N-sight check inventory is unavailable")
        if not isinstance(checks, list) or any(not isinstance(check, dict) for check in checks):
            return _failed("N-sight returned malformed check inventory data")
        output_checks = [cast(dict[str, object], redact_value(check)) for check in checks[:100]]
        return ActionResult(
            status="success",
            output={
                "checks": output_checks,
                "count": len(output_checks),
                "source": provider.adapter_id,
            },
            evidence=[
                {
                    "type": "rmm_check",
                    "device_id": device_id.strip(),
                    "source": provider.adapter_id,
                    "check_id": check.get("check_id"),
                }
                for check in output_checks
            ],
        )


class NSightCheckConfigAction:
    manifest = SmartActionManifest(
        action_id="nsight-check-config",
        title="N-sight check configuration",
        description=(
            "Read one mapped N-sight check's documented configuration, including "
            "script or automated-task metadata when the provider returns it."
        ),
        kind="deterministic",
        input_schema={
            "type": "object",
            "required": ["device_id", "check_id"],
            "properties": {
                "device_id": {"type": "string", "minLength": 1, "maxLength": 80},
                "check_id": {"type": "string", "pattern": "^[1-9][0-9]*$", "maxLength": 10},
            },
        },
        output_schema={
            "device_id": "string",
            "check_id": "integer",
            "check_type": "integer|null",
            "description": "string",
            "configuration": "object",
        },
        requires_approval=False,
        estimated_minutes_saved=4,
        risk_level="low",
        required_role="technician",
        access_mode="read",
    )

    def run(self, context: ActionContext, payload: dict[str, object]) -> ActionResult:
        device_id = payload.get("device_id")
        check_id = payload.get("check_id")
        if not isinstance(device_id, str) or not device_id.strip() or len(device_id.strip()) > 80:
            return _failed("device_id must be a non-empty string of at most 80 characters")
        if (
            not isinstance(check_id, str)
            or not check_id.isdigit()
            or not (1 <= int(check_id) <= 2_147_483_647)
        ):
            return _failed("check_id must be a positive integer string")
        provider = context.rmm_provider or LocalCollectorRmmAdapter(context.store)
        get_check_config = getattr(provider, "get_check_config", None)
        if getattr(provider, "adapter_id", "") != "n-sight" or not callable(get_check_config):
            return _failed("N-sight check configuration requires the N-sight RMM adapter")
        try:
            configuration = get_check_config(
                device_id.strip(),
                int(check_id),
                client_id=context.client_id,
            )
        except Exception:
            return _failed("N-sight check configuration is unavailable")
        if not isinstance(configuration, dict):
            return _failed("N-sight returned malformed check configuration data")
        output = cast(dict[str, object], redact_value(configuration))
        return ActionResult(
            status="success",
            output=output,
            evidence=[
                {
                    "type": "rmm_check_configuration",
                    "operation": "list_check_config",
                    "device_id": device_id.strip(),
                    "check_id": int(check_id),
                    "source": provider.adapter_id,
                }
            ],
        )


class NSightPerformanceHistoryAction:
    manifest = SmartActionManifest(
        action_id="nsight-performance-history",
        title="N-sight performance history",
        description=(
            "Read bounded documented performance and bandwidth history for one "
            "mapped N-sight server or workstation."
        ),
        kind="deterministic",
        input_schema={
            "type": "object",
            "required": ["device_id"],
            "properties": {
                "device_id": {"type": "string", "minLength": 1, "maxLength": 80},
            },
        },
        output_schema={"records": "array", "count": "integer", "source": "string"},
        requires_approval=False,
        estimated_minutes_saved=5,
        risk_level="low",
        required_role="technician",
        access_mode="read",
    )

    def run(self, context: ActionContext, payload: dict[str, object]) -> ActionResult:
        device_id = payload.get("device_id")
        if not isinstance(device_id, str) or not device_id.strip() or len(device_id.strip()) > 80:
            return _failed("device_id must be a non-empty string of at most 80 characters")
        provider = context.rmm_provider or LocalCollectorRmmAdapter(context.store)
        list_history = getattr(provider, "list_performance_history", None)
        if getattr(provider, "adapter_id", "") != "n-sight" or not callable(list_history):
            return _failed("N-sight performance history requires the N-sight RMM adapter")
        try:
            records = list_history(device_id.strip(), client_id=context.client_id)
        except Exception:
            return _failed("N-sight performance history is unavailable")
        if not isinstance(records, list) or any(not isinstance(record, dict) for record in records):
            return _failed("N-sight returned malformed performance history data")
        output_records = [cast(dict[str, object], redact_value(record)) for record in records[:100]]
        return ActionResult(
            status="success",
            output={
                "records": output_records,
                "count": len(output_records),
                "source": provider.adapter_id,
            },
            evidence=[
                {
                    "type": "rmm_performance_history",
                    "device_id": device_id.strip(),
                    "source": provider.adapter_id,
                    "category": record.get("category"),
                    "check_id": record.get("check_id"),
                }
                for record in output_records
            ],
        )


class NSightAssetDetailsAction:
    manifest = SmartActionManifest(
        action_id="nsight-asset-details",
        title="N-sight asset details",
        description=(
            "Read bounded documented asset details plus hardware and software "
            "inventory for one mapped N-sight device."
        ),
        kind="deterministic",
        input_schema={
            "type": "object",
            "required": ["device_id"],
            "properties": {
                "device_id": {"type": "string", "minLength": 1, "maxLength": 80},
            },
        },
        output_schema={
            "details": "object",
            "hardware": "array",
            "software": "array",
            "source": "string",
        },
        requires_approval=False,
        estimated_minutes_saved=6,
        risk_level="low",
        required_role="technician",
        access_mode="read",
    )

    def run(self, context: ActionContext, payload: dict[str, object]) -> ActionResult:
        device_id = payload.get("device_id")
        if not isinstance(device_id, str) or not device_id.strip() or len(device_id.strip()) > 80:
            return _failed("device_id must be a non-empty string of at most 80 characters")
        provider = context.rmm_provider or LocalCollectorRmmAdapter(context.store)
        list_details = getattr(provider, "list_asset_details", None)
        if getattr(provider, "adapter_id", "") != "n-sight" or not callable(list_details):
            return _failed("N-sight asset details requires the N-sight RMM adapter")
        try:
            asset = list_details(device_id.strip(), client_id=context.client_id)
        except Exception:
            return _failed("N-sight asset details are unavailable")
        if not isinstance(asset, dict):
            return _failed("N-sight returned malformed asset details")
        details = asset.get("details")
        hardware = asset.get("hardware")
        software = asset.get("software")
        if not isinstance(details, dict) or not isinstance(hardware, list) or not isinstance(software, list):
            return _failed("N-sight returned malformed asset details")
        if any(not isinstance(item, dict) for item in [*hardware[:100], *software[:100]]):
            return _failed("N-sight returned malformed asset details")
        output = cast(
            dict[str, object],
            redact_value(
                {
                    "details": details,
                    "hardware": hardware[:100],
                    "software": software[:100],
                }
            ),
        )
        output["source"] = provider.adapter_id
        return ActionResult(
            status="success",
            output=output,
            evidence=[
                {"type": "rmm_asset", "device_id": device_id.strip(), "source": provider.adapter_id},
                *[
                    {
                        "type": "rmm_hardware",
                        "device_id": device_id.strip(),
                        "hardware_id": item.get("hardware_id"),
                        "source": provider.adapter_id,
                    }
                    for item in hardware[:100]
                ],
                *[
                    {
                        "type": "rmm_software",
                        "device_id": device_id.strip(),
                        "software_id": item.get("software_id"),
                        "source": provider.adapter_id,
                    }
                    for item in software[:100]
                ],
            ],
        )


class NSightMonitoringDetailsAction:
    manifest = SmartActionManifest(
        action_id="nsight-monitoring-details",
        title="N-sight monitoring details",
        description=(
            "Read bounded documented device monitoring details, checks, outages, "
            "notes, and feature flags for one mapped N-sight device."
        ),
        kind="deterministic",
        input_schema={
            "type": "object",
            "required": ["device_id"],
            "properties": {
                "device_id": {"type": "string", "minLength": 1, "maxLength": 80},
            },
        },
        output_schema={
            "device": "object",
            "checks": "array",
            "outages": "array",
            "notes": "array",
            "features": "object",
            "source": "string",
        },
        requires_approval=False,
        estimated_minutes_saved=7,
        risk_level="low",
        required_role="technician",
        access_mode="read",
    )

    def run(self, context: ActionContext, payload: dict[str, object]) -> ActionResult:
        device_id = payload.get("device_id")
        if not isinstance(device_id, str) or not device_id.strip() or len(device_id.strip()) > 80:
            return _failed("device_id must be a non-empty string of at most 80 characters")
        provider = context.rmm_provider or LocalCollectorRmmAdapter(context.store)
        list_details = getattr(provider, "list_monitoring_details", None)
        if getattr(provider, "adapter_id", "") != "n-sight" or not callable(list_details):
            return _failed("N-sight monitoring details requires the N-sight RMM adapter")
        try:
            details = list_details(device_id.strip(), client_id=context.client_id)
        except Exception:
            return _failed("N-sight monitoring details are unavailable")
        if not isinstance(details, dict):
            return _failed("N-sight returned malformed monitoring details")
        device = details.get("device")
        checks = details.get("checks")
        outages = details.get("outages")
        notes = details.get("notes")
        features = details.get("features")
        if (
            not isinstance(device, dict)
            or not isinstance(checks, list)
            or not isinstance(outages, list)
            or not isinstance(notes, list)
            or not isinstance(features, dict)
            or any(not isinstance(item, dict) for item in checks[:100])
            or any(not isinstance(item, dict) for item in outages[:100])
            or any(not isinstance(item, dict) for item in notes[:100])
        ):
            return _failed("N-sight returned malformed monitoring details")
        output = cast(
            dict[str, object],
            redact_value(
                {
                    "device": device,
                    "checks": checks[:100],
                    "outages": outages[:100],
                    "notes": notes[:100],
                    "features": features,
                }
            ),
        )
        output["source"] = provider.adapter_id
        return ActionResult(
            status="success",
            output=output,
            evidence=[
                {"type": "rmm_monitoring_device", "device_id": device_id.strip(), "source": provider.adapter_id},
                *[
                    {
                        "type": "rmm_monitoring_check",
                        "device_id": device_id.strip(),
                        "check_id": check.get("check_id"),
                        "source": provider.adapter_id,
                    }
                    for check in checks[:100]
                ],
                *[
                    {
                        "type": "rmm_monitoring_outage",
                        "device_id": device_id.strip(),
                        "outage_id": outage.get("id"),
                        "source": provider.adapter_id,
                    }
                    for outage in outages[:100]
                ],
                *[
                    {
                        "type": "rmm_monitoring_note",
                        "device_id": device_id.strip(),
                        "note_id": note.get("note_id"),
                        "source": provider.adapter_id,
                    }
                    for note in notes[:100]
                ],
            ],
        )


class NSightAntivirusThreatsAction:
    manifest = SmartActionManifest(
        action_id="nsight-antivirus-threats",
        title="N-sight antivirus threat lookup",
        description=(
            "Read bounded managed-antivirus threat records for one mapped N-sight "
            "server or workstation."
        ),
        kind="deterministic",
        input_schema={
            "type": "object",
            "required": ["device_id"],
            "properties": {
                "device_id": {"type": "string", "minLength": 1, "maxLength": 80},
            },
        },
        output_schema={"threats": "array", "count": "integer", "source": "string"},
        requires_approval=False,
        estimated_minutes_saved=4,
        risk_level="low",
        required_role="technician",
        access_mode="read",
    )

    def run(self, context: ActionContext, payload: dict[str, object]) -> ActionResult:
        device_id = payload.get("device_id")
        if not isinstance(device_id, str) or not device_id.strip() or len(device_id.strip()) > 80:
            return _failed("device_id must be a non-empty string of at most 80 characters")
        provider = context.rmm_provider or LocalCollectorRmmAdapter(context.store)
        list_threats = getattr(provider, "list_antivirus_threats", None)
        if getattr(provider, "adapter_id", "") != "n-sight" or not callable(list_threats):
            return _failed("N-sight antivirus lookup requires the N-sight RMM adapter")
        try:
            threats = list_threats(device_id.strip(), client_id=context.client_id)
        except Exception:
            return _failed("N-sight antivirus threats are unavailable")
        if not isinstance(threats, list) or any(not isinstance(threat, dict) for threat in threats):
            return _failed("N-sight returned malformed antivirus threat data")
        output_threats = [cast(dict[str, object], redact_value(threat)) for threat in threats[:100]]
        return ActionResult(
            status="success",
            output={
                "threats": output_threats,
                "count": len(output_threats),
                "source": provider.adapter_id,
            },
            evidence=[
                {
                    "type": "rmm_antivirus_threat",
                    "device_id": device_id.strip(),
                    "source": provider.adapter_id,
                }
                for _ in output_threats
            ],
        )


class NSightOutageLookupAction:
    manifest = SmartActionManifest(
        action_id="nsight-outage-lookup",
        title="N-sight outage lookup",
        description=(
            "Read bounded open and recent outage records for one mapped N-sight "
            "server or workstation."
        ),
        kind="deterministic",
        input_schema={
            "type": "object",
            "required": ["device_id"],
            "properties": {
                "device_id": {"type": "string", "minLength": 1, "maxLength": 80},
            },
        },
        output_schema={"outages": "array", "count": "integer", "source": "string"},
        requires_approval=False,
        estimated_minutes_saved=4,
        risk_level="low",
        required_role="technician",
        access_mode="read",
    )

    def run(self, context: ActionContext, payload: dict[str, object]) -> ActionResult:
        device_id = payload.get("device_id")
        if not isinstance(device_id, str) or not device_id.strip() or len(device_id.strip()) > 80:
            return _failed("device_id must be a non-empty string of at most 80 characters")
        provider = context.rmm_provider or LocalCollectorRmmAdapter(context.store)
        list_outages = getattr(provider, "list_outages", None)
        if getattr(provider, "adapter_id", "") != "n-sight" or not callable(list_outages):
            return _failed("N-sight outage lookup requires the N-sight RMM adapter")
        try:
            outages = list_outages(device_id.strip(), client_id=context.client_id)
        except Exception:
            return _failed("N-sight outages are unavailable")
        if not isinstance(outages, list) or any(not isinstance(outage, dict) for outage in outages):
            return _failed("N-sight returned malformed outage data")
        output_outages = [cast(dict[str, object], redact_value(outage)) for outage in outages[:100]]
        return ActionResult(
            status="success",
            output={
                "outages": output_outages,
                "count": len(output_outages),
                "source": provider.adapter_id,
            },
            evidence=[
                {
                    "type": "rmm_outage",
                    "device_id": device_id.strip(),
                    "source": provider.adapter_id,
                    "outage_id": outage.get("outage_id"),
                }
                for outage in output_outages
            ],
        )


class NSightBackupSessionsAction:
    manifest = SmartActionManifest(
        action_id="nsight-backup-sessions",
        title="N-sight backup session lookup",
        description=(
            "Read bounded Backup & Recovery session history for one mapped "
            "N-sight server or workstation."
        ),
        kind="deterministic",
        input_schema={
            "type": "object",
            "required": ["device_id"],
            "properties": {
                "device_id": {"type": "string", "minLength": 1, "maxLength": 80},
            },
        },
        output_schema={"sessions": "array", "count": "integer", "source": "string"},
        requires_approval=False,
        estimated_minutes_saved=5,
        risk_level="low",
        required_role="technician",
        access_mode="read",
    )

    def run(self, context: ActionContext, payload: dict[str, object]) -> ActionResult:
        device_id = payload.get("device_id")
        if not isinstance(device_id, str) or not device_id.strip() or len(device_id.strip()) > 80:
            return _failed("device_id must be a non-empty string of at most 80 characters")
        provider = context.rmm_provider or LocalCollectorRmmAdapter(context.store)
        list_sessions = getattr(provider, "list_backup_sessions", None)
        if getattr(provider, "adapter_id", "") != "n-sight" or not callable(list_sessions):
            return _failed("N-sight backup lookup requires the N-sight RMM adapter")
        try:
            sessions = list_sessions(device_id.strip(), client_id=context.client_id)
        except Exception:
            return _failed("N-sight backup sessions are unavailable")
        if not isinstance(sessions, list) or any(
            not isinstance(session, dict) for session in sessions
        ):
            return _failed("N-sight returned malformed backup session data")
        output_sessions = [
            cast(dict[str, object], redact_value(session)) for session in sessions[:100]
        ]
        return ActionResult(
            status="success",
            output={
                "sessions": output_sessions,
                "count": len(output_sessions),
                "source": provider.adapter_id,
            },
            evidence=[
                {
                    "type": "rmm_backup_session",
                    "device_id": device_id.strip(),
                    "source": provider.adapter_id,
                    "session_id": session.get("session_id"),
                }
                for session in output_sessions
            ],
        )


class NSightBackupHistoryAction:
    manifest = SmartActionManifest(
        action_id="nsight-backup-history",
        title="N-sight backup history lookup",
        description=(
            "Read bounded 60-day Backup Check status history for one mapped "
            "N-sight server or workstation."
        ),
        kind="deterministic",
        input_schema={
            "type": "object",
            "required": ["device_id"],
            "properties": {
                "device_id": {"type": "string", "minLength": 1, "maxLength": 80},
            },
        },
        output_schema={
            "checks": "array",
            "days": "array",
            "count": "integer",
            "source": "string",
        },
        requires_approval=False,
        estimated_minutes_saved=5,
        risk_level="low",
        required_role="technician",
        access_mode="read",
    )

    def run(self, context: ActionContext, payload: dict[str, object]) -> ActionResult:
        device_id = payload.get("device_id")
        if not isinstance(device_id, str) or not device_id.strip() or len(device_id.strip()) > 80:
            return _failed("device_id must be a non-empty string of at most 80 characters")
        provider = context.rmm_provider or LocalCollectorRmmAdapter(context.store)
        list_history = getattr(provider, "list_backup_history", None)
        if getattr(provider, "adapter_id", "") != "n-sight" or not callable(list_history):
            return _failed("N-sight backup history requires the N-sight RMM adapter")
        try:
            history = list_history(device_id.strip(), client_id=context.client_id)
        except Exception:
            return _failed("N-sight backup history is unavailable")
        if not isinstance(history, dict):
            return _failed("N-sight returned malformed backup history data")
        checks = history.get("checks")
        days = history.get("days")
        if not isinstance(checks, list) or any(not isinstance(name, str) for name in checks):
            return _failed("N-sight returned malformed backup history data")
        if not isinstance(days, list) or any(
            not isinstance(day, dict)
            or not isinstance(day.get("date"), str)
            or not isinstance(day.get("status"), str)
            for day in days
        ):
            return _failed("N-sight returned malformed backup history data")
        output = cast(dict[str, object], redact_value({"checks": checks, "days": days}))
        output["count"] = len(days)
        output["source"] = provider.adapter_id
        return ActionResult(
            status="success",
            output=output,
            evidence=[
                {
                    "type": "rmm_backup_history",
                    "device_id": device_id.strip(),
                    "source": provider.adapter_id,
                    "date": day.get("date"),
                    "status": day.get("status"),
                }
                for day in days
            ],
        )


class NSightPatchApproveAction:
    manifest = SmartActionManifest(
        action_id="nsight-patch-approve",
        title="Approve N-sight patches",
        description=(
            "Preview and, after technician approval, approve existing patches "
            "for one mapped N-sight device."
        ),
        kind="deterministic",
        input_schema={
            "type": "object",
            "required": ["device_id", "patch_ids"],
            "properties": {
                "device_id": {"type": "string", "minLength": 1, "maxLength": 80},
                "patch_ids": {"type": "array", "minItems": 1, "maxItems": 20},
            },
        },
        output_schema={
            "status": "string",
            "device_id": "string",
            "patch_ids": "array",
            "approval_required": "boolean",
            "approved": "boolean",
        },
        requires_approval=True,
        estimated_minutes_saved=5,
        risk_level="high",
        required_role="technician",
        access_mode="write",
    )

    def run(self, context: ActionContext, payload: dict[str, object]) -> ActionResult:
        return _run_nsight_patch_write(
            context,
            payload,
            operation_label="approval",
            provider_method="approve_patches",
            provider_operation="patch_approve",
        )


class NSightPatchReprocessAction:
    manifest = SmartActionManifest(
        action_id="nsight-patch-reprocess",
        title="Reprocess N-sight patches",
        description=(
            "Preview and, after technician approval, request reprocessing for existing "
            "patches on one mapped N-sight device."
        ),
        kind="deterministic",
        input_schema={
            "type": "object",
            "required": ["device_id", "patch_ids"],
            "properties": {
                "device_id": {"type": "string", "minLength": 1, "maxLength": 80},
                "patch_ids": {"type": "array", "minItems": 1, "maxItems": 20},
            },
        },
        output_schema={
            "status": "string",
            "device_id": "string",
            "patch_ids": "array",
            "approval_required": "boolean",
            "approved": "boolean",
        },
        requires_approval=True,
        estimated_minutes_saved=5,
        risk_level="high",
        required_role="technician",
        access_mode="write",
    )

    def run(self, context: ActionContext, payload: dict[str, object]) -> ActionResult:
        return _run_nsight_patch_write(
            context,
            payload,
            operation_label="reprocessing",
            provider_method="reprocess_patches",
            provider_operation="patch_reprocess",
        )


class NSightPatchPolicyAction:
    manifest = SmartActionManifest(
        action_id="nsight-patch-policy",
        title="Manage N-sight patch policy",
        description=(
            "Preview and, after technician approval, apply one documented N-sight "
            "patch policy operation to existing patches on a mapped device."
        ),
        kind="deterministic",
        input_schema={
            "type": "object",
            "required": ["device_id", "patch_ids", "operation"],
            "properties": {
                "device_id": {"type": "string", "minLength": 1, "maxLength": 80},
                "patch_ids": {"type": "array", "minItems": 1, "maxItems": 20},
                "operation": {"type": "string", "enum": sorted(PATCH_POLICY_SERVICES)},
            },
        },
        output_schema={
            "status": "string",
            "operation": "string",
            "device_id": "string",
            "patch_ids": "array",
            "approval_required": "boolean",
            "approved": "boolean",
        },
        requires_approval=True,
        estimated_minutes_saved=5,
        risk_level="high",
        required_role="technician",
        access_mode="write",
    )

    def run(self, context: ActionContext, payload: dict[str, object]) -> ActionResult:
        operation = payload.get("operation")
        if not isinstance(operation, str) or operation not in PATCH_POLICY_SERVICES:
            return _failed(
                "N-sight patch operation must be one of: "
                + ", ".join(sorted(PATCH_POLICY_SERVICES))
            )
        clean_payload = {key: value for key, value in payload.items() if key != "operation"}
        result = _run_nsight_patch_write(
            context,
            clean_payload,
            operation_label="policy",
            provider_method="apply_patch_policy",
            provider_operation=PATCH_POLICY_SERVICES[operation],
            provider_kwargs={"operation": operation},
        )
        if result.status == "success":
            result.output["operation"] = operation
        return result


class NSightRunTaskNowAction:
    manifest = SmartActionManifest(
        action_id="nsight-run-task-now",
        title="Run N-sight automated task now",
        description=(
            "Preview and, after technician approval, run one documented automated "
            "task belonging to a mapped N-sight device."
        ),
        kind="deterministic",
        input_schema={
            "type": "object",
            "required": ["device_id", "check_id"],
            "properties": {
                "device_id": {"type": "string", "minLength": 1, "maxLength": 80},
                "check_id": {"type": "string", "pattern": "^[1-9][0-9]*$", "maxLength": 10},
            },
        },
        output_schema={
            "status": "string",
            "device_id": "string",
            "check_id": "integer",
            "minutes_until_run": "integer",
            "approval_required": "boolean",
            "approved": "boolean",
        },
        requires_approval=True,
        estimated_minutes_saved=6,
        risk_level="high",
        required_role="technician",
        access_mode="write",
    )

    def run(self, context: ActionContext, payload: dict[str, object]) -> ActionResult:
        if set(payload) - {"device_id", "check_id", "_approval_completed"}:
            return _failed("N-sight task execution payload contains unsupported fields")
        device_id = payload.get("device_id")
        check_id = payload.get("check_id")
        if not isinstance(device_id, str) or not device_id.strip() or len(device_id.strip()) > 80:
            return _failed("device_id must be a non-empty string of at most 80 characters")
        if (
            not isinstance(check_id, str)
            or not check_id.isdigit()
            or not (1 <= int(check_id) <= 2_147_483_647)
        ):
            return _failed("check_id must be a positive integer string")
        provider = context.rmm_provider or LocalCollectorRmmAdapter(context.store)
        run_task_now = getattr(provider, "run_task_now", None)
        if getattr(provider, "adapter_id", "") != "n-sight" or not callable(run_task_now):
            return _failed("N-sight task execution requires the N-sight RMM adapter")
        clean_device_id = device_id.strip()
        numeric_check_id = int(check_id)
        approved = bool(payload.get("_approval_completed"))
        if not approved:
            return ActionResult(
                status="success",
                output={
                    "status": "preview",
                    "device_id": clean_device_id,
                    "check_id": numeric_check_id,
                    "approval_required": True,
                    "approved": False,
                },
                evidence=[
                    {
                        "type": "rmm_automated_task",
                        "operation": "task_run_now",
                        "device_id": clean_device_id,
                        "check_id": numeric_check_id,
                    }
                ],
            )
        if not context.settings.allow_write_actions:
            return _failed(
                "N-sight task execution is blocked until WAIT_ALLOW_WRITE_ACTIONS=true"
            )
        try:
            operation = run_task_now(
                clean_device_id,
                numeric_check_id,
                client_id=context.client_id,
            )
        except Exception:
            return _failed("N-sight automated task execution failed")
        if not isinstance(operation, dict):
            return _failed("N-sight returned malformed automated-task data")
        output = cast(dict[str, object], redact_value(operation))
        output["approval_required"] = False
        output["approved"] = True
        accepted = output.get("status") == "accepted"
        return ActionResult(
            status="success" if accepted else "failed",
            output=output,
            evidence=[
                {
                    "type": "rmm_automated_task",
                    "operation": "task_run_now",
                    "device_id": clean_device_id,
                    "check_id": numeric_check_id,
                }
            ],
            error_detail="" if accepted else "N-sight automated task execution failed",
        )


def _run_nsight_patch_write(
    context: ActionContext,
    payload: dict[str, object],
    *,
    operation_label: str,
    provider_method: str,
    provider_operation: str,
    provider_kwargs: dict[str, object] | None = None,
) -> ActionResult:
    if set(payload) - {"device_id", "patch_ids", "_approval_completed"}:
        return _failed(f"N-sight patch {operation_label} payload contains unsupported fields")
    device_id = payload.get("device_id")
    patch_ids = payload.get("patch_ids")
    if not isinstance(device_id, str) or not device_id.strip() or len(device_id.strip()) > 80:
        return _failed("device_id must be a non-empty string of at most 80 characters")
    if not isinstance(patch_ids, list) or not patch_ids or len(patch_ids) > 20:
        return _failed("patch_ids must contain between 1 and 20 patch IDs")
    if any(not isinstance(patch_id, str) for patch_id in patch_ids):
        return _failed("patch_ids must contain only strings")
    normalized_ids = [patch_id.strip() for patch_id in patch_ids]
    if any(not patch_id.isdigit() or int(patch_id) <= 0 for patch_id in normalized_ids):
        return _failed("patch_ids must contain positive integers")
    provider = context.rmm_provider or LocalCollectorRmmAdapter(context.store)
    operation_fn = getattr(provider, provider_method, None)
    if getattr(provider, "adapter_id", "") != "n-sight" or not callable(operation_fn):
        return _failed(f"N-sight patch {operation_label} requires the N-sight RMM adapter")
    approved = bool(payload.get("_approval_completed"))
    if not approved:
        return ActionResult(
            status="success",
            output={
                "status": "preview",
                "device_id": device_id.strip(),
                "patch_ids": normalized_ids,
                "approval_required": True,
                "approved": False,
            },
            evidence=[
                {
                    "type": "rmm_patch_approval",
                    "operation": provider_operation,
                    "device_id": device_id.strip(),
                }
            ],
        )
    if not context.settings.allow_write_actions:
        return _failed(
            f"N-sight patch {operation_label} is blocked until WAIT_ALLOW_WRITE_ACTIONS=true"
        )
    try:
        call_kwargs: dict[str, object] = {"client_id": context.client_id}
        if provider_kwargs:
            call_kwargs.update(provider_kwargs)
        operation = operation_fn(device_id.strip(), normalized_ids, **call_kwargs)
    except Exception:
        return _failed(f"N-sight patch {operation_label} failed")
    if not isinstance(operation, dict):
        return _failed(f"N-sight returned malformed patch {operation_label} data")
    output = cast(dict[str, object], redact_value(operation))
    output["approval_required"] = False
    output["approved"] = True
    accepted = output.get("status") == "accepted"
    return ActionResult(
        status="success" if accepted else "failed",
        output=output,
        evidence=[
            {
                "type": "rmm_patch_approval",
                "operation": provider_operation,
                "device_id": device_id.strip(),
            }
        ],
        error_detail="" if accepted else f"N-sight patch {operation_label} failed",
    )


class RmmScriptCatalogAction:
    manifest = SmartActionManifest(
        action_id="rmm-script-catalog",
        title="RMM script catalog",
        description="List script metadata without exposing script source or credentials.",
        kind="deterministic",
        input_schema={"type": "object"},
        output_schema={"scripts": "array", "count": "integer", "source": "string"},
        requires_approval=False,
        estimated_minutes_saved=2,
        risk_level="low",
        required_role="technician",
        access_mode="read",
    )

    def run(self, context: ActionContext, payload: dict[str, object]) -> ActionResult:
        provider = context.rmm_provider or LocalCollectorRmmAdapter(context.store)
        try:
            scripts = provider.list_scripts(context.client_id)
        except Exception:
            return _failed("RMM script catalog is unavailable")
        output = [asdict(script) for script in scripts[:100]]
        return ActionResult(
            status="success",
            output={"scripts": output, "count": len(output), "source": provider.adapter_id},
            evidence=[{"type": "rmm_script", "script_id": script.script_id} for script in scripts[:100]],
        )


class RmmScriptPreviewAction:
    manifest = SmartActionManifest(
        action_id="rmm-script-preview",
        title="RMM script preview",
        description="Validate a bounded script request without executing it.",
        kind="deterministic",
        input_schema={"type": "object", "required": ["script_id", "device_id"]},
        output_schema={"script_id": "string", "device_id": "string", "status": "string"},
        requires_approval=False,
        estimated_minutes_saved=3,
        risk_level="medium",
        required_role="technician",
        access_mode="draft",
    )

    def run(self, context: ActionContext, payload: dict[str, object]) -> ActionResult:
        request = _rmm_script_request(payload)
        if isinstance(request, ActionResult):
            return request
        script_id, device_id, arguments = request
        provider = context.rmm_provider or LocalCollectorRmmAdapter(context.store)
        try:
            preview = provider.preview_script(
                script_id, device_id, arguments, client_id=context.client_id
            )
        except Exception:
            return _failed("RMM script preview failed")
        return ActionResult(
            status="success" if preview.status == "preview" else "failed",
            output=asdict(preview),
            evidence=[{"type": "rmm_script_preview", "script_id": script_id, "device_id": device_id}],
            error_detail="" if preview.status == "preview" else preview.message,
        )


class RmmScriptExecuteAction:
    manifest = SmartActionManifest(
        action_id="rmm-script-execute",
        title="Execute RMM script",
        description="Execute a provider script only after approval and provider authorization.",
        kind="deterministic",
        input_schema={"type": "object", "required": ["script_id", "device_id"]},
        output_schema={"script_id": "string", "device_id": "string", "status": "string"},
        requires_approval=True,
        estimated_minutes_saved=8,
        risk_level="high",
        required_role="technician",
        access_mode="write",
    )

    def run(self, context: ActionContext, payload: dict[str, object]) -> ActionResult:
        request = _rmm_script_request(payload)
        if isinstance(request, ActionResult):
            return request
        script_id, device_id, arguments = request
        provider = context.rmm_provider or LocalCollectorRmmAdapter(context.store)
        if not payload.get("_approval_completed"):
            try:
                preview = provider.preview_script(
                    script_id, device_id, arguments, client_id=context.client_id
                )
            except Exception:
                return _failed("RMM script preview failed")
            return ActionResult(
                status="success" if preview.status == "preview" else "failed",
                output={**asdict(preview), "approval_required": True, "approved": False},
                evidence=[{"type": "rmm_script_preview", "script_id": script_id, "device_id": device_id}],
                error_detail="" if preview.status == "preview" else preview.message,
            )
        if not context.settings.allow_write_actions:
            return _failed("RMM script execution is blocked until WAIT_ALLOW_WRITE_ACTIONS=true")
        try:
            execution = provider.execute_script(
                script_id, device_id, arguments, client_id=context.client_id
            )
        except Exception:
            return _failed("RMM script execution failed")
        return ActionResult(
            status="success" if execution.status in {"queued", "completed", "succeeded"} else "failed",
            output={**asdict(execution), "approved": True},
            evidence=[{"type": "rmm_script_execution", "script_id": script_id, "device_id": device_id}],
            error_detail="" if execution.status in {"queued", "completed", "succeeded"} else execution.message,
        )


class RmmScriptExecutionLookupAction:
    manifest = SmartActionManifest(
        action_id="rmm-script-execution-lookup",
        title="RMM script execution lookup",
        description="Track one approved RMM script execution through the provider adapter.",
        kind="deterministic",
        input_schema={"type": "object", "required": ["execution_id"]},
        output_schema={"execution_id": "string", "status": "string"},
        requires_approval=False,
        estimated_minutes_saved=2,
        risk_level="low",
        required_role="technician",
        access_mode="read",
    )

    def run(self, context: ActionContext, payload: dict[str, object]) -> ActionResult:
        execution_id = payload.get("execution_id")
        if not isinstance(execution_id, str) or not execution_id.strip() or len(execution_id) > 100:
            return _failed("execution_id must be a non-empty string of at most 100 characters")
        provider = context.rmm_provider or LocalCollectorRmmAdapter(context.store)
        try:
            execution = provider.get_execution(execution_id.strip(), client_id=context.client_id)
        except Exception:
            return _failed("RMM script execution lookup failed")
        return ActionResult(
            status="success" if execution.status in {"queued", "completed", "succeeded", "failed"} else "failed",
            output=asdict(execution),
            evidence=[{"type": "rmm_script_execution", "execution_id": execution_id.strip()}],
            error_detail="" if execution.status != "blocked" else execution.message,
        )


class ScreenConnectSessionNoteAction:
    manifest = SmartActionManifest(
        action_id="screenconnect-session-note",
        title="Add ScreenConnect session note",
        description="Preview and, after approval, add a bounded note to one mapped ScreenConnect session.",
        kind="deterministic",
        input_schema={
            "type": "object",
            "required": ["session_id", "note_body"],
            "properties": {
                "session_id": "string",
                "note_body": "string",
            },
        },
        output_schema={
            "session_id": "string",
            "operation": "string",
            "status": "string",
            "proposed_body": "string",
        },
        requires_approval=True,
        estimated_minutes_saved=2,
        risk_level="high",
        required_role="technician",
        access_mode="write",
    )

    def run(self, context: ActionContext, payload: dict[str, object]) -> ActionResult:
        provider = _screenconnect_session_provider(context)
        if isinstance(provider, ActionResult):
            return provider
        session_id = payload.get("session_id")
        note_body = payload.get("note_body")
        if not isinstance(session_id, str) or not isinstance(note_body, str):
            return _failed("session_id and note_body must be strings")
        try:
            if payload.get("_approval_completed"):
                if not context.settings.allow_write_actions:
                    return _failed(
                        "ScreenConnect session notes are blocked until WAIT_ALLOW_WRITE_ACTIONS=true"
                    )
                operation = provider.add_note(
                    session_id, note_body, client_id=context.client_id
                )
            else:
                operation = provider.preview_note(
                    session_id, note_body, client_id=context.client_id
                )
        except Exception as exc:
            return _failed(redact_text(str(exc)))
        output = {
            **asdict(operation),
            "proposed_body": note_body.strip(),
            "approval_required": not bool(payload.get("_approval_completed")),
            "approved": bool(payload.get("_approval_completed")),
        }
        return ActionResult(
            status="success",
            output=output,
            evidence=[
                {
                    "type": "screenconnect_session_mutation",
                    "operation": "add_note",
                    "session_id": operation.session_id,
                }
            ],
        )


class ScreenConnectSessionMessageAction:
    manifest = SmartActionManifest(
        action_id="screenconnect-session-message",
        title="Send ScreenConnect session message",
        description="Preview and, after approval, send a bounded message to one mapped ScreenConnect session.",
        kind="deterministic",
        input_schema={
            "type": "object",
            "required": ["session_id", "by_host", "message"],
            "properties": {
                "session_id": "string",
                "by_host": "string",
                "message": "string",
            },
        },
        output_schema={
            "session_id": "string",
            "operation": "string",
            "status": "string",
            "by_host": "string",
            "proposed_body": "string",
        },
        requires_approval=True,
        estimated_minutes_saved=2,
        risk_level="high",
        required_role="technician",
        access_mode="write",
    )

    def run(self, context: ActionContext, payload: dict[str, object]) -> ActionResult:
        provider = _screenconnect_session_provider(context)
        if isinstance(provider, ActionResult):
            return provider
        session_id = payload.get("session_id")
        by_host = payload.get("by_host")
        message = payload.get("message")
        if (
            not isinstance(session_id, str)
            or not isinstance(by_host, str)
            or not isinstance(message, str)
        ):
            return _failed("session_id, by_host, and message must be strings")
        try:
            if payload.get("_approval_completed"):
                if not context.settings.allow_write_actions:
                    return _failed(
                        "ScreenConnect session messages are blocked until WAIT_ALLOW_WRITE_ACTIONS=true"
                    )
                operation = provider.send_message(
                    session_id, by_host, message, client_id=context.client_id
                )
            else:
                operation = provider.preview_message(
                    session_id, by_host, message, client_id=context.client_id
                )
        except Exception as exc:
            return _failed(redact_text(str(exc)))
        output = {
            **asdict(operation),
            "proposed_body": message.strip(),
            "approval_required": not bool(payload.get("_approval_completed")),
            "approved": bool(payload.get("_approval_completed")),
        }
        return ActionResult(
            status="success",
            output=output,
            evidence=[
                {
                    "type": "screenconnect_session_mutation",
                    "operation": "send_message",
                    "session_id": operation.session_id,
                }
            ],
        )


def _screenconnect_session_provider(
    context: ActionContext,
) -> ScreenConnectRmmAdapter | ActionResult:
    provider = context.rmm_provider
    if not isinstance(provider, ScreenConnectRmmAdapter):
        return _failed(
            "ScreenConnect session operations require a configured ScreenConnect adapter"
        )
    return provider


class HaloPSATicketLookupAction:
    manifest = SmartActionManifest(
        action_id="halopsa-ticket-lookup",
        title="HaloPSA ticket lookup",
        description="Read one tenant-scoped ticket through the existing HaloPSA connector.",
        kind="deterministic",
        input_schema={"type": "object", "required": ["ticket_id"]},
        output_schema={"ticket": "object", "connector_status": "string"},
        requires_approval=False,
        estimated_minutes_saved=4,
        risk_level="low",
        required_role="technician",
        access_mode="read",
    )

    def run(self, context: ActionContext, payload: dict[str, object]) -> ActionResult:
        ticket = _ticket_from_payload(context.store, payload, context.client_id)
        if ticket is None:
            return _failed("ticket_id must identify an existing ticket in the tenant scope")
        from wait_local_agent.halopsa import HaloPSAClient

        provider = cast(
            HaloPSAReadProvider,
            context.halopsa_client or HaloPSAClient(context.settings),
        )
        try:
            response = provider.get_ticket(ticket.id)
        except Exception:
            return _failed("HaloPSA ticket lookup failed")
        result = getattr(response, "result", None)
        status = str(getattr(result, "status", "failed"))
        message = redact_text(str(getattr(result, "message", "HaloPSA read failed")))
        items = getattr(response, "items", [])
        if not isinstance(items, list):
            return _failed("HaloPSA returned malformed ticket data")
        if status != "ready":
            return ActionResult(
                status="failed",
                output={"ticket_id": ticket.id, "connector_status": status, "ticket": {}},
                error_detail=message,
            )
        normalized = [
            cast(dict[str, object], redact_value(asdict(item)))
            for item in items[:1]
            if hasattr(item, "__dataclass_fields__")
            and (
                context.client_id is None
                or not getattr(item, "client_id", "")
                or getattr(item, "client_id", "") == context.client_id
            )
        ]
        if not normalized:
            return ActionResult(
                status="failed",
                output={"ticket_id": ticket.id, "connector_status": "empty", "ticket": {}},
                error_detail="HaloPSA returned no matching ticket",
            )
        return ActionResult(
            status="success",
            output={
                "ticket_id": ticket.id,
                "connector_status": status,
                "ticket": normalized[0],
            },
            evidence=[
                {
                    "type": "connector_read",
                    "connector": "halopsa",
                    "operation": "tickets.get",
                    "ticket_id": ticket.id,
                }
            ],
        )


class HaloPSATicketWriteAction:
    def __init__(self, *, action_id: str, title: str, action_type: str) -> None:
        self.action_type = action_type
        self.manifest = SmartActionManifest(
            action_id=action_id,
            title=title,
            description=(
                f"Prepare an approval-gated HaloPSA {action_type} for one explicit "
                "tenant-scoped ticket."
            ),
            kind="deterministic",
            input_schema={
                "type": "object",
                "required": ["ticket_id", "fields"],
                "properties": {
                    "ticket_id": {"type": "string", "minLength": 1, "maxLength": 320},
                    "fields": {"type": "object", "minProperties": 1},
                },
            },
            output_schema={
                "operation": "string",
                "connector_status": "string",
                "ticket_id": "string",
                "action_type": "string",
                "status_code": "number",
                "remote_id": "string",
            },
            requires_approval=True,
            estimated_minutes_saved=3,
            risk_level="high",
            required_role="technician",
            access_mode="write",
        )

    def run(self, context: ActionContext, payload: dict[str, object]) -> ActionResult:
        if set(payload) - {"ticket_id", "fields", "_approval_completed"}:
            return _failed(f"HaloPSA {self.action_type} payload contains unsupported fields")
        ticket = _ticket_from_payload(context.store, payload, context.client_id)
        fields = payload.get("fields")
        if (
            ticket is None
            or not isinstance(fields, dict)
        ):
            return _failed("HaloPSA ticket write payload is invalid or outside tenant scope")
        ticket_id = ticket.id
        fields = dict(fields)
        try:
            from wait_local_agent.connectors import validate_halopsa_action_fields

            validate_halopsa_action_fields(self.action_type, fields)
        except (TypeError, ValueError) as exc:
            return _failed(redact_text(str(exc)))
        from wait_local_agent.halopsa import HaloPSAClient

        provider = cast(
            HaloPSAWriteProvider,
            context.halopsa_client or HaloPSAClient(context.settings),
        )
        try:
            health = provider.write_health()
        except Exception:
            return _failed("HaloPSA write readiness check failed")
        connector_status = str(getattr(health, "status", "failed"))
        connector_message = redact_text(
            str(getattr(health, "message", "HaloPSA writes are unavailable"))
        )
        output: dict[str, object] = {
            "operation": "ticket_write",
            "connector_status": connector_status,
            "ticket_id": ticket_id,
            "action_type": self.action_type,
        }
        evidence: list[dict[str, object]] = [
            {
                "type": "connector_write_preflight",
                "connector": "halopsa",
                "operation": self.action_type,
                "client_id": context.client_id,
                "ticket_id": ticket_id,
                "field_names": sorted(str(name) for name in fields),
            }
        ]
        if connector_status != "ready":
            return ActionResult(
                status="failed",
                output=output,
                evidence=evidence,
                error_detail=connector_message,
            )
        if not payload.get("_approval_completed"):
            return ActionResult(
                status="success",
                output={**output, "approval_required": True},
                evidence=evidence,
            )
        try:
            result = provider.execute_write(
                HaloWriteRequest(
                    ticket_id=ticket_id,
                    action_type=self.action_type,
                    fields=fields,
                )
            )
        except Exception:
            return ActionResult(
                status="failed",
                output=output,
                evidence=evidence,
                error_detail=f"HaloPSA {self.action_type} failed",
            )
        result_output = {
            **output,
            "status_code": getattr(result, "status_code", None),
            "remote_id": getattr(result, "remote_id", ""),
        }
        if str(getattr(result, "status", "failed")) != "succeeded":
            return ActionResult(
                status="failed",
                output=result_output,
                evidence=evidence,
                error_detail=redact_text(
                    str(getattr(result, "message", f"HaloPSA {self.action_type} failed"))
                ),
            )
        return ActionResult(
            status="success",
            output={**result_output, "approved": True},
            evidence=evidence,
        )


class ConnectWiseTicketWriteAction:
    def __init__(self, *, action_id: str, title: str, action_type: str) -> None:
        self.action_type = action_type
        self.manifest = SmartActionManifest(
            action_id=action_id,
            title=title,
            description=(
                f"Prepare an approval-gated ConnectWise PSA {action_type} for one "
                "explicit tenant-scoped ticket."
            ),
            kind="deterministic",
            input_schema={
                "type": "object",
                "required": ["ticket_id", "fields"],
                "properties": {
                    "ticket_id": {"type": "string", "minLength": 1, "maxLength": 320},
                    "fields": {"type": "object", "minProperties": 1},
                },
            },
            output_schema={
                "operation": "string",
                "connector_status": "string",
                "ticket_id": "string",
                "action_type": "string",
                "status_code": "number",
                "remote_id": "string",
            },
            requires_approval=True,
            estimated_minutes_saved=3,
            risk_level="high",
            required_role="technician",
            access_mode="write",
        )

    def run(self, context: ActionContext, payload: dict[str, object]) -> ActionResult:
        if set(payload) - {"ticket_id", "fields", "_approval_completed"}:
            return _failed(f"ConnectWise {self.action_type} payload contains unsupported fields")
        ticket = _ticket_from_payload(context.store, payload, context.client_id)
        fields = payload.get("fields")
        if (
            ticket is None
            or not isinstance(fields, dict)
        ):
            return _failed("ConnectWise ticket write payload is invalid or outside tenant scope")
        ticket_id = ticket.id
        fields = dict(fields)
        try:
            from wait_local_agent.connectors import validate_connectwise_action_fields

            validate_connectwise_action_fields(self.action_type, fields)
        except (TypeError, ValueError) as exc:
            return _failed(redact_text(str(exc)))
        from wait_local_agent.connectwise import ConnectWiseClient

        provider = cast(
            ConnectWiseWriteProvider,
            context.connectwise_client or ConnectWiseClient(context.settings),
        )
        try:
            health = provider.write_health()
        except Exception:
            return _failed("ConnectWise write readiness check failed")
        connector_status = str(getattr(health, "status", "failed"))
        connector_message = redact_text(
            str(getattr(health, "message", "ConnectWise writes are unavailable"))
        )
        output: dict[str, object] = {
            "operation": "ticket_write",
            "connector_status": connector_status,
            "ticket_id": ticket_id,
            "action_type": self.action_type,
        }
        evidence: list[dict[str, object]] = [
            {
                "type": "connector_write_preflight",
                "connector": "connectwise",
                "operation": self.action_type,
                "client_id": context.client_id,
                "ticket_id": ticket_id,
                "field_names": sorted(str(name) for name in fields),
            }
        ]
        if connector_status != "ready":
            return ActionResult(
                status="failed",
                output=output,
                evidence=evidence,
                error_detail=connector_message,
            )
        if not payload.get("_approval_completed"):
            return ActionResult(
                status="success",
                output={**output, "approval_required": True},
                evidence=evidence,
            )
        try:
            result = provider.execute_write(
                ConnectWiseWriteRequest(
                    ticket_id=ticket_id,
                    action_type=self.action_type,
                    fields=fields,
                )
            )
        except Exception:
            return ActionResult(
                status="failed",
                output=output,
                evidence=evidence,
                error_detail=f"ConnectWise {self.action_type} failed",
            )
        result_output = {
            **output,
            "status_code": getattr(result, "status_code", None),
            "remote_id": getattr(result, "remote_id", ""),
        }
        if str(getattr(result, "status", "failed")) != "succeeded":
            return ActionResult(
                status="failed",
                output=result_output,
                evidence=evidence,
                error_detail=redact_text(
                    str(getattr(result, "message", f"ConnectWise {self.action_type} failed"))
                ),
            )
        return ActionResult(
            status="success",
            output={**result_output, "approved": True},
            evidence=evidence,
        )


class ConnectWiseTicketLookupAction:
    manifest = SmartActionManifest(
        action_id="connectwise-ticket-lookup",
        title="ConnectWise PSA ticket lookup",
        description="Read one tenant-scoped local ticket through the guarded ConnectWise PSA connector.",
        kind="deterministic",
        input_schema={"type": "object", "required": ["ticket_id"]},
        output_schema={"ticket": "object", "connector_status": "string"},
        requires_approval=False,
        estimated_minutes_saved=4,
        risk_level="low",
        required_role="technician",
        access_mode="read",
    )

    def run(self, context: ActionContext, payload: dict[str, object]) -> ActionResult:
        ticket = _ticket_from_payload(context.store, payload, context.client_id)
        if ticket is None:
            return _failed("ticket_id must identify an existing ticket in the tenant scope")
        from wait_local_agent.connectwise import ConnectWiseClient

        provider = cast(
            ConnectWiseReadProvider,
            context.connectwise_client or ConnectWiseClient(context.settings),
        )
        try:
            response = provider.get_ticket(ticket.id)
        except Exception:
            return _failed("ConnectWise PSA ticket lookup failed")
        result = getattr(response, "result", None)
        status = str(getattr(result, "status", "failed"))
        message = redact_text(str(getattr(result, "message", "ConnectWise PSA read failed")))
        items = getattr(response, "items", [])
        if not isinstance(items, list):
            return _failed("ConnectWise PSA returned malformed ticket data")
        if status != "ready":
            return ActionResult(
                status="failed",
                output={"ticket_id": ticket.id, "connector_status": status, "ticket": {}},
                error_detail=message,
            )
        if not items or not isinstance(items[0], dict):
            return ActionResult(
                status="failed",
                output={"ticket_id": ticket.id, "connector_status": "empty", "ticket": {}},
                error_detail="ConnectWise PSA returned no matching ticket",
            )
        normalized = cast(dict[str, object], redact_value(items[0]))
        return ActionResult(
            status="success",
            output={
                "ticket_id": ticket.id,
                "connector_status": status,
                "ticket": normalized,
            },
            evidence=[
                {
                    "type": "connector_read",
                    "connector": "connectwise",
                    "operation": "tickets.get",
                    "ticket_id": ticket.id,
                }
            ],
        )


class SyncroTicketLookupAction:
    manifest = SmartActionManifest(
        action_id="syncro-ticket-lookup",
        title="Syncro ticket lookup",
        description="Read one tenant-scoped ticket through the existing Syncro connector.",
        kind="deterministic",
        input_schema={"type": "object", "required": ["ticket_id"]},
        output_schema={"ticket": "object", "connector_status": "string"},
        requires_approval=False,
        estimated_minutes_saved=4,
        risk_level="low",
        required_role="technician",
        access_mode="read",
    )

    def run(self, context: ActionContext, payload: dict[str, object]) -> ActionResult:
        from wait_local_agent.syncro import SyncroClient

        provider = cast(
            SyncroReadProvider,
            context.syncro_client or SyncroClient(context.settings),
        )
        return _run_psa_ticket_lookup(
            context,
            payload,
            provider.get_ticket,
            connector="syncro",
            operation="tickets.get",
            failure_message="Syncro ticket lookup failed",
            malformed_message="Syncro returned malformed ticket data",
            empty_message="Syncro returned no matching ticket",
        )


class SyncroTicketCommentsAction:
    manifest = SmartActionManifest(
        action_id="syncro-ticket-comments",
        title="Syncro ticket comments",
        description="Read a bounded tenant-scoped Syncro ticket comment history.",
        kind="deterministic",
        input_schema={
            "type": "object",
            "required": ["ticket_id"],
            "properties": {
                "ticket_id": {"type": "string", "pattern": "^[1-9][0-9]{0,18}$"},
                "page": {"type": "integer", "minimum": 1},
                "limit": {"type": "integer", "minimum": 1, "maximum": 50},
            },
        },
        output_schema={
            "ticket_id": "string",
            "comments": "array",
            "count": "integer",
            "meta": "object",
            "connector_status": "string",
        },
        requires_approval=False,
        estimated_minutes_saved=4,
        risk_level="low",
        required_role="technician",
        access_mode="read",
    )

    def run(self, context: ActionContext, payload: dict[str, object]) -> ActionResult:
        ticket = _ticket_from_payload(context.store, payload, context.client_id)
        if ticket is None:
            return _failed("Syncro ticket comments require a tenant-scoped local ticket")
        page = payload.get("page", 1)
        limit = payload.get("limit", 20)
        if not isinstance(page, int) or isinstance(page, bool) or page < 1:
            return _failed("page must be a positive integer")
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1 or limit > 50:
            return _failed("limit must be an integer between 1 and 50")
        from wait_local_agent.syncro import SyncroClient

        provider = cast(
            SyncroReadProvider,
            context.syncro_client or SyncroClient(context.settings),
        )
        try:
            response = provider.list_ticket_comments(
                ticket.id,
                page=page,
                per_page=limit,
            )
        except Exception:
            return _failed("Syncro ticket comments lookup failed")
        result = getattr(response, "result", None)
        status = str(getattr(result, "status", "failed"))
        message = redact_text(str(getattr(result, "message", "Syncro ticket comments read failed")))
        items = getattr(response, "items", [])
        meta = getattr(response, "meta", {})
        if not isinstance(items, list) or not isinstance(meta, dict):
            return _failed("Syncro returned malformed ticket comments")
        comments = [
            cast(dict[str, object], redact_value(item))
            for item in items[:limit]
            if isinstance(item, dict)
        ]
        if status != "ready":
            return ActionResult(
                status="failed",
                output={
                    "ticket_id": ticket.id,
                    "comments": [],
                    "count": 0,
                    "meta": {},
                    "connector_status": status,
                },
                error_detail=message,
            )
        return ActionResult(
            status="success",
            output={
                "ticket_id": ticket.id,
                "comments": comments,
                "count": len(comments),
                "meta": redact_value(meta),
                "connector_status": status,
            },
            evidence=[
                {
                    "type": "connector_read",
                    "connector": "syncro",
                    "operation": "tickets.comments",
                    "ticket_id": ticket.id,
                }
            ],
        )


class SyncroTicketWriteAction:
    def __init__(self, *, action_id: str, title: str, action_type: str) -> None:
        self.action_type = action_type
        self.manifest = SmartActionManifest(
            action_id=action_id,
            title=title,
            description=(
                f"Prepare an approval-gated Syncro {action_type} for one "
                "explicit tenant-scoped ticket."
            ),
            kind="deterministic",
            input_schema={
                "type": "object",
                "required": ["ticket_id", "fields"],
                "properties": {
                    "ticket_id": {
                        "type": "string",
                        "pattern": "^[1-9][0-9]{0,18}$",
                        "minLength": 1,
                        "maxLength": 19,
                    },
                    "fields": {"type": "object", "minProperties": 1},
                },
            },
            output_schema={
                "operation": "string",
                "connector_status": "string",
                "ticket_id": "string",
                "action_type": "string",
                "status_code": "number",
                "remote_id": "string",
            },
            requires_approval=True,
            estimated_minutes_saved=3,
            risk_level="high",
            required_role="technician",
            access_mode="write",
        )

    def run(self, context: ActionContext, payload: dict[str, object]) -> ActionResult:
        if set(payload) - {"ticket_id", "fields", "_approval_completed"}:
            return _failed(f"Syncro {self.action_type} payload contains unsupported fields")
        ticket = _ticket_from_payload(context.store, payload, context.client_id)
        fields = payload.get("fields")
        if ticket is None or not isinstance(fields, dict):
            return _failed("Syncro ticket write payload is invalid or outside tenant scope")
        fields = dict(fields)
        try:
            from wait_local_agent.connectors import validate_syncro_action_fields

            validate_syncro_action_fields(self.action_type, fields)
        except (TypeError, ValueError) as exc:
            return _failed(redact_text(str(exc)))
        from wait_local_agent.syncro import SyncroClient

        provider = cast(
            SyncroWriteProvider,
            context.syncro_client or SyncroClient(context.settings),
        )
        try:
            health = provider.write_health()
        except Exception:
            return _failed("Syncro write readiness check failed")
        connector_status = str(getattr(health, "status", "failed"))
        connector_message = redact_text(
            str(getattr(health, "message", "Syncro writes are unavailable"))
        )
        output: dict[str, object] = {
            "operation": "ticket_write",
            "connector_status": connector_status,
            "ticket_id": ticket.id,
            "action_type": self.action_type,
        }
        evidence: list[dict[str, object]] = [
            {
                "type": "connector_write_preflight",
                "connector": "syncro",
                "operation": self.action_type,
                "client_id": context.client_id,
                "ticket_id": ticket.id,
                "field_names": sorted(str(name) for name in fields),
            }
        ]
        if connector_status != "ready":
            return ActionResult(
                status="failed",
                output=output,
                evidence=evidence,
                error_detail=connector_message,
            )
        if not payload.get("_approval_completed"):
            return ActionResult(
                status="success",
                output={**output, "approval_required": True},
                evidence=evidence,
            )
        try:
            result = provider.execute_write(
                SyncroWriteRequest(
                    ticket_id=ticket.id,
                    action_type=self.action_type,
                    fields=fields,
                )
            )
        except Exception:
            return ActionResult(
                status="failed",
                output=output,
                evidence=evidence,
                error_detail=f"Syncro {self.action_type} failed",
            )
        result_output = {
            **output,
            "status_code": getattr(result, "status_code", None),
            "remote_id": getattr(result, "remote_id", ""),
        }
        if str(getattr(result, "status", "failed")) != "succeeded":
            return ActionResult(
                status="failed",
                output=result_output,
                evidence=evidence,
                error_detail=redact_text(
                    str(getattr(result, "message", f"Syncro {self.action_type} failed"))
                ),
            )
        return ActionResult(
            status="success",
            output={**result_output, "approved": True},
            evidence=evidence,
        )


class ServiceNowIncidentLookupAction:
    manifest = SmartActionManifest(
        action_id="servicenow-incident-lookup",
        title="ServiceNow incident lookup",
        description="Read one tenant-scoped incident through the existing ServiceNow connector.",
        kind="deterministic",
        input_schema={"type": "object", "required": ["ticket_id"]},
        output_schema={"ticket": "object", "connector_status": "string"},
        requires_approval=False,
        estimated_minutes_saved=4,
        risk_level="low",
        required_role="technician",
        access_mode="read",
    )

    def run(self, context: ActionContext, payload: dict[str, object]) -> ActionResult:
        from wait_local_agent.servicenow import ServiceNowClient

        provider = cast(
            ServiceNowReadProvider,
            context.servicenow_client or ServiceNowClient(context.settings),
        )
        return _run_psa_ticket_lookup(
            context,
            payload,
            provider.get_incident,
            connector="servicenow",
            operation="incidents.get",
            failure_message="ServiceNow incident lookup failed",
            malformed_message="ServiceNow returned malformed incident data",
            empty_message="ServiceNow returned no matching incident",
        )


class ServiceNowIncidentWriteAction:
    def __init__(self, *, action_id: str, title: str, action_type: str) -> None:
        self.action_type = action_type
        self.manifest = SmartActionManifest(
            action_id=action_id,
            title=title,
            description=(
                f"Prepare an approval-gated ServiceNow {action_type} for one "
                "explicit tenant-scoped incident."
            ),
            kind="deterministic",
            input_schema={
                "type": "object",
                "required": ["ticket_id", "fields"],
                "properties": {
                    "ticket_id": {"type": "string", "minLength": 1, "maxLength": 64},
                    "fields": {"type": "object", "minProperties": 1},
                },
            },
            output_schema={
                "operation": "string",
                "connector_status": "string",
                "ticket_id": "string",
                "action_type": "string",
                "status_code": "number",
                "remote_id": "string",
            },
            requires_approval=True,
            estimated_minutes_saved=3,
            risk_level="high",
            required_role="technician",
            access_mode="write",
        )

    def run(self, context: ActionContext, payload: dict[str, object]) -> ActionResult:
        if set(payload) - {"ticket_id", "fields", "_approval_completed"}:
            return _failed(f"ServiceNow {self.action_type} payload contains unsupported fields")
        ticket = _ticket_from_payload(context.store, payload, context.client_id)
        fields = payload.get("fields")
        if ticket is None or not isinstance(fields, dict):
            return _failed("ServiceNow incident write payload is invalid or outside tenant scope")
        fields = dict(fields)
        try:
            from wait_local_agent.connectors import validate_servicenow_action_fields

            validate_servicenow_action_fields(self.action_type, fields)
        except (TypeError, ValueError) as exc:
            return _failed(redact_text(str(exc)))
        from wait_local_agent.servicenow import ServiceNowClient

        provider = cast(
            ServiceNowWriteProvider,
            context.servicenow_client or ServiceNowClient(context.settings),
        )
        try:
            health = provider.write_health()
        except Exception:
            return _failed("ServiceNow write readiness check failed")
        connector_status = str(getattr(health, "status", "failed"))
        connector_message = redact_text(
            str(getattr(health, "message", "ServiceNow writes are unavailable"))
        )
        output: dict[str, object] = {
            "operation": "incident_write",
            "connector_status": connector_status,
            "ticket_id": ticket.id,
            "action_type": self.action_type,
        }
        evidence: list[dict[str, object]] = [
            {
                "type": "connector_write_preflight",
                "connector": "servicenow",
                "operation": self.action_type,
                "client_id": context.client_id,
                "ticket_id": ticket.id,
                "field_names": sorted(str(name) for name in fields),
            }
        ]
        if connector_status != "ready":
            return ActionResult(
                status="failed",
                output=output,
                evidence=evidence,
                error_detail=connector_message,
            )
        if not payload.get("_approval_completed"):
            return ActionResult(
                status="success",
                output={**output, "approval_required": True},
                evidence=evidence,
            )
        try:
            result = provider.execute_write(
                ServiceNowWriteRequest(
                    ticket_id=ticket.id,
                    action_type=self.action_type,
                    fields=fields,
                )
            )
        except Exception:
            return ActionResult(
                status="failed",
                output=output,
                evidence=evidence,
                error_detail=f"ServiceNow {self.action_type} failed",
            )
        result_output = {
            **output,
            "status_code": getattr(result, "status_code", None),
            "remote_id": getattr(result, "remote_id", ""),
        }
        if str(getattr(result, "status", "failed")) != "succeeded":
            return ActionResult(
                status="failed",
                output=result_output,
                evidence=evidence,
                error_detail=redact_text(
                    str(getattr(result, "message", f"ServiceNow {self.action_type} failed"))
                ),
            )
        return ActionResult(
            status="success",
            output={**result_output, "approved": True},
            evidence=evidence,
        )


class AutotaskTicketLookupAction:
    manifest = SmartActionManifest(
        action_id="autotask-ticket-lookup",
        title="Autotask ticket lookup",
        description="Read one tenant-scoped ticket through the existing Autotask connector.",
        kind="deterministic",
        input_schema={"type": "object", "required": ["ticket_id"]},
        output_schema={"ticket": "object", "connector_status": "string"},
        requires_approval=False,
        estimated_minutes_saved=4,
        risk_level="low",
        required_role="technician",
        access_mode="read",
    )

    def run(self, context: ActionContext, payload: dict[str, object]) -> ActionResult:
        from wait_local_agent.autotask import AutotaskClient

        provider = cast(
            AutotaskReadProvider,
            context.autotask_client or AutotaskClient(context.settings),
        )
        return _run_psa_ticket_lookup(
            context,
            payload,
            provider.get_ticket,
            connector="autotask",
            operation="tickets.get",
            failure_message="Autotask ticket lookup failed",
            malformed_message="Autotask returned malformed ticket data",
            empty_message="Autotask returned no matching ticket",
        )


class AutotaskTicketWriteAction:
    def __init__(self, *, action_id: str, title: str, action_type: str) -> None:
        self.action_type = action_type
        self.manifest = SmartActionManifest(
            action_id=action_id,
            title=title,
            description=(
                f"Prepare an approval-gated Autotask {action_type} for one "
                "explicit tenant-scoped ticket."
            ),
            kind="deterministic",
            input_schema={
                "type": "object",
                "required": ["ticket_id", "fields"],
                "properties": {
                    "ticket_id": {
                        "type": "string",
                        "pattern": "^[1-9][0-9]{0,18}$",
                        "minLength": 1,
                        "maxLength": 19,
                    },
                    "fields": {"type": "object", "minProperties": 1},
                },
            },
            output_schema={
                "operation": "string",
                "connector_status": "string",
                "ticket_id": "string",
                "action_type": "string",
                "status_code": "number",
                "remote_id": "string",
            },
            requires_approval=True,
            estimated_minutes_saved=3,
            risk_level="high",
            required_role="technician",
            access_mode="write",
        )

    def run(self, context: ActionContext, payload: dict[str, object]) -> ActionResult:
        if set(payload) - {"ticket_id", "fields", "_approval_completed"}:
            return _failed(f"Autotask {self.action_type} payload contains unsupported fields")
        ticket = _ticket_from_payload(context.store, payload, context.client_id)
        fields = payload.get("fields")
        if ticket is None or not isinstance(fields, dict):
            return _failed("Autotask ticket write payload is invalid or outside tenant scope")
        fields = dict(fields)
        try:
            from wait_local_agent.connectors import validate_autotask_action_fields

            validate_autotask_action_fields(self.action_type, fields)
        except (TypeError, ValueError) as exc:
            return _failed(redact_text(str(exc)))
        from wait_local_agent.autotask import AutotaskClient

        provider = cast(
            AutotaskWriteProvider,
            context.autotask_client or AutotaskClient(context.settings),
        )
        try:
            health = provider.write_health()
        except Exception:
            return _failed("Autotask write readiness check failed")
        connector_status = str(getattr(health, "status", "failed"))
        connector_message = redact_text(
            str(getattr(health, "message", "Autotask writes are unavailable"))
        )
        output: dict[str, object] = {
            "operation": "ticket_write",
            "connector_status": connector_status,
            "ticket_id": ticket.id,
            "action_type": self.action_type,
        }
        evidence: list[dict[str, object]] = [
            {
                "type": "connector_write_preflight",
                "connector": "autotask",
                "operation": self.action_type,
                "client_id": context.client_id,
                "ticket_id": ticket.id,
                "field_names": sorted(str(name) for name in fields),
            }
        ]
        if connector_status != "ready":
            return ActionResult(
                status="failed",
                output=output,
                evidence=evidence,
                error_detail=connector_message,
            )
        if not payload.get("_approval_completed"):
            return ActionResult(
                status="success",
                output={**output, "approval_required": True},
                evidence=evidence,
            )
        try:
            result = provider.execute_write(
                AutotaskWriteRequest(
                    ticket_id=ticket.id,
                    action_type=self.action_type,
                    fields=fields,
                )
            )
        except Exception:
            return ActionResult(
                status="failed",
                output=output,
                evidence=evidence,
                error_detail=f"Autotask {self.action_type} failed",
            )
        result_output = {
            **output,
            "status_code": getattr(result, "status_code", None),
            "remote_id": getattr(result, "remote_id", ""),
        }
        if str(getattr(result, "status", "failed")) != "succeeded":
            return ActionResult(
                status="failed",
                output=result_output,
                evidence=evidence,
                error_detail=redact_text(
                    str(getattr(result, "message", f"Autotask {self.action_type} failed"))
                ),
            )
        return ActionResult(
            status="success",
            output={**result_output, "approved": True},
            evidence=evidence,
        )


def _run_psa_ticket_lookup(
    context: ActionContext,
    payload: dict[str, object],
    lookup: object,
    *,
    connector: str,
    operation: str,
    failure_message: str,
    malformed_message: str,
    empty_message: str,
) -> ActionResult:
    ticket = _ticket_from_payload(context.store, payload, context.client_id)
    if ticket is None:
        return _failed("ticket_id must identify an existing ticket in the tenant scope")
    if not callable(lookup):
        return _failed(failure_message)
    try:
        response = lookup(ticket.id)
    except Exception:
        return _failed(failure_message)
    result = getattr(response, "result", None)
    status = str(getattr(result, "status", "failed"))
    message = redact_text(str(getattr(result, "message", f"{connector} read failed")))
    items = getattr(response, "items", [])
    if not isinstance(items, list):
        return _failed(malformed_message)
    if status != "ready":
        return ActionResult(
            status="failed",
            output={"ticket_id": ticket.id, "connector_status": status, "ticket": {}},
            error_detail=message,
        )
    if not items or not isinstance(items[0], dict):
        return ActionResult(
            status="failed",
            output={"ticket_id": ticket.id, "connector_status": "empty", "ticket": {}},
            error_detail=empty_message,
        )
    raw_record = items[0]
    returned_id = raw_record.get("id", raw_record.get("sys_id"))
    if returned_id not in (None, "") and str(returned_id) != ticket.id:
        return ActionResult(
            status="failed",
            output={"ticket_id": ticket.id, "connector_status": "scope_mismatch", "ticket": {}},
            error_detail="PSA returned a record outside the requested ticket scope",
        )
    normalized = cast(dict[str, object], redact_value(raw_record))
    return ActionResult(
        status="success",
        output={
            "ticket_id": ticket.id,
            "connector_status": status,
            "ticket": normalized,
        },
        evidence=[
            {
                "type": "connector_read",
                "connector": connector,
                "operation": operation,
                "ticket_id": ticket.id,
            }
        ],
    )


class HuduDocumentationSearchAction:
    manifest = SmartActionManifest(
        action_id="hudu-documentation-search",
        title="Hudu documentation search",
        description=(
            "Search tenant-scoped Hudu article titles and bounded content "
            "through the existing read-only connector."
        ),
        kind="deterministic",
        input_schema={
            "type": "object",
            "required": ["query", "company_id"],
            "properties": {
                "query": {"type": "string", "minLength": 1, "maxLength": 200},
                "company_id": {"type": "string", "minLength": 1, "maxLength": 120},
                "limit": {"type": "integer", "minimum": 1, "maximum": 50},
            },
        },
        output_schema={"articles": "array", "count": "integer", "connector_status": "string"},
        requires_approval=False,
        estimated_minutes_saved=5,
        risk_level="low",
        required_role="technician",
        access_mode="read",
    )

    def run(self, context: ActionContext, payload: dict[str, object]) -> ActionResult:
        query = payload.get("query")
        company_id = payload.get("company_id")
        if not isinstance(query, str) or not query.strip() or len(query.strip()) > 200:
            return _failed("query must be a non-empty string of at most 200 characters")
        if not isinstance(company_id, str) or not company_id.strip() or len(company_id.strip()) > 120:
            return _failed("company_id must be a non-empty string of at most 120 characters")
        if context.client_id is not None and company_id.strip() != context.client_id:
            return _failed("company_id is outside the tenant scope")
        limit = payload.get("limit", 20)
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1 or limit > 50:
            return _failed("limit must be an integer between 1 and 50")
        from wait_local_agent.hudu import HuduClient

        provider = context.hudu_client or HuduClient(context.settings)
        try:
            response = provider.list_articles(company_id=company_id.strip(), page=1, page_size=limit)
        except Exception:
            return _failed("Hudu documentation lookup failed")
        result = getattr(response, "result", None)
        status = str(getattr(result, "status", "failed"))
        message = redact_text(str(getattr(result, "message", "Hudu read failed")))
        items = getattr(response, "items", [])
        if not isinstance(items, list):
            return _failed("Hudu returned malformed article data")
        if status != "ready":
            return ActionResult(
                status="failed",
                output={"company_id": company_id.strip(), "connector_status": status, "articles": []},
                error_detail=message,
            )
        query_value = query.strip().casefold()
        articles = [
            cast(dict[str, object], redact_value(asdict(item)))
            for item in items
            if hasattr(item, "__dataclass_fields__")
            and (
                context.client_id is None
                or not getattr(item, "company_id", "")
                or getattr(item, "company_id", "") == context.client_id
            )
            and (
                query_value in str(getattr(item, "name", "")).casefold()
                or query_value in str(getattr(item, "content", "")).casefold()
            )
        ][:limit]
        return ActionResult(
            status="success",
            output={
                "company_id": company_id.strip(),
                "connector_status": status,
                "articles": articles,
                "count": len(articles),
            },
            evidence=[
                {
                    "type": "connector_read",
                    "connector": "hudu",
                    "operation": "articles.list",
                    "company_id": company_id.strip(),
                }
            ],
        )


class ItGlueDocumentationSearchAction:
    manifest = SmartActionManifest(
        action_id="itglue-documentation-search",
        title="IT Glue documentation search",
        description=(
            "Search tenant-scoped IT Glue document names and bounded text/step content "
            "through the existing read-only connector."
        ),
        kind="deterministic",
        input_schema={
            "type": "object",
            "required": ["query", "organization_id"],
            "properties": {
                "query": {"type": "string", "minLength": 1, "maxLength": 200},
                "organization_id": {"type": "string", "minLength": 1, "maxLength": 64},
                "folder_id": {"type": "string", "minLength": 1, "maxLength": 64},
                "limit": {"type": "integer", "minimum": 1, "maximum": 50},
            },
        },
        output_schema={"documents": "array", "count": "integer", "connector_status": "string"},
        requires_approval=False,
        estimated_minutes_saved=5,
        risk_level="low",
        required_role="technician",
        access_mode="read",
    )

    def run(self, context: ActionContext, payload: dict[str, object]) -> ActionResult:
        query = payload.get("query")
        organization_id = payload.get("organization_id")
        if not isinstance(query, str) or not query.strip() or len(query.strip()) > 200:
            return _failed("query must be a non-empty string of at most 200 characters")
        if (
            not isinstance(organization_id, str)
            or not organization_id.strip()
            or len(organization_id.strip()) > 64
        ):
            return _failed("organization_id must be a non-empty string of at most 64 characters")
        scoped_organization_id = organization_id.strip()
        if context.client_id is not None and scoped_organization_id != context.client_id:
            return _failed("organization_id is outside the tenant scope")
        limit = payload.get("limit", 20)
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1 or limit > 50:
            return _failed("limit must be an integer between 1 and 50")
        folder_id = payload.get("folder_id")
        if folder_id is not None and (
            not isinstance(folder_id, str) or not folder_id.strip() or len(folder_id.strip()) > 64
        ):
            return _failed("folder_id must be a non-empty string of at most 64 characters")
        from wait_local_agent.itglue import ItGlueClient

        provider = context.itglue_client or ItGlueClient(context.settings)
        try:
            search_documents = getattr(provider, "search_documents", None)
            if callable(search_documents):
                response = search_documents(
                    scoped_organization_id,
                    query.strip(),
                    folder_id=folder_id.strip() if isinstance(folder_id, str) else None,
                    limit=limit,
                )
            else:
                response = provider.list_documents(
                    scoped_organization_id,
                    folder_id=folder_id.strip() if isinstance(folder_id, str) else None,
                    page=1,
                    page_size=limit,
                )
        except Exception:
            return _failed("IT Glue documentation lookup failed")
        result = getattr(response, "result", None)
        status = str(getattr(result, "status", "failed"))
        message = redact_text(str(getattr(result, "message", "IT Glue read failed")))
        items = getattr(response, "items", [])
        if not isinstance(items, list):
            return _failed("IT Glue returned malformed document data")
        if status != "ready":
            return ActionResult(
                status="failed",
                output={
                    "organization_id": scoped_organization_id,
                    "connector_status": status,
                    "documents": [],
                    "count": 0,
                },
                error_detail=message,
            )
        query_value = query.strip().casefold()
        documents = [
            cast(dict[str, object], redact_value(asdict(item)))
            for item in items
            if hasattr(item, "__dataclass_fields__")
            and (
                not getattr(item, "organization_id", "")
                or getattr(item, "organization_id", "") == scoped_organization_id
            )
            and (
                query_value in str(getattr(item, "name", "")).casefold()
                or query_value in str(getattr(item, "content", "")).casefold()
            )
        ][:limit]
        return ActionResult(
            status="success",
            output={
                "organization_id": scoped_organization_id,
                "connector_status": status,
                "documents": documents,
                "count": len(documents),
            },
            evidence=[
                {
                    "type": "connector_read",
                    "connector": "itglue",
                    "operation": "documents.list",
                    "organization_id": scoped_organization_id,
                }
            ],
        )


class ConfluenceDocumentationSearchAction:
    manifest = SmartActionManifest(
        action_id="confluence-documentation-search",
        title="Confluence documentation search",
        description=(
            "Search tenant-scoped Confluence page titles and bounded body content "
            "through the existing read-only connector."
        ),
        kind="deterministic",
        input_schema={
            "type": "object",
            "required": ["query", "space_id"],
            "properties": {
                "query": {"type": "string", "minLength": 1, "maxLength": 200},
                "space_id": {"type": "string", "minLength": 1, "maxLength": 64},
                "limit": {"type": "integer", "minimum": 1, "maximum": 50},
            },
        },
        output_schema={"pages": "array", "count": "integer", "connector_status": "string"},
        requires_approval=False,
        estimated_minutes_saved=5,
        risk_level="low",
        required_role="technician",
        access_mode="read",
    )

    def run(self, context: ActionContext, payload: dict[str, object]) -> ActionResult:
        query = payload.get("query")
        space_id = payload.get("space_id")
        if not isinstance(query, str) or not query.strip() or len(query.strip()) > 200:
            return _failed("query must be a non-empty string of at most 200 characters")
        if not isinstance(space_id, str) or not space_id.strip() or len(space_id.strip()) > 64:
            return _failed("space_id must be a non-empty string of at most 64 characters")
        scoped_space_id = space_id.strip()
        if context.client_id is not None and scoped_space_id != context.client_id:
            return _failed("space_id is outside the tenant scope")
        limit = payload.get("limit", 20)
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1 or limit > 50:
            return _failed("limit must be an integer between 1 and 50")
        from wait_local_agent.confluence import ConfluenceClient

        provider = context.confluence_client or ConfluenceClient(context.settings)
        try:
            response = provider.list_pages(space_id=scoped_space_id, page_size=limit)
        except Exception:
            return _failed("Confluence documentation lookup failed")
        result = getattr(response, "result", None)
        status = str(getattr(result, "status", "failed"))
        message = redact_text(str(getattr(result, "message", "Confluence read failed")))
        items = getattr(response, "items", [])
        if not isinstance(items, list):
            return _failed("Confluence returned malformed page data")
        if status != "ready":
            return ActionResult(
                status="failed",
                output={"space_id": scoped_space_id, "connector_status": status, "pages": [], "count": 0},
                error_detail=message,
            )
        query_value = query.strip().casefold()
        pages = [
            {
                "id": str(getattr(item, "id", "")),
                "title": str(getattr(item, "title", "")),
                "space_id": str(getattr(item, "space_id", "")),
                "status": str(getattr(item, "status", "")),
                "version": str(getattr(item, "version", "")),
                "updated_at": str(getattr(item, "updated_at", "")),
                "url": str(getattr(item, "url", "")),
                "body": str(getattr(item, "body", "")),
            }
            for item in items
            if hasattr(item, "__dataclass_fields__")
            and str(getattr(item, "space_id", "")) in {"", scoped_space_id}
            and (
                query_value in str(getattr(item, "title", "")).casefold()
                or query_value in str(getattr(item, "body", "")).casefold()
            )
        ][:limit]
        return ActionResult(
            status="success",
            output={
                "space_id": scoped_space_id,
                "connector_status": status,
                "pages": cast(list[dict[str, object]], redact_value(pages)),
                "count": len(pages),
            },
            evidence=[
                {
                    "type": "connector_read",
                    "connector": "confluence",
                    "operation": "pages.list",
                    "space_id": scoped_space_id,
                }
            ],
        )


class NotionDocumentationSearchAction:
    manifest = SmartActionManifest(
        action_id="notion-documentation-search",
        title="Notion documentation search",
        description=(
            "Search tenant-scoped Notion page titles and retrieve bounded page "
            "markdown through the existing read-only connector."
        ),
        kind="deterministic",
        input_schema={
            "type": "object",
            "required": ["query", "client_id"],
            "properties": {
                "query": {"type": "string", "minLength": 1, "maxLength": 200},
                "client_id": {"type": "string", "minLength": 1, "maxLength": 120},
                "limit": {"type": "integer", "minimum": 1, "maximum": 20},
            },
        },
        output_schema={"pages": "array", "count": "integer", "connector_status": "string"},
        requires_approval=False,
        estimated_minutes_saved=5,
        risk_level="low",
        required_role="technician",
        access_mode="read",
    )

    def run(self, context: ActionContext, payload: dict[str, object]) -> ActionResult:
        query = payload.get("query")
        client_id = payload.get("client_id")
        if not isinstance(query, str) or not query.strip() or len(query.strip()) > 200:
            return _failed("query must be a non-empty string of at most 200 characters")
        if not isinstance(client_id, str) or not client_id.strip() or len(client_id.strip()) > 120:
            return _failed("client_id must be a non-empty string of at most 120 characters")
        scoped_client_id = client_id.strip()
        if context.client_id is not None and scoped_client_id != context.client_id:
            return _failed("client_id is outside the tenant scope")
        limit = payload.get("limit", 10)
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1 or limit > 20:
            return _failed("limit must be an integer between 1 and 20")
        provider = context.notion_client or NotionClient(context.settings)
        try:
            response = provider.search_pages(
                client_id=scoped_client_id,
                query=query.strip(),
                page_size=limit,
            )
        except Exception:
            return _failed("Notion documentation lookup failed")
        result = getattr(response, "result", None)
        status = str(getattr(result, "status", "failed"))
        message = redact_text(str(getattr(result, "message", "Notion read failed")))
        items = getattr(response, "items", [])
        if not isinstance(items, list):
            return _failed("Notion returned malformed page data")
        if status != "ready":
            return ActionResult(
                status="failed",
                output={"client_id": scoped_client_id, "connector_status": status, "pages": [], "count": 0},
                error_detail=message,
            )
        pages: list[dict[str, object]] = []
        for item in items[:limit]:
            page_id = str(getattr(item, "id", ""))
            try:
                detail = provider.get_page(page_id, client_id=scoped_client_id)
            except Exception:
                return _failed("Notion page retrieval failed")
            detail_result = getattr(detail, "result", None)
            if str(getattr(detail_result, "status", "failed")) != "ready":
                return ActionResult(
                    status="failed",
                    output={
                        "client_id": scoped_client_id,
                        "connector_status": str(getattr(detail_result, "status", "failed")),
                        "pages": [],
                        "count": 0,
                    },
                    error_detail=redact_text(
                        str(getattr(detail_result, "message", "Notion page retrieval failed"))
                    ),
                )
            detail_items = getattr(detail, "items", [])
            if not isinstance(detail_items, list) or not detail_items:
                return _failed("Notion returned malformed page detail")
            page = detail_items[0]
            if not hasattr(page, "__dataclass_fields__"):
                return _failed("Notion returned malformed page detail")
            pages.append(cast(dict[str, object], redact_value(asdict(page))))
        return ActionResult(
            status="success",
            output={
                "client_id": scoped_client_id,
                "connector_status": status,
                "pages": pages,
                "count": len(pages),
            },
            evidence=[
                {
                    "type": "connector_read",
                    "connector": "notion",
                    "operation": "search-and-markdown",
                    "client_id": scoped_client_id,
                }
            ],
        )


class NotionDataSourceQueryAction:
    manifest = SmartActionManifest(
        action_id="notion-data-source-query",
        title="Notion data-source query",
        description=(
            "Read a bounded page of rows from a tenant-mapped Notion data source. "
            "The provider query body is fixed and read-only."
        ),
        kind="deterministic",
        input_schema={
            "type": "object",
            "required": ["data_source_id", "client_id"],
            "properties": {
                "data_source_id": {"type": "string", "minLength": 1, "maxLength": 80},
                "client_id": {"type": "string", "minLength": 1, "maxLength": 120},
                "limit": {"type": "integer", "minimum": 1, "maximum": 20},
                "start_cursor": {"type": "string", "maxLength": 4096},
            },
        },
        output_schema={
            "data_source_id": "string",
            "pages": "array",
            "count": "integer",
            "next_cursor": "string",
            "connector_status": "string",
        },
        requires_approval=False,
        estimated_minutes_saved=5,
        risk_level="low",
        required_role="technician",
        access_mode="read",
    )

    def run(self, context: ActionContext, payload: dict[str, object]) -> ActionResult:
        data_source_id = payload.get("data_source_id")
        client_id = payload.get("client_id")
        if (
            not isinstance(data_source_id, str)
            or not data_source_id.strip()
            or len(data_source_id.strip()) > 80
        ):
            return _failed("data_source_id must be a non-empty string of at most 80 characters")
        if not isinstance(client_id, str) or not client_id.strip() or len(client_id.strip()) > 120:
            return _failed("client_id must be a non-empty string of at most 120 characters")
        scoped_client_id = client_id.strip()
        if context.client_id is not None and scoped_client_id != context.client_id:
            return _failed("client_id is outside the tenant scope")
        limit = payload.get("limit", 10)
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1 or limit > 20:
            return _failed("limit must be an integer between 1 and 20")
        start_cursor = payload.get("start_cursor", "")
        if not isinstance(start_cursor, str) or len(start_cursor) > 4096:
            return _failed("start_cursor must be a string of at most 4096 characters")
        provider = context.notion_client or NotionClient(context.settings)
        try:
            response = provider.query_data_source(
                data_source_id.strip(),
                client_id=scoped_client_id,
                page_size=limit,
                start_cursor=start_cursor,
            )
        except Exception:
            return _failed("Notion data-source query failed")
        result = getattr(response, "result", None)
        status = str(getattr(result, "status", "failed"))
        message = redact_text(str(getattr(result, "message", "Notion read failed")))
        items = getattr(response, "items", [])
        if not isinstance(items, list):
            return _failed("Notion returned malformed data-source rows")
        if status != "ready":
            return ActionResult(
                status="failed",
                output={
                    "data_source_id": data_source_id.strip(),
                    "client_id": scoped_client_id,
                    "connector_status": status,
                    "pages": [],
                    "count": 0,
                    "next_cursor": "",
                },
                error_detail=message,
            )
        pages = [
            cast(dict[str, object], redact_value(asdict(item)))
            for item in items[:limit]
            if hasattr(item, "__dataclass_fields__")
        ]
        return ActionResult(
            status="success",
            output={
                "data_source_id": data_source_id.strip(),
                "client_id": scoped_client_id,
                "connector_status": status,
                "pages": pages,
                "count": len(pages),
                "next_cursor": str(getattr(response, "next_cursor", "")),
            },
            evidence=[
                {
                    "type": "connector_read",
                    "connector": "notion",
                    "operation": "data-sources.query",
                    "data_source_id": data_source_id.strip(),
                    "client_id": scoped_client_id,
                }
            ],
        )


class NotionPageCommentAction:
    manifest = SmartActionManifest(
        action_id="notion-page-comment",
        title="Add Notion page comment",
        description=(
            "Preview and, after approval, add one bounded Markdown comment to a "
            "tenant-mapped Notion page."
        ),
        kind="deterministic",
        input_schema={
            "type": "object",
            "required": ["page_id", "client_id", "markdown"],
            "properties": {
                "page_id": {"type": "string", "minLength": 1, "maxLength": 80},
                "client_id": {"type": "string", "minLength": 1, "maxLength": 120},
                "markdown": {"type": "string", "minLength": 1, "maxLength": 10000},
            },
        },
        output_schema={
            "page_id": "string",
            "client_id": "string",
            "status": "string",
            "proposed_markdown": "string",
            "comment_id": "string",
        },
        requires_approval=True,
        estimated_minutes_saved=3,
        risk_level="high",
        required_role="technician",
        access_mode="write",
    )

    def run(self, context: ActionContext, payload: dict[str, object]) -> ActionResult:
        page_id = payload.get("page_id")
        client_id = payload.get("client_id")
        markdown = payload.get("markdown")
        if not isinstance(page_id, str) or not page_id.strip() or len(page_id.strip()) > 80:
            return _failed("page_id must be a non-empty string of at most 80 characters")
        if not isinstance(client_id, str) or not client_id.strip() or len(client_id.strip()) > 120:
            return _failed("client_id must be a non-empty string of at most 120 characters")
        scoped_client_id = client_id.strip()
        if context.client_id is not None and scoped_client_id != context.client_id:
            return _failed("client_id is outside the tenant scope")
        if not isinstance(markdown, str) or not markdown.strip() or len(markdown.strip()) > 10000:
            return _failed("markdown must be non-empty text of at most 10,000 characters")
        provider = context.notion_client or NotionClient(context.settings)
        approved = bool(payload.get("_approval_completed"))
        if approved and not context.settings.allow_write_actions:
            return _failed("Notion page comments are blocked until WAIT_ALLOW_WRITE_ACTIONS=true")
        try:
            operation = (
                provider.create_page_comment(
                    page_id.strip(), markdown, client_id=scoped_client_id
                )
                if approved
                else provider.preview_page_comment(
                    page_id.strip(), markdown, client_id=scoped_client_id
                )
            )
        except Exception:
            return _failed("Notion page comment operation failed")
        operation_status = str(getattr(operation, "status", "failed"))
        message = redact_text(str(getattr(operation, "message", "Notion comment failed")))
        output: dict[str, object] = {
            "page_id": page_id.strip(),
            "client_id": scoped_client_id,
            "status": operation_status,
            "message": message,
            "proposed_markdown": markdown.strip(),
            "approval_required": not approved,
            "approved": approved,
        }
        comment_id = str(getattr(operation, "comment_id", ""))
        if comment_id:
            output["comment_id"] = comment_id
        evidence: list[dict[str, object]] = [
            {
                "type": "connector_mutation",
                "connector": "notion",
                "operation": "comments.create",
                "page_id": page_id.strip(),
                "client_id": scoped_client_id,
            }
        ]
        if operation_status != ("created" if approved else "preview"):
            return ActionResult(
                status="failed",
                output=output,
                evidence=evidence,
                error_detail=message,
            )
        return ActionResult(status="success", output=output, evidence=evidence)


class SharePointDocumentationSearchAction:
    manifest = SmartActionManifest(
        action_id="sharepoint-documentation-search",
        title="SharePoint documentation search",
        description=(
            "Search tenant-scoped SharePoint drive items and provider-indexed file content "
            "through Microsoft Graph."
        ),
        kind="deterministic",
        input_schema={
            "type": "object",
            "required": ["query", "site_id"],
            "properties": {
                "query": {"type": "string", "minLength": 1, "maxLength": 200},
                "site_id": {"type": "string", "minLength": 1, "maxLength": 256},
                "parent_item_id": {"type": "string", "minLength": 1, "maxLength": 256},
                "limit": {"type": "integer", "minimum": 1, "maximum": 50},
            },
        },
        output_schema={"documents": "array", "count": "integer", "connector_status": "string"},
        requires_approval=False,
        estimated_minutes_saved=5,
        risk_level="low",
        required_role="technician",
        access_mode="read",
    )

    def run(self, context: ActionContext, payload: dict[str, object]) -> ActionResult:
        query = payload.get("query")
        site_id = payload.get("site_id")
        if not isinstance(query, str) or not query.strip() or len(query.strip()) > 200:
            return _failed("query must be a non-empty string of at most 200 characters")
        if not isinstance(site_id, str) or not site_id.strip() or len(site_id.strip()) > 256:
            return _failed("site_id must be a non-empty string of at most 256 characters")
        scoped_site_id = site_id.strip()
        if context.client_id is not None and scoped_site_id != context.client_id:
            return _failed("site_id is outside the tenant scope")
        limit = payload.get("limit", 20)
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1 or limit > 50:
            return _failed("limit must be an integer between 1 and 50")
        parent_item_id = payload.get("parent_item_id")
        if parent_item_id is not None and (
            not isinstance(parent_item_id, str)
            or not parent_item_id.strip()
            or len(parent_item_id.strip()) > 256
        ):
            return _failed("parent_item_id must be a non-empty string of at most 256 characters")
        from wait_local_agent.sharepoint import SharePointClient

        provider = context.sharepoint_client or SharePointClient(context.settings)
        try:
            search_documents = getattr(provider, "search_documents", None)
            if callable(search_documents):
                response = search_documents(
                    scoped_site_id,
                    query.strip(),
                    parent_item_id=parent_item_id.strip() if isinstance(parent_item_id, str) else None,
                    limit=limit,
                )
            else:
                response = provider.list_documents(
                    scoped_site_id,
                    parent_item_id=parent_item_id.strip() if isinstance(parent_item_id, str) else None,
                    page_size=limit,
                )
        except Exception:
            return _failed("SharePoint documentation lookup failed")
        result = getattr(response, "result", None)
        status = str(getattr(result, "status", "failed"))
        message = redact_text(str(getattr(result, "message", "SharePoint read failed")))
        items = getattr(response, "items", [])
        if not isinstance(items, list):
            return _failed("SharePoint returned malformed document data")
        if status != "ready":
            return ActionResult(
                status="failed",
                output={"site_id": scoped_site_id, "connector_status": status, "documents": [], "count": 0},
                error_detail=message,
            )
        query_value = query.strip().casefold()
        documents = [
            {
                "id": str(getattr(item, "id", "")),
                "name": str(getattr(item, "name", "")),
                "site_id": str(getattr(item, "site_id", "")),
                "parent_id": str(getattr(item, "parent_id", "")),
                "size": getattr(item, "size", 0),
                "updated_at": str(getattr(item, "updated_at", "")),
                "web_url": str(getattr(item, "web_url", "")),
                "is_folder": bool(getattr(item, "is_folder", False)),
            }
            for item in items
            if hasattr(item, "__dataclass_fields__")
            and str(getattr(item, "site_id", "")) in {"", scoped_site_id}
            and (
                query_value in str(getattr(item, "name", "")).casefold()
                or query_value in str(getattr(item, "content", "")).casefold()
            )
        ][:limit]
        return ActionResult(
            status="success",
            output={
                "site_id": scoped_site_id,
                "connector_status": status,
                "documents": cast(list[dict[str, object]], redact_value(documents)),
                "count": len(documents),
            },
            evidence=[
                {
                    "type": "connector_read",
                    "connector": "sharepoint",
                    "operation": "drive.items.list",
                    "site_id": scoped_site_id,
                }
            ],
        )


class SharePointDocumentationContentAction:
    manifest = SmartActionManifest(
        action_id="sharepoint-document-content",
        title="SharePoint document content",
        description="Retrieve one tenant-scoped SharePoint text document with a bounded content length.",
        kind="deterministic",
        input_schema={
            "type": "object",
            "required": ["site_id", "item_id"],
            "properties": {
                "site_id": {"type": "string", "minLength": 1, "maxLength": 256},
                "item_id": {"type": "string", "minLength": 1, "maxLength": 256},
            },
        },
        output_schema={"document": "object", "connector_status": "string"},
        requires_approval=False,
        estimated_minutes_saved=5,
        risk_level="low",
        required_role="technician",
        access_mode="read",
    )

    def run(self, context: ActionContext, payload: dict[str, object]) -> ActionResult:
        site_id = payload.get("site_id")
        item_id = payload.get("item_id")
        if not isinstance(site_id, str) or not site_id.strip() or len(site_id.strip()) > 256:
            return _failed("site_id must be a non-empty string of at most 256 characters")
        if not isinstance(item_id, str) or not item_id.strip() or len(item_id.strip()) > 256:
            return _failed("item_id must be a non-empty string of at most 256 characters")
        scoped_site_id = site_id.strip()
        scoped_item_id = item_id.strip()
        if context.client_id is not None and scoped_site_id != context.client_id:
            return _failed("site_id is outside the tenant scope")
        from wait_local_agent.sharepoint import SharePointClient

        provider = context.sharepoint_client or SharePointClient(context.settings)
        try:
            response = provider.get_document_content(scoped_site_id, scoped_item_id)
        except Exception:
            return _failed("SharePoint document content lookup failed")
        result = getattr(response, "result", None)
        status = str(getattr(result, "status", "failed"))
        message = redact_text(str(getattr(result, "message", "SharePoint read failed")))
        items = getattr(response, "items", [])
        if not isinstance(items, list):
            return _failed("SharePoint returned malformed document data")
        if status != "ready":
            return ActionResult(
                status="failed",
                output={
                    "site_id": scoped_site_id,
                    "item_id": scoped_item_id,
                    "connector_status": status,
                    "document": {},
                },
                error_detail=message,
            )
        documents = [
            {
                "id": str(getattr(item, "id", "")),
                "name": str(getattr(item, "name", "")),
                "site_id": str(getattr(item, "site_id", "")),
                "parent_id": str(getattr(item, "parent_id", "")),
                "size": getattr(item, "size", 0),
                "updated_at": str(getattr(item, "updated_at", "")),
                "web_url": str(getattr(item, "web_url", "")),
                "is_folder": bool(getattr(item, "is_folder", False)),
                "is_file": bool(getattr(item, "is_file", False)),
                "content": str(getattr(item, "content", "")),
            }
            for item in items
            if hasattr(item, "__dataclass_fields__")
            and str(getattr(item, "site_id", "")) == scoped_site_id
            and str(getattr(item, "id", "")) == scoped_item_id
        ]
        if not documents:
            return _failed("SharePoint returned no matching document")
        return ActionResult(
            status="success",
            output={
                "site_id": scoped_site_id,
                "item_id": scoped_item_id,
                "connector_status": status,
                "document": cast(dict[str, object], redact_value(documents[0])),
            },
            evidence=[
                {
                    "type": "connector_read",
                    "connector": "sharepoint",
                    "operation": "drive.items.content.get",
                    "site_id": scoped_site_id,
                    "item_id": scoped_item_id,
                }
            ],
        )


class TicketQualityAction:
    manifest = SmartActionManifest(
        action_id="ticket-quality",
        title="Ticket quality check",
        description="Check required ticket fields and controlled priority/status values.",
        kind="deterministic",
        input_schema={"type": "object", "required": ["ticket_id"]},
        output_schema={"issues": "array", "quality_score": "number", "ticket_id": "string"},
        requires_approval=False,
        estimated_minutes_saved=3,
        risk_level="low",
        access_mode="read",
    )

    def run(self, context: ActionContext, payload: dict[str, object]) -> ActionResult:
        ticket = _ticket_from_payload(context.store, payload, context.client_id)
        if ticket is None:
            return _failed("ticket_id must identify an existing ticket")
        issues: list[str] = []
        if not ticket.client.strip():
            issues.append("missing_client")
        if not ticket.subject.strip():
            issues.append("missing_subject")
        if not ticket.body.strip():
            issues.append("missing_body")
        if ticket.priority.strip().lower() not in {
            "low", "medium", "high", "critical", "p1", "p2", "p3", "p4"
        }:
            issues.append("unknown_priority")
        if ticket.status.strip().lower() not in {"new", "open", "pending", "resolved", "closed"}:
            issues.append("unknown_status")
        score = max(0, 100 - (len(issues) * 20))
        return ActionResult(
            status="success",
            output={
                "ticket_id": ticket.id,
                "issues": issues,
                "quality_score": score,
                "passed": not issues,
                "estimate": self.manifest.estimated_minutes_saved,
            },
            evidence=[_ticket_evidence(ticket, ["client", "subject", "body", "priority", "status"])],
        )


class TicketSlaAssessmentAction:
    manifest = SmartActionManifest(
        action_id="ticket-sla-assessment",
        title="Assess ticket SLA risk",
        description=(
            "Compare a ticket's age and priority with explicit operator-supplied "
            "thresholds; this does not infer a vendor SLA contract."
        ),
        kind="deterministic",
        input_schema={
            "type": "object",
            "required": ["ticket_id", "thresholds_minutes"],
            "properties": {
                "ticket_id": "string",
                "thresholds_minutes": "object of priority to positive minutes",
            },
        },
        output_schema={
            "ticket_id": "string",
            "assessment": "object",
            "evidence_status": "string",
        },
        requires_approval=False,
        estimated_minutes_saved=3,
        risk_level="low",
        access_mode="read",
    )

    def run(self, context: ActionContext, payload: dict[str, object]) -> ActionResult:
        ticket = _ticket_from_payload(context.store, payload, context.client_id)
        if ticket is None:
            return _failed("ticket_id must identify an existing ticket")
        thresholds = _positive_thresholds(payload.get("thresholds_minutes"))
        if thresholds is None:
            return _failed("thresholds_minutes must map priorities to positive minutes")
        created_at = _parse_ticket_timestamp(ticket.created_at)
        if created_at is None:
            return ActionResult(
                status="success",
                output={
                    "ticket_id": ticket.id,
                    "assessment": {"state": "unknown", "reason": "missing_created_at"},
                    "evidence_status": "insufficient",
                    "estimate": self.manifest.estimated_minutes_saved,
                },
                evidence=[_ticket_evidence(ticket, ["priority", "status"])],
            )
        threshold = thresholds.get(ticket.priority.strip().lower())
        if threshold is None:
            return ActionResult(
                status="success",
                output={
                    "ticket_id": ticket.id,
                    "assessment": {
                        "state": "unknown",
                        "reason": "priority_threshold_not_supplied",
                        "priority": ticket.priority,
                    },
                    "evidence_status": "insufficient",
                    "estimate": self.manifest.estimated_minutes_saved,
                },
                evidence=[_ticket_evidence(ticket, ["priority", "status", "created_at"])],
            )
        age_minutes = max(0, int((datetime.now(UTC) - created_at).total_seconds() // 60))
        terminal = ticket.status.strip().lower() in {"resolved", "closed"}
        at_risk = not terminal and age_minutes >= threshold
        return ActionResult(
            status="success",
            output={
                "ticket_id": ticket.id,
                "assessment": {
                    "state": "resolved" if terminal else "at_risk" if at_risk else "within_threshold",
                    "priority": ticket.priority,
                    "status": ticket.status,
                    "age_minutes": age_minutes,
                    "threshold_minutes": threshold,
                },
                "evidence_status": "complete",
                "estimate": self.manifest.estimated_minutes_saved,
            },
            evidence=[_ticket_evidence(ticket, ["priority", "status", "created_at"])],
        )


class StaleTicketSweepAction:
    manifest = SmartActionManifest(
        action_id="stale-ticket-sweep",
        title="Sweep stale tickets",
        description=(
            "Find open local tickets older than an explicit threshold within the "
            "current tenant scope; missing timestamps are excluded and reported."
        ),
        kind="deterministic",
        input_schema={
            "type": "object",
            "required": ["stale_after_minutes"],
            "properties": {"stale_after_minutes": "positive integer"},
        },
        output_schema={
            "tickets": "array",
            "count": "number",
            "excluded_missing_timestamp": "number",
        },
        requires_approval=False,
        estimated_minutes_saved=5,
        risk_level="low",
        access_mode="read",
    )

    def run(self, context: ActionContext, payload: dict[str, object]) -> ActionResult:
        threshold = payload.get("stale_after_minutes")
        if isinstance(threshold, bool) or not isinstance(threshold, int) or threshold <= 0:
            return _failed("stale_after_minutes must be a positive integer")
        now = datetime.now(UTC)
        stale: list[dict[str, object]] = []
        excluded = 0
        for ticket in context.store.list_tickets(client_id=context.client_id):
            if ticket.status.strip().lower() in {"resolved", "closed"}:
                continue
            created_at = _parse_ticket_timestamp(ticket.created_at)
            if created_at is None:
                excluded += 1
                continue
            age_minutes = max(0, int((now - created_at).total_seconds() // 60))
            if age_minutes >= threshold:
                stale.append(
                    {
                        "ticket_id": ticket.id,
                        "subject": ticket.subject,
                        "priority": ticket.priority,
                        "status": ticket.status,
                        "age_minutes": age_minutes,
                    }
                )
        stale.sort(key=lambda item: (-int(cast(int, item["age_minutes"])), str(item["ticket_id"])))
        return ActionResult(
            status="success",
            output={
                "tickets": stale[:100],
                "count": len(stale),
                "excluded_missing_timestamp": excluded,
                "stale_after_minutes": threshold,
                "estimate": self.manifest.estimated_minutes_saved,
            },
            evidence=[
                {
                    "type": "local_ticket_sweep",
                    "scope": context.client_id or "local",
                    "threshold_minutes": threshold,
                    "returned": min(len(stale), 100),
                }
            ],
        )


class RecurringServiceReviewAction:
    manifest = SmartActionManifest(
        action_id="recurring-service-review",
        title="Recurring service review",
        description=(
            "Review one client's local ticket posture, explicit follow-up candidates, "
            "lifecycle evidence, and automation activity without taking side effects."
        ),
        kind="deterministic",
        input_schema={
            "type": "object",
            "required": ["period_start", "period_end"],
            "properties": {
                "ticket_id": {"type": "string", "maxLength": 200},
                "period_start": {"type": "string", "format": "date"},
                "period_end": {"type": "string", "format": "date"},
                "follow_up_after_days": {"type": "integer", "minimum": 1, "maximum": 90},
            },
        },
        output_schema={
            "report_type": "string",
            "client_id": "string",
            "period_start": "string",
            "period_end": "string",
            "evidence_status": "string",
            "sections": "array",
        },
        requires_approval=False,
        estimated_minutes_saved=20,
        risk_level="low",
        required_role="viewer",
        access_mode="read",
    )

    def run(self, context: ActionContext, payload: dict[str, object]) -> ActionResult:
        if set(payload) - {"ticket_id", "period_start", "period_end", "follow_up_after_days"}:
            return _failed("recurring service review payload contains unsupported fields")
        client_id = context.client_id.strip() if isinstance(context.client_id, str) else ""
        if not client_id:
            return _failed("recurring service review requires a tenant-scoped client")
        ticket_id = payload.get("ticket_id")
        if ticket_id is not None:
            if not isinstance(ticket_id, str) or not ticket_id.strip():
                return _failed("ticket_id must identify an existing ticket")
            if context.store.get_ticket(ticket_id.strip(), client_id=client_id) is None:
                return _failed("ticket_id must identify an existing ticket in the client scope")
        period_start = payload.get("period_start")
        period_end = payload.get("period_end")
        if not isinstance(period_start, str) or not isinstance(period_end, str):
            return _failed("period_start and period_end must be ISO dates")
        follow_up_after_days = payload.get("follow_up_after_days", 14)
        if (
            isinstance(follow_up_after_days, bool)
            or not isinstance(follow_up_after_days, int)
            or not 1 <= follow_up_after_days <= 90
        ):
            return _failed("follow_up_after_days must be an integer between 1 and 90")
        try:
            from wait_local_agent.reports.msp import build_recurring_service_review_report

            sections, metadata = build_recurring_service_review_report(
                context.store,
                client_id=client_id,
                period_start=period_start,
                period_end=period_end,
                follow_up_after_days=follow_up_after_days,
            )
        except ValueError as exc:
            return _failed(redact_text(str(exc)))
        evidence = [
            {
                "type": "local_recurring_service_review",
                "client_id": client_id,
                "period_start": period_start,
                "period_end": period_end,
                "follow_up_after_days": follow_up_after_days,
                "evidence_status": metadata["evidence_status"],
                "claims_excluded": metadata["claims_excluded"],
                "ticket_id": ticket_id.strip() if isinstance(ticket_id, str) else None,
            }
        ]
        return ActionResult(
            status="success",
            output={
                "report_type": "recurring_service_review",
                "client_id": client_id,
                "period_start": period_start,
                "period_end": period_end,
                "evidence_status": metadata["evidence_status"],
                "metadata": metadata,
                "sections": [asdict(section) for section in sections],
            },
            evidence=evidence,
        )


class TicketSentimentAction:
    manifest = SmartActionManifest(
        action_id="ticket-sentiment",
        title="Assess ticket sentiment",
        description="Classify customer-facing ticket language with bounded lexical heuristics.",
        kind="deterministic",
        input_schema={"type": "object", "required": ["ticket_id"]},
        output_schema={"sentiment": "string", "score": "number", "ticket_id": "string"},
        requires_approval=False,
        estimated_minutes_saved=3,
        risk_level="low",
        access_mode="read",
    )

    def run(self, context: ActionContext, payload: dict[str, object]) -> ActionResult:
        ticket = _ticket_from_payload(context.store, payload, context.client_id)
        if ticket is None:
            return _failed("ticket_id must identify an existing ticket")
        tokens = _tokens(f"{ticket.subject} {ticket.body}")
        positive = sorted(tokens & _POSITIVE_SENTIMENT_TERMS)
        negative = sorted(tokens & _NEGATIVE_SENTIMENT_TERMS)
        raw_score = len(positive) - len(negative)
        score = max(-1.0, min(1.0, raw_score / 3.0))
        sentiment = "positive" if score > 0 else "negative" if score < 0 else "neutral"
        return ActionResult(
            status="success",
            output={
                "ticket_id": ticket.id,
                "sentiment": sentiment,
                "score": score,
                "positive_terms": positive,
                "negative_terms": negative,
                "escalation_signal": sentiment == "negative" or ticket.priority.lower() in {"critical", "p1"},
                "estimate": self.manifest.estimated_minutes_saved,
            },
            evidence=[_ticket_evidence(ticket, ["subject", "body", "priority"])],
        )


class TicketEscalationAction:
    manifest = SmartActionManifest(
        action_id="ticket-escalation",
        title="Assess ticket escalation",
        description="Recommend a bounded response urgency from ticket priority, status, and impact language.",
        kind="deterministic",
        input_schema={"type": "object", "required": ["ticket_id"]},
        output_schema={"urgency": "string", "recommendation": "string", "ticket_id": "string"},
        requires_approval=False,
        estimated_minutes_saved=3,
        risk_level="low",
        access_mode="read",
    )

    def run(self, context: ActionContext, payload: dict[str, object]) -> ActionResult:
        ticket = _ticket_from_payload(context.store, payload, context.client_id)
        if ticket is None:
            return _failed("ticket_id must identify an existing ticket")
        priority = ticket.priority.strip().lower()
        status = ticket.status.strip().lower()
        impact_tokens = _tokens(f"{ticket.subject} {ticket.body}")
        broad_impact = bool(impact_tokens & {"outage", "everyone", "users", "production"})
        if status in {"closed", "resolved"}:
            urgency, recommendation = "none", "no escalation for a resolved ticket"
        elif priority in {"critical", "p1"} or broad_impact:
            urgency, recommendation = "immediate", "notify the on-call or senior technician"
        elif priority in {"high", "p2"}:
            urgency, recommendation = "same_day", "assign a senior technician today"
        else:
            urgency, recommendation = "standard", "keep the ticket in the normal triage queue"
        return ActionResult(
            status="success",
            output={
                "ticket_id": ticket.id,
                "urgency": urgency,
                "recommendation": recommendation,
                "priority": ticket.priority,
                "status": ticket.status,
                "broad_impact": broad_impact,
                "estimate": self.manifest.estimated_minutes_saved,
            },
            evidence=[_ticket_evidence(ticket, ["subject", "body", "priority", "status"])],
        )


class SecurityAlertAssessmentAction:
    manifest = SmartActionManifest(
        action_id="security-alert-assessment",
        title="Assess security alert",
        description=(
            "Detect bounded security-alert indicators in a ticket and recommend "
            "human security handling without changing the ticket or running a tool."
        ),
        kind="deterministic",
        input_schema={"type": "object", "required": ["ticket_id"]},
        output_schema={
            "ticket_id": "string",
            "security_signal": "boolean",
            "severity": "string",
            "indicators": "array",
            "recommendation": "string",
        },
        requires_approval=False,
        estimated_minutes_saved=4,
        risk_level="low",
        access_mode="read",
    )

    def run(self, context: ActionContext, payload: dict[str, object]) -> ActionResult:
        ticket = _ticket_from_payload(context.store, payload, context.client_id)
        if ticket is None:
            return _failed("ticket_id must identify an existing ticket")
        text = f"{ticket.subject} {ticket.body}".casefold()
        indicators = sorted(term for term in _SECURITY_ALERT_TERMS if term in text)
        critical = any(term in _CRITICAL_SECURITY_TERMS for term in indicators)
        severity = "critical" if critical else "high" if indicators else "none"
        recommendation = (
            "Pause automated side effects and route to a security-qualified technician."
            if indicators
            else "No bounded security-alert indicator was found in the supplied ticket text."
        )
        return ActionResult(
            status="success",
            output={
                "ticket_id": ticket.id,
                "security_signal": bool(indicators),
                "severity": severity,
                "indicators": indicators,
                "recommendation": recommendation,
                "estimate": self.manifest.estimated_minutes_saved,
            },
            evidence=[_ticket_evidence(ticket, ["subject", "body", "priority", "status"])],
        )


class FindSimilarTicketsAction:
    manifest = SmartActionManifest(
        action_id="find-similar-tickets",
        title="Find similar tickets",
        description="Rank local tickets by deterministic subject and body token overlap.",
        kind="deterministic",
        input_schema={"type": "object", "required": ["ticket_id"]},
        output_schema={"matches": "array", "ticket_id": "string"},
        requires_approval=False,
        estimated_minutes_saved=6,
    )

    def run(self, context: ActionContext, payload: dict[str, object]) -> ActionResult:
        ticket = _ticket_from_payload(context.store, payload, context.client_id)
        if ticket is None:
            return _failed("ticket_id must identify an existing ticket")
        query_tokens = _tokens(f"{ticket.subject} {ticket.body}")
        matches: list[tuple[int, Ticket]] = []
        for candidate in context.store.list_tickets(client_id=ticket.client_id):
            if candidate.id == ticket.id:
                continue
            score = len(query_tokens & _tokens(f"{candidate.subject} {candidate.body}"))
            if score:
                matches.append((score, candidate))
        matches.sort(key=lambda item: (-item[0], item[1].id))
        limited = matches[:5]
        output_matches = [
            {
                "ticket_id": candidate.id,
                "subject": candidate.subject,
                "priority": candidate.priority,
                "status": candidate.status,
                "similarity_score": score,
            }
            for score, candidate in limited
        ]
        evidence = [
            _ticket_evidence(candidate, ["subject", "priority", "status"])
            for _, candidate in limited
        ]
        return ActionResult(
            status="success",
            output={
                "ticket_id": ticket.id,
                "matches": output_matches,
                "estimate": self.manifest.estimated_minutes_saved,
            },
            evidence=evidence,
        )


class CollectorPreviewAction:
    manifest = SmartActionManifest(
        action_id="collector-preview",
        title="Preview collector operation",
        description="Validate an existing read-only collector and estimate its local operation.",
        kind="deterministic",
        input_schema={
            "type": "object",
            "required": ["module_id"],
            "properties": {"module_id": "string", "config": "object"},
        },
        output_schema={
            "module_id": "string",
            "source_name": "string",
            "estimated_assets": "number",
            "estimated_observations": "number",
        },
        requires_approval=False,
        estimated_minutes_saved=2,
        risk_level="low",
        required_role="technician",
        access_mode="read",
    )

    def run(self, context: ActionContext, payload: dict[str, object]) -> ActionResult:
        module_id = payload.get("module_id")
        if not isinstance(module_id, str) or not module_id.strip():
            return _failed("module_id must be a non-empty string")
        config = payload.get("config", {})
        if not isinstance(config, dict):
            return _failed("config must be an object when provided")
        if context.collector_service is None:
            return _failed("collector preview service is unavailable")
        try:
            preview = context.collector_service.preview(
                module_id.strip(),
                config,
                client_id=context.client_id,
            )
        except KeyError:
            return _failed("collector module is not registered")
        except ValueError as exc:
            return _failed(redact_text(str(exc)))
        except Exception:
            return _failed("collector preview failed")
        output = cast(dict[str, object], asdict(preview))
        output["estimate"] = self.manifest.estimated_minutes_saved
        evidence = [
            {
                "type": "collector_preview",
                "module_id": module_id.strip(),
                "scopes": output.get("scopes", []),
            }
        ]
        return ActionResult(status="success", output=output, evidence=evidence)


class DispatchSuggestionAction:
    manifest = SmartActionManifest(
        action_id="dispatch-suggestion",
        title="Dispatch suggestion",
        description="Draft a workload-aware technician recommendation for approval.",
        kind="deterministic",
        input_schema={"type": "object", "required": ["ticket_id"], "properties": {"technicians": "array"}},
        output_schema={"recommendation": "object", "approved": "boolean"},
        requires_approval=True,
        estimated_minutes_saved=5,
    )

    def run(self, context: ActionContext, payload: dict[str, object]) -> ActionResult:
        ticket = _ticket_from_payload(context.store, payload, context.client_id)
        if ticket is None:
            return _failed("ticket_id must identify an existing ticket")
        raw_candidates = payload.get("technicians", [])
        if not isinstance(raw_candidates, list):
            return _failed("technicians must be an array when provided")
        candidates: list[dict[str, object]] = []
        for candidate in raw_candidates:
            if not isinstance(candidate, dict):
                return _failed("each technician must be an object")
            technician_id = candidate.get("id")
            if not isinstance(technician_id, str) or not technician_id.strip():
                return _failed("each technician must have a non-empty id")
            workload = candidate.get("workload", 0)
            if not isinstance(workload, (int, float)) or isinstance(workload, bool):
                return _failed("technician workload must be numeric")
            candidates.append({"id": technician_id, "workload": workload})
        candidates.sort(key=lambda item: (_workload_value(item), str(item["id"])))
        selected = candidates[0] if candidates else None
        recommendation = {
            "ticket_id": ticket.id,
            "technician_id": selected["id"] if selected else None,
            "workload": selected["workload"] if selected else None,
            "priority": ticket.priority,
            "reason": (
                "lowest supplied workload"
                if selected
                else "no technician workload data was supplied"
            ),
        }
        return ActionResult(
            status="success",
            output={
                "ticket_id": ticket.id,
                "recommendation": recommendation,
                "approved": False,
                "estimate": self.manifest.estimated_minutes_saved,
            },
            evidence=[_ticket_evidence(ticket, ["priority", "status", "client"])],
        )


def _build_default_registry() -> SmartActionRegistry:
    registry = SmartActionRegistry()
    for action in (
        TicketTriageAction(),
        TicketSummaryAction(),
        SuggestResolutionAction(),
        DocumentationAssistedResponseAction(),
        KnowledgeSearchAction(),
        M365IdentityLookupAction(),
        RmmDeviceLookupAction(),
        RmmAlertLookupAction(),
        NSightAntivirusThreatsAction(),
        NSightOutageLookupAction(),
        NSightBackupSessionsAction(),
        NSightBackupHistoryAction(),
        NSightCheckInventoryAction(),
        NSightCheckConfigAction(),
        NSightPerformanceHistoryAction(),
        NSightAssetDetailsAction(),
        NSightMonitoringDetailsAction(),
        NSightPatchLookupAction(),
        NSightPatchApproveAction(),
        NSightPatchReprocessAction(),
        NSightPatchPolicyAction(),
        NSightRunTaskNowAction(),
        RmmScriptCatalogAction(),
        RmmScriptPreviewAction(),
        RmmScriptExecuteAction(),
        RmmScriptExecutionLookupAction(),
        ScreenConnectSessionNoteAction(),
        ScreenConnectSessionMessageAction(),
        HaloPSATicketLookupAction(),
        HaloPSATicketWriteAction(
            action_id="halopsa-ticket-add-note",
            title="HaloPSA add ticket note",
            action_type="add_note",
        ),
        HaloPSATicketWriteAction(
            action_id="halopsa-ticket-assign-technician",
            title="HaloPSA assign ticket",
            action_type="assign_technician",
        ),
        HaloPSATicketWriteAction(
            action_id="halopsa-ticket-draft-response",
            title="HaloPSA draft ticket response",
            action_type="draft_response",
        ),
        HaloPSATicketWriteAction(
            action_id="halopsa-ticket-status-update",
            title="HaloPSA update ticket status",
            action_type="update_status",
        ),
        HaloPSATicketWriteAction(
            action_id="halopsa-ticket-update-fields",
            title="HaloPSA update ticket fields",
            action_type="update_ticket_fields",
        ),
        ConnectWiseTicketWriteAction(
            action_id="connectwise-ticket-assign-technician",
            title="ConnectWise assign ticket",
            action_type="assign_technician",
        ),
        ConnectWiseTicketWriteAction(
            action_id="connectwise-ticket-status-update",
            title="ConnectWise update ticket status",
            action_type="update_status",
        ),
        ConnectWiseTicketWriteAction(
            action_id="connectwise-ticket-update-fields",
            title="ConnectWise update ticket fields",
            action_type="update_ticket_fields",
        ),
        ConnectWiseTicketLookupAction(),
        SyncroTicketLookupAction(),
        SyncroTicketCommentsAction(),
        SyncroTicketWriteAction(
            action_id="syncro-ticket-add-note",
            title="Syncro add ticket note",
            action_type="add_note",
        ),
        ServiceNowIncidentLookupAction(),
        ServiceNowIncidentWriteAction(
            action_id="servicenow-incident-add-work-note",
            title="ServiceNow add incident work note",
            action_type="add_work_note",
        ),
        ServiceNowIncidentWriteAction(
            action_id="servicenow-incident-update-state",
            title="ServiceNow update incident state",
            action_type="update_state",
        ),
        ServiceNowIncidentWriteAction(
            action_id="servicenow-incident-assign",
            title="ServiceNow assign incident",
            action_type="assign_incident",
        ),
        ServiceNowIncidentWriteAction(
            action_id="servicenow-incident-update-resolution",
            title="ServiceNow update incident resolution",
            action_type="update_resolution",
        ),
        AutotaskTicketLookupAction(),
        AutotaskTicketWriteAction(
            action_id="autotask-ticket-add-note",
            title="Autotask add ticket note",
            action_type="add_note",
        ),
        AutotaskTicketWriteAction(
            action_id="autotask-ticket-add-time-entry",
            title="Autotask add time entry",
            action_type="add_time_entry",
        ),
        AutotaskTicketWriteAction(
            action_id="autotask-ticket-update-status",
            title="Autotask update ticket status",
            action_type="update_status",
        ),
        AutotaskTicketWriteAction(
            action_id="autotask-ticket-update-resolution",
            title="Autotask update ticket resolution",
            action_type="update_resolution",
        ),
        AutotaskTicketWriteAction(
            action_id="autotask-ticket-assign-technician",
            title="Autotask assign ticket",
            action_type="assign_technician",
        ),
        HuduDocumentationSearchAction(),
        ItGlueDocumentationSearchAction(),
        ConfluenceDocumentationSearchAction(),
        NotionDocumentationSearchAction(),
        NotionDataSourceQueryAction(),
        NotionPageCommentAction(),
        SharePointDocumentationSearchAction(),
        SharePointDocumentationContentAction(),
        TimeZestSchedulingRequestLookupAction(),
        TimeZestSchedulingRequestCreateAction(),
        ScalePadClientLookupAction(),
        ScalePadRiskSummaryAction(),
        ScalePadComplianceHealthAction(),
        ScalePadGoalLookupAction(),
        ScalePadAssessmentLookupAction(),
        M365LiveContextAction(),
        M365GroupMembershipAction(),
        M365LicenseChangeAction(),
        M365SessionRevocationAction(),
        M365PasswordResetAction(),
        M365AuthenticationMethodDeleteAction(),
        M365MailboxSettingsAction(),
        M365MailMessageMoveAction(),
        M365MailMessageReadStateAction(),
        M365MailMessageDeleteAction(),
        M365ManagedDeviceAction(
            action_id="m365-managed-device-retire",
            title="Microsoft 365 managed-device retirement",
            operation="retirement",
            action_type="managed-devices.retire",
            provider_method="retire_managed_device",
            validator_name="validate_m365_managed_device_retirement_payload",
        ),
        M365ManagedDeviceAction(
            action_id="m365-managed-device-sync",
            title="Microsoft 365 managed-device sync",
            operation="sync",
            action_type="managed-devices.sync",
            provider_method="sync_managed_device",
            validator_name="validate_m365_managed_device_sync_payload",
        ),
        M365ManagedDeviceAction(
            action_id="m365-managed-device-reboot",
            title="Microsoft 365 managed-device reboot",
            operation="reboot",
            action_type="managed-devices.reboot",
            provider_method="reboot_managed_device",
            validator_name="validate_m365_managed_device_reboot_payload",
        ),
        M365ManagedDeviceAction(
            action_id="m365-managed-device-remote-lock",
            title="Microsoft 365 managed-device remote lock",
            operation="remote_lock",
            action_type="managed-devices.remote-lock",
            provider_method="remote_lock_managed_device",
            validator_name="validate_m365_managed_device_remote_lock_payload",
        ),
        M365UserOnboardingAction(),
        M365UserOffboardingAction(),
        CommunicationPreviewAction(),
        CommunicationSendAction(),
        TicketQualityAction(),
        TicketSlaAssessmentAction(),
        StaleTicketSweepAction(),
        RecurringServiceReviewAction(),
        TicketSentimentAction(),
        TicketEscalationAction(),
        SecurityAlertAssessmentAction(),
        CollectorPreviewAction(),
        FindSimilarTicketsAction(),
        DispatchSuggestionAction(),
    ):
        registry.register(action)
    return registry


default_registry = _build_default_registry()


class SmartActionService:
    def __init__(
        self,
        store: Store,
        settings: Settings,
        provider: ModelProvider | None = None,
        registry: SmartActionRegistry | None = None,
        provider_configured: bool | None = None,
        collector_service: CollectorPreviewProvider | None = None,
        halopsa_client: HaloPSAReadProvider | HaloPSAWriteProvider | None = None,
        hudu_client: HuduReadProvider | None = None,
        communication_provider: CommunicationProvider | None = None,
        communication_sender: CommunicationSender | None = None,
        rmm_provider: RmmInventoryProvider | None = None,
        connectwise_client: ConnectWiseReadProvider | ConnectWiseWriteProvider | None = None,
        syncro_client: SyncroReadProvider | SyncroWriteProvider | None = None,
        servicenow_client: ServiceNowReadProvider | ServiceNowWriteProvider | None = None,
        autotask_client: AutotaskReadProvider | AutotaskWriteProvider | None = None,
        itglue_client: ItGlueClientProtocol | None = None,
        confluence_client: ConfluenceClientProtocol | None = None,
        notion_client: NotionClientProtocol | None = None,
        sharepoint_client: SharePointClientProtocol | None = None,
        timezest_client: TimeZestReadProvider | TimeZestWriteProvider | None = None,
        scalepad_client: ScalePadReadProvider | None = None,
        m365_client: (
            M365GraphReadProvider
            | M365LifecycleWriteProvider
            | M365UserCreateProvider
            | M365PasswordResetProvider
            | M365AuthenticationMethodDeleteProvider
            | M365GroupMembershipWriteProvider
            | M365LicenseWriteProvider
            | M365SessionRevocationWriteProvider
            | M365MailboxSettingsWriteProvider
            | M365MailMessageMoveWriteProvider
            | M365MailMessageReadStateWriteProvider
            | M365MailMessageDeleteWriteProvider
            | M365ManagedDeviceWriteProvider
            | None
        ) = None,
    ) -> None:
        self.store = store
        self.settings = settings
        self.provider = provider or provider_from_settings(settings)
        self.registry = registry or default_registry
        self.collector_service = collector_service
        self.halopsa_client = halopsa_client
        self.hudu_client = hudu_client
        self.rmm_provider = rmm_provider or rmm_provider_from_settings(settings, store)
        self.connectwise_client = connectwise_client
        self.syncro_client = syncro_client
        self.servicenow_client = servicenow_client
        self.autotask_client = autotask_client
        self.itglue_client = itglue_client
        self.confluence_client = confluence_client
        self.notion_client = notion_client
        self.sharepoint_client = sharepoint_client
        self.timezest_client = timezest_client
        self.scalepad_client = scalepad_client
        self.m365_client = m365_client
        configured_communication = ConfiguredCommunicationProvider(settings)
        self.communication_provider = communication_provider or configured_communication
        self.communication_sender: CommunicationSender | None = communication_sender or (
            configured_communication
            if communication_provider is None
            else communication_provider
            if hasattr(communication_provider, "send")
            else None  # type: ignore[assignment]
        )
        self.provider_configured = (
            bool(provider_configured) and not isinstance(self.provider, DeterministicLocalProvider)
            if provider_configured is not None
            else _provider_is_configured(settings, self.provider)
        )

    def list(self) -> list[SmartActionManifest]:
        return [action.manifest for action in self.registry.list()]

    def describe(self, action_id: str) -> SmartActionManifest:
        return self.registry.get(action_id).manifest

    def invoke(
        self,
        action_id: str,
        payload: dict[str, object],
        actor: str | None,
        *,
        confirm: bool = False,
        client_id: str | None = None,
        approval_expiry_seconds: int | None = None,
        require_approval: bool = False,
    ) -> ActionResult:
        action = self.registry.get(action_id)
        normalized_id = action.manifest.action_id
        if approval_expiry_seconds is not None and (
            isinstance(approval_expiry_seconds, bool)
            or not isinstance(approval_expiry_seconds, int)
            or approval_expiry_seconds < 1
            or approval_expiry_seconds > MAX_APPROVAL_EXPIRY_SECONDS
        ):
            raise ValueError(
                "approval expiry must be between 1 and "
                f"{MAX_APPROVAL_EXPIRY_SECONDS} seconds"
            )
        effective_approval_expiry_seconds = (
            min(approval_expiry_seconds, action.manifest.approval_expiry_seconds)
            if approval_expiry_seconds is not None
            else action.manifest.approval_expiry_seconds
        )
        normalized_payload = dict(payload)
        digest = _payload_digest(normalized_payload)
        effective_client_id = _effective_client_id(self.store, normalized_payload, client_id)
        context = self._context(actor, effective_client_id)
        if not actor or not actor.strip():
            result = ActionResult(status="not_authorized", error_detail="actor is required")
            run = self.store.create_smart_action_run(
                normalized_id,
                "",
                result.status,
                digest,
                result.output,
                result.evidence,
                client_id=effective_client_id,
            )
            if run.id is None:
                raise RuntimeError("smart action run was not persisted")
            self.store.add_audit_event(
                "smart_action.invoked",
                str(run.id),
                f"{normalized_id} unauthorized",
                client_id=effective_client_id,
            )
            self.store.add_audit_event(
                "smart_action.completed",
                str(run.id),
                f"{normalized_id} not_authorized",
                client_id=effective_client_id,
            )
            self._record_execution(
                normalized_id,
                run.id,
                normalized_payload,
                result,
                actor="",
                client_id=effective_client_id,
                trigger_source="invoke",
            )
            return _result_with_run(result, run.id)

        if action.manifest.requires_approval or require_approval:
            draft = _safe_run(action, context, normalized_payload)
            if draft.status != "success":
                return self._persist_result(
                    normalized_id,
                    actor,
                    digest,
                    draft,
                    confirm=confirm,
                    client_id=effective_client_id,
                    payload=normalized_payload,
                )
            pending_output = cast(dict[str, object], redact_value({**draft.output, "approval_required": True}))
            run, approval = self.store.create_pending_smart_action(
                normalized_id,
                actor,
                digest,
                pending_output,
                draft.evidence,
                {
                    "action_id": normalized_id,
                    "payload": normalized_payload,
                },
                client_id=effective_client_id,
                expires_in_seconds=effective_approval_expiry_seconds,
            )
            if approval.id is None:
                raise RuntimeError("smart action approval was not persisted")
            pending_result = ActionResult(
                status="pending_approval",
                output=pending_output,
                evidence=draft.evidence,
                approval_id=approval.id,
            )
            self._record_execution(
                normalized_id,
                run.id,
                normalized_payload,
                pending_result,
                actor=actor,
                client_id=effective_client_id,
                trigger_source="invoke",
            )
            return _result_with_run(pending_result, run.id or 0)

        result = _safe_run(action, context, normalized_payload)
        return self._persist_result(
            normalized_id,
            actor,
            digest,
            result,
            confirm=confirm,
            client_id=effective_client_id,
            payload=normalized_payload,
        )

    def complete_approval(
        self,
        approval_id: int,
        *,
        approver: str | None = None,
        approver_role: Role | None = None,
    ) -> ActionResult | None:
        approval = self.store.get_approval_request(approval_id)
        if approval is None or not approval.action_type.startswith("smart_action:"):
            return None
        run = next(
            (candidate for candidate in self.store.list_smart_action_runs() if candidate.approval_id == approval_id),
            None,
        )
        if run is None or run.id is None:
            raise KeyError(f"smart action run for approval {approval_id} not found")
        if not approver or not approver.strip():
            raise PermissionError("approver is required")
        if approver_role is None or approver_role < Role.TECHNICIAN:
            raise PermissionError("approver must have technician or admin authority")
        if approver == run.actor:
            raise PermissionError("requesting actor cannot approve its own smart action")
        action_id = approval.action_type.removeprefix("smart_action:")
        if approval.status == "expired":
            expired_result = ActionResult(
                status="rejected",
                output=_json_object(run.output_json),
                evidence=_json_list(run.evidence_json),
                error_detail="approval expired",
                run_id=run.id,
                approval_id=approval_id,
            )
            self._record_execution(
                action_id,
                run.id,
                {"approval_id": approval_id, "approval_status": approval.status},
                expired_result,
                actor=run.actor,
                client_id=approval.client_id,
                trigger_source="approval_expiry",
                step_kind="smart_action.approval_expired",
            )
            return expired_result
        if approval.status == "rejected":
            self.store.complete_smart_action_run(
                run.id,
                "rejected",
                _json_object(run.output_json),
                _json_list(run.evidence_json),
                approval_id=approval_id,
                approver_id=approver,
                _smart_action_capability=SMART_ACTION_APPROVAL_CAPABILITY,
            )
            self.store.add_audit_event(
                "smart_action.completed",
                str(run.id),
                f"{action_id} rejected",
                client_id=approval.client_id,
                approver_id=approver,
            )
            rejected_result = ActionResult(
                status="rejected",
                output=_json_object(run.output_json),
                evidence=_json_list(run.evidence_json),
                run_id=run.id,
                approval_id=approval_id,
            )
            self._record_execution(
                action_id,
                run.id,
                {"approval_id": approval_id, "approval_status": approval.status},
                rejected_result,
                actor=run.actor,
                client_id=approval.client_id,
                trigger_source="approval_completion",
                step_kind="smart_action.approval_completed",
            )
            return rejected_result
        if approval.status != "approved":
            return ActionResult(
                status="pending_approval",
                output=_json_object(run.output_json),
                evidence=_json_list(run.evidence_json),
                run_id=run.id,
                approval_id=approval_id,
            )
        if run.status != "pending_approval":
            return ActionResult(
                status=_stored_action_status(run.status),
                output=_json_object(run.output_json),
                evidence=_json_list(run.evidence_json),
                run_id=run.id,
                approval_id=approval_id,
            )
        try:
            action = self.registry.get(action_id)
        except KeyError:
            action = None
        if action is not None:
            _require_action_role(action.manifest, approver_role)
        payload = _json_object(approval.payload_json).get("payload")
        if not isinstance(payload, dict):
            result = _failed("smart action approval payload is malformed")
        else:
            payload = {**payload, "_approval_completed": True}
            if action is None:
                result = _failed(f"smart action {action_id} is not registered")
            else:
                result = _safe_run(action, self._context(run.actor, approval.client_id), payload)
        if result.status == "success":
            result = ActionResult(
                status=result.status,
                output={**result.output, "approved": True},
                evidence=result.evidence,
                error_detail=result.error_detail,
            )
        result = _redact_result(result)
        self.store.complete_smart_action_run(
            run.id,
            result.status,
            result.output,
            result.evidence,
            approval_id=approval_id,
            approver_id=approver,
            _smart_action_capability=SMART_ACTION_APPROVAL_CAPABILITY,
        )
        self.store.add_audit_event(
            "smart_action.completed",
            str(run.id),
            f"{action_id} {result.status}",
            client_id=approval.client_id,
            approver_id=approver,
        )
        final_result = ActionResult(
            status=result.status,
            output=result.output,
            evidence=result.evidence,
            error_detail=result.error_detail,
            approval_id=approval_id,
        )
        self._record_execution(
            action_id,
            run.id,
            {"approval_id": approval_id, "approval_status": approval.status},
            final_result,
            actor=run.actor,
            client_id=approval.client_id,
            trigger_source="approval_completion",
            step_kind="smart_action.approval_completed",
        )
        return _result_with_run(final_result, run.id)

    def update_approval(
        self,
        approval_id: int,
        status: str,
        comment: str = "",
        *,
        approver: str | None = None,
        approver_role: Role | None = None,
    ) -> ApprovalRequest:
        approval = self.store.get_approval_request(approval_id)
        if approval is None:
            raise KeyError(approval_id)
        if approval.action_type.startswith("smart_action:"):
            if not approver or not approver.strip():
                raise PermissionError("approver is required")
            if approver_role is None or approver_role < Role.TECHNICIAN:
                raise PermissionError("approver must have technician or admin authority")
            if status == "approved":
                try:
                    _require_action_role(
                        self.registry.get(approval.action_type.removeprefix("smart_action:")).manifest,
                        approver_role,
                    )
                except KeyError:
                    pass
            updated = self.store.update_approval_request(
                approval_id,
                status,
                comment,
                approver_id=approver,
                _smart_action_capability=SMART_ACTION_APPROVAL_CAPABILITY,
            )
            self.complete_approval(
                approval_id,
                approver=approver,
                approver_role=approver_role,
            )
            return self.store.get_approval_request(approval_id) or updated
        return self.store.update_approval_request(
            approval_id,
            status,
            comment,
            approver_id=approver,
        )

    def _context(self, actor: str | None, client_id: str | None) -> ActionContext:
        return ActionContext(
            store=self.store,
            settings=self.settings,
            provider=self.provider,
            actor=actor or "",
            client_id=client_id,
            provider_available=(
                self.provider_configured
                or isinstance(self.provider, DeterministicLocalProvider)
            ),
            collector_service=self.collector_service,
            halopsa_client=self.halopsa_client,
            hudu_client=self.hudu_client,
            communication_provider=self.communication_provider,
            communication_sender=self.communication_sender,
            rmm_provider=self.rmm_provider,
            connectwise_client=self.connectwise_client,
            syncro_client=self.syncro_client,
            servicenow_client=self.servicenow_client,
            autotask_client=self.autotask_client,
            itglue_client=self.itglue_client,
            confluence_client=self.confluence_client,
            notion_client=self.notion_client,
            sharepoint_client=self.sharepoint_client,
            timezest_client=self.timezest_client,
            scalepad_client=self.scalepad_client,
            m365_client=self.m365_client,
        )

    def _persist_result(
        self,
        action_id: str,
        actor: str,
        digest: str,
        result: ActionResult,
        *,
        confirm: bool,
        client_id: str | None = None,
        payload: dict[str, object] | None = None,
    ) -> ActionResult:
        safe_result = _redact_result(result)
        run = self.store.create_smart_action_run(
            action_id,
            actor,
            result.status,
            digest,
            safe_result.output,
            safe_result.evidence,
            client_id=client_id,
        )
        if run.id is None:
            raise RuntimeError("smart action run was not persisted")
        self.store.add_audit_event(
            "smart_action.invoked",
            str(run.id),
            f"{action_id} status={result.status} confirmed={confirm}",
            client_id=client_id,
        )
        self.store.add_audit_event(
            "smart_action.completed",
            str(run.id),
            f"{action_id} {result.status}",
            client_id=client_id,
        )
        self._record_execution(
            action_id,
            run.id,
            payload if payload is not None else {},
            result=safe_result,
            actor=actor,
            client_id=client_id,
            trigger_source="invoke",
        )
        return _result_with_run(safe_result, run.id)

    def _record_execution(
        self,
        action_id: str,
        run_id: int | None,
        payload: dict[str, object],
        result: ActionResult,
        *,
        actor: str,
        client_id: str | None,
        trigger_source: str,
        step_kind: str = "smart_action.invoke",
    ) -> None:
        """Record the run for observability; never changes the run outcome."""
        step = StepRecord(
            kind=step_kind,
            name=action_id,
            status=result.status,
            input=payload,
            output=result.output,
            error_detail=result.error_detail,
        )
        artifacts: tuple[ArtifactRecord, ...] = ()
        if result.evidence:
            artifacts = (
                ArtifactRecord(
                    name="evidence.json",
                    media_type="application/json",
                    content=json.dumps(
                        redact_value(result.evidence),
                        sort_keys=True,
                        separators=(",", ":"),
                        default=str,
                    ).encode("utf-8"),
                    step_ordinal=None,
                ),
            )
        ExecutionRecorder(self.store).record_execution(
            run_kind="smart_action",
            source_run_id=run_id,
            actor=actor,
            status=result.status,
            trigger_source=trigger_source,
            client_id=client_id,
            metadata={
                **provider_metadata(self.settings, self.provider),
            },
            steps=(step,),
            artifacts=artifacts,
        )


def _safe_run(action: SmartAction, context: ActionContext, payload: dict[str, object]) -> ActionResult:
    try:
        return action.run(context, payload)
    except Exception as exc:
        return _failed(f"action failed: {exc}")


def _communication_message(
    context: ActionContext, payload: dict[str, object]
) -> CommunicationMessage | ActionResult:
    channel = payload.get("channel")
    recipient = payload.get("recipient", "")
    body = payload.get("body")
    subject = payload.get("subject", "")
    ticket_id = payload.get("ticket_id")
    if channel not in {"ticket_note", "email", "teams", "slack", "sms"}:
        return _failed("channel must be one of ticket_note, email, teams, slack, or sms")
    if not isinstance(body, str) or not body.strip() or len(body) > 10_000:
        return _failed("body must be a non-empty string of at most 10000 characters")
    if not isinstance(subject, str) or len(subject) > 500:
        return _failed("subject must be a string of at most 500 characters")
    if channel != "ticket_note" and (
        not isinstance(recipient, str) or not recipient.strip() or len(recipient) > 320
    ):
        return _failed("recipient must be a non-empty string of at most 320 characters")
    if channel == "ticket_note" and not isinstance(ticket_id, str):
        return _failed("ticket_note requires ticket_id")
    if ticket_id is not None:
        if not isinstance(ticket_id, str) or not ticket_id.strip():
            return _failed("ticket_id must be a non-empty string when provided")
        if _ticket_from_payload(context.store, payload, context.client_id) is None:
            return _failed("ticket_id must identify an existing ticket")
    elif context.client_id is None:
        return _failed("communication delivery requires a tenant or ticket_id")
    if channel == "sms" and subject:
        return _failed("subject is not supported for sms")
    return CommunicationMessage(
        channel=cast("CommunicationChannel", channel),
        recipient=(recipient.strip() if isinstance(recipient, str) else f"ticket:{ticket_id}"),
        body=body.strip(),
        subject=subject.strip(),
        client_id=context.client_id,
        ticket_id=ticket_id.strip() if isinstance(ticket_id, str) else None,
    )


def _rmm_script_request(
    payload: dict[str, object],
) -> tuple[str, str, dict[str, str]] | ActionResult:
    script_id = payload.get("script_id")
    device_id = payload.get("device_id")
    arguments = payload.get("arguments", {})
    if not isinstance(script_id, str) or not script_id.strip() or len(script_id.strip()) > 200:
        return _failed("script_id must be a non-empty string of at most 200 characters")
    if not isinstance(device_id, str) or not device_id.strip() or len(device_id.strip()) > 200:
        return _failed("device_id must be a non-empty string of at most 200 characters")
    if not isinstance(arguments, dict) or len(arguments) > 20:
        return _failed("arguments must be an object with at most 20 entries")
    normalized: dict[str, str] = {}
    for key, value in arguments.items():
        if (
            not isinstance(key, str)
            or not key.strip()
            or len(key) > 100
            or not isinstance(value, str)
            or len(value) > 500
            or any(ord(character) < 32 for character in key + value)
        ):
            return _failed("script arguments must be bounded text values")
        normalized[key.strip()] = value
    return script_id.strip(), device_id.strip(), normalized


def _ticket_from_payload(
    store: Store, payload: dict[str, object], client_id: str | None = None
) -> Ticket | None:
    ticket_id = payload.get("ticket_id")
    if not isinstance(ticket_id, str) or not ticket_id.strip():
        return None
    return store.get_ticket(ticket_id.strip(), client_id)


def _sources_for_ticket(context: ActionContext, ticket: Ticket) -> list[SourceReference]:
    return retrieve_sources(
        ticket,
        context.settings.allowed_doc_root,
        context.store,
        context.settings,
        client_id=ticket.client_id,
    )


def _ticket_evidence(ticket: Ticket, fields: list[str]) -> dict[str, object]:
    return {"type": "ticket", "ticket_id": ticket.id, "fields": fields}


def _source_citation(source: SourceReference) -> dict[str, object]:
    citation: dict[str, object] = {
        "type": "knowledge",
        "title": source.title,
        "path": source.path,
        "excerpt": source.excerpt,
    }
    if source.document_id is not None:
        citation["document_id"] = source.document_id
    if source.chunk_id is not None:
        citation["chunk_id"] = source.chunk_id
    return citation


def _provider_id(context: ActionContext) -> str:
    configured = context.settings.local_model_provider.strip()
    return configured or "configured-provider"


def _provider_is_ai_assisted(context: ActionContext) -> bool:
    """Expose whether the current result used a model rather than deterministic fallback."""
    return context.provider is not None and not isinstance(
        context.provider, DeterministicLocalProvider
    )


def _positive_thresholds(value: object) -> dict[str, int] | None:
    if not isinstance(value, dict) or not value:
        return None
    thresholds: dict[str, int] = {}
    for priority, minutes in value.items():
        if (
            not isinstance(priority, str)
            or not priority.strip()
            or isinstance(minutes, bool)
            or not isinstance(minutes, int)
            or minutes <= 0
        ):
            return None
        thresholds[priority.strip().lower()] = minutes
    return thresholds


def _parse_ticket_timestamp(value: str) -> datetime | None:
    if not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _workload_value(candidate: dict[str, object]) -> float:
    value = candidate.get("workload", 0)
    return float(cast(int | float, value))


def _provider_is_configured(settings: Settings, provider: ModelProvider) -> bool:
    return settings.allow_llm_inference and not isinstance(provider, DeterministicLocalProvider)


def _provider_not_configured(detail: str = "") -> ActionResult:
    return ActionResult(
        status="provider_not_configured",
        error_detail=detail or "no local model provider is configured for this action",
    )


def _failed(detail: str) -> ActionResult:
    return ActionResult(status="failed", error_detail=detail)


def _require_action_role(manifest: SmartActionManifest, approver_role: Role | None) -> None:
    required_role = Role.ADMIN if manifest.required_role.strip().lower() == "admin" else Role.TECHNICIAN
    if approver_role is None or approver_role < required_role:
        raise PermissionError(f"{manifest.action_id} approval requires {required_role.label()} authority")


def _stored_action_status(status: str) -> ActionStatus:
    if status == "success":
        return "success"
    if status == "failed":
        return "failed"
    if status == "provider_not_configured":
        return "provider_not_configured"
    if status == "rejected":
        return "rejected"
    return "failed"


def _redact_result(result: ActionResult) -> ActionResult:
    output = redact_value(result.output)
    evidence = redact_value(result.evidence)
    return ActionResult(
        status=result.status,
        output=cast(dict[str, object], output),
        evidence=cast(list[dict[str, object]], evidence),
        error_detail=result.error_detail,
        run_id=result.run_id,
        approval_id=result.approval_id,
    )


def _effective_client_id(
    store: Store, payload: dict[str, object], client_id: str | None
) -> str | None:
    if client_id and client_id.strip():
        return client_id.strip()
    ticket_id = payload.get("ticket_id")
    if not isinstance(ticket_id, str) or not ticket_id.strip():
        return None
    ticket = store.get_ticket(ticket_id.strip())
    return ticket.client_id if ticket is not None else None


def _result_with_run(result: ActionResult, run_id: int) -> ActionResult:
    return ActionResult(
        status=result.status,
        output=result.output,
        evidence=result.evidence,
        error_detail=result.error_detail,
        run_id=run_id,
        approval_id=result.approval_id,
    )


def _payload_digest(payload: dict[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _tokens(value: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]{3,}", value.lower()))


def _json_object(payload_json: str) -> dict[str, object]:
    try:
        payload = json.loads(payload_json)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _json_list(payload_json: str) -> list[dict[str, object]]:
    try:
        payload = json.loads(payload_json)
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, list):
        return []
    return [item for item in payload if isinstance(item, dict)]
