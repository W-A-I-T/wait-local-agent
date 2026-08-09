from __future__ import annotations

from dataclasses import replace

import httpx
import pytest

from wait_local_agent.itglue import (
    MAX_DOCUMENT_CONTENT_LENGTH,
    ItGlueClient,
    ItGlueDocument,
    ItGlueReadError,
    _api_base_url,
    _bounded_page_size,
    _normalize_document,
    _normalize_folder,
    _payload_rows,
    _safe_endpoint,
    _safe_segment,
)


def _configured(settings, *, allow_http_probing: bool = True):
    return replace(
        settings,
        allow_http_probing=allow_http_probing,
        itglue_base_url="https://api.itglue.com",
        itglue_api_key="api-key",
        itglue_page_size=25,
    )


def test_itglue_defaults_block_and_missing_credentials(settings) -> None:
    assert ItGlueClient(settings).list_organizations().result.status == "blocked"
    assert ItGlueClient(settings).health().status == "blocked"
    missing = ItGlueClient(replace(settings, allow_http_probing=True)).health()
    assert missing.status == "not_configured"
    assert "WAIT_ITGLUE_API_KEY" in missing.message
    assert (
        ItGlueClient(replace(settings, allow_http_probing=True)).list_documents("1").result.status
        == "not_configured"
    )


def test_itglue_read_contract_uses_json_api_and_normalizes_resources(settings) -> None:
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        assert request.headers["x-api-key"] == "api-key"
        assert request.headers["Accept"] == "application/vnd.api+json"
        if request.url.path == "/organizations":
            if request.url.params["page[number]"] == "1":
                return httpx.Response(200, json={"data": [{"id": "1", "attributes": {"name": "Acme"}}]})
            assert request.url.params["page[number]"] == "2"
            assert request.url.params["page[size]"] == "2"
            return httpx.Response(
                200,
                json={
                    "data": [
                        {"id": "1", "type": "organizations", "attributes": {"name": "Acme", "status": "active"}},
                        {"type": "organizations", "attributes": {"name": "missing"}},
                    ]
                },
            )
        if request.url.path.endswith("/relationships/documents"):
            assert request.url.params["filter[document_folder_id]"] == "7"
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": "9",
                            "attributes": {
                                "name": "Runbook",
                                "organization-id": "1",
                                "document-folder-id": "7",
                                "updated-at": "today",
                                "resource-url": "https://docs.example.test/9",
                            },
                        }
                    ]
                },
            )
        if request.url.path == "/documents/9":
            return httpx.Response(
                200,
                json={
                    "data": {
                        "id": "9",
                        "attributes": {"title": "Runbook", "content": "token=secret"},
                    }
                },
            )
        if request.url.path.endswith("/relationships/document_folders"):
            return httpx.Response(
                200,
                json=[{"id": "7", "attributes": {"name": "Ops", "organization_id": "1", "parent_id": "0"}}],
            )
        raise AssertionError(request.url)

    client = ItGlueClient(_configured(settings), transport=httpx.MockTransport(handler))
    organizations = client.list_organizations(page=2, page_size=2)
    documents = client.list_documents("1", folder_id="7", page_size=2)
    document = client.get_document("9")
    folders = client.list_folders("1", page_size=2)
    assert client.health().status == "ready"
    assert organizations.items[0].name == "Acme"
    assert documents.items[0].name == "Runbook"
    document_item = document.items[0]
    assert isinstance(document_item, ItGlueDocument)
    assert document_item.name == "Runbook"
    assert document_item.content == "token=secret"
    assert folders.items[0].parent_id == "0"  # type: ignore[union-attr]
    assert paths.count("/organizations") == 2


def test_itglue_content_search_uses_all_folder_listing_and_bounded_detail_sections(settings) -> None:
    requests: list[tuple[str, str | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append((request.url.path, request.url.params.get("filter[document_folder_id]")))
        if request.url.path.endswith("/relationships/documents"):
            assert request.url.params["filter[document_folder_id]"] == "null"
            assert request.url.params["page[size]"] == "12"
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": "9",
                            "attributes": {
                                "name": "VPN runbook",
                                "organization-id": "1",
                                "document-folder-id": "7",
                            },
                        },
                        {
                            "id": "10",
                            "attributes": {
                                "name": "Printer guide",
                                "organization-id": "1",
                            },
                        },
                    ]
                },
            )
        if request.url.path == "/documents/9":
            return httpx.Response(
                200,
                json={
                    "data": {
                        "id": "9",
                        "attributes": {
                            "name": "VPN runbook",
                            "organization-id": "1",
                            "sections": [
                                {"attributes": {"resource-type": "Document::Heading", "content": "VPN"}},
                                {
                                    "attributes": {
                                        "resource-type": "Document::Text",
                                        "content": "MFA reset instructions",
                                    }
                                },
                                {
                                    "attributes": {
                                        "resource-type": "Document::Gallery",
                                        "content": "must not be searched",
                                    }
                                },
                            ],
                        },
                    }
                },
            )
        if request.url.path == "/documents/10":
            return httpx.Response(
                200,
                json={"data": {"id": "10", "attributes": {"name": "Printer guide", "organization-id": "1"}}},
            )
        raise AssertionError(request.url)

    client = ItGlueClient(_configured(settings), transport=httpx.MockTransport(handler))
    response = client.search_documents("1", "mfa", limit=3)

    assert response.result.status == "ready"
    assert response.result.count == 1
    assert isinstance(response.items[0], ItGlueDocument)
    assert response.items[0].name == "VPN runbook"
    assert response.items[0].content == "VPN\nMFA reset instructions"
    assert requests[0] == ("/organizations/1/relationships/documents", "null")
    assert ("/documents/9", None) in requests
    assert ("/documents/10", None) in requests


def test_itglue_content_search_rejects_unbounded_or_failed_reads(settings) -> None:
    configured = _configured(settings)
    assert ItGlueClient(configured).search_documents("1", "", limit=1).result.status == "failed"
    assert ItGlueClient(configured).search_documents("1", "vpn", limit=0).result.status == "failed"

    def failed_detail(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/relationships/documents"):
            return httpx.Response(200, json={"data": [{"id": "9", "attributes": {"name": "VPN"}}]})
        return httpx.Response(500)

    response = ItGlueClient(configured, transport=httpx.MockTransport(failed_detail)).search_documents(
        "1", "vpn", limit=1
    )
    assert response.result.status == "failed"
    assert "could not retrieve document" in response.result.message


def test_itglue_sanitizes_failures_and_bounds_paths(settings) -> None:
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("private timeout")

    result = ItGlueClient(_configured(settings), transport=httpx.MockTransport(timeout)).list_organizations()
    assert result.result.message == "IT Glue request failed before receiving a response."

    def denied(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="private body")

    result = ItGlueClient(_configured(settings), transport=httpx.MockTransport(denied)).list_organizations()
    assert "HTTP 403" in result.result.message
    assert "private body" not in result.result.message
    failed_health = ItGlueClient(_configured(settings), transport=httpx.MockTransport(denied)).health()
    assert failed_health.status == "failed"

    def malformed(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not-json")

    result = ItGlueClient(_configured(settings), transport=httpx.MockTransport(malformed)).list_organizations()
    assert "malformed JSON" in result.result.message

    def protocol_error(request: httpx.Request) -> httpx.Response:
        raise httpx.ProtocolError("private transport detail")

    result = ItGlueClient(_configured(settings), transport=httpx.MockTransport(protocol_error)).list_organizations()
    assert result.result.message == "IT Glue request failed."

    assert ItGlueClient(_configured(settings)).get_document("bad/id").result.status == "failed"
    assert ItGlueClient(_configured(settings)).list_documents("bad/id").result.status == "failed"
    assert ItGlueClient(_configured(settings)).list_documents("1", folder_id="bad/id").result.status == "failed"
    assert ItGlueClient(_configured(settings)).list_folders("bad/id").result.status == "failed"
    missing = ItGlueClient(replace(settings, allow_http_probing=True))
    try:
        missing._get("organizations")
    except ItGlueReadError as exc:
        assert "WAIT_ITGLUE_BASE_URL" in str(exc)
    else:
        raise AssertionError("unconfigured live read was not rejected")
    blocked = ItGlueClient(_configured(settings, allow_http_probing=False))
    try:
        blocked._get("organizations")
    except ItGlueReadError as exc:
        assert "WAIT_ALLOW_HTTP_PROBING=true" in str(exc)
    else:
        raise AssertionError("blocked live read was not rejected")


def test_itglue_helpers_cover_json_shapes_and_bounds() -> None:
    assert _api_base_url("https://api.itglue.com/") == "https://api.itglue.com"
    with pytest.raises(ItGlueReadError):
        _bounded_page_size(0)
    assert _bounded_page_size(1000) == 100
    assert _payload_rows({"data": {"id": "1"}}) == [{"id": "1"}]
    assert _payload_rows({"meta": {}}) == [{"meta": {}}]
    assert _payload_rows({"data": []}) == []
    assert _payload_rows(None) == []
    assert _normalize_document({"name": "missing"}) is None
    assert _normalize_folder({"name": "missing"}) is None
    for helper, value in ((_safe_segment, ""), (_safe_segment, "1/2"), (_safe_endpoint, "//host")):
        try:
            helper(value)
        except ItGlueReadError:
            pass
        else:
            raise AssertionError(f"unsafe value accepted: {value}")
    bounded = _normalize_document(
        {
            "id": "9",
            "attributes": {
                "name": "Large",
                "content": "x" * (MAX_DOCUMENT_CONTENT_LENGTH + 1),
            },
        }
    )
    assert bounded is not None
    assert len(bounded.content) == MAX_DOCUMENT_CONTENT_LENGTH
