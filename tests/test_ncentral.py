from __future__ import annotations

import json
from dataclasses import replace

import httpx
import pytest

from wait_local_agent.connectors import list_connector_statuses, list_secret_records
from wait_local_agent.ncentral import (
    NCentralRmmAdapter,
    NCentralRmmError,
    _first_nested_text,
    _first_text,
    _in_scope,
    _numeric_id,
    _rows,
    _safe_base_url,
    _safe_endpoint,
    _safe_value,
    _severity,
    _status_counts,
    _status_from_response,
    _task_name,
)
from wait_local_agent.rmm import rmm_provider_from_settings
from wait_local_agent.store import Store


def _adapter(settings, handler, **overrides) -> NCentralRmmAdapter:
    values = {
        "allow_http_probing": True,
        "ncentral_base_url": "https://ncentral.example.test",
        "ncentral_access_token": "ncentral-secret-token",
        "ncentral_org_unit_map_json": json.dumps({"acme": [100, 101]}),
        **overrides,
    }
    active = replace(settings, **values)
    return NCentralRmmAdapter(
        active,
        transport=httpx.MockTransport(handler),
        store=Store(active.data_path),
    )


def test_ncentral_calls_are_blocked_by_default(settings) -> None:
    active = replace(
        settings,
        ncentral_base_url="https://ncentral.example.test",
        ncentral_access_token="secret",
        ncentral_org_unit_map_json='{"acme":100}',
    )

    with pytest.raises(NCentralRmmError, match="WAIT_ALLOW_HTTP_PROBING"):
        NCentralRmmAdapter(active).list_devices("acme")


@pytest.mark.parametrize(
    ("mapping", "message"),
    [
        ("", "organization mapping is missing"),
        ("not-json", "is malformed"),
        ("[]", "must be an object"),
        ('{"acme": true}', "positive integers"),
        ('{"acme": [0]}', "positive integers"),
    ],
)
def test_ncentral_requires_explicit_valid_org_unit_map(settings, mapping, message) -> None:
    adapter = _adapter(
        settings,
        lambda request: httpx.Response(200, json=[]),
        ncentral_org_unit_map_json=mapping,
    )

    with pytest.raises(NCentralRmmError, match=message):
        adapter.list_devices("acme")


def test_ncentral_reads_are_tenant_scoped_and_bounded(settings) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path.endswith("/api/devices"):
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "deviceId": 7,
                            "deviceName": "Acme laptop",
                            "deviceClass": "Workstation",
                            "orgUnitId": 100,
                            "lastContact": "2026-08-08T12:00:00Z",
                        },
                        {"deviceId": 8, "deviceName": "Other laptop", "orgUnitId": 999},
                        {"deviceName": "Missing ID", "orgUnitId": 100},
                    ]
                },
            )
        if request.url.path.endswith("/api/org-units/100/active-issues"):
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "deviceId": 7,
                            "orgUnitId": 100,
                            "serviceId": 44,
                            "serviceName": "Disk health",
                            "notificationState": 5,
                        },
                        {"deviceId": 8, "orgUnitId": 999, "serviceId": 45},
                    ]
                },
            )
        if request.url.path.endswith("/api/org-units/101/active-issues"):
            return httpx.Response(200, json={"data": []})
        if request.url.path.endswith("/api/scheduled-tasks"):
            return httpx.Response(
                200,
                json={
                    "data": [
                        {"taskId": 12, "name": "Collect logs", "orgUnitId": 100, "taskType": "Script"},
                        {"taskId": 13, "name": "Other task", "orgUnitId": 999},
                    ]
                },
            )
        raise AssertionError(request.url)

    adapter = _adapter(settings, handler)
    devices = adapter.list_devices("acme")
    alerts = adapter.list_alerts("acme")
    scripts = adapter.list_scripts("acme")

    assert [device.device_id for device in devices] == ["7"]
    assert devices[0].attributes["orgUnitId"] == 100
    assert [alert.alert_id for alert in alerts] == ["100:7:44:active"]
    assert alerts[0].title == "Disk health"
    assert scripts[0].script_id == "12"
    assert scripts[0].description == "N-central Script task"
    assert all(request.headers["authorization"] == "Bearer ncentral-secret-token" for request in seen)
    assert all(request.url.params["pageSize"] == "50" for request in seen)


def test_ncentral_preview_execution_and_status_are_bounded(settings) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path.endswith("/api/devices"):
            return httpx.Response(
                200,
                json={"data": [{"deviceId": 7, "customerId": 200, "orgUnitId": 100}]},
            )
        if request.url.path.endswith("/api/scheduled-tasks") and request.method == "GET":
            return httpx.Response(
                200,
                json={"data": [{"taskId": 12, "name": "Collect logs", "orgUnitId": 100}]},
            )
        if request.url.path.endswith("/api/scheduled-tasks/direct"):
            assert request.method == "POST"
            body = json.loads(request.content)
            assert body["itemId"] == 12
            assert body["taskType"] == "Script"
            assert body["customerId"] == 200
            assert body["deviceId"] == 7
            assert body["parameters"] == [{"name": "days", "value": "7", "type": "string"}]
            assert "credential" not in body
            assert "script" not in body
            return httpx.Response(201, json={"data": {"taskId": 99}})
        if request.url.path.endswith("/api/scheduled-tasks/99/status"):
            return httpx.Response(200, json={"data": {"status": "Completed"}})
        raise AssertionError(request.url)

    adapter = _adapter(settings, handler)
    preview = adapter.preview_script("12", "7", {"days": "7"}, client_id="acme")
    blocked = adapter.execute_script("12", "7", {}, client_id="acme")
    enabled = _adapter(settings, handler, allow_write_actions=True)
    execution = enabled.execute_script("12", "7", {"days": "7"}, client_id="acme")
    tracked = enabled.get_execution("99", client_id="acme")

    assert preview.status == "preview"
    assert "blocked until WAIT_ALLOW_WRITE_ACTIONS=true" in preview.message
    assert blocked.status == "blocked"
    assert execution.status == "queued"
    assert execution.execution_id == "99"
    assert tracked.status == "completed"
    assert tracked.script_id == "12"
    assert tracked.device_id == "7"
    assert [request.method for request in seen].count("POST") == 1


def test_ncentral_preview_and_direct_task_reject_missing_or_malformed_targets(settings) -> None:
    empty = _adapter(settings, lambda request: httpx.Response(200, json={"data": []}), allow_write_actions=True)
    with pytest.raises(NCentralRmmError, match="device is outside"):
        empty.preview_script("12", "7", {}, client_id="acme")

    def missing_script(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/api/devices"):
            return httpx.Response(200, json={"data": [{"deviceId": 7, "customerId": 200, "orgUnitId": 100}]})
        return httpx.Response(200, json={"data": []})

    with pytest.raises(NCentralRmmError, match="scheduled task was not found"):
        _adapter(settings, missing_script, allow_write_actions=True).preview_script(
            "12", "7", {}, client_id="acme"
        )

    def malformed_task(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/api/devices"):
            return httpx.Response(200, json={"data": [{"deviceId": 7, "customerId": 200, "orgUnitId": 100}]})
        if request.url.path.endswith("/api/scheduled-tasks"):
            return httpx.Response(200, json={"data": [{"taskId": 12, "orgUnitId": 100}]})
        return httpx.Response(201, json={"data": {"taskId": "not-numeric"}})

    with pytest.raises(NCentralRmmError, match="direct-task response was malformed"):
        _adapter(settings, malformed_task, allow_write_actions=True).execute_script(
            "12", "7", {}, client_id="acme"
        )


@pytest.mark.parametrize(
    ("status_payload", "expected"),
    [
        ({"data": {"statusCounts": {"Failed": 1}}}, "failed"),
        ({"data": {"statusCounts": {"In Progress": 1}}}, "queued"),
        ({"statusCounts": {"Completed": 1}}, "completed"),
    ],
)
def test_ncentral_status_counts_are_mapped_without_fake_success(settings, status_payload, expected) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/api/devices"):
            return httpx.Response(200, json={"data": [{"deviceId": 7, "customerId": 200, "orgUnitId": 100}]})
        if request.url.path.endswith("/api/scheduled-tasks") and request.method == "GET":
            return httpx.Response(200, json={"data": [{"taskId": 12, "orgUnitId": 100}]})
        if request.url.path.endswith("/direct"):
            return httpx.Response(201, json={"data": {"taskId": 99}})
        return httpx.Response(200, json=status_payload)

    adapter = _adapter(settings, handler, allow_write_actions=True)
    execution = adapter.execute_script("12", "7", {}, client_id="acme")
    assert adapter.get_execution(execution.execution_id, client_id="acme").status == expected


def test_ncentral_numeric_and_status_helpers_fail_closed() -> None:
    assert _first_nested_text({"data": {"taskId": 9}}, "taskId") == "9"
    assert _first_nested_text({"result": {"id": 9}}, "id") == "9"
    assert _first_nested_text({"other": {}}, "id") == ""
    assert _task_name("12", "7", {"secret": "value"}).startswith("WAIT-NC-12-7-")
    assert _status_counts({"statusCounts": {"Unknown": 2, "Failed": True, "Completed": 1}}) == {
        "active": 0,
        "completed": 1,
        "failed": 0,
    }
    assert _status_from_response({"status": "Success"}) == "succeeded"
    with pytest.raises(NCentralRmmError, match="status response was malformed"):
        _status_from_response({"data": {"statusCounts": {"Unknown": 1}}})
    with pytest.raises(NCentralRmmError, match="ID is invalid"):
        _numeric_id(True, "device")
    with pytest.raises(NCentralRmmError, match="ID is invalid"):
        _numeric_id("not-a-number", "device")


def test_ncentral_write_and_status_scope_fail_closed(settings) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"data": []})

    disabled = _adapter(settings, handler, allow_write_actions=False)
    blocked = disabled.execute_script("12", "7", {}, client_id="acme")
    assert blocked.status == "blocked"
    assert seen == []

    enabled = _adapter(settings, handler, allow_write_actions=True)
    outside = enabled.get_execution("99", client_id="acme")
    assert outside.status == "blocked"
    assert "outside" in outside.message
    assert seen == []

    no_store = NCentralRmmAdapter(
        replace(
            settings,
            allow_http_probing=True,
            ncentral_base_url="https://ncentral.example.test",
            ncentral_access_token="secret",
            ncentral_org_unit_map_json='{"acme":100}',
        ),
        transport=httpx.MockTransport(handler),
    )
    assert no_store.get_execution("99", client_id="acme").status == "blocked"
    assert seen == []


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (httpx.Response(200, json={"data": {}}), "malformed"),
        (httpx.Response(200, json={"data": {"status": "Mystery"}}), "malformed"),
        (httpx.Response(401), "unauthorized"),
        (httpx.Response(429), "rate limited"),
        (httpx.Response(500), "HTTP 500"),
    ],
)
def test_ncentral_direct_task_and_status_errors_are_explicit(settings, response, message) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/api/devices"):
            return httpx.Response(200, json={"data": [{"deviceId": 7, "customerId": 200, "orgUnitId": 100}]})
        if request.url.path.endswith("/api/scheduled-tasks") and request.method == "GET":
            return httpx.Response(200, json={"data": [{"taskId": 12, "orgUnitId": 100}]})
        if request.url.path.endswith("/direct"):
            return httpx.Response(201, json={"data": {"taskId": 99}})
        if request.url.path.endswith("/99/status"):
            return response
        raise AssertionError(request.url)

    adapter = _adapter(settings, handler, allow_write_actions=True)
    execution = adapter.execute_script("12", "7", {}, client_id="acme")
    with pytest.raises(NCentralRmmError, match=message):
        adapter.get_execution(execution.execution_id, client_id="acme")


def test_ncentral_http_errors_are_sanitized(settings) -> None:
    adapter = _adapter(
        settings,
        lambda request: httpx.Response(
            403, json={"message": "secret access_token=ncentral-secret"}
        ),
    )

    with pytest.raises(NCentralRmmError, match="unauthorized") as error:
        adapter.list_devices("acme")
    assert "ncentral-secret" not in str(error.value)


def test_ncentral_handles_timeout_malformed_json_and_unsafe_url(settings) -> None:
    timeout_adapter = _adapter(settings, lambda request: (_ for _ in ()).throw(httpx.ReadTimeout("timeout")))
    with pytest.raises(NCentralRmmError, match="before receiving"):
        timeout_adapter.list_devices("acme")

    malformed = _adapter(settings, lambda request: httpx.Response(200, text="not-json"))
    with pytest.raises(NCentralRmmError, match="malformed JSON"):
        malformed.list_devices("acme")

    unsafe = _adapter(
        settings,
        lambda request: httpx.Response(200, json=[]),
        ncentral_base_url="https://user:pass@example.test/api?token=secret",
    )
    with pytest.raises(NCentralRmmError, match="must not contain credentials"):
        unsafe.list_devices("acme")


def test_ncentral_selection_status_and_public_helpers(settings) -> None:
    active = replace(
        settings,
        allow_http_probing=True,
        ncentral_base_url="https://ncentral.example.test",
        ncentral_access_token="ncentral-secret-token",
        ncentral_org_unit_map_json='{"acme":100}',
    )
    provider = rmm_provider_from_settings(active, Store(active.data_path))
    rmm_status = next(item for item in list_connector_statuses(active) if item.id == "rmm")
    secret_keys = {item.key for item in list_secret_records(active)}

    assert provider.adapter_id == "ncentral"
    assert rmm_status.name == "N-able N-central"
    assert rmm_status.status == "configured"
    assert rmm_status.write_actions_enabled is False
    assert "ncentral-secret-token" not in rmm_status.message
    assert "WAIT_NCENTRAL_ACCESS_TOKEN" in secret_keys
    assert _rows({"data": [{"id": 1}]}, "data")[0]["id"] == 1
    assert _first_text({"id": 1}, "id") == "1"
    assert _in_scope({"orgUnitId": 100}, (100,))
    assert not _in_scope({"customerId": 100}, (100,))
    assert _safe_base_url("https://ncentral.example.test/") == "https://ncentral.example.test"
    assert _safe_endpoint("api/devices") == "api/devices"


def test_ncentral_rejects_invalid_script_inputs(settings) -> None:
    adapter = _adapter(settings, lambda request: httpx.Response(200, json=[]))
    with pytest.raises(NCentralRmmError, match="script ID is invalid"):
        adapter.execute_script("task 1", "7", {})
    with pytest.raises(NCentralRmmError, match="execution ID is invalid"):
        adapter.get_execution(" ", client_id="acme")
    with pytest.raises(NCentralRmmError, match="execution ID is invalid"):
        adapter.get_execution("task-1", client_id="acme")


def test_ncentral_missing_credentials_and_no_content_are_safe(settings) -> None:
    incomplete = _adapter(settings, lambda request: httpx.Response(200, json=[]), ncentral_access_token="")
    with pytest.raises(NCentralRmmError, match="credentials are incomplete"):
        incomplete.list_devices("acme")

    no_content = _adapter(settings, lambda request: httpx.Response(204))
    assert no_content.list_devices("acme") == []


def test_ncentral_normalizes_alternate_rows_and_helper_boundaries(settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/active-issues"):
            return httpx.Response(
                200,
                json={
                    "issues": [
                        {"deviceID": 7, "serviceID": 44, "org_unit_id": "100", "_extra": {"deviceName": "Disk"}},
                        {"deviceID": 8, "serviceID": 45, "orgUnitId": 100, "notificationState": "Critical"},
                        {"deviceID": 9, "orgUnitId": 100},
                    ]
                },
            )
        if request.url.path.endswith("/scheduled-tasks"):
            return httpx.Response(
                200,
                json={"tasks": [{"taskID": 12, "displayName": "Task", "orgUnitId": "100"}, {"orgUnitId": 100}]},
            )
        return httpx.Response(
            200,
            json={"items": [{"id": 7, "hostname": "Host", "org_unit_id": "100", "serialNumber": ["a"]}]},
        )

    adapter = _adapter(settings, handler, ncentral_org_unit_map_json='{"acme":[100]}')
    assert adapter.list_devices("acme")[0].name == "Host"
    alerts = adapter.list_alerts("acme")
    assert alerts[0].title == "Disk"
    assert alerts[1].severity == "critical"
    assert adapter.list_scripts("acme")[0].name == "Task"
    assert _rows({"other": "value"}, "data") == []
    assert _rows([{"id": 1}, "bad"])[0]["id"] == 1
    assert _first_text({"value": "  text  "}, "value") == "text"
    assert _first_text({"value": True}, "value") == ""
    assert not _in_scope({"orgUnitId": True}, (1,))
    assert not _in_scope({"orgUnitId": "bad"}, (1,))
    assert _safe_value(["a", 1]) == ["a", 1]
    assert _safe_value({"secret": "value"}) is None
    assert _severity("  Warning ") == "warning"
    assert _severity(3) == "state-3"
    assert _severity(True) == "unknown"


def test_ncentral_rejects_transport_http_payload_and_scope_edges(settings) -> None:
    for response, message in (
        (httpx.Response(429), "rate limited"),
        (httpx.Response(418), "HTTP 418"),
        (httpx.Response(200, json={"errorMessage": "remote detail"}), "error response"),
    ):
        adapter = _adapter(settings, lambda request, response=response: response)
        with pytest.raises(NCentralRmmError, match=message):
            adapter.list_devices("acme")

    transport_error = _adapter(
        settings,
        lambda request: (_ for _ in ()).throw(httpx.WriteError("transport")),
    )
    with pytest.raises(NCentralRmmError, match="request failed$"):
        transport_error.list_devices("acme")

    missing_scope = _adapter(settings, lambda request: httpx.Response(200, json=[]))
    with pytest.raises(NCentralRmmError, match="explicit tenant scope"):
        missing_scope.list_devices(None)
    with pytest.raises(NCentralRmmError, match="mapping is missing"):
        missing_scope.list_devices("other")

    too_many = json.dumps({"acme": list(range(1, 52))})
    with pytest.raises(NCentralRmmError, match="mapping is missing"):
        _adapter(
            settings,
            lambda request: httpx.Response(200, json=[]),
            ncentral_org_unit_map_json=too_many,
        ).list_devices("acme")
    with pytest.raises(NCentralRmmError, match="positive integers"):
        _adapter(
            settings,
            lambda request: httpx.Response(200, json=[]),
            ncentral_org_unit_map_json='{"acme":"nope"}',
        ).list_devices("acme")


def test_ncentral_validates_request_and_url_helpers(settings) -> None:
    adapter = _adapter(settings, lambda request: httpx.Response(200, json=[]))
    with pytest.raises(NCentralRmmError, match="device ID is invalid"):
        adapter.execute_script("task", "device\n", {})
    with pytest.raises(NCentralRmmError, match="limited to 20"):
        adapter.execute_script("task", "device", {str(index): "x" for index in range(21)})
    with pytest.raises(NCentralRmmError, match="bounded text"):
        adapter.execute_script("task", "device", {"key": "bad\nvalue"})
    with pytest.raises(NCentralRmmError, match="script ID is invalid"):
        adapter.execute_script("task id", "device", {})
    with pytest.raises(NCentralRmmError, match="device ID is invalid"):
        adapter.execute_script("task", "", {})
    with pytest.raises(NCentralRmmError, match="bounded text"):
        adapter.execute_script("task", "device", {"k" * 501: "x"})
    with pytest.raises(NCentralRmmError, match="bounded text"):
        adapter.execute_script("task", "device", {"key": "x" * 501})
    with pytest.raises(NCentralRmmError, match="limited to 20"):
        adapter.execute_script("task", "device", {str(index): "x" for index in range(21)})
    with pytest.raises(NCentralRmmError, match=r"HTTP\(S\)"):
        _safe_base_url("ftp://ncentral.example.test")
    with pytest.raises(NCentralRmmError, match="query data"):
        _safe_base_url("https://ncentral.example.test/?token=secret")
    for endpoint, message in (("api/../devices", "endpoint is invalid"), ("api/devices?x=1", "unsafe characters")):
        with pytest.raises(NCentralRmmError, match=message):
            _safe_endpoint(endpoint)
