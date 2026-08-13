from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

import wait_local_agent.event_dispatch as event_dispatch_module
from wait_local_agent.agents import AgentExecutionResult, AgentService
from wait_local_agent.event_dispatch import (
    EventDispatcher,
    EventDispatchError,
    _attempts_from_json,
    _json_list,
    _next_retry_at,
)
from wait_local_agent.msp_playbooks import create_msp_playbook_subscription, update_msp_playbook_subscription
from wait_local_agent.smart_actions import SmartActionService
from wait_local_agent.store import Store


def _seed(store: Store, *, client_id: str | None = "acme") -> None:
    store.ingest_ticket_file(Path("examples/sample_tickets/tickets.json"))
    if client_id is not None:
        with store._connect() as connection:  # noqa: SLF001
            connection.execute("update tickets set client_id = ?", (client_id,))


def _event_agent(settings, store: Store, *, client_id: str | None = "acme"):
    service = AgentService(store, settings, SmartActionService(store, settings))
    definition = service.create(
        name="P1 event triage",
        description="Triage a newly created P1 ticket.",
        enabled=True,
        trigger="event",
        entity_type="ticket",
        filters={"event_type": "ticket.created", "priority": "P1"},
        enabled_tools=["ticket-triage"],
        steps=[{"tool_id": "ticket-triage", "payload": {}}],
        max_steps=1,
        execution_timeout_seconds=30,
        client_id=client_id,
    )
    return service, definition


def test_event_dispatch_matches_filters_redacts_and_is_idempotent(settings) -> None:
    store = Store(settings.data_path)
    _seed(store)
    service, definition = _event_agent(settings, store)
    dispatcher = EventDispatcher(store, service)

    first = dispatcher.dispatch(
        event_type="ticket.created",
        entity_type="ticket",
        entity_id="TCK-1001",
        payload={"priority": "P1", "api_token": "do-not-store"},
        idempotency_key="provider-event-1",
        client_id="acme",
    )

    assert first.duplicate is False
    assert first.delivery.status == "completed"
    assert first.matched_agent_ids == [definition.id]
    assert len(first.run_ids) == 1
    assert len(store.list_agent_runs(client_id="acme")) == 1
    assert "do-not-store" not in first.delivery.payload_json
    saved_run = store.get_agent_run(first.run_ids[0])
    assert saved_run is not None
    assert "do-not-store" not in saved_run.state_json

    duplicate = dispatcher.dispatch(
        event_type="ticket.created",
        entity_type="ticket",
        entity_id="TCK-1001",
        payload={"priority": "P1", "api_token": "changed"},
        idempotency_key="provider-event-1",
        client_id="acme",
    )
    assert duplicate.duplicate is True
    assert duplicate.run_ids == first.run_ids
    assert len(store.list_agent_runs(client_id="acme")) == 1

    with pytest.raises(EventDispatchError, match="different event"):
        dispatcher.dispatch(
            event_type="ticket.created",
            entity_type="ticket",
            entity_id="TCK-1002",
            payload={"priority": "P1"},
            idempotency_key="provider-event-1",
            client_id="acme",
        )

    second_key = dispatcher.dispatch(
        event_type="ticket.created",
        entity_type="ticket",
        entity_id="TCK-1001",
        payload={"priority": "P1"},
        idempotency_key="provider-event-2",
        client_id="acme",
    )
    assert second_key.matched_agent_ids == [definition.id]
    assert second_key.run_ids == []
    assert len(store.list_agent_runs(client_id="acme")) == 1


def test_event_dispatch_runs_tenant_scoped_playbook_subscription_once(settings) -> None:
    store = Store(settings.data_path)
    _seed(store)
    service = AgentService(store, settings, SmartActionService(store, settings))
    subscription = create_msp_playbook_subscription(
        store,
        "ticket-intake-review",
        event_type="ticket.created",
        client_id="acme",
        input_mapping={"priority": "priority"},
    )
    dispatcher = EventDispatcher(store, service)

    first = dispatcher.dispatch(
        event_type="ticket.created",
        entity_type="ticket",
        entity_id="TCK-1001",
        payload={"priority": "P1"},
        idempotency_key="playbook-event-1",
        client_id="acme",
    )

    assert first.matched_playbook_ids == [subscription.id]
    assert len(first.playbook_run_ids) == 1
    assert first.delivery.matched_playbook_count == 1
    assert json.loads(first.delivery.playbook_ids_json) == [subscription.id]
    assert json.loads(first.delivery.playbook_run_ids_json) == first.playbook_run_ids
    assert len(store.list_workflow_runs(client_id="acme")) == 6

    duplicate = dispatcher.dispatch(
        event_type="ticket.created",
        entity_type="ticket",
        entity_id="TCK-1001",
        payload={"priority": "changed"},
        idempotency_key="playbook-event-1",
        client_id="acme",
    )
    assert duplicate.duplicate is True
    assert duplicate.playbook_run_ids == first.playbook_run_ids
    assert len(store.list_workflow_runs(client_id="acme")) == 6

    update_msp_playbook_subscription(
        store,
        subscription.id,
        client_id="acme",
        enabled=False,
    )
    disabled = dispatcher.dispatch(
        event_type="ticket.created",
        entity_type="ticket",
        entity_id="TCK-1001",
        payload={"priority": "P1"},
        idempotency_key="playbook-event-2",
        client_id="acme",
    )
    assert disabled.matched_playbook_ids == []
    assert disabled.playbook_run_ids == []
    assert len(store.list_workflow_runs(client_id="acme")) == 6


def test_event_dispatch_keeps_playbook_approval_pending_without_retrying_it(settings) -> None:
    store = Store(settings.data_path)
    _seed(store)
    service = AgentService(store, settings, SmartActionService(store, settings))
    subscription = create_msp_playbook_subscription(
        store,
        "security-response-review",
        event_type="ticket.created",
        client_id="acme",
    )

    result = EventDispatcher(store, service).dispatch(
        event_type="ticket.created",
        entity_type="ticket",
        entity_id="TCK-1001",
        payload={},
        idempotency_key="playbook-approval-event",
        client_id="acme",
    )

    assert result.delivery.status == "completed"
    assert result.errors == []
    attempts = json.loads(result.delivery.playbook_attempts_json)
    assert attempts[subscription.id]["status"] == "pending"
    assert len(store.list_approval_requests(client_id="acme")) == 1


def test_event_dispatch_records_subscription_failure_as_bounded_retry_evidence(settings, monkeypatch) -> None:
    store = Store(settings.data_path)
    _seed(store)
    service = AgentService(store, settings, SmartActionService(store, settings))
    subscription = create_msp_playbook_subscription(
        store,
        "ticket-intake-review",
        event_type="ticket.created",
        client_id="acme",
    )

    def fail_playbook(*args, **kwargs):
        raise RuntimeError("provider access_token=secret-value")

    monkeypatch.setattr(event_dispatch_module, "run_msp_playbook", fail_playbook)
    result = EventDispatcher(store, service).dispatch(
        event_type="ticket.created",
        entity_type="ticket",
        entity_id="TCK-1001",
        payload={},
        idempotency_key="playbook-failure-event",
        client_id="acme",
        max_retries=1,
    )

    assert result.delivery.status == "failed"
    assert result.delivery.next_retry_at
    assert subscription.id in result.matched_playbook_ids
    assert "secret-value" not in result.errors[0]
    attempts = json.loads(result.delivery.playbook_attempts_json)
    assert attempts[subscription.id]["status"] == "failed"


def test_event_dispatch_retry_skips_playbook_that_is_already_pending(settings, monkeypatch) -> None:
    store = Store(settings.data_path)
    _seed(store)
    service = AgentService(store, settings, SmartActionService(store, settings))
    failed = create_msp_playbook_subscription(
        store,
        "ticket-intake-review",
        event_type="ticket.created",
        client_id="acme",
    )
    pending = create_msp_playbook_subscription(
        store,
        "security-response-review",
        event_type="ticket.created",
        client_id="acme",
    )
    original = event_dispatch_module.run_msp_playbook

    def fail_one(store_arg, playbook_id, *args, **kwargs):
        if playbook_id == failed.playbook_id:
            raise RuntimeError("temporary provider failure")
        return original(store_arg, playbook_id, *args, **kwargs)

    monkeypatch.setattr(event_dispatch_module, "run_msp_playbook", fail_one)
    dispatcher = EventDispatcher(store, service)
    first = dispatcher.dispatch(
        event_type="ticket.created",
        entity_type="ticket",
        entity_id="TCK-1001",
        payload={},
        idempotency_key="playbook-retry-event",
        client_id="acme",
        max_retries=1,
    )
    retried = dispatcher.retry(first.delivery.id or 0, client_id="acme")

    assert retried.delivery.status == "failed"
    attempts = json.loads(retried.delivery.playbook_attempts_json)
    assert attempts[pending.id]["status"] == "pending"
    assert attempts[failed.id]["status"] == "failed"


def test_event_dispatch_preserves_noncompleted_agent_status(settings) -> None:
    store = Store(settings.data_path)
    _seed(store)
    service, definition = _event_agent(settings, store)
    service.run = lambda *args, **kwargs: AgentExecutionResult(
        run_id=77,
        agent_id=definition.id,
        status="pending",
        current_step=0,
        steps=[],
    )

    result = EventDispatcher(store, service).dispatch(
        event_type="ticket.created",
        entity_type="ticket",
        entity_id="TCK-1001",
        payload={"priority": "P1"},
        idempotency_key="pending-agent-event",
        client_id="acme",
    )

    assert result.delivery.status == "completed"
    assert result.run_ids == [77]


def test_event_dispatch_does_not_run_tenant_subscription_for_unscoped_ticket(settings) -> None:
    store = Store(settings.data_path)
    _seed(store, client_id=None)
    service = AgentService(store, settings, SmartActionService(store, settings))
    create_msp_playbook_subscription(
        store,
        "ticket-intake-review",
        event_type="ticket.created",
        client_id="acme",
    )

    result = EventDispatcher(store, service).dispatch(
        event_type="ticket.created",
        entity_type="ticket",
        entity_id="TCK-1001",
        payload={},
        idempotency_key="unscoped-playbook-event",
    )

    assert result.matched_playbook_ids == []
    assert result.playbook_run_ids == []


def test_event_dispatch_rejects_unsupported_events_and_cross_tenant_entities(settings) -> None:
    store = Store(settings.data_path)
    _seed(store)
    service, _ = _event_agent(settings, store)
    dispatcher = EventDispatcher(store, service)

    with pytest.raises(EventDispatchError, match="unsupported"):
        dispatcher.dispatch(
            event_type="ticket.deleted",
            entity_type="ticket",
            entity_id="TCK-1001",
            payload={},
            idempotency_key="bad-event",
            client_id="acme",
        )
    with pytest.raises(EventDispatchError, match="only ticket"):
        dispatcher.dispatch(
            event_type="ticket.created",
            entity_type="user",
            entity_id="TCK-1001",
            payload={},
            idempotency_key="bad-entity-type",
            client_id="acme",
        )
    with pytest.raises(EventDispatchError, match="entity_id"):
        dispatcher.dispatch(
            event_type="ticket.created",
            entity_type="ticket",
            entity_id=" ",
            payload={},
            idempotency_key="bad-entity-id",
            client_id="acme",
        )
    with pytest.raises(EventDispatchError, match="event payload"):
        dispatcher.dispatch(
            event_type="ticket.created",
            entity_type="ticket",
            entity_id="TCK-1001",
            payload=[],  # type: ignore[arg-type]
            idempotency_key="bad-payload",
            client_id="acme",
        )
    with pytest.raises(EventDispatchError, match="idempotency_key"):
        dispatcher.dispatch(
            event_type="ticket.created",
            entity_type="ticket",
            entity_id="TCK-1001",
            payload={},
            idempotency_key=" ",
            client_id="acme",
        )
    assert _json_list("not-json") == []
    assert _json_list("{}") == []
    assert _attempts_from_json("not-json") == {}
    assert _attempts_from_json("[]") == {}
    with pytest.raises(LookupError):
        dispatcher.dispatch(
            event_type="ticket.created",
            entity_type="ticket",
            entity_id="TCK-1001",
            payload={"priority": "P1"},
            idempotency_key="wrong-tenant",
            client_id="beta",
        )


def test_event_dispatch_skips_disabled_nonmatching_and_wrong_scope_agents(settings) -> None:
    store = Store(settings.data_path)
    _seed(store)
    service, definition = _event_agent(settings, store)
    store.create_agent_definition(replace(definition, id="disabled-agent", enabled=False))
    store.create_agent_definition(
        replace(definition, id="manual-agent", trigger="manual", filters={})
    )
    store.create_agent_definition(
        replace(definition, id="other-entity-agent", entity_type="user")
    )
    store.create_agent_definition(replace(definition, id="beta-agent", client_id="beta"))
    store.create_agent_definition(
        replace(
            definition,
            id="priority-mismatch-agent",
            filters={"event_type": "ticket.updated", "priority": "P2"},
        )
    )
    global_agent = store.create_agent_definition(
        replace(
            definition,
            id="global-agent",
            client_id=None,
            filters={"event_type": "ticket.updated"},
        )
    )

    result = EventDispatcher(store, service).dispatch(
        event_type="ticket.updated",
        entity_type="ticket",
        entity_id="TCK-1001",
        payload={"priority": "P1"},
        idempotency_key="branch-coverage-event",
        client_id="acme",
    )

    assert result.matched_agent_ids == [global_agent.id]
    assert len(result.run_ids) == 1

    with store._connect() as connection:  # noqa: SLF001
        connection.execute("update tickets set client_id = null where id = ?", ("TCK-1002",))
    unscoped = EventDispatcher(store, service).dispatch(
        event_type="ticket.updated",
        entity_type="ticket",
        entity_id="TCK-1002",
        payload={"priority": "P1"},
        idempotency_key="branch-coverage-unscoped-event",
    )
    assert unscoped.matched_agent_ids == [global_agent.id]
    assert len(unscoped.run_ids) == 1


def test_event_dispatch_runs_dependency_chain_in_bounded_order_and_blocks_unmet(settings) -> None:
    store = Store(settings.data_path)
    _seed(store)
    service = AgentService(store, settings, SmartActionService(store, settings))
    upstream = service.create(
        name="Upstream triage",
        description="Classify before the dependent agent runs.",
        enabled=True,
        trigger="event",
        entity_type="ticket",
        filters={"event_type": "ticket.created", "priority": "P1"},
        enabled_tools=["ticket-triage"],
        steps=[{"tool_id": "ticket-triage", "payload": {}}],
        max_steps=1,
        execution_timeout_seconds=30,
        client_id="acme",
    )
    dependent = service.create(
        name="A dependent response",
        description="Runs after triage.",
        enabled=True,
        trigger="event",
        entity_type="ticket",
        filters={"event_type": "ticket.created", "priority": "P1"},
        enabled_tools=["ticket-summary"],
        steps=[{"tool_id": "ticket-summary", "payload": {}}],
        max_steps=1,
        execution_timeout_seconds=30,
        client_id="acme",
        depends_on_agent_ids=[upstream.id],
    )

    result = EventDispatcher(store, service).dispatch(
        event_type="ticket.created",
        entity_type="ticket",
        entity_id="TCK-1001",
        payload={"priority": "P1"},
        idempotency_key="dependency-chain-event",
        client_id="acme",
    )
    assert result.delivery.status == "completed"
    assert set(result.matched_agent_ids) == {upstream.id, dependent.id}
    assert len(result.run_ids) == 2
    assert [store.get_agent_run(run_id).agent_id for run_id in result.run_ids] == [upstream.id, dependent.id]  # type: ignore[union-attr]

    blocked_upstream = service.create(
        name="Never matched upstream",
        description="Only listens to a different event.",
        enabled=True,
        trigger="event",
        entity_type="ticket",
        filters={"event_type": "ticket.created"},
        enabled_tools=["ticket-triage"],
        steps=[{"tool_id": "ticket-triage", "payload": {}}],
        max_steps=1,
        execution_timeout_seconds=30,
        client_id="acme",
    )
    blocked = service.create(
        name="Blocked dependent",
        description="Must wait for the unmatched upstream.",
        enabled=True,
        trigger="event",
        entity_type="ticket",
        filters={"event_type": "ticket.updated"},
        enabled_tools=["ticket-summary"],
        steps=[{"tool_id": "ticket-summary", "payload": {}}],
        max_steps=1,
        execution_timeout_seconds=30,
        client_id="acme",
        depends_on_agent_ids=[blocked_upstream.id],
    )
    blocked_result = EventDispatcher(store, service).dispatch(
        event_type="ticket.updated",
        entity_type="ticket",
        entity_id="TCK-1002",
        payload={"priority": "P1"},
        idempotency_key="blocked-dependency-event",
        client_id="acme",
    )
    assert blocked_result.delivery.status == "failed"
    assert blocked.id in blocked_result.matched_agent_ids
    assert blocked_result.run_ids == []
    assert "dependency not completed" in blocked_result.errors[0]


def test_event_dispatch_failure_is_recorded_without_blocking_other_agents(settings) -> None:
    store = Store(settings.data_path)
    _seed(store)
    service, definition = _event_agent(settings, store)

    class FailingAgentService:
        def run(self, *args, **kwargs):
            raise RuntimeError("provider secret=should-redact")

    result = EventDispatcher(store, FailingAgentService()).dispatch(  # type: ignore[arg-type]
        event_type="ticket.created",
        entity_type="ticket",
        entity_id="TCK-1001",
        payload={"priority": "P1"},
        idempotency_key="disabled-event",
        client_id="acme",
    )
    assert result.delivery.status == "failed"
    assert result.matched_agent_ids == [definition.id]
    assert result.run_ids == []
    assert "should-redact" not in result.delivery.error_detail
    failed_duplicate = EventDispatcher(store, FailingAgentService()).dispatch(  # type: ignore[arg-type]
        event_type="ticket.created",
        entity_type="ticket",
        entity_id="TCK-1001",
        payload={"priority": "P1"},
        idempotency_key="disabled-event-second-key",
        client_id="acme",
    )
    assert failed_duplicate.run_ids == []


def test_event_dispatch_retries_only_failed_agents_with_a_bounded_count(settings) -> None:
    store = Store(settings.data_path)
    _seed(store)
    service, definition = _event_agent(settings, store)
    successful_definition = service.create(
        name="Independent event summary",
        description="Runs independently of the flaky agent.",
        enabled=True,
        trigger="event",
        entity_type="ticket",
        filters={"event_type": "ticket.created", "priority": "P1"},
        enabled_tools=["ticket-summary"],
        steps=[{"tool_id": "ticket-summary", "payload": {}}],
        max_steps=1,
        execution_timeout_seconds=30,
        client_id="acme",
    )

    class FlakyAgentService:
        def __init__(self) -> None:
            self.calls = 0

        def run(self, *args, **kwargs):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("provider secret=retry-me")
            return service.run(*args, **kwargs)

    flaky = FlakyAgentService()
    dispatcher = EventDispatcher(store, flaky)  # type: ignore[arg-type]
    failed = dispatcher.dispatch(
        event_type="ticket.created",
        entity_type="ticket",
        entity_id="TCK-1001",
        payload={"priority": "P1"},
        idempotency_key="retryable-event",
        client_id="acme",
    )

    assert failed.delivery.status == "failed"
    assert failed.delivery.retry_count == 0
    assert "retry-me" not in failed.delivery.error_detail

    retried = dispatcher.retry(failed.delivery.id or 0, client_id="acme")
    assert retried.delivery.status == "completed"
    assert retried.delivery.retry_count == 1
    assert retried.run_ids
    assert '"status":"completed"' in retried.delivery.agent_attempts_json
    assert definition.id in retried.delivery.agent_attempts_json
    assert successful_definition.id in retried.delivery.agent_attempts_json
    assert flaky.calls == 3
    assert len(store.list_agent_runs(client_id="acme")) == 2

    with pytest.raises(ValueError, match="only failed"):
        dispatcher.retry(failed.delivery.id or 0, client_id="acme")

    class AlwaysFailingAgentService:
        def run(self, *args, **kwargs):
            raise RuntimeError("still failing")

    exhausted = EventDispatcher(store, AlwaysFailingAgentService()).dispatch(  # type: ignore[arg-type]
        event_type="ticket.created",
        entity_type="ticket",
        entity_id="TCK-1002",
        payload={"priority": "P1"},
        idempotency_key="exhausted-event",
        client_id="acme",
    )
    for _ in range(3):
        exhausted = EventDispatcher(store, AlwaysFailingAgentService()).retry(  # type: ignore[arg-type]
            exhausted.delivery.id or 0,
            client_id="acme",
        )
    assert exhausted.delivery.retry_count == exhausted.delivery.max_retries
    with pytest.raises(ValueError, match="retry limit"):
        EventDispatcher(store, AlwaysFailingAgentService()).retry(  # type: ignore[arg-type]
            exhausted.delivery.id or 0,
            client_id="acme",
        )


def test_event_dispatcher_automatically_retries_due_delivery(settings) -> None:
    store = Store(settings.data_path)
    _seed(store)
    service, definition = _event_agent(settings, store)

    class FailOnce:
        def __init__(self) -> None:
            self.calls = 0

        def run(self, *args, **kwargs):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("provider secret=automatic-retry")
            return service.run(*args, **kwargs)

    dispatcher = EventDispatcher(store, FailOnce())  # type: ignore[arg-type]
    failed = dispatcher.dispatch(
        event_type="ticket.created",
        entity_type="ticket",
        entity_id="TCK-1001",
        payload={"priority": "P1"},
        idempotency_key="automatic-retry-event",
        client_id="acme",
    )

    assert failed.delivery.status == "failed"
    assert failed.delivery.next_retry_at is not None
    store.update_event_delivery(
        failed.delivery.id or 0,
        status="failed",
        matched_agent_count=1,
        agent_ids=[definition.id],
        run_ids=[],
        error_detail=failed.delivery.error_detail,
        agent_attempts={definition.id: {"status": "failed", "error": "", "run_ids": []}},
        next_retry_at="2000-01-01T00:00:00+00:00",
    )

    results = dispatcher.retry_due(now="2000-01-02T00:00:00+00:00")

    assert len(results) == 1
    assert results[0].delivery.status == "completed"
    assert results[0].delivery.retry_count == 1
    assert results[0].delivery.next_retry_at is None


def test_event_dispatch_retry_records_ineligible_agent(settings) -> None:
    store = Store(settings.data_path)
    _seed(store)
    service, definition = _event_agent(settings, store)

    class FailingAgentService:
        def run(self, *args, **kwargs):
            raise RuntimeError("temporary provider failure")

    dispatcher = EventDispatcher(store, FailingAgentService())  # type: ignore[arg-type]
    failed = dispatcher.dispatch(
        event_type="ticket.created",
        entity_type="ticket",
        entity_id="TCK-1001",
        payload={"priority": "P1"},
        idempotency_key="ineligible-retry-event",
        client_id="acme",
    )
    store.update_agent_definition(replace(definition, enabled=False, version=definition.version + 1))

    retry = dispatcher.retry(failed.delivery.id or 0, client_id="acme")
    assert retry.delivery.status == "failed"
    assert "no longer eligible" in retry.errors[0]


def test_event_dispatch_persists_bounded_retry_policy(settings) -> None:
    store = Store(settings.data_path)
    _seed(store)
    _event_agent(settings, store)

    class AlwaysFailingAgentService:
        def run(self, *args, **kwargs):
            raise RuntimeError("temporary failure")

    dispatcher = EventDispatcher(store, AlwaysFailingAgentService())  # type: ignore[arg-type]
    configured = dispatcher.dispatch(
        event_type="ticket.created",
        entity_type="ticket",
        entity_id="TCK-1001",
        payload={"priority": "P1"},
        idempotency_key="configured-retry-policy",
        client_id="acme",
        max_retries=2,
        retry_delay_seconds=7,
    )
    assert configured.delivery.max_retries == 2
    assert configured.delivery.retry_delay_seconds == 7
    assert configured.delivery.next_retry_at is not None

    no_retry = dispatcher.dispatch(
        event_type="ticket.created",
        entity_type="ticket",
        entity_id="TCK-1002",
        payload={"priority": "P1"},
        idempotency_key="no-retry-policy",
        client_id="acme",
        max_retries=0,
        retry_delay_seconds=1,
    )
    assert no_retry.delivery.max_retries == 0
    assert no_retry.delivery.next_retry_at is None

    with pytest.raises(ValueError, match="max_retries"):
        dispatcher.dispatch(
            event_type="ticket.created",
            entity_type="ticket",
            entity_id="TCK-1001",
            payload={},
            idempotency_key="invalid-max-retries",
            client_id="acme",
            max_retries=11,
        )
    with pytest.raises(ValueError, match="retry_delay_seconds"):
        dispatcher.dispatch(
            event_type="ticket.created",
            entity_type="ticket",
            entity_id="TCK-1001",
            payload={},
            idempotency_key="invalid-retry-delay",
            client_id="acme",
            retry_delay_seconds=3601,
        )


def test_next_retry_at_validates_and_exponentially_backoffs() -> None:
    first = _next_retry_at(0, retry_delay_seconds=7)
    second = _next_retry_at(1, retry_delay_seconds=7)
    assert first < second

    with pytest.raises(ValueError, match="integer"):
        _next_retry_at(0, retry_delay_seconds=True)
    with pytest.raises(ValueError, match="between 1"):
        _next_retry_at(0, retry_delay_seconds=0)


def test_retry_due_audits_delivery_claim_races(settings, monkeypatch) -> None:
    store = Store(settings.data_path)
    service = AgentService(store, settings, SmartActionService(store, settings))
    dispatcher = EventDispatcher(store, service)
    monkeypatch.setattr(
        store,
        "list_due_event_delivery_ids",
        lambda *, now, limit: [404],
    )

    assert dispatcher.retry_due(now="2026-08-09T00:00:00+00:00") == []
    audit = store.list_audit_events()
    assert audit[0].event_type == "event.retry_skipped"
    assert audit[0].subject_id == "404"
