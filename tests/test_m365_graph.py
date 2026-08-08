from __future__ import annotations

from dataclasses import replace

import httpx
import pytest

from wait_local_agent.m365_graph import (
    M365GraphClient,
    M365GraphGroup,
    M365GraphGroupReadResponse,
    M365GraphLicenseReadResponse,
    M365GraphMailFolder,
    M365GraphMailFolderReadResponse,
    M365GraphReadError,
    M365GraphSubscribedSku,
    M365GraphUser,
    _api_base_url,
    _bounded_page_size,
    _group_list_params,
    _list_params,
    _mail_folder_endpoint,
    _mail_folder_params,
    _next_cursor,
    _normalize_group,
    _normalize_mail_folder,
    _normalize_user,
    _payload_rows,
    _safe_cursor,
    _safe_endpoint,
    _safe_identity,
)


def _configured(settings, *, allow_http_probing: bool = True):
    return replace(
        settings,
        allow_http_probing=allow_http_probing,
        m365_graph_base_url="https://graph.microsoft.com/v1.0",
        m365_access_token="access-token",
        m365_page_size=25,
    )


def test_m365_graph_defaults_block_and_missing_credentials(settings) -> None:
    assert M365GraphClient(settings).list_users().result.status == "blocked"
    assert M365GraphClient(settings).list_groups().result.status == "blocked"
    assert M365GraphClient(settings).health().status == "blocked"
    missing = M365GraphClient(replace(settings, allow_http_probing=True)).health()
    assert missing.status == "not_configured"
    assert "WAIT_M365_ACCESS_TOKEN" in missing.message


def test_m365_graph_reads_use_bearer_auth_and_bounded_identity_filter(settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1.0/users"
        assert "access-token" not in str(request.url)
        assert request.headers["Authorization"] == "Bearer access-token"
        assert request.headers["Accept"] == "application/json"
        assert request.url.params["$top"] == "2"
        assert request.url.params["$select"] == (
            "id,displayName,userPrincipalName,mail,accountEnabled,jobTitle,department"
        )
        assert request.url.params["$filter"] == (
            "id eq 'o''hare@example.test' or userPrincipalName eq 'o''hare@example.test'"
        )
        return httpx.Response(
            200,
            json={
                "value": [
                    {
                        "id": "user-1",
                        "displayName": "O'Hare",
                        "userPrincipalName": "o'hare@example.test",
                        "mail": "o'hare@example.test",
                        "accountEnabled": True,
                        "jobTitle": "Technician",
                        "department": "Operations",
                    }
                ],
                "@odata.nextLink": (
                    "https://graph.microsoft.com/v1.0/users?$skiptoken=next-token"
                ),
            },
        )

    client = M365GraphClient(_configured(settings), transport=httpx.MockTransport(handler))
    response = client.list_users(identity="o'hare@example.test", page_size=2)
    assert response.items == [
        M365GraphUser(
            "user-1",
            "O'Hare",
            "o'hare@example.test",
            "o'hare@example.test",
            True,
            "Technician",
            "Operations",
        )
    ]
    assert response.next_cursor == "next-token"


def test_m365_graph_health_and_cursor_reads(settings) -> None:
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(str(request.url))
        if len(paths) == 1:
            assert request.url.params.get("$skiptoken") == "cursor"
        else:
            assert request.url.params.get("$skiptoken") is None
        return httpx.Response(200, json={"value": [{"id": "user-1"}]})

    client = M365GraphClient(_configured(settings), transport=httpx.MockTransport(handler))
    response = client.list_users(cursor="cursor", page_size=1000)
    assert response.result.status == "ready"
    assert response.items[0].id == "user-1"
    assert response.items[0].account_enabled is None
    assert client.health().status == "ready"
    assert len(paths) == 2


def test_m365_graph_group_reads_use_bounded_filter_and_normalization(settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1.0/groups"
        assert request.headers["Authorization"] == "Bearer access-token"
        assert request.url.params["$top"] == "2"
        assert request.url.params["$select"] == (
            "id,displayName,mail,mailNickname,description,mailEnabled,securityEnabled,groupTypes"
        )
        assert request.url.params["$filter"] == (
            "id eq 'helpdesk''s@example.test' or mail eq 'helpdesk''s@example.test' "
            "or mailNickname eq 'helpdesk''s@example.test' or "
            "displayName eq 'helpdesk''s@example.test'"
        )
        return httpx.Response(
            200,
            json={
                "value": [
                    {
                        "id": "group-1",
                        "displayName": "Helpdesk",
                        "mail": "helpdesk@example.test",
                        "mailNickname": "helpdesk",
                        "description": "Support team",
                        "mailEnabled": True,
                        "securityEnabled": False,
                        "groupTypes": ["Unified", 7],
                    }
                ],
                "@odata.nextLink": "https://graph.microsoft.com/v1.0/groups?$skiptoken=group-next",
            },
        )

    client = M365GraphClient(_configured(settings), transport=httpx.MockTransport(handler))
    response = client.list_groups(identity="helpdesk's@example.test", page_size=2)

    assert response == M365GraphGroupReadResponse(
        result=response.result,
        items=[
            M365GraphGroup(
                "group-1",
                "Helpdesk",
                "helpdesk@example.test",
                "helpdesk",
                "Support team",
                True,
                False,
                ("Unified",),
            )
        ],
        next_cursor="group-next",
    )
    assert response.result.status == "ready"


def test_m365_graph_subscribed_sku_reads_select_license_context(settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1.0/subscribedSkus"
        assert request.url.params["$select"] == (
            "id,skuId,skuPartNumber,capabilityStatus,consumedUnits,appliesTo,prepaidUnits"
        )
        assert request.url.params.get("$top") is None
        assert request.url.params["$skiptoken"] == "license-next"
        return httpx.Response(
            200,
            json={
                "value": [
                    {
                        "id": "sku-1",
                        "skuId": "sku-guid",
                        "skuPartNumber": "M365_BUSINESS_PREMIUM",
                        "capabilityStatus": "Enabled",
                        "consumedUnits": 7,
                        "appliesTo": "User",
                        "prepaidUnits": {
                            "enabled": 25,
                            "warning": 2,
                            "suspended": 1,
                            "lockedOut": 0,
                        },
                        "servicePlans": [{"servicePlanName": "ignored"}],
                    }
                ],
                "@odata.nextLink": (
                    "https://graph.microsoft.com/v1.0/subscribedSkus?$skiptoken=license-next-2"
                ),
            },
        )

    client = M365GraphClient(_configured(settings), transport=httpx.MockTransport(handler))
    response = client.list_subscribed_skus(cursor="license-next")

    assert response == M365GraphLicenseReadResponse(
        result=response.result,
        items=[
            M365GraphSubscribedSku(
                "sku-1",
                "sku-guid",
                "M365_BUSINESS_PREMIUM",
                "Enabled",
                "User",
                7,
                25,
                2,
                1,
                0,
            )
        ],
        next_cursor="license-next-2",
    )


def test_m365_graph_mail_folder_reads_use_user_path_and_metadata_only(settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/mailFolders")
        assert "/users/alice+ops@example.test/" in request.url.path
        assert request.headers["Authorization"] == "Bearer access-token"
        assert request.url.params["$top"] == "2"
        assert request.url.params["$select"] == (
            "id,displayName,parentFolderId,childFolderCount,totalItemCount,"
            "unreadItemCount,isHidden"
        )
        assert request.url.params["$skiptoken"] == "folder-next"
        assert "messages" not in str(request.url)
        return httpx.Response(
            200,
            json={
                "value": [
                    {
                        "id": "inbox-id",
                        "displayName": "Inbox",
                        "parentFolderId": "root-id",
                        "childFolderCount": 3,
                        "totalItemCount": 42,
                        "unreadItemCount": 5,
                        "isHidden": False,
                        "messages": [{"subject": "ignored"}],
                    }
                ],
                "@odata.nextLink": (
                    "https://graph.microsoft.com/v1.0/users/alice/mailFolders?$skiptoken=folder-next-2"
                ),
            },
        )

    client = M365GraphClient(_configured(settings), transport=httpx.MockTransport(handler))
    response = client.list_mail_folders(
        identity="alice+ops@example.test",
        cursor="folder-next",
        page_size=2,
    )

    assert response == M365GraphMailFolderReadResponse(
        result=response.result,
        items=[M365GraphMailFolder("inbox-id", "Inbox", "root-id", 3, 42, 5, False)],
        next_cursor="folder-next-2",
    )
    assert M365GraphClient(_configured(settings)).list_mail_folders().result.message == (
        "Microsoft Graph mailbox identity is required."
    )


def test_m365_graph_sanitizes_failures_and_edges(settings) -> None:
    def denied(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="private body")

    result = M365GraphClient(_configured(settings), transport=httpx.MockTransport(denied)).list_users()
    assert "HTTP 403" in result.result.message
    assert "private body" not in result.result.message
    group_result = M365GraphClient(
        _configured(settings), transport=httpx.MockTransport(denied)
    ).list_groups()
    assert "HTTP 403" in group_result.result.message
    assert "private body" not in group_result.result.message
    license_result = M365GraphClient(
        _configured(settings), transport=httpx.MockTransport(denied)
    ).list_subscribed_skus()
    assert "HTTP 403" in license_result.result.message
    assert "private body" not in license_result.result.message
    folder_result = M365GraphClient(
        _configured(settings), transport=httpx.MockTransport(denied)
    ).list_mail_folders(identity="user@example.test")
    assert "HTTP 403" in folder_result.result.message
    assert "private body" not in folder_result.result.message

    def malformed(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not-json")

    result = M365GraphClient(
        _configured(settings), transport=httpx.MockTransport(malformed)
    ).list_users()
    assert "malformed JSON" in result.result.message
    assert M365GraphClient(_configured(settings)).list_users(page_size=0).result.status == "failed"
    assert M365GraphClient(_configured(settings)).list_users(identity="bad\nvalue").result.status == "failed"
    assert M365GraphClient(_configured(settings)).list_groups(page_size=0).result.status == "failed"
    assert M365GraphClient(_configured(settings)).list_groups(identity="bad\nvalue").result.status == "failed"

    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("private timeout")

    result = M365GraphClient(
        _configured(settings), transport=httpx.MockTransport(timeout)
    ).list_users()
    assert result.result.message == "Microsoft Graph request failed before receiving a response."
    def protocol_error(request: httpx.Request) -> httpx.Response:
        raise httpx.ProtocolError("private transport detail")

    result = M365GraphClient(
        _configured(settings), transport=httpx.MockTransport(protocol_error)
    ).list_users()
    assert result.result.message == "Microsoft Graph request failed."
    assert M365GraphClient(
        _configured(settings), transport=httpx.MockTransport(lambda request: httpx.Response(500))
    ).health().status == "failed"

    missing = M365GraphClient(replace(settings, allow_http_probing=True))
    with pytest.raises(M365GraphReadError, match="WAIT_M365_GRAPH_BASE_URL"):
        missing._get("users")
    blocked = M365GraphClient(_configured(settings, allow_http_probing=False))
    with pytest.raises(M365GraphReadError, match="WAIT_ALLOW_HTTP_PROBING=true"):
        blocked._get("users")
    assert M365GraphClient(
        replace(
            settings,
            allow_http_probing=True,
            m365_graph_base_url="https://graph.microsoft.com/v1.0",
        )
    ).list_users().result.status == "not_configured"
    assert M365GraphClient(
        replace(
            settings,
            allow_http_probing=True,
            m365_graph_base_url="https://graph.microsoft.com/v1.0",
        )
    ).list_groups().result.status == "not_configured"
    assert M365GraphClient(
        replace(
            settings,
            allow_http_probing=True,
            m365_graph_base_url="https://graph.microsoft.com/v1.0",
        )
    ).list_subscribed_skus().result.status == "not_configured"
    assert M365GraphClient(
        replace(
            settings,
            allow_http_probing=True,
            m365_graph_base_url="https://graph.microsoft.com/v1.0",
        )
    ).list_mail_folders(identity="user@example.test").result.status == "not_configured"

    for status_code, marker in (
        (401, "authentication failed"),
        (404, "not found"),
        (429, "rate limited"),
        (500, "HTTP 500"),
    ):
        def failed(request: httpx.Request, code=status_code) -> httpx.Response:
            return httpx.Response(code, text="private body")

        result = M365GraphClient(
            _configured(settings), transport=httpx.MockTransport(failed)
        ).list_users()
        assert marker in result.result.message

    assert _api_base_url("https://graph.microsoft.com/v1.0/") == "https://graph.microsoft.com/v1.0"
    assert _list_params(1000, "next") == {
        "$top": 200,
        "$select": "id,displayName,userPrincipalName,mail,accountEnabled,jobTitle,department",
        "$skiptoken": "next",
    }
    assert _group_list_params(1000, "next") == {
        "$top": 200,
        "$select": (
            "id,displayName,mail,mailNickname,description,mailEnabled,securityEnabled,groupTypes"
        ),
        "$skiptoken": "next",
    }
    assert _mail_folder_params(1000, "next") == {
        "$top": 200,
        "$select": (
            "id,displayName,parentFolderId,childFolderCount,totalItemCount,"
            "unreadItemCount,isHidden"
        ),
        "$skiptoken": "next",
    }
    assert _mail_folder_endpoint("alice+ops@example.test") == (
        "users/alice%2Bops%40example.test/mailFolders"
    )
    assert _next_cursor(
        {"@odata.nextLink": "https://graph.microsoft.com/v1.0/users?$skiptoken=next"}
    ) == "next"
    assert _next_cursor({"@odata.nextLink": "https://graph.microsoft.com/v1.0/users?$skiptoken=" + "x" * 5000}) == ""
    assert _payload_rows({"value": {"id": "user-1"}}) == [{"id": "user-1"}]
    assert _payload_rows({"id": "user-1"}) == [{"id": "user-1"}]
    assert _payload_rows([{"id": "user-1"}, "ignored"]) == [{"id": "user-1"}]
    assert _normalize_user({"id": "user-1", "accountEnabled": "yes"}) == M365GraphUser(
        "user-1", "", "", "", None, "", ""
    )
    assert _normalize_user({}) is None
    assert _normalize_user({"id": 7}) == M365GraphUser("7", "", "", "", None, "", "")
    assert _normalize_group(
        {"id": "group-1", "groupTypes": ["Unified", 7], "mailEnabled": "yes"}
    ) == M365GraphGroup("group-1", "", "", "", "", None, None, ("Unified",))
    assert _normalize_group({}) is None
    assert _normalize_mail_folder({"id": "folder-1", "isHidden": "yes"}) == M365GraphMailFolder(
        "folder-1", "", "", None, None, None, None
    )
    assert _normalize_mail_folder({}) is None
    assert _payload_rows(None) == []
    assert _next_cursor(None) == ""
    with pytest.raises(M365GraphReadError):
        _bounded_page_size(0)
    with pytest.raises(M365GraphReadError):
        _bounded_page_size(True)
    for base_url in (
        "",
        "ftp://host",
        "https://user:pass@host",
        "https://host?token=x",
        "https://host\n",
    ):
        with pytest.raises(M365GraphReadError):
            _api_base_url(base_url)
    for helper, value in (
        (_safe_identity, ""),
        (_safe_identity, "bad\nvalue"),
        (_safe_cursor, "bad\nvalue"),
        (_safe_endpoint, "users/other"),
        (_safe_endpoint, "//host"),
        (_safe_endpoint, "users/bad\nvalue/mailFolders"),
    ):
        with pytest.raises(M365GraphReadError):
            helper(value)
    assert _safe_endpoint("groups") == "groups"
    assert _safe_endpoint("subscribedSkus") == "subscribedSkus"
    assert _safe_endpoint("users/user%40example.test/mailFolders") == (
        "users/user%40example.test/mailFolders"
    )
