from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Literal, Protocol, cast

from wait_local_agent.config import Settings
from wait_local_agent.models import SourceReference, Ticket
from wait_local_agent.providers import (
    DeterministicLocalProvider,
    ModelProvider,
    provider_from_settings,
)
from wait_local_agent.retrieval import retrieve_sources
from wait_local_agent.services import classify_ticket
from wait_local_agent.store import Store

ActionStatus = Literal[
    "success",
    "provider_not_configured",
    "not_authorized",
    "failed",
    "pending_approval",
    "rejected",
]


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


@dataclass
class ActionContext:
    store: Store
    settings: Settings
    provider: ModelProvider | None = None
    actor: str = ""
    client_id: str | None = None
    provider_available: bool = False


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
        ticket = _ticket_from_payload(context.store, payload)
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
        ticket = _ticket_from_payload(context.store, payload)
        if ticket is None:
            return _failed("ticket_id must identify an existing ticket")
        if not context.provider_available or context.provider is None:
            return _provider_not_configured()
        sources = _sources_for_ticket(context, ticket)
        try:
            summary = context.provider.summarize_ticket(ticket, sources)
            suggested_response = context.provider.draft_response(ticket, sources)
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
        ticket = _ticket_from_payload(context.store, payload)
        if ticket is None:
            return _failed("ticket_id must identify an existing ticket")
        if not context.provider_available or context.provider is None:
            return _provider_not_configured()
        sources = _sources_for_ticket(context, ticket)
        citations = [_source_citation(source) for source in sources]
        if not citations:
            return _failed("suggest-resolution requires retrieval citations")
        try:
            suggestion = context.provider.draft_response(ticket, sources)
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
        ticket = _ticket_from_payload(context.store, payload)
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
        ticket = _ticket_from_payload(context.store, payload)
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
    ) -> None:
        self.store = store
        self.settings = settings
        self.provider = provider or provider_from_settings(settings)
        self.registry = registry or default_registry
        self.provider_configured = (
            provider_configured
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
        context = self._context(actor, client_id)
        if not actor or not actor.strip():
            result = ActionResult(status="not_authorized", error_detail="actor is required")
            run = self.store.create_smart_action_run(
                normalized_id, "", result.status, digest, result.output, result.evidence
            )
            if run.id is None:
                raise RuntimeError("smart action run was not persisted")
            self.store.add_audit_event("smart_action.invoked", str(run.id), f"{normalized_id} unauthorized")
            self.store.add_audit_event("smart_action.completed", str(run.id), f"{normalized_id} not_authorized")
            return _result_with_run(result, run.id)

        if action.manifest.requires_approval:
            draft = _safe_run(action, context, normalized_payload)
            if draft.status != "success":
                return self._persist_result(normalized_id, actor, digest, draft, confirm=confirm)
            pending_output = {**draft.output, "approval_required": True}
            run = self.store.create_smart_action_run(
                normalized_id,
                actor,
                "pending_approval",
                digest,
                pending_output,
                draft.evidence,
            )
            if run.id is None:
                raise RuntimeError("smart action run was not persisted")
            approval = self.store.create_approval_request(
                str(run.id),
                f"smart_action:{normalized_id}",
                {
                    "run_id": run.id,
                    "action_id": normalized_id,
                    "payload": normalized_payload,
                },
                client_id=client_id,
            )
            if approval.id is None:
                raise RuntimeError("smart action approval was not persisted")
            self.store.set_smart_action_run_approval(run.id, approval.id)
            self.store.add_audit_event(
                "smart_action.invoked",
                str(run.id),
                f"{normalized_id} pending approval confirmed={confirm}",
                client_id=client_id,
            )
            return _result_with_run(
                ActionResult(
                    status="pending_approval",
                    output=pending_output,
                    evidence=draft.evidence,
                    approval_id=approval.id,
                ),
                run.id,
            )

        result = _safe_run(action, context, normalized_payload)
        return self._persist_result(normalized_id, actor, digest, result, confirm=confirm, client_id=client_id)

    def complete_approval(self, approval_id: int, *, approver: str | None = None) -> ActionResult | None:
        approval = self.store.get_approval_request(approval_id)
        if approval is None or not approval.action_type.startswith("smart_action:"):
            return None
        run = next(
            (candidate for candidate in self.store.list_smart_action_runs() if candidate.approval_id == approval_id),
            None,
        )
        if run is None or run.id is None:
            raise KeyError(f"smart action run for approval {approval_id} not found")
        action_id = approval.action_type.removeprefix("smart_action:")
        if approval.status == "rejected":
            self.store.complete_smart_action_run(
                run.id,
                "rejected",
                _json_object(run.output_json),
                _json_list(run.evidence_json),
            )
            self.store.add_audit_event(
                "smart_action.completed", str(run.id), f"{action_id} rejected", approver_id=approver
            )
            return ActionResult(
                status="rejected",
                output=_json_object(run.output_json),
                evidence=_json_list(run.evidence_json),
                run_id=run.id,
                approval_id=approval_id,
            )
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
                status=run.status
                if run.status in {"success", "failed", "provider_not_configured", "rejected"}
                else "failed",  # type: ignore[arg-type]
                output=_json_object(run.output_json),
                evidence=_json_list(run.evidence_json),
                run_id=run.id,
                approval_id=approval_id,
            )
        payload = _json_object(approval.payload_json).get("payload")
        if not isinstance(payload, dict):
            result = _failed("smart action approval payload is malformed")
        else:
            action = self.registry.get(action_id)
            result = _safe_run(action, self._context(run.actor, approval.client_id), payload)
        if result.status == "success":
            result = ActionResult(
                status=result.status,
                output={**result.output, "approved": True},
                evidence=result.evidence,
                error_detail=result.error_detail,
            )
        self.store.complete_smart_action_run(run.id, result.status, result.output, result.evidence)
        self.store.add_audit_event(
            "smart_action.completed",
            str(run.id),
            f"{action_id} {result.status}",
            client_id=approval.client_id,
            approver_id=approver,
        )
        return _result_with_run(
            ActionResult(
                status=result.status,
                output=result.output,
                evidence=result.evidence,
                error_detail=result.error_detail,
                approval_id=approval_id,
            ),
            run.id,
        )

    def _context(self, actor: str | None, client_id: str | None) -> ActionContext:
        return ActionContext(
            store=self.store,
            settings=self.settings,
            provider=self.provider,
            actor=actor or "",
            client_id=client_id,
            provider_available=self.provider_configured,
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
    ) -> ActionResult:
        run = self.store.create_smart_action_run(
            action_id,
            actor,
            result.status,
            digest,
            result.output,
            result.evidence,
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
        return _result_with_run(result, run.id)


def _safe_run(action: SmartAction, context: ActionContext, payload: dict[str, object]) -> ActionResult:
    try:
        return action.run(context, payload)
    except Exception as exc:
        return _failed(f"action failed: {exc}")


def _ticket_from_payload(store: Store, payload: dict[str, object]) -> Ticket | None:
    ticket_id = payload.get("ticket_id")
    if not isinstance(ticket_id, str) or not ticket_id.strip():
        return None
    return store.get_ticket(ticket_id.strip())


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
    if settings.allow_llm_inference:
        return True
    return not isinstance(provider, DeterministicLocalProvider)


def _provider_not_configured() -> ActionResult:
    return ActionResult(
        status="provider_not_configured",
        error_detail="no local model provider is configured for this action",
    )


def _failed(detail: str) -> ActionResult:
    return ActionResult(status="failed", error_detail=detail)


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
