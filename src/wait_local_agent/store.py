from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING

from wait_local_agent.models import (
    ApprovalRequest,
    AssetObservation,
    AuditEvent,
    CanonicalAsset,
    CollectorRun,
    CollectorSource,
    ConfigDiff,
    ConfigSnapshot,
    EventHistoryEntry,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeDocumentWrite,
    RestoreExercise,
    ScheduledJob,
    Ticket,
    WorkflowRun,
    utc_now,
)

if TYPE_CHECKING:
    from wait_local_agent.collectors import CollectorResult
    from wait_local_agent.reports.models import GeneratedReport

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
                    status text not null,
                    client_id text
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
                    created_at text not null,
                    client_id text,
                    approver_id text
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
                    updated_at text not null,
                    execution_status text not null default 'not_started',
                    execution_message text not null default '',
                    executed_at text not null default '',
                    execution_result_json text not null default '{}',
                    client_id text,
                    approver_id text
                )
                """
            )
            self._ensure_column(
                connection,
                "approval_requests",
                "execution_status",
                "text not null default 'not_started'",
            )
            self._ensure_column(
                connection,
                "approval_requests",
                "execution_message",
                "text not null default ''",
            )
            self._ensure_column(
                connection,
                "approval_requests",
                "executed_at",
                "text not null default ''",
            )
            self._ensure_column(
                connection,
                "approval_requests",
                "execution_result_json",
                "text not null default '{}'",
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
                    created_at text not null,
                    client_id text
                )
                """
            )
            self._ensure_column(connection, "event_history", "client_id", "text")
            connection.execute(
                """
                create table if not exists workflow_runs (
                    id integer primary key autoincrement,
                    template_id text not null,
                    ticket_id text not null,
                    status text not null,
                    message text not null,
                    approval_request_id integer,
                    client_id text,
                    created_at text not null,
                    updated_at text not null
                )
                """
            )
            connection.execute(
                """
                create table if not exists scheduled_jobs (
                    id integer primary key autoincrement,
                    template_id text not null,
                    cron text not null,
                    params_json text not null,
                    paused integer not null default 0,
                    created_at text not null,
                    updated_at text not null,
                    client_id text
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
                    indexed_at text not null,
                    client_id text
                )
                """
            )
            self._ensure_column(connection, "tickets", "client_id", "text")
            self._ensure_column(connection, "audit_events", "client_id", "text")
            self._ensure_column(connection, "audit_events", "approver_id", "text")
            self._ensure_column(connection, "approval_requests", "client_id", "text")
            self._ensure_column(connection, "approval_requests", "approver_id", "text")
            self._ensure_column(connection, "workflow_runs", "client_id", "text")
            self._ensure_column(connection, "scheduled_jobs", "client_id", "text")
            self._ensure_column(connection, "knowledge_documents", "client_id", "text")
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
            connection.execute(
                """
                create table if not exists reports (
                    id text primary key,
                    report_type text not null,
                    title text not null,
                    created_at text not null,
                    created_by text not null default '',
                    client_id text not null default '',
                    project_id text not null default '',
                    sections_json text not null,
                    metadata_json text not null default '{}'
                )
                """
            )
            connection.execute(
                """
                create table if not exists collector_sources (
                    id integer primary key autoincrement,
                    module_id text not null,
                    name text not null,
                    config_json text not null,
                    config_hash text not null,
                    created_at text not null,
                    updated_at text not null,
                    client_id text,
                    unique(module_id, config_hash, client_id)
                )
                """
            )
            connection.execute(
                """
                create table if not exists collector_runs (
                    id integer primary key autoincrement,
                    module_id text not null,
                    source_id integer references collector_sources(id),
                    status text not null,
                    mode text not null,
                    scope_json text not null,
                    preview_json text not null,
                    result_json text not null default '{}',
                    started_at text not null,
                    completed_at text not null default '',
                    client_id text,
                    actor_id text,
                    report_id text
                )
                """
            )
            connection.execute(
                """
                create table if not exists canonical_assets (
                    id integer primary key autoincrement,
                    canonical_id text not null unique,
                    asset_type text not null,
                    display_name text not null,
                    client_id text,
                    owner text not null default '',
                    source_module text not null default '',
                    source_id text not null default '',
                    confidence real not null default 1.0,
                    first_seen text not null,
                    last_seen text not null,
                    attributes_json text not null
                )
                """
            )
            connection.execute(
                """
                create table if not exists asset_observations (
                    id integer primary key autoincrement,
                    asset_id integer not null references canonical_assets(id),
                    run_id integer not null references collector_runs(id),
                    source_id integer references collector_sources(id),
                    observed_at text not null,
                    observation_type text not null,
                    payload_json text not null,
                    confidence real not null default 1.0
                )
                """
            )
            connection.execute(
                """
                create table if not exists config_snapshots (
                    id integer primary key autoincrement,
                    run_id integer not null references collector_runs(id),
                    asset_id integer references canonical_assets(id),
                    source_id integer references collector_sources(id),
                    snapshot_type text not null,
                    checksum text not null,
                    payload_json text not null,
                    created_at text not null
                )
                """
            )
            connection.execute(
                """
                create table if not exists config_diffs (
                    id integer primary key autoincrement,
                    baseline_snapshot_id integer references config_snapshots(id),
                    candidate_snapshot_id integer references config_snapshots(id),
                    asset_id integer references canonical_assets(id),
                    diff_type text not null,
                    severity text not null,
                    summary text not null,
                    payload_json text not null,
                    created_at text not null
                )
                """
            )
            connection.execute(
                """
                create table if not exists restore_exercises (
                    id integer primary key autoincrement,
                    run_id integer references collector_runs(id),
                    asset_id integer references canonical_assets(id),
                    source_id integer references collector_sources(id),
                    exercise_id text not null,
                    status text not null,
                    target text not null,
                    backup_artifact_id text not null,
                    validation_json text not null,
                    evidence_json text not null,
                    started_at text not null,
                    completed_at text not null,
                    client_id text
                )
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
                    insert into tickets (id, client, subject, body, priority, status, client_id)
                    values (?, ?, ?, ?, ?, ?, ?)
                    on conflict(id) do update set
                      client=excluded.client,
                      subject=excluded.subject,
                      body=excluded.body,
                      priority=excluded.priority,
                      status=excluded.status,
                      client_id=coalesce(excluded.client_id, tickets.client_id)
                    """,
                    (
                        ticket.id,
                        ticket.client,
                        ticket.subject,
                        ticket.body,
                        ticket.priority,
                        ticket.status,
                        _normalize_client_id(ticket.client_id),
                    ),
                )
                self._add_audit_event(
                    connection,
                    "ticket.ingested",
                    ticket.id,
                    f"Imported {ticket.subject}",
                    client_id=_normalize_client_id(ticket.client_id),
                )
        return len(tickets)

    def list_tickets(self, client_id: str | None = None) -> list[Ticket]:
        normalized_client_id = _normalize_client_id(client_id)
        with self._connect() as connection:
            if normalized_client_id is None:
                rows = connection.execute("select * from tickets order by id").fetchall()
            else:
                rows = connection.execute(
                    "select * from tickets where client_id = ? order by id",
                    (normalized_client_id,),
                ).fetchall()
        return [Ticket(**dict(row)) for row in rows]

    def get_ticket(self, ticket_id: str) -> Ticket | None:
        with self._connect() as connection:
            row = connection.execute("select * from tickets where id = ?", (ticket_id,)).fetchone()
        return Ticket(**dict(row)) if row else None

    def set_approval(self, ticket_id: str, status: str, comment: str = "") -> None:
        ticket = self.get_ticket(ticket_id)
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
        self.add_audit_event(
            "approval.updated",
            ticket_id,
            detail,
            client_id=ticket.client_id if ticket is not None else None,
        )

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
        self,
        subject_id: str,
        action_type: str,
        payload: dict[str, object],
        *,
        client_id: str | None = None,
    ) -> ApprovalRequest:
        now = utc_now()
        payload_json = json.dumps(payload, sort_keys=True)
        normalized_client_id = _normalize_client_id(client_id)
        with self._connect() as connection:
            cursor = connection.execute(
                """
                insert into approval_requests
                  (
                    subject_id,
                    action_type,
                    payload_json,
                    status,
                    comment,
                    created_at,
                    updated_at,
                    client_id
                  )
                values (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (subject_id, action_type, payload_json, "pending", "", now, now, normalized_client_id),
            )
            if cursor.lastrowid is None:
                raise RuntimeError("approval request insert did not return an id")
            request_id = int(cursor.lastrowid)
            self._add_audit_event(
                connection,
                "approval.requested",
                subject_id,
                f"{action_type} approval requested",
                client_id=normalized_client_id,
            )
            self._add_event_history(
                connection,
                "approval.requested",
                subject_id,
                "pending",
                f"{action_type} waiting for technician approval",
                payload_json,
                normalized_client_id,
            )
        request = self.get_approval_request(request_id)
        if request is None:
            raise RuntimeError("approval request was not persisted")
        return request

    def update_approval_request(
        self,
        request_id: int,
        status: str,
        comment: str = "",
        *,
        approver_id: str | None = None,
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
                set status = ?, comment = ?, updated_at = ?, approver_id = coalesce(?, approver_id)
                where id = ?
                """,
                (status, comment, now, approver_id, request_id),
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
                client_id=str(row["client_id"]) if row["client_id"] is not None else None,
                approver_id=approver_id,
            )
            self._add_event_history(
                connection,
                "approval_request.updated",
                str(row["subject_id"]),
                status,
                comment or f"{row['action_type']} {status}",
                str(row["payload_json"]),
                str(row["client_id"]) if row["client_id"] is not None else None,
            )
        request = self.get_approval_request(request_id)
        if request is None:
            raise RuntimeError("approval request was not persisted")
        return request

    def update_approval_request_payload(
        self, request_id: int, payload: dict[str, object], comment: str = ""
    ) -> ApprovalRequest:
        now = utc_now()
        payload_json = json.dumps(payload, sort_keys=True)
        with self._connect() as connection:
            row = connection.execute(
                "select * from approval_requests where id = ?", (request_id,)
            ).fetchone()
            if row is None:
                raise KeyError(request_id)
            if str(row["status"]) != "pending":
                raise PermissionError("approval payload can only be edited while pending")
            connection.execute(
                """
                update approval_requests
                set payload_json = ?, comment = ?, updated_at = ?
                where id = ?
                """,
                (payload_json, comment, now, request_id),
            )
            subject_id = str(row["subject_id"])
            action_type = str(row["action_type"])
            message = comment or f"{action_type} payload edited"
            self._add_audit_event(
                connection,
                "approval_request.edited",
                subject_id,
                message,
                client_id=str(row["client_id"]) if row["client_id"] is not None else None,
            )
            self._add_event_history(
                connection,
                "approval_request.edited",
                subject_id,
                "pending",
                message,
                payload_json,
                str(row["client_id"]) if row["client_id"] is not None else None,
            )
        request = self.get_approval_request(request_id)
        if request is None:
            raise RuntimeError("approval request was not persisted")
        return request

    def record_approval_execution(
        self,
        request_id: int,
        *,
        status: str,
        message: str,
        result: dict[str, object],
    ) -> ApprovalRequest:
        now = utc_now()
        result_json = json.dumps(result, sort_keys=True)
        with self._connect() as connection:
            row = connection.execute(
                "select * from approval_requests where id = ?", (request_id,)
            ).fetchone()
            if row is None:
                raise KeyError(request_id)
            connection.execute(
                """
                update approval_requests
                set execution_status = ?, execution_message = ?,
                    executed_at = ?, execution_result_json = ?, updated_at = ?
                where id = ?
                """,
                (status, message, now, result_json, now, request_id),
            )
            action_type = str(row["action_type"])
            subject_id = str(row["subject_id"])
            detail = f"{action_type} execution {status}: {message}"
            self._add_audit_event(
                connection,
                "halopsa.write",
                subject_id,
                detail,
                client_id=str(row["client_id"]) if row["client_id"] is not None else None,
                approver_id=str(row["approver_id"]) if row["approver_id"] is not None else None,
            )
            self._add_event_history(
                connection,
                "halopsa.write",
                subject_id,
                status,
                message,
                result_json,
                str(row["client_id"]) if row["client_id"] is not None else None,
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

    def list_approval_requests(self, client_id: str | None = None) -> list[ApprovalRequest]:
        normalized_client_id = _normalize_client_id(client_id)
        with self._connect() as connection:
            if normalized_client_id is None:
                rows = connection.execute(
                    "select * from approval_requests order by id desc"
                ).fetchall()
            else:
                rows = connection.execute(
                    "select * from approval_requests where client_id = ? order by id desc",
                    (normalized_client_id,),
                ).fetchall()
        return [ApprovalRequest(**dict(row)) for row in rows]

    def add_audit_event(
        self,
        event_type: str,
        subject_id: str,
        detail: str,
        *,
        client_id: str | None = None,
        approver_id: str | None = None,
    ) -> None:
        with self._connect() as connection:
            self._add_audit_event(
                connection,
                event_type,
                subject_id,
                detail,
                client_id=client_id,
                approver_id=approver_id,
            )
            self._add_event_history(
                connection,
                event_type,
                subject_id,
                "completed",
                detail,
                "{}",
                client_id,
            )

    @staticmethod
    def _add_audit_event(
        connection: sqlite3.Connection,
        event_type: str,
        subject_id: str,
        detail: str,
        *,
        client_id: str | None = None,
        approver_id: str | None = None,
    ) -> None:
        connection.execute(
            """
            insert into audit_events
              (event_type, subject_id, detail, created_at, client_id, approver_id)
            values (?, ?, ?, ?, ?, ?)
            """,
            (
                event_type,
                subject_id,
                detail,
                utc_now(),
                _normalize_client_id(client_id),
                approver_id,
            ),
        )

    @staticmethod
    def _add_event_history(
        connection: sqlite3.Connection,
        event_type: str,
        subject_id: str,
        status: str,
        message: str,
        payload_json: str,
        client_id: str | None = None,
    ) -> None:
        connection.execute(
            """
            insert into event_history
              (event_type, subject_id, status, message, payload_json, created_at, client_id)
            values (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_type,
                subject_id,
                status,
                message,
                payload_json,
                utc_now(),
                _normalize_client_id(client_id),
            ),
        )

    def list_audit_events(self, client_id: str | None = None) -> list[AuditEvent]:
        normalized_client_id = _normalize_client_id(client_id)
        with self._connect() as connection:
            if normalized_client_id is None:
                rows = connection.execute("select * from audit_events order by id desc").fetchall()
            else:
                rows = connection.execute(
                    "select * from audit_events where client_id = ? order by id desc",
                    (normalized_client_id,),
                ).fetchall()
        return [AuditEvent(**dict(row)) for row in rows]

    def list_event_history(self, client_id: str | None = None) -> list[EventHistoryEntry]:
        normalized_client_id = _normalize_client_id(client_id)
        with self._connect() as connection:
            if normalized_client_id is None:
                rows = connection.execute("select * from event_history order by id desc").fetchall()
            else:
                rows = connection.execute(
                    "select * from event_history where client_id = ? order by id desc",
                    (normalized_client_id,),
                ).fetchall()
        return [EventHistoryEntry(**dict(row)) for row in rows]

    def create_workflow_run(
        self,
        template_id: str,
        ticket_id: str,
        status: str,
        message: str,
        approval_request_id: int | None = None,
        *,
        client_id: str | None = None,
    ) -> WorkflowRun:
        now = utc_now()
        normalized_client_id = _normalize_client_id(client_id)
        with self._connect() as connection:
            cursor = connection.execute(
                """
                insert into workflow_runs
                  (
                    template_id,
                    ticket_id,
                    status,
                    message,
                    approval_request_id,
                    client_id,
                    created_at,
                    updated_at
                  )
                values (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    template_id,
                    ticket_id,
                    status,
                    message,
                    approval_request_id,
                    normalized_client_id,
                    now,
                    now,
                ),
            )
            if cursor.lastrowid is None:
                raise RuntimeError("workflow run insert did not return an id")
            run_id = int(cursor.lastrowid)
            self._add_audit_event(
                connection,
                "workflow.run_created",
                ticket_id,
                message,
                client_id=normalized_client_id,
            )
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

    def list_workflow_runs(self, client_id: str | None = None) -> list[WorkflowRun]:
        normalized_client_id = _normalize_client_id(client_id)
        with self._connect() as connection:
            if normalized_client_id is None:
                rows = connection.execute("select * from workflow_runs order by id desc").fetchall()
            else:
                rows = connection.execute(
                    "select * from workflow_runs where client_id = ? order by id desc",
                    (normalized_client_id,),
                ).fetchall()
        return [WorkflowRun(**dict(row)) for row in rows]

    def get_workflow_run_for_approval(self, approval_request_id: int) -> WorkflowRun | None:
        with self._connect() as connection:
            row = connection.execute(
                "select * from workflow_runs where approval_request_id = ?",
                (approval_request_id,),
            ).fetchone()
        return WorkflowRun(**dict(row)) if row else None

    def create_scheduled_job(
        self,
        template_id: str,
        cron: str,
        params: dict[str, object],
        *,
        paused: bool = False,
        client_id: str | None = None,
    ) -> ScheduledJob:
        now = utc_now()
        params_json = json.dumps(params, sort_keys=True)
        normalized_client_id = _normalize_client_id(client_id)
        with self._connect() as connection:
            cursor = connection.execute(
                """
                insert into scheduled_jobs
                  (
                    template_id,
                    cron,
                    params_json,
                    paused,
                    created_at,
                    updated_at,
                    client_id
                  )
                values (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    template_id,
                    cron,
                    params_json,
                    int(paused),
                    now,
                    now,
                    normalized_client_id,
                ),
            )
            if cursor.lastrowid is None:
                raise RuntimeError("scheduled job insert did not return an id")
            job_id = int(cursor.lastrowid)
            self._add_audit_event(
                connection,
                "scheduled_job.created",
                str(job_id),
                f"{template_id} scheduled with cron {cron}",
                client_id=normalized_client_id,
            )
            self._add_event_history(
                connection,
                "scheduled_job.created",
                str(job_id),
                "paused" if paused else "scheduled",
                f"{template_id} scheduled with cron {cron}",
                params_json,
                normalized_client_id,
            )
        job = self.get_scheduled_job(job_id)
        if job is None:
            raise RuntimeError("scheduled job was not persisted")
        return job

    def get_scheduled_job(self, job_id: int) -> ScheduledJob | None:
        with self._connect() as connection:
            row = connection.execute(
                "select * from scheduled_jobs where id = ?",
                (job_id,),
            ).fetchone()
        return _scheduled_job_from_row(row) if row else None

    def list_scheduled_jobs(self, client_id: str | None = None) -> list[ScheduledJob]:
        normalized_client_id = _normalize_client_id(client_id)
        with self._connect() as connection:
            if normalized_client_id is None:
                rows = connection.execute(
                    "select * from scheduled_jobs order by id desc"
                ).fetchall()
            else:
                rows = connection.execute(
                    "select * from scheduled_jobs where client_id = ? order by id desc",
                    (normalized_client_id,),
                ).fetchall()
        return [_scheduled_job_from_row(row) for row in rows]

    def update_scheduled_job_paused(self, job_id: int, paused: bool) -> ScheduledJob:
        now = utc_now()
        with self._connect() as connection:
            row = connection.execute(
                "select * from scheduled_jobs where id = ?",
                (job_id,),
            ).fetchone()
            if row is None:
                raise KeyError(job_id)
            connection.execute(
                """
                update scheduled_jobs
                set paused = ?, updated_at = ?
                where id = ?
                """,
                (int(paused), now, job_id),
            )
            template_id = str(row["template_id"])
            detail = "paused" if paused else "resumed"
            self._add_audit_event(
                connection,
                f"scheduled_job.{detail}",
                str(job_id),
                f"{template_id} {detail}",
                client_id=str(row["client_id"]) if row["client_id"] is not None else None,
            )
            self._add_event_history(
                connection,
                f"scheduled_job.{detail}",
                str(job_id),
                detail,
                f"{template_id} {detail}",
                str(row["params_json"]),
                str(row["client_id"]) if row["client_id"] is not None else None,
            )
        job = self.get_scheduled_job(job_id)
        if job is None:
            raise RuntimeError("scheduled job was not persisted")
        return job

    def delete_scheduled_job(self, job_id: int) -> ScheduledJob:
        with self._connect() as connection:
            row = connection.execute(
                "select * from scheduled_jobs where id = ?",
                (job_id,),
            ).fetchone()
            if row is None:
                raise KeyError(job_id)
            connection.execute("delete from scheduled_jobs where id = ?", (job_id,))
            self._add_audit_event(
                connection,
                "scheduled_job.deleted",
                str(job_id),
                f"{row['template_id']} removed",
                client_id=str(row["client_id"]) if row["client_id"] is not None else None,
            )
            self._add_event_history(
                connection,
                "scheduled_job.deleted",
                str(job_id),
                "deleted",
                f"{row['template_id']} removed",
                str(row["params_json"]),
                str(row["client_id"]) if row["client_id"] is not None else None,
            )
        return _scheduled_job_from_row(row)

    def list_event_history_for_subject(self, subject_id: str) -> list[EventHistoryEntry]:
        with self._connect() as connection:
            rows = connection.execute(
                "select * from event_history where subject_id = ? order by id desc",
                (subject_id,),
            ).fetchall()
        return [EventHistoryEntry(**dict(row)) for row in rows]

    def upsert_knowledge_document(
        self,
        *,
        path: str,
        title: str,
        kind: str,
        checksum: str,
        modified_at: str,
        chunks: list[str],
        client_id: str | None = None,
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
            ],
            client_id=client_id,
        )[0]

    def upsert_knowledge_documents(
        self,
        documents: list[KnowledgeDocumentWrite],
        *,
        client_id: str | None = None,
    ) -> list[KnowledgeDocument]:
        if not documents:
            return []
        now = utc_now()
        normalized_client_id = _normalize_client_id(client_id)
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
                            chunk_count = ?, indexed_at = ?, client_id = coalesce(?, client_id)
                        where id = ?
                        """,
                        (
                            document.title,
                            document.kind,
                            document.checksum,
                            document.modified_at,
                            len(document.chunks),
                            now,
                            normalized_client_id,
                            document_id,
                        ),
                    )
                else:
                    cursor = connection.execute(
                        """
                        insert into knowledge_documents
                          (
                            path,
                            title,
                            kind,
                            checksum,
                            modified_at,
                            chunk_count,
                            indexed_at,
                            client_id
                          )
                        values (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            document.path,
                            document.title,
                            document.kind,
                            document.checksum,
                            document.modified_at,
                            len(document.chunks),
                            now,
                            normalized_client_id,
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
                    client_id=normalized_client_id,
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

    def list_knowledge_documents(self, client_id: str | None = None) -> list[KnowledgeDocument]:
        normalized_client_id = _normalize_client_id(client_id)
        with self._connect() as connection:
            if normalized_client_id is None:
                rows = connection.execute(
                    "select * from knowledge_documents order by title, path"
                ).fetchall()
            else:
                rows = connection.execute(
                    "select * from knowledge_documents where client_id = ? order by title, path",
                    (normalized_client_id,),
                ).fetchall()
        return [KnowledgeDocument(**dict(row)) for row in rows]

    def knowledge_chunk_count(self) -> int:
        with self._connect() as connection:
            row = connection.execute("select count(*) as count from knowledge_chunks").fetchone()
        return int(row["count"])

    def search_knowledge_chunks(
        self,
        query: str,
        limit: int = 3,
        client_id: str | None = None,
    ) -> list[KnowledgeChunk]:
        bounded_limit = _bounded_search_limit(limit)
        fts_query = _fts_query(query)
        if not fts_query:
            return []
        normalized_client_id = _normalize_client_id(client_id)
        with self._connect() as connection:
            rows = connection.execute(
                """
                select
                  c.id,
                  c.document_id,
                  d.title,
                  d.path,
                  d.client_id,
                  c.chunk_index,
                  c.text,
                  c.excerpt,
                  bm25(knowledge_chunks_fts) as rank
                from knowledge_chunks_fts
                join knowledge_chunks c on c.id = cast(knowledge_chunks_fts.chunk_id as integer)
                join knowledge_documents d on d.id = c.document_id
                where knowledge_chunks_fts match ?
                  and (? is null or d.client_id = ?)
                order by rank, d.title, c.chunk_index
                limit ?
                """,
                (fts_query, normalized_client_id, normalized_client_id, bounded_limit),
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
                client_id=str(row["client_id"]) if row["client_id"] is not None else None,
            )
            for row in rows
        ]

    def list_knowledge_chunks_for_document(self, document_id: int) -> list[KnowledgeChunk]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                select
                  c.id,
                  c.document_id,
                  d.title,
                  d.path,
                  d.client_id,
                  c.chunk_index,
                  c.text,
                  c.excerpt
                from knowledge_chunks c
                join knowledge_documents d on d.id = c.document_id
                where c.document_id = ?
                order by c.chunk_index
                """,
                (document_id,),
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
                client_id=str(row["client_id"]) if row["client_id"] is not None else None,
            )
            for row in rows
        ]

    def upsert_collector_source(
        self,
        *,
        module_id: str,
        name: str,
        config: dict[str, object],
        client_id: str | None = None,
    ) -> CollectorSource:
        now = utc_now()
        normalized_client_id = _normalize_client_id(client_id)
        config_json = _json_dumps(config)
        config_hash = hashlib.sha256(config_json.encode("utf-8")).hexdigest()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                insert into collector_sources
                  (module_id, name, config_json, config_hash, created_at, updated_at, client_id)
                values (?, ?, ?, ?, ?, ?, ?)
                on conflict(module_id, config_hash, client_id) do update set
                  name=excluded.name,
                  config_json=excluded.config_json,
                  updated_at=excluded.updated_at
                """,
                (module_id, name, config_json, config_hash, now, now, normalized_client_id),
            )
            source_id = cursor.lastrowid
            if source_id is None or source_id == 0:
                row = connection.execute(
                    """
                    select id from collector_sources
                    where module_id = ? and config_hash = ?
                      and ((? is null and client_id is null) or client_id = ?)
                    """,
                    (module_id, config_hash, normalized_client_id, normalized_client_id),
                ).fetchone()
                if row is None:
                    raise RuntimeError("collector source upsert did not return an id")
                source_id = int(row["id"])
            self._add_audit_event(
                connection,
                "collector.source_registered",
                str(source_id),
                f"{module_id} source {name}",
                client_id=normalized_client_id,
            )
        source = self.get_collector_source(int(source_id))
        if source is None:
            raise RuntimeError("collector source was not persisted")
        return source

    def get_collector_source(self, source_id: int) -> CollectorSource | None:
        with self._connect() as connection:
            row = connection.execute(
                "select * from collector_sources where id = ?",
                (source_id,),
            ).fetchone()
        return CollectorSource(**dict(row)) if row else None

    def list_collector_sources(self, client_id: str | None = None) -> list[CollectorSource]:
        normalized_client_id = _normalize_client_id(client_id)
        with self._connect() as connection:
            if normalized_client_id is None:
                rows = connection.execute(
                    "select * from collector_sources order by updated_at desc, id desc"
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    select * from collector_sources
                    where client_id = ?
                    order by updated_at desc, id desc
                    """,
                    (normalized_client_id,),
                ).fetchall()
        return [CollectorSource(**dict(row)) for row in rows]

    def create_collector_run(
        self,
        *,
        module_id: str,
        source_id: int | None,
        status: str,
        mode: str,
        scope: dict[str, object],
        preview: dict[str, object],
        client_id: str | None = None,
        actor_id: str | None = None,
    ) -> CollectorRun:
        now = utc_now()
        normalized_client_id = _normalize_client_id(client_id)
        with self._connect() as connection:
            cursor = connection.execute(
                """
                insert into collector_runs
                  (
                    module_id,
                    source_id,
                    status,
                    mode,
                    scope_json,
                    preview_json,
                    result_json,
                    started_at,
                    completed_at,
                    client_id,
                    actor_id
                  )
                values (?, ?, ?, ?, ?, ?, '{}', ?, '', ?, ?)
                """,
                (
                    module_id,
                    source_id,
                    status,
                    mode,
                    _json_dumps(scope),
                    _json_dumps(preview),
                    now,
                    normalized_client_id,
                    actor_id,
                ),
            )
            if cursor.lastrowid is None:
                raise RuntimeError("collector run insert did not return an id")
            run_id = int(cursor.lastrowid)
            self._add_audit_event(
                connection,
                "collector.run_started",
                str(run_id),
                f"{module_id} {mode}",
                client_id=normalized_client_id,
                approver_id=actor_id,
            )
            self._add_event_history(
                connection,
                "collector.run_started",
                str(run_id),
                status,
                f"{module_id} {mode}",
                _json_dumps(preview),
                normalized_client_id,
            )
        run = self.get_collector_run(run_id)
        if run is None:
            raise RuntimeError("collector run was not persisted")
        return run

    def complete_collector_run(
        self,
        run_id: int,
        status: str,
        *,
        result: dict[str, object],
    ) -> CollectorRun:
        now = utc_now()
        result_json = _json_dumps(result)
        with self._connect() as connection:
            row = connection.execute(
                "select * from collector_runs where id = ?",
                (run_id,),
            ).fetchone()
            if row is None:
                raise KeyError(run_id)
            connection.execute(
                """
                update collector_runs
                set status = ?, result_json = ?, completed_at = ?
                where id = ?
                """,
                (status, result_json, now, run_id),
            )
            event_type = "collector.run_completed" if status == "completed" else "collector.run_failed"
            self._add_audit_event(
                connection,
                event_type,
                str(run_id),
                f"{row['module_id']} {status}",
                client_id=str(row["client_id"]) if row["client_id"] is not None else None,
                approver_id=str(row["actor_id"]) if row["actor_id"] is not None else None,
            )
            self._add_event_history(
                connection,
                event_type,
                str(run_id),
                status,
                f"{row['module_id']} {status}",
                result_json,
                str(row["client_id"]) if row["client_id"] is not None else None,
            )
        run = self.get_collector_run(run_id)
        if run is None:
            raise RuntimeError("collector run was not persisted")
        return run

    def get_collector_run(self, run_id: int) -> CollectorRun | None:
        with self._connect() as connection:
            row = connection.execute(
                "select * from collector_runs where id = ?",
                (run_id,),
            ).fetchone()
        return CollectorRun(**dict(row)) if row else None

    def list_collector_runs(self, client_id: str | None = None) -> list[CollectorRun]:
        normalized_client_id = _normalize_client_id(client_id)
        with self._connect() as connection:
            if normalized_client_id is None:
                rows = connection.execute(
                    "select * from collector_runs order by id desc"
                ).fetchall()
            else:
                rows = connection.execute(
                    "select * from collector_runs where client_id = ? order by id desc",
                    (normalized_client_id,),
                ).fetchall()
        return [CollectorRun(**dict(row)) for row in rows]

    def set_collector_run_report(self, run_id: int, report_id: str) -> CollectorRun:
        with self._connect() as connection:
            row = connection.execute(
                "select id from collector_runs where id = ?",
                (run_id,),
            ).fetchone()
            if row is None:
                raise KeyError(run_id)
            connection.execute(
                "update collector_runs set report_id = ? where id = ?",
                (report_id, run_id),
            )
        run = self.get_collector_run(run_id)
        if run is None:
            raise RuntimeError("collector run was not persisted")
        return run

    def persist_collector_result(
        self,
        run_id: int,
        source_row_id: int | None,
        module_id: str,
        result: CollectorResult,
        *,
        client_id: str | None = None,
    ) -> None:
        asset_by_canonical_id: dict[str, CanonicalAsset] = {}
        for asset_write in result.assets:
            asset = self.upsert_canonical_asset(
                canonical_id=asset_write.canonical_id,
                asset_type=asset_write.asset_type,
                display_name=asset_write.display_name,
                attributes=asset_write.attributes,
                client_id=asset_write.client_id or client_id,
                owner=asset_write.owner,
                source_module=asset_write.source_module or module_id,
                source_id=asset_write.source_id,
                confidence=asset_write.confidence,
            )
            asset_by_canonical_id[asset.canonical_id] = asset
        for observation in result.observations:
            asset = asset_by_canonical_id.get(observation.canonical_id) or self.get_canonical_asset_by_canonical_id(
                observation.canonical_id
            )
            if asset is None or asset.id is None:
                raise KeyError(f"asset {observation.canonical_id} not found")
            self.add_asset_observation(
                asset_id=asset.id,
                run_id=run_id,
                source_id=source_row_id,
                observation_type=observation.observation_type,
                payload=observation.payload,
                confidence=observation.confidence,
            )
        for snapshot in result.config_snapshots:
            asset_id = self._asset_id_for_canonical_id(snapshot.canonical_id)
            self.add_config_snapshot(
                run_id=run_id,
                asset_id=asset_id,
                source_id=source_row_id,
                snapshot_type=snapshot.snapshot_type,
                payload=snapshot.payload,
                checksum=snapshot.checksum,
            )
        for diff in result.config_diffs:
            self.add_config_diff(
                baseline_snapshot_id=diff.baseline_snapshot_id,
                candidate_snapshot_id=diff.candidate_snapshot_id,
                asset_id=self._asset_id_for_canonical_id(diff.canonical_id),
                diff_type=diff.diff_type,
                severity=diff.severity,
                summary=diff.summary,
                payload=diff.payload,
            )
        for exercise in result.restore_exercises:
            self.add_restore_exercise(
                run_id=run_id,
                asset_id=self._asset_id_for_canonical_id(exercise.canonical_id),
                source_id=source_row_id,
                exercise_id=exercise.exercise_id,
                status=exercise.status,
                target=exercise.target,
                backup_artifact_id=exercise.backup_artifact_id,
                validation=exercise.validation,
                evidence=exercise.evidence,
                started_at=exercise.started_at,
                completed_at=exercise.completed_at,
                client_id=client_id,
            )

    def upsert_canonical_asset(
        self,
        *,
        canonical_id: str,
        asset_type: str,
        display_name: str,
        attributes: dict[str, object],
        client_id: str | None = None,
        owner: str = "",
        source_module: str = "",
        source_id: str = "",
        confidence: float = 1.0,
    ) -> CanonicalAsset:
        now = utc_now()
        normalized_client_id = _normalize_client_id(client_id)
        attributes_json = _json_dumps(attributes)
        with self._connect() as connection:
            cursor = connection.execute(
                """
                insert into canonical_assets
                  (
                    canonical_id,
                    asset_type,
                    display_name,
                    client_id,
                    owner,
                    source_module,
                    source_id,
                    confidence,
                    first_seen,
                    last_seen,
                    attributes_json
                  )
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(canonical_id) do update set
                  asset_type=excluded.asset_type,
                  display_name=excluded.display_name,
                  client_id=coalesce(excluded.client_id, canonical_assets.client_id),
                  owner=excluded.owner,
                  source_module=excluded.source_module,
                  source_id=excluded.source_id,
                  confidence=excluded.confidence,
                  last_seen=excluded.last_seen,
                  attributes_json=excluded.attributes_json
                """,
                (
                    canonical_id,
                    asset_type,
                    display_name,
                    normalized_client_id,
                    owner,
                    source_module,
                    source_id,
                    confidence,
                    now,
                    now,
                    attributes_json,
                ),
            )
            asset_id = cursor.lastrowid
            if asset_id is None or asset_id == 0:
                row = connection.execute(
                    "select id from canonical_assets where canonical_id = ?",
                    (canonical_id,),
                ).fetchone()
                if row is None:
                    raise RuntimeError("canonical asset upsert did not return an id")
                asset_id = int(row["id"])
        asset = self.get_canonical_asset(int(asset_id))
        if asset is None:
            raise RuntimeError("canonical asset was not persisted")
        return asset

    def get_canonical_asset(self, asset_id: int) -> CanonicalAsset | None:
        with self._connect() as connection:
            row = connection.execute(
                "select * from canonical_assets where id = ?",
                (asset_id,),
            ).fetchone()
        return CanonicalAsset(**dict(row)) if row else None

    def get_canonical_asset_by_canonical_id(self, canonical_id: str) -> CanonicalAsset | None:
        with self._connect() as connection:
            row = connection.execute(
                "select * from canonical_assets where canonical_id = ?",
                (canonical_id,),
            ).fetchone()
        return CanonicalAsset(**dict(row)) if row else None

    def list_canonical_assets(
        self,
        *,
        run_id: int | None = None,
        client_id: str | None = None,
    ) -> list[CanonicalAsset]:
        normalized_client_id = _normalize_client_id(client_id)
        with self._connect() as connection:
            if run_id is None:
                rows = connection.execute(
                    """
                    select * from canonical_assets
                    where (? is null or client_id = ?)
                    order by display_name, canonical_id
                    """,
                    (normalized_client_id, normalized_client_id),
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    select distinct a.*
                    from canonical_assets a
                    left join asset_observations o on o.asset_id = a.id
                    left join config_snapshots s on s.asset_id = a.id
                    left join restore_exercises r on r.asset_id = a.id
                    where o.run_id = ? or s.run_id = ? or r.run_id = ?
                    order by a.display_name, a.canonical_id
                    """,
                    (run_id, run_id, run_id),
                ).fetchall()
        return [CanonicalAsset(**dict(row)) for row in rows]

    def add_asset_observation(
        self,
        *,
        asset_id: int,
        run_id: int,
        source_id: int | None,
        observation_type: str,
        payload: dict[str, object],
        confidence: float = 1.0,
    ) -> AssetObservation:
        now = utc_now()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                insert into asset_observations
                  (asset_id, run_id, source_id, observed_at, observation_type, payload_json, confidence)
                values (?, ?, ?, ?, ?, ?, ?)
                """,
                (asset_id, run_id, source_id, now, observation_type, _json_dumps(payload), confidence),
            )
            if cursor.lastrowid is None:
                raise RuntimeError("asset observation insert did not return an id")
            observation_id = int(cursor.lastrowid)
        observation = self.get_asset_observation(observation_id)
        if observation is None:
            raise RuntimeError("asset observation was not persisted")
        return observation

    def get_asset_observation(self, observation_id: int) -> AssetObservation | None:
        with self._connect() as connection:
            row = connection.execute(
                "select * from asset_observations where id = ?",
                (observation_id,),
            ).fetchone()
        return AssetObservation(**dict(row)) if row else None

    def list_asset_observations(self, *, run_id: int | None = None) -> list[AssetObservation]:
        with self._connect() as connection:
            if run_id is None:
                rows = connection.execute(
                    "select * from asset_observations order by id"
                ).fetchall()
            else:
                rows = connection.execute(
                    "select * from asset_observations where run_id = ? order by id",
                    (run_id,),
                ).fetchall()
        return [AssetObservation(**dict(row)) for row in rows]

    def add_config_snapshot(
        self,
        *,
        run_id: int,
        asset_id: int | None,
        source_id: int | None,
        snapshot_type: str,
        payload: dict[str, object],
        checksum: str = "",
    ) -> ConfigSnapshot:
        now = utc_now()
        payload_json = _json_dumps(payload)
        stable_checksum = checksum or hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                insert into config_snapshots
                  (run_id, asset_id, source_id, snapshot_type, checksum, payload_json, created_at)
                values (?, ?, ?, ?, ?, ?, ?)
                """,
                (run_id, asset_id, source_id, snapshot_type, stable_checksum, payload_json, now),
            )
            if cursor.lastrowid is None:
                raise RuntimeError("config snapshot insert did not return an id")
            snapshot_id = int(cursor.lastrowid)
            self._add_audit_event(
                connection,
                "collector.snapshot_created",
                str(run_id),
                f"{snapshot_type} checksum={stable_checksum}",
            )
        snapshot = self.get_config_snapshot(snapshot_id)
        if snapshot is None:
            raise RuntimeError("config snapshot was not persisted")
        return snapshot

    def get_config_snapshot(self, snapshot_id: int) -> ConfigSnapshot | None:
        with self._connect() as connection:
            row = connection.execute(
                "select * from config_snapshots where id = ?",
                (snapshot_id,),
            ).fetchone()
        return ConfigSnapshot(**dict(row)) if row else None

    def list_config_snapshots(self, *, run_id: int | None = None) -> list[ConfigSnapshot]:
        with self._connect() as connection:
            if run_id is None:
                rows = connection.execute("select * from config_snapshots order by id").fetchall()
            else:
                rows = connection.execute(
                    "select * from config_snapshots where run_id = ? order by id",
                    (run_id,),
                ).fetchall()
        return [ConfigSnapshot(**dict(row)) for row in rows]

    def add_config_diff(
        self,
        *,
        baseline_snapshot_id: int | None,
        candidate_snapshot_id: int | None,
        asset_id: int | None,
        diff_type: str,
        severity: str,
        summary: str,
        payload: dict[str, object],
    ) -> ConfigDiff:
        now = utc_now()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                insert into config_diffs
                  (
                    baseline_snapshot_id,
                    candidate_snapshot_id,
                    asset_id,
                    diff_type,
                    severity,
                    summary,
                    payload_json,
                    created_at
                  )
                values (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    baseline_snapshot_id,
                    candidate_snapshot_id,
                    asset_id,
                    diff_type,
                    severity,
                    summary,
                    _json_dumps(payload),
                    now,
                ),
            )
            if cursor.lastrowid is None:
                raise RuntimeError("config diff insert did not return an id")
            diff_id = int(cursor.lastrowid)
            self._add_audit_event(
                connection,
                "collector.diff_detected",
                str(candidate_snapshot_id or diff_id),
                f"{severity}: {summary}",
            )
        diff = self.get_config_diff(diff_id)
        if diff is None:
            raise RuntimeError("config diff was not persisted")
        return diff

    def get_config_diff(self, diff_id: int) -> ConfigDiff | None:
        with self._connect() as connection:
            row = connection.execute("select * from config_diffs where id = ?", (diff_id,)).fetchone()
        return ConfigDiff(**dict(row)) if row else None

    def list_config_diffs(self, *, run_id: int | None = None) -> list[ConfigDiff]:
        with self._connect() as connection:
            if run_id is None:
                rows = connection.execute("select * from config_diffs order by id").fetchall()
            else:
                rows = connection.execute(
                    """
                    select distinct d.*
                    from config_diffs d
                    left join config_snapshots c on c.id = d.candidate_snapshot_id
                    left join config_snapshots b on b.id = d.baseline_snapshot_id
                    where c.run_id = ? or b.run_id = ?
                    order by d.id
                    """,
                    (run_id, run_id),
                ).fetchall()
        return [ConfigDiff(**dict(row)) for row in rows]

    def add_restore_exercise(
        self,
        *,
        run_id: int | None,
        asset_id: int | None,
        source_id: int | None,
        exercise_id: str,
        status: str,
        target: str,
        backup_artifact_id: str,
        validation: dict[str, object],
        evidence: dict[str, object],
        started_at: str = "",
        completed_at: str = "",
        client_id: str | None = None,
    ) -> RestoreExercise:
        now = utc_now()
        normalized_client_id = _normalize_client_id(client_id)
        with self._connect() as connection:
            cursor = connection.execute(
                """
                insert into restore_exercises
                  (
                    run_id,
                    asset_id,
                    source_id,
                    exercise_id,
                    status,
                    target,
                    backup_artifact_id,
                    validation_json,
                    evidence_json,
                    started_at,
                    completed_at,
                    client_id
                  )
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    asset_id,
                    source_id,
                    exercise_id,
                    status,
                    target,
                    backup_artifact_id,
                    _json_dumps(validation),
                    _json_dumps(evidence),
                    started_at or now,
                    completed_at or now,
                    normalized_client_id,
                ),
            )
            if cursor.lastrowid is None:
                raise RuntimeError("restore exercise insert did not return an id")
            row_id = int(cursor.lastrowid)
            self._add_audit_event(
                connection,
                "collector.restore_exercise_recorded",
                str(run_id or row_id),
                f"{exercise_id} {status}",
                client_id=normalized_client_id,
            )
        exercise = self.get_restore_exercise(row_id)
        if exercise is None:
            raise RuntimeError("restore exercise was not persisted")
        return exercise

    def get_restore_exercise(self, row_id: int) -> RestoreExercise | None:
        with self._connect() as connection:
            row = connection.execute(
                "select * from restore_exercises where id = ?",
                (row_id,),
            ).fetchone()
        return RestoreExercise(**dict(row)) if row else None

    def list_restore_exercises(self, *, run_id: int | None = None) -> list[RestoreExercise]:
        with self._connect() as connection:
            if run_id is None:
                rows = connection.execute("select * from restore_exercises order by id").fetchall()
            else:
                rows = connection.execute(
                    "select * from restore_exercises where run_id = ? order by id",
                    (run_id,),
                ).fetchall()
        return [RestoreExercise(**dict(row)) for row in rows]

    def _asset_id_for_canonical_id(self, canonical_id: str | None) -> int | None:
        if not canonical_id:
            return None
        asset = self.get_canonical_asset_by_canonical_id(canonical_id)
        if asset is None:
            raise KeyError(f"asset {canonical_id} not found")
        return asset.id

    def save_report(self, report: GeneratedReport) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                insert into reports
                  (id, report_type, title, created_at, created_by,
                   client_id, project_id, sections_json, metadata_json)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(id) do update set
                  report_type=excluded.report_type,
                  title=excluded.title,
                  created_at=excluded.created_at,
                  created_by=excluded.created_by,
                  client_id=excluded.client_id,
                  project_id=excluded.project_id,
                  sections_json=excluded.sections_json,
                  metadata_json=excluded.metadata_json
                """,
                (
                    report.id,
                    report.report_type.value,
                    report.title,
                    report.created_at,
                    report.created_by,
                    report.client_id,
                    report.project_id,
                    report.sections_json(),
                    report.metadata_json(),
                ),
            )

    def get_report(self, report_id: str) -> GeneratedReport | None:
        with self._connect() as connection:
            row = connection.execute("select * from reports where id = ?", (report_id,)).fetchone()
        return _report_from_row(row) if row else None

    def list_reports(
        self,
        report_type: str = "",
        client_id: str = "",
        project_id: str = "",
    ) -> list[GeneratedReport]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                select * from reports
                where (? = '' or report_type = ?)
                  and (? = '' or client_id = ?)
                  and (? = '' or project_id = ?)
                order by created_at desc, id
                """,
                (report_type, report_type, client_id, client_id, project_id, project_id),
            ).fetchall()
        return [_report_from_row(row) for row in rows]


def _report_from_row(row: sqlite3.Row) -> GeneratedReport:
    from wait_local_agent.reports.models import GeneratedReport, ReportType, sections_from_json

    return GeneratedReport(
        id=str(row["id"]),
        report_type=ReportType(str(row["report_type"])),
        title=str(row["title"]),
        created_at=str(row["created_at"]),
        created_by=str(row["created_by"]),
        client_id=str(row["client_id"]),
        project_id=str(row["project_id"]),
        sections=sections_from_json(str(row["sections_json"])),
        metadata=json.loads(str(row["metadata_json"])),
    )


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


def _scheduled_job_from_row(row: sqlite3.Row) -> ScheduledJob:
    payload = dict(row)
    payload["paused"] = bool(payload["paused"])
    return ScheduledJob(**payload)


def _json_dumps(payload: dict[str, object]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _normalize_client_id(client_id: str | None) -> str | None:
    if client_id is None:
        return None
    normalized = client_id.strip()
    return normalized or None
