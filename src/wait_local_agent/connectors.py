from __future__ import annotations

import json
from dataclasses import dataclass
from typing import cast
from uuid import UUID

from wait_local_agent.autotask import AutotaskClient
from wait_local_agent.config import Settings
from wait_local_agent.confluence import ConfluenceClient
from wait_local_agent.connectwise import ConnectWiseClient
from wait_local_agent.halopsa import HaloPSAClient
from wait_local_agent.hudu import HuduClient
from wait_local_agent.itglue import ItGlueClient
from wait_local_agent.m365_graph import (
    M365GraphAuthenticationMethodDeleteResult,
    M365GraphClient,
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
    M365GraphPasswordResetResult,
    M365GraphSessionRevokeResult,
    M365GraphUserCreateResult,
    M365GraphUserDisableResult,
)
from wait_local_agent.models import (
    ApprovalRequest,
    ConnectorStatus,
    ConnectorStatusValue,
    ConnectWiseTicketDraft,
    ConnectWiseWriteRequest,
    ConnectWiseWriteResult,
    HaloTicketDraft,
    HaloWriteRequest,
    HaloWriteResult,
    SecretRecord,
)
from wait_local_agent.notion import NotionClient
from wait_local_agent.reports.renderers import redact_value
from wait_local_agent.servicenow import ServiceNowClient
from wait_local_agent.sharepoint import SharePointClient
from wait_local_agent.store import Store
from wait_local_agent.syncro import SyncroClient
from wait_local_agent.vault import SecretVault, SecretVaultError

HALOPSA_ACTION_TYPES = {
    "add_note",
    "draft_response",
    "update_status",
    "assign_technician",
    "update_ticket_fields",
}

CONNECTWISE_ACTION_TYPES = {
    "update_status",
    "assign_technician",
    "update_ticket_fields",
}

SERVICENOW_ACTION_TYPES = {
    "add_work_note",
    "update_state",
    "assign_incident",
    "update_resolution",
}

AUTOTASK_ACTION_TYPES = {
    "add_note",
    "add_time_entry",
    "update_status",
    "update_resolution",
    "assign_technician",
}

SYNCRO_ACTION_TYPES = {"add_note"}

M365_USER_CREATE_ACTION = "users.create"
M365_USER_DISABLE_ACTION = "users.disable"
M365_PASSWORD_RESET_ACTION = "users.password-reset"  # nosec B105 - action identifier, not a credential.
M365_AUTHENTICATION_METHOD_DELETE_ACTION = "users.authentication-methods.remove"
M365_GROUP_MEMBERSHIP_ADD_ACTION = "groups.members.add"
M365_GROUP_MEMBERSHIP_REMOVE_ACTION = "groups.members.remove"
M365_LICENSE_ADD_ACTION = "users.licenses.add"
M365_LICENSE_REMOVE_ACTION = "users.licenses.remove"
M365_SESSION_REVOKE_ACTION = "users.sessions.revoke"
M365_DEVICE_RETIRE_ACTION = "managed-devices.retire"
M365_DEVICE_SYNC_ACTION = "managed-devices.sync"
M365_DEVICE_REBOOT_ACTION = "managed-devices.reboot"
M365_DEVICE_REMOTE_LOCK_ACTION = "managed-devices.remote-lock"
M365_MAILBOX_SETTINGS_UPDATE_ACTION = "users.mailbox-settings.update"
M365_MAIL_MESSAGE_MOVE_ACTION = "mail-messages.move"
M365_MAIL_MESSAGE_READ_STATE_ACTION = "mail-messages.read-state"
M365_MAIL_MESSAGE_DELETE_ACTION = "mail-messages.delete"
M365_USER_CREATE_FIELDS = {
    "account_enabled",
    "display_name",
    "force_change_next_sign_in",
    "mail_nickname",
    "temporary_vault_name",
    "user_principal_name",
}
M365_PASSWORD_RESET_FIELDS = {
    "force_change_next_sign_in",
    "force_change_next_sign_in_with_mfa",
    "temporary_vault_name",
    "user_identity",
}
M365_AUTHENTICATION_METHOD_DELETE_FIELDS = {"method_id", "method_type", "user_identity"}


@dataclass(frozen=True)
class ConnectorValidationResult:
    connector: str
    passed: bool
    layer: str
    message: str


def list_connector_statuses(settings: Settings) -> list[ConnectorStatus]:
    halopsa_configured = bool(
        settings.halopsa_base_url
        and settings.halopsa_client_id
        and settings.halopsa_client_secret
        and settings.halopsa_tenant
    )
    halopsa_status: ConnectorStatusValue = "not_configured"
    if halopsa_configured:
        halopsa_status = "configured" if settings.allow_http_probing else "blocked"
    hudu_configured = bool(settings.hudu_base_url and settings.hudu_api_key)
    hudu_status: ConnectorStatusValue = "not_configured"
    if hudu_configured:
        hudu_status = "configured" if settings.allow_http_probing else "blocked"
    itglue_configured = bool(settings.itglue_base_url and settings.itglue_api_key)
    itglue_status: ConnectorStatusValue = "not_configured"
    if itglue_configured:
        itglue_status = "configured" if settings.allow_http_probing else "blocked"
    confluence_configured = bool(
        settings.confluence_base_url
        and settings.confluence_email
        and settings.confluence_api_token
    )
    confluence_status: ConnectorStatusValue = "not_configured"
    if confluence_configured:
        confluence_status = "configured" if settings.allow_http_probing else "blocked"
    notion_configured = bool(
        settings.notion_api_token and settings.notion_client_page_map_json
    )
    notion_status: ConnectorStatusValue = "not_configured"
    if notion_configured:
        notion_status = "configured" if settings.allow_http_probing else "blocked"
    sharepoint_configured = bool(
        settings.sharepoint_base_url and settings.sharepoint_access_token
    )
    sharepoint_status: ConnectorStatusValue = "not_configured"
    if sharepoint_configured:
        sharepoint_status = "configured" if settings.allow_http_probing else "blocked"
    connectwise_configured = bool(
        settings.connectwise_base_url
        and settings.connectwise_company
        and settings.connectwise_public_key
        and settings.connectwise_private_key
        and settings.connectwise_client_id
    )
    connectwise_status: ConnectorStatusValue = "not_configured"
    if connectwise_configured:
        connectwise_status = "configured" if settings.allow_http_probing else "blocked"
    syncro_configured = bool(settings.syncro_base_url and settings.syncro_api_token)
    syncro_status: ConnectorStatusValue = "not_configured"
    if syncro_configured:
        syncro_status = "configured" if settings.allow_http_probing else "blocked"
    servicenow_configured = bool(
        settings.servicenow_base_url
        and settings.servicenow_username
        and settings.servicenow_password
    )
    servicenow_status: ConnectorStatusValue = "not_configured"
    if servicenow_configured:
        servicenow_status = "configured" if settings.allow_http_probing else "blocked"
    autotask_configured = bool(
        settings.autotask_base_url
        and settings.autotask_username
        and settings.autotask_secret
        and settings.autotask_integration_code
    )
    autotask_status: ConnectorStatusValue = "not_configured"
    if autotask_configured:
        autotask_status = "configured" if settings.allow_http_probing else "blocked"
    m365_configured = bool(settings.m365_graph_base_url and settings.m365_access_token)
    m365_status: ConnectorStatusValue = "not_configured"
    if m365_configured:
        m365_status = "configured" if settings.allow_http_probing else "blocked"
    ninjaone_configured = bool(
        settings.ninjaone_base_url
        and settings.ninjaone_access_token
        and settings.ninjaone_organization_map_json
    )
    ninjaone_status: ConnectorStatusValue = "not_configured"
    if ninjaone_configured:
        ninjaone_status = "configured" if settings.allow_http_probing else "blocked"
    datto_rmm_configured = bool(
        settings.datto_rmm_base_url
        and settings.datto_rmm_access_token
        and settings.datto_rmm_site_map_json
    )
    datto_rmm_status: ConnectorStatusValue = "not_configured"
    if datto_rmm_configured:
        datto_rmm_status = "configured" if settings.allow_http_probing else "blocked"
    ncentral_configured = bool(
        settings.ncentral_base_url
        and settings.ncentral_access_token
        and settings.ncentral_org_unit_map_json
    )
    ncentral_status: ConnectorStatusValue = "not_configured"
    if ncentral_configured:
        ncentral_status = "configured" if settings.allow_http_probing else "blocked"
    kaseya_rmm_configured = bool(
        settings.kaseya_rmm_base_url
        and settings.kaseya_rmm_token_id
        and settings.kaseya_rmm_token_secret
        and settings.kaseya_rmm_organization_map_json
    )
    kaseya_rmm_status: ConnectorStatusValue = "not_configured"
    if kaseya_rmm_configured:
        kaseya_rmm_status = "configured" if settings.allow_http_probing else "blocked"
    screenconnect_configured = bool(
        settings.screenconnect_base_url
        and settings.screenconnect_extension_id
        and settings.screenconnect_auth_secret
        and settings.screenconnect_origin
        and settings.screenconnect_client_sessions_map_json
    )
    screenconnect_status: ConnectorStatusValue = "not_configured"
    if screenconnect_configured:
        screenconnect_status = "configured" if settings.allow_http_probing else "blocked"
    rmm_configured_name = (
        "NinjaOne RMM"
        if ninjaone_configured
        else "Datto RMM"
        if datto_rmm_configured
        else "N-able N-central"
        if ncentral_configured
        else "Kaseya VSA X"
        if kaseya_rmm_configured
        else "ScreenConnect"
        if screenconnect_configured
        else "RMM"
    )
    rmm_status = (
        ninjaone_status
        if ninjaone_configured
        else datto_rmm_status
        if datto_rmm_configured
        else ncentral_status
        if ncentral_configured
        else kaseya_rmm_status
        if kaseya_rmm_configured
        else screenconnect_status
    )
    rmm_configuration_message = (
        (
            "NinjaOne is configured for tenant-scoped inventory and approval-gated script actions."
            if ninjaone_configured
            else (
                "Datto RMM is configured for tenant-scoped inventory, component "
                "metadata, and approval-gated quick jobs."
                if datto_rmm_configured
                else (
                    "N-able N-central is configured for tenant-scoped device, issue, and task "
                    "metadata plus approval-gated direct tasks and status lookup."
                    if ncentral_configured
                    else (
                        "Kaseya VSA X is configured for tenant-scoped read-only device and notification inventory."
                        if kaseya_rmm_configured
                        else (
                            "ScreenConnect is configured for tenant-scoped session/device "
                            "lookup and an optional local command catalog."
                        )
                    )
                )
            )
        )
        if rmm_status == "configured"
        else (
            "NinjaOne is configured; live RMM reads require WAIT_ALLOW_HTTP_PROBING."
            if ninjaone_configured
            else (
                "Datto RMM is configured; live RMM reads require WAIT_ALLOW_HTTP_PROBING."
                if datto_rmm_configured
                else (
                    "N-able N-central is configured; live RMM reads require WAIT_ALLOW_HTTP_PROBING."
                    if ncentral_configured
                    else (
                        "Kaseya VSA X is configured; live RMM reads require WAIT_ALLOW_HTTP_PROBING."
                        if kaseya_rmm_configured
                        else "ScreenConnect is configured; live RMM reads require WAIT_ALLOW_HTTP_PROBING."
                    )
                )
            )
        )
        if rmm_status == "blocked"
        else (
            "Set WAIT_NINJAONE_*, WAIT_DATTORMM_*, WAIT_NCENTRAL_*, WAIT_KASEYA_RMM_*, "
            "or WAIT_SCREENCONNECT_* values, including the "
            "explicit tenant map, "
            "to enable a vendor RMM adapter."
        )
    )
    return [
        ConnectorStatus(
            id="halopsa",
            kind="psa",
            name="HaloPSA",
            status=halopsa_status,
            message=(
                "HaloPSA credentials are configured; live writes still require approval."
                if halopsa_status == "configured"
                else (
                    "HaloPSA credentials are configured; live reads require "
                    "WAIT_ALLOW_HTTP_PROBING."
                )
                if halopsa_status == "blocked"
                else "Set WAIT_HALOPSA_* values to enable the first PSA read path."
            ),
            write_actions_enabled=settings.allow_write_actions and halopsa_configured,
            http_probing_enabled=settings.allow_http_probing,
        ),
        ConnectorStatus(
            id="hudu",
            kind="documentation",
            name="Hudu",
            status=hudu_status,
            message=(
                "Hudu credentials are configured for read-only documentation lookup."
                if hudu_status == "configured"
                else "Hudu credentials are configured; live reads require WAIT_ALLOW_HTTP_PROBING."
                if hudu_status == "blocked"
                else "Set WAIT_HUDU_BASE_URL and WAIT_HUDU_API_KEY to enable documentation reads."
            ),
            http_probing_enabled=settings.allow_http_probing,
        ),
        ConnectorStatus(
            id="itglue",
            kind="documentation",
            name="IT Glue",
            status=itglue_status,
            message=(
                "IT Glue credentials are configured for read-only documentation lookup."
                if itglue_status == "configured"
                else "IT Glue credentials are configured; live reads require WAIT_ALLOW_HTTP_PROBING."
                if itglue_status == "blocked"
                else "Set WAIT_ITGLUE_BASE_URL and WAIT_ITGLUE_API_KEY to enable IT Glue reads."
            ),
            http_probing_enabled=settings.allow_http_probing,
        ),
        ConnectorStatus(
            id="confluence",
            kind="documentation",
            name="Confluence Cloud",
            status=confluence_status,
            message=(
                "Confluence credentials are configured for read-only page lookup."
                if confluence_status == "configured"
                else "Confluence credentials are configured; live reads require WAIT_ALLOW_HTTP_PROBING."
                if confluence_status == "blocked"
                else (
                    "Set WAIT_CONFLUENCE_BASE_URL, WAIT_CONFLUENCE_EMAIL, and "
                    "WAIT_CONFLUENCE_API_TOKEN to enable Confluence reads."
                )
            ),
            http_probing_enabled=settings.allow_http_probing,
        ),
        ConnectorStatus(
            id="notion",
            kind="documentation",
            name="Notion",
            status=notion_status,
            message=(
                "Notion is configured for tenant-scoped read-only page search and markdown retrieval."
                if notion_status == "configured"
                else "Notion is configured; live reads require WAIT_ALLOW_HTTP_PROBING."
                if notion_status == "blocked"
                else (
                "Set WAIT_NOTION_API_TOKEN and WAIT_NOTION_CLIENT_PAGE_MAP_JSON "
                "to enable Notion page reads."
                )
            ),
            http_probing_enabled=settings.allow_http_probing,
        ),
        ConnectorStatus(
            id="sharepoint",
            kind="documentation",
            name="SharePoint",
            status=sharepoint_status,
            message=(
                "SharePoint credentials are configured for read-only site and document lookup."
                if sharepoint_status == "configured"
                else "SharePoint credentials are configured; live reads require WAIT_ALLOW_HTTP_PROBING."
                if sharepoint_status == "blocked"
                else (
                    "Set WAIT_SHAREPOINT_BASE_URL and WAIT_SHAREPOINT_ACCESS_TOKEN "
                    "to enable SharePoint reads."
                )
            ),
            http_probing_enabled=settings.allow_http_probing,
        ),
        ConnectorStatus(
            id="connectwise",
            kind="psa",
            name="ConnectWise PSA",
            status=connectwise_status,
            message=(
                "ConnectWise PSA credentials are configured for ticket/company lookup and "
                "approval-gated ticket updates."
                if connectwise_status == "configured"
                else "ConnectWise PSA credentials are configured; live reads require WAIT_ALLOW_HTTP_PROBING."
                if connectwise_status == "blocked"
                else "Set WAIT_CONNECTWISE_* values to enable ConnectWise PSA reads and approved ticket updates."
            ),
            write_actions_enabled=settings.allow_write_actions and connectwise_configured,
            http_probing_enabled=settings.allow_http_probing,
        ),
        ConnectorStatus(
            id="syncro",
            kind="psa",
            name="Syncro",
            status=syncro_status,
            message=(
                "Syncro credentials are configured for read-only ticket and customer lookup."
                if syncro_status == "configured"
                else "Syncro credentials are configured; live reads require WAIT_ALLOW_HTTP_PROBING."
                if syncro_status == "blocked"
                else "Set WAIT_SYNCRO_BASE_URL and WAIT_SYNCRO_API_TOKEN to enable Syncro reads."
            ),
            http_probing_enabled=settings.allow_http_probing,
        ),
        ConnectorStatus(
            id="servicenow",
            kind="psa",
            name="ServiceNow",
            status=servicenow_status,
            message=(
                "ServiceNow credentials are configured for incident/company lookup and "
                "approval-gated work-note/state updates."
                if servicenow_status == "configured"
                else "ServiceNow credentials are configured; live reads require WAIT_ALLOW_HTTP_PROBING "
                "and writes also require WAIT_ALLOW_WRITE_ACTIONS."
                if servicenow_status == "blocked"
                else (
                    "Set WAIT_SERVICENOW_BASE_URL, WAIT_SERVICENOW_USERNAME, and "
                    "WAIT_SERVICENOW_PASSWORD to enable ServiceNow reads and approved writes."
                )
            ),
            write_actions_enabled=settings.allow_write_actions and servicenow_configured,
            http_probing_enabled=settings.allow_http_probing,
        ),
        ConnectorStatus(
            id="autotask",
            kind="psa",
            name="Autotask PSA",
            status=autotask_status,
            message=(
                "Autotask credentials are configured for ticket/company lookup and "
                "approval-gated ticket-note, status, and resolution updates."
                if autotask_status == "configured"
                else "Autotask credentials are configured; live reads require WAIT_ALLOW_HTTP_PROBING "
                "and writes also require WAIT_ALLOW_WRITE_ACTIONS."
                if autotask_status == "blocked"
                else "Set WAIT_AUTOTASK_* values to enable Autotask PSA reads and approved ticket actions."
            ),
            write_actions_enabled=settings.allow_write_actions and autotask_configured,
            http_probing_enabled=settings.allow_http_probing,
        ),
        ConnectorStatus(
            id="m365",
            kind="m365",
            name="Microsoft 365 / Entra",
            status=m365_status,
            message=(
                "Microsoft Graph is configured for bounded context lookup plus "
                "approved user lifecycle and group-membership writes."
                if m365_status == "configured"
                else "Microsoft Graph credentials are configured; live reads require WAIT_ALLOW_HTTP_PROBING."
                if m365_status == "blocked"
                else (
                    "Set WAIT_M365_GRAPH_BASE_URL and WAIT_M365_ACCESS_TOKEN to enable "
                    "live identity, group, license, mailbox-folder, and Intune managed-device context."
                )
            ),
            http_probing_enabled=settings.allow_http_probing,
        ),
        ConnectorStatus(
            id="rmm",
            kind="rmm",
            name=rmm_configured_name,
            status=rmm_status,
            message=rmm_configuration_message,
            write_actions_enabled=settings.allow_write_actions
            and (ninjaone_configured or datto_rmm_configured),
            http_probing_enabled=settings.allow_http_probing,
        ),
    ]


def list_secret_records(settings: Settings) -> list[SecretRecord]:
    return [
        SecretRecord("WAIT_HALOPSA_BASE_URL", bool(settings.halopsa_base_url), "halopsa"),
        SecretRecord("WAIT_HALOPSA_CLIENT_ID", bool(settings.halopsa_client_id), "halopsa"),
        SecretRecord(
            "WAIT_HALOPSA_CLIENT_SECRET",
            bool(settings.halopsa_client_secret),
            "halopsa",
        ),
        SecretRecord("WAIT_HALOPSA_TENANT", bool(settings.halopsa_tenant), "halopsa"),
        SecretRecord("WAIT_HALOPSA_TOKEN_URL", bool(settings.halopsa_token_url), "halopsa"),
        SecretRecord(
            "WAIT_HALOPSA_TICKET_WRITE_ENDPOINT",
            bool(settings.halopsa_ticket_write_endpoint),
            "halopsa",
        ),
        SecretRecord(
            "WAIT_HALOPSA_ACTION_WRITE_ENDPOINT",
            bool(settings.halopsa_action_write_endpoint),
            "halopsa",
        ),
        SecretRecord("WAIT_HUDU_BASE_URL", bool(settings.hudu_base_url), "hudu"),
        SecretRecord("WAIT_HUDU_API_KEY", bool(settings.hudu_api_key), "hudu"),
        SecretRecord("WAIT_HUDU_PAGE_SIZE", bool(settings.hudu_page_size), "hudu"),
        SecretRecord("WAIT_ITGLUE_BASE_URL", bool(settings.itglue_base_url), "itglue"),
        SecretRecord("WAIT_ITGLUE_API_KEY", bool(settings.itglue_api_key), "itglue"),
        SecretRecord("WAIT_ITGLUE_PAGE_SIZE", bool(settings.itglue_page_size), "itglue"),
        SecretRecord("WAIT_CONFLUENCE_BASE_URL", bool(settings.confluence_base_url), "confluence"),
        SecretRecord("WAIT_CONFLUENCE_EMAIL", bool(settings.confluence_email), "confluence"),
        SecretRecord("WAIT_CONFLUENCE_API_TOKEN", bool(settings.confluence_api_token), "confluence"),
        SecretRecord("WAIT_CONFLUENCE_PAGE_SIZE", bool(settings.confluence_page_size), "confluence"),
        SecretRecord("WAIT_NOTION_BASE_URL", bool(settings.notion_base_url), "notion"),
        SecretRecord("WAIT_NOTION_API_TOKEN", bool(settings.notion_api_token), "notion"),
        SecretRecord("WAIT_NOTION_VERSION", bool(settings.notion_version), "notion"),
        SecretRecord("WAIT_NOTION_PAGE_SIZE", bool(settings.notion_page_size), "notion"),
        SecretRecord(
            "WAIT_NOTION_CLIENT_PAGE_MAP_JSON",
            bool(settings.notion_client_page_map_json),
            "notion",
        ),
        SecretRecord(
            "WAIT_NOTION_CLIENT_DATA_SOURCE_MAP_JSON",
            bool(settings.notion_client_data_source_map_json),
            "notion",
        ),
        SecretRecord("WAIT_SHAREPOINT_BASE_URL", bool(settings.sharepoint_base_url), "sharepoint"),
        SecretRecord(
            "WAIT_SHAREPOINT_ACCESS_TOKEN",
            bool(settings.sharepoint_access_token),
            "sharepoint",
        ),
        SecretRecord("WAIT_SHAREPOINT_PAGE_SIZE", bool(settings.sharepoint_page_size), "sharepoint"),
        SecretRecord(
            "WAIT_M365_GRAPH_BASE_URL",
            bool(settings.m365_graph_base_url),
            "m365",
        ),
        SecretRecord("WAIT_M365_ACCESS_TOKEN", bool(settings.m365_access_token), "m365"),
        SecretRecord("WAIT_M365_PAGE_SIZE", bool(settings.m365_page_size), "m365"),
        SecretRecord("WAIT_CONNECTWISE_BASE_URL", bool(settings.connectwise_base_url), "connectwise"),
        SecretRecord("WAIT_CONNECTWISE_COMPANY", bool(settings.connectwise_company), "connectwise"),
        SecretRecord("WAIT_CONNECTWISE_PUBLIC_KEY", bool(settings.connectwise_public_key), "connectwise"),
        SecretRecord("WAIT_CONNECTWISE_PRIVATE_KEY", bool(settings.connectwise_private_key), "connectwise"),
        SecretRecord("WAIT_CONNECTWISE_CLIENT_ID", bool(settings.connectwise_client_id), "connectwise"),
        SecretRecord("WAIT_CONNECTWISE_API_VERSION", bool(settings.connectwise_api_version), "connectwise"),
        SecretRecord("WAIT_CONNECTWISE_PAGE_SIZE", bool(settings.connectwise_page_size), "connectwise"),
        SecretRecord("WAIT_SYNCRO_BASE_URL", bool(settings.syncro_base_url), "syncro"),
        SecretRecord("WAIT_SYNCRO_API_TOKEN", bool(settings.syncro_api_token), "syncro"),
        SecretRecord("WAIT_SERVICENOW_BASE_URL", bool(settings.servicenow_base_url), "servicenow"),
        SecretRecord("WAIT_SERVICENOW_USERNAME", bool(settings.servicenow_username), "servicenow"),
        SecretRecord("WAIT_SERVICENOW_PASSWORD", bool(settings.servicenow_password), "servicenow"),
        SecretRecord("WAIT_SERVICENOW_API_VERSION", bool(settings.servicenow_api_version), "servicenow"),
        SecretRecord("WAIT_SERVICENOW_PAGE_SIZE", bool(settings.servicenow_page_size), "servicenow"),
        SecretRecord("WAIT_AUTOTASK_BASE_URL", bool(settings.autotask_base_url), "autotask"),
        SecretRecord("WAIT_AUTOTASK_USERNAME", bool(settings.autotask_username), "autotask"),
        SecretRecord("WAIT_AUTOTASK_SECRET", bool(settings.autotask_secret), "autotask"),
        SecretRecord(
            "WAIT_AUTOTASK_INTEGRATION_CODE",
            bool(settings.autotask_integration_code),
            "autotask",
        ),
        SecretRecord("WAIT_AUTOTASK_PAGE_SIZE", bool(settings.autotask_page_size), "autotask"),
        SecretRecord("WAIT_NINJAONE_BASE_URL", bool(settings.ninjaone_base_url), "ninjaone"),
        SecretRecord(
            "WAIT_NINJAONE_ACCESS_TOKEN",
            bool(settings.ninjaone_access_token),
            "ninjaone",
        ),
        SecretRecord(
            "WAIT_NINJAONE_ORGANIZATION_MAP_JSON",
            bool(settings.ninjaone_organization_map_json),
            "ninjaone",
        ),
        SecretRecord("WAIT_NINJAONE_PAGE_SIZE", bool(settings.ninjaone_page_size), "ninjaone"),
        SecretRecord("WAIT_DATTORMM_BASE_URL", bool(settings.datto_rmm_base_url), "dattormm"),
        SecretRecord(
            "WAIT_DATTORMM_ACCESS_TOKEN",
            bool(settings.datto_rmm_access_token),
            "dattormm",
        ),
        SecretRecord(
            "WAIT_DATTORMM_SITE_MAP_JSON",
            bool(settings.datto_rmm_site_map_json),
            "dattormm",
        ),
        SecretRecord("WAIT_DATTORMM_PAGE_SIZE", bool(settings.datto_rmm_page_size), "dattormm"),
        SecretRecord("WAIT_NCENTRAL_BASE_URL", bool(settings.ncentral_base_url), "ncentral"),
        SecretRecord(
            "WAIT_NCENTRAL_ACCESS_TOKEN",
            bool(settings.ncentral_access_token),
            "ncentral",
        ),
        SecretRecord(
            "WAIT_NCENTRAL_ORG_UNIT_MAP_JSON",
            bool(settings.ncentral_org_unit_map_json),
            "ncentral",
        ),
        SecretRecord("WAIT_NCENTRAL_PAGE_SIZE", bool(settings.ncentral_page_size), "ncentral"),
        SecretRecord("WAIT_KASEYA_RMM_BASE_URL", bool(settings.kaseya_rmm_base_url), "kaseya"),
        SecretRecord("WAIT_KASEYA_RMM_TOKEN_ID", bool(settings.kaseya_rmm_token_id), "kaseya"),
        SecretRecord(
            "WAIT_KASEYA_RMM_TOKEN_SECRET",
            bool(settings.kaseya_rmm_token_secret),
            "kaseya",
        ),
        SecretRecord(
            "WAIT_KASEYA_RMM_ORGANIZATION_MAP_JSON",
            bool(settings.kaseya_rmm_organization_map_json),
            "kaseya",
        ),
        SecretRecord("WAIT_KASEYA_RMM_PAGE_SIZE", bool(settings.kaseya_rmm_page_size), "kaseya"),
        SecretRecord("WAIT_SCREENCONNECT_BASE_URL", bool(settings.screenconnect_base_url), "screenconnect"),
        SecretRecord(
            "WAIT_SCREENCONNECT_EXTENSION_ID",
            bool(settings.screenconnect_extension_id),
            "screenconnect",
        ),
        SecretRecord(
            "WAIT_SCREENCONNECT_AUTH_SECRET",
            bool(settings.screenconnect_auth_secret),
            "screenconnect",
        ),
        SecretRecord("WAIT_SCREENCONNECT_ORIGIN", bool(settings.screenconnect_origin), "screenconnect"),
        SecretRecord(
            "WAIT_SCREENCONNECT_CLIENT_SESSIONS_MAP_JSON",
            bool(settings.screenconnect_client_sessions_map_json),
            "screenconnect",
        ),
        SecretRecord(
            "WAIT_SCREENCONNECT_SCRIPT_CATALOG_JSON",
            bool(settings.screenconnect_script_catalog_json),
            "screenconnect",
        ),
    ]


def validate_connector_credentials(
    connector: str,
    settings: Settings,
    *,
    halopsa_client: HaloPSAClient | None = None,
    hudu_client: HuduClient | None = None,
    connectwise_client: ConnectWiseClient | None = None,
    syncro_client: SyncroClient | None = None,
    servicenow_client: ServiceNowClient | None = None,
    autotask_client: AutotaskClient | None = None,
    itglue_client: ItGlueClient | None = None,
    confluence_client: ConfluenceClient | None = None,
    notion_client: NotionClient | None = None,
    sharepoint_client: SharePointClient | None = None,
    m365_client: M365GraphClient | None = None,
) -> ConnectorValidationResult:
    if connector == "halopsa":
        missing = [
            key
            for key, value in {
                "WAIT_HALOPSA_BASE_URL": settings.halopsa_base_url,
                "WAIT_HALOPSA_CLIENT_ID": settings.halopsa_client_id,
                "WAIT_HALOPSA_CLIENT_SECRET": settings.halopsa_client_secret,
                "WAIT_HALOPSA_TENANT": settings.halopsa_tenant,
            }.items()
            if not value
        ]
        if missing:
            return ConnectorValidationResult(
                connector,
                False,
                "config",
                f"HaloPSA credentials are incomplete: {', '.join(missing)}.",
            )
        result = (halopsa_client or HaloPSAClient(settings)).health()
    elif connector == "hudu":
        missing = [
            key
            for key, value in {
                "WAIT_HUDU_BASE_URL": settings.hudu_base_url,
                "WAIT_HUDU_API_KEY": settings.hudu_api_key,
            }.items()
            if not value
        ]
        if missing:
            return ConnectorValidationResult(
                connector,
                False,
                "config",
                f"Hudu credentials are incomplete: {', '.join(missing)}.",
            )
        result = (hudu_client or HuduClient(settings)).health()
    elif connector == "itglue":
        missing = [
            key
            for key, value in {
                "WAIT_ITGLUE_BASE_URL": settings.itglue_base_url,
                "WAIT_ITGLUE_API_KEY": settings.itglue_api_key,
            }.items()
            if not value
        ]
        if missing:
            return ConnectorValidationResult(
                connector,
                False,
                "config",
                f"IT Glue credentials are incomplete: {', '.join(missing)}.",
            )
        result = (itglue_client or ItGlueClient(settings)).health()
    elif connector == "confluence":
        missing = [
            key
            for key, value in {
                "WAIT_CONFLUENCE_BASE_URL": settings.confluence_base_url,
                "WAIT_CONFLUENCE_EMAIL": settings.confluence_email,
                "WAIT_CONFLUENCE_API_TOKEN": settings.confluence_api_token,
            }.items()
            if not value
        ]
        if missing:
            return ConnectorValidationResult(
                connector,
                False,
                "config",
                f"Confluence credentials are incomplete: {', '.join(missing)}.",
            )
        result = (confluence_client or ConfluenceClient(settings)).health()
    elif connector == "notion":
        missing = [
            key
            for key, value in {
                "WAIT_NOTION_API_TOKEN": settings.notion_api_token,
                "WAIT_NOTION_CLIENT_PAGE_MAP_JSON": settings.notion_client_page_map_json,
            }.items()
            if not value
        ]
        if missing:
            return ConnectorValidationResult(
                connector,
                False,
                "config",
                f"Notion credentials are incomplete: {', '.join(missing)}.",
            )
        result = (notion_client or NotionClient(settings)).health()
    elif connector == "sharepoint":
        missing = [
            key
            for key, value in {
                "WAIT_SHAREPOINT_BASE_URL": settings.sharepoint_base_url,
                "WAIT_SHAREPOINT_ACCESS_TOKEN": settings.sharepoint_access_token,
            }.items()
            if not value
        ]
        if missing:
            return ConnectorValidationResult(
                connector,
                False,
                "config",
                f"SharePoint credentials are incomplete: {', '.join(missing)}.",
            )
        result = (sharepoint_client or SharePointClient(settings)).health()
    elif connector == "m365":
        missing = [
            key
            for key, value in {
                "WAIT_M365_GRAPH_BASE_URL": settings.m365_graph_base_url,
                "WAIT_M365_ACCESS_TOKEN": settings.m365_access_token,
            }.items()
            if not value
        ]
        if missing:
            return ConnectorValidationResult(
                connector,
                False,
                "config",
                f"Microsoft Graph credentials are incomplete: {', '.join(missing)}.",
            )
        result = (m365_client or M365GraphClient(settings)).health()
    elif connector == "connectwise":
        missing = [
            key
            for key, value in {
                "WAIT_CONNECTWISE_BASE_URL": settings.connectwise_base_url,
                "WAIT_CONNECTWISE_COMPANY": settings.connectwise_company,
                "WAIT_CONNECTWISE_PUBLIC_KEY": settings.connectwise_public_key,
                "WAIT_CONNECTWISE_PRIVATE_KEY": settings.connectwise_private_key,
                "WAIT_CONNECTWISE_CLIENT_ID": settings.connectwise_client_id,
            }.items()
            if not value
        ]
        if missing:
            return ConnectorValidationResult(
                connector,
                False,
                "config",
                f"ConnectWise PSA credentials are incomplete: {', '.join(missing)}.",
            )
        result = (connectwise_client or ConnectWiseClient(settings)).health()
    elif connector == "syncro":
        missing = [
            key
            for key, value in {
                "WAIT_SYNCRO_BASE_URL": settings.syncro_base_url,
                "WAIT_SYNCRO_API_TOKEN": settings.syncro_api_token,
            }.items()
            if not value
        ]
        if missing:
            return ConnectorValidationResult(
                connector,
                False,
                "config",
                f"Syncro credentials are incomplete: {', '.join(missing)}.",
            )
        result = (syncro_client or SyncroClient(settings)).health()
    elif connector == "servicenow":
        missing = [
            key
            for key, value in {
                "WAIT_SERVICENOW_BASE_URL": settings.servicenow_base_url,
                "WAIT_SERVICENOW_USERNAME": settings.servicenow_username,
                "WAIT_SERVICENOW_PASSWORD": settings.servicenow_password,
            }.items()
            if not value
        ]
        if missing:
            return ConnectorValidationResult(
                connector,
                False,
                "config",
                f"ServiceNow credentials are incomplete: {', '.join(missing)}.",
            )
        result = (servicenow_client or ServiceNowClient(settings)).health()
    elif connector == "autotask":
        missing = [
            key
            for key, value in {
                "WAIT_AUTOTASK_BASE_URL": settings.autotask_base_url,
                "WAIT_AUTOTASK_USERNAME": settings.autotask_username,
                "WAIT_AUTOTASK_SECRET": settings.autotask_secret,
                "WAIT_AUTOTASK_INTEGRATION_CODE": settings.autotask_integration_code,
            }.items()
            if not value
        ]
        if missing:
            return ConnectorValidationResult(
                connector,
                False,
                "config",
                f"Autotask credentials are incomplete: {', '.join(missing)}.",
            )
        result = (autotask_client or AutotaskClient(settings)).health()
    else:
        raise ValueError(f"unsupported connector: {connector}")
    return _classify_validation_result(connector, result.status, result.message)


def draft_halopsa_ticket_action(
    store: Store,
    ticket_id: str,
    action_type: str,
    fields: dict[str, object],
    *,
    client_id: str | None = None,
) -> HaloTicketDraft:
    if action_type not in HALOPSA_ACTION_TYPES:
        raise ValueError(f"unsupported HaloPSA action type: {action_type}")
    payload: dict[str, object] = {
        "connector": "halopsa",
        "ticket_id": ticket_id,
        "action_type": action_type,
        "fields": fields,
    }
    approval = store.create_approval_request(
        ticket_id,
        f"halopsa.{action_type}",
        payload,
        client_id=client_id,
    )
    return HaloTicketDraft(
        ticket_id=ticket_id,
        action_type=action_type,
        payload_json=json.dumps(redact_value(payload), sort_keys=True),
        approval_required=True,
        status="pending",
        approval_request_id=approval.id,
    )


def draft_connectwise_ticket_action(
    store: Store,
    ticket_id: str,
    action_type: str,
    fields: dict[str, object],
    *,
    client_id: str | None = None,
) -> ConnectWiseTicketDraft:
    validate_connectwise_action_fields(action_type, fields)
    payload: dict[str, object] = {
        "connector": "connectwise",
        "ticket_id": ticket_id,
        "action_type": action_type,
        "fields": fields,
    }
    approval = store.create_approval_request(
        ticket_id,
        f"connectwise.{action_type}",
        payload,
        client_id=client_id,
    )
    return ConnectWiseTicketDraft(
        ticket_id=ticket_id,
        action_type=action_type,
        payload_json=json.dumps(redact_value(payload), sort_keys=True),
        approval_required=True,
        status="pending",
        approval_request_id=approval.id,
    )


def execute_halopsa_approval_request(
    store: Store,
    client: HaloPSAClient,
    request_id: int,
) -> ApprovalRequest:
    approval = store.get_approval_request(request_id)
    if approval is None:
        raise KeyError(request_id)
    if not approval.action_type.startswith("halopsa."):
        raise ValueError("approval request is not a HaloPSA action")
    if approval.status != "approved":
        raise PermissionError("HaloPSA writes require approved approval requests")
    if approval.execution_status == "succeeded":
        raise RuntimeError("HaloPSA approval request has already executed successfully")

    payload = json.loads(approval.payload_json)
    if not isinstance(payload, dict):
        raise ValueError("approval payload is malformed")
    if payload.get("connector") != "halopsa":
        raise ValueError("approval payload connector does not match HaloPSA")
    action_type = str(payload.get("action_type") or approval.action_type.removeprefix("halopsa."))
    if action_type not in HALOPSA_ACTION_TYPES:
        raise ValueError(f"unsupported HaloPSA action type: {action_type}")
    if approval.action_type != f"halopsa.{action_type}":
        raise ValueError("approval payload action does not match approval request")
    ticket_id = str(payload.get("ticket_id") or approval.subject_id)
    if ticket_id != approval.subject_id:
        raise ValueError("approval payload ticket does not match approval request")
    fields = payload.get("fields")
    if not isinstance(fields, dict):
        fields = {}
    result = client.execute_write(
        HaloWriteRequest(
            ticket_id=ticket_id,
            action_type=action_type,
            fields=fields,
            approval_request_id=approval.id,
        )
    )
    return store.record_approval_execution(
        request_id,
        status=result.status,
        message=result.message,
        result=sanitize_halopsa_write_result(result),
    )


def execute_connectwise_approval_request(
    store: Store,
    client: ConnectWiseClient,
    request_id: int,
) -> ApprovalRequest:
    approval = store.get_approval_request(request_id)
    if approval is None:
        raise KeyError(request_id)
    if not approval.action_type.startswith("connectwise."):
        raise ValueError("approval request is not a ConnectWise PSA action")
    if approval.status != "approved":
        raise PermissionError("ConnectWise PSA writes require approved approval requests")
    if approval.execution_status == "succeeded":
        raise RuntimeError("ConnectWise PSA approval request has already executed successfully")
    payload = json.loads(approval.payload_json)
    if not isinstance(payload, dict):
        raise ValueError("approval payload is malformed")
    if payload.get("connector") != "connectwise":
        raise ValueError("approval payload connector does not match ConnectWise PSA")
    action_type = str(payload.get("action_type") or approval.action_type.removeprefix("connectwise."))
    if action_type not in CONNECTWISE_ACTION_TYPES:
        raise ValueError(f"unsupported ConnectWise PSA action type: {action_type}")
    if approval.action_type != f"connectwise.{action_type}":
        raise ValueError("approval payload action does not match approval request")
    ticket_id = str(payload.get("ticket_id") or approval.subject_id)
    if ticket_id != approval.subject_id:
        raise ValueError("approval payload ticket does not match approval request")
    fields = payload.get("fields")
    if not isinstance(fields, dict):
        fields = {}
    validate_connectwise_action_fields(action_type, fields)
    result = client.execute_write(
        ConnectWiseWriteRequest(
            ticket_id=ticket_id,
            action_type=action_type,
            fields=fields,
            approval_request_id=approval.id,
        )
    )
    return store.record_approval_execution(
        request_id,
        status=result.status,
        message=result.message,
        result=sanitize_connectwise_write_result(result),
        audit_event_type="connectwise.write",
    )


def draft_m365_user_creation(
    store: Store,
    *,
    user_principal_name: str,
    display_name: str,
    mail_nickname: str,
    temporary_vault_name: str,
    account_enabled: bool = True,
    force_change_password_next_sign_in: bool = True,
    client_id: str | None = None,
) -> ApprovalRequest:
    payload: dict[str, object] = {
        "connector": "m365",
        "action_type": M365_USER_CREATE_ACTION,
        "account_enabled": account_enabled,
        "display_name": display_name,
        "force_change_next_sign_in": force_change_password_next_sign_in,
        "mail_nickname": mail_nickname,
        "temporary_vault_name": temporary_vault_name,
        "user_principal_name": user_principal_name,
    }
    validate_m365_user_creation_payload(payload)
    return store.create_approval_request(
        f"m365-user:{user_principal_name.strip()}",
        f"m365.{M365_USER_CREATE_ACTION}",
        payload,
        client_id=client_id,
    )


def draft_m365_user_disable(
    store: Store,
    *,
    user_identity: str,
    client_id: str | None = None,
) -> ApprovalRequest:
    payload: dict[str, object] = {
        "connector": "m365",
        "action_type": M365_USER_DISABLE_ACTION,
        "user_identity": user_identity,
    }
    validate_m365_user_disable_payload(payload)
    return store.create_approval_request(
        f"m365-user:{user_identity.strip()}",
        f"m365.{M365_USER_DISABLE_ACTION}",
        payload,
        client_id=client_id,
    )


def draft_m365_password_reset(
    store: Store,
    *,
    user_identity: str,
    temporary_vault_name: str,
    force_change_password_next_sign_in: bool = True,
    force_change_password_next_sign_in_with_mfa: bool = False,
    client_id: str | None = None,
) -> ApprovalRequest:
    payload: dict[str, object] = {
        "connector": "m365",
        "action_type": M365_PASSWORD_RESET_ACTION,
        "force_change_next_sign_in": force_change_password_next_sign_in,
        "force_change_next_sign_in_with_mfa": force_change_password_next_sign_in_with_mfa,
        "temporary_vault_name": temporary_vault_name,
        "user_identity": user_identity,
    }
    validate_m365_password_reset_payload(payload)
    return store.create_approval_request(
        f"m365-user:{user_identity.strip()}:password-reset",
        f"m365.{M365_PASSWORD_RESET_ACTION}",
        payload,
        client_id=client_id,
    )


def draft_m365_authentication_method_delete(
    store: Store,
    *,
    user_identity: str,
    method_type: str,
    method_id: str,
    client_id: str | None = None,
) -> ApprovalRequest:
    payload: dict[str, object] = {
        "connector": "m365",
        "action_type": M365_AUTHENTICATION_METHOD_DELETE_ACTION,
        "method_id": method_id,
        "method_type": method_type,
        "user_identity": user_identity,
    }
    validate_m365_authentication_method_delete_payload(payload)
    return store.create_approval_request(
        f"m365-user:{user_identity.strip()}:authentication:{method_type}:{method_id}",
        f"m365.{M365_AUTHENTICATION_METHOD_DELETE_ACTION}",
        payload,
        client_id=client_id,
    )


def draft_m365_group_membership(
    store: Store,
    *,
    group_id: str,
    user_id: str,
    operation: str,
    client_id: str | None = None,
) -> ApprovalRequest:
    if operation not in {"add", "remove"}:
        raise ValueError("M365 group membership operation must be add or remove")
    action_type = (
        M365_GROUP_MEMBERSHIP_ADD_ACTION
        if operation == "add"
        else M365_GROUP_MEMBERSHIP_REMOVE_ACTION
    )
    payload: dict[str, object] = {
        "connector": "m365",
        "action_type": action_type,
        "group_id": group_id,
        "user_id": user_id,
    }
    validate_m365_group_membership_payload(payload)
    return store.create_approval_request(
        f"m365-group:{group_id.strip()}:member:{user_id.strip()}",
        f"m365.{action_type}",
        payload,
        client_id=client_id,
    )


def draft_m365_license_change(
    store: Store,
    *,
    user_id: str,
    sku_ids: list[str],
    operation: str,
    client_id: str | None = None,
) -> ApprovalRequest:
    if operation not in {"add", "remove"}:
        raise ValueError("M365 license operation must be add or remove")
    action_type = M365_LICENSE_ADD_ACTION if operation == "add" else M365_LICENSE_REMOVE_ACTION
    payload: dict[str, object] = {
        "connector": "m365",
        "action_type": action_type,
        "sku_ids": [_canonical_uuid(value, "sku_id") for value in sku_ids],
        "user_id": user_id,
    }
    validate_m365_license_change_payload(payload)
    return store.create_approval_request(
        f"m365-user:{user_id.strip()}:licenses",
        f"m365.{action_type}",
        payload,
        client_id=client_id,
    )


def draft_m365_session_revocation(
    store: Store,
    *,
    user_id: str,
    client_id: str | None = None,
) -> ApprovalRequest:
    payload: dict[str, object] = {
        "connector": "m365",
        "action_type": M365_SESSION_REVOKE_ACTION,
        "user_id": user_id,
    }
    validate_m365_session_revocation_payload(payload)
    return store.create_approval_request(
        f"m365-user:{user_id.strip()}:sessions",
        f"m365.{M365_SESSION_REVOKE_ACTION}",
        payload,
        client_id=client_id,
    )


def draft_m365_managed_device_retirement(
    store: Store,
    *,
    device_id: str,
    client_id: str | None = None,
) -> ApprovalRequest:
    payload: dict[str, object] = {
        "connector": "m365",
        "action_type": M365_DEVICE_RETIRE_ACTION,
        "device_id": device_id,
    }
    validate_m365_managed_device_retirement_payload(payload)
    return store.create_approval_request(
        f"m365-managed-device:{device_id.strip()}:retire",
        f"m365.{M365_DEVICE_RETIRE_ACTION}",
        payload,
        client_id=client_id,
    )


def draft_m365_managed_device_sync(
    store: Store,
    *,
    device_id: str,
    client_id: str | None = None,
) -> ApprovalRequest:
    payload: dict[str, object] = {
        "connector": "m365",
        "action_type": M365_DEVICE_SYNC_ACTION,
        "device_id": device_id,
    }
    validate_m365_managed_device_sync_payload(payload)
    return store.create_approval_request(
        f"m365-managed-device:{device_id.strip()}:sync",
        f"m365.{M365_DEVICE_SYNC_ACTION}",
        payload,
        client_id=client_id,
    )


def draft_m365_managed_device_reboot(
    store: Store,
    *,
    device_id: str,
    client_id: str | None = None,
) -> ApprovalRequest:
    payload: dict[str, object] = {
        "connector": "m365",
        "action_type": M365_DEVICE_REBOOT_ACTION,
        "device_id": device_id,
    }
    validate_m365_managed_device_reboot_payload(payload)
    return store.create_approval_request(
        f"m365-managed-device:{device_id.strip()}:reboot",
        f"m365.{M365_DEVICE_REBOOT_ACTION}",
        payload,
        client_id=client_id,
    )


def draft_m365_managed_device_remote_lock(
    store: Store,
    device_id: str,
    *,
    client_id: str | None = None,
) -> ApprovalRequest:
    payload: dict[str, object] = {
        "connector": "m365",
        "action_type": M365_DEVICE_REMOTE_LOCK_ACTION,
        "device_id": device_id.strip(),
    }
    validate_m365_managed_device_remote_lock_payload(payload)
    return store.create_approval_request(
        f"m365-managed-device:{device_id.strip()}:remote-lock",
        f"m365.{M365_DEVICE_REMOTE_LOCK_ACTION}",
        payload,
        client_id=client_id,
    )


def draft_m365_mailbox_settings_update(
    store: Store,
    *,
    user_identity: str,
    settings: dict[str, str],
    client_id: str | None = None,
) -> ApprovalRequest:
    payload: dict[str, object] = {
        "connector": "m365",
        "action_type": M365_MAILBOX_SETTINGS_UPDATE_ACTION,
        "settings": settings,
        "user_identity": user_identity,
    }
    validate_m365_mailbox_settings_update_payload(payload)
    return store.create_approval_request(
        f"m365-user:{user_identity.strip()}:mailbox-settings",
        f"m365.{M365_MAILBOX_SETTINGS_UPDATE_ACTION}",
        payload,
        client_id=client_id,
    )


def draft_m365_mail_message_move(
    store: Store,
    *,
    user_identity: str,
    source_folder_id: str,
    message_id: str,
    destination_folder_id: str,
    client_id: str | None = None,
) -> ApprovalRequest:
    payload: dict[str, object] = {
        "connector": "m365",
        "action_type": M365_MAIL_MESSAGE_MOVE_ACTION,
        "destination_folder_id": destination_folder_id,
        "message_id": message_id,
        "source_folder_id": source_folder_id,
        "user_identity": user_identity,
    }
    validate_m365_mail_message_move_payload(payload)
    return store.create_approval_request(
        f"m365-user:{user_identity.strip()}:message:{message_id.strip()}:move",
        f"m365.{M365_MAIL_MESSAGE_MOVE_ACTION}",
        payload,
        client_id=client_id,
    )


def draft_m365_mail_message_read_state(
    store: Store,
    *,
    user_identity: str,
    source_folder_id: str,
    message_id: str,
    is_read: bool,
    client_id: str | None = None,
) -> ApprovalRequest:
    payload: dict[str, object] = {
        "connector": "m365",
        "action_type": M365_MAIL_MESSAGE_READ_STATE_ACTION,
        "is_read": is_read,
        "message_id": message_id,
        "source_folder_id": source_folder_id,
        "user_identity": user_identity,
    }
    validate_m365_mail_message_read_state_payload(payload)
    return store.create_approval_request(
        f"m365-user:{user_identity.strip()}:message:{message_id.strip()}:read-state",
        f"m365.{M365_MAIL_MESSAGE_READ_STATE_ACTION}",
        payload,
        client_id=client_id,
    )


def draft_m365_mail_message_delete(
    store: Store,
    *,
    user_identity: str,
    source_folder_id: str,
    message_id: str,
    client_id: str | None = None,
) -> ApprovalRequest:
    payload: dict[str, object] = {
        "connector": "m365",
        "action_type": M365_MAIL_MESSAGE_DELETE_ACTION,
        "message_id": message_id,
        "source_folder_id": source_folder_id,
        "user_identity": user_identity,
    }
    validate_m365_mail_message_delete_payload(payload)
    return store.create_approval_request(
        f"m365-user:{user_identity.strip()}:message:{message_id.strip()}:delete",
        f"m365.{M365_MAIL_MESSAGE_DELETE_ACTION}",
        payload,
        client_id=client_id,
    )


def execute_m365_approval_request(
    store: Store,
    client: M365GraphClient,
    vault: SecretVault,
    request_id: int,
) -> ApprovalRequest:
    approval = store.get_approval_request(request_id)
    if approval is None:
        raise KeyError(request_id)
    if approval.action_type not in {
        f"m365.{M365_USER_CREATE_ACTION}",
        f"m365.{M365_USER_DISABLE_ACTION}",
        f"m365.{M365_PASSWORD_RESET_ACTION}",
        f"m365.{M365_AUTHENTICATION_METHOD_DELETE_ACTION}",
        f"m365.{M365_GROUP_MEMBERSHIP_ADD_ACTION}",
        f"m365.{M365_GROUP_MEMBERSHIP_REMOVE_ACTION}",
        f"m365.{M365_LICENSE_ADD_ACTION}",
        f"m365.{M365_LICENSE_REMOVE_ACTION}",
        f"m365.{M365_SESSION_REVOKE_ACTION}",
        f"m365.{M365_DEVICE_RETIRE_ACTION}",
        f"m365.{M365_DEVICE_SYNC_ACTION}",
        f"m365.{M365_DEVICE_REBOOT_ACTION}",
        f"m365.{M365_DEVICE_REMOTE_LOCK_ACTION}",
        f"m365.{M365_MAILBOX_SETTINGS_UPDATE_ACTION}",
        f"m365.{M365_MAIL_MESSAGE_MOVE_ACTION}",
        f"m365.{M365_MAIL_MESSAGE_READ_STATE_ACTION}",
        f"m365.{M365_MAIL_MESSAGE_DELETE_ACTION}",
    }:
        raise ValueError("approval request is not a supported M365 action")
    if approval.status != "approved":
        raise PermissionError("M365 writes require approved approval requests")
    if approval.execution_status == "succeeded":
        raise RuntimeError("M365 approval request has already executed successfully")
    payload = json.loads(approval.payload_json)
    if not isinstance(payload, dict):
        raise ValueError("approval payload is malformed")
    action_type = str(payload.get("action_type"))
    if payload.get("connector") != "m365" or action_type not in {
        M365_USER_CREATE_ACTION,
        M365_USER_DISABLE_ACTION,
        M365_PASSWORD_RESET_ACTION,
        M365_AUTHENTICATION_METHOD_DELETE_ACTION,
        M365_GROUP_MEMBERSHIP_ADD_ACTION,
        M365_GROUP_MEMBERSHIP_REMOVE_ACTION,
        M365_LICENSE_ADD_ACTION,
        M365_LICENSE_REMOVE_ACTION,
        M365_SESSION_REVOKE_ACTION,
        M365_DEVICE_RETIRE_ACTION,
        M365_DEVICE_SYNC_ACTION,
        M365_DEVICE_REBOOT_ACTION,
        M365_DEVICE_REMOTE_LOCK_ACTION,
        M365_MAILBOX_SETTINGS_UPDATE_ACTION,
        M365_MAIL_MESSAGE_MOVE_ACTION,
        M365_MAIL_MESSAGE_READ_STATE_ACTION,
        M365_MAIL_MESSAGE_DELETE_ACTION,
    }:
        raise ValueError("approval payload does not match M365 action")
    result: (
        M365GraphUserCreateResult
        | M365GraphUserDisableResult
        | M365GraphPasswordResetResult
        | M365GraphAuthenticationMethodDeleteResult
        | M365GraphGroupMembershipResult
        | M365GraphLicenseChangeResult
        | M365GraphSessionRevokeResult
        | M365GraphManagedDeviceRetireResult
        | M365GraphManagedDeviceSyncResult
        | M365GraphManagedDeviceRebootResult
        | M365GraphManagedDeviceRemoteLockResult
        | M365GraphMailboxSettingsUpdateResult
        | M365GraphMailMessageMoveResult
        | M365GraphMailMessageReadStateResult
        | M365GraphMailMessageDeleteResult
    )
    result_payload: dict[str, object]
    if action_type == M365_USER_CREATE_ACTION:
        validate_m365_user_creation_payload(payload)
        try:
            temporary_password = vault.get(str(payload["temporary_vault_name"]))
        except (SecretVaultError, ValueError) as exc:
            raise RuntimeError("M365 temporary credential could not be read from the local vault") from exc
        if not temporary_password:
            raise RuntimeError("M365 temporary credential is missing from the local vault")
        result = client.create_user(
            user_principal_name=str(payload["user_principal_name"]),
            display_name=str(payload["display_name"]),
            mail_nickname=str(payload["mail_nickname"]),
            temporary_password=temporary_password,
            account_enabled=bool(payload["account_enabled"]),
            force_change_password_next_sign_in=bool(payload["force_change_next_sign_in"]),
        )
        result_payload = {
            "remote_id": result.remote_id,
            "user_principal_name": result.user_principal_name,
            "display_name": result.display_name,
            "account_enabled": result.account_enabled,
            "status_code": result.status_code,
        }
    elif action_type == M365_USER_DISABLE_ACTION:
        validate_m365_user_disable_payload(payload)
        result = client.disable_user(user_identity=str(payload["user_identity"]))
        result_payload = {
            "user_identity": result.user_identity,
            "status_code": result.status_code,
        }
    elif action_type == M365_PASSWORD_RESET_ACTION:
        validate_m365_password_reset_payload(payload)
        try:
            temporary_password = vault.get(str(payload["temporary_vault_name"]))
        except (SecretVaultError, ValueError) as exc:
            raise RuntimeError("M365 temporary credential could not be read from the local vault") from exc
        if not temporary_password:
            raise RuntimeError("M365 temporary credential is missing from the local vault")
        result = client.reset_user_password(
            user_identity=str(payload["user_identity"]),
            temporary_password=temporary_password,
            force_change_password_next_sign_in=bool(payload["force_change_next_sign_in"]),
            force_change_password_next_sign_in_with_mfa=bool(
                payload["force_change_next_sign_in_with_mfa"]
            ),
        )
        result_payload = {
            "user_identity": result.user_identity,
            "force_change_password_next_sign_in": result.force_change_password_next_sign_in,
            "force_change_password_next_sign_in_with_mfa": result.force_change_password_next_sign_in_with_mfa,
            "status_code": result.status_code,
        }
    elif action_type == M365_AUTHENTICATION_METHOD_DELETE_ACTION:
        validate_m365_authentication_method_delete_payload(payload)
        result = client.delete_authentication_method(
            user_identity=str(payload["user_identity"]),
            method_type=str(payload["method_type"]),
            method_id=str(payload["method_id"]),
        )
        result_payload = {
            "user_identity": result.user_identity,
            "method_type": result.method_type,
            "method_id": result.method_id,
            "status_code": result.status_code,
        }
    elif action_type in {M365_GROUP_MEMBERSHIP_ADD_ACTION, M365_GROUP_MEMBERSHIP_REMOVE_ACTION}:
        validate_m365_group_membership_payload(payload)
        operation = "add" if action_type == M365_GROUP_MEMBERSHIP_ADD_ACTION else "remove"
        result = client.change_group_membership(
            group_id=str(payload["group_id"]),
            user_id=str(payload["user_id"]),
            operation=operation,
        )
        result_payload = {
            "group_id": result.group_id,
            "user_id": result.user_id,
            "operation": result.operation,
            "status_code": result.status_code,
        }
    elif action_type in {M365_LICENSE_ADD_ACTION, M365_LICENSE_REMOVE_ACTION}:
        validate_m365_license_change_payload(payload)
        operation = "add" if action_type == M365_LICENSE_ADD_ACTION else "remove"
        result = client.change_user_licenses(
            user_id=str(payload["user_id"]),
            sku_ids=cast(list[str], payload["sku_ids"]),
            operation=operation,
        )
        result_payload = {
            "user_id": result.user_id,
            "operation": result.operation,
            "sku_ids": list(result.sku_ids),
            "status_code": result.status_code,
        }
    elif action_type == M365_SESSION_REVOKE_ACTION:
        validate_m365_session_revocation_payload(payload)
        result = client.revoke_user_sessions(user_id=str(payload["user_id"]))
        result_payload = {
            "user_id": result.user_id,
            "status_code": result.status_code,
        }
    elif action_type == M365_DEVICE_RETIRE_ACTION:
        validate_m365_managed_device_retirement_payload(payload)
        result = client.retire_managed_device(device_id=str(payload["device_id"]))
        result_payload = {
            "device_id": result.device_id,
            "status_code": result.status_code,
        }
    elif action_type == M365_DEVICE_SYNC_ACTION:
        validate_m365_managed_device_sync_payload(payload)
        result = client.sync_managed_device(device_id=str(payload["device_id"]))
        result_payload = {
            "device_id": result.device_id,
            "status_code": result.status_code,
        }
    elif action_type == M365_DEVICE_REBOOT_ACTION:
        validate_m365_managed_device_reboot_payload(payload)
        result = client.reboot_managed_device(device_id=str(payload["device_id"]))
        result_payload = {
            "device_id": result.device_id,
            "status_code": result.status_code,
        }
    elif action_type == M365_DEVICE_REMOTE_LOCK_ACTION:
        validate_m365_managed_device_remote_lock_payload(payload)
        result = client.remote_lock_managed_device(device_id=str(payload["device_id"]))
        result_payload = {
            "device_id": result.device_id,
            "status_code": result.status_code,
        }
    elif action_type == M365_MAILBOX_SETTINGS_UPDATE_ACTION:
        validate_m365_mailbox_settings_update_payload(payload)
        result = client.update_mailbox_settings(
            user_identity=str(payload["user_identity"]),
            settings=cast(dict[str, str], payload["settings"]),
        )
        result_payload = {
            "user_identity": result.user_identity,
            "settings": result.settings,
            "status_code": result.status_code,
        }
    elif action_type == M365_MAIL_MESSAGE_MOVE_ACTION:
        validate_m365_mail_message_move_payload(payload)
        result = client.move_mail_message(
            user_identity=str(payload["user_identity"]),
            source_folder_id=str(payload["source_folder_id"]),
            message_id=str(payload["message_id"]),
            destination_folder_id=str(payload["destination_folder_id"]),
        )
        result_payload = {
            "user_identity": result.user_identity,
            "source_folder_id": result.source_folder_id,
            "message_id": result.message_id,
            "destination_folder_id": result.destination_folder_id,
            "status_code": result.status_code,
        }
    elif action_type == M365_MAIL_MESSAGE_READ_STATE_ACTION:
        validate_m365_mail_message_read_state_payload(payload)
        result = client.update_mail_message_read_state(
            user_identity=str(payload["user_identity"]),
            source_folder_id=str(payload["source_folder_id"]),
            message_id=str(payload["message_id"]),
            is_read=bool(payload["is_read"]),
        )
        result_payload = {
            "user_identity": result.user_identity,
            "source_folder_id": result.source_folder_id,
            "message_id": result.message_id,
            "is_read": result.is_read,
            "status_code": result.status_code,
        }
    else:
        validate_m365_mail_message_delete_payload(payload)
        result = client.delete_mail_message(
            user_identity=str(payload["user_identity"]),
            source_folder_id=str(payload["source_folder_id"]),
            message_id=str(payload["message_id"]),
        )
        result_payload = {
            "user_identity": result.user_identity,
            "source_folder_id": result.source_folder_id,
            "message_id": result.message_id,
            "status_code": result.status_code,
        }
    return store.record_approval_execution(
        request_id,
        status=result.status,
        message=result.message,
        result={
            "connector": "m365",
            "action_type": action_type,
            **result_payload,
        },
    )


def validate_m365_user_creation_payload(payload: dict[str, object]) -> None:
    if set(payload) != {"connector", "action_type", *M365_USER_CREATE_FIELDS}:
        raise ValueError("M365 user creation payload contains unsupported fields")
    if payload.get("connector") != "m365" or payload.get("action_type") != M365_USER_CREATE_ACTION:
        raise ValueError("M365 user creation payload is invalid")
    user_principal_name = payload.get("user_principal_name")
    display_name = payload.get("display_name")
    mail_nickname = payload.get("mail_nickname")
    temporary_vault_name = payload.get("temporary_vault_name")
    if not all(
        isinstance(value, str)
        for value in (user_principal_name, display_name, mail_nickname, temporary_vault_name)
    ):
        raise ValueError("M365 user creation text fields are invalid")
    user_principal_name = cast(str, user_principal_name)
    display_name = cast(str, display_name)
    mail_nickname = cast(str, mail_nickname)
    temporary_vault_name = cast(str, temporary_vault_name)
    if (
        not user_principal_name.strip()
        or user_principal_name.count("@") != 1
        or len(user_principal_name) > 320
        or any(ord(character) < 32 or character.isspace() for character in user_principal_name)
    ):
        raise ValueError("M365 user_principal_name is invalid")
    if (
        not display_name.strip()
        or len(display_name) > 256
        or any(ord(character) < 32 for character in display_name)
    ):
        raise ValueError("M365 display_name is invalid")
    if not mail_nickname.strip() or len(mail_nickname) > 64 or any(
        character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-"
        for character in mail_nickname
    ):
        raise ValueError("M365 mail_nickname is invalid")
    if (
        not temporary_vault_name.startswith("WAIT_M365_TEMP_")
        or len(temporary_vault_name) > 128
        or any(
            character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.-"
            for character in temporary_vault_name
        )
    ):
        raise ValueError("M365 temporary_vault_name must name a WAIT_M365_TEMP_ vault entry")
    if not isinstance(payload.get("account_enabled"), bool) or not isinstance(
        payload.get("force_change_next_sign_in"), bool
    ):
        raise ValueError("M365 user creation flags are invalid")


def validate_m365_password_reset_payload(payload: dict[str, object]) -> None:
    if set(payload) != {"connector", "action_type", *M365_PASSWORD_RESET_FIELDS}:
        raise ValueError("M365 password reset payload contains unsupported fields")
    if payload.get("connector") != "m365" or payload.get("action_type") != M365_PASSWORD_RESET_ACTION:
        raise ValueError("M365 password reset payload is invalid")
    user_identity = payload.get("user_identity")
    vault_name = payload.get("temporary_vault_name")
    if (
        not isinstance(user_identity, str)
        or not user_identity.strip()
        or len(user_identity) > 320
        or any(ord(character) < 32 or character.isspace() for character in user_identity)
    ):
        raise ValueError("M365 user_identity is invalid")
    if (
        not isinstance(vault_name, str)
        or not vault_name.startswith("WAIT_M365_TEMP_")
        or len(vault_name) > 128
        or any(
            character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.-"
            for character in vault_name
        )
    ):
        raise ValueError("M365 temporary_vault_name must name a WAIT_M365_TEMP_ vault entry")
    force_change = payload.get("force_change_next_sign_in")
    force_change_mfa = payload.get("force_change_next_sign_in_with_mfa")
    if not isinstance(force_change, bool) or not isinstance(force_change_mfa, bool):
        raise ValueError("M365 password reset flags are invalid")
    if force_change_mfa and not force_change:
        raise ValueError(
            "M365 force_change_password_next_sign_in_with_mfa requires "
            "force_change_password_next_sign_in"
        )


def validate_m365_authentication_method_delete_payload(payload: dict[str, object]) -> None:
    if set(payload) != {"connector", "action_type", *M365_AUTHENTICATION_METHOD_DELETE_FIELDS}:
        raise ValueError("M365 authentication method payload contains unsupported fields")
    if (
        payload.get("connector") != "m365"
        or payload.get("action_type") != M365_AUTHENTICATION_METHOD_DELETE_ACTION
    ):
        raise ValueError("M365 authentication method payload is invalid")
    for field_name in ("user_identity", "method_id"):
        value = payload.get(field_name)
        if (
            not isinstance(value, str)
            or not value.strip()
            or len(value) > 320
            or any(ord(character) < 32 or character.isspace() for character in value)
        ):
            raise ValueError(f"M365 {field_name} is invalid")
    method_type = payload.get("method_type")
    if method_type not in {"fido2", "microsoft_authenticator", "phone", "software_oath"}:
        raise ValueError("M365 authentication method type is invalid")
    if method_type == "phone" and str(payload["method_id"]).lower() not in {
        "b6332ec1-7057-4abe-9331-3d72feddfe41",
        "e37fc753-ff3b-4958-9484-eaa9425c82bc",
        "3179e48a-750b-4051-897c-87b9720928f7",
    }:
        raise ValueError("M365 phone authentication method ID is invalid")


def validate_m365_user_disable_payload(payload: dict[str, object]) -> None:
    if set(payload) != {"connector", "action_type", "user_identity"}:
        raise ValueError("M365 user disable payload contains unsupported fields")
    if payload.get("connector") != "m365" or payload.get("action_type") != M365_USER_DISABLE_ACTION:
        raise ValueError("M365 user disable payload is invalid")
    user_identity = payload.get("user_identity")
    if (
        not isinstance(user_identity, str)
        or not user_identity.strip()
        or len(user_identity) > 320
        or any(ord(character) < 32 or character.isspace() for character in user_identity)
    ):
        raise ValueError("M365 user_identity is invalid")


def validate_m365_group_membership_payload(payload: dict[str, object]) -> None:
    if set(payload) != {"connector", "action_type", "group_id", "user_id"}:
        raise ValueError("M365 group membership payload contains unsupported fields")
    if payload.get("connector") != "m365" or payload.get("action_type") not in {
        M365_GROUP_MEMBERSHIP_ADD_ACTION,
        M365_GROUP_MEMBERSHIP_REMOVE_ACTION,
    }:
        raise ValueError("M365 group membership payload is invalid")
    for field in ("group_id", "user_id"):
        value = payload.get(field)
        if (
            not isinstance(value, str)
            or not value.strip()
            or len(value) > 320
            or any(ord(character) < 32 or character.isspace() for character in value)
        ):
            raise ValueError(f"M365 {field} is invalid")


def validate_m365_license_change_payload(payload: dict[str, object]) -> None:
    if set(payload) != {"connector", "action_type", "user_id", "sku_ids"}:
        raise ValueError("M365 license payload contains unsupported fields")
    if payload.get("connector") != "m365" or payload.get("action_type") not in {
        M365_LICENSE_ADD_ACTION,
        M365_LICENSE_REMOVE_ACTION,
    }:
        raise ValueError("M365 license payload is invalid")
    user_id = payload.get("user_id")
    if (
        not isinstance(user_id, str)
        or not user_id.strip()
        or len(user_id) > 320
        or any(ord(character) < 32 or character.isspace() for character in user_id)
    ):
        raise ValueError("M365 user_id is invalid")
    sku_ids = payload.get("sku_ids")
    if not isinstance(sku_ids, list) or not 1 <= len(sku_ids) <= 50:
        raise ValueError("M365 sku_ids must contain 1 to 50 IDs")
    canonical_ids = [_canonical_uuid(value, "sku_id") for value in sku_ids]
    if len(set(canonical_ids)) != len(canonical_ids):
        raise ValueError("M365 sku_ids must be unique")


def validate_m365_session_revocation_payload(payload: dict[str, object]) -> None:
    if set(payload) != {"connector", "action_type", "user_id"}:
        raise ValueError("M365 session revocation payload contains unsupported fields")
    if payload.get("connector") != "m365" or payload.get("action_type") != M365_SESSION_REVOKE_ACTION:
        raise ValueError("M365 session revocation payload is invalid")
    user_id = payload.get("user_id")
    if (
        not isinstance(user_id, str)
        or not user_id.strip()
        or len(user_id) > 320
        or any(ord(character) < 32 or character.isspace() for character in user_id)
    ):
        raise ValueError("M365 user_id is invalid")


def validate_m365_managed_device_retirement_payload(payload: dict[str, object]) -> None:
    if set(payload) != {"connector", "action_type", "device_id"}:
        raise ValueError("M365 managed-device retirement payload contains unsupported fields")
    if payload.get("connector") != "m365" or payload.get("action_type") != M365_DEVICE_RETIRE_ACTION:
        raise ValueError("M365 managed-device retirement payload is invalid")
    device_id = payload.get("device_id")
    if (
        not isinstance(device_id, str)
        or not device_id.strip()
        or len(device_id) > 320
        or any(ord(character) < 32 or character.isspace() for character in device_id)
    ):
        raise ValueError("M365 device_id is invalid")


def validate_m365_managed_device_sync_payload(payload: dict[str, object]) -> None:
    if set(payload) != {"connector", "action_type", "device_id"}:
        raise ValueError("M365 managed-device sync payload contains unsupported fields")
    if payload.get("connector") != "m365" or payload.get("action_type") != M365_DEVICE_SYNC_ACTION:
        raise ValueError("M365 managed-device sync payload is invalid")
    device_id = payload.get("device_id")
    if (
        not isinstance(device_id, str)
        or not device_id.strip()
        or len(device_id) > 320
        or any(ord(character) < 32 or character.isspace() for character in device_id)
    ):
        raise ValueError("M365 device_id is invalid")


def validate_m365_managed_device_reboot_payload(payload: dict[str, object]) -> None:
    if set(payload) != {"connector", "action_type", "device_id"}:
        raise ValueError("M365 managed-device reboot payload contains unsupported fields")
    if payload.get("connector") != "m365" or payload.get("action_type") != M365_DEVICE_REBOOT_ACTION:
        raise ValueError("M365 managed-device reboot payload is invalid")
    device_id = payload.get("device_id")
    if (
        not isinstance(device_id, str)
        or not device_id.strip()
        or len(device_id) > 320
        or any(ord(character) < 32 or character.isspace() for character in device_id)
    ):
        raise ValueError("M365 device_id is invalid")


def validate_m365_managed_device_remote_lock_payload(payload: dict[str, object]) -> None:
    if set(payload) != {"connector", "action_type", "device_id"}:
        raise ValueError("M365 managed-device remote-lock payload contains unsupported fields")
    if payload.get("connector") != "m365" or payload.get("action_type") != M365_DEVICE_REMOTE_LOCK_ACTION:
        raise ValueError("M365 managed-device remote-lock payload is invalid")
    device_id = payload.get("device_id")
    if (
        not isinstance(device_id, str)
        or not device_id.strip()
        or len(device_id) > 320
        or any(ord(character) < 32 or character.isspace() for character in device_id)
    ):
        raise ValueError("M365 device_id is invalid")


def validate_m365_mailbox_settings_update_payload(payload: dict[str, object]) -> None:
    if set(payload) != {"connector", "action_type", "settings", "user_identity"}:
        raise ValueError("M365 mailbox settings payload contains unsupported fields")
    if payload.get("connector") != "m365" or payload.get("action_type") != M365_MAILBOX_SETTINGS_UPDATE_ACTION:
        raise ValueError("M365 mailbox settings payload is invalid")
    user_identity = payload.get("user_identity")
    if (
        not isinstance(user_identity, str)
        or not user_identity.strip()
        or len(user_identity) > 320
        or any(ord(character) < 32 or character.isspace() for character in user_identity)
    ):
        raise ValueError("M365 user_identity is invalid")
    settings = payload.get("settings")
    allowed_fields = {"time_zone", "locale", "date_format", "time_format"}
    if not isinstance(settings, dict) or not settings or set(settings) - allowed_fields:
        raise ValueError("M365 mailbox settings must contain supported fields")
    for field_name, value in settings.items():
        if (
            not isinstance(value, str)
            or not value.strip()
            or len(value.strip()) > 128
            or any(ord(character) < 32 for character in value)
        ):
            raise ValueError(f"M365 mailbox setting {field_name} is invalid")


def validate_m365_mail_message_move_payload(payload: dict[str, object]) -> None:
    required = {
        "connector",
        "action_type",
        "user_identity",
        "source_folder_id",
        "message_id",
        "destination_folder_id",
    }
    if set(payload) != required:
        raise ValueError("M365 mail message move payload contains unsupported fields")
    if payload.get("connector") != "m365" or payload.get("action_type") != M365_MAIL_MESSAGE_MOVE_ACTION:
        raise ValueError("M365 mail message move payload is invalid")
    for field_name in ("user_identity", "source_folder_id", "message_id", "destination_folder_id"):
        value = payload.get(field_name)
        if (
            not isinstance(value, str)
            or not value.strip()
            or len(value) > 320
            or any(ord(character) < 32 or character.isspace() for character in value)
        ):
            raise ValueError(f"M365 {field_name} is invalid")


def validate_m365_mail_message_read_state_payload(payload: dict[str, object]) -> None:
    required = {
        "connector",
        "action_type",
        "user_identity",
        "source_folder_id",
        "message_id",
        "is_read",
    }
    if set(payload) != required:
        raise ValueError("M365 mail message read-state payload contains unsupported fields")
    if (
        payload.get("connector") != "m365"
        or payload.get("action_type") != M365_MAIL_MESSAGE_READ_STATE_ACTION
    ):
        raise ValueError("M365 mail message read-state payload is invalid")
    if not isinstance(payload.get("is_read"), bool):
        raise ValueError("M365 is_read is invalid")
    for field_name in ("user_identity", "source_folder_id", "message_id"):
        value = payload.get(field_name)
        if (
            not isinstance(value, str)
            or not value.strip()
            or len(value) > 320
            or any(ord(character) < 32 or character.isspace() for character in value)
        ):
            raise ValueError(f"M365 {field_name} is invalid")


def validate_m365_mail_message_delete_payload(payload: dict[str, object]) -> None:
    required = {
        "connector",
        "action_type",
        "user_identity",
        "source_folder_id",
        "message_id",
    }
    if set(payload) != required:
        raise ValueError("M365 mail message delete payload contains unsupported fields")
    if (
        payload.get("connector") != "m365"
        or payload.get("action_type") != M365_MAIL_MESSAGE_DELETE_ACTION
    ):
        raise ValueError("M365 mail message delete payload is invalid")
    for field_name in ("user_identity", "source_folder_id", "message_id"):
        value = payload.get(field_name)
        if (
            not isinstance(value, str)
            or not value.strip()
            or len(value) > 320
            or any(ord(character) < 32 or character.isspace() for character in value)
        ):
            raise ValueError(f"M365 {field_name} is invalid")


def _canonical_uuid(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"M365 {field} is invalid")
    try:
        parsed = UUID(value)
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"M365 {field} is invalid") from exc
    canonical = str(parsed)
    if value.lower() != canonical:
        raise ValueError(f"M365 {field} is invalid")
    return canonical


def sanitize_halopsa_write_result(result: HaloWriteResult) -> dict[str, object]:
    return {
        "action_type": result.action_type,
        "ticket_id": result.ticket_id,
        "endpoint": result.endpoint,
        "status": result.status,
        "status_code": result.status_code,
        "remote_id": result.remote_id,
    }


def sanitize_connectwise_write_result(result: ConnectWiseWriteResult) -> dict[str, object]:
    return {
        "action_type": result.action_type,
        "ticket_id": result.ticket_id,
        "endpoint": result.endpoint,
        "status": result.status,
        "status_code": result.status_code,
        "remote_id": result.remote_id,
    }


def update_halopsa_approval_fields(
    store: Store,
    request_id: int,
    fields: dict[str, object],
    comment: str = "Draft edited before approval",
) -> ApprovalRequest:
    approval = store.get_approval_request(request_id)
    if approval is None:
        raise KeyError(request_id)
    if not approval.action_type.startswith("halopsa."):
        raise ValueError("approval request is not a HaloPSA action")
    payload = json.loads(approval.payload_json)
    if not isinstance(payload, dict):
        raise ValueError("approval payload is malformed")
    action_type = str(payload.get("action_type") or approval.action_type.removeprefix("halopsa."))
    validate_halopsa_action_fields(action_type, fields)
    payload["fields"] = fields
    return store.update_approval_request_payload(request_id, payload, comment)


def validate_halopsa_action_fields(action_type: str, fields: dict[str, object]) -> None:
    if action_type not in HALOPSA_ACTION_TYPES:
        raise ValueError(f"unsupported HaloPSA action type: {action_type}")
    if action_type in {"add_note", "draft_response"}:
        if not _first_present(fields, "note", "body", "message", "response"):
            raise ValueError(f"HaloPSA {action_type} requires a note or response")
        return
    if action_type == "update_status" and not _first_present(fields, "status", "status_id"):
        raise ValueError("HaloPSA update_status requires status or status_id")
    if action_type == "assign_technician" and not _first_present(
        fields,
        "technician_id",
        "agent_id",
        "assigned_agent_id",
        "team_id",
    ):
        raise ValueError("HaloPSA assign_technician requires technician, agent, or team id")
    has_ticket_field = any(value not in (None, "") for value in fields.values())
    if action_type == "update_ticket_fields" and not has_ticket_field:
        raise ValueError("HaloPSA update_ticket_fields requires at least one field")


def update_connectwise_approval_fields(
    store: Store,
    request_id: int,
    fields: dict[str, object],
    comment: str = "Draft edited before approval",
) -> ApprovalRequest:
    approval = store.get_approval_request(request_id)
    if approval is None:
        raise KeyError(request_id)
    if not approval.action_type.startswith("connectwise."):
        raise ValueError("approval request is not a ConnectWise PSA action")
    payload = json.loads(approval.payload_json)
    if not isinstance(payload, dict):
        raise ValueError("approval payload is malformed")
    action_type = str(payload.get("action_type") or approval.action_type.removeprefix("connectwise."))
    validate_connectwise_action_fields(action_type, fields)
    payload["fields"] = fields
    return store.update_approval_request_payload(request_id, payload, comment)


def validate_connectwise_action_fields(action_type: str, fields: dict[str, object]) -> None:
    if action_type not in CONNECTWISE_ACTION_TYPES:
        raise ValueError(f"unsupported ConnectWise PSA action type: {action_type}")
    if not isinstance(fields, dict) or not fields:
        raise ValueError(f"ConnectWise PSA {action_type} requires ticket fields")
    if action_type == "update_status":
        allowed = {"status_id"}
    elif action_type == "assign_technician":
        allowed = {"owner_id", "team_id"}
    else:
        allowed = {"summary", "description", "status_id", "priority_id", "board_id", "owner_id", "team_id"}
    if set(fields) - allowed:
        raise ValueError("ConnectWise PSA ticket fields contain unsupported keys")
    if action_type == "assign_technician" and not (fields.get("owner_id") or fields.get("team_id")):
        raise ValueError("ConnectWise PSA assign_technician requires owner_id or team_id")
    if action_type == "update_status" and not fields.get("status_id"):
        raise ValueError("ConnectWise PSA update_status requires status_id")
    for field, value in fields.items():
        if isinstance(value, bool) or not isinstance(value, (str, int, float)):
            raise ValueError(f"ConnectWise PSA field {field} must be text or a number")
        if isinstance(value, str) and (
            not value.strip()
            or len(value.strip()) > 2000
            or any(ord(character) < 32 for character in value)
        ):
            raise ValueError(f"ConnectWise PSA field {field} is invalid")


def validate_syncro_action_fields(action_type: str, fields: dict[str, object]) -> None:
    if action_type not in SYNCRO_ACTION_TYPES:
        raise ValueError(f"unsupported Syncro action type: {action_type}")
    if not isinstance(fields, dict) or not fields:
        raise ValueError("Syncro add_note requires ticket comment fields")
    allowed = {"subject", "body", "hidden", "do_not_email"}
    if set(fields) - allowed or not {"subject", "body"} <= set(fields):
        raise ValueError("Syncro add_note requires only subject, body, and optional flags")
    subject = fields["subject"]
    body = fields["body"]
    if (
        not isinstance(subject, str)
        or not subject.strip()
        or len(subject.strip()) > 250
        or any(ord(character) < 32 for character in subject if character not in "\r\n\t")
    ):
        raise ValueError("Syncro comment subject is invalid")
    if (
        not isinstance(body, str)
        or not body.strip()
        or len(body.strip()) > 32_000
        or any(ord(character) < 32 for character in body if character not in "\r\n\t")
    ):
        raise ValueError("Syncro comment body is invalid")
    for field in ("hidden", "do_not_email"):
        if field in fields and not isinstance(fields[field], bool):
            raise ValueError(f"Syncro comment {field} must be a boolean")


def validate_servicenow_action_fields(action_type: str, fields: dict[str, object]) -> None:
    if action_type not in SERVICENOW_ACTION_TYPES:
        raise ValueError(f"unsupported ServiceNow action type: {action_type}")
    if not isinstance(fields, dict) or not fields:
        raise ValueError(f"ServiceNow {action_type} requires incident fields")
    if action_type == "add_work_note":
        allowed = {"work_notes"}
        max_length = 4_000
    elif action_type == "update_state":
        allowed = {"incident_state"}
        max_length = 20
    elif action_type == "update_resolution":
        allowed = {"close_code", "close_notes"}
        if set(fields) != allowed:
            raise ValueError(
                "ServiceNow update_resolution requires close_code and close_notes"
            )
        for field, value in fields.items():
            field_limit = 128 if field == "close_code" else 4_000
            if (
                not isinstance(value, str)
                or not value.strip()
                or len(value.strip()) > field_limit
                or any(ord(character) < 32 for character in value)
            ):
                raise ValueError(f"ServiceNow {field} is invalid")
        return
    else:
        allowed = {"assigned_to", "assignment_group"}
        if set(fields) not in ({"assigned_to"}, {"assignment_group"}):
            raise ValueError(
                "ServiceNow assign_incident requires exactly one of assigned_to or assignment_group"
            )
        max_length = 64
    if set(fields) != allowed and action_type != "assign_incident":
        raise ValueError(f"ServiceNow {action_type} only accepts {sorted(allowed)}")
    value = next(iter(fields.values()))
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > max_length:
        raise ValueError(f"ServiceNow {action_type} field is invalid")
    if any(ord(character) < 32 for character in value):
        raise ValueError(f"ServiceNow {action_type} field contains control characters")


def validate_autotask_action_fields(action_type: str, fields: dict[str, object]) -> None:
    if action_type not in AUTOTASK_ACTION_TYPES:
        raise ValueError(f"unsupported Autotask action type: {action_type}")
    if action_type == "update_status":
        if set(fields) != {"status"}:
            raise ValueError("Autotask update_status requires only a status field")
        value = fields["status"]
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ValueError("Autotask ticket status must be a non-negative integer")
        return
    if action_type == "update_resolution":
        if set(fields) != {"resolution"}:
            raise ValueError("Autotask update_resolution requires only a resolution field")
        value = fields["resolution"]
        if (
            not isinstance(value, str)
            or not value.strip()
            or len(value.strip()) > 32_000
            or any(ord(character) < 32 for character in value)
        ):
            raise ValueError("Autotask ticket resolution is invalid")
        return
    if action_type == "assign_technician":
        if set(fields) != {"assigned_resource_id"}:
            raise ValueError(
                "Autotask assign_technician requires only an assigned_resource_id field"
            )
        value = fields["assigned_resource_id"]
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise ValueError("Autotask assigned_resource_id must be a positive integer")
        return
    if action_type == "add_time_entry":
        allowed = {
            "resource_id",
            "role_id",
            "date_worked",
            "hours_worked",
            "summary_notes",
            "billing_code_id",
            "is_non_billable",
            "show_on_invoice",
        }
        required = {"resource_id", "role_id", "date_worked", "hours_worked", "summary_notes"}
        if set(fields) - allowed or not required <= set(fields):
            raise ValueError(
                "Autotask add_time_entry requires resource_id, role_id, date_worked, "
                "hours_worked, and summary_notes"
            )
        for name in ("resource_id", "role_id"):
            value = fields[name]
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ValueError(f"Autotask time entry {name} must be a positive integer")
        date_worked = fields["date_worked"]
        if (
            not isinstance(date_worked, str)
            or not date_worked.strip()
            or len(date_worked.strip()) != 10
            or any(ord(character) < 32 for character in date_worked)
        ):
            raise ValueError("Autotask time entry date_worked is invalid")
        from datetime import date
        try:
            date.fromisoformat(date_worked.strip())
        except ValueError as exc:
            raise ValueError("Autotask time entry date_worked must be an ISO date") from exc
        hours = fields["hours_worked"]
        import math
        if (
            isinstance(hours, bool)
            or not isinstance(hours, (int, float))
            or not math.isfinite(float(hours))
            or float(hours) <= 0
            or float(hours) > 24
        ):
            raise ValueError("Autotask time entry hours_worked must be greater than 0 and at most 24")
        summary = fields["summary_notes"]
        if (
            not isinstance(summary, str)
            or not summary.strip()
            or len(summary.strip()) > 32_000
            or any(ord(character) < 32 for character in summary)
        ):
            raise ValueError("Autotask time entry summary_notes is invalid")
        for name in ("billing_code_id",):
            if name in fields:
                value = fields[name]
                if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                    raise ValueError(f"Autotask time entry {name} must be a positive integer")
        for name in ("is_non_billable", "show_on_invoice"):
            if name in fields and not isinstance(fields[name], bool):
                raise ValueError(f"Autotask time entry {name} must be boolean")
        return
    if not isinstance(fields, dict) or not {"description", "note_type", "publish"} <= set(fields):
        raise ValueError(
            "Autotask add_note requires description, note_type, and publish fields"
        )
    if set(fields) - {"description", "note_type", "publish", "title"}:
        raise ValueError("Autotask add_note contains unsupported fields")
    description = fields["description"]
    title = fields.get("title", "")
    if not isinstance(description, str) or not description.strip() or len(description.strip()) > 32_000:
        raise ValueError("Autotask note description is invalid")
    if any(ord(character) < 32 for character in description):
        raise ValueError("Autotask note description contains control characters")
    if not isinstance(title, str) or len(title.strip()) > 250:
        raise ValueError("Autotask note title is invalid")
    if any(ord(character) < 32 for character in title):
        raise ValueError("Autotask note title contains control characters")
    for field in ("note_type", "publish"):
        value = fields[field]
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ValueError(f"Autotask note field {field} must be a non-negative integer")


def _first_present(fields: dict[str, object], *keys: str) -> object:
    for key in keys:
        value = fields.get(key)
        if value not in (None, ""):
            return value
    return ""


def _classify_validation_result(
    connector: str,
    status: str,
    message: str,
) -> ConnectorValidationResult:
    if status == "ready":
        return ConnectorValidationResult(connector, True, "connector", message)
    if status == "not_configured":
        return ConnectorValidationResult(connector, False, "config", message)
    if status == "blocked":
        return ConnectorValidationResult(connector, False, "safety", message)
    lowered = message.lower()
    if "http 401" in lowered or "http 403" in lowered or "unauthor" in lowered or "forbidden" in lowered:
        layer = "auth"
    elif (
        "before receiving a response" in lowered
        or "request failed" in lowered
        or "timed out" in lowered
        or "timeout" in lowered
        or "connect" in lowered
    ):
        layer = "connectivity"
    else:
        layer = "connector"
    return ConnectorValidationResult(connector, False, layer, message)
