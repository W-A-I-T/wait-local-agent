from __future__ import annotations

import base64
import json
from dataclasses import replace

import httpx
import pytest

from wait_local_agent.connectwise import (
    ConnectWiseClient,
    ConnectWiseReadError,
    ConnectWiseWriteResult,
    _api_base_url,
    _list_params,
    _normalize_company,
    _normalize_ticket,
    _payload_rows,
    _safe_endpoint,
    _safe_segment,
    _safe_version,
    _write_endpoint_and_patch,
)
from wait_local_agent.models import ConnectWiseWriteRequest


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


def test_connectwise_writes_require_both_flags_and_never_probe_when_blocked(settings) -> None:
    requests: list[httpx.Request] = []

    def blocked_handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(500)

    client = ConnectWiseClient(
        _settings(settings, allow_http_probing=False),
        transport=httpx.MockTransport(blocked_handler),
    )
    request = ConnectWiseWriteRequest("42", "update_status", {"status_id": 7})

    health = client.write_health()
    result = client.execute_write(request)

    assert health.status == "blocked"
    assert "WAIT_ALLOW_HTTP_PROBING=true" in health.message
    assert "WAIT_ALLOW_WRITE_ACTIONS=true" in health.message
    assert result.status == "blocked"
    assert requests == []

    write_disabled = ConnectWiseClient(
        replace(_settings(settings), allow_write_actions=False),
        transport=httpx.MockTransport(blocked_handler),
    )
    assert write_disabled.write_health().status == "blocked"
    assert "WAIT_ALLOW_WRITE_ACTIONS=true" in write_disabled.write_health().message


def test_connectwise_writes_use_allowlisted_patch_and_sanitize_response(settings) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.method == "PATCH"
        assert request.url.path.endswith("/service/tickets/42")
        assert request.headers["content-type"] == "application/json"
        assert json.loads(request.content) == [
            {"op": "replace", "path": "/summary", "value": "Updated summary"},
            {"op": "replace", "path": "/status/id", "value": 7},
            {"op": "replace", "path": "/owner/id", "value": 9},
        ]
        return httpx.Response(200, json={"id": 42, "private": "do-not-store"})

    active = replace(_settings(settings), allow_write_actions=True)
    client = ConnectWiseClient(active, transport=httpx.MockTransport(handler))
    assert client.write_health().status == "ready"
    result = client.execute_write(
        ConnectWiseWriteRequest(
            "42",
            "update_ticket_fields",
            {"summary": "Updated summary", "status_id": 7, "owner_id": 9},
            approval_request_id=3,
        )
    )

    assert result == ConnectWiseWriteResult(
        "succeeded",
        "ConnectWise PSA update_ticket_fields write succeeded.",
        "update_ticket_fields",
        "42",
        endpoint="service/tickets/42",
        status_code=200,
        remote_id="42",
    )
    assert len(requests) == 1


def test_connectwise_write_failures_and_empty_success_are_bounded(settings) -> None:
    active = replace(_settings(settings), allow_write_actions=True)
    request = ConnectWiseWriteRequest("42", "update_status", {"status_id": 7})
    http_failure = ConnectWiseClient(
        active,
        transport=httpx.MockTransport(lambda request: httpx.Response(403)),
    ).execute_write(request)
    malformed = ConnectWiseClient(
        active,
        transport=httpx.MockTransport(lambda request: httpx.Response(200, content=b"bad")),
    ).execute_write(request)
    empty = ConnectWiseClient(
        active,
        transport=httpx.MockTransport(lambda request: httpx.Response(204)),
    ).execute_write(request)
    no_remote_id = ConnectWiseClient(
        active,
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={})),
    ).execute_write(request)
    non_object_remote = ConnectWiseClient(
        active,
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=[])),
    ).execute_write(request)

    def disconnected(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("private key", request=request)

    disconnected_result = ConnectWiseClient(
        active,
        transport=httpx.MockTransport(disconnected),
    ).execute_write(request)

    def patch_http_error(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadError("read failed", request=request)

    generic_failure = ConnectWiseClient(
        active,
        transport=httpx.MockTransport(patch_http_error),
    ).execute_write(request)

    assert http_failure.status == "failed"
    assert "HTTP 403" in http_failure.message
    assert malformed.status == "failed"
    assert malformed.message.endswith("returned malformed JSON.")
    assert empty.status == "succeeded"
    assert empty.status_code == 204
    assert no_remote_id.status == "succeeded"
    assert no_remote_id.remote_id == ""
    assert non_object_remote.remote_id == ""
    assert disconnected_result.status == "failed"
    assert disconnected_result.message.endswith("before receiving a response.")
    assert "private key" not in disconnected_result.message
    assert generic_failure.message == "ConnectWise PSA request failed."


def test_connectwise_write_verification_compares_only_exposed_fields(settings) -> None:
    get_calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "PATCH":
            return httpx.Response(200, json={"id": 42})
        if request.method == "GET":
            get_calls.append(request.url.path)
            return httpx.Response(
                200,
                json={
                    "id": 42,
                    "summary": " Updated summary ",
                    "initialDescription": "DETAILS",
                    "status": {"name": "Open"},
                    "priority": {"name": "High"},
                },
            )
        return httpx.Response(404)

    active = replace(_settings(settings), allow_write_actions=True)
    client = ConnectWiseClient(active, transport=httpx.MockTransport(handler))
    request = ConnectWiseWriteRequest(
        "42",
        "update_ticket_fields",
        {"summary": "updated summary", "description": "details"},
    )
    result = client.execute_write(request)

    assert result.status == "succeeded"
    detail: dict[str, object] = {}
    assert client.verify_write(request, result, detail=detail) == "verified"
    assert detail["fields"] == {
        "summary": {"comparison": "matched"},
        "description": {"comparison": "matched"},
    }

    mismatch = ConnectWiseWriteRequest("42", "update_ticket_fields", {"summary": "other"})
    mismatch_result = client.execute_write(mismatch)
    assert client.verify_write(mismatch, mismatch_result) == "unverified"

    id_request = ConnectWiseWriteRequest("42", "update_status", {"status_id": 7})
    id_result = client.execute_write(id_request)
    assert client.verify_write(id_request, id_result) == "submitted"

    mixed_request = ConnectWiseWriteRequest(
        "42", "update_ticket_fields", {"summary": "updated summary", "owner_id": 9}
    )
    mixed_result = client.execute_write(mixed_request)
    assert client.verify_write(mixed_request, mixed_result) == "submitted"
    assert any(path.endswith("/service/tickets/42") for path in get_calls)


def test_connectwise_write_verification_get_failure_is_unverified(settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "PATCH":
            return httpx.Response(200, json={"id": 42})
        return httpx.Response(503)

    active = replace(_settings(settings), allow_write_actions=True)
    client = ConnectWiseClient(active, transport=httpx.MockTransport(handler))
    request = ConnectWiseWriteRequest("42", "update_ticket_fields", {"summary": "updated"})
    result = client.execute_write(request)

    assert result.status == "succeeded"
    assert client.verify_write(request, result) == "unverified"


def test_connectwise_write_validation_and_missing_configuration(settings) -> None:
    active = replace(_settings(settings), allow_write_actions=True)
    missing = ConnectWiseClient(
        replace(active, connectwise_client_id=""),
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={})),
    ).execute_write(ConnectWiseWriteRequest("42", "update_status", {"status_id": 7}))
    assert missing.status == "not_configured"
    assert ConnectWiseClient(
        replace(active, connectwise_client_id=""),
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={})),
    ).write_health().status == "not_configured"

    invalids = [
        ConnectWiseWriteRequest("42", "bad", {"summary": "x"}),
        ConnectWiseWriteRequest("42/other", "update_status", {"status_id": 7}),
        ConnectWiseWriteRequest("42", "update_status", {}),
        ConnectWiseWriteRequest("42", "update_status", {"summary": "x"}),
        ConnectWiseWriteRequest("42", "assign_technician", {"summary": "x"}),
        ConnectWiseWriteRequest("42", "update_ticket_fields", {"unknown": "x"}),
        ConnectWiseWriteRequest("42", "update_ticket_fields", {"summary": "\n"}),
    ]
    for request in invalids:
        result = ConnectWiseClient(active).execute_write(request)
        assert result.status == "failed"

    assert _write_endpoint_and_patch(
        ConnectWiseWriteRequest("42", "assign_technician", {"team_id": 5})
    )[1] == [{"op": "replace", "path": "/team/id", "value": 5}]
    with pytest.raises(ConnectWiseReadError, match="must be text"):
        _write_endpoint_and_patch(
            ConnectWiseWriteRequest("42", "update_ticket_fields", {"summary": True})
        )
    with pytest.raises(ConnectWiseReadError, match="invalid"):
        _write_endpoint_and_patch(
            ConnectWiseWriteRequest("42", "update_ticket_fields", {"summary": "\n"})
        )
    assert _write_endpoint_and_patch(
        ConnectWiseWriteRequest("42", "update_ticket_fields", {"description": "details"})
    )[1][0]["path"] == "/initialDescription"
    with pytest.raises(ConnectWiseReadError, match="WAIT_ALLOW_HTTP_PROBING"):
        ConnectWiseClient(replace(active, allow_http_probing=False))._patch(
            "service/tickets/42", []
        )
    with pytest.raises(ConnectWiseReadError, match="WAIT_ALLOW_WRITE_ACTIONS"):
        ConnectWiseClient(replace(active, allow_write_actions=False))._patch(
            "service/tickets/42", []
        )
    with pytest.raises(ConnectWiseReadError, match="credentials"):
        ConnectWiseClient(replace(active, connectwise_client_id=""))._patch(
            "service/tickets/42", []
        )


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


def test_connectwise_read_response_metadata_shape_and_caps(settings) -> None:
    def read(payload: object, status_code: int = 200, headers: dict[str, str] | None = None):
        return ConnectWiseClient(
            _settings(settings),
            transport=httpx.MockTransport(
                lambda request: httpx.Response(status_code, json=payload, headers=headers)
            ),
        ).list_tickets()

    full = read(
        [
            {"id": 1, "summary": "one"},
            {"id": 2, "summary": "two"},
        ]
    )
    dropped = read([{"summary": "missing id"}, "not a mapping"])
    empty = read([])
    scalar = read("not a list or envelope")
    wrong_object = read({"unexpected": []})
    redirect = read([], status_code=302)
    throttled = read([], status_code=429, headers={"Retry-After": "9"})
    failed = read([], status_code=503)
    expired_date = read(
        [], status_code=503, headers={"Retry-After": "Thu, 01 Jan 1970 00:00:00 GMT"}
    )

    assert (full.raw_count, full.dropped_count, full.http_status) == (2, 0, 200)
    assert dropped.result.status == "ready"
    assert (dropped.raw_count, dropped.dropped_count, dropped.items) == (2, 2, [])
    assert empty.result.status == "ready"
    assert (empty.raw_count, empty.dropped_count) == (0, 0)
    assert scalar.result.status == "failed"
    assert wrong_object.result.status == "failed"
    assert redirect.result.status == "failed"
    assert redirect.http_status == 302
    assert throttled.result.status == "failed"
    assert throttled.http_status == 429
    assert throttled.retry_after == 9.0
    assert failed.result.status == "failed"
    assert failed.http_status == 503
    assert expired_date.retry_after == 0.0

    long = "x" * 10_000
    capped = read(
        [
            {
                "id": "T-long",
                "summary": long,
                "initialDescription": long,
                "status": {"name": long},
                "priority": {"name": long},
                "company": {"id": "C-1", "name": long},
            }
        ]
    )
    item = capped.items[0]
    assert len(item["summary"]) == 512
    assert len(item["description"]) == 8192
    assert len(item["status"]) == 128
    assert len(item["priority"]) == 128
    assert len(item["company_name"]) == 512


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
