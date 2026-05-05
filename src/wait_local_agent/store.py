from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from wait_local_agent.models import AuditEvent, Ticket, utc_now


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
