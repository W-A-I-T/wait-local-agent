from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

import wait_local_agent.scheduler as scheduler_module
from tests.support import ingest_local
from wait_local_agent.agents import AgentService
from wait_local_agent.config import Settings
from wait_local_agent.event_dispatch import EventDispatcher
from wait_local_agent.ingestion_poller import IngestionPoller, PollStatus, PollSummary
from wait_local_agent.models import ScheduledJob
from wait_local_agent.rbac import Role
from wait_local_agent.scheduler import (
    SCHEDULED_JOB_MAX_INSTANCES,
    SCHEDULED_JOB_MISFIRE_GRACE_TIME_SECONDS,
    SchedulerManager,
    _backup_retention_count,
    _founder_poll_due,
    _schedule_trigger,
    _validate_schedule_target,
    validate_cron_expression,
    validate_schedule,
    validate_scheduled_report_params,
    validate_timezone,
)
from wait_local_agent.security import require_bearer_authorization
from wait_local_agent.smart_actions import (
    ActionResult,
    M365LicenseWriteProvider,
    SmartActionService,
)
from wait_local_agent.store import Store
from wait_local_agent.vault import SecretVault
from wait_local_agent.workflows import get_workflow_template, run_workflow_template


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
        assert reloaded_manager._scheduler is not None  # noqa: SLF001
        live_job = reloaded_manager._scheduler.get_job(  # noqa: SLF001
            reloaded_manager._job_identity(scheduled_job.id)
        )
        assert live_job is not None
        assert live_job.max_instances == SCHEDULED_JOB_MAX_INSTANCES
        assert live_job.misfire_grace_time == SCHEDULED_JOB_MISFIRE_GRACE_TIME_SECONDS

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
        founder_job = manager._scheduler.get_job(manager._founder_poll_job_identity())  # noqa: SLF001
        assert founder_job is not None
        assert founder_job.max_instances == 1
        assert founder_job.coalesce is True
        manager._retry_due_event_deliveries()  # noqa: SLF001
        manager.shutdown()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("case", "mode_values"),
    [
        ("demo", {"demo_mode": True, "offline_mode": False}),
        ("offline", {"demo_mode": False, "offline_mode": True}),
        ("not_configured", {"demo_mode": False, "offline_mode": False}),
    ],
)
def test_founder_polling_idle_ticks_do_not_write_audit_rows(
    tmp_path: Path, settings, case: str, mode_values: dict[str, bool]
) -> None:
    runtime_settings = replace(settings, **mode_values)
    store = Store(tmp_path / f"founder-{case}.db")
    manager = SchedulerManager(store, enabled=True, settings=runtime_settings)

    async def scenario() -> None:
        manager.start()

        assert manager._scheduler is not None  # noqa: SLF001
        founder_job = manager._scheduler.get_job(manager._founder_poll_job_identity())  # noqa: SLF001
        if case in {"demo", "offline"}:
            assert founder_job is None
        else:
            assert founder_job is not None

        for _ in range(10):
            manager._run_founder_poll_iteration()  # noqa: SLF001

        assert store.list_audit_events() == []
        manager.shutdown()

    asyncio.run(scenario())


def test_founder_poll_due_handles_empty_invalid_naive_and_aware_values() -> None:
    now = datetime(2026, 8, 16, 12, 0, tzinfo=UTC)
    assert _founder_poll_due(None, now) is True
    assert _founder_poll_due("", now) is True
    assert _founder_poll_due("not-a-timestamp", now) is True
    assert _founder_poll_due("2026-08-16T11:59:00", now) is True
    assert _founder_poll_due("2026-08-16T12:01:00+00:00", now) is False


def test_scheduler_job_callable_creates_same_approval_path_as_manual_run(tmp_path: Path, settings) -> None:
    db_path = tmp_path / "state.db"
    _seed_tickets(db_path)
    with Store(db_path)._connect() as connection:  # noqa: SLF001
        connection.execute("update tickets set client_id = 'acme'")

    async def scenario() -> None:
        store = Store(db_path)
        service = SmartActionService(store, replace(settings, data_path=db_path))
        manual_run = run_workflow_template(
            store,
            "documentation-assisted-response",
            "TCK-1001",
            client_id="acme",
            actor="requester",
            tool_executor=service,
        )
        manual_approval = store.get_approval_request(manual_run.approval_request_id or 0)
        manager = SchedulerManager(store, enabled=False, smart_action_service=service)
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
        assert scheduled_approval.subject_id != manual_approval.subject_id
        scheduled_payload = json.loads(scheduled_approval.payload_json)
        manual_payload = json.loads(manual_approval.payload_json)
        assert scheduled_payload["action_id"] == manual_payload["action_id"]
        assert scheduled_payload["payload"]["ticket_id"] == manual_payload["payload"]["ticket_id"]

    asyncio.run(scenario())


def test_scheduler_playbook_job_reuses_bounded_playbook_and_approval_path(tmp_path: Path, settings) -> None:
    db_path = tmp_path / "playbook-schedule.db"
    _seed_tickets(db_path)
    with Store(db_path)._connect() as connection:  # noqa: SLF001
        connection.execute("update tickets set client_id = 'acme'")

    async def scenario() -> None:
        store = Store(db_path)
        service = SmartActionService(store, replace(settings, data_path=db_path))
        manager = SchedulerManager(store, enabled=False, smart_action_service=service)
        scheduled_job = manager.register(
            "security-response-review",
            "0 9 * * *",
            {"ticket_id": "TCK-1001", "client_id": "acme", "input": {}},
            job_kind="playbook",
        )

        await manager._build_job_callable(scheduled_job)()  # noqa: SLF001

        events = store.list_audit_events(client_id="acme")
        assert any(event.event_type == "msp.playbook.started" for event in events)
        assert any(event.event_type == "msp.playbook.stopped" for event in events)
        assert any(event.event_type == "scheduled_job.triggered" for event in events)
        assert store.list_approval_requests(client_id="acme")

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
        smart_action_service=SmartActionService(store, settings),
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


def test_scheduler_validation_supports_connector_poll_targets() -> None:
    _validate_schedule_target("connector_poll", "", None, "connector-1")

    with pytest.raises(ValueError, match="connector_poll schedules require entity_id only"):
        _validate_schedule_target("connector_poll", "template", None, "connector-1")
    with pytest.raises(ValueError, match="connector_poll schedules require entity_id only"):
        _validate_schedule_target("connector_poll", "", "agent-1", "connector-1")


def test_scheduler_graph_sync_validates_runs_and_audits(tmp_path: Path, monkeypatch) -> None:
    _validate_schedule_target("graph_sync", "", None, "client-a")
    with pytest.raises(ValueError, match="graph_sync schedules require entity_id only"):
        _validate_schedule_target("graph_sync", "template", None, "client-a")

    store = Store(tmp_path / "graph-sync.db")
    calls: list[str] = []

    def run_graph_sync(client_id: str) -> dict[str, str]:
        calls.append(client_id)
        return {"status": "ready"}

    manager = SchedulerManager(store, enabled=False, graph_sync_runner=run_graph_sync)
    scheduled_job = manager.register(
        "",
        "0 9 * * *",
        {"client_id": "client-a"},
        job_kind="graph_sync",
        entity_id="client-a",
    )

    async def run_in_thread(function, *args, **kwargs):
        return function(*args, **kwargs)

    monkeypatch.setattr("wait_local_agent.scheduler.asyncio.to_thread", run_in_thread)
    asyncio.run(manager._run_job(scheduled_job))  # noqa: SLF001

    assert calls == ["client-a"]
    events = store.list_audit_events()
    assert any(
        event.event_type == "scheduled_job.graph_sync" and "completed" in event.detail
        for event in events
    )


def test_scheduler_graph_sync_scope_validation_skip_and_failure_are_isolated(
    tmp_path: Path, monkeypatch
) -> None:
    store = Store(tmp_path / "graph-sync-edges.db")
    with pytest.raises(ValueError, match="must match entity_id"):
        SchedulerManager(store, enabled=False).register(
            "", "0 9 * * *", {"client_id": "other"}, job_kind="graph_sync", entity_id="client-a"
        )

    async def run_in_thread(function, *args, **kwargs):
        return function(*args, **kwargs)

    monkeypatch.setattr("wait_local_agent.scheduler.asyncio.to_thread", run_in_thread)
    valid_job = ScheduledJob(
        id=7, template_id="", cron="0 9 * * *", params_json="{}", paused=False,
        created_at="", updated_at="", job_kind="graph_sync", entity_id="client-a",
    )
    asyncio.run(SchedulerManager(store, enabled=False)._run_job(replace(valid_job, entity_id=None)))
    manager = SchedulerManager(
        store, enabled=False, graph_sync_runner=lambda _client: (_ for _ in ()).throw(
            RuntimeError("access_token=graph-secret")
        )
    )
    asyncio.run(manager._run_job(valid_job))
    event = next(event for event in store.list_audit_events() if event.event_type == "scheduled_job.graph_sync")
    assert "graph-secret" not in event.detail
    assert "access_token" not in event.detail


def test_scheduler_baseline_snapshot_validates_registers_triggers_and_sanitizes_failure(
    tmp_path: Path, monkeypatch
) -> None:
    _validate_schedule_target("baseline_snapshot", "", None, "client-a")
    with pytest.raises(ValueError, match="baseline_snapshot schedules require entity_id only"):
        _validate_schedule_target("baseline_snapshot", "template", None, "client-a")

    store = Store(tmp_path / "baseline-snapshot.db")
    calls: list[str] = []

    def run_baseline_snapshot(client_id: str) -> SimpleNamespace:
        calls.append(client_id)
        return SimpleNamespace(version=3)

    manager = SchedulerManager(store, enabled=False, baseline_snapshot_runner=run_baseline_snapshot)
    scheduled_job = manager.register(
        "",
        "0 9 * * *",
        {"client_id": "client-a"},
        job_kind="baseline_snapshot",
        entity_id="client-a",
    )

    async def run_in_thread(function, *args, **kwargs):
        return function(*args, **kwargs)

    monkeypatch.setattr("wait_local_agent.scheduler.asyncio.to_thread", run_in_thread)
    asyncio.run(manager._run_job(scheduled_job))  # noqa: SLF001

    assert calls == ["client-a"]
    completed = next(
        event
        for event in store.list_audit_events(client_id="client-a")
        if event.event_type == "scheduled_job.baseline_snapshot"
    )
    assert "completed (version 3)" in completed.detail

    def fail_baseline_snapshot(_client_id: str) -> None:
        raise RuntimeError("provider request failed with token=abc")

    failing_manager = SchedulerManager(
        store,
        enabled=False,
        baseline_snapshot_runner=fail_baseline_snapshot,
    )
    asyncio.run(failing_manager._run_job(scheduled_job))  # noqa: SLF001

    events = store.list_audit_events()
    failed = next(
        event
        for event in events
        if event.event_type == "scheduled_job.baseline_snapshot"
        and "failed" in event.detail
        and "baseline" in event.detail
    )
    assert failed.detail == "scheduled baseline snapshot -> failed: RuntimeError: provider request failed"
    assert "provider request failed with token=abc" not in failed.detail
    assert all("token" not in event.detail for event in events)


def test_scheduler_skips_quarantined_workflow_playbook_and_agent_jobs(tmp_path: Path) -> None:
    store = Store(tmp_path / "quarantine-skip.db")
    manager = SchedulerManager(store, enabled=False)
    manager._is_quarantined_ticket = lambda *_args: True  # type: ignore[method-assign]  # noqa: SLF001

    workflow = ScheduledJob(
        id=1, template_id="template", cron="0 9 * * *", params_json=json.dumps({"ticket_id": "T-1"}),
        paused=False, created_at="", updated_at="", job_kind="workflow",
    )
    playbook = replace(workflow, id=2, job_kind="playbook")
    agent = replace(workflow, id=3, job_kind="agent", agent_id="agent-1", entity_id="T-1")

    async def scenario() -> None:
        await manager._run_job(workflow)  # noqa: SLF001
        await manager._run_job(playbook)  # noqa: SLF001
        await manager._run_job(agent)  # noqa: SLF001

    asyncio.run(scenario())
    assert store.list_audit_events() == []


def test_scheduler_workflow_and_playbook_input_failures_are_audited(
    tmp_path: Path, monkeypatch
) -> None:
    store = Store(tmp_path / "scheduled-input-failures.db")
    manager = SchedulerManager(store, enabled=False)
    workflow = ScheduledJob(
        id=1, template_id="template", cron="0 9 * * *", params_json=json.dumps({"ticket_id": "T-1", "input": []}),
        paused=False, created_at="", updated_at="", job_kind="workflow",
    )
    playbook = replace(workflow, id=2, job_kind="playbook")

    async def scenario() -> None:
        for job, message in ((workflow, "workflow input"), (playbook, "playbook input")):
            with pytest.raises(ValueError, match=message):
                await manager._run_job(job)  # noqa: SLF001

    asyncio.run(scenario())
    assert len([e for e in store.list_audit_events() if e.event_type == "scheduled_job.trigger_failed"]) == 2

    def fail_playbook(*_args, **_kwargs):
        raise RuntimeError("provider access_token=secret")

    monkeypatch.setattr("wait_local_agent.scheduler.run_msp_playbook", fail_playbook)
    failing = replace(playbook, id=3, params_json=json.dumps({"ticket_id": "T-1", "input": {}}))
    with pytest.raises(RuntimeError):
        asyncio.run(manager._run_job(failing))  # noqa: SLF001
    event = next(e for e in store.list_audit_events() if e.subject_id == "3")
    assert "secret" not in event.detail


def test_scheduler_deterministic_noop_and_validation_edges(tmp_path: Path, monkeypatch) -> None:
    store = Store(tmp_path / "scheduler-edges.db")
    manager = SchedulerManager(store, enabled=False)
    job = ScheduledJob(
        id=4, template_id="template", cron="0 9 * * *", params_json=json.dumps({"ticket_id": "T-1"}),
        paused=False, created_at="", updated_at="", job_kind="workflow",
    )

    monkeypatch.setattr(
        "wait_local_agent.scheduler.run_workflow_template",
        lambda *_args, **_kwargs: SimpleNamespace(id=None),
    )
    asyncio.run(manager._run_job(job))  # noqa: SLF001
    manager._dispatch_completion(  # noqa: SLF001
        run_id=None,
        ticket_id="T-1",
        template_id="template",
        status="completed",
        actor="scheduler",
    )
    manager._retry_due_event_deliveries()  # noqa: SLF001

    with pytest.raises(ValueError, match="unsupported scheduled job kind"):
        _validate_schedule_target("unknown", "", None, None)
    with pytest.raises(ValueError, match="playbook schedules"):
        _validate_schedule_target("playbook", "", None, None)
    with pytest.raises(ValueError, match="valid IANA timezone"):
        validate_timezone("")
    with pytest.raises(ValueError, match="scheduled report type"):
        asyncio.run(manager._run_report_job(job, {"client_id": "acme", "period_days": 1}, "acme"))  # noqa: SLF001
    with pytest.raises(ValueError, match="follow_up_after_days"):
        validate_scheduled_report_params({"client_id": "acme", "period_days": 1, "follow_up_after_days": 0})
    with pytest.raises(ValueError, match="period_days"):
        validate_scheduled_report_params({"client_id": "acme", "period_days": 0})
    with pytest.raises(ValueError, match="include client_id"):
        validate_scheduled_report_params({"period_days": 1})


def test_scheduler_backup_registration_and_runner_edges(tmp_path: Path, monkeypatch) -> None:
    store = Store(tmp_path / "backup-edges.db")
    manager = SchedulerManager(store, enabled=False)

    with pytest.raises(ValueError, match="appliance-level"):
        manager.register("", "0 9 * * *", {"client_id": "tenant"}, job_kind="backup")
    failed = manager.run_backup()
    assert failed.status == "failed"
    assert failed.failure_summary == "backup creation failed"

    destination = tmp_path / "backups" / "state-string.db.enc"
    destination.parent.mkdir()
    destination.write_bytes(b"backup")
    string_manager = SchedulerManager(store, enabled=False, backup_runner=cast(Any, lambda: str(destination)))
    monkeypatch.setattr(scheduler_module, "prune_backup_files", lambda *_args: 1)
    pruned = string_manager.run_backup()
    assert pruned.status == "succeeded"
    assert pruned.destination == str(destination.resolve())
    assert pruned.failure_summary == "retention pruning failed"

    monkeypatch.setattr(scheduler_module, "prune_backup_files", lambda *_args: (_ for _ in ()).throw(OSError("busy")))
    failed_prune = string_manager.run_backup()
    assert failed_prune.status == "succeeded"
    assert failed_prune.failure_summary == "retention pruning failed"


def test_scheduler_backup_failure_logs_sanitized_correlation_id(settings, tmp_path: Path, caplog) -> None:
    secure_settings = replace(
        settings,
        secrets_backend="fernet",
        vault_path=tmp_path / "vault",
    )
    SecretVault.initialize(secure_settings.vault_path).set(
        "WAIT_BACKUP_FERNET_KEY",
        "not-a-fernet-key",
    )
    manager = SchedulerManager(Store(secure_settings.data_path), enabled=False, settings=secure_settings)

    with caplog.at_level(logging.ERROR, logger=scheduler_module.LOGGER.name):
        result = manager.run_backup()

    assert result.status == "failed"
    records = [record for record in caplog.records if "backup creation failed" in record.getMessage()]
    assert records
    assert records[0].levelno == logging.ERROR
    assert records[0].correlation_id
    assert "BackupEncryptionError" in records[0].getMessage()
    assert "not-a-fernet-key" not in caplog.text


def test_scheduler_baseline_and_completion_guards_are_noops(tmp_path: Path, caplog) -> None:
    store = Store(tmp_path / "scheduler-guards.db")
    manager = SchedulerManager(store, enabled=False)
    missing_runner = ScheduledJob(
        id=1, template_id="", cron="0 9 * * *", params_json="{}", paused=False,
        created_at="", updated_at="", job_kind="baseline_snapshot", entity_id="client-a",
    )
    missing_scope = replace(missing_runner, id=2, entity_id=" ")

    with caplog.at_level(logging.WARNING):
        asyncio.run(manager._run_baseline_snapshot_job(missing_runner))  # noqa: SLF001
        asyncio.run(manager._run_baseline_snapshot_job(missing_scope))  # noqa: SLF001
    assert caplog.messages.count("Scheduled baseline snapshot skipped: runner or client scope is not configured") == 2

    manager._dispatch_completion(  # noqa: SLF001
        run_id=None, ticket_id="T-1", template_id="template", status="completed", actor="scheduler"
    )
    store.set_app_config("backup.retention_count", "not-an-integer")
    assert _backup_retention_count(store) == 7


def test_scheduler_connector_poll_missing_entity_and_failure_are_audited(tmp_path: Path, monkeypatch) -> None:
    store = Store(tmp_path / "connector-poll-edges.db")
    manager = SchedulerManager(store, enabled=False, ingestion_poller=cast(IngestionPoller, object()))
    missing = ScheduledJob(
        id=1, template_id="", cron="0 9 * * *", params_json="{}", paused=False,
        created_at="", updated_at="", job_kind="connector_poll", entity_id=None,
    )
    asyncio.run(manager._run_job(missing))

    class FailingPoller:
        def poll_instance(self, *_args, **_kwargs):
            raise RuntimeError("poll failed")

    manager = SchedulerManager(store, enabled=False, ingestion_poller=cast(IngestionPoller, FailingPoller()))

    async def run_in_thread(function, *args, **kwargs):
        return function(*args, **kwargs)

    monkeypatch.setattr("wait_local_agent.scheduler.asyncio.to_thread", run_in_thread)
    job = replace(missing, id=2, entity_id="connector-1")
    asyncio.run(manager._run_job(job))
    assert any(event.detail == "scheduled sync -> failed" for event in store.list_audit_events())


@pytest.mark.parametrize("status", ["failed", "degraded", "skipped_locked"])
def test_scheduler_connector_poll_runs_in_thread_and_audits_status(
    tmp_path: Path, status: PollStatus, monkeypatch
) -> None:
    class RecordingPoller:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, float | int]]] = []

        def poll_instance(self, connector_instance_id: str, **kwargs: float | int) -> PollSummary:
            self.calls.append((connector_instance_id, kwargs))
            return PollSummary(connector_instance_id, 0, 0, 0, status, status)

    store = Store(tmp_path / f"connector-poll-{status}.db")
    poller = RecordingPoller()
    manager = SchedulerManager(store, enabled=False, ingestion_poller=cast(IngestionPoller, poller))
    scheduled_job = manager.register(
        "",
        "0 9 * * *",
        {},
        job_kind="connector_poll",
        entity_id="connector-1",
    )

    async def run_in_thread(function, *args, **kwargs):
        return function(*args, **kwargs)

    monkeypatch.setattr("wait_local_agent.scheduler.asyncio.to_thread", run_in_thread)
    monkeypatch.setattr(
        manager,
        "_is_quarantined_ticket",
        lambda *_args: pytest.fail("connector polls must not run the ticket quarantine guard"),
    )

    asyncio.run(manager._run_job(scheduled_job))  # noqa: SLF001

    assert poller.calls == [
        (
            "connector-1",
            {
                "max_pages": 25,
                "page_size": 50,
                "deadline_seconds": 60.0,
                "lease_ttl_seconds": 300.0,
            },
        )
    ]
    assert any(
        event.event_type == "scheduled_job.connector_poll"
        and event.detail == f"scheduled sync -> {status}"
        for event in store.list_audit_events()
    )


def test_scheduler_connector_poll_without_poller_is_safe_noop(tmp_path: Path, caplog) -> None:
    store = Store(tmp_path / "connector-poll-no-poller.db")
    manager = SchedulerManager(store, enabled=False)
    scheduled_job = manager.register(
        "",
        "0 9 * * *",
        {},
        job_kind="connector_poll",
        entity_id="connector-1",
    )

    asyncio.run(manager._run_job(scheduled_job))  # noqa: SLF001

    assert "ingestion poller is not configured" in caplog.text


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
    ingest_local(store, Path("examples/sample_tickets/tickets.json"))
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
        follow_up_run = run_workflow_template(
            store,
            "inactive-ticket-follow-up",
            "TCK-1001",
            actor="scheduler",
            tool_executor=SmartActionService(store, settings),
        )
        alert_run = run_workflow_template(
            store,
            "p1-alert",
            "TCK-1001",
            actor="scheduler",
            tool_executor=SmartActionService(store, settings),
        )

        assert paused_job.id is not None
        assert jobs[0].paused is True
        assert jobs[0].next_run_at is None
        assert triage_run.status == "completed"
        assert "Classified TCK-1001 as" in triage_run.message
        assert "assignment" in assign_run.message
        assert follow_up_run.status == "pending_approval"
        assert "approval required" in follow_up_run.message
        follow_up_approval = store.get_approval_request(follow_up_run.approval_request_id or 0)
        assert follow_up_approval is not None
        assert follow_up_approval.action_type == "smart_action:communication-send"
        assert alert_run.status == "pending_approval"
        assert "approval required" in alert_run.message
        alert_approval = store.get_approval_request(alert_run.approval_request_id or 0)
        assert alert_approval is not None
        assert alert_approval.action_type == "smart_action:communication-send"

        manager.shutdown()

    asyncio.run(scenario())

    with pytest.raises(KeyError):
        run_workflow_template(store, "missing-template", "TCK-1001")
    with pytest.raises(LookupError):
        run_workflow_template(store, "ticket-triage", "NOPE")


def test_inactive_ticket_follow_up_executes_local_note_only_after_approval(
    settings, tmp_path: Path
) -> None:
    store = Store(tmp_path / "follow-up.db")
    ingest_local(store, Path("examples/sample_tickets/tickets.json"))
    with store._connect() as connection:  # noqa: SLF001
        connection.execute("update tickets set client_id = 'acme'")
    service = SmartActionService(store, replace(settings, allow_write_actions=True))

    run = run_workflow_template(
        store,
        "inactive-ticket-follow-up",
        "TCK-1001",
        client_id="acme",
        actor="requester",
        tool_executor=service,
        input_payload={
            "channel": "ticket_note",
            "body": "Please confirm whether this issue is still active.",
        },
    )

    assert run.status == "pending_approval"
    approval = store.get_approval_request(run.approval_request_id or 0)
    assert approval is not None
    payload = json.loads(approval.payload_json)
    assert payload["payload"] == {
        "body": "Please confirm whether this issue is still active.",
        "channel": "ticket_note",
        "ticket_id": "TCK-1001",
    }
    assert store.list_ticket_notes("TCK-1001", client_id="acme") == []

    result = service.update_approval(
        run.approval_request_id or 0,
        "approved",
        approver="technician",
        approver_role=Role.TECHNICIAN,
    )

    assert result.status == "approved"
    notes = store.list_ticket_notes("TCK-1001", client_id="acme")
    assert [note.body for note in notes] == [
        "Please confirm whether this issue is still active."
    ]


def test_inactive_ticket_follow_up_preserves_draft_fallback_without_executor(
    settings, tmp_path: Path
) -> None:
    store = Store(tmp_path / "follow-up-draft.db")
    ingest_local(store, Path("examples/sample_tickets/tickets.json"))
    template = get_workflow_template("inactive-ticket-follow-up")
    assert template is not None

    run = run_workflow_template(
        store,
        "inactive-ticket-follow-up",
        "TCK-1001",
        template_override=replace(template, tool_id=None),
    )

    assert run.status == "pending_approval"
    assert "Drafted inactive ticket follow-up" in run.message

    p1_template = get_workflow_template("p1-alert")
    assert p1_template is not None
    p1_run = run_workflow_template(
        store,
        "p1-alert",
        "TCK-1001",
        template_override=replace(p1_template, tool_id=None),
    )
    assert p1_run.status == "pending_approval"
    assert "Prepared priority alert" in p1_run.message


def test_p1_alert_executes_local_note_only_after_approval(settings, tmp_path: Path) -> None:
    store = Store(tmp_path / "p1-alert.db")
    ingest_local(store, Path("examples/sample_tickets/tickets.json"))
    with store._connect() as connection:  # noqa: SLF001
        connection.execute("update tickets set client_id = 'acme'")
    service = SmartActionService(store, replace(settings, allow_write_actions=True))

    run = run_workflow_template(
        store,
        "p1-alert",
        "TCK-1001",
        client_id="acme",
        actor="monitor",
        tool_executor=service,
    )

    assert run.status == "pending_approval"
    approval = store.get_approval_request(run.approval_request_id or 0)
    assert approval is not None
    payload = json.loads(approval.payload_json)
    assert payload["payload"]["channel"] == "ticket_note"
    assert payload["payload"]["body"].startswith('P1 alert for ticket "')
    assert store.list_ticket_notes("TCK-1001", client_id="acme") == []

    result = service.update_approval(
        run.approval_request_id or 0,
        "approved",
        approver="technician",
        approver_role=Role.TECHNICIAN,
    )

    assert result.status == "approved"
    notes = store.list_ticket_notes("TCK-1001", client_id="acme")
    assert len(notes) == 1
    assert notes[0].body.startswith('P1 alert for ticket "')


def test_scheduler_runs_bounded_client_report_job(settings, tmp_path: Path) -> None:
    db_path = tmp_path / "scheduled-report.db"
    store = Store(db_path)
    ingest_local(store, Path("examples/sample_tickets/tickets.json"))
    with store._connect() as connection:  # noqa: SLF001
        connection.execute("update tickets set client_id = 'acme'")
    manager = SchedulerManager(
        store,
        enabled=False,
        smart_action_service=SmartActionService(store, settings),
    )
    scheduled_job = manager.register(
        "qbr",
        "0 9 * * *",
        {"client_id": "acme", "period_days": 30},
        job_kind="report",
    )
    automation_job = manager.register(
        "automation_opportunity",
        "0 9 * * *",
        {"client_id": "acme", "period_days": 30},
        job_kind="report",
    )
    recurring_job = manager.register(
        "recurring_service_review",
        "0 9 * * *",
        {"client_id": "acme", "period_days": 30, "follow_up_after_days": 14},
        job_kind="report",
    )

    async def scenario() -> None:
        await manager._build_job_callable(scheduled_job)()  # noqa: SLF001
        await manager._build_job_callable(automation_job)()  # noqa: SLF001
        await manager._build_job_callable(recurring_job)()  # noqa: SLF001

    asyncio.run(scenario())

    reports = store.list_reports(report_type="qbr", client_id="acme")
    assert len(reports) == 1
    assert reports[0].created_by == "scheduler"
    assert reports[0].metadata["client_id"] == "acme"
    assert reports[0].metadata["period_start"]
    assert reports[0].metadata["period_end"]
    automation_reports = store.list_reports(report_type="automation_opportunity", client_id="acme")
    assert len(automation_reports) == 1
    assert automation_reports[0].created_by == "scheduler"
    assert any(event.event_type == "report.created" for event in store.list_audit_events(client_id="acme"))
    assert any(event.event_type == "scheduled_job.triggered" for event in store.list_audit_events(client_id="acme"))
    recurring_reports = store.list_reports(report_type="recurring_service_review", client_id="acme")
    assert len(recurring_reports) == 1
    assert recurring_reports[0].metadata["follow_up_after_days"] == 14


def test_scheduler_report_failure_is_audited_and_does_not_create_report(tmp_path: Path) -> None:
    store = Store(tmp_path / "scheduled-report-failure.db")
    manager = SchedulerManager(store, enabled=False)
    scheduled_job = manager.register(
        "automation_opportunity",
        "0 9 * * *",
        {"client_id": "acme", "period_days": 30},
        job_kind="report",
    )

    async def scenario() -> None:
        with pytest.raises(RuntimeError, match="not configured"):
            await manager._build_job_callable(scheduled_job)()  # noqa: SLF001

    asyncio.run(scenario())

    assert store.list_reports(report_type="automation_opportunity", client_id="acme") == []
    failed = [
        event
        for event in store.list_audit_events(client_id="acme")
        if event.event_type == "scheduled_job.trigger_failed"
    ]
    assert len(failed) == 1
    assert "not configured" in failed[0].detail

    invalid_scope = SchedulerManager(store, enabled=False)
    with pytest.raises(ValueError, match="supported report type"):
        invalid_scope.register(
            "qbr",
            "0 9 * * *",
            {"client_id": "acme", "period_days": 30},
            job_kind="report",
            agent_id="agent-1",
        )

    missing_client_job = manager.register("qbr", "0 9 * * *", {}, job_kind="report")

    async def missing_client_scenario() -> None:
        with pytest.raises(ValueError, match="include client_id"):
            await manager._build_job_callable(missing_client_job)()  # noqa: SLF001

    asyncio.run(missing_client_scenario())


def test_scheduled_report_period_validation_covers_explicit_dates() -> None:
    validate_scheduled_report_params(
        {"client_id": "acme", "period_start": "2026-08-01", "period_end": "2026-08-31"}
    )
    with pytest.raises(ValueError, match="ISO dates"):
        validate_scheduled_report_params(
            {"client_id": "acme", "period_start": "not-a-date", "period_end": "2026-08-31"}
        )
    with pytest.raises(ValueError, match="on or after"):
        validate_scheduled_report_params(
            {"client_id": "acme", "period_start": "2026-08-31", "period_end": "2026-08-01"}
        )
    with pytest.raises(ValueError, match="cannot exceed"):
        validate_scheduled_report_params(
            {"client_id": "acme", "period_start": "2026-01-01", "period_end": "2027-01-02"}
        )


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


@pytest.mark.parametrize(
    ("template_id", "payload", "action_id"),
    [
        (
            "m365-user-onboarding-review",
            {
                "user_principal_name": "new.user@example.com",
                "display_name": "New User",
                "mail_nickname": "new.user",
                "temporary_vault_name": "WAIT_M365_TEMP_new_user",
            },
            "m365-user-onboarding",
        ),
        (
            "m365-user-offboarding-review",
            {"user_identity": "former.user@example.com", "user_id": "directory-user-1"},
            "m365-user-offboarding",
        ),
        (
            "m365-password-reset-review",
            {
                "user_identity": "user@example.com",
                "temporary_vault_name": "WAIT_M365_TEMP_user",
            },
            "m365-password-reset",
        ),
        (
            "m365-authentication-method-removal-review",
            {
                "user_identity": "user@example.com",
                "method_type": "fido2",
                "method_id": "method-1",
            },
            "m365-authentication-method-remove",
        ),
        (
            "m365-license-request-review",
            {
                "user_id": "directory-user-1",
                "sku_ids": ["11111111-1111-1111-1111-111111111111"],
                "operation": "add",
            },
            "m365-license-change",
        ),
    ],
)
def test_m365_workflow_templates_reuse_approval_gated_actions(
    settings, template_id: str, payload: dict[str, object], action_id: str
) -> None:
    class FakeM365Writes:
        def write_health(self):
            return type("Health", (), {"status": "ready", "message": "ready"})()

    store = Store(settings.data_path)
    _seed_tickets(settings.data_path)
    with store._connect() as connection:  # noqa: SLF001
        connection.execute("update tickets set client_id = ? where id = ?", ("acme", "TCK-1001"))
    service = SmartActionService(
        store,
        settings,
        m365_client=cast(M365LicenseWriteProvider, FakeM365Writes()),
    )

    run = run_workflow_template(
        store,
        template_id,
        "TCK-1001",
        actor="admin",
        client_id="acme",
        tool_executor=service,
        input_payload=payload,
    )

    assert run.status == "pending_approval", run.message
    assert run.approval_request_id is not None
    action_runs = store.list_smart_action_runs(client_id="acme")
    assert len(action_runs) == 1
    assert action_runs[0].action_id == action_id
    assert action_runs[0].status == "pending_approval"


@pytest.mark.parametrize(
    ("template_id", "tool_id", "expected_status"),
    [
        ("l1-resolution-review", "suggest-resolution", "completed"),
        ("duplicate-ticket-review", "find-similar-tickets", "completed"),
        ("technician-dispatch-review", "dispatch-suggestion", "pending_approval"),
    ],
)
def test_msp_review_templates_reuse_existing_local_tools(
    settings, template_id, tool_id, expected_status
) -> None:
    store = Store(settings.data_path)
    _seed_tickets(settings.data_path)
    with store._connect() as connection:  # noqa: SLF001
        connection.execute("update tickets set client_id = ? where id = ?", ("acme", "TCK-1001"))
    service = SmartActionService(store, settings)

    run = run_workflow_template(
        store,
        template_id,
        "TCK-1001",
        actor="technician",
        client_id="acme",
        tool_executor=service,
    )

    assert run.status == expected_status
    action_runs = store.list_smart_action_runs(client_id="acme")
    assert len(action_runs) == 1
    assert action_runs[0].action_id == tool_id
    expected_action_status = "pending_approval" if expected_status == "pending_approval" else "success"
    assert action_runs[0].status == expected_action_status


@pytest.mark.parametrize(
    ("template_id", "payload", "tool_id"),
    [
        (
            "ticket-sla-risk-review",
            {"thresholds_minutes": {"high": 1}},
            "ticket-sla-assessment",
        ),
        (
            "stale-ticket-sweep-review",
            {"stale_after_minutes": 1},
            "stale-ticket-sweep",
        ),
    ],
)
def test_threshold_review_templates_pass_bounded_payloads(settings, template_id, payload, tool_id) -> None:
    store = Store(settings.data_path)
    _seed_tickets(settings.data_path)
    with store._connect() as connection:  # noqa: SLF001
        connection.execute("update tickets set client_id = ? where id = ?", ("acme", "TCK-1001"))
    service = SmartActionService(store, settings)

    run = run_workflow_template(
        store,
        template_id,
        "TCK-1001",
        actor="technician",
        client_id="acme",
        tool_executor=service,
        input_payload=payload,
    )

    assert run.status == "completed"
    action_runs = store.list_smart_action_runs(client_id="acme")
    assert len(action_runs) == 1
    assert action_runs[0].action_id == tool_id
    assert action_runs[0].status == "success"


def test_workflow_payload_requires_declared_fields_and_preserves_client_scope(settings) -> None:
    store = Store(settings.data_path)
    _seed_tickets(settings.data_path)
    with store._connect() as connection:  # noqa: SLF001
        connection.execute("update tickets set client_id = ? where id = ?", ("acme", "TCK-1001"))

    with pytest.raises(ValueError, match="thresholds_minutes"):
        run_workflow_template(
            store,
            "ticket-sla-risk-review",
            "TCK-1001",
            client_id="acme",
            input_payload={},
        )
    with pytest.raises(LookupError):
        run_workflow_template(
            store,
            "ticket-quality-review",
            "TCK-1001",
            client_id="other-client",
        )
    with pytest.raises(ValueError, match="positive minutes"):
        run_workflow_template(
            store,
            "ticket-sla-risk-review",
            "TCK-1001",
            client_id="acme",
            input_payload={"thresholds_minutes": {"high": 0}},
        )
    with pytest.raises(ValueError, match="positive integer"):
        run_workflow_template(
            store,
            "stale-ticket-sweep-review",
            "TCK-1001",
            client_id="acme",
            input_payload={"stale_after_minutes": True},
        )


@pytest.mark.parametrize(
    ("payload", "error"),
    [
        ({"thresholds_minutes": {}}, "positive minutes"),
        ({"thresholds_minutes": {"high": "1"}}, "positive minutes"),
        ({"thresholds_minutes": {"high": 1}, **{f"extra_{index}": index for index in range(16)}}, "at most 16"),
        ({"thresholds_minutes": {"high": 1}, "notes": "x" * 8_000}, "at most 8000 bytes"),
        ({"thresholds_minutes": {"high": 1}, "unsupported": object()}, "JSON-compatible"),
    ],
)
def test_workflow_payload_rejects_unsafe_or_unbounded_values(settings, payload, error) -> None:
    store = Store(settings.data_path)
    _seed_tickets(settings.data_path)
    with store._connect() as connection:  # noqa: SLF001
        connection.execute("update tickets set client_id = ? where id = ?", ("acme", "TCK-1001"))

    with pytest.raises(ValueError, match=error):
        run_workflow_template(
            store,
            "ticket-sla-risk-review",
            "TCK-1001",
            client_id="acme",
            input_payload=payload,
        )


def test_workflow_payload_requires_json_object(settings) -> None:
    store = Store(settings.data_path)
    _seed_tickets(settings.data_path)

    with pytest.raises(ValueError, match="JSON object"):
        run_workflow_template(
            store,
            "ticket-triage",
            "TCK-1001",
            input_payload=[],  # type: ignore[arg-type]
        )


def test_scheduled_threshold_workflow_uses_bounded_input_payload(settings, tmp_path: Path) -> None:
    db_path = tmp_path / "threshold-schedule.db"
    _seed_tickets(db_path)
    store = Store(db_path)
    with store._connect() as connection:  # noqa: SLF001
        connection.execute("update tickets set client_id = ? where id = ?", ("acme", "TCK-1001"))

    async def scenario() -> None:
        manager = SchedulerManager(
            store,
            enabled=False,
            smart_action_service=SmartActionService(store, settings),
        )
        scheduled_job = manager.register(
            "ticket-sla-risk-review",
            "0 9 * * *",
            {
                "ticket_id": "TCK-1001",
                "client_id": "acme",
                "input": {"thresholds_minutes": {"high": 1}},
            },
        )

        await manager._build_job_callable(scheduled_job)()

        runs = store.list_workflow_runs(client_id="acme")
        assert len(runs) == 1
        assert runs[0].status == "completed"
        action_runs = store.list_smart_action_runs(client_id="acme")
        assert action_runs[0].action_id == "ticket-sla-assessment"
        assert action_runs[0].status == "success"

    asyncio.run(scenario())


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
    ingest_local(Store(db_path), Path("examples/sample_tickets/tickets.json"))
