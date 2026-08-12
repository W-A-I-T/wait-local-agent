"""Tenant-scoped agent health summaries over existing persisted run records."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from typing import cast

from wait_local_agent.models import AgentDefinition, AgentRun


def build_agent_health_summary(
    runs: Sequence[AgentRun],
    definitions: Sequence[AgentDefinition],
    *,
    client_id: str | None,
) -> dict[str, object]:
    """Build bounded health metadata without exposing persisted run payloads."""

    by_agent: dict[str, list[AgentRun]] = defaultdict(list)
    for run in runs:
        by_agent[run.agent_id].append(run)
    definition_by_id = {definition.id: definition for definition in definitions}
    agent_ids = sorted(set(by_agent) | set(definition_by_id))
    agents: list[dict[str, object]] = []
    for agent_id in agent_ids:
        agent_runs = by_agent.get(agent_id, [])
        completed = sum(bool(run.status == "completed") for run in agent_runs)
        failed = sum(bool(run.status in {"failed", "rejected", "cancelled"}) for run in agent_runs)
        pending = sum(bool(run.status in {"queued", "pending_approval"}) for run in agent_runs)
        total = len(agent_runs)
        definition = definition_by_id.get(agent_id)
        last_run = agent_runs[0] if agent_runs else None
        agents.append(
            {
                "agent_id": agent_id,
                "name": definition.name if definition else agent_id,
                "enabled": definition.enabled if definition else None,
                "definition_version": definition.version if definition else None,
                "total_runs": total,
                "completed_runs": completed,
                "failed_runs": failed,
                "pending_runs": pending,
                "success_rate": round(completed / total, 4) if total else None,
                "last_run_at": last_run.finished_at or last_run.started_at if last_run else None,
                "health": _health_status(total, failed, definition),
            }
        )
    total_runs = sum(cast(int, item["total_runs"]) for item in agents)
    failed_runs = sum(cast(int, item["failed_runs"]) for item in agents)
    return {
        "client_id": client_id,
        "agent_count": len(agents),
        "total_runs": total_runs,
        "failed_runs": failed_runs,
        "failure_rate": round(failed_runs / total_runs, 4) if total_runs else None,
        "agents": agents,
        "payloads_exposed": False,
    }


def _health_status(
    total_runs: int,
    failed_runs: int,
    definition: AgentDefinition | None,
) -> str:
    if definition is not None and not definition.enabled:
        return "disabled"
    if not total_runs:
        return "no_runs"
    if failed_runs:
        return "needs_attention"
    return "healthy"
