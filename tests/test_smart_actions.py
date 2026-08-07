from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from wait_local_agent.collectors import CollectorPreview
from wait_local_agent.models import SourceReference, Ticket
from wait_local_agent.providers import ProviderUnavailableError
from wait_local_agent.rbac import Role
from wait_local_agent.reports.renderers import redact_value
from wait_local_agent.smart_actions import (
    ActionContext,
    ActionResult,
    CollectorPreviewAction,
    DispatchSuggestionAction,
    FindSimilarTicketsAction,
    KnowledgeSearchAction,
    M365IdentityLookupAction,
    SmartActionManifest,
    SmartActionRegistry,
    SmartActionService,
    SuggestResolutionAction,
    TicketEscalationAction,
    TicketQualityAction,
    TicketSentimentAction,
    TicketSummaryAction,
    TicketTriageAction,
    _json_list,
    _json_object,
    _stored_action_status,
)
from wait_local_agent.store import Store


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

    triage = TicketTriageAction().run(context, {"ticket_id": "TCK-1001"})
    summary = TicketSummaryAction().run(context, {"ticket_id": "TCK-1001"})
    resolution = SuggestResolutionAction().run(context, {"ticket_id": "TCK-1002"})
    knowledge = KnowledgeSearchAction().run(context, {"ticket_id": "TCK-1001"})
    identity = M365IdentityLookupAction().run(
        replace(context, client_id="acme"),
        {"identity": "ADMIN@ACME.EXAMPLE"},
    )
    quality = TicketQualityAction().run(context, {"ticket_id": "TCK-1001"})
    sentiment = TicketSentimentAction().run(context, {"ticket_id": "TCK-1001"})
    escalation = TicketEscalationAction().run(context, {"ticket_id": "TCK-1001"})
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
        == quality.status
        == sentiment.status
        == escalation.status
        == similar.status
        == dispatch.status
        == "success"
    )
    assert summary.output["suggested_response"] == "Resolution for TCK-1001"
    assert resolution.output["citations"]
    assert knowledge.output["ticket_id"] == "TCK-1001"
    assert identity.output["count"] == 1
    assert identity.output["matches"][0]["user_principal_name"] == "admin@acme.example"  # type: ignore[index]
    assert quality.output["passed"] is True
    assert sentiment.output["sentiment"] == "negative"
    assert escalation.output["urgency"] == "same_day"
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
        TicketQualityAction(),
        TicketSentimentAction(),
        TicketEscalationAction(),
        FindSimilarTicketsAction(),
        DispatchSuggestionAction(),
    )
    for action in actions:
        assert action.run(context, {}) .status == "failed"

    assert CollectorPreviewAction().run(context, {}).status == "failed"
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
        "collector-preview",
        "dispatch-suggestion",
        "find-similar-tickets",
        "knowledge-search",
        "m365-identity-lookup",
        "suggest-resolution",
        "ticket-escalation",
        "ticket-quality",
        "ticket-sentiment",
        "ticket-summary",
        "ticket-triage",
    ]
    assert service.describe("ticket-triage").kind == "deterministic"


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


def test_ai_actions_report_missing_provider(settings) -> None:
    store = Store(settings.data_path)
    _seed_tickets(store)
    service = SmartActionService(store, settings)

    result = service.invoke("ticket-summary", {"ticket_id": "TCK-1001"}, "technician")

    assert result.status == "provider_not_configured"
    assert result.error_detail
    assert result.run_id is not None
    assert store.get_smart_action_run(result.run_id).status == "provider_not_configured"  # type: ignore[union-attr]


def test_deterministic_provider_never_reports_ai_when_inference_is_enabled(settings) -> None:
    store = Store(settings.data_path)
    _seed_tickets(store)
    service = SmartActionService(store, replace(settings, allow_llm_inference=True))

    result = service.invoke("ticket-summary", {"ticket_id": "TCK-1001"}, "technician")

    assert result.status == "provider_not_configured"
    assert result.output == {}


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
