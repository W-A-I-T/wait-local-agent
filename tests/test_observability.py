from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any, cast

import pytest

import wait_local_agent.observability as observability
from wait_local_agent.models import utc_now
from wait_local_agent.observability import (
    EXECUTION_STEP_PAYLOAD_CAP_BYTES,
    ArtifactRecord,
    ExecutionRecorder,
    StepRecord,
    _artifact_dir_fd_supported,
    _capped_payload_json,
    _verify_existing_artifact_at_fd,
    build_analytics_summary,
)
from wait_local_agent.rbac import Role
from wait_local_agent.smart_actions import SmartActionService
from wait_local_agent.store import Store
from wait_local_agent.workflows import run_workflow_template


def _seed_tickets(store: Store) -> None:
    store.ingest_ticket_file(Path("examples/sample_tickets/tickets.json"))


def test_fresh_database_has_execution_tables(settings) -> None:
    store = Store(settings.data_path)
    with store._connect() as connection:  # noqa: SLF001
        tables = {
            str(row["name"])
            for row in connection.execute(
                "select name from sqlite_master where type = 'table'"
            ).fetchall()
        }
    assert {"execution_runs", "execution_steps", "execution_artifacts"} <= tables


def test_preexisting_database_migrates_execution_tables(settings, tmp_path) -> None:
    legacy_path = tmp_path / "legacy.db"
    connection = sqlite3.connect(legacy_path)
    connection.execute(
        "create table tickets (id text primary key, client text not null, subject text not null,"
        " body text not null, priority text not null, status text not null)"
    )
    connection.commit()
    connection.close()

    store = Store(legacy_path)
    run = store.create_execution_run(
        "workflow",
        1,
        "tester",
        "completed",
        utc_now(),
        utc_now(),
        "test",
        client_id="acme",
    )
    assert run.id is not None
    assert store.get_execution_run(run.id) is not None


def test_older_execution_runs_shape_gets_missing_columns(settings, tmp_path) -> None:
    legacy_path = tmp_path / "older-execution-runs.db"
    connection = sqlite3.connect(legacy_path)
    connection.execute(
        "create table execution_runs (id integer primary key autoincrement, run_kind text)"
    )
    connection.commit()
    connection.close()

    store = Store(legacy_path)
    run = store.create_execution_run(
        "smart_action",
        7,
        "tester",
        "failed",
        utc_now(),
        utc_now(),
        "test",
        client_id="acme",
    )

    assert run.client_id == "acme"
    assert run.trigger_source == "test"

    with store._connect() as connection:  # noqa: SLF001
        columns = {str(row["name"]) for row in connection.execute("pragma table_info(execution_runs)")}
    assert {"source_run_id", "actor", "status", "started_at", "finished_at", "client_id", "trigger_source"} <= columns


def test_older_execution_step_and_artifact_shapes_get_upgraded(tmp_path: Path) -> None:
    legacy_path = tmp_path / "older-execution-tables.db"
    with sqlite3.connect(legacy_path) as connection:
        connection.executescript(
            """
            create table execution_steps (id integer primary key autoincrement);
            create table execution_artifacts (id integer primary key autoincrement);
            """
        )

    store = Store(legacy_path)
    run = store.create_execution_run(
        "workflow", 1, "tester", "completed", utc_now(), utc_now(), "migration"
    )
    assert run.id is not None
    step = store.add_execution_step(
        run.id, 0, "workflow.template", "test", "completed", utc_now(), utc_now(),
        "input", "output", "{}", "{}"
    )
    artifact = store.add_execution_artifact(
        run.id, step.ordinal, "evidence.json", "application/json", 2, "ab", "/tmp/evidence"
    )
    assert store.list_execution_steps(run.id)[0].name == "test"
    assert store.list_execution_artifacts(run.id)[0].id == artifact.id


def test_workflow_run_produces_execution_run_with_ordered_steps(settings) -> None:
    store = Store(settings.data_path)
    _seed_tickets(store)

    run = run_workflow_template(store, "ticket-triage", "TCK-1001", actor="tech", trigger_source="test")

    executions = store.list_execution_runs(run_kind="workflow")
    assert len(executions) == 1
    execution = executions[0]
    assert execution.source_run_id == run.id
    assert execution.status == "completed"
    assert execution.actor == "tech"
    assert execution.trigger_source == "test"
    steps = store.list_execution_steps(execution.id or 0)
    assert [step.ordinal for step in steps] == [0]
    assert steps[0].kind == "workflow.template"
    assert steps[0].name == "ticket-triage"
    payload = json.loads(steps[0].input_json)
    assert payload == {"template_id": "ticket-triage", "ticket_id": "TCK-1001"}


def test_smart_action_run_produces_execution_run_with_evidence_artifact(settings) -> None:
    store = Store(settings.data_path)
    _seed_tickets(store)
    service = SmartActionService(store, settings)

    result = service.invoke("ticket-triage", {"ticket_id": "TCK-1001"}, "tech")

    assert result.status == "success"
    executions = store.list_execution_runs(run_kind="smart_action")
    assert len(executions) == 1
    execution = executions[0]
    assert execution.source_run_id == result.run_id
    assert execution.status == "success"
    steps = store.list_execution_steps(execution.id or 0)
    assert [step.ordinal for step in steps] == [0]
    assert steps[0].kind == "smart_action.invoke"
    artifacts = store.list_execution_artifacts(execution.id or 0)
    assert len(artifacts) == 1
    artifact = artifacts[0]
    assert artifact.name == "evidence.json"
    content = Path(artifact.storage_path).read_bytes()
    assert hashlib.sha256(content).hexdigest() == artifact.sha256
    assert artifact.byte_size == len(content)


def test_approval_completion_appends_step_to_existing_execution(settings) -> None:
    store = Store(settings.data_path)
    _seed_tickets(store)
    service = SmartActionService(store, settings)

    pending = service.invoke(
        "dispatch-suggestion",
        {"ticket_id": "TCK-1001", "technicians": [{"id": "tech", "workload": 1}]},
        "requester",
    )

    assert pending.status == "pending_approval"
    assert pending.approval_id is not None
    approval = service.update_approval(
        pending.approval_id,
        "approved",
        approver="approver",
        approver_role=Role.ADMIN,
    )

    assert approval.status == "approved"
    executions = store.list_execution_runs(run_kind="smart_action")
    assert len(executions) == 1
    execution = executions[0]
    assert execution.status == "success"
    steps = store.list_execution_steps(execution.id or 0)
    assert [step.ordinal for step in steps] == [0, 1]
    assert steps[0].status == "pending_approval"
    assert steps[1].kind == "smart_action.approval_completed"
    assert steps[1].status == "success"


def test_recorder_failure_does_not_fail_workflow_run(settings, monkeypatch) -> None:
    store = Store(settings.data_path)
    _seed_tickets(store)

    def exploding_create(*args, **kwargs):
        raise RuntimeError("recorder storage exploded")

    monkeypatch.setattr(Store, "create_execution_run", exploding_create)

    run = run_workflow_template(store, "ticket-triage", "TCK-1001")

    assert run.status == "completed"
    assert store.get_workflow_run(run.id or 0) is not None


def test_recorder_failure_does_not_fail_smart_action_run(settings, monkeypatch) -> None:
    store = Store(settings.data_path)
    _seed_tickets(store)
    service = SmartActionService(store, settings)

    def exploding_create(*args, **kwargs):
        raise RuntimeError("recorder storage exploded")

    monkeypatch.setattr(Store, "create_execution_run", exploding_create)

    result = service.invoke("ticket-triage", {"ticket_id": "TCK-1001"}, "tech")

    assert result.status == "success"
    assert result.run_id is not None


def test_analytics_includes_source_run_when_recorder_fails(settings, monkeypatch) -> None:
    store = Store(settings.data_path)
    _seed_tickets(store)
    service = SmartActionService(store, settings)

    def exploding_create(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("recorder storage exploded")

    monkeypatch.setattr(Store, "create_execution_run", exploding_create)
    result = service.invoke("ticket-triage", {"ticket_id": "NOPE"}, "tech")

    assert result.status == "failed"
    summary = cast(dict[str, Any], build_analytics_summary(store, {}))
    assert summary["success_rate"] == {"total": 1, "succeeded": 0, "rate": 0.0}
    assert summary["failures_by_status"] == [{"status": "failed", "count": 1}]


def test_analytics_counts_successful_execution_bucket(settings) -> None:
    store = Store(settings.data_path)
    store.create_execution_run(
        "smart_action", 1, "tech", "success", "2026-08-01T10:00:00+00:00",
        "2026-08-01T10:00:01+00:00", "test"
    )

    summary = build_analytics_summary(store, {})

    assert summary["executions_over_time"] == [
        {"date": "2026-08-01", "count": 1, "succeeded": 1, "not_succeeded": 0}
    ]


def test_recorder_rejects_missing_persisted_run_id(settings, monkeypatch) -> None:
    recorder = ExecutionRecorder(Store(settings.data_path))

    class RunWithoutId:
        id = None

    monkeypatch.setattr(
        recorder.store, "create_execution_run", lambda *args, **kwargs: RunWithoutId()
    )

    assert recorder.record_execution(
        run_kind="workflow", source_run_id=None, actor="tech", status="completed", trigger_source="test"
    ) is None


def test_step_payloads_are_redacted_before_persistence(settings) -> None:
    store = Store(settings.data_path)
    recorder = ExecutionRecorder(store)

    run_id = recorder.record_execution(
        run_kind="smart_action",
        source_run_id=None,
        actor="tech",
        status="success",
        trigger_source="test",
        steps=(
            StepRecord(
                kind="smart_action.invoke",
                name="ticket-triage",
                status="success",
                input={"ticket_id": "TCK-1", "api_key": "super-secret-value"},
                output={"note": "token=abc123"},
            ),
        ),
    )

    assert run_id is not None
    steps = store.list_execution_steps(run_id)
    assert "super-secret-value" not in steps[0].input_json
    assert "abc123" not in steps[0].output_json


def test_legacy_step_rows_are_redacted_at_read_time(settings) -> None:
    store = Store(settings.data_path)
    run = store.create_execution_run(
        "smart_action", 1, "tech", "success", utc_now(), utc_now(), "test"
    )
    assert run.id is not None
    with store._connect() as connection:  # noqa: SLF001
        connection.execute(
            """
            insert into execution_steps
              (execution_run_id, ordinal, kind, name, status, started_at, finished_at,
               input_digest, output_digest, input_json, output_json, error_detail)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run.id,
                0,
                "smart_action.invoke",
                "legacy",
                "success",
                utc_now(),
                utc_now(),
                "digest",
                "digest",
                '{"note":"password=legacy-secret"}',
                "{}",
                "token=legacy-secret",
            ),
        )

    steps = store.list_execution_steps(run.id)
    assert "legacy-secret" not in steps[0].input_json
    assert "legacy-secret" not in steps[0].error_detail


def test_oversized_step_payload_is_capped_with_digest_marker() -> None:
    payload = {"data": "x" * (EXECUTION_STEP_PAYLOAD_CAP_BYTES * 2)}

    stored, digest = _capped_payload_json(payload)

    marker = json.loads(stored)
    assert marker["truncated"] is True
    assert marker["sha256"] == digest
    full = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    assert digest == hashlib.sha256(full.encode("utf-8")).hexdigest()
    assert len(stored.encode("utf-8")) <= EXECUTION_STEP_PAYLOAD_CAP_BYTES + 512


def test_plain_key_is_redacted_from_truncation_preview() -> None:
    stored, _ = _capped_payload_json(
        {"key": "truncation-secret", "data": "x" * (EXECUTION_STEP_PAYLOAD_CAP_BYTES * 2)}
    )

    assert "truncation-secret" not in stored


def test_small_step_payload_is_stored_verbatim() -> None:
    payload = {"ticket_id": "TCK-1"}

    stored, digest = _capped_payload_json(payload)

    assert json.loads(stored) == payload
    assert digest == hashlib.sha256(stored.encode("utf-8")).hexdigest()


def test_artifacts_are_content_addressed_and_deduplicated(settings, tmp_path) -> None:
    store = Store(settings.data_path)
    recorder = ExecutionRecorder(store, artifacts_dir=tmp_path / "artifacts")
    content = b'[{"type":"ticket"}]'

    first = recorder.record_execution(
        run_kind="workflow",
        source_run_id=1,
        actor="tech",
        status="completed",
        trigger_source="test",
        artifacts=(ArtifactRecord("evidence.json", "application/json", content, 0),),
    )
    second = recorder.record_execution(
        run_kind="workflow",
        source_run_id=2,
        actor="tech",
        status="completed",
        trigger_source="test",
        artifacts=(ArtifactRecord("evidence.json", "application/json", content, 0),),
    )

    assert first is not None and second is not None
    first_artifact = store.list_execution_artifacts(first)[0]
    second_artifact = store.list_execution_artifacts(second)[0]
    assert first_artifact.storage_path == second_artifact.storage_path
    assert first_artifact.sha256 == hashlib.sha256(content).hexdigest()
    assert first_artifact.step_ordinal == 0
    files = list((tmp_path / "artifacts").rglob("*"))
    assert len([path for path in files if path.is_file()]) == 1


def test_oversized_artifact_is_skipped_without_failing_recording(settings, tmp_path) -> None:
    store = Store(settings.data_path)
    recorder = ExecutionRecorder(store, artifacts_dir=tmp_path / "artifacts")
    content = b"x" * (4 * 1024 * 1024 + 1)

    run_id = recorder.record_execution(
        run_kind="workflow",
        source_run_id=1,
        actor="tech",
        status="completed",
        trigger_source="test",
        artifacts=(ArtifactRecord("large.bin", "application/octet-stream", content),),
    )

    assert run_id is not None
    assert store.list_execution_artifacts(run_id) == []


def test_slow_recorder_returns_within_bound(settings, monkeypatch) -> None:
    recorder = ExecutionRecorder(Store(settings.data_path))

    def slow_record(**_kwargs: Any) -> int:
        time.sleep(1.0)
        return 1

    monkeypatch.setattr(recorder, "_record_execution", slow_record)
    started = time.monotonic()
    result = recorder.record_execution(
        run_kind="workflow",
        source_run_id=1,
        actor="tech",
        status="completed",
        trigger_source="test",
    )

    assert result is None
    assert time.monotonic() - started < 0.9


def test_existing_artifact_digest_mismatch_is_rejected(settings, tmp_path) -> None:
    store = Store(settings.data_path)
    recorder = ExecutionRecorder(store, artifacts_dir=tmp_path / "artifacts")
    content = b"correct"
    digest = hashlib.sha256(content).hexdigest()
    artifact_path = tmp_path / "artifacts" / digest[:2] / digest
    artifact_path.parent.mkdir(parents=True)
    artifact_path.write_bytes(b"wrong")

    run_id = recorder.record_execution(
        run_kind="workflow",
        source_run_id=1,
        actor="tech",
        status="completed",
        trigger_source="test",
        artifacts=(ArtifactRecord("evidence.bin", "application/octet-stream", content),),
    )

    assert run_id is None
    assert artifact_path.read_bytes() == b"wrong"
    assert store.list_execution_artifacts(1) == []


def test_artifact_shard_symlink_is_rejected(settings, tmp_path) -> None:
    store = Store(settings.data_path)
    artifacts_dir = tmp_path / "artifacts"
    outside = tmp_path / "outside"
    artifacts_dir.mkdir()
    outside.mkdir()
    content = b"secret evidence"
    digest = hashlib.sha256(content).hexdigest()
    (artifacts_dir / digest[:2]).symlink_to(outside, target_is_directory=True)
    recorder = ExecutionRecorder(store, artifacts_dir=artifacts_dir)

    run_id = recorder.record_execution(
        run_kind="workflow",
        source_run_id=1,
        actor="tech",
        status="completed",
        trigger_source="test",
        artifacts=(ArtifactRecord("evidence.bin", "application/octet-stream", content),),
    )

    assert run_id is None
    assert list(outside.iterdir()) == []


def test_artifact_path_symlink_and_artifact_root_symlink_are_rejected(settings, tmp_path) -> None:
    store = Store(settings.data_path)
    content = b"evidence"
    digest = hashlib.sha256(content).hexdigest()

    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    recorder = ExecutionRecorder(store, artifacts_dir=artifacts_dir)
    shard = artifacts_dir / digest[:2]
    shard.mkdir()
    existing = artifacts_dir / "existing-file"
    existing.write_bytes(content)
    (shard / digest).symlink_to(existing)
    assert recorder.record_execution(
        run_kind="workflow", source_run_id=1, actor="tech", status="completed", trigger_source="test",
        artifacts=(ArtifactRecord("evidence.bin", "application/octet-stream", content),),
    ) is None

    target = tmp_path / "real-artifacts"
    target.mkdir()
    linked_dir = tmp_path / "linked-artifacts"
    linked_dir.symlink_to(target, target_is_directory=True)
    assert ExecutionRecorder(store, artifacts_dir=linked_dir).record_execution(
        run_kind="workflow", source_run_id=2, actor="tech", status="completed", trigger_source="test",
        artifacts=(ArtifactRecord("evidence.bin", "application/octet-stream", content),),
    ) is None


def test_artifact_path_assertion_rejects_symlink_shard_inside_root(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    target = root / "target"
    target.mkdir()
    shard = root / "aa"
    shard.symlink_to(target, target_is_directory=True)

    with pytest.raises(RuntimeError, match="symlink artifact shard"):
        ExecutionRecorder._assert_artifact_path(shard / "digest", root)


@pytest.mark.skipif(
    not _artifact_dir_fd_supported(), reason="directory-FD-relative operations are unavailable"
)
def test_artifact_ancestor_swap_is_rejected(tmp_path: Path, monkeypatch) -> None:
    store = Store(tmp_path / "state.db")
    artifacts_dir = tmp_path / "artifacts"
    recorder = ExecutionRecorder(store, artifacts_dir=artifacts_dir)
    content = b"ancestor swap"
    digest = hashlib.sha256(content).hexdigest()
    shard = artifacts_dir / digest[:2]
    shard.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    replacement = artifacts_dir / "original-shard"
    original_open = os.open
    swapped = False

    def swapping_open(path, flags, mode=0o777, *, dir_fd=None):
        nonlocal swapped
        if not swapped and dir_fd is not None and path == digest[:2]:
            shard.rename(replacement)
            shard.symlink_to(outside, target_is_directory=True)
            swapped = True
        if dir_fd is None:
            return original_open(path, flags, mode)
        return original_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(observability, "_artifact_dir_fd_supported", lambda: True)
    monkeypatch.setattr(os, "open", swapping_open)
    run_id = recorder.record_execution(
        run_kind="workflow",
        source_run_id=1,
        actor="tech",
        status="completed",
        trigger_source="test",
        artifacts=(ArtifactRecord("evidence.bin", "application/octet-stream", content),),
    )

    assert swapped
    assert run_id is None
    assert list(outside.iterdir()) == []
    assert list(replacement.iterdir()) == []


@pytest.mark.skipif(
    not _artifact_dir_fd_supported(), reason="directory-FD-relative operations are unavailable"
)
def test_artifact_destination_race_is_not_silently_overwritten(
    tmp_path: Path, monkeypatch
) -> None:
    content = b"intended content"
    path = tmp_path / hashlib.sha256(content).hexdigest()
    original_link = os.link
    directory_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)

    def racing_link(*args, **kwargs):
        path.write_bytes(b"racing destination")
        return original_link(*args, **kwargs)

    monkeypatch.setattr(os, "link", racing_link)
    try:
        with pytest.raises(RuntimeError, match="digest mismatch"):
            ExecutionRecorder._write_artifact_atomically(
                path, content, directory_fd=directory_fd
            )
    finally:
        os.close(directory_fd)

    assert path.read_bytes() == b"racing destination"


def test_artifact_record_uses_documented_fallback_without_dir_fd(
    settings, tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(observability, "_artifact_dir_fd_supported", lambda: False)
    store = Store(settings.data_path)
    recorder = ExecutionRecorder(store, artifacts_dir=tmp_path / "artifacts")
    content = b"path fallback"

    run_id = recorder.record_execution(
        run_kind="workflow",
        source_run_id=1,
        actor="tech",
        status="completed",
        trigger_source="test",
        artifacts=(ArtifactRecord("evidence.bin", "application/octet-stream", content),),
    )

    assert run_id is not None
    artifact = store.list_execution_artifacts(run_id)[0]
    assert Path(artifact.storage_path).read_bytes() == content


def test_fallback_rejects_symlink_destination_and_invalid_existing_file(
    settings, tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(observability, "_artifact_dir_fd_supported", lambda: False)
    store = Store(settings.data_path)
    artifacts_dir = tmp_path / "artifacts"
    recorder = ExecutionRecorder(store, artifacts_dir=artifacts_dir)
    content = b"fallback content"
    digest = hashlib.sha256(content).hexdigest()
    shard = artifacts_dir / digest[:2]
    shard.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.write_bytes(content)
    (shard / digest).symlink_to(outside)

    assert recorder.record_execution(
        run_kind="workflow", source_run_id=1, actor="tech", status="completed", trigger_source="test",
        artifacts=(ArtifactRecord("evidence.bin", "application/octet-stream", content),),
    ) is None

    (shard / digest).unlink()
    (shard / digest).write_bytes(b"wrong")
    assert recorder.record_execution(
        run_kind="workflow", source_run_id=2, actor="tech", status="completed", trigger_source="test",
        artifacts=(ArtifactRecord("evidence.bin", "application/octet-stream", content),),
    ) is None


def test_fallback_reaches_destination_symlink_check(settings, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(observability, "_artifact_dir_fd_supported", lambda: False)
    monkeypatch.setattr(ExecutionRecorder, "_assert_artifact_path", staticmethod(lambda *_args: None))
    store = Store(settings.data_path)
    recorder = ExecutionRecorder(store, artifacts_dir=tmp_path / "artifacts")
    content = b"symlink destination"
    digest = hashlib.sha256(content).hexdigest()
    shard = tmp_path / "artifacts" / digest[:2]
    shard.mkdir(parents=True)
    target = tmp_path / "target"
    target.write_bytes(content)
    (shard / digest).symlink_to(target)

    assert recorder.record_execution(
        run_kind="workflow", source_run_id=1, actor="tech", status="completed", trigger_source="test",
        artifacts=(ArtifactRecord("evidence.bin", "application/octet-stream", content),),
    ) is None


def test_fallback_rejects_existing_directory_at_artifact_path(settings, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(observability, "_artifact_dir_fd_supported", lambda: False)
    store = Store(settings.data_path)
    recorder = ExecutionRecorder(store, artifacts_dir=tmp_path / "artifacts")
    content = b"directory destination"
    digest = hashlib.sha256(content).hexdigest()
    path = tmp_path / "artifacts" / digest[:2] / digest
    path.parent.mkdir(parents=True)
    path.mkdir()

    assert recorder.record_execution(
        run_kind="workflow", source_run_id=1, actor="tech", status="completed", trigger_source="test",
        artifacts=(ArtifactRecord("evidence.bin", "application/octet-stream", content),),
    ) is None


def test_fallback_record_reconciles_existing_valid_artifact(settings, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(observability, "_artifact_dir_fd_supported", lambda: False)
    store = Store(settings.data_path)
    recorder = ExecutionRecorder(store, artifacts_dir=tmp_path / "artifacts")
    content = b"already present"
    digest = hashlib.sha256(content).hexdigest()
    path = tmp_path / "artifacts" / digest[:2] / digest
    path.parent.mkdir(parents=True)
    path.write_bytes(content)

    run_id = recorder.record_execution(
        run_kind="workflow", source_run_id=1, actor="tech", status="completed", trigger_source="test",
        artifacts=(ArtifactRecord("evidence.bin", "application/octet-stream", content),),
    )
    assert run_id is not None


def test_artifact_path_assertion_rejects_escape(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    with pytest.raises(RuntimeError, match="escapes"):
        ExecutionRecorder._assert_artifact_path(tmp_path / "outside" / "digest", root)


def test_atomic_artifact_write_reconciles_existing_valid_file(tmp_path: Path, monkeypatch) -> None:
    content = b"same content"
    path = tmp_path / hashlib.sha256(content).hexdigest()
    path.write_bytes(content)

    monkeypatch.setattr(os, "rename", lambda *_args: (_ for _ in ()).throw(FileExistsError))

    ExecutionRecorder._write_artifact_atomically(path, content)
    assert path.read_bytes() == content


@pytest.mark.skipif(
    not _artifact_dir_fd_supported(), reason="directory-FD-relative operations are unavailable"
)
def test_descriptor_artifact_write_reconciles_existing_valid_file(tmp_path: Path, monkeypatch) -> None:
    content = b"same descriptor content"
    path = tmp_path / hashlib.sha256(content).hexdigest()
    original_link = os.link

    def racing_link(*args, **kwargs):
        path.write_bytes(content)
        return original_link(*args, **kwargs)

    monkeypatch.setattr(os, "link", racing_link)
    directory_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        ExecutionRecorder._write_artifact_atomically(path, content, directory_fd=directory_fd)
    finally:
        os.close(directory_fd)
    assert path.read_bytes() == content


@pytest.mark.skipif(
    not _artifact_dir_fd_supported(), reason="directory-FD-relative operations are unavailable"
)
def test_descriptor_verification_rejects_symlink_and_non_regular_file(tmp_path: Path, monkeypatch) -> None:
    directory_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    path = tmp_path / ("a" * 64)
    original_open = os.open
    try:
        def symlink_open(*_args, **_kwargs):
            raise OSError(observability.errno.ELOOP, "symlink")

        monkeypatch.setattr(os, "open", symlink_open)
        with pytest.raises(RuntimeError, match="symlink artifact path"):
            _verify_existing_artifact_at_fd(directory_fd, path.name, path)

        def inaccessible_open(*_args, **_kwargs):
            raise OSError("inaccessible")

        monkeypatch.setattr(os, "open", inaccessible_open)
        with pytest.raises(RuntimeError, match="digest mismatch"):
            _verify_existing_artifact_at_fd(directory_fd, path.name, path)

        monkeypatch.setattr(os, "open", original_open)
        path.mkdir()
        with pytest.raises(RuntimeError, match="digest mismatch"):
            _verify_existing_artifact_at_fd(directory_fd, path.name, path)
    finally:
        os.close(directory_fd)


def test_descriptor_artifact_temp_creation_failure_is_propagated(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "artifact"
    directory_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    monkeypatch.setattr(os, "open", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("no temp")))
    try:
        with pytest.raises(OSError, match="no temp"):
            observability._write_artifact_at_fd(directory_fd, path.name, path, b"content")
    finally:
        os.close(directory_fd)


def test_recorder_failure_and_empty_result_are_swallowed(settings, monkeypatch) -> None:
    recorder = ExecutionRecorder(Store(settings.data_path))
    monkeypatch.setattr(recorder, "_record_execution", lambda **_kwargs: None)
    assert recorder.record_execution(
        run_kind="workflow", source_run_id=None, actor="tech", status="completed", trigger_source="test"
    ) is None

    def fail(**_kwargs):
        raise RuntimeError("recording failed")

    monkeypatch.setattr(recorder, "_record_execution", fail)
    assert recorder.record_execution(
        run_kind="workflow", source_run_id=None, actor="tech", status="completed", trigger_source="test"
    ) is None


def test_atomic_artifact_write_closes_descriptor_when_opening_handle_fails(
    tmp_path: Path, monkeypatch
) -> None:
    path = tmp_path / "artifact"
    closed: list[int] = []
    monkeypatch.setattr(os, "fdopen", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("temporary artifact")))
    monkeypatch.setattr(os, "close", lambda descriptor: closed.append(descriptor))

    with pytest.raises(OSError, match="temporary artifact"):
        ExecutionRecorder._write_artifact_atomically(path, b"content")

    assert closed


def test_atomic_artifact_write_rejects_racing_invalid_file(tmp_path: Path, monkeypatch) -> None:
    content = b"same content"
    path = tmp_path / hashlib.sha256(content).hexdigest()
    path.write_bytes(b"wrong content")
    monkeypatch.setattr(os, "rename", lambda *_args: (_ for _ in ()).throw(FileExistsError))

    with pytest.raises(RuntimeError, match="digest mismatch"):
        ExecutionRecorder._write_artifact_atomically(path, content)


def test_fallback_atomic_write_reconciles_valid_and_rejects_invalid_file(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(observability, "_artifact_dir_fd_supported", lambda: False)
    content = b"fallback same content"
    path = tmp_path / hashlib.sha256(content).hexdigest()
    path.write_bytes(content)
    monkeypatch.setattr(os, "rename", lambda *_args: (_ for _ in ()).throw(FileExistsError))
    ExecutionRecorder._write_artifact_atomically(path, content)

    path.write_bytes(b"fallback wrong content")
    with pytest.raises(RuntimeError, match="digest mismatch"):
        ExecutionRecorder._write_artifact_atomically(path, content)


def test_fallback_atomic_write_closes_descriptor_when_handle_fails(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(observability, "_artifact_dir_fd_supported", lambda: False)
    closed: list[int] = []
    monkeypatch.setattr(os, "fdopen", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("temporary")))
    original_close = os.close

    def close(descriptor: int) -> None:
        closed.append(descriptor)
        original_close(descriptor)

    monkeypatch.setattr(os, "close", close)
    with pytest.raises(OSError, match="temporary"):
        ExecutionRecorder._write_artifact_atomically(tmp_path / "artifact", b"content")
    assert closed


def test_list_execution_runs_filters(settings) -> None:
    store = Store(settings.data_path)
    now = utc_now()
    store.create_execution_run("workflow", 1, "a", "completed", now, now, "test", client_id="acme")
    store.create_execution_run("smart_action", 2, "b", "failed", now, now, "test", client_id="acme")
    store.create_execution_run("workflow", 3, "c", "completed", now, now, "test", client_id="beta")

    assert len(store.list_execution_runs()) == 3
    assert len(store.list_execution_runs(client_id="acme")) == 2
    assert len(store.list_execution_runs(run_kind="workflow")) == 2
    assert len(store.list_execution_runs(status="failed")) == 1
    assert len(store.list_execution_runs(started_from="2999-01-01")) == 0
    assert len(store.list_execution_runs(started_to="2000-01-01")) == 0
    assert len(store.list_execution_runs(started_from="2000-01-01", started_to="2999-01-01")) == 3


def test_update_execution_run_and_missing_run(settings) -> None:
    store = Store(settings.data_path)
    run = store.create_execution_run("workflow", 1, "a", "pending_approval", utc_now(), utc_now(), "t")
    assert run.id is not None

    updated = store.update_execution_run(run.id, "completed", utc_now())

    assert updated.status == "completed"
    assert store.find_execution_run("workflow", 1) is not None
    assert store.find_execution_run("workflow", 999) is None
    assert store.get_execution_run(999) is None
    assert store.get_execution_artifact(999) is None
    try:
        store.update_execution_run(999, "completed", utc_now())
        raised = False
    except KeyError:
        raised = True
    assert raised
