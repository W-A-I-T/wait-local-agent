from __future__ import annotations

import json
from dataclasses import replace

import httpx
import pytest

from wait_local_agent.autotask import (
    AutotaskClient,
    AutotaskReadError,
    _api_base_url,
    _bool_value,
    _bounded_page_size,
    _normalize_company,
    _normalize_ticket,
    _payload_rows,
    _remote_id,
    _safe_base_url,
    _safe_endpoint,
    _safe_numeric_id,
    _safe_segment,
    _write_payload,
)
from wait_local_agent.models import AutotaskWriteRequest


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


def test_autotask_writes_require_both_flags_and_create_bounded_ticket_note(settings) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.method == "POST"
        assert request.url.path.endswith("/TicketNotes")
        assert request.headers["Content-Type"] == "application/json"
        assert json.loads(request.content) == {
            "ticketID": 123,
            "description": "Investigated locally",
            "noteType": 3,
            "publish": 0,
            "title": "Investigation",
        }
        return httpx.Response(200, json={"itemId": 456, "secret": "redact"})

    blocked = AutotaskClient(
        _configured(settings, allow_http_probing=False),
        transport=httpx.MockTransport(handler),
    )
    blocked_result = blocked.execute_write(
        AutotaskWriteRequest(
            "123", "add_note", {"description": "note", "note_type": 3, "publish": 0}
        )
    )
    assert blocked.write_health().status == "blocked"
    assert "WAIT_ALLOW_HTTP_PROBING=true" in blocked_result.message
    assert "WAIT_ALLOW_WRITE_ACTIONS=true" in blocked_result.message
    assert requests == []

    active = replace(_configured(settings), allow_write_actions=True)
    client = AutotaskClient(active, transport=httpx.MockTransport(handler))
    assert client.write_health().status == "ready"
    result = client.execute_write(
        AutotaskWriteRequest(
            "123",
            "add_note",
            {
                "description": "Investigated locally",
                "note_type": 3,
                "publish": 0,
                "title": "Investigation",
            },
        )
    )
    assert result.status == "succeeded"
    assert result.remote_id == "456"
    assert client.execute_write(
        AutotaskWriteRequest(
            "123", "add_note", {"description": "unsafe", "note_type": 3, "publish": 0, "extra": 1}
        )
    ).status == "failed"


def test_autotask_write_failures_and_helpers_are_bounded(settings) -> None:
    active = replace(_configured(settings), allow_write_actions=True)
    request = AutotaskWriteRequest(
        "123", "add_note", {"description": "note", "note_type": 3, "publish": 0}
    )
    malformed = AutotaskClient(
        active, transport=httpx.MockTransport(lambda _: httpx.Response(200, text="bad"))
    ).execute_write(request)
    failed = AutotaskClient(
        active, transport=httpx.MockTransport(lambda _: httpx.Response(500))
    ).execute_write(request)
    empty = AutotaskClient(
        active, transport=httpx.MockTransport(lambda _: httpx.Response(204))
    ).execute_write(request)
    assert malformed.status == "failed"
    assert malformed.message.endswith("returned malformed JSON.")
    assert failed.status == "failed"
    assert "HTTP 500" in failed.message
    assert empty.status == "failed"
    assert "unexpected HTTP 204" in empty.message
    assert _remote_id({"itemId": 12}) == "12"
    assert _remote_id({"itemId": "13"}) == "13"
    assert _remote_id({"itemId": True}) == ""
    assert _remote_id([]) == ""
    for action, fields in (
        ("unknown", {"description": "x", "note_type": 3, "publish": 0}),
        ("add_note", {"description": "x"}),
        ("add_note", {"description": "", "note_type": 3, "publish": 0}),
        ("add_note", {"description": "x", "note_type": -1, "publish": 0}),
        ("add_note", {"description": "x", "note_type": 3, "publish": True}),
    ):
        with pytest.raises(AutotaskReadError):
            _write_payload(action, 123, fields)
    for value in ("", "abc", "0", "1" * 20):
        with pytest.raises(AutotaskReadError):
            _safe_numeric_id(value)


def test_autotask_read_contract_normalizes_tickets_and_companies(settings) -> None:
    calls: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        assert request.headers["Username"] == "api-user"
        assert request.headers["Secret"] == "api-secret"
        assert request.headers["APIIntegrationcode"] == "integration-code"
        assert "api-secret" not in str(request.url)
        assert "integration-code" not in str(request.url)
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
        if request.url.path.endswith("/Companies/3"):
            return httpx.Response(200, json={"id": 3, "companyName": "Acme", "isActive": True})
        raise AssertionError(request.url)

    client = AutotaskClient(_configured(settings), transport=httpx.MockTransport(handler))
    assert client.health().status == "ready"
    tickets = client.list_tickets(page=2, page_size=2)
    ticket = client.get_ticket("7")
    companies = client.list_companies(page_size=2)
    company = client.get_company("3")
    assert tickets.items[0]["ticket_number"] == "T-7"
    assert ticket.items[0]["company_id"] == "3"
    assert companies.items[0] == {"id": "3", "name": "Acme", "active": True}
    assert company.items[0]["name"] == "Acme"
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

    for status_code, phrase in ((403, "forbidden"), (429, "rate limited")):
        limited = AutotaskClient(
            _configured(settings),
            transport=httpx.MockTransport(
                lambda request, status_code=status_code: httpx.Response(status_code)
            ),
        ).list_tickets()
        assert phrase in limited.result.message

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
    with pytest.raises(AutotaskReadError):
        _bounded_page_size(0)
    assert _bounded_page_size(1000) == 100
    assert AutotaskClient(_configured(settings)).list_tickets(page=0).result.status == "failed"
    with pytest.raises(AutotaskReadError):
        _safe_base_url("https://zone.test?secret=leak")
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


def test_autotask_security_and_normalization_edges(settings) -> None:
    assert AutotaskClient(_configured(settings, allow_http_probing=False)).health().status == "blocked"
    assert AutotaskClient(
        _configured(settings),
        transport=httpx.MockTransport(lambda request: httpx.Response(500)),
    ).health().status == "failed"
    assert (
        AutotaskClient(replace(_configured(settings), autotask_secret=""))
        .list_tickets()
        .result.status
        == "not_configured"
    )
    assert AutotaskClient(_configured(settings)).get_company("bad/id").result.status == "failed"
    with pytest.raises(AutotaskReadError):
        AutotaskClient(replace(_configured(settings), autotask_secret=""))._get("Tickets/query")
    for value in ("\x00", "not-a-url"):
        with pytest.raises(AutotaskReadError):
            _safe_base_url(value)
    for value in ("", "../Tickets", "Tickets?x=1"):
        with pytest.raises(AutotaskReadError):
            _safe_endpoint(value)
    with pytest.raises(AutotaskReadError):
        _safe_segment("x" * 65)
    assert _payload_rows({"unexpected": True}) == []
    normalized_ticket = _normalize_ticket(
        {
            "ticketID": 8,
            "status": {"displayValue": "Open"},
            "priority": {"value": "High"},
        }
    )
    assert normalized_ticket is not None and normalized_ticket["status"] == "Open"
    normalized_company = _normalize_company({"companyID": 3, "active": "false"})
    assert normalized_company is not None and normalized_company["active"] is False
    assert _bool_value(None) is False
    assert _bool_value(1) is True


def test_autotask_write_and_read_failure_edges_are_explicit(settings) -> None:
    configured = _configured(settings)
    request = AutotaskWriteRequest(
        "123", "add_note", {"description": "note", "note_type": 3, "publish": 0}
    )
    missing = replace(configured, autotask_secret="", allow_write_actions=True)
    assert AutotaskClient(missing).write_health().status == "not_configured"
    assert AutotaskClient(missing).execute_write(request).status == "not_configured"
    assert AutotaskClient(settings).get_ticket("1").result.status == "blocked"

    ready = replace(configured, allow_write_actions=True)
    client = AutotaskClient(settings)
    with pytest.raises(AutotaskReadError):
        client._post("TicketNotes", {})
    with pytest.raises(AutotaskReadError):
        AutotaskClient(replace(ready, allow_write_actions=False))._post("TicketNotes", {})
    with pytest.raises(AutotaskReadError):
        AutotaskClient(replace(ready, autotask_secret=""))._post("TicketNotes", {})

    def protocol_failure(request: httpx.Request) -> httpx.Response:
        raise httpx.ProtocolError("protocol failure")

    assert AutotaskClient(
        ready, transport=httpx.MockTransport(protocol_failure)
    ).execute_write(request).status == "failed"
    assert AutotaskClient(
        ready,
        transport=httpx.MockTransport(
            lambda request: (_ for _ in ()).throw(httpx.ReadTimeout("timeout"))
        ),
    ).execute_write(request).status == "failed"

    empty = AutotaskClient(
        ready, transport=httpx.MockTransport(lambda request: httpx.Response(200))
    ).execute_write(request)
    assert empty.status == "succeeded"
    assert empty.remote_id == ""
    with pytest.raises(AutotaskReadError):
        _write_payload("add_note", 123, {"description": "x", "note_type": 3, "publish": 0, "title": "\x00"})
    with pytest.raises(AutotaskReadError):
        _write_payload("add_note", 123, {"description": "x", "note_type": 3, "publish": 0, "title": "x" * 251})
    assert _remote_id({"itemId": -1}) == ""
    assert _remote_id({"itemId": "not-numeric"}) == ""
    assert _normalize_company({}) is None
    normalized = _normalize_ticket({"id": 1, "status": {}})
    assert normalized is not None and normalized["status"] == ""
