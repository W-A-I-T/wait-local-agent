from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from wait_local_agent.config import Settings
from wait_local_agent.scheduler import SchedulerManager, validate_cron_expression
from wait_local_agent.security import require_bearer_authorization
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

        paused = manager.pause(scheduled_job.id or 0)
        resumed = manager.resume(scheduled_job.id or 0)
        deleted = manager.remove(scheduled_job.id or 0)

        assert paused.paused is True
        assert paused.next_run_at is None
        assert resumed.paused is False
        assert resumed.next_run_at is not None
        assert deleted.id == scheduled_job.id
        assert store.get_scheduled_job(scheduled_job.id or 0) is None

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

        with pytest.raises(LookupError):
            await manager._build_job_callable(scheduled_job)()
        assert any(event.event_type == "scheduled_job.trigger_failed" for event in store.list_audit_events())

        manager.shutdown()
        manager.shutdown()

    asyncio.run(scenario())


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


def _seed_tickets(db_path: Path) -> None:
    Store(db_path).ingest_ticket_file(Path("examples/sample_tickets/tickets.json"))
