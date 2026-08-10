from __future__ import annotations

import json
from dataclasses import replace
from typing import cast

import httpx
import pytest

from wait_local_agent.connectors import list_connector_statuses, list_secret_records
from wait_local_agent.nsight import (
    NSightRmmAdapter,
    NSightRmmError,
    _api_url,
    _device_numeric_id,
    _optional_flag,
    _optional_integer,
    _patch_id_list,
)
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
PATCHES_XML = """
<patches><patch>
  <patchid>681806</patchid><policy>4</policy><status>8</status>
  <statusLabel>Installed</statusLabel><patchTitle>Adobe Reader Security Update</patchTitle>
  <product>Adobe Reader</product><severity>3</severity><severityLabel>Moderate</severityLabel>
  <patchUrl>https://patches.example.test/public</patchUrl>
  <releaseDateText>31-Jul-2024</releaseDateText><installDateText>31-Jul-2024 00:00</installDateText>
  <deployable>1</deployable><uninstallable>1</uninstallable>
</patch><patch><patchid>bad</patchid></patch></patches>
"""
PATCH_APPROVAL_XML = '<result status="OK"><msg>approved</msg></result>'
PATCH_REPROCESS_XML = '<result status="OK"><msg>Reprocessing patches: 681806</msg></result>'
MAV_THREATS_XML = """
<result status="OK"><threat>
  <name>Example.Malware</name><category>Trojan</category>
  <last_event>2026-08-10T10:00:00Z</last_event><last_status>Quarantined</last_status>
  <last_scan_type>Quick</last_scan_type><last_trace_count>2</last_trace_count>
  <engine>Bitdefender</engine>
</threat><threat><name></name><category>ignored</category></threat></result>
"""
EDGE_FAILING_CHECKS_XML = """
<result status="OK"><items><client><clientid>123</clientid>
  <site><siteid>10</siteid><name>HQ</name>
    <servers><server><id>not-an-id</id></server></servers>
    <workstations><workstation><id>38549</id><failed_checks>
      <check><checkid>not-an-id</checkid></check>
    </failed_checks></workstation></workstations>
  </site><site><siteid>11</siteid><name>Branch</name></site>
</client></items></result>
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


def test_nsight_patch_inventory_rechecks_device_and_uses_documented_service(settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        service = request.url.params.get("service")
        if service == "list_sites":
            return httpx.Response(200, text=SITES_XML)
        if service == "list_servers":
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
        if service == "patch_list_all":
            assert request.url.params.get("deviceid") == "49324"
            return httpx.Response(200, text=PATCHES_XML)
        if service == "patch_approve":
            assert request.url.params.get("deviceid") == "49324"
            assert request.url.params.get("patchids") == "681806"
            return httpx.Response(200, text=PATCH_APPROVAL_XML)
        if service == "patch_reprocess":
            assert request.url.params.get("deviceid") == "49324"
            assert request.url.params.get("patchids") == "681806"
            return httpx.Response(200, text=PATCH_REPROCESS_XML)
        if service == "list_mav_threats":
            assert request.url.params.get("deviceid") == "49324"
            assert request.url.params.get("v") == "2"
            return httpx.Response(200, text=MAV_THREATS_XML)
        if service in {"patch_do_nothing", "patch_ignore", "patch_inherit", "patch_retry"}:
            assert request.url.params.get("deviceid") == "49324"
            assert request.url.params.get("patchids") == "681806"
            return httpx.Response(200, text='<result status="OK" />')
        raise AssertionError(f"unexpected service {service}")

    adapter = _adapter(settings, handler)
    patches = adapter.list_patches("server:49324", client_id="acme")

    assert patches == [
        {
            "patch_id": 681806,
            "policy": 4,
            "status": 8,
            "status_label": "Installed",
            "title": "Adobe Reader Security Update",
            "product": "Adobe Reader",
            "severity": 3,
            "severity_label": "Moderate",
            "release_date": "31-Jul-2024",
            "install_date": "31-Jul-2024 00:00",
            "deployable": True,
            "uninstallable": True,
        }
    ]

    with pytest.raises(NSightRmmError, match="outside the mapped client scope"):
        adapter.list_patches("server:999", client_id="acme")

    approved = _adapter(
        settings,
        handler,
        allow_write_actions=True,
    ).approve_patches("server:49324", ["681806"], client_id="acme")
    assert approved == {
        "status": "accepted",
        "message": "approved",
        "device_id": "server:49324",
        "patch_ids": ["681806"],
    }

    reprocessed = _adapter(
        settings,
        handler,
        allow_write_actions=True,
    ).reprocess_patches("server:49324", ["681806"], client_id="acme")
    assert reprocessed["status"] == "accepted"
    assert reprocessed["message"] == "Reprocessing patches: 681806"

    for operation in ("do_nothing", "ignore", "inherit", "retry"):
        result = _adapter(
            settings,
            handler,
            allow_write_actions=True,
        ).apply_patch_policy("server:49324", ["681806"], operation, client_id="acme")
        assert result["status"] == "accepted"
        assert result["operation"] == operation

    with pytest.raises(NSightRmmError, match="not supported"):
        _adapter(settings, handler, allow_write_actions=True).apply_patch_policy(
            "server:49324", ["681806"], "execute", client_id="acme"
        )

    with pytest.raises(NSightRmmError, match="outside the device scope"):
        _adapter(
            settings,
            handler,
            allow_write_actions=True,
        ).approve_patches("server:49324", ["999999"], client_id="acme")

    with pytest.raises(NSightRmmError, match="WAIT_ALLOW_WRITE_ACTIONS"):
        adapter.approve_patches("server:49324", ["681806"], client_id="acme")

    with pytest.raises(NSightRmmError, match="WAIT_ALLOW_WRITE_ACTIONS"):
        adapter.reprocess_patches("server:49324", ["681806"], client_id="acme")

    with pytest.raises(NSightRmmError, match="WAIT_ALLOW_WRITE_ACTIONS"):
        adapter.apply_patch_policy("server:49324", ["681806"], "ignore", client_id="acme")


def test_nsight_antivirus_threats_recheck_device_scope(settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        service = request.url.params.get("service")
        if service == "list_sites":
            return httpx.Response(200, text=SITES_XML)
        if service == "list_servers":
            return httpx.Response(200, text=SERVERS_XML)
        if service == "list_workstations":
            return httpx.Response(200, text=EMPTY_XML)
        if service == "list_mav_threats":
            return httpx.Response(200, text=MAV_THREATS_XML)
        raise AssertionError(f"unexpected service {service}")

    adapter = _adapter(settings, handler)
    threats = adapter.list_antivirus_threats("server:49324", client_id="acme")
    assert threats == [
        {
            "name": "Example.Malware",
            "category": "Trojan",
            "last_event": "2026-08-10T10:00:00Z",
            "last_status": "Quarantined",
            "last_scan_type": "Quick",
            "last_trace_count": 2,
            "engine": "Bitdefender",
        }
    ]
    with pytest.raises(NSightRmmError, match="outside the mapped client scope"):
        adapter.list_antivirus_threats("server:999", client_id="acme")


@pytest.mark.parametrize("patch_ids", [[], ["bad"], ["0"], ["1"] * 21])
def test_nsight_patch_approval_validates_patch_ids(settings, patch_ids) -> None:
    adapter = _adapter(settings, lambda request: httpx.Response(200, text=PATCHES_XML), allow_write_actions=True)

    with pytest.raises(NSightRmmError, match="patch"):
        adapter.approve_patches("server:49324", patch_ids, client_id="acme")


def test_nsight_patch_approval_normalizes_duplicate_ids(settings) -> None:
    adapter = _adapter(
        settings,
        lambda request: httpx.Response(200, text=PATCHES_XML),
        allow_write_actions=True,
    )

    with pytest.raises(NSightRmmError, match="patch"):
        adapter.approve_patches("server:49324", cast(list[str], [681806]), client_id="acme")

    assert _patch_id_list(["681806", "681806"]) == ["681806"]


def test_nsight_failing_check_parser_skips_invalid_provider_rows(settings) -> None:
    adapter = _adapter(
        settings,
        lambda request: httpx.Response(200, text=EDGE_FAILING_CHECKS_XML),
    )

    assert adapter.list_alerts("acme") == []


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ("bad", "mapped server or workstation"),
        ("server:bad", "positive integer"),
        ("server:0", "positive integer"),
    ],
)
def test_nsight_patch_device_id_validation(value, message) -> None:
    with pytest.raises(NSightRmmError, match=message):
        _device_numeric_id(value)

    with pytest.raises(NSightRmmError, match="mapped server or workstation"):
        _device_numeric_id(cast(str, None))


def test_nsight_patch_integer_helpers() -> None:
    assert _optional_integer("") is None
    assert _optional_integer("invalid") is None
    assert _optional_integer(str(2_147_483_648)) is None
    assert _optional_integer("8") == 8
    assert _optional_flag("") is None
    assert _optional_flag("0") is False
    assert _optional_flag("1") is True


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
