from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from wait_local_agent.store import SMART_ACTION_APPROVAL_CAPABILITY, Store
from wait_local_agent.workflows import get_workflow_template


def test_store_migrates_populated_prechange_schema_idempotently(tmp_path: Path) -> None:
    db_path = tmp_path / "state.db"
    _seed_prechange_schema(db_path)

    Store(db_path)
    Store(db_path)

    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        tickets_columns = _columns(connection, "tickets")
        approval_columns = _columns(connection, "approval_requests")
        audit_columns = _columns(connection, "audit_events")
        workflow_columns = _columns(connection, "workflow_runs")
        scheduled_columns = _columns(connection, "scheduled_jobs")
        event_delivery_columns = _columns(connection, "event_deliveries")
        knowledge_columns = _columns(connection, "knowledge_documents")
        smart_action_columns = _columns(connection, "smart_action_runs")
        event_history_columns = _columns(connection, "event_history")
        revision_columns = _columns(connection, "agent_definition_revisions")
        backfill_columns = _columns(connection, "agent_backfills")
        ticket = connection.execute("select * from tickets where id = 'TCK-1'").fetchone()
        approval = connection.execute("select * from approval_requests where id = 1").fetchone()
        audit = connection.execute("select * from audit_events where id = 1").fetchone()
        workflow = connection.execute("select * from workflow_runs where id = 1").fetchone()
        document = connection.execute("select * from knowledge_documents where id = 1").fetchone()

    assert "client_id" in tickets_columns
    assert "client_id" in approval_columns
    assert "approver_id" in approval_columns
    assert "client_id" in audit_columns
    assert "approver_id" in audit_columns
    assert "client_id" in event_history_columns
    assert "client_id" in workflow_columns
    assert "client_id" in scheduled_columns
    assert "job_kind" in scheduled_columns
    assert "agent_id" in scheduled_columns
    assert "entity_id" in scheduled_columns
    assert "idempotency_key" in event_delivery_columns
    assert "processed_at" in event_delivery_columns
    assert "definition_json" in revision_columns
    assert "depends_on_agent_ids_json" in _columns(connection, "agent_definitions")
    assert "failed_entity_ids_json" in backfill_columns
    assert "client_id" in knowledge_columns
    assert "client_id" in smart_action_columns
    assert ticket is not None and ticket["client_id"] is None
    assert approval is not None and approval["client_id"] is None and approval["approver_id"] is None
    assert audit is not None and audit["client_id"] is None and audit["approver_id"] is None
    assert workflow is not None and workflow["client_id"] is None
    assert document is not None and document["client_id"] is None


def test_store_event_delivery_crud_is_idempotent_and_tenant_scoped(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.db")

    delivery, created = store.create_event_delivery(
        idempotency_key="provider-1",
        event_type="ticket.created",
        entity_type="ticket",
        entity_id="TCK-1",
        payload={"priority": "P1", "api_token": "secret-value"},
        client_id=" acme ",
    )
    assert created is True
    assert delivery.id is not None
    assert "secret-value" not in delivery.payload_json

    duplicate, duplicate_created = store.create_event_delivery(
        idempotency_key="provider-1",
        event_type="ticket.created",
        entity_type="ticket",
        entity_id="TCK-1",
        payload={"priority": "P1"},
        client_id="acme",
    )
    assert duplicate_created is False
    assert duplicate.id == delivery.id

    updated = store.update_event_delivery(
        delivery.id,
        status="failed",
        matched_agent_count=1,
        agent_ids=["agent-1"],
        run_ids=[7],
        error_detail="api_token=secret-value",
    )
    assert updated.status == "failed"
    assert updated.matched_agent_count == 1
    assert store.get_event_delivery(delivery.id, client_id="beta") is None
    assert store.get_event_delivery(delivery.id, client_id="acme") is not None
    assert [item.id for item in store.list_event_deliveries(client_id="acme")] == [delivery.id]
    assert store.has_event_agent_run(
        agent_id="agent-1", event_type="ticket.created", entity_id="TCK-1", client_id="acme"
    ) is True
    assert store.has_event_agent_run(
        agent_id="agent-1", event_type="ticket.created", entity_id="TCK-1", client_id="beta"
    ) is False

    with pytest.raises(KeyError):
        store.update_event_delivery(
            99999,
            status="failed",
            matched_agent_count=0,
            agent_ids=[],
            run_ids=[],
        )


def test_store_template_gallery_persists_provenance_and_scope(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.db")
    template = get_workflow_template("ticket-triage")
    assert template is not None

    entry = store.create_template_gallery_entry(
        template,
        provenance="Reviewed local core template",
        client_id="acme",
        name="Acme triage starter",
    )
    assert entry.source_template_id == "ticket-triage"
    assert entry.name == "Acme triage starter"
    assert store.get_template_gallery_entry(entry.id, client_id="beta") is None
    assert store.get_template_gallery_entry(entry.id, client_id="acme") is not None
    assert [item.id for item in store.list_template_gallery_entries(client_id="acme")] == [entry.id]


def test_store_client_filters_cover_required_list_surfaces(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.db")

    with store._connect() as connection:  # noqa: SLF001
        connection.execute(
            """
            insert into tickets (id, client, subject, body, priority, status, client_id)
            values ('TCK-1', 'Acme', 'One', 'Body', 'High', 'Open', 'acme')
            """
        )
        connection.execute(
            """
            insert into tickets (id, client, subject, body, priority, status, client_id)
            values ('TCK-2', 'Beta', 'Two', 'Body', 'Low', 'Open', 'beta')
            """
        )

    acme_approval = store.create_approval_request("TCK-1", "ticket.assign", {"ticket_id": "TCK-1"}, client_id="acme")
    beta_approval = store.create_approval_request("TCK-2", "ticket.assign", {"ticket_id": "TCK-2"}, client_id="beta")
    store.add_audit_event("unit.test", "TCK-1", "acme event", client_id="acme")
    store.add_audit_event("unit.test", "TCK-2", "beta event", client_id="beta")
    store.create_workflow_run(
        "documentation-assisted-response", "TCK-1", "pending_approval", "acme", acme_approval.id, client_id="acme"
    )
    store.create_workflow_run(
        "documentation-assisted-response", "TCK-2", "pending_approval", "beta", beta_approval.id, client_id="beta"
    )
    store.upsert_knowledge_document(
        path="examples/sample_docs/acme.md",
        title="Acme",
        kind="markdown",
        checksum="a1",
        modified_at="2026-07-08T00:00:00+00:00",
        chunks=["one"],
        client_id="acme",
    )
    store.upsert_knowledge_document(
        path="examples/sample_docs/beta.md",
        title="Beta",
        kind="markdown",
        checksum="b1",
        modified_at="2026-07-08T00:00:00+00:00",
        chunks=["two"],
        client_id="beta",
    )

    assert [ticket.id for ticket in store.list_tickets(client_id="acme")] == ["TCK-1"]
    assert [ticket.id for ticket in store.list_tickets(client_id="")] == ["TCK-1", "TCK-2"]
    assert [request.id for request in store.list_approval_requests(client_id="acme")] == [acme_approval.id]
    assert [request.id for request in store.list_approval_requests(client_id="")] == [
        beta_approval.id,
        acme_approval.id,
    ]
    assert any(event.subject_id == "TCK-1" for event in store.list_audit_events(client_id="acme"))
    assert len(store.list_audit_events(client_id="")) == len(store.list_audit_events())
    assert all(event.client_id == "acme" for event in store.list_event_history(client_id="acme"))
    assert len(store.list_event_history(client_id="")) == len(store.list_event_history())
    assert [run.ticket_id for run in store.list_workflow_runs(client_id="acme")] == ["TCK-1"]
    assert [run.ticket_id for run in store.list_workflow_runs(client_id="")] == ["TCK-2", "TCK-1"]
    assert [document.title for document in store.list_knowledge_documents(client_id="acme")] == ["Acme"]
    assert [document.title for document in store.list_knowledge_documents(client_id="")] == ["Acme", "Beta"]
    assert len(store.list_tickets()) == 2
    assert len(store.list_approval_requests()) == 2
    assert len(store.list_workflow_runs()) == 2
    assert len(store.list_knowledge_documents()) == 2


def test_store_rejects_invalid_approval_transitions(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.db")
    approval = store.create_approval_request("TCK-1", "ticket.assign", {})

    store.update_approval_request(approval.id or 0, "approved")

    with pytest.raises(ValueError, match="approval status"):
        store.update_approval_request(approval.id or 0, "unknown")
    with pytest.raises(PermissionError, match="already completed"):
        store.update_approval_request(approval.id or 0, "rejected")


def test_store_scheduled_job_crud_and_client_filters(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.db")

    acme = store.create_scheduled_job(
        "documentation-assisted-response",
        "0 9 * * *",
        {"ticket_id": "TCK-1", "client_id": "acme"},
        client_id="acme",
    )
    beta = store.create_scheduled_job(
        "documentation-assisted-response",
        "15 10 * * 1",
        {"ticket_id": "TCK-2", "client_id": "beta"},
        client_id="beta",
    )
    paused = store.update_scheduled_job_paused(acme.id or 0, True)
    resumed = store.update_scheduled_job_paused(acme.id or 0, False)
    deleted = store.delete_scheduled_job(beta.id or 0)

    assert acme.id is not None
    assert paused.paused is True
    assert resumed.paused is False
    assert deleted.id == beta.id
    assert [job.id for job in store.list_scheduled_jobs(client_id="acme")] == [acme.id]
    assert [job.id for job in store.list_scheduled_jobs(client_id="")] == [acme.id]
    assert store.get_scheduled_job(beta.id or 0) is None


def test_store_smart_action_crud_filters_and_completion_guards(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.db")
    acme_run, acme_approval = store.create_pending_smart_action(
        "dispatch-suggestion",
        "requester",
        "digest",
        {"recommendation": {}},
        [{"type": "ticket", "ticket_id": "TCK-1"}],
        {"action_id": "dispatch-suggestion", "payload": {"ticket_id": "TCK-1"}},
        client_id=" acme ",
    )
    beta_run = store.create_smart_action_run(
        "ticket-triage", "other", "success", "digest", {}, [], client_id="beta"
    )

    assert acme_run.id is not None and acme_approval.id is not None
    assert store.get_smart_action_run(acme_run.id, "acme") is not None
    assert store.get_smart_action_run(acme_run.id, "beta") is None
    assert [run.client_id for run in store.list_smart_action_runs(client_id="acme")] == ["acme"]
    assert [run.client_id for run in store.list_smart_action_runs(client_id="")] == ["beta", "acme"]
    assert store.set_smart_action_run_approval(acme_run.id, acme_approval.id).approval_id == acme_approval.id

    with pytest.raises(PermissionError, match="completed through SmartActionService"):
        store.complete_smart_action_run(
            acme_run.id,
            "success",
            {},
            [],
            approval_id=acme_approval.id,
            approver_id="tech",
        )
    with pytest.raises(PermissionError, match="linked approval"):
        store.complete_smart_action_run(
            acme_run.id,
            "success",
            {},
            [],
            approval_id=acme_approval.id + 1,
            approver_id="tech",
            _smart_action_capability=SMART_ACTION_APPROVAL_CAPABILITY,
        )
    with pytest.raises(ValueError, match="invalid smart action"):
        store.complete_smart_action_run(
            acme_run.id,
            "pending",
            {},
            [],
            approval_id=acme_approval.id,
            approver_id="tech",
            _smart_action_capability=SMART_ACTION_APPROVAL_CAPABILITY,
        )
    assert beta_run.id is not None
    with pytest.raises(KeyError):
        store.set_smart_action_run_approval(99999, acme_approval.id)


def test_store_smart_action_completion_requires_approval_and_approver(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.db")
    run, approval = store.create_pending_smart_action(
        "dispatch-suggestion", "requester", "digest", {}, [], {"payload": {}}, client_id="acme"
    )
    assert run.id is not None and approval.id is not None
    with pytest.raises(PermissionError, match="completed approval"):
        store.complete_smart_action_run(
            run.id,
            "success",
            {},
            [],
            approval_id=approval.id,
            approver_id="tech",
            _smart_action_capability=SMART_ACTION_APPROVAL_CAPABILITY,
        )
    store.update_approval_request(
        approval.id,
        "approved",
        approver_id="tech",
        _smart_action_capability=SMART_ACTION_APPROVAL_CAPABILITY,
    )
    completed = store.complete_smart_action_run(
        run.id,
        "success",
        {"approved": True},
        [],
        approval_id=approval.id,
        approver_id="tech",
        _smart_action_capability=SMART_ACTION_APPROVAL_CAPABILITY,
    )
    assert completed.status == "success"
    with pytest.raises(PermissionError, match="already completed"):
        store.complete_smart_action_run(
            run.id,
            "success",
            {},
            [],
            approval_id=approval.id,
            approver_id="tech",
            _smart_action_capability=SMART_ACTION_APPROVAL_CAPABILITY,
        )


def _seed_prechange_schema(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            create table tickets (
                id text primary key,
                client text not null,
                subject text not null,
                body text not null,
                priority text not null,
                status text not null
            );
            create table approvals (
                ticket_id text primary key,
                status text not null,
                comment text not null default '',
                updated_at text not null
            );
            create table audit_events (
                id integer primary key autoincrement,
                event_type text not null,
                subject_id text not null,
                detail text not null,
                created_at text not null
            );
            create table approval_requests (
                id integer primary key autoincrement,
                subject_id text not null,
                action_type text not null,
                payload_json text not null,
                status text not null,
                comment text not null,
                created_at text not null,
                updated_at text not null,
                execution_status text not null default 'not_started',
                execution_message text not null default '',
                executed_at text not null default '',
                execution_result_json text not null default '{}'
            );
            create table event_history (
                id integer primary key autoincrement,
                event_type text not null,
                subject_id text not null,
                status text not null,
                message text not null,
                payload_json text not null,
                created_at text not null
            );
            create table workflow_runs (
                id integer primary key autoincrement,
                template_id text not null,
                ticket_id text not null,
                status text not null,
                message text not null,
                approval_request_id integer,
                created_at text not null,
                updated_at text not null
            );
            create table knowledge_documents (
                id integer primary key autoincrement,
                path text not null unique,
                title text not null,
                kind text not null,
                checksum text not null,
                modified_at text not null,
                chunk_count integer not null,
                indexed_at text not null
            );
            create table knowledge_chunks (
                id integer primary key autoincrement,
                document_id integer not null references knowledge_documents(id) on delete cascade,
                chunk_index integer not null,
                text text not null,
                excerpt text not null,
                unique(document_id, chunk_index)
            );
            create virtual table knowledge_chunks_fts using fts5(chunk_id unindexed, title, path unindexed, text);
            insert into tickets values ('TCK-1', 'Acme', 'Subject', 'Body', 'High', 'Open');
            insert into audit_events (event_type, subject_id, detail, created_at)
            values ('unit.test', 'TCK-1', 'detail', '2026-07-08T00:00:00+00:00');
            insert into approval_requests
              (
                subject_id,
                action_type,
                payload_json,
                status,
                comment,
                created_at,
                updated_at,
                execution_status,
                execution_message,
                executed_at,
                execution_result_json
              )
            values
              (
                'TCK-1',
                'ticket.assign',
                '{}',
                'pending',
                '',
                '2026-07-08T00:00:00+00:00',
                '2026-07-08T00:00:00+00:00',
                'not_started',
                '',
                '',
                '{}'
              );
            insert into workflow_runs
              (template_id, ticket_id, status, message, approval_request_id, created_at, updated_at)
            values
              (
                'documentation-assisted-response',
                'TCK-1',
                'pending_approval',
                'waiting',
                1,
                '2026-07-08T00:00:00+00:00',
                '2026-07-08T00:00:00+00:00'
              );
            insert into knowledge_documents
              (path, title, kind, checksum, modified_at, chunk_count, indexed_at)
            values
              (
                'examples/sample_docs/doc.md',
                'Doc',
                'markdown',
                'sum',
                '2026-07-08T00:00:00+00:00',
                1,
                '2026-07-08T00:00:00+00:00'
              );
            """
        )


def _columns(connection: sqlite3.Connection, table_name: str) -> set[str]:
    rows = connection.execute(f"pragma table_info({table_name})").fetchall()
    return {str(row[1]) for row in rows}
