from __future__ import annotations

from dataclasses import replace

import httpx

from wait_local_agent.autotask import (
    AutotaskClient,
    AutotaskReadError,
    _api_base_url,
    _bounded_page_size,
    _payload_rows,
    _safe_endpoint,
    _safe_segment,
)


def _configured(settings, *, allow_http_probing: bool = True):
    return replace(
        settings,
        allow_http_probing=allow_http_probing,
        autotask_base_url="https://webservices1.autotask.net",
        autotask_username="api-user",
        autotask_secret="api-secret",
        autotask_integration_code="integration-code",
        autotask_page_size=25,
    )


def test_autotask_defaults_block_and_missing_credentials(settings) -> None:
    assert AutotaskClient(settings).list_tickets().result.status == "blocked"
    missing = AutotaskClient(replace(settings, allow_http_probing=True)).health()
    assert missing.status == "not_configured"
    assert "WAIT_AUTOTASK_BASE_URL" in missing.message


def test_autotask_read_contract_normalizes_tickets_and_companies(settings) -> None:
    calls: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        assert request.headers["Username"] == "api-user"
        assert request.headers["Secret"] == "api-secret"
        assert request.headers["APIIntegrationcode"] == "integration-code"
        if request.url.path.endswith("/Tickets/entityInformation"):
            return httpx.Response(200, json={"name": "Tickets"})
        if request.url.path.endswith("/Tickets/query"):
            assert request.url.params["page"] == "2"
            assert request.url.params["pageSize"] == "2"
            return httpx.Response(
                200,
                json={"items": [{"id": 7, "ticketNumber": "T-7", "title": "Printer"}, {"title": "missing"}]},
            )
        if request.url.path.endswith("/Tickets/7"):
            return httpx.Response(200, json={"id": 7, "companyID": 3, "isActive": True})
        if request.url.path.endswith("/Companies/query"):
            return httpx.Response(200, json=[{"companyID": 3, "companyName": "Acme", "isActive": "yes"}])
        raise AssertionError(request.url)

    client = AutotaskClient(_configured(settings), transport=httpx.MockTransport(handler))
    assert client.health().status == "ready"
    tickets = client.list_tickets(page=2, page_size=2)
    ticket = client.get_ticket("7")
    companies = client.list_companies(page_size=2)
    assert tickets.items[0]["ticket_number"] == "T-7"
    assert ticket.items[0]["company_id"] == "3"
    assert companies.items[0] == {"id": "3", "name": "Acme", "active": True}
    assert calls.count(("GET", "/atservicesrest/v1.0/Tickets/entityInformation")) == 1


def test_autotask_sanitizes_transport_http_and_json_failures(settings) -> None:
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timeout")

    assert "before receiving" in AutotaskClient(
        _configured(settings), transport=httpx.MockTransport(timeout)
    ).health().message

    def unauthorized(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="private response")

    failed = AutotaskClient(
        _configured(settings), transport=httpx.MockTransport(unauthorized)
    ).list_tickets()
    assert failed.result.status == "failed"
    assert "HTTP 401" in failed.result.message
    assert "private response" not in failed.result.message

    def malformed(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not-json")

    result = AutotaskClient(
        _configured(settings), transport=httpx.MockTransport(malformed)
    ).list_tickets()
    assert "malformed JSON" in result.result.message


def test_autotask_helper_edges_and_safe_ids(settings) -> None:
    assert _api_base_url("https://zone.test/atservicesrest/v1.0/") == "https://zone.test/atservicesrest/v1.0"
    assert _api_base_url("https://zone.test/atservicesrest") == "https://zone.test/atservicesrest/v1.0"
    assert _api_base_url("https://zone.test") == "https://zone.test/atservicesrest/v1.0"
    assert _bounded_page_size(0) == 1
    assert _bounded_page_size(1000) == 100
    assert _payload_rows({"items": []}) == []
    assert _payload_rows({"id": 1}) == [{"id": 1}]
    assert _payload_rows(None) == []
    for helper, value in ((_safe_segment, ""), (_safe_segment, "1/2"), (_safe_endpoint, "//host")):
        try:
            helper(value)
        except AutotaskReadError:
            pass
        else:
            raise AssertionError(f"unsafe value accepted: {value}")
    assert AutotaskClient(_configured(settings)).get_ticket("bad/id").result.status == "failed"
