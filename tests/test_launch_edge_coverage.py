from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from typer.testing import CliRunner

from wait_local_agent.api.app import create_app
from wait_local_agent.cli import app
from wait_local_agent.config import load_settings
from wait_local_agent.vault import SecretVault, SecretVaultError


def test_api_token_required_even_in_demo_when_token_is_configured(settings) -> None:
    token_settings = settings.__class__(
        **{
            **settings.__dict__,
            "demo_mode": True,
            "api_token": "configured-token",
        }
    )
    client = TestClient(create_app(token_settings))

    missing = client.get("/health")
    malformed = client.get("/health", headers={"Authorization": "Token configured-token"})
    ok = client.get("/health", headers={"Authorization": "Bearer configured-token"})

    assert missing.status_code == 401
    assert malformed.status_code == 401
    assert ok.status_code == 200


def test_audit_export_api_rejects_unsupported_format(settings) -> None:
    client = TestClient(create_app(settings))

    response = client.get("/audit/export", params={"export_format": "xml"})

    assert response.status_code == 422


def test_vault_set_requires_initialized_key(tmp_path) -> None:
    vault = SecretVault(tmp_path / "vault")

    try:
        vault.set("WAIT_HUDU_API_KEY", "secret")
    except SecretVaultError as exc:
        assert "not initialized" in str(exc)
    else:  # pragma: no cover - documents the required exception path
        raise AssertionError("uninitialized vault write unexpectedly succeeded")


def test_vault_get_rejects_empty_key(tmp_path) -> None:
    vault = SecretVault.initialize(tmp_path / "vault")

    try:
        vault.get("")
    except ValueError as exc:
        assert "must not be empty" in str(exc)
    else:  # pragma: no cover - documents the required exception path
        raise AssertionError("empty key lookup unexpectedly succeeded")


def test_vault_initialize_is_idempotent(tmp_path) -> None:
    vault_path = tmp_path / "vault"
    first = SecretVault.initialize(vault_path)
    first_key = first.key_path.read_bytes()
    second = SecretVault.initialize(vault_path)

    assert second.key_path.read_bytes() == first_key


def test_corrupt_fernet_backend_falls_back_to_env(monkeypatch, tmp_path) -> None:
    vault = SecretVault.initialize(tmp_path / "vault")
    vault.secrets_path.write_text("not encrypted", encoding="utf-8")
    monkeypatch.setenv("WAIT_SECRETS_BACKEND", "fernet")
    monkeypatch.setenv("WAIT_VAULT_PATH", str(vault.vault_path))
    monkeypatch.setenv("WAIT_HUDU_API_KEY", "env-value")

    settings = load_settings()

    assert settings.hudu_api_key == "env-value"


def test_audit_export_cli_rejects_unsupported_format(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("WAIT_DATA_PATH", str(tmp_path / "state.db"))
    runner = CliRunner()

    result = runner.invoke(app, ["audit", "export", str(tmp_path / "audit.xml"), "--format", "xml"])

    assert result.exit_code != 0
    assert "format must be json or csv" in result.output


def test_secret_cli_reports_corrupt_vault(monkeypatch, tmp_path) -> None:
    vault = SecretVault.initialize(tmp_path / "vault")
    vault.secrets_path.write_text("not encrypted", encoding="utf-8")
    monkeypatch.setenv("WAIT_VAULT_PATH", str(vault.vault_path))
    runner = CliRunner()

    result = runner.invoke(app, ["secrets", "list"])

    assert result.exit_code != 0
    assert "secret vault could not be decrypted" in result.output


def test_audit_export_cli_creates_parent_directories(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("WAIT_DATA_PATH", str(tmp_path / "state.db"))
    runner = CliRunner()
    destination = tmp_path / "nested" / "audit" / "events.json"

    result = runner.invoke(app, ["audit", "export", str(destination)])

    assert result.exit_code == 0
    assert destination.exists()
    assert destination.read_text(encoding="utf-8") == "[]\n"


def test_demo_dataset_can_be_ingested(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("WAIT_DATA_PATH", str(tmp_path / "state.db"))
    monkeypatch.setenv("WAIT_ALLOWED_DOC_ROOT", "demo/sample_runbooks")
    runner = CliRunner()

    docs = runner.invoke(app, ["knowledge", "ingest", "demo/sample_runbooks"])
    tickets = runner.invoke(app, ["ingest", "demo/sample_tickets"])
    summary = runner.invoke(app, ["tickets", "summarize", "DEMO-1001"])

    assert docs.exit_code == 0
    assert "documents=3" in docs.output
    assert tickets.exit_code == 0
    assert "ingested=3" in tickets.output
    assert summary.exit_code == 0
    assert "classification=" in summary.output
