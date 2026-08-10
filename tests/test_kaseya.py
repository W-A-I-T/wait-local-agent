from __future__ import annotations

import json
from dataclasses import replace

import httpx
import pytest

from wait_local_agent.connectors import list_connector_statuses, list_secret_records
from wait_local_agent.kaseya import (
    KaseyaRmmAdapter,
    KaseyaRmmError,
    _safe_base_url,
    _safe_endpoint,
)
from wait_local_agent.rmm import rmm_provider_from_settings
from wait_local_agent.store import Store


def _adapter(settings, handler, **overrides) -> KaseyaRmmAdapter:
    values = {
        "allow_http_probing": True,
        "kaseya_rmm_base_url": "https://vsa.example.test/api/v3",
        "kaseya_rmm_token_id": "token-id",
        "kaseya_rmm_token_secret": "token-secret",
        "kaseya_rmm_organization_map_json": json.dumps({"acme": 101}),
        **overrides,
    }
    return KaseyaRmmAdapter(replace(settings, **values), transport=httpx.MockTransport(handler))


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

    assert [device.device_id for device in devices] == [
        "11111111-2222-3333-4444-555555555555"
    ]
    assert [alert.alert_id for alert in alerts] == ["2733"]
    assert alerts[0].device_id == devices[0].device_id
    assert all(request.headers["authorization"].startswith("Basic ") for request in seen)
    assert all(request.url.params["$top"] == "100" for request in seen)
    assert all("token-secret" not in str(request) for request in seen)


def test_kaseya_script_operations_are_explicitly_unavailable(settings) -> None:
    adapter = _adapter(settings, lambda request: httpx.Response(200, json={"Data": []}))

    with pytest.raises(KaseyaRmmError, match="script catalog"):
        adapter.list_scripts("acme")
    with pytest.raises(KaseyaRmmError, match="script execution"):
        adapter.preview_script("script", "device", {}, client_id="acme")


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

    with pytest.raises(KaseyaRmmError, match=r"HTTP\(S\)"):
        _adapter(settings, lambda request: httpx.Response(200), kaseya_rmm_base_url="ftp://vsa.test").list_devices("acme")
    with pytest.raises(KaseyaRmmError, match="query data"):
        _adapter(settings, lambda request: httpx.Response(200), kaseya_rmm_base_url="https://vsa.test/api?secret=bad").list_devices("acme")
    with pytest.raises(KaseyaRmmError, match="unsafe characters"):
        _safe_endpoint("devices/device id")
    with pytest.raises(KaseyaRmmError, match=r"HTTP\(S\)"):
        _safe_base_url("file:///tmp/vsa")
