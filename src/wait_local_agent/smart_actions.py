from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Literal, Protocol, cast

from wait_local_agent.config import Settings
from wait_local_agent.models import ApprovalRequest, SourceReference, Ticket
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
from wait_local_agent.rmm import LocalCollectorRmmAdapter, RmmInventoryProvider
from wait_local_agent.services import classify_ticket
from wait_local_agent.store import SMART_ACTION_APPROVAL_CAPABILITY, Store

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
    ) -> None:
        self.store = store
        self.settings = settings
        self.provider = provider or provider_from_settings(settings)
        self.registry = registry or default_registry
        self.collector_service = collector_service
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
    ) -> ActionResult:
        action = self.registry.get(action_id)
        normalized_id = action.manifest.action_id
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
            steps=(step,),
            artifacts=artifacts,
        )


def _safe_run(action: SmartAction, context: ActionContext, payload: dict[str, object]) -> ActionResult:
    try:
        return action.run(context, payload)
    except Exception as exc:
        return _failed(f"action failed: {exc}")


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
