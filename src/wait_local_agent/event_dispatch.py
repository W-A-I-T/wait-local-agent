"""Bounded, deterministic dispatch for externally delivered automation events."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import cast

from wait_local_agent.agents import (
    SUPPORTED_EVENT_TYPES,
    AgentService,
)
from wait_local_agent.models import EventDelivery
from wait_local_agent.reports.renderers import redact_text
from wait_local_agent.store import Store, _normalize_client_id


@dataclass(frozen=True)
class EventDispatchResult:
    delivery: EventDelivery
    duplicate: bool
    matched_agent_ids: list[str]
    run_ids: list[int]
    errors: list[str]


class EventDispatchError(ValueError):
    """Raised when an event cannot be safely accepted for dispatch."""


class EventDispatcher:
    """Dispatch one event sequentially through the existing bounded agent runtime."""

    def __init__(self, store: Store, agent_service: AgentService) -> None:
        self.store = store
        self.agent_service = agent_service

    def dispatch(
        self,
        *,
        event_type: str,
        entity_type: str,
        entity_id: str,
        payload: dict[str, object],
        idempotency_key: str,
        client_id: str | None = None,
        actor: str = "webhook",
    ) -> EventDispatchResult:
        self._validate_request(
            event_type=event_type,
            entity_type=entity_type,
            entity_id=entity_id,
            payload=payload,
            idempotency_key=idempotency_key,
        )
        requested_client_id = _normalize_client_id(client_id)
        ticket = self.store.get_ticket(entity_id, client_id=requested_client_id)
        if ticket is None:
            raise LookupError(entity_id)
        effective_client_id = requested_client_id or _normalize_client_id(ticket.client_id)
        delivery, created = self.store.create_event_delivery(
            idempotency_key=idempotency_key,
            event_type=event_type,
            entity_type=entity_type,
            entity_id=entity_id,
            payload=payload,
            client_id=effective_client_id,
        )
        if not created:
            if (
                delivery.event_type != event_type
                or delivery.entity_type != entity_type
                or delivery.entity_id != entity_id
                or delivery.client_id != effective_client_id
            ):
                raise EventDispatchError("idempotency_key is already used for a different event")
            return self._result_from_delivery(delivery, duplicate=True)

        event_context = {
            **payload,
            "event_type": event_type,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "ticket_id": entity_id,
        }
        if effective_client_id is not None:
            event_context["client_id"] = effective_client_id
        matched_agent_ids: list[str] = []
        run_ids: list[int] = []
        errors: list[str] = []
        candidates = []
        for definition in self.store.list_agent_definitions():
            if not definition.enabled or definition.trigger != "event":
                continue
            if definition.entity_type != entity_type:
                continue
            if definition.client_id is not None and definition.client_id != effective_client_id:
                continue
            if not _matches_filters(definition.filters, event_context):
                continue
            matched_agent_ids.append(definition.id)
            candidates.append(definition)

        pending = candidates
        completed_agents: set[str] = set()
        while pending:
            progressed = False
            next_pending = []
            for definition in pending:
                if definition.run_once_per_entity and self.store.has_event_agent_run(
                    agent_id=definition.id,
                    event_type=event_type,
                    entity_id=entity_id,
                    client_id=effective_client_id,
                ):
                    if self.store.has_completed_event_agent_run(
                        agent_id=definition.id,
                        event_type=event_type,
                        entity_id=entity_id,
                        client_id=effective_client_id,
                    ):
                        completed_agents.add(definition.id)
                    progressed = True
                    continue
                unmet = [
                    dependency_id
                    for dependency_id in definition.depends_on_agent_ids
                    if dependency_id not in completed_agents
                    and not self.store.has_completed_event_agent_run(
                        agent_id=dependency_id,
                        event_type=event_type,
                        entity_id=entity_id,
                        client_id=effective_client_id,
                    )
                ]
                if unmet:
                    next_pending.append((definition, unmet))
                    continue
                scoped_definition = definition
                if scoped_definition.client_id is None and effective_client_id is not None:
                    scoped_definition = replace(scoped_definition, client_id=effective_client_id)
                try:
                    result = self.agent_service.run(
                        scoped_definition,
                        entity_id=entity_id,
                        actor=actor,
                        input_payload=event_context,
                    )
                    run_ids.append(result.run_id)
                    if result.status == "completed":
                        completed_agents.add(definition.id)
                    progressed = True
                except Exception as exc:  # noqa: BLE001 - one bad agent must not block others
                    errors.append(redact_text(f"{definition.id}: {exc}"))
                    progressed = True
            if not progressed:
                for definition, unmet in next_pending:
                    errors.append(
                        redact_text(
                            f"{definition.id}: dependency not completed: {', '.join(unmet)}"
                        )
                    )
                break
            pending = [definition for definition, _unmet in next_pending]

        status = "failed" if errors else "completed"
        delivery = self.store.update_event_delivery(
            delivery.id or 0,
            status=status,
            matched_agent_count=len(matched_agent_ids),
            agent_ids=matched_agent_ids,
            run_ids=run_ids,
            error_detail="; ".join(errors),
        )
        self.store.add_audit_event(
            "event.processed",
            str(delivery.id),
            f"{event_type} dispatched to {len(matched_agent_ids)} agent(s) with status {status}",
            client_id=effective_client_id,
        )
        return EventDispatchResult(
            delivery=delivery,
            duplicate=False,
            matched_agent_ids=matched_agent_ids,
            run_ids=run_ids,
            errors=errors,
        )

    @staticmethod
    def _validate_request(
        *,
        event_type: str,
        entity_type: str,
        entity_id: str,
        payload: dict[str, object],
        idempotency_key: str,
    ) -> None:
        if event_type not in SUPPORTED_EVENT_TYPES:
            raise EventDispatchError("unsupported event_type")
        if entity_type != "ticket":
            raise EventDispatchError("only ticket event entities are supported")
        if not entity_id.strip() or len(entity_id) > 200:
            raise EventDispatchError("entity_id must contain 1-200 characters")
        if not isinstance(payload, dict):
            raise EventDispatchError("event payload must be an object")
        if not idempotency_key.strip() or len(idempotency_key) > 200:
            raise EventDispatchError("idempotency_key must contain 1-200 characters")

    @staticmethod
    def _result_from_delivery(delivery: EventDelivery, *, duplicate: bool) -> EventDispatchResult:
        return EventDispatchResult(
            delivery=delivery,
            duplicate=duplicate,
            matched_agent_ids=_string_list(delivery.agent_ids_json),
            run_ids=_int_list(delivery.run_ids_json),
            errors=[delivery.error_detail] if delivery.error_detail else [],
        )


def _matches_filters(filters: dict[str, object], event_context: dict[str, object]) -> bool:
    for key, expected in filters.items():
        if event_context.get(key) != expected:
            return False
    return True


def _string_list(payload_json: str) -> list[str]:
    value = _json_list(payload_json)
    return [item for item in value if isinstance(item, str)]


def _int_list(payload_json: str) -> list[int]:
    value = _json_list(payload_json)
    return [item for item in value if isinstance(item, int) and not isinstance(item, bool)]


def _json_list(payload_json: str) -> list[object]:
    import json

    try:
        value = json.loads(payload_json)
    except json.JSONDecodeError:
        return []
    return cast(list[object], value) if isinstance(value, list) else []
