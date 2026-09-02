from __future__ import annotations

import asyncio
import os
import sqlite3
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from wait_local_agent import backup as backup_module
from wait_local_agent.api.app import create_app
from wait_local_agent.backup import (
    BACKUP_KEY_SECRET_NAME,
    RESTORE_EXERCISE_SCRATCH_PREFIX,
    BackupEncryptionError,
    BackupPathError,
    backup_state,
    create_scheduled_backup,
    prune_backup_files,
    restore_state,
    run_restore_exercise,
)
from wait_local_agent.config import Settings
from wait_local_agent.models import ScheduledJob
from wait_local_agent.scheduler import SchedulerManager, _validate_schedule_target
from wait_local_agent.store import Store
from wait_local_agent.vault import SecretVaultError


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

    assert not any(
        event.event_type == "backup.run_requested"
        for event in application.state.store.list_audit_events()
    )


def test_backup_and_restore_reject_paths_outside_data_root(settings: Settings, tmp_path: Path) -> None:
    store = Store(settings.data_path)
    outside = tmp_path.parent / "outside-backup.db"

    with pytest.raises(BackupPathError, match="must remain under"):
        backup_state(store, outside, settings=settings)
    with pytest.raises(BackupPathError, match="must remain under"):
        restore_state(store, outside, settings=settings)


def test_encrypted_backup_reports_missing_and_invalid_fernet_keys(
    settings: Settings, tmp_path: Path, monkeypatch
) -> None:
    secure_settings = settings.__class__(
        **{**settings.__dict__, "secrets_backend": "fernet", "vault_path": tmp_path / "vault"}
    )

    class MissingVault:
        def __init__(self, _path: Path) -> None:
            pass

        def get(self, _name: str) -> str:
            raise SecretVaultError("vault unavailable")

    monkeypatch.setattr(backup_module, "SecretVault", MissingVault)
    with pytest.raises(BackupEncryptionError, match="initialized local secret vault"):
        backup_module._backup_fernet(secure_settings)

    class EmptyVault:
        def __init__(self, _path: Path) -> None:
            pass

        def get(self, name: str) -> None:
            assert name == BACKUP_KEY_SECRET_NAME
            return None

    monkeypatch.setattr(backup_module, "SecretVault", EmptyVault)
    with pytest.raises(BackupEncryptionError, match="WAIT_BACKUP_FERNET_KEY in the local secret vault"):
        backup_module._backup_fernet(secure_settings)

    class InvalidVault:
        def __init__(self, _path: Path) -> None:
            pass

        def get(self, _name: str) -> str:
            return "invalid-key"

    monkeypatch.setattr(backup_module, "SecretVault", InvalidVault)
    with pytest.raises(BackupEncryptionError, match="not a valid Fernet key"):
        backup_module._backup_fernet(secure_settings)


def test_encrypted_restore_rejects_invalid_payload_with_injected_key(
    settings: Settings, tmp_path: Path, monkeypatch
) -> None:
    key = Fernet.generate_key()
    monkeypatch.setattr(backup_module, "_backup_fernet", lambda _settings: Fernet(key))
    source = tmp_path / "not-a-backup.enc"
    source.write_bytes(b"not encrypted")

    with pytest.raises(BackupEncryptionError, match="could not be decrypted"):
        restore_state(Store(tmp_path / "restored.db"), source, encrypted=True, settings=settings)


def test_restore_rejects_invalid_sqlite_payload_and_cleans_sidecars(
    settings: Settings, tmp_path: Path
) -> None:
    source = tmp_path / "invalid.db"
    source.write_bytes(b"not sqlite")
    destination = tmp_path / "restored.db"
    store = Store(destination)
    original_destination = destination.read_bytes()
    Path(f"{destination}-wal").write_bytes(b"wal")
    Path(f"{destination}-shm").write_bytes(b"shm")

    with pytest.raises(sqlite3.Error):
        restore_state(store, source, settings=settings)
    assert destination.read_bytes() == original_destination
    assert not Path(f"{destination}-wal").exists()
    assert not Path(f"{destination}-shm").exists()


def test_restore_exercise_missing_backup_is_recorded_and_scratch_is_removed(
    settings: Settings, tmp_path: Path
) -> None:
    store = Store(settings.data_path)
    result = run_restore_exercise(tmp_path / "missing.db", store=store, settings=settings)

    assert result.status == "failed"
    assert result.validation["error"] == "FileNotFoundError"
    assert result.evidence["scratch_removed"] is True
    assert store.list_restore_exercises()[0].status == "failed"


def test_prune_backup_files_retention_boundaries_and_protected_file(tmp_path: Path) -> None:
    directory = tmp_path / "backups"
    directory.mkdir()
    old_file = directory / "state-old.db.enc"
    middle_file = directory / "state-middle.db.enc"
    just_created = directory / "state-just-created.db.enc"
    for path in (old_file, middle_file, just_created):
        path.write_bytes(path.name.encode())
    os.utime(old_file, ns=(1, 1))
    os.utime(middle_file, ns=(2, 2))
    # Model a coarse filesystem timestamp: the just-created artifact is in the
    # prune window even though it is the protected destination.
    os.utime(just_created, ns=(1, 1))

    assert prune_backup_files(directory, 3, just_created) == 0
    assert len(list(directory.glob("state-*.db.enc"))) == 3
    with pytest.raises(ValueError, match="at least 1"):
        prune_backup_files(directory, 0, just_created)

    assert prune_backup_files(directory, 1, just_created) == 0
    assert just_created.exists()
    assert old_file.exists() is False
    assert middle_file.exists()


def test_restore_exercise_preserves_stale_scratch_file_and_reports_encrypted_key_failure(
    settings: Settings, tmp_path: Path, monkeypatch
) -> None:
    store = Store(settings.data_path)
    stale = settings.data_path.parent / f"{RESTORE_EXERCISE_SCRATCH_PREFIX}file"
    stale.write_text("stale", encoding="utf-8")

    def fail_restore(*_args, **_kwargs):
        raise BackupEncryptionError("bad key")

    monkeypatch.setattr(backup_module, "restore_state", fail_restore)

    result = run_restore_exercise(tmp_path / "backup.enc", store=store, settings=settings, encrypted=True)

    assert stale.exists()
    assert result.status == "failed"
    assert result.validation["error"] == "BackupEncryptionError"
    assert result.evidence["error_detail"] == "bad key"


def test_create_scheduled_backup_builds_timestamped_encrypted_destination(settings: Settings, monkeypatch) -> None:
    store = Store(settings.data_path)
    captured: dict[str, object] = {}

    def fake_backup_state(store_arg, destination, *, encrypt, settings):
        captured.update(store=store_arg, destination=destination, encrypt=encrypt, settings=settings)
        return destination

    monkeypatch.setattr(backup_module, "backup_state", fake_backup_state)
    result = create_scheduled_backup(store, settings)

    assert result == captured["destination"]
    assert captured["store"] is store
    assert captured["settings"] is settings
    assert captured["encrypt"] is True
    assert result.parent == settings.data_path.parent / "backups"
    assert result.name.startswith("state-") and result.name.endswith(".db.enc")


def test_prune_backup_files_records_directory_and_unlink_os_errors(tmp_path: Path, monkeypatch) -> None:
    class BrokenDirectory:
        def expanduser(self):
            return self

        def resolve(self):
            return self

        def glob(self, _pattern):
            raise OSError("directory unavailable")

    assert prune_backup_files(BrokenDirectory(), 1, tmp_path / "protected") == 1  # type: ignore[arg-type]

    directory = tmp_path / "backups"
    directory.mkdir()
    victim = directory / "state-old.db.enc"
    newest = directory / "state-newest.db.enc"
    victim.write_bytes(b"old")
    newest.write_bytes(b"newest")
    original_unlink = Path.unlink

    def fail_victim_unlink(path: Path, *, missing_ok: bool = False) -> None:
        if path == victim:
            raise OSError("permission denied")
        original_unlink(path, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", fail_victim_unlink)
    os.utime(victim, ns=(1, 1))
    os.utime(newest, ns=(2, 2))
    assert prune_backup_files(directory, 1, tmp_path / "protected") == 1
    assert victim.exists()
