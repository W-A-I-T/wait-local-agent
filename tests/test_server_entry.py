from __future__ import annotations

from pathlib import Path
from typing import cast

from fastapi import FastAPI

import wait_local_agent.api.server_entry as server_entry


def test_server_entry_uses_env_settings_and_server_address(monkeypatch, tmp_path: Path) -> None:
    data_path = tmp_path / "state.db"
    vault_path = tmp_path / "vault"
    captured: dict[str, object] = {}

    monkeypatch.setenv("WAIT_DATA_PATH", str(data_path))
    monkeypatch.setenv("WAIT_VAULT_PATH", str(vault_path))
    monkeypatch.setenv("WAIT_HOST", "127.0.0.2")
    monkeypatch.setenv("WAIT_PORT", "9876")
    monkeypatch.setenv("WAIT_SCHEDULER_ENABLED", "false")
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


def test_server_entry_defaults_invalid_port(monkeypatch) -> None:
    monkeypatch.setenv("WAIT_PORT", "not-a-port")

    assert server_entry._port_from_env(None) == 8788
    assert server_entry._port_from_env("not-a-port") == 8788
    assert server_entry._port_from_env("0") == 8788
    assert server_entry._port_from_env("65536") == 8788
    assert server_entry._port_from_env("8789") == 8789
