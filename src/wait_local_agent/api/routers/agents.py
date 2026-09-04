"""Agent, backfill, and agent-run API routes."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace

from fastapi import APIRouter, HTTPException, Request
from pydantic import ValidationError

from wait_local_agent.agents import AgentDefinitionError
from wait_local_agent.api.context import ApiContext, TechnicianAccess, ViewerAccess
from wait_local_agent.api.schemas import (
    AgentBackfillCreateRequest,
    AgentBackfillPreviewRequest,
    AgentDefinitionRequest,
    AgentPlanRequest,
    AgentRunStartRequest,
)
from wait_local_agent.api.scopes import (
    _backfill_scope,
    _request_correlation_id,
    _required_client_id,
    _resolve_detail_scope,
)
from wait_local_agent.api.views import (
    _agent_backfill_view,
    _agent_definition_view,
    _agent_revision_diff_view,
    _agent_revision_view,
    _agent_run_view,
    _redact_payload,
    _safe_json_object,
    _safe_json_values,
)
from wait_local_agent.client_scope import ClientScope, requested_client_from, resolve_client_scope
from wait_local_agent.models import AGENT_BACKFILL_MAX_CONCURRENCY, AgentDefinition
from wait_local_agent.rbac import AuthContext, Role
from wait_local_agent.reports.renderers import redact_text
from wait_local_agent.store import _normalize_client_id


def create_agents_router(ctx: ApiContext) -> APIRouter:
    router = APIRouter()
    store = ctx.store
    agent_service = ctx.agent_service

    @router.post("/agents/plan")
    def plan_agent(payload: AgentPlanRequest, context: TechnicianAccess) -> dict[str, object]:
        scoped_client_id = resolve_client_scope(context, payload.client_id).client_id
        if context.role < Role.ADMIN and scoped_client_id is None:
            raise HTTPException(status_code=403, detail="authenticated principal has no tenant")
        try:
            plan = agent_service.plan(
                payload.instruction,
                entity_id=payload.entity_id,
                client_id=scoped_client_id,
                max_steps=payload.max_steps,
            )
        except AgentDefinitionError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return asdict(plan)

    @router.get("/agents")
    def agents(
        context: ViewerAccess,
        client_id: str | None = None,
    ) -> list[dict[str, object]]:
        scoped_client_id = resolve_client_scope(context, client_id).client_id
        if context.role < Role.ADMIN and scoped_client_id is None and not context.is_msp_admin:
            return []
        return [_agent_definition_view(definition) for definition in agent_service.list_definitions(scoped_client_id)]

    @router.post("/agents")
    def create_agent(
        payload: AgentDefinitionRequest,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        scoped_client_id = resolve_client_scope(context, payload.client_id).client_id
        if context.role < Role.ADMIN and scoped_client_id is None:
            raise HTTPException(status_code=403, detail="authenticated principal has no tenant")
        try:
            definition = agent_service.create(
                name=payload.name,
                description=payload.description,
                enabled=payload.enabled,
                trigger=payload.trigger,
                entity_type=payload.entity_type,
                filters=payload.filters,
                enabled_tools=payload.enabled_tools,
                steps=[step.model_dump() for step in payload.steps],
                max_steps=payload.max_steps,
                execution_timeout_seconds=payload.execution_timeout_seconds,
                client_id=scoped_client_id,
                run_once_per_entity=payload.run_once_per_entity,
                depends_on_agent_ids=payload.depends_on_agent_ids,
                execution_window_start=payload.execution_window_start,
                execution_window_end=payload.execution_window_end,
                execution_window_timezone=payload.execution_window_timezone,
                context_sources=list(payload.context_sources),
                approval_expiry_seconds=payload.approval_expiry_seconds,
                result_aware=payload.result_aware,
                approval_required_tools=payload.approval_required_tools,
                approval_rules=[rule.model_dump() for rule in payload.approval_rules],
            )
        except AgentDefinitionError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _agent_definition_view(definition)

    @router.get("/agents/{agent_id}")
    def agent_detail(agent_id: str, context: ViewerAccess, client_id: str | None = None) -> dict[str, object]:
        scoped_client_id = _resolve_detail_scope(context, client_id).client_id
        if context.role < Role.ADMIN and scoped_client_id is None and not context.is_msp_admin:
            raise HTTPException(status_code=404, detail="agent not found")
        definition = agent_service.get(agent_id, scoped_client_id)
        if definition is None:
            raise HTTPException(status_code=404, detail="agent not found")
        return _agent_definition_view(definition)

    @router.get("/agents/{agent_id}/revisions")
    def agent_revisions(
        agent_id: str,
        context: ViewerAccess,
        client_id: str | None = None,
    ) -> list[dict[str, object]]:
        scoped_client_id = resolve_client_scope(context, client_id).client_id
        if context.role < Role.ADMIN and scoped_client_id is None and not context.is_msp_admin:
            return []
        definition = agent_service.get(agent_id, scoped_client_id)
        if definition is None:
            return []
        return [
            _agent_revision_view(revision)
            for revision in store.list_agent_definition_revisions(agent_id, definition.client_id)
        ]

    @router.get("/agents/{agent_id}/revisions/{version}/diff/{other_version}")
    def agent_revision_diff(
        agent_id: str,
        version: int,
        other_version: int,
        context: ViewerAccess,
        client_id: str | None = None,
    ) -> dict[str, object]:
        scoped_client_id = _resolve_detail_scope(context, client_id).client_id
        if context.role < Role.ADMIN and scoped_client_id is None and not context.is_msp_admin:
            raise HTTPException(status_code=404, detail="agent revision not found")
        definition = agent_service.get(agent_id, scoped_client_id)
        if definition is None:
            raise HTTPException(status_code=404, detail="agent revision not found")
        left = store.get_agent_definition_revision(agent_id, version, definition.client_id)
        right = store.get_agent_definition_revision(agent_id, other_version, definition.client_id)
        if left is None or right is None:
            raise HTTPException(status_code=404, detail="agent revision not found")
        return _agent_revision_diff_view(left, right)

    @router.post("/agents/{agent_id}/revisions/{version}/restore")
    def restore_agent_revision(
        agent_id: str,
        version: int,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        scoped_client_id = resolve_client_scope(context, None).client_id
        if context.role < Role.ADMIN and scoped_client_id is None and not context.is_msp_admin:
            raise HTTPException(status_code=404, detail="agent not found")
        existing = agent_service.get(agent_id, scoped_client_id)
        if existing is None:
            raise HTTPException(status_code=404, detail="agent not found")
        revision = store.get_agent_definition_revision(agent_id, version, existing.client_id)
        if revision is None:
            raise HTTPException(status_code=404, detail="agent revision not found")
        try:
            payload = AgentDefinitionRequest.model_validate(_safe_json_object(revision.definition_json))
            restored = agent_service.update(
                existing,
                name=payload.name,
                description=payload.description,
                enabled=payload.enabled,
                trigger=payload.trigger,
                entity_type=payload.entity_type,
                filters=payload.filters,
                enabled_tools=payload.enabled_tools,
                steps=[step.model_dump() for step in payload.steps],
                max_steps=payload.max_steps,
                execution_timeout_seconds=payload.execution_timeout_seconds,
                run_once_per_entity=payload.run_once_per_entity,
                depends_on_agent_ids=payload.depends_on_agent_ids,
                execution_window_start=payload.execution_window_start,
                execution_window_end=payload.execution_window_end,
                execution_window_timezone=payload.execution_window_timezone,
                context_sources=list(payload.context_sources),
                approval_expiry_seconds=payload.approval_expiry_seconds,
                result_aware=payload.result_aware,
                approval_required_tools=payload.approval_required_tools,
                approval_rules=[rule.model_dump() for rule in payload.approval_rules],
            )
        except (AgentDefinitionError, ValidationError) as exc:
            raise HTTPException(status_code=409, detail="agent revision is no longer valid") from exc
        return _agent_definition_view(restored)

    @router.put("/agents/{agent_id}")
    def update_agent(
        agent_id: str,
        payload: AgentDefinitionRequest,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        scoped_client_id = resolve_client_scope(context, payload.client_id).client_id
        if context.role < Role.ADMIN and scoped_client_id is None:
            raise HTTPException(status_code=404, detail="agent not found")
        existing = agent_service.get(agent_id, scoped_client_id)
        if existing is None:
            raise HTTPException(status_code=404, detail="agent not found")
        if payload.client_id is not None and _normalize_client_id(payload.client_id) != existing.client_id:
            raise HTTPException(status_code=409, detail="agent tenant scope cannot be changed")
        try:
            updated = agent_service.update(
                existing,
                name=payload.name,
                description=payload.description,
                enabled=payload.enabled,
                trigger=payload.trigger,
                entity_type=payload.entity_type,
                filters=payload.filters,
                enabled_tools=payload.enabled_tools,
                steps=[step.model_dump() for step in payload.steps],
                max_steps=payload.max_steps,
                execution_timeout_seconds=payload.execution_timeout_seconds,
                run_once_per_entity=payload.run_once_per_entity,
                depends_on_agent_ids=payload.depends_on_agent_ids,
                execution_window_start=payload.execution_window_start,
                execution_window_end=payload.execution_window_end,
                execution_window_timezone=payload.execution_window_timezone,
                context_sources=list(payload.context_sources),
                approval_expiry_seconds=payload.approval_expiry_seconds,
                result_aware=payload.result_aware,
                approval_required_tools=payload.approval_required_tools,
                approval_rules=[rule.model_dump() for rule in payload.approval_rules],
            )
        except AgentDefinitionError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _agent_definition_view(updated)

    @router.post("/agents/{agent_id}/run")
    def run_agent(
        agent_id: str,
        payload: AgentRunStartRequest,
        request: Request,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        scoped_client_id = resolve_client_scope(context, payload.client_id).client_id
        if context.role < Role.ADMIN and scoped_client_id is None:
            raise HTTPException(status_code=403, detail="authenticated principal has no tenant")
        definition = agent_service.get(agent_id, scoped_client_id)
        if definition is None:
            raise HTTPException(status_code=404, detail="agent not found")
        if definition.client_id is None and scoped_client_id is not None:
            definition = replace(definition, client_id=scoped_client_id)
        try:
            result = agent_service.run(
                definition,
                entity_id=payload.entity_id,
                actor=context.approver_id or "api",
                input_payload=payload.input,
                actor_role=context.role,
                correlation_id=_request_correlation_id(request),
            )
        except AgentDefinitionError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return asdict(result)

    def _process_backfill(
        backfill,
        definition,
        context: AuthContext,
        scope: ClientScope,
        scoped_client_id: str | None,
        correlation_id: str | None = None,
    ):
        entity_ids = [item for item in _safe_json_values(backfill.entity_ids_json) if isinstance(item, str)]
        input_payload = _safe_json_object(backfill.input_json)
        run_ids = [
            item
            for item in _safe_json_values(backfill.run_ids_json)
            if isinstance(item, int) and not isinstance(item, bool)
        ]
        failed_entity_ids = [
            item for item in _safe_json_values(backfill.failed_entity_ids_json) if isinstance(item, str)
        ]
        errors = [backfill.error_detail] if backfill.error_detail else []
        if definition.client_id is None and scoped_client_id is not None:
            definition = replace(definition, client_id=scoped_client_id)
        store.update_agent_backfill(
            backfill.id or 0,
            client_id=scope,
            status="running",
            next_index=backfill.next_index,
            processed_count=backfill.processed_count,
            succeeded_count=backfill.succeeded_count,
            failed_count=backfill.failed_count,
            run_ids=run_ids,
            failed_entity_ids=failed_entity_ids,
            error_detail="; ".join(errors),
        )
        processed_count = backfill.processed_count
        succeeded_count = backfill.succeeded_count
        failed_count = backfill.failed_count

        def run_entity(entity_id: str):
            try:
                result = agent_service.run(
                    definition,
                    entity_id=entity_id,
                    actor=backfill.actor or context.approver_id or "api",
                    input_payload=input_payload,
                    actor_role=context.role,
                    correlation_id=correlation_id,
                )
                if result.status in {"completed", "pending_approval"}:
                    return result, None
                return result, f"{entity_id}: agent run status {result.status}"
            except Exception as exc:  # continue independent entities
                return None, redact_text(f"{entity_id}: {exc}")

        max_concurrency = min(max(1, backfill.max_concurrency), AGENT_BACKFILL_MAX_CONCURRENCY)
        for batch_start in range(backfill.next_index, len(entity_ids), max_concurrency):
            batch = entity_ids[batch_start : batch_start + max_concurrency]
            if max_concurrency == 1:
                outcomes = [run_entity(batch[0])]
            else:
                with ThreadPoolExecutor(max_workers=max_concurrency) as executor:
                    outcomes = list(executor.map(run_entity, batch))
            for offset, (result, error_detail) in enumerate(outcomes):
                index = batch_start + offset
                entity_id = entity_ids[index]
                if result is not None:
                    if result.run_id:
                        run_ids.append(result.run_id)
                    if error_detail is None:
                        succeeded_count += 1
                    else:
                        failed_count += 1
                        failed_entity_ids.append(entity_id)
                        errors.append(error_detail)
                else:
                    failed_count += 1
                    failed_entity_ids.append(entity_id)
                    errors.append(error_detail or f"{entity_id}: agent run failed")
                processed_count += 1
                store.update_agent_backfill(
                    backfill.id or 0,
                    client_id=scope,
                    status="running",
                    next_index=index + 1,
                    processed_count=processed_count,
                    succeeded_count=succeeded_count,
                    failed_count=failed_count,
                    run_ids=run_ids,
                    failed_entity_ids=failed_entity_ids,
                    error_detail="; ".join(errors),
                )
        final_status = "completed_with_errors" if failed_entity_ids else "completed"
        return store.update_agent_backfill(
            backfill.id or 0,
            client_id=scope,
            status=final_status,
            next_index=len(entity_ids),
            processed_count=processed_count,
            succeeded_count=succeeded_count,
            failed_count=failed_count,
            run_ids=run_ids,
            failed_entity_ids=failed_entity_ids,
            error_detail="; ".join(errors),
        )

    @router.post("/agent-backfills")
    def create_agent_backfill(
        payload: AgentBackfillCreateRequest,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        scoped_client_id = _required_client_id(context, payload.client_id)
        if len(set(payload.entity_ids)) != len(payload.entity_ids):
            raise HTTPException(status_code=422, detail="entity_ids must not contain duplicates")
        definition = agent_service.get(payload.agent_id, scoped_client_id)
        if definition is None:
            raise HTTPException(status_code=404, detail="agent not found")
        backfill_scope = scoped_client_id
        for entity_id in payload.entity_ids:
            if store.get_ticket(entity_id, client_id=backfill_scope) is None:
                raise HTTPException(status_code=404, detail=f"ticket not found: {entity_id}")
        backfill = store.create_agent_backfill(
            payload.agent_id,
            payload.entity_ids,
            payload.input,
            actor=context.approver_id or "api",
            max_concurrency=payload.max_concurrency,
            client_id=scoped_client_id,
        )
        return _agent_backfill_view(backfill)

    @router.post("/agent-backfills/preview")
    def preview_agent_backfill(
        payload: AgentBackfillPreviewRequest,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        scoped_client_id = _required_client_id(context, payload.client_id)
        if len(set(payload.entity_ids)) != len(payload.entity_ids):
            raise HTTPException(status_code=422, detail="entity_ids must not contain duplicates")
        definition = agent_service.get(payload.agent_id, scoped_client_id)
        if definition is None:
            raise HTTPException(status_code=404, detail="agent not found")
        backfill_scope = scoped_client_id
        missing_entity_ids = [
            entity_id
            for entity_id in payload.entity_ids
            if store.get_ticket(entity_id, client_id=backfill_scope) is None
        ]
        if missing_entity_ids:
            raise HTTPException(
                status_code=404,
                detail=f"ticket not found: {missing_entity_ids[0]}",
            )
        execution_mode = "sequential" if payload.max_concurrency == 1 else "bounded_parallel"
        return {
            "dry_run": True,
            "agent_id": payload.agent_id,
            "entity_count": len(payload.entity_ids),
            "estimated_runs": len(payload.entity_ids),
            "max_concurrency": payload.max_concurrency,
            "execution_mode": execution_mode,
            "will_persist": False,
            "input": _redact_payload(payload.input),
            "client_id": scoped_client_id,
        }

    @router.get("/agent-backfills")
    def agent_backfills(
        context: ViewerAccess,
        client_id: str | None = None,
    ) -> list[dict[str, object]]:
        scope = _backfill_scope(context, client_id)
        return [_agent_backfill_view(item) for item in store.list_agent_backfills(scope)]

    @router.get("/agent-backfills/{backfill_id}")
    def agent_backfill_detail(backfill_id: int, context: ViewerAccess) -> dict[str, object]:
        scope = _backfill_scope(context, None)
        backfill = store.get_agent_backfill(backfill_id, scope)
        if backfill is None:
            raise HTTPException(status_code=404, detail="agent backfill not found")
        return _agent_backfill_view(backfill)

    @router.post("/agent-backfills/{backfill_id}/run")
    def run_agent_backfill(
        backfill_id: int,
        request: Request,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        scope = _backfill_scope(context, None)
        backfill = store.get_agent_backfill(backfill_id, scope)
        if backfill is None:
            raise HTTPException(status_code=404, detail="agent backfill not found")
        if backfill.status not in {"queued", "paused"}:
            raise HTTPException(status_code=409, detail="agent backfill is not runnable in its current state")
        definition = agent_service.get(backfill.agent_id, backfill.client_id)
        if definition is None:
            raise HTTPException(status_code=404, detail="agent not found")
        return _agent_backfill_view(
            _process_backfill(
                backfill,
                definition,
                context,
                scope,
                backfill.client_id,
                _request_correlation_id(request),
            )
        )

    @router.post("/agent-backfills/{backfill_id}/pause")
    def pause_agent_backfill(backfill_id: int, context: TechnicianAccess) -> dict[str, object]:
        scope = _backfill_scope(context, None)
        backfill = store.get_agent_backfill(backfill_id, scope)
        if backfill is None:
            raise HTTPException(status_code=404, detail="agent backfill not found")
        if backfill.status != "queued":
            raise HTTPException(status_code=409, detail="only queued backfills can be paused")
        return _agent_backfill_view(
            store.update_agent_backfill(
                backfill_id,
                client_id=scope,
                status="paused",
                next_index=backfill.next_index,
                processed_count=backfill.processed_count,
                succeeded_count=backfill.succeeded_count,
                failed_count=backfill.failed_count,
                run_ids=[
                    item
                    for item in _safe_json_values(backfill.run_ids_json)
                    if isinstance(item, int) and not isinstance(item, bool)
                ],
                failed_entity_ids=[
                    item for item in _safe_json_values(backfill.failed_entity_ids_json) if isinstance(item, str)
                ],
                error_detail=backfill.error_detail,
            )
        )

    @router.post("/agent-backfills/{backfill_id}/cancel")
    def cancel_agent_backfill(backfill_id: int, context: TechnicianAccess) -> dict[str, object]:
        scope = _backfill_scope(context, None)
        backfill = store.get_agent_backfill(backfill_id, scope)
        if backfill is None:
            raise HTTPException(status_code=404, detail="agent backfill not found")
        if backfill.status in {"completed", "completed_with_errors", "cancelled"}:
            raise HTTPException(status_code=409, detail="agent backfill is already terminal")
        return _agent_backfill_view(
            store.update_agent_backfill(
                backfill_id,
                client_id=scope,
                status="cancelled",
                next_index=backfill.next_index,
                processed_count=backfill.processed_count,
                succeeded_count=backfill.succeeded_count,
                failed_count=backfill.failed_count,
                run_ids=[],
                failed_entity_ids=[],
                error_detail=backfill.error_detail,
            )
        )

    @router.post("/agent-backfills/{backfill_id}/rerun-failed")
    def rerun_failed_backfill(
        backfill_id: int,
        request: Request,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        scope = _backfill_scope(context, None)
        backfill = store.get_agent_backfill(backfill_id, scope)
        if backfill is None:
            raise HTTPException(status_code=404, detail="agent backfill not found")
        failed_entity_ids = [
            item for item in _safe_json_values(backfill.failed_entity_ids_json) if isinstance(item, str)
        ]
        if not failed_entity_ids:
            raise HTTPException(status_code=409, detail="agent backfill has no failed entities")
        reset = store.reset_agent_backfill_failed(backfill_id, failed_entity_ids, client_id=scope)
        definition = agent_service.get(reset.agent_id, reset.client_id)
        if definition is None:
            raise HTTPException(status_code=404, detail="agent not found")
        return _agent_backfill_view(
            _process_backfill(
                reset,
                definition,
                context,
                scope,
                reset.client_id,
                _request_correlation_id(request),
            )
        )

    def _definition_for_agent_run(run) -> AgentDefinition | None:
        definition = agent_service.get(run.agent_id, run.client_id)
        if definition is None:
            definition = agent_service.get(run.agent_id)
        if definition is None:
            return None
        if definition.client_id is not None and definition.client_id != run.client_id:
            return None
        if definition.client_id is None and run.client_id is not None:
            return replace(definition, client_id=run.client_id)
        return definition

    @router.get("/agent-runs")
    def agent_runs(
        request: Request,
        context: ViewerAccess,
        client_id: str | None = None,
    ) -> list[dict[str, object]]:
        scope = resolve_client_scope(context, requested_client_from(request, client_id))
        return [_agent_run_view(run) for run in store.list_agent_runs(scope)]

    @router.get("/agent-runs/{run_id}")
    def agent_run_detail(run_id: int, context: ViewerAccess, client_id: str | None = None) -> dict[str, object]:
        scope = _resolve_detail_scope(context, client_id)
        run = store.get_agent_run(run_id, scope)
        if run is None:
            raise HTTPException(status_code=404, detail="agent run not found")
        view = _agent_run_view(run)
        definition = _definition_for_agent_run(run)
        if definition is not None and run.revision_version is not None:
            revision = store.get_agent_definition_revision(
                run.agent_id,
                run.revision_version,
                definition.client_id,
            )
            if revision is None and definition.client_id == run.client_id:
                revision = store.get_agent_definition_revision(
                    run.agent_id,
                    run.revision_version,
                    None,
                )
            if revision is not None:
                view["definition_revision"] = _agent_revision_view(revision)
        return view

    @router.post("/agent-runs/{run_id}/resume")
    def resume_agent(
        run_id: int,
        request: Request,
        context: TechnicianAccess,
        client_id: str | None = None,
    ) -> dict[str, object]:
        scope = _resolve_detail_scope(context, client_id)
        run = store.get_agent_run(run_id, scope)
        if run is None:
            raise HTTPException(status_code=404, detail="agent run not found")
        definition = _definition_for_agent_run(run)
        if definition is None:
            raise HTTPException(status_code=404, detail="agent definition not found")
        try:
            result = agent_service.resume(
                definition,
                run,
                approver=context.approver_id or "api",
                approver_role=context.role,
                correlation_id=_request_correlation_id(request),
            )
        except (AgentDefinitionError, PermissionError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return asdict(result)

    @router.post("/agent-runs/{run_id}/cancel")
    def cancel_agent_run(
        run_id: int,
        request: Request,
        context: TechnicianAccess,
        client_id: str | None = None,
    ) -> dict[str, object]:
        scope = _resolve_detail_scope(context, client_id)
        run = store.get_agent_run(run_id, scope)
        if run is None:
            raise HTTPException(status_code=404, detail="agent run not found")
        definition = _definition_for_agent_run(run)
        if definition is None:
            raise HTTPException(status_code=404, detail="agent definition not found")
        try:
            result = agent_service.cancel(
                definition,
                run,
                actor=context.approver_id or "api",
                approver_role=context.role,
                correlation_id=_request_correlation_id(request),
            )
        except (AgentDefinitionError, PermissionError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return asdict(result)

    @router.post("/agent-runs/{run_id}/retry")
    def retry_agent_run(
        run_id: int,
        request: Request,
        context: TechnicianAccess,
        client_id: str | None = None,
    ) -> dict[str, object]:
        scope = _resolve_detail_scope(context, client_id)
        run = store.get_agent_run(run_id, scope)
        if run is None:
            raise HTTPException(status_code=404, detail="agent run not found")
        definition = _definition_for_agent_run(run)
        if definition is None:
            raise HTTPException(status_code=404, detail="agent definition not found")
        try:
            result = agent_service.retry(
                definition,
                run,
                actor=context.approver_id or "api",
                actor_role=context.role,
                correlation_id=_request_correlation_id(request),
            )
        except (AgentDefinitionError, PermissionError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"retry_of_run_id": run.id, **asdict(result)}


    return router


__all__ = ["create_agents_router"]
