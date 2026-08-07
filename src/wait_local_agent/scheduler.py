from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger

from wait_local_agent.agents import AgentService
from wait_local_agent.models import ScheduledJob
from wait_local_agent.store import Store
from wait_local_agent.workflows import run_workflow_template


class SchedulerManager:
    def __init__(
        self,
        store: Store,
        *,
        enabled: bool = True,
        agent_service: AgentService | None = None,
    ) -> None:
        self._store = store
        self._enabled = enabled
        self._agent_service = agent_service
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
        validate_schedule(schedule_type, cron, interval_seconds, run_at, timezone)
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
            timezone=timezone,
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

    def remove(self, job_id: int) -> ScheduledJob:
        scheduled_job = self._store.delete_scheduled_job(job_id)
        if self._scheduler is not None:
            live_job = self._scheduler.get_job(self._job_identity(job_id))
            if live_job is not None:
                self._scheduler.remove_job(self._job_identity(job_id))
        return self._with_runtime_state(scheduled_job)

    def reschedule(
        self,
        job_id: int,
        *,
        schedule_type: str,
        cron: str,
        interval_seconds: int | None,
        run_at: str | None,
        timezone: str = "UTC",
    ) -> ScheduledJob:
        validate_schedule(schedule_type, cron, interval_seconds, run_at, timezone)
        scheduled_job = self._store.update_scheduled_job_schedule(
            job_id,
            schedule_type=schedule_type,
            cron=cron,
            interval_seconds=interval_seconds,
            run_at=run_at,
            timezone=timezone,
        )
        if self._scheduler is not None:
            self._register_live_job(scheduled_job)
        return self._with_runtime_state(scheduled_job)

    async def _run_job(self, scheduled_job: ScheduledJob) -> None:
        params = _safe_json_object(scheduled_job.params_json)
        client_id = _string_or_none(params.get("client_id")) or scheduled_job.client_id
        if scheduled_job.job_kind == "agent":
            await self._run_agent_job(scheduled_job, params, client_id)
            return
        ticket_id = _required_ticket_id(params)
        try:
            run = run_workflow_template(
                self._store,
                scheduled_job.template_id,
                ticket_id,
                client_id=client_id,
                actor="scheduler",
                trigger_source="scheduler",
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

    def _register_live_job(self, scheduled_job: ScheduledJob) -> None:
        if self._scheduler is None or scheduled_job.id is None:
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


def validate_cron_expression(cron: str, timezone: str = "UTC") -> None:
    try:
        CronTrigger.from_crontab(cron, timezone=_timezone(timezone))
    except ValueError as exc:
        raise ValueError("invalid cron expression; expected standard 5-field crontab syntax") from exc


def validate_schedule(
    schedule_type: str,
    cron: str,
    interval_seconds: int | None,
    run_at: str | None,
    timezone: str = "UTC",
) -> None:
    _timezone(timezone)
    if schedule_type == "cron":
        validate_cron_expression(cron, timezone)
        if interval_seconds is not None or run_at is not None:
            raise ValueError("cron schedules cannot include interval_seconds or run_at")
        return
    if schedule_type == "interval":
        if not isinstance(interval_seconds, int) or isinstance(interval_seconds, bool):
            raise ValueError("interval schedules require interval_seconds")
        if interval_seconds < 1 or interval_seconds > 31_536_000:
            raise ValueError("interval_seconds must be between 1 and 31536000")
        if cron or run_at is not None:
            raise ValueError("interval schedules cannot include cron or run_at")
        return
    if schedule_type == "once":
        if not isinstance(run_at, str) or not run_at.strip():
            raise ValueError("one-time schedules require run_at")
        if cron or interval_seconds is not None:
            raise ValueError("one-time schedules cannot include cron or interval_seconds")
        parsed = _parse_run_at(run_at)
        if parsed <= datetime.now(UTC):
            raise ValueError("run_at must be in the future")
        return
    raise ValueError("schedule_type must be cron, interval, or once")


def _schedule_trigger(scheduled_job: ScheduledJob) -> Any:
    timezone = _timezone(scheduled_job.timezone)
    if scheduled_job.schedule_type == "interval":
        return IntervalTrigger(seconds=scheduled_job.interval_seconds or 0, timezone=timezone)
    if scheduled_job.schedule_type == "once":
        return DateTrigger(run_date=_parse_run_at(scheduled_job.run_at or ""), timezone=timezone)
    return CronTrigger.from_crontab(scheduled_job.cron, timezone=timezone)


def _timezone(value: str) -> ZoneInfo:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("timezone must be a valid IANA timezone")
    try:
        return ZoneInfo(value)
    except ZoneInfoNotFoundError as exc:
        raise ValueError("timezone must be a valid IANA timezone") from exc


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
    raise ValueError("unsupported scheduled job kind")


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
