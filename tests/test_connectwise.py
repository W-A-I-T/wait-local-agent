from __future__ import annotations

import base64
from dataclasses import replace

import httpx

from wait_local_agent.connectwise import (
    ConnectWiseClient,
    ConnectWiseReadError,
    _bounded_page_size,
    _payload_rows,
    _safe_endpoint,
    _safe_segment,
)


def _configured(settings, *, allow_http_probing: bool = True):
    return replace(
        settings,
        allow_http_probing=allow_http_probing,
        connectwise_base_url="https://api-na.myconnectwise.net/v4_6_release/apis/3.0",
        connectwise_company_id="Acme+MSP",
        connectwise_public_key="public-key",
        connectwise_private_key="private-key",
        connectwise_client_id="client-id",
        connectwise_page_size=25,
    )


def test_connectwise_defaults_block_and_missing_credentials(settings) -> None:
    assert ConnectWiseClient(settings).list_tickets().result.status == "blocked"
    assert ConnectWiseClient(settings).health().status == "blocked"
    missing = ConnectWiseClient(replace(settings, allow_http_probing=True)).health()
    assert missing.status == "not_configured"
    assert "WAIT_CONNECTWISE_BASE_URL" in missing.message
    assert (
        ConnectWiseClient(replace(settings, allow_http_probing=True)).list_tickets().result.status
        == "not_configured"
    )
    assert ConnectWiseClient(settings).get_ticket("7").result.status == "blocked"
    assert (
        ConnectWiseClient(replace(settings, allow_http_probing=True)).get_ticket("7").result.status
        == "not_configured"
    )


def test_connectwise_read_contract_normalizes_tickets_and_companies(settings) -> None:
    calls: list[tuple[str, str]] = []
    expected_auth = "Basic " + base64.b64encode(b"Acme+MSP+public-key:private-key").decode("ascii")

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        assert request.headers["Authorization"] == expected_auth
        assert request.headers["clientId"] == "client-id"
        if request.url.path.endswith("/service/tickets"):
            if request.url.params["page"] == "1":
                return httpx.Response(200, json=[])
            assert request.url.params["page"] == "2"
            assert request.url.params["pageSize"] == "2"
            return httpx.Response(
                200,
                json=[
                    {
                        "id": 7,
                        "summary": "Printer",
                        "company": {"id": 3, "name": "Acme"},
                        "board": {"name": "Service Desk"},
                        "status": {"name": "New"},
                        "priority": {"name": "High"},
                        "dateEntered": "2026-08-07T00:00:00Z",
                    },
                    {"summary": "missing"},
                ],
            )
        if request.url.path.endswith("/service/tickets/7"):
            return httpx.Response(200, json={"id": 7, "company": {"id": 3}})
        if request.url.path.endswith("/company/companies"):
            return httpx.Response(
                200,
                json=[
                    {"id": 3, "name": "Acme", "status": {"name": "Active"}, "identifier": "ACME"},
                    {"companyId": 4, "companyName": "Beta", "statusReference": "Inactive"},
                    {"companyName": "missing"},
                ],
            )
        raise AssertionError(request.url)

    client = ConnectWiseClient(_configured(settings), transport=httpx.MockTransport(handler))
    assert client.health().status == "ready"
    tickets = client.list_tickets(page=2, page_size=2)
    ticket = client.get_ticket("7")
    companies = client.list_companies(page_size=2)
    assert tickets.items[0] == {
        "id": "7",
        "summary": "Printer",
        "record_type": "",
        "company_id": "3",
        "company_name": "Acme",
        "board_name": "Service Desk",
        "status": "New",
        "priority": "High",
        "date_entered": "2026-08-07T00:00:00Z",
    }
    assert ticket.items[0]["id"] == "7"
    assert companies.items[0] == {
        "id": "3",
        "name": "Acme",
        "status": "Active",
        "identifier": "ACME",
    }
    assert companies.items[1]["status"] == "Inactive"
    assert calls.count(("GET", "/v4_6_release/apis/3.0/service/tickets")) == 2


def test_connectwise_sanitizes_transport_http_and_json_failures(settings) -> None:
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timeout")

    assert "before receiving" in ConnectWiseClient(
        _configured(settings), transport=httpx.MockTransport(timeout)
    ).health().message

    def unauthorized(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="private response")

    failed = ConnectWiseClient(
        _configured(settings), transport=httpx.MockTransport(unauthorized)
    ).list_tickets()
    assert failed.result.status == "failed"
    assert "HTTP 401" in failed.result.message
    assert "private response" not in failed.result.message
    assert ConnectWiseClient(
        _configured(settings), transport=httpx.MockTransport(unauthorized)
    ).health().status == "failed"

    def malformed(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not-json")

    result = ConnectWiseClient(
        _configured(settings), transport=httpx.MockTransport(malformed)
    ).list_tickets()
    assert "malformed JSON" in result.result.message

    def protocol_error(request: httpx.Request) -> httpx.Response:
        raise httpx.ProtocolError("private transport detail")

    failed = ConnectWiseClient(
        _configured(settings), transport=httpx.MockTransport(protocol_error)
    ).list_tickets()
    assert failed.result.status == "failed"
    assert failed.result.message == "ConnectWise request failed."

    blocked = ConnectWiseClient(_configured(settings, allow_http_probing=False))
    try:
        blocked._get("service/tickets")
    except ConnectWiseReadError as exc:
        assert "WAIT_ALLOW_HTTP_PROBING=true" in str(exc)
    else:
        raise AssertionError("blocked live read was not rejected")

    missing = ConnectWiseClient(replace(settings, allow_http_probing=True))
    try:
        missing._get("service/tickets")
    except ConnectWiseReadError as exc:
        assert "WAIT_CONNECTWISE_BASE_URL" in str(exc)
    else:
        raise AssertionError("unconfigured live read was not rejected")


def test_connectwise_helper_edges_and_safe_ids(settings) -> None:
    assert _bounded_page_size(0) == 1
    assert _bounded_page_size(1000) == 100
    assert _payload_rows([]) == []
    assert _payload_rows({"items": []}) == []
    assert _payload_rows({"id": 1}) == [{"id": 1}]
    assert _payload_rows(None) == []
    for helper, value in ((_safe_segment, ""), (_safe_segment, "1/2"), (_safe_endpoint, "//host")):
        try:
            helper(value)
        except ConnectWiseReadError:
            pass
        else:
            raise AssertionError(f"unsafe value accepted: {value}")
    assert ConnectWiseClient(_configured(settings)).get_ticket("bad/id").result.status == "failed"
