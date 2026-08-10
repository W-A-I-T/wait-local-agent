from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

import wait_local_agent.agents as agents_module
import wait_local_agent.api.app as app_module
from wait_local_agent.agents import AgentDefinitionError, AgentService
from wait_local_agent.api.app import create_app
from wait_local_agent.models import (
    AgentDefinitionRevision,
    AgentRun,
    HaloTicket,
    HuduArticle,
    SourceReference,
    Ticket,
)
from wait_local_agent.providers import ProviderUnavailableError
from wait_local_agent.rbac import Role
from wait_local_agent.smart_actions import ActionResult, SmartActionService
from wait_local_agent.store import Store


def _seed(store: Store, *, client_id: str | None = None) -> None:
    store.ingest_ticket_file(Path("examples/sample_tickets/tickets.json"))
    if client_id is not None:
        with store._connect() as connection:  # noqa: SLF001
            connection.execute("update tickets set client_id = ?", (client_id,))


def _service(settings, *, client_id: str | None = "acme") -> AgentService:
    store = Store(settings.data_path)
    _seed(store, client_id=client_id)
    actions = SmartActionService(store, settings)
    return AgentService(store, settings, actions)


def _create(service: AgentService, *, client_id: str | None = "acme"):
    return service.create(
        name="Ticket triage agent",
        description="Runs the existing deterministic triage action.",
        enabled=True,
        trigger="manual",
        entity_type="ticket",
        filters={},
        enabled_tools=["ticket-triage"],
        steps=[{"tool_id": "ticket-triage", "payload": {}}],
        max_steps=1,
        execution_timeout_seconds=30,
        client_id=client_id,
    )


def test_tool_catalog_reuses_smart_action_contract(settings) -> None:
    service = _service(settings)

    tools = {tool.id: tool for tool in service.list_tools()}

    assert set(tools) == {
        "autotask-ticket-add-note",
        "autotask-ticket-add-time-entry",
        "autotask-ticket-assign-technician",
        "autotask-ticket-lookup",
        "autotask-ticket-update-status",
        "autotask-ticket-update-resolution",
        "ticket-triage",
        "ticket-summary",
        "suggest-resolution",
        "find-similar-tickets",
        "knowledge-search",
        "m365-identity-lookup",
        "m365-live-context",
        "m365-authentication-method-remove",
        "m365-group-membership",
        "m365-user-offboarding",
        "m365-user-onboarding",
        "m365-license-change",
        "m365-mailbox-settings",
        "m365-mail-message-delete",
        "m365-mail-message-move",
        "m365-mail-message-read-state",
        "m365-session-revocation",
        "m365-managed-device-reboot",
        "m365-managed-device-remote-lock",
        "m365-managed-device-retire",
        "m365-managed-device-sync",
        "m365-password-reset",
        "halopsa-ticket-lookup",
        "halopsa-ticket-add-note",
        "halopsa-ticket-assign-technician",
        "halopsa-ticket-draft-response",
        "halopsa-ticket-status-update",
        "halopsa-ticket-update-fields",
        "hudu-documentation-search",
        "itglue-documentation-search",
        "rmm-device-lookup",
        "rmm-alert-lookup",
        "rmm-script-catalog",
        "rmm-script-preview",
        "rmm-script-execute",
        "rmm-script-execution-lookup",
        "security-alert-assessment",
        "ticket-quality",
        "ticket-escalation",
        "ticket-sentiment",
        "ticket-sla-assessment",
        "recurring-service-review",
        "stale-ticket-sweep",
        "communication-draft",
        "communication-send",
        "documentation-assisted-response",
        "connectwise-ticket-lookup",
        "connectwise-ticket-assign-technician",
        "connectwise-ticket-status-update",
        "connectwise-ticket-update-fields",
        "confluence-documentation-search",
        "notion-documentation-search",
        "notion-data-source-query",
        "notion-page-comment",
        "syncro-ticket-lookup",
        "syncro-ticket-comments",
        "syncro-ticket-add-note",
        "screenconnect-session-note",
        "screenconnect-session-message",
        "servicenow-incident-add-work-note",
        "servicenow-incident-assign",
        "servicenow-incident-lookup",
        "servicenow-incident-update-state",
        "servicenow-incident-update-resolution",
        "sharepoint-document-content",
        "sharepoint-documentation-search",
        "dispatch-suggestion",
        "collector-preview",
    }
    assert tools["ticket-triage"].access_mode == "read"
    assert tools["dispatch-suggestion"].approval_required is True


def test_plan_preview_selects_existing_tools_without_executing(settings) -> None:
    service = _service(settings)

    result = service.plan(
        "Triage this ticket, search the runbook, and suggest a resolution.",
        entity_id="TCK-1001",
        client_id="acme",
    )

    assert result.status == "preview"
    assert [step["tool_id"] for step in result.steps] == [
        "knowledge-search",
        "ticket-triage",
        "suggest-resolution",
    ]
    assert result.context["ticket"]["id"] == "TCK-1001"  # type: ignore[index]
    assert result.definition["enabled"] is False
    assert result.definition["steps"] == [
        {"tool_id": "knowledge-search", "payload": {}},
        {"tool_id": "ticket-triage", "payload": {}},
        {"tool_id": "suggest-resolution", "payload": {}},
    ]
    assert service.store.list_agent_runs(client_id="acme") == []
    assert all("approval_required" in step for step in result.steps)
    assert result.selection_mode == "deterministic"


def test_plan_preview_uses_configured_model_but_keeps_catalog_scope(settings) -> None:
    store = Store(settings.data_path)
    _seed(store, client_id="acme")

    class PlanningProvider:
        def summarize_ticket(self, ticket: Ticket, sources: list[SourceReference]) -> str:
            return "summary"

        def draft_response(self, ticket: Ticket, sources: list[SourceReference]) -> str:
            return "response"

        def select_tools(
            self,
            instruction: str,
            ticket: Ticket,
            sources: list[SourceReference],
            tools: list[dict[str, str]],
            *,
            max_tools: int,
        ) -> list[str]:
            return ["ticket-summary", "not-a-registered-tool", "knowledge-search"]

    actions = SmartActionService(
        store,
        settings,
        provider=PlanningProvider(),
        provider_configured=True,
    )
    service = AgentService(store, settings, actions)

    result = service.plan(
        "Use the configured planner for this ticket.",
        entity_id="TCK-1001",
        client_id="acme",
        max_steps=3,
    )

    assert result.status == "preview"
    assert result.selection_mode == "model"
    assert [step["tool_id"] for step in result.steps] == [
        "ticket-summary",
        "knowledge-search",
    ]
    assert store.list_agent_runs(client_id="acme") == []


def test_plan_preview_blocks_unknown_requests_and_enforces_scope(settings) -> None:
    service = _service(settings)

    blocked = service.plan("Please do something unrelated.", entity_id="TCK-1001", client_id="acme")

    assert blocked.status == "blocked"
    assert blocked.steps == []
    with pytest.raises(AgentDefinitionError, match="not found in the requested scope"):
        service.plan("summarize", entity_id="TCK-1001", client_id="other")


def test_agent_executes_bounded_steps_and_records_grouped_trace(settings) -> None:
    service = _service(settings)
    definition = service.create(
        name="Triage and similar tickets",
        description="Use two existing local actions.",
        enabled=True,
        trigger="manual",
        entity_type="ticket",
        filters={},
        enabled_tools=["ticket-triage", "find-similar-tickets"],
        steps=[
            {"tool_id": "ticket-triage", "payload": {}},
            {"tool_id": "find-similar-tickets", "payload": {}},
        ],
        max_steps=2,
        execution_timeout_seconds=30,
        client_id="acme",
    )

    result = service.run(definition, entity_id="TCK-1001", actor="requester", input_payload={})

    assert result.status == "completed"
    assert result.final_result["status"] == "success"
    assert result.final_result["tool_id"] == "find-similar-tickets"
    assert isinstance(result.final_result["output"], dict)
    assert service.store.get_agent_run(result.run_id, client_id="acme").revision_version == definition.version  # type: ignore[union-attr]
    assert [step["status"] for step in result.steps] == ["success", "success"]
    executions = service.store.list_execution_runs(client_id="acme", run_kind="agent")
    assert len(executions) == 1
    assert executions[0].source_run_id == result.run_id
    assert len(service.store.list_execution_steps(executions[0].id or 0)) == 2


def test_result_aware_agent_uses_model_selection_and_never_repeats_tools(settings) -> None:
    store = Store(settings.data_path)
    _seed(store, client_id="acme")

    class ResultAwareProvider:
        def summarize_ticket(self, ticket: Ticket, sources: list[SourceReference]) -> str:
            return "summary"

        def draft_response(self, ticket: Ticket, sources: list[SourceReference]) -> str:
            return "response"

        def select_next_tool(
            self,
            instruction: str,
            ticket: Ticket,
            sources: list[SourceReference],
            tools: list[dict[str, str]],
            previous_result: dict[str, object] | None,
            completed_tool_ids: list[str],
        ) -> str:
            return "ticket-summary" if "ticket-summary" not in completed_tool_ids else "ticket-triage"

    service = AgentService(
        store,
        settings,
        SmartActionService(
            store,
            settings,
            provider=ResultAwareProvider(),
            provider_configured=True,
        ),
    )
    definition = service.create(
        name="Result-aware triage",
        description="Inspect each result before selecting the next approved tool.",
        enabled=True,
        trigger="manual",
        entity_type="ticket",
        filters={},
        enabled_tools=["ticket-triage", "ticket-summary"],
        steps=[
            {"tool_id": "ticket-triage", "payload": {}},
            {"tool_id": "ticket-summary", "payload": {}},
        ],
        max_steps=2,
        execution_timeout_seconds=30,
        client_id="acme",
        result_aware=True,
    )

    result = service.run(definition, entity_id="TCK-1001", actor="requester", input_payload={})

    assert result.status == "completed"
    assert [step["tool_id"] for step in result.steps] == ["ticket-summary", "ticket-triage"]
    assert [
        cast(dict[str, object], step["continuation"]).get("selection_mode")
        for step in result.steps
    ] == ["model", "model"]
    assert definition.result_aware is True
    persisted = service.store.get_agent_definition(definition.id, client_id="acme")
    assert persisted is not None and persisted.result_aware is True


@pytest.mark.parametrize("provider_mode", ["unavailable", "invalid"])
def test_result_aware_agent_uses_deterministic_fallback_and_stops_at_remaining_catalog(
    settings, provider_mode: str
) -> None:
    store = Store(settings.data_path)
    _seed(store, client_id="acme")

    class Provider:
        def summarize_ticket(self, ticket: Ticket, sources: list[SourceReference]) -> str:
            return "summary"

        def draft_response(self, ticket: Ticket, sources: list[SourceReference]) -> str:
            return "response"

        def select_next_tool(self, *args, **kwargs) -> str:
            if provider_mode == "unavailable":
                raise RuntimeError("provider unavailable")
            return "not-approved"

    service = AgentService(
        store,
        settings,
        SmartActionService(store, settings, provider=Provider(), provider_configured=True),
    )
    definition = service.create(
        name=f"Fallback {provider_mode}",
        description="Use a bounded fallback.",
        enabled=True,
        trigger="manual",
        entity_type="ticket",
        filters={},
        enabled_tools=["ticket-triage"],
        steps=[{"tool_id": "ticket-triage", "payload": {}}],
        max_steps=2,
        execution_timeout_seconds=30,
        client_id="acme",
        result_aware=True,
        context_sources=["ticket"],
    )

    result = service.run(definition, entity_id="TCK-1001", actor="requester", input_payload={})

    assert result.status == "completed"
    assert len(result.steps) == 1
    assert cast(dict[str, object], result.steps[0]["continuation"]).get("selection_mode") in {
        "deterministic-fallback",
        "deterministic-rejected-model",
    }


def test_result_aware_agent_preserves_approval_pause_and_failure(settings) -> None:
    service = _service(settings)
    approval_definition = service.create(
        name="Result-aware approval",
        description="Pause before dispatch.",
        enabled=True,
        trigger="manual",
        entity_type="ticket",
        filters={},
        enabled_tools=["dispatch-suggestion"],
        steps=[{"tool_id": "dispatch-suggestion", "payload": {}}],
        max_steps=1,
        execution_timeout_seconds=30,
        client_id="acme",
        result_aware=True,
    )
    pending = service.run(approval_definition, entity_id="TCK-1001", actor="requester", input_payload={})
    assert pending.status == "pending_approval"

    class UnavailableProvider:
        def summarize_ticket(self, ticket: Ticket, sources: list[SourceReference]) -> str:
            raise ProviderUnavailableError("offline")

        def draft_response(self, ticket: Ticket, sources: list[SourceReference]) -> str:
            raise ProviderUnavailableError("offline")

    failure_service = AgentService(
        service.store,
        settings,
        SmartActionService(
            service.store,
            settings,
            provider=UnavailableProvider(),
            provider_configured=True,
        ),
    )
    failure_definition = failure_service.create(
        name="Result-aware failure",
        description="Fail without a model.",
        enabled=True,
        trigger="manual",
        entity_type="ticket",
        filters={},
        enabled_tools=["suggest-resolution"],
        steps=[{"tool_id": "suggest-resolution", "payload": {}}],
        max_steps=1,
        execution_timeout_seconds=30,
        client_id="acme",
        result_aware=True,
    )
    failed = failure_service.run(
        failure_definition, entity_id="TCK-1001", actor="requester", input_payload={}
    )
    assert failed.status == "failed"


def test_agent_context_sources_are_selected_scoped_and_recorded(settings) -> None:
    service = _service(settings)
    service.store.upsert_knowledge_document(
        path="examples/sample_docs/mfa-runbook.md",
        title="MFA Runbook",
        kind="markdown",
        checksum="mfa-checksum",
        modified_at="2026-08-08T00:00:00+00:00",
        chunks=["MFA phone replacement requires identity verification and a new authenticator registration."],
        client_id="acme",
    )
    definition = service.create(
        name="Context-aware triage",
        description="Pass selected ticket and knowledge context to bounded tools.",
        enabled=True,
        trigger="manual",
        entity_type="ticket",
        filters={},
        enabled_tools=["ticket-triage"],
        steps=[{"tool_id": "ticket-triage", "payload": {}}],
        max_steps=1,
        execution_timeout_seconds=30,
        client_id="acme",
        context_sources=["ticket", "client", "knowledge"],
    )

    result = service.run(definition, entity_id="TCK-1001", actor="requester", input_payload={})
    persisted = service.store.get_agent_run(result.run_id, client_id="acme")
    assert persisted is not None
    state = json.loads(persisted.state_json)
    assert set(state["context"]) == {"ticket", "client", "knowledge"}
    assert state["context"]["knowledge"]["status"] == "ready"
    assert state["context"]["ticket"]["id"] == "TCK-1001"
    assert state["context"]["client"] == {"id": "acme", "name": "Northwind Dental"}
    assert state["context"]["knowledge"]["count"] == 1
    assert state["steps"][0]["input"]["_agent_context"] == state["context"]

    with pytest.raises(AgentDefinitionError, match="unsupported context sources"):
        service.create(
            name="Invalid context",
            description="",
            enabled=True,
            trigger="manual",
            entity_type="ticket",
            filters={},
            enabled_tools=["ticket-triage"],
            steps=[{"tool_id": "ticket-triage", "payload": {}}],
            max_steps=1,
            execution_timeout_seconds=30,
            client_id="acme",
            context_sources=["secrets"],
        )
    with pytest.raises(AgentDefinitionError, match="duplicates"):
        service.create(
            name="Duplicate context",
            description="",
            enabled=True,
            trigger="manual",
            entity_type="ticket",
            filters={},
            enabled_tools=["ticket-triage"],
            steps=[{"tool_id": "ticket-triage", "payload": {}}],
            max_steps=1,
            execution_timeout_seconds=30,
            client_id="acme",
            context_sources=["ticket", "ticket"],
        )
    with pytest.raises(AgentDefinitionError, match="contain 0-3"):
        service.create(
            name="Too much context",
            description="",
            enabled=True,
            trigger="manual",
            entity_type="ticket",
            filters={},
            enabled_tools=["ticket-triage"],
            steps=[{"tool_id": "ticket-triage", "payload": {}}],
            max_steps=1,
            execution_timeout_seconds=30,
            client_id="acme",
            context_sources=["ticket", "client", "knowledge", "extra"],
        )
    with pytest.raises(AgentDefinitionError, match="non-empty strings"):
        service.create(
            name="Empty context",
            description="",
            enabled=True,
            trigger="manual",
            entity_type="ticket",
            filters={},
            enabled_tools=["ticket-triage"],
            steps=[{"tool_id": "ticket-triage", "payload": {}}],
            max_steps=1,
            execution_timeout_seconds=30,
            client_id="acme",
            context_sources=[""],
        )


def test_agent_context_reports_knowledge_unavailable(settings, monkeypatch) -> None:
    service = _service(settings)
    definition = service.create(
        name="Unavailable knowledge context",
        description="Surface retrieval failure without treating it as no matches.",
        enabled=True,
        trigger="manual",
        entity_type="ticket",
        filters={},
        enabled_tools=["ticket-triage"],
        steps=[{"tool_id": "ticket-triage", "payload": {}}],
        max_steps=1,
        execution_timeout_seconds=30,
        client_id="acme",
        context_sources=["knowledge"],
    )
    def unavailable(*args, **kwargs):
        raise RuntimeError("backend unavailable")

    monkeypatch.setattr(agents_module, "retrieve_sources", unavailable)

    context = service._build_context(definition, "TCK-1001")  # noqa: SLF001

    assert context["knowledge"] == {"status": "unavailable", "sources": [], "count": 0}


def test_agent_execution_windows_normalize_timezones_and_support_overnight_ranges(settings) -> None:
    service = _service(settings)
    definition = service.create(
        name="Business-hours triage",
        description="Run during the tenant's local business hours.",
        enabled=True,
        trigger="manual",
        entity_type="ticket",
        filters={},
        enabled_tools=["ticket-triage"],
        steps=[{"tool_id": "ticket-triage", "payload": {}}],
        max_steps=1,
        execution_timeout_seconds=30,
        client_id="acme",
        execution_window_start="09:00",
        execution_window_end="17:00",
        execution_window_timezone=" America/Vancouver ",
    )

    assert definition.execution_window_start == "09:00"
    assert definition.execution_window_end == "17:00"
    assert definition.execution_window_timezone == "America/Vancouver"
    assert AgentService.execution_window_open(
        definition,
        now=datetime(2026, 8, 7, 16, 0, tzinfo=UTC),
    )
    assert not AgentService.execution_window_open(
        definition,
        now=datetime(2026, 8, 8, 1, 0, tzinfo=UTC),
    )

    overnight = service.update(
        definition,
        name=definition.name,
        description=definition.description,
        enabled=True,
        trigger=definition.trigger,
        entity_type=definition.entity_type,
        filters=definition.filters,
        enabled_tools=definition.enabled_tools,
        steps=definition.steps,
        max_steps=definition.max_steps,
        execution_timeout_seconds=definition.execution_timeout_seconds,
        execution_window_start="22:00",
        execution_window_end="06:00",
        execution_window_timezone="UTC",
    )
    assert AgentService.execution_window_open(
        overnight,
        now=datetime(2026, 8, 7, 23, 30, tzinfo=UTC),
    )
    assert AgentService.execution_window_open(
        overnight,
        now=datetime(2026, 8, 8, 5, 59, tzinfo=UTC),
    )
    assert not AgentService.execution_window_open(
        overnight,
        now=datetime(2026, 8, 8, 6, 0, tzinfo=UTC),
    )


def test_agent_execution_windows_reject_malformed_definitions(settings) -> None:
    service = _service(settings)
    for start, end, timezone, message in [
        ("09:00", None, "UTC", "provided together"),
        ("9:00", "17:00", "UTC", "HH:MM"),
        ("09:00", "17:00", "Mars/Olympus", "IANA"),
        ("09:00", "09:00", "UTC", "must differ"),
    ]:
        with pytest.raises(AgentDefinitionError, match=message):
            service.create(
                name="Window validation",
                description="",
                enabled=True,
                trigger="manual",
                entity_type="ticket",
                filters={},
                enabled_tools=["ticket-triage"],
                steps=[{"tool_id": "ticket-triage", "payload": {}}],
                max_steps=1,
                execution_timeout_seconds=30,
                client_id="acme",
                execution_window_start=start,
                execution_window_end=end,
                execution_window_timezone=timezone,
            )


def test_agent_run_does_not_persist_when_execution_window_is_closed(settings) -> None:
    service = _service(settings)
    now = datetime.now(UTC)
    start = (now + timedelta(hours=2)).strftime("%H:%M")
    end = (now + timedelta(hours=3)).strftime("%H:%M")
    definition = service.create(
        name="Closed-window triage",
        description="Should wait until its execution window opens.",
        enabled=True,
        trigger="manual",
        entity_type="ticket",
        filters={},
        enabled_tools=["ticket-triage"],
        steps=[{"tool_id": "ticket-triage", "payload": {}}],
        max_steps=1,
        execution_timeout_seconds=30,
        client_id="acme",
        execution_window_start=start,
        execution_window_end=end,
        execution_window_timezone="UTC",
    )

    with pytest.raises(AgentDefinitionError, match="window is closed"):
        service.run(definition, entity_id="TCK-1001", actor="requester", input_payload={})
    assert service.store.list_agent_runs(client_id="acme") == []


def test_agent_final_result_redacts_action_output(settings, monkeypatch) -> None:
    service = _service(settings)
    definition = _create(service)

    monkeypatch.setattr(
        service.smart_actions,
        "invoke",
        lambda *args, **kwargs: ActionResult(
            status="success",
            output={"api_key": "supersecret", "classification": "network"},
        ),
    )

    result = service.run(definition, entity_id="TCK-1001", actor="requester", input_payload={})

    assert result.final_result["output"] == {"api_key": "[redacted]", "classification": "network"}
    persisted = service.store.get_agent_run(result.run_id, client_id="acme")
    assert persisted is not None
    assert "supersecret" not in persisted.state_json


def test_write_like_action_stops_for_approval_and_resumes_only_with_other_approver(settings) -> None:
    service = _service(settings)
    definition = service.create(
        name="Dispatch review",
        description="Prepare a dispatch proposal.",
        enabled=True,
        trigger="manual",
        entity_type="ticket",
        filters={},
        enabled_tools=["dispatch-suggestion"],
        steps=[{"tool_id": "dispatch-suggestion", "payload": {"technicians": []}}],
        max_steps=1,
        execution_timeout_seconds=30,
        client_id="acme",
    )

    pending = service.run(definition, entity_id="TCK-1001", actor="requester", input_payload={})

    assert pending.status == "pending_approval"
    assert pending.approval_id is not None
    assert pending.final_result["status"] == "pending_approval"
    assert pending.final_result["tool_id"] == "dispatch-suggestion"
    with pytest.raises(PermissionError, match="cannot approve"):
        service.resume(
            definition,
            service.store.get_agent_run(pending.run_id, client_id="acme"),  # type: ignore[arg-type]
            approver="requester",
            approver_role=Role.TECHNICIAN,
        )

    resumed = service.resume(
        definition,
        service.store.get_agent_run(pending.run_id, client_id="acme"),  # type: ignore[arg-type]
        approver="approver",
        approver_role=Role.TECHNICIAN,
    )
    assert resumed.status == "completed"
    assert resumed.steps[0]["status"] == "success"
    assert resumed.final_result["status"] == "success"


def test_agent_can_add_approval_to_a_read_only_tool(settings) -> None:
    service = _service(settings)
    definition = service.create(
        name="Reviewed triage",
        description="Require a human review before a read-only triage result is accepted.",
        enabled=True,
        trigger="manual",
        entity_type="ticket",
        filters={},
        enabled_tools=["ticket-triage"],
        steps=[{"tool_id": "ticket-triage", "payload": {}}],
        max_steps=1,
        execution_timeout_seconds=30,
        client_id="acme",
        approval_required_tools=["ticket-triage"],
    )

    assert service.get(definition.id, client_id="acme").approval_required_tools == ["ticket-triage"]  # type: ignore[union-attr]
    pending = service.run(definition, entity_id="TCK-1001", actor="requester", input_payload={})
    assert pending.status == "pending_approval"
    assert pending.approval_id is not None

    resumed = service.resume(
        definition,
        service.store.get_agent_run(pending.run_id, client_id="acme"),  # type: ignore[arg-type]
        approver="approver",
        approver_role=Role.TECHNICIAN,
    )
    assert resumed.status == "completed"


def test_agent_conditional_approval_matches_explicit_ticket_fields(settings) -> None:
    service = _service(settings)
    definition = service.create(
        name="Priority-gated triage",
        description="Require review for high-priority triage.",
        enabled=True,
        trigger="manual",
        entity_type="ticket",
        filters={},
        enabled_tools=["ticket-triage"],
        steps=[{"tool_id": "ticket-triage", "payload": {}}],
        max_steps=1,
        execution_timeout_seconds=30,
        client_id="acme",
        approval_rules=[
            {"tool_id": "ticket-triage", "when": {"priority": ["HIGH", " high "]}}
        ],
    )

    persisted = service.store.get_agent_definition(definition.id, client_id="acme")
    assert persisted is not None
    assert persisted.approval_rules == [{"tool_id": "ticket-triage", "when": {"priority": ["high"]}}]

    high_priority = service.run(definition, entity_id="TCK-1001", actor="requester", input_payload={})
    assert high_priority.status == "pending_approval"
    assert high_priority.steps[0]["approval_policy"] == {
        "type": "conditional",
        "tool_id": "ticket-triage",
        "when": {"priority": ["high"]},
    }

    medium_priority = service.run(definition, entity_id="TCK-1002", actor="requester", input_payload={})
    assert medium_priority.status == "completed"
    assert "approval_policy" not in medium_priority.steps[0]


def test_agent_conditional_approval_rules_are_bounded(settings) -> None:
    service = _service(settings)
    base: dict[str, Any] = {
        "name": "Invalid conditional approval",
        "description": "",
        "enabled": True,
        "trigger": "manual",
        "entity_type": "ticket",
        "filters": {},
        "enabled_tools": ["ticket-triage"],
        "steps": [{"tool_id": "ticket-triage", "payload": {}}],
        "max_steps": 1,
        "execution_timeout_seconds": 30,
        "client_id": "acme",
    }
    invalid_rules: list[tuple[Any, str]] = [
        ([{}], "tool_id must be a non-empty string"),
        (
            [{"tool_id": "ticket-triage", "when": {"priority": ["high"]}, "extra": True}],
            "may only contain tool_id and when",
        ),
        ([{"tool_id": "not-enabled", "when": {"priority": ["high"]}}], "must be enabled"),
        ([{"tool_id": "ticket-triage", "when": {"unknown": ["high"]}}], "unsupported approval rule fields"),
        ([{"tool_id": "ticket-triage", "when": {}}], "at least one condition"),
        ([{"tool_id": "ticket-triage", "when": {"priority": [""]}}], "non-empty strings"),
        (
            [{"tool_id": "ticket-triage", "when": {"priority": ["high"] * 9}}],
            "must contain 1-8 values",
        ),
        (
            [{"tool_id": "ticket-triage", "when": {"priority": ["x" * 41]}}],
            "at most 40 characters",
        ),
        ([
            {"tool_id": "ticket-triage", "when": {"priority": ["high"]}},
            {"tool_id": "ticket-triage", "when": {"status": ["new"]}},
        ], "must not duplicate tool"),
        (
            [{"tool_id": "ticket-triage", "when": {"priority": ["high"]}} for _ in range(9)],
            "contain 0-8 rules",
        ),
    ]
    for rules, message in invalid_rules:
        with pytest.raises(AgentDefinitionError, match=message):
            service.create(**base, approval_rules=rules)

    with pytest.raises(AgentDefinitionError, match="actor_role values must be one of"):
        service.create(
            **base,
            approval_rules=[
                {"tool_id": "ticket-triage", "when": {"actor_role": ["owner"]}}
            ],
        )


def test_agent_conditional_approval_matches_authenticated_role_and_survives_resume(settings) -> None:
    service = _service(settings)
    definition = service.create(
        name="Role-gated triage",
        description="Require review for technician-triggered triage and summary.",
        enabled=True,
        trigger="manual",
        entity_type="ticket",
        filters={},
        enabled_tools=["ticket-triage", "ticket-summary"],
        steps=[
            {"tool_id": "ticket-triage", "payload": {}},
            {"tool_id": "ticket-summary", "payload": {}},
        ],
        max_steps=2,
        execution_timeout_seconds=30,
        client_id="acme",
        approval_rules=[
            {"tool_id": "ticket-triage", "when": {"actor_role": ["TECHNICIAN"]}},
            {"tool_id": "ticket-summary", "when": {"actor_role": ["technician"]}},
        ],
    )

    technician = service.run(
        definition,
        entity_id="TCK-1001",
        actor="technician",
        actor_role=Role.TECHNICIAN,
        input_payload={},
    )
    assert technician.status == "pending_approval"
    technician_policy = cast(dict[str, object], technician.steps[0]["approval_policy"])
    assert technician_policy["when"] == {"actor_role": ["technician"]}
    stored = service.store.get_agent_run(technician.run_id, client_id="acme")
    assert stored is not None
    assert json.loads(stored.state_json)["actor_role"] == "technician"

    second_pending = service.resume(
        definition,
        stored,
        approver="admin",
        approver_role=Role.ADMIN,
    )
    assert second_pending.status == "pending_approval"
    second_policy = cast(dict[str, object], second_pending.steps[1]["approval_policy"])
    assert second_policy["when"] == {"actor_role": ["technician"]}

    completed = service.resume(
        definition,
        service.store.get_agent_run(second_pending.run_id, client_id="acme"),  # type: ignore[arg-type]
        approver="admin",
        approver_role=Role.ADMIN,
    )
    assert completed.status == "completed"

    no_role = service.run(
        definition,
        entity_id="TCK-1002",
        actor="scheduler",
        input_payload={},
    )
    assert no_role.status == "completed"

    wrong_role = service.run(
        definition,
        entity_id="TCK-1002",
        actor="admin",
        actor_role=Role.ADMIN,
        input_payload={},
    )
    assert wrong_role.status == "completed"
    assert agents_module._actor_role_from_state({"actor_role": "owner"}) is None  # noqa: SLF001
    assert (
        agents_module._approval_policy_for_ticket(  # noqa: SLF001
            definition,
            "ticket-triage",
            "NOPE",
            service.store,
            actor_role=Role.ADMIN,
        )
        is None
    )


def test_agent_approval_policy_shortens_tool_deadline(settings) -> None:
    service = _service(settings)
    definition = service.create(
        name="Short approval dispatch",
        description="Use a one-hour approval policy for dispatch proposals.",
        enabled=True,
        trigger="manual",
        entity_type="ticket",
        filters={},
        enabled_tools=["dispatch-suggestion"],
        steps=[{"tool_id": "dispatch-suggestion", "payload": {"technicians": []}}],
        max_steps=1,
        execution_timeout_seconds=30,
        client_id="acme",
        approval_expiry_seconds=60 * 60,
    )

    pending = service.run(definition, entity_id="TCK-1001", actor="requester", input_payload={})

    assert pending.status == "pending_approval"
    approval = service.store.get_approval_request(pending.approval_id or 0)
    assert approval is not None
    assert approval.expires_at is not None
    assert (
        datetime.fromisoformat(approval.expires_at)
        - datetime.fromisoformat(approval.created_at)
        == timedelta(hours=1)
    )

    extended_definition = service.create(
        name="Capped approval dispatch",
        description="A policy cannot extend the dispatch tool deadline.",
        enabled=True,
        trigger="manual",
        entity_type="ticket",
        filters={},
        enabled_tools=["dispatch-suggestion"],
        steps=[{"tool_id": "dispatch-suggestion", "payload": {"technicians": []}}],
        max_steps=1,
        execution_timeout_seconds=30,
        client_id="acme",
        approval_expiry_seconds=2 * 24 * 60 * 60,
    )
    extended_pending = service.run(
        extended_definition,
        entity_id="TCK-1001",
        actor="requester-2",
        input_payload={},
    )
    extended_approval = service.store.get_approval_request(extended_pending.approval_id or 0)
    assert extended_approval is not None and extended_approval.expires_at is not None
    assert (
        datetime.fromisoformat(extended_approval.expires_at)
        - datetime.fromisoformat(extended_approval.created_at)
        == timedelta(days=1)
    )


def test_agent_approval_policy_bounds_are_enforced(settings) -> None:
    service = _service(settings)

    with pytest.raises(AgentDefinitionError, match="approval_expiry_seconds"):
        service.create(
            name="Invalid approval policy",
            description="",
            enabled=True,
            trigger="manual",
            entity_type="ticket",
            filters={},
            enabled_tools=["dispatch-suggestion"],
            steps=[{"tool_id": "dispatch-suggestion", "payload": {}}],
            max_steps=1,
            execution_timeout_seconds=30,
            client_id="acme",
            approval_expiry_seconds=0,
        )

    with pytest.raises(AgentDefinitionError, match="enabled tools"):
        service.create(
            name="Invalid tool approval policy",
            description="",
            enabled=True,
            trigger="manual",
            entity_type="ticket",
            filters={},
            enabled_tools=["ticket-triage"],
            steps=[{"tool_id": "ticket-triage", "payload": {}}],
            max_steps=1,
            execution_timeout_seconds=30,
            client_id="acme",
            approval_required_tools=["dispatch-suggestion"],
        )

    for invalid_policy, message in (
        (["ticket-triage"] * 9, "contain 0-8"),
        (cast(list[str], [123]), "non-empty strings"),
        (["ticket-triage", "ticket-triage"], "duplicates"),
    ):
        with pytest.raises(AgentDefinitionError, match=message):
            service.create(
                name="Invalid additional approval policy",
                description="",
                enabled=True,
                trigger="manual",
                entity_type="ticket",
                filters={},
                enabled_tools=["ticket-triage"],
                steps=[{"tool_id": "ticket-triage", "payload": {}}],
                max_steps=1,
                execution_timeout_seconds=30,
                client_id="acme",
                approval_required_tools=invalid_policy,
            )


def test_agent_run_cancellation_revokes_pending_approval(settings) -> None:
    service = _service(settings)
    definition = service.create(
        name="Dispatch cancellation",
        description="Prepare a dispatch proposal that can be cancelled.",
        enabled=True,
        trigger="manual",
        entity_type="ticket",
        filters={},
        enabled_tools=["dispatch-suggestion"],
        steps=[{"tool_id": "dispatch-suggestion", "payload": {}}],
        max_steps=1,
        execution_timeout_seconds=30,
        client_id="acme",
    )

    pending = service.run(definition, entity_id="TCK-1001", actor="requester", input_payload={})
    cancelled = service.cancel(
        definition,
        service.store.get_agent_run(pending.run_id, client_id="acme"),  # type: ignore[arg-type]
        actor="requester",
        approver_role=Role.TECHNICIAN,
    )

    assert cancelled.status == "cancelled"
    assert cancelled.error_detail == "agent run cancelled"
    assert cancelled.final_result["status"] == "cancelled"
    assert cancelled.final_result["error_detail"] == "agent run cancelled"
    assert cancelled.approval_id is None
    approval = service.store.get_approval_request(pending.approval_id or 0)
    assert approval is not None
    assert approval.status == "rejected"
    action_run = next(
        action
        for action in service.store.list_smart_action_runs(client_id="acme")
        if action.approval_id == pending.approval_id
    )
    assert action_run is not None
    assert action_run.status == "rejected"
    assert service.resume(
        definition,
        service.store.get_agent_run(pending.run_id, client_id="acme"),  # type: ignore[arg-type]
        approver="approver",
        approver_role=Role.TECHNICIAN,
    ).status == "cancelled"


def test_pending_run_continues_from_its_revision_after_definition_update(settings) -> None:
    service = _service(settings)
    definition = service.create(
        name="Dispatch then triage",
        description="Keep the pending run tied to its original definition.",
        enabled=True,
        trigger="manual",
        entity_type="ticket",
        filters={},
        enabled_tools=["dispatch-suggestion", "ticket-triage"],
        steps=[
            {"tool_id": "dispatch-suggestion", "payload": {"technicians": []}},
            {"tool_id": "ticket-triage", "payload": {}},
        ],
        max_steps=2,
        execution_timeout_seconds=30,
        client_id="acme",
    )

    pending = service.run(definition, entity_id="TCK-1001", actor="requester", input_payload={})
    assert pending.status == "pending_approval"
    assert pending.revision_version == 1

    updated = service.update(
        definition,
        name="Only triage now",
        description="The active definition changed after the run started.",
        enabled=True,
        trigger="manual",
        entity_type="ticket",
        filters={},
        enabled_tools=["ticket-triage"],
        steps=[{"tool_id": "ticket-triage", "payload": {}}],
        max_steps=1,
        execution_timeout_seconds=30,
    )
    assert updated.version == 2

    resumed = service.resume(
        updated,
        service.store.get_agent_run(pending.run_id, client_id="acme"),  # type: ignore[arg-type]
        approver="approver",
        approver_role=Role.TECHNICIAN,
    )
    assert resumed.status == "completed"
    assert len(resumed.steps) == 2
    assert resumed.steps[1]["tool_id"] == "ticket-triage"


def test_agent_run_can_cancel_pending_approval_and_retry(settings) -> None:
    service = _service(settings)
    definition = service.create(
        name="Cancellable dispatch",
        description="Cancel the pending run before retrying it.",
        enabled=True,
        trigger="manual",
        entity_type="ticket",
        filters={},
        enabled_tools=["dispatch-suggestion"],
        steps=[{"tool_id": "dispatch-suggestion", "payload": {"technicians": []}}],
        max_steps=1,
        execution_timeout_seconds=30,
        client_id="acme",
    )

    pending = service.run(definition, entity_id="TCK-1001", actor="requester", input_payload={})
    cancelled = service.cancel(
        definition,
        service.store.get_agent_run(pending.run_id, client_id="acme"),  # type: ignore[arg-type]
        actor="approver",
        approver_role=Role.TECHNICIAN,
    )
    assert cancelled.status == "cancelled"
    assert cancelled.steps[0]["status"] == "cancelled"
    assert service.store.get_approval_request(pending.approval_id or 0).status == "rejected"  # type: ignore[union-attr]
    assert (
        service.cancel(
            definition,
            service.store.get_agent_run(pending.run_id, client_id="acme"),  # type: ignore[arg-type]
            actor="approver",
            approver_role=Role.TECHNICIAN,
        ).status
        == "cancelled"
    )

    assert cancelled.status == "cancelled"
    assert cancelled.error_detail == "agent run cancelled"
    assert cancelled.final_result["status"] == "cancelled"
    assert cancelled.final_result["error_detail"] == "agent run cancelled"
    assert cancelled.approval_id is None
    approval = service.store.get_approval_request(pending.approval_id or 0)
    assert approval is not None
    assert approval.status == "rejected"
    action_run = next(
        action
        for action in service.store.list_smart_action_runs(client_id="acme")
        if action.approval_id == pending.approval_id
    )
    assert action_run is not None
    assert action_run.status == "rejected"
    assert service.resume(
        definition,
        service.store.get_agent_run(pending.run_id, client_id="acme"),  # type: ignore[arg-type]
        approver="approver",
        approver_role=Role.TECHNICIAN,
    ).status == "cancelled"

    retried = service.retry(
        definition,
        service.store.get_agent_run(pending.run_id, client_id="acme"),  # type: ignore[arg-type]
        actor="requester",
    )
    assert retried.status == "pending_approval"
    assert retried.revision_version == definition.version

def test_agent_api_can_cancel_pending_run_and_preserves_tenant_scope(settings) -> None:
    scoped = settings.__class__(**{**settings.__dict__, "client_id": "acme"})
    store = Store(scoped.data_path)
    _seed(store, client_id="acme")
    client = TestClient(create_app(scoped))
    created = client.post(
        "/agents",
        json={
            "name": "Cancellable dispatch agent",
            "enabled_tools": ["dispatch-suggestion"],
            "steps": [{"tool_id": "dispatch-suggestion", "payload": {}}],
            "max_steps": 1,
            "client_id": "acme",
            "approval_expiry_seconds": 1800,
            "approval_required_tools": ["dispatch-suggestion"],
        },
    )
    assert created.status_code == 200
    assert created.json()["approval_expiry_seconds"] == 1800
    assert created.json()["approval_required_tools"] == ["dispatch-suggestion"]
    agent_id = created.json()["id"]
    pending = client.post(f"/agents/{agent_id}/run", json={"entity_id": "TCK-1001"})
    assert pending.status_code == 200
    run_id = pending.json()["run_id"]

    cancelled = client.post(f"/agent-runs/{run_id}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    assert client.get(f"/agent-runs/{run_id}").json()["status"] == "cancelled"
    assert client.post(f"/agent-runs/{run_id}/resume").json()["status"] == "cancelled"
    assert client.post(f"/agent-runs/{run_id}/cancel").json()["status"] == "cancelled"
    assert client.post(f"/agent-runs/{run_id}/cancel", params={"client_id": "other"}).status_code == 404


def test_agent_run_retry_is_bounded_and_preserves_input_trace(settings) -> None:
    class UnavailableProvider:
        def summarize_ticket(self, ticket: Ticket, sources: list[SourceReference]) -> str:
            raise ProviderUnavailableError("offline")

        def draft_response(self, ticket: Ticket, sources: list[SourceReference]) -> str:
            raise ProviderUnavailableError("offline")

    store = Store(settings.data_path)
    _seed(store, client_id="acme")
    service = AgentService(
        store,
        settings,
        SmartActionService(
            store,
            settings,
            provider=UnavailableProvider(),
            provider_configured=True,
        ),
    )
    definition = service.create(
        name="Retrying summary agent",
        description="Exercise bounded retry behavior.",
        enabled=True,
        trigger="manual",
        entity_type="ticket",
        filters={},
        enabled_tools=["suggest-resolution"],
        steps=[{"tool_id": "suggest-resolution", "payload": {}}],
        max_steps=1,
        execution_timeout_seconds=30,
        client_id="acme",
    )

    first = service.run(
        definition,
        entity_id="TCK-1001",
        actor="requester",
        input_payload={"safe_context": "keep"},
    )
    assert first.status == "failed"
    assert first.final_result["status"] == "failed"
    assert first.final_result["error_detail"] == "offline"
    previous = service.store.get_agent_run(first.run_id, client_id="acme")
    assert previous is not None

    updated = service.update(
        definition,
        name=definition.name,
        description=definition.description,
        enabled=True,
        trigger=definition.trigger,
        entity_type=definition.entity_type,
        filters=definition.filters,
        enabled_tools=definition.enabled_tools,
        steps=definition.steps,
        max_steps=definition.max_steps,
        execution_timeout_seconds=definition.execution_timeout_seconds,
    )
    with pytest.raises(AgentDefinitionError, match="definition changed"):
        service.retry(updated, previous, actor="requester")

    retry = service.retry(definition, previous, actor="requester")
    assert retry.status == "failed"
    retried_run = service.store.get_agent_run(retry.run_id, client_id="acme")
    assert retried_run is not None
    retried_state = json.loads(retried_run.state_json)
    assert retried_state["retry_count"] == 1
    assert retried_state["retry_of_run_id"] == first.run_id
    assert retried_state["input"] == {"safe_context": "keep"}

    current = retried_run
    for _ in range(2):
        current_result = service.retry(definition, current, actor="requester")
        next_run = service.store.get_agent_run(current_result.run_id, client_id="acme")
        assert next_run is not None
        current = next_run

    with pytest.raises(AgentDefinitionError, match="retry limit"):
        service.retry(definition, current, actor="requester")


def test_agent_api_retry_is_tenant_scoped_and_rejects_completed_runs(settings) -> None:
    scoped = settings.__class__(
        **{
            **settings.__dict__,
            "client_id": "acme",
            "allow_llm_inference": True,
            "local_model_provider": "openai-compatible",
            "local_model_base_url": "http://127.0.0.1:1/v1",
            "local_model_timeout_seconds": 0.01,
        }
    )
    store = Store(scoped.data_path)
    _seed(store, client_id="acme")
    client = TestClient(create_app(scoped))

    created = client.post(
        "/agents",
        json={
            "name": "Retrying summary agent",
            "enabled_tools": ["suggest-resolution"],
            "steps": [{"tool_id": "suggest-resolution", "payload": {}}],
            "max_steps": 1,
            "client_id": "acme",
        },
    )
    assert created.status_code == 200
    agent_id = created.json()["id"]
    failed = client.post(f"/agents/{agent_id}/run", json={"entity_id": "TCK-1001"})
    assert failed.status_code == 200
    assert failed.json()["status"] == "failed"
    run_id = failed.json()["run_id"]

    retry = client.post(f"/agent-runs/{run_id}/retry")
    assert retry.status_code == 200
    assert retry.json()["status"] == "failed"
    assert client.post(f"/agent-runs/{run_id}/retry", params={"client_id": "other"}).status_code == 404

    successful = client.post(
        "/agents",
        json={
            "name": "Completed triage agent",
            "enabled_tools": ["ticket-triage"],
            "steps": [{"tool_id": "ticket-triage", "payload": {}}],
            "max_steps": 1,
            "client_id": "acme",
        },
    )
    assert successful.status_code == 200
    completed_run = client.post(f"/agents/{successful.json()['id']}/run", json={"entity_id": "TCK-1001"})
    assert completed_run.json()["status"] == "completed"
    assert client.post(f"/agent-runs/{completed_run.json()['run_id']}/retry").status_code == 409


def test_collector_preview_tool_reuses_api_rbac_and_redacts_config(settings) -> None:
    secure = settings.__class__(
        **{
            **settings.__dict__,
            "demo_mode": False,
            "client_id": "acme",
            "tech_token": "tech-token",
            "viewer_token": "viewer-token",
        }
    )
    client = TestClient(create_app(secure))
    viewer = client.post(
        "/smart-actions/collector-preview/invoke",
        headers={"Authorization": "Bearer viewer-token"},
        json={"payload": {"module_id": "host-runtime", "config": {}}},
    )
    preview = client.post(
        "/smart-actions/collector-preview/invoke",
        headers={"Authorization": "Bearer tech-token"},
        json={"payload": {"module_id": "host-runtime", "config": {}}},
    )
    result = client.post(
        "/smart-actions/collector-preview/invoke",
        headers={"Authorization": "Bearer tech-token"},
        json={
            "payload": {
                "module_id": "host-runtime",
                "config": {"api_key": "supersecret"},
            }
        },
    )

    assert viewer.status_code == 403
    assert preview.status_code == 200
    assert preview.json()["status"] == "success"
    assert result.status_code == 200
    assert result.json()["status"] == "failed"
    executions = Store(secure.data_path).list_execution_runs(client_id="acme")
    assert executions
    steps = Store(secure.data_path).list_execution_steps(executions[0].id or 0)
    assert steps
    assert "supersecret" not in steps[0].input_json
    audit = Store(secure.data_path).list_audit_events(client_id="acme")
    assert any(event.event_type == "collector.previewed" for event in audit)


def test_sentiment_and_escalation_tools_are_tenant_scoped_and_technician_gated(settings) -> None:
    secure = settings.__class__(
        **{
            **settings.__dict__,
            "demo_mode": False,
            "client_id": "acme",
            "tech_token": "tech-token",
            "viewer_token": "viewer-token",
        }
    )
    store = Store(secure.data_path)
    _seed(store, client_id="acme")
    with store._connect() as connection:  # noqa: SLF001
        connection.execute("update tickets set client_id = 'beta' where id = 'TCK-1002'")
    client = TestClient(create_app(secure))
    viewer = client.post(
        "/smart-actions/ticket-sentiment/invoke",
        headers={"Authorization": "Bearer viewer-token"},
        json={"payload": {"ticket_id": "TCK-1001"}},
    )
    sentiment = client.post(
        "/smart-actions/ticket-sentiment/invoke",
        headers={"Authorization": "Bearer tech-token"},
        json={"payload": {"ticket_id": "TCK-1001"}},
    )
    foreign = client.post(
        "/smart-actions/ticket-escalation/invoke",
        headers={"Authorization": "Bearer tech-token"},
        json={"payload": {"ticket_id": "TCK-1002"}},
    )

    assert viewer.status_code == 403
    assert sentiment.status_code == 200
    assert sentiment.json()["status"] == "success"
    assert sentiment.json()["output"]["sentiment"] == "negative"
    assert foreign.status_code == 200
    assert foreign.json()["status"] == "failed"


def test_m365_identity_lookup_is_read_only_tenant_scoped_and_technician_gated(settings) -> None:
    secure = settings.__class__(
        **{
            **settings.__dict__,
            "demo_mode": False,
            "client_id": "acme",
            "tech_token": "tech-token",
            "viewer_token": "viewer-token",
        }
    )
    store = Store(secure.data_path)
    store.upsert_canonical_asset(
        canonical_id="m365:user:acme-1",
        asset_type="m365-user",
        display_name="Acme Admin",
        attributes={
            "user_id": "acme-1",
            "display_name": "Acme Admin",
            "user_principal_name": "admin@acme.example",
            "mail": "admin@acme.example",
            "account_enabled": True,
        },
        client_id="acme",
        source_module="cloud-m365",
    )
    store.upsert_canonical_asset(
        canonical_id="m365:user:beta-1",
        asset_type="m365-user",
        display_name="Beta Admin",
        attributes={
            "user_id": "beta-1",
            "display_name": "Beta Admin",
            "user_principal_name": "admin@beta.example",
            "mail": "admin@beta.example",
            "account_enabled": True,
        },
        client_id="beta",
        source_module="cloud-m365",
    )
    store.upsert_canonical_asset(
        canonical_id="agent:acme-rmm",
        asset_type="endpoint-agent",
        display_name="Acme RMM",
        attributes={"agent": "Acme RMM", "category": "rmm"},
        client_id="acme",
        source_module="endpoint-agents",
    )
    client = TestClient(create_app(secure))
    viewer = client.post(
        "/smart-actions/m365-identity-lookup/invoke",
        headers={"Authorization": "Bearer viewer-token"},
        json={"payload": {"identity": "admin"}},
    )
    acme = client.post(
        "/smart-actions/m365-identity-lookup/invoke",
        headers={"Authorization": "Bearer tech-token"},
        json={"payload": {"identity": "admin"}},
    )
    beta = client.post(
        "/smart-actions/m365-identity-lookup/invoke",
        headers={"Authorization": "Bearer tech-token"},
        json={"payload": {"identity": "admin@beta.example"}},
    )
    rmm = client.post(
        "/smart-actions/rmm-device-lookup/invoke",
        headers={"Authorization": "Bearer tech-token"},
        json={"payload": {"query": "acme"}},
    )

    assert viewer.status_code == 403
    assert acme.status_code == 200
    assert acme.json()["output"]["count"] == 1
    assert acme.json()["output"]["matches"][0]["user_principal_name"] == "admin@acme.example"
    assert beta.status_code == 200
    assert beta.json()["output"]["count"] == 0
    assert rmm.status_code == 200
    assert rmm.json()["output"]["count"] == 1


def test_agent_retry_rejects_completed_runs(settings) -> None:
    service = _service(settings)
    definition = _create(service)
    completed = service.run(definition, entity_id="TCK-1001", actor="requester", input_payload={})
    assert completed.status == "completed"
    with pytest.raises(AgentDefinitionError, match="only failed"):
        service.retry(
            definition,
            service.store.get_agent_run(completed.run_id, client_id="acme"),  # type: ignore[arg-type]
            actor="requester",
        )


def test_agent_run_guards_reject_unsupported_and_malformed_states(settings) -> None:
    service = _service(settings)
    definition = _create(service)

    completed = AgentRun(
        id=1,
        agent_id=definition.id,
        entity_id="TCK-1001",
        actor="requester",
        status="completed",
        current_step=1,
        state_json="{}",
        started_at="",
        finished_at="",
        revision_version=definition.version,
        client_id="acme",
    )
    assert (
        service.resume(definition, completed, approver="approver", approver_role=Role.TECHNICIAN).status
        == "completed"
    )

    with pytest.raises(AgentDefinitionError, match="entity_type is not supported"):
        service.run(
            replace(definition, entity_type="user"),
            entity_id="TCK-1001",
            actor="requester",
            input_payload={},
        )

    malformed = replace(
        completed,
        status="pending_approval",
        state_json=json.dumps({"steps": [{"approval_id": "not-an-id"}], "pending_approval_step": 0}),
    )
    with pytest.raises(AgentDefinitionError, match="approval id is missing"):
        service.resume(definition, malformed, approver="approver", approver_role=Role.TECHNICIAN)

    missing = replace(
        completed,
        status="pending_approval",
        state_json=json.dumps({"steps": [{"approval_id": 999999}], "pending_approval_step": 0}),
    )
    with pytest.raises(AgentDefinitionError, match="approval could not be found"):
        service.resume(definition, missing, approver="approver", approver_role=Role.TECHNICIAN)


def test_agent_runtime_fails_closed_for_malformed_disabled_and_missing_tools(settings, monkeypatch) -> None:
    service = _service(settings)
    definition = _create(service)

    malformed = replace(definition, steps=[{"tool_id": None, "payload": {}}])
    malformed_result = service.run(malformed, entity_id="TCK-1001", actor="requester", input_payload={})
    assert malformed_result.status == "failed"
    assert malformed_result.error_detail == "agent step is malformed"

    disabled_tool = replace(
        definition,
        enabled_tools=["ticket-triage"],
        steps=[{"tool_id": "dispatch-suggestion", "payload": {}}],
    )
    disabled_tool_result = service.run(
        disabled_tool, entity_id="TCK-1001", actor="requester", input_payload={}
    )
    assert disabled_tool_result.status == "failed"
    assert "not enabled" in disabled_tool_result.error_detail

    def missing_invoke(*args, **kwargs):
        raise KeyError

    monkeypatch.setattr(service.smart_actions, "invoke", missing_invoke)
    missing_tool = replace(
        definition,
        enabled_tools=["ticket-triage"],
        steps=[{"tool_id": "ticket-triage", "payload": {}}],
    )
    missing_tool_result = service.run(
        missing_tool, entity_id="TCK-1001", actor="requester", input_payload={}
    )
    assert missing_tool_result.status == "failed"
    assert missing_tool_result.steps[0]["error_detail"] == "tool ticket-triage is not registered"


def test_agent_runtime_timeout_and_rejected_approval_are_terminal(settings, monkeypatch) -> None:
    service = _service(settings)
    definition = _create(service)
    clock = iter((0.0, 1.0))
    monkeypatch.setattr(agents_module.time, "monotonic", lambda: next(clock))

    timed_out = service.run(
        replace(definition, execution_timeout_seconds=0.5),
        entity_id="TCK-1001",
        actor="requester",
        input_payload={},
    )
    assert timed_out.status == "failed"
    assert timed_out.error_detail == "agent execution timed out"

    monkeypatch.undo()
    approval_definition = service.update(
        definition,
        name="Approval agent",
        description="",
        enabled=True,
        trigger="manual",
        entity_type="ticket",
        filters={},
        enabled_tools=["dispatch-suggestion"],
        steps=[{"tool_id": "dispatch-suggestion", "payload": {}}],
        max_steps=1,
        execution_timeout_seconds=30,
    )
    pending = service.run(approval_definition, entity_id="TCK-1001", actor="requester", input_payload={})
    assert pending.approval_id is not None
    from wait_local_agent.smart_actions import ActionResult

    monkeypatch.setattr(service.smart_actions, "update_approval", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        service.smart_actions,
        "complete_approval",
        lambda *args, **kwargs: ActionResult(status="rejected", approval_id=pending.approval_id),
    )
    rejected = service.resume(
        approval_definition,
        service.store.get_agent_run(pending.run_id, client_id="acme"),  # type: ignore[arg-type]
        approver="approver",
        approver_role=Role.TECHNICIAN,
    )
    assert rejected.status == "rejected"


def test_agent_revision_and_runtime_guards_fail_closed(settings, monkeypatch) -> None:
    service = _service(settings)
    definition = _create(service)
    base_run = AgentRun(
        id=1,
        agent_id=definition.id,
        entity_id="TCK-1001",
        actor="requester",
        status="pending_approval",
        current_step=0,
        state_json=json.dumps({"steps": [{"approval_id": 1}], "pending_approval_step": 3}),
        started_at="",
        finished_at="",
        revision_version=definition.version,
        client_id="acme",
    )
    with pytest.raises(AgentDefinitionError, match="approval state is malformed"):
        service.resume(definition, base_run, approver="approver", approver_role=Role.TECHNICIAN)

    with pytest.raises(AgentDefinitionError, match="revision is no longer available"):
        service._definition_for_run(definition, replace(base_run, revision_version=99))  # noqa: SLF001

    def revision_with(payload: str) -> AgentDefinitionRevision:
        return AgentDefinitionRevision(
            id=1,
            agent_id=definition.id,
            version=0,
            definition_json=payload,
            created_at="",
            client_id="acme",
        )

    monkeypatch.setattr(
        service.store,
        "get_agent_definition_revision",
        lambda *args, **kwargs: revision_with("not-json"),
    )
    with pytest.raises(AgentDefinitionError, match="revision is malformed"):
        service._definition_for_run(definition, replace(base_run, revision_version=0))  # noqa: SLF001

    monkeypatch.setattr(
        service.store,
        "get_agent_definition_revision",
        lambda *args, **kwargs: revision_with("[]"),
    )
    with pytest.raises(AgentDefinitionError, match="revision is malformed"):
        service._definition_for_run(definition, replace(base_run, revision_version=0))  # noqa: SLF001

    monkeypatch.setattr(
        service.store,
        "get_agent_definition_revision",
        lambda *args, **kwargs: revision_with(json.dumps({"filters": []})),
    )
    with pytest.raises(AgentDefinitionError, match="revision is malformed"):
        service._definition_for_run(definition, replace(base_run, revision_version=0))  # noqa: SLF001

    monkeypatch.setattr(
        service.store,
        "get_agent_definition_revision",
        lambda *args, **kwargs: revision_with(json.dumps({"filters": {}, "enabled_tools": [], "steps": {}})),
    )
    with pytest.raises(AgentDefinitionError, match="revision is malformed"):
        service._definition_for_run(definition, replace(base_run, revision_version=0))  # noqa: SLF001

    monkeypatch.setattr(
        service.store,
        "get_agent_definition_revision",
        lambda *args, **kwargs: revision_with(
            json.dumps(
                {
                    "filters": {},
                    "enabled_tools": ["ticket-triage"],
                    "steps": [{"tool_id": "ticket-triage", "payload": {}}],
                    "approval_rules": {},
                }
            )
        ),
    )
    with pytest.raises(AgentDefinitionError, match="revision is malformed"):
        service._definition_for_run(definition, replace(base_run, revision_version=0))  # noqa: SLF001

    with pytest.raises(AgentDefinitionError, match="only queued or approval-paused"):
        service.cancel(
            definition,
            replace(base_run, status="completed"),
            actor="approver",
            approver_role=Role.TECHNICIAN,
        )


def test_connector_read_tools_reuse_existing_clients_and_tenant_scope(settings, monkeypatch) -> None:
    secure = settings.__class__(
        **{
            **settings.__dict__,
            "demo_mode": False,
            "client_id": "acme",
            "tech_token": "tech-token",
            "viewer_token": "viewer-token",
        }
    )
    store = Store(secure.data_path)
    _seed(store, client_id="acme")
    halo = SimpleNamespace(
        get_ticket=lambda ticket_id: SimpleNamespace(
            result=SimpleNamespace(status="ready", message="ok", count=1),
            items=[HaloTicket(ticket_id, "Remote ticket", "Open", "P2", "acme", "Acme")],
        )
    )
    hudu = SimpleNamespace(
        list_articles=lambda company_id, page, page_size: SimpleNamespace(
            result=SimpleNamespace(status="ready", message="ok", count=1),
            items=[HuduArticle("article-1", "VPN setup", company_id or "", "folder-1", "2026-08-01", "https://hudu")],
        )
    )
    monkeypatch.setattr(app_module, "HaloPSAClient", lambda settings: halo)
    monkeypatch.setattr(app_module, "HuduClient", lambda settings: hudu)
    client = TestClient(create_app(secure))

    viewer = client.post(
        "/smart-actions/halopsa-ticket-lookup/invoke",
        headers={"Authorization": "Bearer viewer-token"},
        json={"payload": {"ticket_id": "TCK-1001"}},
    )
    ticket = client.post(
        "/smart-actions/halopsa-ticket-lookup/invoke",
        headers={"Authorization": "Bearer tech-token"},
        json={"payload": {"ticket_id": "TCK-1001"}},
    )
    docs = client.post(
        "/smart-actions/hudu-documentation-search/invoke",
        headers={"Authorization": "Bearer tech-token"},
        json={"payload": {"query": "vpn", "company_id": "acme"}},
    )
    foreign_docs = client.post(
        "/smart-actions/hudu-documentation-search/invoke",
        headers={"Authorization": "Bearer tech-token"},
        json={"payload": {"query": "vpn", "company_id": "other"}},
    )

    assert viewer.status_code == 403
    assert ticket.status_code == 200
    assert ticket.json()["output"]["ticket"]["id"] == "TCK-1001"
    assert docs.status_code == 200
    assert docs.json()["output"]["count"] == 1
    assert foreign_docs.status_code == 200
    assert foreign_docs.json()["status"] == "failed"


def test_agent_scope_and_definition_bounds_are_enforced(settings) -> None:
    service = _service(settings)
    definition = _create(service)

    updated = service.update(
        definition,
        name="Updated triage agent",
        description="Updated description.",
        enabled=True,
        trigger="manual",
        entity_type="ticket",
        filters={},
        enabled_tools=["ticket-triage"],
        steps=[{"tool_id": "ticket-triage", "payload": {}}],
        max_steps=1,
        execution_timeout_seconds=45,
    )
    assert updated.version == 2
    assert updated.name == "Updated triage agent"
    revisions = service.store.list_agent_definition_revisions(definition.id, client_id="acme")
    assert [revision.version for revision in revisions] == [2, 1]
    assert "Ticket triage agent" in revisions[-1].definition_json
    assert service.store.get_agent_definition_revision(definition.id, 1) is not None
    assert len(service.store.list_agent_definition_revisions(definition.id)) == 2
    Store(settings.data_path)

    dependent = service.create(
        name="Dependent triage agent",
        description="Depends on the original definition.",
        enabled=True,
        trigger="manual",
        entity_type="ticket",
        filters={},
        enabled_tools=["ticket-triage"],
        steps=[{"tool_id": "ticket-triage", "payload": {}}],
        max_steps=1,
        execution_timeout_seconds=30,
        client_id="acme",
        depends_on_agent_ids=[definition.id],
    )
    with pytest.raises(AgentDefinitionError, match="cycle"):
        service.update(
            definition,
            name=definition.name,
            description=definition.description,
            enabled=True,
            trigger=definition.trigger,
            entity_type=definition.entity_type,
            filters={},
            enabled_tools=definition.enabled_tools,
            steps=definition.steps,
            max_steps=definition.max_steps,
            execution_timeout_seconds=definition.execution_timeout_seconds,
            depends_on_agent_ids=[dependent.id],
        )

    def create_with_dependencies(dependencies: list[str]) -> None:
        service.create(
            name="Invalid dependency agent",
            description="",
            enabled=True,
            trigger="manual",
            entity_type="ticket",
            filters={},
            enabled_tools=["ticket-triage"],
            steps=[{"tool_id": "ticket-triage", "payload": {}}],
            max_steps=1,
            execution_timeout_seconds=30,
            client_id="acme",
            depends_on_agent_ids=dependencies,
        )

    with pytest.raises(AgentDefinitionError, match="not found"):
        create_with_dependencies(["missing-agent"])
    with pytest.raises(AgentDefinitionError, match="duplicates"):
        create_with_dependencies([dependent.id, dependent.id])
    with pytest.raises(AgentDefinitionError, match="0-8"):
        create_with_dependencies([dependent.id] * 9)
    with pytest.raises(AgentDefinitionError, match="non-empty"):
        create_with_dependencies([" "])
    with pytest.raises(AgentDefinitionError, match="itself"):
        service.update(
            definition,
            name=definition.name,
            description=definition.description,
            enabled=True,
            trigger=definition.trigger,
            entity_type=definition.entity_type,
            filters={},
            enabled_tools=definition.enabled_tools,
            steps=definition.steps,
            max_steps=definition.max_steps,
            execution_timeout_seconds=definition.execution_timeout_seconds,
            depends_on_agent_ids=[definition.id],
        )
    beta = _create(service, client_id="beta")
    with pytest.raises(AgentDefinitionError, match="outside the tenant"):
        create_with_dependencies([beta.id])

    disabled = service.update(
        updated,
        name=updated.name,
        description=updated.description,
        enabled=False,
        trigger=updated.trigger,
        entity_type=updated.entity_type,
        filters={},
        enabled_tools=updated.enabled_tools,
        steps=updated.steps,
        max_steps=updated.max_steps,
        execution_timeout_seconds=updated.execution_timeout_seconds,
    )
    with pytest.raises(AgentDefinitionError, match="disabled"):
        service.run(disabled, entity_id="TCK-1001", actor="requester", input_payload={})

    with pytest.raises(AgentDefinitionError, match="ticket was not found"):
        service.run(definition, entity_id="NOPE", actor="requester", input_payload={})

    with pytest.raises(AgentDefinitionError, match="only manual"):
        service.create(
            name="future",
            description="",
            enabled=True,
            trigger="ticket.created",
            entity_type="ticket",
            filters={},
            enabled_tools=["ticket-triage"],
            steps=[{"tool_id": "ticket-triage", "payload": {}}],
            max_steps=1,
            execution_timeout_seconds=30,
            client_id="acme",
        )

    with pytest.raises(AgentDefinitionError, match="filters are reserved"):
        service.create(
            name="filtered",
            description="",
            enabled=True,
            trigger="manual",
            entity_type="ticket",
            filters={"priority": "high"},
            enabled_tools=["ticket-triage"],
            steps=[{"tool_id": "ticket-triage", "payload": {}}],
            max_steps=1,
            execution_timeout_seconds=30,
            client_id="acme",
        )

    with pytest.raises(AgentDefinitionError, match="unsupported event filter"):
        service.create(
            name="unknown event filter",
            description="",
            enabled=True,
            trigger="event",
            entity_type="ticket",
            filters={"event_type": "ticket.created", "unknown": "value"},
            enabled_tools=["ticket-triage"],
            steps=[{"tool_id": "ticket-triage", "payload": {}}],
            max_steps=1,
            execution_timeout_seconds=30,
            client_id="acme",
        )

    with pytest.raises(AgentDefinitionError, match="supported event_type"):
        service.create(
            name="unknown event type",
            description="",
            enabled=True,
            trigger="event",
            entity_type="ticket",
            filters={},
            enabled_tools=["ticket-triage"],
            steps=[{"tool_id": "ticket-triage", "payload": {}}],
            max_steps=1,
            execution_timeout_seconds=30,
            client_id="acme",
        )

    with pytest.raises(AgentDefinitionError, match="must be a non-empty string"):
        service.create(
            name="bad event filter value",
            description="",
            enabled=True,
            trigger="event",
            entity_type="ticket",
            filters={"event_type": "ticket.created", "priority": 1},
            enabled_tools=["ticket-triage"],
            steps=[{"tool_id": "ticket-triage", "payload": {}}],
            max_steps=1,
            execution_timeout_seconds=30,
            client_id="acme",
        )

    with pytest.raises(AgentDefinitionError, match="unknown tools"):
        service.create(
            name="unknown tool",
            description="",
            enabled=True,
            trigger="manual",
            entity_type="ticket",
            filters={},
            enabled_tools=["does-not-exist"],
            steps=[{"tool_id": "does-not-exist", "payload": {}}],
            max_steps=1,
            execution_timeout_seconds=30,
            client_id="acme",
        )

    with pytest.raises(AgentDefinitionError, match="max_steps"):
        service.create(
            name="too many",
            description="",
            enabled=True,
            trigger="manual",
            entity_type="ticket",
            filters={},
            enabled_tools=["ticket-triage"],
            steps=[{"tool_id": "ticket-triage", "payload": {}}],
            max_steps=0,
            execution_timeout_seconds=30,
            client_id="acme",
        )

    with pytest.raises(AgentDefinitionError, match="execution_timeout_seconds"):
        service.create(
            name="slow",
            description="",
            enabled=True,
            trigger="manual",
            entity_type="ticket",
            filters={},
            enabled_tools=["ticket-triage"],
            steps=[{"tool_id": "ticket-triage", "payload": {}}],
            max_steps=1,
            execution_timeout_seconds=121,
            client_id="acme",
        )

    with pytest.raises(AgentDefinitionError, match="only contain"):
        service.create(
            name="extra step field",
            description="",
            enabled=True,
            trigger="manual",
            entity_type="ticket",
            filters={},
            enabled_tools=["ticket-triage"],
            steps=[{"tool_id": "ticket-triage", "payload": {}, "extra": True}],
            max_steps=1,
            execution_timeout_seconds=30,
            client_id="acme",
        )

    with pytest.raises(AgentDefinitionError, match="payload must be an object"):
        service.create(
            name="bad step payload",
            description="",
            enabled=True,
            trigger="manual",
            entity_type="ticket",
            filters={},
            enabled_tools=["ticket-triage"],
            steps=[{"tool_id": "ticket-triage", "payload": "bad"}],
            max_steps=1,
            execution_timeout_seconds=30,
            client_id="acme",
        )


def test_agent_api_exposes_catalog_tenant_scope_and_run_trace(settings) -> None:
    scoped = settings.__class__(**{**settings.__dict__, "client_id": "acme"})
    store = Store(scoped.data_path)
    _seed(store, client_id="acme")
    client = TestClient(create_app(scoped))

    created = client.post(
        "/agents",
        json={
            "name": "Triage agent",
            "enabled_tools": ["ticket-triage"],
            "steps": [{"tool_id": "ticket-triage", "payload": {}}],
            "max_steps": 1,
            "execution_window_start": "00:00",
            "execution_window_end": "23:59",
            "execution_window_timezone": "America/Vancouver",
            "context_sources": ["ticket", "client"],
            "client_id": "acme",
            "approval_rules": [
                {
                    "tool_id": "ticket-triage",
                    "when": {"priority": ["medium"], "actor_role": ["admin"]},
                }
            ],
        },
    )
    assert created.status_code == 200
    agent_id = created.json()["id"]
    assert created.json()["execution_window_start"] == "00:00"
    assert created.json()["execution_window_end"] == "23:59"
    assert created.json()["execution_window_timezone"] == "America/Vancouver"
    assert created.json()["context_sources"] == ["ticket", "client"]
    assert created.json()["approval_rules"] == [
        {
            "tool_id": "ticket-triage",
            "when": {"priority": ["medium"], "actor_role": ["admin"]},
        }
    ]
    tools_response = client.get("/tools")
    assert tools_response.status_code == 200
    tool_ids = {tool["id"] for tool in tools_response.json()}
    assert {
        "syncro-ticket-lookup",
        "syncro-ticket-comments",
        "syncro-ticket-add-note",
        "servicenow-incident-lookup",
        "servicenow-incident-assign",
        "autotask-ticket-lookup",
        "servicenow-incident-update-resolution",
        "autotask-ticket-add-note",
        "autotask-ticket-update-status",
        "autotask-ticket-update-resolution",
    } <= tool_ids
    assert (
        next(
            tool for tool in tools_response.json() if tool["id"] == "autotask-ticket-lookup"
        )["access_mode"]
        == "read"
    )
    assert client.get("/agents").json()[0]["client_id"] == "acme"

    run = client.post(f"/agents/{agent_id}/run", json={"entity_id": "TCK-1001"})
    assert run.status_code == 200
    assert run.json()["status"] == "completed"
    detail = client.get(f"/agent-runs/{run.json()['run_id']}")
    assert detail.status_code == 200
    assert detail.json()["state"]["steps"][0]["tool_id"] == "ticket-triage"
    assert detail.json()["state"]["final_result"]["status"] == "success"
    assert detail.json()["state"]["final_result"]["tool_id"] == "ticket-triage"
    assert set(detail.json()["state"]["context"]) == {"ticket", "client"}
    assert detail.json()["revision_version"] == 1
    assert detail.json()["definition_revision"]["version"] == 1
    assert client.post(f"/agent-runs/{run.json()['run_id']}/retry").status_code == 409
    assert client.post(f"/agent-runs/{run.json()['run_id']}/cancel").status_code == 409

    approval_agent = client.post(
        "/agents",
        json={
            "name": "Approval agent",
            "enabled_tools": ["dispatch-suggestion"],
            "steps": [{"tool_id": "dispatch-suggestion", "payload": {"technicians": []}}],
            "max_steps": 1,
            "client_id": "acme",
        },
    )
    assert approval_agent.status_code == 200
    pending = client.post(
        f"/agents/{approval_agent.json()['id']}/run",
        json={"entity_id": "TCK-1001"},
    )
    assert pending.status_code == 200
    cancelled = client.post(f"/agent-runs/{pending.json()['run_id']}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    retried = client.post(f"/agent-runs/{pending.json()['run_id']}/retry")
    assert retried.status_code == 200
    assert retried.json()["status"] == "pending_approval"

    updated = client.put(
        f"/agents/{agent_id}",
        json={
            "name": "Updated triage agent",
            "description": "Updated through the API.",
            "enabled_tools": ["ticket-triage"],
            "steps": [{"tool_id": "ticket-triage", "payload": {}}],
            "max_steps": 1,
            "execution_timeout_seconds": 45,
            "execution_window_start": "01:00",
            "execution_window_end": "23:59",
            "execution_window_timezone": "America/Vancouver",
            "client_id": "acme",
        },
    )
    assert updated.status_code == 200
    assert updated.json()["version"] == 2

    revisions = client.get(f"/agents/{agent_id}/revisions")
    assert revisions.status_code == 200
    assert [revision["version"] for revision in revisions.json()] == [2, 1]
    diff = client.get(f"/agents/{agent_id}/revisions/1/diff/2")
    assert diff.status_code == 200
    assert diff.json()["changed"] is True
    assert {change["field"] for change in diff.json()["changes"]} >= {"name", "description"}
    assert client.get(f"/agents/{agent_id}/revisions/1/diff/99").status_code == 404
    assert client.get("/agents/no-such-agent/revisions/1/diff/2").status_code == 404
    restored = client.post(f"/agents/{agent_id}/revisions/1/restore")
    assert restored.status_code == 200
    assert restored.json()["version"] == 3
    assert restored.json()["name"] == "Triage agent"
    assert restored.json()["execution_window_start"] == "00:00"
    assert restored.json()["execution_window_end"] == "23:59"
    assert restored.json()["execution_window_timezone"] == "America/Vancouver"
    missing_revision = client.post(f"/agents/{agent_id}/revisions/99/restore")
    assert missing_revision.status_code == 404
    missing_agent_revision = client.post("/agents/no-such-agent/revisions/1/restore")
    assert missing_agent_revision.status_code == 404

    disabled = client.put(
        f"/agents/{agent_id}",
        json={
            "name": "Updated triage agent",
            "enabled": False,
            "enabled_tools": ["ticket-triage"],
            "steps": [{"tool_id": "ticket-triage", "payload": {}}],
            "max_steps": 1,
            "client_id": "acme",
        },
    )
    assert disabled.status_code == 200
    disabled_run = client.post(f"/agents/{agent_id}/run", json={"entity_id": "TCK-1001"})
    assert disabled_run.status_code == 400

    cross_tenant = client.post(f"/agents/{agent_id}/run", json={"entity_id": "TCK-1002", "client_id": "beta"})
    assert cross_tenant.status_code in {404, 403}


def test_agent_plan_api_is_preview_only_and_tenant_scoped(settings) -> None:
    scoped = settings.__class__(**{**settings.__dict__, "client_id": "acme"})
    store = Store(scoped.data_path)
    _seed(store, client_id="acme")
    client = TestClient(create_app(scoped))

    response = client.post(
        "/agents/plan",
        json={
            "instruction": "Triage this ticket and search the runbook",
            "entity_id": "TCK-1001",
            "client_id": "acme",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "preview"
    assert payload["selection_mode"] == "deterministic"
    assert [step["tool_id"] for step in payload["steps"]] == [
        "knowledge-search",
        "ticket-triage",
    ]
    assert payload["context"]["ticket"]["id"] == "TCK-1001"
    assert payload["definition"]["enabled"] is False
    assert payload["definition"]["client_id"] == "acme"
    assert Store(scoped.data_path).list_agent_runs(client_id="acme") == []

    cross_tenant = client.post(
        "/agents/plan",
        json={"instruction": "summarize", "entity_id": "TCK-1001", "client_id": "beta"},
    )
    assert cross_tenant.status_code == 400


def test_agent_revision_restore_requires_tenant_for_authenticated_technicians(settings) -> None:
    secure = settings.__class__(
        **{
            **settings.__dict__,
            "demo_mode": False,
            "tech_token": "tech-token",
            "viewer_token": "viewer-token",
        }
    )
    client = TestClient(create_app(secure))
    response = client.post(
        "/agents/anything/revisions/1/restore",
        headers={"Authorization": "Bearer tech-token"},
    )
    assert response.status_code == 404
    assert client.get(
        "/agents/anything/revisions/1/diff/2",
        headers={"Authorization": "Bearer viewer-token"},
    ).status_code == 404
    assert client.get(
        "/agents/anything/revisions",
        headers={"Authorization": "Bearer viewer-token"},
    ).json() == []
