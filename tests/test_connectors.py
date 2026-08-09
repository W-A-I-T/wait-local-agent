from __future__ import annotations

from dataclasses import replace
from typing import Any, cast

import pytest

from wait_local_agent import cloud_connectors
from wait_local_agent.connectors import (
    draft_connectwise_ticket_action,
    draft_m365_group_membership,
    draft_m365_license_change,
    draft_m365_mail_message_delete,
    draft_m365_mail_message_move,
    draft_m365_mail_message_read_state,
    draft_m365_mailbox_settings_update,
    draft_m365_managed_device_reboot,
    draft_m365_managed_device_remote_lock,
    draft_m365_managed_device_retirement,
    draft_m365_managed_device_sync,
    draft_m365_session_revocation,
    draft_m365_user_creation,
    draft_m365_user_disable,
    execute_connectwise_approval_request,
    execute_halopsa_approval_request,
    execute_m365_approval_request,
    list_connector_statuses,
    update_connectwise_approval_fields,
    update_halopsa_approval_fields,
    validate_connectwise_action_fields,
    validate_halopsa_action_fields,
    validate_m365_group_membership_payload,
    validate_m365_license_change_payload,
    validate_m365_mail_message_delete_payload,
    validate_m365_mail_message_move_payload,
    validate_m365_mail_message_read_state_payload,
    validate_m365_mailbox_settings_update_payload,
    validate_m365_managed_device_reboot_payload,
    validate_m365_managed_device_remote_lock_payload,
    validate_m365_managed_device_retirement_payload,
    validate_m365_managed_device_sync_payload,
    validate_m365_session_revocation_payload,
    validate_m365_user_creation_payload,
    validate_m365_user_disable_payload,
    validate_syncro_action_fields,
)
from wait_local_agent.m365_graph import (
    M365GraphGroupMembershipResult,
    M365GraphLicenseChangeResult,
    M365GraphMailboxSettingsUpdateResult,
    M365GraphMailMessageDeleteResult,
    M365GraphMailMessageMoveResult,
    M365GraphMailMessageReadStateResult,
    M365GraphManagedDeviceRebootResult,
    M365GraphManagedDeviceRemoteLockResult,
    M365GraphManagedDeviceRetireResult,
    M365GraphManagedDeviceSyncResult,
    M365GraphSessionRevokeResult,
    M365GraphUserDisableResult,
)
from wait_local_agent.models import ConnectWiseWriteResult, HaloWriteResult
from wait_local_agent.store import Store
from wait_local_agent.vault import SecretVault


class FakeHaloClient:
    def execute_write(self, request):
        return HaloWriteResult("succeeded", "posted", request.action_type, request.ticket_id)


class FakeConnectWiseClient:
    def execute_write(self, request):
        return ConnectWiseWriteResult(
            "succeeded",
            "updated",
            request.action_type,
            request.ticket_id,
            endpoint="service/tickets/42",
            status_code=200,
            remote_id="42",
        )


class FakeM365Client:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def create_user(self, **kwargs):
        self.calls.append(kwargs)
        return type(
            "Result",
            (),
            {
                "status": "succeeded",
                "message": "created",
                "remote_id": "user-1",
                "user_principal_name": kwargs["user_principal_name"],
                "display_name": kwargs["display_name"],
                "account_enabled": kwargs["account_enabled"],
                "status_code": 201,
            },
        )()

    def disable_user(self, **kwargs):
        self.calls.append(kwargs)
        return M365GraphUserDisableResult(
            "succeeded",
            "disabled",
            user_identity=str(kwargs["user_identity"]),
            status_code=204,
        )


    def change_group_membership(self, **kwargs):
        self.calls.append(kwargs)
        return M365GraphGroupMembershipResult(
            "succeeded",
            "membership changed",
            group_id=str(kwargs["group_id"]),
            user_id=str(kwargs["user_id"]),
            operation=str(kwargs["operation"]),
            status_code=204,
        )

    def change_user_licenses(self, **kwargs):
        self.calls.append(kwargs)
        return M365GraphLicenseChangeResult(
            "succeeded",
            "licenses changed",
            user_id=str(kwargs["user_id"]),
            operation=str(kwargs["operation"]),
            sku_ids=tuple(kwargs["sku_ids"]),
            status_code=200,
        )

    def retire_managed_device(self, **kwargs):
        self.calls.append(kwargs)
        return M365GraphManagedDeviceRetireResult(
            "succeeded",
            "device retired",
            device_id=str(kwargs["device_id"]),
            status_code=204,
        )

    def sync_managed_device(self, **kwargs):
        self.calls.append(kwargs)
        return M365GraphManagedDeviceSyncResult(
            "succeeded",
            "device synced",
            device_id=str(kwargs["device_id"]),
            status_code=204,
        )

    def reboot_managed_device(self, **kwargs):
        self.calls.append(kwargs)
        return M365GraphManagedDeviceRebootResult(
            "succeeded",
            "device rebooted",
            device_id=str(kwargs["device_id"]),
            status_code=204,
        )

    def remote_lock_managed_device(self, **kwargs):
        self.calls.append(kwargs)
        return M365GraphManagedDeviceRemoteLockResult(
            "succeeded",
            "device locked",
            device_id=str(kwargs["device_id"]),
            status_code=204,
        )

    def update_mailbox_settings(self, **kwargs):
        self.calls.append(kwargs)
        return M365GraphMailboxSettingsUpdateResult(
            "succeeded",
            "mailbox settings updated",
            user_identity=str(kwargs["user_identity"]),
            settings=dict(kwargs["settings"]),
            status_code=200,
        )

    def move_mail_message(self, **kwargs):
        self.calls.append(kwargs)
        return M365GraphMailMessageMoveResult(
            "succeeded",
            "message moved",
            user_identity=str(kwargs["user_identity"]),
            source_folder_id=str(kwargs["source_folder_id"]),
            message_id=str(kwargs["message_id"]),
            destination_folder_id=str(kwargs["destination_folder_id"]),
            status_code=201,
        )

    def update_mail_message_read_state(self, **kwargs):
        self.calls.append(kwargs)
        return M365GraphMailMessageReadStateResult(
            "succeeded",
            "message read state updated",
            user_identity=str(kwargs["user_identity"]),
            source_folder_id=str(kwargs["source_folder_id"]),
            message_id=str(kwargs["message_id"]),
            is_read=bool(kwargs["is_read"]),
            status_code=200,
        )

    def delete_mail_message(self, **kwargs):
        self.calls.append(kwargs)
        return M365GraphMailMessageDeleteResult(
            "succeeded",
            "message deleted",
            user_identity=str(kwargs["user_identity"]),
            source_folder_id=str(kwargs["source_folder_id"]),
            message_id=str(kwargs["message_id"]),
            status_code=204,
        )

    def revoke_user_sessions(self, **kwargs):
        self.calls.append(kwargs)
        return M365GraphSessionRevokeResult(
            "succeeded",
            "sessions revoked",
            user_id=str(kwargs["user_id"]),
            status_code=200,
        )


def test_connector_write_status_is_scoped_to_each_connector(settings) -> None:
    active = replace(
        settings,
        allow_write_actions=True,
        halopsa_base_url="https://halo.example.test",
        halopsa_client_id="halo-client",
        halopsa_client_secret="halo-secret",
        halopsa_tenant="halo-tenant",
        connectwise_base_url="",
        servicenow_base_url="https://service-now.example.test",
        servicenow_username="api-user",
        servicenow_password="api-password",
        autotask_base_url="https://autotask.example.test",
        autotask_username="api-user",
        autotask_secret="api-secret",
        autotask_integration_code="integration-code",
    )

    statuses = {status.id: status for status in list_connector_statuses(active)}

    assert statuses["halopsa"].write_actions_enabled is True
    assert statuses["connectwise"].write_actions_enabled is False
    assert statuses["servicenow"].write_actions_enabled is True
    assert statuses["autotask"].write_actions_enabled is True


def test_m365_user_creation_approval_resolves_vault_secret_without_persisting_it(settings, tmp_path) -> None:
    active_settings = settings.__class__(**{**settings.__dict__, "vault_path": tmp_path / "vault"})
    store = Store(active_settings.data_path)
    vault = SecretVault.initialize(active_settings.vault_path)
    vault.set("WAIT_M365_TEMP_ADELE", "Temporary-Password-123!")

    approval = draft_m365_user_creation(
        store,
        user_principal_name="adele.vance@example.test",
        display_name="Adele Vance",
        mail_nickname="adele.vance",
        temporary_vault_name="WAIT_M365_TEMP_ADELE",
    )
    assert approval.id is not None
    persisted = store.get_approval_request(approval.id)
    assert persisted is not None
    assert "Temporary-Password-123!" not in persisted.payload_json
    assert "WAIT_M365_TEMP_ADELE" in persisted.payload_json

    store.update_approval_request(approval.id, "approved")
    client = FakeM365Client()
    executed = execute_m365_approval_request(
        store,
        cast(Any, client),
        vault,
        approval.id,
    )

    assert executed.execution_status == "succeeded"
    assert client.calls[0]["temporary_password"] == "Temporary-Password-123!"
    assert all(
        "Temporary-Password-123!" not in str(event.detail)
        for event in store.list_audit_events()
    )
    with pytest.raises(RuntimeError, match="already executed"):
        execute_m365_approval_request(store, cast(Any, client), vault, approval.id)


def test_m365_user_creation_rejects_unapproved_payload_fields(settings) -> None:
    with pytest.raises(ValueError, match="unsupported fields"):
        validate_m365_user_creation_payload(
            {
                "connector": "m365",
                "action_type": "users.create",
                "account_enabled": True,
                "display_name": "Adele Vance",
                "force_change_password_next_sign_in": True,
                "mail_nickname": "adele.vance",
                "temporary_vault_name": "WAIT_M365_TEMP_ADELE",
                "user_principal_name": "adele.vance@example.test",
                "raw_endpoint": "users",
            }
        )


def test_m365_user_disable_approval_has_no_secret_fields_and_executes(settings, tmp_path) -> None:
    store = Store(settings.data_path)
    vault = SecretVault.initialize(tmp_path / "vault")
    approval = draft_m365_user_disable(
        store,
        user_identity="adele.vance@example.test",
        client_id="tenant-a",
    )
    persisted = store.get_approval_request(approval.id or 0)
    assert persisted is not None
    assert persisted.client_id == "tenant-a"
    assert persisted.payload_json == (
        '{"action_type":"users.disable","connector":"m365",'
        '"user_identity":"adele.vance@example.test"}'
    )
    assert "password" not in persisted.payload_json.lower()

    store.update_approval_request(approval.id or 0, "approved")
    client = FakeM365Client()
    executed = execute_m365_approval_request(
        store,
        cast(Any, client),
        vault,
        approval.id or 0,
    )

    assert executed.execution_status == "succeeded"
    assert client.calls == [{"user_identity": "adele.vance@example.test"}]
    assert "password" not in executed.execution_result_json.lower()


def test_m365_user_disable_payload_validation_rejects_extra_or_unsafe_fields() -> None:
    valid: dict[str, object] = {
        "connector": "m365",
        "action_type": "users.disable",
        "user_identity": "adele.vance@example.test",
    }
    validate_m365_user_disable_payload(valid)
    cases: tuple[dict[str, object], ...] = (
        {**valid, "account_enabled": False},
        {**valid, "user_identity": "bad\nvalue"},
        {**valid, "user_identity": "adele vance@example.test"},
        {**valid, "action_type": "users.create"},
    )
    for payload in cases:
        with pytest.raises(ValueError):
            validate_m365_user_disable_payload(payload)


def test_m365_group_membership_approval_is_strict_and_executes(settings, tmp_path) -> None:
    store = Store(settings.data_path)
    vault = SecretVault.initialize(tmp_path / "vault")
    approval = draft_m365_group_membership(
        store,
        group_id="group-1",
        user_id="user-1",
        operation="add",
        client_id="tenant-a",
    )
    persisted = store.get_approval_request(approval.id or 0)
    assert persisted is not None
    assert persisted.client_id == "tenant-a"
    assert persisted.payload_json == (
        '{"action_type":"groups.members.add","connector":"m365",'
        '"group_id":"group-1","user_id":"user-1"}'
    )
    assert "password" not in persisted.payload_json.lower()

    store.update_approval_request(approval.id or 0, "approved")
    client = FakeM365Client()
    executed = execute_m365_approval_request(
        store,
        cast(Any, client),
        vault,
        approval.id or 0,
    )

    assert executed.execution_status == "succeeded"
    assert client.calls == [
        {"group_id": "group-1", "user_id": "user-1", "operation": "add"}
    ]
    assert "password" not in executed.execution_result_json.lower()


def test_m365_group_membership_payload_validation_rejects_unsafe_shapes(settings) -> None:
    valid: dict[str, object] = {
        "connector": "m365",
        "action_type": "groups.members.remove",
        "group_id": "group-1",
        "user_id": "user-1",
    }
    validate_m365_group_membership_payload(valid)
    cases: tuple[dict[str, object], ...] = (
        {**valid, "raw_endpoint": "groups/group-1"},
        {**valid, "group_id": "group 1"},
        {**valid, "user_id": "user\n1"},
        {**valid, "action_type": "groups.delete"},
        {**valid, "user_id": 7},
    )
    for payload in cases:
        with pytest.raises(ValueError):
            validate_m365_group_membership_payload(payload)

    with pytest.raises(ValueError, match="add or remove"):
        draft_m365_group_membership(
            Store(settings.data_path),
            group_id="group-1",
            user_id="user-1",
            operation="replace",
        )


def test_m365_license_change_approval_is_strict_and_executes(settings, tmp_path) -> None:
    sku_ids = [
        "84a661c4-e949-4bd2-a560-ed7766fcaf2b",
        "f30db892-07e9-47e9-837c-80727f46fd3d",
    ]
    store = Store(settings.data_path)
    vault = SecretVault.initialize(tmp_path / "vault")
    approval = draft_m365_license_change(
        store,
        user_id="user-1",
        sku_ids=sku_ids,
        operation="add",
        client_id="tenant-a",
    )
    persisted = store.get_approval_request(approval.id or 0)
    assert persisted is not None
    assert persisted.client_id == "tenant-a"
    assert persisted.payload_json == (
        '{"action_type":"users.licenses.add","connector":"m365",'
        '"sku_ids":["84a661c4-e949-4bd2-a560-ed7766fcaf2b",'
        '"f30db892-07e9-47e9-837c-80727f46fd3d"],"user_id":"user-1"}'
    )

    store.update_approval_request(approval.id or 0, "approved")
    client = FakeM365Client()
    executed = execute_m365_approval_request(
        store, cast(Any, client), vault, approval.id or 0
    )

    assert executed.execution_status == "succeeded"
    assert client.calls == [
        {"user_id": "user-1", "sku_ids": sku_ids, "operation": "add"}
    ]
    assert "password" not in executed.execution_result_json.lower()


def test_m365_license_change_payload_rejects_unsafe_shapes() -> None:
    sku_id = "84a661c4-e949-4bd2-a560-ed7766fcaf2b"
    valid: dict[str, object] = {
        "connector": "m365",
        "action_type": "users.licenses.remove",
        "user_id": "user-1",
        "sku_ids": [sku_id],
    }
    validate_m365_license_change_payload(valid)
    cases: tuple[dict[str, object], ...] = (
        {**valid, "raw_endpoint": "users/user-1/assignLicense"},
        {**valid, "sku_ids": ["not-a-guid"]},
        {**valid, "sku_ids": [7]},
        {**valid, "sku_ids": []},
        {**valid, "sku_ids": [sku_id, sku_id]},
        {**valid, "user_id": "user 1"},
        {**valid, "action_type": "users.disable"},
    )
    for payload in cases:
        with pytest.raises(ValueError):
            validate_m365_license_change_payload(payload)


def test_m365_session_revocation_approval_is_strict_and_executes(settings, tmp_path) -> None:
    store = Store(settings.data_path)
    vault = SecretVault.initialize(tmp_path / "vault")
    approval = draft_m365_session_revocation(
        store, user_id="user-1", client_id="tenant-a"
    )
    persisted = store.get_approval_request(approval.id or 0)
    assert persisted is not None
    assert persisted.client_id == "tenant-a"
    assert persisted.payload_json == (
        '{"action_type":"users.sessions.revoke","connector":"m365",'
        '"user_id":"user-1"}'
    )

    store.update_approval_request(approval.id or 0, "approved")
    client = FakeM365Client()
    executed = execute_m365_approval_request(
        store, cast(Any, client), vault, approval.id or 0
    )

    assert executed.execution_status == "succeeded"
    assert client.calls == [{"user_id": "user-1"}]
    assert "password" not in executed.execution_result_json.lower()


def test_m365_session_revocation_payload_rejects_extra_or_unsafe_fields() -> None:
    valid: dict[str, object] = {
        "connector": "m365",
        "action_type": "users.sessions.revoke",
        "user_id": "user-1",
    }
    validate_m365_session_revocation_payload(valid)
    for payload in (
        {**valid, "raw_endpoint": "users/user-1/revokeSignInSessions"},
        {**valid, "user_id": "user 1"},
        {**valid, "action_type": "users.disable"},
    ):
        with pytest.raises(ValueError):
            validate_m365_session_revocation_payload(payload)


def test_m365_managed_device_retirement_approval_is_strict_and_executes(settings, tmp_path) -> None:
    store = Store(settings.data_path)
    vault = SecretVault.initialize(tmp_path / "vault")
    approval = draft_m365_managed_device_retirement(
        store, device_id="device-1", client_id="tenant-a"
    )
    persisted = store.get_approval_request(approval.id or 0)
    assert persisted is not None
    assert persisted.client_id == "tenant-a"
    assert persisted.payload_json == (
        '{"action_type":"managed-devices.retire","connector":"m365",'
        '"device_id":"device-1"}'
    )

    store.update_approval_request(approval.id or 0, "approved")
    client = FakeM365Client()
    executed = execute_m365_approval_request(
        store, cast(Any, client), vault, approval.id or 0
    )

    assert executed.execution_status == "succeeded"
    assert client.calls == [{"device_id": "device-1"}]
    assert "password" not in executed.execution_result_json.lower()


def test_m365_managed_device_retirement_payload_rejects_extra_or_unsafe_fields() -> None:
    valid: dict[str, object] = {
        "connector": "m365",
        "action_type": "managed-devices.retire",
        "device_id": "device-1",
    }
    validate_m365_managed_device_retirement_payload(valid)
    for payload in (
        {**valid, "raw_endpoint": "deviceManagement/managedDevices/device-1/retire"},
        {**valid, "device_id": "device 1"},
        {**valid, "action_type": "managed-devices.wipe"},
    ):
        with pytest.raises(ValueError):
            validate_m365_managed_device_retirement_payload(payload)


def test_m365_managed_device_sync_approval_is_strict_and_executes(settings, tmp_path) -> None:
    store = Store(settings.data_path)
    vault = SecretVault.initialize(tmp_path / "vault")
    approval = draft_m365_managed_device_sync(
        store, device_id="device-1", client_id="tenant-a"
    )
    persisted = store.get_approval_request(approval.id or 0)
    assert persisted is not None
    assert persisted.payload_json == (
        '{"action_type":"managed-devices.sync","connector":"m365",'
        '"device_id":"device-1"}'
    )
    validate_m365_managed_device_sync_payload(
        {
            "connector": "m365",
            "action_type": "managed-devices.sync",
            "device_id": "device-1",
        }
    )

    store.update_approval_request(approval.id or 0, "approved")
    client = FakeM365Client()
    executed = execute_m365_approval_request(
        store, cast(Any, client), vault, approval.id or 0
    )

    assert executed.execution_status == "succeeded"
    assert client.calls == [{"device_id": "device-1"}]


def test_m365_managed_device_sync_payload_rejects_extra_or_unsafe_fields() -> None:
    valid: dict[str, object] = {
        "connector": "m365",
        "action_type": "managed-devices.sync",
        "device_id": "device-1",
    }
    for payload in (
        {**valid, "raw_endpoint": "deviceManagement/managedDevices/device-1/syncDevice"},
        {**valid, "device_id": "device 1"},
        {**valid, "action_type": "managed-devices.wipe"},
    ):
        with pytest.raises(ValueError):
            validate_m365_managed_device_sync_payload(payload)


def test_m365_managed_device_reboot_approval_is_strict_and_executes(settings, tmp_path) -> None:
    store = Store(settings.data_path)
    vault = SecretVault.initialize(tmp_path / "vault")
    approval = draft_m365_managed_device_reboot(
        store, device_id="device-1", client_id="tenant-a"
    )
    persisted = store.get_approval_request(approval.id or 0)
    assert persisted is not None
    assert persisted.payload_json == (
        '{"action_type":"managed-devices.reboot","connector":"m365",'
        '"device_id":"device-1"}'
    )
    validate_m365_managed_device_reboot_payload(
        {
            "connector": "m365",
            "action_type": "managed-devices.reboot",
            "device_id": "device-1",
        }
    )

    store.update_approval_request(approval.id or 0, "approved")
    client = FakeM365Client()
    executed = execute_m365_approval_request(
        store, cast(Any, client), vault, approval.id or 0
    )

    assert executed.execution_status == "succeeded"
    assert client.calls == [{"device_id": "device-1"}]


def test_m365_managed_device_reboot_payload_rejects_extra_or_unsafe_fields() -> None:
    valid: dict[str, object] = {
        "connector": "m365",
        "action_type": "managed-devices.reboot",
        "device_id": "device-1",
    }
    for payload in (
        {**valid, "raw_endpoint": "deviceManagement/managedDevices/device-1/rebootNow"},
        {**valid, "device_id": "device 1"},
        {**valid, "action_type": "managed-devices.wipe"},
    ):
        with pytest.raises(ValueError):
            validate_m365_managed_device_reboot_payload(payload)


def test_m365_managed_device_remote_lock_approval_is_strict_and_executes(settings, tmp_path) -> None:
    store = Store(settings.data_path)
    vault = SecretVault.initialize(tmp_path / "vault")
    approval = draft_m365_managed_device_remote_lock(
        store, device_id="device-1", client_id="tenant-a"
    )
    persisted = store.get_approval_request(approval.id or 0)
    assert persisted is not None
    assert persisted.payload_json == (
        '{"action_type":"managed-devices.remote-lock","connector":"m365",'
        '"device_id":"device-1"}'
    )
    valid: dict[str, object] = {
        "connector": "m365",
        "action_type": "managed-devices.remote-lock",
        "device_id": "device-1",
    }
    validate_m365_managed_device_remote_lock_payload(valid)

    store.update_approval_request(approval.id or 0, "approved")
    client = FakeM365Client()
    executed = execute_m365_approval_request(
        store, cast(Any, client), vault, approval.id or 0
    )

    assert executed.execution_status == "succeeded"
    assert client.calls == [{"device_id": "device-1"}]


def test_m365_managed_device_remote_lock_payload_rejects_extra_or_unsafe_fields() -> None:
    valid: dict[str, object] = {
        "connector": "m365",
        "action_type": "managed-devices.remote-lock",
        "device_id": "device-1",
    }
    for payload in (
        {**valid, "raw_endpoint": "deviceManagement/managedDevices/device-1/remoteLock"},
        {**valid, "device_id": "device 1"},
        {**valid, "action_type": "managed-devices.wipe"},
    ):
        with pytest.raises(ValueError):
            validate_m365_managed_device_remote_lock_payload(payload)


def test_m365_mailbox_settings_update_approval_is_strict_and_executes(settings, tmp_path) -> None:
    store = Store(settings.data_path)
    vault = SecretVault.initialize(tmp_path / "vault")
    settings_payload = {"locale": "en-US", "time_zone": "UTC"}
    approval = draft_m365_mailbox_settings_update(
        store,
        user_identity="user-1",
        settings=settings_payload,
        client_id="tenant-a",
    )
    persisted = store.get_approval_request(approval.id or 0)
    assert persisted is not None
    assert persisted.payload_json == (
        '{"action_type":"users.mailbox-settings.update","connector":"m365",'
        '"settings":{"locale":"en-US","time_zone":"UTC"},'
        '"user_identity":"user-1"}'
    )

    validate_m365_mailbox_settings_update_payload(
        {
            "connector": "m365",
            "action_type": "users.mailbox-settings.update",
            "settings": settings_payload,
            "user_identity": "user-1",
        }
    )
    store.update_approval_request(approval.id or 0, "approved")
    client = FakeM365Client()
    executed = execute_m365_approval_request(store, cast(Any, client), vault, approval.id or 0)

    assert executed.execution_status == "succeeded"
    assert client.calls == [{"user_identity": "user-1", "settings": settings_payload}]


def test_m365_mailbox_settings_update_payload_rejects_unsafe_shapes() -> None:
    valid: dict[str, object] = {
        "connector": "m365",
        "action_type": "users.mailbox-settings.update",
        "settings": {"locale": "en-US"},
        "user_identity": "user-1",
    }
    for payload in (
        {},
        {**valid, "action_type": "users.mailbox-settings.delete"},
        {**valid, "settings": {}},
        {**valid, "settings": {"forwarding_address": "bad@example.test"}},
        {**valid, "settings": {"locale": "en\nUS"}},
        {**valid, "user_identity": "user 1"},
    ):
        with pytest.raises(ValueError):
            validate_m365_mailbox_settings_update_payload(payload)


def test_m365_mail_message_move_approval_is_strict_and_executes(settings, tmp_path) -> None:
    store = Store(settings.data_path)
    vault = SecretVault.initialize(tmp_path / "vault")
    approval = draft_m365_mail_message_move(
        store,
        user_identity="user-1",
        source_folder_id="inbox",
        message_id="message-1",
        destination_folder_id="archive",
        client_id="tenant-a",
    )
    persisted = store.get_approval_request(approval.id or 0)
    assert persisted is not None
    assert "message-1" in persisted.payload_json
    validate_m365_mail_message_move_payload(
        {
            "connector": "m365",
            "action_type": "mail-messages.move",
            "user_identity": "user-1",
            "source_folder_id": "inbox",
            "message_id": "message-1",
            "destination_folder_id": "archive",
        }
    )
    store.update_approval_request(approval.id or 0, "approved")
    client = FakeM365Client()
    executed = execute_m365_approval_request(store, cast(Any, client), vault, approval.id or 0)
    assert executed.execution_status == "succeeded"
    assert client.calls == [
        {
            "user_identity": "user-1",
            "source_folder_id": "inbox",
            "message_id": "message-1",
            "destination_folder_id": "archive",
        }
    ]


def test_m365_mail_message_move_payload_rejects_unsafe_shapes() -> None:
    valid: dict[str, object] = {
        "connector": "m365",
        "action_type": "mail-messages.move",
        "user_identity": "user-1",
        "source_folder_id": "inbox",
        "message_id": "message-1",
        "destination_folder_id": "archive",
    }
    for payload in (
        {},
        {**valid, "action_type": "mail-messages.delete"},
        {**valid, "message_id": "message 1"},
        {**valid, "destination_folder_id": ""},
        {**valid, "unexpected": "field"},
    ):
        with pytest.raises(ValueError):
            validate_m365_mail_message_move_payload(payload)


def test_m365_mail_message_read_state_approval_is_strict_and_executes(settings, tmp_path) -> None:
    store = Store(settings.data_path)
    vault = SecretVault.initialize(tmp_path / "vault")
    approval = draft_m365_mail_message_read_state(
        store,
        user_identity="user-1",
        source_folder_id="inbox",
        message_id="message-1",
        is_read=False,
        client_id="tenant-a",
    )
    validate_m365_mail_message_read_state_payload(
        {
            "connector": "m365",
            "action_type": "mail-messages.read-state",
            "user_identity": "user-1",
            "source_folder_id": "inbox",
            "message_id": "message-1",
            "is_read": False,
        }
    )
    store.update_approval_request(approval.id or 0, "approved")
    client = FakeM365Client()
    executed = execute_m365_approval_request(store, cast(Any, client), vault, approval.id or 0)
    assert executed.execution_status == "succeeded"
    assert client.calls == [
        {
            "user_identity": "user-1",
            "source_folder_id": "inbox",
            "message_id": "message-1",
            "is_read": False,
        }
    ]


def test_m365_mail_message_read_state_payload_rejects_unsafe_shapes() -> None:
    valid: dict[str, object] = {
        "connector": "m365",
        "action_type": "mail-messages.read-state",
        "user_identity": "user-1",
        "source_folder_id": "inbox",
        "message_id": "message-1",
        "is_read": True,
    }
    for payload in (
        {},
        {**valid, "action_type": "mail-messages.delete"},
        {**valid, "is_read": "true"},
        {**valid, "message_id": "message 1"},
        {**valid, "unexpected": "field"},
    ):
        with pytest.raises(ValueError):
            validate_m365_mail_message_read_state_payload(payload)


def test_m365_mail_message_delete_approval_is_strict_and_executes(settings, tmp_path) -> None:
    store = Store(settings.data_path)
    vault = SecretVault.initialize(tmp_path / "vault")
    approval = draft_m365_mail_message_delete(
        store,
        user_identity="user-1",
        source_folder_id="inbox",
        message_id="message-1",
        client_id="tenant-a",
    )
    validate_m365_mail_message_delete_payload(
        {
            "connector": "m365",
            "action_type": "mail-messages.delete",
            "user_identity": "user-1",
            "source_folder_id": "inbox",
            "message_id": "message-1",
        }
    )
    store.update_approval_request(approval.id or 0, "approved")
    client = FakeM365Client()
    executed = execute_m365_approval_request(store, cast(Any, client), vault, approval.id or 0)
    assert executed.execution_status == "succeeded"
    assert client.calls == [
        {
            "user_identity": "user-1",
            "source_folder_id": "inbox",
            "message_id": "message-1",
        }
    ]


def test_m365_mail_message_delete_payload_rejects_unsafe_shapes() -> None:
    valid: dict[str, object] = {
        "connector": "m365",
        "action_type": "mail-messages.delete",
        "user_identity": "user-1",
        "source_folder_id": "inbox",
        "message_id": "message-1",
    }
    for payload in (
        {},
        {**valid, "action_type": "mail-messages.permanent-delete"},
        {**valid, "message_id": "message 1"},
        {**valid, "unexpected": "field"},
    ):
        with pytest.raises(ValueError):
            validate_m365_mail_message_delete_payload(payload)


def test_m365_user_creation_execution_rejects_invalid_state_and_missing_vault(settings, tmp_path) -> None:
    store = Store(settings.data_path)
    vault = SecretVault.initialize(tmp_path / "vault")
    pending = draft_m365_user_creation(
        store,
        user_principal_name="adele.vance@example.test",
        display_name="Adele Vance",
        mail_nickname="adele.vance",
        temporary_vault_name="WAIT_M365_TEMP_ADELE",
    )
    with pytest.raises(PermissionError, match="approved"):
        execute_m365_approval_request(store, cast(Any, FakeM365Client()), vault, pending.id or 0)

    wrong = store.create_approval_request("subject", "m365.users.delete", {})
    with pytest.raises(ValueError, match="supported M365"):
        execute_m365_approval_request(store, cast(Any, FakeM365Client()), vault, wrong.id or 0)

    store.update_approval_request(pending.id or 0, "approved")
    with pytest.raises(RuntimeError, match="missing"):
        execute_m365_approval_request(store, cast(Any, FakeM365Client()), vault, pending.id or 0)


def test_m365_user_execution_rejects_missing_and_malformed_approval_records(settings, tmp_path) -> None:
    store = Store(settings.data_path)
    vault = SecretVault.initialize(tmp_path / "vault")
    with pytest.raises(KeyError):
        execute_m365_approval_request(store, cast(Any, FakeM365Client()), vault, 9999)

    malformed = store.create_approval_request(
        "subject",
        "m365.users.disable",
        cast(Any, []),
    )
    store.update_approval_request(malformed.id or 0, "approved")
    with pytest.raises(ValueError, match="malformed"):
        execute_m365_approval_request(
            store, cast(Any, FakeM365Client()), vault, malformed.id or 0
        )

    mismatched = store.create_approval_request(
        "subject",
        "m365.users.disable",
        {"connector": "m365", "action_type": "users.delete"},
    )
    store.update_approval_request(mismatched.id or 0, "approved")
    with pytest.raises(ValueError, match="does not match"):
        execute_m365_approval_request(
            store, cast(Any, FakeM365Client()), vault, mismatched.id or 0
        )

    corrupt = draft_m365_user_creation(
        store,
        user_principal_name="adele.vance@example.test",
        display_name="Adele Vance",
        mail_nickname="adele.vance",
        temporary_vault_name="WAIT_M365_TEMP_ADELE",
    )
    store.update_approval_request(corrupt.id or 0, "approved")
    vault.secrets_path.write_bytes(b"not-encrypted")
    with pytest.raises(RuntimeError, match="could not be read"):
        execute_m365_approval_request(
            store, cast(Any, FakeM365Client()), vault, corrupt.id or 0
        )


def test_m365_user_creation_payload_validation_rejects_each_sensitive_shape() -> None:
    base = {
        "connector": "m365",
        "action_type": "users.create",
        "account_enabled": True,
        "display_name": "Adele Vance",
        "force_change_next_sign_in": True,
        "mail_nickname": "adele.vance",
        "temporary_vault_name": "WAIT_M365_TEMP_ADELE",
        "user_principal_name": "adele.vance@example.test",
    }
    cases: list[dict[str, object]] = [
        {**base, "connector": "other"},
        {**base, "display_name": "\n"},
        {**base, "user_principal_name": "bad"},
        {**base, "mail_nickname": "bad+alias"},
        {**base, "temporary_vault_name": "OTHER_SECRET"},
        {**base, "account_enabled": "true"},
        {**base, "display_name": 7},
        {**base, "account_enabled": "true"},
        {**base, "force_change_next_sign_in": "true"},
    ]
    for payload in cases:
        with pytest.raises(ValueError):
            validate_m365_user_creation_payload(payload)


def test_cloud_inventory_connectors_are_public_exports() -> None:
    expected = [
        "AwsInventoryConnector",
        "AzureInventoryConnector",
        "GCPInventoryConnector",
        "M365InventoryConnector",
    ]

    assert cloud_connectors.__all__ == expected
    assert all(hasattr(cloud_connectors, name) for name in expected)


def test_halopsa_approval_payload_validation_edges(settings) -> None:
    store = Store(settings.data_path)
    wrong_connector = store.create_approval_request(
        "HALO-2",
        "halopsa.add_note",
        {"connector": "hudu", "ticket_id": "HALO-2", "action_type": "add_note", "fields": {}},
    )
    store.update_approval_request(wrong_connector.id or 0, "approved")
    wrong_ticket = store.create_approval_request(
        "HALO-3",
        "halopsa.add_note",
        {"connector": "halopsa", "ticket_id": "OTHER", "action_type": "add_note", "fields": {}},
    )
    store.update_approval_request(wrong_ticket.id or 0, "approved")
    unsupported = store.create_approval_request(
        "HALO-4",
        "halopsa.add_note",
        {"connector": "halopsa", "ticket_id": "HALO-4", "action_type": "nope", "fields": {}},
    )
    store.update_approval_request(unsupported.id or 0, "approved")
    wrong_action = store.create_approval_request(
        "HALO-5",
        "halopsa.add_note",
        {
            "connector": "halopsa",
            "ticket_id": "HALO-5",
            "action_type": "update_status",
            "fields": {},
        },
    )
    store.update_approval_request(wrong_action.id or 0, "approved")

    with pytest.raises(ValueError, match="connector"):
        execute_halopsa_approval_request(
            store,
            cast(Any, FakeHaloClient()),
            wrong_connector.id or 0,
        )
    with pytest.raises(ValueError, match="ticket"):
        execute_halopsa_approval_request(
            store,
            cast(Any, FakeHaloClient()),
            wrong_ticket.id or 0,
        )
    with pytest.raises(ValueError, match="unsupported"):
        execute_halopsa_approval_request(
            store,
            cast(Any, FakeHaloClient()),
            unsupported.id or 0,
        )
    with pytest.raises(ValueError, match="action"):
        execute_halopsa_approval_request(
            store,
            cast(Any, FakeHaloClient()),
            wrong_action.id or 0,
        )


def test_halopsa_field_edit_validation_edges(settings) -> None:
    store = Store(settings.data_path)
    non_halo = store.create_approval_request("TCK-1", "ticket.draft_response", {})
    unsupported = store.create_approval_request(
        "HALO-1",
        "halopsa.add_note",
        {"connector": "halopsa", "ticket_id": "HALO-1", "action_type": "nope", "fields": {}},
    )

    with pytest.raises(ValueError, match="not a HaloPSA"):
        update_halopsa_approval_fields(store, non_halo.id or 0, {"note": "x"})
    with pytest.raises(ValueError, match="unsupported"):
        update_halopsa_approval_fields(store, unsupported.id or 0, {"note": "x"})
    with pytest.raises(ValueError, match="note or response"):
        validate_halopsa_action_fields("add_note", {})
    with pytest.raises(ValueError, match="status"):
        validate_halopsa_action_fields("update_status", {})
    with pytest.raises(ValueError, match="technician"):
        validate_halopsa_action_fields("assign_technician", {})
    with pytest.raises(ValueError, match="at least one"):
        validate_halopsa_action_fields("update_ticket_fields", {})
    validate_halopsa_action_fields("draft_response", {"response": "ok"})
    validate_halopsa_action_fields("update_status", {"status_id": "1"})
    validate_halopsa_action_fields("assign_technician", {"team_id": "2"})
    validate_halopsa_action_fields("update_ticket_fields", {"custom_field": "value"})


def test_syncro_comment_field_validation_edges() -> None:
    validate_syncro_action_fields(
        "add_note",
        {"subject": "Internal", "body": "Reviewed", "hidden": True, "do_not_email": False},
    )
    invalid_cases: list[tuple[str, dict[str, object]]] = [
        ("unknown", {"subject": "x", "body": "y"}),
        ("add_note", {}),
        ("add_note", {"subject": "x"}),
        ("add_note", {"subject": "x", "body": "y", "extra": "no"}),
        ("add_note", {"subject": 1, "body": "y"}),
        ("add_note", {"subject": "\x00", "body": "y"}),
        ("add_note", {"subject": "x", "body": 1}),
        ("add_note", {"subject": "x", "body": "\x00"}),
        ("add_note", {"subject": "x", "body": "y", "hidden": "yes"}),
        ("add_note", {"subject": "x", "body": "y", "do_not_email": 1}),
    ]
    for action_type, fields in invalid_cases:
        with pytest.raises(ValueError):
            validate_syncro_action_fields(action_type, fields)


def test_connectwise_drafts_edits_and_approval_execution(settings) -> None:
    store = Store(settings.data_path)
    draft = draft_connectwise_ticket_action(
        store,
        "CW-42",
        "update_status",
        {"status_id": 7},
        client_id="acme",
    )
    assert draft.approval_required is True
    assert draft.approval_request_id is not None
    edited = update_connectwise_approval_fields(
        store, draft.approval_request_id, {"status_id": 8}, "reviewed"
    )
    assert edited.comment == "reviewed"
    with pytest.raises(PermissionError, match="approved"):
        execute_connectwise_approval_request(
            store, cast(Any, FakeConnectWiseClient()), draft.approval_request_id
        )
    store.update_approval_request(draft.approval_request_id, "approved")
    completed = execute_connectwise_approval_request(
        store, cast(Any, FakeConnectWiseClient()), draft.approval_request_id
    )
    assert completed.execution_status == "succeeded"
    with pytest.raises(RuntimeError, match="already executed"):
        execute_connectwise_approval_request(
            store, cast(Any, FakeConnectWiseClient()), draft.approval_request_id
        )


def test_connectwise_approval_payload_and_field_validation_edges(settings) -> None:
    store = Store(settings.data_path)
    with pytest.raises(KeyError):
        update_connectwise_approval_fields(store, 999, {"status_id": 1})
    non_connectwise = store.create_approval_request("TCK-1", "halopsa.add_note", {})
    with pytest.raises(ValueError, match="not a ConnectWise"):
        update_connectwise_approval_fields(store, non_connectwise.id or 0, {"status_id": 1})
    with pytest.raises(ValueError, match="not a ConnectWise"):
        execute_connectwise_approval_request(
            store, cast(Any, FakeConnectWiseClient()), non_connectwise.id or 0
        )
    cases: list[tuple[str, dict[str, object]]] = [
        ("bad", {"status_id": 1}),
        ("update_status", {}),
        ("update_status", {"summary": "x"}),
        ("assign_technician", {"owner_id": ""}),
        ("update_ticket_fields", {"unknown": "x"}),
        ("update_ticket_fields", {"summary": True}),
        ("update_ticket_fields", {"summary": "\n"}),
    ]
    for action_type, fields in cases:
        with pytest.raises(ValueError):
            validate_connectwise_action_fields(action_type, fields)
    validate_connectwise_action_fields("assign_technician", {"team_id": 4})
    validate_connectwise_action_fields("update_ticket_fields", {"description": "details"})
    with pytest.raises(ValueError, match="requires status_id"):
        validate_connectwise_action_fields("update_status", {"status_id": 0})

    wrong_connector = store.create_approval_request(
        "CW-1",
        "connectwise.update_status",
        {"connector": "other", "ticket_id": "CW-1", "action_type": "update_status", "fields": {"status_id": 1}},
    )
    store.update_approval_request(wrong_connector.id or 0, "approved")
    with pytest.raises(ValueError, match="connector"):
        execute_connectwise_approval_request(
            store, cast(Any, FakeConnectWiseClient()), wrong_connector.id or 0
        )

    wrong_ticket = store.create_approval_request(
        "CW-2",
        "connectwise.update_status",
        {"connector": "connectwise", "ticket_id": "OTHER", "action_type": "update_status", "fields": {"status_id": 1}},
    )
    store.update_approval_request(wrong_ticket.id or 0, "approved")
    with pytest.raises(ValueError, match="ticket"):
        execute_connectwise_approval_request(
            store, cast(Any, FakeConnectWiseClient()), wrong_ticket.id or 0
        )

    unsupported = store.create_approval_request(
        "CW-3",
        "connectwise.update_status",
        {"connector": "connectwise", "ticket_id": "CW-3", "action_type": "bad", "fields": {"status_id": 1}},
    )
    store.update_approval_request(unsupported.id or 0, "approved")
    with pytest.raises(ValueError, match="unsupported"):
        execute_connectwise_approval_request(
            store, cast(Any, FakeConnectWiseClient()), unsupported.id or 0
        )

    wrong_action = store.create_approval_request(
        "CW-4",
        "connectwise.update_status",
        {"connector": "connectwise", "ticket_id": "CW-4", "action_type": "assign_technician", "fields": {"team_id": 1}},
    )
    store.update_approval_request(wrong_action.id or 0, "approved")
    with pytest.raises(ValueError, match="action"):
        execute_connectwise_approval_request(
            store, cast(Any, FakeConnectWiseClient()), wrong_action.id or 0
        )
