from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

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


def test_api_auth_leaves_local_api_open_without_configured_token(settings) -> None:
    secured_settings = settings.__class__(**{**settings.__dict__, "demo_mode": False})
    client = TestClient(create_app(secured_settings))

    response = client.get("/health")

    assert auth_required(secured_settings) is False
    assert response.status_code == 200
    assert response.json()["api_auth_required"] is False


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
