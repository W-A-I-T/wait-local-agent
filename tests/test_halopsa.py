from __future__ import annotations

import json
from pathlib import Path

import httpx

from wait_local_agent.config import Settings
from wait_local_agent.halopsa import (
    HaloPSAReadClient,
    _normalize_client,
    _normalize_note,
    _remote_id,
    _safe_endpoint,
)
from wait_local_agent.models import HaloAsset, HaloCategory, HaloClient, HaloNote, HaloWriteRequest


def _settings(
    tmp_path: Path,
    *,
    allow_http_probing: bool = True,
    allow_write_actions: bool = False,
    base_url: str = "https://halo.example.test",
    client_id: str = "client-id",
    client_secret: str = "secret",
    tenant: str = "tenant",
    token_url: str = "",
) -> Settings:
    return Settings(
        data_path=tmp_path / "state.db",
        allowed_doc_root=Path("examples/sample_docs"),
        allow_write_actions=allow_write_actions,
        allow_http_probing=allow_http_probing,
        allow_cloud_fallback=False,
        allow_llm_inference=False,
        local_model_provider="deterministic",
        local_model_base_url="http://127.0.0.1:11434/v1",
        local_model_name="llama3.1",
        local_model_timeout_seconds=20.0,
        vector_backend="sqlite",
        halopsa_base_url=base_url,
        halopsa_client_id=client_id,
        halopsa_client_secret=client_secret,
        halopsa_tenant=tenant,
        halopsa_token_url=token_url,
        halopsa_ticket_write_endpoint="Ticket",
        halopsa_action_write_endpoint="Actions",
    )


def test_halopsa_reads_block_without_http_flag(tmp_path: Path) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(500)

    client = HaloPSAReadClient(
        _settings(tmp_path, allow_http_probing=False),
        transport=httpx.MockTransport(handler),
    )

    health = client.health()
    tickets = client.list_tickets()

    assert health.status == "blocked"
    assert tickets.result.status == "blocked"
    assert tickets.items == []
    assert requests == []


def test_halopsa_reads_report_missing_credentials(tmp_path: Path) -> None:
    client = HaloPSAReadClient(
        _settings(tmp_path, client_secret="", tenant=""),
        transport=httpx.MockTransport(lambda request: httpx.Response(500)),
    )

    result = client.health()

    assert result.status == "not_configured"
    assert "WAIT_HALOPSA_CLIENT_SECRET" in result.message
    assert "WAIT_HALOPSA_TENANT" in result.message


def test_halopsa_single_reads_share_blocked_and_missing_states(tmp_path: Path) -> None:
    blocked = HaloPSAReadClient(
        _settings(tmp_path, allow_http_probing=False),
        transport=httpx.MockTransport(lambda request: httpx.Response(500)),
    ).get_ticket("42")
    missing = HaloPSAReadClient(
        _settings(tmp_path, client_id=""),
        transport=httpx.MockTransport(lambda request: httpx.Response(500)),
    ).get_ticket("42")

    assert blocked.result.status == "blocked"
    assert missing.result.status == "not_configured"


def test_halopsa_ticket_list_uses_token_auth_and_pagination(tmp_path: Path) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/auth/token"):
            assert b"client_id=client-id" in request.content
            assert b"client_secret=secret" in request.content
            return httpx.Response(200, json={"access_token": "token-123"})
        assert request.headers["authorization"] == "Bearer token-123"
        assert request.url.path == "/api/Ticket"
        assert request.url.params["page_no"] == "2"
        assert request.url.params["page_size"] == "100"
        return httpx.Response(
            200,
            json={
                "tickets": [
                    {
                        "id": 42,
                        "summary": "Printer offline",
                        "status": "Open",
                        "priority": "High",
                        "client_id": 7,
                        "client_name": "Northwind",
                    }
                ]
            },
        )

    client = HaloPSAReadClient(
        _settings(tmp_path),
        transport=httpx.MockTransport(handler),
    )

    response = client.list_tickets(page=2, page_size=500)

    assert response.result.status == "ready"
    assert response.result.count == 1
    assert response.items[0].id == "42"
    assert len(requests) == 2


def test_halopsa_uses_custom_token_url_and_normalizes_read_shapes(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth2/token":
            return httpx.Response(200, json={"access_token": "token-123"})
        if request.url.path == "/api/Ticket/42/Actions":
            return httpx.Response(
                200,
                json={"actions": [{"id": "n1", "note": "Called user", "private": True}]},
            )
        if request.url.path == "/api/Client":
            return httpx.Response(200, json={"clients": [{"id": "c1", "name": "Contoso"}]})
        if request.url.path == "/api/Asset":
            assert request.url.params["client_id"] == "c1"
            return httpx.Response(200, json={"assets": [{"id": "a1", "name": "Laptop"}]})
        if request.url.path == "/api/Category":
            return httpx.Response(200, json=[{"id": "cat1", "name": "Access"}])
        return httpx.Response(404)

    client = HaloPSAReadClient(
        _settings(tmp_path, token_url="https://auth.example.test/oauth2/token"),
        transport=httpx.MockTransport(handler),
    )

    notes = client.list_ticket_notes("42")
    clients = client.list_clients()
    assets = client.list_client_assets("c1")
    categories = client.list_categories()

    assert isinstance(notes.items[0], HaloNote)
    assert isinstance(clients.items[0], HaloClient)
    assert isinstance(categories.items[0], HaloCategory)
    assert notes.items[0].ticket_id == "42"
    assert clients.items[0].id == "c1"
    assert assets.items[0].id == "a1"
    assert categories.items[0].name == "Access"


def test_halopsa_health_and_failures_are_normalized(tmp_path: Path) -> None:
    def token_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"access_token": "token-123"})

    ready = HaloPSAReadClient(
        _settings(tmp_path),
        transport=httpx.MockTransport(token_handler),
    ).health()

    def bad_token_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"token": "missing"})

    failed_token = HaloPSAReadClient(
        _settings(tmp_path),
        transport=httpx.MockTransport(bad_token_handler),
    ).health()

    def bad_get_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/auth/token"):
            return httpx.Response(200, json={"access_token": "token-123"})
        return httpx.Response(503, json={"error": "unavailable"})

    failed_get = HaloPSAReadClient(
        _settings(tmp_path),
        transport=httpx.MockTransport(bad_get_handler),
    ).list_tickets()

    def malformed_get_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/auth/token"):
            return httpx.Response(200, json={"access_token": "token-123"})
        return httpx.Response(200, content=b"not json")

    malformed = HaloPSAReadClient(
        _settings(tmp_path),
        transport=httpx.MockTransport(malformed_get_handler),
    ).list_tickets()

    def malformed_token_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not json")

    malformed_token = HaloPSAReadClient(
        _settings(tmp_path),
        transport=httpx.MockTransport(malformed_token_handler),
    ).health()

    assert ready.status == "ready"
    assert failed_token.status == "failed"
    assert malformed_token.status == "failed"
    assert failed_get.result.status == "failed"
    assert malformed.result.status == "failed"
    assert "malformed JSON" in malformed.result.message


def test_halopsa_skips_malformed_rows(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/auth/token"):
            return httpx.Response(200, json={"access_token": "token-123"})
        return httpx.Response(
            200,
            json=json.loads('{"tickets":[{"summary":"missing id"},{"id":"TCK-1"}]}'),
        )

    response = HaloPSAReadClient(
        _settings(tmp_path),
        transport=httpx.MockTransport(handler),
    ).list_tickets()

    assert response.result.count == 1
    assert response.items[0].id == "TCK-1"


def test_halopsa_single_payloads_and_boolean_variants(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/auth/token"):
            return httpx.Response(200, json={"access_token": "token-123"})
        if request.url.path == "/api/Ticket/42":
            return httpx.Response(200, json={"faultid": 42, "title": "Single ticket"})
        if request.url.path == "/api/Ticket/string/Actions":
            return httpx.Response(200, json={"actions": [{"id": "n1", "hiddenfromuser": "yes"}]})
        if request.url.path == "/api/Ticket/int/Actions":
            return httpx.Response(200, json={"actions": [{"id": "n2", "hiddenfromuser": 1}]})
        if request.url.path == "/api/Asset":
            return httpx.Response(200, json={"assets": [{"name": "missing id"}, {"id": "a1"}]})
        if request.url.path == "/api/Category":
            return httpx.Response(200, json={"categories": [{"name": "missing id"}]})
        if request.url.path == "/api/Client":
            return httpx.Response(200, json="not a row container")
        return httpx.Response(404)

    client = HaloPSAReadClient(
        _settings(tmp_path, base_url="https://halo.example.test/api"),
        transport=httpx.MockTransport(handler),
    )

    ticket = client.get_ticket("42")
    string_note = client.list_ticket_notes("string")
    int_note = client.list_ticket_notes("int")
    assets = client.list_client_assets("c1")
    categories = client.list_categories()
    clients = client.list_clients()

    assert ticket.items[0].id == "42"
    assert isinstance(string_note.items[0], HaloNote)
    assert isinstance(int_note.items[0], HaloNote)
    assert string_note.items[0].is_private is True
    assert int_note.items[0].is_private is True
    assert isinstance(assets.items[0], HaloAsset)
    assert assets.items[0].id == "a1"
    assert categories.items == []
    assert clients.items == []


def test_halopsa_writes_require_both_side_effect_flags(tmp_path: Path) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(500)

    client = HaloPSAReadClient(
        _settings(tmp_path, allow_http_probing=True, allow_write_actions=False),
        transport=httpx.MockTransport(handler),
    )

    result = client.execute_write(HaloWriteRequest("TCK-1", "add_note", {"note": "hi"}, 1))

    assert result.status == "blocked"
    assert "WAIT_ALLOW_WRITE_ACTIONS=true" in result.message
    assert requests == []


def test_halopsa_write_health_reports_missing_credentials(tmp_path: Path) -> None:
    result = HaloPSAReadClient(
        _settings(tmp_path, allow_write_actions=True, client_secret=""),
        transport=httpx.MockTransport(lambda request: httpx.Response(500)),
    ).write_health()

    assert result.status == "not_configured"
    assert "WAIT_HALOPSA_CLIENT_SECRET" in result.message


def test_halopsa_write_health_ready_and_failed(tmp_path: Path) -> None:
    ready = HaloPSAReadClient(
        _settings(tmp_path, allow_write_actions=True),
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"access_token": "t"})
        ),
    ).write_health()
    failed = HaloPSAReadClient(
        _settings(tmp_path, allow_write_actions=True),
        transport=httpx.MockTransport(lambda request: httpx.Response(500, json={"error": "no"})),
    ).write_health()

    assert ready.status == "ready"
    assert failed.status == "failed"


def test_halopsa_write_reports_missing_credentials(tmp_path: Path) -> None:
    result = HaloPSAReadClient(
        _settings(tmp_path, allow_write_actions=True, client_id=""),
        transport=httpx.MockTransport(lambda request: httpx.Response(500)),
    ).execute_write(HaloWriteRequest("TCK-1", "add_note", {"note": "hi"}, 1))

    assert result.status == "not_configured"
    assert "WAIT_HALOPSA_CLIENT_ID" in result.message


def test_halopsa_add_note_and_response_payload_mapping(tmp_path: Path) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/auth/token"):
            return httpx.Response(200, json={"access_token": "token-123"})
        payload = json.loads(request.content.decode())
        assert request.url.path == "/api/Actions"
        assert payload[0]["ticket_id"] == "TCK-1"
        assert payload[0]["faultid"] == "TCK-1"
        assert payload[0]["note"] in {"Internal note", "Client response"}
        return httpx.Response(200, json={"id": "A-1"})

    client = HaloPSAReadClient(
        _settings(tmp_path, allow_write_actions=True),
        transport=httpx.MockTransport(handler),
    )

    note = client.execute_write(HaloWriteRequest("TCK-1", "add_note", {"note": "Internal note"}, 7))
    response = client.execute_write(
        HaloWriteRequest("TCK-1", "draft_response", {"response": "Client response"}, 8)
    )

    assert note.status == "succeeded"
    assert note.endpoint == "Actions"
    assert note.remote_id == "A-1"
    assert response.status == "succeeded"
    assert len(requests) == 4


def test_halopsa_write_bool_variants_and_empty_response(tmp_path: Path) -> None:
    posted: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/auth/token"):
            return httpx.Response(200, json={"access_token": "token-123"})
        posted.append(json.loads(request.content.decode())[0])
        return httpx.Response(204)

    client = HaloPSAReadClient(
        _settings(tmp_path, allow_write_actions=True),
        transport=httpx.MockTransport(handler),
    )

    result = client.execute_write(
        HaloWriteRequest("TCK-1", "add_note", {"body": "Internal", "private": "false"})
    )

    assert result.status == "succeeded"
    assert result.remote_id == ""
    assert posted[0]["hiddenfromuser"] is False


def test_halopsa_ticket_field_write_payload_mapping(tmp_path: Path) -> None:
    posted: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/auth/token"):
            return httpx.Response(200, json={"access_token": "token-123"})
        posted.append(json.loads(request.content.decode())[0])
        assert request.url.path == "/api/Ticket"
        return httpx.Response(200, json=[{"faultid": "TCK-1"}])

    client = HaloPSAReadClient(
        _settings(tmp_path, allow_write_actions=True),
        transport=httpx.MockTransport(handler),
    )

    status = client.execute_write(HaloWriteRequest("TCK-1", "update_status", {"status_id": 9}, 1))
    assign = client.execute_write(
        HaloWriteRequest("TCK-1", "assign_technician", {"technician_id": 42}, 2)
    )
    fields = client.execute_write(
        HaloWriteRequest(
            "TCK-1",
            "update_ticket_fields",
            {"category_id": 5, "priority": "High", "custom_reference": "WAIT"},
            3,
        )
    )

    assert status.status == "succeeded"
    assert assign.status == "succeeded"
    assert fields.status == "succeeded"
    assert posted[0]["status_id"] == 9
    assert posted[1]["agent_id"] == 42
    assert posted[2]["category_id"] == 5
    assert posted[2]["priority"] == "High"
    assert posted[2]["custom_reference"] == "WAIT"


def test_halopsa_write_failures_are_sanitized(tmp_path: Path) -> None:
    def non_2xx(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/auth/token"):
            return httpx.Response(200, json={"access_token": "token-123"})
        return httpx.Response(500, json={"client_secret": "secret", "body": "customer"})

    result = HaloPSAReadClient(
        _settings(tmp_path, allow_write_actions=True),
        transport=httpx.MockTransport(non_2xx),
    ).execute_write(HaloWriteRequest("TCK-1", "add_note", {"note": "secret"}, 1))

    assert result.status == "failed"
    assert "HTTP 500" in result.message
    assert "secret" not in result.message


def test_halopsa_write_validation_and_malformed_json_failures(tmp_path: Path) -> None:
    client = HaloPSAReadClient(
        _settings(tmp_path, allow_write_actions=True),
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"access_token": "t"})
        ),
    )
    missing_note = client.execute_write(HaloWriteRequest("TCK-1", "add_note", {}, 1))
    missing_field = client.execute_write(HaloWriteRequest("TCK-1", "update_status", {}, 1))
    unsupported = client.execute_write(HaloWriteRequest("TCK-1", "delete_ticket", {}, 1))

    def malformed_post(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/auth/token"):
            return httpx.Response(200, json={"access_token": "token-123"})
        return httpx.Response(200, content=b"nope")

    malformed = HaloPSAReadClient(
        _settings(tmp_path, allow_write_actions=True),
        transport=httpx.MockTransport(malformed_post),
    ).execute_write(HaloWriteRequest("TCK-1", "update_status", {"status": "Open"}, 1))

    assert missing_note.status == "failed"
    assert missing_field.status == "failed"
    assert unsupported.status == "failed"
    assert malformed.status == "failed"
    assert "malformed JSON" in malformed.message


def test_halopsa_transport_errors_and_token_cache(tmp_path: Path) -> None:
    token_calls = 0

    def cached_token_handler(request: httpx.Request) -> httpx.Response:
        nonlocal token_calls
        if request.url.path.endswith("/auth/token"):
            token_calls += 1
            return httpx.Response(200, json={"access_token": "token-123", "expires_in": 300})
        return httpx.Response(200, json={"tickets": []})

    cached = HaloPSAReadClient(
        _settings(tmp_path),
        transport=httpx.MockTransport(cached_token_handler),
    )

    cached.list_tickets()
    cached.list_clients()

    assert token_calls == 1

    def get_connect_error(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/auth/token"):
            return httpx.Response(200, json={"access_token": "token-123"})
        raise httpx.ConnectError("boom", request=request)

    read_error = HaloPSAReadClient(
        _settings(tmp_path),
        transport=httpx.MockTransport(get_connect_error),
    ).list_tickets()

    def token_timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("slow", request=request)

    token_error = HaloPSAReadClient(
        _settings(tmp_path),
        transport=httpx.MockTransport(token_timeout),
    ).health()

    def post_timeout(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/auth/token"):
            return httpx.Response(200, json={"access_token": "token-123"})
        raise httpx.TimeoutException("slow", request=request)

    write_error = HaloPSAReadClient(
        _settings(tmp_path, allow_write_actions=True),
        transport=httpx.MockTransport(post_timeout),
    ).execute_write(HaloWriteRequest("TCK-1", "add_note", {"note": "hello"}, 1))

    assert read_error.result.status == "failed"
    assert "before receiving" in read_error.result.message
    assert token_error.status == "failed"
    assert "token request failed" in token_error.message
    assert write_error.status == "failed"
    assert "before receiving" in write_error.message


def test_halopsa_helper_edges() -> None:
    try:
        _safe_endpoint("https://evil.test")
    except Exception as exc:
        assert "relative paths" in str(exc)
    assert _normalize_client({}) is None
    assert _normalize_note({}) is None
    assert _remote_id({"faultid": "TCK-1"}) == "TCK-1"
    assert _remote_id("bad") == ""
