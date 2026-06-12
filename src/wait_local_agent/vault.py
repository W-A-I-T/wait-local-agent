from __future__ import annotations

import json
import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken


class SecretVaultError(RuntimeError):
    """Raised when the local secret vault cannot be read or decrypted."""


class SecretVault:
    """Small Fernet-backed secret store for local connector credentials."""

    def __init__(self, vault_path: Path) -> None:
        self.vault_path = Path(vault_path)
        self.key_path = self.vault_path / "vault.key"
        self.secrets_path = self.vault_path / "secrets.json.enc"

    @classmethod
    def initialize(cls, vault_path: Path) -> SecretVault:
        vault = cls(vault_path)
        vault.vault_path.mkdir(parents=True, exist_ok=True)
        _chmod(vault.vault_path, 0o700)
        if not vault.key_path.exists():
            vault.key_path.write_bytes(Fernet.generate_key())
            _chmod(vault.key_path, 0o600)
        if not vault.secrets_path.exists():
            vault._write_encrypted({})
        return vault

    def is_initialized(self) -> bool:
        return self.key_path.exists()

    def set(self, key: str, value: str) -> None:
        _validate_key(key)
        secrets = self._read_encrypted() if self.secrets_path.exists() else {}
        secrets[key] = value
        self._write_encrypted(secrets)

    def get(self, key: str) -> str | None:
        _validate_key(key)
        if not self.is_initialized() or not self.secrets_path.exists():
            return None
        return self._read_encrypted().get(key)

    def list_keys(self) -> list[str]:
        if not self.is_initialized() or not self.secrets_path.exists():
            return []
        return sorted(self._read_encrypted())

    def _fernet(self) -> Fernet:
        if not self.key_path.exists():
            raise SecretVaultError(f"secret vault is not initialized at {self.vault_path}")
        try:
            key = self.key_path.read_bytes()
        except OSError as exc:
            raise SecretVaultError("secret vault key could not be read") from exc
        return Fernet(key)

    def _read_encrypted(self) -> dict[str, str]:
        try:
            token = self.secrets_path.read_bytes()
            raw = self._fernet().decrypt(token)
            payload = json.loads(raw.decode("utf-8"))
        except (OSError, InvalidToken, ValueError) as exc:
            raise SecretVaultError("secret vault could not be decrypted") from exc
        if not isinstance(payload, dict):
            raise SecretVaultError("secret vault payload is malformed")
        return {str(key): str(value) for key, value in payload.items()}

    def _write_encrypted(self, payload: dict[str, str]) -> None:
        self.vault_path.mkdir(parents=True, exist_ok=True)
        _chmod(self.vault_path, 0o700)
        token = self._fernet().encrypt(json.dumps(payload, sort_keys=True).encode("utf-8"))
        self.secrets_path.write_bytes(token)
        _chmod(self.secrets_path, 0o600)


def _validate_key(key: str) -> None:
    if not key or not key.strip():
        raise ValueError("secret key must not be empty")


def _chmod(path: Path, mode: int) -> None:
    try:
        os.chmod(path, mode)
    except OSError:
        return
