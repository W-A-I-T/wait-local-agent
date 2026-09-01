"""Unified, tenant-scoped activity projection across WAIT run stores."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from wait_local_agent.client_scope import ClientScope
from wait_local_agent.store import Store


@dataclass(frozen=True)
class ActivityItem:
    activity_id: str
    kind: str
    source_run_id: int | None
    canonical_execution_id: int | None
    title: str
    entity_id: str
    actor: str
    status: str
    started_at: str
    finished_at: str
    client_id: str | None
    detail_path: str
    trigger_source: str = ""


def list_activity(
    store: Store,
    *,
    scope: ClientScope,
    kinds: frozenset[str] | None = None,
    status: str | None = None,
    limit: int = 100,
) -> list[ActivityItem]:
    """Return one ordered activity stream while preserving source-run lineage."""

    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
        raise ValueError("limit must be between 1 and 500")
    normalized_status = status.strip().lower() if isinstance(status, str) and status.strip() else None
    normalized_kinds = frozenset(kind.strip().lower() for kind in kinds or frozenset() if kind.strip()) or None

    executions = store.list_execution_runs(scope)
    canonical: dict[tuple[str, int], int] = {}
    items: list[ActivityItem] = []
    for execution in executions:
        source_id = execution.source_run_id
        run_kind = execution.run_kind.strip().lower()
        if source_id is not None:
            canonical[(run_kind, source_id)] = int(execution.id) if execution.id is not None else 0
        items.append(
            ActivityItem(
                activity_id=f"execution:{execution.id}",
                kind=run_kind or "execution",
                source_run_id=source_id,
                canonical_execution_id=execution.id,
                title=_execution_title(run_kind, source_id),
                entity_id=str(source_id or ""),
                actor=execution.actor,
                status=execution.status,
                started_at=execution.started_at,
                finished_at=execution.finished_at,
                client_id=execution.client_id,
                detail_path="/executions",
                trigger_source=execution.trigger_source,
            )
        )

    for agent_run in store.list_agent_runs(scope):
        if agent_run.id is not None and _is_canonical(canonical, "agent", agent_run.id):
            continue
        items.append(
            ActivityItem(
                activity_id=f"agent:{agent_run.id}",
                kind="agent",
                source_run_id=agent_run.id,
                canonical_execution_id=_canonical_id(canonical, "agent", agent_run.id),
                title=agent_run.agent_id,
                entity_id=agent_run.entity_id,
                actor=agent_run.actor,
                status=str(agent_run.status),
                started_at=agent_run.started_at,
                finished_at=agent_run.finished_at,
                client_id=agent_run.client_id,
                detail_path="/agents",
            )
        )

    for workflow_run in store.list_workflow_runs(scope):
        if workflow_run.id is not None and _is_canonical(canonical, "workflow", workflow_run.id):
            continue
        items.append(
            ActivityItem(
                activity_id=f"workflow:{workflow_run.id}",
                kind="workflow",
                source_run_id=workflow_run.id,
                canonical_execution_id=_canonical_id(canonical, "workflow", workflow_run.id),
                title=workflow_run.template_id,
                entity_id=workflow_run.ticket_id,
                actor="",
                status=str(workflow_run.status),
                started_at=workflow_run.created_at,
                finished_at=workflow_run.updated_at,
                client_id=workflow_run.client_id,
                detail_path="/workflows",
            )
        )

    for action_run in store.list_smart_action_runs(scope):
        if action_run.id is not None and (
            _is_canonical(canonical, "smart_action", action_run.id)
            or _is_canonical(canonical, "smart-action", action_run.id)
        ):
            continue
        items.append(
            ActivityItem(
                activity_id=f"smart-action:{action_run.id}",
                kind="smart_action",
                source_run_id=action_run.id,
                canonical_execution_id=(
                    _canonical_id(canonical, "smart_action", action_run.id)
                    or _canonical_id(canonical, "smart-action", action_run.id)
                ),
                title=action_run.action_id,
                entity_id="",
                actor=action_run.actor,
                status=action_run.status,
                started_at=action_run.created_at,
                finished_at=action_run.updated_at,
                client_id=action_run.client_id,
                detail_path="/smart-actions/runs",
            )
        )

    for collector_run in store.list_collector_runs(scope):
        if collector_run.id is not None and _is_canonical(canonical, "collector", collector_run.id):
            continue
        items.append(
            ActivityItem(
                activity_id=f"collector:{collector_run.id}",
                kind="collector",
                source_run_id=collector_run.id,
                canonical_execution_id=_canonical_id(canonical, "collector", collector_run.id),
                title=collector_run.module_id,
                entity_id=str(collector_run.source_id or ""),
                actor=collector_run.actor_id or "",
                status=collector_run.status,
                started_at=collector_run.started_at,
                finished_at=collector_run.completed_at,
                client_id=collector_run.client_id,
                detail_path="/collectors",
            )
        )

    for backfill in store.list_agent_backfills(scope):
        items.append(
            ActivityItem(
                activity_id=f"backfill:{backfill.id}",
                kind="backfill",
                source_run_id=backfill.id,
                canonical_execution_id=None,
                title=backfill.agent_id,
                entity_id="",
                actor=backfill.actor,
                status=backfill.status,
                started_at=backfill.created_at,
                finished_at=backfill.updated_at,
                client_id=backfill.client_id,
                detail_path="/backfills",
            )
        )

    filtered = [
        item
        for item in items
        if (normalized_kinds is None or item.kind in normalized_kinds)
        and (normalized_status is None or item.status.strip().lower() == normalized_status)
    ]
    filtered.sort(key=lambda item: (item.started_at or item.finished_at, item.activity_id), reverse=True)
    return filtered[:limit]


def activity_to_dict(item: ActivityItem) -> dict[str, object]:
    return asdict(item)


def _execution_title(run_kind: str, source_run_id: int | None) -> str:
    normalized = (run_kind or "execution").replace("_", " ").title()
    if source_run_id is None:
        return normalized
    return f"{normalized} {source_run_id}"


def _is_canonical(canonical: dict[tuple[str, int], int], kind: str, source_run_id: int) -> bool:
    return (kind, source_run_id) in canonical


def _canonical_id(canonical: dict[tuple[str, int], int], kind: str, source_run_id: int | None) -> int | None:
    if source_run_id is None:
        return None
    value = canonical.get((kind, source_run_id))
    return value or None


__all__ = ["ActivityItem", "activity_to_dict", "list_activity"]
