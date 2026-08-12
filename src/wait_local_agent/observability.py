"""Execution observability: per-run step logs, artifacts, and analytics.

Recording is best-effort by contract: a recorder failure is logged and
swallowed so it can never change the outcome of a workflow or smart-action
run. Step payloads pass through the existing redaction helpers before
persistence, and analytics time-saved figures are estimates derived from
smart-action manifests, never measurements.
"""

from __future__ import annotations

import errno
import hashlib
import json
import logging
import os
import stat
import threading
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TypedDict, cast

from wait_local_agent.models import utc_now
from wait_local_agent.reports.renderers import redact_text, redact_value
from wait_local_agent.store import Store

LOGGER = logging.getLogger(__name__)

# Step input/output payloads are redacted and then capped at this many bytes
# of serialized JSON. Larger payloads are replaced by a truncation marker
# object carrying the digest of the full redacted payload plus a preview.
EXECUTION_STEP_PAYLOAD_CAP_BYTES = 8192
EXECUTION_ARTIFACT_MAX_BYTES = 4 * 1024 * 1024
EXECUTION_RECORD_TIMEOUT_SECONDS = 0.5

EXECUTION_SUCCESS_STATUSES = frozenset({"success", "completed"})

ESTIMATED_MINUTES_SAVED_DERIVATION = (
    "Sum of the per-action estimated_minutes_saved declared in smart-action "
    "manifests for successful smart-action executions in the range. This is "
    "derived from manifest estimates, not measured wall-clock time."
)

APPROVAL_RATE_DERIVATION = (
    "Approved approval requests divided by decided approval requests in the "
    "requested date range; pending requests are reported separately."
)

TICKET_METRICS_DERIVATION = (
    "Distinct tickets referenced by workflow/agent source records or explicit "
    "ticket_id fields in redacted execution-step inputs. Resolved means the "
    "current ticket status is resolved or closed; historical resolution time "
    "is not inferred."
)

TICKET_LIFECYCLE_DERIVATION = (
    "Historical resolution metrics use explicit local ticket status transitions "
    "recorded during ticket ingestion or local end-user actions. Existing tickets "
    "start with a snapshot and do not receive an inferred historical transition."
)

MODEL_COST_DERIVATION = (
    "Configured estimate from redacted provider usage metadata and operator-supplied "
    "input/output rates; WAIT never infers provider pricing or measured savings."
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
        run_kind: Literal["workflow", "smart_action", "agent"],
        source_run_id: int | None,
        actor: str,
        status: str,
        trigger_source: str,
        client_id: str | None = None,
        metadata: dict[str, object] | None = None,
        steps: tuple[StepRecord, ...] = (),
        artifacts: tuple[ArtifactRecord, ...] = (),
    ) -> int | None:
        """Record an execution; return the execution run id or None on failure.

        Recording never changes run outcomes: any failure is logged and
        swallowed, returning None. The bounded worker keeps a slow database or
        filesystem off the workflow/action critical path.
        """
        result: list[int] = []
        failure: list[BaseException] = []

        def record() -> None:
            try:
                execution_run_id = self._record_execution(
                    run_kind=run_kind,
                    source_run_id=source_run_id,
                    actor=actor,
                    status=status,
                    trigger_source=trigger_source,
                    client_id=client_id,
                    metadata=metadata,
                    steps=steps,
                    artifacts=artifacts,
                )
                result.append(execution_run_id)
            except Exception as exc:  # noqa: BLE001 - recording must never fail a run
                failure.append(exc)

        worker = threading.Thread(target=record, name="execution-recorder", daemon=True)
        worker.start()
        worker.join(EXECUTION_RECORD_TIMEOUT_SECONDS)
        if worker.is_alive():
            LOGGER.warning(
                "execution recording exceeded %.2fs; run outcome unchanged",
                EXECUTION_RECORD_TIMEOUT_SECONDS,
            )
            return None
        if failure:
            LOGGER.error("execution recording failed; run outcome unchanged: %s", failure[0])
            return None
        return result[0] if result else None

    def _record_execution(
        self,
        *,
        run_kind: Literal["workflow", "smart_action", "agent"],
        source_run_id: int | None,
        actor: str,
        status: str,
        trigger_source: str,
        client_id: str | None,
        metadata: dict[str, object] | None,
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
                metadata=metadata,
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
        if len(artifact.content) > EXECUTION_ARTIFACT_MAX_BYTES:
            LOGGER.warning(
                "skipping execution artifact larger than %d bytes",
                EXECUTION_ARTIFACT_MAX_BYTES,
            )
            return
        digest = hashlib.sha256(artifact.content).hexdigest()
        root = self._artifact_root()
        path = root / digest[:2] / digest
        if _artifact_dir_fd_supported():
            # Keep the root and every shard component anchored by descriptors.
            # No path-based validation is used between opening a directory and
            # creating or publishing the artifact beneath it.
            root_fd = os.open(root, _artifact_directory_flags())
            try:
                shard_fd = _open_artifact_shard(root_fd, digest[:2])
                try:
                    self._write_artifact_atomically(
                        path, artifact.content, directory_fd=shard_fd
                    )
                finally:
                    os.close(shard_fd)
            finally:
                os.close(root_fd)
        else:
            # Platforms without the required dir_fd APIs retain the previous
            # path-based behavior. Their artifact directory must be trusted.
            if not path.parent.exists():
                path.parent.mkdir(parents=True, exist_ok=True)
            self._assert_artifact_path(path, root)
            if path.is_symlink():
                raise RuntimeError(f"refusing symlink artifact path: {path}")
            if path.exists():
                if not path.is_file() or _sha256_file(path) != digest:
                    raise RuntimeError(f"existing artifact digest mismatch: {path}")
            else:
                self._write_artifact_atomically(path, artifact.content)
        self.store.add_execution_artifact(
            execution_run_id,
            artifact.step_ordinal,
            artifact.name,
            artifact.media_type,
            len(artifact.content),
            digest,
            str(path),
        )

    def _artifact_root(self) -> Path:
        if self.artifacts_dir.is_symlink():
            raise RuntimeError("refusing symlink artifact directory")
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        # Keep symlinks visible until the descriptor-relative open can reject
        # a root that was swapped after the initial check.
        return self.artifacts_dir.absolute()

    @staticmethod
    def _assert_artifact_path(path: Path, root: Path) -> None:
        if not path.resolve().is_relative_to(root):
            raise RuntimeError("artifact path escapes the artifact data directory")
        if path.parent.is_symlink():
            raise RuntimeError("refusing symlink artifact shard directory")

    @staticmethod
    def _write_artifact_atomically(
        path: Path, content: bytes, *, directory_fd: int | None = None
    ) -> None:
        """Write an artifact without replacing a destination file.

        The descriptor-relative path is used on platforms that support all
        required operations. The path-based implementation below is retained
        only as the documented compatibility fallback for other platforms.
        """
        if directory_fd is not None:
            _write_artifact_at_fd(directory_fd, path.name, path, content)
            return
        if _artifact_dir_fd_supported():
            directory_fd = os.open(path.parent, _artifact_directory_flags())
            try:
                _write_artifact_at_fd(directory_fd, path.name, path, content)
            finally:
                os.close(directory_fd)
            return
        _write_artifact_path_based(path, content)


def _artifact_dir_fd_supported() -> bool:
    """Return whether artifact writes can be anchored to directory FDs."""
    required_dir_fd_operations = (os.open, os.mkdir, os.link, os.unlink)
    return bool(
        getattr(os, "O_DIRECTORY", 0)
        and getattr(os, "O_NOFOLLOW", 0)
        and all(operation in os.supports_dir_fd for operation in required_dir_fd_operations)
        and os.link in os.supports_follow_symlinks
    )


def _artifact_directory_flags() -> int:
    return os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW


def _open_artifact_shard(root_fd: int, shard_name: str) -> int:
    try:
        os.mkdir(shard_name, 0o700, dir_fd=root_fd)
    except FileExistsError:
        pass
    return os.open(shard_name, _artifact_directory_flags(), dir_fd=root_fd)


def _write_artifact_at_fd(
    directory_fd: int, artifact_name: str, path: Path, content: bytes
) -> None:
    temp_name = f".{artifact_name}.{uuid.uuid4().hex}.tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    file_descriptor = os.open(temp_name, flags, 0o600, dir_fd=directory_fd)
    try:
        with os.fdopen(file_descriptor, "wb") as handle:
            file_descriptor = -1
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            # link() fails if the destination exists; unlike rename(), it can
            # never silently replace a destination that raced this write.
            os.link(
                temp_name,
                artifact_name,
                src_dir_fd=directory_fd,
                dst_dir_fd=directory_fd,
                follow_symlinks=False,
            )
        except FileExistsError:
            _verify_existing_artifact_at_fd(directory_fd, artifact_name, path)
        else:
            os.unlink(temp_name, dir_fd=directory_fd)
    finally:
        if file_descriptor >= 0:
            os.close(file_descriptor)
        try:
            os.unlink(temp_name, dir_fd=directory_fd)
        except FileNotFoundError:
            pass


def _verify_existing_artifact_at_fd(directory_fd: int, artifact_name: str, path: Path) -> None:
    flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_NONBLOCK", 0)
    try:
        file_descriptor = os.open(artifact_name, flags, dir_fd=directory_fd)
    except OSError as exc:
        if getattr(exc, "errno", None) == getattr(errno, "ELOOP", 40):
            raise RuntimeError(f"refusing symlink artifact path: {path}") from exc
        raise RuntimeError(f"existing artifact digest mismatch: {path}") from exc
    try:
        if not stat.S_ISREG(os.fstat(file_descriptor).st_mode):
            raise RuntimeError(f"existing artifact digest mismatch: {path}")
        if _sha256_fd(file_descriptor) != path.name:
            raise RuntimeError(f"existing artifact digest mismatch: {path}")
    finally:
        os.close(file_descriptor)


def _sha256_fd(file_descriptor: int) -> str:
    digest = hashlib.sha256()
    os.lseek(file_descriptor, 0, os.SEEK_SET)
    for chunk in iter(lambda: os.read(file_descriptor, 1024 * 1024), b""):
        digest.update(chunk)
    return digest.hexdigest()


def _write_artifact_path_based(path: Path, content: bytes) -> None:
    """Compatibility fallback for platforms without descriptor-relative APIs."""
    temp_path = path.parent / f".{path.name}.{uuid.uuid4().hex}.tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    file_descriptor = os.open(temp_path, flags, 0o600)
    try:
        with os.fdopen(file_descriptor, "wb") as handle:
            file_descriptor = -1
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.rename(temp_path, path)
        except FileExistsError:
            if path.is_symlink() or not path.is_file() or _sha256_file(path) != path.name:
                raise RuntimeError(f"existing artifact digest mismatch: {path}") from None
            temp_path.unlink(missing_ok=True)
    finally:
        if file_descriptor >= 0:
            os.close(file_descriptor)
        temp_path.unlink(missing_ok=True)


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
    activity_breakdown = [
        {
            "run_kind": run_kind,
            "trigger_source": trigger_source,
            "status": status,
            "count": count,
        }
        for run_kind, trigger_source, status, count in store.execution_activity_counts(
            started_from, started_to, client_id
        )
    ]
    approval_status_counts = dict(
        store.approval_activity_counts(started_from, started_to, client_id)
    )
    approved = approval_status_counts.get("approved", 0)
    rejected = approval_status_counts.get("rejected", 0)
    decided = approved + rejected
    ticket_activity = store.execution_ticket_activity(started_from, started_to, client_id)
    lifecycle = store.ticket_lifecycle_metrics(started_from, started_to, client_id)
    resolved_tickets = sum(
        1 for _, status in ticket_activity if status.strip().lower() in {"resolved", "closed"}
    )
    workflow_buckets: dict[tuple[str, str], dict[str, object]] = {}
    for run_kind, workflow_id, status, count in store.execution_workflow_activity(
        started_from, started_to, client_id
    ):
        workflow_bucket = workflow_buckets.setdefault(
            (run_kind, workflow_id),
            {"run_kind": run_kind, "workflow_id": workflow_id, "total": 0, "statuses": {}},
        )
        workflow_bucket["total"] = cast(int, workflow_bucket["total"]) + count
        statuses = cast(dict[str, int], workflow_bucket["statuses"])
        statuses[status] = statuses.get(status, 0) + count
    activity_by_workflow: list[dict[str, object]] = []
    for workflow_bucket in workflow_buckets.values():
        statuses = cast(dict[str, int], workflow_bucket.pop("statuses"))
        succeeded_for_bucket = sum(
            count for status, count in statuses.items() if status in EXECUTION_SUCCESS_STATUSES
        )
        activity_by_workflow.append(
            {
                **workflow_bucket,
                "succeeded": succeeded_for_bucket,
                "status_counts": [
                    {"status": status, "count": count}
                    for status, count in sorted(statuses.items())
                ],
            }
        )
    activity_by_workflow.sort(key=lambda item: (str(item["run_kind"]), str(item["workflow_id"])))
    model_usage = _model_usage_summary(
        store.list_execution_runs(
            client_id,
            started_from=started_from,
            started_to=started_to,
        )
    )
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
        "activity_breakdown": activity_breakdown,
        "approval_rate": {
            "requested": sum(approval_status_counts.values()),
            "decided": decided,
            "approved": approved,
            "rejected": rejected,
            "pending": approval_status_counts.get("pending", 0),
            "rate": (approved / decided) if decided else 0.0,
            "derivation": APPROVAL_RATE_DERIVATION,
        },
        "ticket_metrics": {
            "touched": len(ticket_activity),
            "resolved": resolved_tickets,
            "resolution_rate": (resolved_tickets / len(ticket_activity)) if ticket_activity else 0.0,
            "derivation": TICKET_METRICS_DERIVATION,
            "historical_resolution": {
                **lifecycle,
                "derivation": TICKET_LIFECYCLE_DERIVATION,
            },
        },
        "activity_by_workflow": activity_by_workflow,
        "estimated_minutes_saved": {
            "minutes": minutes,
            "estimate": True,
            "derivation": ESTIMATED_MINUTES_SAVED_DERIVATION,
        },
        "model_usage": model_usage,
    }


def _model_usage_summary(runs: Sequence[object]) -> dict[str, object]:
    input_tokens = 0
    output_tokens = 0
    runs_with_usage = 0
    runs_with_cost = 0
    estimated_cost_usd = 0.0
    for run in runs:
        try:
            metadata = json.loads(str(getattr(run, "metadata_json", "{}")))
        except (TypeError, ValueError):
            continue
        if not isinstance(metadata, dict):
            continue
        if metadata.get("usage_status") == "reported":
            runs_with_usage += 1
            input_value = metadata.get("input_tokens")
            output_value = metadata.get("output_tokens")
            if isinstance(input_value, int) and input_value >= 0:
                input_tokens += input_value
            if isinstance(output_value, int) and output_value >= 0:
                output_tokens += output_value
        if metadata.get("cost_status") != "configured_estimate":
            continue
        cost = metadata.get("cost_usd")
        if isinstance(cost, (int, float)) and not isinstance(cost, bool) and cost >= 0:
            runs_with_cost += 1
            estimated_cost_usd += float(cost)
    return {
        "runs_with_usage": runs_with_usage,
        "runs_with_cost": runs_with_cost,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "estimated_cost_usd": round(estimated_cost_usd, 8),
        "estimate": True,
        "derivation": MODEL_COST_DERIVATION,
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
