from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import httpx
import pytest

from wait_local_agent.collectors import CollectorPreview
from wait_local_agent.confluence import ConfluencePage
from wait_local_agent.itglue import ItGlueDocument
from wait_local_agent.m365_graph import (
    M365GraphGroup,
    M365GraphGroupReadResponse,
    M365GraphLicenseDetail,
    M365GraphLicenseDetailReadResponse,
    M365GraphLicenseReadResponse,
    M365GraphMailFolder,
    M365GraphMailFolderReadResponse,
    M365GraphMailMessage,
    M365GraphMailMessageReadResponse,
    M365GraphManagedDevice,
    M365GraphManagedDeviceReadResponse,
    M365GraphReadResponse,
    M365GraphSubscribedSku,
    M365GraphUser,
)
from wait_local_agent.models import (
    AutotaskWriteRequest,
    ConnectorReadResult,
    ConnectWiseWriteRequest,
    HaloTicket,
    HaloWriteRequest,
    HuduArticle,
    ServiceNowWriteRequest,
    SourceReference,
    SyncroWriteRequest,
    Ticket,
)
from wait_local_agent.providers import ProviderUnavailableError
from wait_local_agent.rbac import Role
from wait_local_agent.reports.renderers import redact_value
from wait_local_agent.rmm import LocalCollectorRmmAdapter
from wait_local_agent.screenconnect import ScreenConnectRmmAdapter
from wait_local_agent.sharepoint import SharePointDocument
from wait_local_agent.smart_actions import (
    ActionContext,
    ActionResult,
    AutotaskTicketLookupAction,
    AutotaskTicketWriteAction,
    CollectorPreviewAction,
    ConfluenceDocumentationSearchAction,
    ConnectWiseTicketLookupAction,
    ConnectWiseTicketWriteAction,
    DispatchSuggestionAction,
    FindSimilarTicketsAction,
    HaloPSATicketLookupAction,
    HaloPSATicketWriteAction,
    HuduDocumentationSearchAction,
    ItGlueDocumentationSearchAction,
    KnowledgeSearchAction,
    M365AuthenticationMethodDeleteAction,
    M365GroupMembershipAction,
    M365IdentityLookupAction,
    M365LicenseChangeAction,
    M365LiveContextAction,
    M365MailboxSettingsAction,
    M365MailMessageDeleteAction,
    M365MailMessageMoveAction,
    M365MailMessageReadStateAction,
    M365ManagedDeviceAction,
    M365PasswordResetAction,
    M365SessionRevocationAction,
    M365UserOffboardingAction,
    M365UserOnboardingAction,
    NotionPageCommentAction,
    RecurringServiceReviewAction,
    RmmDeviceLookupAction,
    SecurityAlertAssessmentAction,
    ServiceNowIncidentLookupAction,
    ServiceNowIncidentWriteAction,
    SharePointDocumentationContentAction,
    SharePointDocumentationSearchAction,
    SmartActionManifest,
    SmartActionRegistry,
    SmartActionService,
    StaleTicketSweepAction,
    SuggestResolutionAction,
    SyncroTicketCommentsAction,
    SyncroTicketLookupAction,
    SyncroTicketWriteAction,
    TeamsGraphContextAction,
    TicketEscalationAction,
    TicketQualityAction,
    TicketSentimentAction,
    TicketSlaAssessmentAction,
    TicketSummaryAction,
    TicketTriageAction,
    _json_list,
    _json_object,
    _stored_action_status,
)
from wait_local_agent.store import Store
from wait_local_agent.teams_graph import (
    TeamsChannel,
    TeamsChannelReadResponse,
    TeamsMessage,
    TeamsMessageReadResponse,
    TeamsTeam,
    TeamsTeamReadResponse,
)
from wait_local_agent.vault import SecretVault


def test_redacts_embedded_secrets_in_free_text_payload_values() -> None:
    payload = redact_value({"note": "token=abc password=def secret=ghi key=jkl AKIA1234567890ABCDEF"})

    assert payload == {"note": "token=[redacted] password=[redacted] secret=[redacted] key=[redacted] [redacted]"}


def test_redacts_secret_key_tokens_without_substring_overreach() -> None:
    payload = redact_value(
        {
            "key": "plain-secret",
            "api-key": "hyphen-secret",
            "APIKey": "camel-secret",
            "passwordValue": "camel-password",
            "passwd": "password-secret",
            "authorization": "auth-secret",
            "bearer": "bearer-secret",
            "privateKey": "private-secret",
            "monkey": "benign-monkey",
            "keyboard": "benign-keyboard",
            "tokenizer": "benign-tokenizer",
        }
    )

    assert payload == {
        "key": "[redacted]",
        "api-key": "[redacted]",
        "APIKey": "[redacted]",
        "passwordValue": "[redacted]",
        "passwd": "[redacted]",
        "authorization": "[redacted]",
        "bearer": "[redacted]",
        "privateKey": "[redacted]",
        "monkey": "benign-monkey",
        "keyboard": "benign-keyboard",
        "tokenizer": "benign-tokenizer",
    }


def test_event_history_redacts_legacy_payloads_at_read_time(settings) -> None:
    store = Store(settings.data_path)
    with store._connect() as connection:  # noqa: SLF001
        connection.execute(
            "insert into event_history "
            "(event_type, subject_id, status, message, payload_json, created_at) "
            "values (?, ?, ?, ?, ?, ?)",
            ("legacy", "TCK-1", "done", "token=old", '{"note":"password=old"}', "2026-01-01T00:00:00+00:00"),
        )

    event = store.list_event_history_for_subject("TCK-1")[0]
    assert "old" not in event.message
    assert "old" not in event.payload_json


def test_approval_payload_is_redacted_when_read_from_legacy_row(settings) -> None:
    store = Store(settings.data_path)
    approval = store.create_approval_request("TCK-1", "halopsa.add_note", {})
    with store._connect() as connection:  # noqa: SLF001
        connection.execute(
            "update approval_requests set payload_json = ? where id = ?",
            ('{"note":"key=old AKIA1234567890ABCDEF"}', approval.id),
        )

    assert approval.id is not None
    loaded = store.get_approval_request(approval.id)
    assert loaded is not None
    assert "old" not in loaded.payload_json


def _seed_tickets(store: Store) -> None:
    store.ingest_ticket_file(Path("examples/sample_tickets/tickets.json"))


class FakeProvider:
    def summarize_ticket(self, ticket: Ticket, sources: list[SourceReference]) -> str:
        return f"Summary for {ticket.id}"

    def draft_response(self, ticket: Ticket, sources: list[SourceReference]) -> str:
        return f"Resolution for {ticket.id}"


class FailingProvider(FakeProvider):
    def summarize_ticket(self, ticket: Ticket, sources: list[SourceReference]) -> str:
        raise RuntimeError("provider exploded")

    def draft_response(self, ticket: Ticket, sources: list[SourceReference]) -> str:
        raise RuntimeError("provider exploded")


class UnavailableProvider(FakeProvider):
    def summarize_ticket(self, ticket: Ticket, sources: list[SourceReference]) -> str:
        raise ProviderUnavailableError("offline")

    def draft_response(self, ticket: Ticket, sources: list[SourceReference]) -> str:
        raise ProviderUnavailableError("offline")


def _action_context(
    store: Store,
    settings,
    provider=None,
    *,
    client_id=None,
    available=False,
    collector_service=None,
):
    return ActionContext(
        store=store,
        settings=settings,
        provider=provider,
        actor="technician",
        client_id=client_id,
        provider_available=available,
        collector_service=collector_service,
    )


def test_teams_context_action_is_bounded_and_read_only(settings) -> None:
    provider = SimpleNamespace(
        list_teams=lambda **_: TeamsTeamReadResponse(
            ConnectorReadResult("ready", "ok", 1),
            [TeamsTeam("team-1", "Operations", "", "")],
        ),
        list_channels=lambda team_id, **_: TeamsChannelReadResponse(
            ConnectorReadResult("ready", "ok", 1),
            [TeamsChannel("channel-1", team_id, "General", "", "standard", "")],
        ),
        list_messages=lambda team_id, channel_id, **_: TeamsMessageReadResponse(
            ConnectorReadResult("ready", "ok", 1),
            [TeamsMessage("message-1", team_id, channel_id, "", "token=secret", "Adele", "", "")],
        ),
    )
    context = ActionContext(
        store=Store(settings.data_path),
        settings=settings,
        client_id="acme",
        teams_client=provider,
    )

    teams = TeamsGraphContextAction().run(context, {"resource": "teams"})
    channels = TeamsGraphContextAction().run(
        context, {"resource": "channels", "team_id": "team-1"}
    )
    messages = TeamsGraphContextAction().run(
        context,
        {"resource": "messages", "team_id": "team-1", "channel_id": "channel-1"},
    )

    assert teams.status == channels.status == messages.status == "success"
    assert teams.output["items"][0]["id"] == "team-1"  # type: ignore[index]
    assert channels.output["items"][0]["team_id"] == "team-1"  # type: ignore[index]
    assert messages.output["items"][0]["body"] == "token=[redacted]"  # type: ignore[index]
    assert messages.evidence[0]["connector"] == "m365-teams"


class FakeCollectorPreviewService:
    def __init__(self, result: CollectorPreview | None = None, error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.calls: list[tuple[str, dict[str, object]]] = []

    def preview(
        self,
        module_id: str,
        config: dict[str, object],
        *,
        client_id: str | None = None,
    ) -> CollectorPreview:
        self.calls.append((module_id, config))
        if self.error is not None:
            raise self.error
        if self.result is None:
            raise RuntimeError("missing fake preview")
        return self.result


def test_each_action_run_body_covers_success_and_input_guards(settings) -> None:
    store = Store(settings.data_path)
    _seed_tickets(store)
    context = _action_context(store, settings, FakeProvider(), available=True)
    store.upsert_canonical_asset(
        canonical_id="m365:user:user-1",
        asset_type="m365-user",
        display_name="Acme Admin",
        attributes={
            "user_id": "user-1",
            "display_name": "Acme Admin",
            "user_principal_name": "admin@acme.example",
            "mail": "admin@acme.example",
            "account_enabled": True,
            "job_title": "Administrator",
            "department": "IT",
        },
        client_id="acme",
        source_module="cloud-m365",
    )
    store.upsert_canonical_asset(
        canonical_id="agent:sentinelone",
        asset_type="endpoint-agent",
        display_name="SentinelOne",
        attributes={"agent": "SentinelOne", "category": "edr"},
        client_id="acme",
        source_module="endpoint-agents",
    )
    with store._connect() as connection:  # noqa: SLF001
        connection.execute("update tickets set client_id = 'acme'")

    triage = TicketTriageAction().run(context, {"ticket_id": "TCK-1001"})
    summary = TicketSummaryAction().run(context, {"ticket_id": "TCK-1001"})
    resolution = SuggestResolutionAction().run(context, {"ticket_id": "TCK-1002"})
    knowledge = KnowledgeSearchAction().run(context, {"ticket_id": "TCK-1001"})
    identity = M365IdentityLookupAction().run(
        replace(context, client_id="acme"),
        {"identity": "ADMIN@ACME.EXAMPLE"},
    )
    rmm = RmmDeviceLookupAction().run(
        replace(context, client_id="acme"),
        {"query": "sentinel"},
    )
    connector_context = replace(
        context,
        client_id="acme",
        halopsa_client=SimpleNamespace(
            get_ticket=lambda ticket_id: SimpleNamespace(
                result=SimpleNamespace(status="ready", message="ok", count=1),
                items=[HaloTicket(ticket_id, "Remote ticket", "Open", "P2", "acme", "Acme")],
            )
        ),
        connectwise_client=SimpleNamespace(
            get_ticket=lambda ticket_id: SimpleNamespace(
                result=SimpleNamespace(status="ready", message="ok", count=1),
                items=[
                    {
                        "id": ticket_id,
                        "summary": "Remote ticket",
                        "company_id": "acme-company",
                    }
                ],
            )
        ),
        syncro_client=SimpleNamespace(
            get_ticket=lambda ticket_id: SimpleNamespace(
                result=SimpleNamespace(status="ready", message="ok", count=1),
                items=[{"id": ticket_id, "subject": "Remote ticket", "customer_id": "acme"}],
            ),
            list_ticket_comments=lambda ticket_id, **kwargs: SimpleNamespace(
                result=SimpleNamespace(status="ready", message="ok", count=1),
                items=[{"id": "comment-1", "ticket_id": ticket_id, "body": "Reviewed"}],
                meta={"page": kwargs["page"], "per_page": kwargs["per_page"], "total_pages": 1},
            ),
        ),
        servicenow_client=SimpleNamespace(
            get_incident=lambda ticket_id: SimpleNamespace(
                result=SimpleNamespace(status="ready", message="ok", count=1),
                items=[{"sys_id": ticket_id, "short_description": "Remote incident"}],
            )
        ),
        autotask_client=SimpleNamespace(
            get_ticket=lambda ticket_id: SimpleNamespace(
                result=SimpleNamespace(status="ready", message="ok", count=1),
                items=[{"id": ticket_id, "title": "Remote ticket", "company_id": "acme"}],
            )
        ),
        itglue_client=SimpleNamespace(
            list_documents=lambda organization_id, folder_id, page, page_size: SimpleNamespace(
                result=SimpleNamespace(status="ready", message="ok", count=1),
                items=[ItGlueDocument(
                    "doc-1",
                    "VPN runbook",
                    organization_id,
                    "folder-1",
                    "today",
                    "https://itglue",
                    "MFA reset token=secret",
                )],
            )
        ),
        confluence_client=SimpleNamespace(
            list_pages=lambda space_id, page_size: SimpleNamespace(
                result=SimpleNamespace(status="ready", message="ok", count=1),
                items=[
                    ConfluencePage(
                        "page-1", "VPN runbook", space_id, "current", "3", "today",
                        "https://confluence", "MFA reset token=secret",
                    )
                ],
            )
        ),
        sharepoint_client=SimpleNamespace(
            list_documents=lambda site_id, parent_item_id=None, cursor=None, page_size=20: SimpleNamespace(
                result=SimpleNamespace(status="ready", message="ok", count=1),
                items=[
                    SharePointDocument(
                        "doc-1", "VPN runbook", site_id, "root", 10, "today",
                        "https://sharepoint", False,
                    )
                ],
            ),
            get_document_content=lambda site_id, item_id: SimpleNamespace(
                result=SimpleNamespace(status="ready", message="ok", count=1),
                items=[SharePointDocument(
                    item_id, "VPN runbook", site_id, "root", 10, "today",
                    "https://sharepoint", False, True, "MFA reset token=secret",
                )],
            ),
        ),
        m365_client=SimpleNamespace(
            list_users=lambda identity, page_size: M365GraphReadResponse(
                ConnectorReadResult("ready", "ok", 1),
                [M365GraphUser("user-1", "Alice", identity, "alice@example.test", True, "IT", "Ops")],
            ),
            list_groups=lambda identity, page_size: M365GraphGroupReadResponse(
                ConnectorReadResult("ready", "ok", 1),
                [M365GraphGroup("group-1", "IT", "it@example.test", "it", "", True, True, ())],
            ),
            list_subscribed_skus=lambda: M365GraphLicenseReadResponse(
                ConnectorReadResult("ready", "ok", 1),
                [M365GraphSubscribedSku("sku-1", "sku-1", "BUSINESS", "Enabled", "User", 1, 2, 0, 0, 0)],
            ),
            list_license_details=lambda identity, page_size: M365GraphLicenseDetailReadResponse(
                ConnectorReadResult("ready", "ok", 1),
                [M365GraphLicenseDetail("detail-1", "sku-1", "BUSINESS", ())],
            ),
            list_mail_folders=lambda identity, page_size: M365GraphMailFolderReadResponse(
                ConnectorReadResult("ready", "ok", 1),
                [M365GraphMailFolder("folder-1", "Inbox", "", 0, 1, 0, False)],
            ),
            list_mail_messages=lambda identity, folder_id, page_size: M365GraphMailMessageReadResponse(
                ConnectorReadResult("ready", "ok", 1),
                [
                    M365GraphMailMessage(
                        "message-1", "VPN issue", "Adele", "adele@example.test",
                        "today", False, True, "high",
                    )
                ],
            ),
            list_managed_devices=lambda page_size: M365GraphManagedDeviceReadResponse(
                ConnectorReadResult("ready", "ok", 1),
                [
                    M365GraphManagedDevice(
                        "device-1", "user-1", "Laptop", "company", "", "", "Windows",
                        "compliant", "mdm", "11", True, "registered", True,
                        "alice@example.test", "Alice", "Model", "Maker",
                    )
                ],
            ),
        ),
        hudu_client=SimpleNamespace(
            list_articles=lambda company_id, page, page_size: SimpleNamespace(
                result=SimpleNamespace(status="ready", message="ok", count=1),
                items=[HuduArticle(
                    "article-1",
                    "VPN setup",
                    company_id,
                    "folder-1",
                    "2026-08-01",
                    "https://hudu",
                    "MFA reset instructions token=secret",
                )],
            )
        ),
    )
    halopsa = HaloPSATicketLookupAction().run(connector_context, {"ticket_id": "TCK-1001"})
    connectwise = ConnectWiseTicketLookupAction().run(
        connector_context, {"ticket_id": "TCK-1001"}
    )
    syncro = SyncroTicketLookupAction().run(connector_context, {"ticket_id": "TCK-1001"})
    syncro_comments = SyncroTicketCommentsAction().run(
        connector_context, {"ticket_id": "TCK-1001", "limit": 1}
    )
    servicenow = ServiceNowIncidentLookupAction().run(
        connector_context, {"ticket_id": "TCK-1001"}
    )
    autotask = AutotaskTicketLookupAction().run(
        connector_context, {"ticket_id": "TCK-1001"}
    )
    itglue = ItGlueDocumentationSearchAction().run(
        replace(connector_context, client_id="org-1"),
        {"query": "vpn", "organization_id": "org-1"},
    )
    itglue_content = ItGlueDocumentationSearchAction().run(
        replace(connector_context, client_id="org-1"),
        {"query": "mfa", "organization_id": "org-1"},
    )
    confluence = ConfluenceDocumentationSearchAction().run(
        replace(connector_context, client_id="space-1"),
        {"query": "vpn", "space_id": "space-1"},
    )
    confluence_content = ConfluenceDocumentationSearchAction().run(
        connector_context,
        {"query": "mfa", "space_id": "acme"},
    )
    sharepoint = SharePointDocumentationSearchAction().run(
        replace(connector_context, client_id="site-1"),
        {"query": "vpn", "site_id": "site-1"},
    )
    sharepoint_content = SharePointDocumentationContentAction().run(
        replace(connector_context, client_id="site-1"),
        {"site_id": "site-1", "item_id": "doc-1"},
    )
    m365_user = M365LiveContextAction().run(
        connector_context, {"resource": "user", "identity": "alice@example.test"}
    )
    m365_group = M365LiveContextAction().run(
        connector_context, {"resource": "group", "identity": "it"}
    )
    m365_license = M365LiveContextAction().run(connector_context, {"resource": "licenses"})
    m365_license_detail = M365LiveContextAction().run(
        connector_context,
        {"resource": "license_details", "identity": "alice@example.test"},
    )
    m365_mail = M365LiveContextAction().run(
        connector_context, {"resource": "mailbox_folders", "identity": "alice@example.test"}
    )
    m365_messages = M365LiveContextAction().run(
        connector_context,
        {"resource": "mail_messages", "identity": "alice@example.test", "folder_id": "inbox"},
    )
    m365_device = M365LiveContextAction().run(
        connector_context, {"resource": "managed_devices"}
    )
    hudu = HuduDocumentationSearchAction().run(
        connector_context,
        {"query": "vpn", "company_id": "acme"},
    )
    hudu_content = HuduDocumentationSearchAction().run(
        connector_context,
        {"query": "mfa", "company_id": "acme"},
    )
    quality = TicketQualityAction().run(context, {"ticket_id": "TCK-1001"})
    sentiment = TicketSentimentAction().run(context, {"ticket_id": "TCK-1001"})
    escalation = TicketEscalationAction().run(context, {"ticket_id": "TCK-1001"})
    security = SecurityAlertAssessmentAction().run(context, {"ticket_id": "TCK-1001"})
    similar = FindSimilarTicketsAction().run(context, {"ticket_id": "TCK-1001"})
    dispatch = DispatchSuggestionAction().run(
        context,
        {"ticket_id": "TCK-1001", "technicians": [{"id": "tech", "workload": 1}]},
    )

    assert (
        triage.status
        == summary.status
        == resolution.status
        == knowledge.status
        == identity.status
        == rmm.status
        == halopsa.status
        == connectwise.status
        == syncro.status
        == syncro_comments.status
        == servicenow.status
        == autotask.status
        == itglue.status
        == confluence.status
        == sharepoint.status
        == sharepoint_content.status
        == m365_user.status
        == m365_group.status
        == m365_license.status
        == m365_license_detail.status
        == m365_mail.status
        == m365_messages.status
        == m365_device.status
        == hudu.status
        == quality.status
        == sentiment.status
        == escalation.status
        == security.status
        == similar.status
        == dispatch.status
        == "success"
    )
    assert summary.output["suggested_response"] == "Resolution for TCK-1001"
    assert resolution.output["citations"]
    assert knowledge.output["ticket_id"] == "TCK-1001"
    assert identity.output["count"] == 1
    assert identity.output["matches"][0]["user_principal_name"] == "admin@acme.example"  # type: ignore[index]
    assert rmm.output["count"] == 1
    assert rmm.output["devices"][0]["device_id"] == "agent:sentinelone"  # type: ignore[index]
    assert halopsa.output["ticket"]["id"] == "TCK-1001"  # type: ignore[index]
    assert connectwise.output["ticket"]["id"] == "TCK-1001"  # type: ignore[index]
    assert syncro.output["ticket"]["id"] == "TCK-1001"  # type: ignore[index]
    assert syncro_comments.output["comments"][0]["body"] == "Reviewed"  # type: ignore[index]
    assert servicenow.output["ticket"]["sys_id"] == "TCK-1001"  # type: ignore[index]
    assert autotask.output["ticket"]["id"] == "TCK-1001"  # type: ignore[index]
    assert itglue.output["documents"][0]["name"] == "VPN runbook"  # type: ignore[index]
    assert itglue_content.status == "success"
    assert itglue_content.output["documents"][0]["content"] == "MFA reset token=[redacted]"  # type: ignore[index]
    confluence_pages = confluence.output["pages"]
    assert isinstance(confluence_pages, list)
    confluence_page = confluence_pages[0]
    assert isinstance(confluence_page, dict)
    assert confluence_page["title"] == "VPN runbook"
    assert confluence_page["body"] == "MFA reset token=[redacted]"
    assert confluence_content.status == "success"
    assert confluence_content.output["pages"][0]["body"] == "MFA reset token=[redacted]"  # type: ignore[index]
    sharepoint_documents = sharepoint.output["documents"]
    assert isinstance(sharepoint_documents, list)
    assert isinstance(sharepoint_documents[0], dict)
    assert sharepoint_documents[0]["name"] == "VPN runbook"
    assert sharepoint_content.output["document"]["content"] == "MFA reset token=[redacted]"  # type: ignore[index]
    assert m365_user.output["count"] == 1
    assert m365_group.output["count"] == 1
    assert m365_license.output["count"] == 1
    assert m365_license_detail.output["count"] == 1
    assert m365_mail.output["count"] == 1
    assert m365_messages.output["count"] == 1
    assert m365_device.output["count"] == 1
    assert hudu.output["articles"][0]["name"] == "VPN setup"  # type: ignore[index]
    assert hudu_content.status == "success"
    assert hudu_content.output["articles"][0]["content"] == "MFA reset instructions token=[redacted]"  # type: ignore[index]
    assert quality.output["passed"] is True
    assert sentiment.output["sentiment"] == "negative"
    assert escalation.output["urgency"] == "same_day"
    assert security.output["security_signal"] is False
    assert security.output["severity"] == "none"
    assert similar.output["matches"]
    assert dispatch.output["recommendation"]["technician_id"] == "tech"  # type: ignore[index]

    collector = FakeCollectorPreviewService(
        CollectorPreview(
            module_id="process-inventory",
            source_name="Processes",
            scopes=["local_host"],
            estimated_assets=2,
            estimated_observations=2,
        )
    )
    collector_result = CollectorPreviewAction().run(
        replace(context, collector_service=collector),
        {"module_id": "process-inventory", "config": {"limit": 2}},
    )
    assert collector_result.status == "success"
    assert collector_result.output["estimated_assets"] == 2
    assert collector.calls == [("process-inventory", {"limit": 2})]

    actions = (
        TicketTriageAction(),
        TicketSummaryAction(),
        SuggestResolutionAction(),
        KnowledgeSearchAction(),
        M365IdentityLookupAction(),
        RmmDeviceLookupAction(),
        HaloPSATicketLookupAction(),
        SyncroTicketLookupAction(),
        SyncroTicketCommentsAction(),
        ServiceNowIncidentLookupAction(),
        AutotaskTicketLookupAction(),
        ItGlueDocumentationSearchAction(),
        ConfluenceDocumentationSearchAction(),
        SharePointDocumentationSearchAction(),
        M365LiveContextAction(),
        HuduDocumentationSearchAction(),
        TicketQualityAction(),
        TicketSentimentAction(),
        TicketEscalationAction(),
        FindSimilarTicketsAction(),
        DispatchSuggestionAction(),
    )
    for action in actions:
        assert action.run(context, {}) .status == "failed"
    assert RmmDeviceLookupAction().run(context, {"query": "agent", "limit": 0}).status == "failed"
    assert HuduDocumentationSearchAction().run(
        replace(context, client_id="acme"),
        {"query": "vpn", "company_id": "other"},
    ).status == "failed"

    assert CollectorPreviewAction().run(context, {}).status == "failed"
    assert CollectorPreviewAction().run(context, {"module_id": "process-inventory"}).status == "failed"
    assert CollectorPreviewAction().run(
        replace(context, collector_service=FakeCollectorPreviewService()),
        {"module_id": ""},
    ).status == "failed"
    assert CollectorPreviewAction().run(
        replace(context, collector_service=FakeCollectorPreviewService()),
        {"module_id": "process-inventory", "config": "bad"},
    ).status == "failed"
    assert CollectorPreviewAction().run(
        replace(context, collector_service=FakeCollectorPreviewService(error=KeyError("unknown"))),
        {"module_id": "unknown"},
    ).error_detail == "collector module is not registered"
    assert CollectorPreviewAction().run(
        replace(context, collector_service=FakeCollectorPreviewService(error=ValueError("password=secret"))),
        {"module_id": "process-inventory"},
    ).error_detail == "password=[redacted]"


def test_action_run_validation_and_provider_errors(settings) -> None:
    store = Store(settings.data_path)
    _seed_tickets(store)
    unavailable = _action_context(store, settings)
    assert TicketSummaryAction().run(unavailable, {"ticket_id": "TCK-1001"}).status == "provider_not_configured"
    assert SuggestResolutionAction().run(unavailable, {"ticket_id": "TCK-1001"}).status == "provider_not_configured"

    failing = _action_context(store, settings, FailingProvider(), available=True)
    result = TicketSummaryAction().run(failing, {"ticket_id": "TCK-1001"})
    assert result.status == "failed" and "provider request failed" in result.error_detail
    resolution_failure = SuggestResolutionAction().run(failing, {"ticket_id": "TCK-1001"})
    assert resolution_failure.status == "failed" and "provider request failed" in resolution_failure.error_detail
    unavailable_provider = _action_context(store, settings, UnavailableProvider(), available=True)
    assert TicketSummaryAction().run(unavailable_provider, {"ticket_id": "TCK-1001"}).error_detail == "offline"
    assert SuggestResolutionAction().run(unavailable_provider, {"ticket_id": "TCK-1001"}).error_detail == "offline"

    assert (
        DispatchSuggestionAction()
        .run(unavailable, {"ticket_id": "TCK-1001", "technicians": "bad"})
        .error_detail
        == "technicians must be an array when provided"
    )
    assert DispatchSuggestionAction().run(
        unavailable, {"ticket_id": "TCK-1001", "technicians": ["bad"]}
    ).status == "failed"
    assert DispatchSuggestionAction().run(
        unavailable, {"ticket_id": "TCK-1001", "technicians": [{"id": "", "workload": 1}]}
    ).status == "failed"
    assert DispatchSuggestionAction().run(
        unavailable, {"ticket_id": "TCK-1001", "technicians": [{"id": "tech", "workload": True}]}
    ).status == "failed"

def test_action_bodies_respect_tenancy_and_citation_optional_ids(settings) -> None:
    store = Store(settings.data_path)
    _seed_tickets(store)
    with store._connect() as connection:  # noqa: SLF001
        connection.execute("update tickets set client_id = 'acme' where id = 'TCK-1001'")
        connection.execute("update tickets set client_id = 'beta' where id = 'TCK-1002'")
        connection.execute(
            "insert into tickets (id, client, subject, body, priority, status, client_id) values (?, ?, ?, ?, ?, ?, ?)",
            ("TCK-OTHER", "Acme", "Printer", "Paper jam", "Low", "Open", "acme"),
        )
    context = _action_context(store, settings, client_id="acme")
    assert TicketTriageAction().run(context, {"ticket_id": "TCK-1002"}).status == "failed"
    assert FindSimilarTicketsAction().run(context, {"ticket_id": "TCK-1001"}).output["matches"] == []

    source = SourceReference("Title", "path", "excerpt", document_id=3, chunk_id=4)
    from wait_local_agent.smart_actions import _source_citation

    assert _source_citation(source)["document_id"] == 3
    assert _source_citation(SourceReference("Title", "path", "excerpt")) == {
        "type": "knowledge", "title": "Title", "path": "path", "excerpt": "excerpt"
    }


def test_ticket_quality_reports_explainable_field_issues(settings) -> None:
    store = Store(settings.data_path)
    with store._connect() as connection:  # noqa: SLF001
        connection.execute(
            "insert into tickets (id, client, subject, body, priority, status) values (?, ?, ?, ?, ?, ?)",
            ("TCK-BAD", "", "", "", "urgent", "waiting"),
        )
    result = TicketQualityAction().run(_action_context(store, settings), {"ticket_id": "TCK-BAD"})
    assert result.status == "success"
    assert result.output["issues"] == [
        "missing_client",
        "missing_subject",
        "missing_body",
        "unknown_priority",
        "unknown_status",
    ]
    assert result.output["quality_score"] == 0


def test_security_alert_assessment_is_deterministic_and_non_mutating(settings) -> None:
    store = Store(settings.data_path)
    with store._connect() as connection:  # noqa: SLF001
        connection.execute(
            "insert into tickets (id, client, subject, body, priority, status, client_id) values (?, ?, ?, ?, ?, ?, ?)",
            (
                "SEC-1",
                "Acme",
                "Suspected phishing and suspicious login",
                "Possible credential theft after an impossible travel alert.",
                "critical",
                "open",
                "acme",
            ),
        )
    result = SecurityAlertAssessmentAction().run(
        _action_context(store, settings, client_id="acme"), {"ticket_id": "SEC-1"}
    )
    assert result.status == "success"
    assert result.output["security_signal"] is True
    assert result.output["severity"] == "critical"
    assert result.output["indicators"] == [
        "credential theft",
        "impossible travel",
        "phishing",
        "suspicious login",
    ]
    assert str(result.output["recommendation"]).startswith("Pause automated side effects")
    assert store.get_ticket("SEC-1", client_id="other") is None


def test_ticket_sla_assessment_uses_explicit_threshold_and_reports_missing_evidence(settings) -> None:
    store = Store(settings.data_path)
    with store._connect() as connection:  # noqa: SLF001
        connection.execute(
            """
            insert into tickets
              (id, client, subject, body, priority, status, client_id, created_at)
            values (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "TCK-OLD",
                "Acme",
                "Old request",
                "Waiting",
                "high",
                "open",
                "acme",
                "2020-01-01T00:00:00+00:00",
            ),
        )
        connection.execute(
            "insert into tickets (id, client, subject, body, priority, status, client_id) values (?, ?, ?, ?, ?, ?, ?)",
            ("TCK-NO-TIME", "Acme", "No timestamp", "Unknown age", "high", "open", "acme"),
        )
    context = _action_context(store, settings, client_id="acme")
    result = TicketSlaAssessmentAction().run(
        context,
        {"ticket_id": "TCK-OLD", "thresholds_minutes": {"high": 60}},
    )
    assert result.status == "success"
    assessment = cast(dict[str, object], result.output["assessment"])
    assert assessment["state"] == "at_risk"
    assert assessment["threshold_minutes"] == 60
    assert TicketSlaAssessmentAction().run(context, {}).status == "failed"
    assert TicketSlaAssessmentAction().run(
        context, {"ticket_id": "TCK-OLD", "thresholds_minutes": {"high": 0}}
    ).status == "failed"
    unknown_priority = TicketSlaAssessmentAction().run(
        context,
        {"ticket_id": "TCK-OLD", "thresholds_minutes": {"low": 60}},
    )
    assert unknown_priority.output["assessment"]["reason"] == "priority_threshold_not_supplied"  # type: ignore[index]
    missing = TicketSlaAssessmentAction().run(
        context,
        {"ticket_id": "TCK-NO-TIME", "thresholds_minutes": {"high": 60}},
    )
    assert missing.status == "success"
    assert missing.output["evidence_status"] == "insufficient"
    missing_assessment = cast(dict[str, object], missing.output["assessment"])
    assert missing_assessment["reason"] == "missing_created_at"
    with store._connect() as connection:  # noqa: SLF001
        connection.execute(
            "update tickets set status = 'closed' where id = ?",
            ("TCK-OLD",),
        )
    closed = TicketSlaAssessmentAction().run(
        context,
        {"ticket_id": "TCK-OLD", "thresholds_minutes": {"high": 60}},
    )
    assert closed.output["assessment"]["state"] == "resolved"  # type: ignore[index]


def test_stale_ticket_sweep_is_tenant_scoped_and_bounded(settings) -> None:
    store = Store(settings.data_path)
    with store._connect() as connection:  # noqa: SLF001
        connection.executemany(
            """
            insert into tickets
              (id, client, subject, body, priority, status, client_id, created_at)
            values (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                ("TCK-STALE", "Acme", "Old", "Needs follow-up", "high", "open", "acme", "2020-01-01T00:00:00+00:00"),
                ("TCK-FRESH", "Acme", "New", "Recent", "low", "open", "acme", "2099-01-01T00:00:00+00:00"),
                ("TCK-FOREIGN", "Beta", "Old", "Private", "high", "open", "beta", "2020-01-01T00:00:00+00:00"),
                ("TCK-CLOSED", "Acme", "Old", "Done", "high", "closed", "acme", "2020-01-01T00:00:00+00:00"),
            ],
        )
    result = StaleTicketSweepAction().run(
        _action_context(store, settings, client_id="acme"),
        {"stale_after_minutes": 60},
    )
    assert result.status == "success"
    tickets = cast(list[dict[str, object]], result.output["tickets"])
    assert [item["ticket_id"] for item in tickets] == ["TCK-STALE"]
    assert result.output["count"] == 1
    assert StaleTicketSweepAction().run(
        _action_context(store, settings, client_id="acme"), {"stale_after_minutes": 0}
    ).status == "failed"
    with store._connect() as connection:  # noqa: SLF001
        connection.execute(
            """
            insert into tickets
              (id, client, subject, body, priority, status, client_id, created_at)
            values (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("TCK-MISSING-TIME", "Acme", "Missing", "Unknown", "low", "open", "acme", "bad-date"),
        )
    with_missing = StaleTicketSweepAction().run(
        _action_context(store, settings, client_id="acme"), {"stale_after_minutes": 60}
    )
    assert with_missing.output["excluded_missing_timestamp"] == 1


def test_approval_pending_rejected_malformed_and_repeat_paths(settings) -> None:
    store = Store(settings.data_path)
    _seed_tickets(store)
    service = SmartActionService(store, settings)
    pending = service.invoke("dispatch-suggestion", {"ticket_id": "TCK-1001"}, "requester")
    assert pending.approval_id is not None and pending.run_id is not None
    waiting = service.complete_approval(pending.approval_id, approver="approver", approver_role=Role.TECHNICIAN)
    assert waiting is not None and waiting.status == "pending_approval"

    service.update_approval(pending.approval_id, "rejected", approver="approver", approver_role=Role.TECHNICIAN)
    rejected = store.get_smart_action_run(pending.run_id)
    assert rejected is not None and rejected.status == "rejected"
    assert service.complete_approval(9999, approver="approver", approver_role=Role.TECHNICIAN) is None

    second = service.invoke("dispatch-suggestion", {"ticket_id": "TCK-1001"}, "requester")
    assert second.approval_id is not None and second.run_id is not None
    with store._connect() as connection:  # noqa: SLF001
        connection.execute(
            "update approval_requests set payload_json = ? where id = ?",
            ('{"payload": "bad"}', second.approval_id),
        )
    service.update_approval(second.approval_id, "approved", approver="approver", approver_role=Role.TECHNICIAN)
    malformed = store.get_smart_action_run(second.run_id)
    assert malformed is not None and malformed.status == "failed"
    assert _json_object("[]") == {}
    assert _json_list("{}") == []
    assert _json_list('[1, {"ok": true}]') == [{"ok": True}]


def test_service_guards_registry_and_unauthorized_paths(settings) -> None:
    store = Store(settings.data_path)
    _seed_tickets(store)
    service = SmartActionService(store, settings)

    unauthorized = service.invoke("ticket-triage", {"ticket_id": "TCK-1001"}, None)
    assert unauthorized.status == "not_authorized" and unauthorized.run_id is not None
    with pytest.raises(ValueError, match="approval expiry"):
        service.invoke(
            "dispatch-suggestion",
            {"ticket_id": "TCK-1001"},
            "requester",
            approval_expiry_seconds=0,
        )
    assert service.complete_approval(9999) is None
    legacy = store.create_approval_request("TCK-1", "ticket.assign", {})
    assert service.complete_approval(legacy.id or 0, approver="tech", approver_role=Role.TECHNICIAN) is None
    with pytest.raises(KeyError):
        service.update_approval(9999, "approved")
    updated = service.update_approval(legacy.id or 0, "approved")
    assert updated.status == "approved"

    duplicate = SmartActionRegistry()
    duplicate.register(TicketTriageAction())
    with pytest.raises(ValueError, match="already registered"):
        duplicate.register(TicketTriageAction())
    bad = SmartActionManifest("Upper", "", "", "deterministic", {}, {}, False, 0)

    class BadAction:
        manifest = bad

        def run(self, context, payload):
            return ActionResult(status="success")

    with pytest.raises(ValueError, match="lowercase"):
        duplicate.register(BadAction())
    invalid_expiry = SmartActionManifest(
        action_id="needs-approval",
        title="Needs approval",
        description="",
        kind="deterministic",
        input_schema={},
        output_schema={},
        requires_approval=True,
        estimated_minutes_saved=0,
        approval_expiry_seconds=0,
    )

    class InvalidExpiryAction:
        manifest = invalid_expiry

        def run(self, context, payload):
            return ActionResult(status="success")

    with pytest.raises(ValueError, match="approval expiry"):
        duplicate.register(InvalidExpiryAction())
    duplicate.clear()
    assert duplicate.list() == []

    class BrokenAction:
        manifest = SmartActionManifest("broken", "", "", "deterministic", {}, {}, False, 0)

        def run(self, context, payload):
            raise RuntimeError("broken")

    broken = SmartActionRegistry()
    broken.register(BrokenAction())
    failed = SmartActionService(store, settings, registry=broken).invoke("broken", {}, "actor")
    assert failed.status == "failed" and "action failed" in failed.error_detail


def test_service_edge_guards_and_status_helpers(settings) -> None:
    store = Store(settings.data_path)
    _seed_tickets(store)
    service = SmartActionService(store, settings)

    assert service.invoke(
        "dispatch-suggestion", {"ticket_id": "TCK-1001", "technicians": "bad"}, "actor"
    ).status == "failed"
    pending = service.invoke("dispatch-suggestion", {"ticket_id": "TCK-1001"}, "actor")
    assert pending.approval_id is not None
    with pytest.raises(PermissionError, match="approver is required"):
        service.update_approval(pending.approval_id, "approved")
    with pytest.raises(PermissionError, match="technician"):
        service.update_approval(pending.approval_id, "approved", approver="viewer", approver_role=Role.VIEWER)

    orphan_approval = store.create_approval_request("1", "smart_action:dispatch-suggestion", {})
    with pytest.raises(KeyError, match="smart action run"):
        service.complete_approval(orphan_approval.id or 0, approver="tech", approver_role=Role.TECHNICIAN)

    assert [
        _stored_action_status(status)
        for status in ("success", "failed", "provider_not_configured", "rejected", "pending")
    ] == [
        "success", "failed", "provider_not_configured", "rejected", "failed"
    ]
    assert _json_object("not-json") == {}
    assert _json_list("not-json") == []

    class NullIdStore(Store):
        def create_smart_action_run(self, *args, **kwargs):
            return replace(super().create_smart_action_run(*args, **kwargs), id=None)

    null_store = NullIdStore(settings.data_path.with_name("null.db"))
    with pytest.raises(RuntimeError, match="not persisted"):
        SmartActionService(null_store, settings).invoke("ticket-triage", {}, "actor")

    null_auth_store = NullIdStore(settings.data_path.with_name("null-auth.db"))
    with pytest.raises(RuntimeError, match="not persisted"):
        SmartActionService(null_auth_store, settings).invoke("ticket-triage", {}, None)

    class NullApprovalStore(Store):
        def create_pending_smart_action(self, *args, **kwargs):
            run, approval = super().create_pending_smart_action(*args, **kwargs)
            return run, replace(approval, id=None)

    null_approval_store = NullApprovalStore(settings.data_path.with_name("null-approval.db"))
    _seed_tickets(null_approval_store)
    with pytest.raises(RuntimeError, match="approval was not persisted"):
        SmartActionService(null_approval_store, settings).invoke(
            "dispatch-suggestion", {"ticket_id": "TCK-1001"}, "actor"
        )


def test_registry_lists_all_seed_actions(settings) -> None:
    service = SmartActionService(Store(settings.data_path), settings)

    assert [manifest.action_id for manifest in service.list()] == [
        "autotask-ticket-add-note",
        "autotask-ticket-add-time-entry",
        "autotask-ticket-assign-technician",
        "autotask-ticket-lookup",
        "autotask-ticket-update-resolution",
        "autotask-ticket-update-status",
        "collector-preview",
        "communication-draft",
        "communication-send",
        "confluence-documentation-search",
        "connectwise-ticket-assign-technician",
        "connectwise-ticket-lookup",
        "connectwise-ticket-status-update",
        "connectwise-ticket-update-fields",
        "dispatch-suggestion",
        "documentation-assisted-response",
        "find-similar-tickets",
        "halopsa-ticket-add-note",
        "halopsa-ticket-assign-technician",
        "halopsa-ticket-draft-response",
        "halopsa-ticket-lookup",
        "halopsa-ticket-status-update",
        "halopsa-ticket-update-fields",
        "hudu-documentation-search",
        "itglue-documentation-search",
        "knowledge-search",
        "m365-authentication-method-remove",
        "m365-group-membership",
        "m365-identity-lookup",
        "m365-license-change",
        "m365-live-context",
        "m365-mail-message-delete",
            "m365-mail-message-move",
        "m365-mail-message-read-state",
        "m365-mailbox-settings",
        "m365-managed-device-reboot",
        "m365-managed-device-remote-lock",
        "m365-managed-device-retire",
        "m365-managed-device-sync",
        "m365-password-reset",
        "m365-session-revocation",
        "m365-teams-context",
        "m365-user-offboarding",
        "m365-user-onboarding",
        "notion-data-source-query",
        "notion-documentation-search",
        "notion-page-comment",
        "nsight-antivirus-definitions",
        "nsight-antivirus-products",
        "nsight-antivirus-quarantine",
        "nsight-antivirus-quarantine-release",
        "nsight-antivirus-quarantine-remove",
        "nsight-antivirus-scan-cancel",
        "nsight-antivirus-scan-pause",
        "nsight-antivirus-scan-resume",
        "nsight-antivirus-scan-start",
        "nsight-antivirus-scans",
        "nsight-antivirus-threats",
        "nsight-antivirus-update-history",
        "nsight-asset-details",
        "nsight-backup-history",
        "nsight-backup-sessions",
        "nsight-check-config",
        "nsight-check-inventory",
        "nsight-hardware-inventory",
        "nsight-monitoring-details",
        "nsight-outage-lookup",
        "nsight-patch-approve",
        "nsight-patch-lookup",
        "nsight-patch-policy",
        "nsight-patch-reprocess",
        "nsight-performance-history",
        "nsight-run-task-now",
        "nsight-software-inventory",
        "recurring-service-review",
        "rmm-alert-lookup",
        "rmm-device-lookup",
        "rmm-script-catalog",
        "rmm-script-execute",
        "rmm-script-execution-lookup",
        "rmm-script-preview",
        "scalepad-assessment-lookup",
        "scalepad-client-lookup",
        "scalepad-compliance-health",
        "scalepad-goal-lookup",
        "scalepad-risk-summary",
        "screenconnect-session-message",
        "screenconnect-session-note",
        "security-alert-assessment",
        "servicenow-incident-add-work-note",
        "servicenow-incident-assign",
        "servicenow-incident-lookup",
        "servicenow-incident-update-resolution",
        "servicenow-incident-update-state",
        "sharepoint-document-content",
        "sharepoint-documentation-search",
        "stale-ticket-sweep",
        "suggest-resolution",
        "syncro-ticket-add-note",
        "syncro-ticket-comments",
        "syncro-ticket-lookup",
        "ticket-escalation",
        "ticket-quality",
        "ticket-sentiment",
        "ticket-sla-assessment",
        "ticket-summary",
        "ticket-triage",
        "timezest-scheduling-request-create",
        "timezest-scheduling-request-lookup",
        "workiq-fetch",
    ]
    assert service.describe("ticket-triage").kind == "deterministic"


def test_every_registered_action_handles_empty_input_without_raising(settings) -> None:
    service = SmartActionService(Store(settings.data_path), settings)

    payloads: tuple[dict[str, object], ...] = ({}, {"client_id": "acme"}, {"unexpected": "value"})
    for payload in payloads:
        for manifest in service.list():
            result = service.invoke(manifest.action_id, payload, "coverage", client_id="acme")
            assert result.status in {"failed", "success", "blocked", "pending", "not_authorized"}


def test_autotask_ticket_writes_are_approval_gated_and_validated(settings) -> None:
    class FakeAutotaskWrites:
        def __init__(self, *, health_status="ready", result_status="succeeded"):
            self.health_status = health_status
            self.result_status = result_status
            self.calls: list[AutotaskWriteRequest] = []

        def write_health(self):
            return SimpleNamespace(status=self.health_status, message="write ready")

        def execute_write(self, request):
            self.calls.append(request)
            return SimpleNamespace(
                status=self.result_status,
                message="write completed" if self.result_status == "succeeded" else "provider rejected write",
                status_code=200 if self.result_status == "succeeded" else 400,
                remote_id="456",
            )

    store = Store(settings.data_path)
    _seed_tickets(store)
    with store._connect() as connection:  # noqa: SLF001
        connection.execute("update tickets set id = '123', client_id = 'acme' where id = 'TCK-1001'")
    provider = FakeAutotaskWrites()
    context = _action_context(store, settings, client_id="acme")
    action = AutotaskTicketWriteAction(
        action_id="test-autotask",
        title="test",
        action_type="add_note",
    )
    fields: dict[str, object] = {"description": "note", "note_type": 3, "publish": 0}
    preview = action.run(
        replace(context, autotask_client=provider),
        {"ticket_id": "123", "fields": fields},
    )
    assert preview.status == "success"
    assert preview.output["approval_required"] is True
    completed = action.run(
        replace(context, autotask_client=provider),
        {"ticket_id": "123", "fields": fields, "_approval_completed": True},
    )
    assert completed.status == "success"
    assert provider.calls == [AutotaskWriteRequest("123", "add_note", fields)]
    status_action = AutotaskTicketWriteAction(
        action_id="test-autotask-status",
        title="test status",
        action_type="update_status",
    )
    status_fields: dict[str, object] = {"status": 7}
    assert status_action.run(
        replace(context, autotask_client=provider),
        {"ticket_id": "123", "fields": status_fields},
    ).output["approval_required"] is True
    assert status_action.run(
        replace(context, autotask_client=provider),
        {"ticket_id": "123", "fields": status_fields, "_approval_completed": True},
    ).status == "success"
    assert provider.calls[-1] == AutotaskWriteRequest("123", "update_status", status_fields)
    resolution_action = AutotaskTicketWriteAction(
        action_id="test-autotask-resolution",
        title="test resolution",
        action_type="update_resolution",
    )
    resolution_fields: dict[str, object] = {"resolution": "Resolved by local runbook."}
    assert resolution_action.run(
        replace(context, autotask_client=provider),
        {"ticket_id": "123", "fields": resolution_fields},
    ).output["approval_required"] is True
    assert resolution_action.run(
        replace(context, autotask_client=provider),
        {"ticket_id": "123", "fields": resolution_fields, "_approval_completed": True},
    ).status == "success"
    assert provider.calls[-1] == AutotaskWriteRequest(
        "123", "update_resolution", resolution_fields
    )
    assignment_action = AutotaskTicketWriteAction(
        action_id="test-autotask-assignment",
        title="test assignment",
        action_type="assign_technician",
    )
    assignment_fields: dict[str, object] = {"assigned_resource_id": 456}
    assert assignment_action.run(
        replace(context, autotask_client=provider),
        {"ticket_id": "123", "fields": assignment_fields},
    ).output["approval_required"] is True
    assert assignment_action.run(
        replace(context, autotask_client=provider),
        {
            "ticket_id": "123",
            "fields": assignment_fields,
            "_approval_completed": True,
        },
    ).status == "success"
    assert provider.calls[-1] == AutotaskWriteRequest(
        "123", "assign_technician", assignment_fields
    )
    time_action = AutotaskTicketWriteAction(
        action_id="test-autotask-time-entry",
        title="test time entry",
        action_type="add_time_entry",
    )
    time_fields: dict[str, object] = {
        "resource_id": 456,
        "role_id": 789,
        "date_worked": "2026-08-09",
        "hours_worked": 1.5,
        "summary_notes": "Investigated locally",
    }
    assert time_action.run(
        replace(context, autotask_client=provider),
        {"ticket_id": "123", "fields": time_fields},
    ).output["approval_required"] is True
    assert time_action.run(
        replace(context, autotask_client=provider),
        {"ticket_id": "123", "fields": time_fields, "_approval_completed": True},
    ).status == "success"
    assert provider.calls[-1] == AutotaskWriteRequest(
        "123", "add_time_entry", time_fields
    )
    assert action.run(
        replace(context, client_id="other", autotask_client=provider),
        {"ticket_id": "123", "fields": fields},
    ).status == "failed"
    assert action.run(
        replace(context, autotask_client=provider),
        {"ticket_id": "123", "fields": {"description": "bad"}},
    ).status == "failed"
    assert action.run(
        replace(context, autotask_client=FakeAutotaskWrites(health_status="blocked")),
        {"ticket_id": "123", "fields": fields},
    ).status == "failed"
    assert action.run(
        replace(context, autotask_client=FakeAutotaskWrites(result_status="failed")),
        {"ticket_id": "123", "fields": fields, "_approval_completed": True},
    ).status == "failed"


def test_syncro_ticket_comments_are_tenant_scoped_and_fail_closed(settings) -> None:
    store = Store(settings.data_path)
    _seed_tickets(store)
    with store._connect() as connection:  # noqa: SLF001
        connection.execute("update tickets set client_id = 'acme'")
    provider = SimpleNamespace(
        list_ticket_comments=lambda ticket_id, **kwargs: SimpleNamespace(
            result=SimpleNamespace(status="ready", message="ok", count=1),
            items=[{"id": "comment-1", "ticket_id": ticket_id, "body": "Reviewed"}],
            meta={"page": 1, "per_page": 1, "total_pages": 1},
        )
    )
    context = _action_context(store, settings, client_id="acme")
    success = SyncroTicketCommentsAction().run(
        replace(context, syncro_client=provider),
        {"ticket_id": "TCK-1001", "limit": 1},
    )
    assert success.status == "success"
    assert success.output["count"] == 1
    assert success.evidence[0]["operation"] == "tickets.comments"

    foreign = SyncroTicketCommentsAction().run(
        replace(context, client_id="other", syncro_client=provider),
        {"ticket_id": "TCK-1001"},
    )
    invalid_limit = SyncroTicketCommentsAction().run(
        replace(context, syncro_client=provider),
        {"ticket_id": "TCK-1001", "limit": 51},
    )
    malformed = SyncroTicketCommentsAction().run(
        replace(
            context,
            syncro_client=SimpleNamespace(
                list_ticket_comments=lambda ticket_id, **kwargs: SimpleNamespace(
                    result=SimpleNamespace(status="ready", message="ok", count=1),
                    items="not-a-list",
                    meta={},
                )
            ),
        ),
        {"ticket_id": "TCK-1001"},
    )
    assert foreign.status == "failed"
    assert invalid_limit.status == "failed"
    assert malformed.status == "failed"


def test_notion_page_comments_are_previewed_approval_gated_and_scoped(settings) -> None:
    store = Store(settings.data_path)

    class FakeNotionComments:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str, str]] = []

        def preview_page_comment(self, page_id: str, markdown: str, *, client_id: str):
            return SimpleNamespace(
                page_id=page_id,
                status="preview",
                message="ready for approval",
                comment_id="",
            )

        def create_page_comment(self, page_id: str, markdown: str, *, client_id: str):
            self.calls.append((page_id, markdown, client_id))
            return SimpleNamespace(
                page_id=page_id,
                status="created",
                message="accepted",
                comment_id="33333333-4444-5555-6666-777777777777",
            )

    provider = FakeNotionComments()
    context = _action_context(store, settings, client_id="acme")
    payload: dict[str, object] = {
        "page_id": "11111111-2222-3333-4444-555555555555",
        "client_id": "acme",
        "markdown": "Reviewed **locally**.",
    }

    draft = NotionPageCommentAction().run(replace(context, notion_client=provider), payload)
    blocked_write = NotionPageCommentAction().run(
        replace(context, notion_client=provider), {**payload, "_approval_completed": True}
    )
    assert draft.status == "success"
    assert draft.output["approval_required"] is True
    assert blocked_write.status == "failed"
    assert provider.calls == []

    approved = NotionPageCommentAction().run(
        replace(context, settings=replace(settings, allow_write_actions=True), notion_client=provider),
        {**payload, "_approval_completed": True},
    )
    foreign = NotionPageCommentAction().run(
        replace(context, notion_client=provider), {**payload, "client_id": "other"}
    )

    assert approved.status == "success"
    assert approved.output["comment_id"] == "33333333-4444-5555-6666-777777777777"
    assert provider.calls == [(payload["page_id"], payload["markdown"], "acme")]
    assert foreign.status == "failed"


def test_notion_page_comment_action_rejects_bad_payload_and_provider_edges(settings) -> None:
    store = Store(settings.data_path)
    context = _action_context(store, settings, client_id="acme")
    action = NotionPageCommentAction()
    valid: dict[str, object] = {
        "page_id": "11111111-2222-3333-4444-555555555555",
        "client_id": "acme",
        "markdown": "comment",
    }

    for payload in (
        {**valid, "page_id": ""},
        {**valid, "client_id": ""},
        {**valid, "markdown": ""},
    ):
        assert action.run(context, payload).status == "failed"

    class RaisingProvider:
        def preview_page_comment(self, *args, **kwargs):
            raise RuntimeError("provider failed")

        def create_page_comment(self, *args, **kwargs):
            raise RuntimeError("provider failed")

    raising = action.run(replace(context, notion_client=RaisingProvider()), valid)
    assert raising.status == "failed"
    assert raising.error_detail == "Notion page comment operation failed"

    class FailedProvider:
        def preview_page_comment(self, *args, **kwargs):
            return SimpleNamespace(status="failed", message="provider rejected", comment_id="")

        def create_page_comment(self, *args, **kwargs):
            return SimpleNamespace(status="failed", message="provider rejected", comment_id="")

    failed = action.run(replace(context, notion_client=FailedProvider()), valid)
    assert failed.status == "failed"
    assert failed.error_detail == "provider rejected"


def test_syncro_ticket_writes_are_approval_gated_and_tenant_scoped(settings) -> None:
    class FakeSyncroWrites:
        def __init__(self, *, health_status="ready", result_status="succeeded"):
            self.health_status = health_status
            self.result_status = result_status
            self.calls: list[SyncroWriteRequest] = []

        def write_health(self):
            return SimpleNamespace(status=self.health_status, message="write ready")

        def execute_write(self, request):
            self.calls.append(request)
            return SimpleNamespace(
                status=self.result_status,
                message="write completed" if self.result_status == "succeeded" else "provider rejected write",
                status_code=201 if self.result_status == "succeeded" else 403,
                remote_id="99",
            )

    store = Store(settings.data_path)
    _seed_tickets(store)
    with store._connect() as connection:  # noqa: SLF001
        connection.execute("update tickets set id = '42', client_id = 'acme' where id = 'TCK-1001'")
    provider = FakeSyncroWrites()
    context = _action_context(store, settings, client_id="acme")
    action = SyncroTicketWriteAction(
        action_id="test-syncro-note",
        title="test",
        action_type="add_note",
    )
    fields: dict[str, object] = {"subject": "Internal review", "body": "Reviewed locally"}
    preview = action.run(
        replace(context, syncro_client=provider),
        {"ticket_id": "42", "fields": fields},
    )
    assert preview.status == "success"
    assert preview.output["approval_required"] is True
    assert provider.calls == []
    completed = action.run(
        replace(context, syncro_client=provider),
        {"ticket_id": "42", "fields": fields, "_approval_completed": True},
    )
    assert completed.status == "success"
    assert completed.output["approved"] is True
    assert provider.calls == [SyncroWriteRequest("42", "add_note", fields)]
    assert action.run(
        replace(context, client_id="other", syncro_client=provider),
        {"ticket_id": "42", "fields": fields},
    ).status == "failed"
    assert action.run(
        replace(context, syncro_client=provider),
        {"ticket_id": "42", "fields": {"subject": "x", "body": "y", "token": "secret"}},
    ).status == "failed"
    assert action.run(
        replace(context, syncro_client=FakeSyncroWrites(health_status="blocked")),
        {"ticket_id": "42", "fields": fields},
    ).status == "failed"
    assert action.run(
        replace(context, syncro_client=FakeSyncroWrites(result_status="failed")),
        {"ticket_id": "42", "fields": fields, "_approval_completed": True},
    ).status == "failed"


def test_connectwise_ticket_writes_are_approval_gated_and_validated(settings) -> None:
    class FakeConnectWiseWrites:
        def __init__(self, *, health_status="ready", result_status="succeeded", result_error=False):
            self.health_status = health_status
            self.result_status = result_status
            self.result_error = result_error
            self.calls: list[ConnectWiseWriteRequest] = []

        def write_health(self):
            return SimpleNamespace(status=self.health_status, message="write ready")

        def execute_write(self, request):
            self.calls.append(request)
            if self.result_error:
                raise RuntimeError("write unavailable")
            return SimpleNamespace(
                status=self.result_status,
                message="write completed" if self.result_status == "succeeded" else "provider rejected write",
                status_code=200 if self.result_status == "succeeded" else 400,
                remote_id="remote-1",
            )

    store = Store(settings.data_path)
    _seed_tickets(store)
    with store._connect() as connection:  # noqa: SLF001
        connection.execute("update tickets set client_id = 'acme'")
    provider = FakeConnectWiseWrites()
    context = _action_context(store, settings, client_id="acme")
    specs = [
        ("assign_technician", {"owner_id": "owner-1"}),
        ("update_status", {"status_id": "status-1"}),
        ("update_ticket_fields", {"priority_id": 3}),
    ]
    for action_type, fields in specs:
        action = ConnectWiseTicketWriteAction(
            action_id="test-connectwise",
            title="test",
            action_type=action_type,
        )
        preview = action.run(
            replace(context, connectwise_client=provider),
            {"ticket_id": "TCK-1001", "fields": fields},
        )
        assert preview.status == "success", preview.error_detail
        assert action.run(
            replace(context, connectwise_client=provider),
            {"ticket_id": "TCK-1001", "fields": fields, "_approval_completed": True},
        ).status == "success"
    assert provider.calls[0] == ConnectWiseWriteRequest(
        ticket_id="TCK-1001",
        action_type="assign_technician",
        fields={"owner_id": "owner-1"},
    )
    assert ConnectWiseTicketWriteAction(
        action_id="test-connectwise",
        title="test",
        action_type="update_status",
    ).run(
        replace(context, client_id="other", connectwise_client=provider),
        {"ticket_id": "TCK-1001", "fields": {"status_id": "status-1"}},
    ).status == "failed"
    action = ConnectWiseTicketWriteAction(
        action_id="test-connectwise",
        title="test",
        action_type="update_status",
    )
    assert action.run(
        replace(context, connectwise_client=provider),
        {"ticket_id": "TCK-1001", "fields": {}},
    ).status == "failed"
    assert action.run(
        replace(context, connectwise_client=FakeConnectWiseWrites(health_status="blocked")),
        {"ticket_id": "TCK-1001", "fields": {"status_id": "status-1"}},
    ).status == "failed"
    assert action.run(
        replace(context, connectwise_client=FakeConnectWiseWrites(result_status="failed")),
        {"ticket_id": "TCK-1001", "fields": {"status_id": "status-1"}, "_approval_completed": True},
    ).status == "failed"
    assert action.run(
        replace(context, connectwise_client=FakeConnectWiseWrites(result_error=True)),
        {"ticket_id": "TCK-1001", "fields": {"status_id": "status-1"}, "_approval_completed": True},
    ).status == "failed"


def test_servicenow_incident_writes_are_approval_gated_and_validated(settings) -> None:
    class FakeServiceNowWrites:
        def __init__(self, *, health_status="ready", result_status="succeeded"):
            self.health_status = health_status
            self.result_status = result_status
            self.calls: list[ServiceNowWriteRequest] = []

        def write_health(self):
            return SimpleNamespace(status=self.health_status, message="write ready")

        def execute_write(self, request):
            self.calls.append(request)
            return SimpleNamespace(
                status=self.result_status,
                message="write completed" if self.result_status == "succeeded" else "provider rejected write",
                status_code=200 if self.result_status == "succeeded" else 400,
                remote_id="abc123",
            )

    store = Store(settings.data_path)
    _seed_tickets(store)
    with store._connect() as connection:  # noqa: SLF001
        connection.execute("update tickets set client_id = 'acme'")
    provider = FakeServiceNowWrites()
    context = _action_context(store, settings, client_id="acme")
    action = ServiceNowIncidentWriteAction(
        action_id="test-servicenow",
        title="test",
        action_type="add_work_note",
    )
    fields: dict[str, object] = {"work_notes": "Investigated locally"}
    preview = action.run(
        replace(context, servicenow_client=provider),
        {"ticket_id": "TCK-1001", "fields": fields},
    )
    assert preview.status == "success"
    assert preview.output["approval_required"] is True
    completed = action.run(
        replace(context, servicenow_client=provider),
        {"ticket_id": "TCK-1001", "fields": fields, "_approval_completed": True},
    )
    assert completed.status == "success"
    assert provider.calls == [
        ServiceNowWriteRequest("TCK-1001", "add_work_note", fields)
    ]
    assert action.run(
        replace(context, client_id="other", servicenow_client=provider),
        {"ticket_id": "TCK-1001", "fields": fields},
    ).status == "failed"
    assert action.run(
        replace(context, servicenow_client=provider),
        {"ticket_id": "TCK-1001", "fields": {"comments": "unsafe"}},
    ).status == "failed"
    assert action.run(
        replace(context, servicenow_client=FakeServiceNowWrites(health_status="blocked")),
        {"ticket_id": "TCK-1001", "fields": fields},
    ).status == "failed"
    assert action.run(
        replace(context, servicenow_client=FakeServiceNowWrites(result_status="failed")),
        {"ticket_id": "TCK-1001", "fields": fields, "_approval_completed": True},
    ).status == "failed"

    assignment = ServiceNowIncidentWriteAction(
        action_id="test-servicenow-assignment",
        title="test",
        action_type="assign_incident",
    )
    assignment_fields: dict[str, object] = {"assigned_to": "agent-123"}
    assert assignment.run(
        replace(context, servicenow_client=provider),
        {"ticket_id": "TCK-1001", "fields": assignment_fields},
    ).output["approval_required"] is True
    completed_assignment = assignment.run(
        replace(context, servicenow_client=provider),
        {
            "ticket_id": "TCK-1001",
            "fields": assignment_fields,
            "_approval_completed": True,
        },
    )
    assert completed_assignment.status == "success"
    assert provider.calls[-1] == ServiceNowWriteRequest(
        "TCK-1001", "assign_incident", assignment_fields
    )

    resolution = ServiceNowIncidentWriteAction(
        action_id="test-servicenow-resolution",
        title="test",
        action_type="update_resolution",
    )
    resolution_fields: dict[str, object] = {
        "close_code": "Solved (Permanently)",
        "close_notes": "Resolved using the approved local runbook.",
    }
    assert resolution.run(
        replace(context, servicenow_client=provider),
        {"ticket_id": "TCK-1001", "fields": resolution_fields},
    ).output["approval_required"] is True
    completed_resolution = resolution.run(
        replace(context, servicenow_client=provider),
        {
            "ticket_id": "TCK-1001",
            "fields": resolution_fields,
            "_approval_completed": True,
        },
    )
    assert completed_resolution.status == "success"
    assert provider.calls[-1] == ServiceNowWriteRequest(
        "TCK-1001", "update_resolution", resolution_fields
    )
    assert resolution.run(
        replace(context, servicenow_client=provider),
        {
            "ticket_id": "TCK-1001",
            "fields": {"close_code": "Solved", "close_notes": "\x00"},
        },
    ).status == "failed"


def test_halopsa_ticket_writes_are_approval_gated_and_validated(settings) -> None:
    class FakeHaloWrites:
        def __init__(
            self,
            *,
            health_status="ready",
            health_error=False,
            result_status="succeeded",
            result_error=False,
        ) -> None:
            self.health_status = health_status
            self.health_error = health_error
            self.result_status = result_status
            self.result_error = result_error
            self.calls: list[HaloWriteRequest] = []

        def write_health(self):
            if self.health_error:
                raise RuntimeError("health unavailable")
            return SimpleNamespace(status=self.health_status, message="write ready")

        def execute_write(self, request):
            self.calls.append(request)
            if self.result_error:
                raise RuntimeError("write unavailable")
            return SimpleNamespace(
                status=self.result_status,
                message=(
                    "ticket write succeeded"
                    if self.result_status == "succeeded"
                    else "provider rejected ticket write"
                ),
                status_code=200 if self.result_status == "succeeded" else 400,
                remote_id="remote-1",
            )

    specs = [
        ("add_note", "halopsa-ticket-add-note", {"note": "hello"}),
        (
            "assign_technician",
            "halopsa-ticket-assign-technician",
            {"technician_id": "tech-1"},
        ),
        ("draft_response", "halopsa-ticket-draft-response", {"response": "hello"}),
        ("update_status", "halopsa-ticket-status-update", {"status_id": "status-1"}),
        (
            "update_ticket_fields",
            "halopsa-ticket-update-fields",
            {"priority": "high"},
        ),
    ]
    store = Store(settings.data_path)
    _seed_tickets(store)
    with store._connect() as connection:  # noqa: SLF001
        connection.execute("update tickets set client_id = 'acme'")
    provider = FakeHaloWrites()
    service = SmartActionService(store, settings, halopsa_client=provider)
    context = _action_context(store, settings, client_id="acme")
    first_action = None
    for action_type, action_id, fields in specs:
        action = HaloPSATicketWriteAction(
            action_id=f"test-{action_type}",
            title="test",
            action_type=action_type,
        )
        first_action = first_action or action
        pending = service.invoke(
            action_id,
            {"ticket_id": "TCK-1001", "fields": fields},
            "requester",
            client_id="acme",
        )
        if action_type == "add_note":
            assert pending.status == "pending_approval"
            assert pending.approval_id is not None
            service.update_approval(
                pending.approval_id,
                "approved",
                approver="technician",
                approver_role=Role.TECHNICIAN,
            )
        assert action.run(
            replace(context, halopsa_client=provider),
            {"ticket_id": "TCK-1001", "fields": fields, "_approval_completed": True},
        ).status == "success"
    assert first_action is not None
    assert provider.calls[0] == HaloWriteRequest(
        ticket_id="TCK-1001",
        action_type="add_note",
        fields={"note": "hello"},
    )
    assert first_action.run(
        replace(context, halopsa_client=provider),
        {"ticket_id": "TCK-1001", "fields": {}},
    ).status == "failed"
    assert first_action.run(
        replace(context, client_id="other", halopsa_client=provider),
        {"ticket_id": "TCK-1001", "fields": {"note": "hello"}},
    ).status == "failed"
    assert first_action.run(
        replace(context, halopsa_client=provider),
        {"ticket_id": "TCK-1001", "fields": {"note": "hello"}, "unexpected": True},
    ).status == "failed"
    assert first_action.run(
        replace(context, halopsa_client=FakeHaloWrites(health_status="blocked")),
        {"ticket_id": "TCK-1001", "fields": {"note": "hello"}},
    ).status == "failed"
    assert first_action.run(
        replace(context, halopsa_client=FakeHaloWrites(health_error=True)),
        {"ticket_id": "TCK-1001", "fields": {"note": "hello"}},
    ).status == "failed"
    assert first_action.run(
        replace(context, halopsa_client=FakeHaloWrites(result_status="failed")),
        {"ticket_id": "TCK-1001", "fields": {"note": "hello"}, "_approval_completed": True},
    ).status == "failed"
    assert first_action.run(
        replace(context, halopsa_client=FakeHaloWrites(result_error=True)),
        {"ticket_id": "TCK-1001", "fields": {"note": "hello"}, "_approval_completed": True},
    ).status == "failed"


def test_m365_group_membership_is_approval_gated_and_immutable_id_scoped(settings) -> None:
    class FakeM365GroupWrites:
        def __init__(self, *, health_status="ready", change_status="succeeded") -> None:
            self.health_status = health_status
            self.change_status = change_status
            self.calls: list[dict[str, str]] = []

        def write_health(self):
            return SimpleNamespace(status=self.health_status, message="write ready")

        def change_group_membership(self, **kwargs):
            self.calls.append(kwargs)
            return SimpleNamespace(
                status=self.change_status,
                message="membership changed" if self.change_status == "succeeded" else "provider rejected membership",
                status_code=204 if self.change_status == "succeeded" else 400,
            )

    store = Store(settings.data_path)
    provider = FakeM365GroupWrites()
    service = SmartActionService(store, settings, m365_client=provider)
    payload: dict[str, object] = {
        "group_id": "group-immutable-id",
        "user_id": "user-immutable-id",
        "operation": "add",
    }

    pending = service.invoke("m365-group-membership", payload, "requester", client_id="acme")
    assert pending.status == "pending_approval"
    assert pending.approval_id is not None
    assert provider.calls == []
    with pytest.raises(PermissionError, match="admin authority"):
        service.update_approval(
            pending.approval_id,
            "approved",
            approver="technician",
            approver_role=Role.TECHNICIAN,
        )
    service.update_approval(
        pending.approval_id,
        "approved",
        approver="admin",
        approver_role=Role.ADMIN,
    )
    assert provider.calls == [
        {
            "group_id": "group-immutable-id",
            "user_id": "user-immutable-id",
            "operation": "add",
        }
    ]
    run = store.get_smart_action_run(pending.run_id or 0)
    assert run is not None and run.status == "success"

    context = _action_context(store, settings, client_id="acme")
    assert M365GroupMembershipAction().run(
        replace(context, m365_client=provider),
        {**payload, "operation": "remove", "_approval_completed": True},
    ).status == "success"
    assert M365GroupMembershipAction().run(
        replace(context, m365_client=provider),
        {**payload, "operation": "invalid"},
    ).status == "failed"
    assert M365GroupMembershipAction().run(
        replace(context, m365_client=provider),
        {**payload, "unexpected": "field"},
    ).status == "failed"
    assert M365GroupMembershipAction().run(
        replace(context, m365_client=FakeM365GroupWrites(health_status="blocked")),
        payload,
    ).status == "failed"
    assert M365GroupMembershipAction().run(
        replace(context, m365_client=FakeM365GroupWrites(change_status="failed")),
        {**payload, "_approval_completed": True},
    ).status == "failed"


def test_m365_license_change_is_approval_gated_and_sku_scoped(settings) -> None:
    class FakeM365LicenseWrites:
        def __init__(
            self,
            *,
            health_status="ready",
            health_error=False,
            change_status="succeeded",
            change_error=False,
        ) -> None:
            self.health_status = health_status
            self.health_error = health_error
            self.change_status = change_status
            self.change_error = change_error
            self.calls: list[dict[str, object]] = []

        def write_health(self):
            if self.health_error:
                raise RuntimeError("health unavailable")
            return SimpleNamespace(status=self.health_status, message="write ready")

        def change_user_licenses(self, **kwargs):
            self.calls.append(kwargs)
            if self.change_error:
                raise RuntimeError("change unavailable")
            return SimpleNamespace(
                status=self.change_status,
                message="licenses changed" if self.change_status == "succeeded" else "provider rejected license change",
                status_code=204 if self.change_status == "succeeded" else 400,
            )

    store = Store(settings.data_path)
    provider = FakeM365LicenseWrites()
    service = SmartActionService(store, settings, m365_client=provider)
    payload: dict[str, object] = {
        "user_id": "user-immutable-id",
        "sku_ids": ["00000000-0000-0000-0000-000000000001"],
        "operation": "add",
    }

    pending = service.invoke(
        "m365-license-change",
        {**payload, "ticket_id": "TCK-1001"},
        "requester",
        client_id="acme",
    )
    assert pending.status == "pending_approval"
    assert pending.approval_id is not None
    assert provider.calls == []
    with pytest.raises(PermissionError, match="admin authority"):
        service.update_approval(
            pending.approval_id,
            "approved",
            approver="technician",
            approver_role=Role.TECHNICIAN,
        )
    service.update_approval(
        pending.approval_id,
        "approved",
        approver="admin",
        approver_role=Role.ADMIN,
    )
    assert provider.calls == [
        {
            "user_id": "user-immutable-id",
            "sku_ids": ["00000000-0000-0000-0000-000000000001"],
            "operation": "add",
        }
    ]

    context = _action_context(store, settings, client_id="acme")
    assert M365LicenseChangeAction().run(
        replace(context, m365_client=provider),
        {**payload, "operation": "remove", "_approval_completed": True},
    ).status == "success"
    assert M365LicenseChangeAction().run(
        replace(context, m365_client=provider),
        {**payload, "sku_ids": ["not-a-uuid"]},
    ).status == "failed"
    assert M365LicenseChangeAction().run(
        replace(context, m365_client=provider),
        {**payload, "unexpected": "field"},
    ).status == "failed"
    assert M365LicenseChangeAction().run(
        replace(context, m365_client=FakeM365LicenseWrites(health_status="blocked")),
        payload,
    ).status == "failed"
    assert M365LicenseChangeAction().run(
        replace(context, m365_client=FakeM365LicenseWrites(health_error=True)),
        payload,
    ).status == "failed"
    assert M365LicenseChangeAction().run(
        replace(context, m365_client=FakeM365LicenseWrites(change_error=True)),
        {**payload, "_approval_completed": True},
    ).status == "failed"
    assert M365LicenseChangeAction().run(
        replace(context, m365_client=FakeM365LicenseWrites(change_status="failed")),
        {**payload, "_approval_completed": True},
    ).status == "failed"


def test_m365_session_revocation_is_approval_gated_and_user_scoped(settings) -> None:
    class FakeM365SessionWrites:
        def __init__(
            self,
            *,
            health_status="ready",
            health_error=False,
            revoke_status="succeeded",
            revoke_error=False,
        ) -> None:
            self.health_status = health_status
            self.health_error = health_error
            self.revoke_status = revoke_status
            self.revoke_error = revoke_error
            self.calls: list[dict[str, str]] = []

        def write_health(self):
            if self.health_error:
                raise RuntimeError("health unavailable")
            return SimpleNamespace(status=self.health_status, message="write ready")

        def revoke_user_sessions(self, **kwargs):
            self.calls.append(kwargs)
            if self.revoke_error:
                raise RuntimeError("revoke unavailable")
            return SimpleNamespace(
                status=self.revoke_status,
                message="sessions revoked" if self.revoke_status == "succeeded" else "provider rejected revocation",
                status_code=204 if self.revoke_status == "succeeded" else 400,
            )

    store = Store(settings.data_path)
    provider = FakeM365SessionWrites()
    service = SmartActionService(store, settings, m365_client=provider)
    payload: dict[str, object] = {"user_id": "user-immutable-id"}

    pending = service.invoke("m365-session-revocation", payload, "requester", client_id="acme")
    assert pending.status == "pending_approval"
    assert pending.approval_id is not None
    assert provider.calls == []
    with pytest.raises(PermissionError, match="admin authority"):
        service.update_approval(
            pending.approval_id,
            "approved",
            approver="technician",
            approver_role=Role.TECHNICIAN,
        )
    service.update_approval(
        pending.approval_id,
        "approved",
        approver="admin",
        approver_role=Role.ADMIN,
    )
    assert provider.calls == [{"user_id": "user-immutable-id"}]

    context = _action_context(store, settings, client_id="acme")
    assert M365SessionRevocationAction().run(
        replace(context, m365_client=provider),
        {**payload, "_approval_completed": True},
    ).status == "success"
    assert M365SessionRevocationAction().run(
        replace(context, m365_client=provider),
        {**payload, "unexpected": "field"},
    ).status == "failed"
    assert M365SessionRevocationAction().run(
        replace(context, m365_client=provider),
        {"user_id": ""},
    ).status == "failed"
    assert M365SessionRevocationAction().run(
        replace(context, m365_client=FakeM365SessionWrites(health_status="blocked")),
        payload,
    ).status == "failed"
    assert M365SessionRevocationAction().run(
        replace(context, m365_client=FakeM365SessionWrites(health_error=True)),
        payload,
    ).status == "failed"
    assert M365SessionRevocationAction().run(
        replace(context, m365_client=FakeM365SessionWrites(revoke_error=True)),
        {**payload, "_approval_completed": True},
    ).status == "failed"
    assert M365SessionRevocationAction().run(
        replace(context, m365_client=FakeM365SessionWrites(revoke_status="failed")),
        {**payload, "_approval_completed": True},
    ).status == "failed"


def test_m365_mailbox_settings_is_approval_gated_and_allowlisted(settings) -> None:
    class FakeM365MailboxWrites:
        def __init__(
            self,
            *,
            health_status="ready",
            health_error=False,
            update_status="succeeded",
            update_error=False,
        ) -> None:
            self.health_status = health_status
            self.health_error = health_error
            self.update_status = update_status
            self.update_error = update_error
            self.calls: list[dict[str, object]] = []

        def write_health(self):
            if self.health_error:
                raise RuntimeError("health unavailable")
            return SimpleNamespace(status=self.health_status, message="write ready")

        def update_mailbox_settings(self, **kwargs):
            self.calls.append(kwargs)
            if self.update_error:
                raise RuntimeError("update unavailable")
            return SimpleNamespace(
                status=self.update_status,
                message="settings updated" if self.update_status == "succeeded" else "provider rejected settings",
                settings=kwargs["settings"],
                status_code=200 if self.update_status == "succeeded" else 400,
            )

    store = Store(settings.data_path)
    provider = FakeM365MailboxWrites()
    service = SmartActionService(store, settings, m365_client=provider)
    payload: dict[str, object] = {
        "user_identity": "user@example.test",
        "settings": {"locale": "en-US", "time_zone": "Pacific Standard Time"},
    }

    pending = service.invoke("m365-mailbox-settings", payload, "requester", client_id="acme")
    assert pending.status == "pending_approval"
    assert pending.approval_id is not None
    assert provider.calls == []
    with pytest.raises(PermissionError, match="admin authority"):
        service.update_approval(
            pending.approval_id,
            "approved",
            approver="technician",
            approver_role=Role.TECHNICIAN,
        )
    service.update_approval(
        pending.approval_id,
        "approved",
        approver="admin",
        approver_role=Role.ADMIN,
    )
    assert provider.calls == [{"user_identity": "user@example.test", "settings": payload["settings"]}]

    context = _action_context(store, settings, client_id="acme")
    assert M365MailboxSettingsAction().run(
        replace(context, m365_client=provider),
        {**payload, "_approval_completed": True},
    ).status == "success"
    assert M365MailboxSettingsAction().run(
        replace(context, m365_client=provider),
        {**payload, "settings": {"unsupported": "value"}},
    ).status == "failed"
    assert M365MailboxSettingsAction().run(
        replace(context, m365_client=provider),
        {**payload, "unexpected": "field"},
    ).status == "failed"
    assert M365MailboxSettingsAction().run(
        replace(context, m365_client=FakeM365MailboxWrites(health_status="blocked")),
        payload,
    ).status == "failed"
    assert M365MailboxSettingsAction().run(
        replace(context, m365_client=FakeM365MailboxWrites(health_error=True)),
        payload,
    ).status == "failed"
    assert M365MailboxSettingsAction().run(
        replace(context, m365_client=FakeM365MailboxWrites(update_error=True)),
        {**payload, "_approval_completed": True},
    ).status == "failed"
    assert M365MailboxSettingsAction().run(
        replace(context, m365_client=FakeM365MailboxWrites(update_status="failed")),
        {**payload, "_approval_completed": True},
    ).status == "failed"


def test_m365_mail_message_move_is_approval_gated_and_explicitly_scoped(settings) -> None:
    class FakeM365MessageWrites:
        def __init__(
            self,
            *,
            health_status="ready",
            health_error=False,
            move_status="succeeded",
            move_error=False,
            read_state_status="succeeded",
            read_state_error=False,
            delete_status="succeeded",
            delete_error=False,
        ) -> None:
            self.health_status = health_status
            self.health_error = health_error
            self.move_status = move_status
            self.move_error = move_error
            self.read_state_status = read_state_status
            self.read_state_error = read_state_error
            self.delete_status = delete_status
            self.delete_error = delete_error
            self.calls: list[dict[str, str]] = []

        def write_health(self):
            if self.health_error:
                raise RuntimeError("health unavailable")
            return SimpleNamespace(status=self.health_status, message="write ready")

        def move_mail_message(self, **kwargs):
            self.calls.append(kwargs)
            if self.move_error:
                raise RuntimeError("move unavailable")
            return SimpleNamespace(
                status=self.move_status,
                message="message moved" if self.move_status == "succeeded" else "provider rejected move",
                status_code=201 if self.move_status == "succeeded" else 400,
            )

        def update_mail_message_read_state(self, **kwargs):
            self.calls.append(kwargs)
            if self.read_state_error:
                raise RuntimeError("read state unavailable")
            return SimpleNamespace(
                status=self.read_state_status,
                message=(
                    "message read state updated"
                    if self.read_state_status == "succeeded"
                    else "provider rejected read state"
                ),
                is_read=kwargs["is_read"],
                status_code=200 if self.read_state_status == "succeeded" else 400,
            )

        def delete_mail_message(self, **kwargs):
            self.calls.append(kwargs)
            if self.delete_error:
                raise RuntimeError("delete unavailable")
            return SimpleNamespace(
                status=self.delete_status,
                message=(
                    "message deleted"
                    if self.delete_status == "succeeded"
                    else "provider rejected delete"
                ),
                status_code=204 if self.delete_status == "succeeded" else 400,
            )

    store = Store(settings.data_path)
    provider = FakeM365MessageWrites()
    service = SmartActionService(store, settings, m365_client=provider)
    payload: dict[str, object] = {
        "user_identity": "user@example.test",
        "source_folder_id": "inbox-id",
        "message_id": "message-id",
        "destination_folder_id": "archive-id",
    }

    pending = service.invoke("m365-mail-message-move", payload, "requester", client_id="acme")
    assert pending.status == "pending_approval"
    assert pending.approval_id is not None
    assert provider.calls == []
    with pytest.raises(PermissionError, match="admin authority"):
        service.update_approval(
            pending.approval_id,
            "approved",
            approver="technician",
            approver_role=Role.TECHNICIAN,
        )
    service.update_approval(
        pending.approval_id,
        "approved",
        approver="admin",
        approver_role=Role.ADMIN,
    )
    assert provider.calls == [
        {
            "user_identity": "user@example.test",
            "source_folder_id": "inbox-id",
            "message_id": "message-id",
            "destination_folder_id": "archive-id",
        }
    ]

    context = _action_context(store, settings, client_id="acme")
    assert M365MailMessageMoveAction().run(
        replace(context, m365_client=provider),
        {**payload, "_approval_completed": True},
    ).status == "success"
    assert M365MailMessageMoveAction().run(
        replace(context, m365_client=provider),
        {**payload, "source_folder_id": ""},
    ).status == "failed"
    assert M365MailMessageMoveAction().run(
        replace(context, m365_client=provider),
        {**payload, "unexpected": "field"},
    ).status == "failed"
    assert M365MailMessageMoveAction().run(
        replace(context, m365_client=FakeM365MessageWrites(health_status="blocked")),
        payload,
    ).status == "failed"
    assert M365MailMessageMoveAction().run(
        replace(context, m365_client=FakeM365MessageWrites(health_error=True)),
        payload,
    ).status == "failed"
    assert M365MailMessageMoveAction().run(
        replace(context, m365_client=FakeM365MessageWrites(move_error=True)),
        {**payload, "_approval_completed": True},
    ).status == "failed"
    assert M365MailMessageMoveAction().run(
        replace(context, m365_client=FakeM365MessageWrites(move_status="failed")),
        {**payload, "_approval_completed": True},
    ).status == "failed"

    read_payload: dict[str, object] = {
        "user_identity": "user@example.test",
        "source_folder_id": "inbox-id",
        "message_id": "message-id",
        "is_read": True,
    }
    assert service.invoke(
        "m365-mail-message-read-state", read_payload, "requester", client_id="acme"
    ).status == "pending_approval"
    assert M365MailMessageReadStateAction().run(
        replace(context, m365_client=provider),
        {**read_payload, "_approval_completed": True},
    ).status == "success"
    assert M365MailMessageReadStateAction().run(
        replace(context, m365_client=provider),
        {**read_payload, "is_read": "true"},
    ).status == "failed"
    assert M365MailMessageReadStateAction().run(
        replace(context, m365_client=FakeM365MessageWrites(read_state_status="failed")),
        {**read_payload, "_approval_completed": True},
    ).status == "failed"
    assert M365MailMessageReadStateAction().run(
        replace(context, m365_client=FakeM365MessageWrites(read_state_error=True)),
        {**read_payload, "_approval_completed": True},
    ).status == "failed"

    delete_payload: dict[str, object] = {
        "user_identity": "user@example.test",
        "source_folder_id": "inbox-id",
        "message_id": "message-id",
    }
    assert service.invoke(
        "m365-mail-message-delete", delete_payload, "requester", client_id="acme"
    ).status == "pending_approval"
    assert M365MailMessageDeleteAction().run(
        replace(context, m365_client=provider),
        {**delete_payload, "_approval_completed": True},
    ).status == "success"
    assert M365MailMessageDeleteAction().run(
        replace(context, m365_client=provider),
        {**delete_payload, "message_id": ""},
    ).status == "failed"
    assert M365MailMessageDeleteAction().run(
        replace(context, m365_client=FakeM365MessageWrites(delete_status="failed")),
        {**delete_payload, "_approval_completed": True},
    ).status == "failed"
    assert M365MailMessageDeleteAction().run(
        replace(context, m365_client=FakeM365MessageWrites(delete_error=True)),
        {**delete_payload, "_approval_completed": True},
    ).status == "failed"


def test_m365_managed_device_actions_are_approval_gated(settings) -> None:
    class FakeM365DeviceWrites:
        def __init__(
            self,
            *,
            health_status="ready",
            health_error=False,
            result_status="succeeded",
            result_error=False,
        ) -> None:
            self.health_status = health_status
            self.health_error = health_error
            self.result_status = result_status
            self.result_error = result_error
            self.calls: list[dict[str, str]] = []

        def write_health(self):
            if self.health_error:
                raise RuntimeError("health unavailable")
            return SimpleNamespace(status=self.health_status, message="write ready")

        def _run(self, **kwargs):
            self.calls.append(kwargs)
            if self.result_error:
                raise RuntimeError("device action unavailable")
            return SimpleNamespace(
                status=self.result_status,
                message=(
                    "device action completed"
                    if self.result_status == "succeeded"
                    else "provider rejected device action"
                ),
                status_code=202 if self.result_status == "succeeded" else 400,
            )

        def retire_managed_device(self, **kwargs):
            return self._run(**kwargs)

        def sync_managed_device(self, **kwargs):
            return self._run(**kwargs)

        def reboot_managed_device(self, **kwargs):
            return self._run(**kwargs)

        def remote_lock_managed_device(self, **kwargs):
            return self._run(**kwargs)

    store = Store(settings.data_path)
    provider = FakeM365DeviceWrites()
    service = SmartActionService(store, settings, m365_client=provider)
    context = _action_context(store, settings, client_id="acme")
    specs = [
        (
            "m365-managed-device-retire",
            "retirement",
            "managed-devices.retire",
            "retire_managed_device",
            "validate_m365_managed_device_retirement_payload",
        ),
        (
            "m365-managed-device-sync",
            "sync",
            "managed-devices.sync",
            "sync_managed_device",
            "validate_m365_managed_device_sync_payload",
        ),
        (
            "m365-managed-device-reboot",
            "reboot",
            "managed-devices.reboot",
            "reboot_managed_device",
            "validate_m365_managed_device_reboot_payload",
        ),
        (
            "m365-managed-device-remote-lock",
            "remote_lock",
            "managed-devices.remote-lock",
            "remote_lock_managed_device",
            "validate_m365_managed_device_remote_lock_payload",
        ),
    ]
    for action_id, operation, action_type, provider_method, validator_name in specs:
        pending = service.invoke(action_id, {"device_id": "device-1"}, "requester", client_id="acme")
        assert pending.status == "pending_approval"
        action = M365ManagedDeviceAction(
            action_id=action_id,
            title="test",
            operation=operation,
            action_type=action_type,
            provider_method=provider_method,
            validator_name=validator_name,
        )
        assert action.run(
            replace(context, m365_client=provider),
            {"device_id": "device-1", "_approval_completed": True},
        ).status == "success"

    action = M365ManagedDeviceAction(
        action_id="m365-managed-device-sync",
        title="test",
        operation="sync",
        action_type="managed-devices.sync",
        provider_method="sync_managed_device",
        validator_name="validate_m365_managed_device_sync_payload",
    )
    assert action.run(
        replace(context, m365_client=provider),
        {"device_id": "", "_approval_completed": True},
    ).status == "failed"
    assert action.run(
        replace(context, m365_client=provider),
        {"device_id": "device-1", "unexpected": "field"},
    ).status == "failed"
    assert action.run(
        replace(context, m365_client=FakeM365DeviceWrites(health_status="blocked")),
        {"device_id": "device-1"},
    ).status == "failed"
    assert action.run(
        replace(context, m365_client=FakeM365DeviceWrites(health_error=True)),
        {"device_id": "device-1"},
    ).status == "failed"
    assert action.run(
        replace(context, m365_client=FakeM365DeviceWrites(result_status="failed")),
        {"device_id": "device-1", "_approval_completed": True},
    ).status == "failed"
    assert action.run(
        replace(context, m365_client=FakeM365DeviceWrites(result_error=True)),
        {"device_id": "device-1", "_approval_completed": True},
    ).status == "failed"


def test_m365_user_onboarding_is_vault_backed_and_approval_gated(settings, tmp_path) -> None:
    class FakeM365Create:
        def __init__(self, status: str = "succeeded") -> None:
            self.status = status
            self.calls: list[dict[str, object]] = []

        def write_health(self):
            return SimpleNamespace(status="ready", message="write ready")

        def create_user(self, **kwargs):
            self.calls.append(kwargs)
            return SimpleNamespace(
                status=self.status,
                message="created" if self.status == "succeeded" else "provider rejected user",
                remote_id="user-1",
                status_code=201 if self.status == "succeeded" else 400,
            )

    active_settings = replace(settings, vault_path=tmp_path / "vault")
    SecretVault.initialize(active_settings.vault_path).set(
        "WAIT_M365_TEMP_ADELE", "Temporary-Password-123!"
    )
    store = Store(active_settings.data_path)
    provider = FakeM365Create()
    service = SmartActionService(store, active_settings, m365_client=provider)
    payload: dict[str, object] = {
        "user_principal_name": "adele.vance@example.test",
        "display_name": "Adele Vance",
        "mail_nickname": "adele.vance",
        "temporary_vault_name": "WAIT_M365_TEMP_ADELE",
    }

    pending = service.invoke("m365-user-onboarding", payload, "requester", client_id="acme")
    assert pending.status == "pending_approval"
    assert pending.approval_id is not None
    assert provider.calls == []
    pending_request = store.get_approval_request(pending.approval_id)
    assert pending_request is not None
    assert "Temporary-Password-123!" not in pending_request.payload_json
    assert "WAIT_M365_TEMP_ADELE" in pending_request.payload_json
    with pytest.raises(PermissionError, match="admin authority"):
        service.update_approval(
            pending.approval_id,
            "approved",
            approver="technician",
            approver_role=Role.TECHNICIAN,
        )
    service.update_approval(
        pending.approval_id,
        "approved",
        approver="admin",
        approver_role=Role.ADMIN,
    )
    assert provider.calls == [
        {
            "user_principal_name": "adele.vance@example.test",
            "display_name": "Adele Vance",
            "mail_nickname": "adele.vance",
            "temporary_password": "Temporary-Password-123!",
            "account_enabled": True,
            "force_change_password_next_sign_in": True,
        }
    ]
    run = store.get_smart_action_run(pending.run_id or 0)
    assert run is not None and run.status == "success"
    assert "Temporary-Password-123!" not in run.output_json
    assert "Temporary-Password-123!" not in run.evidence_json

    unsupported = service.invoke(
        "m365-user-onboarding",
        {**payload, "temporary_password": "should-never-be-accepted"},
        "requester",
        client_id="acme",
    )
    assert unsupported.status == "failed"
    assert provider.calls[0]["temporary_password"] == "Temporary-Password-123!"

    missing_secret_settings = replace(settings, vault_path=tmp_path / "missing-vault")
    missing_provider = FakeM365Create()
    missing_service = SmartActionService(
        Store(missing_secret_settings.data_path),
        missing_secret_settings,
        m365_client=missing_provider,
    )
    missing = missing_service.invoke(
        "m365-user-onboarding", payload, "requester", client_id="acme"
    )
    assert missing.approval_id is not None
    missing_service.update_approval(
        missing.approval_id,
        "approved",
        approver="admin-2",
        approver_role=Role.ADMIN,
    )
    assert missing_provider.calls == []
    missing_run = missing_service.store.get_smart_action_run(missing.run_id or 0)
    assert missing_run is not None and missing_run.status == "failed"

def test_m365_user_onboarding_rejects_unready_and_failed_provider_paths(settings, tmp_path) -> None:
    class FakeM365Create:
        def __init__(
            self,
            *,
            health_status="ready",
            health_error=False,
            create_error=False,
            create_status="succeeded",
        ) -> None:
            self.health_status = health_status
            self.health_error = health_error
            self.create_error = create_error
            self.create_status = create_status

        def write_health(self):
            if self.health_error:
                raise RuntimeError("health unavailable")
            return SimpleNamespace(status=self.health_status, message="provider unavailable")

        def create_user(self, **kwargs):
            del kwargs
            if self.create_error:
                raise RuntimeError("create unavailable")
            return SimpleNamespace(
                status=self.create_status,
                message="provider rejected user",
                remote_id="user-1",
                status_code=400,
            )

    vault_path = tmp_path / "vault"
    SecretVault.initialize(vault_path).set("WAIT_M365_TEMP_EDGE", "Temporary-Password-123!")
    valid_payload: dict[str, object] = {
        "user_principal_name": "edge@example.test",
        "display_name": "Edge User",
        "mail_nickname": "edge.user",
        "temporary_vault_name": "WAIT_M365_TEMP_EDGE",
        "ticket_id": "TCK-1001",
        "_approval_completed": True,
    }

    def run(payload, provider, *, path=vault_path):
        action_settings = replace(settings, vault_path=path)
        context = replace(
            _action_context(Store(action_settings.data_path), action_settings),
            m365_client=provider,
            client_id="acme",
        )
        return M365UserOnboardingAction().run(context, payload)

    assert run({**valid_payload, "account_enabled": "yes"}, FakeM365Create()).status == "failed"
    assert run({**valid_payload, "user_principal_name": ""}, FakeM365Create()).status == "failed"
    assert run(valid_payload, FakeM365Create(health_error=True)).status == "failed"
    assert run(valid_payload, FakeM365Create(health_status="blocked")).status == "failed"
    missing_vault = tmp_path / "missing-vault"
    SecretVault.initialize(missing_vault)
    assert run(valid_payload, FakeM365Create(), path=missing_vault).status == "failed"
    assert run(valid_payload, FakeM365Create(create_error=True)).status == "failed"
    assert run(valid_payload, FakeM365Create(create_status="failed")).status == "failed"


def test_m365_user_offboarding_is_approval_gated_and_reports_partial_failure(settings) -> None:
    class FakeM365Writes:
        def __init__(
            self,
            revoke_status: str = "succeeded",
            disable_status: str = "succeeded",
            *,
            health_status: str = "ready",
            health_error: bool = False,
            disable_error: bool = False,
            revoke_error: bool = False,
        ) -> None:
            self.revoke_status = revoke_status
            self.disable_status = disable_status
            self.health_status = health_status
            self.health_error = health_error
            self.disable_error = disable_error
            self.revoke_error = revoke_error
            self.calls: list[tuple[str, str]] = []

        def write_health(self):
            if self.health_error:
                raise RuntimeError("health unavailable")
            return SimpleNamespace(status=self.health_status, message="write ready")

        def disable_user(self, *, user_identity: str):
            self.calls.append(("disable", user_identity))
            if self.disable_error:
                raise RuntimeError("disable unavailable")
            return SimpleNamespace(status=self.disable_status, message="disabled")

        def revoke_user_sessions(self, *, user_id: str):
            self.calls.append(("revoke", user_id))
            if self.revoke_error:
                raise RuntimeError("revoke unavailable")
            return SimpleNamespace(status=self.revoke_status, message="revoke result")

    store = Store(settings.data_path)
    provider = FakeM365Writes()
    service = SmartActionService(store, settings, m365_client=provider)
    payload: dict[str, object] = {
        "user_identity": "adele@example.test",
        "user_id": "graph-user-1",
    }

    pending = service.invoke("m365-user-offboarding", payload, "requester", client_id="acme")
    assert pending.status == "pending_approval"
    assert pending.approval_id is not None
    assert provider.calls == []
    with pytest.raises(PermissionError, match="admin authority"):
        service.update_approval(
            pending.approval_id,
            "approved",
            approver="technician",
            approver_role=Role.TECHNICIAN,
        )
    assert provider.calls == []

    approved = service.update_approval(
        pending.approval_id,
        "approved",
        approver="admin",
        approver_role=Role.ADMIN,
    )
    assert approved.status == "approved"
    assert provider.calls == [
        ("disable", "adele@example.test"),
        ("revoke", "graph-user-1"),
    ]

    action_context = replace(_action_context(store, settings), m365_client=provider)
    assert M365UserOffboardingAction().run(
        action_context, {"user_identity": "", "user_id": "graph-user-1"}
    ).status == "failed"
    assert M365UserOffboardingAction().run(
        action_context, {"user_identity": "user@example.test", "user_id": "x" * 321}
    ).status == "failed"

    for unavailable in (
        FakeM365Writes(health_status="blocked"),
        FakeM365Writes(health_error=True),
    ):
        unavailable_result = SmartActionService(
            store, settings, m365_client=unavailable
        ).invoke("m365-user-offboarding", payload, "requester", client_id="acme")
        assert unavailable_result.status == "failed"

    disable_failed = FakeM365Writes(disable_status="failed")
    disable_service = SmartActionService(store, settings, m365_client=disable_failed)
    disable_pending = disable_service.invoke(
        "m365-user-offboarding", payload, "requester", client_id="acme"
    )
    assert disable_pending.approval_id is not None
    disable_service.update_approval(
        disable_pending.approval_id,
        "approved",
        approver="admin-3",
        approver_role=Role.ADMIN,
    )
    assert disable_failed.calls == [("disable", "adele@example.test")]

    disable_exception = FakeM365Writes(disable_error=True)
    disable_exception_service = SmartActionService(store, settings, m365_client=disable_exception)
    exception_pending = disable_exception_service.invoke(
        "m365-user-offboarding", payload, "requester", client_id="acme"
    )
    assert exception_pending.approval_id is not None
    disable_exception_service.update_approval(
        exception_pending.approval_id,
        "approved",
        approver="admin-4",
        approver_role=Role.ADMIN,
    )
    assert disable_exception.calls == [("disable", "adele@example.test")]

    revoke_exception = FakeM365Writes(revoke_error=True)
    revoke_exception_service = SmartActionService(store, settings, m365_client=revoke_exception)
    revoke_pending = revoke_exception_service.invoke(
        "m365-user-offboarding", payload, "requester", client_id="acme"
    )
    assert revoke_pending.approval_id is not None
    revoke_exception_service.update_approval(
        revoke_pending.approval_id,
        "approved",
        approver="admin-5",
        approver_role=Role.ADMIN,
    )
    assert revoke_exception.calls == [
        ("disable", "adele@example.test"),
        ("revoke", "graph-user-1"),
    ]
    run = store.get_smart_action_run(pending.run_id or 0)
    assert run is not None and run.status == "success"

    partial_provider = FakeM365Writes(revoke_status="failed")
    partial_service = SmartActionService(store, settings, m365_client=partial_provider)
    partial = partial_service.invoke("m365-user-offboarding", payload, "requester", client_id="acme")
    assert partial.approval_id is not None
    partial_service.update_approval(
        partial.approval_id,
        "approved",
        approver="admin-2",
        approver_role=Role.ADMIN,
    )
    partial_run = store.get_smart_action_run(partial.run_id or 0)
    assert partial_run is not None and partial_run.status == "failed"
    assert '"partial_failure":true' in partial_run.output_json
    assert partial_provider.calls == [
        ("disable", "adele@example.test"),
        ("revoke", "graph-user-1"),
    ]


def test_connector_read_tools_reject_malformed_or_foreign_records(settings, monkeypatch) -> None:
    store = Store(settings.data_path)
    _seed_tickets(store)
    with store._connect() as connection:  # noqa: SLF001
        connection.execute("update tickets set client_id = 'acme'")
    context = _action_context(store, settings, client_id="acme")
    foreign_halo = replace(
        context,
        halopsa_client=SimpleNamespace(
            get_ticket=lambda ticket_id: SimpleNamespace(
                result=SimpleNamespace(status="ready", message="ok", count=1),
                items=[HaloTicket(ticket_id, "Foreign", "Open", "P2", "beta", "Beta")],
            )
        ),
    )
    foreign_hudu = replace(
        context,
        hudu_client=SimpleNamespace(
            list_articles=lambda company_id, page, page_size: SimpleNamespace(
                result=SimpleNamespace(status="ready", message="ok", count=1),
                items=[HuduArticle("article-1", "Foreign", "beta", "folder-1", "", "")],
            )
        ),
    )
    blocked_connectwise = replace(
        context,
        connectwise_client=SimpleNamespace(
            get_ticket=lambda ticket_id: SimpleNamespace(
                result=SimpleNamespace(status="blocked", message="reads disabled", count=0),
                items=[],
            )
        ),
    )
    malformed_connectwise = replace(
        context,
        connectwise_client=SimpleNamespace(
            get_ticket=lambda ticket_id: SimpleNamespace(
                result=SimpleNamespace(status="ready", message="ok", count=1), items={}
            )
        ),
    )
    unavailable_connectwise = replace(
        context,
        connectwise_client=SimpleNamespace(
            get_ticket=lambda ticket_id: (_ for _ in ()).throw(RuntimeError("offline"))
        ),
    )
    empty_connectwise = replace(
        context,
        connectwise_client=SimpleNamespace(
            get_ticket=lambda ticket_id: SimpleNamespace(
                result=SimpleNamespace(status="ready", message="ok", count=0), items=[]
            )
        ),
    )
    blocked_syncro = replace(
        context,
        syncro_client=SimpleNamespace(
            get_ticket=lambda ticket_id: SimpleNamespace(
                result=SimpleNamespace(status="blocked", message="reads disabled", count=0),
                items=[],
            )
        ),
    )
    malformed_servicenow = replace(
        context,
        servicenow_client=SimpleNamespace(
            get_incident=lambda ticket_id: SimpleNamespace(
                result=SimpleNamespace(status="ready", message="ok", count=1),
                items={},
            )
        ),
    )
    unavailable_autotask = replace(
        context,
        autotask_client=SimpleNamespace(
            get_ticket=lambda ticket_id: (_ for _ in ()).throw(RuntimeError("offline")),
        ),
    )
    mismatched_syncro = replace(
        context,
        syncro_client=SimpleNamespace(
            get_ticket=lambda ticket_id: SimpleNamespace(
                result=SimpleNamespace(status="ready", message="ok", count=1),
                items=[{"id": "different-ticket", "subject": "Unexpected"}],
            )
        ),
    )
    blocked_itglue = replace(
        context,
        itglue_client=SimpleNamespace(
            list_documents=lambda organization_id, folder_id, page, page_size: SimpleNamespace(
                result=SimpleNamespace(status="blocked", message="reads disabled", count=0),
                items=[],
            )
        ),
    )
    blocked_confluence = replace(
        context,
        confluence_client=SimpleNamespace(
            list_pages=lambda space_id, page_size: SimpleNamespace(
                result=SimpleNamespace(status="blocked", message="reads disabled", count=0),
                items=[],
            )
        ),
    )
    blocked_sharepoint = replace(
        context,
        sharepoint_client=SimpleNamespace(
            list_documents=lambda site_id, parent_item_id=None, cursor=None, page_size=20: SimpleNamespace(
                result=SimpleNamespace(status="blocked", message="reads disabled", count=0),
                items=[],
            )
        ),
    )
    blocked_m365 = replace(
        context,
        m365_client=SimpleNamespace(
            list_users=lambda identity, page_size: SimpleNamespace(
                result=SimpleNamespace(status="blocked", message="reads disabled", count=0),
                items=[],
            )
        ),
    )
    malformed_halo = replace(
        context,
        halopsa_client=SimpleNamespace(
            get_ticket=lambda ticket_id: SimpleNamespace(
                result=SimpleNamespace(status="ready", message="ok", count=1), items={}
            )
        ),
    )
    blocked_halo = replace(
        context,
        halopsa_client=SimpleNamespace(
            get_ticket=lambda ticket_id: SimpleNamespace(
                result=SimpleNamespace(status="blocked", message="reads disabled", count=0), items=[]
            )
        ),
    )
    blocked_hudu = replace(
        context,
        hudu_client=SimpleNamespace(
            list_articles=lambda company_id, page, page_size: SimpleNamespace(
                result=SimpleNamespace(status="blocked", message="reads disabled", count=0), items=[]
            )
        ),
    )
    unavailable_hudu = replace(
        context,
        hudu_client=SimpleNamespace(
            list_articles=lambda company_id, page, page_size: (_ for _ in ()).throw(RuntimeError("offline")),
        ),
    )
    malformed_hudu = replace(
        context,
        hudu_client=SimpleNamespace(
            list_articles=lambda company_id, page, page_size: SimpleNamespace(
                result=SimpleNamespace(status="ready", message="ok", count=1), items={}
            ),
        ),
    )
    unavailable_rmm = replace(
        context,
        rmm_provider=SimpleNamespace(
            adapter_id="fake",
            list_devices=lambda client_id: (_ for _ in ()).throw(RuntimeError("offline")),
        ),
    )
    malformed_assets = [
        SimpleNamespace(asset_type="m365-user", attributes_json="{bad"),
        SimpleNamespace(asset_type="m365-user", attributes_json="[]"),
    ]
    monkeypatch.setattr(store, "list_canonical_assets", lambda *, client_id=None: malformed_assets)

    assert HaloPSATicketLookupAction().run(foreign_halo, {"ticket_id": "TCK-1001"}).status == "failed"
    assert ConnectWiseTicketLookupAction().run(
        blocked_connectwise, {"ticket_id": "TCK-1001"}
    ).status == "failed"
    assert ConnectWiseTicketLookupAction().run(
        malformed_connectwise, {"ticket_id": "TCK-1001"}
    ).status == "failed"
    assert ConnectWiseTicketLookupAction().run(
        unavailable_connectwise, {"ticket_id": "TCK-1001"}
    ).status == "failed"
    assert ConnectWiseTicketLookupAction().run(
        empty_connectwise, {"ticket_id": "TCK-1001"}
    ).status == "failed"
    assert SyncroTicketLookupAction().run(
        blocked_syncro, {"ticket_id": "TCK-1001"}
    ).status == "failed"
    assert ServiceNowIncidentLookupAction().run(
        malformed_servicenow, {"ticket_id": "TCK-1001"}
    ).status == "failed"
    assert AutotaskTicketLookupAction().run(
        unavailable_autotask, {"ticket_id": "TCK-1001"}
    ).status == "failed"
    mismatched = SyncroTicketLookupAction().run(
        mismatched_syncro, {"ticket_id": "TCK-1001"}
    )
    assert mismatched.status == "failed"
    assert mismatched.output["connector_status"] == "scope_mismatch"
    assert ItGlueDocumentationSearchAction().run(
        blocked_itglue, {"query": "vpn", "organization_id": "acme"}
    ).status == "failed"
    assert ConfluenceDocumentationSearchAction().run(
        blocked_confluence, {"query": "vpn", "space_id": "acme"}
    ).status == "failed"
    assert SharePointDocumentationSearchAction().run(
        blocked_sharepoint, {"query": "vpn", "site_id": "acme"}
    ).status == "failed"
    assert M365LiveContextAction().run(
        blocked_m365, {"resource": "user", "identity": "alice@example.test"}
    ).status == "failed"
    assert M365LiveContextAction().run(context, {"resource": "user"}).status == "failed"
    assert M365LiveContextAction().run(
        context,
        {"resource": "mail_messages", "identity": "alice@example.test"},
    ).status == "failed"
    assert HuduDocumentationSearchAction().run(
        foreign_hudu,
        {"query": "foreign", "company_id": "acme"},
    ).output["articles"] == []
    assert HaloPSATicketLookupAction().run(malformed_halo, {"ticket_id": "TCK-1001"}).status == "failed"
    assert HaloPSATicketLookupAction().run(blocked_halo, {"ticket_id": "TCK-1001"}).status == "failed"
    assert HuduDocumentationSearchAction().run(
        blocked_hudu,
        {"query": "vpn", "company_id": "acme"},
    ).status == "failed"
    assert HuduDocumentationSearchAction().run(
        unavailable_hudu,
        {"query": "vpn", "company_id": "acme"},
    ).status == "failed"
    assert HuduDocumentationSearchAction().run(
        malformed_hudu,
        {"query": "vpn", "company_id": "acme"},
    ).status == "failed"

    assert RmmDeviceLookupAction().run(unavailable_rmm, {"query": "agent"}).status == "failed"
    assert M365IdentityLookupAction().run(
        replace(context, client_id="acme"),
        {"identity": "admin", "limit": 0},
    ).status == "failed"
    assert HuduDocumentationSearchAction().run(
        context,
        {"query": "vpn", "company_id": "acme", "limit": 0},
    ).status == "failed"
    assert HuduDocumentationSearchAction().run(
        context,
        {"query": "vpn", "company_id": 1},
    ).status == "failed"


def test_m365_context_action_rejects_invalid_and_malformed_provider_results(settings) -> None:
    store = Store(settings.data_path)
    context = _action_context(store, settings, client_id="acme")
    action = M365LiveContextAction()

    assert action.run(context, {"resource": "unknown"}).status == "failed"
    assert action.run(context, {"resource": "user", "identity": 42}).status == "failed"
    assert action.run(context, {"resource": "user", "identity": "alice", "limit": True}).status == "failed"
    assert action.run(
        context,
        {"resource": "mail_messages", "identity": "alice", "folder_id": "bad folder"},
    ).status == "failed"

    unavailable = replace(
        context,
        m365_client=SimpleNamespace(
            list_users=lambda identity, page_size: (_ for _ in ()).throw(RuntimeError("offline")),
        ),
    )
    assert action.run(unavailable, {"resource": "user", "identity": "alice"}).status == "failed"

    malformed = replace(
        context,
        m365_client=SimpleNamespace(
            list_users=lambda identity, page_size: SimpleNamespace(
                result=SimpleNamespace(status="ready", message="ok"), items={}
            ),
        ),
    )
    assert action.run(malformed, {"resource": "user", "identity": "alice"}).status == "failed"

    blocked = replace(
        context,
        m365_client=SimpleNamespace(
            list_users=lambda identity, page_size: SimpleNamespace(
                result=SimpleNamespace(status="blocked", message="access denied token=secret"), items=[]
            ),
        ),
    )
    blocked_result = action.run(blocked, {"resource": "user", "identity": "alice"})
    assert blocked_result.status == "failed"
    assert blocked_result.output["items"] == []
    assert "secret" not in (blocked_result.error_detail or "")

    filtered = replace(
        context,
        m365_client=SimpleNamespace(
            list_users=lambda identity, page_size: SimpleNamespace(
                result=SimpleNamespace(status="ready", message="ok"),
                items=[SimpleNamespace(not_a_dataclass=True)],
            ),
        ),
    )
    filtered_result = action.run(filtered, {"resource": "user", "identity": "alice"})
    assert filtered_result.status == "success"
    assert filtered_result.output["items"] == []

    itglue = ItGlueDocumentationSearchAction()
    assert itglue.run(context, {"query": "vpn", "organization_id": "other"}).status == "failed"
    assert itglue.run(context, {"query": "vpn", "organization_id": "acme", "limit": 0}).status == "failed"
    assert itglue.run(
        context,
        {"query": "vpn", "organization_id": "acme", "folder_id": ""},
    ).status == "failed"
    search_calls: list[tuple[str, str, str | None, int]] = []

    def search_itglue_documents(
        organization_id: str,
        query: str,
        *,
        folder_id: str | None,
        limit: int,
    ) -> SimpleNamespace:
        search_calls.append((organization_id, query, folder_id, limit))
        return SimpleNamespace(
            result=SimpleNamespace(status="ready", message="ok", count=1),
            items=[
                ItGlueDocument(
                    "doc-1",
                    "VPN runbook",
                    organization_id,
                    "folder-1",
                    "today",
                    "https://itglue",
                    "MFA token=secret",
                )
            ],
        )

    itglue_content = replace(
        context,
        itglue_client=SimpleNamespace(
            search_documents=search_itglue_documents,
        ),
    )
    itglue_content_result = itglue.run(
        itglue_content,
        {"query": "mfa", "organization_id": "acme", "folder_id": "folder-1", "limit": 3},
    )
    assert itglue_content_result.status == "success"
    assert search_calls == [("acme", "mfa", "folder-1", 3)]
    assert itglue_content_result.output["documents"][0]["content"] == "MFA token=[redacted]"  # type: ignore[index]
    itglue_error = replace(
        context,
        itglue_client=SimpleNamespace(
            list_documents=lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("offline")),
        ),
    )
    assert itglue.run(itglue_error, {"query": "vpn", "organization_id": "acme"}).status == "failed"

    confluence = ConfluenceDocumentationSearchAction()
    assert confluence.run(context, {"query": "vpn", "space_id": "other"}).status == "failed"
    assert confluence.run(context, {"query": "vpn", "space_id": "acme", "limit": 0}).status == "failed"
    confluence_error = replace(
        context,
        confluence_client=SimpleNamespace(
            list_pages=lambda **kwargs: (_ for _ in ()).throw(RuntimeError("offline")),
        ),
    )
    assert confluence.run(confluence_error, {"query": "vpn", "space_id": "acme"}).status == "failed"
    confluence_malformed = replace(
        context,
        confluence_client=SimpleNamespace(
            list_pages=lambda **kwargs: SimpleNamespace(
                result=SimpleNamespace(status="ready", message="ok"), items={}
            ),
        ),
    )
    assert confluence.run(confluence_malformed, {"query": "vpn", "space_id": "acme"}).status == "failed"

    sharepoint = SharePointDocumentationSearchAction()
    assert sharepoint.run(context, {"query": "vpn", "site_id": "other"}).status == "failed"
    assert sharepoint.run(context, {"query": "vpn", "site_id": "acme", "limit": 0}).status == "failed"
    assert sharepoint.run(
        context,
        {"query": "vpn", "site_id": "acme", "parent_item_id": ""},
    ).status == "failed"
    sharepoint_search_calls: list[tuple[str, str, str | None, int]] = []

    def search_sharepoint_documents(
        site_id: str,
        query: str,
        *,
        parent_item_id: str | None,
        limit: int,
    ) -> SimpleNamespace:
        sharepoint_search_calls.append((site_id, query, parent_item_id, limit))
        return SimpleNamespace(
            result=SimpleNamespace(status="ready", message="ok", count=1),
            items=[
                SharePointDocument(
                    "file-1",
                    "MFA.md",
                    site_id,
                    "root",
                    42,
                    "today",
                    "https://sharepoint",
                    False,
                    True,
                    "token=secret",
                )
            ],
        )

    sharepoint_content_search = replace(
        context,
        sharepoint_client=SimpleNamespace(search_documents=search_sharepoint_documents),
    )
    sharepoint_content_search_result = sharepoint.run(
        sharepoint_content_search,
        {"query": "mfa", "site_id": "acme", "parent_item_id": "root", "limit": 3},
    )
    assert sharepoint_content_search_result.status == "success"
    assert sharepoint_search_calls == [("acme", "mfa", "root", 3)]
    assert sharepoint_content_search_result.output["documents"][0]["name"] == "MFA.md"  # type: ignore[index]
    sharepoint_error = replace(
        context,
        sharepoint_client=SimpleNamespace(
            list_documents=lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("offline")),
        ),
    )
    assert sharepoint.run(sharepoint_error, {"query": "vpn", "site_id": "acme"}).status == "failed"


def test_local_rmm_adapter_skips_malformed_assets(settings, monkeypatch) -> None:
    store = Store(settings.data_path)
    assets = [
        SimpleNamespace(asset_type="host", attributes_json="{}"),
        SimpleNamespace(asset_type="endpoint-agent", attributes_json="[]"),
        SimpleNamespace(asset_type="endpoint-agent", attributes_json="{bad"),
    ]
    monkeypatch.setattr(store, "list_canonical_assets", lambda *, client_id=None: assets)

    assert LocalCollectorRmmAdapter(store).list_devices(client_id="acme") == []


def test_deterministic_action_persists_run_and_audit(settings) -> None:
    store = Store(settings.data_path)
    _seed_tickets(store)
    service = SmartActionService(store, settings)

    result = service.invoke("ticket-triage", {"ticket_id": "TCK-1001"}, "technician")

    assert result.status == "success"
    assert result.output["classification"] == "identity-access"
    assert result.run_id is not None
    run = store.get_smart_action_run(result.run_id)
    assert run is not None
    assert run.status == "success"
    event_types = [event.event_type for event in store.list_audit_events()]
    assert "smart_action.invoked" in event_types
    assert "smart_action.completed" in event_types


def test_ai_actions_use_deterministic_local_fallback(settings) -> None:
    store = Store(settings.data_path)
    _seed_tickets(store)
    service = SmartActionService(store, settings)

    result = service.invoke("ticket-summary", {"ticket_id": "TCK-1001"}, "technician")
    resolution = service.invoke("suggest-resolution", {"ticket_id": "TCK-1001"}, "technician")

    assert result.status == "success"
    assert result.output["ai_assisted"] is False
    assert result.output["provider_id"] == "deterministic"
    assert result.output["summary"]
    assert resolution.status == "success"
    assert resolution.output["ai_assisted"] is False
    assert resolution.output["provider_id"] == "deterministic"
    assert resolution.output["suggestion"]
    assert result.run_id is not None
    assert store.get_smart_action_run(result.run_id).status == "success"  # type: ignore[union-attr]


def test_documentation_assisted_response_drafts_and_delivers_local_note_after_approval(settings) -> None:
    store = Store(settings.data_path)
    _seed_tickets(store)
    with store._connect() as connection:  # noqa: SLF001
        connection.execute("update tickets set client_id = 'acme'")
    service = SmartActionService(store, replace(settings, allow_write_actions=True))

    pending = service.invoke(
        "documentation-assisted-response",
        {"ticket_id": "TCK-1001"},
        "requester",
    )

    assert pending.status == "pending_approval"
    assert pending.approval_id is not None
    assert pending.output["response"]
    assert pending.output["citations"]
    citations = cast(list[dict[str, object]], pending.output["citations"])
    assert citations[0]["type"] == "ticket"
    assert any(item["type"] == "knowledge" for item in citations)
    assert store.list_ticket_notes("TCK-1001", client_id="acme") == []

    completed = service.update_approval(
        pending.approval_id,
        "approved",
        approver="technician",
        approver_role=Role.TECHNICIAN,
    )

    assert completed.status == "approved"
    notes = store.list_ticket_notes("TCK-1001", client_id="acme")
    assert [note.body for note in notes] == [pending.output["response"]]


def test_documentation_assisted_response_fails_closed_without_knowledge(settings, tmp_path) -> None:
    doc_root = tmp_path / "docs"
    doc_root.mkdir()
    (doc_root / "unrelated.md").write_text("# Unrelated\n\nOther material.", encoding="utf-8")
    active_settings = replace(settings, allowed_doc_root=doc_root)
    store = Store(active_settings.data_path)
    _seed_tickets(store)
    service = SmartActionService(store, active_settings)

    result = service.invoke(
        "documentation-assisted-response",
        {"ticket_id": "TCK-1001"},
        "requester",
    )

    assert result.status == "failed"
    assert result.error_detail == "no_relevant_sources"
    assert store.list_approval_requests() == []


def test_documentation_assisted_response_reports_unavailable_provider(settings) -> None:
    store = Store(settings.data_path)
    _seed_tickets(store)
    service = SmartActionService(
        store,
        settings,
        provider=UnavailableProvider(),
        provider_configured=True,
    )

    result = service.invoke(
        "documentation-assisted-response",
        {"ticket_id": "TCK-1001"},
        "requester",
    )

    assert result.status == "provider_not_configured"
    assert store.list_approval_requests() == []


def test_documentation_assisted_response_validates_payload_and_provider_failures(settings) -> None:
    store = Store(settings.data_path)
    _seed_tickets(store)

    service = SmartActionService(store, settings)
    assert service.invoke(
        "documentation-assisted-response",
        {"ticket_id": "TCK-1001", "unexpected": True},
        "requester",
    ).error_detail.endswith("unsupported fields")
    assert service.invoke(
        "documentation-assisted-response",
        {"ticket_id": "NOPE"},
        "requester",
    ).error_detail == "ticket_id must identify an existing ticket"
    unavailable = SmartActionService(
        store,
        settings,
        provider=FakeProvider(),
        provider_configured=False,
    ).invoke("documentation-assisted-response", {"ticket_id": "TCK-1001"}, "requester")
    assert unavailable.status == "provider_not_configured"

    failing = SmartActionService(
        store,
        settings,
        provider=FailingProvider(),
        provider_configured=True,
    ).invoke("documentation-assisted-response", {"ticket_id": "TCK-1001"}, "requester")
    assert failing.status == "failed"
    assert failing.error_detail == "provider request failed: provider exploded"

    invalid = service.invoke(
        "documentation-assisted-response",
        {"ticket_id": "TCK-1001", "response": " "},
        "requester",
    )
    assert invalid.status == "failed"
    assert invalid.error_detail.startswith("response must be")
    bad_channel = service.invoke(
        "documentation-assisted-response",
        {"ticket_id": "TCK-1001", "response": "Reviewed.", "channel": "carrier-pigeon"},
        "requester",
    )
    assert bad_channel.status == "failed"
    assert "channel must be" in bad_channel.error_detail


def test_documentation_assisted_response_uses_edited_response_and_preserves_write_gate(settings) -> None:
    store = Store(settings.data_path)
    _seed_tickets(store)
    service = SmartActionService(store, settings)

    pending = service.invoke(
        "documentation-assisted-response",
        {"ticket_id": "TCK-1001", "response": "Reviewed response."},
        "requester",
    )
    assert pending.status == "pending_approval"
    assert pending.output["response"] == "Reviewed response."

    service.update_approval(
        pending.approval_id or 0,
        "approved",
        approver="technician",
        approver_role=Role.TECHNICIAN,
    )
    smart_run = store.get_smart_action_run(pending.run_id or 0)
    assert smart_run is not None
    assert smart_run.status == "failed"
    assert store.list_ticket_notes("TCK-1001", client_id="acme") == []


def test_deterministic_provider_never_reports_ai_when_inference_is_enabled(settings) -> None:
    store = Store(settings.data_path)
    _seed_tickets(store)
    service = SmartActionService(store, replace(settings, allow_llm_inference=True))

    result = service.invoke("ticket-summary", {"ticket_id": "TCK-1001"}, "technician")

    assert result.status == "success"
    assert result.output["ai_assisted"] is False
    assert result.output["provider_id"] == "deterministic"


def test_suggest_resolution_rejects_zero_positive_retrieval_hits(settings, tmp_path) -> None:
    doc_root = tmp_path / "docs"
    doc_root.mkdir()
    (doc_root / "unrelated.md").write_text("# Unrelated\n\nOther material.", encoding="utf-8")
    active_settings = replace(settings, allowed_doc_root=doc_root)
    store = Store(active_settings.data_path)
    _seed_tickets(store)
    service = SmartActionService(store, active_settings, provider=FakeProvider(), provider_configured=True)

    result = service.invoke("suggest-resolution", {"ticket_id": "TCK-1001"}, "technician")

    assert result.status == "failed"
    assert result.error_detail == "no_relevant_sources"
    assert result.output == {}
    assert result.evidence == []


def test_resolution_has_retrieval_citations_and_provider_label(settings) -> None:
    store = Store(settings.data_path)
    _seed_tickets(store)
    service = SmartActionService(store, settings, provider=FakeProvider(), provider_configured=True)

    result = service.invoke("suggest-resolution", {"ticket_id": "TCK-1002"}, "technician")

    assert result.status == "success"
    assert result.output["ai_assisted"] is True
    assert result.output["provider_id"] == "deterministic"
    citations = result.output["citations"]
    assert isinstance(citations, list)
    assert citations[0]["title"] == "Shared Mailbox Runbook"
    assert result.evidence == citations


def test_screenconnect_session_actions_are_preview_first_and_approval_gated(settings) -> None:
    requests: list[tuple[str, list[str]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append((request.url.path.rsplit("/", 1)[-1], json.loads(request.content)))
        return httpx.Response(204)

    session_settings = replace(
        settings,
        allow_http_probing=True,
        allow_write_actions=True,
        screenconnect_base_url="https://screenconnect.example.test",
        screenconnect_extension_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        screenconnect_auth_secret="screenconnect-secret",
        screenconnect_origin="https://screenconnect.example.test",
        screenconnect_client_sessions_map_json=json.dumps({"acme": [
            "11111111-2222-3333-4444-555555555555"
        ]}),
    )
    adapter = ScreenConnectRmmAdapter(
        session_settings,
        transport=httpx.MockTransport(handler),
    )
    store = Store(session_settings.data_path)
    service = SmartActionService(store, session_settings, rmm_provider=adapter)

    note_pending = service.invoke(
        "screenconnect-session-note",
        {
            "session_id": "11111111-2222-3333-4444-555555555555",
            "note_body": "Reviewed with the customer.",
        },
        "requester",
        client_id="acme",
    )
    assert note_pending.status == "pending_approval"
    assert note_pending.approval_id is not None
    note_approval_id = note_pending.approval_id
    assert requests == []
    service.update_approval(
        note_approval_id,
        "approved",
        "reviewed",
        approver="approver",
        approver_role=Role.TECHNICIAN,
    )
    note_completed = service.complete_approval(
        note_approval_id,
        approver="approver",
        approver_role=Role.TECHNICIAN,
    )
    assert note_completed is not None
    assert note_completed.status == "success"
    assert requests == [
        ("AddNoteToSession", [
            "11111111-2222-3333-4444-555555555555",
            "Reviewed with the customer.",
        ])
    ]

    message_pending = service.invoke(
        "screenconnect-session-message",
        {
            "session_id": "11111111-2222-3333-4444-555555555555",
            "by_host": "WAIT technician",
            "message": "Please save your work.",
        },
        "requester",
        client_id="acme",
    )
    assert message_pending.status == "pending_approval"
    assert message_pending.approval_id is not None
    message_approval_id = message_pending.approval_id
    service.update_approval(
        message_approval_id,
        "approved",
        "reviewed",
        approver="approver-2",
        approver_role=Role.TECHNICIAN,
    )
    message_completed = service.complete_approval(
        message_approval_id,
        approver="approver-2",
        approver_role=Role.TECHNICIAN,
    )
    assert message_completed is not None
    assert message_completed.status == "success"
    assert requests[-1] == (
        "SendMessageToSession",
        [
            "11111111-2222-3333-4444-555555555555",
            "WAIT technician",
            "Please save your work.",
        ],
    )


def test_dispatch_requires_approval_and_completes_after_approval(settings) -> None:
    store = Store(settings.data_path)
    _seed_tickets(store)
    service = SmartActionService(store, settings)

    pending = service.invoke(
        "dispatch-suggestion",
        {
            "ticket_id": "TCK-1001",
            "technicians": [{"id": "tech-b", "workload": 4}, {"id": "tech-a", "workload": 2}],
        },
        "technician",
        confirm=True,
    )

    assert pending.status == "pending_approval"
    assert pending.approval_id is not None
    assert pending.run_id is not None
    service.update_approval(
        pending.approval_id,
        "approved",
        "reviewed",
        approver="approver",
        approver_role=Role.TECHNICIAN,
    )
    completed = service.complete_approval(
        pending.approval_id,
        approver="approver",
        approver_role=Role.TECHNICIAN,
    )

    assert completed is not None
    assert completed.status == "success"
    assert completed.output["approved"] is True
    assert isinstance(completed.output["recommendation"], dict)
    assert completed.output["recommendation"]["technician_id"] == "tech-a"
    assert store.get_smart_action_run(pending.run_id).status == "success"  # type: ignore[union-attr]


def test_read_only_smart_action_can_be_made_approval_gated(settings) -> None:
    store = Store(settings.data_path)
    _seed_tickets(store)
    service = SmartActionService(store, settings)

    pending = service.invoke(
        "ticket-triage",
        {"ticket_id": "TCK-1001"},
        "technician",
        require_approval=True,
    )

    assert pending.status == "pending_approval"
    assert pending.approval_id is not None


def test_expired_smart_action_approval_rejects_without_execution(settings) -> None:
    store = Store(settings.data_path)
    _seed_tickets(store)
    service = SmartActionService(store, settings)
    pending = service.invoke("dispatch-suggestion", {"ticket_id": "TCK-1001"}, "technician")
    assert pending.approval_id is not None and pending.run_id is not None
    with store._connect() as connection:  # noqa: SLF001
        connection.execute(
            "update approval_requests set expires_at = ? where id = ?",
            ("2000-01-01T00:00:00+00:00", pending.approval_id),
        )

    expired = store.get_approval_request(pending.approval_id)
    result = service.complete_approval(
        pending.approval_id,
        approver="approver",
        approver_role=Role.TECHNICIAN,
    )

    assert expired is not None and expired.status == "expired"
    assert result is not None
    assert result.status == "rejected"
    assert result.error_detail == "approval expired"
    assert store.get_smart_action_run(pending.run_id).status == "rejected"  # type: ignore[union-attr]


def test_approval_completion_requires_authorized_different_approver(settings) -> None:
    store = Store(settings.data_path)
    _seed_tickets(store)
    service = SmartActionService(store, settings)
    pending = service.invoke(
        "dispatch-suggestion",
        {"ticket_id": "TCK-1001", "technicians": []},
        "requester",
    )
    assert pending.approval_id is not None
    with pytest.raises(PermissionError, match="SmartActionService"):
        store.update_approval_request(pending.approval_id, "approved")
    with pytest.raises(PermissionError, match="SmartActionService"):
        store.complete_smart_action_run(
            pending.run_id or 0,
            "success",
            {},
            [],
            approval_id=pending.approval_id,
            approver_id="attacker",
        )

    with pytest.raises(PermissionError, match="approver is required"):
        service.complete_approval(pending.approval_id, approver=None, approver_role=Role.TECHNICIAN)
    with pytest.raises(PermissionError, match="technician or admin"):
        service.complete_approval(pending.approval_id, approver="viewer", approver_role=Role.VIEWER)
    with pytest.raises(PermissionError, match="cannot approve"):
        service.complete_approval(
            pending.approval_id,
            approver="requester",
            approver_role=Role.TECHNICIAN,
        )


def test_unknown_approved_action_is_failed_and_audited(settings) -> None:
    store = Store(settings.data_path)
    _seed_tickets(store)
    with store._connect() as connection:  # noqa: SLF001
        connection.execute("update tickets set client_id = 'acme' where id = 'TCK-1001'")
    service = SmartActionService(store, settings)
    pending = service.invoke(
        "dispatch-suggestion",
        {"ticket_id": "TCK-1001", "technicians": []},
        "requester",
        client_id="acme",
    )
    assert pending.approval_id is not None and pending.run_id is not None
    with store._connect() as connection:  # noqa: SLF001
        connection.execute(
            "update approval_requests set action_type = ? where id = ?",
            ("smart_action:missing-action", pending.approval_id),
        )

    service.update_approval(
        pending.approval_id,
        "approved",
        approver="approver",
        approver_role=Role.TECHNICIAN,
    )
    result = service.complete_approval(
        pending.approval_id,
        approver="approver",
        approver_role=Role.TECHNICIAN,
    )

    assert result is not None and result.status == "failed"
    assert store.get_smart_action_run(pending.run_id).status == "failed"  # type: ignore[union-attr]
    assert any(
        event.event_type == "smart_action.completed"
        and event.client_id == "acme"
        and "failed" in event.detail
        for event in store.list_audit_events(client_id="acme")
    )


def test_smart_action_json_storage_redacts_secrets(settings) -> None:
    class SecretAction:
        manifest = SmartActionManifest(
            action_id="secret-test",
            title="Secret test",
            description="test",
            kind="deterministic",
            input_schema={"type": "object"},
            output_schema={"type": "object"},
            requires_approval=False,
            estimated_minutes_saved=0,
        )

        def run(self, context, payload):
            return ActionResult(
                status="success",
                output={
                    "key": "raw-plain-key",
                    "api-key": "raw-api-key",
                    "nested": {"password": "raw-password"},
                },
                evidence=[{"privateKey": "raw-private-key", "token": "raw-token"}],
            )

    registry = SmartActionRegistry()
    registry.register(SecretAction())
    store = Store(settings.data_path)
    result = SmartActionService(store, settings, registry=registry).invoke(
        "secret-test", {"token": "payload-token"}, "actor"
    )

    assert result.output["key"] == "[redacted]"
    assert result.output["api-key"] == "[redacted]"
    assert result.evidence[0]["token"] == "[redacted]"
    run = store.get_smart_action_run(result.run_id or 0)
    assert run is not None
    assert "raw-key" not in run.output_json
    assert "raw-token" not in run.evidence_json
    execution = store.list_execution_runs(run_kind="smart_action")[0]
    artifact = store.list_execution_artifacts(execution.id or 0)[0]
    artifact_bytes = Path(artifact.storage_path).read_bytes()
    assert b"raw-private-key" not in artifact_bytes
    assert b"raw-token" not in artifact_bytes


def test_invoke_records_execution_row_with_ordered_steps(settings) -> None:
    store = Store(settings.data_path)
    _seed_tickets(store)
    service = SmartActionService(store, settings)

    result = service.invoke("ticket-triage", {"ticket_id": "TCK-1001"}, "tech")

    assert result.status == "success"
    runs = store.list_execution_runs(run_kind="smart_action")
    assert len(runs) == 1
    assert runs[0].source_run_id == result.run_id
    assert runs[0].status == "success"
    steps = store.list_execution_steps(runs[0].id or 0)
    assert [step.ordinal for step in steps] == [0]
    assert steps[0].kind == "smart_action.invoke"
    assert "TCK-1001" in steps[0].input_json


def test_recorder_failure_does_not_change_action_outcome(settings, monkeypatch) -> None:
    store = Store(settings.data_path)
    _seed_tickets(store)
    service = SmartActionService(store, settings)

    def exploding_create(*args, **kwargs):
        raise RuntimeError("recorder storage exploded")

    monkeypatch.setattr(Store, "create_execution_run", exploding_create)

    result = service.invoke("ticket-triage", {"ticket_id": "TCK-1001"}, "tech")

    assert result.status == "success"
    assert store.get_smart_action_run(result.run_id or 0) is not None


def test_recurring_service_review_action_is_read_only_and_tenant_scoped(settings) -> None:
    store = Store(settings.data_path)
    _seed_tickets(store)
    with store._connect() as connection:  # noqa: SLF001
        connection.execute(
            "update tickets set client_id = ?, created_at = ?, updated_at = ? where id = ?",
            ("acme", "2026-01-01T00:00:00+00:00", "2026-01-05T00:00:00+00:00", "TCK-1001"),
        )

    service = SmartActionService(store, settings)
    result = service.invoke(
        "recurring-service-review",
        {
            "period_start": "2026-01-01",
            "period_end": "2026-03-31",
            "follow_up_after_days": 14,
        },
        "viewer",
        client_id="acme",
    )

    assert result.status == "success"
    assert result.output["report_type"] == "recurring_service_review"
    assert result.output["client_id"] == "acme"
    assert result.evidence[0]["claims_excluded"]
    assert service.store.list_execution_runs(client_id="acme", run_kind="smart_action")
    action = RecurringServiceReviewAction()
    scoped_ticket_result = action.run(
        _action_context(store, settings, client_id="acme"),
        {
            "ticket_id": "TCK-1001",
            "period_start": "2026-01-01",
            "period_end": "2026-03-31",
        },
    )
    assert scoped_ticket_result.status == "success"

    assert action.run(_action_context(store, settings, client_id="acme"), {"unexpected": True}).status == "failed"
    assert action.run(
        _action_context(store, settings),
        {"period_start": "2026-01-01", "period_end": "2026-03-31"},
    ).status == "failed"
    assert action.run(
        _action_context(store, settings, client_id="acme"),
        {"ticket_id": 123, "period_start": "2026-01-01", "period_end": "2026-03-31"},
    ).status == "failed"
    assert action.run(
        _action_context(store, settings, client_id="acme"),
        {"period_start": None, "period_end": "2026-03-31"},
    ).status == "failed"
    assert action.run(
        _action_context(store, settings, client_id="acme"),
        {"period_start": "2026-01-01", "period_end": "2026-03-31", "follow_up_after_days": True},
    ).status == "failed"

    invalid = RecurringServiceReviewAction().run(
        _action_context(store, settings, client_id="acme"),
        {"period_start": "2026-01-01", "period_end": "not-a-date", "follow_up_after_days": 14},
    )
    assert invalid.status == "failed"
    cross_tenant = RecurringServiceReviewAction().run(
        _action_context(store, settings, client_id="globex"),
        {
            "ticket_id": "TCK-1001",
            "period_start": "2026-01-01",
            "period_end": "2026-03-31",
        },
    )
    assert cross_tenant.status == "failed"
def test_m365_password_reset_and_authentication_method_removal_are_admin_approval_gated(
    settings, tmp_path
) -> None:
    class FakeM365SecurityWrites:
        def __init__(self) -> None:
            self.password_calls: list[dict[str, object]] = []
            self.method_calls: list[dict[str, object]] = []

        def write_health(self):
            return SimpleNamespace(status="ready", message="write ready")

        def reset_user_password(self, **kwargs):
            self.password_calls.append(kwargs)
            return SimpleNamespace(status="succeeded", message="reset", status_code=204)

        def delete_authentication_method(self, **kwargs):
            self.method_calls.append(kwargs)
            return SimpleNamespace(status="succeeded", message="removed", status_code=204)

    active_settings = replace(settings, vault_path=tmp_path / "vault")
    SecretVault.initialize(active_settings.vault_path).set(
        "WAIT_M365_TEMP_ADELE", "Temporary-Password-123!"
    )
    provider = FakeM365SecurityWrites()
    service = SmartActionService(
        Store(active_settings.data_path), active_settings, m365_client=provider
    )

    password = service.invoke(
        "m365-password-reset",
        {
            "user_identity": "adele.vance@example.test",
            "temporary_vault_name": "WAIT_M365_TEMP_ADELE",
        },
        "requester",
        client_id="acme",
    )
    assert password.status == "pending_approval"
    assert password.approval_id is not None
    service.update_approval(
        password.approval_id,
        "approved",
        approver="admin",
        approver_role=Role.ADMIN,
    )
    assert provider.password_calls[0]["temporary_password"] == "Temporary-Password-123!"
    password_run = service.store.get_smart_action_run(password.run_id or 0)
    assert password_run is not None and "Temporary-Password-123!" not in password_run.output_json

    method = service.invoke(
        "m365-authentication-method-remove",
        {
            "user_identity": "adele.vance@example.test",
            "method_type": "fido2",
            "method_id": "method-1",
        },
        "requester",
        client_id="acme",
    )
    assert method.status == "pending_approval"
    with pytest.raises(PermissionError, match="admin authority"):
        service.update_approval(
            method.approval_id or 0,
            "approved",
            approver="technician",
            approver_role=Role.TECHNICIAN,
        )
    service.update_approval(
        method.approval_id or 0,
        "approved",
        approver="admin",
        approver_role=Role.ADMIN,
    )
    assert provider.method_calls == [
        {
            "user_identity": "adele.vance@example.test",
            "method_type": "fido2",
            "method_id": "method-1",
        }
    ]


def test_m365_security_actions_report_invalid_unready_missing_and_provider_failures(settings, tmp_path) -> None:
    class FakeM365SecurityWrites:
        def __init__(self, health_status: str = "ready", result_status: str = "failed") -> None:
            self.health_status = health_status
            self.result_status = result_status
            self.calls: list[dict[str, object]] = []

        def write_health(self):
            return SimpleNamespace(status=self.health_status, message="provider unavailable")

        def reset_user_password(self, **kwargs):
            self.calls.append(kwargs)
            return SimpleNamespace(status=self.result_status, message="provider rejected", status_code=400)

        def delete_authentication_method(self, **kwargs):
            self.calls.append(kwargs)
            return SimpleNamespace(status=self.result_status, message="provider rejected", status_code=400)

    failing_settings = replace(settings, vault_path=tmp_path / "failing-vault")
    SecretVault.initialize(failing_settings.vault_path).set(
        "WAIT_M365_TEMP_USER", "Temporary-Password-123!"
    )
    failing_service = SmartActionService(
        Store(failing_settings.data_path),
        failing_settings,
        m365_client=FakeM365SecurityWrites(result_status="failed"),
    )
    failed_provider = failing_service.invoke(
        "m365-password-reset",
        {"user_identity": "user@example.test", "temporary_vault_name": "WAIT_M365_TEMP_USER"},
        "requester",
    )
    failing_service.update_approval(
        failed_provider.approval_id or 0,
        "approved",
        approver="admin",
        approver_role=Role.ADMIN,
    )
    failed_run = failing_service.store.get_smart_action_run(failed_provider.run_id or 0)
    assert failed_run is not None and failed_run.status == "failed"

    invalid_service = SmartActionService(
        Store(settings.data_path), settings, m365_client=FakeM365SecurityWrites()
    )
    invalid = invalid_service.invoke(
        "m365-password-reset",
        {"user_identity": "user@example.test", "temporary_password": "never-accepted"},
        "requester",
    )
    assert invalid.status == "failed"
    invalid_method = invalid_service.invoke(
        "m365-authentication-method-remove",
        {"user_identity": "user@example.test", "method_type": "all", "method_id": "method-1"},
        "requester",
    )
    assert invalid_method.status == "failed"

    unavailable = SmartActionService(
        Store(settings.data_path), settings, m365_client=FakeM365SecurityWrites("blocked")
    ).invoke(
        "m365-authentication-method-remove",
        {"user_identity": "user@example.test", "method_type": "fido2", "method_id": "method-1"},
        "requester",
    )
    assert unavailable.status == "failed"

    active_settings = replace(settings, vault_path=tmp_path / "missing-vault")
    missing_service = SmartActionService(
        Store(active_settings.data_path), active_settings, m365_client=FakeM365SecurityWrites()
    )
    missing = missing_service.invoke(
        "m365-password-reset",
        {"user_identity": "user@example.test", "temporary_vault_name": "WAIT_M365_TEMP_USER"},
        "requester",
    )
    assert missing.approval_id is not None
    missing_service.update_approval(
        missing.approval_id,
        "approved",
        approver="admin",
        approver_role=Role.ADMIN,
    )
    missing_run = missing_service.store.get_smart_action_run(missing.run_id or 0)
    assert missing_run is not None and missing_run.status == "failed"


def test_m365_security_actions_cover_exception_and_non_success_paths(settings, tmp_path) -> None:
    store = Store(settings.data_path)

    invalid_context = _action_context(store, settings)
    assert M365PasswordResetAction().run(
        invalid_context,
        {"user_identity": "user@example.test", "temporary_vault_name": "not-a-vault"},
    ).status == "failed"
    assert M365AuthenticationMethodDeleteAction().run(
        invalid_context,
        {
            "user_identity": "user@example.test",
            "method_type": "all",
            "method_id": "method-1",
        },
    ).status == "failed"

    class HealthFailureProvider:
        def write_health(self):
            raise RuntimeError("health unavailable")

        def reset_user_password(self, **kwargs):
            raise AssertionError("password reset must not run after health failure")

        def delete_authentication_method(self, **kwargs):
            raise AssertionError("authentication removal must not run after health failure")

    health_context = ActionContext(
        store=store,
        settings=settings,
        actor="technician",
        m365_client=HealthFailureProvider(),
    )
    assert M365PasswordResetAction().run(
        health_context,
        {"user_identity": "user@example.test", "temporary_vault_name": "WAIT_M365_TEMP_USER"},
    ).status == "failed"
    assert M365AuthenticationMethodDeleteAction().run(
        health_context,
        {
            "user_identity": "user@example.test",
            "method_type": "fido2",
            "method_id": "method-1",
        },
    ).status == "failed"

    class UnreadyProvider:
        def write_health(self):
            return SimpleNamespace(status="blocked", message="writes disabled")

        def reset_user_password(self, **kwargs):
            raise AssertionError("password reset must not run when writes are blocked")

        def delete_authentication_method(self, **kwargs):
            raise AssertionError("authentication removal must not run when writes are blocked")

    assert M365PasswordResetAction().run(
        ActionContext(
            store=store,
            settings=settings,
            actor="technician",
            m365_client=UnreadyProvider(),
        ),
        {"user_identity": "user@example.test", "temporary_vault_name": "WAIT_M365_TEMP_USER"},
    ).status == "failed"

    active_settings = replace(settings, vault_path=tmp_path / "exception-vault")
    SecretVault.initialize(active_settings.vault_path).set(
        "WAIT_M365_TEMP_USER", "Temporary-Password-123!"
    )

    class PasswordFailureProvider:
        def write_health(self):
            return SimpleNamespace(status="ready", message="ready")

        def reset_user_password(self, **kwargs):
            raise RuntimeError("password reset failed")

    password_context = ActionContext(
        store=Store(active_settings.data_path),
        settings=active_settings,
        actor="technician",
        m365_client=PasswordFailureProvider(),
    )
    password_result = M365PasswordResetAction().run(
        password_context,
        {
            "user_identity": "user@example.test",
            "temporary_vault_name": "WAIT_M365_TEMP_USER",
            "_approval_completed": True,
        },
    )
    assert password_result.status == "failed"

    missing_vault_result = M365PasswordResetAction().run(
        ActionContext(
            store=Store(replace(active_settings, vault_path=tmp_path / "missing-vault").data_path),
            settings=replace(active_settings, vault_path=tmp_path / "missing-vault"),
            actor="technician",
            m365_client=PasswordFailureProvider(),
        ),
        {
            "user_identity": "user@example.test",
            "temporary_vault_name": "WAIT_M365_TEMP_USER",
            "_approval_completed": True,
        },
    )
    assert missing_vault_result.status == "failed"

    assert M365AuthenticationMethodDeleteAction().run(
        invalid_context,
        {
            "user_identity": "user@example.test",
            "method_type": "fido2",
            "method_id": "method-1",
            "unexpected": True,
        },
    ).status == "failed"

    class AuthenticationFailureProvider:
        def write_health(self):
            return SimpleNamespace(status="ready", message="ready")

        def delete_authentication_method(self, **kwargs):
            return SimpleNamespace(status="failed", message="provider rejected", status_code=400)

    authentication_result = M365AuthenticationMethodDeleteAction().run(
        ActionContext(
            store=store,
            settings=settings,
            actor="technician",
            m365_client=AuthenticationFailureProvider(),
        ),
        {
            "user_identity": "user@example.test",
            "method_type": "fido2",
            "method_id": "method-1",
            "_approval_completed": True,
        },
    )
    assert authentication_result.status == "failed"
    assert authentication_result.error_detail == "provider rejected"

    class AuthenticationExceptionProvider:
        def write_health(self):
            return SimpleNamespace(status="ready", message="ready")

        def delete_authentication_method(self, **kwargs):
            raise RuntimeError("authentication removal failed")

    exception_result = M365AuthenticationMethodDeleteAction().run(
        ActionContext(
            store=store,
            settings=settings,
            actor="technician",
            m365_client=AuthenticationExceptionProvider(),
        ),
        {
            "user_identity": "user@example.test",
            "method_type": "fido2",
            "method_id": "method-1",
            "_approval_completed": True,
        },
    )
    assert exception_result.status == "failed"
