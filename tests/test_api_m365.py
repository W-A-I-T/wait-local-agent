from __future__ import annotations

from dataclasses import replace

from fastapi.testclient import TestClient

import wait_local_agent.api.app as app_module
from tests.api_helpers import _auth, _provision_bound_principal
from wait_local_agent.api.app import create_app
from wait_local_agent.m365_graph import (
    M365GraphAuthenticationMethodDeleteResult,
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
    M365GraphPasswordResetResult,
    M365GraphReadResponse,
    M365GraphSessionRevokeResult,
    M365GraphSubscribedSku,
    M365GraphUser,
    M365GraphUserCreateResult,
    M365GraphUserDisableResult,
)
from wait_local_agent.models import (
    ConnectorReadResult,
)
from wait_local_agent.vault import SecretVault


def test_m365_graph_identity_routes_and_audit(settings, monkeypatch) -> None:
    class FakeM365GraphClient:
        def __init__(self, _settings) -> None:
            pass

        def health(self):
            return ConnectorReadResult("ready", "Microsoft Graph ready", 1)

        def list_users(self, **kwargs):
            return M365GraphReadResponse(
                ConnectorReadResult("ready", str(kwargs), 1),
                [
                    M365GraphUser(
                        "user-1",
                        "Adele Vance",
                        "adele@example.test",
                        "adele@example.test",
                        True,
                        "Manager",
                        "Operations",
                    )
                ],
                "next-token",
            )

        def list_groups(self, **kwargs):
            return M365GraphGroupReadResponse(
                ConnectorReadResult("ready", str(kwargs), 1),
                [
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
                "group-next-token",
            )

        def list_subscribed_skus(self, **kwargs):
            return M365GraphLicenseReadResponse(
                ConnectorReadResult("ready", str(kwargs), 1),
                [
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
                "license-next-token",
            )

        def list_license_details(self, **kwargs):
            return M365GraphLicenseDetailReadResponse(
                ConnectorReadResult("ready", str(kwargs), 1),
                [
                    M365GraphLicenseDetail(
                        "detail-1",
                        "sku-guid",
                        "M365_BUSINESS_PREMIUM",
                        (),
                    )
                ],
                "detail-next-token",
            )

        def list_mail_folders(self, **kwargs):
            return M365GraphMailFolderReadResponse(
                ConnectorReadResult("ready", str(kwargs), 1),
                [M365GraphMailFolder("inbox-id", "Inbox", "root-id", 3, 42, 5, False)],
                "folder-next-token",
            )

        def list_mail_messages(self, **kwargs):
            return M365GraphMailMessageReadResponse(
                ConnectorReadResult("ready", str(kwargs), 1),
                [
                    M365GraphMailMessage(
                        "message-1",
                        "VPN issue",
                        "Adele Vance",
                        "adele@example.test",
                        "today",
                        False,
                        True,
                        "high",
                    )
                ],
                "message-next-token",
            )

        def list_managed_devices(self, **kwargs):
            return M365GraphManagedDeviceReadResponse(
                ConnectorReadResult("ready", str(kwargs), 1),
                [
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
                "device-next-token",
            )

    monkeypatch.setattr(app_module, "M365GraphClient", FakeM365GraphClient)
    client = TestClient(create_app(settings))

    health = client.get("/connectors/m365/health")
    users = client.get(
        "/connectors/m365/users",
        params={"identity": "adele@example.test", "cursor": "next", "page_size": 2},
    )
    groups = client.get(
        "/connectors/m365/groups",
        params={"identity": "helpdesk@example.test", "cursor": "group-next", "page_size": 2},
    )
    licenses = client.get(
        "/connectors/m365/licenses",
        params={"cursor": "license-next"},
    )
    license_details = client.get(
        "/connectors/m365/users/license-details",
        params={"identity": "adele@example.test", "cursor": "detail-next", "page_size": 2},
    )
    mail_folders = client.get(
        "/connectors/m365/mail-folders",
        params={"identity": "adele@example.test", "cursor": "folder-next", "page_size": 2},
    )
    mail_messages = client.get(
        "/connectors/m365/mail-messages",
        params={
            "identity": "adele@example.test",
            "folder_id": "inbox-id",
            "cursor": "message-next",
            "page_size": 2,
        },
    )
    managed_devices = client.get(
        "/connectors/m365/managed-devices",
        params={"cursor": "device-next", "page_size": 2},
    )
    connectors = client.get("/connectors")
    audit = client.get("/audit")

    assert health.status_code == 200
    assert health.json()["status"] == "ready"
    assert users.json()["items"][0]["user_principal_name"] == "adele@example.test"
    assert users.json()["next_cursor"] == "next-token"
    assert groups.json()["items"][0]["mail_nickname"] == "helpdesk"
    assert groups.json()["next_cursor"] == "group-next-token"
    assert licenses.json()["items"][0]["sku_part_number"] == "M365_BUSINESS_PREMIUM"
    assert licenses.json()["next_cursor"] == "license-next-token"
    assert license_details.json()["items"][0]["sku_part_number"] == "M365_BUSINESS_PREMIUM"
    assert license_details.json()["next_cursor"] == "detail-next-token"
    assert mail_folders.json()["items"][0]["display_name"] == "Inbox"
    assert mail_folders.json()["next_cursor"] == "folder-next-token"
    assert mail_messages.json()["items"][0]["subject"] == "VPN issue"
    assert mail_messages.json()["next_cursor"] == "message-next-token"
    assert managed_devices.json()["items"][0]["device_name"] == "LAPTOP-1"
    assert managed_devices.json()["next_cursor"] == "device-next-token"
    assert any(connector["id"] == "m365" for connector in connectors.json())
    assert any(event["event_type"] == "m365.read" for event in audit.json())


def test_m365_graph_routes_keep_viewer_auth_boundary(settings) -> None:
    settings = replace(settings, demo_mode=False, admin_token="admin-token", viewer_token="viewer-secret")
    client = TestClient(create_app(settings))
    assert client.get("/connectors/m365/health").status_code == 401
    assert client.get("/connectors/m365/groups").status_code == 401
    assert client.get("/connectors/m365/licenses").status_code == 401
    assert client.get("/connectors/m365/users/license-details", params={"identity": "user-1"}).status_code == 401
    assert client.get("/connectors/m365/mail-folders").status_code == 401
    assert client.get("/connectors/m365/mail-messages").status_code == 401
    assert client.get("/connectors/m365/managed-devices").status_code == 401


def test_m365_user_creation_requires_admin_approval_and_uses_vault_secret(settings, monkeypatch, tmp_path) -> None:
    calls: list[dict[str, object]] = []

    class FakeM365GraphClient:
        def __init__(self, _settings) -> None:
            pass

        def write_health(self):
            return ConnectorReadResult("ready", "write ready")

        def create_user(self, **kwargs):
            calls.append(kwargs)
            return M365GraphUserCreateResult(
                "succeeded",
                "created",
                remote_id="user-1",
                user_principal_name=str(kwargs["user_principal_name"]),
                display_name=str(kwargs["display_name"]),
                account_enabled=bool(kwargs["account_enabled"]),
                status_code=201,
            )

    secure_settings = replace(
        settings,
        demo_mode=False,
        admin_token="admin-token",
        tech_token="tech-token",
        viewer_token="viewer-token",
        allow_http_probing=True,
        allow_write_actions=True,
        m365_graph_base_url="https://graph.microsoft.com/v1.0",
        m365_access_token="graph-token",
        vault_path=tmp_path / "vault",
    )
    SecretVault.initialize(secure_settings.vault_path).set(
        "WAIT_M365_TEMP_ADELE", "Temporary-Password-123!"
    )
    monkeypatch.setattr(app_module, "M365GraphClient", FakeM365GraphClient)
    client = TestClient(create_app(secure_settings))

    draft = client.post(
        "/connectors/m365/users/drafts",
        headers=_auth("admin-token"),
        json={
            "user_principal_name": "adele.vance@example.test",
            "display_name": "Adele Vance",
            "mail_nickname": "adele.vance",
            "temporary_vault_name": "WAIT_M365_TEMP_ADELE",
            "client_id": "tenant-a",
        },
    )
    request_id = draft.json()["id"]
    technician_approval = client.post(
        f"/approval-requests/{request_id}",
        headers=_auth("tech-token"),
        json={"status": "approved"},
    )
    admin_approval = client.post(
        f"/approval-requests/{request_id}",
        headers=_auth("admin-token"),
        json={"status": "approved"},
    )
    assert draft.status_code == 200
    assert technician_approval.status_code == 403
    assert admin_approval.status_code == 200
    assert admin_approval.json()["execution_status"] == "succeeded"
    assert calls[0]["temporary_password"] == "Temporary-Password-123!"
    assert "Temporary-Password-123!" not in admin_approval.text


def test_m365_draft_routes_reject_foreign_client_for_bound_table_admin(settings) -> None:
    secure_settings = replace(
        settings,
        demo_mode=False,
        client_id="acme",
        admin_token="bootstrap-admin",
        tech_token="",
        viewer_token="",
    )
    app = create_app(secure_settings)
    app.state.store.create_principal("acme-admin", kind="staff")
    app.state.store.add_principal_credential("acme-admin", "acme-admin-token")
    app.state.store.add_principal_client_role("acme-admin", "acme", "admin")
    client = TestClient(app)
    headers = _auth("acme-admin-token")
    draft_requests: list[tuple[str, dict[str, object]]] = [
        (
            "/connectors/m365/users/drafts",
            {
                "user_principal_name": "adele.vance@example.test",
                "display_name": "Adele Vance",
                "mail_nickname": "adele.vance",
                "temporary_vault_name": "WAIT_M365_TEMP_ADELE",
            },
        ),
        ("/connectors/m365/users/disable-drafts", {"user_identity": "adele.vance@example.test"}),
        (
            "/connectors/m365/users/password-reset-drafts",
            {
                "user_identity": "adele.vance@example.test",
                "temporary_vault_name": "WAIT_M365_TEMP_ADELE",
            },
        ),
        (
            "/connectors/m365/users/authentication-method-drafts",
            {
                "user_identity": "adele.vance@example.test",
                "method_type": "fido2",
                "method_id": "method-1",
            },
        ),
        (
            "/connectors/m365/groups/membership-drafts",
            {"group_id": "group-1", "user_id": "user-1", "operation": "add"},
        ),
        (
            "/connectors/m365/users/license-drafts",
            {
                "user_id": "user-1",
                "sku_ids": ["00000000-0000-0000-0000-000000000001"],
                "operation": "add",
            },
        ),
        ("/connectors/m365/users/session-revocation-drafts", {"user_id": "user-1"}),
        ("/connectors/m365/managed-devices/retire-drafts", {"device_id": "device-1"}),
        ("/connectors/m365/managed-devices/sync-drafts", {"device_id": "device-1"}),
        ("/connectors/m365/managed-devices/reboot-drafts", {"device_id": "device-1"}),
        ("/connectors/m365/managed-devices/remote-lock-drafts", {"device_id": "device-1"}),
        (
            "/connectors/m365/users/mailbox-settings-drafts",
            {"user_identity": "adele.vance@example.test", "settings": {"locale": "en-US"}},
        ),
        (
            "/connectors/m365/mail-messages/move-drafts",
            {
                "user_identity": "adele.vance@example.test",
                "source_folder_id": "inbox",
                "message_id": "message-1",
                "destination_folder_id": "archive",
            },
        ),
        (
            "/connectors/m365/mail-messages/read-state-drafts",
            {
                "user_identity": "adele.vance@example.test",
                "source_folder_id": "inbox",
                "message_id": "message-1",
                "is_read": True,
            },
        ),
        (
            "/connectors/m365/mail-messages/delete-drafts",
            {
                "user_identity": "adele.vance@example.test",
                "source_folder_id": "inbox",
                "message_id": "message-1",
            },
        ),
    ]

    for path, payload in draft_requests:
        response = client.post(path, headers=headers, json={**payload, "client_id": "beta"})
        assert response.status_code == 403, path
        assert response.json()["detail"] == "requested tenant is outside authenticated scope"


def test_m365_draft_routes_return_400_for_invalid_payloads(settings) -> None:
    secure_settings = replace(
        settings,
        demo_mode=False,
        client_id="acme",
        admin_token="bootstrap-admin",
        tech_token="",
        viewer_token="",
    )
    app = create_app(secure_settings)
    _provision_bound_principal(app.state.store, "acme-admin", "acme-admin-token", "acme", "admin")
    client = TestClient(app)
    headers = _auth("acme-admin-token")
    draft_requests: list[tuple[str, dict[str, object]]] = [
        (
            "/connectors/m365/users/drafts",
            {
                "user_principal_name": "   ",
                "display_name": "Adele Vance",
                "mail_nickname": "adele.vance",
                "temporary_vault_name": "WAIT_M365_TEMP_ADELE",
            },
        ),
        ("/connectors/m365/users/disable-drafts", {"user_identity": " "}),
        (
            "/connectors/m365/users/password-reset-drafts",
            {"user_identity": " ", "temporary_vault_name": "WAIT_M365_TEMP_ADELE"},
        ),
        (
            "/connectors/m365/users/authentication-method-drafts",
            {"user_identity": " ", "method_type": "fido2", "method_id": "method-1"},
        ),
        (
            "/connectors/m365/groups/membership-drafts",
            {"group_id": " ", "user_id": "user-1", "operation": "add"},
        ),
        (
            "/connectors/m365/users/license-drafts",
            {
                "user_id": " ",
                "sku_ids": ["00000000-0000-0000-0000-000000000001"],
                "operation": "add",
            },
        ),
        ("/connectors/m365/users/session-revocation-drafts", {"user_id": " "}),
        ("/connectors/m365/managed-devices/retire-drafts", {"device_id": " "}),
        ("/connectors/m365/managed-devices/sync-drafts", {"device_id": " "}),
        ("/connectors/m365/managed-devices/reboot-drafts", {"device_id": " "}),
        ("/connectors/m365/managed-devices/remote-lock-drafts", {"device_id": " "}),
        (
            "/connectors/m365/users/mailbox-settings-drafts",
            {"user_identity": "user-1", "settings": {"locale": " "}},
        ),
        (
            "/connectors/m365/mail-messages/move-drafts",
            {
                "user_identity": " ",
                "source_folder_id": "inbox",
                "message_id": "message-1",
                "destination_folder_id": "archive",
            },
        ),
        (
            "/connectors/m365/mail-messages/read-state-drafts",
            {
                "user_identity": " ",
                "source_folder_id": "inbox",
                "message_id": "message-1",
                "is_read": True,
            },
        ),
        (
            "/connectors/m365/mail-messages/delete-drafts",
            {"user_identity": " ", "source_folder_id": "inbox", "message_id": "message-1"},
        ),
    ]

    for path, payload in draft_requests:
        response = client.post(path, headers=headers, json=payload)
        assert response.status_code == 400, path


def test_m365_user_disable_requires_admin_and_auto_executes_after_approval(settings, monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    class FakeM365GraphClient:
        def __init__(self, _settings) -> None:
            pass

        def write_health(self):
            return ConnectorReadResult("ready", "write ready")

        def disable_user(self, **kwargs):
            calls.append(kwargs)
            return M365GraphUserDisableResult(
                "succeeded",
                "disabled",
                user_identity=str(kwargs["user_identity"]),
                status_code=204,
            )

    secure_settings = replace(
        settings,
        demo_mode=False,
        admin_token="admin-token",
        tech_token="tech-token",
        viewer_token="viewer-token",
        allow_http_probing=True,
        allow_write_actions=True,
        m365_graph_base_url="https://graph.microsoft.com/v1.0",
        m365_access_token="graph-token",
    )
    monkeypatch.setattr(app_module, "M365GraphClient", FakeM365GraphClient)
    client = TestClient(create_app(secure_settings))

    draft = client.post(
        "/connectors/m365/users/disable-drafts",
        headers=_auth("admin-token"),
        json={
            "user_identity": "adele.vance@example.test",
            "client_id": "tenant-a",
        },
    )
    request_id = draft.json()["id"]
    technician_approval = client.post(
        f"/approval-requests/{request_id}",
        headers=_auth("tech-token"),
        json={"status": "approved"},
    )
    admin_approval = client.post(
        f"/approval-requests/{request_id}",
        headers=_auth("admin-token"),
        json={"status": "approved"},
    )

    assert draft.status_code == 200
    assert draft.json()["action_type"] == "m365.users.disable"
    assert draft.json()["payload"]["user_identity"] == "adele.vance@example.test"
    assert technician_approval.status_code == 403
    assert admin_approval.status_code == 200
    assert admin_approval.json()["execution_status"] == "succeeded"
    assert admin_approval.json()["output"]["status_code"] == 204
    assert calls == [{"user_identity": "adele.vance@example.test"}]
    assert "password" not in admin_approval.text.lower()


def test_m365_password_and_authentication_method_routes_require_admin_approval(
    settings, monkeypatch, tmp_path
) -> None:
    calls: list[dict[str, object]] = []

    class FakeM365GraphClient:
        def __init__(self, _settings) -> None:
            pass

        def write_health(self):
            return ConnectorReadResult("ready", "write ready")

        def reset_user_password(self, **kwargs):
            calls.append(kwargs)
            return M365GraphPasswordResetResult(
                "succeeded", "reset", user_identity=str(kwargs["user_identity"]), status_code=204
            )

        def delete_authentication_method(self, **kwargs):
            calls.append(kwargs)
            return M365GraphAuthenticationMethodDeleteResult(
                "succeeded",
                "removed",
                user_identity=str(kwargs["user_identity"]),
                method_type=str(kwargs["method_type"]),
                method_id=str(kwargs["method_id"]),
                status_code=204,
            )

    secure_settings = replace(
        settings,
        demo_mode=False,
        admin_token="admin-token",
        tech_token="tech-token",
        allow_http_probing=True,
        allow_write_actions=True,
        m365_graph_base_url="https://graph.microsoft.com/v1.0",
        m365_access_token="graph-token",
        vault_path=tmp_path / "vault",
    )
    SecretVault.initialize(secure_settings.vault_path).set(
        "WAIT_M365_TEMP_ADELE", "Temporary-Password-123!"
    )
    monkeypatch.setattr(app_module, "M365GraphClient", FakeM365GraphClient)
    client = TestClient(create_app(secure_settings))
    headers = _auth("admin-token")

    password_draft = client.post(
        "/connectors/m365/users/password-reset-drafts",
        headers=headers,
        json={
            "user_identity": "adele.vance@example.test",
            "temporary_vault_name": "WAIT_M365_TEMP_ADELE",
            "force_change_password_next_sign_in_with_mfa": True,
            "client_id": "tenant-a",
        },
    )
    assert password_draft.status_code == 200
    assert "Temporary-Password-123!" not in password_draft.text
    password_approval = client.post(
        f"/approval-requests/{password_draft.json()['id']}",
        headers=headers,
        json={"status": "approved"},
    )
    assert password_approval.status_code == 200
    assert password_approval.json()["status"] == "approved"

    method_draft = client.post(
        "/connectors/m365/users/authentication-method-drafts",
        headers=headers,
        json={
            "user_identity": "adele.vance@example.test",
            "method_type": "fido2",
            "method_id": "method-1",
        },
    )
    assert method_draft.status_code == 200
    method_approval = client.post(
        f"/approval-requests/{method_draft.json()['id']}",
        headers=headers,
        json={"status": "approved"},
    )
    assert method_approval.status_code == 200
    assert method_approval.json()["status"] == "approved"
    assert calls == [
        {
            "user_identity": "adele.vance@example.test",
            "temporary_password": "Temporary-Password-123!",
            "force_change_password_next_sign_in": True,
            "force_change_password_next_sign_in_with_mfa": True,
        },
        {
            "user_identity": "adele.vance@example.test",
            "method_type": "fido2",
            "method_id": "method-1",
        },
    ]
    assert "Temporary-Password-123!" not in password_approval.text


def test_m365_group_membership_requires_admin_and_auto_executes_after_approval(settings, monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    class FakeM365GraphClient:
        def __init__(self, _settings) -> None:
            pass

        def write_health(self):
            return ConnectorReadResult("ready", "write ready")

        def change_group_membership(self, **kwargs):
            calls.append(kwargs)
            return M365GraphGroupMembershipResult(
                "succeeded",
                "membership changed",
                group_id=str(kwargs["group_id"]),
                user_id=str(kwargs["user_id"]),
                operation=str(kwargs["operation"]),
                status_code=204,
            )

    secure_settings = replace(
        settings,
        demo_mode=False,
        admin_token="admin-token",
        tech_token="tech-token",
        viewer_token="viewer-token",
        allow_http_probing=True,
        allow_write_actions=True,
        m365_graph_base_url="https://graph.microsoft.com/v1.0",
        m365_access_token="graph-token",
    )
    monkeypatch.setattr(app_module, "M365GraphClient", FakeM365GraphClient)
    client = TestClient(create_app(secure_settings))

    viewer_draft = client.post(
        "/connectors/m365/groups/membership-drafts",
        headers=_auth("viewer-token"),
        json={"group_id": "group-1", "user_id": "user-1", "operation": "add"},
    )

    draft = client.post(
        "/connectors/m365/groups/membership-drafts",
        headers=_auth("admin-token"),
        json={
            "group_id": "group-1",
            "user_id": "user-1",
            "operation": "remove",
            "client_id": "tenant-a",
        },
    )
    request_id = draft.json()["id"]
    technician_approval = client.post(
        f"/approval-requests/{request_id}",
        headers=_auth("tech-token"),
        json={"status": "approved"},
    )
    admin_approval = client.post(
        f"/approval-requests/{request_id}",
        headers=_auth("admin-token"),
        json={"status": "approved"},
    )

    assert viewer_draft.status_code == 403
    assert draft.status_code == 200
    assert draft.json()["action_type"] == "m365.groups.members.remove"
    assert draft.json()["payload"]["group_id"] == "group-1"
    assert technician_approval.status_code == 403
    assert admin_approval.status_code == 200
    assert admin_approval.json()["execution_status"] == "succeeded"
    assert admin_approval.json()["output"]["operation"] == "remove"
    assert calls == [{"group_id": "group-1", "user_id": "user-1", "operation": "remove"}]


def test_m365_license_change_requires_admin_and_auto_executes_after_approval(settings, monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    class FakeM365GraphClient:
        def __init__(self, _settings) -> None:
            pass

        def write_health(self):
            return ConnectorReadResult("ready", "write ready")

        def change_user_licenses(self, **kwargs):
            calls.append(kwargs)
            return M365GraphLicenseChangeResult(
                "succeeded",
                "licenses changed",
                user_id=str(kwargs["user_id"]),
                operation=str(kwargs["operation"]),
                sku_ids=tuple(kwargs["sku_ids"]),
                status_code=200,
            )

    secure_settings = replace(
        settings,
        demo_mode=False,
        admin_token="admin-token",
        tech_token="tech-token",
        viewer_token="viewer-token",
        allow_http_probing=True,
        allow_write_actions=True,
        m365_graph_base_url="https://graph.microsoft.com/v1.0",
        m365_access_token="graph-token",
    )
    monkeypatch.setattr(app_module, "M365GraphClient", FakeM365GraphClient)
    client = TestClient(create_app(secure_settings))
    sku_ids = ["84a661c4-e949-4bd2-a560-ed7766fcaf2b"]

    viewer_draft = client.post(
        "/connectors/m365/users/license-drafts",
        headers=_auth("viewer-token"),
        json={"user_id": "user-1", "sku_ids": sku_ids, "operation": "add"},
    )
    draft = client.post(
        "/connectors/m365/users/license-drafts",
        headers=_auth("admin-token"),
        json={
            "user_id": "user-1",
            "sku_ids": sku_ids,
            "operation": "add",
            "client_id": "tenant-a",
        },
    )
    request_id = draft.json()["id"]
    technician_approval = client.post(
        f"/approval-requests/{request_id}",
        headers=_auth("tech-token"),
        json={"status": "approved"},
    )
    admin_approval = client.post(
        f"/approval-requests/{request_id}",
        headers=_auth("admin-token"),
        json={"status": "approved"},
    )

    assert viewer_draft.status_code == 403
    assert draft.status_code == 200
    assert draft.json()["action_type"] == "m365.users.licenses.add"
    assert draft.json()["payload"]["sku_ids"] == sku_ids
    assert technician_approval.status_code == 403
    assert admin_approval.status_code == 200
    assert admin_approval.json()["execution_status"] == "succeeded"
    assert admin_approval.json()["output"]["operation"] == "add"
    assert calls == [{"user_id": "user-1", "sku_ids": sku_ids, "operation": "add"}]


def test_m365_session_revocation_requires_admin_and_auto_executes_after_approval(settings, monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    class FakeM365GraphClient:
        def __init__(self, _settings) -> None:
            pass

        def write_health(self):
            return ConnectorReadResult("ready", "write ready")

        def revoke_user_sessions(self, **kwargs):
            calls.append(kwargs)
            return M365GraphSessionRevokeResult(
                "succeeded",
                "sessions revoked",
                user_id=str(kwargs["user_id"]),
                status_code=200,
            )

    secure_settings = replace(
        settings,
        demo_mode=False,
        admin_token="admin-token",
        tech_token="tech-token",
        viewer_token="viewer-token",
        allow_http_probing=True,
        allow_write_actions=True,
        m365_graph_base_url="https://graph.microsoft.com/v1.0",
        m365_access_token="graph-token",
    )
    monkeypatch.setattr(app_module, "M365GraphClient", FakeM365GraphClient)
    client = TestClient(create_app(secure_settings))

    viewer_draft = client.post(
        "/connectors/m365/users/session-revocation-drafts",
        headers=_auth("viewer-token"),
        json={"user_id": "user-1"},
    )
    draft = client.post(
        "/connectors/m365/users/session-revocation-drafts",
        headers=_auth("admin-token"),
        json={"user_id": "user-1", "client_id": "tenant-a"},
    )
    request_id = draft.json()["id"]
    technician_approval = client.post(
        f"/approval-requests/{request_id}",
        headers=_auth("tech-token"),
        json={"status": "approved"},
    )
    admin_approval = client.post(
        f"/approval-requests/{request_id}",
        headers=_auth("admin-token"),
        json={"status": "approved"},
    )

    assert viewer_draft.status_code == 403
    assert draft.status_code == 200
    assert draft.json()["action_type"] == "m365.users.sessions.revoke"
    assert technician_approval.status_code == 403
    assert admin_approval.status_code == 200
    assert admin_approval.json()["execution_status"] == "succeeded"
    assert admin_approval.json()["output"]["status_code"] == 200
    assert calls == [{"user_id": "user-1"}]


def test_m365_managed_device_retirement_requires_admin_and_auto_executes_after_approval(settings, monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    class FakeM365GraphClient:
        def __init__(self, _settings) -> None:
            pass

        def write_health(self):
            return ConnectorReadResult("ready", "write ready")

        def retire_managed_device(self, **kwargs):
            calls.append(kwargs)
            return M365GraphManagedDeviceRetireResult(
                "succeeded",
                "device retired",
                device_id=str(kwargs["device_id"]),
                status_code=204,
            )

    secure_settings = replace(
        settings,
        demo_mode=False,
        admin_token="admin-token",
        tech_token="tech-token",
        viewer_token="viewer-token",
        allow_http_probing=True,
        allow_write_actions=True,
        m365_graph_base_url="https://graph.microsoft.com/v1.0",
        m365_access_token="graph-token",
    )
    monkeypatch.setattr(app_module, "M365GraphClient", FakeM365GraphClient)
    client = TestClient(create_app(secure_settings))

    viewer_draft = client.post(
        "/connectors/m365/managed-devices/retire-drafts",
        headers=_auth("viewer-token"),
        json={"device_id": "device-1"},
    )
    draft = client.post(
        "/connectors/m365/managed-devices/retire-drafts",
        headers=_auth("admin-token"),
        json={"device_id": "device-1", "client_id": "tenant-a"},
    )
    request_id = draft.json()["id"]
    technician_approval = client.post(
        f"/approval-requests/{request_id}",
        headers=_auth("tech-token"),
        json={"status": "approved"},
    )
    admin_approval = client.post(
        f"/approval-requests/{request_id}",
        headers=_auth("admin-token"),
        json={"status": "approved"},
    )

    assert viewer_draft.status_code == 403
    assert draft.status_code == 200
    assert draft.json()["action_type"] == "m365.managed-devices.retire"
    assert draft.json()["payload"]["device_id"] == "device-1"
    assert technician_approval.status_code == 403
    assert admin_approval.status_code == 200
    assert admin_approval.json()["execution_status"] == "succeeded"
    assert admin_approval.json()["output"]["status_code"] == 204
    assert calls == [{"device_id": "device-1"}]


def test_m365_managed_device_sync_requires_admin_and_auto_executes_after_approval(
    settings, monkeypatch
) -> None:
    calls: list[dict[str, object]] = []

    class FakeM365GraphClient:
        def __init__(self, _settings) -> None:
            pass

        def sync_managed_device(self, **kwargs):
            calls.append(kwargs)
            return M365GraphManagedDeviceSyncResult(
                "succeeded",
                "device synced",
                device_id=str(kwargs["device_id"]),
                status_code=204,
            )

    secure_settings = replace(
        settings,
        demo_mode=False,
        admin_token="admin-token",
        tech_token="tech-token",
        viewer_token="viewer-token",
        allow_http_probing=True,
        allow_write_actions=True,
        m365_graph_base_url="https://graph.microsoft.com/v1.0",
        m365_access_token="graph-token",
    )
    monkeypatch.setattr(app_module, "M365GraphClient", FakeM365GraphClient)
    client = TestClient(create_app(secure_settings))

    viewer_draft = client.post(
        "/connectors/m365/managed-devices/sync-drafts",
        headers=_auth("viewer-token"),
        json={"device_id": "device-1"},
    )
    draft = client.post(
        "/connectors/m365/managed-devices/sync-drafts",
        headers=_auth("admin-token"),
        json={"device_id": "device-1", "client_id": "tenant-a"},
    )
    request_id = draft.json()["id"]
    technician_approval = client.post(
        f"/approval-requests/{request_id}",
        headers=_auth("tech-token"),
        json={"status": "approved"},
    )
    admin_approval = client.post(
        f"/approval-requests/{request_id}",
        headers=_auth("admin-token"),
        json={"status": "approved"},
    )

    assert viewer_draft.status_code == 403
    assert draft.status_code == 200
    assert draft.json()["action_type"] == "m365.managed-devices.sync"
    assert draft.json()["payload"]["device_id"] == "device-1"
    assert technician_approval.status_code == 403
    assert admin_approval.status_code == 200
    assert admin_approval.json()["execution_status"] == "succeeded"
    assert admin_approval.json()["output"]["status_code"] == 204
    assert calls == [{"device_id": "device-1"}]


def test_m365_managed_device_reboot_requires_admin_and_auto_executes_after_approval(
    settings, monkeypatch
) -> None:
    calls: list[dict[str, object]] = []

    class FakeM365GraphClient:
        def __init__(self, _settings) -> None:
            pass

        def reboot_managed_device(self, **kwargs):
            calls.append(kwargs)
            return M365GraphManagedDeviceRebootResult(
                "succeeded",
                "device rebooted",
                device_id=str(kwargs["device_id"]),
                status_code=204,
            )

    secure_settings = replace(
        settings,
        demo_mode=False,
        admin_token="admin-token",
        tech_token="tech-token",
        viewer_token="viewer-token",
        allow_http_probing=True,
        allow_write_actions=True,
        m365_graph_base_url="https://graph.microsoft.com/v1.0",
        m365_access_token="graph-token",
    )
    monkeypatch.setattr(app_module, "M365GraphClient", FakeM365GraphClient)
    client = TestClient(create_app(secure_settings))

    viewer_draft = client.post(
        "/connectors/m365/managed-devices/reboot-drafts",
        headers=_auth("viewer-token"),
        json={"device_id": "device-1"},
    )
    draft = client.post(
        "/connectors/m365/managed-devices/reboot-drafts",
        headers=_auth("admin-token"),
        json={"device_id": "device-1", "client_id": "tenant-a"},
    )
    request_id = draft.json()["id"]
    technician_approval = client.post(
        f"/approval-requests/{request_id}",
        headers=_auth("tech-token"),
        json={"status": "approved"},
    )
    admin_approval = client.post(
        f"/approval-requests/{request_id}",
        headers=_auth("admin-token"),
        json={"status": "approved"},
    )

    assert viewer_draft.status_code == 403
    assert draft.status_code == 200
    assert draft.json()["action_type"] == "m365.managed-devices.reboot"
    assert draft.json()["payload"]["device_id"] == "device-1"
    assert technician_approval.status_code == 403
    assert admin_approval.status_code == 200
    assert admin_approval.json()["execution_status"] == "succeeded"
    assert admin_approval.json()["output"]["status_code"] == 204
    assert calls == [{"device_id": "device-1"}]


def test_m365_managed_device_remote_lock_requires_admin_and_auto_executes_after_approval(
    settings, monkeypatch
) -> None:
    calls: list[dict[str, object]] = []

    class FakeM365GraphClient:
        def __init__(self, _settings) -> None:
            pass

        def remote_lock_managed_device(self, **kwargs):
            calls.append(kwargs)
            return M365GraphManagedDeviceRemoteLockResult(
                "succeeded",
                "device locked",
                device_id=str(kwargs["device_id"]),
                status_code=204,
            )

    secure_settings = replace(
        settings,
        demo_mode=False,
        admin_token="admin-token",
        tech_token="tech-token",
        viewer_token="viewer-token",
        allow_http_probing=True,
        allow_write_actions=True,
        m365_graph_base_url="https://graph.microsoft.com/v1.0",
        m365_access_token="graph-token",
    )
    monkeypatch.setattr(app_module, "M365GraphClient", FakeM365GraphClient)
    client = TestClient(create_app(secure_settings))

    viewer_draft = client.post(
        "/connectors/m365/managed-devices/remote-lock-drafts",
        headers=_auth("viewer-token"),
        json={"device_id": "device-1"},
    )
    draft = client.post(
        "/connectors/m365/managed-devices/remote-lock-drafts",
        headers=_auth("admin-token"),
        json={"device_id": "device-1", "client_id": "tenant-a"},
    )
    request_id = draft.json()["id"]
    technician_approval = client.post(
        f"/approval-requests/{request_id}",
        headers=_auth("tech-token"),
        json={"status": "approved"},
    )
    admin_approval = client.post(
        f"/approval-requests/{request_id}",
        headers=_auth("admin-token"),
        json={"status": "approved"},
    )

    assert viewer_draft.status_code == 403
    assert draft.status_code == 200
    assert draft.json()["action_type"] == "m365.managed-devices.remote-lock"
    assert draft.json()["payload"]["device_id"] == "device-1"
    assert technician_approval.status_code == 403
    assert admin_approval.status_code == 200
    assert admin_approval.json()["execution_status"] == "succeeded"
    assert admin_approval.json()["output"]["status_code"] == 204
    assert calls == [{"device_id": "device-1"}]


def test_m365_mailbox_settings_update_requires_admin_and_auto_executes_after_approval(settings, monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    class FakeM365GraphClient:
        def __init__(self, _settings) -> None:
            pass

        def update_mailbox_settings(self, **kwargs):
            calls.append(kwargs)
            return M365GraphMailboxSettingsUpdateResult(
                "succeeded",
                "mailbox settings updated",
                user_identity=str(kwargs["user_identity"]),
                settings=dict(kwargs["settings"]),
                status_code=200,
            )

    secure_settings = replace(
        settings,
        demo_mode=False,
        admin_token="admin-token",
        tech_token="tech-token",
        viewer_token="viewer-token",
        allow_http_probing=True,
        allow_write_actions=True,
        m365_graph_base_url="https://graph.microsoft.com/v1.0",
        m365_access_token="graph-token",
    )
    monkeypatch.setattr(app_module, "M365GraphClient", FakeM365GraphClient)
    client = TestClient(create_app(secure_settings))
    settings_payload = {"locale": "en-US", "time_zone": "UTC"}

    viewer_draft = client.post(
        "/connectors/m365/users/mailbox-settings-drafts",
        headers=_auth("viewer-token"),
        json={"user_identity": "user-1", "settings": settings_payload},
    )
    invalid_draft = client.post(
        "/connectors/m365/users/mailbox-settings-drafts",
        headers=_auth("admin-token"),
        json={
            "user_identity": "user-1",
            "settings": {"forwarding": "bad"},
            "client_id": "tenant-a",
        },
    )
    draft = client.post(
        "/connectors/m365/users/mailbox-settings-drafts",
        headers=_auth("admin-token"),
        json={
            "user_identity": "user-1",
            "settings": settings_payload,
            "client_id": "tenant-a",
        },
    )
    request_id = draft.json()["id"]
    technician_approval = client.post(
        f"/approval-requests/{request_id}",
        headers=_auth("tech-token"),
        json={"status": "approved"},
    )
    admin_approval = client.post(
        f"/approval-requests/{request_id}",
        headers=_auth("admin-token"),
        json={"status": "approved"},
    )

    assert viewer_draft.status_code == 403
    assert invalid_draft.status_code == 400
    assert draft.status_code == 200
    assert draft.json()["action_type"] == "m365.users.mailbox-settings.update"
    assert technician_approval.status_code == 403
    assert admin_approval.status_code == 200
    assert admin_approval.json()["execution_status"] == "succeeded"
    assert admin_approval.json()["output"]["settings"] == settings_payload
    assert calls == [{"user_identity": "user-1", "settings": settings_payload}]


def test_m365_mail_message_move_requires_admin_and_auto_executes_after_approval(settings, monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    class FakeM365GraphClient:
        def __init__(self, _settings) -> None:
            pass

        def move_mail_message(self, **kwargs):
            calls.append(kwargs)
            return M365GraphMailMessageMoveResult(
                "succeeded",
                "message moved",
                user_identity=str(kwargs["user_identity"]),
                source_folder_id=str(kwargs["source_folder_id"]),
                message_id=str(kwargs["message_id"]),
                destination_folder_id=str(kwargs["destination_folder_id"]),
                status_code=201,
            )

    secure_settings = replace(
        settings,
        demo_mode=False,
        admin_token="admin-token",
        tech_token="tech-token",
        viewer_token="viewer-token",
        allow_http_probing=True,
        allow_write_actions=True,
        m365_graph_base_url="https://graph.microsoft.com/v1.0",
        m365_access_token="graph-token",
    )
    monkeypatch.setattr(app_module, "M365GraphClient", FakeM365GraphClient)
    client = TestClient(create_app(secure_settings))
    payload = {
        "user_identity": "user-1",
        "source_folder_id": "inbox",
        "message_id": "message-1",
        "destination_folder_id": "archive",
        "client_id": "tenant-a",
    }

    viewer_draft = client.post(
        "/connectors/m365/mail-messages/move-drafts",
        headers=_auth("viewer-token"),
        json=payload,
    )
    draft = client.post(
        "/connectors/m365/mail-messages/move-drafts",
        headers=_auth("admin-token"),
        json=payload,
    )
    request_id = draft.json()["id"]
    technician_approval = client.post(
        f"/approval-requests/{request_id}",
        headers=_auth("tech-token"),
        json={"status": "approved"},
    )
    admin_approval = client.post(
        f"/approval-requests/{request_id}",
        headers=_auth("admin-token"),
        json={"status": "approved"},
    )

    assert viewer_draft.status_code == 403
    assert draft.status_code == 200
    assert draft.json()["action_type"] == "m365.mail-messages.move"
    assert technician_approval.status_code == 403
    assert admin_approval.status_code == 200
    assert admin_approval.json()["execution_status"] == "succeeded"
    assert calls == [
        {
            "user_identity": "user-1",
            "source_folder_id": "inbox",
            "message_id": "message-1",
            "destination_folder_id": "archive",
        }
    ]


def test_m365_mail_message_read_state_requires_admin_and_auto_executes_after_approval(
    settings, monkeypatch
) -> None:
    calls: list[dict[str, object]] = []

    class FakeM365GraphClient:
        def __init__(self, _settings) -> None:
            pass

        def update_mail_message_read_state(self, **kwargs):
            calls.append(kwargs)
            return M365GraphMailMessageReadStateResult(
                "succeeded",
                "message read state updated",
                user_identity=str(kwargs["user_identity"]),
                source_folder_id=str(kwargs["source_folder_id"]),
                message_id=str(kwargs["message_id"]),
                is_read=bool(kwargs["is_read"]),
                status_code=200,
            )

    secure_settings = replace(
        settings,
        demo_mode=False,
        admin_token="admin-token",
        tech_token="tech-token",
        viewer_token="viewer-token",
        allow_http_probing=True,
        allow_write_actions=True,
        m365_graph_base_url="https://graph.microsoft.com/v1.0",
        m365_access_token="graph-token",
    )
    monkeypatch.setattr(app_module, "M365GraphClient", FakeM365GraphClient)
    client = TestClient(create_app(secure_settings))
    payload = {
        "user_identity": "user-1",
        "source_folder_id": "inbox",
        "message_id": "message-1",
        "is_read": False,
        "client_id": "tenant-a",
    }

    viewer_draft = client.post(
        "/connectors/m365/mail-messages/read-state-drafts",
        headers=_auth("viewer-token"),
        json=payload,
    )
    draft = client.post(
        "/connectors/m365/mail-messages/read-state-drafts",
        headers=_auth("admin-token"),
        json=payload,
    )
    request_id = draft.json()["id"]
    technician_approval = client.post(
        f"/approval-requests/{request_id}",
        headers=_auth("tech-token"),
        json={"status": "approved"},
    )
    admin_approval = client.post(
        f"/approval-requests/{request_id}",
        headers=_auth("admin-token"),
        json={"status": "approved"},
    )

    assert viewer_draft.status_code == 403
    assert draft.status_code == 200
    assert draft.json()["action_type"] == "m365.mail-messages.read-state"
    assert technician_approval.status_code == 403
    assert admin_approval.status_code == 200
    assert admin_approval.json()["execution_status"] == "succeeded"
    assert admin_approval.json()["output"]["is_read"] is False
    assert calls == [
        {
            "user_identity": "user-1",
            "source_folder_id": "inbox",
            "message_id": "message-1",
            "is_read": False,
        }
    ]


def test_m365_mail_message_delete_requires_admin_and_auto_executes_after_approval(
    settings, monkeypatch
) -> None:
    calls: list[dict[str, object]] = []

    class FakeM365GraphClient:
        def __init__(self, _settings) -> None:
            pass

        def delete_mail_message(self, **kwargs):
            calls.append(kwargs)
            return M365GraphMailMessageDeleteResult(
                "succeeded",
                "message deleted",
                user_identity=str(kwargs["user_identity"]),
                source_folder_id=str(kwargs["source_folder_id"]),
                message_id=str(kwargs["message_id"]),
                status_code=204,
            )

    secure_settings = replace(
        settings,
        demo_mode=False,
        admin_token="admin-token",
        tech_token="tech-token",
        viewer_token="viewer-token",
        allow_http_probing=True,
        allow_write_actions=True,
        m365_graph_base_url="https://graph.microsoft.com/v1.0",
        m365_access_token="graph-token",
    )
    monkeypatch.setattr(app_module, "M365GraphClient", FakeM365GraphClient)
    client = TestClient(create_app(secure_settings))
    payload = {
        "user_identity": "user-1",
        "source_folder_id": "inbox",
        "message_id": "message-1",
        "client_id": "tenant-a",
    }

    viewer_draft = client.post(
        "/connectors/m365/mail-messages/delete-drafts",
        headers=_auth("viewer-token"),
        json=payload,
    )
    draft = client.post(
        "/connectors/m365/mail-messages/delete-drafts",
        headers=_auth("admin-token"),
        json=payload,
    )
    request_id = draft.json()["id"]
    technician_approval = client.post(
        f"/approval-requests/{request_id}",
        headers=_auth("tech-token"),
        json={"status": "approved"},
    )
    admin_approval = client.post(
        f"/approval-requests/{request_id}",
        headers=_auth("admin-token"),
        json={"status": "approved"},
    )

    assert viewer_draft.status_code == 403
    assert draft.status_code == 200
    assert draft.json()["action_type"] == "m365.mail-messages.delete"
    assert technician_approval.status_code == 403
    assert admin_approval.status_code == 200
    assert admin_approval.json()["execution_status"] == "succeeded"
    assert calls == [
        {
            "user_identity": "user-1",
            "source_folder_id": "inbox",
            "message_id": "message-1",
        }
    ]

