"""Guarded Microsoft Graph identity, group, license, mailbox, and Intune access.

The live connector is intentionally narrower than the cloud inventory adapter:
it looks up bounded user, group, tenant license, mailbox, and Intune device context,
and permits explicitly approval-gated user lifecycle and group-membership
operations only after the write-safety boundaries have passed.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol, cast
from urllib.parse import parse_qs, quote, unquote, urlsplit

import httpx

from wait_local_agent.config import Settings
from wait_local_agent.models import ConnectorReadResult

DEFAULT_PAGE_SIZE = 25
MAX_PAGE_SIZE = 200
MAX_CURSOR_LENGTH = 4096
MAX_IDENTITY_LENGTH = 320
MAX_LICENSE_ITEMS = 200


@dataclass(frozen=True)
class M365GraphUser:
    id: str
    display_name: str
    user_principal_name: str
    mail: str
    account_enabled: bool | None
    job_title: str
    department: str


@dataclass(frozen=True)
class M365GraphGroup:
    id: str
    display_name: str
    mail: str
    mail_nickname: str
    description: str
    mail_enabled: bool | None
    security_enabled: bool | None
    group_types: tuple[str, ...]


@dataclass(frozen=True)
class M365GraphReadResponse:
    result: ConnectorReadResult
    items: list[M365GraphUser]
    next_cursor: str = ""


@dataclass(frozen=True)
class M365GraphGroupReadResponse:
    result: ConnectorReadResult
    items: list[M365GraphGroup]
    next_cursor: str = ""


@dataclass(frozen=True)
class M365GraphSubscribedSku:
    id: str
    sku_id: str
    sku_part_number: str
    capability_status: str
    applies_to: str
    consumed_units: int | None
    prepaid_enabled: int | None
    prepaid_warning: int | None
    prepaid_suspended: int | None
    prepaid_locked_out: int | None


@dataclass(frozen=True)
class M365GraphLicenseReadResponse:
    result: ConnectorReadResult
    items: list[M365GraphSubscribedSku]
    next_cursor: str = ""


@dataclass(frozen=True)
class M365GraphMailFolder:
    id: str
    display_name: str
    parent_folder_id: str
    child_folder_count: int | None
    total_item_count: int | None
    unread_item_count: int | None
    is_hidden: bool | None


@dataclass(frozen=True)
class M365GraphMailFolderReadResponse:
    result: ConnectorReadResult
    items: list[M365GraphMailFolder]
    next_cursor: str = ""


@dataclass(frozen=True)
class M365GraphManagedDevice:
    id: str
    user_id: str
    device_name: str
    owner_type: str
    enrolled_date_time: str
    last_sync_date_time: str
    operating_system: str
    compliance_state: str
    management_agent: str
    os_version: str
    azure_ad_registered: bool | None
    device_registration_state: str
    is_encrypted: bool | None
    user_principal_name: str
    user_display_name: str
    model: str
    manufacturer: str


@dataclass(frozen=True)
class M365GraphManagedDeviceReadResponse:
    result: ConnectorReadResult
    items: list[M365GraphManagedDevice]
    next_cursor: str = ""


@dataclass(frozen=True)
class M365GraphUserCreateResult:
    status: str
    message: str
    remote_id: str = ""
    user_principal_name: str = ""
    display_name: str = ""
    account_enabled: bool | None = None
    status_code: int | None = None


@dataclass(frozen=True)
class M365GraphUserDisableResult:
    status: str
    message: str
    user_identity: str = ""
    status_code: int | None = None


@dataclass(frozen=True)
class M365GraphGroupMembershipResult:
    status: str
    message: str
    group_id: str = ""
    user_id: str = ""
    operation: str = ""
    status_code: int | None = None


@dataclass(frozen=True)
class M365GraphLicenseChangeResult:
    status: str
    message: str
    user_id: str = ""
    operation: str = ""
    sku_ids: tuple[str, ...] = ()
    status_code: int | None = None


@dataclass(frozen=True)
class M365GraphSessionRevokeResult:
    status: str
    message: str
    user_id: str = ""
    status_code: int | None = None


@dataclass(frozen=True)
class M365GraphManagedDeviceRetireResult:
    status: str
    message: str
    device_id: str = ""
    status_code: int | None = None


@dataclass(frozen=True)
class M365GraphMailboxSettingsUpdateResult:
    status: str
    message: str
    user_identity: str = ""
    settings: dict[str, str] = field(default_factory=dict)
    status_code: int | None = None


class M365GraphReadProvider(Protocol):
    def list_users(
        self,
        *,
        identity: str | None = None,
        cursor: str | None = None,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> M365GraphReadResponse:
        ...

    def list_groups(
        self,
        *,
        identity: str | None = None,
        cursor: str | None = None,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> M365GraphGroupReadResponse:
        ...

    def list_subscribed_skus(self, *, cursor: str | None = None) -> M365GraphLicenseReadResponse:
        ...

    def list_mail_folders(
        self,
        *,
        identity: str | None = None,
        cursor: str | None = None,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> M365GraphMailFolderReadResponse:
        ...

    def list_managed_devices(
        self,
        *,
        cursor: str | None = None,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> M365GraphManagedDeviceReadResponse:
        ...


class M365GraphReadError(Exception):
    """A sanitized live Graph failure."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class M365GraphClient:
    """Bounded Microsoft Graph context lookup and approved-write client."""

    def __init__(self, settings: Settings, *, transport: httpx.BaseTransport | None = None) -> None:
        self.settings = settings
        self.transport = transport

    def health(self) -> ConnectorReadResult:
        blocked = self._blocked_result()
        if blocked is not None:
            return blocked
        missing = self._not_configured_result()
        if missing is not None:
            return missing
        response = self.list_users(page_size=1)
        if response.result.status == "ready":
            return ConnectorReadResult(
                "ready",
                "Microsoft Graph identity, group, license, mailbox, and Intune read prerequisites are ready.",
            )
        return response.result

    def list_users(
        self,
        *,
        identity: str | None = None,
        cursor: str | None = None,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> M365GraphReadResponse:
        try:
            params = _list_params(page_size, cursor)
            if identity is not None:
                safe_identity = _safe_identity(identity)
                escaped = safe_identity.replace("'", "''")
                params["$filter"] = (
                    f"id eq '{escaped}' or userPrincipalName eq '{escaped}'"
                )
        except M365GraphReadError as exc:
            return M365GraphReadResponse(ConnectorReadResult("failed", exc.message), [])
        return self._request_users(params)

    def list_groups(
        self,
        *,
        identity: str | None = None,
        cursor: str | None = None,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> M365GraphGroupReadResponse:
        try:
            params = _group_list_params(page_size, cursor)
            if identity is not None:
                safe_identity = _safe_identity(identity)
                escaped = safe_identity.replace("'", "''")
                params["$filter"] = (
                    f"id eq '{escaped}' or mail eq '{escaped}' or "
                    f"mailNickname eq '{escaped}' or displayName eq '{escaped}'"
                )
        except M365GraphReadError as exc:
            return M365GraphGroupReadResponse(ConnectorReadResult("failed", exc.message), [])
        return self._request_groups(params)

    def list_subscribed_skus(
        self,
        *,
        cursor: str | None = None,
    ) -> M365GraphLicenseReadResponse:
        try:
            params = _license_list_params(cursor)
        except M365GraphReadError as exc:
            return M365GraphLicenseReadResponse(ConnectorReadResult("failed", exc.message), [])
        return self._request_subscribed_skus(params)

    def list_mail_folders(
        self,
        *,
        identity: str | None = None,
        cursor: str | None = None,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> M365GraphMailFolderReadResponse:
        try:
            if identity is None:
                raise M365GraphReadError("Microsoft Graph mailbox identity is required.")
            endpoint = _mail_folder_endpoint(identity)
            params = _mail_folder_params(page_size, cursor)
        except M365GraphReadError as exc:
            return M365GraphMailFolderReadResponse(ConnectorReadResult("failed", exc.message), [])
        return self._request_mail_folders(endpoint, params)

    def list_managed_devices(
        self,
        *,
        cursor: str | None = None,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> M365GraphManagedDeviceReadResponse:
        try:
            params = _managed_device_params(page_size, cursor)
        except M365GraphReadError as exc:
            return M365GraphManagedDeviceReadResponse(ConnectorReadResult("failed", exc.message), [])
        return self._request_managed_devices(params)

    def write_health(self) -> ConnectorReadResult:
        if not self.settings.allow_http_probing:
            return ConnectorReadResult(
                "blocked",
                "Microsoft Graph live writes are blocked until WAIT_ALLOW_HTTP_PROBING=true.",
            )
        if not self.settings.allow_write_actions:
            return ConnectorReadResult(
                "blocked",
                "Microsoft Graph live writes are blocked until WAIT_ALLOW_WRITE_ACTIONS=true.",
            )
        missing = self._not_configured_result()
        if missing is not None:
            return ConnectorReadResult("not_configured", missing.message)
        return ConnectorReadResult(
            "ready",
            "Microsoft Graph approved user lifecycle, group-membership, and managed-device prerequisites are ready.",
        )

    def create_user(
        self,
        *,
        user_principal_name: str,
        display_name: str,
        mail_nickname: str,
        temporary_password: str,
        account_enabled: bool,
        force_change_password_next_sign_in: bool,
    ) -> M365GraphUserCreateResult:
        health = self.write_health()
        if health.status != "ready":
            return M365GraphUserCreateResult("blocked", health.message)
        try:
            payload = _user_create_payload(
                user_principal_name=user_principal_name,
                display_name=display_name,
                mail_nickname=mail_nickname,
                temporary_password=temporary_password,
                account_enabled=account_enabled,
                force_change_password_next_sign_in=force_change_password_next_sign_in,
            )
            response_payload, status_code = self._post("users", payload)
        except M365GraphReadError as exc:
            return M365GraphUserCreateResult("failed", exc.message)
        user = _normalize_user(response_payload if isinstance(response_payload, Mapping) else {})
        if user is None:
            return M365GraphUserCreateResult(
                "failed",
                "Microsoft Graph POST users returned no usable user identity.",
                status_code=status_code,
            )
        return M365GraphUserCreateResult(
            "succeeded",
            "Microsoft Graph user creation succeeded.",
            remote_id=user.id,
            user_principal_name=user.user_principal_name,
            display_name=user.display_name,
            account_enabled=user.account_enabled,
            status_code=status_code,
        )

    def disable_user(self, *, user_identity: str) -> M365GraphUserDisableResult:
        health = self.write_health()
        if health.status != "ready":
            return M365GraphUserDisableResult("blocked", health.message)
        try:
            safe_identity = _safe_user_target(user_identity)
            endpoint = f"users/{quote(safe_identity, safe='')}"
            _, status_code = self._patch(endpoint, {"accountEnabled": False})
        except M365GraphReadError as exc:
            return M365GraphUserDisableResult("failed", exc.message)
        return M365GraphUserDisableResult(
            "succeeded",
            "Microsoft Graph user disable succeeded.",
            user_identity=safe_identity,
            status_code=status_code,
        )

    def change_group_membership(
        self,
        *,
        group_id: str,
        user_id: str,
        operation: str,
    ) -> M365GraphGroupMembershipResult:
        health = self.write_health()
        if health.status != "ready":
            return M365GraphGroupMembershipResult("blocked", health.message)
        try:
            safe_group_id = _safe_directory_object_id(group_id, "group_id")
            safe_user_id = _safe_directory_object_id(user_id, "user_id")
            if operation not in {"add", "remove"}:
                raise M365GraphReadError("Microsoft Graph group membership operation is invalid.")
            encoded_group_id = quote(safe_group_id, safe="")
            encoded_user_id = quote(safe_user_id, safe="")
            if operation == "add":
                endpoint = f"groups/{encoded_group_id}/members/$ref"
                payload: dict[str, object] = {
                    "@odata.id": (
                        f"{_api_base_url(self.settings.m365_graph_base_url)}"
                        f"/directoryObjects/{encoded_user_id}"
                    )
                }
                _, status_code = self._post(endpoint, payload)
            else:
                endpoint = (
                    f"groups/{encoded_group_id}/members/{encoded_user_id}/$ref"
                )
                _, status_code = self._delete(endpoint)
        except M365GraphReadError as exc:
            return M365GraphGroupMembershipResult("failed", exc.message)
        return M365GraphGroupMembershipResult(
            "succeeded",
            f"Microsoft Graph group membership {operation} succeeded.",
            group_id=safe_group_id,
            user_id=safe_user_id,
            operation=operation,
            status_code=status_code,
        )

    def change_user_licenses(
        self,
        *,
        user_id: str,
        sku_ids: list[str],
        operation: str,
    ) -> M365GraphLicenseChangeResult:
        health = self.write_health()
        if health.status != "ready":
            return M365GraphLicenseChangeResult("blocked", health.message)
        try:
            safe_user_id = _safe_directory_object_id(user_id, "user_id")
            safe_sku_ids = _safe_sku_ids(sku_ids)
            if operation not in {"add", "remove"}:
                raise M365GraphReadError("Microsoft Graph license operation is invalid.")
            endpoint = f"users/{quote(safe_user_id, safe='')}/assignLicense"
            payload: dict[str, object]
            if operation == "add":
                payload = {
                    "addLicenses": [
                        {"disabledPlans": [], "skuId": sku_id}
                        for sku_id in safe_sku_ids
                    ],
                    "removeLicenses": [],
                }
            else:
                payload = {"addLicenses": [], "removeLicenses": safe_sku_ids}
            _, status_code = self._post(endpoint, payload)
        except M365GraphReadError as exc:
            return M365GraphLicenseChangeResult("failed", exc.message)
        return M365GraphLicenseChangeResult(
            "succeeded",
            f"Microsoft Graph user license {operation} succeeded.",
            user_id=safe_user_id,
            operation=operation,
            sku_ids=tuple(safe_sku_ids),
            status_code=status_code,
        )

    def revoke_user_sessions(self, *, user_id: str) -> M365GraphSessionRevokeResult:
        health = self.write_health()
        if health.status != "ready":
            return M365GraphSessionRevokeResult("blocked", health.message)
        try:
            safe_user_id = _safe_directory_object_id(user_id, "user_id")
            endpoint = f"users/{quote(safe_user_id, safe='')}/revokeSignInSessions"
            _, status_code = self._post(endpoint, None)
        except M365GraphReadError as exc:
            return M365GraphSessionRevokeResult("failed", exc.message)
        return M365GraphSessionRevokeResult(
            "succeeded",
            "Microsoft Graph user session revocation succeeded.",
            user_id=safe_user_id,
            status_code=status_code,
        )

    def retire_managed_device(self, *, device_id: str) -> M365GraphManagedDeviceRetireResult:
        health = self.write_health()
        if health.status != "ready":
            return M365GraphManagedDeviceRetireResult("blocked", health.message)
        try:
            safe_device_id = _safe_directory_object_id(device_id, "device_id")
            endpoint = f"deviceManagement/managedDevices/{quote(safe_device_id, safe='')}/retire"
            _, status_code = self._post(endpoint, None)
        except M365GraphReadError as exc:
            return M365GraphManagedDeviceRetireResult("failed", exc.message)
        return M365GraphManagedDeviceRetireResult(
            "succeeded",
            "Microsoft Graph Intune managed-device retirement succeeded.",
            device_id=safe_device_id,
            status_code=status_code,
        )

    def update_mailbox_settings(
        self,
        *,
        user_identity: str,
        settings: Mapping[str, str],
    ) -> M365GraphMailboxSettingsUpdateResult:
        health = self.write_health()
        if health.status != "ready":
            return M365GraphMailboxSettingsUpdateResult("blocked", health.message)
        try:
            safe_identity = _safe_user_target(user_identity)
            payload = cast(dict[str, object], _mailbox_settings_payload(settings))
            endpoint = f"users/{quote(safe_identity, safe='')}/mailboxSettings"
            _, status_code = self._patch(endpoint, payload)
        except M365GraphReadError as exc:
            return M365GraphMailboxSettingsUpdateResult("failed", exc.message)
        return M365GraphMailboxSettingsUpdateResult(
            "succeeded",
            "Microsoft Graph mailbox settings update succeeded.",
            user_identity=safe_identity,
            settings=cast(dict[str, str], payload),
            status_code=status_code,
        )

    def _request_users(self, params: dict[str, str | int]) -> M365GraphReadResponse:
        blocked = self._blocked_response()
        if blocked is not None:
            return blocked
        missing = self._not_configured_response()
        if missing is not None:
            return missing
        try:
            payload = self._get("users", params=params)
        except M365GraphReadError as exc:
            return M365GraphReadResponse(ConnectorReadResult("failed", exc.message), [])
        items = [user for row in _payload_rows(payload) if (user := _normalize_user(row)) is not None]
        return M365GraphReadResponse(
            ConnectorReadResult("ready", "Microsoft Graph user identity read succeeded.", len(items)),
            items,
            _next_cursor(payload),
        )

    def _request_groups(self, params: dict[str, str | int]) -> M365GraphGroupReadResponse:
        blocked = self._blocked_result()
        if blocked is not None:
            return M365GraphGroupReadResponse(blocked, [])
        missing = self._not_configured_result()
        if missing is not None:
            return M365GraphGroupReadResponse(missing, [])
        try:
            payload = self._get("groups", params=params)
        except M365GraphReadError as exc:
            return M365GraphGroupReadResponse(ConnectorReadResult("failed", exc.message), [])
        items = [group for row in _payload_rows(payload) if (group := _normalize_group(row)) is not None]
        return M365GraphGroupReadResponse(
            ConnectorReadResult("ready", "Microsoft Graph group read succeeded.", len(items)),
            items,
            _next_cursor(payload),
        )

    def _request_subscribed_skus(
        self,
        params: dict[str, str | int],
    ) -> M365GraphLicenseReadResponse:
        blocked = self._blocked_result()
        if blocked is not None:
            return M365GraphLicenseReadResponse(blocked, [])
        missing = self._not_configured_result()
        if missing is not None:
            return M365GraphLicenseReadResponse(missing, [])
        try:
            payload = self._get("subscribedSkus", params=params)
        except M365GraphReadError as exc:
            return M365GraphLicenseReadResponse(ConnectorReadResult("failed", exc.message), [])
        rows = _payload_rows(payload)[:MAX_LICENSE_ITEMS]
        items = [sku for row in rows if (sku := _normalize_subscribed_sku(row)) is not None]
        return M365GraphLicenseReadResponse(
            ConnectorReadResult("ready", "Microsoft Graph subscribed license read succeeded.", len(items)),
            items,
            _next_cursor(payload),
        )

    def _request_mail_folders(
        self,
        endpoint: str,
        params: dict[str, str | int],
    ) -> M365GraphMailFolderReadResponse:
        blocked = self._blocked_result()
        if blocked is not None:
            return M365GraphMailFolderReadResponse(blocked, [])
        missing = self._not_configured_result()
        if missing is not None:
            return M365GraphMailFolderReadResponse(missing, [])
        try:
            payload = self._get(endpoint, params=params)
        except M365GraphReadError as exc:
            return M365GraphMailFolderReadResponse(ConnectorReadResult("failed", exc.message), [])
        items = [
            folder
            for row in _payload_rows(payload)
            if (folder := _normalize_mail_folder(row)) is not None
        ]
        return M365GraphMailFolderReadResponse(
            ConnectorReadResult("ready", "Microsoft Graph mailbox folder read succeeded.", len(items)),
            items,
            _next_cursor(payload),
        )

    def _request_managed_devices(
        self,
        params: dict[str, str | int],
    ) -> M365GraphManagedDeviceReadResponse:
        blocked = self._blocked_result()
        if blocked is not None:
            return M365GraphManagedDeviceReadResponse(blocked, [])
        missing = self._not_configured_result()
        if missing is not None:
            return M365GraphManagedDeviceReadResponse(missing, [])
        try:
            payload = self._get("deviceManagement/managedDevices", params=params)
        except M365GraphReadError as exc:
            return M365GraphManagedDeviceReadResponse(ConnectorReadResult("failed", exc.message), [])
        items = [
            device
            for row in _payload_rows(payload)
            if (device := _normalize_managed_device(row)) is not None
        ]
        return M365GraphManagedDeviceReadResponse(
            ConnectorReadResult("ready", "Microsoft Graph Intune managed-device read succeeded.", len(items)),
            items,
            _next_cursor(payload),
        )

    def _get(self, endpoint: str, *, params: dict[str, str | int] | None = None) -> object:
        if not self.settings.allow_http_probing:
            raise M365GraphReadError(
                "Microsoft Graph live reads are blocked until WAIT_ALLOW_HTTP_PROBING=true."
            )
        missing = self._not_configured_result()
        if missing is not None:
            raise M365GraphReadError(missing.message)
        try:
            safe_endpoint = _safe_endpoint(endpoint)
            with httpx.Client(timeout=self.settings.connector_timeout_seconds, transport=self.transport) as client:
                response = client.get(
                    f"{_api_base_url(self.settings.m365_graph_base_url)}/{safe_endpoint}",
                    headers={
                        "Authorization": f"Bearer {self.settings.m365_access_token}",
                        "Accept": "application/json",
                    },
                    params=params,
                )
        except (httpx.TimeoutException, httpx.ConnectError) as exc:
            raise M365GraphReadError(
                "Microsoft Graph request failed before receiving a response."
            ) from exc
        except httpx.HTTPError as exc:
            raise M365GraphReadError("Microsoft Graph request failed.") from exc
        if response.status_code >= 400:
            raise M365GraphReadError(_http_error_message(response.status_code, safe_endpoint))
        try:
            return response.json()
        except ValueError as exc:
            raise M365GraphReadError(
                f"Microsoft Graph GET {safe_endpoint} returned malformed JSON."
            ) from exc

    def _post(
        self,
        endpoint: str,
        payload: dict[str, object] | None,
    ) -> tuple[object, int]:
        if not self.settings.allow_http_probing:
            raise M365GraphReadError(
                "Microsoft Graph live writes are blocked until WAIT_ALLOW_HTTP_PROBING=true."
            )
        if not self.settings.allow_write_actions:
            raise M365GraphReadError(
                "Microsoft Graph live writes are blocked until WAIT_ALLOW_WRITE_ACTIONS=true."
            )
        missing = self._not_configured_result()
        if missing is not None:
            raise M365GraphReadError(missing.message)
        try:
            safe_endpoint = _safe_endpoint(endpoint)
            with httpx.Client(timeout=self.settings.connector_timeout_seconds, transport=self.transport) as client:
                headers = {
                    "Authorization": f"Bearer {self.settings.m365_access_token}",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                }
                if payload is None:
                    response = client.post(
                        f"{_api_base_url(self.settings.m365_graph_base_url)}/{safe_endpoint}",
                        headers=headers,
                        content=b"",
                    )
                else:
                    response = client.post(
                        f"{_api_base_url(self.settings.m365_graph_base_url)}/{safe_endpoint}",
                        headers=headers,
                        json=payload,
                    )
        except (httpx.TimeoutException, httpx.ConnectError) as exc:
            raise M365GraphReadError(
                "Microsoft Graph request failed before receiving a response."
            ) from exc
        except httpx.HTTPError as exc:
            raise M365GraphReadError("Microsoft Graph request failed.") from exc
        if response.status_code >= 400:
            raise M365GraphReadError(
                _http_error_message(response.status_code, safe_endpoint, method="POST")
            )
        if not response.content:
            return {}, response.status_code
        try:
            return response.json(), response.status_code
        except ValueError as exc:
            raise M365GraphReadError(
                f"Microsoft Graph POST {safe_endpoint} returned malformed JSON."
            ) from exc

    def _patch(self, endpoint: str, payload: dict[str, object]) -> tuple[object, int]:
        if not self.settings.allow_http_probing:
            raise M365GraphReadError(
                "Microsoft Graph live writes are blocked until WAIT_ALLOW_HTTP_PROBING=true."
            )
        if not self.settings.allow_write_actions:
            raise M365GraphReadError(
                "Microsoft Graph live writes are blocked until WAIT_ALLOW_WRITE_ACTIONS=true."
            )
        missing = self._not_configured_result()
        if missing is not None:
            raise M365GraphReadError(missing.message)
        try:
            safe_endpoint = _safe_endpoint(endpoint)
            with httpx.Client(timeout=self.settings.connector_timeout_seconds, transport=self.transport) as client:
                response = client.patch(
                    f"{_api_base_url(self.settings.m365_graph_base_url)}/{safe_endpoint}",
                    headers={
                        "Authorization": f"Bearer {self.settings.m365_access_token}",
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
        except (httpx.TimeoutException, httpx.ConnectError) as exc:
            raise M365GraphReadError(
                "Microsoft Graph request failed before receiving a response."
            ) from exc
        except httpx.HTTPError as exc:
            raise M365GraphReadError("Microsoft Graph request failed.") from exc
        if response.status_code >= 400:
            raise M365GraphReadError(
                _http_error_message(response.status_code, safe_endpoint, method="PATCH")
            )
        if not response.content:
            return {}, response.status_code
        try:
            return response.json(), response.status_code
        except ValueError as exc:
            raise M365GraphReadError(
                f"Microsoft Graph PATCH {safe_endpoint} returned malformed JSON."
            ) from exc

    def _delete(self, endpoint: str) -> tuple[object, int]:
        if not self.settings.allow_http_probing:
            raise M365GraphReadError(
                "Microsoft Graph live writes are blocked until WAIT_ALLOW_HTTP_PROBING=true."
            )
        if not self.settings.allow_write_actions:
            raise M365GraphReadError(
                "Microsoft Graph live writes are blocked until WAIT_ALLOW_WRITE_ACTIONS=true."
            )
        missing = self._not_configured_result()
        if missing is not None:
            raise M365GraphReadError(missing.message)
        try:
            safe_endpoint = _safe_endpoint(endpoint)
            with httpx.Client(timeout=self.settings.connector_timeout_seconds, transport=self.transport) as client:
                response = client.delete(
                    f"{_api_base_url(self.settings.m365_graph_base_url)}/{safe_endpoint}",
                    headers={
                        "Authorization": f"Bearer {self.settings.m365_access_token}",
                        "Accept": "application/json",
                    },
                )
        except (httpx.TimeoutException, httpx.ConnectError) as exc:
            raise M365GraphReadError(
                "Microsoft Graph request failed before receiving a response."
            ) from exc
        except httpx.HTTPError as exc:
            raise M365GraphReadError("Microsoft Graph request failed.") from exc
        if response.status_code >= 400:
            raise M365GraphReadError(
                _http_error_message(response.status_code, safe_endpoint, method="DELETE")
            )
        return {}, response.status_code

    def _blocked_result(self) -> ConnectorReadResult | None:
        if self.settings.allow_http_probing:
            return None
        return ConnectorReadResult(
            "blocked",
            "Microsoft Graph live reads are blocked until WAIT_ALLOW_HTTP_PROBING=true.",
        )

    def _not_configured_result(self) -> ConnectorReadResult | None:
        missing = [
            key
            for key, value in {
                "WAIT_M365_GRAPH_BASE_URL": self.settings.m365_graph_base_url,
                "WAIT_M365_ACCESS_TOKEN": self.settings.m365_access_token,
            }.items()
            if not value
        ]
        if not missing:
            return None
        return ConnectorReadResult(
            "not_configured",
            f"Microsoft Graph live read credentials are incomplete: {', '.join(missing)}.",
        )

    def _blocked_response(self) -> M365GraphReadResponse | None:
        blocked = self._blocked_result()
        return M365GraphReadResponse(blocked, []) if blocked else None

    def _not_configured_response(self) -> M365GraphReadResponse | None:
        missing = self._not_configured_result()
        return M365GraphReadResponse(missing, []) if missing else None


def _api_base_url(base_url: str) -> str:
    if any(ord(character) < 32 for character in base_url):
        raise M365GraphReadError("Microsoft Graph base URL contains control characters.")
    parsed = urlsplit(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise M365GraphReadError("Microsoft Graph base URL must be an HTTP(S) URL.")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise M365GraphReadError(
            "Microsoft Graph base URL must not contain credentials or query data."
        )
    return base_url.rstrip("/")


def _safe_endpoint(endpoint: str) -> str:
    endpoint_parts = endpoint.split("/")
    is_mail_folder_endpoint = (
        len(endpoint_parts) == 3
        and endpoint_parts[0] == "users"
        and bool(endpoint_parts[1])
        and endpoint_parts[2] == "mailFolders"
        and quote(unquote(endpoint_parts[1]), safe="") == endpoint_parts[1]
        and not any(ord(character) < 32 for character in endpoint)
    )
    is_user_endpoint = (
        len(endpoint_parts) == 2
        and endpoint_parts[0] == "users"
        and bool(endpoint_parts[1])
        and quote(unquote(endpoint_parts[1]), safe="") == endpoint_parts[1]
        and not any(ord(character) < 32 for character in endpoint)
    )
    is_user_license_endpoint = (
        len(endpoint_parts) == 3
        and endpoint_parts[0] == "users"
        and endpoint_parts[2] == "assignLicense"
        and _safe_encoded_segment(endpoint_parts[1])
        and not any(ord(character) < 32 for character in endpoint)
    )
    is_user_session_revoke_endpoint = (
        len(endpoint_parts) == 3
        and endpoint_parts[0] == "users"
        and endpoint_parts[2] == "revokeSignInSessions"
        and _safe_encoded_segment(endpoint_parts[1])
        and not any(ord(character) < 32 for character in endpoint)
    )
    is_managed_device_retire_endpoint = (
        len(endpoint_parts) == 4
        and endpoint_parts[0] == "deviceManagement"
        and endpoint_parts[1] == "managedDevices"
        and endpoint_parts[3] == "retire"
        and _safe_encoded_segment(endpoint_parts[2])
        and not any(ord(character) < 32 for character in endpoint)
    )
    is_mailbox_settings_endpoint = (
        len(endpoint_parts) == 3
        and endpoint_parts[0] == "users"
        and endpoint_parts[2] == "mailboxSettings"
        and _safe_encoded_segment(endpoint_parts[1])
        and not any(ord(character) < 32 for character in endpoint)
    )
    is_group_members_add_endpoint = (
        len(endpoint_parts) == 4
        and endpoint_parts[0] == "groups"
        and endpoint_parts[2] == "members"
        and endpoint_parts[3] == "$ref"
        and _safe_encoded_segment(endpoint_parts[1])
        and not any(ord(character) < 32 for character in endpoint)
    )
    is_group_members_remove_endpoint = (
        len(endpoint_parts) == 5
        and endpoint_parts[0] == "groups"
        and endpoint_parts[2] == "members"
        and endpoint_parts[4] == "$ref"
        and _safe_encoded_segment(endpoint_parts[1])
        and _safe_encoded_segment(endpoint_parts[3])
        and not any(ord(character) < 32 for character in endpoint)
    )
    if endpoint not in {
        "users",
        "groups",
        "subscribedSkus",
        "deviceManagement/managedDevices",
    } and (
        not is_mail_folder_endpoint
        and not is_user_endpoint
        and not is_user_license_endpoint
        and not is_user_session_revoke_endpoint
        and not is_managed_device_retire_endpoint
        and not is_mailbox_settings_endpoint
        and not is_group_members_add_endpoint
        and not is_group_members_remove_endpoint
    ):
        raise M365GraphReadError("Microsoft Graph endpoint is invalid.")
    return endpoint


def _safe_encoded_segment(value: str) -> bool:
    return bool(value) and quote(unquote(value), safe="") == value


def _user_create_payload(
    *,
    user_principal_name: str,
    display_name: str,
    mail_nickname: str,
    temporary_password: str,
    account_enabled: bool,
    force_change_password_next_sign_in: bool,
) -> dict[str, object]:
    safe_upn = _safe_user_principal_name(user_principal_name)
    safe_display_name = _safe_required_text(display_name, "display_name", 256)
    safe_mail_nickname = _safe_mail_nickname(mail_nickname)
    if not isinstance(account_enabled, bool) or not isinstance(force_change_password_next_sign_in, bool):
        raise M365GraphReadError("Microsoft Graph user creation flags are invalid.")
    if (
        not isinstance(temporary_password, str)
        or not 8 <= len(temporary_password) <= 256
        or any(ord(character) < 32 for character in temporary_password)
    ):
        raise M365GraphReadError("Microsoft Graph temporary password is invalid.")
    return {
        "accountEnabled": account_enabled,
        "displayName": safe_display_name,
        "mailNickname": safe_mail_nickname,
        "userPrincipalName": safe_upn,
        "passwordProfile": {
            "forceChangePasswordNextSignIn": force_change_password_next_sign_in,
            "password": temporary_password,
        },
    }


def _safe_required_text(value: str, field: str, maximum: int) -> str:
    stripped = value.strip()
    if not stripped or len(stripped) > maximum or any(ord(character) < 32 for character in stripped):
        raise M365GraphReadError(f"Microsoft Graph {field} is invalid.")
    return stripped


def _safe_user_principal_name(value: str) -> str:
    stripped = _safe_required_text(value, "user_principal_name", 320)
    if stripped.count("@") != 1 or any(character.isspace() for character in stripped):
        raise M365GraphReadError("Microsoft Graph user_principal_name is invalid.")
    return stripped


def _safe_user_target(value: str) -> str:
    stripped = value.strip()
    if (
        not stripped
        or len(stripped) > MAX_IDENTITY_LENGTH
        or any(ord(character) < 32 or character.isspace() for character in stripped)
    ):
        raise M365GraphReadError("Microsoft Graph user identity is invalid.")
    return stripped


def _safe_directory_object_id(value: str, field: str) -> str:
    stripped = value.strip()
    if (
        not stripped
        or len(stripped) > MAX_IDENTITY_LENGTH
        or any(ord(character) < 32 or character.isspace() for character in stripped)
    ):
        raise M365GraphReadError(f"Microsoft Graph {field} is invalid.")
    return stripped


def _mailbox_settings_payload(settings: Mapping[str, str]) -> dict[str, str]:
    field_names = {
        "time_zone": "timeZone",
        "locale": "locale",
        "date_format": "dateFormat",
        "time_format": "timeFormat",
    }
    if not isinstance(settings, Mapping) or not settings:
        raise M365GraphReadError("Microsoft Graph mailbox settings must contain at least one setting.")
    if set(settings) - set(field_names):
        raise M365GraphReadError("Microsoft Graph mailbox settings contain an unsupported field.")
    payload: dict[str, str] = {}
    for field_name, value in settings.items():
        if (
            not isinstance(value, str)
            or not value.strip()
            or len(value.strip()) > 128
            or any(ord(character) < 32 for character in value)
        ):
            raise M365GraphReadError(f"Microsoft Graph mailbox setting {field_name} is invalid.")
        payload[field_names[field_name]] = value.strip()
    return payload


def _safe_sku_ids(values: list[str]) -> list[str]:
    if not isinstance(values, list) or not 1 <= len(values) <= 50:
        raise M365GraphReadError("Microsoft Graph sku_ids must contain 1 to 50 IDs.")
    normalized: list[str] = []
    for value in values:
        if not isinstance(value, str):
            raise M365GraphReadError("Microsoft Graph sku_id is invalid.")
        stripped = value.strip()
        parts = stripped.split("-")
        if (
            len(stripped) != 36
            or len(parts) != 5
            or [len(part) for part in parts] != [8, 4, 4, 4, 12]
            or any(character not in "0123456789abcdefABCDEF" for character in stripped.replace("-", ""))
        ):
            raise M365GraphReadError("Microsoft Graph sku_id is invalid.")
        canonical = stripped.lower()
        if canonical in normalized:
            raise M365GraphReadError("Microsoft Graph sku_ids must be unique.")
        normalized.append(canonical)
    return normalized


def _safe_mail_nickname(value: str) -> str:
    stripped = _safe_required_text(value, "mail_nickname", 64)
    if any(
        character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-"
        for character in stripped
    ):
        raise M365GraphReadError("Microsoft Graph mail_nickname is invalid.")
    return stripped


def _safe_identity(value: str) -> str:
    stripped = value.strip()
    if (
        not stripped
        or len(stripped) > MAX_IDENTITY_LENGTH
        or any(ord(character) < 32 for character in stripped)
    ):
        raise M365GraphReadError("Microsoft Graph identity is invalid.")
    return stripped


def _safe_cursor(value: str) -> str:
    stripped = value.strip()
    if not stripped or len(stripped) > MAX_CURSOR_LENGTH or any(ord(character) < 32 for character in stripped):
        raise M365GraphReadError("Microsoft Graph cursor is invalid.")
    return stripped


def _bounded_page_size(value: int) -> int:
    if isinstance(value, bool) or value < 1:
        raise M365GraphReadError("Microsoft Graph page_size must be at least 1.")
    return min(value, MAX_PAGE_SIZE)


def _list_params(page_size: int, cursor: str | None) -> dict[str, str | int]:
    params: dict[str, str | int] = {
        "$top": _bounded_page_size(page_size),
        "$select": (
            "id,displayName,userPrincipalName,mail,accountEnabled,jobTitle,department"
        ),
    }
    if cursor is not None:
        params["$skiptoken"] = _safe_cursor(cursor)
    return params


def _group_list_params(page_size: int, cursor: str | None) -> dict[str, str | int]:
    params: dict[str, str | int] = {
        "$top": _bounded_page_size(page_size),
        "$select": (
            "id,displayName,mail,mailNickname,description,mailEnabled,securityEnabled,groupTypes"
        ),
    }
    if cursor is not None:
        params["$skiptoken"] = _safe_cursor(cursor)
    return params


def _mail_folder_endpoint(identity: str) -> str:
    return f"users/{quote(_safe_identity(identity), safe='')}/mailFolders"


def _mail_folder_params(page_size: int, cursor: str | None) -> dict[str, str | int]:
    params: dict[str, str | int] = {
        "$top": _bounded_page_size(page_size),
        "$select": (
            "id,displayName,parentFolderId,childFolderCount,totalItemCount,"
            "unreadItemCount,isHidden"
        ),
    }
    if cursor is not None:
        params["$skiptoken"] = _safe_cursor(cursor)
    return params


def _managed_device_params(page_size: int, cursor: str | None) -> dict[str, str | int]:
    params: dict[str, str | int] = {
        "$top": _bounded_page_size(page_size),
        "$select": (
            "id,userId,deviceName,managedDeviceOwnerType,enrolledDateTime,"
            "lastSyncDateTime,operatingSystem,complianceState,managementAgent,"
            "osVersion,azureADRegistered,deviceRegistrationState,isEncrypted,"
            "userPrincipalName,userDisplayName,model,manufacturer"
        ),
    }
    if cursor is not None:
        params["$skiptoken"] = _safe_cursor(cursor)
    return params


def _license_list_params(cursor: str | None) -> dict[str, str | int]:
    params: dict[str, str | int] = {
        "$select": (
            "id,skuId,skuPartNumber,capabilityStatus,consumedUnits,appliesTo,prepaidUnits"
        ),
    }
    if cursor is not None:
        params["$skiptoken"] = _safe_cursor(cursor)
    return params


def _payload_rows(payload: object) -> list[Mapping[str, object]]:
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        value = payload.get("value")
        if isinstance(value, list):
            rows = value
        elif isinstance(value, dict):
            rows = [value]
        else:
            rows = [payload]
    else:
        return []
    return [row for row in rows if isinstance(row, dict)]


def _normalize_user(row: Mapping[str, object]) -> M365GraphUser | None:
    user_id = _string_value(row, "id")
    if not user_id:
        return None
    account_enabled = row.get("accountEnabled")
    return M365GraphUser(
        id=user_id,
        display_name=_string_value(row, "displayName"),
        user_principal_name=_string_value(row, "userPrincipalName"),
        mail=_string_value(row, "mail"),
        account_enabled=account_enabled if isinstance(account_enabled, bool) else None,
        job_title=_string_value(row, "jobTitle"),
        department=_string_value(row, "department"),
    )


def _normalize_group(row: Mapping[str, object]) -> M365GraphGroup | None:
    group_id = _string_value(row, "id")
    if not group_id:
        return None
    group_types = row.get("groupTypes")
    normalized_group_types = (
        tuple(value for value in group_types if isinstance(value, str))
        if isinstance(group_types, list)
        else ()
    )
    mail_enabled = row.get("mailEnabled")
    security_enabled = row.get("securityEnabled")
    return M365GraphGroup(
        id=group_id,
        display_name=_string_value(row, "displayName"),
        mail=_string_value(row, "mail"),
        mail_nickname=_string_value(row, "mailNickname"),
        description=_string_value(row, "description"),
        mail_enabled=mail_enabled if isinstance(mail_enabled, bool) else None,
        security_enabled=security_enabled if isinstance(security_enabled, bool) else None,
        group_types=normalized_group_types,
    )


def _normalize_subscribed_sku(row: Mapping[str, object]) -> M365GraphSubscribedSku | None:
    sku_id = _string_value(row, "id")
    if not sku_id:
        return None
    prepaid_units = row.get("prepaidUnits")
    prepaid = prepaid_units if isinstance(prepaid_units, Mapping) else {}
    return M365GraphSubscribedSku(
        id=sku_id,
        sku_id=_string_value(row, "skuId"),
        sku_part_number=_string_value(row, "skuPartNumber"),
        capability_status=_string_value(row, "capabilityStatus"),
        applies_to=_string_value(row, "appliesTo"),
        consumed_units=_int_value(row.get("consumedUnits")),
        prepaid_enabled=_int_value(prepaid.get("enabled")),
        prepaid_warning=_int_value(prepaid.get("warning")),
        prepaid_suspended=_int_value(prepaid.get("suspended")),
        prepaid_locked_out=_int_value(prepaid.get("lockedOut")),
    )


def _normalize_mail_folder(row: Mapping[str, object]) -> M365GraphMailFolder | None:
    folder_id = _string_value(row, "id")
    if not folder_id:
        return None
    return M365GraphMailFolder(
        id=folder_id,
        display_name=_string_value(row, "displayName"),
        parent_folder_id=_string_value(row, "parentFolderId"),
        child_folder_count=_int_value(row.get("childFolderCount")),
        total_item_count=_int_value(row.get("totalItemCount")),
        unread_item_count=_int_value(row.get("unreadItemCount")),
        is_hidden=_bool_value(row.get("isHidden")),
    )


def _normalize_managed_device(row: Mapping[str, object]) -> M365GraphManagedDevice | None:
    device_id = _string_value(row, "id")
    if not device_id:
        return None
    return M365GraphManagedDevice(
        id=device_id,
        user_id=_string_value(row, "userId"),
        device_name=_string_value(row, "deviceName"),
        owner_type=_string_value(row, "managedDeviceOwnerType"),
        enrolled_date_time=_string_value(row, "enrolledDateTime"),
        last_sync_date_time=_string_value(row, "lastSyncDateTime"),
        operating_system=_string_value(row, "operatingSystem"),
        compliance_state=_string_value(row, "complianceState"),
        management_agent=_string_value(row, "managementAgent"),
        os_version=_string_value(row, "osVersion"),
        azure_ad_registered=_bool_value(row.get("azureADRegistered")),
        device_registration_state=_string_value(row, "deviceRegistrationState"),
        is_encrypted=_bool_value(row.get("isEncrypted")),
        user_principal_name=_string_value(row, "userPrincipalName"),
        user_display_name=_string_value(row, "userDisplayName"),
        model=_string_value(row, "model"),
        manufacturer=_string_value(row, "manufacturer"),
    )


def _string_value(row: Mapping[str, object], key: str) -> str:
    value = row.get(key)
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)):
        return str(value)
    return ""


def _int_value(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _bool_value(value: object) -> bool | None:
    return value if isinstance(value, bool) else None


def _next_cursor(payload: object) -> str:
    if not isinstance(payload, dict):
        return ""
    next_link = payload.get("@odata.nextLink")
    if not isinstance(next_link, str):
        return ""
    query = parse_qs(urlsplit(next_link).query)
    values = query.get("$skiptoken", [])
    return values[0] if values and len(values[0]) <= MAX_CURSOR_LENGTH else ""


def _http_error_message(status_code: int, endpoint: str, *, method: str = "GET") -> str:
    if status_code == 401:
        return f"Microsoft Graph {method} {endpoint} returned HTTP 401 (authentication failed)."
    if status_code == 403:
        return f"Microsoft Graph {method} {endpoint} returned HTTP 403 (access denied)."
    if status_code == 404:
        return f"Microsoft Graph {method} {endpoint} returned HTTP 404 (not found)."
    if status_code == 429:
        return f"Microsoft Graph {method} {endpoint} returned HTTP 429 (rate limited)."
    return f"Microsoft Graph {method} {endpoint} returned HTTP {status_code}."


__all__ = [
    "M365GraphClient",
    "M365GraphGroup",
    "M365GraphGroupMembershipResult",
    "M365GraphGroupReadResponse",
    "M365GraphLicenseChangeResult",
    "M365GraphManagedDeviceRetireResult",
    "M365GraphMailboxSettingsUpdateResult",
    "M365GraphSessionRevokeResult",
    "M365GraphLicenseReadResponse",
    "M365GraphMailFolder",
    "M365GraphMailFolderReadResponse",
    "M365GraphManagedDevice",
    "M365GraphManagedDeviceReadResponse",
    "M365GraphUserCreateResult",
    "M365GraphUserDisableResult",
    "M365GraphReadError",
    "M365GraphReadResponse",
    "M365GraphSubscribedSku",
    "M365GraphUser",
]
