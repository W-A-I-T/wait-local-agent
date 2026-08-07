from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from wait_local_agent.models import utc_now
from wait_local_agent.observability import (
    EXECUTION_STEP_PAYLOAD_CAP_BYTES,
    ArtifactRecord,
    ExecutionRecorder,
    StepRecord,
    _capped_payload_json,
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
