from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import wait_local_agent.agents as agents_module
from wait_local_agent.agents import AgentDefinitionError, AgentService
from wait_local_agent.api.app import create_app
from wait_local_agent.models import AgentDefinitionRevision, AgentRun
from wait_local_agent.rbac import Role
from wait_local_agent.smart_actions import SmartActionService
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
        "ticket-triage",
        "ticket-summary",
        "suggest-resolution",
        "find-similar-tickets",
        "dispatch-suggestion",
    }
    assert tools["ticket-triage"].access_mode == "read"
    assert tools["dispatch-suggestion"].approval_required is True


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
    assert service.store.get_agent_run(result.run_id, client_id="acme").revision_version == definition.version  # type: ignore[union-attr]
    assert [step["status"] for step in result.steps] == ["success", "success"]
    executions = service.store.list_execution_runs(client_id="acme", run_kind="agent")
    assert len(executions) == 1
    assert executions[0].source_run_id == result.run_id
    assert len(service.store.list_execution_steps(executions[0].id or 0)) == 2


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

    retried = service.retry(
        definition,
        service.store.get_agent_run(pending.run_id, client_id="acme"),  # type: ignore[arg-type]
        actor="requester",
    )
    assert retried.status == "pending_approval"
    assert retried.revision_version == definition.version


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

    with pytest.raises(AgentDefinitionError, match="only queued or approval-paused"):
        service.cancel(
            definition,
            replace(base_run, status="completed"),
            actor="approver",
            approver_role=Role.TECHNICIAN,
        )


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
            "client_id": "acme",
        },
    )
    assert created.status_code == 200
    agent_id = created.json()["id"]
    assert client.get("/tools").json()[0]["access_mode"] == "read"
    assert client.get("/agents").json()[0]["client_id"] == "acme"

    run = client.post(f"/agents/{agent_id}/run", json={"entity_id": "TCK-1001"})
    assert run.status_code == 200
    assert run.json()["status"] == "completed"
    detail = client.get(f"/agent-runs/{run.json()['run_id']}")
    assert detail.status_code == 200
    assert detail.json()["state"]["steps"][0]["tool_id"] == "ticket-triage"
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
