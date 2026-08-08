from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Literal, Protocol, cast

from wait_local_agent.autotask import AutotaskReadProvider
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
from wait_local_agent.connectwise import ConnectWiseReadProvider
from wait_local_agent.itglue import ItGlueClientProtocol
from wait_local_agent.m365_graph import M365GraphReadProvider
from wait_local_agent.models import (
    DEFAULT_APPROVAL_EXPIRY_SECONDS,
    MAX_APPROVAL_EXPIRY_SECONDS,
    ApprovalRequest,
    SourceReference,
    Ticket,
)
from wait_local_agent.observability import ArtifactRecord, ExecutionRecorder, StepRecord
from wait_local_agent.providers import (
    DeterministicLocalProvider,
    ModelProvider,
    ProviderUnavailableError,
    provider_from_settings,
)
from wait_local_agent.rbac import Role
from wait_local_agent.reports.renderers import redact_text, redact_value
from wait_local_agent.retrieval import retrieve_sources
from wait_local_agent.rmm import (
    LocalCollectorRmmAdapter,
    RmmInventoryProvider,
    rmm_provider_from_settings,
)
from wait_local_agent.servicenow import ServiceNowReadProvider
from wait_local_agent.services import classify_ticket
from wait_local_agent.sharepoint import SharePointClientProtocol
from wait_local_agent.store import SMART_ACTION_APPROVAL_CAPABILITY, Store
from wait_local_agent.syncro import SyncroReadProvider

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
    connectwise_client: ConnectWiseReadProvider | None = None
    syncro_client: SyncroReadProvider | None = None
    servicenow_client: ServiceNowReadProvider | None = None
    autotask_client: AutotaskReadProvider | None = None
    itglue_client: ItGlueClientProtocol | None = None
    confluence_client: ConfluenceClientProtocol | None = None
    sharepoint_client: SharePointClientProtocol | None = None
    m365_client: M365GraphReadProvider | None = None
    halopsa_client: HaloPSAReadProvider | None = None
    hudu_client: HuduReadProvider | None = None
    communication_provider: CommunicationProvider | None = None
    communication_sender: CommunicationSender | None = None


class HaloPSAReadProvider(Protocol):
    def get_ticket(self, ticket_id: str) -> object:
        """Read one PSA ticket through the existing guarded client."""


class HuduReadProvider(Protocol):
    def list_articles(
        self,
        company_id: str | None = None,
        page: int = 1,
        page_size: int | None = None,
    ) -> object:
        """Read documentation articles through the existing guarded client."""


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
                },
                evidence=[{"type": "ticket_note", "ticket_id": message.ticket_id}],
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
        return ActionResult(
            status="success",
            output=asdict(delivery),
            evidence=[{"type": "communication_delivery", "channel": message.channel}],
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
                "ai_assisted": True,
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
                "ai_assisted": True,
                "provider_id": _provider_id(context),
                "estimate": self.manifest.estimated_minutes_saved,
            },
            evidence=citations,
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

        provider = context.m365_client or M365GraphClient(context.settings)
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

        provider = context.halopsa_client or HaloPSAClient(context.settings)
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

        provider = context.connectwise_client or ConnectWiseClient(context.settings)
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

        provider = context.syncro_client or SyncroClient(context.settings)
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

        provider = context.servicenow_client or ServiceNowClient(context.settings)
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

        provider = context.autotask_client or AutotaskClient(context.settings)
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
        description="Search tenant-scoped IT Glue document metadata through the existing read-only connector.",
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


class SharePointDocumentationSearchAction:
    manifest = SmartActionManifest(
        action_id="sharepoint-documentation-search",
        title="SharePoint documentation search",
        description="Search tenant-scoped SharePoint drive-item metadata through Microsoft Graph.",
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
            and query_value in str(getattr(item, "name", "")).casefold()
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
        KnowledgeSearchAction(),
        M365IdentityLookupAction(),
        RmmDeviceLookupAction(),
        RmmAlertLookupAction(),
        RmmScriptCatalogAction(),
        RmmScriptPreviewAction(),
        RmmScriptExecuteAction(),
        RmmScriptExecutionLookupAction(),
        HaloPSATicketLookupAction(),
        ConnectWiseTicketLookupAction(),
        SyncroTicketLookupAction(),
        ServiceNowIncidentLookupAction(),
        AutotaskTicketLookupAction(),
        HuduDocumentationSearchAction(),
        ItGlueDocumentationSearchAction(),
        ConfluenceDocumentationSearchAction(),
        SharePointDocumentationSearchAction(),
        SharePointDocumentationContentAction(),
        M365LiveContextAction(),
        CommunicationPreviewAction(),
        CommunicationSendAction(),
        TicketQualityAction(),
        TicketSentimentAction(),
        TicketEscalationAction(),
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
        halopsa_client: HaloPSAReadProvider | None = None,
        hudu_client: HuduReadProvider | None = None,
        communication_provider: CommunicationProvider | None = None,
        communication_sender: CommunicationSender | None = None,
        rmm_provider: RmmInventoryProvider | None = None,
        connectwise_client: ConnectWiseReadProvider | None = None,
        syncro_client: SyncroReadProvider | None = None,
        servicenow_client: ServiceNowReadProvider | None = None,
        autotask_client: AutotaskReadProvider | None = None,
        itglue_client: ItGlueClientProtocol | None = None,
        confluence_client: ConfluenceClientProtocol | None = None,
        sharepoint_client: SharePointClientProtocol | None = None,
        m365_client: M365GraphReadProvider | None = None,
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
        self.sharepoint_client = sharepoint_client
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

        if action.manifest.requires_approval:
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
        payload = _json_object(approval.payload_json).get("payload")
        if not isinstance(payload, dict):
            result = _failed("smart action approval payload is malformed")
        else:
            payload = {**payload, "_approval_completed": True}
            try:
                action = self.registry.get(action_id)
            except KeyError:
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
            provider_available=self.provider_configured,
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
            sharepoint_client=self.sharepoint_client,
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
                "provider": self.settings.local_model_provider or "deterministic",
                "model": self.settings.local_model_name,
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
