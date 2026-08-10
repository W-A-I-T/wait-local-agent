from __future__ import annotations

import json
from dataclasses import replace

import httpx
import pytest

from wait_local_agent.connectors import list_connector_statuses, list_secret_records
from wait_local_agent.nsight import NSightRmmAdapter, NSightRmmError, _api_url
from wait_local_agent.rmm import rmm_provider_from_settings
from wait_local_agent.store import Store

CLIENT_XML = """
<result status="OK"><items><client><clientid>123</clientid><name>Acme</name></client></items></result>
"""
SITES_XML = """
<result status="OK"><items>
  <site><siteid>10</siteid><name>HQ</name></site>
  <site><siteid>11</siteid><name>Branch</name></site>
</items></result>
"""
SERVERS_XML = """
<result status="OK"><items>
  <server><serverid>49324</serverid><name>SRV-01</name><online>0</online>
    <status_247>1</status_247><dsc_status>1</dsc_status><missed_247>1</missed_247>
    <os>Windows Server</os><ip>10.0.0.10</ip><device_serial>SN-1</device_serial>
  </server>
</items></result>
"""
WORKSTATIONS_XML = """
<result status="OK"><items>
  <workstation><workstationid>38549</workstationid><name>WS-01</name><online>1</online>
    <status_247>5</status_247><dsc_status>5</dsc_status><missed_247>0</missed_247>
    <os>Windows 11</os><ip>10.0.0.20</ip><agent_version>6_0_0</agent_version>
  </workstation>
</items></result>
"""
FAILING_CHECKS_XML = """
<result status="OK"><items>
  <client><clientid>123</clientid><name>Acme</name><site><siteid>10</siteid><name>HQ</name>
    <workstations><workstation><id>38549</id><name>WS-01</name>
      <failed_checks><check><checkid>77</checkid><check_type>1013</check_type>
        <description>Windows Service Check - Spooler</description>
        <formatted_output>Status: STOPPED</formatted_output><checkstatus>testerror</checkstatus>
      </check></failed_checks>
    </workstation></workstations>
    <servers><server><id>49324</id><name>SRV-01</name>
      <offline><description>offline - maintenance mode</description></offline>
    </server></servers>
  </site></client>
</items></result>
"""
EMPTY_XML = "<result status=\"OK\"><items /></result>"


def _adapter(settings, handler, **overrides) -> NSightRmmAdapter:
    values = {
        "allow_http_probing": True,
        "n_sight_base_url": "https://nsight.example.test",
        "n_sight_api_key": "nsight-secret-token",
        "n_sight_client_map_json": json.dumps({"acme": 123}),
    }
    values.update(overrides)
    active = replace(settings, **values)
    return NSightRmmAdapter(active, transport=httpx.MockTransport(handler))


def test_nsight_inventory_uses_documented_xml_services_and_tenant_map(settings) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        service = request.url.params.get("service")
        assert request.url.params.get("apikey") == "nsight-secret-token"
        assert request.url.path == "/api/"
        if service == "list_sites":
            assert request.url.params.get("clientid") == "123"
            return httpx.Response(200, text=SITES_XML)
        if service == "list_servers":
            assert request.url.params.get("siteid") in {"10", "11"}
            return httpx.Response(
                200,
                text=SERVERS_XML if request.url.params.get("siteid") == "10" else EMPTY_XML,
            )
        if service == "list_workstations":
            return httpx.Response(
                200,
                text=WORKSTATIONS_XML
                if request.url.params.get("siteid") == "10"
                else EMPTY_XML,
            )
        if service == "list_failing_checks":
            assert request.url.params.get("clientid") == "123"
            assert request.url.params.get("check_type") == "checks"
            return httpx.Response(200, text=FAILING_CHECKS_XML)
        raise AssertionError(f"unexpected service {service}")

    adapter = _adapter(settings, handler)
    devices = adapter.list_devices("acme")
    alerts = adapter.list_alerts("acme")

    assert {device.device_id for device in devices} == {"server:49324", "workstation:38549"}
    assert devices[0].attributes["site_id"] == 10
    assert devices[0].attributes["serial"] == "SN-1"
    assert {alert.device_id for alert in alerts} == {"server:49324", "workstation:38549"}
    assert any("Spooler" in alert.title for alert in alerts)
    assert any(alert.alert_id == "server:49324:offline" for alert in alerts)
    assert all(alert.severity == "high" for alert in alerts)
    assert len(seen) == 6


def test_nsight_failing_checks_recheck_returned_client_scope(settings) -> None:
    mismatched = FAILING_CHECKS_XML.replace("<clientid>123</clientid>", "<clientid>999</clientid>")
    adapter = _adapter(settings, lambda request: httpx.Response(200, text=mismatched))

    assert adapter.list_alerts("acme") == []


def test_nsight_bounds_invalid_rows_and_device_count(settings) -> None:
    rows = ["<server><serverid>not-an-id</serverid></server>"]
    rows.extend(
        f"<server><serverid>{index}</serverid><name>server-{index}</name></server>"
        for index in range(1, 101)
    )
    servers_xml = f'<result status="OK"><items>{"".join(rows)}</items></result>'

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("service") == "list_sites":
            return httpx.Response(
                200,
                text='<result status="OK"><items><site><siteid>10</siteid></site></items></result>',
            )
        return httpx.Response(200, text=servers_xml)

    devices = _adapter(settings, handler).list_devices("acme")

    assert len(devices) == 100
    assert devices[-1].device_id == "server:100"


def test_nsight_caps_sites_and_skips_invalid_site_rows(settings) -> None:
    rows = ["<site><siteid>invalid</siteid><name>ignored</name></site>"]
    rows.extend(f"<site><siteid>{index}</siteid><name>Site {index}</name></site>" for index in range(1, 27))
    sites_xml = f'<result status="OK"><items>{"".join(rows)}</items></result>'

    adapter = _adapter(settings, lambda request: httpx.Response(200, text=sites_xml))

    sites = adapter._list_sites("acme")

    assert len(sites) == 25
    assert sites[-1].site_id == 25


def test_nsight_script_mutations_are_explicitly_unavailable(settings) -> None:
    adapter = _adapter(settings, lambda request: httpx.Response(200, text=SITES_XML))

    assert adapter.list_scripts("acme") == []
    preview = adapter.preview_script("script-1", "server:1", {}, client_id="acme")
    execution = adapter.execute_script("script-1", "server:1", {}, client_id="acme")
    lookup = adapter.get_execution("execution-1", client_id="acme")

    assert preview.status == "blocked"
    assert execution.status == "blocked"
    assert lookup.status == "blocked"
    assert "no documented" in preview.message


@pytest.mark.parametrize(
    ("mapping", "message"),
    [
        ("", "tenant client mapping is missing"),
        ("not-json", "is malformed"),
        ("[]", "must be an object"),
        ('{"acme":"nope"}', "tenant client mapping is missing"),
        ('{"acme":true}', "tenant client mapping is missing"),
        ('{"acme":0}', "positive integers"),
    ],
)
def test_nsight_requires_valid_tenant_mapping(settings, mapping, message) -> None:
    adapter = _adapter(settings, lambda request: httpx.Response(200, text=SITES_XML), n_sight_client_map_json=mapping)

    with pytest.raises(NSightRmmError, match=message):
        adapter.list_devices("acme")


def test_nsight_blocks_network_and_sanitizes_provider_edges(settings) -> None:
    blocked = _adapter(
        settings,
        lambda request: httpx.Response(200, text=SITES_XML),
        allow_http_probing=False,
    )
    with pytest.raises(NSightRmmError, match="WAIT_ALLOW_HTTP_PROBING"):
        blocked.list_devices("acme")

    malformed = _adapter(settings, lambda request: httpx.Response(200, text="not xml"))
    with pytest.raises(NSightRmmError, match="malformed XML"):
        malformed.list_devices("acme")

    unauthorized = _adapter(settings, lambda request: httpx.Response(401, text="secret nsight key"))
    with pytest.raises(NSightRmmError, match="unauthorized") as error:
        unauthorized.list_devices("acme")
    assert "nsight-secret-token" not in str(error.value)

    unsafe = _adapter(settings, lambda request: httpx.Response(200, text=SITES_XML), n_sight_base_url="https://user:pass@example.test/api?key=secret")
    with pytest.raises(NSightRmmError, match="credentials or query"):
        unsafe.list_devices("acme")


@pytest.mark.parametrize(
    ("status_code", "message"),
    [(403, "unauthorized"), (429, "rate limited"), (500, "HTTP 500")],
)
def test_nsight_handles_provider_status_errors(settings, status_code, message) -> None:
    adapter = _adapter(settings, lambda request: httpx.Response(status_code, text="secret"))

    with pytest.raises(NSightRmmError, match=message):
        adapter.list_devices("acme")


def test_nsight_handles_transport_and_xml_error_responses(settings) -> None:
    def transport_error(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection failed", request=request)

    with pytest.raises(NSightRmmError, match="before receiving"):
        _adapter(settings, transport_error).list_devices("acme")

    provider_error = _adapter(
        settings,
        lambda request: httpx.Response(200, text='<result status="FAILED"><message /></result>'),
    )
    with pytest.raises(NSightRmmError, match="returned an error response"):
        provider_error.list_devices("acme")


def test_nsight_rejects_missing_scope_credentials_and_invalid_urls(settings) -> None:
    adapter = _adapter(settings, lambda request: httpx.Response(200, text=SITES_XML))
    with pytest.raises(NSightRmmError, match="explicit tenant scope"):
        adapter.list_devices()

    with pytest.raises(NSightRmmError, match="WAIT_NSIGHT_API_KEY"):
        _adapter(settings, lambda request: httpx.Response(200, text=SITES_XML), n_sight_api_key="").list_devices("acme")

    with pytest.raises(NSightRmmError, match="unsafe characters"):
        _api_url("https://nsight.example.test\n")
    with pytest.raises(NSightRmmError, match=r"HTTP\(S\) URL"):
        _api_url("ftp://nsight.example.test")


def test_nsight_selection_status_and_helpers(settings) -> None:
    active = replace(
        settings,
        allow_http_probing=True,
        n_sight_base_url="https://nsight.example.test",
        n_sight_api_key="nsight-secret-token",
        n_sight_client_map_json='{"acme":123}',
    )
    provider = rmm_provider_from_settings(active, Store(active.data_path))
    rmm_status = next(item for item in list_connector_statuses(active) if item.id == "rmm")
    secret_keys = {item.key for item in list_secret_records(active)}

    assert provider.adapter_id == "n-sight"
    assert rmm_status.name == "N-able N-sight"
    assert rmm_status.status == "configured"
    assert rmm_status.write_actions_enabled is False
    assert "nsight-secret-token" not in rmm_status.message
    assert "WAIT_NSIGHT_API_KEY" in secret_keys
    assert _api_url("https://nsight.example.test") == "https://nsight.example.test/api/"
    assert _api_url("https://nsight.example.test/api") == "https://nsight.example.test/api"
