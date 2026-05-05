from __future__ import annotations

from wait_local_agent.config import load_settings


def test_safe_defaults_are_disabled(monkeypatch) -> None:
    monkeypatch.delenv("WAIT_ALLOW_WRITE_ACTIONS", raising=False)
    monkeypatch.delenv("WAIT_ALLOW_HTTP_PROBING", raising=False)
    monkeypatch.delenv("WAIT_ALLOW_CLOUD_FALLBACK", raising=False)

    settings = load_settings()

    assert settings.allow_write_actions is False
    assert settings.allow_http_probing is False
    assert settings.allow_cloud_fallback is False


def test_boolean_env_accepts_disabled_values(monkeypatch) -> None:
    monkeypatch.setenv("WAIT_ALLOW_WRITE_ACTIONS", "false")

    settings = load_settings()

    assert settings.allow_write_actions is False
