from __future__ import annotations

from dataclasses import replace

import pytest

from wait_local_agent.agents import AgentExecutionResult
from wait_local_agent.models import AgentDefinition
from wait_local_agent.rbac import Role
from wait_local_agent.store import Store
from wait_local_agent.supervisor import (
    SupervisorPlanError,
    build_supervisor_delegation_plan,
    execute_supervisor_delegation,
)


def _definition(agent_id: str, *, client_id: str | None = "acme") -> AgentDefinition:
    return AgentDefinition(
        id=agent_id,
        name=agent_id.title(),
        description="bounded child",
        enabled=True,
        trigger="manual",
        entity_type="ticket",
        filters={},
        enabled_tools=["ticket-triage"],
        steps=[{"tool_id": "ticket-triage", "payload": {}}],
        max_steps=1,
        execution_timeout_seconds=30,
        client_id=client_id,
        version=1,
        created_at="2026-08-11T00:00:00Z",
        updated_at="2026-08-11T00:00:00Z",
        depends_on_agent_ids=[],
    )


def test_supervisor_plan_selects_explicit_children_and_bounds_context() -> None:
    child = replace(_definition("security"), depends_on_agent_ids=["identity"])
    result = build_supervisor_delegation_plan(
        client_id="acme",
        task="Review onboarding security prerequisites",
        child_agent_ids=["identity", "security"],
        definitions=[_definition("identity"), child],
    )

    assert result["format"] == "wait-local-agent.supervisor-delegation-plan"
    assert result["supervisor"]["children"][1]["depends_on_agent_ids"] == ["identity"]
    assert result["assignments"][0]["input_contract"]["client_id"] == "acme"
    assert result["delegation_started"] is False
    assert result["execution_started"] is False
    assert result["cross_tenant_context"] is False


def test_supervisor_execution_orders_children_and_passes_bounded_prior_results(settings) -> None:
    identity = _definition("identity")
    security = replace(identity, id="security", depends_on_agent_ids=["identity"])

    class FakeAgentService:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, object]]] = []

        def run(self, definition, *, supervisor_context, **kwargs):
            self.calls.append((definition.id, supervisor_context))
            return AgentExecutionResult(
                run_id=len(self.calls),
                agent_id=definition.id,
                status="completed",
                current_step=1,
                steps=[],
                final_result={"summary": f"{definition.id} complete"},
            )

    service = FakeAgentService()
    result = execute_supervisor_delegation(
        client_id="acme",
        entity_id="TCK-1001",
        task="Review onboarding",
        child_agent_ids=["security", "identity"],
        definitions=[identity, security],
        agent_service=service,
        store=Store(settings.data_path),
        actor="technician",
        actor_role=Role.TECHNICIAN,
        input_payload={"ticket_id": "TCK-1001"},
    )

    assert result["status"] == "completed"
    assert result["delegation_started"] is True
    assert result["execution_started"] is True
    assert result["supervisor"]["ordered_child_agent_ids"] == ["identity", "security"]
    assert [call[0] for call in service.calls] == ["identity", "security"]
    assert service.calls[1][1]["prior_results"][0]["agent_id"] == "identity"
    assert result["cross_tenant_context"] is False


@pytest.mark.parametrize(
    ("child_ids", "definitions", "message"),
    [
        (["missing"], [_definition("identity")], "not found"),
        (["identity", "identity"], [_definition("identity")], "duplicates"),
        ([], [_definition("identity")], "contain 1-8"),
        (["identity"], [replace(_definition("identity"), client_id="beta")], "outside the tenant"),
    ],
)
def test_supervisor_plan_rejects_missing_duplicate_or_foreign_children(child_ids, definitions, message) -> None:
    with pytest.raises(SupervisorPlanError, match=message):
        build_supervisor_delegation_plan(
            client_id="acme",
            task="Review request",
            child_agent_ids=child_ids,
            definitions=definitions,
        )
