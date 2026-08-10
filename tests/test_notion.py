from __future__ import annotations

import json
from dataclasses import replace
from typing import cast

import httpx
import pytest

from wait_local_agent.connectors import list_connector_statuses, list_secret_records
from wait_local_agent.notion import (
    DEFAULT_NOTION_VERSION,
    MAX_PAGE_MARKDOWN_LENGTH,
    NotionClient,
    NotionDataSource,
    NotionPage,
    NotionReadError,
    NotionReadResponse,
    _api_base_url,
    _bounded_page_size,
    _markdown_value,
    _next_cursor,
    _normalize_data_source,
    _normalize_page,
    _normalize_search_page,
    _payload_rows,
    _safe_cursor,
    _safe_endpoint,
    _safe_query,
    _safe_uuid,
    _safe_version,
    _title_from_properties,
)
from wait_local_agent.rmm import rmm_provider_from_settings
from wait_local_agent.store import Store

PAGE_ID = "11111111-2222-3333-4444-555555555555"
OTHER_PAGE_ID = "22222222-3333-4444-5555-666666666666"
DATA_SOURCE_ID = "66666666-7777-8888-9999-000000000000"
OTHER_DATA_SOURCE_ID = "77777777-8888-9999-0000-111111111111"


def _configured(settings, *, allow_http_probing: bool = True, mapping: str | None = None):
    return replace(
        settings,
        allow_http_probing=allow_http_probing,
        notion_api_token="notion-secret-token",
        notion_version=DEFAULT_NOTION_VERSION,
        notion_client_page_map_json=mapping or json.dumps({"acme": [PAGE_ID]}),
    )


def _configured_data_source(settings, *, allow_http_probing: bool = True):
    return replace(
        _configured(settings, allow_http_probing=allow_http_probing),
        notion_client_data_source_map_json=json.dumps({"acme": [DATA_SOURCE_ID]}),
    )


def test_notion_defaults_block_and_report_missing_configuration(settings) -> None:
    assert NotionClient(settings).search_pages(client_id="acme").result.status == "blocked"
    assert NotionClient(settings).get_page(PAGE_ID, client_id="acme").result.status == "blocked"
    assert NotionClient(settings).health().status == "blocked"
    missing = NotionClient(replace(settings, allow_http_probing=True)).health()
    assert missing.status == "not_configured"
    assert "WAIT_NOTION_API_TOKEN" in missing.message
    active_without_config = NotionClient(replace(settings, allow_http_probing=True))
    assert active_without_config.search_pages(client_id="acme").result.status == "not_configured"
    assert active_without_config.get_page(PAGE_ID, client_id="acme").result.status == "not_configured"


def test_notion_status_and_secret_records_are_safe(settings) -> None:
    active = _configured(settings, allow_http_probing=True)
    status = next(item for item in list_connector_statuses(active) if item.id == "notion")
    records = {item.key: item for item in list_secret_records(active)}

    assert status.status == "configured"
    assert "notion-secret-token" not in status.message
    assert records["WAIT_NOTION_API_TOKEN"].configured is True
    assert records["WAIT_NOTION_CLIENT_PAGE_MAP_JSON"].configured is True
    assert rmm_provider_from_settings(active, Store(active.data_path)).adapter_id == "local-collector"


def test_notion_search_and_markdown_reads_use_documented_contract(settings) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.headers["Authorization"] == "Bearer notion-secret-token"
        assert request.headers["Notion-Version"] == DEFAULT_NOTION_VERSION
        if request.url.path == "/v1/search":
            assert request.method == "POST"
            body = json.loads(request.content)
            assert body == {
                "query": "MFA",
                "page_size": 2,
                "filter": {"property": "object", "value": "page"},
            }
            return httpx.Response(
                200,
                json={
                    "object": "list",
                    "next_cursor": "next-page",
                    "results": [
                        {
                            "object": "page",
                            "id": PAGE_ID,
                            "url": "https://notion.example/page",
                            "last_edited_time": "2026-08-09T00:00:00Z",
                            "properties": {
                                "Name": {
                                    "type": "title",
                                    "title": [{"plain_text": "MFA runbook"}],
                                }
                            },
                        },
                        {"object": "page", "id": OTHER_PAGE_ID, "properties": {}},
                    ],
                },
            )
        if request.url.path == f"/v1/pages/{PAGE_ID}":
            assert request.method == "GET"
            return httpx.Response(
                200,
                json={
                    "id": PAGE_ID,
                    "url": "https://notion.example/page",
                    "last_edited_time": "2026-08-09T00:00:00Z",
                    "properties": {
                        "Name": {"type": "title", "title": [{"plain_text": "MFA runbook"}]}
                    },
                },
            )
        if request.url.path == f"/v1/pages/{PAGE_ID}/markdown":
            assert request.method == "GET"
            return httpx.Response(200, json={"id": PAGE_ID, "markdown": "Rotate MFA keys."})
        raise AssertionError(request.url)

    client = NotionClient(_configured(settings), transport=httpx.MockTransport(handler))
    search = client.search_pages(client_id="acme", query="MFA", page_size=2)
    page = client.get_page(PAGE_ID, client_id="acme")

    assert search.result.status == "ready"
    assert search.next_cursor == "next-page"
    assert [item.id for item in search.items] == [PAGE_ID]
    assert search.items[0].title == "MFA runbook"
    assert page.items == [
        NotionPage(
            PAGE_ID,
            "MFA runbook",
            "https://notion.example/page",
            "2026-08-09T00:00:00Z",
            False,
            "Rotate MFA keys.",
        )
    ]
    assert len(requests) == 3


def test_notion_data_source_query_is_mapped_bounded_and_read_only(settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == f"/v1/data_sources/{DATA_SOURCE_ID}/query"
        assert json.loads(request.content) == {"page_size": 2, "start_cursor": "cursor-1"}
        return httpx.Response(
            200,
            json={
                "object": "list",
                "next_cursor": "cursor-2",
                "results": [
                    {"object": "page", "id": PAGE_ID, "properties": {}},
                    {"object": "page", "id": "not-a-page", "properties": {}},
                ],
            },
        )

    response = NotionClient(
        _configured_data_source(settings), transport=httpx.MockTransport(handler)
    ).query_data_source(
        DATA_SOURCE_ID, client_id="acme", page_size=2, start_cursor="cursor-1"
    )
    assert response.result.status == "ready"
    assert response.next_cursor == "cursor-2"
    assert [item.id for item in response.items] == [PAGE_ID]


def test_notion_data_source_query_rejects_scope_and_configuration(settings) -> None:
    client = NotionClient(
        _configured_data_source(settings),
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={})),
    )
    outside = client.query_data_source(OTHER_DATA_SOURCE_ID, client_id="acme")
    assert outside.result.status == "failed"
    assert "outside the tenant scope" in outside.result.message
    assert "invalid" in client.query_data_source(DATA_SOURCE_ID, client_id="acme", start_cursor=" ").result.message

    blocked = NotionClient(
        _configured_data_source(settings, allow_http_probing=False)
    ).query_data_source(DATA_SOURCE_ID, client_id="acme")
    assert blocked.result.status == "blocked"

    provider_failure = NotionClient(
        _configured_data_source(settings),
        transport=httpx.MockTransport(lambda request: httpx.Response(401, json={})),
    ).query_data_source(DATA_SOURCE_ID, client_id="acme")
    assert provider_failure.result.status == "failed"

    missing = NotionClient(
        replace(settings, allow_http_probing=True, notion_api_token="")
    ).query_data_source(DATA_SOURCE_ID, client_id="acme")
    assert missing.result.status == "not_configured"


def test_notion_data_source_metadata_is_mapped_and_returns_only_schema_types(settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == f"/v1/data_sources/{DATA_SOURCE_ID}"
        return httpx.Response(
            200,
            json={
                "object": "data_source",
                "id": DATA_SOURCE_ID,
                "properties": {
                    "Name": {"type": "title", "title": {}},
                    "Status": {"type": "status", "status": {}},
                },
            },
        )

    response = NotionClient(
        _configured_data_source(settings), transport=httpx.MockTransport(handler)
    ).get_data_source(DATA_SOURCE_ID, client_id="acme")
    assert response.result.status == "ready"
    assert response.items == [NotionDataSource(DATA_SOURCE_ID, {"Name": "title", "Status": "status"})]


def test_notion_data_source_metadata_rejects_scope_and_malformed_payload(settings) -> None:
    outside = NotionClient(
        _configured_data_source(settings),
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={})),
    ).get_data_source(OTHER_DATA_SOURCE_ID, client_id="acme")
    assert outside.result.status == "failed"
    assert "outside the tenant scope" in outside.result.message

    malformed = NotionClient(
        _configured_data_source(settings),
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"id": DATA_SOURCE_ID, "properties": []})
        ),
    ).get_data_source(DATA_SOURCE_ID, client_id="acme")
    assert malformed.result.status == "failed"
    assert "malformed" in malformed.result.message


def test_notion_health_uses_a_mapped_page_and_empty_search_query(settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/search"
        body = json.loads(request.content)
        assert "query" not in body
        return httpx.Response(200, json={"results": []})

    result = NotionClient(
        _configured(settings), transport=httpx.MockTransport(handler)
    ).health()
    assert result.status == "ready"


@pytest.mark.parametrize(
    ("mapping", "message"),
    [
        ("not-json", "is malformed"),
        ("[]", "must be an object"),
        ('{"acme": []}', "mapping is missing"),
        ('{"acme": ["not-a-uuid"]}', "must be UUIDs"),
        ('{"acme": [1]}', "must be UUIDs"),
    ],
)
def test_notion_rejects_invalid_tenant_maps(settings, mapping, message) -> None:
    response = NotionClient(
        _configured(settings, mapping=mapping),
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={})),
    ).search_pages(client_id="acme", query="runbook")
    assert response.result.status == "failed"
    assert message in response.result.message


def test_notion_rejects_tenant_maps_over_the_bound(settings) -> None:
    mapping = json.dumps({"acme": [PAGE_ID] * 101})
    response = NotionClient(
        _configured(settings, mapping=mapping),
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={})),
    ).search_pages(client_id="acme", query="runbook")
    assert response.result.status == "failed"
    assert "exceeds" in response.result.message


def test_notion_scope_and_page_ids_are_enforced(settings) -> None:
    client = NotionClient(
        _configured(settings),
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={})),
    )
    assert "tenant scope" in client.search_pages(client_id="").result.message
    assert "outside the tenant scope" in client.get_page(OTHER_PAGE_ID, client_id="acme").result.message
    assert "must be a UUID" in client.get_page("not-a-page", client_id="acme").result.message


def test_notion_http_failures_are_sanitized(settings) -> None:
    for status_code, marker in ((401, "unauthorized"), (404, "not found"), (429, "rate limited"), (500, "HTTP 500")):
        response = NotionClient(
            _configured(settings),
            transport=httpx.MockTransport(
                lambda request, code=status_code: httpx.Response(code, text="private token")
            ),
        ).search_pages(client_id="acme", query="runbook")
        assert marker in response.result.message
        assert "private token" not in response.result.message

    malformed = NotionClient(
        _configured(settings),
        transport=httpx.MockTransport(lambda request: httpx.Response(200, text="not-json")),
    ).search_pages(client_id="acme", query="runbook")
    assert "malformed JSON" in malformed.result.message

    timeout = NotionClient(
        _configured(settings),
        transport=httpx.MockTransport(lambda request: (_ for _ in ()).throw(httpx.ReadTimeout("offline"))),
    ).search_pages(client_id="acme", query="runbook")
    assert timeout.result.message == "Notion request failed before receiving a response."


def test_notion_helpers_fail_closed() -> None:
    assert _api_base_url("https://api.notion.com") == "https://api.notion.com/v1"
    assert _api_base_url("https://api.notion.com/v1/") == "https://api.notion.com/v1"
    assert _payload_rows({"results": [{"id": PAGE_ID}, "ignored"]}) == [{"id": PAGE_ID}]
    assert _payload_rows(None) == []
    assert _normalize_search_page({"id": PAGE_ID, "properties": {}}) is not None
    assert _normalize_search_page({"id": 1}) is None
    assert _normalize_search_page({"id": "bad"}) is None
    assert _normalize_page({"id": PAGE_ID, "properties": {}}) is not None
    assert _normalize_page(None) is None
    assert _normalize_page({"id": 1}) is None
    assert _normalize_page({"id": "bad"}) is None
    assert _normalize_data_source({"id": PAGE_ID, "properties": {"Name": {"type": "title"}}}) == NotionDataSource(
        PAGE_ID, {"Name": "title"}
    )
    assert _normalize_data_source({"id": PAGE_ID, "properties": {"Name": {}}}) is None
    assert _markdown_value({"markdown": "x" * (MAX_PAGE_MARKDOWN_LENGTH + 1)}) == "x" * MAX_PAGE_MARKDOWN_LENGTH
    assert _markdown_value(None) is None
    assert _markdown_value({"markdown": 1}) is None
    assert _bounded_page_size(1000) == 100
    assert _next_cursor(None) == ""
    assert _next_cursor({"next_cursor": " "}) == ""
    assert _next_cursor({"next_cursor": "x" * 4097}) == ""
    assert _safe_uuid(PAGE_ID) == PAGE_ID
    assert _safe_query(" MFA ") == "MFA"
    with pytest.raises(NotionReadError):
        _api_base_url("https://user:pass@host")
    with pytest.raises(NotionReadError):
        _api_base_url("not-a-url")
    with pytest.raises(NotionReadError):
        _safe_endpoint("pages/../secret")
    with pytest.raises(NotionReadError):
        _safe_endpoint("pages/not allowed")
    assert _safe_cursor(" cursor ") == "cursor"
    with pytest.raises(NotionReadError):
        _safe_cursor(" ")
    with pytest.raises(NotionReadError):
        _safe_cursor("bad\ncursor")
    with pytest.raises(NotionReadError):
        _safe_query("x\nunsafe")
    with pytest.raises(NotionReadError):
        _bounded_page_size(0)
    with pytest.raises(NotionReadError):
        _safe_version("2026-03-11\nunsafe")
    with pytest.raises(NotionReadError):
        _safe_uuid("not-a-uuid")
    assert _title_from_properties(None) == ""
    assert _title_from_properties({"x": "not-a-property"}) == ""
    assert _title_from_properties({"x": {"type": "unsupported"}}) == ""
    assert _title_from_properties({"x": {"type": "title", "title": "not-a-list"}}) == ""
    assert _title_from_properties({"x": {"type": "title", "title": [{"plain_text": ""}]}}) == ""


def test_notion_invalid_base_url_is_reported_without_raising(settings) -> None:
    invalid = NotionClient(
        replace(_configured(settings), notion_base_url="https://api.notion.com\nattacker"),
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={})),
    ).search_pages(client_id="acme", query="runbook")
    assert invalid.result.status == "failed"
    assert "control characters" in invalid.result.message


def test_notion_health_and_page_failures_are_safe(settings) -> None:
    configured = _configured(settings)

    invalid_map = NotionClient(
        replace(configured, notion_client_page_map_json='{"acme": [1]}'),
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={})),
    )
    assert invalid_map.health().status == "failed"
    assert "UUIDs" in invalid_map.health().message

    not_ready = NotionClient(
        configured,
        transport=httpx.MockTransport(lambda request: httpx.Response(401, json={})),
    )
    assert not_ready.health().status == "failed"
    assert (
        "unauthorized"
        in not_ready.get_page(PAGE_ID, client_id="acme").result.message
    )

    malformed_page = NotionClient(
        configured,
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"bad": True})),
    )
    assert "malformed" in malformed_page.get_page(PAGE_ID, client_id="acme").result.message

    calls = 0

    def markdown_failure(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(200, json={"id": PAGE_ID, "properties": {}})
        return httpx.Response(404, json={})

    response = NotionClient(
        configured, transport=httpx.MockTransport(markdown_failure)
    ).get_page(PAGE_ID, client_id="acme")
    assert response.result.status == "failed"
    assert "not found" in response.result.message

    malformed_markdown = NotionClient(
        configured,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={"id": PAGE_ID, "properties": {}}
                if request.url.path.endswith(f"/pages/{PAGE_ID}")
                else {"markdown": 1},
            )
        ),
    ).get_page(PAGE_ID, client_id="acme")
    assert "markdown response was malformed" in malformed_markdown.result.message


def test_notion_request_boundary_handles_blocked_missing_and_http_errors(settings) -> None:
    blocked = NotionClient(settings)
    blocked_result = cast(NotionReadResponse, blocked._request("GET", "pages/x"))
    assert blocked_result.result.status == "blocked"

    missing = NotionClient(replace(settings, allow_http_probing=True))
    missing_result = cast(NotionReadResponse, missing._request("GET", "pages/x"))
    assert missing_result.result.status == "not_configured"

    generic_error = NotionClient(
        _configured(settings),
        transport=httpx.MockTransport(
            lambda request: (_ for _ in ()).throw(httpx.NetworkError("network"))
        ),
    ).search_pages(client_id="acme")
    assert generic_error.result.message == "Notion request failed."
