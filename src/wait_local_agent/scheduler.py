from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from wait_local_agent.models import ScheduledJob
from wait_local_agent.store import Store
from wait_local_agent.workflows import run_workflow_template


class SchedulerManager:
    def __init__(self, store: Store, *, enabled: bool = True) -> None:
        self._store = store
        self._enabled = enabled
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
    ) -> ScheduledJob:
        validate_cron_expression(cron)
        client_id = _string_or_none(params.get("client_id"))
        scheduled_job = self._store.create_scheduled_job(
            template_id,
            cron,
            params,
            client_id=client_id,
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

    async def _run_job(self, scheduled_job: ScheduledJob) -> None:
        params = _safe_json_object(scheduled_job.params_json)
        ticket_id = _required_ticket_id(params)
        client_id = _string_or_none(params.get("client_id")) or scheduled_job.client_id
        try:
            run = run_workflow_template(
                self._store,
                scheduled_job.template_id,
                ticket_id,
                client_id=client_id,
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

    def _register_live_job(self, scheduled_job: ScheduledJob) -> None:
        if self._scheduler is None or scheduled_job.id is None:
            return
        trigger = CronTrigger.from_crontab(scheduled_job.cron, timezone=UTC)
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


def validate_cron_expression(cron: str) -> None:
    try:
        CronTrigger.from_crontab(cron, timezone=UTC)
    except ValueError as exc:
        raise ValueError("invalid cron expression; expected standard 5-field crontab syntax") from exc


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
