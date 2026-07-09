from __future__ import annotations

from typer.testing import CliRunner

import wait_local_agent.cli as cli_module
from wait_local_agent.cli import app
from wait_local_agent.models import ConnectorReadResult, HaloReadResult


class _FakeHaloClient:
    def __init__(self, _settings) -> None:
        pass

    def health(self) -> HaloReadResult:
        return HaloReadResult("ready", "HaloPSA token request succeeded.")


class _FakeHuduClient:
    def __init__(self, _settings) -> None:
        pass

    def health(self) -> ConnectorReadResult:
        return ConnectorReadResult("ready", "Hudu read prerequisites are ready.")


def test_validate_halopsa_cli_success(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("WAIT_DATA_PATH", str(tmp_path / "state.db"))
    monkeypatch.setenv("WAIT_ALLOW_HTTP_PROBING", "true")
    monkeypatch.setenv("WAIT_HALOPSA_BASE_URL", "https://halo.example.test")
    monkeypatch.setenv("WAIT_HALOPSA_CLIENT_ID", "client-id")
    monkeypatch.setenv("WAIT_HALOPSA_CLIENT_SECRET", "secret")
    monkeypatch.setenv("WAIT_HALOPSA_TENANT", "tenant")
    monkeypatch.setattr(cli_module, "HaloPSAClient", _FakeHaloClient)
    runner = CliRunner()

    result = runner.invoke(app, ["connectors", "validate", "halopsa"])

    assert result.exit_code == 0
    assert "PASS connector=halopsa layer=connector" in result.output


def test_validate_halopsa_cli_auth_failure(monkeypatch, tmp_path) -> None:
    class FakeHaloClient(_FakeHaloClient):
        def health(self) -> HaloReadResult:
            return HaloReadResult("failed", "HaloPSA token request failed with HTTP 401.")

    monkeypatch.setenv("WAIT_DATA_PATH", str(tmp_path / "state.db"))
    monkeypatch.setenv("WAIT_ALLOW_HTTP_PROBING", "true")
    monkeypatch.setenv("WAIT_HALOPSA_BASE_URL", "https://halo.example.test")
    monkeypatch.setenv("WAIT_HALOPSA_CLIENT_ID", "client-id")
    monkeypatch.setenv("WAIT_HALOPSA_CLIENT_SECRET", "secret")
    monkeypatch.setenv("WAIT_HALOPSA_TENANT", "tenant")
    monkeypatch.setattr(cli_module, "HaloPSAClient", FakeHaloClient)
    runner = CliRunner()

    result = runner.invoke(app, ["connectors", "validate", "halopsa"])

    assert result.exit_code == 1
    assert "layer=auth" in result.output


def test_validate_halopsa_cli_connectivity_failure(monkeypatch, tmp_path) -> None:
    class FakeHaloClient(_FakeHaloClient):
        def health(self) -> HaloReadResult:
            return HaloReadResult("failed", "HaloPSA token request failed before receiving a response.")

    monkeypatch.setenv("WAIT_DATA_PATH", str(tmp_path / "state.db"))
    monkeypatch.setenv("WAIT_ALLOW_HTTP_PROBING", "true")
    monkeypatch.setenv("WAIT_HALOPSA_BASE_URL", "https://halo.example.test")
    monkeypatch.setenv("WAIT_HALOPSA_CLIENT_ID", "client-id")
    monkeypatch.setenv("WAIT_HALOPSA_CLIENT_SECRET", "secret")
    monkeypatch.setenv("WAIT_HALOPSA_TENANT", "tenant")
    monkeypatch.setattr(cli_module, "HaloPSAClient", FakeHaloClient)
    runner = CliRunner()

    result = runner.invoke(app, ["connectors", "validate", "halopsa"])

    assert result.exit_code == 1
    assert "layer=connectivity" in result.output


def test_validate_hudu_cli_missing_config_and_safety(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("WAIT_DATA_PATH", str(tmp_path / "state.db"))
    runner = CliRunner()

    missing = runner.invoke(app, ["connectors", "validate", "hudu"])

    monkeypatch.setenv("WAIT_HUDU_BASE_URL", "https://hudu.example.test")
    monkeypatch.setenv("WAIT_HUDU_API_KEY", "api-key")
    blocked = runner.invoke(app, ["connectors", "validate", "hudu"])

    assert missing.exit_code == 1
    assert "layer=config" in missing.output
    assert blocked.exit_code == 1
    assert "layer=safety" in blocked.output


def test_validate_hudu_cli_success_and_unreachable(monkeypatch, tmp_path) -> None:
    class FakeHuduClient(_FakeHuduClient):
        def health(self) -> ConnectorReadResult:
            return ConnectorReadResult("failed", "Hudu request failed before receiving a response.")

    monkeypatch.setenv("WAIT_DATA_PATH", str(tmp_path / "state.db"))
    monkeypatch.setenv("WAIT_ALLOW_HTTP_PROBING", "true")
    monkeypatch.setenv("WAIT_HUDU_BASE_URL", "https://hudu.example.test")
    monkeypatch.setenv("WAIT_HUDU_API_KEY", "api-key")
    runner = CliRunner()

    monkeypatch.setattr(cli_module, "HuduClient", _FakeHuduClient)
    success = runner.invoke(app, ["connectors", "validate", "hudu"])

    monkeypatch.setattr(cli_module, "HuduClient", FakeHuduClient)
    failed = runner.invoke(app, ["connectors", "validate", "hudu"])

    assert success.exit_code == 0
    assert "PASS connector=hudu layer=connector" in success.output
    assert failed.exit_code == 1
    assert "layer=connectivity" in failed.output
