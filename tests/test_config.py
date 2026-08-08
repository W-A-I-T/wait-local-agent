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
    monkeypatch.delenv("WAIT_CONNECTWISE_BASE_URL", raising=False)
    monkeypatch.delenv("WAIT_CONNECTWISE_COMPANY", raising=False)
    monkeypatch.delenv("WAIT_CONNECTWISE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("WAIT_CONNECTWISE_PRIVATE_KEY", raising=False)
    monkeypatch.delenv("WAIT_CONNECTWISE_CLIENT_ID", raising=False)
    monkeypatch.delenv("WAIT_CONNECTWISE_API_VERSION", raising=False)
    monkeypatch.delenv("WAIT_SYNCRO_BASE_URL", raising=False)
    monkeypatch.delenv("WAIT_SYNCRO_API_TOKEN", raising=False)
    monkeypatch.delenv("WAIT_CONFLUENCE_BASE_URL", raising=False)
    monkeypatch.delenv("WAIT_CONFLUENCE_EMAIL", raising=False)
    monkeypatch.delenv("WAIT_CONFLUENCE_API_TOKEN", raising=False)
    monkeypatch.delenv("WAIT_SHAREPOINT_BASE_URL", raising=False)
    monkeypatch.delenv("WAIT_SHAREPOINT_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("WAIT_M365_GRAPH_BASE_URL", raising=False)
    monkeypatch.delenv("WAIT_M365_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("WAIT_RATE_LIMIT_ENABLED", raising=False)
    monkeypatch.delenv("WAIT_RATE_LIMIT_GENERAL", raising=False)
    monkeypatch.delenv("WAIT_RATE_LIMIT_CONNECTOR", raising=False)
    monkeypatch.delenv("WAIT_UPDATE_CHANNEL_URL", raising=False)
    monkeypatch.delenv("WAIT_UPDATE_PUBKEYS", raising=False)
    monkeypatch.delenv("WAIT_LICENSE_KEY", raising=False)
    monkeypatch.delenv("WAIT_LICENSE_SECRET", raising=False)
    monkeypatch.delenv("WAIT_PACK_SIGNING_SECRET", raising=False)

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
    assert settings.connectwise_base_url == ""
    assert settings.connectwise_company == ""
    assert settings.connectwise_public_key == ""
    assert settings.connectwise_private_key == ""
    assert settings.connectwise_client_id == ""
    assert settings.connectwise_api_version == "2022.1"
    assert settings.connectwise_page_size == 25
    assert settings.syncro_base_url == ""
    assert settings.syncro_api_token == ""
    assert settings.servicenow_base_url == ""
    assert settings.servicenow_username == ""
    assert settings.servicenow_password == ""
    assert settings.servicenow_api_version == ""
    assert settings.servicenow_page_size == 25
    assert settings.autotask_base_url == ""
    assert settings.autotask_username == ""
    assert settings.autotask_secret == ""
    assert settings.autotask_integration_code == ""
    assert settings.autotask_page_size == 50
    assert settings.itglue_base_url == ""
    assert settings.itglue_api_key == ""
    assert settings.itglue_page_size == 25
    assert settings.confluence_base_url == ""
    assert settings.confluence_email == ""
    assert settings.confluence_api_token == ""
    assert settings.confluence_page_size == 25
    assert settings.sharepoint_base_url == ""
    assert settings.sharepoint_access_token == ""
    assert settings.sharepoint_page_size == 25
    assert settings.m365_graph_base_url == ""
    assert settings.m365_access_token == ""
    assert settings.m365_page_size == 25
    assert settings.rate_limit_enabled is True
    assert settings.rate_limit_general == "100/minute"
    assert settings.rate_limit_connector == "10/minute"
    assert settings.update_channel_url == ""
    assert settings.update_pubkeys == ()
    assert settings.license_key == ""
    assert settings.license_secret == ""
    assert settings.pack_signing_secret == ""


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


def test_connectwise_env_values(monkeypatch) -> None:
    monkeypatch.setenv("WAIT_CONNECTWISE_BASE_URL", "https://cw.example.test")
    monkeypatch.setenv("WAIT_CONNECTWISE_COMPANY", "Acme")
    monkeypatch.setenv("WAIT_CONNECTWISE_PUBLIC_KEY", "public")
    monkeypatch.setenv("WAIT_CONNECTWISE_PRIVATE_KEY", "private")
    monkeypatch.setenv("WAIT_CONNECTWISE_CLIENT_ID", "client")
    monkeypatch.setenv("WAIT_CONNECTWISE_API_VERSION", "2023.1")
    monkeypatch.setenv("WAIT_CONNECTWISE_PAGE_SIZE", "10")

    settings = load_settings()

    assert settings.connectwise_base_url == "https://cw.example.test"
    assert settings.connectwise_company == "Acme"
    assert settings.connectwise_public_key == "public"
    assert settings.connectwise_private_key == "private"
    assert settings.connectwise_client_id == "client"
    assert settings.connectwise_api_version == "2023.1"
    assert settings.connectwise_page_size == 10


def test_syncro_env_values(monkeypatch) -> None:
    monkeypatch.setenv("WAIT_SYNCRO_BASE_URL", "https://acme.syncromsp.com")
    monkeypatch.setenv("WAIT_SYNCRO_API_TOKEN", "syncro-token")

    settings = load_settings()

    assert settings.syncro_base_url == "https://acme.syncromsp.com"
    assert settings.syncro_api_token == "syncro-token"


def test_confluence_env_values(monkeypatch) -> None:
    monkeypatch.setenv("WAIT_CONFLUENCE_BASE_URL", "https://acme.atlassian.net")
    monkeypatch.setenv("WAIT_CONFLUENCE_EMAIL", "agent@example.test")
    monkeypatch.setenv("WAIT_CONFLUENCE_API_TOKEN", "api-token")
    monkeypatch.setenv("WAIT_CONFLUENCE_PAGE_SIZE", "10")

    settings = load_settings()

    assert settings.confluence_base_url == "https://acme.atlassian.net"
    assert settings.confluence_email == "agent@example.test"
    assert settings.confluence_api_token == "api-token"
    assert settings.confluence_page_size == 10


def test_sharepoint_env_values(monkeypatch) -> None:
    monkeypatch.setenv("WAIT_SHAREPOINT_BASE_URL", "https://graph.microsoft.com/v1.0")
    monkeypatch.setenv("WAIT_SHAREPOINT_ACCESS_TOKEN", "access-token")
    monkeypatch.setenv("WAIT_SHAREPOINT_PAGE_SIZE", "50")

    settings = load_settings()

    assert settings.sharepoint_base_url == "https://graph.microsoft.com/v1.0"
    assert settings.sharepoint_access_token == "access-token"
    assert settings.sharepoint_page_size == 50


def test_m365_graph_env_values(monkeypatch) -> None:
    monkeypatch.setenv("WAIT_M365_GRAPH_BASE_URL", "https://graph.microsoft.com/v1.0")
    monkeypatch.setenv("WAIT_M365_ACCESS_TOKEN", "access-token")
    monkeypatch.setenv("WAIT_M365_PAGE_SIZE", "50")

    settings = load_settings()

    assert settings.m365_graph_base_url == "https://graph.microsoft.com/v1.0"
    assert settings.m365_access_token == "access-token"
    assert settings.m365_page_size == 50


def test_servicenow_env_values(monkeypatch) -> None:
    monkeypatch.setenv("WAIT_SERVICENOW_BASE_URL", "https://service-now.example.test")
    monkeypatch.setenv("WAIT_SERVICENOW_USERNAME", "api-user")
    monkeypatch.setenv("WAIT_SERVICENOW_PASSWORD", "password")
    monkeypatch.setenv("WAIT_SERVICENOW_API_VERSION", "v1")
    monkeypatch.setenv("WAIT_SERVICENOW_PAGE_SIZE", "10")

    settings = load_settings()

    assert settings.servicenow_base_url == "https://service-now.example.test"
    assert settings.servicenow_username == "api-user"
    assert settings.servicenow_password == "password"
    assert settings.servicenow_api_version == "v1"
    assert settings.servicenow_page_size == 10


def test_autotask_env_values(monkeypatch) -> None:
    monkeypatch.setenv("WAIT_AUTOTASK_BASE_URL", "https://webservices1.autotask.net")
    monkeypatch.setenv("WAIT_AUTOTASK_USERNAME", "api-user")
    monkeypatch.setenv("WAIT_AUTOTASK_SECRET", "secret")
    monkeypatch.setenv("WAIT_AUTOTASK_INTEGRATION_CODE", "integration-code")
    monkeypatch.setenv("WAIT_AUTOTASK_PAGE_SIZE", "20")

    settings = load_settings()

    assert settings.autotask_base_url == "https://webservices1.autotask.net"
    assert settings.autotask_username == "api-user"
    assert settings.autotask_secret == "secret"
    assert settings.autotask_integration_code == "integration-code"
    assert settings.autotask_page_size == 20


def test_itglue_env_values(monkeypatch) -> None:
    monkeypatch.setenv("WAIT_ITGLUE_BASE_URL", "https://api.itglue.com")
    monkeypatch.setenv("WAIT_ITGLUE_API_KEY", "api-key")
    monkeypatch.setenv("WAIT_ITGLUE_PAGE_SIZE", "10")

    settings = load_settings()

    assert settings.itglue_base_url == "https://api.itglue.com"
    assert settings.itglue_api_key == "api-key"
    assert settings.itglue_page_size == 10


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
    vault.set("license_key", "vault-license-key")
    monkeypatch.setenv("WAIT_SECRETS_BACKEND", "fernet")
    monkeypatch.setenv("WAIT_VAULT_PATH", str(vault_path))
    monkeypatch.setenv("WAIT_HALOPSA_CLIENT_SECRET", "env-secret")
    monkeypatch.setenv("WAIT_HUDU_API_KEY", "env-hudu-key")
    monkeypatch.setenv("WAIT_LICENSE_KEY", "env-license-key")

    settings = load_settings()

    assert settings.secrets_backend == "fernet"
    assert settings.halopsa_client_secret == "vault-secret"
    assert settings.hudu_api_key == "vault-hudu-key"
    assert settings.license_key == "vault-license-key"


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
