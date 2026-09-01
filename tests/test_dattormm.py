from __future__ import annotations

import json
from dataclasses import replace
from typing import cast

import httpx
import pytest

from wait_local_agent.connectors import list_connector_statuses, list_secret_records
from wait_local_agent.dattormm import (
    DattoRmmAdapter,
    DattoRmmError,
    _first_text,
    _rows,
    _safe_attribute,
    _safe_base_url,
    _safe_endpoint,
)
from wait_local_agent.rmm import rmm_provider_from_settings
from wait_local_agent.store import Store


def _adapter(settings, handler, **overrides) -> DattoRmmAdapter:
    values = {
        "allow_http_probing": True,
        "datto_rmm_base_url": "https://datto.example.test/api",
        "datto_rmm_access_token": "datto-secret-token",
        "datto_rmm_site_map_json": json.dumps({"acme": "site-42"}),
        **overrides,
    }
    active = replace(settings, **values)
    return DattoRmmAdapter(active, transport=httpx.MockTransport(handler))


def test_dattormm_calls_are_blocked_by_default(settings) -> None:
    active = replace(
        settings,
        datto_rmm_base_url="https://datto.example.test/api",
        datto_rmm_access_token="secret",
        datto_rmm_site_map_json='{"acme":"site-42"}',
    )

    with pytest.raises(DattoRmmError, match="WAIT_ALLOW_HTTP_PROBING"):
        DattoRmmAdapter(active).list_devices("acme")


def test_dattormm_is_selected_and_reported_without_exposing_credentials(settings) -> None:
    active = replace(
        settings,
        allow_http_probing=True,
        datto_rmm_base_url="https://datto.example.test/api",
        datto_rmm_access_token="datto-secret-token",
        datto_rmm_site_map_json='{"acme":"site-42"}',
    )

    provider = rmm_provider_from_settings(active, Store(active.data_path))
    rmm_status = next(item for item in list_connector_statuses(active) if item.id == "rmm")
    secret_keys = {item.key for item in list_secret_records(active)}

    assert provider.adapter_id == "dattormm"
    assert rmm_status.name == "Datto RMM"
    assert rmm_status.status == "configured"
    assert "datto-secret-token" not in rmm_status.message
    assert "WAIT_DATTORMM_ACCESS_TOKEN" in secret_keys


@pytest.mark.parametrize(
    ("mapping", "message"),
    [
        ("", "tenant site mapping is missing"),
        ("not-json", "is malformed"),
        ("[]", "must be an object"),
        ('{"acme": true}', "tenant site mapping is missing"),
    ],
)
def test_dattormm_requires_explicit_valid_site_map(settings, mapping, message) -> None:
    adapter = _adapter(settings, lambda request: httpx.Response(200, json=[]), datto_rmm_site_map_json=mapping)

    with pytest.raises(DattoRmmError, match=message):
        adapter.list_devices("acme")


def test_dattormm_inventory_is_site_scoped_and_bounded(settings) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path.endswith("/devices"):
            return httpx.Response(
                200,
                json={
                    "devices": [
                        {"uid": "device-1", "siteUid": "site-42", "hostname": "Acme laptop", "online": True},
                        {"uid": "device-2", "siteUid": "other-site", "hostname": "Other laptop"},
                        {"siteUid": "site-42"},
                    ]
                },
            )
        if request.url.path.endswith("/alerts/open"):
            return httpx.Response(
                200,
                json={
                    "alerts": [
                        {
                            "alertUid": "alert-1",
                            "deviceUid": "device-1",
                            "siteUid": "site-42",
                            "severity": "high",
                            "message": "Disk",
                        },
                        {
                            "alertUid": "alert-2",
                            "deviceUid": "device-2",
                            "siteUid": "other-site",
                            "message": "Other",
                        },
                    ]
                },
            )
        if request.url.path.endswith("/components"):
            return httpx.Response(200, json={"components": [{"uid": "component-1", "name": "Collect logs"}]})
        raise AssertionError(request.url)

    adapter = _adapter(settings, handler, datto_rmm_page_size=500)
    devices = adapter.list_devices("acme")
    alerts = adapter.list_alerts("acme")
    scripts = adapter.list_scripts("acme")

    assert [device.device_id for device in devices] == ["device-1"]
    assert [alert.alert_id for alert in alerts] == ["alert-1"]
    assert scripts[0].script_id == "component-1"
    assert all(request.headers["authorization"] == "Bearer datto-secret-token" for request in seen)
    assert all(request.url.params["max"] == "250" for request in seen)


def test_dattormm_preview_validates_device_and_component_without_writing(settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/devices"):
            return httpx.Response(200, json=[{"uid": "device-1", "siteUid": "site-42"}])
        return httpx.Response(200, json=[{"uid": "component-1", "name": "Collect logs"}])

    preview = _adapter(settings, handler).preview_script(
        "component-1", "device-1", {"days": "7"}, client_id="acme"
    )

    assert preview.status == "preview"
    assert "WAIT_ALLOW_WRITE_ACTIONS" in preview.message


def test_dattormm_preview_rejects_unknown_device_and_component(settings) -> None:
    def empty_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[])

    adapter = _adapter(settings, empty_handler)
    with pytest.raises(DattoRmmError, match="outside the tenant scope"):
        adapter.preview_script("component-1", "device-1", {}, client_id="acme")

    def known_device_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/devices"):
            return httpx.Response(200, json=[{"uid": "device-1", "siteUid": "site-42"}])
        return httpx.Response(200, json=[])

    with pytest.raises(DattoRmmError, match="component was not found"):
        _adapter(settings, known_device_handler).preview_script(
            "component-1", "device-1", {}, client_id="acme"
        )


def test_dattormm_alert_nested_device_and_invalid_rows_are_bounded(settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": {
                    "alerts": [
                        {
                            "alertUid": "nested",
                            "device": {"uid": "device-1"},
                            "siteUid": "site-42",
                        },
                        {"alertUid": "missing-device", "siteUid": "site-42"},
                        {"deviceUid": "missing-alert", "siteUid": "site-42"},
                    ]
                }
            },
        )

    alerts = _adapter(settings, handler).list_alerts("acme")
    assert [alert.alert_id for alert in alerts] == ["nested"]


def test_dattormm_missing_credentials_and_no_content_are_safe(settings) -> None:
    missing = replace(
        settings,
        allow_http_probing=True,
        datto_rmm_base_url="https://datto.example.test/api",
        datto_rmm_site_map_json='{"acme":"site-42"}',
    )
    with pytest.raises(DattoRmmError, match="credentials are incomplete"):
        DattoRmmAdapter(missing).list_devices("acme")

    no_content = _adapter(settings, lambda request: httpx.Response(204))
    assert no_content.list_devices("acme") == []


def test_dattormm_helpers_reject_unsafe_shapes_and_urls() -> None:
    assert _rows({"data": {"items": [{"id": 1}]}}, "data", "items") == [{"id": 1}]
    assert _rows("not-a-response") == []
    assert _first_text({"name": True, "id": 4}, "name", "id") == "4"
    assert _safe_attribute({"not": "scalar"}) is None
    with pytest.raises(DattoRmmError, match=r"HTTP\(S\)"):
        _safe_base_url("ftp://datto.example.test/api")
    with pytest.raises(DattoRmmError, match="query data"):
        _safe_base_url("https://datto.example.test/api?x=1")
    with pytest.raises(DattoRmmError, match="unsafe characters"):
        _safe_endpoint("v2/site/site 42/devices")


def test_dattormm_write_requires_flag_and_execution_lookup_is_live(settings) -> None:
    adapter = _adapter(settings, lambda request: httpx.Response(200, json={"status": "active"}))

    execution = adapter.execute_script("component-1", "device-1", {}, client_id="acme")
    lookup = adapter.get_execution("job-1", client_id="acme")

    assert execution.status == "blocked"
    assert lookup.status == "queued"
    assert "WAIT_ALLOW_WRITE_ACTIONS" in execution.message
    assert "active" in lookup.message


def test_dattormm_approved_quick_job_is_tenant_validated_and_bounded(settings) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path.endswith("/devices"):
            return httpx.Response(200, json=[{"uid": "device-1", "siteUid": "site-42"}])
        if request.url.path.endswith("/components"):
            return httpx.Response(200, json=[{"uid": "component-1", "name": "Collect logs"}])
        if request.url.path.endswith("/quickjob"):
            assert request.method == "PUT"
            assert str(request.url.params) == ""
            assert json.loads(request.read()) == {
                "jobName": "WAIT approved quick job",
                "jobComponent": {
                    "componentUid": "component-1",
                    "variables": [
                        {"name": "days", "value": "7"},
                        {"name": "scope", "value": "logs"},
                    ],
                },
            }
            return httpx.Response(200, json={"uid": "job-99"})
        raise AssertionError(request)

    adapter = _adapter(settings, handler, allow_write_actions=True)
    execution = adapter.execute_script(
        "component-1",
        "device-1",
        {"scope": "logs", "days": "7"},
        client_id="acme",
    )

    assert execution.status == "queued"
    assert execution.execution_id == "job-99"
    assert len(seen) == 3
    assert all(request.headers["authorization"] == "Bearer datto-secret-token" for request in seen)


@pytest.mark.parametrize(
    ("provider_status", "expected_status", "expected_message"),
    [
        ("active", "queued", "active"),
        ("completed", "completed", "does not expose component output"),
        ("failed", "failed", "failed"),
    ],
)
def test_dattormm_execution_lookup_maps_documented_job_states(
    settings, provider_status, expected_status, expected_message
) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        assert request.method == "GET"
        assert request.url.path.endswith("/v2/job/job-99")
        assert str(request.url.params) == ""
        return httpx.Response(200, json={"status": provider_status})

    execution = _adapter(settings, handler).get_execution("job-99", client_id="acme")

    assert execution.status == expected_status
    assert expected_message in execution.message
    assert len(seen) == 1


def test_dattormm_rejects_malformed_quick_job_responses(settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/devices"):
            return httpx.Response(200, json=[{"uid": "device-1", "siteUid": "site-42"}])
        if request.url.path.endswith("/components"):
            return httpx.Response(200, json=[{"uid": "component-1"}])
        return httpx.Response(200, json={"status": "accepted"})

    with pytest.raises(DattoRmmError, match="quick-job response was malformed"):
        _adapter(settings, handler, allow_write_actions=True).execute_script(
            "component-1", "device-1", {}, client_id="acme"
        )

    with pytest.raises(DattoRmmError, match="job response was malformed"):
        _adapter(
            settings,
            lambda request: httpx.Response(200, json={"status": "unknown"}),
        ).get_execution("job-99", client_id="acme")


def test_dattormm_status_lookup_requires_persisted_tenant_scope(settings) -> None:
    store = Store(settings.data_path)
    with pytest.raises(ValueError, match="requires a tenant"):
        store.record_rmm_execution_scope("job-0", "dattormm", "component-1", "device-1", "")
    assert store.get_rmm_execution_scope("job-0", "dattormm", "") is None

    active_settings = replace(
        settings,
        allow_http_probing=True,
        allow_write_actions=True,
        datto_rmm_base_url="https://datto.example.test/api",
        datto_rmm_access_token="datto-secret-token",
        datto_rmm_site_map_json=json.dumps({"acme": "site-42"}),
    )

    def write_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/devices"):
            return httpx.Response(200, json=[{"uid": "device-1", "siteUid": "site-42"}])
        if request.url.path.endswith("/components"):
            return httpx.Response(200, json=[{"uid": "component-1"}])
        return httpx.Response(200, json={"uid": "job-99"})

    active = DattoRmmAdapter(
        active_settings,
        transport=httpx.MockTransport(write_handler),
        store=store,
    )
    execution = active.execute_script("component-1", "device-1", {}, client_id="acme")
    assert execution.execution_id == "job-99"

    lookup = DattoRmmAdapter(
        active.settings,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"status": "completed"})
        ),
        store=store,
    ).get_execution("job-99", client_id="acme")
    assert lookup.status == "completed"
    assert lookup.script_id == "component-1"
    assert lookup.device_id == "device-1"

    with pytest.raises(DattoRmmError, match="outside the tenant scope"):
        DattoRmmAdapter(
            active.settings,
            transport=httpx.MockTransport(
                lambda request: (_ for _ in ()).throw(
                    AssertionError("network should not be used")
                )
            ),
            store=store,
        ).get_execution("unknown-job", client_id="acme")


@pytest.mark.parametrize("status", [401, 403, 500])
def test_dattormm_http_errors_are_sanitized(settings, status) -> None:
    adapter = _adapter(
        settings,
        lambda request: httpx.Response(status, text="datto-secret-token leaked"),
    )

    with pytest.raises(DattoRmmError) as error:
        adapter.list_devices("acme")

    assert "datto-secret-token" not in str(error.value)
    assert "unauthorized" in str(error.value) if status in {401, 403} else "HTTP 500" in str(error.value)


def test_dattormm_handles_timeout_malformed_json_and_unsafe_url(settings) -> None:
    timeout_adapter = _adapter(
        settings,
        lambda request: (_ for _ in ()).throw(httpx.ReadTimeout("timed out")),
    )
    with pytest.raises(DattoRmmError, match="before receiving"):
        timeout_adapter.list_devices("acme")

    malformed_adapter = _adapter(settings, lambda request: httpx.Response(200, text="not-json"))
    with pytest.raises(DattoRmmError, match="malformed JSON"):
        malformed_adapter.list_devices("acme")

    unsafe_adapter = _adapter(
        settings,
        lambda request: httpx.Response(200, json=[]),
        datto_rmm_base_url="https://user:pass@example.test/api",
    )
    with pytest.raises(DattoRmmError, match="must not contain credentials"):
        unsafe_adapter.list_devices("acme")


def test_dattormm_rejects_unscoped_and_invalid_requests(settings) -> None:
    adapter = _adapter(settings, lambda request: httpx.Response(200, json=[]))

    with pytest.raises(DattoRmmError, match="explicit tenant scope"):
        adapter.list_devices(None)
    with pytest.raises(DattoRmmError, match="script ID is invalid"):
        adapter.preview_script("", "device-1", {}, client_id="acme")
    with pytest.raises(DattoRmmError, match="arguments are too numerous"):
        adapter.preview_script("script-1", "device-1", {str(index): "x" for index in range(21)}, client_id="acme")
    with pytest.raises(DattoRmmError, match="argument values are invalid"):
        adapter.preview_script("script-1", "device-1", cast(dict[str, str], {"key": 7}), client_id="acme")
    with pytest.raises(DattoRmmError, match="unsafe characters"):
        _safe_endpoint("v2/site/site-42/devices?limit=1")
