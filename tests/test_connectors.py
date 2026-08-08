from __future__ import annotations

from typing import Any, cast

import pytest

from wait_local_agent import cloud_connectors
from wait_local_agent.connectors import (
    draft_m365_group_membership,
    draft_m365_license_change,
    draft_m365_mailbox_settings_update,
    draft_m365_managed_device_retirement,
    draft_m365_session_revocation,
    draft_m365_user_creation,
    draft_m365_user_disable,
    execute_halopsa_approval_request,
    execute_m365_approval_request,
    update_halopsa_approval_fields,
    validate_halopsa_action_fields,
    validate_m365_group_membership_payload,
    validate_m365_license_change_payload,
    validate_m365_mailbox_settings_update_payload,
    validate_m365_managed_device_retirement_payload,
    validate_m365_session_revocation_payload,
    validate_m365_user_creation_payload,
    validate_m365_user_disable_payload,
)
from wait_local_agent.m365_graph import (
    M365GraphGroupMembershipResult,
    M365GraphLicenseChangeResult,
    M365GraphMailboxSettingsUpdateResult,
    M365GraphManagedDeviceRetireResult,
    M365GraphSessionRevokeResult,
    M365GraphUserDisableResult,
)
from wait_local_agent.models import HaloWriteResult
from wait_local_agent.store import Store
from wait_local_agent.vault import SecretVault


class FakeHaloClient:
    def execute_write(self, request):
        return HaloWriteResult("succeeded", "posted", request.action_type, request.ticket_id)


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

    def update_mailbox_settings(self, **kwargs):
        self.calls.append(kwargs)
        return M365GraphMailboxSettingsUpdateResult(
            "succeeded",
            "mailbox settings updated",
            user_identity=str(kwargs["user_identity"]),
            settings=dict(kwargs["settings"]),
            status_code=200,
        )

    def revoke_user_sessions(self, **kwargs):
        self.calls.append(kwargs)
        return M365GraphSessionRevokeResult(
            "succeeded",
            "sessions revoked",
            user_id=str(kwargs["user_id"]),
            status_code=200,
        )


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
    cases = [
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
