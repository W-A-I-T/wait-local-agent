from __future__ import annotations

import json
from dataclasses import replace

import httpx
import pytest

from wait_local_agent.connectors import list_connector_statuses, list_secret_records, validate_connector_credentials
from wait_local_agent.models import ConnectorReadResult
from wait_local_agent.smart_actions import SmartActionService
from wait_local_agent.store import Store
from wait_local_agent.timezest import (
    TimeZestClient,
    TimeZestReadError,
    TimeZestSchedulingResponse,
    _bounded_limit,
    _endpoint_url,
    _normalize_entities,
    _normalize_request,
    _optional_int,
    _safe_client_id,
)

REQUESTS_JSON = {
    "object": "list",
    "next_page": "https://api.timezest.com/v1/scheduling_requests?starting_after=sreq_next",
    "previous_page": None,
    "data": [
        {
            "id": "sreq_matching",
            "appointment_type_id": "apty_remote",
            "status": "scheduled",
            "duration_mins": 60,
            "end_user_name": "Rodney Smith",
            "end_user_email": "rodney@example.test",
            "scheduled_at": 1691931421,
            "selected_start_time": 1692363445,
            "selected_time_zone": "Pacific Time (US & Canada)",
            "created_at": 1691585916,
            "updated_at": 1691931421,
            "scheduling_url": "https://example.timezest.com/schedule/private",
            "associated_entities": [
                {"type": "connectwise_psa/company", "id": 209116},
                {"type": "connectwise_psa/service_ticket", "id": 1234, "number": "#1234"},
            ],
            "resources": [{"type": "agent", "id": "agnt_1", "name": "Samantha Jones"}],
        },
        {
            "id": "sreq_other_tenant",
            "status": "new",
            "associated_entities": [{"type": "connectwise_psa/company", "id": 999}],
        },
        "malformed row",
    ],
}


def _client(settings, handler, **overrides) -> TimeZestClient:
    values = {
        "allow_http_probing": True,
        "timezest_base_url": "https://api.timezest.com",
        "timezest_api_key": "timezest-secret-token",
        "timezest_client_map_json": json.dumps(
            {"acme": {"connectwise_psa_company_id": 209116}}
        ),
    }
    values.update(overrides)
    active = replace(settings, **values)
    return TimeZestClient(active, transport=httpx.MockTransport(handler))


def test_timezest_reads_are_filtered_and_bounded_by_documented_company_scope(settings) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        assert request.url.path == "/v1/scheduling_requests"
        assert request.headers["authorization"] == "Bearer timezest-secret-token"
        assert request.url.params["filter"] == (
            "scheduling_request.connectwise_psa_company_id EQ 209116"
        )
        return httpx.Response(200, json=REQUESTS_JSON)

    client = _client(settings, handler)
    response = client.list_scheduling_requests(client_id="acme", limit=20)

    assert response.result.status == "ready"
    assert [item.id for item in response.items] == ["sreq_matching"]
    assert response.items[0].has_scheduling_url is True
    assert response.items[0].associated_entities[0]["id"] == 209116
    assert response.items[0].resources[0]["name"] == "Samantha Jones"
    assert response.has_more is True
    assert len(seen) == 1


def test_timezest_health_and_smart_action_are_reachable(settings) -> None:
    client = _client(settings, lambda request: httpx.Response(200, json=REQUESTS_JSON))
    assert client.health().status == "ready"

    store = Store(settings.data_path)
    active = client.settings
    service = SmartActionService(store, active, timezest_client=client)
    result = service.invoke(
        "timezest-scheduling-request-lookup",
        {"client_id": "acme", "limit": 1},
        "tech",
        client_id="acme",
    )

    assert result.status == "success"
    assert result.output["count"] == 1
    assert result.output["has_more"] is True
    assert result.evidence[0]["operation"] == "scheduling_requests.list"
    assert "timezest-scheduling-request-lookup" in {item.action_id for item in service.list()}


def test_timezest_connector_status_validation_and_secrets(settings) -> None:
    client = _client(settings, lambda request: httpx.Response(200, json=REQUESTS_JSON))
    active = client.settings
    status = next(item for item in list_connector_statuses(active) if item.id == "timezest")
    secrets = {item.key for item in list_secret_records(active)}
    validation = validate_connector_credentials("timezest", active, timezest_client=client)

    assert status.status == "configured"
    assert status.kind == "marketplace"
    assert validation.passed is True
    assert {"WAIT_TIMEZEST_API_KEY", "WAIT_TIMEZEST_CLIENT_MAP_JSON"} <= secrets


@pytest.mark.parametrize(
    ("mapping", "message"),
    [
        ("", "at least one client mapping"),
        ("not-json", "malformed"),
        ("[]", "must be an object"),
        ('{"acme": {}}', "one supported company ID"),
        ('{"acme": {"halo_psa_client_id": 12}}', "unsupported company ID"),
        ('{"acme": {"connectwise_psa_company_id": "nope"}}', "positive integers"),
        ('{"acme": {"connectwise_psa_company_id": 0}}', "positive integers"),
        ('{"acme": {"connectwise_psa_company_id": true}}', "unsupported company ID"),
    ],
)
def test_timezest_requires_explicit_supported_mapping(settings, mapping, message) -> None:
    client = _client(
        settings,
        lambda request: httpx.Response(200, json=REQUESTS_JSON),
        timezest_client_map_json=mapping,
    )

    response = client.list_scheduling_requests(client_id="acme")

    expected_status = "not_configured" if mapping == "" else "failed"
    assert response.result.status == expected_status
    if mapping:
        assert message in response.result.message


def test_timezest_blocks_missing_scope_and_network(settings) -> None:
    blocked = _client(
        settings,
        lambda request: httpx.Response(200, json=REQUESTS_JSON),
        allow_http_probing=False,
    )
    assert blocked.list_scheduling_requests(client_id="acme").result.status == "blocked"
    assert blocked.health().status == "blocked"

    client = _client(settings, lambda request: httpx.Response(200, json=REQUESTS_JSON))
    missing_scope = client.list_scheduling_requests(client_id="other")
    assert missing_scope.result.status == "failed"
    assert "tenant scope" in missing_scope.result.message


@pytest.mark.parametrize(
    ("status_code", "message"),
    [(401, "unauthorized"), (403, "unauthorized"), (429, "rate limited"), (500, "HTTP 500")],
)
def test_timezest_handles_provider_errors(settings, status_code, message) -> None:
    client = _client(settings, lambda request: httpx.Response(status_code, text="timezest-secret-token"))

    response = client.list_scheduling_requests(client_id="acme")

    assert response.result.status == "failed"
    assert message in response.result.message
    assert "timezest-secret-token" not in response.result.message


def test_timezest_handles_transport_malformed_and_invalid_response(settings) -> None:
    def transport_error(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection failed", request=request)

    transport_response = _client(settings, transport_error).list_scheduling_requests(client_id="acme")
    assert "before receiving" in transport_response.result.message

    malformed = _client(settings, lambda request: httpx.Response(200, text="not-json"))
    assert "malformed JSON" in malformed.list_scheduling_requests(client_id="acme").result.message

    invalid_object = _client(settings, lambda request: httpx.Response(200, json=[]))
    assert "malformed response object" in invalid_object.list_scheduling_requests(client_id="acme").result.message

    invalid_data = _client(settings, lambda request: httpx.Response(200, json={"data": {}}))
    assert "malformed scheduling-request data" in invalid_data.list_scheduling_requests(client_id="acme").result.message


def test_timezest_covers_internal_error_and_normalization_edges(settings, monkeypatch) -> None:
    client = _client(settings, lambda request: httpx.Response(200, json=REQUESTS_JSON))

    not_configured = TimeZestClient(replace(settings, allow_http_probing=True))
    assert not_configured.health().status == "not_configured"
    invalid_mapping = _client(
        settings,
        lambda request: httpx.Response(200, json=REQUESTS_JSON),
        timezest_client_map_json='{"acme": {}}',
    )
    assert invalid_mapping.health().status == "failed"
    empty_mapping = _client(
        settings,
        lambda request: httpx.Response(200, json=REQUESTS_JSON),
        timezest_client_map_json="{}",
    )
    assert empty_mapping.health().status == "failed"

    blocked = _client(settings, lambda request: httpx.Response(200, json=REQUESTS_JSON), allow_http_probing=False)
    with pytest.raises(TimeZestReadError, match="blocked"):
        blocked._get("v1/scheduling_requests")
    incomplete = TimeZestClient(replace(settings, allow_http_probing=True, timezest_api_key=""))
    with pytest.raises(TimeZestReadError, match="incomplete"):
        incomplete._get("v1/scheduling_requests")

    def generic_transport_error(request: httpx.Request) -> httpx.Response:
        raise httpx.WriteError("write failed", request=request)

    generic_error = _client(settings, generic_transport_error).list_scheduling_requests(client_id="acme")
    assert generic_error.result.message == "TimeZest request failed."

    monkeypatch.setattr(
        client,
        "_get",
        lambda endpoint, params=None: TimeZestSchedulingResponse(
            ConnectorReadResult("failed", "stub"), []
        ),
    )
    assert client.list_scheduling_requests(client_id="acme").result.message == "stub"
    monkeypatch.setattr(client, "_get", lambda endpoint, params=None: object())
    assert "malformed response object" in client.list_scheduling_requests(client_id="acme").result.message

    assert _normalize_request({"id": "", "associated_entities": []}, "connectwise_psa_company_id", 1) is None
    assert _normalize_entities("not-a-list") == []
    assert _normalize_entities([None, {"type": "", "id": "not-an-id"}]) == []
    assert _optional_int(None) is None
    with pytest.raises(TimeZestReadError, match="tenant scope"):
        _safe_client_id(None)  # type: ignore[arg-type]
    with pytest.raises(TimeZestReadError, match="tenant scope"):
        _safe_client_id("x" * 121)
    with pytest.raises(TimeZestReadError, match="between 1 and 20"):
        _bounded_limit(0)


def test_timezest_action_validates_tenant_payload_and_provider_result(settings) -> None:
    client = _client(settings, lambda request: httpx.Response(200, json=REQUESTS_JSON))
    service = SmartActionService(Store(client.settings.data_path), client.settings, timezest_client=client)

    cases: list[tuple[dict[str, object], str]] = [
        ({"client_id": "other"}, "outside the tenant scope"),
        ({"client_id": "acme", "limit": True}, "limit must be"),
        ({"client_id": ""}, "client_id must be"),
    ]
    for payload, expected in cases:
        result = service.invoke("timezest-scheduling-request-lookup", payload, "tech", client_id="acme")
        assert result.status == "failed"
        assert expected in result.error_detail

    failed = TimeZestSchedulingResponse(ConnectorReadResult("failed", "provider unavailable"), [])

    class FailedProvider:
        def health(self) -> ConnectorReadResult:
            return ConnectorReadResult("failed", "provider unavailable")

        def list_scheduling_requests(self, *, client_id: str, limit: int = 20):
            return failed

    result = SmartActionService(
        Store(client.settings.data_path),
        client.settings,
        timezest_client=FailedProvider(),
    ).invoke("timezest-scheduling-request-lookup", {"client_id": "acme"}, "tech", client_id="acme")
    assert result.status == "failed"
    assert result.output["requests"] == []


def test_timezest_rejects_unsafe_urls_and_limits(settings) -> None:
    with pytest.raises(TimeZestReadError, match="control characters"):
        _endpoint_url("https://api.timezest.com\n", "v1/scheduling_requests")
    with pytest.raises(TimeZestReadError, match=r"HTTP\(S\)"):
        _endpoint_url("ftp://api.timezest.com", "v1/scheduling_requests")
    with pytest.raises(TimeZestReadError, match="credentials or query"):
        _endpoint_url("https://user:pass@api.timezest.com?secret=1", "v1/scheduling_requests")
    with pytest.raises(TimeZestReadError, match="not supported"):
        _endpoint_url("https://api.timezest.com", "v1/agents")
