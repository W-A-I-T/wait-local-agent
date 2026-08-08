from __future__ import annotations

from typer.testing import CliRunner

import wait_local_agent.cli as cli_module
from wait_local_agent.autotask import PsaReadResponse
from wait_local_agent.cli import app
from wait_local_agent.itglue import ItGlueDocument, ItGlueFolder, ItGlueOrganization, ItGlueReadResponse
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


def test_validate_itglue_cli_requires_credentials_and_accepts_ready(monkeypatch, tmp_path) -> None:
    class FakeItGlueClient:
        def __init__(self, _settings) -> None:
            pass

        def health(self) -> ConnectorReadResult:
            return ConnectorReadResult("ready", "IT Glue read prerequisites are ready.")

    monkeypatch.setenv("WAIT_DATA_PATH", str(tmp_path / "state.db"))
    missing = CliRunner().invoke(app, ["connectors", "validate", "itglue"])
    assert missing.exit_code == 1
    assert "WAIT_ITGLUE_API_KEY" in missing.output

    monkeypatch.setenv("WAIT_ALLOW_HTTP_PROBING", "true")
    monkeypatch.setenv("WAIT_ITGLUE_BASE_URL", "https://api.itglue.com")
    monkeypatch.setenv("WAIT_ITGLUE_API_KEY", "api-key")
    monkeypatch.setattr(cli_module, "ItGlueClient", FakeItGlueClient)
    ready = CliRunner().invoke(app, ["connectors", "validate", "itglue"])
    assert ready.exit_code == 0
    assert "PASS connector=itglue layer=connector" in ready.output


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


def test_validate_dattormm_cli_requires_credentials_and_accepts_ready(monkeypatch, tmp_path) -> None:
    class FakeDattoRmmClient:
        def __init__(self, _settings) -> None:
            pass

        def health(self) -> ConnectorReadResult:
            return ConnectorReadResult("ready", "Datto RMM read prerequisites are ready.")

    monkeypatch.setenv("WAIT_DATA_PATH", str(tmp_path / "state.db"))
    missing = CliRunner().invoke(app, ["connectors", "validate", "dattormm"])
    assert missing.exit_code == 1
    assert "WAIT_DATTORMM_BASE_URL" in missing.output

    monkeypatch.setenv("WAIT_ALLOW_HTTP_PROBING", "true")
    monkeypatch.setenv("WAIT_DATTORMM_BASE_URL", "https://merlot-api.centrastage.net")
    monkeypatch.setenv("WAIT_DATTORMM_API_KEY", "datto-key")
    monkeypatch.setenv("WAIT_DATTORMM_API_SECRET", "datto-secret")
    monkeypatch.setattr(cli_module, "DattoRmmClient", FakeDattoRmmClient)
    ready = CliRunner().invoke(app, ["connectors", "validate", "dattormm"])
    assert ready.exit_code == 0
    assert "PASS connector=dattormm layer=connector" in ready.output


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


def test_validate_connectwise_cli_requires_credentials_and_accepts_ready(monkeypatch, tmp_path) -> None:
    class FakeConnectWiseClient:
        def __init__(self, _settings) -> None:
            pass

        def health(self):
            return ConnectorReadResult("ready", "ConnectWise read prerequisites are ready.")

    monkeypatch.setenv("WAIT_DATA_PATH", str(tmp_path / "state.db"))
    missing = CliRunner().invoke(app, ["connectors", "validate", "connectwise"])
    assert missing.exit_code == 1
    assert "WAIT_CONNECTWISE_BASE_URL" in missing.output

    monkeypatch.setenv("WAIT_ALLOW_HTTP_PROBING", "true")
    monkeypatch.setenv("WAIT_CONNECTWISE_BASE_URL", "https://connectwise.example.test/api")
    monkeypatch.setenv("WAIT_CONNECTWISE_COMPANY_ID", "Acme+MSP")
    monkeypatch.setenv("WAIT_CONNECTWISE_PUBLIC_KEY", "public-key")
    monkeypatch.setenv("WAIT_CONNECTWISE_PRIVATE_KEY", "private-key")
    monkeypatch.setenv("WAIT_CONNECTWISE_CLIENT_ID", "client-id")
    monkeypatch.setattr(cli_module, "ConnectWiseClient", FakeConnectWiseClient)
    ready = CliRunner().invoke(app, ["connectors", "validate", "connectwise"])
    assert ready.exit_code == 0
    assert "PASS connector=connectwise layer=connector" in ready.output


def test_validate_syncro_cli_requires_credentials_and_accepts_ready(monkeypatch, tmp_path) -> None:
    class FakeSyncroClient:
        def __init__(self, _settings) -> None:
            pass

        def health(self):
            return ConnectorReadResult("ready", "Syncro read prerequisites are ready.")

    monkeypatch.setenv("WAIT_DATA_PATH", str(tmp_path / "state.db"))
    missing = CliRunner().invoke(app, ["connectors", "validate", "syncro"])
    assert missing.exit_code == 1
    assert "WAIT_SYNCRO_BASE_URL" in missing.output

    monkeypatch.setenv("WAIT_ALLOW_HTTP_PROBING", "true")
    monkeypatch.setenv("WAIT_SYNCRO_BASE_URL", "https://acme.syncromsp.com/api/v1")
    monkeypatch.setenv("WAIT_SYNCRO_API_KEY", "syncro-key")
    monkeypatch.setattr(cli_module, "SyncroClient", FakeSyncroClient)
    ready = CliRunner().invoke(app, ["connectors", "validate", "syncro"])
    assert ready.exit_code == 0
    assert "PASS connector=syncro layer=connector" in ready.output


def test_validate_servicenow_cli_requires_credentials_and_accepts_ready(monkeypatch, tmp_path) -> None:
    class FakeServiceNowClient:
        def __init__(self, _settings) -> None:
            pass

        def health(self):
            return ConnectorReadResult("ready", "ServiceNow read prerequisites are ready.")

    monkeypatch.setenv("WAIT_DATA_PATH", str(tmp_path / "state.db"))
    missing = CliRunner().invoke(app, ["connectors", "validate", "servicenow"])
    assert missing.exit_code == 1
    assert "WAIT_SERVICENOW_BASE_URL" in missing.output

    monkeypatch.setenv("WAIT_ALLOW_HTTP_PROBING", "true")
    monkeypatch.setenv("WAIT_SERVICENOW_BASE_URL", "https://acme.service-now.com")
    monkeypatch.setenv("WAIT_SERVICENOW_USERNAME", "readonly")
    monkeypatch.setenv("WAIT_SERVICENOW_PASSWORD", "password")
    monkeypatch.setattr(cli_module, "ServiceNowClient", FakeServiceNowClient)
    ready = CliRunner().invoke(app, ["connectors", "validate", "servicenow"])
    assert ready.exit_code == 0
    assert "PASS connector=servicenow layer=connector" in ready.output


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


def test_dattormm_cli_read_commands_use_safe_contract(monkeypatch, tmp_path) -> None:
    result = ConnectorReadResult("ready", "fake Datto RMM response", 1)

    class FakeDattoRmmClient:
        def health(self):
            return result

        def list_devices(self, *, page_size=None, after=None):
            return RmmReadResponse(result, [{"id": "device-1"}])

        def get_device(self, device_id):
            return RmmReadResponse(result, [{"id": device_id}])

        def list_alerts(self, *, page_size=None, after=None):
            return RmmReadResponse(result, [{"id": "alert-1"}])

        def list_scripts(self):
            return RmmReadResponse(result, [{"id": "component-1"}])

        def preview_script(self, device_id, script_id, variables=None):
            return RmmReadResponse(result, [{"device_id": device_id, "script_id": script_id}])

    monkeypatch.setenv("WAIT_DATA_PATH", str(tmp_path / "state.db"))
    monkeypatch.setattr(cli_module, "_dattormm_client", lambda: FakeDattoRmmClient())
    runner = CliRunner()
    commands = [
        ["connectors", "dattormm-health"],
        ["connectors", "dattormm-devices"],
        ["connectors", "dattormm-device", "device-1"],
        ["connectors", "dattormm-alerts"],
        ["connectors", "dattormm-scripts"],
        ["connectors", "dattormm-script-preview", "device-1", "component-1"],
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


def test_connectwise_cli_read_commands_use_safe_contract(monkeypatch, tmp_path) -> None:
    result = ConnectorReadResult("ready", "fake ConnectWise response", 1)

    class FakeConnectWiseClient:
        def health(self):
            return result

        def list_tickets(self, *, page=1, page_size=None):
            return PsaReadResponse(result, [{"id": "ticket-1"}])

        def get_ticket(self, ticket_id):
            return PsaReadResponse(result, [{"id": ticket_id}])

        def list_companies(self, *, page=1, page_size=None):
            return PsaReadResponse(result, [{"id": "company-1"}])

    monkeypatch.setenv("WAIT_DATA_PATH", str(tmp_path / "state.db"))
    monkeypatch.setattr(cli_module, "_connectwise_client", lambda: FakeConnectWiseClient())
    commands = [
        ["connectors", "connectwise-health"],
        ["connectors", "connectwise-tickets"],
        ["connectors", "connectwise-ticket", "ticket-1"],
        ["connectors", "connectwise-companies"],
    ]
    results = [CliRunner().invoke(app, command) for command in commands]
    assert all(item.exit_code == 0 for item in results)
    assert all("ready count=1" in item.output for item in results)


def test_syncro_cli_read_commands_use_safe_contract(monkeypatch, tmp_path) -> None:
    result = ConnectorReadResult("ready", "fake Syncro response", 1)

    class FakeSyncroClient:
        def health(self):
            return result

        def list_tickets(self, *, page=1, page_size=None):
            return PsaReadResponse(result, [{"id": "ticket-1"}])

        def get_ticket(self, ticket_id):
            return PsaReadResponse(result, [{"id": ticket_id}])

        def list_companies(self, *, page=1, page_size=None):
            return PsaReadResponse(result, [{"id": "customer-1"}])

    monkeypatch.setenv("WAIT_DATA_PATH", str(tmp_path / "state.db"))
    monkeypatch.setattr(cli_module, "_syncro_client", lambda: FakeSyncroClient())
    commands = [
        ["connectors", "syncro-health"],
        ["connectors", "syncro-tickets"],
        ["connectors", "syncro-ticket", "ticket-1"],
        ["connectors", "syncro-companies"],
    ]
    results = [CliRunner().invoke(app, command) for command in commands]
    assert all(item.exit_code == 0 for item in results)
    assert all("ready count=1" in item.output for item in results)


def test_servicenow_cli_read_commands_use_safe_contract(monkeypatch, tmp_path) -> None:
    result = ConnectorReadResult("ready", "fake ServiceNow response", 1)

    class FakeServiceNowClient:
        def health(self):
            return result

        def list_tickets(self, *, page=1, page_size=None):
            return PsaReadResponse(result, [{"id": "incident-1"}])

        def get_ticket(self, ticket_id):
            return PsaReadResponse(result, [{"id": ticket_id}])

        def list_companies(self, *, page=1, page_size=None):
            return PsaReadResponse(result, [{"id": "company-1"}])

    monkeypatch.setenv("WAIT_DATA_PATH", str(tmp_path / "state.db"))
    monkeypatch.setattr(cli_module, "_servicenow_client", lambda: FakeServiceNowClient())
    commands = [
        ["connectors", "servicenow-health"],
        ["connectors", "servicenow-tickets"],
        ["connectors", "servicenow-ticket", "incident-1"],
        ["connectors", "servicenow-companies"],
    ]
    results = [CliRunner().invoke(app, command) for command in commands]
    assert all(item.exit_code == 0 for item in results)
    assert all("ready count=1" in item.output for item in results)


def test_itglue_cli_read_commands_use_safe_contract(monkeypatch, tmp_path) -> None:
    result = ConnectorReadResult("ready", "fake IT Glue response", 1)

    class FakeItGlueClient:
        def health(self):
            return result

        def list_organizations(self, *, page=1, page_size=None):
            return ItGlueReadResponse(result, [ItGlueOrganization("organization-1", "Org", "active")])

        def list_documents(self, organization_id, *, folder_id=None, page=1, page_size=None):
            return ItGlueReadResponse(result, [ItGlueDocument("document-1", "Doc", organization_id, "", "", "")])

        def get_document(self, document_id):
            return ItGlueReadResponse(result, [ItGlueDocument(document_id, "Doc", "organization-1", "", "", "")])

        def list_folders(self, organization_id, *, page=1, page_size=None):
            return ItGlueReadResponse(result, [ItGlueFolder("folder-1", "Folder", organization_id, "")])

    monkeypatch.setenv("WAIT_DATA_PATH", str(tmp_path / "state.db"))
    monkeypatch.setattr(cli_module, "_itglue_client", lambda: FakeItGlueClient())
    commands = [
        ["connectors", "itglue-health"],
        ["connectors", "itglue-organizations"],
        ["connectors", "itglue-documents", "organization-1"],
        ["connectors", "itglue-document", "document-1"],
        ["connectors", "itglue-folders", "organization-1"],
    ]
    results = [CliRunner().invoke(app, command) for command in commands]
    assert all(item.exit_code == 0 for item in results)
    assert all("ready count=1" in item.output for item in results)
