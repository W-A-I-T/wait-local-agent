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

    settings = load_settings()

    assert settings.allow_write_actions is False
    assert settings.allow_http_probing is False
    assert settings.allow_cloud_fallback is False
    assert settings.allow_llm_inference is False
    assert settings.local_model_provider == "deterministic"
    assert settings.local_model_timeout_seconds == 20.0
    assert settings.halopsa_base_url == ""


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


def test_non_positive_timeout_env_falls_back_to_default(monkeypatch) -> None:
    monkeypatch.setenv("WAIT_LOCAL_MODEL_TIMEOUT_SECONDS", "0")

    settings = load_settings()

    assert settings.local_model_timeout_seconds == 20.0
