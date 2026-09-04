"""Scheduled-job API routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from wait_local_agent.api.context import ApiContext, TechnicianAccess, ViewerAccess
from wait_local_agent.api.schemas import ScheduledJobCreateRequest, ScheduledJobRescheduleRequest
from wait_local_agent.api.scopes import (
    _require_msp_operator,
    _required_client_id,
    _scheduled_job_for_context,
)
from wait_local_agent.api.views import _scheduled_job_view, _scheduled_ticket_id
from wait_local_agent.client_scope import AllClients, resolve_client_scope
from wait_local_agent.msp_playbooks import preview_msp_playbook
from wait_local_agent.rbac import AuthContext, Role
from wait_local_agent.scheduler import validate_scheduled_report_params
from wait_local_agent.store import _normalize_client_id
from wait_local_agent.workflows import get_workflow_template


def create_scheduled_jobs_router(ctx: ApiContext) -> APIRouter:
    router = APIRouter()
    active_settings = ctx.active_settings
    store = ctx.store
    scheduler = ctx.scheduler
    agent_service = ctx.agent_service

    @router.get("/scheduled-jobs")
    def scheduled_jobs(
        context: ViewerAccess,
        client_id: str | None = None,
    ) -> list[dict[str, object]]:
        scope = resolve_client_scope(context, client_id)
        return [_scheduled_job_view(job) for job in scheduler.list_jobs(client_id=scope)]

    @router.post("/scheduled-jobs")
    def create_scheduled_job(
        request: ScheduledJobCreateRequest,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        if request.job_kind == "backup":
            return _create_scheduled_backup_job(request, context)
        if request.job_kind == "baseline_snapshot":
            return _create_scheduled_baseline_snapshot_job(request, context)
        if request.graph_sync or request.job_kind == "graph_sync":
            return _create_scheduled_graph_sync_job(request, context)
        if request.playbook_id is not None:
            return _create_scheduled_playbook_job(request, context)
        if request.report_type is not None:
            return _create_scheduled_report_job(request, context)
        if request.agent_id is not None:
            return _create_scheduled_agent_job(request, context)
        if request.template_id is None:
            raise HTTPException(status_code=422, detail="template_id or agent_id is required")
        if get_workflow_template(request.template_id) is None:
            raise HTTPException(status_code=404, detail="workflow template not found")
        ticket_id = _scheduled_ticket_id(request.params)
        requested_client_id = request.params.get("client_id")
        if requested_client_id is not None and not isinstance(requested_client_id, str):
            raise HTTPException(status_code=422, detail="params.client_id must be a string")
        normalized_requested_client_id = (
            requested_client_id.strip() if isinstance(requested_client_id, str) else None
        )
        scope = resolve_client_scope(context, normalized_requested_client_id)
        ticket = store.get_ticket(ticket_id, client_id=scope)
        if ticket is None:
            raise HTTPException(status_code=404, detail="ticket not found")
        params = dict(request.params)
        if ticket.client_id:
            params["client_id"] = ticket.client_id
        try:
            scheduled_job = scheduler.register(
                request.template_id,
                request.cron,
                params,
                schedule_type=request.schedule_type,
                interval_seconds=request.interval_seconds,
                run_at=request.run_at,
                timezone=request.timezone,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return _scheduled_job_view(scheduled_job)

    def _create_scheduled_backup_job(
        request: ScheduledJobCreateRequest,
        context: AuthContext,
    ) -> dict[str, object]:
        if context.role < Role.ADMIN:
            raise HTTPException(status_code=403, detail="administrator access required")
        _require_msp_operator(context)
        if active_settings.demo_mode:
            raise HTTPException(status_code=403, detail="backup scheduling is unavailable in demo mode")
        if request.graph_sync or any(
            value is not None
            for value in (
                request.template_id,
                request.report_type,
                request.playbook_id,
                request.agent_id,
                request.entity_id,
            )
        ):
            raise HTTPException(status_code=422, detail="backup schedules cannot include another target")
        if request.params:
            raise HTTPException(status_code=422, detail="backup schedules do not accept params")
        try:
            scheduled_job = scheduler.register(
                "",
                request.cron,
                {},
                job_kind="backup",
                schedule_type=request.schedule_type,
                interval_seconds=request.interval_seconds,
                run_at=request.run_at,
                timezone=request.timezone,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return _scheduled_job_view(scheduled_job)

    def _create_scheduled_playbook_job(
        request: ScheduledJobCreateRequest,
        context: AuthContext,
    ) -> dict[str, object]:
        if request.template_id is not None or request.report_type is not None or request.agent_id is not None:
            raise HTTPException(status_code=422, detail="playbook schedules cannot include another target")
        if request.entity_id is not None:
            raise HTTPException(status_code=422, detail="playbook schedules use params.ticket_id")
        requested_client_id = request.params.get("client_id")
        if requested_client_id is not None and not isinstance(requested_client_id, str):
            raise HTTPException(status_code=422, detail="params.client_id must be a string")
        scoped_client_id = _required_client_id(
            context,
            requested_client_id.strip() if isinstance(requested_client_id, str) else None,
        )
        raw_ticket_id = request.params.get("ticket_id")
        if raw_ticket_id is not None and not isinstance(raw_ticket_id, str):
            raise HTTPException(status_code=422, detail="params.ticket_id must be a string")
        raw_input = request.params.get("input", {})
        if not isinstance(raw_input, dict):
            raise HTTPException(status_code=422, detail="params.input must be an object")
        try:
            preview = preview_msp_playbook(
                store,
                request.playbook_id or "",
                ticket_id=raw_ticket_id.strip() if isinstance(raw_ticket_id, str) and raw_ticket_id.strip() else None,
                client_id=scoped_client_id,
                input_payload=raw_input,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="MSP playbook not found") from exc
        except LookupError as exc:
            raise HTTPException(status_code=404, detail="ticket not found") from exc
        except PermissionError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        effective_client_id = preview.get("client_id")
        if not isinstance(effective_client_id, str) or not effective_client_id:
            raise HTTPException(status_code=422, detail="scheduled playbook requires a client scope")
        params = dict(request.params)
        params["client_id"] = effective_client_id
        if isinstance(raw_ticket_id, str) and raw_ticket_id.strip():
            params["ticket_id"] = raw_ticket_id.strip()
        params["input"] = dict(raw_input)
        try:
            scheduled_job = scheduler.register(
                request.playbook_id or "",
                request.cron,
                params,
                job_kind="playbook",
                schedule_type=request.schedule_type,
                interval_seconds=request.interval_seconds,
                run_at=request.run_at,
                timezone=request.timezone,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return _scheduled_job_view(scheduled_job)

    def _create_scheduled_report_job(
        request: ScheduledJobCreateRequest,
        context: AuthContext,
    ) -> dict[str, object]:
        if request.template_id is not None or request.agent_id is not None or request.entity_id is not None:
            raise HTTPException(status_code=422, detail="report schedules cannot include a workflow or agent target")
        requested_client_id = request.params.get("client_id")
        if requested_client_id is not None and not isinstance(requested_client_id, str):
            raise HTTPException(status_code=422, detail="params.client_id must be a string")
        scoped_client_id = resolve_client_scope(context, requested_client_id).client_id
        if scoped_client_id is None:
            raise HTTPException(status_code=400, detail="client_id is required for a scheduled report")
        params = dict(request.params)
        params["client_id"] = scoped_client_id
        try:
            validate_scheduled_report_params(params, timezone=request.timezone)
            scheduled_job = scheduler.register(
                request.report_type or "",
                request.cron,
                params,
                job_kind="report",
                schedule_type=request.schedule_type,
                interval_seconds=request.interval_seconds,
                run_at=request.run_at,
                timezone=request.timezone,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return _scheduled_job_view(scheduled_job)

    def _create_scheduled_agent_job(
        request: ScheduledJobCreateRequest,
        context: AuthContext,
    ) -> dict[str, object]:
        if request.template_id is not None:
            raise HTTPException(status_code=422, detail="choose either template_id or agent_id")
        if request.entity_id is None or not request.entity_id.strip():
            raise HTTPException(status_code=422, detail="agent schedules require entity_id")
        requested_client_id = request.params.get("client_id")
        if requested_client_id is not None and not isinstance(requested_client_id, str):
            raise HTTPException(status_code=422, detail="params.client_id must be a string")
        scope = resolve_client_scope(
            context,
            requested_client_id.strip() if isinstance(requested_client_id, str) else None,
        )
        scoped_client_id = scope.client_id
        if scoped_client_id is None:
            scoped_client_id = _normalize_client_id(context.client_id)
        if scoped_client_id is None:
            raise HTTPException(status_code=403, detail="client scope is required")
        definition = agent_service.get(request.agent_id or "")
        if definition is None:
            raise HTTPException(status_code=404, detail="agent not found")
        if definition.trigger != "scheduled":
            raise HTTPException(status_code=422, detail="agent is not configured for scheduled execution")
        if definition.client_id is not None and definition.client_id != scoped_client_id:
            raise HTTPException(status_code=404, detail="agent not found")
        effective_client_id = definition.client_id or scoped_client_id
        ticket_scope = effective_client_id if effective_client_id is not None else scope
        ticket = store.get_ticket(request.entity_id, client_id=ticket_scope)
        if ticket is None:
            raise HTTPException(status_code=404, detail="ticket not found")
        params = dict(request.params)
        raw_client_id = params.get("client_id")
        if (
            raw_client_id is None or (isinstance(raw_client_id, str) and not raw_client_id.strip())
        ) and ticket.client_id:
            params["client_id"] = ticket.client_id
        input_payload = params.get("input", {})
        if not isinstance(input_payload, dict):
            raise HTTPException(status_code=422, detail="params.input must be an object")
        try:
            scheduled_job = scheduler.register(
                "",
                request.cron,
                params,
                job_kind="agent",
                agent_id=definition.id,
                entity_id=request.entity_id,
                schedule_type=request.schedule_type,
                interval_seconds=request.interval_seconds,
                run_at=request.run_at,
                timezone=request.timezone,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return _scheduled_job_view(scheduled_job)

    def _create_scheduled_graph_sync_job(
        request: ScheduledJobCreateRequest,
        context: AuthContext,
    ) -> dict[str, object]:
        if any(
            value is not None
            for value in (request.template_id, request.report_type, request.playbook_id, request.agent_id)
        ):
            raise HTTPException(status_code=422, detail="environment sync schedules cannot include another target")
        requested_client_id = request.params.get("client_id")
        if requested_client_id is not None and not isinstance(requested_client_id, str):
            raise HTTPException(status_code=422, detail="params.client_id must be a string")
        scoped_client_id = resolve_client_scope(
            context,
            requested_client_id.strip() if isinstance(requested_client_id, str) else None,
        ).client_id
        if scoped_client_id is None:
            raise HTTPException(status_code=403, detail="client scope is required")
        if store.get_client(AllClients(), scoped_client_id) is None:
            raise HTTPException(status_code=404, detail="client not found")
        params = dict(request.params)
        params["client_id"] = scoped_client_id
        try:
            scheduled_job = scheduler.register(
                "",
                request.cron,
                params,
                job_kind="graph_sync",
                entity_id=scoped_client_id,
                schedule_type=request.schedule_type,
                interval_seconds=request.interval_seconds,
                run_at=request.run_at,
                timezone=request.timezone,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return _scheduled_job_view(scheduled_job)

    def _create_scheduled_baseline_snapshot_job(
        request: ScheduledJobCreateRequest,
        context: AuthContext,
    ) -> dict[str, object]:
        if context.role < Role.ADMIN:
            raise HTTPException(status_code=403, detail="administrator access required")
        _require_msp_operator(context)
        if active_settings.demo_mode or not active_settings.allow_write_actions:
            raise HTTPException(status_code=403, detail="baseline scheduling is unavailable in demo mode")
        if any(
            value is not None
            for value in (request.template_id, request.report_type, request.playbook_id, request.agent_id)
        ):
            raise HTTPException(status_code=422, detail="baseline snapshot schedules cannot include another target")
        requested_client_id = request.params.get("client_id")
        if requested_client_id is not None and not isinstance(requested_client_id, str):
            raise HTTPException(status_code=422, detail="params.client_id must be a string")
        scoped_client_id = resolve_client_scope(
            context,
            requested_client_id.strip() if isinstance(requested_client_id, str) else None,
        ).client_id
        if scoped_client_id is None:
            raise HTTPException(status_code=403, detail="client scope is required")
        if store.get_client(AllClients(), scoped_client_id) is None:
            raise HTTPException(status_code=404, detail="client not found")
        params = dict(request.params)
        params["client_id"] = scoped_client_id
        try:
            scheduled_job = scheduler.register(
                "",
                request.cron,
                params,
                job_kind="baseline_snapshot",
                entity_id=scoped_client_id,
                schedule_type=request.schedule_type,
                interval_seconds=request.interval_seconds,
                run_at=request.run_at,
                timezone=request.timezone,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return _scheduled_job_view(scheduled_job)

    @router.post("/scheduled-jobs/{job_id}/pause")
    def pause_scheduled_job(job_id: int, context: TechnicianAccess) -> dict[str, object]:
        try:
            _scheduled_job_for_context(store, job_id, context)
            return _scheduled_job_view(scheduler.pause(job_id))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="scheduled job not found") from exc

    @router.post("/scheduled-jobs/{job_id}/resume")
    def resume_scheduled_job(job_id: int, context: TechnicianAccess) -> dict[str, object]:
        try:
            _scheduled_job_for_context(store, job_id, context)
            return _scheduled_job_view(scheduler.resume(job_id))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="scheduled job not found") from exc

    @router.post("/scheduled-jobs/{job_id}/reschedule")
    def reschedule_scheduled_job(
        job_id: int,
        payload: ScheduledJobRescheduleRequest,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        try:
            _scheduled_job_for_context(store, job_id, context)
            return _scheduled_job_view(
                scheduler.reschedule(
                    job_id,
                    cron=payload.cron,
                    schedule_type=payload.schedule_type,
                    interval_seconds=payload.interval_seconds,
                    run_at=payload.run_at,
                    timezone=payload.timezone,
                )
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="scheduled job not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.delete("/scheduled-jobs/{job_id}")
    def delete_scheduled_job(job_id: int, context: TechnicianAccess) -> dict[str, object]:
        try:
            _scheduled_job_for_context(store, job_id, context)
            return _scheduled_job_view(scheduler.remove(job_id))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="scheduled job not found") from exc

    return router


__all__ = ["create_scheduled_jobs_router"]
