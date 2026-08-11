from __future__ import annotations

import json
from dataclasses import replace
from types import SimpleNamespace
from typing import Any, cast
from xml.etree import ElementTree

import httpx
import pytest

from wait_local_agent.connectors import list_connector_statuses, list_secret_records
from wait_local_agent.nsight import (
    NSightRmmAdapter,
    NSightRmmError,
    _api_url,
    _asset_detail_records,
    _backup_history_records,
    _backup_session_records,
    _check_records,
    _device_numeric_id,
    _monitoring_detail_records,
    _optional_flag,
    _optional_integer,
    _optional_number,
    _outage_records,
    _patch_id_list,
    _performance_history_records,
    _xml_config_value,
)
from wait_local_agent.rmm import rmm_provider_from_settings
from wait_local_agent.smart_actions import (
    ActionContext,
    NSightAntivirusDefinitionsAction,
    NSightAntivirusProductsAction,
    NSightAntivirusQuarantineAction,
    NSightAntivirusQuarantineMutationAction,
    NSightAntivirusScanCancelAction,
    NSightAntivirusScansAction,
    NSightAntivirusScanStartAction,
    NSightCheckConfigAction,
    SmartActionService,
)
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
MAV_SCANS_XML = """
<result status="OK">
  <scan>
    <type>Quick</type><status>Finished Normally</status>
    <start>2026-08-10 09:00:00</start><end>2026-08-10 09:05:00</end>
    <files_scanned>42</files_scanned><folders_scanned>4</folders_scanned>
    <processes_scanned>7</processes_scanned><engine>Bitdefender</engine>
    <threats><threat><name>Example.Malware</name><category>Trojan</category>
      <status>Quarantined</status></threat></threats>
  </scan>
  <scan><type>Deep</type><status>RUNNING</status><start>2026-08-10 10:00:00</start></scan>
  <scan><type></type><status>ignored</status><start>2026-08-10</start></scan>
</result>
"""
MAV_SCAN_START_XML = '<result status="OK"><msg>scan accepted</msg></result>'
MAV_SCAN_CANCEL_XML = '<result status="OK"><msg>scan cancelled</msg></result>'
MAV_PRODUCTS_XML = """
<products>
  <product><name>Bitdefender</name><id>bitdefender</id></product>
  <product><name>Sophos Anti-Virus</name><id>sophos</id></product>
  <product><name></name><id>ignored</id></product>
  <product><name>Ignored</name><id></id></product>
</products>
"""
MAV_DEFINITIONS_XML = """
<result status="OK"><definitions>
  <definition><product>bitdefender</product><version>7.9.1</version><date>2026-08-10 10:00:00</date></definition>
  <definition><product>bitdefender</product><version>7.9.0</version><date>2026-08-03 10:00:00</date></definition>
  <definition><product></product><version>ignored</version><date>2026-08-01</date></definition>
  <definition><product>bitdefender</product><version></version><date>2026-07-01</date></definition>
</definitions></result>
"""
MAV_QUARANTINE_XML = """
<quarantines>
  <quarantine>
    <quarantineguid>q-123</quarantineguid>
    <statusid>1</statusid>
    <group>0</group>
    <quarantineStatus>Quarantined</quarantineStatus>
    <eventDate>2026-08-10 10:00:00</eventDate>
    <threatName>EICAR (v)</threatName>
    <traces>2</traces>
    <eventtype>Deep scan</eventtype>
    <engine>Bitdefender</engine>
  </quarantine>
  <quarantine><statusid>1</statusid></quarantine>
</quarantines>
"""
MAV_QUARANTINE_MUTATION_XML = '<result status="OK"><msg>accepted</msg></result>'
OUTAGES_XML = """
<result status="OK"><outage>
  <reason>CHECK_FAILURE</reason><state>OPEN</state>
  <utc_start>2026-08-10 09:35:04</utc_start><outage_id>103725102</outage_id>
  <check_id>12231188</check_id><check_type>1002</check_type>
  <check_description>Backup Check</check_description><check_status>FAILING</check_status>
  <check_frequency>DAILY</check_frequency><cause>Backup status cannot be determined</cause>
</outage><outage><reason></reason><state>CLOSED</state><outage_id>bad</outage_id></outage></result>
"""
BACKUP_SESSIONS_XML = """
<result status="OK"><session>
  <session_id>12345</session_id><type>BACKUP</type><storage_account_id>139</storage_account_id>
  <plugin>FILE_SYSTEM</plugin><start>2026-08-10 00:06:57</start><end>2026-08-10 00:07:23</end>
  <selection_size>132579334528</selection_size><selection_item_count>22</selection_item_count>
  <size_change>843776</size_change><item_count_change>2</item_count_change>
  <removed_item_count>0</removed_item_count><processed_size>132579334528</processed_size>
  <processed_item_count>22</processed_item_count><transferred_size>955045456</transferred_size>
  <error_count>0</error_count><status>COMPLETED</status>
</session><session><session_id>bad</session_id><status>FAILED</status></session></result>
"""
BACKUP_HISTORY_XML = """
<result status="OK"><checks><name>Backup Check - Example</name><name>Backup Check - Example</name></checks>
<days><day><date>2026-08-10</date><status>PASS</status></day></days>
<days><day><date>2026-08-09</date><status>FAIL</status></day></days>
<days><day><date></date><status>PASS</status></day></days></result>
"""
CHECKS_XML = """
<result status="OK"><items><check>
  <uid>19</uid><sync_status>0</sync_status>
  <description>Web Page Check - Example</description><statusid>5</statusid>
  <date>2026-08-10</date><time>01:08:38</time><utc_run>2026-08-10 08:08:38</utc_run>
  <email>1</email><sms>0</sms><checkid>1304847</checkid><check_type>1012</check_type>
  <dsc_247>1</dsc_247><consecutive_fails>0</consecutive_fails>
</check><check><checkid>bad</checkid><description>ignored</description></check></items></result>
"""
AUTOMATED_TASK_CHECKS_XML = CHECKS_XML.replace(
    "<check_type>1012</check_type>", "<check_type>1023</check_type>"
)
TASK_RUN_NOW_XML = '<result status="OK"><message time="15">15 minutes</message></result>'
CHECK_CONFIG_XML = """
<result status="OK"><check_config><ScriptCheck uid="58">
  <description>Maintenance script</description><scriptname>cleanup.ps1</scriptname>
  <scriptlanguage>7</scriptlanguage><timeout>60</timeout>
  <password>provider-secret</password><argument>one</argument><argument>two</argument>
</ScriptCheck></check_config></result>
"""
PERFORMANCE_HISTORY_XML = """
<result status="OK">
  <bandwidth><host>
    <name>WAN Check</name><host>example.com</host><check_id>101</check_id>
    <receive>2000</receive><transmit>2000</transmit><history>
      <data><start>2026-08-10 10:00:00</start><end>2026-08-10 10:14:59</end>
        <receive>125.5</receive><transmit>50</transmit><ignored>secret</ignored></data>
    </history>
  </host></bandwidth>
  <cpu_load><check_id>102</check_id><average_load>70</average_load><history>
    <data><start>2026-08-10 10:00:00</start><end>2026-08-10 10:59:59</end>
      <cpu><cpu_id>1</cpu_id><load_average>0.5</load_average><load_max>2</load_max></cpu>
      <cpu><cpu_id>2</cpu_id><load_average>0.4</load_average><load_max>2</load_max></cpu>
      <cpu><cpu_id>3</cpu_id><load_average>0.3</load_average><load_max>2</load_max></cpu>
      <cpu><cpu_id>4</cpu_id><load_average>0.2</load_average><load_max>2</load_max></cpu>
      <cpu><cpu_id>5</cpu_id><load_average>0.1</load_average><load_max>2</load_max></cpu>
      <cpu><cpu_id>bad</cpu_id><load_average>bad</load_average><load_max>bad</load_max></cpu>
    </data>
  </history></cpu_load>
  <disk_load><disk>C:</disk><check_id>103</check_id><read_queue_length>2</read_queue_length>
    <history><data><start>2026-08-10</start><disk_time_average>0.5</disk_time_average>
      <read_queue_average></read_queue_average></data></history>
  </disk_load>
  <cpu_queue><check_id>104</check_id><average_length>2</average_length>
    <history><data><queue_average>0.1</queue_average><queue_max>1</queue_max></data></history>
  </cpu_queue>
  <network_usage><interface><adapter>Ethernet</adapter><check_id>105</check_id>
    <average_usage>40</average_usage><history><data><total_average>2</total_average></data></history>
  </interface></network_usage>
  <memory_usage><check_id>106</check_id><available_min>10</available_min></memory_usage>
</result>
"""
ASSET_DETAILS_XML = """
<result status="OK">
  <client>DOMAIN\\foo.user</client><chassistype>8</chassistype><ip>192.0.2.10</ip>
  <mac1>01:23:45:67:89:AA</mac1><user>FOO-LAPTOP</user><manufacturer>LENOVO</manufacturer>
  <model>0657KFG</model><os>Linux</os><role>0</role><ram>2684354560</ram>
  <productkey>SECRET-KEY</productkey>
  <hardware><item><hardwareid>123456</hardwareid><name>Ethernet Adapter</name><type>1</type>
    <manufacturer>Example</manufacturer><details>AdapterType=Ethernet</details><deleted>0</deleted><modified>1</modified></item>
    <item><hardwareid>bad</hardwareid><name>ignored</name></item></hardware>
  <software><item><softwareid>654321</softwareid><name>Agent</name><version>1.2</version>
    <install_date>2026-08-10</install_date><type>All</type><deleted>0</deleted><modified>0</modified></item>
    <item><softwareid>bad</softwareid><name>ignored</name></item></software>
</result>
"""
MONITORING_DETAILS_XML = """
<result status="OK"><server>
  <id>49324</id><name>SRV-01</name><description>Primary server</description>
  <username>DOMAIN\\admin</username><guid>guid-1</guid><os>Windows Server</os>
  <agent>Agent v8.2.6</agent><lastresponse>2026-08-10 16:54:35</lastresponse>
  <lastboot>2026-08-02 09:12:56</lastboot>
  <checks><check><checkid>2089484</checkid><dsc_247>2</dsc_247>
    <description>Windows Service Check</description><checkstatus>testok</checkstatus>
    <extra>Status RUNNING</extra><datetime>2026-08-10 17:54:34</datetime>
    <consecutive_fails>0</consecutive_fails><emailalerts>1</emailalerts><smsalerts>0</smsalerts>
    <emailrecoveryalerts>1</emailrecoveryalerts><smsrecoveryalerts>0</smsrecoveryalerts>
    <servertime>2026-08-10 18:00:00</servertime></check>
    <check><checkid>bad</checkid></check></checks>
  <outages><outage><id>103725102</id><checkid>2089484</checkid><descriptorid>1002</descriptorid>
    <checkstatusicon>testerror</checkstatusicon><description>Backup outage</description>
    <isclosed>0</isclosed><startdate>2026-08-10 09:35:04</startdate></outage>
    <outage><id>bad</id></outage></outages>
  <notes><note><noteid>117575</noteid><created>2026-08-10 11:38:14</created>
    <description>Server note</description><devicename>SRV-01</devicename>
    <note>Maintenance complete</note><public_note>Maintenance complete</public_note></note>
    <note><noteid>bad</noteid></note></notes>
  <takecontrol>1</takecontrol><patch>1</patch><mav>0</mav><mob>0</mob><systray>1</systray><mavbreck>0</mavbreck>
</server></result>
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


def test_nsight_run_task_now_rechecks_device_and_uses_documented_service(settings) -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        service = request.url.params.get("service")
        seen.append(service or "")
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
        if service == "list_checks":
            assert request.url.params.get("deviceid") == "49324"
            return httpx.Response(200, text=AUTOMATED_TASK_CHECKS_XML)
        if service == "task_run_now":
            assert request.url.params.get("checkid") == "1304847"
            return httpx.Response(200, text=TASK_RUN_NOW_XML)
        raise AssertionError(f"unexpected service {service}")

    adapter = _adapter(settings, handler, allow_write_actions=True)
    operation = adapter.run_task_now("server:49324", 1304847, client_id="acme")

    assert operation == {
        "status": "accepted",
        "device_id": "server:49324",
        "check_id": 1304847,
        "minutes_until_run": 15,
        "message": "15 minutes",
    }
    assert seen[:2] == ["list_sites", "list_servers"]
    assert "list_checks" in seen
    assert seen[-1] == "task_run_now"


def test_nsight_check_config_rechecks_device_and_uses_documented_service(settings) -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        service = request.url.params.get("service")
        seen.append(service or "")
        if service == "list_sites":
            return httpx.Response(200, text=SITES_XML)
        if service == "list_servers":
            return httpx.Response(200, text=SERVERS_XML)
        if service == "list_workstations":
            return httpx.Response(200, text=EMPTY_XML)
        if service == "list_checks":
            assert request.url.params.get("deviceid") == "49324"
            return httpx.Response(200, text=CHECKS_XML)
        if service == "list_check_config":
            assert request.url.params.get("checkid") == "1304847"
            return httpx.Response(200, text=CHECK_CONFIG_XML)
        raise AssertionError(f"unexpected service {service}")

    adapter = _adapter(settings, handler)
    result = adapter.get_check_config("server:49324", 1304847, client_id="acme")

    assert result["device_id"] == "server:49324"
    assert result["check_id"] == 1304847
    assert result["check_type"] == 1012
    configuration = result["configuration"]
    assert isinstance(configuration, dict)
    script = configuration["ScriptCheck"]
    assert isinstance(script, dict)
    assert script["@attributes"] == {"uid": "58"}
    assert script["argument"] == ["one", "two"]
    assert script["password"] == "[redacted]"
    assert seen[-1] == "list_check_config"

    service = SmartActionService(
        Store(adapter.settings.data_path),
        adapter.settings,
        rmm_provider=adapter,
    )
    action = service.invoke(
        "nsight-check-config",
        {"device_id": "server:49324", "check_id": "1304847"},
        "tech",
        client_id="acme",
    )
    assert action.status == "success"
    assert action.output["check_id"] == 1304847
    assert action.evidence[0]["operation"] == "list_check_config"


def test_nsight_check_config_rejects_out_of_scope_and_malformed_results(settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        service = request.url.params.get("service")
        if service == "list_sites":
            return httpx.Response(200, text=SITES_XML)
        if service == "list_servers":
            return httpx.Response(200, text=SERVERS_XML)
        if service == "list_workstations":
            return httpx.Response(200, text=EMPTY_XML)
        if service == "list_checks":
            return httpx.Response(200, text=CHECKS_XML)
        if service == "list_check_config":
            return httpx.Response(200, text='<result status="OK"><items /></result>')
        raise AssertionError(f"unexpected service {service}")

    adapter = _adapter(settings, handler)
    with pytest.raises(NSightRmmError, match="positive integer"):
        adapter.get_check_config("server:49324", 0, client_id="acme")
    with pytest.raises(NSightRmmError, match="outside the mapped device scope"):
        adapter.get_check_config("server:49324", 999999, client_id="acme")
    with pytest.raises(NSightRmmError, match="malformed check configuration"):
        adapter.get_check_config("server:49324", 1304847, client_id="acme")

    def malformed_handler(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("service") == "list_sites":
            return httpx.Response(200, text=SITES_XML)
        if request.url.params.get("service") == "list_servers":
            return httpx.Response(200, text=SERVERS_XML)
        if request.url.params.get("service") == "list_workstations":
            return httpx.Response(200, text=EMPTY_XML)
        if request.url.params.get("service") == "list_checks":
            return httpx.Response(200, text=CHECKS_XML)
        return httpx.Response(
            200,
            text='<result status="OK"><check_config>text</check_config></result>',
        )

    malformed_adapter = _adapter(settings, malformed_handler)
    with pytest.raises(NSightRmmError, match="malformed check configuration"):
        malformed_adapter.get_check_config("server:49324", 1304847, client_id="acme")


def test_nsight_xml_config_value_is_bounded() -> None:
    element = ElementTree.fromstring(
        '<check_config><one><two><three><four><five><six><seven>value</seven>'
        "</six></five></four></three></two></one></check_config>"
    )
    assert _xml_config_value(element, depth=0)["one"]["two"]["three"]["four"]["five"]["six"]["seven"] == "[truncated]"  # type: ignore[index]
    leaf = ElementTree.fromstring('<leaf key="value">text</leaf>')
    assert _xml_config_value(leaf, depth=0) == {
        "@attributes": {"key": "value"},
        "value": "text",
    }


def test_nsight_check_config_action_rejects_invalid_and_unavailable_providers(settings) -> None:
    store = Store(settings.data_path)
    action = NSightCheckConfigAction()

    def invoke(provider, payload):
        return action.run(
            ActionContext(store=store, settings=settings, actor="technician", rmm_provider=provider),
            payload,
        )

    assert invoke(SimpleNamespace(adapter_id="n-sight"), {}).status == "failed"
    assert (
        invoke(
            SimpleNamespace(adapter_id="n-sight"),
            {"device_id": "server:1", "check_id": "0"},
        ).status
        == "failed"
    )
    assert (
        invoke(
            SimpleNamespace(
                adapter_id="other",
                get_check_config=lambda *args, **kwargs: {},
            ),
            {"device_id": "server:1", "check_id": "1"},
        ).status
        == "failed"
    )

    class FailingProvider:
        adapter_id = "n-sight"

        def get_check_config(self, *args, **kwargs):
            raise RuntimeError("provider failure")

    class MalformedProvider:
        adapter_id = "n-sight"

        def get_check_config(self, *args, **kwargs):
            return []

    payload = {"device_id": "server:1", "check_id": "1"}
    assert invoke(FailingProvider(), payload).status == "failed"
    assert invoke(MalformedProvider(), payload).status == "failed"


def test_nsight_run_task_now_blocks_without_write_flag(settings) -> None:
    adapter = _adapter(
        settings,
        lambda request: pytest.fail("blocked call must not reach transport"),
    )

    with pytest.raises(NSightRmmError, match="WAIT_ALLOW_WRITE_ACTIONS"):
        adapter.run_task_now("server:49324", 1304847, client_id="acme")


@pytest.mark.parametrize(
    ("checks_xml", "task_xml", "message"),
    [
        (CHECKS_XML, TASK_RUN_NOW_XML, "not a documented automated task"),
        (
            AUTOMATED_TASK_CHECKS_XML,
            '<result status="OK"><message>15 minutes</message></result>',
            "malformed automated-task response",
        ),
    ],
)
def test_nsight_run_task_now_rejects_unsafe_provider_results(
    settings, checks_xml, task_xml, message
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        service = request.url.params.get("service")
        if service == "list_sites":
            return httpx.Response(200, text=SITES_XML)
        if service == "list_servers":
            return httpx.Response(200, text=SERVERS_XML)
        if service == "list_workstations":
            return httpx.Response(200, text=EMPTY_XML)
        if service == "list_checks":
            return httpx.Response(200, text=checks_xml)
        if service == "task_run_now":
            return httpx.Response(200, text=task_xml)
        raise AssertionError(f"unexpected service {service}")

    adapter = _adapter(settings, handler, allow_write_actions=True)
    with pytest.raises(NSightRmmError, match=message):
        adapter.run_task_now("server:49324", 1304847, client_id="acme")


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


def test_nsight_antivirus_quarantine_rechecks_device_and_bounds_records(settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        service = request.url.params.get("service")
        if service == "list_sites":
            return httpx.Response(200, text=SITES_XML)
        if service == "list_servers":
            return httpx.Response(200, text=SERVERS_XML)
        if service == "list_workstations":
            return httpx.Response(200, text=EMPTY_XML)
        if service == "mav_quarantine_list":
            assert request.url.params.get("deviceid") == "49324"
            assert request.url.params.get("v") == "2"
            return httpx.Response(200, text=MAV_QUARANTINE_XML)
        raise AssertionError(f"unexpected service {service}")

    adapter = _adapter(settings, handler)
    quarantine = adapter.list_antivirus_quarantine("server:49324", client_id="acme")
    assert quarantine == [
        {
            "quarantine_id": "q-123",
            "status_id": 1,
            "group": 0,
            "status": "Quarantined",
            "event_date": "2026-08-10 10:00:00",
            "threat_name": "EICAR (v)",
            "trace_count": 2,
            "event_type": "Deep scan",
            "engine": "Bitdefender",
        }
    ]
    with pytest.raises(NSightRmmError, match="outside the mapped client scope"):
        adapter.list_antivirus_quarantine("server:999", client_id="acme")


def test_nsight_supported_antivirus_products_are_bounded_and_mapped(settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params.get("service") == "list_supported_av_products"
        return httpx.Response(200, text=MAV_PRODUCTS_XML)

    adapter = _adapter(settings, handler)
    assert adapter.list_supported_antivirus_products(client_id="acme") == [
        {"id": "bitdefender", "name": "Bitdefender"},
        {"id": "sophos", "name": "Sophos Anti-Virus"},
    ]


def test_nsight_supported_antivirus_products_action_rejects_inputs_and_failures(settings) -> None:
    action = NSightAntivirusProductsAction()
    store = Store(settings.data_path)

    def run(provider, payload):
        return action.run(
            ActionContext(store=store, settings=settings, actor="technician", rmm_provider=provider),
            payload,
        )

    provider = SimpleNamespace(
        adapter_id="n-sight",
        list_supported_antivirus_products=lambda **kwargs: [
            {"id": "bitdefender", "name": "Bitdefender"}
        ],
    )
    assert run(provider, {}).status == "success"
    assert run(provider, {"unexpected": True}).status == "failed"
    assert run(SimpleNamespace(adapter_id="other"), {}).status == "failed"
    assert run(
        SimpleNamespace(
            adapter_id="n-sight",
            list_supported_antivirus_products=lambda **kwargs: (_ for _ in ()).throw(
                RuntimeError("unavailable")
            ),
        ),
        {},
    ).status == "failed"
    assert run(
        SimpleNamespace(adapter_id="n-sight", list_supported_antivirus_products=lambda **kwargs: {}),
        {},
    ).status == "failed"


def test_nsight_antivirus_definitions_recheck_product_and_bound_results(settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        service = request.url.params.get("service")
        if service == "list_supported_av_products":
            return httpx.Response(200, text=MAV_PRODUCTS_XML)
        if service == "list_av_definitions":
            assert request.url.params.get("product") == "bitdefender"
            assert request.url.params.get("max_results") == "2"
            return httpx.Response(200, text=MAV_DEFINITIONS_XML)
        raise AssertionError(f"unexpected service {service}")

    adapter = _adapter(settings, handler)
    assert adapter.list_antivirus_definitions(
        " bitdefender ", max_results=2, client_id="acme"
    ) == [
        {"product": "bitdefender", "version": "7.9.1", "date": "2026-08-10 10:00:00"},
        {"product": "bitdefender", "version": "7.9.0", "date": "2026-08-03 10:00:00"},
    ]
    with pytest.raises(NSightRmmError, match="not in the supported product catalog"):
        adapter.list_antivirus_definitions("unknown", client_id="acme")
    with pytest.raises(NSightRmmError, match="1 to 20"):
        adapter.list_antivirus_definitions("bitdefender", max_results=21, client_id="acme")


def test_nsight_antivirus_definitions_action_rejects_invalid_and_unavailable_inputs(settings) -> None:
    action = NSightAntivirusDefinitionsAction()
    store = Store(settings.data_path)

    def run(provider, payload):
        return action.run(
            ActionContext(store=store, settings=settings, actor="technician", rmm_provider=provider),
            payload,
        )

    provider = SimpleNamespace(
        adapter_id="n-sight",
        list_antivirus_definitions=lambda product_id, **kwargs: [
            {"product": product_id, "version": "7.9.1", "date": "2026-08-10"}
        ],
    )
    result = run(provider, {"product_id": " bitdefender ", "max_results": 2})
    assert result.status == "success"
    assert result.output["product_id"] == "bitdefender"
    assert result.evidence[0]["type"] == "rmm_antivirus_definition"
    assert run(provider, {}).status == "failed"
    assert run(provider, {"product_id": "", "max_results": 2}).status == "failed"
    assert run(provider, {"product_id": "bitdefender", "max_results": 21}).status == "failed"
    assert run(provider, {"product_id": "bitdefender", "unexpected": True}).status == "failed"
    assert run(SimpleNamespace(adapter_id="other"), {"product_id": "bitdefender"}).status == "failed"
    assert run(
        SimpleNamespace(
            adapter_id="n-sight",
            list_antivirus_definitions=lambda product_id, **kwargs: (_ for _ in ()).throw(
                RuntimeError("unavailable")
            ),
        ),
        {"product_id": "bitdefender"},
    ).status == "failed"
    assert run(
        SimpleNamespace(adapter_id="n-sight", list_antivirus_definitions=lambda product_id, **kwargs: {}),
        {"product_id": "bitdefender"},
    ).status == "failed"


def test_nsight_antivirus_quarantine_action_rejects_invalid_and_unavailable_inputs(settings) -> None:
    action = NSightAntivirusQuarantineAction()
    store = Store(settings.data_path)

    def run(provider, payload):
        return action.run(
            ActionContext(store=store, settings=settings, actor="technician", rmm_provider=provider),
            payload,
        )

    provider = SimpleNamespace(
        adapter_id="n-sight",
        list_antivirus_quarantine=lambda device_id, **kwargs: [
            {"quarantine_id": "q-123", "status": "Quarantined"}
        ],
    )
    assert run(provider, {}).status == "failed"
    assert run(SimpleNamespace(adapter_id="other"), {"device_id": "server:1"}).status == "failed"
    result = run(provider, {"device_id": "server:1"})
    assert result.status == "success"
    assert result.output["count"] == 1
    assert result.evidence[0]["type"] == "rmm_antivirus_quarantine"

    malformed = SimpleNamespace(
        adapter_id="n-sight",
        list_antivirus_quarantine=lambda device_id, **kwargs: {},
    )
    assert run(malformed, {"device_id": "server:1"}).status == "failed"

    failing = SimpleNamespace(
        adapter_id="n-sight",
        list_antivirus_quarantine=lambda device_id, **kwargs: (_ for _ in ()).throw(
            RuntimeError("provider unavailable")
        ),
    )
    assert run(failing, {"device_id": "server:1"}).status == "failed"


def test_nsight_antivirus_quarantine_mutations_recheck_ids_and_use_documented_services(
    settings,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        service = request.url.params.get("service")
        if service == "list_sites":
            return httpx.Response(200, text=SITES_XML)
        if service == "list_servers":
            return httpx.Response(200, text=SERVERS_XML)
        if service == "list_workstations":
            return httpx.Response(200, text=EMPTY_XML)
        if service == "mav_quarantine_list":
            return httpx.Response(200, text=MAV_QUARANTINE_XML)
        if service == "mav_quarantine_release":
            assert request.url.params.get("deviceid") == "49324"
            assert request.url.params.get("guids") == "q-123"
            return httpx.Response(200, text=MAV_QUARANTINE_MUTATION_XML)
        if service == "mav_quarantine_remove":
            assert request.url.params.get("deviceid") == "49324"
            assert request.url.params.get("guids") == "q-123"
            return httpx.Response(200, text=MAV_QUARANTINE_MUTATION_XML)
        raise AssertionError(f"unexpected service {service}")

    adapter = _adapter(settings, handler, allow_write_actions=True)
    released = adapter.release_antivirus_quarantine(
        "server:49324", [" q-123", "q-123"], client_id="acme"
    )
    removed = adapter.remove_antivirus_quarantine("server:49324", ["q-123"], client_id="acme")
    assert released == {
        "status": "accepted",
        "operation": "release",
        "device_id": "server:49324",
        "guids": ["q-123"],
        "message": "accepted",
    }
    assert removed["operation"] == "remove"
    with pytest.raises(NSightRmmError, match="WAIT_ALLOW_WRITE_ACTIONS"):
        _adapter(settings, handler).release_antivirus_quarantine(
            "server:49324", ["q-123"], client_id="acme"
        )
    with pytest.raises(NSightRmmError, match="outside the device scope"):
        adapter.release_antivirus_quarantine("server:49324", ["missing"], client_id="acme")


def test_nsight_antivirus_quarantine_mutation_actions_preview_and_gate_writes(settings) -> None:
    store = Store(settings.data_path)

    class Provider:
        adapter_id = "n-sight"

        def release_antivirus_quarantine(self, device_id, guids, *, client_id):
            return {
                "status": "accepted",
                "operation": "release",
                "device_id": device_id,
                "guids": guids,
                "message": "released",
            }

        def remove_antivirus_quarantine(self, device_id, guids, *, client_id):
            return {
                "status": "accepted",
                "operation": "remove",
                "device_id": device_id,
                "guids": guids,
                "message": "removed",
            }

    provider = Provider()
    for operation, method in (
        ("release", "release_antivirus_quarantine"),
        ("remove", "remove_antivirus_quarantine"),
    ):
        action = NSightAntivirusQuarantineMutationAction(
            action_id=f"test-{operation}",
            title=operation,
            operation=operation,
            provider_method=method,
            description=operation,
        )
        preview = action.run(
            ActionContext(
                store=store,
                settings=settings,
                actor="technician",
                rmm_provider=cast(Any, provider),
            ),
            {"device_id": "server:1", "guids": ["q-123"]},
        )
        assert preview.status == "success"
        assert preview.output["approval_required"] is True
        approved = action.run(
            ActionContext(
                store=store,
                settings=replace(settings, allow_write_actions=True),
                actor="technician",
                rmm_provider=cast(Any, provider),
            ),
            {"device_id": "server:1", "guids": ["q-123"], "_approval_completed": True},
        )
        assert approved.status == "success"
        assert approved.output["approved"] is True
        assert approved.evidence[0]["operation"] == operation
        assert action.run(
            ActionContext(store=store, settings=settings, actor="technician", rmm_provider=cast(Any, provider)),
            {"device_id": "server:1", "guids": ["q-123"], "_approval_completed": True},
        ).status == "failed"
        assert action.run(
            ActionContext(store=store, settings=settings, actor="technician", rmm_provider=cast(Any, provider)),
            {"device_id": "server:1", "guids": []},
        ).status == "failed"


def test_nsight_antivirus_quarantine_mutation_actions_reject_invalid_and_provider_failures(
    settings,
) -> None:
    store = Store(settings.data_path)
    action = NSightAntivirusQuarantineMutationAction(
        action_id="test-release-failures",
        title="release",
        operation="release",
        provider_method="release_antivirus_quarantine",
        description="release",
    )

    class FailingProvider:
        adapter_id = "n-sight"

        def release_antivirus_quarantine(self, device_id, guids, *, client_id):
            raise RuntimeError("provider unavailable")

    class MalformedProvider:
        adapter_id = "n-sight"

        def release_antivirus_quarantine(self, device_id, guids, *, client_id):
            return []

    class RejectedProvider:
        adapter_id = "n-sight"

        def release_antivirus_quarantine(self, device_id, guids, *, client_id):
            return {"status": "rejected", "message": "provider denied"}

    def run(provider, payload):
        prepared_payload = dict(payload)
        prepared_payload.setdefault("_approval_completed", True)
        return action.run(
            ActionContext(
                store=store,
                settings=replace(settings, allow_write_actions=True),
                actor="technician",
                rmm_provider=cast(Any, provider),
            ),
            prepared_payload,
        )

    assert run(FailingProvider(), {"device_id": "server:1", "guids": ["q-1"]}).status == "failed"
    assert run(MalformedProvider(), {"device_id": "server:1", "guids": ["q-1"]}).status == "failed"
    rejected = run(RejectedProvider(), {"device_id": "server:1", "guids": [" q-1", "q-1"]})
    assert rejected.status == "failed"
    assert rejected.error_detail == "N-sight antivirus quarantine release failed"
    assert rejected.output["approved"] is True
    assert run(SimpleNamespace(adapter_id="other"), {"device_id": "server:1", "guids": ["q-1"]}).status == "failed"
    assert run(FailingProvider(), {"device_id": "", "guids": ["q-1"]}).status == "failed"
    assert run(FailingProvider(), {"device_id": "server:1", "guids": [""]}).status == "failed"
    assert run(FailingProvider(), {"device_id": "server:1", "guids": ["q-1"], "unexpected": True}).status == "failed"


def test_nsight_antivirus_scans_recheck_device_and_expose_documented_details(settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        service = request.url.params.get("service")
        if service == "list_sites":
            return httpx.Response(200, text=SITES_XML)
        if service == "list_servers":
            return httpx.Response(200, text=SERVERS_XML)
        if service == "list_workstations":
            return httpx.Response(200, text=EMPTY_XML)
        if service == "list_mav_scans":
            assert request.url.params.get("deviceid") == "49324"
            assert request.url.params.get("v") == "2"
            if request.url.params.get("details") == "NO":
                return httpx.Response(
                    200,
                    text=(
                        '<result status="OK"><scan><type>Quick</type>'
                        '<status>FINISHED</status><start>2026-08-10</start>'
                        "</scan></result>"
                    ),
                )
            assert request.url.params.get("details") == "YES"
            return httpx.Response(200, text=MAV_SCANS_XML)
        raise AssertionError(f"unexpected service {service}")

    adapter = _adapter(settings, handler)
    scans = adapter.list_antivirus_scans(
        "server:49324", include_details=True, client_id="acme"
    )
    assert scans == [
        {
            "type": "Quick",
            "status": "Finished Normally",
            "start": "2026-08-10 09:00:00",
            "end": "2026-08-10 09:05:00",
            "engine": "Bitdefender",
            "files_scanned": 42,
            "folders_scanned": 4,
            "processes_scanned": 7,
            "threats": [
                {"name": "Example.Malware", "category": "Trojan", "status": "Quarantined"}
            ],
        },
        {
            "type": "Deep",
            "status": "RUNNING",
            "start": "2026-08-10 10:00:00",
        },
    ]
    summary_scans = adapter.list_antivirus_scans("server:49324", client_id="acme")
    assert summary_scans == [
        {"type": "Quick", "status": "FINISHED", "start": "2026-08-10"}
    ]

    service = SmartActionService(
        Store(adapter.settings.data_path),
        adapter.settings,
        rmm_provider=adapter,
    )
    action = service.invoke(
        "nsight-antivirus-scans",
        {"device_id": "server:49324", "include_details": True},
        "tech",
        client_id="acme",
    )
    assert action.status == "success"
    assert action.output["count"] == 2
    assert action.evidence[0]["operation"] == "list_mav_scans"

    with pytest.raises(NSightRmmError, match="outside the mapped client scope"):
        adapter.list_antivirus_scans("server:999", client_id="acme")


def test_nsight_antivirus_scan_start_rechecks_device_and_uses_documented_service(settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        service = request.url.params.get("service")
        if service == "list_sites":
            return httpx.Response(200, text=SITES_XML)
        if service == "list_servers":
            return httpx.Response(200, text=SERVERS_XML)
        if service == "list_workstations":
            return httpx.Response(200, text=EMPTY_XML)
        if service == "mav_scan_start":
            assert request.url.params.get("deviceid") == "49324"
            return httpx.Response(200, text=MAV_SCAN_START_XML)
        raise AssertionError(f"unexpected service {service}")

    adapter = _adapter(settings, handler, allow_write_actions=True)
    operation = adapter.start_antivirus_scan("server:49324", client_id="acme")
    assert operation == {
        "status": "accepted",
        "device_id": "server:49324",
        "message": "scan accepted",
    }

    with pytest.raises(NSightRmmError, match="WAIT_ALLOW_WRITE_ACTIONS"):
        _adapter(settings, handler).start_antivirus_scan("server:49324", client_id="acme")
    with pytest.raises(NSightRmmError, match="outside the mapped client scope"):
        adapter.start_antivirus_scan("server:999", client_id="acme")


def test_nsight_antivirus_scan_cancel_rechecks_device_and_uses_documented_service(settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        service = request.url.params.get("service")
        if service == "list_sites":
            return httpx.Response(200, text=SITES_XML)
        if service == "list_servers":
            return httpx.Response(200, text=SERVERS_XML)
        if service == "list_workstations":
            return httpx.Response(200, text=EMPTY_XML)
        if service == "mav_scan_cancel":
            assert request.url.params.get("deviceid") == "49324"
            return httpx.Response(200, text=MAV_SCAN_CANCEL_XML)
        raise AssertionError(f"unexpected service {service}")

    adapter = _adapter(settings, handler, allow_write_actions=True)
    operation = adapter.cancel_antivirus_scan("server:49324", client_id="acme")
    assert operation == {
        "status": "accepted",
        "device_id": "server:49324",
        "message": "scan cancelled",
    }

    with pytest.raises(NSightRmmError, match="WAIT_ALLOW_WRITE_ACTIONS"):
        _adapter(settings, handler).cancel_antivirus_scan("server:49324", client_id="acme")
    with pytest.raises(NSightRmmError, match="outside the mapped client scope"):
        adapter.cancel_antivirus_scan("server:999", client_id="acme")


def test_nsight_antivirus_scan_action_rejects_invalid_and_unavailable_inputs(settings) -> None:
    action = NSightAntivirusScansAction()
    store = Store(settings.data_path)

    def run(provider, payload):
        return action.run(
            ActionContext(store=store, settings=settings, actor="technician", rmm_provider=provider),
            payload,
        )

    provider = SimpleNamespace(
        adapter_id="n-sight",
        list_antivirus_scans=lambda device_id, **kwargs: [],
    )
    assert run(provider, {"device_id": "server:1", "unexpected": True}).status == "failed"
    assert run(provider, {"device_id": "server:1", "include_details": "yes"}).status == "failed"
    assert run(SimpleNamespace(adapter_id="other"), {"device_id": "server:1"}).status == "failed"
    assert run(provider, {"device_id": "server:1"}).status == "success"

    malformed = SimpleNamespace(
        adapter_id="n-sight",
        list_antivirus_scans=lambda device_id, **kwargs: {},
    )
    assert run(malformed, {"device_id": "server:1"}).status == "failed"


def test_nsight_antivirus_scan_start_action_previews_and_requires_write_gate(settings) -> None:
    action = NSightAntivirusScanStartAction()
    store = Store(settings.data_path)

    class Provider:
        adapter_id = "n-sight"

        def start_antivirus_scan(self, device_id, *, client_id):
            return {
                "status": "accepted",
                "device_id": device_id,
                "message": "accepted",
            }

    provider = Provider()
    preview = action.run(
        ActionContext(
            store=store,
            settings=settings,
            actor="technician",
            rmm_provider=cast(Any, provider),
        ),
        {"device_id": "server:1"},
    )
    assert preview.status == "success"
    assert preview.output["approval_required"] is True
    assert preview.output["approved"] is False

    approved = action.run(
        ActionContext(
            store=store,
            settings=replace(settings, allow_write_actions=True),
            actor="technician",
            rmm_provider=cast(Any, provider),
        ),
        {"device_id": "server:1", "_approval_completed": True},
    )
    assert approved.status == "success"
    assert approved.output["approved"] is True
    assert approved.evidence[0]["operation"] == "mav_scan_start"

    assert action.run(
        ActionContext(
            store=store,
            settings=settings,
            actor="technician",
            rmm_provider=cast(Any, provider),
        ),
        {"device_id": "server:1", "unexpected": True},
    ).status == "failed"
    assert action.run(
        ActionContext(store=store, settings=settings, actor="technician", rmm_provider=SimpleNamespace()),
        {"device_id": "server:1"},
    ).status == "failed"

    assert action.run(
        ActionContext(
            store=store,
            settings=settings,
            actor="technician",
            rmm_provider=cast(Any, provider),
        ),
        {"device_id": "server:1", "_approval_completed": True},
    ).status == "failed"
    assert action.run(
        ActionContext(
            store=store,
            settings=replace(settings, allow_write_actions=True),
            actor="technician",
            rmm_provider=cast(Any, provider),
        ),
        {"device_id": ""},
    ).status == "failed"

    class FailingProvider:
        adapter_id = "n-sight"

        def start_antivirus_scan(self, device_id, *, client_id):
            raise RuntimeError("provider failure")

    class MalformedProvider:
        adapter_id = "n-sight"

        def start_antivirus_scan(self, device_id, *, client_id):
            return []

    class RejectedProvider:
        adapter_id = "n-sight"

        def start_antivirus_scan(self, device_id, *, client_id):
            return {"status": "rejected", "message": "device unavailable"}

    def approved_context(provider) -> ActionContext:
        return ActionContext(
            store=store,
            settings=replace(settings, allow_write_actions=True),
            actor="technician",
            rmm_provider=cast(Any, provider),
        )
    payload = {"device_id": "server:1", "_approval_completed": True}
    assert action.run(approved_context(FailingProvider()), payload).status == "failed"
    assert action.run(approved_context(MalformedProvider()), payload).status == "failed"
    rejected = action.run(approved_context(RejectedProvider()), payload)
    assert rejected.status == "failed"
    assert rejected.error_detail == "N-sight antivirus scan start failed"


def test_nsight_antivirus_scan_cancel_action_previews_and_requires_write_gate(settings) -> None:
    action = NSightAntivirusScanCancelAction()
    store = Store(settings.data_path)

    class Provider:
        adapter_id = "n-sight"

        def cancel_antivirus_scan(self, device_id, *, client_id):
            return {
                "status": "accepted",
                "device_id": device_id,
                "message": "cancelled",
            }

    provider = Provider()
    preview = action.run(
        ActionContext(
            store=store,
            settings=settings,
            actor="technician",
            rmm_provider=cast(Any, provider),
        ),
        {"device_id": "server:1"},
    )
    assert preview.status == "success"
    assert preview.output["approval_required"] is True
    assert preview.output["approved"] is False

    approved = action.run(
        ActionContext(
            store=store,
            settings=replace(settings, allow_write_actions=True),
            actor="technician",
            rmm_provider=cast(Any, provider),
        ),
        {"device_id": "server:1", "_approval_completed": True},
    )
    assert approved.status == "success"
    assert approved.output["approved"] is True
    assert approved.evidence[0]["operation"] == "mav_scan_cancel"

    assert action.run(
        ActionContext(store=store, settings=settings, actor="technician", rmm_provider=cast(Any, provider)),
        {"device_id": "server:1", "_approval_completed": True},
    ).status == "failed"
    assert action.run(
        ActionContext(store=store, settings=settings, actor="technician", rmm_provider=cast(Any, provider)),
        {"device_id": "server:1", "unexpected": True},
    ).status == "failed"
    assert action.run(
        ActionContext(store=store, settings=settings, actor="technician", rmm_provider=SimpleNamespace()),
        {"device_id": "server:1"},
    ).status == "failed"


def test_nsight_outage_lookup_rechecks_device_scope(settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        service = request.url.params.get("service")
        if service == "list_sites":
            return httpx.Response(200, text=SITES_XML)
        if service == "list_servers":
            return httpx.Response(200, text=SERVERS_XML)
        if service == "list_workstations":
            return httpx.Response(200, text=EMPTY_XML)
        if service == "list_outages":
            assert request.url.params.get("deviceid") == "49324"
            return httpx.Response(200, text=OUTAGES_XML)
        raise AssertionError(f"unexpected service {service}")

    adapter = _adapter(settings, handler)
    outages = adapter.list_outages("server:49324", client_id="acme")
    assert outages == [
        {
            "outage_id": 103725102,
            "reason": "CHECK_FAILURE",
            "state": "OPEN",
            "utc_start": "2026-08-10 09:35:04",
            "utc_end": "",
            "check_id": 12231188,
            "check_type": 1002,
            "check_description": "Backup Check",
            "check_status": "FAILING",
            "check_frequency": "DAILY",
            "cause": "Backup status cannot be determined",
        }
    ]
    with pytest.raises(NSightRmmError, match="outside the mapped client scope"):
        adapter.list_outages("server:999", client_id="acme")


def test_nsight_outage_parser_skips_malformed_rows() -> None:
    assert _outage_records(ElementTree.fromstring(OUTAGES_XML)) == [
        {
            "outage_id": 103725102,
            "reason": "CHECK_FAILURE",
            "state": "OPEN",
            "utc_start": "2026-08-10 09:35:04",
            "utc_end": "",
            "check_id": 12231188,
            "check_type": 1002,
            "check_description": "Backup Check",
            "check_status": "FAILING",
            "check_frequency": "DAILY",
            "cause": "Backup status cannot be determined",
        }
    ]


def test_nsight_backup_sessions_recheck_device_scope(settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        service = request.url.params.get("service")
        if service == "list_sites":
            return httpx.Response(200, text=SITES_XML)
        if service == "list_servers":
            return httpx.Response(200, text=SERVERS_XML)
        if service == "list_workstations":
            return httpx.Response(200, text=EMPTY_XML)
        if service == "list_mob_sessions":
            assert request.url.params.get("deviceid") == "49324"
            return httpx.Response(200, text=BACKUP_SESSIONS_XML)
        raise AssertionError(f"unexpected service {service}")

    adapter = _adapter(settings, handler)
    sessions = adapter.list_backup_sessions("server:49324", client_id="acme")
    assert sessions == [
        {
            "session_id": 12345,
            "type": "BACKUP",
            "storage_account_id": 139,
            "plugin": "FILE_SYSTEM",
            "start": "2026-08-10 00:06:57",
            "end": "2026-08-10 00:07:23",
            "selection_size": 132579334528,
            "selection_item_count": 22,
            "size_change": 843776,
            "item_count_change": 2,
            "removed_item_count": 0,
            "processed_size": 132579334528,
            "processed_item_count": 22,
            "transferred_size": 955045456,
            "error_count": 0,
            "status": "COMPLETED",
        }
    ]
    assert _backup_session_records(ElementTree.fromstring(BACKUP_SESSIONS_XML)) == sessions
    with pytest.raises(NSightRmmError, match="outside the mapped client scope"):
        adapter.list_backup_sessions("server:999", client_id="acme")


def test_nsight_backup_history_rechecks_device_scope(settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        service = request.url.params.get("service")
        if service == "list_sites":
            return httpx.Response(200, text=SITES_XML)
        if service == "list_servers":
            return httpx.Response(200, text=SERVERS_XML)
        if service == "list_workstations":
            return httpx.Response(200, text=EMPTY_XML)
        if service == "list_backup_history":
            assert request.url.params.get("deviceid") == "49324"
            return httpx.Response(200, text=BACKUP_HISTORY_XML)
        raise AssertionError(f"unexpected service {service}")

    adapter = _adapter(settings, handler)
    history = adapter.list_backup_history("server:49324", client_id="acme")
    assert history == {
        "checks": ["Backup Check - Example"],
        "days": [
            {"date": "2026-08-10", "status": "PASS"},
            {"date": "2026-08-09", "status": "FAIL"},
        ],
    }
    assert _backup_history_records(ElementTree.fromstring(BACKUP_HISTORY_XML)) == history
    with pytest.raises(NSightRmmError, match="outside the mapped client scope"):
        adapter.list_backup_history("server:999", client_id="acme")


def test_nsight_check_inventory_rechecks_device_scope(settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        service = request.url.params.get("service")
        if service == "list_sites":
            return httpx.Response(200, text=SITES_XML)
        if service == "list_servers":
            return httpx.Response(200, text=SERVERS_XML)
        if service == "list_workstations":
            return httpx.Response(200, text=EMPTY_XML)
        if service == "list_checks":
            assert request.url.params.get("deviceid") == "49324"
            return httpx.Response(200, text=CHECKS_XML)
        raise AssertionError(f"unexpected service {service}")

    adapter = _adapter(settings, handler)
    checks = adapter.list_checks("server:49324", client_id="acme")

    assert checks == [
        {
            "check_id": 1304847,
            "uid": 19,
            "sync_status": 0,
            "description": "Web Page Check - Example",
            "status_id": 5,
            "date": "2026-08-10",
            "time": "01:08:38",
            "utc_run": "2026-08-10 08:08:38",
            "email_alerts": True,
            "sms_alerts": False,
            "check_type": 1012,
            "dsc_247": 1,
            "consecutive_fails": 0,
        }
    ]
    assert _check_records(ElementTree.fromstring(CHECKS_XML)) == checks
    with pytest.raises(NSightRmmError, match="outside the mapped client scope"):
        adapter.list_checks("server:999", client_id="acme")


def test_nsight_performance_history_rechecks_device_scope(settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        service = request.url.params.get("service")
        if service == "list_sites":
            return httpx.Response(200, text=SITES_XML)
        if service == "list_servers":
            return httpx.Response(200, text=SERVERS_XML)
        if service == "list_workstations":
            return httpx.Response(200, text=EMPTY_XML)
        if service == "list_performance_history":
            assert request.url.params.get("deviceid") == "49324"
            return httpx.Response(200, text=PERFORMANCE_HISTORY_XML)
        raise AssertionError(f"unexpected service {service}")

    adapter = _adapter(settings, handler)
    records = adapter.list_performance_history("server:49324", client_id="acme")

    assert records[0] == {
        "category": "bandwidth",
        "check_id": 101,
        "target": {"name": "WAN Check", "host": "example.com"},
        "thresholds": {"receive": 2000, "transmit": 2000},
        "history": [
            {
                "start": "2026-08-10 10:00:00",
                "end": "2026-08-10 10:14:59",
                "receive": 125.5,
                "transmit": 50,
            }
        ],
    }
    cpu_load = next(record for record in records if record["category"] == "cpu_load")
    assert cpu_load["history"] == [
        {
            "start": "2026-08-10 10:00:00",
            "end": "2026-08-10 10:59:59",
            "cpus": [
                {"cpu_id": 1, "load_average": 0.5, "load_max": 2},
                {"cpu_id": 2, "load_average": 0.4, "load_max": 2},
                {"cpu_id": 3, "load_average": 0.3, "load_max": 2},
                {"cpu_id": 4, "load_average": 0.2, "load_max": 2},
            ],
        }
    ]
    assert _performance_history_records(ElementTree.fromstring(PERFORMANCE_HISTORY_XML)) == records
    with pytest.raises(NSightRmmError, match="outside the mapped client scope"):
        adapter.list_performance_history("server:999", client_id="acme")


def test_nsight_asset_details_rechecks_device_scope(settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        service = request.url.params.get("service")
        if service == "list_sites":
            return httpx.Response(200, text=SITES_XML)
        if service == "list_servers":
            return httpx.Response(200, text=SERVERS_XML)
        if service == "list_workstations":
            return httpx.Response(200, text=EMPTY_XML)
        if service == "list_device_asset_details":
            assert request.url.params.get("deviceid") == "49324"
            return httpx.Response(200, text=ASSET_DETAILS_XML)
        raise AssertionError(f"unexpected service {service}")

    adapter = _adapter(settings, handler)
    asset = adapter.list_asset_details("server:49324", client_id="acme")

    assert asset["details"] == {
        "client": "DOMAIN\\foo.user",
        "chassistype": 8,
        "ip": "192.0.2.10",
        "mac1": "01:23:45:67:89:AA",
        "user": "FOO-LAPTOP",
        "manufacturer": "LENOVO",
        "model": "0657KFG",
        "os": "Linux",
        "role": 0,
        "ram": 2684354560,
    }
    assert asset["hardware"] == [
        {
            "hardware_id": 123456,
            "name": "Ethernet Adapter",
            "type": 1,
            "manufacturer": "Example",
            "details": "AdapterType=Ethernet",
            "status": "",
            "deleted": False,
            "modified": True,
        }
    ]
    assert cast(list[dict[str, object]], asset["software"])[0]["software_id"] == 654321
    assert "productkey" not in cast(dict[str, object], asset["details"])
    assert _asset_detail_records(ElementTree.fromstring(ASSET_DETAILS_XML)) == asset
    with pytest.raises(NSightRmmError, match="outside the mapped client scope"):
        adapter.list_asset_details("server:999", client_id="acme")


def test_nsight_monitoring_details_rechecks_device_scope(settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        service = request.url.params.get("service")
        if service == "list_sites":
            return httpx.Response(200, text=SITES_XML)
        if service == "list_servers":
            return httpx.Response(200, text=SERVERS_XML)
        if service == "list_workstations":
            return httpx.Response(200, text=EMPTY_XML)
        if service == "list_device_monitoring_details":
            assert request.url.params.get("deviceid") == "49324"
            return httpx.Response(200, text=MONITORING_DETAILS_XML)
        raise AssertionError(f"unexpected service {service}")

    adapter = _adapter(settings, handler)
    monitoring = adapter.list_monitoring_details("server:49324", client_id="acme")

    assert cast(dict[str, object], monitoring["device"])["type"] == "server"
    assert cast(list[dict[str, object]], monitoring["checks"])[0]["check_id"] == 2089484
    assert cast(list[dict[str, object]], monitoring["outages"])[0]["isclosed"] is False
    assert cast(list[dict[str, object]], monitoring["notes"])[0]["note_id"] == 117575
    assert cast(dict[str, bool], monitoring["features"]) == {
        "takecontrol": True,
        "patch": True,
        "mav": False,
        "mob": False,
        "systray": True,
        "mavbreck": False,
    }
    assert _monitoring_detail_records(ElementTree.fromstring(MONITORING_DETAILS_XML)) == monitoring
    with pytest.raises(NSightRmmError, match="outside the mapped client scope"):
        adapter.list_monitoring_details("server:999", client_id="acme")


def test_nsight_monitoring_details_parser_handles_missing_device() -> None:
    assert _monitoring_detail_records(ElementTree.fromstring("<result />")) == {
        "device": {},
        "checks": [],
        "outages": [],
        "notes": [],
        "features": {},
    }
    workstation = _monitoring_detail_records(
        ElementTree.fromstring("<result><workstation><id>38549</id></workstation></result>")
    )
    assert cast(dict[str, object], workstation["device"])["type"] == "workstation"


def test_nsight_inventory_and_performance_parsers_enforce_bounds() -> None:
    checks = ElementTree.fromstring(
        "<result><items>"
        + "".join(f"<check><checkid>{index}</checkid></check>" for index in range(1, 105))
        + "</items></result>"
    )
    performance = ElementTree.fromstring(
        "<result><bandwidth>"
        + "".join(
            f"<host><check_id>{index}</check_id><history><data><receive>1</receive></data></history></host>"
            for index in range(1, 105)
        )
        + "</bandwidth></result>"
    )

    assert len(_check_records(checks)) == 100
    assert len(_performance_history_records(performance)) == 100
    assert _optional_number("") is None
    assert _optional_number("not-a-number") is None
    assert _optional_number("nan") is None
    assert _optional_number("1e100") is None


def test_nsight_asset_details_omit_invalid_numeric_fields_and_empty_inventory() -> None:
    asset = _asset_detail_records(
        ElementTree.fromstring(
            "<result><chassistype>not-a-number</chassistype>"
            "<ram>999999999999999999999999999999</ram></result>"
        )
    )
    assert asset == {"details": {}, "hardware": [], "software": []}


def test_backup_history_parser_enforces_documented_bounds() -> None:
    checks = "".join(f"<name>Check {index}</name>" for index in range(30))
    days = "".join(
        f"<day><date>2026-08-{(index % 28) + 1:02d}</date><status>PASS</status></day>"
        for index in range(65)
    )
    root = ElementTree.fromstring(f"<result><checks>{checks}</checks><days>{days}</days></result>")

    parsed = _backup_history_records(root)

    assert len(cast(list[str], parsed["checks"])) == 25
    assert len(cast(list[dict[str, str]], parsed["days"])) == 60


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
