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


class _FakeConnectWiseClient:
    def __init__(self, _settings) -> None:
        self.settings = _settings

    def health(self) -> ConnectorReadResult:
        if not self.settings.allow_http_probing:
            return ConnectorReadResult("blocked", "ConnectWise live reads are blocked.")
        return ConnectorReadResult("ready", "ConnectWise PSA read prerequisites are ready.")


class _FakeSyncroClient:
    def __init__(self, _settings) -> None:
        self.settings = _settings

    def health(self) -> ConnectorReadResult:
        if not self.settings.allow_http_probing:
            return ConnectorReadResult("blocked", "Syncro live reads are blocked.")
        return ConnectorReadResult("ready", "Syncro read prerequisites are ready.")


class _FakeServiceNowClient:
    def __init__(self, _settings) -> None:
        self.settings = _settings

    def health(self) -> ConnectorReadResult:
        if not self.settings.allow_http_probing:
            return ConnectorReadResult("blocked", "ServiceNow live reads are blocked.")
        return ConnectorReadResult("ready", "ServiceNow read prerequisites are ready.")


class _FakeAutotaskClient:
    def __init__(self, _settings) -> None:
        self.settings = _settings

    def health(self) -> ConnectorReadResult:
        if not self.settings.allow_http_probing:
            return ConnectorReadResult("blocked", "Autotask live reads are blocked.")
        return ConnectorReadResult("ready", "Autotask read prerequisites are ready.")


class _FakeItGlueClient:
    def __init__(self, _settings) -> None:
        self.settings = _settings

    def health(self) -> ConnectorReadResult:
        if not self.settings.allow_http_probing:
            return ConnectorReadResult("blocked", "IT Glue live reads are blocked.")
        return ConnectorReadResult("ready", "IT Glue read prerequisites are ready.")


class _FakeConfluenceClient:
    def __init__(self, _settings) -> None:
        self.settings = _settings

    def health(self) -> ConnectorReadResult:
        if not self.settings.allow_http_probing:
            return ConnectorReadResult("blocked", "Confluence live reads are blocked.")
        return ConnectorReadResult("ready", "Confluence read prerequisites are ready.")


class _FakeSharePointClient:
    def __init__(self, _settings) -> None:
        self.settings = _settings

    def health(self) -> ConnectorReadResult:
        if not self.settings.allow_http_probing:
            return ConnectorReadResult("blocked", "SharePoint live reads are blocked.")
        return ConnectorReadResult("ready", "SharePoint read prerequisites are ready.")


class _FakeM365Client:
    def __init__(self, _settings) -> None:
        self.settings = _settings

    def health(self) -> ConnectorReadResult:
        if not self.settings.allow_http_probing:
            return ConnectorReadResult("blocked", "Microsoft Graph live reads are blocked.")
        return ConnectorReadResult("ready", "Microsoft Graph identity reads are ready.")


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


def test_validate_connectwise_cli_success_and_safety(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("WAIT_DATA_PATH", str(tmp_path / "state.db"))
    monkeypatch.setenv("WAIT_CONNECTWISE_BASE_URL", "https://cw.example.test")
    monkeypatch.setenv("WAIT_CONNECTWISE_COMPANY", "Acme")
    monkeypatch.setenv("WAIT_CONNECTWISE_PUBLIC_KEY", "public")
    monkeypatch.setenv("WAIT_CONNECTWISE_PRIVATE_KEY", "private")
    monkeypatch.setenv("WAIT_CONNECTWISE_CLIENT_ID", "client")
    monkeypatch.setattr(cli_module, "ConnectWiseClient", _FakeConnectWiseClient)
    runner = CliRunner()

    blocked = runner.invoke(app, ["connectors", "validate", "connectwise"])

    monkeypatch.setenv("WAIT_ALLOW_HTTP_PROBING", "true")
    success = runner.invoke(app, ["connectors", "validate", "connectwise"])

    assert blocked.exit_code == 1
    assert "layer=safety" in blocked.output
    assert success.exit_code == 0
    assert "PASS connector=connectwise layer=connector" in success.output


def test_validate_syncro_cli_success_and_missing_config(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("WAIT_DATA_PATH", str(tmp_path / "state.db"))
    runner = CliRunner()

    missing = runner.invoke(app, ["connectors", "validate", "syncro"])

    monkeypatch.setenv("WAIT_SYNCRO_BASE_URL", "https://acme.syncromsp.com")
    monkeypatch.setenv("WAIT_SYNCRO_API_TOKEN", "syncro-token")
    monkeypatch.setenv("WAIT_ALLOW_HTTP_PROBING", "true")
    monkeypatch.setattr(cli_module, "SyncroClient", _FakeSyncroClient)
    success = runner.invoke(app, ["connectors", "validate", "syncro"])

    assert missing.exit_code == 1
    assert "layer=config" in missing.output
    assert success.exit_code == 0
    assert "PASS connector=syncro layer=connector" in success.output


def test_validate_servicenow_cli_success_and_missing_config(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("WAIT_DATA_PATH", str(tmp_path / "state.db"))
    runner = CliRunner()

    missing = runner.invoke(app, ["connectors", "validate", "servicenow"])

    monkeypatch.setenv("WAIT_SERVICENOW_BASE_URL", "https://service-now.example.test")
    monkeypatch.setenv("WAIT_SERVICENOW_USERNAME", "api-user")
    monkeypatch.setenv("WAIT_SERVICENOW_PASSWORD", "password")
    monkeypatch.setenv("WAIT_ALLOW_HTTP_PROBING", "true")
    monkeypatch.setattr(cli_module, "ServiceNowClient", _FakeServiceNowClient)
    success = runner.invoke(app, ["connectors", "validate", "servicenow"])

    assert missing.exit_code == 1
    assert "layer=config" in missing.output
    assert success.exit_code == 0
    assert "PASS connector=servicenow layer=connector" in success.output


def test_validate_autotask_cli_success_and_missing_config(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("WAIT_DATA_PATH", str(tmp_path / "state.db"))
    runner = CliRunner()

    missing = runner.invoke(app, ["connectors", "validate", "autotask"])

    monkeypatch.setenv("WAIT_AUTOTASK_BASE_URL", "https://webservices1.autotask.net")
    monkeypatch.setenv("WAIT_AUTOTASK_USERNAME", "api-user")
    monkeypatch.setenv("WAIT_AUTOTASK_SECRET", "secret")
    monkeypatch.setenv("WAIT_AUTOTASK_INTEGRATION_CODE", "integration-code")
    monkeypatch.setenv("WAIT_ALLOW_HTTP_PROBING", "true")
    monkeypatch.setattr(cli_module, "AutotaskClient", _FakeAutotaskClient)
    success = runner.invoke(app, ["connectors", "validate", "autotask"])

    assert missing.exit_code == 1
    assert "layer=config" in missing.output
    assert success.exit_code == 0
    assert "PASS connector=autotask layer=connector" in success.output


def test_validate_itglue_cli_success_and_missing_config(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("WAIT_DATA_PATH", str(tmp_path / "state.db"))
    runner = CliRunner()

    missing = runner.invoke(app, ["connectors", "validate", "itglue"])

    monkeypatch.setenv("WAIT_ITGLUE_BASE_URL", "https://api.itglue.com")
    monkeypatch.setenv("WAIT_ITGLUE_API_KEY", "api-key")
    monkeypatch.setenv("WAIT_ALLOW_HTTP_PROBING", "true")
    monkeypatch.setattr(cli_module, "ItGlueClient", _FakeItGlueClient)
    success = runner.invoke(app, ["connectors", "validate", "itglue"])

    assert missing.exit_code == 1
    assert "layer=config" in missing.output
    assert success.exit_code == 0
    assert "PASS connector=itglue layer=connector" in success.output


def test_validate_confluence_cli_success_and_missing_config(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("WAIT_DATA_PATH", str(tmp_path / "state.db"))
    runner = CliRunner()

    missing = runner.invoke(app, ["connectors", "validate", "confluence"])

    monkeypatch.setenv("WAIT_CONFLUENCE_BASE_URL", "https://acme.atlassian.net")
    monkeypatch.setenv("WAIT_CONFLUENCE_EMAIL", "agent@example.test")
    monkeypatch.setenv("WAIT_CONFLUENCE_API_TOKEN", "api-token")
    monkeypatch.setenv("WAIT_ALLOW_HTTP_PROBING", "true")
    monkeypatch.setattr(cli_module, "ConfluenceClient", _FakeConfluenceClient)
    success = runner.invoke(app, ["connectors", "validate", "confluence"])

    assert missing.exit_code == 1
    assert "layer=config" in missing.output
    assert success.exit_code == 0
    assert "PASS connector=confluence layer=connector" in success.output


def test_validate_sharepoint_cli_success_and_missing_config(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("WAIT_DATA_PATH", str(tmp_path / "state.db"))
    runner = CliRunner()

    missing = runner.invoke(app, ["connectors", "validate", "sharepoint"])

    monkeypatch.setenv("WAIT_SHAREPOINT_BASE_URL", "https://graph.microsoft.com/v1.0")
    monkeypatch.setenv("WAIT_SHAREPOINT_ACCESS_TOKEN", "access-token")
    monkeypatch.setenv("WAIT_ALLOW_HTTP_PROBING", "true")
    monkeypatch.setattr(cli_module, "SharePointClient", _FakeSharePointClient)
    success = runner.invoke(app, ["connectors", "validate", "sharepoint"])

    assert missing.exit_code == 1
    assert "layer=config" in missing.output
    assert success.exit_code == 0
    assert "PASS connector=sharepoint layer=connector" in success.output


def test_validate_m365_cli_success_and_missing_config(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("WAIT_DATA_PATH", str(tmp_path / "state.db"))
    runner = CliRunner()

    missing = runner.invoke(app, ["connectors", "validate", "m365"])

    monkeypatch.setenv("WAIT_M365_GRAPH_BASE_URL", "https://graph.microsoft.com/v1.0")
    monkeypatch.setenv("WAIT_M365_ACCESS_TOKEN", "access-token")
    monkeypatch.setenv("WAIT_ALLOW_HTTP_PROBING", "true")
    monkeypatch.setattr(cli_module, "M365GraphClient", _FakeM365Client)
    success = runner.invoke(app, ["connectors", "validate", "m365"])

    assert missing.exit_code == 1
    assert "layer=config" in missing.output
    assert success.exit_code == 0
    assert "PASS connector=m365 layer=connector" in success.output
