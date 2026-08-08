from __future__ import annotations

import base64
from dataclasses import replace

import httpx

from wait_local_agent.servicenow import (
    ServiceNowClient,
    ServiceNowReadError,
    _bounded_page_size,
    _payload_rows,
    _safe_endpoint,
    _safe_segment,
)


def _configured(settings, *, allow_http_probing: bool = True):
    return replace(
        settings,
        allow_http_probing=allow_http_probing,
        servicenow_base_url="https://acme.service-now.com",
        servicenow_username="readonly",
        servicenow_password="password",
        servicenow_page_size=25,
    )


def test_servicenow_defaults_block_and_missing_credentials(settings) -> None:
    assert ServiceNowClient(settings).list_tickets().result.status == "blocked"
    assert ServiceNowClient(settings).health().status == "blocked"
    missing = ServiceNowClient(replace(settings, allow_http_probing=True)).health()
    assert missing.status == "not_configured"
    assert "WAIT_SERVICENOW_BASE_URL" in missing.message
    assert ServiceNowClient(replace(settings, allow_http_probing=True)).list_tickets().result.status == "not_configured"
    assert (
        ServiceNowClient(replace(settings, allow_http_probing=True)).get_ticket("7").result.status
        == "not_configured"
    )
    assert ServiceNowClient(settings).get_ticket("7").result.status == "blocked"


def test_servicenow_read_contract_normalizes_incidents_and_companies(settings) -> None:
    calls: list[tuple[str, str]] = []
    expected_auth = "Basic " + base64.b64encode(b"readonly:password").decode("ascii")

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        assert request.headers["Authorization"] == expected_auth
        assert request.headers["Accept"] == "application/json"
        assert request.url.params["sysparm_display_value"] == "true"
        assert "sysparm_fields" in request.url.params
        if request.url.path.endswith("/incident"):
            if request.url.params["sysparm_offset"] == "0":
                return httpx.Response(200, json={"result": []})
            assert request.url.params["sysparm_offset"] == "2"
            assert request.url.params["sysparm_limit"] == "2"
            return httpx.Response(
                200,
                json={
                    "result": [
                        {
                            "sys_id": "abc",
                            "number": "INC001",
                            "short_description": "Printer",
                            "company": {"value": "company-1", "display_value": "Acme"},
                            "state": "In Progress",
                            "priority": "2 - High",
                            "opened_at": "2026-08-07 00:00:00",
                            "sys_updated_on": "2026-08-07 01:00:00",
                        },
                        {"short_description": "missing"},
                    ]
                },
            )
        if request.url.path.endswith("/incident/abc"):
            return httpx.Response(200, json={"result": {"sys_id": "abc", "number": "INC001"}})
        if request.url.path.endswith("/core_company"):
            return httpx.Response(
                200,
                json={
                    "result": [
                        {"sys_id": "company-1", "name": {"display_value": "Acme"}, "phone": "555-0100"},
                        {"sys_id": "company-2", "name": "Beta", "state": "BC"},
                        {"name": "missing"},
                    ]
                },
            )
        raise AssertionError(request.url)

    client = ServiceNowClient(_configured(settings), transport=httpx.MockTransport(handler))
    assert client.health().status == "ready"
    tickets = client.list_tickets(page=2, page_size=2)
    ticket = client.get_ticket("abc")
    companies = client.list_companies(page_size=2)
    assert tickets.items[0] == {
        "id": "abc",
        "number": "INC001",
        "summary": "Printer",
        "company_id": "company-1",
        "company_name": "Acme",
        "status": "In Progress",
        "priority": "2 - High",
        "opened_at": "2026-08-07 00:00:00",
        "updated_at": "2026-08-07 01:00:00",
    }
    assert ticket.items[0]["id"] == "abc"
    assert companies.items[0] == {
        "id": "company-1",
        "name": "Acme",
        "phone": "555-0100",
        "city": "",
        "state": "",
    }
    assert calls.count(("GET", "/api/now/table/incident")) == 2


def test_servicenow_sanitizes_transport_http_and_json_failures(settings) -> None:
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("private timeout detail")

    assert "before receiving" in ServiceNowClient(
        _configured(settings), transport=httpx.MockTransport(timeout)
    ).health().message

    def unauthorized(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="private response password")

    failed = ServiceNowClient(
        _configured(settings), transport=httpx.MockTransport(unauthorized)
    ).list_tickets()
    assert failed.result.status == "failed"
    assert "HTTP 401" in failed.result.message
    assert "private response" not in failed.result.message
    assert "password" not in failed.result.message

    def malformed(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not-json")

    result = ServiceNowClient(
        _configured(settings), transport=httpx.MockTransport(malformed)
    ).list_tickets()
    assert "malformed JSON" in result.result.message

    def protocol_error(request: httpx.Request) -> httpx.Response:
        raise httpx.ProtocolError("private transport detail")

    failed = ServiceNowClient(
        _configured(settings), transport=httpx.MockTransport(protocol_error)
    ).list_tickets()
    assert failed.result.message == "ServiceNow request failed."

    blocked = ServiceNowClient(_configured(settings, allow_http_probing=False))
    try:
        blocked._get("incident", "sys_id")
    except ServiceNowReadError as exc:
        assert "WAIT_ALLOW_HTTP_PROBING=true" in str(exc)
    else:
        raise AssertionError("blocked live read was not rejected")

    missing = ServiceNowClient(replace(settings, allow_http_probing=True))
    try:
        missing._get("incident", "sys_id")
    except ServiceNowReadError as exc:
        assert "WAIT_SERVICENOW_BASE_URL" in str(exc)
    else:
        raise AssertionError("unconfigured live read was not rejected")


def test_servicenow_helper_edges_and_safe_ids(settings) -> None:
    assert _bounded_page_size(0) == 1
    assert _bounded_page_size(1000) == 100
    assert _payload_rows({"result": []}) == []
    assert _payload_rows({"result": {"sys_id": "1"}}) == [{"sys_id": "1"}]
    assert _payload_rows({"items": []}) == []
    assert _payload_rows(None) == []
    for helper, value in ((_safe_segment, ""), (_safe_segment, "1/2"), (_safe_endpoint, "//host")):
        try:
            helper(value)
        except ServiceNowReadError:
            pass
        else:
            raise AssertionError(f"unsafe value accepted: {value}")
    assert ServiceNowClient(_configured(settings)).get_ticket("bad/id").result.status == "failed"
