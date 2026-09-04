"""Workflow, execution, and template gallery API routes."""

from __future__ import annotations

from dataclasses import asdict, replace
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse

from wait_local_agent.api.context import ApiContext, TechnicianAccess, ViewerAccess
from wait_local_agent.api.schemas import (
    TemplateGalleryCreateRequest,
    TemplateGalleryImportRequest,
    TemplateGalleryRestoreRequest,
    TemplateGalleryUpdateRequest,
    WorkflowRunRequest,
)
from wait_local_agent.api.scopes import (
    _approval_scope_visible,
    _request_correlation_id,
    _required_client_id,
    _resolve_detail_scope,
)
from wait_local_agent.api.views import (
    _dispatch_workflow_completion_event,
    _execution_artifact_view,
    _execution_run_view,
    _execution_step_view,
    _template_gallery_export_view,
    _template_gallery_revision_diff_view,
    _template_gallery_revision_view,
    _template_gallery_view,
    _workflow_run_comparison_view,
)
from wait_local_agent.client_scope import AllClients, BoundClients, requested_client_from, resolve_client_scope
from wait_local_agent.observability import build_analytics_summary
from wait_local_agent.rbac import Role
from wait_local_agent.workflow_designer import WorkflowDesignError, default_workflow_design
from wait_local_agent.workflows import get_workflow_template, list_workflow_templates, run_workflow_template


def create_workflows_router(ctx: ApiContext) -> APIRouter:
    router = APIRouter()
    store = ctx.store
    smart_action_service = ctx.smart_action_service
    event_dispatcher = ctx.event_dispatcher
    _approval_view = ctx.approval_view

    @router.get("/workflows/templates")
    def workflow_templates(_: ViewerAccess) -> list[dict[str, object]]:
        return [asdict(template) for template in list_workflow_templates()]

    @router.get("/workflow-templates/gallery")
    def template_gallery(
        context: ViewerAccess,
        client_id: str | None = None,
    ) -> list[dict[str, object]]:
        scope = resolve_client_scope(context, client_id)
        return [_template_gallery_view(entry) for entry in store.list_template_gallery_entries(scope)]

    @router.post("/workflow-templates/gallery")
    def create_template_gallery_entry(
        payload: TemplateGalleryCreateRequest,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        template = get_workflow_template(payload.source_template_id)
        if template is None:
            raise HTTPException(status_code=404, detail="workflow template not found")
        scoped_client_id = _required_client_id(context, payload.client_id)
        try:
            definition = payload.definition if payload.definition is not None else default_workflow_design(template)
            entry = store.create_template_gallery_entry(
                template,
                provenance=payload.provenance,
                client_id=scoped_client_id,
                name=payload.display_name,
                instructions=payload.instructions,
                definition=definition,
            )
        except (ValueError, WorkflowDesignError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return _template_gallery_view(entry)

    @router.get("/workflow-templates/gallery/{entry_id}/export")
    def export_template_gallery_entry(entry_id: str, context: ViewerAccess) -> dict[str, object]:
        scope = _resolve_detail_scope(context, None)
        entry = store.get_template_gallery_entry(entry_id, scope)
        if entry is None:
            raise HTTPException(status_code=404, detail="template gallery entry not found")
        return _template_gallery_export_view(entry)

    @router.post("/workflow-templates/gallery/import")
    def import_template_gallery_entry(
        payload: TemplateGalleryImportRequest,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        template = get_workflow_template(payload.source_template_id)
        if template is None:
            raise HTTPException(status_code=404, detail="workflow template not found")
        scoped_client_id = _required_client_id(context, payload.client_id)
        try:
            entry = store.create_template_gallery_entry(
                template,
                provenance=payload.provenance,
                client_id=scoped_client_id,
                name=payload.name,
                description=payload.description,
                instructions=payload.instructions,
                enabled=False,
                definition=(
                    payload.definition if payload.definition is not None else default_workflow_design(template)
                ),
            )
        except (ValueError, WorkflowDesignError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return _template_gallery_view(entry)

    @router.get("/workflow-templates/gallery/{entry_id}")
    def template_gallery_detail(entry_id: str, context: ViewerAccess) -> dict[str, object]:
        scope = _resolve_detail_scope(context, None)
        entry = store.get_template_gallery_entry(entry_id, scope)
        if entry is None:
            raise HTTPException(status_code=404, detail="template gallery entry not found")
        return _template_gallery_view(entry)

    @router.patch("/workflow-templates/gallery/{entry_id}")
    def update_template_gallery_entry(
        entry_id: str,
        payload: TemplateGalleryUpdateRequest,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        scope = resolve_client_scope(context, payload.client_id)
        entry = store.get_template_gallery_entry(entry_id, scope)
        if entry is None:
            raise HTTPException(status_code=404, detail="template gallery entry not found")
        try:
            updated = store.update_template_gallery_entry(
                entry_id,
                name=payload.name,
                description=payload.description,
                instructions=payload.instructions,
                enabled=payload.enabled,
                definition=payload.definition,
                client_id=entry.client_id,
            )
        except (ValueError, WorkflowDesignError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return _template_gallery_view(updated)

    @router.get("/workflow-templates/gallery/{entry_id}/revisions")
    def template_gallery_revisions(
        entry_id: str,
        context: ViewerAccess,
        client_id: str | None = None,
    ) -> list[dict[str, object]]:
        scope = resolve_client_scope(context, client_id)
        entry = store.get_template_gallery_entry(entry_id, scope)
        if entry is None:
            return []
        return [
            _template_gallery_revision_view(revision)
            for revision in store.list_template_gallery_revisions(
                entry_id,
                entry.client_id if entry.client_id is not None else AllClients(),
            )
        ]

    @router.get("/workflow-templates/gallery/{entry_id}/revisions/{version}/diff/{other_version}")
    def template_gallery_revision_diff(
        entry_id: str,
        version: int,
        other_version: int,
        context: ViewerAccess,
        client_id: str | None = None,
    ) -> dict[str, object]:
        scope = _resolve_detail_scope(context, client_id)
        entry = store.get_template_gallery_entry(entry_id, scope)
        if entry is None:
            raise HTTPException(status_code=404, detail="template gallery revision not found")
        revision_scope = entry.client_id if entry.client_id is not None else AllClients()
        left = store.get_template_gallery_revision(entry_id, version, revision_scope)
        right = store.get_template_gallery_revision(entry_id, other_version, revision_scope)
        if left is None or right is None:
            raise HTTPException(status_code=404, detail="template gallery revision not found")
        return _template_gallery_revision_diff_view(left, right)

    @router.post("/workflow-templates/gallery/{entry_id}/revisions/{version}/restore")
    def restore_template_gallery_revision(
        entry_id: str,
        version: int,
        payload: TemplateGalleryRestoreRequest,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        scope = _resolve_detail_scope(context, payload.client_id)
        entry = store.get_template_gallery_entry(entry_id, scope)
        if entry is None:
            raise HTTPException(status_code=404, detail="template gallery entry not found")
        try:
            restored = store.restore_template_gallery_revision(
                entry_id,
                version,
                entry.client_id if entry.client_id is not None else AllClients(),
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="template gallery revision not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail="template gallery revision is no longer valid") from exc
        return _template_gallery_view(restored)

    @router.post("/workflow-templates/gallery/{entry_id}/runs")
    def run_template_gallery_entry(
        entry_id: str,
        payload: WorkflowRunRequest,
        request: Request,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        scope = resolve_client_scope(context, payload.client_id)
        entry = store.get_template_gallery_entry(entry_id, scope)
        if entry is None:
            raise HTTPException(status_code=404, detail="template gallery entry not found")
        if not entry.enabled:
            raise HTTPException(status_code=409, detail="template gallery entry is disabled")
        ticket = store.get_ticket(payload.ticket_id, client_id=scope)
        if ticket is None or ticket.client_id != entry.client_id:
            raise HTTPException(status_code=404, detail="ticket not found")
        source_template = get_workflow_template(entry.source_template_id)
        if source_template is None:
            raise HTTPException(status_code=409, detail="source workflow template is unavailable")
        try:
            run = run_workflow_template(
                store,
                entry.source_template_id,
                payload.ticket_id,
                client_id=entry.client_id,
                actor=context.approver_id or "api",
                trigger_source="template_gallery",
                tool_executor=smart_action_service,
                template_override=replace(
                    source_template,
                    name=entry.name,
                    description=entry.description,
                ),
                operator_instructions=entry.instructions,
                template_version=entry.version,
                input_payload=payload.payload,
                correlation_id=_request_correlation_id(request),
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if run.id is None:
            raise HTTPException(status_code=409, detail="ticket is quarantined pending client mapping")
        _dispatch_workflow_completion_event(event_dispatcher, run, context.approver_id or "api")
        return asdict(run)

    @router.post("/workflows/templates/{template_id}/runs")
    def run_workflow(
        template_id: str,
        payload: WorkflowRunRequest,
        request: Request,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        scope = resolve_client_scope(context, payload.client_id)
        ticket = store.get_ticket(payload.ticket_id, client_id=scope)
        if ticket is None:
            raise HTTPException(status_code=404, detail="ticket not found")
        try:
            run = run_workflow_template(
                store,
                template_id,
                payload.ticket_id,
                client_id=ticket.client_id,
                actor=context.approver_id or "api",
                trigger_source="api",
                tool_executor=smart_action_service,
                input_payload=payload.payload,
                correlation_id=_request_correlation_id(request),
            )
            if run.id is None:
                raise HTTPException(status_code=409, detail="ticket is quarantined pending client mapping")
            _dispatch_workflow_completion_event(event_dispatcher, run, context.approver_id or "api")
            return asdict(run)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="workflow template not found") from exc
        except LookupError as exc:
            raise HTTPException(status_code=404, detail="ticket not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.get("/workflow-runs")
    def workflow_runs(
        request: Request,
        context: ViewerAccess,
        client_id: str | None = None,
    ) -> list[dict[str, object]]:
        scope = resolve_client_scope(context, requested_client_from(request, client_id))
        return [asdict(run) for run in store.list_workflow_runs(client_id=scope)]

    @router.get("/workflow-runs/{run_id}")
    def workflow_run_detail(run_id: int, context: ViewerAccess) -> dict[str, object]:
        scope = _resolve_detail_scope(context, None)
        run = store.get_workflow_run(run_id, client_id=scope)
        if run is None:
            raise HTTPException(status_code=404, detail="workflow run not found")
        template = next(
            (item for item in list_workflow_templates() if item.id == run.template_id),
            None,
        )
        approval = store.get_approval_request(run.approval_request_id) if run.approval_request_id is not None else None
        return {
            **asdict(run),
            "template": asdict(template) if template is not None else None,
            "approval_request": (
                _approval_view(approval)
                if (
                    approval is not None
                    and approval.client_id == run.client_id
                    and _approval_scope_visible(context, approval)
                )
                else None
            ),
            "events": [asdict(event) for event in store.list_event_history_for_subject(run.ticket_id)],
        }

    @router.get("/workflow-runs/{run_id}/compare/{other_run_id}")
    def workflow_run_compare(
        run_id: int,
        other_run_id: int,
        context: ViewerAccess,
    ) -> dict[str, object]:
        scope = _resolve_detail_scope(context, None)
        left = store.get_workflow_run(run_id, client_id=scope)
        right = store.get_workflow_run(other_run_id, client_id=scope)
        if left is None or right is None:
            raise HTTPException(status_code=404, detail="workflow run not found")
        return _workflow_run_comparison_view(left, right)

    @router.get("/executions")
    def executions(
        request: Request,
        context: ViewerAccess,
        kind: str | None = None,
        status: str | None = None,
        started_from: Annotated[str | None, Query(alias="from")] = None,
        started_to: Annotated[str | None, Query(alias="to")] = None,
        client_id: str | None = None,
    ) -> list[dict[str, object]]:
        scope = resolve_client_scope(context, requested_client_from(request, client_id))
        if isinstance(scope, BoundClients) and scope.client_id is None:
            raise HTTPException(status_code=403, detail="execution lists require a single client or all-client scope")
        return [
            _execution_run_view(run)
            for run in store.list_execution_runs(
                client_id=scope,
                run_kind=kind,
                status=status,
                started_from=started_from,
                started_to=started_to,
            )
        ]

    @router.get("/executions/{execution_id}")
    def execution_detail(
        execution_id: int,
        request: Request,
        context: ViewerAccess,
        client_id: str | None = None,
    ) -> dict[str, object]:
        scope = _resolve_detail_scope(context, requested_client_from(request, client_id))
        if isinstance(scope, BoundClients) and scope.client_id is None:
            raise HTTPException(status_code=404, detail="execution not found")
        scoped_client_id = scope.client_id
        if context.role < Role.ADMIN and scoped_client_id is None and not context.is_msp_admin:
            raise HTTPException(status_code=404, detail="execution not found")
        run = store.get_execution_run(execution_id, client_id=scope)
        if run is None or run.id is None:
            raise HTTPException(status_code=404, detail="execution not found")
        return {
            **_execution_run_view(run),
            "steps": [_execution_step_view(step) for step in store.list_execution_steps(run.id)],
            "artifacts": [
                _execution_artifact_view(artifact)
                for artifact in store.list_execution_artifacts(
                    run.id,
                    client_id=run.client_id if run.client_id is not None else AllClients(),
                )
            ],
        }

    @router.get("/executions/{execution_id}/artifacts/{artifact_id}")
    def execution_artifact_download(
        execution_id: int,
        artifact_id: int,
        context: TechnicianAccess,
        client_id: str | None = None,
    ) -> FileResponse:
        scope = _resolve_detail_scope(context, client_id)
        if isinstance(scope, BoundClients) and scope.client_id is None:
            raise HTTPException(status_code=404, detail="execution artifact not found")
        scoped_client_id = scope.client_id
        if context.role < Role.ADMIN and scoped_client_id is None and not context.is_msp_admin:
            raise HTTPException(status_code=404, detail="execution artifact not found")
        run = store.get_execution_run(execution_id, client_id=scope)
        if run is None or run.id is None:
            raise HTTPException(status_code=404, detail="execution artifact not found")
        artifact = store.get_execution_artifact(
            artifact_id,
            client_id=run.client_id if run.client_id is not None else AllClients(),
        )
        if artifact is None or artifact.execution_run_id != run.id:
            raise HTTPException(status_code=404, detail="execution artifact not found")
        path = Path(artifact.storage_path).resolve()
        # Artifacts are content-addressed: the file name must be its digest.
        if path.name != artifact.sha256 or not path.is_file():
            raise HTTPException(status_code=404, detail="execution artifact not found")
        return FileResponse(path, media_type=artifact.media_type, filename=artifact.name)

    @router.get("/analytics/summary")
    def analytics_summary(
        context: ViewerAccess,
        started_from: Annotated[str | None, Query(alias="from")] = None,
        started_to: Annotated[str | None, Query(alias="to")] = None,
        client_id: str | None = None,
    ) -> dict[str, object]:
        scope = resolve_client_scope(context, client_id)
        if isinstance(scope, BoundClients) and scope.client_id is None:
            raise HTTPException(status_code=403, detail="analytics require a single client or all-client scope")
        estimates = {manifest.action_id: manifest.estimated_minutes_saved for manifest in smart_action_service.list()}
        return build_analytics_summary(
            store,
            estimates,
            started_from=started_from,
            started_to=started_to,
            client_id=scope,
        )

    return router


__all__ = ["create_workflows_router"]
