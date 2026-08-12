from __future__ import annotations

from dataclasses import replace

import pytest

from wait_local_agent.models import AgentDefinition
from wait_local_agent.supervisor import SupervisorPlanError, build_supervisor_delegation_plan


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
