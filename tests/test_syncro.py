from __future__ import annotations

from dataclasses import replace

import httpx

from wait_local_agent.syncro import (
    SyncroClient,
    SyncroReadError,
    _api_base_url,
    _http_error_message,
    _list_params,
    _normalize_customer,
    _normalize_ticket,
    _payload_rows,
    _safe_base_url,
    _safe_endpoint,
    _safe_filter,
    _safe_id,
)


def _settings(settings, *, allow_http_probing: bool = True):
    return replace(
        settings,
        allow_http_probing=allow_http_probing,
        syncro_base_url="https://acme.syncromsp.com",
        syncro_api_token="syncro-token",
    )


def test_syncro_reads_are_blocked_without_http_flag(settings) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(500)

    client = SyncroClient(
        _settings(settings, allow_http_probing=False),
        transport=httpx.MockTransport(handler),
    )

    assert client.health().status == "blocked"
    assert client.list_tickets().result.status == "blocked"
    assert client.get_ticket("42").result.status == "blocked"
    assert client.get_customer("7").result.status == "blocked"
    assert requests == []


def test_syncro_reads_report_missing_credentials(settings) -> None:
    client = SyncroClient(
        replace(_settings(settings), syncro_api_token=""),
        transport=httpx.MockTransport(lambda request: httpx.Response(500)),
    )

    health = client.health()
    response = client.list_customers()

    assert health.status == "not_configured"
    assert "WAIT_SYNCRO_API_TOKEN" in health.message
    assert response.result.status == "not_configured"


def test_syncro_reads_normalize_payloads_and_bound_filters(settings) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.url.path.startswith("/api/v1/")
        assert request.headers["authorization"] == "Bearer syncro-token"
        assert "api_key" not in request.url.params
        if request.url.path.endswith("/tickets"):
            assert request.url.params["page"] == "2"
            assert request.url.params["query"] == "printer"
            assert request.url.params["customer_id"] == "7"
            assert request.url.params["status"] == "Open"
            assert request.url.params["since_updated_at"] == "2026-08-01"
            return httpx.Response(
                200,
                json={
                    "tickets": [
                        {
                            "id": 42,
                            "number": 1002,
                            "subject": "Printer offline",
                            "status": "Open",
                            "priority": "High",
                            "customer_id": 7,
                            "customer_business_then_name": "Contoso",
                            "problem_type": "Hardware",
                            "created_at": "2026-08-01T00:00:00Z",
                            "updated_at": "2026-08-02T00:00:00Z",
                        },
                        {"subject": "discarded without an id"},
                    ],
                    "meta": {"page": 2},
                },
            )
        if request.url.path.endswith("/tickets/42"):
            return httpx.Response(200, json={"ticket": {"id": 42, "title": "Single ticket"}})
        if request.url.path.endswith("/customers"):
            return httpx.Response(
                200,
                json={"customers": [{"id": 7, "business_name": "Contoso", "disabled": False}]},
            )
        return httpx.Response(
            200,
            json={"customer": {"id": 7, "business_and_full_name": "Contoso", "email": "ops@example.test"}},
        )

    client = SyncroClient(_settings(settings), transport=httpx.MockTransport(handler))

    tickets = client.list_tickets(
        page=2,
        query=" printer ",
        customer_id="7",
        status="Open",
        since_updated_at="2026-08-01",
    )
    ticket = client.get_ticket("42")
    customers = client.list_customers(query="Contoso", business_name="Contoso")
    customer = client.get_customer("7")
    health = client.health()

    assert tickets.result.status == "ready"
    assert tickets.result.count == 1
    assert tickets.items[0]["customer_name"] == "Contoso"
    assert ticket.items[0]["subject"] == "Single ticket"
    assert customers.items[0] == {
        "id": "7",
        "name": "Contoso",
        "email": "",
        "phone": "",
        "disabled": False,
    }
    assert customer.items[0]["email"] == "ops@example.test"
    assert health.status == "ready"
    assert len(requests) == 5


def test_syncro_failures_are_sanitized_and_distinguish_auth(settings) -> None:
    active = _settings(settings)
    unauthorized = SyncroClient(
        active,
        transport=httpx.MockTransport(lambda request: httpx.Response(401)),
    ).list_customers()
    forbidden = SyncroClient(
        active,
        transport=httpx.MockTransport(lambda request: httpx.Response(403)),
    ).list_customers()
    rate_limited = SyncroClient(
        active,
        transport=httpx.MockTransport(lambda request: httpx.Response(429)),
    ).list_customers()
    malformed = SyncroClient(
        active,
        transport=httpx.MockTransport(lambda request: httpx.Response(200, content=b"bad")),
    ).list_customers()

    def connect_failure(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("syncro-token should not leak", request=request)

    disconnected = SyncroClient(
        active,
        transport=httpx.MockTransport(connect_failure),
    ).list_customers()

    def generic_http_error(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadError("read failed", request=request)

    generic_failure = SyncroClient(
        active,
        transport=httpx.MockTransport(generic_http_error),
    ).list_customers()
    health_failure = SyncroClient(
        active,
        transport=httpx.MockTransport(lambda request: httpx.Response(500)),
    ).health()

    assert "unauthorized" in unauthorized.result.message
    assert "forbidden" in forbidden.result.message
    assert "rate limited" in rate_limited.result.message
    assert malformed.result.message.endswith("returned malformed JSON.")
    assert disconnected.result.message.endswith("before receiving a response.")
    assert "syncro-token" not in disconnected.result.message
    assert generic_failure.result.message == "Syncro request failed."
    assert health_failure.status == "failed"


def test_syncro_helpers_and_invalid_inputs(settings) -> None:
    active = _settings(settings)
    invalid_page = SyncroClient(active).list_tickets(page=0)
    invalid_filter = SyncroClient(active).list_tickets(query="\n")
    invalid_customer_filter = SyncroClient(active).list_customers(business_name="\n")
    invalid_customer = SyncroClient(active).list_tickets(customer_id="7/8")
    invalid_ticket = SyncroClient(active).get_ticket("not-a-number")
    invalid_customer_id = SyncroClient(active).get_customer("not-a-number")
    invalid_base = SyncroClient(
        replace(active, syncro_base_url="https://syncro.test?api_key=leak"),
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=[])),
    ).list_customers()

    assert invalid_page.result.status == "failed"
    assert invalid_filter.result.status == "failed"
    assert invalid_customer_filter.result.status == "failed"
    assert invalid_customer.result.status == "failed"
    assert invalid_ticket.result.status == "failed"
    assert invalid_customer_id.result.status == "failed"
    assert invalid_base.result.status == "failed"
    assert _api_base_url("https://syncro.test/") == "https://syncro.test/api/v1"
    assert _api_base_url("https://syncro.test/api/v1") == "https://syncro.test/api/v1"
    assert _payload_rows([{"id": 1}, "bad"], "tickets") == [{"id": 1}]
    assert _payload_rows({"tickets": [{"id": 1}, "bad"]}, "tickets") == [{"id": 1}]
    assert _payload_rows({"ticket": {"id": 1}}, "ticket") == [{"id": 1}]
    assert _payload_rows({"items": [{"id": 1}]}, "tickets") == [{"id": 1}]
    assert _payload_rows({"id": 1}, "ticket") == [{"id": 1}]
    assert _payload_rows({}, "ticket") == []
    assert _payload_rows("bad", "tickets") == []
    ticket = _normalize_ticket({"ticket_id": 4, "title": "Subject"})
    customer = _normalize_customer({"id": 7, "fullname": "Contoso", "disabled": "true"})
    assert ticket is not None and ticket["id"] == "4"
    assert customer is not None and customer["disabled"] is True
    assert _safe_base_url("https://syncro.test") == "https://syncro.test"
    assert _safe_endpoint("/tickets/1") == "tickets/1"
    assert _safe_id(" 42 ") == "42"
    assert _safe_filter(" value ") == "value"
    assert _list_params(2, {"query": "x", "status": None}) == {"page": 2, "query": "x"}
    assert _normalize_ticket({}) is None
    assert _normalize_customer({}) is None

    invalid_helpers = (
        (_safe_base_url, "https://bad\x00.test"),
        (_safe_base_url, "not-a-url"),
        (_safe_endpoint, "https://evil.test"),
        (_safe_endpoint, "../tickets"),
        (_safe_id, ""),
        (_safe_filter, "x" * 201),
    )
    for helper, value in invalid_helpers:
        try:
            helper(value)
        except SyncroReadError:
            pass
        else:
            raise AssertionError("invalid Syncro input was accepted")

    try:
        SyncroClient(replace(active, allow_http_probing=False))._get("customers")
    except SyncroReadError:
        pass
    else:
        raise AssertionError("blocked direct request was accepted")

    try:
        SyncroClient(replace(active, syncro_api_token=""))._get("customers")
    except SyncroReadError:
        pass
    else:
        raise AssertionError("missing direct request was accepted")
    blocked_direct = SyncroClient(replace(active, allow_http_probing=False))._request_items(
        "customers", "customers", _normalize_customer
    )
    missing_direct = SyncroClient(replace(active, syncro_api_token=""))._request_items(
        "customers", "customers", _normalize_customer
    )
    assert blocked_direct.result.status == "blocked"
    assert missing_direct.result.status == "not_configured"
    assert _http_error_message(500, "customers") == "Syncro GET customers failed with HTTP 500."
