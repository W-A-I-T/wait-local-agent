from __future__ import annotations

from wait_local_agent.config import load_settings
from wait_local_agent.vault import SecretVault


def test_safe_defaults_are_disabled(monkeypatch) -> None:
    monkeypatch.delenv("WAIT_ALLOW_WRITE_ACTIONS", raising=False)
    monkeypatch.delenv("WAIT_ALLOW_HTTP_PROBING", raising=False)
    monkeypatch.delenv("WAIT_ALLOW_CLOUD_FALLBACK", raising=False)
    monkeypatch.delenv("WAIT_ALLOW_LLM_INFERENCE", raising=False)
    monkeypatch.delenv("WAIT_API_TOKEN", raising=False)
    monkeypatch.delenv("WAIT_DEMO_MODE", raising=False)
    monkeypatch.delenv("WAIT_SECRETS_BACKEND", raising=False)
    monkeypatch.delenv("WAIT_VAULT_PATH", raising=False)
    monkeypatch.delenv("WAIT_LOCAL_MODEL_PROVIDER", raising=False)
    monkeypatch.delenv("WAIT_LOCAL_MODEL_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("WAIT_HALOPSA_BASE_URL", raising=False)
    monkeypatch.delenv("WAIT_HALOPSA_TOKEN_URL", raising=False)
    monkeypatch.delenv("WAIT_HALOPSA_TICKET_WRITE_ENDPOINT", raising=False)
    monkeypatch.delenv("WAIT_HALOPSA_ACTION_WRITE_ENDPOINT", raising=False)
    monkeypatch.delenv("WAIT_DOCUMENT_PARSER", raising=False)
    monkeypatch.delenv("WAIT_ALLOW_OCR", raising=False)
    monkeypatch.delenv("WAIT_VECTOR_BACKEND", raising=False)
    monkeypatch.delenv("WAIT_QDRANT_URL", raising=False)
    monkeypatch.delenv("WAIT_HUDU_BASE_URL", raising=False)
    monkeypatch.delenv("WAIT_HUDU_API_KEY", raising=False)
    monkeypatch.delenv("WAIT_RATE_LIMIT_ENABLED", raising=False)
    monkeypatch.delenv("WAIT_RATE_LIMIT_GENERAL", raising=False)
    monkeypatch.delenv("WAIT_RATE_LIMIT_CONNECTOR", raising=False)
    monkeypatch.delenv("WAIT_UPDATE_CHANNEL_URL", raising=False)
    monkeypatch.delenv("WAIT_UPDATE_PUBKEYS", raising=False)

    settings = load_settings()

    assert settings.allow_write_actions is False
    assert settings.allow_http_probing is False
    assert settings.allow_cloud_fallback is False
    assert settings.allow_llm_inference is False
    assert settings.api_token == ""
    assert settings.admin_token == ""
    assert settings.tech_token == ""
    assert settings.viewer_token == ""
    assert settings.demo_mode is True
    assert settings.secrets_backend == "env"
    assert str(settings.vault_path) == ".wait-local-agent/vault"
    assert settings.local_model_provider == "deterministic"
    assert settings.local_model_timeout_seconds == 20.0
    assert settings.halopsa_base_url == ""
    assert settings.halopsa_token_url == ""
    assert settings.halopsa_ticket_write_endpoint == "Ticket"
    assert settings.halopsa_action_write_endpoint == "Actions"
    assert settings.document_parser == "basic"
    assert settings.allow_ocr is False
    assert settings.vector_backend == "sqlite"
    assert settings.qdrant_url == ""
    assert settings.hudu_base_url == ""
    assert settings.hudu_api_key == ""
    assert settings.hudu_page_size == 25
    assert settings.rate_limit_enabled is True
    assert settings.rate_limit_general == "100/minute"
    assert settings.rate_limit_connector == "10/minute"
    assert settings.update_channel_url == ""
    assert settings.update_pubkeys == ()


def test_boolean_env_accepts_disabled_values(monkeypatch) -> None:
    monkeypatch.setenv("WAIT_ALLOW_WRITE_ACTIONS", "false")
    monkeypatch.setenv("WAIT_ALLOW_LLM_INFERENCE", "true")
    monkeypatch.setenv("WAIT_DEMO_MODE", "false")

    settings = load_settings()

    assert settings.allow_write_actions is False
    assert settings.allow_llm_inference is True
    assert settings.demo_mode is False


def test_invalid_timeout_env_falls_back_to_default(monkeypatch) -> None:
    monkeypatch.setenv("WAIT_LOCAL_MODEL_TIMEOUT_SECONDS", "nope")

    settings = load_settings()

    assert settings.local_model_timeout_seconds == 20.0


def test_hudu_and_knowledge_env_values(monkeypatch) -> None:
    monkeypatch.setenv("WAIT_DOCUMENT_PARSER", "docling")
    monkeypatch.setenv("WAIT_ALLOW_OCR", "true")
    monkeypatch.setenv("WAIT_VECTOR_BACKEND", "qdrant")
    monkeypatch.setenv("WAIT_QDRANT_URL", "http://127.0.0.1:6333")
    monkeypatch.setenv("WAIT_HUDU_BASE_URL", "https://hudu.example.test")
    monkeypatch.setenv("WAIT_HUDU_API_KEY", "api-key")
    monkeypatch.setenv("WAIT_HUDU_PAGE_SIZE", "10")

    settings = load_settings()

    assert settings.document_parser == "docling"
    assert settings.allow_ocr is True
    assert settings.vector_backend == "qdrant"
    assert settings.qdrant_url == "http://127.0.0.1:6333"
    assert settings.hudu_base_url == "https://hudu.example.test"
    assert settings.hudu_api_key == "api-key"
    assert settings.hudu_page_size == 10


def test_rate_limit_env_values(monkeypatch) -> None:
    monkeypatch.setenv("WAIT_RATE_LIMIT_ENABLED", "false")
    monkeypatch.setenv("WAIT_RATE_LIMIT_GENERAL", "25/minute")
    monkeypatch.setenv("WAIT_RATE_LIMIT_CONNECTOR", "5/minute")

    settings = load_settings()

    assert settings.rate_limit_enabled is False
    assert settings.rate_limit_general == "25/minute"
    assert settings.rate_limit_connector == "5/minute"


def test_update_channel_env_values(monkeypatch) -> None:
    monkeypatch.setenv("WAIT_UPDATE_CHANNEL_URL", "https://updates.wait.example.test/channel.json")
    monkeypatch.setenv("WAIT_UPDATE_PUBKEYS", " key-one ,key-two, , key-three ")

    settings = load_settings()

    assert settings.update_channel_url == "https://updates.wait.example.test/channel.json"
    assert settings.update_pubkeys == ("key-one", "key-two", "key-three")


def test_fernet_secret_backend_overrides_env_values(monkeypatch, tmp_path) -> None:
    vault_path = tmp_path / "vault"
    vault = SecretVault.initialize(vault_path)
    vault.set("WAIT_HALOPSA_CLIENT_SECRET", "vault-secret")
    vault.set("WAIT_HUDU_API_KEY", "vault-hudu-key")
    monkeypatch.setenv("WAIT_SECRETS_BACKEND", "fernet")
    monkeypatch.setenv("WAIT_VAULT_PATH", str(vault_path))
    monkeypatch.setenv("WAIT_HALOPSA_CLIENT_SECRET", "env-secret")
    monkeypatch.setenv("WAIT_HUDU_API_KEY", "env-hudu-key")

    settings = load_settings()

    assert settings.secrets_backend == "fernet"
    assert settings.halopsa_client_secret == "vault-secret"
    assert settings.hudu_api_key == "vault-hudu-key"


def test_invalid_secrets_backend_falls_back_to_env(monkeypatch) -> None:
    monkeypatch.setenv("WAIT_SECRETS_BACKEND", "sqlite")
    monkeypatch.setenv("WAIT_HUDU_API_KEY", "env-key")

    settings = load_settings()

    assert settings.secrets_backend == "env"
    assert settings.hudu_api_key == "env-key"


def test_non_positive_timeout_env_falls_back_to_default(monkeypatch) -> None:
    monkeypatch.setenv("WAIT_LOCAL_MODEL_TIMEOUT_SECONDS", "0")

    settings = load_settings()

    assert settings.local_model_timeout_seconds == 20.0
