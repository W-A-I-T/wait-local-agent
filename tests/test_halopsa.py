from __future__ import annotations

import json
from pathlib import Path

import httpx

from wait_local_agent.config import Settings
from wait_local_agent.halopsa import HaloPSAReadClient
from wait_local_agent.models import HaloAsset, HaloCategory, HaloClient, HaloNote


def _settings(
    tmp_path: Path,
    *,
    allow_http_probing: bool = True,
    base_url: str = "https://halo.example.test",
    client_id: str = "client-id",
    client_secret: str = "secret",
    tenant: str = "tenant",
    token_url: str = "",
) -> Settings:
    return Settings(
        data_path=tmp_path / "state.db",
        allowed_doc_root=Path("examples/sample_docs"),
        allow_write_actions=False,
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
