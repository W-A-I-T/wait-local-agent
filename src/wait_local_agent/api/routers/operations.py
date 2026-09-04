"""Operations, reporting, diagnostics, and audit API routes."""

from __future__ import annotations

import csv
import io
import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi import status as http_status
from fastapi.responses import FileResponse

from wait_local_agent.api.context import AdminAccess, ApiContext, TechnicianAccess, ViewerAccess
from wait_local_agent.api.schemas import (
    BackupCreateRequest,
    BackupRestoreRequest,
    ClientReportRequest,
    CollectorConfigRequest,
    CollectorRunRequest,
    DiagnosticsBundleRequest,
    DiagnosticsUploadRequest,
    HardeningRunRequest,
    RestoreExerciseRequest,
    SecretSetRequest,
)
from wait_local_agent.api.scopes import (
    _operator_scope,
    _require_msp_operator,
)
from wait_local_agent.api.views import _scheduled_job_view
from wait_local_agent.backup import (
    BackupEncryptionError,
    backup_state,
    restore_state,
    run_restore_exercise,
)
from wait_local_agent.client_scope import (
    AllClients,
    BoundClients,
    requested_client_from,
    resolve_client_scope,
)
from wait_local_agent.collectors import (
    collector_run_collection_scope,
    collector_run_result_status,
)
from wait_local_agent.connectors import list_secret_records
from wait_local_agent.diagnostics import (
    BundleLimitError,
    build_support_bundle,
    collect_diagnostics,
    preview_support_bundle,
    support_upload_refusal,
)
from wait_local_agent.diagnostics import scrub_text as scrub_diagnostic_text
from wait_local_agent.rbac import Role
from wait_local_agent.reports.builders import (
    build_appliance_hardening_report,
    build_restore_evidence_report,
)
from wait_local_agent.reports.hardening_checks import HardeningContext, run_hardening_checks
from wait_local_agent.reports.models import ReportFormat, ReportType
from wait_local_agent.reports.msp import (
    build_automation_opportunity_report,
    build_qbr_report,
    build_recurring_service_review_report,
)
from wait_local_agent.reports.renderers import report_as_dict
from wait_local_agent.vault import SecretVault, SecretVaultError


def create_operations_router(ctx: ApiContext) -> APIRouter:
    router = APIRouter()
    active_settings = ctx.active_settings
    store = ctx.store
    report_service = ctx.report_service
    collector_service = ctx.collector_service
    scheduler = ctx.scheduler
    smart_action_service = ctx.smart_action_service

    @router.get("/collectors/modules")
    def collector_modules(_: ViewerAccess) -> list[dict[str, object]]:
        return [asdict(manifest) for manifest in collector_service.list_modules()]

    @router.post("/collectors/modules/{module_id}/validate")
    def collector_validate(
        module_id: str,
        payload: CollectorConfigRequest,
        _: ViewerAccess,
    ) -> dict[str, object]:
        try:
            return asdict(collector_service.validate(module_id, payload.config))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="collector module not found") from exc

    @router.post("/collectors/modules/{module_id}/preview")
    def collector_preview(
        module_id: str,
        payload: CollectorConfigRequest,
        context: ViewerAccess,
    ) -> dict[str, object]:
        scoped_client_id = resolve_client_scope(context, payload.client_id).client_id
        try:
            return asdict(
                collector_service.preview(
                    module_id,
                    payload.config,
                    client_id=scoped_client_id,
                )
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="collector module not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/collectors/modules/{module_id}/run")
    def collector_run(
        module_id: str,
        payload: CollectorRunRequest,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        scoped_client_id = resolve_client_scope(context, payload.client_id).client_id
        try:
            run = collector_service.run(
                module_id,
                payload.config,
                confirm=payload.confirm,
                client_id=scoped_client_id,
                actor_id=context.approver_id,
            )
            return {
                **asdict(run),
                "result_status": collector_run_result_status(run),
                "collection_scope": collector_run_collection_scope(run),
            }
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="collector module not found") from exc
        except PermissionError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/collectors/runs")
    def collector_runs(
        context: ViewerAccess,
        client_id: str | None = None,
    ) -> list[dict[str, object]]:
        return [
            {
                **asdict(run),
                "result_status": collector_run_result_status(run),
                "collection_scope": collector_run_collection_scope(run),
            }
            for run in store.list_collector_runs(
                client_id=resolve_client_scope(context, client_id)
            )
        ]

    @router.get("/collectors/runs/{run_id}")
    def collector_run_detail(run_id: int, context: ViewerAccess) -> dict[str, object]:
        scope = resolve_client_scope(context, None)
        run = store.get_collector_run(run_id, client_id=scope)
        if run is None:
            raise HTTPException(status_code=404, detail="collector run not found")
        return {
            **asdict(run),
            "result_status": collector_run_result_status(run),
            "collection_scope": collector_run_collection_scope(run),
            "assets": [
                asdict(asset)
                for asset in store.list_canonical_assets(run_id=run_id, client_id=scope)
            ],
            "observations": [asdict(observation) for observation in store.list_asset_observations(run_id=run_id)],
            "config_snapshots": [asdict(snapshot) for snapshot in store.list_config_snapshots(run_id=run_id)],
            "config_diffs": [asdict(diff) for diff in store.list_config_diffs(run_id=run_id)],
            "restore_exercises": [asdict(exercise) for exercise in store.list_restore_exercises(run_id=run_id)],
        }

    @router.post("/collectors/runs/{run_id}/export")
    def collector_run_export(
        run_id: int,
        context: ViewerAccess,
        report_type: ReportType = ReportType.COLLECTOR_BUNDLE,
    ) -> dict[str, object]:
        scope = resolve_client_scope(context, None)
        if store.get_collector_run(run_id, client_id=scope) is None:
            raise HTTPException(status_code=404, detail="collector run not found")
        try:
            report = collector_service.export_report(
                run_id,
                report_type,
                created_by=context.approver_id or "system",
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="collector run not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return report_as_dict(report)

    @router.post("/reports/qbr")
    def create_qbr_report(
        request: ClientReportRequest,
        context: ViewerAccess,
    ) -> dict[str, object]:
        scope = _operator_scope(context, active_settings.client_id, request.client_id)
        if context.role < Role.ADMIN and isinstance(scope, AllClients):
            raise HTTPException(status_code=403, detail="reports require a client scope")
        scoped_client_id = scope.client_id
        if scoped_client_id is None:
            raise HTTPException(status_code=400, detail="client_id is required to generate a client report")
        if request.period_end < request.period_start:
            raise HTTPException(status_code=400, detail="period_end must be on or after period_start")
        estimates = {manifest.action_id: manifest.estimated_minutes_saved for manifest in smart_action_service.list()}
        sections, metadata = build_qbr_report(
            store,
            estimates,
            client_id=scoped_client_id,
            period_start=request.period_start.isoformat(),
            period_end=request.period_end.isoformat(),
        )
        report = report_service.create_report(
            ReportType.QBR,
            f"Quarterly business review — {scoped_client_id}",
            sections,
            created_by=context.approver_id or "system",
            client_id=scoped_client_id,
            metadata=metadata,
        )
        return report_as_dict(report)

    @router.post("/reports/automation-opportunity")
    def create_automation_opportunity_report(
        request: ClientReportRequest,
        context: ViewerAccess,
    ) -> dict[str, object]:
        scope = _operator_scope(context, active_settings.client_id, request.client_id)
        if context.role < Role.ADMIN and isinstance(scope, AllClients):
            raise HTTPException(status_code=403, detail="reports require a client scope")
        scoped_client_id = scope.client_id
        if scoped_client_id is None:
            raise HTTPException(status_code=400, detail="client_id is required to generate a client report")
        if request.period_end < request.period_start:
            raise HTTPException(status_code=400, detail="period_end must be on or after period_start")
        estimates = {manifest.action_id: manifest.estimated_minutes_saved for manifest in smart_action_service.list()}
        sections, metadata = build_automation_opportunity_report(
            store,
            estimates,
            client_id=scoped_client_id,
            period_start=request.period_start.isoformat(),
            period_end=request.period_end.isoformat(),
        )
        report = report_service.create_report(
            ReportType.AUTOMATION_OPPORTUNITY,
            f"Automation opportunities — {scoped_client_id}",
            sections,
            created_by=context.approver_id or "system",
            client_id=scoped_client_id,
            metadata=metadata,
        )
        return report_as_dict(report)

    @router.post("/reports/recurring-service-review")
    def create_recurring_service_review_report(
        request: ClientReportRequest,
        context: ViewerAccess,
        follow_up_after_days: int = Query(default=14, ge=1, le=90),
    ) -> dict[str, object]:
        scope = _operator_scope(context, active_settings.client_id, request.client_id)
        if context.role < Role.ADMIN and isinstance(scope, AllClients):
            raise HTTPException(status_code=403, detail="reports require a client scope")
        scoped_client_id = scope.client_id
        if scoped_client_id is None:
            raise HTTPException(status_code=400, detail="client_id is required to generate a client report")
        if request.period_end < request.period_start:
            raise HTTPException(status_code=400, detail="period_end must be on or after period_start")
        try:
            sections, metadata = build_recurring_service_review_report(
                store,
                client_id=scoped_client_id,
                period_start=request.period_start.isoformat(),
                period_end=request.period_end.isoformat(),
                follow_up_after_days=follow_up_after_days,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        report = report_service.create_report(
            ReportType.RECURRING_SERVICE_REVIEW,
            f"Recurring service review — {scoped_client_id}",
            sections,
            created_by=context.approver_id or "system",
            client_id=scoped_client_id,
            metadata=metadata,
        )
        return report_as_dict(report)

    @router.get("/reports")
    def reports(
        context: ViewerAccess,
        report_type: ReportType | None = None,
        client_id: str = "",
        project_id: str = "",
    ) -> list[dict[str, object]]:
        scope = _operator_scope(context, active_settings.client_id, client_id or None)
        if context.role < Role.ADMIN and isinstance(scope, AllClients):
            raise HTTPException(status_code=403, detail="reports require a single client or all-client scope")
        if isinstance(scope, BoundClients) and scope.client_id is None:
            raise HTTPException(status_code=403, detail="reports require a single client or all-client scope")
        scoped_client_id = scope.client_id
        stored = report_service.list_reports(
            report_type=report_type,
            client_id=scoped_client_id or "",
            project_id=project_id,
        )
        return [report_as_dict(report) for report in stored]

    @router.get("/reports/{report_id}")
    def report_detail(report_id: str, context: ViewerAccess) -> dict[str, object]:
        scope = _operator_scope(context, active_settings.client_id)
        if context.role < Role.ADMIN and isinstance(scope, AllClients):
            raise HTTPException(status_code=404, detail="report not found")
        if isinstance(scope, BoundClients) and scope.client_id is None:
            raise HTTPException(status_code=404, detail="report not found")
        report = report_service.get_report(report_id, client_id=scope.client_id)
        if report is None:
            raise HTTPException(status_code=404, detail="report not found")
        return report_as_dict(report)

    @router.get("/reports/{report_id}/export")
    def report_export(
        report_id: str,
        context: ViewerAccess,
        export_format: Literal["json", "markdown", "pdf"] = "json",
    ) -> Response:
        scope = _operator_scope(context, active_settings.client_id)
        if context.role < Role.ADMIN and isinstance(scope, AllClients):
            raise HTTPException(status_code=404, detail="report not found")
        if isinstance(scope, BoundClients) and scope.client_id is None:
            raise HTTPException(status_code=404, detail="report not found")
        try:
            rendered = report_service.export_report(
                report_id,
                ReportFormat(export_format),
                client_id=scope.client_id,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="report not found") from exc
        media_type = {"json": "application/json", "markdown": "text/markdown", "pdf": "application/pdf"}[export_format]
        extension = {"json": "json", "markdown": "md", "pdf": "pdf"}[export_format]
        return Response(
            rendered,
            media_type=media_type,
            headers={"Content-Disposition": f'attachment; filename="wait-report-{report_id}.{extension}"'},
        )

    @router.get("/audit")
    def audit(
        request: Request,
        context: ViewerAccess,
        client_id: str | None = None,
    ) -> list[dict[str, object]]:
        scope = resolve_client_scope(context, requested_client_from(request, client_id))
        return [asdict(event) for event in store.list_audit_events(client_id=scope)]

    @router.get("/audit-events/export")
    def audit_events_export(
        request: Request,
        context: AdminAccess,
        format: Literal["json", "csv"] = "json",
        from_: Annotated[datetime | None, Query(alias="from")] = None,
        to_: Annotated[datetime | None, Query(alias="to")] = None,
        client_id: str | None = None,
    ) -> Response:
        scope = resolve_client_scope(context, requested_client_from(request, client_id))
        all_events = store.list_audit_events(client_id=scope)
        filtered = [
            e
            for e in all_events
            if (from_ is None or datetime.fromisoformat(e.created_at) >= from_.astimezone(UTC))
            and (to_ is None or datetime.fromisoformat(e.created_at) <= to_.astimezone(UTC))
        ]
        events = [asdict(e) for e in filtered]
        if format == "csv":
            output = io.StringIO()
            fieldnames = ["id", "event_type", "subject_id", "detail", "created_at", "client_id", "approver_id"]
            writer = csv.DictWriter(output, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(events)
            return Response(
                output.getvalue(),
                media_type="text/csv",
                headers={"Content-Disposition": 'attachment; filename="wait-audit-events.csv"'},
            )
        return Response(
            json.dumps({"count": len(events), "events": events}),
            media_type="application/json",
        )

    @router.get("/event-history")
    def event_history(
        request: Request,
        context: ViewerAccess,
        client_id: str | None = None,
    ) -> list[dict[str, object]]:
        scope = resolve_client_scope(context, requested_client_from(request, client_id))
        return [asdict(event) for event in store.list_event_history(client_id=scope)]


    @router.get("/secrets")
    def secrets(_: AdminAccess) -> list[dict[str, object]]:
        if active_settings.demo_mode:
            raise HTTPException(status_code=403, detail="secrets are unavailable in demo mode")
        return [asdict(secret) for secret in list_secret_records(active_settings)]

    @router.post("/secrets")
    def set_secret(payload: SecretSetRequest, _: AdminAccess) -> dict[str, str]:
        if active_settings.demo_mode:
            raise HTTPException(status_code=403, detail="secrets are unavailable in demo mode")
        try:
            SecretVault.initialize(
                active_settings.vault_path,
                demo_mode=active_settings.demo_mode,
            ).set(payload.name, payload.value)
        except (SecretVaultError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"name": payload.name, "status": "stored"}

    @router.get("/backups")
    def list_backups(
        context: AdminAccess,
        page: Annotated[int, Query(ge=1, le=100)] = 1,
        page_size: Annotated[int, Query(ge=1, le=100)] = 25,
    ) -> dict[str, object]:
        _require_msp_operator(context)
        offset = (page - 1) * page_size
        runs = store.list_backup_runs(limit=page_size, offset=offset)
        backup_schedules = [job for job in store.list_scheduled_jobs() if job.job_kind == "backup"]
        latest_exercise = store.list_restore_exercises()[-1:]
        restore_reference: dict[str, object] | None = None
        if latest_exercise:
            exercise = latest_exercise[0]
            restore_reference = {
                "id": exercise.id,
                "exercise_id": exercise.exercise_id,
                "status": exercise.status,
                "backup_artifact_id": exercise.backup_artifact_id,
                "completed_at": exercise.completed_at,
                "evidence_reference": exercise.exercise_id,
            }
        schedule = _scheduled_job_view(backup_schedules[0]) if backup_schedules else None
        return {
            "items": [asdict(run) for run in runs],
            "runs": [asdict(run) for run in runs],
            "page": page,
            "page_size": page_size,
            "total": store.count_backup_runs(),
            "schedule_configured": schedule is not None,
            "schedule": schedule,
            "last_restore_exercise": restore_reference,
        }

    @router.post("/backups/run")
    def run_backup(context: AdminAccess) -> dict[str, object]:
        _require_msp_operator(context)
        if active_settings.demo_mode:
            raise HTTPException(status_code=403, detail="backup runs are unavailable in demo mode")
        store.add_audit_event(
            "backup.run_requested",
            "manual",
            "admin requested backup run",
            approver_id=context.approver_id,
        )
        return asdict(scheduler.run_backup())

    @router.post("/backups")
    def create_backup(payload: BackupCreateRequest, _: AdminAccess) -> dict[str, object]:
        try:
            path = backup_state(
                store,
                Path(payload.destination),
                encrypt=payload.encrypt,
                settings=active_settings,
            )
        except (BackupEncryptionError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except OSError as exc:
            raise HTTPException(status_code=400, detail="backup destination could not be written") from exc
        return {"backup": str(path), "encrypted": payload.encrypt}

    @router.post("/backups/restore")
    def restore_backup(payload: BackupRestoreRequest, _: AdminAccess) -> dict[str, object]:
        try:
            path = restore_state(
                store,
                Path(payload.source),
                encrypted=payload.encrypted,
                settings=active_settings,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="backup source not found") from exc
        except (BackupEncryptionError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except OSError as exc:
            raise HTTPException(status_code=400, detail="backup source could not be restored") from exc
        return {"restored": str(path), "encrypted": payload.encrypted}

    @router.post("/hardening/runs")
    def create_hardening_run(payload: HardeningRunRequest, context: AdminAccess) -> dict[str, object]:
        store.add_audit_event("hardening.run_requested", "hardening", "admin requested hardening checks")
        backup_paths = tuple(Path(item) for item in payload.backup_paths)
        if not backup_paths:
            backup_paths = tuple(
                path
                for path in active_settings.data_path.parent.glob("*")
                if path.is_file() and path != active_settings.data_path
            )
        hardening_context = HardeningContext.from_settings(
            active_settings,
            store=store,
            backup_paths=backup_paths,
            audit_event_count=len(store.list_audit_events()),
        )
        run = run_hardening_checks(hardening_context, store=store)
        if run.id is None:
            raise HTTPException(status_code=500, detail="hardening run was not persisted")
        sections, metadata = build_appliance_hardening_report(store, run.id)
        report = report_service.create_report(
            ReportType.APPLIANCE_HARDENING,
            f"Appliance Hardening Evidence {run.id}",
            sections,
            created_by=context.approver_id or "system",
            project_id=f"hardening-run-{run.id}",
            metadata=metadata,
        )
        store.add_audit_event("hardening.run_completed", str(run.id), run.status)
        return {"run": asdict(run), "report": report_as_dict(report)}

    @router.get("/hardening/runs")
    def list_hardening_runs(_: ViewerAccess) -> list[dict[str, object]]:
        return [asdict(run) for run in store.list_hardening_runs()]

    @router.get("/diagnostics/summary")
    def diagnostics_summary(context: AdminAccess) -> dict[str, object]:
        _require_msp_operator(context)
        return collect_diagnostics(active_settings, store).to_dict()

    @router.post("/diagnostics/bundle/preview")
    def diagnostics_bundle_preview(
        payload: DiagnosticsBundleRequest,
        context: AdminAccess,
    ) -> dict[str, object]:
        _require_msp_operator(context)
        return preview_support_bundle(
            active_settings,
            store,
            case_id=payload.case_id,
        ).to_dict()

    @router.post("/diagnostics/bundle")
    def diagnostics_bundle(
        payload: DiagnosticsBundleRequest,
        context: AdminAccess,
    ) -> FileResponse:
        _require_msp_operator(context)
        try:
            result = build_support_bundle(
                active_settings,
                store,
                case_id=payload.case_id,
            )
        except BundleLimitError as exc:
            raise HTTPException(status_code=507, detail="support bundle exceeded its safety limit") from exc
        store.add_audit_event(
            "support.bundle_created",
            result.sha256[:16],
            "redacted support bundle created locally",
        )
        return FileResponse(
            result.path,
            media_type="application/zip",
            filename=result.path.name,
            headers={"X-Support-Bundle-SHA256": result.sha256},
        )

    @router.post("/diagnostics/bundle/upload")
    def diagnostics_bundle_upload(
        payload: DiagnosticsUploadRequest,
        context: AdminAccess,
    ) -> dict[str, object]:
        _require_msp_operator(context)
        reason = support_upload_refusal(active_settings, consent=payload.consent)
        store.add_audit_event("support.upload_unavailable", "support-bundle", scrub_diagnostic_text(reason))
        raise HTTPException(
            status_code=http_status.HTTP_501_NOT_IMPLEMENTED,
            detail={
                "code": "support_upload_unavailable",
                "message": scrub_diagnostic_text(reason),
            },
        )

    @router.post("/backup/restore-exercises")
    def create_restore_exercise(
        payload: RestoreExerciseRequest,
        context: AdminAccess,
    ) -> dict[str, object]:
        store.add_audit_event(
            "backup.restore_exercise_requested",
            payload.backup_id,
            "admin requested restore exercise",
        )
        try:
            result = run_restore_exercise(
                payload.backup_id,
                store=store,
                settings=active_settings,
                encrypted=payload.encrypted,
            )
        except OSError as exc:
            raise HTTPException(status_code=400, detail="restore exercise could not be started") from exc
        sections, metadata = build_restore_evidence_report(store)
        report = report_service.create_report(
            ReportType.RESTORE_EVIDENCE,
            "Restore Evidence",
            sections,
            created_by=context.approver_id or "system",
            project_id=f"restore-exercise-{result.exercise_id}",
            metadata=metadata,
        )
        return {"exercise": asdict(result), "report": report_as_dict(report)}

    @router.get("/backup/restore-exercises")
    def list_restore_exercises(_: ViewerAccess) -> list[dict[str, object]]:
        return [asdict(exercise) for exercise in store.list_restore_exercises()]



    return router


__all__ = ["create_operations_router"]
