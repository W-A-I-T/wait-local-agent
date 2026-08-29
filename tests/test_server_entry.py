from __future__ import annotations

import runpy
from pathlib import Path
from typing import cast

from fastapi import FastAPI

import wait_local_agent.api.app as app_module
import wait_local_agent.api.server_entry as server_entry
import wait_local_agent.config as config_module


def test_server_entry_uses_env_settings_and_server_address(monkeypatch, tmp_path: Path) -> None:
    data_path = tmp_path / "state.db"
    vault_path = tmp_path / "vault"
    captured: dict[str, object] = {}

    monkeypatch.setenv("WAIT_DATA_PATH", str(data_path))
    monkeypatch.setenv("WAIT_VAULT_PATH", str(vault_path))
    monkeypatch.setenv("WAIT_HOST", "127.0.0.2")
    monkeypatch.setenv("WAIT_PORT", "9876")
    monkeypatch.setenv("WAIT_SCHEDULER_ENABLED", "false")
    monkeypatch.setenv("WAIT_DEMO_MODE", "true")
    monkeypatch.setattr(
        server_entry.uvicorn,
        "run",
        lambda app, *, host, port: captured.update(app=app, host=host, port=port),
    )

    server_entry.main()

    assert captured["host"] == "127.0.0.2"
    assert captured["port"] == 9876
    app = cast(FastAPI, captured["app"])
    assert app.state.settings.data_path == data_path
    assert app.state.settings.vault_path == vault_path
    assert data_path.exists()


def test_server_entry_executes_main_when_run_as_script(monkeypatch) -> None:
    fake_settings = object()
    fake_app = object()
    calls: list[tuple[object, str, int]] = []

    monkeypatch.setenv("WAIT_HOST", "127.0.0.2")
    monkeypatch.setenv("WAIT_PORT", "9876")
    monkeypatch.setattr(config_module, "load_settings", lambda: fake_settings)
    monkeypatch.setattr(app_module, "create_app", lambda settings: fake_app if settings is fake_settings else None)
    monkeypatch.setattr(
        server_entry.uvicorn,
        "run",
        lambda app, *, host, port: calls.append((app, host, port)),
    )

    runpy.run_module("wait_local_agent.api.server_entry", run_name="__main__")

    assert calls == [(fake_app, "127.0.0.2", 9876)]


def test_server_entry_defaults_invalid_port(monkeypatch) -> None:
    monkeypatch.setenv("WAIT_PORT", "not-a-port")

    assert server_entry._port_from_env(None) == 8788
    assert server_entry._port_from_env("not-a-port") == 8788
    assert server_entry._port_from_env("0") == 8788
    assert server_entry._port_from_env("65536") == 8788
    assert server_entry._port_from_env("8789") == 8789
