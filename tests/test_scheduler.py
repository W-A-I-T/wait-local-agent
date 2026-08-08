from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from wait_local_agent.agents import AgentService
from wait_local_agent.config import Settings
from wait_local_agent.event_dispatch import EventDispatcher
from wait_local_agent.models import ScheduledJob
from wait_local_agent.scheduler import (
    SchedulerManager,
    _schedule_trigger,
    validate_cron_expression,
    validate_schedule,
)
from wait_local_agent.security import require_bearer_authorization
from wait_local_agent.smart_actions import ActionResult, SmartActionService
from wait_local_agent.store import Store
from wait_local_agent.workflows import run_workflow_template


def test_scheduler_manager_registers_and_reloads_persisted_jobs(tmp_path: Path) -> None:
    db_path = tmp_path / "state.db"
    _seed_tickets(db_path)

    async def scenario() -> None:
        first_store = Store(db_path)
        first_manager = SchedulerManager(first_store, enabled=True)
        first_manager.start()
        scheduled_job = first_manager.register(
            "documentation-assisted-response",
            "0 9 * * *",
            {"ticket_id": "TCK-1001", "client_id": "acme"},
        )
        first_manager.shutdown()

        reloaded_store = Store(db_path)
        reloaded_manager = SchedulerManager(reloaded_store, enabled=True)
        reloaded_manager.start()
        jobs = reloaded_manager.list_jobs()

        assert scheduled_job.id is not None
        assert scheduled_job.next_run_at is not None
        assert len(jobs) == 1
        assert jobs[0].id == scheduled_job.id
        assert jobs[0].next_run_at is not None

        reloaded_manager.shutdown()

    asyncio.run(scenario())


def test_scheduler_registers_bounded_event_retry_worker(tmp_path: Path, settings) -> None:
    db_path = tmp_path / "retry-worker.db"
    _seed_tickets(db_path)

    async def scenario() -> None:
        store = Store(db_path)
        dispatcher = EventDispatcher(
            store,
            AgentService(store, settings, SmartActionService(store, settings)),
        )
        manager = SchedulerManager(store, enabled=True, event_dispatcher=dispatcher)
        manager.start()

        assert manager._scheduler is not None  # noqa: SLF001
        retry_job = manager._scheduler.get_job(manager._retry_job_identity())  # noqa: SLF001
        assert retry_job is not None
        manager._retry_due_event_deliveries()  # noqa: SLF001
        manager.shutdown()

    asyncio.run(scenario())


def test_scheduler_job_callable_creates_same_approval_path_as_manual_run(tmp_path: Path) -> None:
    db_path = tmp_path / "state.db"
    _seed_tickets(db_path)

    async def scenario() -> None:
        store = Store(db_path)
        manual_run = run_workflow_template(
            store,
            "documentation-assisted-response",
            "TCK-1001",
            client_id="acme",
        )
        manual_approval = store.get_approval_request(manual_run.approval_request_id or 0)
        manager = SchedulerManager(store, enabled=False)
        scheduled_job = manager.register(
            "documentation-assisted-response",
            "0 9 * * *",
            {"ticket_id": "TCK-1001", "client_id": "acme"},
        )

        await manager._build_job_callable(scheduled_job)()

        scheduled_run = store.list_workflow_runs()[0]
        scheduled_approval = store.get_approval_request(scheduled_run.approval_request_id or 0)

        assert manual_approval is not None
        assert scheduled_approval is not None
        assert scheduled_run.status == manual_run.status == "pending_approval"
        assert scheduled_approval.action_type == manual_approval.action_type
        assert scheduled_approval.subject_id == manual_approval.subject_id
        assert json.loads(scheduled_approval.payload_json)["template_id"] == json.loads(
            manual_approval.payload_json
        )["template_id"]

    asyncio.run(scenario())


def test_scheduled_workflow_completion_triggers_tenant_scoped_event_agent(tmp_path: Path, settings) -> None:
    db_path = tmp_path / "completion.db"
    _seed_tickets(db_path)
    store = Store(db_path)
    with store._connect() as connection:  # noqa: SLF001
        connection.execute("update tickets set client_id = 'acme'")
    service = AgentService(store, settings, SmartActionService(store, settings))
    definition = service.create(
        name="After triage",
        description="Runs after a scheduled triage workflow completes.",
        enabled=True,
        trigger="event",
        entity_type="ticket",
        filters={
            "event_type": "workflow.completed",
            "workflow_template_id": "ticket-triage",
        },
        enabled_tools=["ticket-summary"],
        steps=[{"tool_id": "ticket-summary", "payload": {}}],
        max_steps=1,
        execution_timeout_seconds=30,
        client_id="acme",
    )
    manager = SchedulerManager(
        store,
        enabled=False,
        agent_service=service,
        event_dispatcher=EventDispatcher(store, service),
    )
    scheduled_job = manager.register(
        "ticket-triage",
        "0 9 * * *",
        {"ticket_id": "TCK-1001", "client_id": "acme"},
    )

    asyncio.run(manager._build_job_callable(scheduled_job)())

    deliveries = store.list_event_deliveries(client_id="acme")
    assert len(deliveries) == 1
    assert deliveries[0].event_type == "workflow.completed"
    assert json.loads(deliveries[0].payload_json)["workflow_template_id"] == "ticket-triage"
    runs = store.list_agent_runs(client_id="acme")
    assert len(runs) == 1
    assert runs[0].agent_id == definition.id
    assert any(
        event.event_type == "workflow.completion_dispatched"
        for event in store.list_audit_events(client_id="acme")
    )


def test_scheduled_pending_workflow_does_not_emit_completion_event(tmp_path: Path, settings) -> None:
    db_path = tmp_path / "pending-completion.db"
    _seed_tickets(db_path)
    store = Store(db_path)
    service = AgentService(store, settings, SmartActionService(store, settings))
    manager = SchedulerManager(
        store,
        enabled=False,
        agent_service=service,
        event_dispatcher=EventDispatcher(store, service),
    )
    scheduled_job = manager.register(
        "documentation-assisted-response",
        "0 9 * * *",
        {"ticket_id": "TCK-1001"},
    )

    asyncio.run(manager._build_job_callable(scheduled_job)())

    assert store.list_event_deliveries() == []


def test_completion_dispatch_failure_is_audited_without_replaying_workflow(tmp_path: Path) -> None:
    db_path = tmp_path / "completion-failure.db"
    _seed_tickets(db_path)
    store = Store(db_path)

    class BrokenDispatcher:
        def dispatch(self, **kwargs):
            raise RuntimeError("provider access_token=super-secret")

    manager = SchedulerManager(store, enabled=False, event_dispatcher=BrokenDispatcher())  # type: ignore[arg-type]
    scheduled_job = manager.register(
        "ticket-triage",
        "0 9 * * *",
        {"ticket_id": "TCK-1001"},
    )

    asyncio.run(manager._build_job_callable(scheduled_job)())

    events = store.list_audit_events()
    failure = next(event for event in events if event.event_type == "workflow.completion_dispatch_failed")
    assert "super-secret" not in failure.detail


def test_scheduler_pause_resume_remove_update_store_and_live_state(tmp_path: Path) -> None:
    db_path = tmp_path / "state.db"
    _seed_tickets(db_path)

    async def scenario() -> None:
        store = Store(db_path)
        manager = SchedulerManager(store, enabled=True)
        manager.start()
        scheduled_job = manager.register(
            "documentation-assisted-response",
            "0 9 * * *",
            {"ticket_id": "TCK-1001"},
        )

        rescheduled = manager.reschedule(
            scheduled_job.id or 0,
            schedule_type="interval",
            cron="",
            interval_seconds=60,
            run_at=None,
        )
        assert rescheduled.schedule_type == "interval"
        assert rescheduled.interval_seconds == 60

        paused = manager.pause(scheduled_job.id or 0)
        resumed = manager.resume(scheduled_job.id or 0)
        rescheduled = manager.reschedule(
            scheduled_job.id or 0,
            cron="0 10 * * *",
            schedule_type="cron",
            interval_seconds=None,
            run_at=None,
            timezone="America/Vancouver",
        )
        deleted = manager.remove(scheduled_job.id or 0)

        assert paused.paused is True
        assert paused.next_run_at is None
        assert resumed.paused is False
        assert resumed.next_run_at is not None
        assert rescheduled.cron == "0 10 * * *"
        assert rescheduled.schedule_type == "cron"
        assert rescheduled.timezone == "America/Vancouver"
        assert rescheduled.next_run_at is not None
        assert deleted.id == scheduled_job.id
        assert store.get_scheduled_job(scheduled_job.id or 0) is None
        with pytest.raises(KeyError):
            manager.reschedule(
                999,
                cron="0 11 * * *",
                schedule_type="cron",
                interval_seconds=None,
                run_at=None,
                timezone="UTC",
            )
        with pytest.raises(KeyError):
            store.update_scheduled_job_schedule(
                999,
                cron="0 11 * * *",
                schedule_type="cron",
                interval_seconds=None,
                run_at=None,
                timezone="UTC",
            )

        unregistered = manager.register(
            "documentation-assisted-response",
            "0 9 * * *",
            {"ticket_id": "TCK-1001"},
        )
        assert manager._scheduler is not None
        manager._scheduler.remove_job(manager._job_identity(unregistered.id or 0))  # noqa: SLF001
        manager.pause(unregistered.id or 0)
        manager.resume(unregistered.id or 0)
        manager.remove(unregistered.id or 0)

        manager.shutdown()

    asyncio.run(scenario())


def test_scheduler_validation_rejects_invalid_cron() -> None:
    validate_cron_expression("0 9 * * *")

    try:
        validate_cron_expression("not a cron")
    except ValueError as exc:
        assert "invalid cron expression" in str(exc)
    else:
        raise AssertionError("expected invalid cron expression to fail")


def test_scheduler_validation_supports_interval_and_one_time_triggers() -> None:
    validate_schedule("interval", "", 60, None)
    assert validate_schedule("cron", "0 9 * * *", None, None, " America/Vancouver ") == "America/Vancouver"
    validate_schedule("once", "", None, "2099-01-01T00:00:00+00:00")
    with pytest.raises(ValueError, match="interval_seconds"):
        validate_schedule("interval", "", None, None)
    with pytest.raises(ValueError, match="between 1"):
        validate_schedule("interval", "", 0, None)
    with pytest.raises(ValueError, match="cannot include cron"):
        validate_schedule("interval", "0 9 * * *", 60, None)
    with pytest.raises(ValueError, match="cannot include interval"):
        validate_schedule("cron", "0 9 * * *", 60, None)
    with pytest.raises(ValueError, match="require run_at"):
        validate_schedule("once", "", None, None)
    with pytest.raises(ValueError, match="cannot include cron"):
        validate_schedule("once", "0 9 * * *", None, "2099-01-01T00:00:00+00:00")
    with pytest.raises(ValueError, match="timezone"):
        validate_schedule("once", "", None, "2099-01-01T00:00:00")
    with pytest.raises(ValueError, match="ISO-8601"):
        validate_schedule("once", "", None, "not-a-date")
    with pytest.raises(ValueError, match="future"):
        validate_schedule("once", "", None, "2020-01-01T00:00:00+00:00")
    with pytest.raises(ValueError, match="schedule_type"):
        validate_schedule("unknown", "", None, None)
    with pytest.raises(ValueError, match="valid IANA timezone"):
        validate_schedule("cron", "0 9 * * *", None, None, "Not/AZone")
    assert _schedule_trigger(  # noqa: SLF001
        ScheduledJob(
            id=1,
            template_id="template",
            cron="",
            params_json="{}",
            paused=False,
            created_at="",
            updated_at="",
            schedule_type="interval",
            interval_seconds=60,
        )
    ) is not None
    timezone_trigger = _schedule_trigger(  # noqa: SLF001
        ScheduledJob(
            id=3,
            template_id="template",
            cron="0 9 * * *",
            params_json="{}",
            paused=False,
            created_at="",
            updated_at="",
            timezone="America/Vancouver",
        )
    )
    assert str(timezone_trigger.timezone) == "America/Vancouver"


def test_scheduler_validation_rejects_cross_type_and_malformed_schedule_values() -> None:
    with pytest.raises(ValueError, match="cron schedules"):
        validate_schedule("cron", "0 9 * * *", 60, None)
    with pytest.raises(ValueError, match="require interval_seconds"):
        validate_schedule("interval", "", True, None)
    with pytest.raises(ValueError, match="between 1"):
        validate_schedule("interval", "", 31_536_001, None)
    with pytest.raises(ValueError, match="cannot include cron"):
        validate_schedule("interval", "0 9 * * *", 60, None)
    with pytest.raises(ValueError, match="require run_at"):
        validate_schedule("once", "", None, "")
    with pytest.raises(ValueError, match="cannot include cron"):
        validate_schedule("once", "0 9 * * *", None, "2099-01-01T00:00:00+00:00")
    with pytest.raises(ValueError, match="ISO-8601"):
        validate_schedule("once", "", None, "not-a-timestamp")
    with pytest.raises(ValueError, match="schedule_type"):
        validate_schedule("unsupported", "", None, None)
    assert _schedule_trigger(  # noqa: SLF001
        ScheduledJob(
            id=2,
            template_id="template",
            cron="",
            params_json="{}",
            paused=False,
            created_at="",
            updated_at="",
            schedule_type="once",
            run_at="2099-01-01T00:00:00+00:00",
        )
    ) is not None


def test_scheduler_does_not_replay_expired_one_time_jobs(tmp_path: Path) -> None:
    async def scenario() -> None:
        store = Store(tmp_path / "state.db")
        manager = SchedulerManager(store, enabled=True)
        manager.start()
        expired = store.create_scheduled_job(
            "documentation-assisted-response",
            "",
            {"ticket_id": "TCK-1001"},
            schedule_type="once",
            run_at="2020-01-01T00:00:00+00:00",
        )
        manager._register_live_job(expired)  # noqa: SLF001
        assert manager._scheduler is not None  # noqa: SLF001
        assert manager._scheduler.get_job(manager._job_identity(expired.id or 0)) is None  # noqa: SLF001
        manager.shutdown()

    asyncio.run(scenario())


def test_scheduler_ignores_jobs_without_runtime_identity(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.db")
    manager = SchedulerManager(store, enabled=True)
    async def scenario() -> None:
        manager.start()
        manager._register_live_job(  # noqa: SLF001
            ScheduledJob(
                id=None,
                template_id="template",
                cron="0 9 * * *",
                params_json="{}",
                paused=False,
                created_at="",
                updated_at="",
            )
        )
        manager.shutdown()

    asyncio.run(scenario())


def test_scheduler_disabled_mode_and_failed_run_are_audited(tmp_path: Path) -> None:
    db_path = tmp_path / "state.db"
    _seed_tickets(db_path)

    async def scenario() -> None:
        store = Store(db_path)
        manager = SchedulerManager(store, enabled=False)
        manager.start()
        manager.start()
        scheduled_job = manager.register(
            "documentation-assisted-response",
            "0 9 * * *",
            {"ticket_id": "NOPE", "client_id": "acme"},
        )

        assert manager.enabled is False
        assert manager.list_jobs()[0].next_run_at is None
        assert store.get_scheduled_job(scheduled_job.id or 0) is not None
        rescheduled = manager.reschedule(
            scheduled_job.id or 0,
            schedule_type="interval",
            cron="",
            interval_seconds=60,
            run_at=None,
        )
        assert rescheduled.schedule_type == "interval"

        with pytest.raises(LookupError):
            await manager._build_job_callable(scheduled_job)()
        assert any(event.event_type == "scheduled_job.trigger_failed" for event in store.list_audit_events())

        manager.pause(scheduled_job.id or 0)
        manager.resume(scheduled_job.id or 0)
        manager.remove(scheduled_job.id or 0)

        manager.shutdown()
        manager.shutdown()

    asyncio.run(scenario())


def test_scheduler_skips_agent_when_execution_window_is_closed(settings, tmp_path: Path) -> None:
    db_path = tmp_path / "state.db"
    _seed_tickets(db_path)
    store = Store(db_path)
    with store._connect() as connection:  # noqa: SLF001
        connection.execute("update tickets set client_id = 'acme'")
    agent_service = AgentService(store, settings, SmartActionService(store, settings))
    now = datetime.now(UTC)
    definition = agent_service.create(
        name="Closed scheduled agent",
        description="Wait for the configured execution window.",
        enabled=True,
        trigger="scheduled",
        entity_type="ticket",
        filters={},
        enabled_tools=["ticket-triage"],
        steps=[{"tool_id": "ticket-triage", "payload": {}}],
        max_steps=1,
        execution_timeout_seconds=30,
        client_id="acme",
        execution_window_start=(now + timedelta(hours=2)).strftime("%H:%M"),
        execution_window_end=(now + timedelta(hours=3)).strftime("%H:%M"),
        execution_window_timezone="UTC",
    )
    manager = SchedulerManager(store, enabled=False, agent_service=agent_service)
    scheduled_job = manager.register(
        "",
        "0 9 * * *",
        {"client_id": "acme", "input": {}},
        job_kind="agent",
        agent_id=definition.id,
        entity_id="TCK-1001",
    )

    async def scenario() -> None:
        await manager._build_job_callable(scheduled_job)()

    asyncio.run(scenario())

    assert store.list_agent_runs(client_id="acme") == []
    events = store.list_audit_events(client_id="acme")
    assert any(event.event_type == "scheduled_job.window_closed" for event in events)
    assert not any(event.event_type == "scheduled_job.trigger_failed" for event in events)


def test_scheduler_start_respects_paused_jobs_and_workflow_variants(settings, tmp_path: Path) -> None:
    db_path = tmp_path / "state.db"
    store = Store(db_path)
    store.ingest_ticket_file(Path("examples/sample_tickets/tickets.json"))
    paused_job = store.create_scheduled_job(
        "ticket-triage",
        "0 9 * * *",
        {"ticket_id": "TCK-1001"},
        paused=True,
    )

    async def scenario() -> None:
        manager = SchedulerManager(store, enabled=True)
        manager.start()
        jobs = manager.list_jobs()
        triage_run = run_workflow_template(store, "ticket-triage", "TCK-1001")
        assign_run = run_workflow_template(store, "assign-technician", "TCK-1001")
        follow_up_run = run_workflow_template(store, "inactive-ticket-follow-up", "TCK-1001")
        alert_run = run_workflow_template(store, "p1-alert", "TCK-1001")

        assert paused_job.id is not None
        assert jobs[0].paused is True
        assert jobs[0].next_run_at is None
        assert triage_run.status == "completed"
        assert "Classified TCK-1001 as" in triage_run.message
        assert "assignment" in assign_run.message
        assert "follow-up" in follow_up_run.message
        assert "priority alert" in alert_run.message

        manager.shutdown()

    asyncio.run(scenario())

    with pytest.raises(KeyError):
        run_workflow_template(store, "missing-template", "TCK-1001")
    with pytest.raises(LookupError):
        run_workflow_template(store, "ticket-triage", "NOPE")


def test_tool_backed_workflow_reuses_smart_action_contract(settings) -> None:
    store = Store(settings.data_path)
    _seed_tickets(settings.data_path)
    with store._connect() as connection:  # noqa: SLF001
        connection.execute("update tickets set client_id = ? where id = ?", ("acme", "TCK-1001"))
    service = SmartActionService(store, settings)

    run = run_workflow_template(
        store,
        "ticket-quality-review",
        "TCK-1001",
        actor="technician",
        client_id="acme",
        tool_executor=service,
    )

    assert run.status == "completed"
    assert "ticket quality review" in run.message.lower()
    action_runs = store.list_smart_action_runs(client_id="acme")
    assert len(action_runs) == 1
    assert action_runs[0].action_id == "ticket-quality"
    assert action_runs[0].status == "success"


def test_tool_backed_workflow_requires_executor(settings) -> None:
    store = Store(settings.data_path)
    _seed_tickets(settings.data_path)

    with pytest.raises(RuntimeError, match="workflow tool ticket-quality is not configured"):
        run_workflow_template(store, "ticket-quality-review", "TCK-1001")


@pytest.mark.parametrize(
    ("result", "expected_status"),
    [
        (ActionResult(status="failed", error_detail="token=should-not-leak"), "failed"),
        (ActionResult(status="pending_approval", approval_id=91), "pending_approval"),
    ],
)
def test_tool_backed_workflow_maps_non_success_tool_results(settings, result, expected_status) -> None:
    store = Store(settings.data_path)
    _seed_tickets(settings.data_path)

    class StubExecutor:
        def invoke(self, *_args, **_kwargs):
            return result

    run = run_workflow_template(
        store,
        "ticket-quality-review",
        "TCK-1001",
        actor="technician",
        tool_executor=StubExecutor(),
    )

    assert run.status == expected_status
    if expected_status == "failed":
        assert "should-not-leak" not in run.message
        assert "[redacted]" in run.message
    else:
        assert run.approval_request_id == 91


def test_security_and_store_error_edges(settings) -> None:
    secure_settings = Settings(
        **{
            **settings.__dict__,
            "demo_mode": False,
            "viewer_token": "viewer-token",
        }
    )
    store = Store(settings.data_path)

    require_bearer_authorization(secure_settings, "Bearer viewer-token")

    with pytest.raises(KeyError):
        store.update_approval_request(999, "approved")
    with pytest.raises(KeyError):
        store.update_approval_request_payload(999, {"ticket_id": "TCK-1"})
    with pytest.raises(KeyError):
        store.record_approval_execution(999, status="failed", message="nope", result={})
    with pytest.raises(KeyError):
        store.update_scheduled_job_paused(999, True)
    with pytest.raises(KeyError):
        store.delete_scheduled_job(999)
    assert store.get_workflow_run_for_approval(999) is None


def test_scheduled_agent_uses_persisted_definition_and_records_run(settings, tmp_path: Path) -> None:
    db_path = tmp_path / "agent-schedule.db"
    store = Store(db_path)
    _seed_tickets(db_path)
    with store._connect() as connection:  # noqa: SLF001
        connection.execute("update tickets set client_id = ?", ("acme",))
    agent_service = AgentService(store, settings, SmartActionService(store, settings))
    definition = agent_service.create(
        name="Scheduled triage",
        description="Runs deterministic triage on a schedule.",
        enabled=True,
        trigger="scheduled",
        entity_type="ticket",
        filters={},
        enabled_tools=["ticket-triage"],
        steps=[{"tool_id": "ticket-triage", "payload": {}}],
        max_steps=1,
        execution_timeout_seconds=30,
        client_id="acme",
    )

    async def scenario() -> None:
        manager = SchedulerManager(store, enabled=False, agent_service=agent_service)
        scheduled_job = manager.register(
            "",
            "0 9 * * *",
            {"client_id": "acme", "input": {"instruction": "triage"}},
            job_kind="agent",
            agent_id=definition.id,
            entity_id="TCK-1001",
        )

        await manager._build_job_callable(scheduled_job)()

        runs = store.list_agent_runs(client_id="acme")
        assert len(runs) == 1
        assert runs[0].actor == "scheduler"
        assert runs[0].status == "completed"
        assert any(event.event_type == "scheduled_job.triggered" for event in store.list_audit_events())

    asyncio.run(scenario())


def test_scheduled_agent_validation_and_failure_paths_are_audited(settings, tmp_path: Path) -> None:
    db_path = tmp_path / "agent-schedule-failures.db"
    store = Store(db_path)
    _seed_tickets(db_path)
    agent_service = AgentService(store, settings, SmartActionService(store, settings))
    manual = agent_service.create(
        name="Manual triage",
        description="Manual only.",
        enabled=True,
        trigger="manual",
        entity_type="ticket",
        filters={},
        enabled_tools=["ticket-triage"],
        steps=[{"tool_id": "ticket-triage", "payload": {}}],
        max_steps=1,
        execution_timeout_seconds=30,
        client_id=None,
    )
    scheduled = agent_service.create(
        name="Scheduled triage",
        description="Scheduled only.",
        enabled=True,
        trigger="scheduled",
        entity_type="ticket",
        filters={},
        enabled_tools=["ticket-triage"],
        steps=[{"tool_id": "ticket-triage", "payload": {}}],
        max_steps=1,
        execution_timeout_seconds=30,
        client_id=None,
    )

    with pytest.raises(ValueError, match="workflow schedules"):
        SchedulerManager(store, enabled=False).register(
            "template",
            "0 9 * * *",
            {},
            job_kind="workflow",
            agent_id="agent",
        )
    with pytest.raises(ValueError, match="agent schedules"):
        SchedulerManager(store, enabled=False).register(
            "",
            "0 9 * * *",
            {},
            job_kind="agent",
            agent_id="agent",
        )
    with pytest.raises(ValueError, match="unsupported"):
        SchedulerManager(store, enabled=False).register(
            "",
            "0 9 * * *",
            {},
            job_kind="other",
        )

    async def scenario() -> None:
        no_service = SchedulerManager(store, enabled=False)
        no_service_job = no_service.register(
            "",
            "0 9 * * *",
            {},
            job_kind="agent",
            agent_id="missing",
            entity_id="TCK-1001",
        )
        with pytest.raises(RuntimeError, match="not configured"):
            await no_service._build_job_callable(no_service_job)()

        manager = SchedulerManager(store, enabled=False, agent_service=agent_service)
        missing_job = manager.register(
            "",
            "0 9 * * *",
            {},
            job_kind="agent",
            agent_id="missing",
            entity_id="TCK-1001",
        )
        with pytest.raises(LookupError, match="definition"):
            await manager._build_job_callable(missing_job)()

        wrong_trigger_job = manager.register(
            "",
            "0 9 * * *",
            {},
            job_kind="agent",
            agent_id=manual.id,
            entity_id="TCK-1001",
        )
        with pytest.raises(ValueError, match="wrong trigger"):
            await manager._build_job_callable(wrong_trigger_job)()

        bad_input_job = manager.register(
            "",
            "0 9 * * *",
            {"input": ["not", "an", "object"]},
            job_kind="agent",
            agent_id=scheduled.id,
            entity_id="TCK-1001",
        )
        with pytest.raises(ValueError, match="input"):
            await manager._build_job_callable(bad_input_job)()

        missing_entity = store.create_scheduled_job(
            "",
            "0 9 * * *",
            {},
            job_kind="agent",
            agent_id=scheduled.id,
            entity_id=None,
        )
        with pytest.raises(ValueError, match="missing agent_id or entity_id"):
            await manager._build_job_callable(missing_entity)()

        scoped = agent_service.create(
            name="Acme scheduled triage",
            description="Tenant-scoped scheduled agent.",
            enabled=True,
            trigger="scheduled",
            entity_type="ticket",
            filters={},
            enabled_tools=["ticket-triage"],
            steps=[{"tool_id": "ticket-triage", "payload": {}}],
            max_steps=1,
            execution_timeout_seconds=30,
            client_id="acme",
        )
        mismatch = manager.register(
            "",
            "0 9 * * *",
            {"client_id": "beta"},
            job_kind="agent",
            agent_id=scoped.id,
            entity_id="TCK-1001",
        )
        with pytest.raises(PermissionError, match="tenant scope"):
            await manager._build_job_callable(mismatch)()

        failed_run = manager.register(
            "",
            "0 9 * * *",
            {},
            job_kind="agent",
            agent_id=scheduled.id,
            entity_id="NOPE",
        )
        with pytest.raises(Exception, match="ticket was not found"):
            await manager._build_job_callable(failed_run)()

        with store._connect() as connection:  # noqa: SLF001
            connection.execute("update tickets set client_id = ?", ("acme",))
        replacement_job = manager.register(
            "",
            "0 9 * * *",
            {"client_id": "acme"},
            job_kind="agent",
            agent_id=scheduled.id,
            entity_id="TCK-1001",
        )
        await manager._build_job_callable(replacement_job)()

        missing_ticket = store.create_scheduled_job("", "0 9 * * *", {})
        with pytest.raises(ValueError, match="ticket_id"):
            await manager._build_job_callable(missing_ticket)()

        failed_events = [
            event
            for event in store.list_audit_events()
            if event.event_type == "scheduled_job.trigger_failed"
        ]
        assert len(failed_events) >= 4

    asyncio.run(scenario())


def _seed_tickets(db_path: Path) -> None:
    Store(db_path).ingest_ticket_file(Path("examples/sample_tickets/tickets.json"))
