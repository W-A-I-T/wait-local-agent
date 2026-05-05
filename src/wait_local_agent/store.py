from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from wait_local_agent.models import AuditEvent, KnowledgeChunk, KnowledgeDocument, Ticket, utc_now


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
                    updated_at text not null
                )
                """
            )
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

    def set_approval(self, ticket_id: str, status: str) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                insert into approvals (ticket_id, status, updated_at)
                values (?, ?, ?)
                on conflict(ticket_id) do update set
                  status=excluded.status,
                  updated_at=excluded.updated_at
                """,
                (ticket_id, status, utc_now()),
            )
        self.add_audit_event("approval.updated", ticket_id, status)

    def get_approval(self, ticket_id: str) -> str:
        with self._connect() as connection:
            row = connection.execute(
                "select status from approvals where ticket_id = ?", (ticket_id,)
            ).fetchone()
        return str(row["status"]) if row else "pending"

    def add_audit_event(self, event_type: str, subject_id: str, detail: str) -> None:
        with self._connect() as connection:
            self._add_audit_event(connection, event_type, subject_id, detail)

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

    def list_audit_events(self) -> list[AuditEvent]:
        with self._connect() as connection:
            rows = connection.execute("select * from audit_events order by id desc").fetchall()
        return [AuditEvent(**dict(row)) for row in rows]

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
        now = utc_now()
        with self._connect() as connection:
            existing = connection.execute(
                "select id from knowledge_documents where path = ?", (path,)
            ).fetchone()
            if existing:
                document_id = int(existing["id"])
                chunk_rows = connection.execute(
                    "select id from knowledge_chunks where document_id = ?", (document_id,)
                ).fetchall()
                for row in chunk_rows:
                    connection.execute(
                        "delete from knowledge_chunks_fts where chunk_id = ?", (str(row["id"]),)
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
                    (title, kind, checksum, modified_at, len(chunks), now, document_id),
                )
            else:
                cursor = connection.execute(
                    """
                    insert into knowledge_documents
                      (path, title, kind, checksum, modified_at, chunk_count, indexed_at)
                    values (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (path, title, kind, checksum, modified_at, len(chunks), now),
                )
                document_id = int(cursor.lastrowid)

            for index, text in enumerate(chunks):
                excerpt = " ".join(text.split()[:36])
                cursor = connection.execute(
                    """
                    insert into knowledge_chunks (document_id, chunk_index, text, excerpt)
                    values (?, ?, ?, ?)
                    """,
                    (document_id, index, text, excerpt),
                )
                chunk_id = int(cursor.lastrowid)
                connection.execute(
                    """
                    insert into knowledge_chunks_fts (chunk_id, title, path, text)
                    values (?, ?, ?, ?)
                    """,
                    (str(chunk_id), title, path, text),
                )
            self._add_audit_event(connection, "knowledge.ingested", path, f"Indexed {title}")

        document = self.get_knowledge_document(document_id)
        if document is None:
            raise RuntimeError("knowledge document was not persisted")
        return document

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
                (fts_query, limit),
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
