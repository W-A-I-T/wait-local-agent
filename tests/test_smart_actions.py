from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from wait_local_agent.models import SourceReference, Ticket
from wait_local_agent.rbac import Role
from wait_local_agent.reports.renderers import redact_value
from wait_local_agent.smart_actions import (
    ActionResult,
    SmartActionManifest,
    SmartActionRegistry,
    SmartActionService,
)
from wait_local_agent.store import Store


def test_redacts_embedded_secrets_in_free_text_payload_values() -> None:
    payload = redact_value({"note": "token=abc password=def secret=ghi key=jkl AKIA1234567890ABCDEF"})

    assert payload == {"note": "token=[redacted] password=[redacted] secret=[redacted] key=[redacted] [redacted]"}


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


def test_registry_lists_all_seed_actions(settings) -> None:
    service = SmartActionService(Store(settings.data_path), settings)

    assert [manifest.action_id for manifest in service.list()] == [
        "dispatch-suggestion",
        "find-similar-tickets",
        "suggest-resolution",
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
                output={"api_key": "raw-key", "nested": {"password": "raw-password"}},
                evidence=[{"token": "raw-token"}],
            )

    registry = SmartActionRegistry()
    registry.register(SecretAction())
    store = Store(settings.data_path)
    result = SmartActionService(store, settings, registry=registry).invoke(
        "secret-test", {"token": "payload-token"}, "actor"
    )

    assert result.output["api_key"] == "[redacted]"
    assert result.evidence[0]["token"] == "[redacted]"
    run = store.get_smart_action_run(result.run_id or 0)
    assert run is not None
    assert "raw-key" not in run.output_json
    assert "raw-token" not in run.evidence_json
