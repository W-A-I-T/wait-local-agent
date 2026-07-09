from __future__ import annotations

import shutil
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from wait_local_agent.config import Settings
from wait_local_agent.store import Store
from wait_local_agent.vault import SecretVault, SecretVaultError

BACKUP_KEY_SECRET_NAME = "WAIT_BACKUP_FERNET_KEY"  # nosec B105: secret name constant, not a secret value


class BackupEncryptionError(RuntimeError):
    """Raised when encrypted backup or restore cannot proceed."""


def backup_state(
    store: Store,
    destination: Path,
    *,
    encrypt: bool = False,
    settings: Settings | None = None,
) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if encrypt:
        fernet = _backup_fernet(settings)
        destination.write_bytes(fernet.encrypt(_store_bytes(store)))
        return destination
    if store.path.exists():
        shutil.copy2(store.path, destination)
    else:
        Store(store.path)
        shutil.copy2(store.path, destination)
    return destination


def restore_state(
    store: Store,
    source: Path,
    *,
    encrypted: bool = False,
    settings: Settings | None = None,
) -> Path:
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
        store.path.write_bytes(payload)
        Store(store.path)
        return store.path
    shutil.copy2(source, store.path)
    Store(store.path)
    return store.path


def _store_bytes(store: Store) -> bytes:
    if not store.path.exists():
        Store(store.path)
    return store.path.read_bytes()


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
