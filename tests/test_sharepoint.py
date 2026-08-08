from __future__ import annotations

from dataclasses import replace

import httpx
import pytest

from wait_local_agent.sharepoint import (
    MAX_CONTENT_LENGTH,
    SharePointClient,
    SharePointDocument,
    SharePointReadError,
    SharePointSite,
    _api_base_url,
    _bounded_page_size,
    _list_params,
    _next_cursor,
    _normalize_document,
    _normalize_site,
    _payload_rows,
    _safe_cursor,
    _safe_endpoint,
    _safe_segment,
    _string_value,
)

SITE_ID = "contoso.sharepoint.com,site-id,web-id"


def _configured(settings, *, allow_http_probing: bool = True):
    return replace(
        settings,
        allow_http_probing=allow_http_probing,
        sharepoint_base_url="https://graph.microsoft.com/v1.0",
        sharepoint_access_token="access-token",
        sharepoint_page_size=25,
    )


def test_sharepoint_defaults_block_and_missing_credentials(settings) -> None:
    assert SharePointClient(settings).list_sites().result.status == "blocked"
    assert SharePointClient(settings).health().status == "blocked"
    missing = SharePointClient(replace(settings, allow_http_probing=True)).health()
    assert missing.status == "not_configured"
    assert "WAIT_SHAREPOINT_ACCESS_TOKEN" in missing.message


def test_sharepoint_reads_use_bearer_auth_and_normalize_graph_resources(settings) -> None:
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        assert request.headers["Authorization"] == "Bearer access-token"
        assert request.headers["Accept"] == "application/json"
        if request.url.path == "/v1.0/sites":
            if request.url.params.get("$skiptoken"):
                assert request.url.params["$top"] == "2"
                assert request.url.params["$skiptoken"] == "next-token"
            return httpx.Response(
                200,
                json={
                    "value": [
                        {
                            "id": SITE_ID,
                            "name": "ops",
                            "displayName": "Operations",
                            "webUrl": "https://contoso.sharepoint.com/teams/ops",
                        }
                    ],
                    "@odata.nextLink": "https://graph.microsoft.com/v1.0/sites?$skiptoken=next-next",
                },
            )
        if request.url.path == f"/v1.0/sites/{SITE_ID}/drive/root/children":
            return httpx.Response(
                200,
                json={
                    "value": [
                        {
                            "id": "folder-1",
                            "name": "Runbooks",
                            "folder": {"childCount": 2},
                            "parentReference": {"id": "root"},
                            "webUrl": "https://contoso.sharepoint.com/runbooks",
                        },
                        {
                            "id": "file-1",
                            "name": "MFA.md",
                            "size": 42,
                            "lastModifiedDateTime": "2026-08-07T20:00:00Z",
                            "parentReference": {"id": "root"},
                            "webUrl": "https://contoso.sharepoint.com/mfa",
                        },
                    ]
                },
            )
        if request.url.path == f"/v1.0/sites/{SITE_ID}/drive/items/folder-1/children":
            return httpx.Response(200, json={"value": [{"id": "file-2", "name": "VPN.md"}]})
        if request.url.path == f"/v1.0/sites/{SITE_ID}":
            return httpx.Response(200, json={"id": SITE_ID, "displayName": "Operations"})
        if request.url.path == f"/v1.0/sites/{SITE_ID}/drive/items/file-1":
            return httpx.Response(200, json={"id": "file-1", "name": "MFA.md"})
        raise AssertionError(request.url)

    client = SharePointClient(_configured(settings), transport=httpx.MockTransport(handler))
    sites = client.list_sites(cursor="next-token", page_size=2)
    root = client.list_documents(SITE_ID)
    children = client.list_documents(SITE_ID, parent_item_id="folder-1")
    site = client.get_site(SITE_ID)
    document = client.get_document(SITE_ID, "file-1")
    assert sites.items[0] == SharePointSite(
        SITE_ID, "ops", "Operations", "https://contoso.sharepoint.com/teams/ops"
    )
    assert sites.next_cursor == "next-next"
    assert root.items[0].is_folder is True  # type: ignore[union-attr]
    assert root.items[1].size == 42  # type: ignore[union-attr]
    assert children.items[0].id == "file-2"
    assert site.items[0].display_name == "Operations"  # type: ignore[union-attr]
    assert document.items[0].id == "file-1"
    assert client.health().status == "ready"
    assert paths.count("/v1.0/sites") == 2


def test_sharepoint_sanitizes_failures_and_bounds_inputs(settings) -> None:
    def denied(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="private body")

    result = SharePointClient(_configured(settings), transport=httpx.MockTransport(denied)).list_sites()
    assert "HTTP 403" in result.result.message
    assert "private body" not in result.result.message
    assert SharePointClient(_configured(settings)).list_sites(page_size=0).result.status == "failed"

    def malformed(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not-json")

    result = SharePointClient(_configured(settings), transport=httpx.MockTransport(malformed)).list_sites()
    assert "malformed JSON" in result.result.message
    assert SharePointClient(_configured(settings)).get_site("bad/id").result.status == "failed"
    assert SharePointClient(_configured(settings)).list_documents("bad/id").result.status == "failed"
    assert SharePointClient(_configured(settings)).get_document(SITE_ID, "bad/id").result.status == "failed"
    assert SharePointClient(_configured(settings)).list_sites(cursor=" ").result.status == "failed"

    missing = SharePointClient(replace(settings, allow_http_probing=True))
    with pytest.raises(SharePointReadError, match="WAIT_SHAREPOINT_BASE_URL"):
        missing._get("sites")
    assert missing.list_sites().result.status == "not_configured"
    assert missing.list_documents(SITE_ID).result.status == "not_configured"
    blocked = SharePointClient(_configured(settings, allow_http_probing=False))
    with pytest.raises(SharePointReadError, match="WAIT_ALLOW_HTTP_PROBING=true"):
        blocked._get("sites")
    assert blocked.get_document_content(SITE_ID, "file-1").result.status == "blocked"
    with pytest.raises(SharePointReadError, match="WAIT_ALLOW_HTTP_PROBING=true"):
        blocked._get_content("sites/file-1/content", filename="file.txt")
    with pytest.raises(SharePointReadError, match="WAIT_SHAREPOINT_BASE_URL"):
        missing._get_content("sites/file-1/content", filename="file.txt")


def test_sharepoint_http_and_normalization_edges(settings) -> None:
    for status_code, marker in (
        (401, "authentication failed"),
        (404, "not found"),
        (429, "rate limited"),
        (500, "HTTP 500"),
    ):
        def failed(request: httpx.Request, code=status_code) -> httpx.Response:
            return httpx.Response(code, text="private body")

        result = SharePointClient(
            _configured(settings), transport=httpx.MockTransport(failed)
        ).list_sites()
        assert marker in result.result.message

    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("private timeout")

    result = SharePointClient(_configured(settings), transport=httpx.MockTransport(timeout)).list_sites()
    assert result.result.message == "SharePoint request failed before receiving a response."

    def protocol_error(request: httpx.Request) -> httpx.Response:
        raise httpx.ProtocolError("private transport detail")

    result = SharePointClient(
        _configured(settings), transport=httpx.MockTransport(protocol_error)
    ).list_sites()
    assert result.result.message == "SharePoint request failed."
    assert SharePointClient(
        _configured(settings), transport=httpx.MockTransport(lambda request: httpx.Response(500))
    ).health().status == "failed"

    assert _api_base_url("https://graph.microsoft.com/v1.0/") == "https://graph.microsoft.com/v1.0"
    assert _list_params(1000, "next") == {"$top": 200, "$skiptoken": "next"}
    assert _next_cursor({"@odata.nextLink": "https://graph.microsoft.com/v1.0/sites?$skiptoken=next"}) == "next"
    assert _next_cursor({"@odata.nextLink": "https://graph.microsoft.com/v1.0/sites?$skiptoken=" + "x" * 5000}) == ""
    assert _payload_rows({"data": {"id": "1"}}) == [{"id": "1"}]
    assert _payload_rows([{"id": "1"}, "ignored"]) == [{"id": "1"}]
    assert _normalize_site({"id": "1", "name": "ops"}) == SharePointSite("1", "ops", "", "")
    assert _normalize_document(
        {"id": "2", "name": "file", "size": 4, "parentReference": {"id": "root"}},
        SITE_ID,
    ) == SharePointDocument("2", "file", SITE_ID, "root", 4, "", "", False)
    assert _normalize_document({"name": "missing"}, SITE_ID) is None
    with pytest.raises(SharePointReadError):
        _bounded_page_size(0)
    with pytest.raises(SharePointReadError):
        _bounded_page_size(True)
    for base_url in (
        "",
        "ftp://host",
        "https://user:pass@host",
        "https://host?token=x",
        "https://host\n",
    ):
        with pytest.raises(SharePointReadError):
            _api_base_url(base_url)
    assert _payload_rows(None) == []
    assert _normalize_site({}) is None
    assert _next_cursor({}) == ""
    for helper, value in (
        (_safe_segment, ""),
        (_safe_segment, "bad/id"),
        (_safe_segment, ".."),
        (_safe_cursor, "bad\nvalue"),
        (_safe_endpoint, "//host"),
        (_safe_endpoint, ""),
        (_safe_endpoint, "sites/$bad"),
    ):
        with pytest.raises(SharePointReadError):
            helper(value)
    assert _next_cursor([]) == ""
    assert _string_value(None, "id") == ""


def test_sharepoint_text_document_content_is_bounded_and_rejects_binary(settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/content"):
            if request.url.path.endswith("file-1/content"):
                assert request.headers["Range"] == f"bytes=0-{MAX_CONTENT_LENGTH}"
                return httpx.Response(
                    200,
                    headers={"content-type": "text/plain"},
                    content=("token=secret " + "x" * (MAX_CONTENT_LENGTH + 100)).encode(),
                )
            if request.url.path.endswith("file-3/content"):
                return httpx.Response(404)
            return httpx.Response(200, headers={"content-type": "application/octet-stream"}, content=b"binary")
        file_id = (
            "file-1"
            if request.url.path.endswith("file-1")
            else "file-2"
            if request.url.path.endswith("file-2")
            else "file-3"
        )
        return httpx.Response(
            200,
            json={
                "id": file_id,
                "name": "MFA.txt" if file_id == "file-1" else "MFA.bin",
                "file": {"mimeType": "text/plain"},
            },
        )

    client = SharePointClient(_configured(settings), transport=httpx.MockTransport(handler))
    content = client.get_document_content(SITE_ID, "file-1")
    assert content.result.status == "ready"
    assert len(content.items[0].content) == MAX_CONTENT_LENGTH  # type: ignore[union-attr]
    assert content.items[0].content.startswith("token=secret")  # type: ignore[union-attr]

    binary = client.get_document_content(SITE_ID, "file-2")
    assert binary.result.status == "failed"
    assert "supported text document" in binary.result.message

    failed = client.get_document_content(SITE_ID, "file-3")
    assert failed.result.status == "failed"
    assert "HTTP 404" in failed.result.message

    non_file = SharePointClient(
        _configured(settings),
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"id": "folder-1", "name": "Folder"})),
    ).get_document_content(SITE_ID, "folder-1")
    assert non_file.result.status == "failed"
    assert "not a downloadable file" in non_file.result.message
