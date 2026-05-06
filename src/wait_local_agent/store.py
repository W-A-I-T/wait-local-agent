from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from wait_local_agent.models import (
    ApprovalRequest,
    AuditEvent,
    EventHistoryEntry,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeDocumentWrite,
    Ticket,
    WorkflowRun,
    utc_now,
)

MAX_SEARCH_LIMIT = 25


class Store:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _init_schema(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                create table if not exists tickets (
                    id text primary key,
                    client text not null,
                    subject text not null,
                    body text not null,
                    priority text not null,
                    status text not null
                )
                """
            )
            connection.execute(
                """
                create table if not exists approvals (
                    ticket_id text primary key,
                    status text not null,
                    comment text not null default '',
                    updated_at text not null
                )
                """
            )
            self._ensure_column(connection, "approvals", "comment", "text not null default ''")
            connection.execute(
                """
                create table if not exists audit_events (
                    id integer primary key autoincrement,
                    event_type text not null,
                    subject_id text not null,
                    detail text not null,
                    created_at text not null
                )
                """
            )
            connection.execute(
                """
                create table if not exists approval_requests (
                    id integer primary key autoincrement,
                    subject_id text not null,
                    action_type text not null,
                    payload_json text not null,
                    status text not null,
                    comment text not null,
                    created_at text not null,
                    updated_at text not null
                )
                """
            )
            connection.execute(
                """
                create table if not exists event_history (
                    id integer primary key autoincrement,
                    event_type text not null,
                    subject_id text not null,
                    status text not null,
                    message text not null,
                    payload_json text not null,
                    created_at text not null
                )
                """
            )
            connection.execute(
                """
                create table if not exists workflow_runs (
                    id integer primary key autoincrement,
                    template_id text not null,
                    ticket_id text not null,
                    status text not null,
                    message text not null,
                    approval_request_id integer,
                    created_at text not null,
                    updated_at text not null
                )
                """
            )
            connection.execute(
                """
                create table if not exists knowledge_documents (
                    id integer primary key autoincrement,
                    path text not null unique,
                    title text not null,
                    kind text not null,
                    checksum text not null,
                    modified_at text not null,
                    chunk_count integer not null,
                    indexed_at text not null
                )
                """
            )
            connection.execute(
                """
                create table if not exists knowledge_chunks (
                    id integer primary key autoincrement,
                    document_id integer not null
                      references knowledge_documents(id) on delete cascade,
                    chunk_index integer not null,
                    text text not null,
                    excerpt text not null,
                    unique(document_id, chunk_index)
                )
                """
            )
            connection.execute(
                """
                create virtual table if not exists knowledge_chunks_fts
                using fts5(chunk_id unindexed, title, path unindexed, text)
                """
            )

    @staticmethod
    def _ensure_column(
        connection: sqlite3.Connection, table_name: str, column_name: str, definition: str
    ) -> None:
        rows = connection.execute(f"pragma table_info({table_name})").fetchall()
        if column_name not in {str(row["name"]) for row in rows}:
            connection.execute(f"alter table {table_name} add column {column_name} {definition}")

    def ingest_ticket_file(self, path: Path) -> int:
        payload = json.loads(path.read_text(encoding="utf-8"))
        tickets = [Ticket(**item) for item in payload]
        with self._connect() as connection:
            for ticket in tickets:
                connection.execute(
                    """
                    insert into tickets (id, client, subject, body, priority, status)
                    values (?, ?, ?, ?, ?, ?)
                    on conflict(id) do update set
                      client=excluded.client,
                      subject=excluded.subject,
                      body=excluded.body,
                      priority=excluded.priority,
                      status=excluded.status
                    """,
                    (
                        ticket.id,
                        ticket.client,
                        ticket.subject,
                        ticket.body,
                        ticket.priority,
                        ticket.status,
                    ),
                )
                self._add_audit_event(
                    connection,
                    "ticket.ingested",
                    ticket.id,
                    f"Imported {ticket.subject}",
                )
        return len(tickets)

    def list_tickets(self) -> list[Ticket]:
        with self._connect() as connection:
            rows = connection.execute("select * from tickets order by id").fetchall()
        return [Ticket(**dict(row)) for row in rows]

    def get_ticket(self, ticket_id: str) -> Ticket | None:
        with self._connect() as connection:
            row = connection.execute("select * from tickets where id = ?", (ticket_id,)).fetchone()
        return Ticket(**dict(row)) if row else None

    def set_approval(self, ticket_id: str, status: str, comment: str = "") -> None:
        with self._connect() as connection:
            connection.execute(
                """
                insert into approvals (ticket_id, status, comment, updated_at)
                values (?, ?, ?, ?)
                on conflict(ticket_id) do update set
                  status=excluded.status,
                  comment=excluded.comment,
                  updated_at=excluded.updated_at
                """,
                (ticket_id, status, comment, utc_now()),
            )
        detail = status if not comment else f"{status}: {comment}"
        self.add_audit_event("approval.updated", ticket_id, detail)

    def get_approval(self, ticket_id: str) -> str:
        with self._connect() as connection:
            row = connection.execute(
                "select status from approvals where ticket_id = ?", (ticket_id,)
            ).fetchone()
        return str(row["status"]) if row else "pending"

    def get_approval_comment(self, ticket_id: str) -> str:
        with self._connect() as connection:
            row = connection.execute(
                "select comment from approvals where ticket_id = ?", (ticket_id,)
            ).fetchone()
        return str(row["comment"]) if row else ""

    def create_approval_request(
        self, subject_id: str, action_type: str, payload: dict[str, object]
    ) -> ApprovalRequest:
        now = utc_now()
        payload_json = json.dumps(payload, sort_keys=True)
        with self._connect() as connection:
            cursor = connection.execute(
                """
                insert into approval_requests
                  (subject_id, action_type, payload_json, status, comment, created_at, updated_at)
                values (?, ?, ?, ?, ?, ?, ?)
                """,
                (subject_id, action_type, payload_json, "pending", "", now, now),
            )
            if cursor.lastrowid is None:
                raise RuntimeError("approval request insert did not return an id")
            request_id = int(cursor.lastrowid)
            self._add_audit_event(
                connection,
                "approval.requested",
                subject_id,
                f"{action_type} approval requested",
            )
            self._add_event_history(
                connection,
                "approval.requested",
                subject_id,
                "pending",
                f"{action_type} waiting for technician approval",
                payload_json,
            )
        request = self.get_approval_request(request_id)
        if request is None:
            raise RuntimeError("approval request was not persisted")
        return request

    def update_approval_request(
        self, request_id: int, status: str, comment: str = ""
    ) -> ApprovalRequest:
        now = utc_now()
        with self._connect() as connection:
            row = connection.execute(
                "select * from approval_requests where id = ?", (request_id,)
            ).fetchone()
            if row is None:
                raise KeyError(request_id)
            connection.execute(
                """
                update approval_requests
                set status = ?, comment = ?, updated_at = ?
                where id = ?
                """,
                (status, comment, now, request_id),
            )
            workflow_status = _workflow_status_for_approval(status)
            connection.execute(
                """
                update workflow_runs
                set status = ?, updated_at = ?
                where approval_request_id = ?
                """,
                (workflow_status, now, request_id),
            )
            self._add_audit_event(
                connection,
                "approval_request.updated",
                str(row["subject_id"]),
                f"{row['action_type']} {status}",
            )
            self._add_event_history(
                connection,
                "approval_request.updated",
                str(row["subject_id"]),
                status,
                comment or f"{row['action_type']} {status}",
                str(row["payload_json"]),
            )
        request = self.get_approval_request(request_id)
        if request is None:
            raise RuntimeError("approval request was not persisted")
        return request

    def get_approval_request(self, request_id: int) -> ApprovalRequest | None:
        with self._connect() as connection:
            row = connection.execute(
                "select * from approval_requests where id = ?", (request_id,)
            ).fetchone()
        return ApprovalRequest(**dict(row)) if row else None

    def list_approval_requests(self) -> list[ApprovalRequest]:
        with self._connect() as connection:
            rows = connection.execute(
                "select * from approval_requests order by id desc"
            ).fetchall()
        return [ApprovalRequest(**dict(row)) for row in rows]

    def add_audit_event(self, event_type: str, subject_id: str, detail: str) -> None:
        with self._connect() as connection:
            self._add_audit_event(connection, event_type, subject_id, detail)
            self._add_event_history(
                connection,
                event_type,
                subject_id,
                "completed",
                detail,
                "{}",
            )

    @staticmethod
    def _add_audit_event(
        connection: sqlite3.Connection, event_type: str, subject_id: str, detail: str
    ) -> None:
        connection.execute(
            """
            insert into audit_events (event_type, subject_id, detail, created_at)
            values (?, ?, ?, ?)
            """,
            (event_type, subject_id, detail, utc_now()),
        )

    @staticmethod
    def _add_event_history(
        connection: sqlite3.Connection,
        event_type: str,
        subject_id: str,
        status: str,
        message: str,
        payload_json: str,
    ) -> None:
        connection.execute(
            """
            insert into event_history
              (event_type, subject_id, status, message, payload_json, created_at)
            values (?, ?, ?, ?, ?, ?)
            """,
            (event_type, subject_id, status, message, payload_json, utc_now()),
        )

    def list_audit_events(self) -> list[AuditEvent]:
        with self._connect() as connection:
            rows = connection.execute("select * from audit_events order by id desc").fetchall()
        return [AuditEvent(**dict(row)) for row in rows]

    def list_event_history(self) -> list[EventHistoryEntry]:
        with self._connect() as connection:
            rows = connection.execute("select * from event_history order by id desc").fetchall()
        return [EventHistoryEntry(**dict(row)) for row in rows]

    def create_workflow_run(
        self,
        template_id: str,
        ticket_id: str,
        status: str,
        message: str,
        approval_request_id: int | None = None,
    ) -> WorkflowRun:
        now = utc_now()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                insert into workflow_runs
                  (template_id, ticket_id, status, message, approval_request_id,
                   created_at, updated_at)
                values (?, ?, ?, ?, ?, ?, ?)
                """,
                (template_id, ticket_id, status, message, approval_request_id, now, now),
            )
            if cursor.lastrowid is None:
                raise RuntimeError("workflow run insert did not return an id")
            run_id = int(cursor.lastrowid)
            self._add_audit_event(connection, "workflow.run_created", ticket_id, message)
            payload = json.dumps(
                {
                    "template_id": template_id,
                    "ticket_id": ticket_id,
                    "approval_request_id": approval_request_id,
                },
                sort_keys=True,
            )
            self._add_event_history(
                connection,
                "workflow.execution",
                ticket_id,
                status,
                message,
                payload,
            )
        run = self.get_workflow_run(run_id)
        if run is None:
            raise RuntimeError("workflow run was not persisted")
        return run

    def get_workflow_run(self, run_id: int) -> WorkflowRun | None:
        with self._connect() as connection:
            row = connection.execute(
                "select * from workflow_runs where id = ?", (run_id,)
            ).fetchone()
        return WorkflowRun(**dict(row)) if row else None

    def list_workflow_runs(self) -> list[WorkflowRun]:
        with self._connect() as connection:
            rows = connection.execute("select * from workflow_runs order by id desc").fetchall()
        return [WorkflowRun(**dict(row)) for row in rows]

    def upsert_knowledge_document(
        self,
        *,
        path: str,
        title: str,
        kind: str,
        checksum: str,
        modified_at: str,
        chunks: list[str],
    ) -> KnowledgeDocument:
        return self.upsert_knowledge_documents(
            [
                KnowledgeDocumentWrite(
                    path=path,
                    title=title,
                    kind=kind,
                    checksum=checksum,
                    modified_at=modified_at,
                    chunks=chunks,
                )
            ]
        )[0]

    def upsert_knowledge_documents(
        self, documents: list[KnowledgeDocumentWrite]
    ) -> list[KnowledgeDocument]:
        if not documents:
            return []
        now = utc_now()
        document_ids: list[int] = []
        with self._connect() as connection:
            for document in documents:
                existing = connection.execute(
                    "select id from knowledge_documents where path = ?", (document.path,)
                ).fetchone()
                if existing:
                    document_id = int(existing["id"])
                    chunk_rows = connection.execute(
                        "select id from knowledge_chunks where document_id = ?", (document_id,)
                    ).fetchall()
                    for row in chunk_rows:
                        connection.execute(
                            "delete from knowledge_chunks_fts where chunk_id = ?",
                            (str(row["id"]),),
                        )
                    connection.execute(
                        "delete from knowledge_chunks where document_id = ?", (document_id,)
                    )
                    connection.execute(
                        """
                        update knowledge_documents
                        set title = ?, kind = ?, checksum = ?, modified_at = ?,
                            chunk_count = ?, indexed_at = ?
                        where id = ?
                        """,
                        (
                            document.title,
                            document.kind,
                            document.checksum,
                            document.modified_at,
                            len(document.chunks),
                            now,
                            document_id,
                        ),
                    )
                else:
                    cursor = connection.execute(
                        """
                        insert into knowledge_documents
                          (path, title, kind, checksum, modified_at, chunk_count, indexed_at)
                        values (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            document.path,
                            document.title,
                            document.kind,
                            document.checksum,
                            document.modified_at,
                            len(document.chunks),
                            now,
                        ),
                    )
                    if cursor.lastrowid is None:
                        raise RuntimeError("knowledge document insert did not return an id")
                    document_id = cursor.lastrowid

                for index, text in enumerate(document.chunks):
                    excerpt = " ".join(text.split()[:36])
                    cursor = connection.execute(
                        """
                        insert into knowledge_chunks (document_id, chunk_index, text, excerpt)
                        values (?, ?, ?, ?)
                        """,
                        (document_id, index, text, excerpt),
                    )
                    if cursor.lastrowid is None:
                        raise RuntimeError("knowledge chunk insert did not return an id")
                    chunk_id = cursor.lastrowid
                    connection.execute(
                        """
                        insert into knowledge_chunks_fts (chunk_id, title, path, text)
                        values (?, ?, ?, ?)
                        """,
                        (str(chunk_id), document.title, document.path, text),
                    )
                self._add_audit_event(
                    connection,
                    "knowledge.ingested",
                    document.path,
                    f"Indexed {document.title}",
                )
                document_ids.append(document_id)

        persisted: list[KnowledgeDocument] = []
        for document_id in document_ids:
            persisted_document = self.get_knowledge_document(document_id)
            if persisted_document is not None:
                persisted.append(persisted_document)
        if len(persisted) != len(document_ids):
            raise RuntimeError("knowledge document was not persisted")
        return persisted

    def get_knowledge_document(self, document_id: int) -> KnowledgeDocument | None:
        with self._connect() as connection:
            row = connection.execute(
                "select * from knowledge_documents where id = ?", (document_id,)
            ).fetchone()
        return KnowledgeDocument(**dict(row)) if row else None

    def list_knowledge_documents(self) -> list[KnowledgeDocument]:
        with self._connect() as connection:
            rows = connection.execute(
                "select * from knowledge_documents order by title, path"
            ).fetchall()
        return [KnowledgeDocument(**dict(row)) for row in rows]

    def knowledge_chunk_count(self) -> int:
        with self._connect() as connection:
            row = connection.execute("select count(*) as count from knowledge_chunks").fetchone()
        return int(row["count"])

    def search_knowledge_chunks(self, query: str, limit: int = 3) -> list[KnowledgeChunk]:
        bounded_limit = _bounded_search_limit(limit)
        fts_query = _fts_query(query)
        if not fts_query:
            return []
        with self._connect() as connection:
            rows = connection.execute(
                """
                select
                  c.id,
                  c.document_id,
                  d.title,
                  d.path,
                  c.chunk_index,
                  c.text,
                  c.excerpt,
                  bm25(knowledge_chunks_fts) as rank
                from knowledge_chunks_fts
                join knowledge_chunks c on c.id = cast(knowledge_chunks_fts.chunk_id as integer)
                join knowledge_documents d on d.id = c.document_id
                where knowledge_chunks_fts match ?
                order by rank, d.title, c.chunk_index
                limit ?
                """,
                (fts_query, bounded_limit),
            ).fetchall()
        return [
            KnowledgeChunk(
                id=int(row["id"]),
                document_id=int(row["document_id"]),
                title=str(row["title"]),
                path=str(row["path"]),
                chunk_index=int(row["chunk_index"]),
                text=str(row["text"]),
                excerpt=str(row["excerpt"]),
            )
            for row in rows
        ]


def _fts_query(query: str) -> str:
    import re

    tokens = re.findall(r"[A-Za-z0-9_]{2,}", query.lower())
    unique_tokens = list(dict.fromkeys(tokens))
    return " OR ".join(f"{token}*" for token in unique_tokens[:12])


def _bounded_search_limit(limit: int) -> int:
    return min(max(limit, 1), MAX_SEARCH_LIMIT)


def _workflow_status_for_approval(status: str) -> str:
    if status == "approved":
        return "approved"
    if status == "rejected":
        return "rejected"
    return "pending_approval"
