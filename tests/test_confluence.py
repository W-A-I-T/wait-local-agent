from __future__ import annotations

from dataclasses import replace

import httpx
import pytest

from wait_local_agent.confluence import (
    MAX_PAGE_BODY_LENGTH,
    ConfluenceClient,
    ConfluencePage,
    ConfluenceReadError,
    _api_base_url,
    _bounded_page_size,
    _next_cursor,
    _normalize_page,
    _payload_rows,
    _safe_cursor,
    _safe_endpoint,
    _safe_segment,
    _safe_title,
)


def _configured(settings, *, allow_http_probing: bool = True):
    return replace(
        settings,
        allow_http_probing=allow_http_probing,
        confluence_base_url="https://acme.atlassian.net",
        confluence_email="agent@example.test",
        confluence_api_token="api-token",
        confluence_page_size=25,
    )


def test_confluence_defaults_block_and_missing_credentials(settings) -> None:
    assert ConfluenceClient(settings).list_pages().result.status == "blocked"
    assert ConfluenceClient(settings).health().status == "blocked"
    missing = ConfluenceClient(replace(settings, allow_http_probing=True)).health()
    assert missing.status == "not_configured"
    assert "WAIT_CONFLUENCE_API_TOKEN" in missing.message


def test_confluence_reads_use_v2_basic_auth_and_normalize_pages(settings) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.url.path == "/wiki/api/v2/pages"
        assert request.headers["Accept"] == "application/json"
        assert request.headers["Authorization"].startswith("Basic ")
        assert request.url.params["space-id"] == "42"
        assert request.url.params["title"] == "Runbook"
        assert request.url.params["cursor"] == "next-token"
        assert request.url.params["limit"] == "2"
        assert request.url.params["body-format"] == "storage"
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "id": "9",
                        "title": "Runbook",
                        "spaceId": "42",
                        "status": "current",
                        "version": {"number": 3},
                        "updatedAt": "2026-08-07T20:00:00Z",
                        "_links": {"webui": "/spaces/OPS/pages/9"},
                        "body": {"storage": {"value": "<p>Use MFA.</p>"}},
                    }
                ],
                "_links": {"next": "/wiki/api/v2/pages?cursor=next-next"},
            },
        )

    client = ConfluenceClient(_configured(settings), transport=httpx.MockTransport(handler))
    pages = client.list_pages(space_id="42", title="Runbook", cursor="next-token", page_size=2)
    assert pages.result.status == "ready"
    assert pages.items[0].id == "9"
    assert pages.items[0].version == "3"
    assert pages.items[0].body == "<p>Use MFA.</p>"
    assert pages.next_cursor == "next-next"
    assert len(requests) == 1


def test_confluence_page_detail_and_health(settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/pages/9"):
            assert request.url.params["body-format"] == "storage"
            return httpx.Response(
                200,
                json={
                    "id": "9",
                    "title": "Runbook",
                    "body": {"storage": {"value": "<p>Use MFA.</p>"}},
                },
            )
        return httpx.Response(200, json={"results": []})

    client = ConfluenceClient(_configured(settings), transport=httpx.MockTransport(handler))
    page = client.get_page("9").items[0]
    assert isinstance(page, ConfluencePage)
    assert page.title == "Runbook"
    assert page.body == "<p>Use MFA.</p>"
    assert client.health().status == "ready"


def test_confluence_sanitizes_failures_and_bounds_inputs(settings) -> None:
    def denied(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="private body")

    result = ConfluenceClient(_configured(settings), transport=httpx.MockTransport(denied)).list_pages()
    assert "HTTP 403" in result.result.message
    assert "private body" not in result.result.message

    def malformed(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not-json")

    result = ConfluenceClient(_configured(settings), transport=httpx.MockTransport(malformed)).list_pages()
    assert "malformed JSON" in result.result.message
    assert ConfluenceClient(_configured(settings)).get_page("bad/id").result.status == "failed"
    assert ConfluenceClient(_configured(settings)).list_pages(space_id="bad/id").result.status == "failed"
    assert ConfluenceClient(_configured(settings)).list_pages(cursor=" ").result.status == "failed"

    missing = ConfluenceClient(replace(settings, allow_http_probing=True))
    with pytest.raises(ConfluenceReadError, match="WAIT_CONFLUENCE_BASE_URL"):
        missing._get("pages")
    blocked = ConfluenceClient(_configured(settings, allow_http_probing=False))
    with pytest.raises(ConfluenceReadError, match="WAIT_ALLOW_HTTP_PROBING=true"):
        blocked._get("pages")


def test_confluence_covers_http_statuses_transport_errors_and_normalization_edges(settings) -> None:
    for status_code, marker in (
        (401, "authentication failed"),
        (404, "not found"),
        (429, "rate limited"),
        (500, "HTTP 500"),
    ):
        def denied(request: httpx.Request, code=status_code) -> httpx.Response:
            return httpx.Response(code, text="private body")

        response = ConfluenceClient(
            _configured(settings), transport=httpx.MockTransport(denied)
        ).list_pages()
        assert marker in response.result.message

    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("private timeout")

    response = ConfluenceClient(
        _configured(settings), transport=httpx.MockTransport(timeout)
    ).list_pages()
    assert response.result.message == "Confluence request failed before receiving a response."

    def protocol_error(request: httpx.Request) -> httpx.Response:
        raise httpx.ProtocolError("private transport detail")

    response = ConfluenceClient(
        _configured(settings), transport=httpx.MockTransport(protocol_error)
    ).list_pages()
    assert response.result.message == "Confluence request failed."
    assert ConfluenceClient(
        _configured(settings), transport=httpx.MockTransport(lambda request: httpx.Response(500))
    ).health().status == "failed"

    assert _normalize_page(
        {
            "id": 9,
            "title": "Page",
            "space_id": 42,
            "createdAt": "yesterday",
            "_links": {"base": "https://acme.atlassian.net"},
            "body": {"atlas_doc_format": {"value": "doc"}},
        }
    ) == ConfluencePage("9", "Page", "42", "", "", "yesterday", "https://acme.atlassian.net", "doc")
    bounded = _normalize_page(
        {
            "id": "10",
            "title": "Large",
            "body": {"storage": {"value": "x" * (MAX_PAGE_BODY_LENGTH + 1)}},
        }
    )
    assert bounded is not None
    assert len(bounded.body) == MAX_PAGE_BODY_LENGTH
    assert _payload_rows([{"id": "1"}, "ignored"]) == [{"id": "1"}]
    assert _next_cursor({"_links": {"next": "/pages?cursor=" + "x" * 5000}}) == ""

    for value in ("", "ftp://host", "https://user:pass@host", "https://host?token=x", "https://host\n"):
        with pytest.raises(ConfluenceReadError):
            _api_base_url(value)
    for value in ("", "bad\nname"):
        with pytest.raises(ConfluenceReadError):
            _safe_title(value)
    with pytest.raises(ConfluenceReadError):
        _safe_cursor("x\nbad")
    with pytest.raises(ConfluenceReadError):
        _bounded_page_size(True)
    with pytest.raises(ConfluenceReadError):
        _safe_endpoint("pages/$bad")


def test_confluence_helpers_cover_shapes_and_bounds() -> None:
    assert _api_base_url("https://acme.atlassian.net") == "https://acme.atlassian.net/wiki/api/v2"
    assert _api_base_url("https://acme.atlassian.net/wiki") == "https://acme.atlassian.net/wiki/api/v2"
    assert _api_base_url("https://acme.atlassian.net/wiki/api/v2/") == "https://acme.atlassian.net/wiki/api/v2"
    with pytest.raises(ConfluenceReadError):
        _bounded_page_size(0)
    assert _bounded_page_size(1000) == 100
    assert _payload_rows({"data": {"id": "1"}}) == [{"id": "1"}]
    assert _payload_rows({"meta": {}}) == [{"meta": {}}]
    assert _payload_rows(None) == []
    assert _normalize_page({"id": "9"}) is None
    for helper, value in (
        (_safe_segment, ""),
        (_safe_segment, "1/2"),
        (_safe_endpoint, "//host"),
        (_safe_cursor, ""),
    ):
        with pytest.raises(ConfluenceReadError):
            helper(value)
