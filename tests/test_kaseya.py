from __future__ import annotations

import json
from dataclasses import replace

import httpx
import pytest

from wait_local_agent.connectors import list_connector_statuses, list_secret_records
from wait_local_agent.kaseya import (
    KaseyaRmmAdapter,
    KaseyaRmmError,
    _int_value,
    _path_segment,
    _rows,
    _safe_attribute,
    _safe_base_url,
    _safe_endpoint,
    _variable_id,
)
from wait_local_agent.rmm import rmm_provider_from_settings
from wait_local_agent.store import Store


def _adapter(settings, handler, **overrides) -> KaseyaRmmAdapter:
    store = overrides.pop("store", None)
    values = {
        "allow_http_probing": True,
        "kaseya_rmm_base_url": "https://vsa.example.test/api/v3",
        "kaseya_rmm_token_id": "token-id",
        "kaseya_rmm_token_secret": "token-secret",
        "kaseya_rmm_organization_map_json": json.dumps({"acme": 101}),
        **overrides,
    }
    return KaseyaRmmAdapter(
        replace(settings, **values),
        store=store,
        transport=httpx.MockTransport(handler),
    )


def test_kaseya_calls_are_blocked_by_default(settings) -> None:
    active = replace(
        settings,
        kaseya_rmm_base_url="https://vsa.example.test/api/v3",
        kaseya_rmm_token_id="token-id",
        kaseya_rmm_token_secret="token-secret",
        kaseya_rmm_organization_map_json='{"acme":101}',
    )

    with pytest.raises(KaseyaRmmError, match="WAIT_ALLOW_HTTP_PROBING"):
        KaseyaRmmAdapter(active).list_devices("acme")


def test_kaseya_is_selected_and_reported_without_exposing_credentials(settings) -> None:
    active = replace(
        settings,
        allow_http_probing=True,
        kaseya_rmm_base_url="https://vsa.example.test/api/v3",
        kaseya_rmm_token_id="token-id",
        kaseya_rmm_token_secret="token-secret",
        kaseya_rmm_organization_map_json='{"acme":101}',
    )

    provider = rmm_provider_from_settings(active, Store(active.data_path))
    status = next(item for item in list_connector_statuses(active) if item.id == "rmm")
    secret_keys = {item.key for item in list_secret_records(active)}

    assert provider.adapter_id == "kaseya-vsa-x"
    assert status.name == "Kaseya VSA X"
    assert status.status == "configured"
    assert status.tier == "appliance-wide"
    assert "token-secret" not in status.message
    assert "WAIT_KASEYA_RMM_TOKEN_SECRET" in secret_keys


def test_kaseya_inventory_and_notifications_are_organization_scoped(settings) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path.endswith("/devices"):
            return httpx.Response(
                200,
                json={
                    "Data": [
                        {
                            "Identifier": "11111111-2222-3333-4444-555555555555",
                            "Name": "Acme laptop",
                            "OrganizationId": 101,
                            "SiteName": "Acme site",
                            "IsAgentInstalled": True,
                        },
                        {
                            "Identifier": "other-device",
                            "Name": "Other laptop",
                            "OrganizationId": 202,
                        },
                        {"Name": "Missing identifier", "OrganizationId": 101},
                    ]
                },
            )
        if request.url.path.endswith("/notifications"):
            return httpx.Response(
                200,
                json={
                    "Data": [
                        {"Id": 2733, "Message": "Disk space low", "Priority": "elevated"},
                        {"Message": "Missing ID", "Priority": "critical"},
                    ]
                },
            )
        raise AssertionError(request.url)

    adapter = _adapter(settings, handler, kaseya_rmm_page_size=500)
    devices = adapter.list_devices("acme")
    alerts = adapter.list_alerts("acme")

    assert [device.device_id for device in devices] == ["11111111-2222-3333-4444-555555555555"]
    assert [alert.alert_id for alert in alerts] == ["2733"]
    assert alerts[0].device_id == devices[0].device_id
    assert all(request.headers["authorization"].startswith("Basic ") for request in seen)
    assert all(request.url.params["$top"] == "100" for request in seen)
    assert all("token-secret" not in str(request) for request in seen)


def test_kaseya_alert_reads_are_bounded(settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/devices"):
            return httpx.Response(
                200,
                json={"Data": [{"Identifier": "device-1", "OrganizationId": 101}]},
            )
        return httpx.Response(
            200,
            json={
                "Data": [
                    {"Id": 1, "Message": "one"},
                    {"Id": 2, "Message": "two"},
                ]
            },
        )

    assert len(_adapter(settings, handler, kaseya_rmm_page_size=1).list_alerts("acme")) == 1


def test_kaseya_script_catalog_preview_execution_and_polling(settings) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path.endswith("/devices"):
            return httpx.Response(
                200,
                json={"Data": [{"Identifier": "device-1", "OrganizationId": 101}]},
            )
        if request.url.path.endswith("/automation/scripts"):
            return httpx.Response(
                200,
                json={
                    "Data": [
                        {"Id": "script-1", "Name": "Collect logs", "Description": "Bounded"},
                        {"Name": "Missing ID"},
                    ]
                },
            )
        if request.url.path.endswith("/automation/scripts/script-1"):
            return httpx.Response(
                200,
                json={
                    "Data": {
                        "Id": "script-1",
                        "Name": "Collect logs",
                        "InputVariables": [{"Id": 7, "Name": "days", "VariableType": "Number"}],
                    }
                },
            )
        if request.url.path.endswith("/automation/scripts/script-1/run"):
            assert request.method == "POST"
            assert json.loads(request.content) == {
                "DeviceIdentifier": "device-1",
                "Variables": [{"Id": 7, "Value": "7"}],
            }
            return httpx.Response(200, json={"Data": {"ExecutionId": "exec-1"}})
        if request.url.path.endswith("/automation/scripts/script-1/device/device-1/executions/exec-1"):
            return httpx.Response(200, json={"Data": {"Id": "exec-1", "State": "Successful"}})
        raise AssertionError(request.url)

    store = Store(settings.data_path)
    adapter = _adapter(
        replace(settings, allow_write_actions=True),
        handler,
        store=store,
    )

    scripts = adapter.list_scripts("acme")
    assert scripts[0].script_id == "script-1"
    assert len(scripts) == 1
    preview = adapter.preview_script("script-1", "device-1", {"7": "7"}, client_id="acme")
    assert preview.status == "preview"
    execution = adapter.execute_script("script-1", "device-1", {"7": "7"}, client_id="acme")
    assert execution.status == "queued"
    assert execution.execution_id == "exec-1"
    tracked = adapter.get_execution("exec-1", client_id="acme")
    assert tracked.status == "succeeded"
    assert tracked.script_id == "script-1"
    assert tracked.device_id == "device-1"
    assert all("token-secret" not in str(request) for request in seen)


def test_kaseya_script_execution_requires_write_flag(settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/devices"):
            return httpx.Response(
                200,
                json={"Data": [{"Identifier": "device-1", "OrganizationId": 101}]},
            )
        if request.url.path.endswith("/automation/scripts/script-1"):
            return httpx.Response(
                200,
                json={"Data": {"Id": "script-1", "InputVariables": []}},
            )
        raise AssertionError(request.url)

    result = _adapter(
        settings,
        handler,
    ).execute_script("script-1", "device-1", {}, client_id="acme")
    assert result.status == "blocked"
    assert "WAIT_ALLOW_WRITE_ACTIONS" in result.message


@pytest.mark.parametrize("arguments", [{"days": "7"}, {"8": "7"}])
def test_kaseya_rejects_non_numeric_or_unknown_script_variables(settings, arguments) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/devices"):
            return httpx.Response(
                200,
                json={"Data": [{"Identifier": "device-1", "OrganizationId": 101}]},
            )
        return httpx.Response(
            200,
            json={"Data": {"Id": "script-1", "InputVariables": [{"Id": 7}]}},
        )

    with pytest.raises(KaseyaRmmError, match="variable"):
        _adapter(settings, handler).preview_script("script-1", "device-1", arguments, client_id="acme")


def test_kaseya_rejects_out_of_scope_devices_and_malformed_script_details(settings) -> None:
    def device_only(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"Data": [{"Identifier": "device-1", "OrganizationId": 101}]},
        )

    with pytest.raises(KaseyaRmmError, match="outside the tenant scope"):
        _adapter(settings, device_only).preview_script("script-1", "device-2", {}, client_id="acme")

    def wrong_script(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/devices"):
            return device_only(request)
        return httpx.Response(200, json={"Data": {"Id": "other-script", "InputVariables": []}})

    with pytest.raises(KaseyaRmmError, match="script was not found"):
        _adapter(settings, wrong_script).preview_script("script-1", "device-1", {}, client_id="acme")

    def missing_variables(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/devices"):
            return device_only(request)
        return httpx.Response(200, json={"Data": {"Id": "script-1"}})

    with pytest.raises(KaseyaRmmError, match="malformed"):
        _adapter(settings, missing_variables).preview_script("script-1", "device-1", {}, client_id="acme")


def test_kaseya_rejects_argument_bounds_and_malformed_execution_responses(settings) -> None:
    def valid_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/devices"):
            return httpx.Response(
                200,
                json={"Data": [{"Identifier": "device-1", "OrganizationId": 101}]},
            )
        if request.url.path.endswith("/automation/scripts/script-1"):
            return httpx.Response(200, json={"Data": {"Id": "script-1", "InputVariables": []}})
        return httpx.Response(200, json={"Data": {}})

    with pytest.raises(KaseyaRmmError, match="exceed 20"):
        _adapter(settings, valid_handler).preview_script(
            "script-1", "device-1", {str(index): "v" for index in range(21)}, client_id="acme"
        )
    with pytest.raises(KaseyaRmmError, match="at most 500"):
        _adapter(settings, valid_handler).preview_script("script-1", "device-1", {"1": "x" * 501}, client_id="acme")

    def malformed_run(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/devices"):
            return httpx.Response(
                200,
                json={"Data": [{"Identifier": "device-1", "OrganizationId": 101}]},
            )
        if request.url.path.endswith("/automation/scripts/script-1"):
            return httpx.Response(200, json={"Data": {"Id": "script-1", "InputVariables": []}})
        return httpx.Response(200, json={"Data": {}})

    with pytest.raises(KaseyaRmmError, match="response was malformed"):
        _adapter(
            replace(settings, allow_write_actions=True),
            malformed_run,
            store=Store(settings.data_path),
        ).execute_script("script-1", "device-1", {}, client_id="acme")


def test_kaseya_execution_scope_and_provider_states_are_safe(settings) -> None:
    adapter = _adapter(settings, lambda request: httpx.Response(200, json={"Data": {}}))
    with pytest.raises(KaseyaRmmError, match="local execution scope"):
        adapter.get_execution("exec-1", client_id="acme")

    store = Store(settings.data_path)
    store.record_rmm_execution_scope("exec-1", "kaseya-vsa-x", "script-1", "device-1", "acme")

    def response_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/devices"):
            return httpx.Response(
                200,
                json={"Data": [{"Identifier": "device-1", "OrganizationId": 101}]},
            )
        if request.url.path.endswith("/executions/exec-1"):
            return httpx.Response(200, json={"Data": {"Id": "other", "State": "Running"}})
        raise AssertionError(request.url)

    with pytest.raises(KaseyaRmmError, match="outside the requested scope"):
        _adapter(settings, response_handler, store=store).get_execution("exec-1", client_id="acme")

    def running_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/devices"):
            return httpx.Response(
                200,
                json={"Data": [{"Identifier": "device-1", "OrganizationId": 101}]},
            )
        return httpx.Response(200, json={"Data": {"Id": "exec-1", "State": "Running"}})

    running = _adapter(settings, running_handler, store=store).get_execution("exec-1", client_id="acme")
    assert running.status == "queued"

    def unknown_state_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/devices"):
            return httpx.Response(
                200,
                json={"Data": [{"Identifier": "device-1", "OrganizationId": 101}]},
            )
        return httpx.Response(200, json={"Data": {"Id": "exec-1", "State": "Unknown"}})

    with pytest.raises(KaseyaRmmError, match="malformed"):
        _adapter(settings, unknown_state_handler, store=store).get_execution("exec-1", client_id="acme")


def test_kaseya_variable_id_upper_bound_is_rejected() -> None:
    with pytest.raises(KaseyaRmmError, match="32-bit"):
        _variable_id(str(2_147_483_648))


@pytest.mark.parametrize(
    ("method", "value", "message"),
    [
        ("list_devices", None, "explicit tenant scope"),
        ("list_devices", "other", "mapping is missing"),
    ],
)
def test_kaseya_requires_explicit_tenant_mapping(settings, method, value, message) -> None:
    adapter = _adapter(settings, lambda request: httpx.Response(200, json={"Data": []}))
    with pytest.raises(KaseyaRmmError, match=message):
        getattr(adapter, method)(value)


def test_kaseya_http_errors_and_unsafe_urls_are_sanitized(settings) -> None:
    adapter = _adapter(
        settings,
        lambda request: httpx.Response(401, text="token-secret should not leak"),
    )
    with pytest.raises(KaseyaRmmError, match="unauthorized") as error:
        adapter.list_devices("acme")
    assert "token-secret" not in str(error.value)
    with pytest.raises(KaseyaRmmError, match="HTTP 500"):
        _adapter(
            settings,
            lambda request: httpx.Response(500, text="secret"),
        ).list_devices("acme")
    with pytest.raises(KaseyaRmmError, match="request failed$"):
        _adapter(
            settings,
            lambda request: (_ for _ in ()).throw(httpx.ReadError("broken")),
        ).list_devices("acme")

    with pytest.raises(KaseyaRmmError, match=r"HTTP\(S\)"):
        _adapter(settings, lambda request: httpx.Response(200), kaseya_rmm_base_url="ftp://vsa.test").list_devices(
            "acme"
        )
    with pytest.raises(KaseyaRmmError, match="query data"):
        _adapter(
            settings, lambda request: httpx.Response(200), kaseya_rmm_base_url="https://vsa.test/api?secret=bad"
        ).list_devices("acme")
    with pytest.raises(KaseyaRmmError, match="unsafe characters"):
        _safe_endpoint("devices/device id")
    with pytest.raises(KaseyaRmmError, match="invalid"):
        _safe_endpoint("")
    with pytest.raises(KaseyaRmmError, match=r"HTTP\(S\)"):
        _safe_base_url("file:///tmp/vsa")
    assert _rows("not-a-response") == []
    assert _rows({"Data": "not-a-list"}) == []
    assert _int_value({}) is None
    assert _int_value("not-an-int") is None
    with pytest.raises(KaseyaRmmError, match="invalid"):
        _path_segment("device id")
    assert _safe_attribute(["not", "scalar"]) is None


def test_kaseya_missing_credentials_malformed_response_and_transport_failures(settings) -> None:
    missing_base = replace(
        settings,
        allow_http_probing=True,
        kaseya_rmm_token_id="token-id",
        kaseya_rmm_token_secret="token-secret",
        kaseya_rmm_organization_map_json='{"acme":101}',
    )
    with pytest.raises(KaseyaRmmError, match="WAIT_KASEYA_RMM_BASE_URL"):
        KaseyaRmmAdapter(missing_base).list_devices("acme")
    missing_token = replace(
        settings,
        allow_http_probing=True,
        kaseya_rmm_base_url="https://vsa.example.test/api/v3",
        kaseya_rmm_organization_map_json='{"acme":101}',
    )
    with pytest.raises(KaseyaRmmError, match="TOKEN_ID"):
        KaseyaRmmAdapter(missing_token).list_devices("acme")

    malformed = _adapter(
        settings,
        lambda request: httpx.Response(200, text="not-json"),
    )
    with pytest.raises(KaseyaRmmError, match="malformed JSON"):
        malformed.list_devices("acme")
    timeout = _adapter(
        settings,
        lambda request: (_ for _ in ()).throw(httpx.TimeoutException("offline")),
    )
    with pytest.raises(KaseyaRmmError, match="before receiving"):
        timeout.list_devices("acme")


@pytest.mark.parametrize(
    ("mapping", "message"),
    [
        ("not-json", "is malformed"),
        ("[]", "must be an object"),
        ('{"acme":true}', "mapping is missing"),
        ('{"acme":"not-an-int"}', "IDs must be integers"),
        ('{"acme":0}', "must be positive"),
    ],
)
def test_kaseya_rejects_invalid_organization_maps(settings, mapping, message) -> None:
    adapter = _adapter(
        settings,
        lambda request: httpx.Response(200, json={"Data": []}),
        kaseya_rmm_organization_map_json=mapping,
    )
    with pytest.raises(KaseyaRmmError, match=message):
        adapter.list_devices("acme")
