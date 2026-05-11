from __future__ import annotations

from wait_local_agent.config import load_settings


def test_safe_defaults_are_disabled(monkeypatch) -> None:
    monkeypatch.delenv("WAIT_ALLOW_WRITE_ACTIONS", raising=False)
    monkeypatch.delenv("WAIT_ALLOW_HTTP_PROBING", raising=False)
    monkeypatch.delenv("WAIT_ALLOW_CLOUD_FALLBACK", raising=False)
    monkeypatch.delenv("WAIT_ALLOW_LLM_INFERENCE", raising=False)
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

    settings = load_settings()

    assert settings.allow_write_actions is False
    assert settings.allow_http_probing is False
    assert settings.allow_cloud_fallback is False
    assert settings.allow_llm_inference is False
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


def test_boolean_env_accepts_disabled_values(monkeypatch) -> None:
    monkeypatch.setenv("WAIT_ALLOW_WRITE_ACTIONS", "false")
    monkeypatch.setenv("WAIT_ALLOW_LLM_INFERENCE", "true")

    settings = load_settings()

    assert settings.allow_write_actions is False
    assert settings.allow_llm_inference is True


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


def test_non_positive_timeout_env_falls_back_to_default(monkeypatch) -> None:
    monkeypatch.setenv("WAIT_LOCAL_MODEL_TIMEOUT_SECONDS", "0")

    settings = load_settings()

    assert settings.local_model_timeout_seconds == 20.0
