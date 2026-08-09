from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger

from wait_local_agent.agents import AgentService
from wait_local_agent.models import EVENT_RETRY_POLL_SECONDS, ScheduledJob
from wait_local_agent.reports.models import ReportType
from wait_local_agent.reports.msp import build_automation_opportunity_report, build_qbr_report
from wait_local_agent.reports.renderers import redact_text
from wait_local_agent.reports.service import ReportService
from wait_local_agent.smart_actions import SmartActionService
from wait_local_agent.store import Store
from wait_local_agent.workflows import run_workflow_template

if TYPE_CHECKING:
    from wait_local_agent.event_dispatch import EventDispatcher


class SchedulerManager:
    def __init__(
        self,
        store: Store,
        *,
        enabled: bool = True,
        agent_service: AgentService | None = None,
        smart_action_service: SmartActionService | None = None,
        event_dispatcher: EventDispatcher | None = None,
    ) -> None:
        self._store = store
        self._enabled = enabled
        self._agent_service = agent_service
        self._smart_action_service = smart_action_service
        self._event_dispatcher = event_dispatcher
        self._scheduler: AsyncIOScheduler | None = None
        self._started = False

    @property
    def enabled(self) -> bool:
        return self._enabled

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        if not self._enabled:
            return
        self._scheduler = AsyncIOScheduler(timezone=UTC)
        self._scheduler.start()
        if self._event_dispatcher is not None:
            self._scheduler.add_job(
                self._retry_due_event_deliveries,
                trigger=IntervalTrigger(seconds=EVENT_RETRY_POLL_SECONDS, timezone=UTC),
                id=self._retry_job_identity(),
                replace_existing=True,
                coalesce=True,
                max_instances=1,
            )
        for scheduled_job in self._store.list_scheduled_jobs():
            self._register_live_job(scheduled_job)

    def shutdown(self) -> None:
        if self._scheduler is not None:
            self._scheduler.shutdown(wait=False)
            self._scheduler = None
        self._started = False

    def register(
        self,
        template_id: str,
        cron: str,
        params: dict[str, object],
        *,
        job_kind: str = "workflow",
        agent_id: str | None = None,
        entity_id: str | None = None,
        schedule_type: str = "cron",
        interval_seconds: int | None = None,
        run_at: str | None = None,
        timezone: str = "UTC",
    ) -> ScheduledJob:
        normalized_timezone = validate_schedule(schedule_type, cron, interval_seconds, run_at, timezone)
        _validate_schedule_target(job_kind, template_id, agent_id, entity_id)
        client_id = _string_or_none(params.get("client_id"))
        scheduled_job = self._store.create_scheduled_job(
            template_id,
            cron,
            params,
            client_id=client_id,
            job_kind=job_kind,
            agent_id=agent_id,
            entity_id=entity_id,
            schedule_type=schedule_type,
            interval_seconds=interval_seconds,
            run_at=run_at,
            timezone=normalized_timezone,
        )
        if self._scheduler is not None:
            self._register_live_job(scheduled_job)
        return self._with_runtime_state(scheduled_job)

    def list_jobs(self, client_id: str | None = None) -> list[ScheduledJob]:
        return [self._with_runtime_state(job) for job in self._store.list_scheduled_jobs(client_id=client_id)]

    def pause(self, job_id: int) -> ScheduledJob:
        scheduled_job = self._store.update_scheduled_job_paused(job_id, True)
        if self._scheduler is not None:
            live_job = self._scheduler.get_job(self._job_identity(job_id))
            if live_job is not None:
                self._scheduler.pause_job(self._job_identity(job_id))
        return self._with_runtime_state(scheduled_job)

    def resume(self, job_id: int) -> ScheduledJob:
        scheduled_job = self._store.update_scheduled_job_paused(job_id, False)
        if self._scheduler is not None:
            live_job = self._scheduler.get_job(self._job_identity(job_id))
            if live_job is not None:
                self._scheduler.resume_job(self._job_identity(job_id))
        return self._with_runtime_state(scheduled_job)

    def reschedule(
        self,
        job_id: int,
        *,
        cron: str,
        schedule_type: str,
        interval_seconds: int | None,
        run_at: str | None,
        timezone: str = "UTC",
    ) -> ScheduledJob:
        existing = self._store.get_scheduled_job(job_id)
        if existing is None:
            raise KeyError(job_id)
        normalized_timezone = validate_schedule(schedule_type, cron, interval_seconds, run_at, timezone)
        _validate_schedule_target(existing.job_kind, existing.template_id, existing.agent_id, existing.entity_id)
        scheduled_job = self._store.update_scheduled_job_schedule(
            job_id,
            cron=cron,
            schedule_type=schedule_type,
            interval_seconds=interval_seconds,
            run_at=run_at,
            timezone=normalized_timezone,
        )
        if self._scheduler is not None:
            self._register_live_job(scheduled_job)
        return self._with_runtime_state(scheduled_job)

    def remove(self, job_id: int) -> ScheduledJob:
        scheduled_job = self._store.delete_scheduled_job(job_id)
        if self._scheduler is not None:
            live_job = self._scheduler.get_job(self._job_identity(job_id))
            if live_job is not None:
                self._scheduler.remove_job(self._job_identity(job_id))
        return self._with_runtime_state(scheduled_job)

    async def _run_job(self, scheduled_job: ScheduledJob) -> None:
        params = _safe_json_object(scheduled_job.params_json)
        client_id = _string_or_none(params.get("client_id")) or scheduled_job.client_id
        if scheduled_job.job_kind == "agent":
            await self._run_agent_job(scheduled_job, params, client_id)
            return
        if scheduled_job.job_kind == "report":
            await self._run_report_job(scheduled_job, params, client_id)
            return
        ticket_id = _required_ticket_id(params)
        try:
            input_payload = params.get("input", {})
            if not isinstance(input_payload, dict):
                raise ValueError("scheduled workflow input must be an object")
            run = run_workflow_template(
                self._store,
                scheduled_job.template_id,
                ticket_id,
                client_id=client_id,
                actor="scheduler",
                trigger_source="scheduler",
                tool_executor=self._smart_action_service,
                input_payload=input_payload,
            )
        except Exception as exc:
            self._store.add_audit_event(
                "scheduled_job.trigger_failed",
                str(scheduled_job.id),
                f"{scheduled_job.template_id} failed: {exc}",
                client_id=client_id,
            )
            raise
        self._store.add_audit_event(
            "scheduled_job.triggered",
            str(scheduled_job.id),
            f"{scheduled_job.template_id} created workflow run {run.id}",
            client_id=client_id,
        )
        self._dispatch_completion(
            run_id=run.id,
            ticket_id=run.ticket_id,
            template_id=run.template_id,
            status=run.status,
            client_id=run.client_id,
            actor="scheduler",
        )

    async def _run_report_job(
        self,
        scheduled_job: ScheduledJob,
        params: dict[str, object],
        client_id: str | None,
    ) -> None:
        try:
            if client_id is None:
                raise ValueError("scheduled report params must include client_id")
            report_type = _scheduled_report_type(scheduled_job.template_id)
            period_start, period_end = _scheduled_report_period(
                params,
                timezone=scheduled_job.timezone,
            )
            if self._smart_action_service is None:
                raise RuntimeError("scheduled report execution is not configured")
            estimates = {
                manifest.action_id: manifest.estimated_minutes_saved
                for manifest in self._smart_action_service.list()
            }
            if report_type is ReportType.QBR:
                sections, metadata = build_qbr_report(
                    self._store,
                    estimates,
                    client_id=client_id,
                    period_start=period_start,
                    period_end=period_end,
                )
                title = f"Quarterly business review — {client_id}"
            else:
                sections, metadata = build_automation_opportunity_report(
                    self._store,
                    estimates,
                    client_id=client_id,
                    period_start=period_start,
                    period_end=period_end,
                )
                title = f"Automation opportunities — {client_id}"
            report = ReportService(self._store).create_report(
                report_type,
                title,
                sections,
                created_by="scheduler",
                client_id=client_id,
                metadata=metadata,
            )
        except Exception as exc:
            self._store.add_audit_event(
                "scheduled_job.trigger_failed",
                str(scheduled_job.id),
                f"{scheduled_job.template_id} report failed: {redact_text(str(exc))}",
                client_id=client_id,
            )
            raise
        self._store.add_audit_event(
            "scheduled_job.triggered",
            str(scheduled_job.id),
            f"{scheduled_job.template_id} created report {report.id}",
            client_id=client_id,
        )

    async def _run_agent_job(
        self,
        scheduled_job: ScheduledJob,
        params: dict[str, object],
        client_id: str | None,
    ) -> None:
        try:
            if self._agent_service is None:
                raise RuntimeError("scheduled agent execution is not configured")
            if scheduled_job.agent_id is None or scheduled_job.entity_id is None:
                raise ValueError("scheduled agent is missing agent_id or entity_id")
            definition = self._agent_service.get(scheduled_job.agent_id)
            if definition is None:
                raise LookupError("scheduled agent definition not found")
            if definition.trigger != "scheduled":
                raise ValueError("scheduled agent definition has the wrong trigger")
            if definition.client_id is not None and definition.client_id != client_id:
                raise PermissionError("scheduled agent is outside the schedule tenant scope")
            if definition.client_id is None and client_id is not None:
                definition = replace(definition, client_id=client_id)
            input_payload = params.get("input", {})
            if not isinstance(input_payload, dict):
                raise ValueError("scheduled agent input must be an object")
            if not self._agent_service.execution_window_open(definition):
                self._store.add_audit_event(
                    "scheduled_job.window_closed",
                    str(scheduled_job.id),
                    f"agent {scheduled_job.agent_id} execution window is closed",
                    client_id=client_id,
                )
                return
        except Exception as exc:
            self._store.add_audit_event(
                "scheduled_job.trigger_failed",
                str(scheduled_job.id),
                f"agent {scheduled_job.agent_id} failed: {exc}",
                client_id=client_id,
            )
            raise
        try:
            result = self._agent_service.run(
                definition,
                entity_id=scheduled_job.entity_id,
                actor="scheduler",
                input_payload=input_payload,
            )
        except Exception as exc:
            self._store.add_audit_event(
                "scheduled_job.trigger_failed",
                str(scheduled_job.id),
                f"agent {scheduled_job.agent_id} failed: {exc}",
                client_id=client_id,
            )
            raise
        self._store.add_audit_event(
            "scheduled_job.triggered",
            str(scheduled_job.id),
            f"agent {scheduled_job.agent_id} created agent run {result.run_id} ({result.status})",
            client_id=client_id,
        )
        if result.status == "completed":
            self._dispatch_completion(
                run_id=result.run_id,
                ticket_id=scheduled_job.entity_id,
                template_id=scheduled_job.agent_id,
                status=result.status,
                client_id=client_id,
                actor="scheduler",
            )

    def _dispatch_completion(
        self,
        *,
        run_id: int | None = None,
        ticket_id: str | None = None,
        template_id: str | None = None,
        status: str,
        client_id: str | None = None,
        actor: str,
    ) -> None:
        if self._event_dispatcher is None or status != "completed":
            return
        if not isinstance(run_id, int) or not isinstance(ticket_id, str) or not isinstance(template_id, str):
            return
        try:
            result = self._event_dispatcher.dispatch(
                event_type="workflow.completed",
                entity_type="ticket",
                entity_id=ticket_id,
                payload={
                    "workflow_run_id": str(run_id),
                    "workflow_template_id": template_id,
                    "status": "completed",
                },
                idempotency_key=f"workflow-completed:{run_id}",
                client_id=client_id,
                actor=actor,
            )
            self._store.add_audit_event(
                "workflow.completion_dispatched",
                str(run_id),
                f"workflow completion dispatched to {len(result.matched_agent_ids)} agent(s)",
                client_id=client_id,
            )
        except Exception as exc:  # noqa: BLE001 - completion must not undo a finished run
            self._store.add_audit_event(
                "workflow.completion_dispatch_failed",
                str(run_id),
                redact_text(f"workflow completion dispatch failed: {exc}"),
                client_id=client_id,
            )

    def _register_live_job(self, scheduled_job: ScheduledJob) -> None:
        if self._scheduler is None or scheduled_job.id is None:
            return
        if (
            scheduled_job.schedule_type == "once"
            and _parse_run_at(scheduled_job.run_at or "") <= datetime.now(UTC)
        ):
            return
        trigger = _schedule_trigger(scheduled_job)
        self._scheduler.add_job(
            self._build_job_callable(scheduled_job),
            trigger=trigger,
            id=self._job_identity(scheduled_job.id),
            replace_existing=True,
            coalesce=True,
        )
        if scheduled_job.paused:
            self._scheduler.pause_job(self._job_identity(scheduled_job.id))

    def _build_job_callable(self, scheduled_job: ScheduledJob) -> Any:
        async def run_job() -> None:
            await self._run_job(scheduled_job)

        return run_job

    def _retry_due_event_deliveries(self) -> None:
        if self._event_dispatcher is None:
            return
        self._event_dispatcher.retry_due()

    def _with_runtime_state(self, scheduled_job: ScheduledJob) -> ScheduledJob:
        if scheduled_job.id is None or self._scheduler is None:
            return scheduled_job
        live_job = self._scheduler.get_job(self._job_identity(scheduled_job.id))
        if live_job is None:
            return scheduled_job
        next_run_at = live_job.next_run_time.isoformat() if live_job.next_run_time is not None else None
        return replace(scheduled_job, next_run_at=next_run_at)

    @staticmethod
    def _job_identity(job_id: int) -> str:
        return f"scheduled-job:{job_id}"

    @staticmethod
    def _retry_job_identity() -> str:
        return "event-delivery-retry-worker"


def validate_cron_expression(cron: str, timezone: str = "UTC") -> None:
    try:
        CronTrigger.from_crontab(cron, timezone=ZoneInfo(validate_timezone(timezone)))
    except ValueError as exc:
        raise ValueError("invalid cron expression; expected standard 5-field crontab syntax") from exc


def validate_schedule(
    schedule_type: str,
    cron: str,
    interval_seconds: int | None,
    run_at: str | None,
    timezone: str = "UTC",
) -> str:
    normalized_timezone = validate_timezone(timezone)
    if schedule_type == "cron":
        validate_cron_expression(cron, normalized_timezone)
        if interval_seconds is not None or run_at is not None:
            raise ValueError("cron schedules cannot include interval_seconds or run_at")
        return normalized_timezone
    if schedule_type == "interval":
        if not isinstance(interval_seconds, int) or isinstance(interval_seconds, bool):
            raise ValueError("interval schedules require interval_seconds")
        if interval_seconds < 1 or interval_seconds > 31_536_000:
            raise ValueError("interval_seconds must be between 1 and 31536000")
        if cron or run_at is not None:
            raise ValueError("interval schedules cannot include cron or run_at")
        return normalized_timezone
    if schedule_type == "once":
        if not isinstance(run_at, str) or not run_at.strip():
            raise ValueError("one-time schedules require run_at")
        if cron or interval_seconds is not None:
            raise ValueError("one-time schedules cannot include cron or interval_seconds")
        parsed = _parse_run_at(run_at)
        if parsed <= datetime.now(UTC):
            raise ValueError("run_at must be in the future")
        return normalized_timezone
    raise ValueError("schedule_type must be cron, interval, or once")


def validate_timezone(timezone: str) -> str:
    if not isinstance(timezone, str) or not timezone.strip():
        raise ValueError("timezone must be a valid IANA timezone")
    normalized_timezone = timezone.strip()
    try:
        ZoneInfo(normalized_timezone)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError("timezone must be a valid IANA timezone") from exc
    return normalized_timezone


def _schedule_trigger(scheduled_job: ScheduledJob) -> Any:
    if scheduled_job.schedule_type == "interval":
        return IntervalTrigger(
            seconds=scheduled_job.interval_seconds or 0,
            timezone=ZoneInfo(validate_timezone(scheduled_job.timezone)),
        )
    if scheduled_job.schedule_type == "once":
        return DateTrigger(
            run_date=_parse_run_at(scheduled_job.run_at or ""),
            timezone=ZoneInfo(validate_timezone(scheduled_job.timezone)),
        )
    return CronTrigger.from_crontab(
        scheduled_job.cron,
        timezone=ZoneInfo(validate_timezone(scheduled_job.timezone)),
    )


def _parse_run_at(run_at: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(run_at)
    except ValueError as exc:
        raise ValueError("run_at must be a valid ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError("run_at must include a timezone")
    return parsed.astimezone(UTC)


def _validate_schedule_target(
    job_kind: str,
    template_id: str,
    agent_id: str | None,
    entity_id: str | None,
) -> None:
    if job_kind == "workflow":
        if not template_id or agent_id is not None or entity_id is not None:
            raise ValueError("workflow schedules require template_id only")
        return
    if job_kind == "agent":
        if template_id or not _string_or_none(agent_id) or not _string_or_none(entity_id):
            raise ValueError("agent schedules require agent_id and entity_id")
        return
    if job_kind == "report":
        if template_id not in _SCHEDULED_REPORT_TYPES or agent_id is not None or entity_id is not None:
            raise ValueError("report schedules require a supported report type only")
        return
    raise ValueError("unsupported scheduled job kind")


_SCHEDULED_REPORT_TYPES = {
    ReportType.QBR.value,
    ReportType.AUTOMATION_OPPORTUNITY.value,
}


def _scheduled_report_type(value: str) -> ReportType:
    if value not in _SCHEDULED_REPORT_TYPES:
        raise ValueError("scheduled report type must be qbr or automation_opportunity")
    return ReportType(value)


def _scheduled_report_period(params: dict[str, object], *, timezone: str) -> tuple[str, str]:
    period_days = params.get("period_days")
    if period_days is not None:
        if isinstance(period_days, bool) or not isinstance(period_days, int) or not 1 <= period_days <= 366:
            raise ValueError("period_days must be an integer between 1 and 366")
        local_today = datetime.now(ZoneInfo(validate_timezone(timezone))).date()
        return (
            (local_today - timedelta(days=period_days - 1)).isoformat(),
            local_today.isoformat(),
        )
    period_start = params.get("period_start")
    period_end = params.get("period_end")
    if not isinstance(period_start, str) or not isinstance(period_end, str):
        raise ValueError("scheduled report params require period_days or period_start and period_end")
    try:
        start = date.fromisoformat(period_start)
        end = date.fromisoformat(period_end)
    except ValueError as exc:
        raise ValueError("scheduled report period must use ISO dates") from exc
    if end < start:
        raise ValueError("scheduled report period_end must be on or after period_start")
    if (end - start).days > 365:
        raise ValueError("scheduled report period cannot exceed 366 days")
    return start.isoformat(), end.isoformat()


def validate_scheduled_report_params(params: dict[str, object], *, timezone: str = "UTC") -> None:
    """Validate the bounded scope and period required by a scheduled report."""
    client_id = params.get("client_id")
    if not isinstance(client_id, str) or not client_id.strip():
        raise ValueError("scheduled report params must include client_id")
    _scheduled_report_period(params, timezone=timezone)


def _safe_json_object(payload_json: str) -> dict[str, object]:
    payload = json.loads(payload_json)
    return payload if isinstance(payload, dict) else {}


def _required_ticket_id(params: dict[str, object]) -> str:
    ticket_id = params.get("ticket_id")
    if not isinstance(ticket_id, str) or not ticket_id.strip():
        raise ValueError("scheduled job params must include ticket_id")
    return ticket_id


def _string_or_none(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value
    return None
