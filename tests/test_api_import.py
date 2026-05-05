from __future__ import annotations

import importlib


def test_api_module_import_does_not_create_default_state(monkeypatch, tmp_path) -> None:
    data_path = tmp_path / "state.db"
    monkeypatch.setenv("WAIT_DATA_PATH", str(data_path))

    import wait_local_agent.api.app as app_module

    importlib.reload(app_module)

    assert not data_path.exists()

