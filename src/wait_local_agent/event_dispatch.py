"""Bounded, deterministic dispatch for externally delivered automation events."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import cast

from wait_local_agent.agents import (
    SUPPORTED_EVENT_TYPES,
    AgentService,
)
from wait_local_agent.client_scope import AllClients
from wait_local_agent.models import (
    DEFAULT_EVENT_MAX_RETRIES,
    DEFAULT_EVENT_RETRY_DELAY_SECONDS,
    EVENT_RETRY_BATCH_SIZE,
    MAX_EVENT_RETRY_DELAY_SECONDS,
    EventDelivery,
    utc_now,
)
from wait_local_agent.msp_playbooks import msp_playbook_subscription_input, run_msp_playbook
from wait_local_agent.reports.renderers import redact_text
from wait_local_agent.store import _QUARANTINE_CLIENT_ID, Store, _normalize_client_id


@dataclass(frozen=True)
class EventDispatchResult:
    delivery: EventDelivery
    duplicate: bool
    matched_agent_ids: list[str]
    run_ids: list[int]
    matched_playbook_ids: list[str]
    playbook_run_ids: list[str]
    errors: list[str]


class EventDispatchError(ValueError):
    """Raised when an event cannot be safely accepted for dispatch."""


LOGGER = logging.getLogger(__name__)


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
        max_retries: int = DEFAULT_EVENT_MAX_RETRIES,
        retry_delay_seconds: int = DEFAULT_EVENT_RETRY_DELAY_SECONDS,
    ) -> EventDispatchResult:
        self._validate_request(
            event_type=event_type,
            entity_type=entity_type,
            entity_id=entity_id,
            payload=payload,
            idempotency_key=idempotency_key,
        )
        requested_client_id = _normalize_client_id(client_id)
        ticket = self.store.get_ticket(
            entity_id,
            client_id=requested_client_id if requested_client_id is not None else AllClients(),
            include_quarantine=True,
        )
        if ticket is None:
            raise LookupError(entity_id)
        if ticket.client_id == _QUARANTINE_CLIENT_ID:
            LOGGER.warning("Skipping event dispatch for quarantined ticket %s", entity_id)
            return _quarantine_result(
                idempotency_key=idempotency_key,
                event_type=event_type,
                entity_type=entity_type,
                entity_id=entity_id,
                payload=payload,
                client_id=ticket.client_id,
            )
        effective_client_id = requested_client_id or _normalize_client_id(ticket.client_id)
        delivery, created = self.store.create_event_delivery(
            idempotency_key=idempotency_key,
            event_type=event_type,
            entity_type=entity_type,
            entity_id=entity_id,
            payload=payload,
            client_id=effective_client_id,
            max_retries=max_retries,
            retry_delay_seconds=retry_delay_seconds,
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

        return self._process_delivery(
            delivery,
            payload=payload,
            client_id=effective_client_id,
            actor=actor,
            retry_only=False,
        )

    def retry(
        self,
        delivery_id: int,
        *,
        client_id: str | None = None,
        actor: str = "operator",
    ) -> EventDispatchResult:
        scope = client_id if client_id is not None else AllClients()
        existing = self.store.get_event_delivery(delivery_id, client_id=scope)
        if existing is None:
            raise KeyError(delivery_id)
        if existing.entity_type.strip().lower() == "ticket":
            ticket = self.store.get_ticket(
                existing.entity_id,
                client_id=AllClients(),
                include_quarantine=True,
            )
            if ticket is not None and ticket.client_id == _QUARANTINE_CLIENT_ID:
                LOGGER.warning("Skipping event retry for quarantined ticket %s", existing.entity_id)
                return _quarantine_result(
                    idempotency_key=existing.idempotency_key,
                    event_type=existing.event_type,
                    entity_type=existing.entity_type,
                    entity_id=existing.entity_id,
                    payload=self.store.get_event_delivery_payload(delivery_id, client_id=scope),
                    client_id=existing.client_id,
                    delivery=existing,
                )
        delivery = self.store.claim_event_delivery_retry(delivery_id, client_id=scope)
        effective_client_id = delivery.client_id
        payload = self.store.get_event_delivery_payload(
            delivery_id,
            client_id=effective_client_id if effective_client_id is not None else AllClients(),
        )
        return self._process_delivery(
            delivery,
            payload=payload,
            client_id=effective_client_id,
            actor=actor,
            retry_only=True,
        )

    def retry_due(self, *, now: str | None = None) -> list[EventDispatchResult]:
        """Retry a bounded batch of failed deliveries whose due time has arrived."""
        results: list[EventDispatchResult] = []
        for delivery_id in self.store.list_due_event_delivery_ids(
            now=now,
            limit=EVENT_RETRY_BATCH_SIZE,
        ):
            try:
                results.append(self.retry(delivery_id, actor="event-retry-worker"))
            except (KeyError, ValueError) as exc:
                # Another worker or an operator may have claimed the row first.
                self.store.add_audit_event(
                    "event.retry_skipped",
                    str(delivery_id),
                    redact_text(f"automatic event retry skipped: {exc}"),
                )
        return results

    def _process_delivery(
        self,
        delivery: EventDelivery,
        *,
        payload: dict[str, object],
        client_id: str | None,
        actor: str,
        retry_only: bool,
    ) -> EventDispatchResult:
        event_type = delivery.event_type
        entity_type = delivery.entity_type
        entity_id = delivery.entity_id

        event_context = {
            **payload,
            "event_type": event_type,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "ticket_id": entity_id,
        }
        if client_id is not None:
            event_context["client_id"] = client_id
        matched_agent_ids = _string_list(delivery.agent_ids_json) if retry_only else []
        run_ids = _int_list(delivery.run_ids_json) if retry_only else []
        matched_playbook_ids = _string_list(delivery.playbook_ids_json) if retry_only else []
        playbook_run_ids = _string_list(delivery.playbook_run_ids_json) if retry_only else []
        errors: list[str] = []
        attempts = _attempts_from_json(delivery.agent_attempts_json)
        playbook_attempts = _attempts_from_json(delivery.playbook_attempts_json)
        if retry_only and not attempts:
            attempts = {
                agent_id: {"status": "failed", "error": "", "run_ids": []}
                for agent_id in matched_agent_ids
            }
        retryable_ids = {
            agent_id
            for agent_id, attempt in attempts.items()
            if attempt.get("status") in {"failed", "blocked"}
        }
        found_retryable_ids: set[str] = set()
        candidates = []
        for definition in self.store.list_agent_definitions():
            if not definition.enabled or definition.trigger != "event":
                continue
            if definition.entity_type != entity_type:
                continue
            if definition.client_id is not None and definition.client_id != client_id:
                continue
            if not _matches_filters(definition.filters, event_context):
                continue
            if not retry_only:
                matched_agent_ids.append(definition.id)
                candidates.append(definition)
                continue
            if attempts.get(definition.id, {}).get("status") in {"failed", "blocked"}:
                found_retryable_ids.add(definition.id)
                candidates.append(definition)

        if retry_only and not matched_agent_ids:
            matched_agent_ids = [definition.id for definition in candidates]
        if retry_only:
            for agent_id in sorted(retryable_ids - found_retryable_ids):
                error = f"{agent_id}: agent is no longer eligible for retry"
                attempts[agent_id] = {"status": "failed", "error": error, "run_ids": []}
                errors.append(error)

        pending = candidates
        completed_agents = {
            agent_id
            for agent_id, attempt in attempts.items()
            if attempt.get("status") == "completed"
        }
        while pending:
            progressed = False
            next_pending = []
            for definition in pending:
                if not retry_only and definition.run_once_per_entity and self.store.has_event_agent_run(
                    agent_id=definition.id,
                    event_type=event_type,
                    entity_id=entity_id,
                    client_id=client_id if client_id is not None else AllClients(),
                ):
                    if self.store.has_completed_event_agent_run(
                        agent_id=definition.id,
                        event_type=event_type,
                        entity_id=entity_id,
                        client_id=client_id if client_id is not None else AllClients(),
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
                        client_id=client_id if client_id is not None else AllClients(),
                    )
                ]
                if unmet:
                    next_pending.append((definition, unmet))
                    continue
                scoped_definition = definition
                if scoped_definition.client_id is None and client_id is not None:
                    scoped_definition = replace(scoped_definition, client_id=client_id)
                try:
                    attempts[definition.id] = {"status": "running", "error": "", "run_ids": []}
                    result = self.agent_service.run(
                        scoped_definition,
                        entity_id=entity_id,
                        actor=actor,
                        input_payload=event_context,
                    )
                    run_ids.append(result.run_id)
                    attempts[definition.id] = {
                        "status": "completed" if result.status == "completed" else "pending",
                        "error": "",
                        "run_ids": [result.run_id],
                    }
                    if result.status == "completed":
                        completed_agents.add(definition.id)
                    progressed = True
                except Exception as exc:  # one bad agent must not block others
                    error = redact_text(f"{definition.id}: {exc}")
                    attempts[definition.id] = {"status": "failed", "error": error, "run_ids": []}
                    errors.append(error)
                    progressed = True
            if not progressed:
                for definition, unmet in next_pending:
                    error = redact_text(
                        f"{definition.id}: dependency not completed: {', '.join(unmet)}"
                    )
                    attempts[definition.id] = {"status": "blocked", "error": error, "run_ids": []}
                    errors.append(
                        error
                    )
                break
            pending = [definition for definition, _unmet in next_pending]

        subscriptions = (
            self.store.list_msp_playbook_subscriptions(client_id, event_type=event_type)
            if client_id is not None
            else []
        )
        for subscription in subscriptions:
            if not subscription.enabled:
                continue
            previous = playbook_attempts.get(subscription.id, {})
            if retry_only and previous.get("status") not in {"failed", "blocked"}:
                continue
            if subscription.id not in matched_playbook_ids:
                matched_playbook_ids.append(subscription.id)
            try:
                playbook_attempts[subscription.id] = {"status": "running", "error": "", "run_ids": []}
                playbook_result = run_msp_playbook(
                    self.store,
                    subscription.playbook_id,
                    ticket_id=entity_id,
                    client_id=client_id,
                    actor=actor,
                    trigger_source=f"event:{event_type}",
                    input_payload=msp_playbook_subscription_input(subscription, event_context),
                    tool_executor=self.agent_service.smart_actions,
                    smart_action_service=self.agent_service.smart_actions,
                )
                playbook_run_id = str(playbook_result["run_id"])
                playbook_run_ids.append(playbook_run_id)
                result_status = str(playbook_result.get("status", "failed"))
                attempt_status = "completed" if result_status == "completed" else "pending"
                playbook_attempts[subscription.id] = {
                    "status": attempt_status,
                    "error": "" if attempt_status == "completed" else "playbook requires review",
                    "run_ids": [playbook_run_id],
                }
            except Exception as exc:  # preserve one subscription failure explicitly.
                error = redact_text(f"{subscription.id}: {exc}")
                playbook_attempts[subscription.id] = {"status": "failed", "error": error, "run_ids": []}
                errors.append(error)

        status = "failed" if errors else "completed"
        next_retry_at = (
            _next_retry_at(delivery.retry_count, delivery.retry_delay_seconds)
            if status == "failed" and delivery.retry_count < delivery.max_retries
            else ""
        )
        delivery = self.store.update_event_delivery(
            delivery.id or 0,
            status=status,
            matched_agent_count=len(matched_agent_ids),
            agent_ids=matched_agent_ids,
            run_ids=run_ids,
            matched_playbook_count=len(matched_playbook_ids),
            playbook_ids=matched_playbook_ids,
            playbook_run_ids=playbook_run_ids,
            playbook_attempts=playbook_attempts,
            error_detail="; ".join(errors),
            agent_attempts=attempts,
            next_retry_at=next_retry_at,
        )
        self.store.add_audit_event(
            "event.retried" if retry_only else "event.processed",
            str(delivery.id),
            f"{event_type} dispatched to {len(matched_agent_ids)} agent(s) with status {status}",
            client_id=client_id,
        )
        return EventDispatchResult(
            delivery=delivery,
            duplicate=False,
            matched_agent_ids=matched_agent_ids,
            run_ids=run_ids,
            matched_playbook_ids=matched_playbook_ids,
            playbook_run_ids=playbook_run_ids,
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
            matched_playbook_ids=_string_list(delivery.playbook_ids_json),
            playbook_run_ids=_string_list(delivery.playbook_run_ids_json),
            errors=[delivery.error_detail] if delivery.error_detail else [],
        )


def _quarantine_result(
    *,
    idempotency_key: str,
    event_type: str,
    entity_type: str,
    entity_id: str,
    payload: dict[str, object],
    client_id: str | None,
    delivery: EventDelivery | None = None,
) -> EventDispatchResult:
    if delivery is None:
        delivery = EventDelivery(
            id=None,
            idempotency_key=idempotency_key,
            event_type=event_type,
            entity_type=entity_type,
            entity_id=entity_id,
            payload_json=json.dumps(payload, sort_keys=True),
            status="skipped_quarantine",
            matched_agent_count=0,
            agent_ids_json="[]",
            run_ids_json="[]",
            error_detail="ticket is quarantined pending client mapping",
            received_at=utc_now(),
            processed_at="",
            client_id=client_id,
        )
    return EventDispatchResult(
        delivery=delivery,
        duplicate=False,
        matched_agent_ids=[],
        run_ids=[],
        matched_playbook_ids=[],
        playbook_run_ids=[],
        errors=[],
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


def _attempts_from_json(payload_json: str) -> dict[str, dict[str, object]]:
    import json

    try:
        value = json.loads(payload_json)
    except json.JSONDecodeError:
        return {}
    if not isinstance(value, dict):
        return {}
    return {
        str(agent_id): dict(attempt)
        for agent_id, attempt in value.items()
        if isinstance(agent_id, str) and isinstance(attempt, dict)
    }


def _next_retry_at(retry_count: int, retry_delay_seconds: int = DEFAULT_EVENT_RETRY_DELAY_SECONDS) -> str:
    if isinstance(retry_delay_seconds, bool) or not isinstance(retry_delay_seconds, int):
        raise ValueError("event retry_delay_seconds must be an integer")
    if retry_delay_seconds < 1 or retry_delay_seconds > MAX_EVENT_RETRY_DELAY_SECONDS:
        raise ValueError(
            "event retry_delay_seconds must be between 1 and "
            f"{MAX_EVENT_RETRY_DELAY_SECONDS} seconds"
        )
    delay = min(
        retry_delay_seconds * (2**max(retry_count, 0)),
        MAX_EVENT_RETRY_DELAY_SECONDS,
    )
    return (datetime.now(UTC) + timedelta(seconds=delay)).isoformat()
