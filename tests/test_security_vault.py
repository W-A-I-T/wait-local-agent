from __future__ import annotations

from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

import wait_local_agent.fs_permissions as fs_permissions
from wait_local_agent.api.app import _redact_payload, create_app
from wait_local_agent.security import auth_required
from wait_local_agent.vault import SecretVault, SecretVaultError


def test_api_auth_demo_mode_allows_local_demo_without_token(settings) -> None:
    client = TestClient(create_app(settings))

    response = client.get("/health")

    assert auth_required(settings) is False
    assert response.status_code == 200
    assert response.json()["api_auth_required"] is False


def test_api_auth_requires_bearer_token_when_production_mode_enabled(settings) -> None:
    secured_settings = settings.__class__(
        **{
            **settings.__dict__,
            "demo_mode": False,
            "api_token": "local-token",
        }
    )
    client = TestClient(create_app(secured_settings))

    missing = client.get("/health")
    bad = client.get("/health", headers={"Authorization": "Bearer wrong"})
    ok = client.get("/health", headers={"Authorization": "Bearer local-token"})

    assert auth_required(secured_settings) is True
    assert missing.status_code == 401
    assert bad.status_code == 401
    assert ok.status_code == 200
    assert ok.json()["api_auth_required"] is True


def test_non_demo_startup_fails_closed_without_configured_admin_credential(settings) -> None:
    secured_settings = settings.__class__(**{**settings.__dict__, "demo_mode": False})

    with pytest.raises(RuntimeError, match="without an admin credential"):
        create_app(secured_settings)
    assert auth_required(secured_settings) is True


def test_secret_vault_round_trip_and_corruption_error(tmp_path) -> None:
    vault_path = tmp_path / "vault"
    missing_vault = SecretVault(vault_path)

    assert missing_vault.get("WAIT_HUDU_API_KEY") is None
    assert missing_vault.list_keys() == []

    vault = SecretVault.initialize(vault_path)
    vault.set("WAIT_HUDU_API_KEY", "hudu-secret")
    vault.set("WAIT_HALOPSA_CLIENT_SECRET", "halo-secret")

    assert vault.get("WAIT_HUDU_API_KEY") == "hudu-secret"
    assert vault.list_keys() == ["WAIT_HALOPSA_CLIENT_SECRET", "WAIT_HUDU_API_KEY"]
    assert vault.key_path.exists()
    assert vault.secrets_path.exists()

    with pytest.raises(ValueError):
        vault.set("", "nope")

    vault.secrets_path.write_text("not encrypted", encoding="utf-8")
    with pytest.raises(SecretVaultError):
        vault.list_keys()


def test_secret_vault_can_use_an_external_fernet_key_without_writing_key_file(tmp_path, monkeypatch) -> None:
    key = Fernet.generate_key().decode("utf-8")
    monkeypatch.setenv("WAIT_VAULT_KEY", key)
    vault_path = tmp_path / "external-vault"

    vault = SecretVault.initialize(vault_path)
    vault.set("WAIT_EXTERNAL_SECRET", "external-value")

    assert not vault.key_path.exists()
    assert vault.get("WAIT_EXTERNAL_SECRET") == "external-value"


def test_non_demo_vault_requires_external_key(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("WAIT_VAULT_KEY", raising=False)

    with pytest.raises(SecretVaultError, match="WAIT_VAULT_KEY is required"):
        SecretVault.initialize(tmp_path / "production-vault", demo_mode=False)


def test_secret_vault_explicit_migration_reencrypts_and_retains_local_key(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("WAIT_VAULT_KEY", raising=False)
    vault_path = tmp_path / "migrate-vault"
    local_vault = SecretVault.initialize(vault_path)
    local_key = local_vault.key_path.read_text(encoding="utf-8").strip()
    local_vault.set("WAIT_MIGRATED_SECRET", "migrated-value")
    external_key = Fernet.generate_key().decode("utf-8")

    count = SecretVault.migrate_to_external_key(
        vault_path,
        source_key=local_key,
        destination_key=external_key,
    )

    assert count == 1
    assert local_vault.key_path.exists()
    monkeypatch.setenv("WAIT_VAULT_KEY", external_key)
    migrated = SecretVault(vault_path)
    assert migrated.get("WAIT_MIGRATED_SECRET") == "migrated-value"


def test_secret_vault_migration_rejects_wrong_source_without_overwriting(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("WAIT_VAULT_KEY", raising=False)
    vault_path = tmp_path / "wrong-source-vault"
    local_vault = SecretVault.initialize(vault_path)
    local_vault.set("WAIT_SECRET", "value")
    before = local_vault.secrets_path.read_bytes()

    with pytest.raises(SecretVaultError, match="could not be decrypted"):
        SecretVault.migrate_to_external_key(
            vault_path,
            source_key=Fernet.generate_key().decode("utf-8"),
            destination_key=Fernet.generate_key().decode("utf-8"),
        )

    assert local_vault.secrets_path.read_bytes() == before


def test_secret_vault_rejects_invalid_external_fernet_key(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("WAIT_VAULT_KEY", "not-a-fernet-key")

    with pytest.raises(SecretVaultError, match="WAIT_VAULT_KEY"):
        SecretVault.initialize(tmp_path / "invalid-external-vault")

    with pytest.raises(SecretVaultError, match="WAIT_VAULT_KEY"):
        SecretVault(tmp_path / "invalid-external-vault")._fernet()


def test_secret_vault_migration_rejects_missing_and_malformed_payloads(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("WAIT_VAULT_KEY", raising=False)
    with pytest.raises(SecretVaultError, match="no encrypted payload"):
        SecretVault.migrate_to_external_key(
            tmp_path / "missing-vault",
            source_key=Fernet.generate_key().decode("utf-8"),
            destination_key=Fernet.generate_key().decode("utf-8"),
        )

    vault_path = tmp_path / "malformed-vault"
    vault = SecretVault.initialize(vault_path)
    local_key = vault.key_path.read_text(encoding="utf-8").strip()
    vault.secrets_path.write_bytes(Fernet(local_key.encode("utf-8")).encrypt(b"[]"))
    with pytest.raises(SecretVaultError, match="payload is malformed"):
        SecretVault.migrate_to_external_key(
            vault_path,
            source_key=local_key,
            destination_key=Fernet.generate_key().decode("utf-8"),
        )


def test_redaction_covers_launch_key_variants() -> None:
    redacted = _redact_payload(
        {
            "apikey": "a",
            "auth_token": "b",
            "bearer": "c",
            "authorization": "d",
            "x-api-key": "e",
            "client_secret": "f",
            "access_token": "g",
            "nested": {"password": "h", "safe": "visible"},
            "items": [{"token": "i", "safe": "also-visible"}],
        }
    )

    assert redacted["apikey"] == "[redacted]"
    assert redacted["auth_token"] == "[redacted]"
    assert redacted["bearer"] == "[redacted]"
    assert redacted["authorization"] == "[redacted]"
    assert redacted["x-api-key"] == "[redacted]"
    assert redacted["client_secret"] == "[redacted]"
    assert redacted["access_token"] == "[redacted]"
    assert redacted["nested"] == {"password": "[redacted]", "safe": "visible"}
    assert redacted["items"] == [{"token": "[redacted]", "safe": "also-visible"}]


def test_secret_vault_handles_key_read_payload_and_permission_failures(tmp_path, monkeypatch, caplog) -> None:
    vault = SecretVault.initialize(tmp_path / "vault")

    def fail_read(_path: Path) -> bytes:
        raise OSError("unreadable")

    with monkeypatch.context() as patch:
        patch.setattr(Path, "read_bytes", fail_read)
        with pytest.raises(SecretVaultError, match="key could not be read"):
            vault._fernet()

    vault = SecretVault.initialize(tmp_path / "payload-vault")
    vault.secrets_path.write_bytes(vault._fernet().encrypt(b"[]"))
    with pytest.raises(SecretVaultError, match="payload is malformed"):
        vault.list_keys()

    def fail_chmod(*_args) -> None:
        raise OSError("permission denied")

    monkeypatch.setattr(fs_permissions.os, "chmod", fail_chmod)
    with caplog.at_level("WARNING", logger=fs_permissions.LOGGER.name):
        assert (
            fs_permissions.restrict_existing_file(
                tmp_path, backend=fs_permissions._PosixBackend()
            )
            is False
        )
    assert str(tmp_path) in caplog.text
