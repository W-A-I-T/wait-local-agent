"""Microsoft 365 connector API routes."""

from __future__ import annotations

from dataclasses import asdict
from typing import cast

from fastapi import APIRouter, HTTPException, Request

from wait_local_agent.api.context import AdminAccess, ApiContext, ViewerAccess
from wait_local_agent.api.schemas import (
    M365AuthenticationMethodDeleteDraftRequest,
    M365GroupMembershipDraftRequest,
    M365LicenseChangeDraftRequest,
    M365MailboxSettingsUpdateDraftRequest,
    M365MailMessageDeleteDraftRequest,
    M365MailMessageMoveDraftRequest,
    M365MailMessageReadStateDraftRequest,
    M365ManagedDeviceRebootDraftRequest,
    M365ManagedDeviceRemoteLockDraftRequest,
    M365ManagedDeviceRetirementDraftRequest,
    M365ManagedDeviceSyncDraftRequest,
    M365PasswordResetDraftRequest,
    M365SessionRevocationDraftRequest,
    M365UserDisableDraftRequest,
    M365UserDraftRequest,
    TeamsMessageDraftRequest,
)
from wait_local_agent.api.scopes import _approval_scope_visible, _required_client_id
from wait_local_agent.api.views import _safe_json_object
from wait_local_agent.client_scope import resolve_client_scope
from wait_local_agent.connectors import (
    draft_m365_authentication_method_delete,
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
    draft_m365_password_reset,
    draft_m365_session_revocation,
    draft_m365_user_creation,
    draft_m365_user_disable,
    execute_m365_approval_request,
)
from wait_local_agent.m365_graph import (
    M365GraphClient,
    M365GraphGroupReadResponse,
    M365GraphLicenseDetailReadResponse,
    M365GraphLicenseReadResponse,
    M365GraphMailFolderReadResponse,
    M365GraphMailMessageReadResponse,
    M365GraphManagedDeviceReadResponse,
    M365GraphReadError,
    M365GraphReadResponse,
)
from wait_local_agent.store import QuarantinedTicketError
from wait_local_agent.teams_graph import TeamsGraphClient
from wait_local_agent.vault import SecretVault


def create_m365_router(ctx: ApiContext) -> APIRouter:
    router = APIRouter()
    active_settings = ctx.active_settings
    store = ctx.store
    limiter = ctx.limiter
    m365_client = ctx.m365_client
    teams_client = ctx.teams_client
    _connector_read_client = ctx.connector_read_client
    _approval_view = ctx.approval_view

    def _raise_m365_graph_http_error(error: M365GraphReadError | None) -> None:
        if error is None or error.code is None:
            return
        status_code = {
            "m365_throttled": 429,
            "m365_auth_required": 502,
            "m365_insufficient_permission": 403,
            "m365_unavailable": 503,
            "m365_pagination_failed": 502,
        }.get(error.code, 502)
        detail: dict[str, object] = {"code": error.code, "message": error.message}
        if error.retry_after is not None:
            detail["retry_after_seconds"] = max(0, round(error.retry_after))
        raise HTTPException(status_code=status_code, detail=detail)

    def _m365_response(
        read_type: str,
        response: M365GraphReadResponse,
    ) -> dict[str, object]:
        _raise_m365_graph_http_error(response.error)
        _audit_m365_read(read_type, response.result.status, response.result.count)
        return {
            "result": asdict(response.result),
            "items": [asdict(item) for item in response.items],
            "next_cursor": response.next_cursor,
        }

    def _audit_m365_read(read_type: str, status: str, count: int) -> None:
        store.add_audit_event("m365.read", read_type, f"{status} count={count}")

    def _m365_group_response(
        read_type: str,
        response: M365GraphGroupReadResponse,
    ) -> dict[str, object]:
        _raise_m365_graph_http_error(response.error)
        _audit_m365_read(read_type, response.result.status, response.result.count)
        return {
            "result": asdict(response.result),
            "items": [asdict(item) for item in response.items],
            "next_cursor": response.next_cursor,
        }

    def _m365_license_response(
        read_type: str,
        response: M365GraphLicenseReadResponse,
    ) -> dict[str, object]:
        _raise_m365_graph_http_error(response.error)
        _audit_m365_read(read_type, response.result.status, response.result.count)
        return {
            "result": asdict(response.result),
            "items": [asdict(item) for item in response.items],
            "next_cursor": response.next_cursor,
        }

    def _m365_license_detail_response(
        read_type: str,
        response: M365GraphLicenseDetailReadResponse,
    ) -> dict[str, object]:
        _raise_m365_graph_http_error(response.error)
        _audit_m365_read(read_type, response.result.status, response.result.count)
        return {
            "result": asdict(response.result),
            "items": [asdict(item) for item in response.items],
            "next_cursor": response.next_cursor,
        }

    def _m365_mail_folder_response(
        read_type: str,
        response: M365GraphMailFolderReadResponse,
    ) -> dict[str, object]:
        _raise_m365_graph_http_error(response.error)
        _audit_m365_read(read_type, response.result.status, response.result.count)
        return {
            "result": asdict(response.result),
            "items": [asdict(item) for item in response.items],
            "next_cursor": response.next_cursor,
        }

    def _m365_mail_message_response(
        read_type: str,
        response: M365GraphMailMessageReadResponse,
    ) -> dict[str, object]:
        _raise_m365_graph_http_error(response.error)
        _audit_m365_read(read_type, response.result.status, response.result.count)
        return {
            "result": asdict(response.result),
            "items": [asdict(item) for item in response.items],
            "next_cursor": response.next_cursor,
        }

    def _m365_managed_device_response(
        read_type: str,
        response: M365GraphManagedDeviceReadResponse,
    ) -> dict[str, object]:
        _raise_m365_graph_http_error(response.error)
        _audit_m365_read(read_type, response.result.status, response.result.count)
        return {
            "result": asdict(response.result),
            "items": [asdict(item) for item in response.items],
            "next_cursor": response.next_cursor,
        }

    @router.get("/connectors/m365/health")
    @limiter.limit(active_settings.rate_limit_connector)
    def m365_health(request: Request, _: ViewerAccess) -> dict[str, object]:
        result = m365_client.health()
        _audit_m365_read("health", result.status, result.count)
        return asdict(result)

    @router.get("/connectors/m365/users")
    @limiter.limit(active_settings.rate_limit_connector)
    def m365_users(
        request: Request,
        context: ViewerAccess,
        identity: str | None = None,
        cursor: str | None = None,
        page_size: int | None = None,
        client_id: str | None = None,
    ) -> dict[str, object]:
        client = cast(
            M365GraphClient,
            _connector_read_client(request, context, "m365", m365_client, requested_client_id=client_id),
        )
        response = client.list_users(
            identity=identity,
            cursor=cursor,
            page_size=(page_size if page_size is not None else active_settings.m365_page_size),
        )
        return _m365_response("users.list", response)

    @router.get("/connectors/m365/groups")
    @limiter.limit(active_settings.rate_limit_connector)
    def m365_groups(
        request: Request,
        context: ViewerAccess,
        identity: str | None = None,
        cursor: str | None = None,
        page_size: int | None = None,
        client_id: str | None = None,
    ) -> dict[str, object]:
        client = cast(
            M365GraphClient,
            _connector_read_client(request, context, "m365", m365_client, requested_client_id=client_id),
        )
        response = client.list_groups(
            identity=identity,
            cursor=cursor,
            page_size=(page_size if page_size is not None else active_settings.m365_page_size),
        )
        return _m365_group_response("groups.list", response)

    @router.get("/connectors/m365/licenses")
    @limiter.limit(active_settings.rate_limit_connector)
    def m365_licenses(
        request: Request,
        context: ViewerAccess,
        cursor: str | None = None,
        client_id: str | None = None,
    ) -> dict[str, object]:
        client = cast(
            M365GraphClient,
            _connector_read_client(request, context, "m365", m365_client, requested_client_id=client_id),
        )
        response = client.list_subscribed_skus(cursor=cursor)
        return _m365_license_response("licenses.list", response)

    @router.get("/connectors/m365/users/license-details")
    @limiter.limit(active_settings.rate_limit_connector)
    def m365_user_license_details(
        request: Request,
        context: ViewerAccess,
        identity: str,
        cursor: str | None = None,
        page_size: int | None = None,
        client_id: str | None = None,
    ) -> dict[str, object]:
        client = cast(
            M365GraphClient,
            _connector_read_client(request, context, "m365", m365_client, requested_client_id=client_id),
        )
        response = client.list_license_details(
            identity=identity,
            cursor=cursor,
            page_size=(page_size if page_size is not None else active_settings.m365_page_size),
        )
        return _m365_license_detail_response("users.license-details.list", response)

    @router.get("/connectors/m365/mail-folders")
    @limiter.limit(active_settings.rate_limit_connector)
    def m365_mail_folders(
        request: Request,
        context: ViewerAccess,
        identity: str | None = None,
        cursor: str | None = None,
        page_size: int | None = None,
        client_id: str | None = None,
    ) -> dict[str, object]:
        client = cast(
            M365GraphClient,
            _connector_read_client(request, context, "m365", m365_client, requested_client_id=client_id),
        )
        response = client.list_mail_folders(
            identity=identity,
            cursor=cursor,
            page_size=(page_size if page_size is not None else active_settings.m365_page_size),
        )
        return _m365_mail_folder_response("mail-folders.list", response)

    @router.get("/connectors/m365/mail-messages")
    @limiter.limit(active_settings.rate_limit_connector)
    def m365_mail_messages(
        request: Request,
        context: ViewerAccess,
        identity: str | None = None,
        folder_id: str | None = None,
        cursor: str | None = None,
        page_size: int | None = None,
        client_id: str | None = None,
    ) -> dict[str, object]:
        client = cast(
            M365GraphClient,
            _connector_read_client(request, context, "m365", m365_client, requested_client_id=client_id),
        )
        response = client.list_mail_messages(
            identity=identity,
            folder_id=folder_id,
            cursor=cursor,
            page_size=(page_size if page_size is not None else active_settings.m365_page_size),
        )
        return _m365_mail_message_response("mail-messages.list", response)

    @router.get("/connectors/m365/managed-devices")
    @limiter.limit(active_settings.rate_limit_connector)
    def m365_managed_devices(
        request: Request,
        context: ViewerAccess,
        cursor: str | None = None,
        page_size: int | None = None,
        client_id: str | None = None,
    ) -> dict[str, object]:
        client = cast(
            M365GraphClient,
            _connector_read_client(request, context, "m365", m365_client, requested_client_id=client_id),
        )
        response = client.list_managed_devices(
            cursor=cursor,
            page_size=(page_size if page_size is not None else active_settings.m365_page_size),
        )
        return _m365_managed_device_response("managed-devices.list", response)

    @router.get("/connectors/m365/teams")
    @limiter.limit(active_settings.rate_limit_connector)
    def m365_teams(
        request: Request,
        context: ViewerAccess,
        client_id: str | None = None,
    ) -> dict[str, object]:
        client = cast(
            TeamsGraphClient,
            _connector_read_client(
                request, context, "m365", teams_client, requested_client_id=client_id, m365_teams=True
            ),
        )
        response = client.list_teams(page_size=active_settings.m365_page_size)
        _audit_m365_read("teams.list", response.result.status, response.result.count)
        return {
            "result": asdict(response.result),
            "items": [asdict(item) for item in response.items],
            "next_cursor": response.next_cursor,
        }

    @router.get("/connectors/m365/teams/{team_id}/channels")
    @limiter.limit(active_settings.rate_limit_connector)
    def m365_team_channels(
        team_id: str,
        request: Request,
        context: ViewerAccess,
        cursor: str | None = None,
        page_size: int | None = None,
        client_id: str | None = None,
    ) -> dict[str, object]:
        client = cast(
            TeamsGraphClient,
            _connector_read_client(
                request, context, "m365", teams_client, requested_client_id=client_id, m365_teams=True
            ),
        )
        response = client.list_channels(
            team_id,
            cursor=cursor,
            page_size=(page_size if page_size is not None else active_settings.m365_page_size),
        )
        _audit_m365_read("teams.channels.list", response.result.status, response.result.count)
        return {
            "result": asdict(response.result),
            "items": [asdict(item) for item in response.items],
            "next_cursor": response.next_cursor,
        }

    @router.get("/connectors/m365/teams/{team_id}/channels/{channel_id}/messages")
    @limiter.limit(active_settings.rate_limit_connector)
    def m365_team_messages(
        team_id: str,
        channel_id: str,
        request: Request,
        context: ViewerAccess,
        cursor: str | None = None,
        page_size: int | None = None,
        client_id: str | None = None,
    ) -> dict[str, object]:
        client = cast(
            TeamsGraphClient,
            _connector_read_client(
                request, context, "m365", teams_client, requested_client_id=client_id, m365_teams=True
            ),
        )
        response = client.list_messages(
            team_id,
            channel_id,
            cursor=cursor,
            page_size=(page_size if page_size is not None else active_settings.m365_page_size),
        )
        _audit_m365_read("teams.messages.list", response.result.status, response.result.count)
        return {
            "result": asdict(response.result),
            "items": [asdict(item) for item in response.items],
            "next_cursor": response.next_cursor,
        }

    @router.post("/connectors/m365/teams/message-drafts", status_code=201)
    @limiter.limit(active_settings.rate_limit_connector)
    def draft_m365_team_message(
        payload: TeamsMessageDraftRequest,
        request: Request,
        context: AdminAccess,
    ) -> dict[str, object]:
        client_id = resolve_client_scope(context, payload.client_id).client_id
        if client_id is None:
            raise HTTPException(status_code=403, detail="authenticated principal has no tenant")
        approval = store.create_approval_request(
            subject_id=f"{client_id}:{payload.team_id}:{payload.channel_id}",
            action_type="teams.message.send",
            payload={
                "connector": "m365-teams",
                "action_type": "message.send",
                "client_id": client_id,
                "team_id": payload.team_id,
                "channel_id": payload.channel_id,
                "body": payload.body,
            },
            client_id=client_id,
        )
        return _approval_view(approval)

    @router.post("/connectors/m365/teams/approval-requests/{request_id}/execute")
    @limiter.limit(active_settings.rate_limit_connector)
    def execute_m365_team_message(
        request_id: int,
        request: Request,
        context: AdminAccess,
    ) -> dict[str, object]:
        approval = store.get_approval_request(request_id)
        if (
            approval is None
            or approval.action_type != "teams.message.send"
            or not _approval_scope_visible(context, approval)
        ):
            raise HTTPException(status_code=404, detail="Teams message approval request not found")
        if approval.status != "approved":
            raise HTTPException(status_code=409, detail="Teams message approval must be approved before execution")
        payload = _safe_json_object(approval.payload_json)
        team_id = payload.get("team_id")
        channel_id = payload.get("channel_id")
        body = payload.get("body")
        if not all(isinstance(value, str) for value in (team_id, channel_id, body)):
            raise HTTPException(status_code=409, detail="Teams message approval payload is invalid")
        result = teams_client.send_message(
            team_id=cast(str, team_id),
            channel_id=cast(str, channel_id),
            body=cast(str, body),
        )
        updated = store.record_approval_execution(
            request_id,
            status=result.status,
            message=result.message,
            result=asdict(result),
            audit_event_type="teams.message.send",
        )
        return _approval_view(updated)

    @router.post("/connectors/m365/users/drafts")
    @limiter.limit(active_settings.rate_limit_connector)
    def m365_user_draft(
        payload: M365UserDraftRequest,
        request: Request,
        context: AdminAccess,
    ) -> dict[str, object]:
        client_id = _required_client_id(context, payload.client_id)
        try:
            approval = draft_m365_user_creation(
                store,
                user_principal_name=payload.user_principal_name,
                display_name=payload.display_name,
                mail_nickname=payload.mail_nickname,
                temporary_vault_name=payload.temporary_vault_name,
                account_enabled=payload.account_enabled,
                force_change_password_next_sign_in=payload.force_change_password_next_sign_in,
                client_id=client_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _approval_view(approval)

    @router.post("/connectors/m365/users/disable-drafts")
    @limiter.limit(active_settings.rate_limit_connector)
    def m365_user_disable_draft(
        payload: M365UserDisableDraftRequest,
        request: Request,
        context: AdminAccess,
    ) -> dict[str, object]:
        client_id = _required_client_id(context, payload.client_id)
        try:
            approval = draft_m365_user_disable(
                store,
                user_identity=payload.user_identity,
                client_id=client_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _approval_view(approval)

    @router.post("/connectors/m365/users/password-reset-drafts")
    @limiter.limit(active_settings.rate_limit_connector)
    def m365_password_reset_draft(
        payload: M365PasswordResetDraftRequest,
        request: Request,
        context: AdminAccess,
    ) -> dict[str, object]:
        client_id = _required_client_id(context, payload.client_id)
        try:
            approval = draft_m365_password_reset(
                store,
                user_identity=payload.user_identity,
                temporary_vault_name=payload.temporary_vault_name,
                force_change_password_next_sign_in=payload.force_change_password_next_sign_in,
                force_change_password_next_sign_in_with_mfa=payload.force_change_password_next_sign_in_with_mfa,
                client_id=client_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _approval_view(approval)

    @router.post("/connectors/m365/users/authentication-method-drafts")
    @limiter.limit(active_settings.rate_limit_connector)
    def m365_authentication_method_delete_draft(
        payload: M365AuthenticationMethodDeleteDraftRequest,
        request: Request,
        context: AdminAccess,
    ) -> dict[str, object]:
        client_id = resolve_client_scope(context, payload.client_id).client_id
        try:
            approval = draft_m365_authentication_method_delete(
                store,
                user_identity=payload.user_identity,
                method_type=payload.method_type,
                method_id=payload.method_id,
                client_id=client_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _approval_view(approval)

    @router.post("/connectors/m365/groups/membership-drafts")
    @limiter.limit(active_settings.rate_limit_connector)
    def m365_group_membership_draft(
        payload: M365GroupMembershipDraftRequest,
        request: Request,
        context: AdminAccess,
    ) -> dict[str, object]:
        client_id = _required_client_id(context, payload.client_id)
        try:
            approval = draft_m365_group_membership(
                store,
                group_id=payload.group_id,
                user_id=payload.user_id,
                operation=payload.operation,
                client_id=client_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _approval_view(approval)

    @router.post("/connectors/m365/users/license-drafts")
    @limiter.limit(active_settings.rate_limit_connector)
    def m365_license_change_draft(
        payload: M365LicenseChangeDraftRequest,
        request: Request,
        context: AdminAccess,
    ) -> dict[str, object]:
        client_id = _required_client_id(context, payload.client_id)
        try:
            approval = draft_m365_license_change(
                store,
                user_id=payload.user_id,
                sku_ids=payload.sku_ids,
                operation=payload.operation,
                client_id=client_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _approval_view(approval)

    @router.post("/connectors/m365/users/session-revocation-drafts")
    @limiter.limit(active_settings.rate_limit_connector)
    def m365_session_revocation_draft(
        payload: M365SessionRevocationDraftRequest,
        request: Request,
        context: AdminAccess,
    ) -> dict[str, object]:
        client_id = _required_client_id(context, payload.client_id)
        try:
            approval = draft_m365_session_revocation(
                store,
                user_id=payload.user_id,
                client_id=client_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _approval_view(approval)

    @router.post("/connectors/m365/managed-devices/retire-drafts")
    @limiter.limit(active_settings.rate_limit_connector)
    def m365_managed_device_retirement_draft(
        payload: M365ManagedDeviceRetirementDraftRequest,
        request: Request,
        context: AdminAccess,
    ) -> dict[str, object]:
        client_id = _required_client_id(context, payload.client_id)
        try:
            approval = draft_m365_managed_device_retirement(
                store,
                device_id=payload.device_id,
                client_id=client_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _approval_view(approval)

    @router.post("/connectors/m365/managed-devices/sync-drafts")
    @limiter.limit(active_settings.rate_limit_connector)
    def m365_managed_device_sync_draft(
        payload: M365ManagedDeviceSyncDraftRequest,
        request: Request,
        context: AdminAccess,
    ) -> dict[str, object]:
        client_id = _required_client_id(context, payload.client_id)
        try:
            approval = draft_m365_managed_device_sync(
                store,
                device_id=payload.device_id,
                client_id=client_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _approval_view(approval)

    @router.post("/connectors/m365/managed-devices/reboot-drafts")
    @limiter.limit(active_settings.rate_limit_connector)
    def m365_managed_device_reboot_draft(
        payload: M365ManagedDeviceRebootDraftRequest,
        request: Request,
        context: AdminAccess,
    ) -> dict[str, object]:
        client_id = _required_client_id(context, payload.client_id)
        try:
            approval = draft_m365_managed_device_reboot(
                store,
                device_id=payload.device_id,
                client_id=client_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _approval_view(approval)

    @router.post("/connectors/m365/managed-devices/remote-lock-drafts")
    @limiter.limit(active_settings.rate_limit_connector)
    def m365_managed_device_remote_lock_draft(
        payload: M365ManagedDeviceRemoteLockDraftRequest,
        request: Request,
        context: AdminAccess,
    ) -> dict[str, object]:
        client_id = _required_client_id(context, payload.client_id)
        try:
            approval = draft_m365_managed_device_remote_lock(
                store,
                device_id=payload.device_id,
                client_id=client_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _approval_view(approval)

    @router.post("/connectors/m365/users/mailbox-settings-drafts")
    @limiter.limit(active_settings.rate_limit_connector)
    def m365_mailbox_settings_update_draft(
        payload: M365MailboxSettingsUpdateDraftRequest,
        request: Request,
        context: AdminAccess,
    ) -> dict[str, object]:
        client_id = _required_client_id(context, payload.client_id)
        try:
            approval = draft_m365_mailbox_settings_update(
                store,
                user_identity=payload.user_identity,
                settings=payload.settings,
                client_id=client_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _approval_view(approval)

    @router.post("/connectors/m365/mail-messages/move-drafts")
    @limiter.limit(active_settings.rate_limit_connector)
    def m365_mail_message_move_draft(
        payload: M365MailMessageMoveDraftRequest,
        request: Request,
        context: AdminAccess,
    ) -> dict[str, object]:
        client_id = _required_client_id(context, payload.client_id)
        try:
            approval = draft_m365_mail_message_move(
                store,
                user_identity=payload.user_identity,
                source_folder_id=payload.source_folder_id,
                message_id=payload.message_id,
                destination_folder_id=payload.destination_folder_id,
                client_id=client_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _approval_view(approval)

    @router.post("/connectors/m365/mail-messages/read-state-drafts")
    @limiter.limit(active_settings.rate_limit_connector)
    def m365_mail_message_read_state_draft(
        payload: M365MailMessageReadStateDraftRequest,
        request: Request,
        context: AdminAccess,
    ) -> dict[str, object]:
        client_id = _required_client_id(context, payload.client_id)
        try:
            approval = draft_m365_mail_message_read_state(
                store,
                user_identity=payload.user_identity,
                source_folder_id=payload.source_folder_id,
                message_id=payload.message_id,
                is_read=payload.is_read,
                client_id=client_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _approval_view(approval)

    @router.post("/connectors/m365/mail-messages/delete-drafts")
    @limiter.limit(active_settings.rate_limit_connector)
    def m365_mail_message_delete_draft(
        payload: M365MailMessageDeleteDraftRequest,
        request: Request,
        context: AdminAccess,
    ) -> dict[str, object]:
        client_id = _required_client_id(context, payload.client_id)
        try:
            approval = draft_m365_mail_message_delete(
                store,
                user_identity=payload.user_identity,
                source_folder_id=payload.source_folder_id,
                message_id=payload.message_id,
                client_id=client_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _approval_view(approval)

    @router.post("/connectors/m365/approval-requests/{request_id}/execute")
    @limiter.limit(active_settings.rate_limit_connector)
    def execute_m365_user_creation(
        request_id: int,
        request: Request,
        context: AdminAccess,
    ) -> dict[str, object]:
        try:
            approval = store.get_approval_request(request_id)
            if approval is None or not _approval_scope_visible(context, approval):
                raise KeyError(request_id)
            return _approval_view(
                execute_m365_approval_request(
                    store,
                    m365_client,
                    SecretVault(active_settings.vault_path),
                    request_id,
                )
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="approval request not found") from exc
        except PermissionError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except QuarantinedTicketError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return router


__all__ = ["create_m365_router"]
