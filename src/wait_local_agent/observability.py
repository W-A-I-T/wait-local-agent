"""Execution observability: per-run step logs, artifacts, and analytics.

Recording is best-effort by contract: a recorder failure is logged and
swallowed so it can never change the outcome of a workflow or smart-action
run. Step payloads pass through the existing redaction helpers before
persistence, and analytics time-saved figures are estimates derived from
smart-action manifests, never measurements.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TypedDict

from wait_local_agent.models import utc_now
from wait_local_agent.reports.renderers import redact_text, redact_value
from wait_local_agent.store import Store

LOGGER = logging.getLogger(__name__)

# Step input/output payloads are redacted and then capped at this many bytes
# of serialized JSON. Larger payloads are replaced by a truncation marker
# object carrying the digest of the full redacted payload plus a preview.
EXECUTION_STEP_PAYLOAD_CAP_BYTES = 8192

EXECUTION_SUCCESS_STATUSES = frozenset({"success", "completed"})

ESTIMATED_MINUTES_SAVED_DERIVATION = (
    "Sum of the per-action estimated_minutes_saved declared in smart-action "
    "manifests for successful smart-action executions in the range. This is "
    "derived from manifest estimates, not measured wall-clock time."
)


@dataclass(frozen=True)
class StepRecord:
    kind: str
    name: str
    status: str
    input: object = None
    output: object = None
    error_detail: str = ""
    started_at: str = ""
    finished_at: str = ""


@dataclass(frozen=True)
class ArtifactRecord:
    name: str
    media_type: str
    content: bytes
    step_ordinal: int | None = None


class _DailyBucket(TypedDict):
    date: str
    count: int
    succeeded: int
    not_succeeded: int


class ExecutionRecorder:
    """Persist execution runs, ordered steps, and content-addressed artifacts."""

    def __init__(self, store: Store, artifacts_dir: Path | None = None) -> None:
        self.store = store
        self.artifacts_dir = artifacts_dir or store.path.parent / "execution_artifacts"

    def record_execution(
        self,
        *,
        run_kind: Literal["workflow", "smart_action"],
        source_run_id: int | None,
        actor: str,
        status: str,
        trigger_source: str,
        client_id: str | None = None,
        steps: tuple[StepRecord, ...] = (),
        artifacts: tuple[ArtifactRecord, ...] = (),
    ) -> int | None:
        """Record an execution; return the execution run id or None on failure.

        Recording never changes run outcomes: any failure is logged and
        swallowed, returning None.
        """
        try:
            return self._record_execution(
                run_kind=run_kind,
                source_run_id=source_run_id,
                actor=actor,
                status=status,
                trigger_source=trigger_source,
                client_id=client_id,
                steps=steps,
                artifacts=artifacts,
            )
        except Exception:  # noqa: BLE001 - recording must never fail a run
            LOGGER.exception("execution recording failed; run outcome unchanged")
            return None

    def _record_execution(
        self,
        *,
        run_kind: Literal["workflow", "smart_action"],
        source_run_id: int | None,
        actor: str,
        status: str,
        trigger_source: str,
        client_id: str | None,
        steps: tuple[StepRecord, ...],
        artifacts: tuple[ArtifactRecord, ...],
    ) -> int:
        now = utc_now()
        existing = (
            self.store.find_execution_run(run_kind, source_run_id)
            if source_run_id is not None
            else None
        )
        if existing is not None and existing.id is not None:
            run = self.store.update_execution_run(existing.id, status, now)
            ordinal = self.store.next_execution_step_ordinal(existing.id)
        else:
            run = self.store.create_execution_run(
                run_kind,
                source_run_id,
                actor.strip() or "system",
                status,
                now,
                now,
                trigger_source,
                client_id=client_id,
            )
            ordinal = 0
        if run.id is None:
            raise RuntimeError("execution run was not persisted")
        for step in steps:
            self._record_step(run.id, ordinal, step, now)
            ordinal += 1
        for artifact in artifacts:
            self._record_artifact(run.id, artifact)
        return run.id

    def _record_step(
        self, execution_run_id: int, ordinal: int, step: StepRecord, now: str
    ) -> None:
        input_json, input_digest = _capped_payload_json(step.input)
        output_json, output_digest = _capped_payload_json(step.output)
        self.store.add_execution_step(
            execution_run_id,
            ordinal,
            step.kind,
            step.name,
            step.status,
            step.started_at or now,
            step.finished_at or now,
            input_digest,
            output_digest,
            input_json,
            output_json,
            redact_text(step.error_detail),
        )

    def _record_artifact(self, execution_run_id: int, artifact: ArtifactRecord) -> None:
        digest = hashlib.sha256(artifact.content).hexdigest()
        path = self.artifacts_dir / digest[:2] / digest
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_bytes(artifact.content)
        self.store.add_execution_artifact(
            execution_run_id,
            artifact.step_ordinal,
            artifact.name,
            artifact.media_type,
            len(artifact.content),
            digest,
            str(path),
        )


def _capped_payload_json(value: object) -> tuple[str, str]:
    """Redact then serialize a payload; cap it, keeping digest and marker.

    Returns (stored_json, digest). When the redacted payload exceeds
    EXECUTION_STEP_PAYLOAD_CAP_BYTES, the stored JSON is a truncation marker
    carrying the digest of the full redacted payload and a bounded preview.
    """
    redacted = redact_value(value)
    text = json.dumps(redacted, sort_keys=True, separators=(",", ":"), default=str)
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    if len(text.encode("utf-8")) <= EXECUTION_STEP_PAYLOAD_CAP_BYTES:
        return text, digest
    marker = {
        "truncated": True,
        "sha256": digest,
        "preview": text[:EXECUTION_STEP_PAYLOAD_CAP_BYTES],
    }
    return json.dumps(marker, sort_keys=True, separators=(",", ":")), digest


def build_analytics_summary(
    store: Store,
    estimates: dict[str, int],
    *,
    started_from: str | None = None,
    started_to: str | None = None,
    client_id: str | None = None,
) -> dict[str, object]:
    """Aggregate execution analytics from the store at read time.

    estimated_minutes_saved is an estimate derived from smart-action
    manifests; it is labeled as such and never presented as a measurement.
    Failure states are reported, never omitted.
    """
    daily_rows = store.execution_daily_status_counts(started_from, started_to, client_id)
    buckets: dict[str, _DailyBucket] = {}
    status_counts: dict[str, int] = {}
    for day, status, count in daily_rows:
        bucket = buckets.setdefault(
            day, {"date": day, "count": 0, "succeeded": 0, "not_succeeded": 0}
        )
        bucket["count"] += count
        if status in EXECUTION_SUCCESS_STATUSES:
            bucket["succeeded"] += count
        else:
            bucket["not_succeeded"] += count
        status_counts[status] = status_counts.get(status, 0) + count
    total = sum(status_counts.values())
    succeeded = sum(
        count for status, count in status_counts.items() if status in EXECUTION_SUCCESS_STATUSES
    )
    failures_by_status = [
        {"status": status, "count": count}
        for status, count in sorted(status_counts.items())
        if status not in EXECUTION_SUCCESS_STATUSES
    ]
    success_counts = store.execution_smart_action_success_counts(
        started_from, started_to, client_id
    )
    minutes = sum(estimates.get(action_id, 0) * count for action_id, count in success_counts)
    return {
        "range": {"from": started_from, "to": started_to},
        "client_id": client_id,
        "executions_over_time": [buckets[day] for day in sorted(buckets)],
        "success_rate": {
            "total": total,
            "succeeded": succeeded,
            "rate": (succeeded / total) if total else 0.0,
        },
        "failures_by_status": failures_by_status,
        "estimated_minutes_saved": {
            "minutes": minutes,
            "estimate": True,
            "derivation": ESTIMATED_MINUTES_SAVED_DERIVATION,
        },
    }
