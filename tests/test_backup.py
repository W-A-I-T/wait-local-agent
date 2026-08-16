from __future__ import annotations

from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from typer.testing import CliRunner

from tests.support import ingest_local
from wait_local_agent import backup as backup_module
from wait_local_agent.backup import (
    BACKUP_KEY_SECRET_NAME,
    RESTORE_EXERCISE_SCRATCH_PREFIX,
    BackupEncryptionError,
    backup_state,
    restore_state,
    run_restore_exercise,
)
from wait_local_agent.cli import app
from wait_local_agent.store import Store
from wait_local_agent.vault import SecretVault


def test_encrypted_backup_restore_round_trip(settings, tmp_path: Path) -> None:
    secure_settings = settings.__class__(
        **{
            **settings.__dict__,
            "secrets_backend": "fernet",
            "vault_path": tmp_path / "vault",
        }
    )
    vault = SecretVault.initialize(secure_settings.vault_path)
    vault.set(BACKUP_KEY_SECRET_NAME, Fernet.generate_key().decode("utf-8"))
    store = Store(secure_settings.data_path)
    ingest_local(store, Path("examples/sample_tickets/tickets.json"))
    original_bytes = secure_settings.data_path.read_bytes()
    encrypted_backup = tmp_path / "state.db.enc"
    restored_path = tmp_path / "restored.db"

    backup_state(store, encrypted_backup, encrypt=True, settings=secure_settings)
    restore_state(
        Store(restored_path),
        encrypted_backup,
        encrypted=True,
        settings=secure_settings,
    )

    assert encrypted_backup.read_bytes() != original_bytes
    with Store(restored_path)._connect() as connection:  # noqa: SLF001
        assert connection.execute("select count(*) from tickets").fetchone()[0] > 0
        assert connection.execute("pragma integrity_check").fetchone()[0] == "ok"


def test_encrypted_backup_requires_vault_key(settings, tmp_path: Path) -> None:
    secure_settings = settings.__class__(
        **{
            **settings.__dict__,
            "secrets_backend": "fernet",
            "vault_path": tmp_path / "vault",
        }
    )
    SecretVault.initialize(secure_settings.vault_path)

    with pytest.raises(BackupEncryptionError, match=BACKUP_KEY_SECRET_NAME):
        backup_state(
            Store(secure_settings.data_path),
            tmp_path / "state.db.enc",
            encrypt=True,
            settings=secure_settings,
        )


def test_encrypted_backup_restore_cli_fails_cleanly_without_key(monkeypatch, tmp_path: Path) -> None:
    source_data = tmp_path / "source.db"
    source_vault = tmp_path / "vault-source"
    restore_vault = tmp_path / "vault-restore"
    encrypted_backup = tmp_path / "backup.enc"
    runner = CliRunner()

    monkeypatch.setenv("WAIT_DATA_PATH", str(source_data))
    monkeypatch.setenv("WAIT_SECRETS_BACKEND", "fernet")
    monkeypatch.setenv("WAIT_VAULT_PATH", str(source_vault))
    SecretVault.initialize(source_vault).set(BACKUP_KEY_SECRET_NAME, Fernet.generate_key().decode("utf-8"))
    ingest_local(Store(source_data), Path("examples/sample_tickets/tickets.json"))

    create = runner.invoke(app, ["backup", "create", str(encrypted_backup), "--encrypt"])

    monkeypatch.setenv("WAIT_DATA_PATH", str(tmp_path / "restored.db"))
    monkeypatch.setenv("WAIT_VAULT_PATH", str(restore_vault))
    SecretVault.initialize(restore_vault)
    restore = runner.invoke(app, ["backup", "restore", str(encrypted_backup), "--encrypted"])

    assert create.exit_code == 0
    assert restore.exit_code != 0
    assert BACKUP_KEY_SECRET_NAME in restore.output


def test_plain_backup_bootstraps_missing_store_and_restore_requires_existing_source(
    settings, tmp_path: Path
) -> None:
    store = Store(tmp_path / "missing-state.db")
    store.path.unlink()
    backup_path = tmp_path / "backup" / "state.db"

    result = backup_state(store, backup_path)

    assert result == backup_path
    assert backup_path.exists()
    assert store.path.exists()

    with pytest.raises(FileNotFoundError):
        restore_state(store, tmp_path / "missing.db")


def test_restore_exercise_reports_row_count_mismatch(settings, tmp_path: Path) -> None:
    store = Store(settings.data_path)
    ingest_local(store, Path("examples/sample_tickets/tickets.json"))
    empty_store = Store(tmp_path / "empty.db")
    backup_path = tmp_path / "empty-backup.db"
    backup_state(empty_store, backup_path)

    result = run_restore_exercise(backup_path, store=store, settings=settings)

    assert result.status == "failed"
    assert result.validation["error"] == "ValueError"
    assert "row counts did not match" in result.evidence["error_detail"]


def test_restore_exercise_reports_failed_integrity_check(settings, tmp_path: Path, monkeypatch) -> None:
    store = Store(settings.data_path)
    source = tmp_path / "backup.db"
    backup_state(store, source)

    class ScratchStore:
        def __init__(self, path: Path) -> None:
            self.path = path

    class IntegrityConnection:
        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        def execute(self, query: str):
            assert query == "pragma integrity_check"
            class IntegrityResult:
                def fetchone(self):
                    return ("corrupt",)

            return IntegrityResult()

    monkeypatch.setattr(backup_module, "Store", ScratchStore)
    monkeypatch.setattr(backup_module, "_live_core_row_counts", lambda _path: {})
    original_connect = backup_module.sqlite3.connect
    monkeypatch.setattr(
        backup_module.sqlite3,
        "connect",
        lambda *args, **kwargs: (
            IntegrityConnection()
            if str(args[0]).startswith("file:")
            else original_connect(*args, **kwargs)
        ),
    )

    result = run_restore_exercise(source, store=store, settings=settings)

    assert result.status == "failed"
    assert result.validation["error"] == "ValueError"
    assert "integrity check returned corrupt" in result.evidence["error_detail"]


def test_restore_exercise_removes_matching_stale_file(settings, tmp_path: Path) -> None:
    store = Store(settings.data_path)
    stale_file = settings.data_path.parent / f"{RESTORE_EXERCISE_SCRATCH_PREFIX}file"
    stale_file.write_text("not a directory", encoding="utf-8")
    source = tmp_path / "backup.db"
    backup_state(store, source)

    result = run_restore_exercise(source, store=store, settings=settings)

    assert result.status == "passed"
    assert stale_file.exists()


def test_default_settings_and_store_bytes_bootstrap_missing_store(tmp_path: Path) -> None:
    settings = backup_module._default_settings()
    assert settings.data_path == Path(".wait-local-agent/state.db")

    store = Store(tmp_path / "missing.db")
    store.path.unlink()
    assert backup_module._store_bytes(store)


def test_encrypted_backup_rejects_uninitialized_vault_and_invalid_keys(
    settings, tmp_path: Path
) -> None:
    secure_settings = settings.__class__(
        **{
            **settings.__dict__,
            "secrets_backend": "fernet",
            "vault_path": tmp_path / "vault",
        }
    )

    with pytest.raises(BackupEncryptionError, match=BACKUP_KEY_SECRET_NAME):
        backup_state(
            Store(secure_settings.data_path),
            tmp_path / "state.db.enc",
            encrypt=True,
            settings=secure_settings,
        )

    SecretVault.initialize(secure_settings.vault_path).set(BACKUP_KEY_SECRET_NAME, "not-a-fernet-key")

    with pytest.raises(BackupEncryptionError, match="not a valid Fernet key"):
        backup_state(
            Store(secure_settings.data_path),
            tmp_path / "state-invalid.db.enc",
            encrypt=True,
            settings=secure_settings,
        )


def test_encrypted_backup_rejects_non_fernet_backend(settings, tmp_path: Path) -> None:
    with pytest.raises(BackupEncryptionError, match="WAIT_SECRETS_BACKEND=fernet"):
        backup_state(Store(settings.data_path), tmp_path / "backup.enc", encrypt=True, settings=settings)


def test_encrypted_backup_rejects_unreadable_vault(settings, tmp_path: Path) -> None:
    secure_settings = settings.__class__(
        **{**settings.__dict__, "secrets_backend": "fernet", "vault_path": tmp_path / "vault"}
    )
    vault = SecretVault.initialize(secure_settings.vault_path)
    vault.secrets_path.write_bytes(b"corrupt vault payload")

    with pytest.raises(BackupEncryptionError, match="initialized local secret vault"):
        backup_state(
            Store(secure_settings.data_path),
            tmp_path / "backup.enc",
            encrypt=True,
            settings=secure_settings,
        )


def test_encrypted_restore_rejects_invalid_ciphertext(settings, tmp_path: Path) -> None:
    secure_settings = settings.__class__(
        **{
            **settings.__dict__,
            "secrets_backend": "fernet",
            "vault_path": tmp_path / "vault",
        }
    )
    SecretVault.initialize(secure_settings.vault_path).set(
        BACKUP_KEY_SECRET_NAME,
        Fernet.generate_key().decode("utf-8"),
    )
    encrypted_backup = tmp_path / "broken.enc"
    encrypted_backup.write_bytes(b"not encrypted")

    with pytest.raises(BackupEncryptionError, match="could not be decrypted"):
        restore_state(
            Store(tmp_path / "restored.db"),
            encrypted_backup,
            encrypted=True,
            settings=secure_settings,
        )


def test_restore_exercise_uses_scratch_and_preserves_live_rows(settings, tmp_path: Path) -> None:
    store = Store(settings.data_path)
    ingest_local(store, Path("examples/sample_tickets/tickets.json"))
    backup_path = tmp_path / "exercise.db"
    backup_state(store, backup_path)
    before_ids = [ticket.id for ticket in store.list_tickets()]

    result = run_restore_exercise(backup_path, store=store, settings=settings)

    assert result.status == "passed"
    assert result.validation["integrity_check"] == "ok"
    assert result.validation["verified_tables"]
    assert result.evidence["scratch_removed"] is True
    assert [ticket.id for ticket in store.list_tickets()] == before_ids
    assert store.list_restore_exercises()[0].status == "passed"


def test_restore_exercise_removes_stale_scratch_dirs(settings, tmp_path: Path) -> None:
    store = Store(settings.data_path)
    stale_dir = settings.data_path.parent / f"{RESTORE_EXERCISE_SCRATCH_PREFIX}stale"
    stale_dir.mkdir()
    (stale_dir / "leftover").write_text("leftover", encoding="utf-8")
    backup_path = tmp_path / "exercise.db"
    backup_state(store, backup_path)

    result = run_restore_exercise(backup_path, store=store, settings=settings)

    assert result.status == "passed"
    assert not stale_dir.exists()


def test_restore_exercise_records_failure_and_cleans_scratch(settings, tmp_path: Path) -> None:
    store = Store(settings.data_path)
    broken_backup = tmp_path / "broken.db"
    broken_backup.write_bytes(b"not sqlite")

    result = run_restore_exercise(broken_backup, store=store, settings=settings)

    assert result.status == "failed"
    assert result.evidence["scratch_removed"] is True
    assert "error_detail" in result.evidence
