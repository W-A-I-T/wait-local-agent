from __future__ import annotations

from typer.testing import CliRunner

import wait_local_agent.cli as cli_module
from wait_local_agent.autotask import PsaReadResponse
from wait_local_agent.cli import app
from wait_local_agent.models import ConnectorReadResult, HaloReadResult
from wait_local_agent.rmm import RmmReadResponse


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


def test_validate_ninjaone_cli_requires_read_only_credentials_and_accepts_ready(monkeypatch, tmp_path) -> None:
    class FakeNinjaOneClient:
        def __init__(self, _settings) -> None:
            pass

        def health(self) -> ConnectorReadResult:
            return ConnectorReadResult("ready", "NinjaOne monitoring token request succeeded.")

    monkeypatch.setenv("WAIT_DATA_PATH", str(tmp_path / "state.db"))
    missing = CliRunner().invoke(app, ["connectors", "validate", "ninjaone"])
    assert missing.exit_code == 1
    assert "WAIT_NINJAONE_BASE_URL" in missing.output

    monkeypatch.setenv("WAIT_ALLOW_HTTP_PROBING", "true")
    monkeypatch.setenv("WAIT_NINJAONE_BASE_URL", "https://app.ninjarmm.com")
    monkeypatch.setenv("WAIT_NINJAONE_CLIENT_ID", "client-id")
    monkeypatch.setenv("WAIT_NINJAONE_CLIENT_SECRET", "client-secret")
    monkeypatch.setattr(cli_module, "NinjaOneClient", FakeNinjaOneClient)
    ready = CliRunner().invoke(app, ["connectors", "validate", "ninjaone"])
    assert ready.exit_code == 0
    assert "PASS connector=ninjaone layer=connector" in ready.output


def test_validate_autotask_cli_requires_credentials_and_accepts_ready(monkeypatch, tmp_path) -> None:
    class FakeAutotaskClient:
        def __init__(self, _settings) -> None:
            pass

        def health(self):
            return ConnectorReadResult("ready", "Autotask read prerequisites are ready.")

    monkeypatch.setenv("WAIT_DATA_PATH", str(tmp_path / "state.db"))
    missing = CliRunner().invoke(app, ["connectors", "validate", "autotask"])
    assert missing.exit_code == 1
    assert "WAIT_AUTOTASK_BASE_URL" in missing.output

    monkeypatch.setenv("WAIT_ALLOW_HTTP_PROBING", "true")
    monkeypatch.setenv("WAIT_AUTOTASK_BASE_URL", "https://autotask.example.test")
    monkeypatch.setenv("WAIT_AUTOTASK_USERNAME", "user")
    monkeypatch.setenv("WAIT_AUTOTASK_SECRET", "secret")
    monkeypatch.setenv("WAIT_AUTOTASK_INTEGRATION_CODE", "code")
    monkeypatch.setattr(cli_module, "AutotaskClient", FakeAutotaskClient)
    ready = CliRunner().invoke(app, ["connectors", "validate", "autotask"])
    assert ready.exit_code == 0
    assert "PASS connector=autotask layer=connector" in ready.output


def test_ninjaone_cli_read_commands_use_safe_contract(monkeypatch, tmp_path) -> None:
    result = ConnectorReadResult("ready", "fake NinjaOne response", 1)

    class FakeNinjaOneClient:
        def health(self):
            return result

        def list_devices(self, *, page_size=None, after=None):
            return RmmReadResponse(result, [{"id": "device-1"}])

        def get_device(self, device_id):
            return RmmReadResponse(result, [{"id": device_id}])

        def list_alerts(self, *, page_size=None, after=None):
            return RmmReadResponse(result, [{"id": "alert-1"}])

        def list_scripts(self):
            return RmmReadResponse(result, [{"id": "script-1"}])

        def preview_script(self, device_id, script_id, variables=None):
            return RmmReadResponse(result, [{"device_id": device_id, "script_id": script_id}])

    monkeypatch.setenv("WAIT_DATA_PATH", str(tmp_path / "state.db"))
    monkeypatch.setattr(cli_module, "_ninjaone_client", lambda: FakeNinjaOneClient())
    runner = CliRunner()

    commands = [
        ["connectors", "ninjaone-health"],
        ["connectors", "ninjaone-devices"],
        ["connectors", "ninjaone-device", "device-1"],
        ["connectors", "ninjaone-alerts"],
        ["connectors", "ninjaone-scripts"],
        ["connectors", "ninjaone-script-preview", "device-1", "script-1"],
    ]
    results = [runner.invoke(app, command) for command in commands]

    assert all(item.exit_code == 0 for item in results)
    assert all("ready count=1" in item.output for item in results)


def test_autotask_cli_read_commands_use_safe_contract(monkeypatch, tmp_path) -> None:
    result = ConnectorReadResult("ready", "fake Autotask response", 1)

    class FakeAutotaskClient:
        def health(self):
            return result

        def list_tickets(self, *, page=1, page_size=None):
            return PsaReadResponse(result, [{"id": "ticket-1"}])

        def get_ticket(self, ticket_id):
            return PsaReadResponse(result, [{"id": ticket_id}])

        def list_companies(self, *, page=1, page_size=None):
            return PsaReadResponse(result, [{"id": "company-1"}])

    monkeypatch.setenv("WAIT_DATA_PATH", str(tmp_path / "state.db"))
    monkeypatch.setattr(cli_module, "_autotask_client", lambda: FakeAutotaskClient())
    runner = CliRunner()
    commands = [
        ["connectors", "autotask-health"],
        ["connectors", "autotask-tickets"],
        ["connectors", "autotask-ticket", "ticket-1"],
        ["connectors", "autotask-companies"],
    ]
    results = [runner.invoke(app, command) for command in commands]
    assert all(item.exit_code == 0 for item in results)
    assert all("ready count=1" in item.output for item in results)
