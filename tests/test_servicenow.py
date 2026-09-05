from __future__ import annotations

from dataclasses import replace

import httpx
import pytest

from wait_local_agent.models import ServiceNowWriteRequest
from wait_local_agent.servicenow import (
    ServiceNowClient,
    ServiceNowReadError,
    _api_base_url,
    _bool_value,
    _http_error_message,
    _list_params,
    _normalize_company,
    _normalize_incident,
    _payload_rows,
    _reference_value,
    _remote_id,
    _safe_base_url,
    _safe_endpoint,
    _safe_query,
    _safe_sys_id,
    _safe_version,
    _write_fields,
)


def _settings(settings, *, allow_http_probing: bool = True):
    return replace(
        settings,
        allow_http_probing=allow_http_probing,
        servicenow_base_url="https://acme.service-now.com",
        servicenow_username="api-user",
        servicenow_password="servicenow-password",
        servicenow_api_version="v1",
        servicenow_page_size=25,
    )


def test_servicenow_reads_are_blocked_without_http_flag(settings) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(500)

    client = ServiceNowClient(
        _settings(settings, allow_http_probing=False),
        transport=httpx.MockTransport(handler),
    )

    assert client.health().status == "blocked"
    assert client.list_incidents().result.status == "blocked"
    assert client.get_incident("abc123").result.status == "blocked"
    assert client.get_company("abc123").result.status == "blocked"
    assert requests == []


def test_servicenow_reads_report_missing_credentials(settings) -> None:
    client = ServiceNowClient(
        replace(_settings(settings), servicenow_password=""),
        transport=httpx.MockTransport(lambda request: httpx.Response(500)),
    )

    health = client.health()
    response = client.list_companies()

    assert health.status == "not_configured"
    assert "WAIT_SERVICENOW_PASSWORD" in health.message
    assert response.result.status == "not_configured"


def test_servicenow_writes_require_both_flags_and_use_allowlisted_patch(settings) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.method == "PATCH"
        assert request.url.path.endswith("/incident/abc123")
        assert request.headers["content-type"] == "application/json"
        assert request.headers["authorization"].startswith("Basic ")
        assert request.read() == b'{"work_notes":"Investigated locally"}'
        return httpx.Response(200, json={"result": {"sys_id": "abc123", "password": "redact"}})

    blocked = ServiceNowClient(
        _settings(settings, allow_http_probing=False),
        transport=httpx.MockTransport(handler),
    )
    blocked_result = blocked.execute_write(
        ServiceNowWriteRequest("abc123", "add_work_note", {"work_notes": "note"})
    )
    assert blocked.write_health().status == "blocked"
    assert "WAIT_ALLOW_HTTP_PROBING=true" in blocked_result.message
    assert "WAIT_ALLOW_WRITE_ACTIONS=true" in blocked_result.message
    assert requests == []

    active = replace(_settings(settings), allow_write_actions=True)
    client = ServiceNowClient(active, transport=httpx.MockTransport(handler))
    assert client.write_health().status == "ready"
    result = client.execute_write(
        ServiceNowWriteRequest(
            "abc123", "add_work_note", {"work_notes": "Investigated locally"}
        )
    )
    assert result.status == "succeeded"
    assert result.remote_id == "abc123"
    assert client.execute_write(
        ServiceNowWriteRequest("abc123", "add_work_note", {"comments": "unsafe"})
    ).status == "failed"


def test_servicenow_write_failures_are_bounded(settings) -> None:
    active = replace(_settings(settings), allow_write_actions=True)
    request = ServiceNowWriteRequest("abc123", "update_state", {"incident_state": "2"})
    malformed = ServiceNowClient(
        active,
        transport=httpx.MockTransport(lambda _: httpx.Response(200, content=b"bad")),
    ).execute_write(request)
    failed = ServiceNowClient(
        active,
        transport=httpx.MockTransport(lambda _: httpx.Response(500)),
    ).execute_write(request)

    assert malformed.status == "failed"
    assert malformed.message.endswith("returned malformed JSON.")
    assert failed.status == "failed"
    assert "HTTP 500" in failed.message


def test_servicenow_assignment_write_uses_one_allowlisted_reference(settings) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.method == "PATCH"
        assert request.url.path.endswith("/incident/abc123")
        assert request.read() == b'{"assigned_to":"681b365ec0a80164000fb0b05854a0cd"}'
        return httpx.Response(200, json={"result": {"sys_id": "abc123"}})

    client = ServiceNowClient(
        replace(_settings(settings), allow_write_actions=True),
        transport=httpx.MockTransport(handler),
    )
    result = client.execute_write(
        ServiceNowWriteRequest(
            "abc123",
            "assign_incident",
            {"assigned_to": "681b365ec0a80164000fb0b05854a0cd"},
        )
    )
    assert result.status == "succeeded"
    assert len(requests) == 1
    assert client.execute_write(
        ServiceNowWriteRequest("abc123", "assign_incident", {"assigned_to": "bad/id"})
    ).status == "failed"
    assert client.execute_write(
        ServiceNowWriteRequest(
            "abc123",
            "assign_incident",
            {"assigned_to": "a", "assignment_group": "b"},
        )
    ).status == "failed"


def test_servicenow_resolution_write_uses_documented_fields(settings) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.method == "PATCH"
        assert request.url.path.endswith("/incident/abc123")
        assert request.read() == (
            b'{"close_code":"Solved (Permanently)",'
            b'"close_notes":"Resolved using the approved local runbook."}'
        )
        return httpx.Response(200, json={"result": {"sys_id": "abc123"}})

    client = ServiceNowClient(
        replace(_settings(settings), allow_write_actions=True),
        transport=httpx.MockTransport(handler),
    )
    result = client.execute_write(
        ServiceNowWriteRequest(
            "abc123",
            "update_resolution",
            {
                "close_code": "Solved (Permanently)",
                "close_notes": "Resolved using the approved local runbook.",
            },
        )
    )
    assert result.status == "succeeded"
    assert len(requests) == 1


def test_servicenow_write_guards_and_helpers_cover_failure_boundaries(settings) -> None:
    active = _settings(settings)
    request = ServiceNowWriteRequest("abc123", "update_state", {"incident_state": "2"})
    missing = ServiceNowClient(
        replace(active, servicenow_password="", allow_write_actions=True),
        transport=httpx.MockTransport(lambda _: httpx.Response(500)),
    )
    assert missing.write_health().status == "not_configured"
    assert missing.execute_write(request).status == "not_configured"

    write_disabled = ServiceNowClient(
        replace(active, allow_write_actions=False),
        transport=httpx.MockTransport(lambda _: httpx.Response(500)),
    )
    with pytest.raises(ServiceNowReadError, match="WAIT_ALLOW_WRITE_ACTIONS=true"):
        write_disabled._patch("incident/abc123", {"incident_state": "2"})

    def connect_failure(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("secret should not leak")

    def generic_failure(_: httpx.Request) -> httpx.Response:
        raise httpx.ReadError("read failed")

    assert ServiceNowClient(
        replace(active, allow_write_actions=True), transport=httpx.MockTransport(connect_failure)
    ).execute_write(request).message.endswith("before receiving a response.")
    assert ServiceNowClient(
        replace(active, allow_write_actions=True), transport=httpx.MockTransport(generic_failure)
    ).execute_write(request).message == "ServiceNow request failed."
    empty = ServiceNowClient(
        replace(active, allow_write_actions=True),
        transport=httpx.MockTransport(lambda _: httpx.Response(204)),
    ).execute_write(request)
    assert empty.status == "succeeded" and empty.remote_id == ""

    invalid_fields = (
        ("add_work_note", {"comments": "wrong"}),
        ("add_work_note", {"work_notes": ""}),
        ("update_state", {"state": "2"}),
        ("update_state", {"incident_state": ""}),
        ("assign_incident", {"assigned_to": "bad/id"}),
        ("assign_incident", {"assigned_to": "a", "assignment_group": "b"}),
        ("update_resolution", {"close_code": "Solved"}),
        ("update_resolution", {"close_code": "Solved", "close_notes": "\x00"}),
        ("unknown", {"field": "value"}),
    )
    for action_type, fields in invalid_fields:
        with pytest.raises(ServiceNowReadError):
            _write_fields(action_type, fields)
    assert _remote_id({"result": {"sys_id": "abc123"}}) == "abc123"
    assert _remote_id({"result": []}) == ""
    assert _remote_id([]) == ""


def test_servicenow_reads_normalize_payloads_and_bound_requests(settings) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.url.path.startswith("/api/now/v1/")
        assert request.headers["accept"] == "application/json"
        assert request.headers["authorization"].startswith("Basic ")
        if request.url.path.endswith("/incident"):
            assert request.url.params["sysparm_display_value"] == "true"
            assert request.url.params["sysparm_limit"] == "100"
            assert request.url.params["sysparm_offset"] == "100"
            assert request.url.params["sysparm_query"] == "active=true"
            return httpx.Response(
                200,
                json={
                    "result": [
                        {
                            "sys_id": "abc123",
                            "number": "INC0010001",
                            "short_description": "Printer offline",
                            "state": {"display_value": "In Progress", "value": "2"},
                            "priority": {"display_value": "High"},
                            "company": {"display_value": "Contoso"},
                            "caller_id": {"name": "A. User"},
                            "assigned_to": {"value": "tech-1"},
                        },
                        {"short_description": "discarded without sys_id"},
                    ]
                },
            )
        if request.url.path.endswith("/incident/abc123"):
            return httpx.Response(200, json={"result": {"sys_id": "abc123", "number": "INC0010001"}})
        if request.url.path.endswith("/core_company"):
            assert request.url.params["sysparm_display_value"] == "true"
            return httpx.Response(
                200,
                json={"result": [{"sys_id": "co-1", "name": "Contoso", "active": "true"}]},
            )
        return httpx.Response(200, json={"result": {"sys_id": "co-1", "name": "Contoso"}})

    client = ServiceNowClient(_settings(settings), transport=httpx.MockTransport(handler))

    health = client.health()
    incidents = client.list_incidents(page=2, page_size=250, query=" active=true ")
    incident = client.get_incident(" abc123 ")
    companies = client.list_companies()
    company = client.get_company("co-1")

    assert health.status == "ready"
    assert incidents.result.status == "ready"
    assert incidents.items[0]["state"] == "In Progress"
    assert incidents.items[0]["caller"] == "A. User"
    assert incident.items[0]["number"] == "INC0010001"
    assert companies.items[0] == {
        "sys_id": "co-1",
        "name": "Contoso",
        "active": True,
        "created_at": "",
        "updated_at": "",
    }
    assert company.items[0]["name"] == "Contoso"
    assert len(requests) == 5


def test_servicenow_failures_are_sanitized_and_distinguish_auth(settings) -> None:
    active = _settings(settings)
    unauthorized = ServiceNowClient(
        active, transport=httpx.MockTransport(lambda request: httpx.Response(401))
    ).list_companies()
    forbidden = ServiceNowClient(
        active, transport=httpx.MockTransport(lambda request: httpx.Response(403))
    ).list_companies()
    rate_limited = ServiceNowClient(
        active, transport=httpx.MockTransport(lambda request: httpx.Response(429))
    ).list_companies()
    malformed = ServiceNowClient(
        active, transport=httpx.MockTransport(lambda request: httpx.Response(200, content=b"bad"))
    ).list_companies()

    def connect_failure(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("servicenow-password should not leak", request=request)

    disconnected = ServiceNowClient(
        active, transport=httpx.MockTransport(connect_failure)
    ).list_companies()

    def generic_http_error(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadError("read failed", request=request)

    generic_failure = ServiceNowClient(
        active, transport=httpx.MockTransport(generic_http_error)
    ).list_companies()
    health_failure = ServiceNowClient(
        active, transport=httpx.MockTransport(lambda request: httpx.Response(500))
    ).health()

    assert "unauthorized" in unauthorized.result.message
    assert "forbidden" in forbidden.result.message
    assert "rate limited" in rate_limited.result.message
    assert malformed.result.message.endswith("returned malformed JSON.")
    assert disconnected.result.message.endswith("before receiving a response.")
    assert "servicenow-password" not in disconnected.result.message
    assert generic_failure.result.message == "ServiceNow request failed."
    assert health_failure.status == "failed"


@pytest.mark.parametrize("query", ["\n", "active=true\n", "\tactive=true", "active=true\r\n", "\x7f"])
def test_servicenow_control_characters_never_reach_provider(settings, query: str) -> None:
    def unexpected_request(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("malformed query reached provider")

    client = ServiceNowClient(_settings(settings), transport=httpx.MockTransport(unexpected_request))
    result = client.list_incidents(query=query)
    assert result.result.status == "failed"
    assert "control characters" in result.result.message


def test_servicenow_helpers_and_invalid_inputs(settings) -> None:
    active = _settings(settings)
    def unexpected_request(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("invalid ServiceNow input must not contact a provider")

    invalid_client = ServiceNowClient(active, transport=httpx.MockTransport(unexpected_request))
    invalid_page = ServiceNowClient(active).list_incidents(page=0)
    invalid_page_size = ServiceNowClient(active).list_incidents(page_size=0)
    invalid_query = invalid_client.list_incidents(query="\n")
    invalid_id = ServiceNowClient(active).get_incident("../secret")
    invalid_base = ServiceNowClient(
        replace(active, servicenow_base_url="https://service-now.test?token=leak"),
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=[])),
    ).list_companies()

    assert invalid_page.result.status == "failed"
    assert invalid_page_size.result.status == "failed"
    assert invalid_query.result.status == "failed"
    assert invalid_id.result.status == "failed"
    assert invalid_base.result.status == "failed"
    assert _api_base_url("https://service-now.test/", "v1") == "https://service-now.test/api/now/v1"
    assert _api_base_url("https://service-now.test/api/now", "v1") == "https://service-now.test/api/now/v1"
    assert _api_base_url("https://service-now.test/api/now/v1", "") == "https://service-now.test/api/now"
    assert _payload_rows([{"sys_id": "1"}, "bad"]) == [{"sys_id": "1"}]
    assert _payload_rows({"result": [{"sys_id": "1"}, "bad"]}) == [{"sys_id": "1"}]
    assert _payload_rows({"result": {"sys_id": "1"}}) == [{"sys_id": "1"}]
    assert _payload_rows({"sys_id": "1"}) == [{"sys_id": "1"}]
    assert _payload_rows({}) == []
    assert _payload_rows("bad") == []
    assert _normalize_incident({}) is None
    assert _normalize_company({}) is None
    assert _normalize_incident({"sys_id": "1", "state": "New"}) is not None
    normalized_company = _normalize_company({"sys_id": "1", "active": "yes"})
    assert normalized_company is not None and normalized_company["active"] is True
    assert _bool_value("off") is False
    assert _bool_value(True) is True
    assert _bool_value(1) is True
    assert _reference_value({}) == ""
    assert _list_params("incident", 2, 250, "x")["sysparm_limit"] == 100
    assert _safe_base_url("https://service-now.test") == "https://service-now.test"
    assert _safe_endpoint("/incident/abc123") == "incident/abc123"
    assert _safe_sys_id(" abc123 ") == "abc123"
    assert _safe_query(" active=true ") == "active=true"
    assert _safe_query("") is None
    assert _safe_version("v1") == "v1"
    assert _http_error_message(500, "incident") == "ServiceNow GET incident failed with HTTP 500."

    invalid_helpers = (
        (_safe_base_url, "https://bad\x00.test"),
        (_safe_base_url, "not-a-url"),
        (_safe_endpoint, "../incident"),
        (_safe_endpoint, "incident/abc?x=1"),
        (_safe_sys_id, ""),
        (_safe_query, "x" * 501),
        (_safe_version, "bad/version"),
    )
    for helper, value in invalid_helpers:
        with pytest.raises(ServiceNowReadError):
            helper(value)

    with pytest.raises(ServiceNowReadError, match="table is not enabled"):
        _list_params("problem", 1, 1, None)

    for client in (
        ServiceNowClient(replace(active, allow_http_probing=False)),
        ServiceNowClient(replace(active, servicenow_password="")),
    ):
        with pytest.raises(ServiceNowReadError):
            client._get("incident")

    assert ServiceNowClient(replace(active, allow_http_probing=False))._request_items(
        "incident", "incidents", _normalize_incident
    ).result.status == "blocked"
    assert ServiceNowClient(replace(active, servicenow_password=""))._request_items(
        "incident", "incidents", _normalize_incident
    ).result.status == "not_configured"
