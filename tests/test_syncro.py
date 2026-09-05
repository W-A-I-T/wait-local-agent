from __future__ import annotations

from dataclasses import replace

import httpx

from wait_local_agent.syncro import (
    SyncroClient,
    SyncroReadError,
    _api_base_url,
    _comment_meta,
    _comment_params,
    _http_error_message,
    _list_params,
    _normalize_comment,
    _normalize_customer,
    _normalize_ticket,
    _payload_rows,
    _remote_id,
    _safe_base_url,
    _safe_endpoint,
    _safe_filter,
    _safe_id,
    _write_payload,
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


def test_syncro_writes_require_both_flags_and_credentials(settings) -> None:
    from wait_local_agent.models import SyncroWriteRequest

    request = SyncroWriteRequest(
        ticket_id="42",
        action_type="add_note",
        fields={"subject": "Internal", "body": "Reviewed"},
    )
    client = SyncroClient(
        replace(_settings(settings), allow_write_actions=False),
        transport=httpx.MockTransport(lambda request: httpx.Response(500)),
    )
    assert client.write_health().status == "blocked"
    assert client.execute_write(request).status == "blocked"
    missing = SyncroClient(
        replace(_settings(settings), allow_write_actions=True, syncro_api_token=""),
    )
    assert missing.write_health().status == "not_configured"
    assert missing.execute_write(request).status == "not_configured"


def test_syncro_add_note_uses_documented_comment_endpoint(settings) -> None:
    from wait_local_agent.models import SyncroWriteRequest

    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.method == "POST"
        assert request.url.path == "/api/v1/tickets/42/comment"
        assert request.headers["authorization"] == "Bearer syncro-token"
        assert request.read().decode() == (
            '{"subject":"Internal","body":"Reviewed\\nby WAIT",'
            '"hidden":true,"do_not_email":true}'
        )
        return httpx.Response(201, json={"comment": {"id": 99}})

    client = SyncroClient(
        replace(_settings(settings), allow_write_actions=True),
        transport=httpx.MockTransport(handler),
    )
    result = client.execute_write(
        SyncroWriteRequest(
            ticket_id="42",
            action_type="add_note",
            fields={"subject": " Internal ", "body": " Reviewed\nby WAIT "},
        )
    )
    assert result.status == "succeeded"
    assert result.endpoint == "tickets/42/comment"
    assert result.status_code == 201
    assert result.remote_id == "99"
    assert len(requests) == 1


def test_syncro_write_validation_and_failures_are_sanitized(settings) -> None:
    from wait_local_agent.models import SyncroWriteRequest

    active = replace(_settings(settings), allow_write_actions=True)
    for status, expected in ((401, "unauthorized"), (403, "forbidden"), (429, "rate limited")):
        result = SyncroClient(
            active,
            transport=httpx.MockTransport(lambda request, status=status: httpx.Response(status)),
        ).execute_write(
            SyncroWriteRequest("42", "add_note", {"subject": "Internal", "body": "Reviewed"})
        )
        assert result.status == "failed"
        assert expected in result.message
        assert "syncro-token" not in result.message
    malformed = SyncroClient(
        active,
        transport=httpx.MockTransport(lambda request: httpx.Response(200, content=b"bad")),
    ).execute_write(SyncroWriteRequest("42", "add_note", {"subject": "Internal", "body": "Reviewed"}))
    assert malformed.status == "failed"
    assert malformed.message.endswith("returned malformed JSON.")
    assert _remote_id({"comment": {"comment_id": 8}}) == "8"
    invalid = (
        ("bad", {"subject": "Internal", "body": "Reviewed"}),
        ("add_note", {"subject": "Internal", "body": "Reviewed", "secret": "no"}),
        ("add_note", {"subject": "", "body": "Reviewed"}),
        ("add_note", {"subject": "Internal", "body": "Reviewed", "hidden": "yes"}),
    )
    for action_type, fields in invalid:
        try:
            _write_payload(action_type, fields)
        except SyncroReadError:
            pass
        else:
            raise AssertionError("invalid Syncro write was accepted")


def test_syncro_write_boundaries_cover_transport_and_payload_edges(settings) -> None:
    from wait_local_agent.models import SyncroWriteRequest

    active = replace(_settings(settings), allow_write_actions=True)
    assert SyncroClient(active).write_health().status == "ready"
    assert SyncroClient(replace(active, allow_http_probing=False)).write_health().status == "blocked"
    request = SyncroWriteRequest("42", "add_note", {"subject": "Internal", "body": "Reviewed"})
    for blocked_settings, expected in (
        (replace(active, allow_http_probing=False), "WAIT_ALLOW_HTTP_PROBING"),
        (replace(active, allow_write_actions=False), "WAIT_ALLOW_WRITE_ACTIONS"),
        (replace(active, syncro_api_token=""), "WAIT_SYNCRO_API_TOKEN"),
    ):
        try:
            SyncroClient(blocked_settings)._post("tickets/42/comment", {"subject": "x"})
        except SyncroReadError as exc:
            assert expected in str(exc)
        else:
            raise AssertionError("blocked Syncro POST was accepted")

    def connect_failure(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("token=must-not-leak", request=request)

    disconnected = SyncroClient(
        active,
        transport=httpx.MockTransport(connect_failure),
    ).execute_write(request)
    assert disconnected.status == "failed"
    assert disconnected.message.endswith("before receiving a response.")
    assert "token=" not in disconnected.message

    generic = SyncroClient(
        active,
        transport=httpx.MockTransport(
            lambda request: (_ for _ in ()).throw(httpx.ReadError("read failed", request=request))
        ),
    ).execute_write(request)
    assert generic.message == "Syncro POST request failed."

    unexpected = SyncroClient(
        active,
        transport=httpx.MockTransport(lambda request: httpx.Response(202)),
    ).execute_write(request)
    assert unexpected.status == "failed"
    assert "unexpected HTTP 202" in unexpected.message

    empty = SyncroClient(
        active,
        transport=httpx.MockTransport(lambda request: httpx.Response(200, content=b"")),
    ).execute_write(request)
    assert empty.status == "succeeded"
    assert empty.remote_id == ""

    invalid_fields = (
        {"subject": "x" * 251, "body": "ok"},
        {"subject": "ok", "body": "x" * 32_001},
        {"subject": "ok\x00", "body": "ok"},
        {"subject": "ok", "body": "ok", "do_not_email": 1},
    )
    for fields in invalid_fields:
        try:
            _write_payload("add_note", fields)
        except SyncroReadError:
            pass
        else:
            raise AssertionError("invalid Syncro comment edge was accepted")
    assert _remote_id([{"nested": {"comment_id": 7}}]) == "7"
    assert SyncroClient(active).list_customers(business_name="x\ny").result.status == "failed"
    assert _remote_id({"nested": [{"nothing": 1}]}) == ""


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


def test_syncro_ticket_comments_use_documented_paginated_contract(settings) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.method == "GET"
        assert request.url.path == "/api/v1/tickets/42/comments"
        assert request.headers["authorization"] == "Bearer syncro-token"
        assert dict(request.url.params) == {
            "page": "2",
            "per_page": "5",
            "sort_by": "updated_at",
            "sort_direction": "DESC",
            "comment_format": "plaintext",
            "created_after": "2026-08-01",
            "created_before": "2026-08-10",
        }
        return httpx.Response(
            200,
            json={
                "comments": [
                    {
                        "id": 9,
                        "created_at": "2026-08-02T10:00:00Z",
                        "updated_at": "2026-08-02T10:01:00Z",
                        "ticket_id": 42,
                        "subject": "Internal review",
                        "body": "Reviewed locally",
                        "tech": "Taylor",
                        "hidden": True,
                        "user_id": 7,
                        "is_rich_text": False,
                    },
                    {"subject": "discarded without an id"},
                ],
                "meta": {"total_pages": 3, "page": 2, "per_page": 5},
            },
        )

    response = SyncroClient(
        _settings(settings), transport=httpx.MockTransport(handler)
    ).list_ticket_comments(
        "42",
        page=2,
        per_page=5,
        sort_by="updated_at",
        sort_direction="desc",
        created_after="2026-08-01",
        created_before="2026-08-10",
    )

    assert response.result.status == "ready"
    assert response.result.count == 1
    assert response.items[0] == {
        "id": "9",
        "ticket_id": "42",
        "created_at": "2026-08-02T10:00:00Z",
        "updated_at": "2026-08-02T10:01:00Z",
        "subject": "Internal review",
        "body": "Reviewed locally",
        "tech": "Taylor",
        "hidden": True,
        "user_id": 7,
        "is_rich_text": False,
    }
    assert response.meta == {"total_pages": 3, "page": 2, "per_page": 5}
    assert len(requests) == 1


def test_syncro_ticket_comments_fail_closed_and_bound_inputs(settings) -> None:
    active = _settings(settings)
    blocked = SyncroClient(
        replace(active, allow_http_probing=False),
        transport=httpx.MockTransport(lambda request: httpx.Response(500)),
    ).list_ticket_comments("42")
    missing = SyncroClient(
        replace(active, syncro_api_token=""),
        transport=httpx.MockTransport(lambda request: httpx.Response(500)),
    ).list_ticket_comments("42")
    assert blocked.result.status == "blocked"
    assert missing.result.status == "not_configured"

    invalid = (
        {"ticket_id": "not-a-number"},
        {"page": 0},
        {"per_page": 101},
        {"sort_by": "created"},
        {"sort_direction": "sideways"},
        {"created_after": "bad\nvalue"},
    )
    for kwargs in invalid:
        ticket_id = str(kwargs.pop("ticket_id", "42"))
        result = SyncroClient(active).list_ticket_comments(ticket_id, **kwargs)
        assert result.result.status == "failed"
        assert result.items == []
        assert result.meta == {}

    unauthorized = SyncroClient(
        active,
        transport=httpx.MockTransport(lambda request: httpx.Response(401)),
    ).list_ticket_comments("42")
    malformed = SyncroClient(
        active,
        transport=httpx.MockTransport(lambda request: httpx.Response(200, content=b"bad")),
    ).list_ticket_comments("42")
    assert "unauthorized" in unauthorized.result.message
    assert malformed.result.message.endswith("returned malformed JSON.")
    assert "syncro-token" not in unauthorized.result.message

    assert _comment_params(
        page=1,
        per_page=10,
        sort_by="created_at",
        sort_direction="ASC",
        created_after=None,
        created_before=None,
    ) == {
        "page": 1,
        "per_page": 10,
        "sort_by": "created_at",
        "sort_direction": "ASC",
        "comment_format": "plaintext",
    }
    normalized = _normalize_comment({"comment_id": 4, "body": "x" * 32_100})
    assert normalized is not None and normalized["body"] == "x" * 32_000
    assert _normalize_comment({}) is None
    assert _comment_meta({"meta": {"total_pages": 2, "page": 1, "per_page": 10, "bad": -1}}) == {
        "total_pages": 2,
        "page": 1,
        "per_page": 10,
    }
    assert _comment_meta({"meta": {"page": True, "per_page": "10"}}) == {}


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
    def unexpected_request(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("invalid Syncro input must not contact a provider")

    invalid_client = SyncroClient(active, transport=httpx.MockTransport(unexpected_request))
    invalid_page = SyncroClient(active).list_tickets(page=0)
    invalid_filter = invalid_client.list_tickets(query="\n")
    invalid_customer_filter = invalid_client.list_customers(business_name="x\n")
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
    assert _comment_meta([]) == {}

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
