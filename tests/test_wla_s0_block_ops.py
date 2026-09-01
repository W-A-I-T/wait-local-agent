from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest

from tests.support import ingest_local
from wait_local_agent.agents import AgentService
from wait_local_agent.event_dispatch import EventDispatcher
from wait_local_agent.models import AgentDefinition, AgentRun
from wait_local_agent.msp_playbooks import preview_msp_playbook, run_msp_playbook
from wait_local_agent.providers import ModelProvider
from wait_local_agent.rbac import Role
from wait_local_agent.scheduler import SchedulerManager
from wait_local_agent.services import TicketIntelligenceService
from wait_local_agent.smart_actions import SmartActionService
from wait_local_agent.store import QuarantinedTicketError, Store
from wait_local_agent.workflows import run_workflow_template, validate_workflow_input

QUARANTINE_TICKET = "quarantine-ticket"


def _store_with_tickets(tmp_path: Path) -> Store:
    store = Store(tmp_path / "state.db")
    ingest_local(store, Path("examples/sample_tickets/tickets.json"))
    with store._connect() as connection:  # noqa: SLF001
        connection.execute(
            """
            insert into tickets
              (id, client, subject, body, priority, status, client_id, requester_id, source_system)
            values (?, ?, ?, ?, 'normal', 'new', '__quarantine__', ?, 'test')
            """,
            (QUARANTINE_TICKET, "Unmapped", "Pending mapping", "Body", "requester-a"),
        )
    return store


def test_store_ticket_dependent_writes_raise_and_normal_writes_continue(tmp_path: Path) -> None:
    store = _store_with_tickets(tmp_path)

    with pytest.raises(QuarantinedTicketError):
        store.create_ticket_note(
            QUARANTINE_TICKET,
            client_id="__quarantine__",
            author="operator",
            body="triage",
        )
    with pytest.raises(QuarantinedTicketError):
        store.create_technician_chat_session(
            client_id="__quarantine__",
            principal_id="operator",
            ticket_id=QUARANTINE_TICKET,
        )
    with pytest.raises(QuarantinedTicketError):
        store.create_end_user_message(
            QUARANTINE_TICKET,
            client_id="__quarantine__",
            requester_id="requester-a",
            body="reply",
        )
    with pytest.raises(QuarantinedTicketError):
        store.create_support_end_user_message(
            QUARANTINE_TICKET,
            client_id="__quarantine__",
            author_id="operator",
            body="reply",
        )
    with pytest.raises(QuarantinedTicketError):
        store.set_approval(QUARANTINE_TICKET, "approved")
    with pytest.raises(QuarantinedTicketError):
        store.create_workflow_run("ticket-triage", QUARANTINE_TICKET, "completed", "blocked")
    with pytest.raises(QuarantinedTicketError):
        store.create_approval_request(
            QUARANTINE_TICKET,
            "ticket.follow_up",
            {"ticket_id": QUARANTINE_TICKET},
            client_id="__quarantine__",
        )
    with pytest.raises(QuarantinedTicketError):
        store.create_event_delivery(
            idempotency_key="quarantine-event",
            event_type="ticket.created",
            entity_type="ticket",
            entity_id=QUARANTINE_TICKET,
            payload={},
            client_id="__quarantine__",
        )
    with pytest.raises(QuarantinedTicketError):
        store.create_agent_backfill(
            "agent-id",
            [QUARANTINE_TICKET],
            {},
            actor="operator",
            client_id="__quarantine__",
        )
    with pytest.raises(QuarantinedTicketError):
        store.create_agent_run(
            "agent-id",
            QUARANTINE_TICKET,
            "operator",
            "queued",
            0,
            {},
            client_id="__quarantine__",
        )
    with pytest.raises(QuarantinedTicketError):
        store.create_scheduled_job(
            "ticket-triage",
            "0 * * * *",
            {"ticket_id": QUARANTINE_TICKET},
            client_id="__quarantine__",
        )

    note = store.create_ticket_note(
        "TCK-1001",
        client_id="acme",
        author="operator",
        body="triage",
    )
    run = store.create_workflow_run("ticket-triage", "TCK-1001", "completed", "ok", client_id="acme")
    assert note is not None
    assert run.ticket_id == "TCK-1001"


def test_store_remaining_quarantine_mutation_guards_raise(tmp_path: Path) -> None:
    store = _store_with_tickets(tmp_path)
    with store._connect() as connection:  # noqa: SLF001
        connection.execute(
            "update tickets set requester_id = 'requester-a' where id = 'TCK-1001'"
        )

    approval = store.create_approval_request(
        "TCK-1001",
        "ticket.follow_up",
        {"ticket_id": "TCK-1001"},
        client_id="acme",
    )
    session = store.create_technician_chat_session(
        client_id="acme",
        principal_id="operator",
        ticket_id="TCK-1001",
    )
    with store._connect() as connection:  # noqa: SLF001
        connection.execute(
            "update tickets set client_id = '__quarantine__' where id = 'TCK-1001'"
        )
        connection.execute(
            "update technician_chat_sessions set client_id = '__quarantine__' where id = ?",
            (session.id,),
        )

    with pytest.raises(QuarantinedTicketError):
        store.update_technician_chat_session_ticket(
            session.id,
            client_id="__quarantine__",
            ticket_id="TCK-1001",
            principal_id="operator",
        )
    with pytest.raises(QuarantinedTicketError):
        store.close_technician_chat_session(
            session.id,
            client_id="__quarantine__",
            principal_id="operator",
        )
    with pytest.raises(QuarantinedTicketError):
        store.add_technician_chat_message(
            session.id,
            role="user",
            message="still blocked",
            status="blocked",
            client_id="__quarantine__",
            principal_id="operator",
        )
    with pytest.raises(QuarantinedTicketError):
        store.escalate_end_user_ticket(
            "TCK-1001",
            client_id="__quarantine__",
            requester_id="requester-a",
        )
    with pytest.raises(QuarantinedTicketError):
        store.create_end_user_message(
            "TCK-1001",
            client_id="__quarantine__",
            requester_id="requester-a",
            body="still blocked",
        )
    with pytest.raises(QuarantinedTicketError):
        store.create_support_end_user_message(
            "TCK-1001",
            client_id="__quarantine__",
            author_id="operator",
            body="still blocked",
        )
    with pytest.raises(QuarantinedTicketError):
        store.update_approval_request(approval.id or 0, "approved")
    with pytest.raises(QuarantinedTicketError):
        store.update_approval_request_payload(approval.id or 0, {})
    with pytest.raises(QuarantinedTicketError):
        store.record_approval_execution(
            approval.id or 0,
            status="failed",
            message="blocked",
            result={},
        )
    with pytest.raises(QuarantinedTicketError):
        store.create_pending_smart_action(
            "ticket-triage",
            "operator",
            "digest",
            {},
            [],
            {"ticket_id": "TCK-1001"},
            client_id="__quarantine__",
        )


def test_orchestration_entries_skip_quarantine_before_side_effects(settings) -> None:
    store = Store(settings.data_path)
    ingest_local(store, Path("examples/sample_tickets/tickets.json"))
    with store._connect() as connection:  # noqa: SLF001
        connection.execute("update tickets set client_id = '__quarantine__' where id = 'TCK-1001'")

    class CountingTool:
        calls = 0

        def invoke(self, action_id, payload, actor, *, confirm=False, client_id=None, correlation_id=None):
            del correlation_id
            self.calls += 1
            raise AssertionError("quarantined ticket reached a tool")

    tool = CountingTool()
    workflow = run_workflow_template(
        store,
        "ticket-triage",
        "TCK-1001",
        tool_executor=tool,
    )
    assert workflow.id is None
    assert tool.calls == 0

    dispatcher = EventDispatcher(store, AgentService(store, settings, SmartActionService(store, settings)))
    event = dispatcher.dispatch(
        event_type="ticket.created",
        entity_type="ticket",
        entity_id="TCK-1001",
        payload={},
        idempotency_key="quarantine-dispatch",
    )
    assert event.matched_agent_ids == []
    assert event.run_ids == []
    assert store.list_event_deliveries() == []

    class NoModelCalls:
        calls = 0

        def summarize_ticket(self, *args: object) -> str:
            self.calls += 1
            raise AssertionError("quarantined ticket reached the model")

        def draft_response(self, *args: object) -> str:
            self.calls += 1
            raise AssertionError("quarantined ticket reached the model")

    model = NoModelCalls()
    summary = TicketIntelligenceService(
        store,
        settings,
        cast(ModelProvider, model),
    ).summarize("TCK-1001")
    assert summary.summary == ""
    assert summary.sources == []
    assert model.calls == 0


def test_ticket_intelligence_quarantine_skip_does_not_call_model(settings) -> None:
    store = _store_with_tickets(settings.data_path.parent)

    class NoModelCalls:
        calls = 0

        def summarize_ticket(self, *args: object) -> str:
            self.calls += 1
            raise AssertionError("quarantined ticket reached the model")

        def draft_response(self, *args: object) -> str:
            self.calls += 1
            raise AssertionError("quarantined ticket reached the model")

    model = NoModelCalls()
    summary = TicketIntelligenceService(
        store,
        settings,
        cast(ModelProvider, model),
    ).summarize(QUARANTINE_TICKET)

    assert summary.ticket_id == QUARANTINE_TICKET
    assert summary.classification == ""
    assert summary.summary == ""
    assert summary.suggested_response == ""
    assert summary.sources == []
    assert model.calls == 0


def test_ticket_intelligence_missing_ticket_raises_key_error(settings) -> None:
    store = Store(settings.data_path)

    class NoModelCalls:
        pass

    service = TicketIntelligenceService(
        store,
        settings,
        cast(ModelProvider, NoModelCalls()),
    )

    with pytest.raises(KeyError):
        service.summarize("nonexistent-ticket-id")


def test_m365_compliance_review_rejects_out_of_range_limit() -> None:
    with pytest.raises(ValueError, match="limit"):
        validate_workflow_input("m365-compliance-review", {"limit": 0})


def test_m365_inactive_license_review_rejects_out_of_range_limit() -> None:
    with pytest.raises(ValueError, match="limit"):
        validate_workflow_input("m365-inactive-license-review", {"limit": 51})


def test_workflow_runner_quarantine_skip_has_no_tool_or_run_side_effect(settings) -> None:
    store = _store_with_tickets(settings.data_path.parent)

    class CountingTool:
        calls = 0

        def invoke(self, action_id, payload, actor, *, confirm=False, client_id=None, correlation_id=None):
            del correlation_id
            self.calls += 1
            raise AssertionError("quarantined ticket reached a tool")

    tool = CountingTool()
    run = run_workflow_template(
        store,
        "ticket-triage",
        QUARANTINE_TICKET,
        client_id="__quarantine__",
        tool_executor=tool,
    )

    assert run.id is None
    assert run.status == "failed"
    assert run.message == "ticket is quarantined pending client mapping"
    assert tool.calls == 0
    assert store.list_workflow_runs() == []
    assert store.list_approval_requests() == []


def test_scheduler_quarantine_skip_has_no_tool_or_trigger_side_effect(settings) -> None:
    store = _store_with_tickets(settings.data_path.parent)

    class CountingTool:
        calls = 0

        def invoke(self, action_id, payload, actor, *, confirm=False, client_id=None):
            self.calls += 1
            raise AssertionError("quarantined ticket reached a scheduled tool")

    tool = CountingTool()
    scheduler = SchedulerManager(
        store,
        enabled=False,
        smart_action_service=cast(SmartActionService, tool),
    )
    job = store.create_scheduled_job(
        "ticket-triage",
        "0 * * * *",
        {"ticket_id": "TCK-1001", "client_id": "acme"},
        client_id="acme",
    )
    scheduled = replace(
        job,
        params_json=json.dumps(
            {"ticket_id": QUARANTINE_TICKET, "client_id": "__quarantine__"}
        ),
    )

    import asyncio

    asyncio.run(scheduler._run_job(scheduled))  # noqa: SLF001

    assert tool.calls == 0
    assert store.list_workflow_runs() == []
    assert not any(
        event.event_type == "scheduled_job.triggered"
        for event in store.list_audit_events()
    )


def test_event_retry_and_approval_resume_skip_without_claim_or_provider_call(settings) -> None:
    store = Store(settings.data_path)
    ingest_local(store, Path("examples/sample_tickets/tickets.json"))
    dispatcher = EventDispatcher(store, AgentService(store, settings, SmartActionService(store, settings)))
    first = dispatcher.dispatch(
        event_type="ticket.created",
        entity_type="ticket",
        entity_id="TCK-1001",
        payload={},
        idempotency_key="retry-quarantine",
    )
    assert first.delivery.id is not None
    settings_store = SmartActionService(store, settings)
    run, approval = store.create_pending_smart_action(
        "ticket-follow-up",
        "operator",
        "digest",
        {},
        [],
        {"action_id": "ticket-follow-up", "payload": {"ticket_id": "TCK-1001"}},
        client_id="acme",
    )
    with store._connect() as connection:  # noqa: SLF001
        connection.execute("update tickets set client_id = '__quarantine__' where id = 'TCK-1001'")
        connection.execute(
            "update event_deliveries set status = 'failed', next_retry_at = '2026-08-16T00:00:00+00:00' where id = ?",
            (first.delivery.id,),
        )
    retried = dispatcher.retry(first.delivery.id)
    assert retried.matched_agent_ids == []
    saved_delivery = store.get_event_delivery(first.delivery.id)
    assert saved_delivery is not None
    assert saved_delivery.status == "failed"

    with store._connect() as connection:  # noqa: SLF001
        connection.execute("update approval_requests set status = 'approved' where id = ?", (approval.id,))
    assert (
        settings_store.complete_approval(
            approval.id or 0,
            approver="technician",
            approver_role=Role.TECHNICIAN,
        )
        is None
    )
    assert run.id is not None


def test_playbook_and_scheduler_skip_quarantined_ticket(settings) -> None:
    store = Store(settings.data_path)
    ingest_local(store, Path("examples/sample_tickets/tickets.json"))
    with store._connect() as connection:  # noqa: SLF001
        connection.execute("update tickets set client_id = '__quarantine__' where id = 'TCK-1001'")

    playbook = run_msp_playbook(store, "ticket-intake-review", ticket_id="TCK-1001")
    assert playbook["status"] == "skipped"
    assert playbook["steps"] == []
    preview = preview_msp_playbook(store, "ticket-intake-review", ticket_id="TCK-1001")
    assert preview["execution_mode"] == "skipped_quarantine"
    assert preview["steps"] == []

    scheduler = SchedulerManager(store, enabled=False)
    job = store.create_scheduled_job(
        "ticket-triage",
        "0 * * * *",
        {"ticket_id": "TCK-1002", "client_id": "acme"},
        client_id="acme",
    )
    with store._connect() as connection:  # noqa: SLF001
        connection.execute(
            "update scheduled_jobs set params_json = ? where id = ?",
            (json.dumps({"ticket_id": "TCK-1001", "client_id": "acme"}), job.id),
        )

    import asyncio

    scheduled = replace(
        job,
        params_json=json.dumps({"ticket_id": "TCK-1001", "client_id": "acme"}),
    )
    asyncio.run(scheduler._run_job(scheduled))  # noqa: SLF001

    playbook_job = store.create_scheduled_job(
        "ticket-intake-review",
        "0 * * * *",
        {"ticket_id": "TCK-1002", "client_id": "acme"},
        client_id="acme",
        job_kind="playbook",
    )
    asyncio.run(
        scheduler._run_playbook_job(  # noqa: SLF001
            replace(
                playbook_job,
                params_json=json.dumps({"ticket_id": "TCK-1001", "client_id": "acme"}),
            ),
            {"ticket_id": "TCK-1001", "client_id": "acme"},
            "acme",
        )
    )

    agent_job = store.create_scheduled_job(
        "agent-id",
        "0 * * * *",
        {"client_id": "acme"},
        client_id="acme",
        job_kind="agent",
        agent_id="agent-id",
        entity_id="TCK-1002",
    )
    asyncio.run(
        scheduler._run_agent_job(  # noqa: SLF001
            replace(agent_job, entity_id="TCK-1001"),
            {},
            "acme",
        )
    )


def test_agent_run_and_resume_skip_quarantine_without_side_effects(settings) -> None:
    store = Store(settings.data_path)
    ingest_local(store, Path("examples/sample_tickets/tickets.json"))
    service = AgentService(store, settings, SmartActionService(store, settings))
    definition = AgentDefinition(
        id="agent-id",
        name="Ticket agent",
        description="Bounded test agent",
        enabled=True,
        trigger="manual",
        entity_type="ticket",
        filters={},
        enabled_tools=[],
        steps=[],
        max_steps=1,
        execution_timeout_seconds=30.0,
        client_id=None,
        version=1,
        created_at="",
        updated_at="",
    )

    with store._connect() as connection:  # noqa: SLF001
        connection.execute("update tickets set client_id = '__quarantine__' where id = 'TCK-1001'")

    with pytest.raises(QuarantinedTicketError):
        service.run(
            definition,
            entity_id="TCK-1001",
            actor="operator",
            input_payload={},
        )

    pending_run = AgentRun(
        id=41,
        agent_id=definition.id,
        entity_id="TCK-1001",
        actor="operator",
        status="pending_approval",
        current_step=0,
        state_json="{}",
        started_at="",
        finished_at="",
        revision_version=definition.version,
        client_id="acme",
    )
    resumed = service.resume(
        definition,
        pending_run,
        approver="technician",
        approver_role=Role.TECHNICIAN,
    )
    assert resumed.run_id == pending_run.id
    assert resumed.status == "pending_approval"


def test_smart_action_quarantine_guards_block_invoke_and_approval_update(settings) -> None:
    store = _store_with_tickets(settings.data_path.parent)
    service = SmartActionService(store, settings)

    with pytest.raises(QuarantinedTicketError):
        service.invoke(
            "ticket-triage",
            {"ticket_id": QUARANTINE_TICKET},
            "operator",
            client_id="__quarantine__",
        )

    run, approval = store.create_pending_smart_action(
        "ticket-follow-up",
        "operator",
        "digest",
        {},
        [],
        {"action_id": "ticket-follow-up", "payload": {"ticket_id": "TCK-1001"}},
        client_id="acme",
    )
    with store._connect() as connection:  # noqa: SLF001
        connection.execute("update tickets set client_id = '__quarantine__' where id = 'TCK-1001'")
    with pytest.raises(QuarantinedTicketError):
        service.update_approval(
            approval.id or 0,
            "approved",
            approver="technician",
            approver_role=Role.TECHNICIAN,
        )
    assert run.id is not None
