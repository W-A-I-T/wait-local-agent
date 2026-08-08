from __future__ import annotations

from dataclasses import replace

import httpx

from wait_local_agent.syncro import (
    SyncroClient,
    SyncroReadError,
    _bounded_page_size,
    _payload_rows,
    _safe_endpoint,
    _safe_segment,
)


def _configured(settings, *, allow_http_probing: bool = True):
    return replace(
        settings,
        allow_http_probing=allow_http_probing,
        syncro_base_url="https://acme.syncromsp.com/api/v1",
        syncro_api_key="syncro-key",
        syncro_page_size=25,
    )


def test_syncro_defaults_block_and_missing_credentials(settings) -> None:
    assert SyncroClient(settings).list_tickets().result.status == "blocked"
    assert SyncroClient(settings).health().status == "blocked"
    missing = SyncroClient(replace(settings, allow_http_probing=True)).health()
    assert missing.status == "not_configured"
    assert "WAIT_SYNCRO_BASE_URL" in missing.message
    assert SyncroClient(replace(settings, allow_http_probing=True)).list_tickets().result.status == "not_configured"
    assert SyncroClient(settings).get_ticket("7").result.status == "blocked"
    assert SyncroClient(replace(settings, allow_http_probing=True)).get_ticket("7").result.status == "not_configured"


def test_syncro_read_contract_normalizes_tickets_and_customers(settings) -> None:
    calls: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        assert request.url.params["api_key"] == "syncro-key"
        assert request.headers["Accept"] == "application/json"
        if request.url.path.endswith("/tickets"):
            if request.url.params["page"] == "1":
                return httpx.Response(200, json={"tickets": []})
            assert request.url.params["page"] == "2"
            assert request.url.params["page_size"] == "2"
            return httpx.Response(
                200,
                json={
                    "tickets": [
                        {
                            "id": 7,
                            "number": 700,
                            "subject": "Printer",
                            "customer": {"id": 3, "business_name": "Acme"},
                            "status": {"name": "New"},
                            "priority": {"name": "High"},
                            "created_at": "2026-08-07T00:00:00Z",
                        },
                        {"subject": "missing"},
                    ]
                },
            )
        if request.url.path.endswith("/tickets/7"):
            return httpx.Response(200, json={"id": 7, "subject": "Printer"})
        if request.url.path.endswith("/customers"):
            return httpx.Response(
                200,
                json={
                    "customers": [
                        {"id": 3, "business_name": "Acme", "phone": "555-0100"},
                        {"customerId": 4, "name": "Beta", "state": "BC"},
                        {"name": "missing"},
                    ]
                },
            )
        raise AssertionError(request.url)

    client = SyncroClient(_configured(settings), transport=httpx.MockTransport(handler))
    assert client.health().status == "ready"
    tickets = client.list_tickets(page=2, page_size=2)
    ticket = client.get_ticket("7")
    companies = client.list_companies(page_size=2)
    assert tickets.items[0] == {
        "id": "7",
        "number": "700",
        "subject": "Printer",
        "customer_id": "3",
        "customer_name": "Acme",
        "status": "New",
        "priority": "High",
        "created_at": "2026-08-07T00:00:00Z",
        "updated_at": "",
    }
    assert ticket.items[0]["id"] == "7"
    assert companies.items[0] == {
        "id": "3",
        "name": "Acme",
        "phone": "555-0100",
        "city": "",
        "state": "",
    }
    assert companies.items[1]["name"] == "Beta"
    assert calls.count(("GET", "/api/v1/tickets")) == 2


def test_syncro_sanitizes_transport_http_and_json_failures(settings) -> None:
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("private timeout detail")

    assert "before receiving" in SyncroClient(
        _configured(settings), transport=httpx.MockTransport(timeout)
    ).health().message

    def unauthorized(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="private response syncro-key")

    failed = SyncroClient(
        _configured(settings), transport=httpx.MockTransport(unauthorized)
    ).list_tickets()
    assert failed.result.status == "failed"
    assert "HTTP 401" in failed.result.message
    assert "private response" not in failed.result.message
    assert "syncro-key" not in failed.result.message

    def malformed(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not-json")

    result = SyncroClient(
        _configured(settings), transport=httpx.MockTransport(malformed)
    ).list_tickets()
    assert "malformed JSON" in result.result.message

    def protocol_error(request: httpx.Request) -> httpx.Response:
        raise httpx.ProtocolError("private transport detail")

    failed = SyncroClient(
        _configured(settings), transport=httpx.MockTransport(protocol_error)
    ).list_tickets()
    assert failed.result.message == "Syncro request failed."

    blocked = SyncroClient(_configured(settings, allow_http_probing=False))
    try:
        blocked._get("tickets")
    except SyncroReadError as exc:
        assert "WAIT_ALLOW_HTTP_PROBING=true" in str(exc)
    else:
        raise AssertionError("blocked live read was not rejected")

    missing = SyncroClient(replace(settings, allow_http_probing=True))
    try:
        missing._get("tickets")
    except SyncroReadError as exc:
        assert "WAIT_SYNCRO_BASE_URL" in str(exc)
    else:
        raise AssertionError("unconfigured live read was not rejected")


def test_syncro_helper_edges_and_safe_ids(settings) -> None:
    assert _bounded_page_size(0) == 1
    assert _bounded_page_size(1000) == 100
    assert _payload_rows([], "tickets") == []
    assert _payload_rows({"items": []}, "tickets") == []
    assert _payload_rows({"id": 1}, "tickets") == [{"id": 1}]
    assert _payload_rows(None, "tickets") == []
    for helper, value in ((_safe_segment, ""), (_safe_segment, "1/2"), (_safe_endpoint, "//host")):
        try:
            helper(value)
        except SyncroReadError:
            pass
        else:
            raise AssertionError(f"unsafe value accepted: {value}")
    assert SyncroClient(_configured(settings)).get_ticket("bad/id").result.status == "failed"
