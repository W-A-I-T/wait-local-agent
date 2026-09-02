from __future__ import annotations

import shutil
import sqlite3
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from cryptography.fernet import Fernet, InvalidToken

from wait_local_agent.config import Settings
from wait_local_agent.models import RestoreExerciseWrite
from wait_local_agent.store import Store
from wait_local_agent.vault import SecretVault, SecretVaultError

BACKUP_KEY_SECRET_NAME = "WAIT_BACKUP_FERNET_KEY"  # nosec B105: secret name constant, not a secret value
RESTORE_EXERCISE_SCRATCH_PREFIX = "restore-exercise-scratch-"
BACKUP_FILE_PREFIX = "state-"
BACKUP_FILE_SUFFIX = ".db.enc"


class BackupEncryptionError(RuntimeError):
    """Raised when encrypted backup or restore cannot proceed."""


class BackupPathError(ValueError):
    """Raised when a backup path escapes the appliance data directory."""


def scheduled_backup_directory(settings: Settings) -> Path:
    return settings.data_path.expanduser().resolve().parent / "backups"


def create_scheduled_backup(store: Store, settings: Settings) -> Path:
    """Create the appliance's encrypted scheduled-backup artifact."""

    destination = scheduled_backup_directory(settings) / (
        f"{BACKUP_FILE_PREFIX}{datetime.now(UTC).strftime('%Y%m%dT%H%M%S%fZ')}{BACKUP_FILE_SUFFIX}"
    )
    return backup_state(store, destination, encrypt=True, settings=settings)


def prune_backup_files(directory: Path, retention_count: int, protected: Path) -> int:
    """Retain the newest generated backup files and return pruning failures."""

    if retention_count < 1:
        raise ValueError("retention_count must be at least 1")
    directory = directory.expanduser().resolve()
    protected = protected.expanduser().resolve()
    try:
        candidates = [
            candidate
            for candidate in directory.glob(f"{BACKUP_FILE_PREFIX}*{BACKUP_FILE_SUFFIX}")
            if candidate.is_file() and not candidate.is_symlink()
        ]
        candidates.sort(key=lambda candidate: (candidate.stat().st_mtime_ns, candidate.name), reverse=True)
    except OSError:
        return 1

    failures = 0
    for candidate in candidates[retention_count:]:
        if candidate.resolve() == protected:
            continue
        try:
            candidate.unlink()
        except OSError:
            failures += 1
    return failures


def _confine_backup_path(path: Path, settings: Settings | None) -> Path:
    resolved = path.expanduser().resolve()
    if settings is None:
        return resolved
    root = settings.data_path.expanduser().resolve().parent
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise BackupPathError(
            f"backup paths must remain under the appliance data directory: {root}"
        ) from exc
    return resolved


def backup_state(
    store: Store,
    destination: Path,
    *,
    encrypt: bool = False,
    settings: Settings | None = None,
) -> Path:
    destination = _confine_backup_path(destination, settings)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if encrypt:
        fernet = _backup_fernet(settings)
        destination.write_bytes(fernet.encrypt(_store_bytes(store)))
        return destination
    if not store.path.exists():
        Store(store.path)
    _backup_sqlite(store.path, destination)
    return destination


def restore_state(
    store: Store,
    source: Path,
    *,
    encrypted: bool = False,
    settings: Settings | None = None,
) -> Path:
    source = _confine_backup_path(source, settings)
    if not source.exists():
        raise FileNotFoundError(source)
    store.path.parent.mkdir(parents=True, exist_ok=True)
    if encrypted:
        fernet = _backup_fernet(settings)
        try:
            payload = fernet.decrypt(source.read_bytes())
        except InvalidToken as exc:
            raise BackupEncryptionError(
                "Encrypted backup could not be decrypted with the configured WAIT_BACKUP_FERNET_KEY."
            ) from exc
        _remove_sqlite_files(store.path)
        store.path.write_bytes(payload)
        Store(store.path)
        return store.path
    try:
        payload = _snapshot_bytes(source)
    except (OSError, sqlite3.Error):
        _remove_sqlite_sidecars(store.path)
        raise
    _remove_sqlite_files(store.path)
    store.path.write_bytes(payload)
    Store(store.path)
    return store.path


def run_restore_exercise(
    backup_id: str | Path,
    *,
    store: Store | None = None,
    settings: Settings | None = None,
    encrypted: bool = False,
) -> RestoreExerciseWrite:
    """Verify a backup in a disposable scratch database without touching live state."""

    active_settings = settings or _default_settings()
    live_store = store or Store(active_settings.data_path)
    _remove_stale_restore_exercise_scratch_dirs(live_store.path.parent)
    source = Path(backup_id)
    exercise_id = str(uuid4())
    started_at = time.monotonic()
    started_iso = _utc_now()
    scratch_dir = Path(
        tempfile.mkdtemp(prefix=RESTORE_EXERCISE_SCRATCH_PREFIX, dir=live_store.path.parent)
    )
    scratch_db = scratch_dir / "restored.db"
    validation: dict[str, object] = {"verified_tables": [], "row_counts": {}}
    evidence: dict[str, object] = {"scratch_path": str(scratch_dir), "backup_artifact_id": str(source)}
    status = "failed"
    error_detail: str | None = None
    try:
        expected_counts = _live_core_row_counts(live_store.path)
        scratch_store = Store(scratch_db)
        restore_state(scratch_store, source, encrypted=encrypted, settings=active_settings)
        with sqlite3.connect(f"file:{scratch_db}?mode=ro", uri=True) as connection:
            connection.row_factory = sqlite3.Row
            integrity = str(connection.execute("pragma integrity_check").fetchone()[0])
            if integrity != "ok":
                raise ValueError(f"SQLite integrity check returned {integrity}")
            actual_counts, verified_tables = _restored_core_row_counts(connection)
            mismatches = {
                table: {"expected": expected, "actual": actual_counts.get(table)}
                for table, expected in expected_counts.items()
                if actual_counts.get(table) != expected
            }
            if mismatches:
                raise ValueError(f"restored row counts did not match expectations: {sorted(mismatches)}")
            validation.update(
                {
                    "integrity_check": integrity,
                    "verified_tables": verified_tables,
                    "row_counts": actual_counts,
                    "expected_row_counts": expected_counts,
                }
            )
        status = "passed"
    except (OSError, sqlite3.Error, ValueError, BackupEncryptionError) as exc:
        error_detail = str(exc)
        validation["error"] = type(exc).__name__
    finally:
        shutil.rmtree(scratch_dir, ignore_errors=True)
        evidence["scratch_removed"] = not scratch_dir.exists()

    validation["duration_seconds"] = time.monotonic() - started_at
    if error_detail:
        evidence["error_detail"] = error_detail
    result = RestoreExerciseWrite(
        exercise_id=exercise_id,
        status=status,
        target="temporary scratch database",
        backup_artifact_id=str(source),
        validation=validation,
        evidence=evidence,
        started_at=started_iso,
        completed_at=_utc_now(),
    )
    live_store.add_restore_exercise(
        run_id=None,
        asset_id=None,
        source_id=None,
        exercise_id=result.exercise_id,
        status=result.status,
        target=result.target,
        backup_artifact_id=result.backup_artifact_id,
        validation=result.validation,
        evidence=result.evidence,
        started_at=result.started_at,
        completed_at=result.completed_at,
    )
    return result


_CORE_RESTORE_TABLES = (
    "tickets",
    "approvals",
    "approval_requests",
    "event_history",
    "workflow_runs",
    "scheduled_jobs",
    "knowledge_documents",
    "knowledge_chunks",
)
_CORE_RESTORE_COUNT_QUERIES = {
    "tickets": "select count(*) from tickets",
    "approvals": "select count(*) from approvals",
    "approval_requests": "select count(*) from approval_requests",
    "event_history": "select count(*) from event_history",
    "workflow_runs": "select count(*) from workflow_runs",
    "scheduled_jobs": "select count(*) from scheduled_jobs",
    "knowledge_documents": "select count(*) from knowledge_documents",
    "knowledge_chunks": "select count(*) from knowledge_chunks",
}


def _live_core_row_counts(path: Path) -> dict[str, int]:
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as connection:
        return _core_row_counts(connection)


def _remove_stale_restore_exercise_scratch_dirs(parent: Path) -> None:
    for candidate in parent.glob(f"{RESTORE_EXERCISE_SCRATCH_PREFIX}*"):
        if candidate.is_dir():
            shutil.rmtree(candidate, ignore_errors=True)


def _restored_core_row_counts(connection: sqlite3.Connection) -> tuple[dict[str, int], list[str]]:
    counts = _core_row_counts(connection)
    return counts, sorted(counts)


def _core_row_counts(connection: sqlite3.Connection) -> dict[str, int]:
    tables = {
        str(row[0])
        for row in connection.execute("select name from sqlite_master where type = 'table'")
    }
    return {
        table: int(connection.execute(_CORE_RESTORE_COUNT_QUERIES[table]).fetchone()[0])
        for table in _CORE_RESTORE_TABLES
        if table in tables
    }


def _default_settings() -> Settings:
    return Settings(
        data_path=Path(".wait-local-agent/state.db"),
        allowed_doc_root=Path("."),
        allow_write_actions=False,
        allow_http_probing=False,
        allow_insecure_provider_transport=False,
        allow_cloud_fallback=False,
        allow_llm_inference=False,
        local_model_provider="deterministic",
        local_model_base_url="",
        local_model_name="",
        local_model_timeout_seconds=20.0,
        vector_backend="sqlite",
    )


def _utc_now() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()


def _store_bytes(store: Store) -> bytes:
    if not store.path.exists():
        Store(store.path)
    return _snapshot_bytes(store.path)


def _backup_sqlite(source_path: Path, destination_path: Path) -> None:
    """Copy a SQLite database, including committed pages still in its WAL."""

    snapshot = _snapshot_bytes(source_path)
    _remove_sqlite_files(destination_path)
    destination_path.write_bytes(snapshot)


def _remove_sqlite_files(path: Path) -> None:
    path.unlink(missing_ok=True)
    _remove_sqlite_sidecars(path)


def _remove_sqlite_sidecars(path: Path) -> None:
    for suffix in ("-wal", "-shm"):
        Path(f"{path}{suffix}").unlink(missing_ok=True)


def _snapshot_bytes(source_path: Path) -> bytes:
    with tempfile.TemporaryDirectory(prefix="wait-sqlite-snapshot-") as directory:
        snapshot_path = Path(directory) / "snapshot.db"
        with sqlite3.connect(source_path) as source:
            source.execute("vacuum into ?", (str(snapshot_path),))
        return snapshot_path.read_bytes()


def _backup_fernet(settings: Settings | None) -> Fernet:
    if settings is None or settings.secrets_backend != "fernet":
        raise BackupEncryptionError(
            "Encrypted backups require WAIT_SECRETS_BACKEND=fernet and a local secret vault."
        )
    try:
        key = SecretVault(settings.vault_path).get(BACKUP_KEY_SECRET_NAME)
    except SecretVaultError as exc:
        raise BackupEncryptionError(
            "Encrypted backups require an initialized local secret vault and a stored WAIT_BACKUP_FERNET_KEY."
        ) from exc
    if not key:
        raise BackupEncryptionError(
            "Encrypted backups require WAIT_BACKUP_FERNET_KEY in the local secret vault."
        )
    try:
        return Fernet(key.encode("utf-8"))
    except ValueError as exc:
        raise BackupEncryptionError(
            "The stored WAIT_BACKUP_FERNET_KEY is not a valid Fernet key."
        ) from exc
