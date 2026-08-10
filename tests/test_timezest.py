from __future__ import annotations

import json
from dataclasses import replace
from typing import Any, cast

import httpx
import pytest

import wait_local_agent.timezest as timezest_module
from wait_local_agent.connectors import list_connector_statuses, list_secret_records, validate_connector_credentials
from wait_local_agent.models import ConnectorReadResult
from wait_local_agent.rbac import Role
from wait_local_agent.smart_actions import SmartActionService
from wait_local_agent.store import Store
from wait_local_agent.timezest import (
    TimeZestClient,
    TimeZestReadError,
    TimeZestSchedulingCreateResponse,
    TimeZestSchedulingResponse,
    _bounded_limit,
    _endpoint_url,
    _normalize_entities,
    _normalize_request,
    _optional_int,
    _safe_client_id,
    _safe_scheduling_url,
    _validate_create_fields,
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

CREATE_JSON = {
    "object": "scheduling_request",
    "id": "sreq_created",
    "appointment_type_id": "apty_remote",
    "duration_mins": 60,
    "earliest_date": "2025-05-01",
    "earliest_time": "10:00:00",
    "latest_date": "2025-05-31",
    "latest_time": "16:30:00",
    "status": "new",
    "scheduling_url": "https://example.timezest.com/schedule/created",
    "associated_entities": [{"type": "connectwise_psa/company", "id": 209116}],
    "resources": [{"type": "agent", "id": "agnt_1", "name": "Samantha Jones"}],
    "created_at": 1691585916,
    "updated_at": 1691585916,
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


def _write_client(settings, handler, **overrides) -> TimeZestClient:
    return _client(settings, handler, allow_write_actions=True, **overrides)


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


def test_timezest_create_posts_only_documented_scoped_fields(settings) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        assert request.method == "POST"
        assert request.url.path == "/v1/scheduling_requests"
        assert request.headers["authorization"] == "Bearer timezest-secret-token"
        assert request.read()
        assert json.loads(request.content) == {
            "appointment_type_id": "apty_remote",
            "trigger_mode": "pod",
            "associated_entities": [{"type": "connectwise_psa/company", "id": 209116}],
            "resource_ids": ["agnt_1", "team_1"],
            "duration_mins": 60,
            "earliest_date": "2025-05-01",
            "earliest_time": "10:00:00",
            "latest_date": "2025-05-31",
            "latest_time": "16:30:00",
            "end_user_name": "Rodney Smith",
            "end_user_email": "rodney@example.test",
            "end_user_company": "Acme",
        }
        return httpx.Response(201, json=CREATE_JSON)

    response = _write_client(settings, handler).create_scheduling_request(
        client_id="acme",
        appointment_type_id="apty_remote",
        trigger_mode="pod",
        resource_ids=["agnt_1", "team_1"],
        duration_mins=60,
        earliest_date="2025-05-01",
        earliest_time="10:00:00",
        latest_date="2025-05-31",
        latest_time="16:30:00",
        end_user_name="Rodney Smith",
        end_user_email="rodney@example.test",
        end_user_company="Acme",
    )

    assert response.result.status == "ready"
    assert response.request["id"] == "sreq_created"
    assert cast(str, response.request["scheduling_url"]).startswith("https://")
    assert len(seen) == 1


def test_timezest_create_requires_write_and_http_gates(settings) -> None:
    read_only = _client(settings, lambda request: httpx.Response(201, json=CREATE_JSON))
    assert read_only.write_health().status == "blocked"
    assert read_only.create_scheduling_request(
        client_id="acme",
        appointment_type_id="apty_remote",
        trigger_mode="pod",
        resource_ids=["agnt_1"],
        end_user_name="Rodney Smith",
        end_user_email="rodney@example.test",
    ).result.status == "blocked"

    offline = _write_client(
        settings,
        lambda request: httpx.Response(201, json=CREATE_JSON),
        allow_http_probing=False,
    )
    assert offline.write_health().status == "blocked"


def test_timezest_create_is_approval_gated_and_executes_once_after_approval(settings) -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(201, json=CREATE_JSON)

    client = _write_client(settings, handler)
    service = SmartActionService(Store(client.settings.data_path), client.settings, timezest_client=client)
    payload: dict[str, object] = {
        "client_id": "acme",
        "appointment_type_id": "apty_remote",
        "trigger_mode": "generate_url",
        "resource_ids": ["agnt_1"],
        "end_user_name": "Rodney Smith",
        "end_user_email": "rodney@example.test",
    }

    pending = service.invoke(
        "timezest-scheduling-request-create",
        payload,
        "requester",
        client_id="acme",
    )
    assert pending.status == "pending_approval"
    assert pending.approval_id is not None
    assert calls == []

    approval = service.update_approval(
        pending.approval_id,
        "approved",
        approver="approver",
        approver_role=Role.TECHNICIAN,
    )
    assert approval.status == "approved"
    runs = service.store.list_smart_action_runs(client_id="acme")
    assert runs[-1].status == "success"
    assert len(calls) == 1
    assert "sreq_created" in runs[-1].output_json


def test_timezest_create_action_rejects_invalid_inputs_and_unavailable_provider(settings) -> None:
    client = _write_client(settings, lambda request: httpx.Response(201, json=CREATE_JSON))
    service = SmartActionService(Store(client.settings.data_path), client.settings, timezest_client=client)
    base: dict[str, object] = {
        "client_id": "acme",
        "appointment_type_id": "apty_remote",
        "trigger_mode": "pod",
        "resource_ids": ["agnt_1"],
        "end_user_name": "Rodney Smith",
        "end_user_email": "rodney@example.test",
    }
    invalid_cases = (
        ({"unsupported": True}, "unsupported fields"),
        ({"client_id": ""}, "client_id must be"),
        ({"client_id": "other"}, "outside the tenant scope"),
        ({"appointment_type_id": ""}, "appointment_type_id"),
        ({"trigger_mode": "invalid"}, "trigger_mode"),
        ({"resource_ids": []}, "resource_ids must be"),
        ({"resource_ids": ["agnt_1", "agnt_1"]}, "duplicates"),
        ({"end_user_name": ""}, "end_user_name"),
        ({"end_user_email": "not-an-email"}, "end_user_email"),
        ({"duration_mins": {}}, "invalid type"),
        ({"duration_mins": True}, "duration_mins"),
        ({"end_user_company": ""}, "non-empty string"),
    )
    for overrides, message in invalid_cases:
        result = service.invoke(
            "timezest-scheduling-request-create",
            {**base, **overrides},
            "tech",
            client_id="acme",
        )
        assert result.status == "failed"
        assert message in result.error_detail

    class UnavailableProvider:
        def write_health(self) -> ConnectorReadResult:
            return ConnectorReadResult("failed", "provider unavailable")

        def create_scheduling_request(self, **kwargs: object) -> TimeZestSchedulingCreateResponse:
            raise AssertionError("provider write must not run when preflight fails")

    unavailable = SmartActionService(
        Store(client.settings.data_path), client.settings, timezest_client=UnavailableProvider()
    ).invoke("timezest-scheduling-request-create", base, "tech", client_id="acme")
    assert unavailable.status == "failed"
    assert unavailable.error_detail == "provider unavailable"

    class BrokenHealthProvider:
        def write_health(self) -> ConnectorReadResult:
            raise RuntimeError("provider health failed")

    broken_health = SmartActionService(
        Store(client.settings.data_path), client.settings, timezest_client=BrokenHealthProvider()
    ).invoke("timezest-scheduling-request-create", base, "tech", client_id="acme")
    assert broken_health.status == "failed"
    assert broken_health.error_detail == "TimeZest write readiness check failed"

    class BrokenWriteProvider:
        def write_health(self) -> ConnectorReadResult:
            return ConnectorReadResult("ready", "ready")

        def create_scheduling_request(self, **kwargs: object) -> TimeZestSchedulingCreateResponse:
            raise RuntimeError("provider write failed")

    class InvalidResponseProvider:
        def write_health(self) -> ConnectorReadResult:
            return ConnectorReadResult("ready", "ready")

        def create_scheduling_request(self, **kwargs: object) -> TimeZestSchedulingCreateResponse:
            return TimeZestSchedulingCreateResponse(ConnectorReadResult("ready", "ready"), {})

    for provider in (BrokenWriteProvider(), InvalidResponseProvider()):
        provider_service = SmartActionService(
            Store(client.settings.data_path), client.settings, timezest_client=provider
        )
        pending = provider_service.invoke(
            "timezest-scheduling-request-create", base, "requester", client_id="acme"
        )
        assert pending.approval_id is not None
        completed = provider_service.update_approval(
            pending.approval_id,
            "approved",
            approver="approver",
            approver_role=Role.TECHNICIAN,
        )
        assert completed.status == "approved"
        run = provider_service.store.list_smart_action_runs(client_id="acme")[-1]
        assert run.status == "failed"


@pytest.mark.parametrize(
    ("status_code", "message"),
    [(401, "unauthorized"), (403, "unauthorized"), (429, "rate limited"), (500, "HTTP 500")],
)
def test_timezest_create_preserves_provider_failures(settings, status_code, message) -> None:
    client = _write_client(
        settings,
        lambda request: httpx.Response(status_code, text="timezest-secret-token"),
    )
    response = client.create_scheduling_request(
        client_id="acme",
        appointment_type_id="apty_remote",
        trigger_mode="pod",
        resource_ids=["agnt_1"],
        end_user_name="Rodney Smith",
        end_user_email="rodney@example.test",
    )
    assert response.result.status == "failed"
    assert message in response.result.message
    assert "timezest-secret-token" not in response.result.message


def test_timezest_create_rejects_malformed_provider_payloads_and_write_helpers(settings, monkeypatch) -> None:
    invalid_object = _write_client(
        settings,
        lambda request: httpx.Response(201, json={"object": "wrong", "id": "sreq_created"}),
    )
    assert invalid_object.create_scheduling_request(
        client_id="acme",
        appointment_type_id="apty_remote",
        trigger_mode="pod",
        resource_ids=["agnt_1"],
        end_user_name="Rodney Smith",
        end_user_email="rodney@example.test",
    ).result.status == "failed"

    malformed = _write_client(
        settings,
        lambda request: httpx.Response(201, json=CREATE_JSON),
    )
    monkeypatch.setattr(malformed, "_post", lambda endpoint, json_body: [])
    assert malformed.create_scheduling_request(
        client_id="acme",
        appointment_type_id="apty_remote",
        trigger_mode="pod",
        resource_ids=["agnt_1"],
        end_user_name="Rodney Smith",
        end_user_email="rodney@example.test",
    ).result.status == "failed"

    monkeypatch.setattr(malformed, "_post", lambda endpoint, json_body: {"object": "scheduling_request"})
    assert malformed.create_scheduling_request(
        client_id="acme",
        appointment_type_id="apty_remote",
        trigger_mode="pod",
        resource_ids=["agnt_1"],
        end_user_name="Rodney Smith",
        end_user_email="rodney@example.test",
    ).result.status == "failed"

    with pytest.raises(TimeZestReadError, match="WAIT_ALLOW_WRITE_ACTIONS"):
        _client(settings, lambda request: httpx.Response(200, json={}))._post(
            "v1/scheduling_requests", json_body={}
        )
    with pytest.raises(TimeZestReadError, match="HTTP method"):
        malformed._request("DELETE", "v1/scheduling_requests")


def test_timezest_write_health_rejects_invalid_write_maps(settings) -> None:
    for mapping, message in (
        ("", "incomplete"),
        ("{}", "at least one client mapping"),
        ("[]", "at least one client mapping"),
        ('{"acme": {}}', "one supported company ID"),
    ):
        client = _write_client(settings, lambda request: httpx.Response(200, json={}), timezest_client_map_json=mapping)
        result = client.write_health()
        assert result.status == "failed" or result.status == "not_configured"
        assert message in result.message


def test_timezest_write_health_redacts_unexpected_mapping_parse_errors(settings, monkeypatch) -> None:
    client = _write_client(settings, lambda request: httpx.Response(200, json={}))
    monkeypatch.setattr(timezest_module.json, "loads", lambda value: (_ for _ in ()).throw(TypeError("secret")))
    result = client.write_health()
    assert result.status == "failed"
    assert result.message == "WAIT_TIMEZEST_CLIENT_MAP_JSON must contain a valid client mapping."
    assert "secret" not in result.message


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"trigger_mode": "invalid"}, "trigger_mode"),
        ({"resource_ids": "agnt_1"}, "resource_ids must be a non-empty array"),
        ({"resource_ids": []}, "between 1 and"),
        ({"resource_ids": ["agnt_1", "agnt_1"]}, "duplicates"),
        ({"duration_mins": True}, "duration_mins"),
        ({"earliest_date": "2025-1-1"}, "earliest_date"),
        ({"earliest_date": "2025-01-01", "latest_date": "2024-12-31"}, "after"),
        ({"earliest_time": "10:00"}, "earliest_time"),
        ({"end_user_email": "not-an-email"}, "end_user_email"),
        ({"end_user_name": ""}, "end_user_name"),
    ],
)
def test_timezest_create_validates_documented_fields(settings, overrides, message) -> None:
    values: dict[str, Any] = {
        "appointment_type_id": "apty_remote",
        "trigger_mode": "pod",
        "resource_ids": ["agnt_1"],
        "duration_mins": None,
        "earliest_date": None,
        "earliest_time": None,
        "latest_date": None,
        "latest_time": None,
        "end_user_name": "Rodney Smith",
        "end_user_email": "rodney@example.test",
        "end_user_company": None,
    }
    values.update(overrides)
    with pytest.raises(TimeZestReadError, match=message):
        _validate_create_fields(**values)


def test_timezest_create_validates_date_time_shape_and_safe_urls() -> None:
    with pytest.raises(TimeZestReadError, match="YYYY-MM-DD"):
        _validate_create_fields(
            appointment_type_id="apty_remote",
            trigger_mode="pod",
            resource_ids=["agnt_1"],
            duration_mins=None,
            earliest_date="20250101",
            earliest_time=None,
            latest_date=None,
            latest_time=None,
            end_user_name="Rodney Smith",
            end_user_email="rodney@example.test",
            end_user_company=None,
        )
    with pytest.raises(TimeZestReadError, match="HH:MM:SS"):
        _validate_create_fields(
            appointment_type_id="apty_remote",
            trigger_mode="pod",
            resource_ids=["agnt_1"],
            duration_mins=None,
            earliest_date=None,
            earliest_time="100000",
            latest_date=None,
            latest_time=None,
            end_user_name="Rodney Smith",
            end_user_email="rodney@example.test",
            end_user_company=None,
        )
    with pytest.raises(TimeZestReadError, match="HH:MM:SS"):
        _validate_create_fields(
            appointment_type_id="apty_remote",
            trigger_mode="pod",
            resource_ids=["agnt_1"],
            duration_mins=None,
            earliest_date=None,
            earliest_time="xx:yy:zz",
            latest_date=None,
            latest_time=None,
            end_user_name="Rodney Smith",
            end_user_email="rodney@example.test",
            end_user_company=None,
        )
    with pytest.raises(TimeZestReadError, match="control characters"):
        _validate_create_fields(
            appointment_type_id="apty_remote",
            trigger_mode="pod",
            resource_ids=["agnt_1"],
            duration_mins=None,
            earliest_date=None,
            earliest_time=None,
            latest_date=None,
            latest_time=None,
            end_user_name="Rodney\x01Smith",
            end_user_email="rodney@example.test",
            end_user_company=None,
        )
    assert _safe_scheduling_url("https://example.timezest.com/schedule/ok")
    for value in (
        None,
        "",
        "http://example.test/x",
        "https://user:pass@example.test/x",
        "https://example.test/\x01",
        "x" * 2_001,
    ):
        assert _safe_scheduling_url(value) == ""


def test_timezest_create_requires_end_user_identity_for_company_mapping(settings) -> None:
    client = _write_client(settings, lambda request: httpx.Response(201, json=CREATE_JSON))
    missing_name = client.create_scheduling_request(
        client_id="acme",
        appointment_type_id="apty_remote",
        trigger_mode="pod",
        resource_ids=["agnt_1"],
        end_user_email="rodney@example.test",
    )
    missing_email = client.create_scheduling_request(
        client_id="acme",
        appointment_type_id="apty_remote",
        trigger_mode="pod",
        resource_ids=["agnt_1"],
        end_user_name="Rodney Smith",
    )
    assert missing_name.result.status == "failed"
    assert "end_user_name is required" in missing_name.result.message
    assert missing_email.result.status == "failed"
    assert "end_user_email is required" in missing_email.result.message


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
