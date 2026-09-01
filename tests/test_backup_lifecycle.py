from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi.testclient import TestClient

from wait_local_agent.api.app import create_app
from wait_local_agent.config import Settings
from wait_local_agent.models import ScheduledJob
from wait_local_agent.scheduler import SchedulerManager, _validate_schedule_target
from wait_local_agent.store import Store


def test_backup_scheduler_records_success_and_applies_retention(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.db")
    backup_directory = tmp_path / "backups"
    calls = 0

    def create_backup() -> Path:
        nonlocal calls
        calls += 1
        destination = backup_directory / f"state-{calls}.db.enc"
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(f"backup-{calls}".encode())
        return destination

    store.set_app_config("backup.retention_count", "2")
    manager = SchedulerManager(
        store,
        enabled=False,
        backup_runner=create_backup,
        backup_directory=backup_directory,
    )
    for _ in range(3):
        manager.run_backup(audit_event_type="scheduled_job.backup", subject_id="7")

    runs = store.list_backup_runs()
    assert len(runs) == 3
    assert all(run.status == "succeeded" for run in runs)
    assert len(list(backup_directory.glob("state-*.db.enc"))) == 2
    assert any(event.event_type == "scheduled_job.backup" for event in store.list_audit_events())


def test_failed_backup_is_recorded_without_runner_error_details(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.db")

    def failing_backup() -> Path:
        raise RuntimeError("provider path=/private/operator-data")

    result = SchedulerManager(store, enabled=False, backup_runner=failing_backup).run_backup()

    assert result.status == "failed"
    assert result.size_bytes is None
    assert result.failure_summary == "backup creation failed"
    assert "/private/operator-data" not in result.failure_summary


def test_backup_schedule_target_has_no_tenant_or_other_target() -> None:
    _validate_schedule_target("backup", "", None, None)

    try:
        _validate_schedule_target("backup", "other", None, None)
    except ValueError as exc:
        assert "no target" in str(exc)
    else:  # pragma: no cover - assertion branch
        raise AssertionError("backup schedule accepted a target")


def test_scheduled_backup_job_runs_through_scheduler(tmp_path: Path, monkeypatch) -> None:
    store = Store(tmp_path / "state.db")
    destination = tmp_path / "backups" / "state-scheduled.db.enc"

    def create_backup() -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"scheduled")
        return destination

    manager = SchedulerManager(
        store,
        enabled=False,
        backup_runner=create_backup,
        backup_directory=destination.parent,
    )
    async def run_in_thread(function, *args, **kwargs):
        return function(*args, **kwargs)

    monkeypatch.setattr("wait_local_agent.scheduler.asyncio.to_thread", run_in_thread)
    job = ScheduledJob(
        id=4,
        template_id="",
        cron="0 9 * * *",
        params_json="{}",
        paused=False,
        created_at="",
        updated_at="",
        job_kind="backup",
    )

    asyncio.run(manager._run_job(job))

    latest = store.latest_backup_run()
    assert latest is not None
    assert latest.status == "succeeded"


def test_backup_status_api_is_paged_and_refuses_demo_runs(settings: Settings) -> None:
    application = create_app(settings)

    with TestClient(application) as client:
        status = client.get("/backups")
        assert status.status_code == 200
        assert status.json()["items"] == []
        assert status.json()["total"] == 0
        assert status.json()["last_restore_exercise"] is None

        refused = client.post("/backups/run")
        assert refused.status_code == 403
        assert "demo mode" in refused.json()["detail"]

    assert any(event.event_type == "backup.run_requested" for event in application.state.store.list_audit_events())
