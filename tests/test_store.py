from __future__ import annotations

import sqlite3
from pathlib import Path

from wait_local_agent.store import Store


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
        knowledge_columns = _columns(connection, "knowledge_documents")
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
    assert "client_id" in workflow_columns
    assert "client_id" in knowledge_columns
    assert ticket is not None and ticket["client_id"] is None
    assert approval is not None and approval["client_id"] is None and approval["approver_id"] is None
    assert audit is not None and audit["client_id"] is None and audit["approver_id"] is None
    assert workflow is not None and workflow["client_id"] is None
    assert document is not None and document["client_id"] is None


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
    assert [request.id for request in store.list_approval_requests(client_id="acme")] == [acme_approval.id]
    assert any(event.subject_id == "TCK-1" for event in store.list_audit_events(client_id="acme"))
    assert [run.ticket_id for run in store.list_workflow_runs(client_id="acme")] == ["TCK-1"]
    assert [document.title for document in store.list_knowledge_documents(client_id="acme")] == ["Acme"]
    assert len(store.list_tickets()) == 2
    assert len(store.list_approval_requests()) == 2
    assert len(store.list_workflow_runs()) == 2
    assert len(store.list_knowledge_documents()) == 2


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
