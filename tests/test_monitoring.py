from __future__ import annotations

from wait_local_agent.models import AgentDefinition, AgentRun, AgentRunStatus
from wait_local_agent.monitoring import build_agent_health_summary


def _definition(agent_id: str, *, enabled: bool = True) -> AgentDefinition:
    return AgentDefinition(
        id=agent_id,
        name=agent_id.title(),
        description="test",
        enabled=enabled,
        trigger="manual",
        entity_type="ticket",
        filters={},
        enabled_tools=[],
        steps=[],
        max_steps=1,
        execution_timeout_seconds=30,
        client_id="acme",
        version=2,
        created_at="2026-08-11T00:00:00Z",
        updated_at="2026-08-11T00:00:00Z",
    )


def _run(agent_id: str, status: AgentRunStatus, run_id: int) -> AgentRun:
    return AgentRun(
        id=run_id,
        agent_id=agent_id,
        entity_id=f"T-{run_id}",
        actor="tech",
        status=status,
        current_step=1,
        state_json='{"internal":"not exposed"}',
        started_at=f"2026-08-11T00:0{run_id}:00Z",
        finished_at=f"2026-08-11T00:1{run_id}:00Z" if status != "queued" else "",
        client_id="acme",
    )


def test_agent_health_summary_is_bounded_and_tenant_scoped() -> None:
    result = build_agent_health_summary(
        [_run("onboarding", "completed", 1), _run("onboarding", "failed", 2), _run("waiting", "queued", 3)],
        [_definition("onboarding"), _definition("waiting"), _definition("disabled", enabled=False)],
        client_id="acme",
    )

    assert result["client_id"] == "acme"
    assert result["total_runs"] == 3
    assert result["failed_runs"] == 1
    assert result["payloads_exposed"] is False
    rows = {row["agent_id"]: row for row in result["agents"]}
    assert rows["onboarding"]["health"] == "needs_attention"
    assert rows["onboarding"]["success_rate"] == 0.5
    assert rows["waiting"]["health"] == "no_runs" or rows["waiting"]["health"] == "healthy"
    assert rows["disabled"]["health"] == "disabled"
    assert "not exposed" not in str(result)


def test_agent_health_summary_handles_empty_records() -> None:
    result = build_agent_health_summary([], [], client_id=None)

    assert result == {
        "client_id": None,
        "agent_count": 0,
        "total_runs": 0,
        "failed_runs": 0,
        "failure_rate": None,
        "agents": [],
        "payloads_exposed": False,
    }
