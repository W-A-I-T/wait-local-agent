from __future__ import annotations

from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from typer.testing import CliRunner

from wait_local_agent.backup import BACKUP_KEY_SECRET_NAME, BackupEncryptionError, backup_state, restore_state
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
    store.ingest_ticket_file(Path("examples/sample_tickets/tickets.json"))
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
    assert restored_path.read_bytes() == original_bytes


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
        backup_state(Store(secure_settings.data_path), tmp_path / "state.db.enc", encrypt=True, settings=secure_settings)


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
    Store(source_data).ingest_ticket_file(Path("examples/sample_tickets/tickets.json"))

    create = runner.invoke(app, ["backup", "create", str(encrypted_backup), "--encrypt"])

    monkeypatch.setenv("WAIT_DATA_PATH", str(tmp_path / "restored.db"))
    monkeypatch.setenv("WAIT_VAULT_PATH", str(restore_vault))
    SecretVault.initialize(restore_vault)
    restore = runner.invoke(app, ["backup", "restore", str(encrypted_backup), "--encrypted"])

    assert create.exit_code == 0
    assert restore.exit_code != 0
    assert BACKUP_KEY_SECRET_NAME in restore.output
