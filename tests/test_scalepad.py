from __future__ import annotations

import json
from dataclasses import replace

import httpx
import pytest

from wait_local_agent.api.app import create_app
from wait_local_agent.connectors import list_connector_statuses, list_secret_records, validate_connector_credentials
from wait_local_agent.models import ConnectorReadResult
from wait_local_agent.scalepad import (
    ScalePadClient,
    ScalePadClientResponse,
    ScalePadReadError,
    _bounded_provider_id,
    _endpoint_url,
    _normalize_client,
    _optional_nonnegative_int,
    _optional_provider_id,
    _safe_client_id,
)
from wait_local_agent.smart_actions import SmartActionService
from wait_local_agent.store import Store

CLIENTS_JSON = {
    "data": [
        {
            "id": "sp-client-1",
            "name": "Acme Corporation",
            "lifecycle": "active",
            "num_contacts": 12,
            "num_hardware_assets": 48,
            "record_created_at": "2026-01-01T00:00:00Z",
            "record_updated_at": "2026-08-01T00:00:00Z",
        },
        {"id": "sp-other", "name": "Other Tenant"},
        "malformed row",
    ],
    "total_count": 1,
    "next_cursor": "cursor-next",
}


def _client(settings, handler, **overrides) -> ScalePadClient:
    values = {
        "allow_http_probing": True,
        "scalepad_base_url": "https://api.scalepad.com",
        "scalepad_api_key": "scalepad-secret-token",
        "scalepad_client_map_json": json.dumps({"acme": "sp-client-1"}),
    }
    values.update(overrides)
    active = replace(settings, **values)
    return ScalePadClient(active, transport=httpx.MockTransport(handler))


def test_scalepad_client_read_is_filtered_and_rechecked(settings) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        assert request.url.path == "/core/v1/clients"
        assert request.headers["x-api-key"] == "scalepad-secret-token"
        assert request.url.params["filter[id]"] == "eq:sp-client-1"
        assert request.url.params["page_size"] == "1"
        return httpx.Response(200, json=CLIENTS_JSON)

    response = _client(settings, handler).get_client(client_id="acme")

    assert response.result.status == "ready"
    assert [item.id for item in response.items] == ["sp-client-1"]
    assert response.items[0].num_hardware_assets == 48
    assert response.next_cursor == "cursor-next"
    assert len(seen) == 1


def test_scalepad_health_action_and_connector_surfaces(settings) -> None:
    client = _client(settings, lambda request: httpx.Response(200, json=CLIENTS_JSON))
    assert client.health().status == "ready"
    assert _client(
        settings,
        lambda request: httpx.Response(200, json=CLIENTS_JSON),
        scalepad_client_map_json="{}",
    ).health().status == "failed"
    status = next(item for item in list_connector_statuses(client.settings) if item.id == "scalepad")
    validation = validate_connector_credentials("scalepad", client.settings, scalepad_client=client)
    secret_keys = {item.key for item in list_secret_records(client.settings)}

    service = SmartActionService(Store(client.settings.data_path), client.settings, scalepad_client=client)
    result = service.invoke(
        "scalepad-client-lookup",
        {"client_id": "acme"},
        "tech",
        client_id="acme",
    )

    assert status.status == "configured"
    assert validation.passed is True
    assert {"WAIT_SCALEPAD_API_KEY", "WAIT_SCALEPAD_CLIENT_MAP_JSON"} <= secret_keys
    assert result.status == "success"
    assert result.output["count"] == 1
    assert result.evidence[0]["operation"] == "clients.get"


def test_scalepad_api_routes_are_reachable_and_tenant_scoped(settings) -> None:
    active = replace(settings, allow_http_probing=True)
    routes = {getattr(route, "path", "") for route in create_app(active).routes}
    assert "/connectors/scalepad/health" in routes
    assert "/connectors/scalepad/clients" in routes


@pytest.mark.parametrize(
    ("mapping", "expected"),
    [
        ("", "not_configured"),
        ("not-json", "malformed"),
        ("[]", "must be an object"),
        ('{"acme": ""}', "non-empty strings"),
        ('{"acme": 123}', "non-empty strings"),
    ],
)
def test_scalepad_requires_explicit_client_mapping(settings, mapping, expected) -> None:
    client = _client(
        settings,
        lambda request: httpx.Response(200, json=CLIENTS_JSON),
        scalepad_client_map_json=mapping,
    )
    response = client.get_client(client_id="acme")
    assert response.result.status == ("not_configured" if mapping == "" else "failed")
    assert expected in response.result.status or expected in response.result.message


def test_scalepad_blocks_missing_scope_and_http(settings) -> None:
    blocked = _client(
        settings,
        lambda request: httpx.Response(200, json=CLIENTS_JSON),
        allow_http_probing=False,
    )
    assert blocked.health().status == "blocked"
    assert blocked.get_client(client_id="acme").result.status == "blocked"
    assert blocked.get_client(client_id="other").result.status == "blocked"

    client = _client(settings, lambda request: httpx.Response(200, json=CLIENTS_JSON))
    outside = client.get_client(client_id="other")
    assert outside.result.status == "failed"
    assert "tenant scope" in outside.result.message

    missing = ScalePadClient(replace(settings, allow_http_probing=True))
    assert missing.health().status == "not_configured"
    with pytest.raises(ScalePadReadError, match="blocked"):
        blocked._get("core/v1/clients")
    with pytest.raises(ScalePadReadError, match="incomplete"):
        missing._get("core/v1/clients")


@pytest.mark.parametrize(
    ("status_code", "message"),
    [
        (401, "unauthorized"),
        (403, "unauthorized"),
        (402, "subscription"),
        (429, "rate limited"),
        (500, "HTTP 500"),
    ],
)
def test_scalepad_handles_provider_errors(settings, status_code, message) -> None:
    client = _client(settings, lambda request: httpx.Response(status_code, text="scalepad-secret-token"))
    response = client.get_client(client_id="acme")
    assert response.result.status == "failed"
    assert message in response.result.message
    assert "scalepad-secret-token" not in response.result.message


def test_scalepad_handles_malformed_transport_and_action_scope(settings) -> None:
    malformed_json = _client(settings, lambda request: httpx.Response(200, text="not-json"))
    assert "malformed JSON" in malformed_json.get_client(client_id="acme").result.message

    invalid_data = _client(settings, lambda request: httpx.Response(200, json={"data": {}}))
    assert "malformed client data" in invalid_data.get_client(client_id="acme").result.message

    invalid_object = _client(settings, lambda request: httpx.Response(200, json=[]))
    assert "malformed response object" in invalid_object.get_client(client_id="acme").result.message

    def transport_error(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection failed", request=request)

    failed_transport = _client(settings, transport_error)
    assert "before receiving" in failed_transport.get_client(client_id="acme").result.message

    def generic_transport_error(request: httpx.Request) -> httpx.Response:
        raise httpx.WriteError("write failed", request=request)

    generic = _client(settings, generic_transport_error)
    assert generic.get_client(client_id="acme").result.message == "ScalePad request failed."

    client = _client(settings, lambda request: httpx.Response(200, json=CLIENTS_JSON))
    service = SmartActionService(Store(client.settings.data_path), client.settings, scalepad_client=client)
    outside = service.invoke(
        "scalepad-client-lookup",
        {"client_id": "other"},
        "tech",
        client_id="acme",
    )
    assert outside.status == "failed"
    assert "tenant scope" in outside.error_detail


def test_scalepad_unsafe_urls_and_normalizers(settings) -> None:
    with pytest.raises(ScalePadReadError, match="HTTPS"):
        _endpoint_url("http://api.scalepad.com", "core/v1/clients")
    with pytest.raises(ScalePadReadError, match="credentials"):
        _endpoint_url("https://user:pass@api.scalepad.com", "core/v1/clients")
    with pytest.raises(ScalePadReadError, match="not supported"):
        _endpoint_url("https://api.scalepad.com", "core/v1/other")
    with pytest.raises(ScalePadReadError, match="tenant scope"):
        _safe_client_id(None)  # type: ignore[arg-type]
    with pytest.raises(ScalePadReadError, match="tenant scope"):
        _safe_client_id("")
    with pytest.raises(ScalePadReadError, match="tenant scope"):
        _safe_client_id("x" * 121)
    with pytest.raises(ScalePadReadError, match="non-empty strings"):
        _client(
            settings,
            lambda request: httpx.Response(200, json=CLIENTS_JSON),
            scalepad_client_map_json='{"acme": 1}',
        )._client_mapping("acme")
    with pytest.raises(ScalePadReadError, match="bounded strings"):
        _client(
            settings,
            lambda request: httpx.Response(200, json=CLIENTS_JSON),
            scalepad_client_map_json='{"acme": "' + ("x" * 201) + '"}',
        )._client_mapping("acme")
    with pytest.raises(ScalePadReadError, match="control characters"):
        _client(
            settings,
            lambda request: httpx.Response(200, json=CLIENTS_JSON),
            scalepad_client_map_json='{"acme": "bad\\nvalue"}',
        )._client_mapping("acme")
    with pytest.raises(ScalePadReadError, match="non-empty strings"):
        _bounded_provider_id(1)
    with pytest.raises(ScalePadReadError, match="bounded strings"):
        _bounded_provider_id("")
    with pytest.raises(ScalePadReadError, match="control characters"):
        _bounded_provider_id("bad\nvalue")
    with pytest.raises(ScalePadReadError, match="invalid"):
        _endpoint_url("https://" + ("x" * 250), "core/v1/clients")
    with pytest.raises(ScalePadReadError, match="invalid"):
        _endpoint_url("https://api.scalepad.com\n", "core/v1/clients")
    assert _normalize_client(None, "sp-client-1") is None
    assert _normalize_client({"name": "missing id"}, "sp-client-1") is None
    assert _optional_nonnegative_int(None) is None
    assert _optional_nonnegative_int("") is None
    assert _optional_nonnegative_int("not-an-int") is None
    assert _optional_nonnegative_int(-1) is None
    assert _optional_provider_id(None) == ""
    assert _normalize_client({"id": "wrong"}, "sp-client-1") is None


class _FailedScalePadProvider:
    def health(self) -> ConnectorReadResult:
        return ConnectorReadResult("failed", "provider unavailable")

    def get_client(self, *, client_id: str) -> ScalePadClientResponse:
        return ScalePadClientResponse(ConnectorReadResult("failed", "provider unavailable"), [])
