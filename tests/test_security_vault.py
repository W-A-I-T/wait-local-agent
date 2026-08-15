from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import wait_local_agent.vault as vault_module
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


def test_secret_vault_handles_key_read_payload_and_permission_failures(tmp_path, monkeypatch) -> None:
    vault = SecretVault.initialize(tmp_path / "vault")

    def fail_read(_path: Path) -> bytes:
        raise OSError("unreadable")

    with monkeypatch.context() as patch:
        patch.setattr(Path, "read_bytes", fail_read)
        with pytest.raises(SecretVaultError, match="key could not be read"):
            vault._fernet()  # noqa: SLF001

    vault = SecretVault.initialize(tmp_path / "payload-vault")
    vault.secrets_path.write_bytes(vault._fernet().encrypt(b"[]"))  # noqa: SLF001
    with pytest.raises(SecretVaultError, match="payload is malformed"):
        vault.list_keys()

    def fail_chmod(*_args) -> None:
        raise OSError("permission denied")

    monkeypatch.setattr(vault_module.os, "chmod", fail_chmod)
    vault_module._chmod(tmp_path, 0o700)  # noqa: SLF001
