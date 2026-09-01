from __future__ import annotations

import json
from dataclasses import replace
from typing import Any, cast

import httpx
import pytest

from wait_local_agent.m365_auth import M365AuthFailure, M365Connection, M365ProfileResolutionError
from wait_local_agent.m365_graph import (
    M365GraphClient,
    M365GraphGroup,
    M365GraphGroupMembershipResult,
    M365GraphGroupReadResponse,
    M365GraphLicenseChangeResult,
    M365GraphLicenseDetail,
    M365GraphLicenseDetailReadResponse,
    M365GraphLicenseReadResponse,
    M365GraphMailboxSettingsUpdateResult,
    M365GraphMailFolder,
    M365GraphMailFolderReadResponse,
    M365GraphMailMessage,
    M365GraphMailMessageDeleteResult,
    M365GraphMailMessageMoveResult,
    M365GraphMailMessageReadResponse,
    M365GraphMailMessageReadStateResult,
    M365GraphManagedDevice,
    M365GraphManagedDeviceReadResponse,
    M365GraphManagedDeviceRebootResult,
    M365GraphManagedDeviceRemoteLockResult,
    M365GraphManagedDeviceRetireResult,
    M365GraphManagedDeviceSyncResult,
    M365GraphReadError,
    M365GraphServicePlan,
    M365GraphSessionRevokeResult,
    M365GraphSubscribedSku,
    M365GraphUser,
    M365GraphUserCreateResult,
    M365GraphUserDisableResult,
    _api_base_url,
    _bounded_page_size,
    _group_list_params,
    _license_detail_params,
    _license_details_endpoint,
    _list_params,
    _mail_folder_endpoint,
    _mail_folder_params,
    _mail_message_endpoint,
    _mail_message_params,
    _managed_device_params,
    _next_cursor,
    _normalize_group,
    _normalize_license_detail,
    _normalize_mail_folder,
    _normalize_mail_message,
    _normalize_managed_device,
    _normalize_subscribed_sku,
    _normalize_user,
    _payload_rows,
    _safe_cursor,
    _safe_endpoint,
    _safe_identity,
    _safe_mail_folder_id,
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


@pytest.mark.parametrize("operation", ["get", "post", "patch", "delete"])
def test_connection_seam_auth_failures_are_sanitized(settings, operation: str) -> None:
    class FailingToken:
        configured = True

        def get_token(self) -> str:
            raise M365AuthFailure("secret token detail")

    client = M365GraphClient(
        replace(_configured(settings, allow_http_probing=True), allow_write_actions=True),
        connection=M365Connection(
            graph_base_url="https://graph.microsoft.com/v1.0",
            token_provider=FailingToken(),
        ),
    )
    calls = {
        "get": lambda: client._get("users"),
        "post": lambda: client._post("users", {}),
        "patch": lambda: client._patch("users/user-1", {}),
        "delete": lambda: client._delete("users/user-1"),
    }
    with pytest.raises(M365GraphReadError, match="token acquisition failed"):
        calls[operation]()


@pytest.mark.parametrize("operation", ["get", "post", "patch", "delete"])
def test_connection_seam_profile_resolution_failures_are_sanitized(settings, operation: str) -> None:
    class Resolver:
        calls = 0

        def resolve(self, _client_id: str | None):
            self.calls += 1
            if self.calls == 1:
                return M365Connection(
                    graph_base_url="https://graph.microsoft.com/v1.0",
                    token_provider=type("ConfiguredToken", (), {"configured": True})(),
                )
            raise M365ProfileResolutionError("profile selection detail")

    client = M365GraphClient(
        _configured(settings, allow_http_probing=True),
        connection_resolver=cast(Any, Resolver()),
    )
    client.settings = replace(client.settings, allow_write_actions=True)
    calls = {
        "get": lambda: client._get("users"),
        "post": lambda: client._post("users", {}),
        "patch": lambda: client._patch("users/user-1", {}),
        "delete": lambda: client._delete("users/user-1"),
    }
    with pytest.raises(M365GraphReadError, match="profile selection detail"):
        calls[operation]()
    assert M365GraphClient(settings).list_license_details(identity="user-1").result.status == "blocked"
    assert (
        M365GraphClient(settings)
        .update_mailbox_settings(user_identity="user-1", settings={"locale": "en-US"})
        .status
        == "blocked"
    )
    assert M365GraphClient(settings).health().status == "blocked"
    missing = M365GraphClient(replace(settings, allow_http_probing=True)).health()
    assert missing.status == "not_configured"
    assert "WAIT_M365_ACCESS_TOKEN" in missing.message
    missing_license_details = M365GraphClient(
        replace(settings, allow_http_probing=True)
    ).list_license_details(identity="user-1")
    assert missing_license_details.result.status == "not_configured"


def test_m365_graph_user_creation_is_write_gated_and_never_returns_password(settings) -> None:
    active_settings = replace(
        _configured(settings),
        allow_write_actions=True,
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/v1.0/users"
        assert request.headers["Authorization"] == "Bearer access-token"
        payload = json.loads(request.content)
        assert payload == {
            "accountEnabled": True,
            "displayName": "Adele Vance",
            "mailNickname": "adele.vance",
            "userPrincipalName": "adele.vance@example.test",
            "passwordProfile": {
                "forceChangePasswordNextSignIn": True,
                "password": "Temporary-Password-123!",
            },
        }
        return httpx.Response(
            201,
            json={
                "id": "user-1",
                "displayName": "Adele Vance",
                "userPrincipalName": "adele.vance@example.test",
                "accountEnabled": True,
                "passwordProfile": {"password": "must-not-leak"},
            },
        )

    response = M365GraphClient(
        active_settings,
        transport=httpx.MockTransport(handler),
    ).create_user(
        user_principal_name="adele.vance@example.test",
        display_name="Adele Vance",
        mail_nickname="adele.vance",
        temporary_password="Temporary-Password-123!",
        account_enabled=True,
        force_change_password_next_sign_in=True,
    )

    assert response == M365GraphUserCreateResult(
        "succeeded",
        "Microsoft Graph user creation succeeded.",
        remote_id="user-1",
        user_principal_name="adele.vance@example.test",
        display_name="Adele Vance",
        account_enabled=True,
        status_code=201,
    )
    assert "password" not in response.message.lower()


def test_m365_graph_password_reset_uses_documented_password_profile_patch(settings) -> None:
    active_settings = replace(_configured(settings), allow_write_actions=True)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "PATCH"
        assert request.url.path == "/v1.0/users/adele.vance@example.test"
        assert json.loads(request.content) == {
            "passwordProfile": {
                "password": "Temporary-Password-123!",
                "forceChangePasswordNextSignIn": True,
                "forceChangePasswordNextSignInWithMfa": True,
            }
        }
        return httpx.Response(204)

    response = M365GraphClient(
        active_settings, transport=httpx.MockTransport(handler)
    ).reset_user_password(
        user_identity="adele.vance@example.test",
        temporary_password="Temporary-Password-123!",
        force_change_password_next_sign_in=True,
        force_change_password_next_sign_in_with_mfa=True,
    )
    assert response.status == "succeeded"
    assert response.status_code == 204
    assert "Temporary-Password-123!" not in response.message


def test_m365_graph_authentication_method_delete_uses_allowlisted_endpoint(settings) -> None:
    active_settings = replace(_configured(settings), allow_write_actions=True)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "DELETE"
        assert (
            request.url.path
            == "/v1.0/users/adele.vance@example.test/authentication/fido2Methods/method-1"
        )
        return httpx.Response(204)

    response = M365GraphClient(
        active_settings, transport=httpx.MockTransport(handler)
    ).delete_authentication_method(
        user_identity="adele.vance@example.test",
        method_type="fido2",
        method_id="method-1",
    )
    assert response.status == "succeeded"
    assert response.method_type == "fido2"

    blocked = M365GraphClient(
        active_settings, transport=httpx.MockTransport(handler)
    ).delete_authentication_method(
        user_identity="adele.vance@example.test",
        method_type="phone",
        method_id="not-a-phone-resource-id",
    )
    assert blocked.status == "failed"


def test_m365_graph_password_and_authentication_validation_fail_closed(settings) -> None:
    blocked = M365GraphClient(_configured(settings, allow_http_probing=False)).reset_user_password(
        user_identity="user@example.test",
        temporary_password="Temporary-Password-123!",
        force_change_password_next_sign_in=True,
        force_change_password_next_sign_in_with_mfa=False,
    )
    assert blocked.status == "blocked"

    blocked_method = M365GraphClient(
        _configured(settings, allow_http_probing=False)
    ).delete_authentication_method(
        user_identity="user@example.test",
        method_type="fido2",
        method_id="method-1",
    )
    assert blocked_method.status == "blocked"

    active_settings = replace(_configured(settings), allow_write_actions=True)
    invalid_password = M365GraphClient(
        active_settings, transport=httpx.MockTransport(lambda request: httpx.Response(204))
    ).reset_user_password(
        user_identity="user@example.test",
        temporary_password="short",
        force_change_password_next_sign_in=True,
        force_change_password_next_sign_in_with_mfa=False,
    )
    assert invalid_password.status == "failed"

    invalid_flags = M365GraphClient(
        active_settings, transport=httpx.MockTransport(lambda request: httpx.Response(204))
    ).reset_user_password(
        user_identity="user@example.test",
        temporary_password="Temporary-Password-123!",
        force_change_password_next_sign_in=False,
        force_change_password_next_sign_in_with_mfa=True,
    )
    assert invalid_flags.status == "failed"

    invalid_flag_type = M365GraphClient(
        active_settings, transport=httpx.MockTransport(lambda request: httpx.Response(204))
    ).reset_user_password(
        user_identity="user@example.test",
        temporary_password="Temporary-Password-123!",
        force_change_password_next_sign_in=cast(Any, "yes"),
        force_change_password_next_sign_in_with_mfa=False,
    )
    assert invalid_flag_type.status == "failed"

    invalid_method = M365GraphClient(
        active_settings, transport=httpx.MockTransport(lambda request: httpx.Response(204))
    ).delete_authentication_method(
        user_identity="user@example.test",
        method_type="unsupported",
        method_id="method-1",
    )
    assert invalid_method.status == "failed"


def test_m365_graph_user_creation_blocks_when_write_flag_is_disabled(settings) -> None:
    active_settings = _configured(settings)
    response = M365GraphClient(active_settings).create_user(
        user_principal_name="adele.vance@example.test",
        display_name="Adele Vance",
        mail_nickname="adele.vance",
        temporary_password="Temporary-Password-123!",
        account_enabled=True,
        force_change_password_next_sign_in=True,
    )
    assert response.status == "blocked"
    assert "WAIT_ALLOW_WRITE_ACTIONS" in response.message


def test_m365_graph_write_health_and_create_failure_paths(settings) -> None:
    assert M365GraphClient(settings).write_health().status == "blocked"
    missing = replace(settings, allow_http_probing=True, allow_write_actions=True)
    assert M365GraphClient(missing).write_health().status == "not_configured"

    active_settings = replace(
        _configured(settings),
        allow_write_actions=True,
    )

    def forbidden(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"error": {"message": "secret must not leak"}})

    forbidden_result = M365GraphClient(
        active_settings,
        transport=httpx.MockTransport(forbidden),
    ).create_user(
        user_principal_name="adele.vance@example.test",
        display_name="Adele Vance",
        mail_nickname="adele.vance",
        temporary_password="Temporary-Password-123!",
        account_enabled=True,
        force_change_password_next_sign_in=True,
    )
    assert forbidden_result.status == "failed"
    assert "access denied" in forbidden_result.message
    assert "secret must not leak" not in forbidden_result.message

    malformed = M365GraphClient(
        active_settings,
        transport=httpx.MockTransport(lambda _request: httpx.Response(201, content=b"not-json")),
    ).create_user(
        user_principal_name="adele.vance@example.test",
        display_name="Adele Vance",
        mail_nickname="adele.vance",
        temporary_password="Temporary-Password-123!",
        account_enabled=True,
        force_change_password_next_sign_in=True,
    )
    assert malformed.status == "failed"
    assert "malformed JSON" in malformed.message

    empty = M365GraphClient(
        active_settings,
        transport=httpx.MockTransport(lambda _request: httpx.Response(201, json={})),
    ).create_user(
        user_principal_name="adele.vance@example.test",
        display_name="Adele Vance",
        mail_nickname="adele.vance",
        temporary_password="Temporary-Password-123!",
        account_enabled=True,
        force_change_password_next_sign_in=True,
    )
    assert empty.status == "failed"
    assert "no usable user identity" in empty.message

    invalid_values = [
        {"user_principal_name": "bad", "display_name": "Adele", "mail_nickname": "adele"},
        {"user_principal_name": "a@b.test", "display_name": "", "mail_nickname": "adele"},
        {"user_principal_name": "a@b.test", "display_name": "Adele", "mail_nickname": "bad+alias"},
        {
            "user_principal_name": "a@b.test",
            "display_name": "Adele",
            "mail_nickname": "adele",
            "temporary_password": "short",
        },
    ]
    for values in invalid_values:
        kwargs = {
            "user_principal_name": "a@b.test",
            "display_name": "Adele",
            "mail_nickname": "adele",
            "temporary_password": "Temporary-Password-123!",
            "account_enabled": True,
            "force_change_password_next_sign_in": True,
            **values,
        }
        result = M365GraphClient(active_settings).create_user(**cast(Any, kwargs))
        assert result.status == "failed"

    assert M365GraphClient(active_settings).list_subscribed_skus(cursor=" ").result.status == "failed"
    assert M365GraphClient(active_settings).list_managed_devices(page_size=0).result.status == "failed"
    for gated_settings in (
        settings,
        replace(settings, allow_http_probing=True, allow_write_actions=False),
        replace(settings, allow_http_probing=True, allow_write_actions=True),
    ):
        try:
            M365GraphClient(gated_settings)._post("users", {})
        except M365GraphReadError:
            pass

    def connect_failure(request: httpx.Request) -> None:
        raise httpx.ConnectError("connect failed", request=request)

    with pytest.raises(M365GraphReadError, match="before receiving"):
        M365GraphClient(
            active_settings,
            transport=httpx.MockTransport(cast(Any, connect_failure)),
        )._post("users", {})

    def generic_failure(request: httpx.Request) -> None:
        raise httpx.ReadError("read failed", request=request)

    with pytest.raises(M365GraphReadError, match="request failed"):
        M365GraphClient(
            active_settings,
            transport=httpx.MockTransport(cast(Any, generic_failure)),
        )._post("users", {})

    invalid_flags = M365GraphClient(active_settings).create_user(
            user_principal_name="a@b.test",
            display_name="Adele",
            mail_nickname="adele",
            temporary_password="Temporary-Password-123!",
            account_enabled=cast(Any, 1),
            force_change_password_next_sign_in=True,
        )
    assert invalid_flags.status == "failed"
    assert "flags" in invalid_flags.message


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


def test_m365_graph_reads_per_user_license_details(settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1.0/users/alice@example.test/licenseDetails"
        assert request.url.params["$top"] == "2"
        assert request.url.params["$select"] == "id,skuId,skuPartNumber,servicePlans"
        assert request.url.params["$skiptoken"] == "detail-next"
        return httpx.Response(
            200,
            json={
                "value": [
                    {
                        "id": "detail-1",
                        "skuId": "sku-guid",
                        "skuPartNumber": "M365_BUSINESS_PREMIUM",
                        "servicePlans": [
                            {
                                "servicePlanId": "plan-guid",
                                "servicePlanName": "EXCHANGE_S_FOUNDATION",
                                "provisioningStatus": "Success",
                                "appliesTo": "User",
                            },
                            {"servicePlanName": "missing-id"},
                            "malformed",
                        ],
                    }
                ],
                "@odata.nextLink": "https://graph.microsoft.com/v1.0/users/alice@example.test/licenseDetails?$skiptoken=detail-next-2",
            },
        )

    client = M365GraphClient(_configured(settings), transport=httpx.MockTransport(handler))
    response = client.list_license_details(
        identity="alice@example.test",
        cursor="detail-next",
        page_size=2,
    )

    assert response == M365GraphLicenseDetailReadResponse(
        result=response.result,
        items=[
            M365GraphLicenseDetail(
                "detail-1",
                "sku-guid",
                "M365_BUSINESS_PREMIUM",
                (M365GraphServicePlan("plan-guid", "EXCHANGE_S_FOUNDATION", "Success", "User"),),
            )
        ],
        next_cursor="detail-next-2",
    )
    assert _license_details_endpoint("alice@example.test").endswith("/licenseDetails")
    assert _license_detail_params(2, "next")["$top"] == 2
    assert _normalize_license_detail({"skuId": "missing-id"}) is None
    assert _normalize_license_detail({"id": "detail-2"}) == M365GraphLicenseDetail(
        "detail-2", "", "", ()
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


def test_m365_graph_mail_message_reads_select_metadata_without_body(settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1.0/users/alice@example.test/mailFolders/inbox/messages"
        assert request.headers["Authorization"] == "Bearer access-token"
        assert request.url.params["$top"] == "2"
        assert request.url.params["$select"] == (
            "id,subject,sender,receivedDateTime,isRead,hasAttachments,importance"
        )
        assert request.url.params["$skiptoken"] == "message-next"
        return httpx.Response(
            200,
            json={
                "value": [
                    {
                        "id": "message-1",
                        "subject": "VPN issue",
                        "sender": {
                            "emailAddress": {
                                "name": "Adele Vance",
                                "address": "adele@example.test",
                            }
                        },
                        "receivedDateTime": "2026-08-08T10:00:00Z",
                        "isRead": False,
                        "hasAttachments": True,
                        "importance": "high",
                        "body": {"content": "must not be returned"},
                        "bodyPreview": "must not be returned",
                    }
                ],
                "@odata.nextLink": (
                    "https://graph.microsoft.com/v1.0/users/alice/mailFolders/inbox/messages"
                    "?$skiptoken=message-next-2"
                ),
            },
        )

    client = M365GraphClient(_configured(settings), transport=httpx.MockTransport(handler))
    response = client.list_mail_messages(
        identity="alice@example.test",
        folder_id="inbox",
        cursor="message-next",
        page_size=2,
    )

    assert response == M365GraphMailMessageReadResponse(
        result=response.result,
        items=[
            M365GraphMailMessage(
                "message-1",
                "VPN issue",
                "Adele Vance",
                "adele@example.test",
                "2026-08-08T10:00:00Z",
                False,
                True,
                "high",
            )
        ],
        next_cursor="message-next-2",
    )
    assert _mail_message_endpoint("alice@example.test", "inbox").endswith(
        "/mailFolders/inbox/messages"
    )
    assert _mail_message_params(2, "next")["$top"] == 2
    assert _normalize_mail_message({"subject": "missing id"}) is None
    assert M365GraphClient(_configured(settings)).list_mail_messages(
        identity="alice@example.test"
    ).result.message == "Microsoft Graph mail folder is required."


def test_m365_graph_mail_message_move_is_write_gated_and_allowlisted(settings) -> None:
    blocked = M365GraphClient(_configured(settings)).move_mail_message(
        user_identity="alice@example.test",
        source_folder_id="inbox",
        message_id="message-1",
        destination_folder_id="archive",
    )
    assert blocked.status == "blocked"

    active = replace(_configured(settings), allow_write_actions=True)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == (
            "/v1.0/users/alice@example.test/mailFolders/inbox/messages/message-1/move"
        )
        assert request.headers["Authorization"] == "Bearer access-token"
        assert request.headers["Content-Type"] == "application/json"
        assert json.loads(request.content) == {"destinationId": "archive"}
        return httpx.Response(201, json={})

    moved = M365GraphClient(active, transport=httpx.MockTransport(handler)).move_mail_message(
        user_identity="alice@example.test",
        source_folder_id="inbox",
        message_id="message-1",
        destination_folder_id="archive",
    )
    assert moved == M365GraphMailMessageMoveResult(
        "succeeded",
        "Microsoft Graph mail message move succeeded.",
        "alice@example.test",
        "inbox",
        "message-1",
        "archive",
        201,
    )
    assert M365GraphClient(active).move_mail_message(
        user_identity="alice@example.test",
        source_folder_id="bad folder",
        message_id="message-1",
        destination_folder_id="archive",
    ).status == "failed"


def test_m365_graph_mail_message_read_state_is_write_gated_and_allowlisted(settings) -> None:
    blocked = M365GraphClient(_configured(settings)).update_mail_message_read_state(
        user_identity="alice@example.test",
        source_folder_id="inbox",
        message_id="message-1",
        is_read=True,
    )
    assert blocked.status == "blocked"

    active = replace(_configured(settings), allow_write_actions=True)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "PATCH"
        assert request.url.path == (
            "/v1.0/users/alice@example.test/mailFolders/inbox/messages/message-1"
        )
        assert request.headers["Authorization"] == "Bearer access-token"
        assert request.headers["Content-Type"] == "application/json"
        assert json.loads(request.content) == {"isRead": False}
        return httpx.Response(200, json={})

    updated = M365GraphClient(
        active, transport=httpx.MockTransport(handler)
    ).update_mail_message_read_state(
        user_identity="alice@example.test",
        source_folder_id="inbox",
        message_id="message-1",
        is_read=False,
    )
    assert updated == M365GraphMailMessageReadStateResult(
        "succeeded",
        "Microsoft Graph mail message read-state update succeeded.",
        "alice@example.test",
        "inbox",
        "message-1",
        False,
        200,
    )
    assert M365GraphClient(active).update_mail_message_read_state(
        user_identity="alice@example.test",
        source_folder_id="bad folder",
        message_id="message-1",
        is_read=True,
    ).status == "failed"
    assert M365GraphClient(active).update_mail_message_read_state(
        user_identity="alice@example.test",
        source_folder_id="inbox",
        message_id="message-1",
        is_read=cast(Any, "true"),
    ).status == "failed"


def test_m365_graph_mail_message_delete_is_write_gated_and_allowlisted(settings) -> None:
    blocked = M365GraphClient(_configured(settings)).delete_mail_message(
        user_identity="alice@example.test",
        source_folder_id="inbox",
        message_id="message-1",
    )
    assert blocked.status == "blocked"

    active = replace(_configured(settings), allow_write_actions=True)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "DELETE"
        assert request.url.path == (
            "/v1.0/users/alice@example.test/mailFolders/inbox/messages/message-1"
        )
        assert request.headers["Authorization"] == "Bearer access-token"
        assert request.content == b""
        return httpx.Response(204)

    deleted = M365GraphClient(
        active, transport=httpx.MockTransport(handler)
    ).delete_mail_message(
        user_identity="alice@example.test",
        source_folder_id="inbox",
        message_id="message-1",
    )
    assert deleted == M365GraphMailMessageDeleteResult(
        "succeeded",
        "Microsoft Graph mail message deletion succeeded.",
        "alice@example.test",
        "inbox",
        "message-1",
        204,
    )
    assert M365GraphClient(active).delete_mail_message(
        user_identity="alice@example.test",
        source_folder_id="bad folder",
        message_id="message-1",
    ).status == "failed"


def test_m365_graph_managed_device_reads_select_safe_intune_context(settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1.0/deviceManagement/managedDevices"
        assert request.headers["Authorization"] == "Bearer access-token"
        assert request.url.params["$top"] == "2"
        assert request.url.params["$select"] == (
            "id,userId,deviceName,managedDeviceOwnerType,enrolledDateTime,"
            "lastSyncDateTime,operatingSystem,complianceState,managementAgent,"
            "osVersion,azureADRegistered,deviceRegistrationState,isEncrypted,"
            "userPrincipalName,userDisplayName,model,manufacturer"
        )
        assert request.url.params["$skiptoken"] == "device-next"
        assert "serialNumber" not in str(request.url)
        return httpx.Response(
            200,
            json={
                "value": [
                    {
                        "id": "device-1",
                        "userId": "user-1",
                        "deviceName": "LAPTOP-1",
                        "managedDeviceOwnerType": "company",
                        "enrolledDateTime": "2026-08-01T10:00:00Z",
                        "lastSyncDateTime": "2026-08-07T10:00:00Z",
                        "operatingSystem": "Windows",
                        "complianceState": "compliant",
                        "managementAgent": "mdm",
                        "osVersion": "11.0",
                        "azureADRegistered": True,
                        "deviceRegistrationState": "registered",
                        "isEncrypted": True,
                        "userPrincipalName": "user@example.test",
                        "userDisplayName": "Adele Vance",
                        "model": "Surface",
                        "manufacturer": "Microsoft",
                        "serialNumber": "sensitive-serial",
                        "imei": "sensitive-imei",
                        "remoteAssistanceSessionUrl": "https://sensitive.example.test",
                    }
                ],
                "@odata.nextLink": (
                    "https://graph.microsoft.com/v1.0/deviceManagement/managedDevices?"
                    "$skiptoken=device-next-2"
                ),
            },
        )

    client = M365GraphClient(_configured(settings), transport=httpx.MockTransport(handler))
    response = client.list_managed_devices(cursor="device-next", page_size=2)

    assert response == M365GraphManagedDeviceReadResponse(
        result=response.result,
        items=[
            M365GraphManagedDevice(
                "device-1",
                "user-1",
                "LAPTOP-1",
                "company",
                "2026-08-01T10:00:00Z",
                "2026-08-07T10:00:00Z",
                "Windows",
                "compliant",
                "mdm",
                "11.0",
                True,
                "registered",
                True,
                "user@example.test",
                "Adele Vance",
                "Surface",
                "Microsoft",
            )
        ],
        next_cursor="device-next-2",
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
    license_detail_result = M365GraphClient(
        _configured(settings), transport=httpx.MockTransport(denied)
    ).list_license_details(identity="user@example.test")
    assert "HTTP 403" in license_detail_result.result.message
    assert "private body" not in license_detail_result.result.message
    folder_result = M365GraphClient(
        _configured(settings), transport=httpx.MockTransport(denied)
    ).list_mail_folders(identity="user@example.test")
    assert "HTTP 403" in folder_result.result.message
    assert "private body" not in folder_result.result.message
    message_result = M365GraphClient(
        _configured(settings), transport=httpx.MockTransport(denied)
    ).list_mail_messages(identity="user@example.test", folder_id="inbox")
    assert "HTTP 403" in message_result.result.message
    assert "private body" not in message_result.result.message
    device_result = M365GraphClient(
        _configured(settings), transport=httpx.MockTransport(denied)
    ).list_managed_devices()
    assert "HTTP 403" in device_result.result.message
    assert "private body" not in device_result.result.message

    def malformed(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not-json")

    result = M365GraphClient(
        _configured(settings), transport=httpx.MockTransport(malformed)
    ).list_users()
    assert "malformed JSON" in result.result.message
    message_result = M365GraphClient(
        _configured(settings), transport=httpx.MockTransport(malformed)
    ).list_mail_messages(identity="user@example.test", folder_id="inbox")
    assert "malformed JSON" in message_result.result.message
    assert M365GraphClient(_configured(settings)).list_users(page_size=0).result.status == "failed"
    assert M365GraphClient(_configured(settings)).list_license_details(
        identity="user@example.test", page_size=0
    ).result.status == "failed"
    assert M365GraphClient(_configured(settings)).list_users(identity="bad\nvalue").result.status == "failed"
    assert M365GraphClient(_configured(settings)).list_groups(page_size=0).result.status == "failed"
    assert M365GraphClient(_configured(settings)).list_groups(identity="bad\nvalue").result.status == "failed"
    assert M365GraphClient(_configured(settings)).list_license_details(
        identity="bad\nvalue"
    ).result.status == "failed"
    assert (
        M365GraphClient(_configured(settings))
        .list_mail_messages(identity=None, folder_id="inbox")
        .result.status
        == "failed"
    )
    assert (
        M365GraphClient(_configured(settings))
        .list_mail_messages(identity="user@example.test", folder_id="bad folder")
        .result.status
        == "failed"
    )

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
    assert M365GraphClient(
        replace(
            settings,
            allow_http_probing=True,
            m365_graph_base_url="https://graph.microsoft.com/v1.0",
        )
    ).list_mail_messages(identity="user@example.test", folder_id="inbox").result.status == "not_configured"
    assert M365GraphClient(
        replace(
            settings,
            allow_http_probing=True,
            m365_graph_base_url="https://graph.microsoft.com/v1.0",
        )
    ).list_managed_devices().result.status == "not_configured"

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
    with pytest.raises(M365GraphReadError, match="mail folder is invalid"):
        _safe_mail_folder_id("bad folder")
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
    assert _managed_device_params(1000, "next") == {
        "$top": 200,
        "$select": (
            "id,userId,deviceName,managedDeviceOwnerType,enrolledDateTime,"
            "lastSyncDateTime,operatingSystem,complianceState,managementAgent,"
            "osVersion,azureADRegistered,deviceRegistrationState,isEncrypted,"
            "userPrincipalName,userDisplayName,model,manufacturer"
        ),
        "$skiptoken": "next",
    }
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
    assert _normalize_managed_device({}) is None
    assert _normalize_subscribed_sku({}) is None
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
        (_safe_endpoint, "users/other/extra"),
        (_safe_endpoint, "//host"),
        (_safe_endpoint, "users/bad\nvalue/mailFolders"),
        (_safe_endpoint, "users/user-1/assignLicense/extra"),
        (_safe_endpoint, "users/user-1/revokeSignInSessions/extra"),
    ):
        with pytest.raises(M365GraphReadError):
            helper(value)
    assert _safe_endpoint("groups") == "groups"
    assert _safe_endpoint("subscribedSkus") == "subscribedSkus"
    assert _safe_endpoint("deviceManagement/managedDevices") == (
        "deviceManagement/managedDevices"
    )
    assert _safe_endpoint("users/user%40example.test/mailFolders") == (
        "users/user%40example.test/mailFolders"
    )
    assert _safe_endpoint("users/user%40example.test") == "users/user%40example.test"
    assert _safe_endpoint("users/user-1/assignLicense") == "users/user-1/assignLicense"
    assert _safe_endpoint("users/user-1/revokeSignInSessions") == (
        "users/user-1/revokeSignInSessions"
    )
    assert _safe_endpoint("users/user-1/mailFolders/inbox/messages/message-1") == (
        "users/user-1/mailFolders/inbox/messages/message-1"
    )


def test_m365_graph_user_disable_patches_only_account_enabled(settings) -> None:
    active_settings = replace(
        _configured(settings),
        allow_write_actions=True,
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "PATCH"
        assert request.url.raw_path == b"/v1.0/users/adele.vance%40example.test"
        assert request.headers["Authorization"] == "Bearer access-token"
        assert json.loads(request.content) == {"accountEnabled": False}
        return httpx.Response(204)

    response = M365GraphClient(
        active_settings,
        transport=httpx.MockTransport(handler),
    ).disable_user(user_identity="adele.vance@example.test")

    assert response == M365GraphUserDisableResult(
        "succeeded",
        "Microsoft Graph user disable succeeded.",
        user_identity="adele.vance@example.test",
        status_code=204,
    )


def test_m365_graph_user_disable_is_write_gated_and_sanitizes_failures(settings) -> None:
    blocked = M365GraphClient(_configured(settings)).disable_user(
        user_identity="adele.vance@example.test"
    )
    assert blocked.status == "blocked"
    assert "WAIT_ALLOW_WRITE_ACTIONS" in blocked.message

    active_settings = replace(
        _configured(settings),
        allow_write_actions=True,
    )
    forbidden = M365GraphClient(
        active_settings,
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                403,
                json={"error": {"message": "secret must not leak"}},
            )
        ),
    ).disable_user(user_identity="adele.vance@example.test")
    assert forbidden.status == "failed"
    assert "access denied" in forbidden.message
    assert "secret must not leak" not in forbidden.message

    malformed = M365GraphClient(
        active_settings,
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(200, content=b"not-json")
        ),
    ).disable_user(user_identity="adele.vance@example.test")
    assert malformed.status == "failed"
    assert "malformed JSON" in malformed.message

    invalid = M365GraphClient(active_settings).disable_user(user_identity="bad\nvalue")
    assert invalid.status == "failed"
    assert "identity is invalid" in invalid.message


def test_m365_graph_group_membership_add_and_remove_use_ref_endpoints(settings) -> None:
    active_settings = replace(
        _configured(settings),
        allow_write_actions=True,
    )
    requests: list[tuple[str, str, bytes]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append((request.method, request.url.path, request.content))
        if request.method == "POST":
            assert json.loads(request.content) == {
                "@odata.id": "https://graph.microsoft.com/v1.0/directoryObjects/user-1"
            }
        else:
            assert request.content == b""
        assert request.headers["Authorization"] == "Bearer access-token"
        return httpx.Response(204)

    client = M365GraphClient(
        active_settings,
        transport=httpx.MockTransport(handler),
    )
    added = client.change_group_membership(
        group_id="group-1",
        user_id="user-1",
        operation="add",
    )
    removed = client.change_group_membership(
        group_id="group-1",
        user_id="user-1",
        operation="remove",
    )

    assert added == M365GraphGroupMembershipResult(
        "succeeded",
        "Microsoft Graph group membership add succeeded.",
        group_id="group-1",
        user_id="user-1",
        operation="add",
        status_code=204,
    )
    assert removed == M365GraphGroupMembershipResult(
        "succeeded",
        "Microsoft Graph group membership remove succeeded.",
        group_id="group-1",
        user_id="user-1",
        operation="remove",
        status_code=204,
    )
    assert requests == [
        ("POST", "/v1.0/groups/group-1/members/$ref", b'{"@odata.id":"https://graph.microsoft.com/v1.0/directoryObjects/user-1"}'),
        ("DELETE", "/v1.0/groups/group-1/members/user-1/$ref", b""),
    ]


def test_m365_graph_group_membership_validates_ids_and_sanitizes_delete_failures(settings) -> None:
    active_settings = replace(
        _configured(settings),
        allow_write_actions=True,
    )
    invalid_operation = M365GraphClient(active_settings).change_group_membership(
        group_id="group-1",
        user_id="user-1",
        operation="replace",
    )
    assert invalid_operation.status == "failed"
    assert "operation is invalid" in invalid_operation.message

    invalid_id = M365GraphClient(active_settings).change_group_membership(
        group_id="group\n1",
        user_id="user-1",
        operation="add",
    )
    assert invalid_id.status == "failed"
    assert "group_id is invalid" in invalid_id.message

    forbidden = M365GraphClient(
        active_settings,
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                403,
                json={"error": {"message": "secret must not leak"}},
            )
        ),
    ).change_group_membership(
        group_id="group-1",
        user_id="user-1",
        operation="remove",
    )
    assert forbidden.status == "failed"
    assert "access denied" in forbidden.message
    assert "secret must not leak" not in forbidden.message


def test_m365_graph_group_membership_delete_guards_and_transport_failures(settings) -> None:
    blocked = M365GraphClient(_configured(settings)).change_group_membership(
        group_id="group-1",
        user_id="user-1",
        operation="remove",
    )
    assert blocked.status == "blocked"
    assert "WAIT_ALLOW_WRITE_ACTIONS" in blocked.message

    with pytest.raises(M365GraphReadError, match="WAIT_ALLOW_HTTP_PROBING"):
        M365GraphClient(settings)._delete("groups/group-1/members/user-1/$ref")

    write_blocked = replace(_configured(settings), allow_write_actions=False)
    with pytest.raises(M365GraphReadError, match="WAIT_ALLOW_WRITE_ACTIONS"):
        M365GraphClient(write_blocked)._delete("groups/group-1/members/user-1/$ref")

    missing = replace(settings, allow_http_probing=True, allow_write_actions=True)
    with pytest.raises(M365GraphReadError, match="WAIT_M365_ACCESS_TOKEN"):
        M365GraphClient(missing)._delete("groups/group-1/members/user-1/$ref")

    active_settings = replace(_configured(settings), allow_write_actions=True)
    timeout = M365GraphClient(
        active_settings,
        transport=httpx.MockTransport(
            lambda _request: (_ for _ in ()).throw(httpx.ReadTimeout("timed out"))
        ),
    ).change_group_membership(
        group_id="group-1",
        user_id="user-1",
        operation="remove",
    )
    assert timeout.status == "failed"
    assert "before receiving a response" in timeout.message

    transport_error = M365GraphClient(
        active_settings,
        transport=httpx.MockTransport(
            lambda _request: (_ for _ in ()).throw(httpx.WriteError("transport failed"))
        ),
    ).change_group_membership(
        group_id="group-1",
        user_id="user-1",
        operation="remove",
    )
    assert transport_error.status == "failed"
    assert transport_error.message == "Microsoft Graph request failed."


def test_m365_graph_license_changes_use_assign_license_contract(settings) -> None:
    sku_ids = [
        "84a661c4-e949-4bd2-a560-ed7766fcaf2b",
        "f30db892-07e9-47e9-837c-80727f46fd3d",
    ]
    requests: list[tuple[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append((request.url.path, json.loads(request.content)))
        assert request.method == "POST"
        assert request.headers["Authorization"] == "Bearer access-token"
        return httpx.Response(200, json={"id": "must-not-be-persisted"})

    client = M365GraphClient(
        replace(_configured(settings), allow_write_actions=True),
        transport=httpx.MockTransport(handler),
    )
    added = client.change_user_licenses(
        user_id="user-1", sku_ids=sku_ids, operation="add"
    )
    removed = client.change_user_licenses(
        user_id="user-1", sku_ids=[sku_ids[0]], operation="remove"
    )

    assert requests == [
        (
            "/v1.0/users/user-1/assignLicense",
            {
                "addLicenses": [
                    {"disabledPlans": [], "skuId": sku_ids[0]},
                    {"disabledPlans": [], "skuId": sku_ids[1]},
                ],
                "removeLicenses": [],
            },
        ),
        (
            "/v1.0/users/user-1/assignLicense",
            {"addLicenses": [], "removeLicenses": [sku_ids[0]]},
        ),
    ]
    assert added == M365GraphLicenseChangeResult(
        "succeeded",
        "Microsoft Graph user license add succeeded.",
        user_id="user-1",
        operation="add",
        sku_ids=tuple(sku_ids),
        status_code=200,
    )
    assert removed.operation == "remove"
    assert "must-not-be-persisted" not in removed.message


def test_m365_graph_license_changes_are_strict_and_write_gated(settings) -> None:
    sku_id = "84a661c4-e949-4bd2-a560-ed7766fcaf2b"
    blocked = M365GraphClient(_configured(settings)).change_user_licenses(
        user_id="user-1", sku_ids=[sku_id], operation="add"
    )
    invalid_operation = M365GraphClient(
        replace(_configured(settings), allow_write_actions=True)
    ).change_user_licenses(user_id="user-1", sku_ids=[sku_id], operation="replace")
    invalid_sku = M365GraphClient(
        replace(_configured(settings), allow_write_actions=True)
    ).change_user_licenses(user_id="user-1", sku_ids=["not-a-guid"], operation="add")
    duplicate_sku = M365GraphClient(
        replace(_configured(settings), allow_write_actions=True)
    ).change_user_licenses(user_id="user-1", sku_ids=[sku_id, sku_id], operation="add")
    empty_skus = M365GraphClient(
        replace(_configured(settings), allow_write_actions=True)
    ).change_user_licenses(user_id="user-1", sku_ids=[], operation="add")
    non_string_sku = M365GraphClient(
        replace(_configured(settings), allow_write_actions=True)
    ).change_user_licenses(user_id="user-1", sku_ids=[7], operation="add")  # type: ignore[list-item]

    assert blocked.status == "blocked"
    assert invalid_operation.status == "failed"
    assert invalid_sku.status == "failed"
    assert duplicate_sku.status == "failed"
    assert empty_skus.status == "failed"
    assert non_string_sku.status == "failed"


def test_m365_graph_session_revocation_posts_no_body(settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/v1.0/users/user-1/revokeSignInSessions"
        assert request.content == b""
        assert request.headers["Authorization"] == "Bearer access-token"
        return httpx.Response(200, json={"value": True})

    response = M365GraphClient(
        replace(_configured(settings), allow_write_actions=True),
        transport=httpx.MockTransport(handler),
    ).revoke_user_sessions(user_id="user-1")

    assert response == M365GraphSessionRevokeResult(
        "succeeded",
        "Microsoft Graph user session revocation succeeded.",
        user_id="user-1",
        status_code=200,
    )


def test_m365_graph_session_revocation_is_write_gated_and_sanitized(settings) -> None:
    blocked = M365GraphClient(_configured(settings)).revoke_user_sessions(user_id="user-1")
    invalid = M365GraphClient(
        replace(_configured(settings), allow_write_actions=True)
    ).revoke_user_sessions(user_id="user\n1")
    forbidden = M365GraphClient(
        replace(_configured(settings), allow_write_actions=True),
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                403, json={"error": {"message": "secret must not leak"}}
            )
        ),
    ).revoke_user_sessions(user_id="user-1")

    assert blocked.status == "blocked"
    assert invalid.status == "failed"
    assert forbidden.status == "failed"
    assert "access denied" in forbidden.message
    assert "secret must not leak" not in forbidden.message


def test_m365_graph_managed_device_retirement_posts_no_body(settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/v1.0/deviceManagement/managedDevices/device-1/retire"
        assert request.content == b""
        assert request.headers["Authorization"] == "Bearer access-token"
        return httpx.Response(204)

    response = M365GraphClient(
        replace(_configured(settings), allow_write_actions=True),
        transport=httpx.MockTransport(handler),
    ).retire_managed_device(device_id="device-1")

    assert response == M365GraphManagedDeviceRetireResult(
        "succeeded",
        "Microsoft Graph Intune managed-device retirement succeeded.",
        device_id="device-1",
        status_code=204,
    )


def test_m365_graph_managed_device_retirement_is_write_gated_and_sanitized(settings) -> None:
    blocked = M365GraphClient(_configured(settings)).retire_managed_device(device_id="device-1")
    invalid = M365GraphClient(
        replace(_configured(settings), allow_write_actions=True)
    ).retire_managed_device(device_id="device\n1")
    forbidden = M365GraphClient(
        replace(_configured(settings), allow_write_actions=True),
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                403, json={"error": {"message": "secret must not leak"}}
            )
        ),
    ).retire_managed_device(device_id="device-1")

    assert blocked.status == "blocked"
    assert invalid.status == "failed"
    assert forbidden.status == "failed"
    assert "access denied" in forbidden.message
    assert "secret must not leak" not in forbidden.message


def test_m365_graph_managed_device_sync_posts_no_body(settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == (
            "/v1.0/deviceManagement/managedDevices/device-1/syncDevice"
        )
        assert request.content == b""
        assert request.headers["Authorization"] == "Bearer access-token"
        return httpx.Response(204)

    response = M365GraphClient(
        replace(_configured(settings), allow_write_actions=True),
        transport=httpx.MockTransport(handler),
    ).sync_managed_device(device_id="device-1")

    assert response == M365GraphManagedDeviceSyncResult(
        "succeeded",
        "Microsoft Graph Intune managed-device sync succeeded.",
        device_id="device-1",
        status_code=204,
    )


def test_m365_graph_managed_device_sync_is_write_gated_and_sanitized(settings) -> None:
    blocked = M365GraphClient(_configured(settings)).sync_managed_device(device_id="device-1")
    invalid = M365GraphClient(
        replace(_configured(settings), allow_write_actions=True)
    ).sync_managed_device(device_id="device\n1")
    forbidden = M365GraphClient(
        replace(_configured(settings), allow_write_actions=True),
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                403, json={"error": {"message": "secret must not leak"}}
            )
        ),
    ).sync_managed_device(device_id="device-1")

    assert blocked.status == "blocked"
    assert invalid.status == "failed"
    assert forbidden.status == "failed"
    assert "access denied" in forbidden.message
    assert "secret must not leak" not in forbidden.message


def test_m365_graph_managed_device_reboot_posts_no_body(settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == (
            "/v1.0/deviceManagement/managedDevices/device-1/rebootNow"
        )
        assert request.content == b""
        assert request.headers["Authorization"] == "Bearer access-token"
        return httpx.Response(204)

    response = M365GraphClient(
        replace(_configured(settings), allow_write_actions=True),
        transport=httpx.MockTransport(handler),
    ).reboot_managed_device(device_id="device-1")

    assert response == M365GraphManagedDeviceRebootResult(
        "succeeded",
        "Microsoft Graph Intune managed-device reboot succeeded.",
        device_id="device-1",
        status_code=204,
    )


def test_m365_graph_managed_device_reboot_is_write_gated_and_sanitized(settings) -> None:
    blocked = M365GraphClient(_configured(settings)).reboot_managed_device(device_id="device-1")
    invalid = M365GraphClient(
        replace(_configured(settings), allow_write_actions=True)
    ).reboot_managed_device(device_id="device\n1")
    forbidden = M365GraphClient(
        replace(_configured(settings), allow_write_actions=True),
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                403, json={"error": {"message": "secret must not leak"}}
            )
        ),
    ).reboot_managed_device(device_id="device-1")

    assert blocked.status == "blocked"
    assert invalid.status == "failed"
    assert forbidden.status == "failed"
    assert "access denied" in forbidden.message
    assert "secret must not leak" not in forbidden.message


def test_m365_graph_managed_device_remote_lock_posts_no_body(settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == (
            "/v1.0/deviceManagement/managedDevices/device-1/remoteLock"
        )
        assert request.content == b""
        assert request.headers["Authorization"] == "Bearer access-token"
        return httpx.Response(204)

    response = M365GraphClient(
        replace(_configured(settings), allow_write_actions=True),
        transport=httpx.MockTransport(handler),
    ).remote_lock_managed_device(device_id="device-1")

    assert response == M365GraphManagedDeviceRemoteLockResult(
        "succeeded",
        "Microsoft Graph Intune managed-device remote lock succeeded.",
        device_id="device-1",
        status_code=204,
    )


def test_m365_graph_managed_device_remote_lock_is_write_gated_and_sanitized(settings) -> None:
    blocked = M365GraphClient(_configured(settings)).remote_lock_managed_device(device_id="device-1")
    invalid = M365GraphClient(
        replace(_configured(settings), allow_write_actions=True)
    ).remote_lock_managed_device(device_id="device\n1")
    forbidden = M365GraphClient(
        replace(_configured(settings), allow_write_actions=True),
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                403, json={"error": {"message": "secret must not leak"}}
            )
        ),
    ).remote_lock_managed_device(device_id="device-1")

    assert blocked.status == "blocked"
    assert invalid.status == "failed"
    assert forbidden.status == "failed"
    assert "access denied" in forbidden.message
    assert "secret must not leak" not in forbidden.message


def test_m365_graph_mailbox_settings_update_patches_only_allowlisted_fields(settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "PATCH"
        assert request.url.path == "/v1.0/users/alice@example.test/mailboxSettings"
        assert json.loads(request.content) == {
            "timeZone": "Pacific Standard Time",
            "locale": "en-US",
        }
        return httpx.Response(200, json={})

    response = M365GraphClient(
        replace(_configured(settings), allow_write_actions=True),
        transport=httpx.MockTransport(handler),
    ).update_mailbox_settings(
        user_identity="alice@example.test",
        settings={"time_zone": "Pacific Standard Time", "locale": "en-US"},
    )

    assert response == M365GraphMailboxSettingsUpdateResult(
        "succeeded",
        "Microsoft Graph mailbox settings update succeeded.",
        user_identity="alice@example.test",
        settings={"timeZone": "Pacific Standard Time", "locale": "en-US"},
        status_code=200,
    )


def test_m365_graph_mailbox_settings_update_rejects_unsafe_fields(settings) -> None:
    client = M365GraphClient(replace(_configured(settings), allow_write_actions=True))
    for values in (
        {},
        {"forwarding_address": "attacker@example.test"},
        {"locale": ""},
        {"locale": "en\nUS"},
    ):
        response = client.update_mailbox_settings(
            user_identity="alice@example.test",
            settings=values,
        )
        assert response.status == "failed"
    invalid_identity = client.update_mailbox_settings(
        user_identity="alice\n@example.test",
        settings={"locale": "en-US"},
    )
    assert invalid_identity.status == "failed"


def test_m365_graph_patch_guards_transport_failures_and_missing_configuration(settings) -> None:
    with pytest.raises(M365GraphReadError, match="WAIT_ALLOW_HTTP_PROBING"):
        M365GraphClient(settings)._patch("users/user-1", {})

    write_blocked = replace(_configured(settings), allow_write_actions=False)
    with pytest.raises(M365GraphReadError, match="WAIT_ALLOW_WRITE_ACTIONS"):
        M365GraphClient(write_blocked)._patch("users/user-1", {})

    missing = replace(settings, allow_http_probing=True, allow_write_actions=True)
    with pytest.raises(M365GraphReadError, match="WAIT_M365_ACCESS_TOKEN"):
        M365GraphClient(missing)._patch("users/user-1", {})

    timeout = replace(_configured(settings), allow_write_actions=True)
    timeout_result = M365GraphClient(
        timeout,
        transport=httpx.MockTransport(
            lambda _request: (_ for _ in ()).throw(httpx.ReadTimeout("timed out"))
        ),
    ).disable_user(user_identity="user-1")
    assert timeout_result.status == "failed"
    assert "before receiving a response" in timeout_result.message

    http_error_result = M365GraphClient(
        timeout,
        transport=httpx.MockTransport(
            lambda _request: (_ for _ in ()).throw(httpx.WriteError("transport failed"))
        ),
    ).disable_user(user_identity="user-1")
    assert http_error_result.status == "failed"
    assert http_error_result.message == "Microsoft Graph request failed."
