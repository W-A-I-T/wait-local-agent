from __future__ import annotations

import base64
from dataclasses import replace

import httpx

from wait_local_agent.connectwise import (
    ConnectWiseClient,
    ConnectWiseReadError,
    _api_base_url,
    _list_params,
    _normalize_company,
    _normalize_ticket,
    _payload_rows,
    _safe_endpoint,
    _safe_segment,
    _safe_version,
)


def _settings(settings, *, allow_http_probing: bool = True):
    return replace(
        settings,
        allow_http_probing=allow_http_probing,
        connectwise_base_url="https://cw.example.test",
        connectwise_company="Acme+MSP",
        connectwise_public_key="public-key",
        connectwise_private_key="private-key",
        connectwise_client_id="client-id",
        connectwise_api_version="2022.1",
        connectwise_page_size=25,
    )


def test_connectwise_reads_are_blocked_without_http_flag(settings) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(500)

    client = ConnectWiseClient(
        _settings(settings, allow_http_probing=False),
        transport=httpx.MockTransport(handler),
    )

    assert client.health().status == "blocked"
    assert client.list_tickets().result.status == "blocked"
    assert client.get_ticket("42").result.status == "blocked"
    assert requests == []


def test_connectwise_reads_report_missing_credentials(settings) -> None:
    client = ConnectWiseClient(
        replace(_settings(settings), connectwise_private_key=""),
        transport=httpx.MockTransport(lambda request: httpx.Response(500)),
    )

    result = client.health()
    response = client.list_companies()

    assert result.status == "not_configured"
    assert "WAIT_CONNECTWISE_PRIVATE_KEY" in result.message
    assert response.result.status == "not_configured"


def test_connectwise_reads_normalize_payloads_and_bound_requests(settings) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.url.path.startswith("/v4_6_release/apis/3.0/")
        assert request.headers["clientid"] == "client-id"
        assert request.headers["accept"] == "application/vnd.connectwise.com+json; version=2022.1"
        auth = request.headers["authorization"].removeprefix("Basic ")
        assert base64.b64decode(auth).decode() == "Acme+MSP+public-key:private-key"
        if request.url.path.endswith("/service/tickets"):
            assert request.url.params["page"] == "2"
            assert request.url.params["pageSize"] == "100"
            assert request.url.params["conditions"] == "status/name = 'Open'"
            return httpx.Response(
                200,
                json=[
                    {
                        "id": 42,
                        "summary": "Printer offline",
                        "initialDescription": "No print jobs",
                        "status": {"name": "Open"},
                        "priority": {"name": "High"},
                        "company": {"id": 7, "name": "Contoso"},
                        "board": {"name": "Service"},
                    },
                    {"summary": "discarded without an id"},
                ],
            )
        if request.url.path.endswith("/service/tickets/42"):
            return httpx.Response(200, json={"id": 42, "subject": "Single ticket"})
        return httpx.Response(
            200,
            json={"items": [{"identifier": "C-1", "companyName": "Contoso", "status": "Active"}]},
        )

    client = ConnectWiseClient(_settings(settings), transport=httpx.MockTransport(handler))

    tickets = client.list_tickets(page=2, page_size=500, conditions=" status/name = 'Open' ")
    ticket = client.get_ticket("42")
    companies = client.list_companies()
    health = client.health()

    assert tickets.result.status == "ready"
    assert tickets.result.count == 1
    assert tickets.items[0] == {
        "id": "42",
        "summary": "Printer offline",
        "description": "No print jobs",
        "status": "Open",
        "priority": "High",
        "company_id": "7",
        "company_name": "Contoso",
        "board": "Service",
    }
    assert ticket.items[0]["summary"] == "Single ticket"
    assert companies.items[0] == {"id": "C-1", "name": "Contoso", "status": "Active"}
    assert health.status == "ready"
    assert len(requests) == 4


def test_connectwise_read_failures_are_sanitized(settings) -> None:
    active = _settings(settings)

    http_failure = ConnectWiseClient(
        active,
        transport=httpx.MockTransport(lambda request: httpx.Response(503)),
    ).list_companies()
    malformed = ConnectWiseClient(
        active,
        transport=httpx.MockTransport(lambda request: httpx.Response(200, content=b"not-json")),
    ).list_companies()

    def connect_failure(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("private-key should not leak", request=request)

    disconnected = ConnectWiseClient(
        active,
        transport=httpx.MockTransport(connect_failure),
    ).list_companies()

    def http_error(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadError("read failed", request=request)

    generic_failure = ConnectWiseClient(
        active,
        transport=httpx.MockTransport(http_error),
    ).list_companies()
    health_failure = ConnectWiseClient(
        active,
        transport=httpx.MockTransport(lambda request: httpx.Response(503)),
    ).health()

    assert http_failure.result.status == "failed"
    assert "HTTP 503" in http_failure.result.message
    assert malformed.result.message.endswith("returned malformed JSON.")
    assert disconnected.result.message.endswith("before receiving a response.")
    assert "private-key" not in disconnected.result.message
    assert generic_failure.result.message == "ConnectWise PSA request failed."
    assert health_failure.status == "failed"


def test_connectwise_validation_and_empty_shapes(settings) -> None:
    active = _settings(settings)
    invalid_page = ConnectWiseClient(active).list_tickets(page=0)
    invalid_size = ConnectWiseClient(active).list_tickets(page_size=0)
    invalid_conditions = ConnectWiseClient(active).list_tickets(conditions="\n")
    invalid_id = ConnectWiseClient(active).get_ticket("42/other")
    missing_id = ConnectWiseClient(
        replace(active, connectwise_private_key=""),
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=[])),
    ).get_ticket("42")
    invalid_version = ConnectWiseClient(
        replace(active, connectwise_api_version="2022-beta"),
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=[])),
    ).list_companies()

    assert invalid_page.result.status == "failed"
    assert invalid_size.result.status == "failed"
    assert invalid_conditions.result.status == "failed"
    assert invalid_id.result.status == "failed"
    assert missing_id.result.status == "not_configured"
    assert invalid_version.result.status == "failed"
    empty = ConnectWiseClient(
        active,
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={})),
    ).list_companies()
    assert empty.items == []

    assert _api_base_url("https://cw.test/") == "https://cw.test/v4_6_release/apis/3.0"
    assert _api_base_url("https://cw.test/v4_6_release/apis/3.0") == "https://cw.test/v4_6_release/apis/3.0"
    assert _safe_endpoint("/service/tickets") == "service/tickets"
    assert _payload_rows({"items": [{"id": 1}, "bad"]}) == [{"id": 1}]
    assert _payload_rows({"id": 1}) == [{"id": 1}]
    assert _payload_rows("bad") == []
    ticket = _normalize_ticket({"ticketNumber": 3, "subject": "Subject", "status": 1})
    company = _normalize_company({"id": 1, "name": "Contoso"})
    assert ticket is not None
    assert company is not None
    assert ticket["id"] == "3"
    assert company["id"] == "1"
    assert _normalize_ticket({}) is None
    assert _normalize_company({}) is None

    for helper, value in ((_safe_endpoint, "https://evil.test"), (_safe_segment, "a/b")):
        try:
            helper(value)
        except ConnectWiseReadError:
            pass
        else:
            raise AssertionError("unsafe value was accepted")
    try:
        _safe_endpoint("/../")
    except ConnectWiseReadError:
        pass
    else:
        raise AssertionError("traversal endpoint was accepted")
    for helper, value in ((_safe_version, ""), (_safe_version, "2022-beta")):
        try:
            helper(value)
        except ConnectWiseReadError:
            pass
        else:
            raise AssertionError("invalid version was accepted")
    try:
        _list_params(1, 1, "x" * 501)
    except ConnectWiseReadError:
        pass
    else:
        raise AssertionError("oversized conditions were accepted")
    for client in (
        ConnectWiseClient(replace(active, allow_http_probing=False)),
        ConnectWiseClient(replace(active, connectwise_private_key="")),
    ):
        try:
            client._get("service/tickets")
        except ConnectWiseReadError:
            pass
        else:
            raise AssertionError("unsafe direct request was accepted")
