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
    for run in executions:
        source_id = run.source_run_id
        run_kind = run.run_kind.strip().lower()
        if source_id is not None:
            canonical[(run_kind, source_id)] = int(run.id) if run.id is not None else 0
        items.append(
            ActivityItem(
                activity_id=f"execution:{run.id}",
                kind=run_kind or "execution",
                source_run_id=source_id,
                canonical_execution_id=run.id,
                title=_execution_title(run_kind, source_id),
                entity_id=str(source_id or ""),
                actor=run.actor,
                status=run.status,
                started_at=run.started_at,
                finished_at=run.finished_at,
                client_id=run.client_id,
                detail_path="/executions",
                trigger_source=run.trigger_source,
            )
        )

    for run in store.list_agent_runs(scope):
        if run.id is not None and _is_canonical(canonical, "agent", run.id):
            continue
        items.append(
            ActivityItem(
                activity_id=f"agent:{run.id}",
                kind="agent",
                source_run_id=run.id,
                canonical_execution_id=_canonical_id(canonical, "agent", run.id),
                title=run.agent_id,
                entity_id=run.entity_id,
                actor=run.actor,
                status=str(run.status),
                started_at=run.started_at,
                finished_at=run.finished_at,
                client_id=run.client_id,
                detail_path="/agents",
            )
        )

    for run in store.list_workflow_runs(scope):
        if run.id is not None and _is_canonical(canonical, "workflow", run.id):
            continue
        items.append(
            ActivityItem(
                activity_id=f"workflow:{run.id}",
                kind="workflow",
                source_run_id=run.id,
                canonical_execution_id=_canonical_id(canonical, "workflow", run.id),
                title=run.template_id,
                entity_id=run.ticket_id,
                actor="",
                status=str(run.status),
                started_at=run.created_at,
                finished_at=run.updated_at,
                client_id=run.client_id,
                detail_path="/workflows",
            )
        )

    for run in store.list_smart_action_runs(scope):
        if run.id is not None and (
            _is_canonical(canonical, "smart_action", run.id)
            or _is_canonical(canonical, "smart-action", run.id)
        ):
            continue
        items.append(
            ActivityItem(
                activity_id=f"smart-action:{run.id}",
                kind="smart_action",
                source_run_id=run.id,
                canonical_execution_id=(
                    _canonical_id(canonical, "smart_action", run.id)
                    or _canonical_id(canonical, "smart-action", run.id)
                ),
                title=run.action_id,
                entity_id="",
                actor=run.actor,
                status=run.status,
                started_at=run.created_at,
                finished_at=run.updated_at,
                client_id=run.client_id,
                detail_path="/smart-actions/runs",
            )
        )

    for run in store.list_collector_runs(scope):
        if run.id is not None and _is_canonical(canonical, "collector", run.id):
            continue
        items.append(
            ActivityItem(
                activity_id=f"collector:{run.id}",
                kind="collector",
                source_run_id=run.id,
                canonical_execution_id=_canonical_id(canonical, "collector", run.id),
                title=run.module_id,
                entity_id=str(run.source_id or ""),
                actor=run.actor_id or "",
                status=run.status,
                started_at=run.started_at,
                finished_at=run.completed_at,
                client_id=run.client_id,
                detail_path="/collectors",
            )
        )

    for run in store.list_agent_backfills(scope):
        items.append(
            ActivityItem(
                activity_id=f"backfill:{run.id}",
                kind="backfill",
                source_run_id=run.id,
                canonical_execution_id=None,
                title=run.agent_id,
                entity_id="",
                actor=run.actor,
                status=run.status,
                started_at=run.created_at,
                finished_at=run.updated_at,
                client_id=run.client_id,
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
    normalized = run_kind or "execution"
    return f"{normalized.replace('_', ' ').title()} {source_run_id}" if source_run_id is not None else normalized.replace("_", " ").title()


def _is_canonical(canonical: dict[tuple[str, int], int], kind: str, source_run_id: int) -> bool:
    return (kind, source_run_id) in canonical


def _canonical_id(canonical: dict[tuple[str, int], int], kind: str, source_run_id: int | None) -> int | None:
    if source_run_id is None:
        return None
    value = canonical.get((kind, source_run_id))
    return value or None


__all__ = ["ActivityItem", "activity_to_dict", "list_activity"]
