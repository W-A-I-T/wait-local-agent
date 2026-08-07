from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING, Literal, cast

from wait_local_agent.models import (
    AgentDefinition,
    AgentDefinitionRevision,
    AgentRun,
    ApprovalRequest,
    AssetObservation,
    AuditEvent,
    CanonicalAsset,
    CollectorRun,
    CollectorSource,
    ConfigDiff,
    ConfigSnapshot,
    EventDelivery,
    EventHistoryEntry,
    ExecutionArtifact,
    ExecutionRun,
    ExecutionStep,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeDocumentWrite,
    RestoreExercise,
    ScheduledJob,
    SmartActionRun,
    Ticket,
    WorkflowRun,
    utc_now,
)

# Opaque capability used only by SmartActionService.  A boolean flag would make
# it too easy for an unrelated caller to reach the smart-action state machine.
SMART_ACTION_APPROVAL_CAPABILITY = object()

if TYPE_CHECKING:
    from wait_local_agent.collectors import CollectorResult
    from wait_local_agent.reports.hardening_checks import (
        CheckResult,
        HardeningCheckResultRecord,
        HardeningRunRecord,
    )
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
                create table if not exists event_deliveries (
                    id integer primary key autoincrement,
                    idempotency_key text not null unique,
                    event_type text not null,
                    entity_type text not null,
                    entity_id text not null,
                    payload_json text not null,
                    status text not null,
                    matched_agent_count integer not null default 0,
                    agent_ids_json text not null default '[]',
                    run_ids_json text not null default '[]',
                    error_detail text not null default '',
                    received_at text not null,
                    processed_at text not null default '',
                    client_id text
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
                    client_id text,
                    created_at text not null,
                    updated_at text not null
                )
                """
            )
            connection.execute(
                """
                create table if not exists smart_action_runs (
                    id integer primary key autoincrement,
                    action_id text not null,
                    actor text not null,
                    status text not null,
                    payload_digest text not null,
                    output_json text not null,
                    evidence_json text not null,
                    approval_id integer,
                    created_at text not null,
                    updated_at text not null,
                    client_id text
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
                    client_id text,
                    job_kind text not null default 'workflow',
                    agent_id text,
                    entity_id text
                )
                """
            )
            connection.execute(
                """
                create table if not exists agent_definitions (
                    id text primary key,
                    name text not null,
                    description text not null,
                    enabled integer not null default 1,
                    trigger text not null,
                    entity_type text not null,
                    filters_json text not null,
                    enabled_tools_json text not null,
                    steps_json text not null,
                    max_steps integer not null,
                    execution_timeout_seconds real not null,
                    client_id text,
                    version integer not null default 1,
                    created_at text not null,
                    updated_at text not null,
                    run_once_per_entity integer not null default 1,
                    depends_on_agent_ids_json text not null default '[]'
                )
                """
            )
            connection.execute(
                """
                create table if not exists agent_definition_revisions (
                    id integer primary key autoincrement,
                    agent_id text not null,
                    version integer not null,
                    definition_json text not null,
                    created_at text not null,
                    client_id text,
                    unique(agent_id, version)
                )
                """
            )
            connection.execute(
                """
                create table if not exists agent_runs (
                    id integer primary key autoincrement,
                    agent_id text not null,
                    entity_id text not null,
                    actor text not null,
                    status text not null,
                    current_step integer not null default 0,
                    state_json text not null,
                    started_at text not null,
                    finished_at text not null,
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
            self._ensure_column(connection, "scheduled_jobs", "job_kind", "text not null default 'workflow'")
            self._ensure_column(connection, "scheduled_jobs", "agent_id", "text")
            self._ensure_column(connection, "scheduled_jobs", "entity_id", "text")
            self._ensure_column(
                connection,
                "agent_definitions",
                "run_once_per_entity",
                "integer not null default 1",
            )
            self._ensure_column(
                connection,
                "agent_definitions",
                "depends_on_agent_ids_json",
                "text not null default '[]'",
            )
            self._ensure_column(connection, "knowledge_documents", "client_id", "text")
            self._ensure_column(connection, "smart_action_runs", "client_id", "text")
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
            self._ensure_column(connection, "reports", "evidence_status", "text not null default 'not_run'")
            connection.execute(
                """
                create table if not exists founder_config (
                    id integer primary key check (id = 1),
                    lp_base_url text not null,
                    lp_project_id text not null,
                    token_vault_ref text not null,
                    created_at text not null,
                    updated_at text not null
                )
                """
            )
            connection.execute(
                """
                create table if not exists founder_artifacts (
                    artifact_id text primary key,
                    project_id text not null,
                    bundle_hash text not null,
                    bundle_json text not null,
                    created_at text not null,
                    previewed_at text not null default '',
                    uploaded_at text not null default '',
                    remote_scan_id text not null default '',
                    remote_scan_status text not null default '',
                    remote_scan_json text not null default '{}',
                    latest_report_reference text not null default '',
                    latest_report_json text not null default '{}',
                    polling_status text not null default ''
                )
                """
            )
            self._ensure_column(connection, "founder_artifacts", "previewed_at", "text not null default ''")
            self._ensure_column(connection, "founder_artifacts", "uploaded_at", "text not null default ''")
            self._ensure_column(connection, "founder_artifacts", "remote_scan_id", "text not null default ''")
            self._ensure_column(connection, "founder_artifacts", "remote_scan_status", "text not null default ''")
            self._ensure_column(connection, "founder_artifacts", "remote_scan_json", "text not null default '{}'")
            self._ensure_column(
                connection,
                "founder_artifacts",
                "latest_report_reference",
                "text not null default ''",
            )
            self._ensure_column(connection, "founder_artifacts", "latest_report_json", "text not null default '{}'")
            self._ensure_column(connection, "founder_artifacts", "polling_status", "text not null default ''")
            connection.execute(
                """
                create table if not exists founder_artifact_previews (
                    artifact_id text primary key,
                    previewed_at text not null
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
            connection.execute(
                """
                create table if not exists hardening_runs (
                    id integer primary key autoincrement,
                    status text not null,
                    expected_check_count integer not null,
                    started_at text not null,
                    completed_at text not null default ''
                )
                """
            )
            connection.execute(
                """
                create table if not exists hardening_check_results (
                    id integer primary key autoincrement,
                    run_id integer not null references hardening_runs(id) on delete cascade,
                    check_id text not null,
                    title text not null,
                    scope text not null,
                    severity text not null,
                    status text not null,
                    evidence_json text not null,
                    remediation_hint text,
                    unique(run_id, check_id)
                )
                """
            )
            connection.execute(
                """
                create table if not exists execution_runs (
                    id integer primary key autoincrement,
                    run_kind text not null,
                    source_run_id integer,
                    actor text not null,
                    client_id text,
                    status text not null,
                    started_at text not null,
                    finished_at text not null,
                    trigger_source text not null default ''
                )
                """
            )
            for column_name, definition in (
                ("run_kind", "text not null default 'workflow'"),
                ("source_run_id", "integer"),
                ("actor", "text not null default 'system'"),
                ("client_id", "text"),
                ("status", "text not null default 'unknown'"),
                ("started_at", "text not null default ''"),
                ("finished_at", "text not null default ''"),
                ("trigger_source", "text not null default ''"),
            ):
                self._ensure_column(connection, "execution_runs", column_name, definition)
            connection.execute(
                """
                create table if not exists execution_steps (
                    id integer primary key autoincrement,
                    execution_run_id integer not null
                      references execution_runs(id) on delete cascade,
                    ordinal integer not null,
                    kind text not null,
                    name text not null,
                    status text not null,
                    started_at text not null,
                    finished_at text not null,
                    input_digest text not null,
                    output_digest text not null,
                    input_json text not null,
                    output_json text not null,
                    error_detail text not null default ''
                )
                """
            )
            for column_name, definition in (
                ("execution_run_id", "integer"),
                ("ordinal", "integer not null default 0"),
                ("kind", "text not null default 'unknown'"),
                ("name", "text not null default ''"),
                ("status", "text not null default 'unknown'"),
                ("started_at", "text not null default ''"),
                ("finished_at", "text not null default ''"),
                ("input_digest", "text not null default ''"),
                ("output_digest", "text not null default ''"),
                ("input_json", "text not null default '{}'"),
                ("output_json", "text not null default '{}'"),
                ("error_detail", "text not null default ''"),
            ):
                self._ensure_column(connection, "execution_steps", column_name, definition)
            connection.execute(
                """
                create table if not exists execution_artifacts (
                    id integer primary key autoincrement,
                    execution_run_id integer not null
                      references execution_runs(id) on delete cascade,
                    step_ordinal integer,
                    name text not null,
                    media_type text not null,
                    byte_size integer not null,
                    sha256 text not null,
                    storage_path text not null
                )
                """
            )
            for column_name, definition in (
                ("execution_run_id", "integer"),
                ("step_ordinal", "integer"),
                ("name", "text not null default ''"),
                ("media_type", "text not null default 'application/octet-stream'"),
                ("byte_size", "integer not null default 0"),
                ("sha256", "text not null default ''"),
                ("storage_path", "text not null default ''"),
            ):
                self._ensure_column(connection, "execution_artifacts", column_name, definition)
            self._backfill_agent_revisions(connection)

    @staticmethod
    def _ensure_column(
        connection: sqlite3.Connection, table_name: str, column_name: str, definition: str
    ) -> None:
        rows = connection.execute(f"pragma table_info({table_name})").fetchall()
        if column_name not in {str(row["name"]) for row in rows}:
            connection.execute(f"alter table {table_name} add column {column_name} {definition}")

    @staticmethod
    def _backfill_agent_revisions(connection: sqlite3.Connection) -> None:
        for row in connection.execute("select * from agent_definitions").fetchall():
            definition = _agent_definition_from_row(row)
            connection.execute(
                """
                insert or ignore into agent_definition_revisions
                  (agent_id, version, definition_json, created_at, client_id)
                values (?, ?, ?, ?, ?)
                """,
                (
                    definition.id,
                    definition.version,
                    _agent_definition_snapshot(definition),
                    definition.updated_at,
                    _normalize_client_id(definition.client_id),
                ),
            )

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

    def get_ticket(self, ticket_id: str, client_id: str | None = None) -> Ticket | None:
        normalized_client_id = _normalize_client_id(client_id)
        with self._connect() as connection:
            if normalized_client_id is None:
                row = connection.execute(
                    "select * from tickets where id = ?", (ticket_id,)
                ).fetchone()
            else:
                row = connection.execute(
                    "select * from tickets where id = ? and client_id = ?",
                    (ticket_id, normalized_client_id),
                ).fetchone()
        return Ticket(**dict(row)) if row else None

    def get_ticket_for_client(
        self, ticket_id: str, client_id: str | None = None
    ) -> Ticket | None:
        return self.get_ticket(ticket_id, client_id)

    def set_approval(self, ticket_id: str, status: str, comment: str = "") -> None:
        safe_comment = _redact_text(comment)
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
                (ticket_id, status, safe_comment, utc_now()),
            )
        detail = status if not safe_comment else f"{status}: {safe_comment}"
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
        return _redact_text(str(row["comment"])) if row else ""

    def create_approval_request(
        self,
        subject_id: str,
        action_type: str,
        payload: dict[str, object],
        *,
        client_id: str | None = None,
    ) -> ApprovalRequest:
        now = utc_now()
        payload_json = _json_dumps(payload)
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
                _redact_json_text(payload_json),
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
        allow_completed: bool = False,
        _smart_action_capability: object | None = None,
    ) -> ApprovalRequest:
        now = utc_now()
        with self._connect() as connection:
            row = connection.execute(
                "select * from approval_requests where id = ?", (request_id,)
            ).fetchone()
            if row is None:
                raise KeyError(request_id)
            current_status = str(row["status"])
            is_smart_action = str(row["action_type"]).startswith("smart_action:")
            if is_smart_action and _smart_action_capability is not SMART_ACTION_APPROVAL_CAPABILITY:
                raise PermissionError("smart-action approvals must be updated through SmartActionService")
            if status not in {"pending", "approved", "rejected"}:
                raise ValueError("approval status must be pending, approved, or rejected")
            if current_status != "pending" and not allow_completed:
                raise PermissionError("approval request has already completed")
            connection.execute(
                """
                update approval_requests
                set status = ?, comment = ?, updated_at = ?, approver_id = coalesce(?, approver_id)
                where id = ?
                """,
                (status, _redact_text(comment), now, approver_id, request_id),
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
                _redact_text(comment or f"{row['action_type']} {status}"),
                _redact_json_text(str(row["payload_json"])),
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
        payload_json = _json_dumps(payload)
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
                (payload_json, _redact_text(comment), now, request_id),
            )
            subject_id = str(row["subject_id"])
            action_type = str(row["action_type"])
            message = _redact_text(comment or f"{action_type} payload edited")
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
                _redact_json_text(payload_json),
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
        result_json = _json_dumps(result)
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
        if row is None:
            return None
        payload = dict(row)
        payload["comment"] = _redact_text(str(payload["comment"]))
        payload["payload_json"] = _redact_json_text(str(payload["payload_json"]))
        payload["execution_result_json"] = _redact_json_text(str(payload["execution_result_json"]))
        return ApprovalRequest(**payload)

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
        requests: list[ApprovalRequest] = []
        for row in rows:
            payload = dict(row)
            payload["comment"] = _redact_text(str(payload["comment"]))
            payload["payload_json"] = _redact_json_text(str(payload["payload_json"]))
            payload["execution_result_json"] = _redact_json_text(str(payload["execution_result_json"]))
            requests.append(ApprovalRequest(**payload))
        return requests

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
        payload_json = _redact_json_text(payload_json)
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
        return [_event_history_from_row(row) for row in rows]

    def create_event_delivery(
        self,
        *,
        idempotency_key: str,
        event_type: str,
        entity_type: str,
        entity_id: str,
        payload: dict[str, object],
        client_id: str | None = None,
    ) -> tuple[EventDelivery, bool]:
        received_at = utc_now()
        normalized_client_id = _normalize_client_id(client_id)
        payload_json = _json_dumps(payload)
        with self._connect() as connection:
            cursor = connection.execute(
                """
                insert or ignore into event_deliveries
                  (idempotency_key, event_type, entity_type, entity_id, payload_json,
                   status, matched_agent_count, agent_ids_json, run_ids_json,
                   error_detail, received_at, processed_at, client_id)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    idempotency_key,
                    event_type,
                    entity_type,
                    entity_id,
                    payload_json,
                    "received",
                    0,
                    "[]",
                    "[]",
                    "",
                    received_at,
                    "",
                    normalized_client_id,
                ),
            )
            created = cursor.rowcount == 1
            row = connection.execute(
                "select * from event_deliveries where idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
            if row is None:
                raise RuntimeError("event delivery was not persisted")
            if created:
                self._add_audit_event(
                    connection,
                    "event.received",
                    str(row["id"]),
                    f"{event_type} received for {entity_id}",
                    client_id=normalized_client_id,
                )
                self._add_event_history(
                    connection,
                    "event.received",
                    str(row["id"]),
                    "received",
                    f"{event_type} received for {entity_id}",
                    payload_json,
                    normalized_client_id,
                )
        return _event_delivery_from_row(row), created

    def update_event_delivery(
        self,
        delivery_id: int,
        *,
        status: str,
        matched_agent_count: int,
        agent_ids: list[str],
        run_ids: list[int],
        error_detail: str = "",
    ) -> EventDelivery:
        processed_at = utc_now()
        safe_error = _redact_text(error_detail)
        with self._connect() as connection:
            cursor = connection.execute(
                """
                update event_deliveries
                set status = ?, matched_agent_count = ?, agent_ids_json = ?,
                    run_ids_json = ?, error_detail = ?, processed_at = ?
                where id = ?
                """,
                (
                    status,
                    matched_agent_count,
                    _json_dumps_value(agent_ids),
                    _json_dumps_value(run_ids),
                    safe_error,
                    processed_at,
                    delivery_id,
                ),
            )
            if cursor.rowcount != 1:
                raise KeyError(delivery_id)
        delivery = self.get_event_delivery(delivery_id)
        if delivery is None:
            raise RuntimeError("event delivery was not persisted")
        return delivery

    def get_event_delivery(self, delivery_id: int, client_id: str | None = None) -> EventDelivery | None:
        normalized_client_id = _normalize_client_id(client_id)
        with self._connect() as connection:
            if normalized_client_id is None:
                row = connection.execute(
                    "select * from event_deliveries where id = ?", (delivery_id,)
                ).fetchone()
            else:
                row = connection.execute(
                    "select * from event_deliveries where id = ? and client_id = ?",
                    (delivery_id, normalized_client_id),
                ).fetchone()
        return _event_delivery_from_row(row) if row else None

    def list_event_deliveries(self, client_id: str | None = None) -> list[EventDelivery]:
        normalized_client_id = _normalize_client_id(client_id)
        with self._connect() as connection:
            if normalized_client_id is None:
                rows = connection.execute(
                    "select * from event_deliveries order by id desc"
                ).fetchall()
            else:
                rows = connection.execute(
                    "select * from event_deliveries where client_id = ? order by id desc",
                    (normalized_client_id,),
                ).fetchall()
        return [_event_delivery_from_row(row) for row in rows]

    def has_event_agent_run(
        self,
        *,
        agent_id: str,
        event_type: str,
        entity_id: str,
        client_id: str | None = None,
    ) -> bool:
        normalized_client_id = _normalize_client_id(client_id)
        with self._connect() as connection:
            rows = connection.execute(
                """
                select agent_ids_json from event_deliveries
                where event_type = ? and entity_id = ?
                  and status in ('completed', 'failed')
                  and (? is null or client_id = ?)
                """,
                (event_type, entity_id, normalized_client_id, normalized_client_id),
            ).fetchall()
        return any(agent_id in _json_string_list(row["agent_ids_json"]) for row in rows)

    def has_completed_event_agent_run(
        self,
        *,
        agent_id: str,
        event_type: str,
        entity_id: str,
        client_id: str | None = None,
    ) -> bool:
        normalized_client_id = _normalize_client_id(client_id)
        with self._connect() as connection:
            rows = connection.execute(
                """
                select agent_ids_json from event_deliveries
                where event_type = ? and entity_id = ? and status = 'completed'
                  and (? is null or client_id = ?)
                """,
                (event_type, entity_id, normalized_client_id, normalized_client_id),
            ).fetchall()
        return any(agent_id in _json_string_list(row["agent_ids_json"]) for row in rows)

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

    def create_agent_definition(
        self,
        definition: AgentDefinition,
    ) -> AgentDefinition:
        with self._connect() as connection:
            connection.execute(
                """
                insert into agent_definitions
                  (id, name, description, enabled, trigger, entity_type,
                   filters_json, enabled_tools_json, steps_json, max_steps,
                   execution_timeout_seconds, client_id, version, created_at, updated_at,
                   run_once_per_entity, depends_on_agent_ids_json)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    definition.id,
                    definition.name,
                    definition.description,
                    int(definition.enabled),
                    definition.trigger,
                    definition.entity_type,
                    _json_dumps(definition.filters),
                    _json_dumps_value(definition.enabled_tools),
                    _json_dumps_value(definition.steps),
                    definition.max_steps,
                    definition.execution_timeout_seconds,
                    _normalize_client_id(definition.client_id),
                    definition.version,
                    definition.created_at,
                    definition.updated_at,
                    int(definition.run_once_per_entity),
                    _json_dumps_value(definition.depends_on_agent_ids),
                ),
            )
            self._add_audit_event(
                connection,
                "agent.created",
                definition.id,
                f"agent {definition.name} created",
                client_id=definition.client_id,
            )
            self._insert_agent_revision(connection, definition)
        created = self.get_agent_definition(definition.id)
        if created is None:
            raise RuntimeError("agent definition was not persisted")
        return created

    def get_agent_definition(self, agent_id: str, client_id: str | None = None) -> AgentDefinition | None:
        normalized_client_id = _normalize_client_id(client_id)
        with self._connect() as connection:
            if normalized_client_id is None:
                row = connection.execute(
                    "select * from agent_definitions where id = ?",
                    (agent_id,),
                ).fetchone()
            else:
                row = connection.execute(
                    "select * from agent_definitions where id = ? and client_id = ?",
                    (agent_id, normalized_client_id),
                ).fetchone()
        return _agent_definition_from_row(row) if row else None

    def list_agent_definitions(self, client_id: str | None = None) -> list[AgentDefinition]:
        normalized_client_id = _normalize_client_id(client_id)
        with self._connect() as connection:
            if normalized_client_id is None:
                rows = connection.execute(
                    "select * from agent_definitions order by name, id"
                ).fetchall()
            else:
                rows = connection.execute(
                    "select * from agent_definitions where client_id = ? order by name, id",
                    (normalized_client_id,),
                ).fetchall()
        return [_agent_definition_from_row(row) for row in rows]

    def update_agent_definition(self, definition: AgentDefinition) -> AgentDefinition:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                update agent_definitions
                set name = ?, description = ?, enabled = ?, trigger = ?, entity_type = ?,
                    filters_json = ?, enabled_tools_json = ?, steps_json = ?, max_steps = ?,
                    execution_timeout_seconds = ?, client_id = ?, version = ?, updated_at = ?,
                    run_once_per_entity = ?, depends_on_agent_ids_json = ?
                where id = ?
                """,
                (
                    definition.name,
                    definition.description,
                    int(definition.enabled),
                    definition.trigger,
                    definition.entity_type,
                    _json_dumps(definition.filters),
                    _json_dumps_value(definition.enabled_tools),
                    _json_dumps_value(definition.steps),
                    definition.max_steps,
                    definition.execution_timeout_seconds,
                    _normalize_client_id(definition.client_id),
                    definition.version,
                    definition.updated_at,
                    int(definition.run_once_per_entity),
                    _json_dumps_value(definition.depends_on_agent_ids),
                    definition.id,
                ),
            )
            if cursor.rowcount != 1:
                raise KeyError(definition.id)
            self._add_audit_event(
                connection,
                "agent.updated",
                definition.id,
                f"agent {definition.name} updated to version {definition.version}",
                client_id=definition.client_id,
            )
            self._insert_agent_revision(connection, definition)
        updated = self.get_agent_definition(definition.id)
        if updated is None:
            raise RuntimeError("agent definition was not persisted")
        return updated

    @staticmethod
    def _insert_agent_revision(
        connection: sqlite3.Connection,
        definition: AgentDefinition,
    ) -> None:
        connection.execute(
            """
            insert into agent_definition_revisions
              (agent_id, version, definition_json, created_at, client_id)
            values (?, ?, ?, ?, ?)
            """,
            (
                definition.id,
                definition.version,
                _agent_definition_snapshot(definition),
                definition.updated_at,
                _normalize_client_id(definition.client_id),
            ),
        )

    def get_agent_definition_revision(
        self,
        agent_id: str,
        version: int,
        client_id: str | None = None,
    ) -> AgentDefinitionRevision | None:
        normalized_client_id = _normalize_client_id(client_id)
        with self._connect() as connection:
            if normalized_client_id is None:
                row = connection.execute(
                    """
                    select * from agent_definition_revisions
                    where agent_id = ? and version = ?
                    """,
                    (agent_id, version),
                ).fetchone()
            else:
                row = connection.execute(
                    """
                    select * from agent_definition_revisions
                    where agent_id = ? and version = ? and client_id = ?
                    """,
                    (agent_id, version, normalized_client_id),
                ).fetchone()
        return _agent_definition_revision_from_row(row) if row else None

    def list_agent_definition_revisions(
        self,
        agent_id: str,
        client_id: str | None = None,
    ) -> list[AgentDefinitionRevision]:
        normalized_client_id = _normalize_client_id(client_id)
        with self._connect() as connection:
            if normalized_client_id is None:
                rows = connection.execute(
                    """
                    select * from agent_definition_revisions
                    where agent_id = ? order by version desc
                    """,
                    (agent_id,),
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    select * from agent_definition_revisions
                    where agent_id = ? and client_id = ? order by version desc
                    """,
                    (agent_id, normalized_client_id),
                ).fetchall()
        return [_agent_definition_revision_from_row(row) for row in rows]

    def create_agent_run(
        self,
        agent_id: str,
        entity_id: str,
        actor: str,
        status: str,
        current_step: int,
        state: dict[str, object],
        *,
        client_id: str | None = None,
    ) -> AgentRun:
        now = utc_now()
        normalized_client_id = _normalize_client_id(client_id)
        state_json = _json_dumps(state)
        with self._connect() as connection:
            cursor = connection.execute(
                """
                insert into agent_runs
                  (agent_id, entity_id, actor, status, current_step, state_json,
                   started_at, finished_at, client_id)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    agent_id,
                    entity_id,
                    actor,
                    status,
                    current_step,
                    state_json,
                    now,
                    now,
                    normalized_client_id,
                ),
            )
            if cursor.lastrowid is None:
                raise RuntimeError("agent run insert did not return an id")
            run_id = int(cursor.lastrowid)
            self._add_audit_event(
                connection,
                "agent.run_created",
                str(run_id),
                f"agent {agent_id} started for {entity_id}",
                client_id=normalized_client_id,
            )
        run = self.get_agent_run(run_id)
        if run is None:
            raise RuntimeError("agent run was not persisted")
        return run

    def update_agent_run(
        self,
        run_id: int,
        status: str,
        current_step: int,
        state: dict[str, object],
    ) -> AgentRun:
        now = utc_now()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                update agent_runs
                set status = ?, current_step = ?, state_json = ?, finished_at = ?
                where id = ?
                """,
                (status, current_step, _json_dumps(state), now, run_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(run_id)
        run = self.get_agent_run(run_id)
        if run is None:
            raise RuntimeError("agent run was not persisted")
        return run

    def get_agent_run(self, run_id: int, client_id: str | None = None) -> AgentRun | None:
        normalized_client_id = _normalize_client_id(client_id)
        with self._connect() as connection:
            if normalized_client_id is None:
                row = connection.execute("select * from agent_runs where id = ?", (run_id,)).fetchone()
            else:
                row = connection.execute(
                    "select * from agent_runs where id = ? and client_id = ?",
                    (run_id, normalized_client_id),
                ).fetchone()
        return _agent_run_from_row(row) if row else None

    def list_agent_runs(self, client_id: str | None = None) -> list[AgentRun]:
        normalized_client_id = _normalize_client_id(client_id)
        with self._connect() as connection:
            if normalized_client_id is None:
                rows = connection.execute("select * from agent_runs order by id desc").fetchall()
            else:
                rows = connection.execute(
                    "select * from agent_runs where client_id = ? order by id desc",
                    (normalized_client_id,),
                ).fetchall()
        return [_agent_run_from_row(row) for row in rows]

    def create_smart_action_run(
        self,
        action_id: str,
        actor: str,
        status: str,
        payload_digest: str,
        output: dict[str, object],
        evidence: list[dict[str, object]],
        *,
        approval_id: int | None = None,
        client_id: str | None = None,
    ) -> SmartActionRun:
        now = utc_now()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                insert into smart_action_runs
                  (action_id, actor, status, payload_digest, output_json,
                   evidence_json, approval_id, created_at, updated_at, client_id)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    action_id,
                    actor,
                    status,
                    payload_digest,
                    _json_dumps(output),
                    _json_dumps_value(evidence),
                    approval_id,
                    now,
                    now,
                    _normalize_client_id(client_id),
                ),
            )
            if cursor.lastrowid is None:
                raise RuntimeError("smart action run insert did not return an id")
            run_id = int(cursor.lastrowid)
        run = self.get_smart_action_run(run_id)
        if run is None:
            raise RuntimeError("smart action run was not persisted")
        return run

    def create_pending_smart_action(
        self,
        action_id: str,
        actor: str,
        payload_digest: str,
        output: dict[str, object],
        evidence: list[dict[str, object]],
        approval_payload: dict[str, object],
        *,
        client_id: str | None = None,
    ) -> tuple[SmartActionRun, ApprovalRequest]:
        """Create a pending run, approval, and audit trail in one transaction."""
        now = utc_now()
        normalized_client_id = _normalize_client_id(client_id)
        output_json = _json_dumps(output)
        evidence_json = _json_dumps_value(evidence)
        approval_payload_json = _json_dumps(approval_payload)
        with self._connect() as connection:
            run_cursor = connection.execute(
                """
                insert into smart_action_runs
                  (action_id, actor, status, payload_digest, output_json,
                   evidence_json, approval_id, created_at, updated_at, client_id)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    action_id,
                    actor,
                    "pending_approval",
                    payload_digest,
                    output_json,
                    evidence_json,
                    None,
                    now,
                    now,
                    normalized_client_id,
                ),
            )
            if run_cursor.lastrowid is None:
                raise RuntimeError("smart action run insert did not return an id")
            run_id = int(run_cursor.lastrowid)
            approval_payload = dict(approval_payload)
            approval_payload.setdefault("run_id", run_id)
            approval_payload_json = _json_dumps(approval_payload)
            approval_cursor = connection.execute(
                """
                insert into approval_requests
                  (subject_id, action_type, payload_json, status, comment,
                   created_at, updated_at, client_id)
                values (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(run_id),
                    f"smart_action:{action_id}",
                    approval_payload_json,
                    "pending",
                    "",
                    now,
                    now,
                    normalized_client_id,
                ),
            )
            if approval_cursor.lastrowid is None:
                raise RuntimeError("approval request insert did not return an id")
            approval_id = int(approval_cursor.lastrowid)
            connection.execute(
                "update smart_action_runs set approval_id = ?, updated_at = ? where id = ?",
                (approval_id, now, run_id),
            )
            self._add_audit_event(
                connection,
                "approval.requested",
                str(run_id),
                f"smart_action:{action_id} approval requested",
                client_id=normalized_client_id,
            )
            self._add_event_history(
                connection,
                "approval.requested",
                str(run_id),
                "pending",
                f"smart_action:{action_id} waiting for technician approval",
                approval_payload_json,
                normalized_client_id,
            )
            self._add_audit_event(
                connection,
                "smart_action.invoked",
                str(run_id),
                f"{action_id} pending approval",
                client_id=normalized_client_id,
            )
        run = self.get_smart_action_run(run_id)
        approval = self.get_approval_request(approval_id)
        if run is None or approval is None:
            raise RuntimeError("pending smart action was not persisted")
        return run, approval

    def set_smart_action_run_approval(self, run_id: int, approval_id: int) -> SmartActionRun:
        with self._connect() as connection:
            cursor = connection.execute(
                "update smart_action_runs set approval_id = ?, updated_at = ? where id = ?",
                (approval_id, utc_now(), run_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(run_id)
        run = self.get_smart_action_run(run_id)
        if run is None:
            raise RuntimeError("smart action run was not persisted")
        return run

    def complete_smart_action_run(
        self,
        run_id: int,
        status: str,
        output: dict[str, object],
        evidence: list[dict[str, object]],
        *,
        approval_id: int | None = None,
        approver_id: str | None = None,
        _smart_action_capability: object | None = None,
    ) -> SmartActionRun:
        with self._connect() as connection:
            current = connection.execute(
                "select * from smart_action_runs where id = ?", (run_id,)
            ).fetchone()
            if current is None:
                raise KeyError(run_id)
            if _smart_action_capability is not SMART_ACTION_APPROVAL_CAPABILITY:
                raise PermissionError("smart-action runs must be completed through SmartActionService")
            if str(current["status"]) != "pending_approval":
                raise PermissionError("smart action run has already completed")
            if status not in {"success", "provider_not_configured", "failed", "rejected"}:
                raise ValueError("invalid smart action run completion status")
            linked_approval_id = current["approval_id"]
            if (
                approval_id is None
                or linked_approval_id is None
                or int(linked_approval_id) != approval_id
                or not approver_id
            ):
                raise PermissionError("smart action completion requires its linked approval and approver")
            approval = connection.execute(
                "select action_type, status, approver_id from approval_requests where id = ?",
                (approval_id,),
            ).fetchone()
            if approval is None or not str(approval["action_type"]).startswith("smart_action:"):
                raise PermissionError("smart action completion requires a linked smart-action approval")
            if str(approval["status"]) not in {"approved", "rejected"}:
                raise PermissionError("smart action completion requires a completed approval")
            if str(approval["approver_id"] or "") != approver_id:
                raise PermissionError("smart action completion requires the approval approver")
            cursor = connection.execute(
                """
                update smart_action_runs
                set status = ?, output_json = ?, evidence_json = ?, updated_at = ?
                where id = ?
                """,
                (
                    status,
                    _json_dumps(output),
                    _json_dumps_value(evidence),
                    utc_now(),
                    run_id,
                ),
            )
            if cursor.rowcount != 1:
                raise KeyError(run_id)
        run = self.get_smart_action_run(run_id)
        if run is None:
            raise RuntimeError("smart action run was not persisted")
        return run

    def get_smart_action_run(
        self, run_id: int, client_id: str | None = None
    ) -> SmartActionRun | None:
        normalized_client_id = _normalize_client_id(client_id)
        with self._connect() as connection:
            if normalized_client_id is None:
                row = connection.execute(
                    "select * from smart_action_runs where id = ?", (run_id,)
                ).fetchone()
            else:
                row = connection.execute(
                    "select * from smart_action_runs where id = ? and client_id = ?",
                    (run_id, normalized_client_id),
                ).fetchone()
        return SmartActionRun(**dict(row)) if row else None

    def list_smart_action_runs(self, client_id: str | None = None) -> list[SmartActionRun]:
        normalized_client_id = _normalize_client_id(client_id)
        with self._connect() as connection:
            if normalized_client_id is None:
                rows = connection.execute(
                    "select * from smart_action_runs order by id desc"
                ).fetchall()
            else:
                rows = connection.execute(
                    "select * from smart_action_runs where client_id = ? order by id desc",
                    (normalized_client_id,),
                ).fetchall()
        return [SmartActionRun(**dict(row)) for row in rows]

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
        job_kind: str = "workflow",
        agent_id: str | None = None,
        entity_id: str | None = None,
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
                    client_id,
                    job_kind,
                    agent_id,
                    entity_id
                )
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    template_id,
                    cron,
                    params_json,
                    int(paused),
                    now,
                    now,
                    normalized_client_id,
                    job_kind,
                    agent_id,
                    entity_id,
                ),
            )
            if cursor.lastrowid is None:
                raise RuntimeError("scheduled job insert did not return an id")
            job_id = int(cursor.lastrowid)
            self._add_audit_event(
                connection,
                "scheduled_job.created",
                str(job_id),
                f"{_scheduled_target(job_kind, template_id, agent_id)} scheduled with cron {cron}",
                client_id=normalized_client_id,
            )
            self._add_event_history(
                connection,
                "scheduled_job.created",
                str(job_id),
                "paused" if paused else "scheduled",
                f"{_scheduled_target(job_kind, template_id, agent_id)} scheduled with cron {cron}",
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
        return [_event_history_from_row(row) for row in rows]

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
            obs_asset = asset_by_canonical_id.get(observation.canonical_id) or self.get_canonical_asset_by_canonical_id(
                observation.canonical_id
            )
            if obs_asset is None or obs_asset.id is None:
                raise KeyError(f"asset {observation.canonical_id} not found")
            self.add_asset_observation(
                asset_id=obs_asset.id,
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

    def create_hardening_run(self, *, expected_check_count: int, started_at: str) -> HardeningRunRecord:
        from wait_local_agent.reports.hardening_checks import HardeningRunRecord

        with self._connect() as connection:
            cursor = connection.execute(
                """
                insert into hardening_runs
                  (status, expected_check_count, started_at, completed_at)
                values ('running', ?, ?, '')
                """,
                (expected_check_count, started_at),
            )
            if cursor.lastrowid is None:
                raise RuntimeError("hardening run insert did not return an id")
            run_id = int(cursor.lastrowid)
        return HardeningRunRecord(run_id, "running", started_at, "", expected_check_count, 0)

    def add_hardening_check_result(
        self,
        *,
        run_id: int,
        check_id: str,
        title: str,
        scope: str,
        severity: str,
        result: CheckResult,
    ) -> HardeningCheckResultRecord:
        from wait_local_agent.reports.hardening_checks import HardeningCheckResultRecord

        with self._connect() as connection:
            cursor = connection.execute(
                """
                insert into hardening_check_results
                  (run_id, check_id, title, scope, severity, status, evidence_json, remediation_hint)
                values (?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(run_id, check_id) do update set
                  title=excluded.title,
                  scope=excluded.scope,
                  severity=excluded.severity,
                  status=excluded.status,
                  evidence_json=excluded.evidence_json,
                  remediation_hint=excluded.remediation_hint
                """,
                (
                    run_id,
                    check_id,
                    title,
                    scope,
                    severity,
                    result.status,
                    _json_dumps(result.evidence),
                    result.remediation_hint,
                ),
            )
            result_id = int(cursor.lastrowid or 0)
        return HardeningCheckResultRecord(
            result_id,
            run_id,
            check_id,
            title,
            scope,
            severity,
            result.status,
            result.evidence,
            result.remediation_hint,
        )

    def list_hardening_check_results(self, run_id: int) -> list[HardeningCheckResultRecord]:
        from wait_local_agent.reports.hardening_checks import HardeningCheckResultRecord

        with self._connect() as connection:
            rows = connection.execute(
                "select * from hardening_check_results where run_id = ? order by id",
                (run_id,),
            ).fetchall()
        return [
            HardeningCheckResultRecord(
                int(row["id"]),
                int(row["run_id"]),
                str(row["check_id"]),
                str(row["title"]),
                str(row["scope"]),
                str(row["severity"]),
                cast(Literal["passed", "failed", "not_applicable", "error"], str(row["status"])),
                json.loads(str(row["evidence_json"])),
                str(row["remediation_hint"]) if row["remediation_hint"] is not None else None,
            )
            for row in rows
        ]

    def complete_hardening_run(
        self,
        run_id: int,
        status: Literal["running", "completed", "partial"],
        completed_at: str,
    ) -> HardeningRunRecord:
        with self._connect() as connection:
            connection.execute(
                "update hardening_runs set status = ?, completed_at = ? where id = ?",
                (status, completed_at, run_id),
            )
        run = self.get_hardening_run(run_id)
        if run is None:
            raise RuntimeError("hardening run was not persisted")
        return run

    def get_hardening_run(self, run_id: int) -> HardeningRunRecord | None:
        from wait_local_agent.reports.hardening_checks import HardeningRunRecord

        with self._connect() as connection:
            row = connection.execute("select * from hardening_runs where id = ?", (run_id,)).fetchone()
        if row is None:
            return None
        results = self.list_hardening_check_results(run_id)
        return HardeningRunRecord(
            int(row["id"]),
            cast(Literal["running", "completed", "partial"], str(row["status"])),
            str(row["started_at"]),
            str(row["completed_at"]),
            int(row["expected_check_count"]),
            len(results),
            results,
        )

    def list_hardening_runs(self) -> list[HardeningRunRecord]:
        with self._connect() as connection:
            ids = [int(row["id"]) for row in connection.execute("select id from hardening_runs order by id desc")]
        return [run for run_id in ids if (run := self.get_hardening_run(run_id)) is not None]

    def create_execution_run(
        self,
        run_kind: str,
        source_run_id: int | None,
        actor: str,
        status: str,
        started_at: str,
        finished_at: str,
        trigger_source: str,
        *,
        client_id: str | None = None,
    ) -> ExecutionRun:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                insert into execution_runs
                  (run_kind, source_run_id, actor, client_id, status,
                   started_at, finished_at, trigger_source)
                values (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_kind,
                    source_run_id,
                    actor,
                    _normalize_client_id(client_id),
                    status,
                    started_at,
                    finished_at,
                    trigger_source,
                ),
            )
            if cursor.lastrowid is None:
                raise RuntimeError("execution run insert did not return an id")
            run_id = int(cursor.lastrowid)
        run = self.get_execution_run(run_id)
        if run is None:
            raise RuntimeError("execution run was not persisted")
        return run

    def get_execution_run(
        self, run_id: int, client_id: str | None = None
    ) -> ExecutionRun | None:
        normalized_client_id = _normalize_client_id(client_id)
        with self._connect() as connection:
            if normalized_client_id is None:
                row = connection.execute(
                    "select * from execution_runs where id = ?", (run_id,)
                ).fetchone()
            else:
                row = connection.execute(
                    "select * from execution_runs where id = ? and client_id = ?",
                    (run_id, normalized_client_id),
                ).fetchone()
        return _execution_run_from_row(row) if row else None

    def find_execution_run(
        self, run_kind: str, source_run_id: int
    ) -> ExecutionRun | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                select * from execution_runs
                where run_kind = ? and source_run_id = ?
                order by id desc
                """,
                (run_kind, source_run_id),
            ).fetchone()
        return _execution_run_from_row(row) if row else None

    def update_execution_run(
        self, run_id: int, status: str, finished_at: str
    ) -> ExecutionRun:
        with self._connect() as connection:
            cursor = connection.execute(
                "update execution_runs set status = ?, finished_at = ? where id = ?",
                (status, finished_at, run_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(run_id)
        run = self.get_execution_run(run_id)
        if run is None:
            raise RuntimeError("execution run was not persisted")
        return run

    def list_execution_runs(
        self,
        client_id: str | None = None,
        *,
        run_kind: str | None = None,
        status: str | None = None,
        started_from: str | None = None,
        started_to: str | None = None,
    ) -> list[ExecutionRun]:
        clauses: list[str] = []
        params: list[object] = []
        normalized_client_id = _normalize_client_id(client_id)
        if normalized_client_id is not None:
            clauses.append("client_id = ?")
            params.append(normalized_client_id)
        if run_kind:
            clauses.append("run_kind = ?")
            params.append(run_kind)
        if status:
            clauses.append("status = ?")
            params.append(status)
        if started_from:
            clauses.append("date(started_at) >= date(?)")
            params.append(started_from)
        if started_to:
            clauses.append("date(started_at) <= date(?)")
            params.append(started_to)
        where = f" where {' and '.join(clauses)}" if clauses else ""
        with self._connect() as connection:
            rows = connection.execute(
                f"select * from execution_runs{where} order by id desc",  # nosec B608: static clause strings only; values are parameterized
                params,
            ).fetchall()
        return [_execution_run_from_row(row) for row in rows]

    def add_execution_step(
        self,
        execution_run_id: int,
        ordinal: int,
        kind: str,
        name: str,
        status: str,
        started_at: str,
        finished_at: str,
        input_digest: str,
        output_digest: str,
        input_json: str,
        output_json: str,
        error_detail: str = "",
    ) -> ExecutionStep:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                insert into execution_steps
                  (execution_run_id, ordinal, kind, name, status, started_at,
                   finished_at, input_digest, output_digest, input_json,
                   output_json, error_detail)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    execution_run_id,
                    ordinal,
                    kind,
                    name,
                    status,
                    started_at,
                    finished_at,
                    input_digest,
                    output_digest,
                    input_json,
                    output_json,
                    error_detail,
                ),
            )
            if cursor.lastrowid is None:
                raise RuntimeError("execution step insert did not return an id")
            step_id = int(cursor.lastrowid)
            row = connection.execute(
                "select * from execution_steps where id = ?", (step_id,)
            ).fetchone()
        if row is None:
            raise RuntimeError("execution step was not persisted")
        return _execution_step_from_row(row)

    def list_execution_steps(self, execution_run_id: int) -> list[ExecutionStep]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                select * from execution_steps
                where execution_run_id = ?
                order by ordinal, id
                """,
                (execution_run_id,),
            ).fetchall()
        return [_execution_step_from_row(row) for row in rows]

    def next_execution_step_ordinal(self, execution_run_id: int) -> int:
        with self._connect() as connection:
            row = connection.execute(
                "select max(ordinal) as top from execution_steps where execution_run_id = ?",
                (execution_run_id,),
            ).fetchone()
        if row is None or row["top"] is None:
            return 0
        return int(row["top"]) + 1

    def add_execution_artifact(
        self,
        execution_run_id: int,
        step_ordinal: int | None,
        name: str,
        media_type: str,
        byte_size: int,
        sha256: str,
        storage_path: str,
    ) -> ExecutionArtifact:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                insert into execution_artifacts
                  (execution_run_id, step_ordinal, name, media_type,
                   byte_size, sha256, storage_path)
                values (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    execution_run_id,
                    step_ordinal,
                    name,
                    media_type,
                    byte_size,
                    sha256,
                    storage_path,
                ),
            )
            if cursor.lastrowid is None:
                raise RuntimeError("execution artifact insert did not return an id")
            artifact_id = int(cursor.lastrowid)
        artifact = self.get_execution_artifact(artifact_id)
        if artifact is None:
            raise RuntimeError("execution artifact was not persisted")
        return artifact

    def get_execution_artifact(self, artifact_id: int) -> ExecutionArtifact | None:
        with self._connect() as connection:
            row = connection.execute(
                "select * from execution_artifacts where id = ?", (artifact_id,)
            ).fetchone()
        return _execution_artifact_from_row(row) if row else None

    def list_execution_artifacts(self, execution_run_id: int) -> list[ExecutionArtifact]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                select * from execution_artifacts
                where execution_run_id = ?
                order by id
                """,
                (execution_run_id,),
            ).fetchall()
        return [_execution_artifact_from_row(row) for row in rows]

    def execution_daily_status_counts(
        self,
        started_from: str | None,
        started_to: str | None,
        client_id: str | None = None,
    ) -> list[tuple[str, str, int]]:
        clauses, params = _execution_range_filters(started_from, started_to, client_id)
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                with source_runs(run_kind, source_run_id, status, started_at, client_id) as (
                    select 'workflow', id, status, created_at, client_id from workflow_runs
                    union all
                    select 'smart_action', id, status, created_at, client_id from smart_action_runs
                ), all_runs as (
                    select er.run_kind, er.source_run_id, er.status, er.started_at, er.client_id
                    from execution_runs er
                    union all
                    select sr.run_kind, sr.source_run_id, sr.status, sr.started_at, sr.client_id
                    from source_runs sr
                    where not exists (
                        select 1 from execution_runs recorded
                        where recorded.run_kind = sr.run_kind
                          and recorded.source_run_id = sr.source_run_id
                    )
                )
                select date(er.started_at) as day, er.status as status, count(*) as count
                from all_runs er{clauses}
                group by day, status
                order by day
                """,  # nosec B608: static clause strings only; values are parameterized
                params,
            ).fetchall()
        return [(str(row["day"]), str(row["status"]), int(row["count"])) for row in rows]

    def execution_smart_action_success_counts(
        self,
        started_from: str | None,
        started_to: str | None,
        client_id: str | None = None,
    ) -> list[tuple[str, int]]:
        clauses, params = _execution_range_filters(started_from, started_to, client_id)
        prefix = " where" if not clauses else f"{clauses} and"
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                with source_runs(run_kind, source_run_id, status, started_at, client_id) as (
                    select 'smart_action', id, status, created_at, client_id from smart_action_runs
                ), all_runs as (
                    select er.run_kind, er.source_run_id, er.status, er.started_at, er.client_id
                    from execution_runs er
                    union all
                    select sr.run_kind, sr.source_run_id, sr.status, sr.started_at, sr.client_id
                    from source_runs sr
                    where not exists (
                        select 1 from execution_runs recorded
                        where recorded.run_kind = sr.run_kind
                          and recorded.source_run_id = sr.source_run_id
                    )
                )
                select sar.action_id as action_id, count(*) as count
                from all_runs er
                join smart_action_runs sar on sar.id = er.source_run_id
                {prefix} er.run_kind = 'smart_action' and er.status = 'success'
                group by sar.action_id
                order by sar.action_id
                """,  # nosec B608: static clause strings only; values are parameterized
                params,
            ).fetchall()
        return [(str(row["action_id"]), int(row["count"])) for row in rows]

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
                   client_id, project_id, sections_json, metadata_json, evidence_status)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(id) do update set
                  report_type=excluded.report_type,
                  title=excluded.title,
                  created_at=excluded.created_at,
                  created_by=excluded.created_by,
                  client_id=excluded.client_id,
                  project_id=excluded.project_id,
                  sections_json=excluded.sections_json,
                  metadata_json=excluded.metadata_json,
                  evidence_status=excluded.evidence_status
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
                    report.evidence_status,
                ),
            )

    def get_founder_config(self) -> dict[str, str] | None:
        with self._connect() as connection:
            row = connection.execute("select * from founder_config where id = 1").fetchone()
        return {str(key): str(value) for key, value in dict(row).items()} if row else None

    def save_founder_config(self, *, lp_base_url: str, lp_project_id: str, token_vault_ref: str) -> None:
        now = utc_now()
        with self._connect() as connection:
            connection.execute(
                """
                insert into founder_config
                  (id, lp_base_url, lp_project_id, token_vault_ref, created_at, updated_at)
                values (1, ?, ?, ?, ?, ?)
                on conflict(id) do update set
                  lp_base_url=excluded.lp_base_url,
                  lp_project_id=excluded.lp_project_id,
                  token_vault_ref=excluded.token_vault_ref,
                  updated_at=excluded.updated_at
                """,
                (lp_base_url, lp_project_id, token_vault_ref, now, now),
            )

    def save_founder_artifact(
        self,
        *,
        artifact_id: str,
        project_id: str,
        bundle_hash: str,
        bundle: dict[str, object],
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                insert into founder_artifacts
                  (artifact_id, project_id, bundle_hash, bundle_json, created_at)
                values (?, ?, ?, ?, ?)
                on conflict(artifact_id) do update set
                  project_id=excluded.project_id,
                  bundle_hash=excluded.bundle_hash,
                  bundle_json=excluded.bundle_json,
                  created_at=excluded.created_at,
                  previewed_at='',
                  uploaded_at='',
                  remote_scan_id='',
                  remote_scan_status='',
                  remote_scan_json='{}',
                  latest_report_reference='',
                  latest_report_json='{}',
                  polling_status=''
                """,
                (artifact_id, project_id, bundle_hash, _json_dumps(bundle), utc_now()),
            )
            connection.execute("delete from founder_artifact_previews where artifact_id = ?", (artifact_id,))

    def get_founder_artifact(self, artifact_id: str) -> dict[str, object] | None:
        with self._connect() as connection:
            row = connection.execute(
                "select * from founder_artifacts where artifact_id = ?",
                (artifact_id,),
            ).fetchone()
        if row is None:
            return None
        return self._founder_artifact_from_row(row)

    def list_founder_artifacts(self, project_id: str = "") -> list[dict[str, object]]:
        with self._connect() as connection:
            rows = connection.execute(
                "select * from founder_artifacts "
                "where (? = '' or project_id = ?) order by created_at desc, artifact_id",
                (project_id, project_id),
            ).fetchall()
        return [self._founder_artifact_from_row(row) for row in rows]

    def update_founder_artifact_remote(
        self,
        artifact_id: str,
        *,
        scan_id: str | None = None,
        scan_status: str | None = None,
        scan: dict[str, object] | None = None,
        report_reference: str | None = None,
        report: dict[str, object] | list[object] | None = None,
        polling_status: str | None = None,
    ) -> None:
        if all(value is None for value in (scan_id, scan_status, scan, report_reference, report, polling_status)):
            return
        with self._connect() as connection:
            connection.execute(
                """
                update founder_artifacts
                set remote_scan_id = coalesce(?, remote_scan_id),
                    remote_scan_status = coalesce(?, remote_scan_status),
                    remote_scan_json = coalesce(?, remote_scan_json),
                    latest_report_reference = coalesce(?, latest_report_reference),
                    latest_report_json = coalesce(?, latest_report_json),
                    polling_status = coalesce(?, polling_status)
                where artifact_id = ?
                """,
                (
                    scan_id,
                    scan_status,
                    _json_dumps_value(scan) if scan is not None else None,
                    report_reference,
                    _json_dumps_value(report) if report is not None else None,
                    polling_status,
                    artifact_id,
                ),
            )

    def mark_founder_artifact_previewed(self, artifact_id: str) -> None:
        with self._connect() as connection:
            now = utc_now()
            updated = connection.execute(
                "update founder_artifacts set previewed_at = ? where artifact_id = ?",
                (now, artifact_id),
            )
            if updated.rowcount == 0:
                connection.execute(
                    """
                    insert into founder_artifact_previews (artifact_id, previewed_at)
                    values (?, ?)
                    on conflict(artifact_id) do update set previewed_at = excluded.previewed_at
                    """,
                    (artifact_id, now),
                )

    def get_founder_artifact_previewed_at(self, artifact_id: str) -> str:
        with self._connect() as connection:
            row = connection.execute(
                "select previewed_at from founder_artifacts where artifact_id = ?",
                (artifact_id,),
            ).fetchone()
            if row is not None and str(row["previewed_at"]):
                return str(row["previewed_at"])
            marker = connection.execute(
                "select previewed_at from founder_artifact_previews where artifact_id = ?",
                (artifact_id,),
            ).fetchone()
        return str(marker["previewed_at"]) if marker is not None else ""

    def mark_founder_artifact_uploaded(self, artifact_id: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "update founder_artifacts set uploaded_at = ? where artifact_id = ?",
                (utc_now(), artifact_id),
            )

    @staticmethod
    def _founder_artifact_from_row(row: sqlite3.Row) -> dict[str, object]:
        return {
            "artifact_id": str(row["artifact_id"]),
            "project_id": str(row["project_id"]),
            "bundle_hash": str(row["bundle_hash"]),
            "bundle": json.loads(str(row["bundle_json"])),
            "created_at": str(row["created_at"]),
            "previewed_at": str(row["previewed_at"]),
            "uploaded_at": str(row["uploaded_at"]),
            "remote_scan_id": str(row["remote_scan_id"]),
            "remote_scan_status": str(row["remote_scan_status"]),
            "remote_scan": _json_object_or_empty(row["remote_scan_json"]),
            "latest_report_reference": str(row["latest_report_reference"]),
            "latest_report": _json_value_or_empty(row["latest_report_json"]),
            "polling_status": str(row["polling_status"]),
        }

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
    from wait_local_agent.reports.models import EvidenceStatus, GeneratedReport, ReportType, sections_from_json

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
        evidence_status=cast(
            EvidenceStatus,
            str(row["evidence_status"]),
        ),
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


def _event_delivery_from_row(row: sqlite3.Row) -> EventDelivery:
    payload = dict(row)
    payload["matched_agent_count"] = int(payload["matched_agent_count"])
    payload["client_id"] = _normalize_client_id(payload.get("client_id"))
    payload["payload_json"] = _redact_json_text(str(payload["payload_json"]))
    payload["error_detail"] = _redact_text(str(payload["error_detail"]))
    return EventDelivery(**payload)


def _scheduled_target(job_kind: str, template_id: str, agent_id: str | None) -> str:
    if job_kind == "agent":
        return f"agent {agent_id or 'unknown'}"
    return template_id


def _agent_definition_from_row(row: sqlite3.Row) -> AgentDefinition:
    payload = dict(row)
    payload["enabled"] = bool(payload["enabled"])
    payload["run_once_per_entity"] = bool(payload["run_once_per_entity"])
    payload["depends_on_agent_ids"] = cast(
        list[str], _json_list_or_empty(payload.pop("depends_on_agent_ids_json"))
    )
    payload["filters"] = _json_object_or_empty(payload.pop("filters_json"))
    payload["enabled_tools"] = cast(list[str], _json_list_or_empty(payload.pop("enabled_tools_json")))
    payload["steps"] = cast(list[dict[str, object]], _json_list_or_empty(payload.pop("steps_json")))
    payload["client_id"] = _normalize_client_id(payload.get("client_id"))
    return AgentDefinition(**payload)


def _agent_definition_revision_from_row(row: sqlite3.Row) -> AgentDefinitionRevision:
    payload = dict(row)
    payload["client_id"] = _normalize_client_id(payload.get("client_id"))
    payload["definition_json"] = _redact_json_text(str(payload["definition_json"]))
    return AgentDefinitionRevision(**payload)


def _agent_definition_snapshot(definition: AgentDefinition) -> str:
    return _json_dumps_value(
        {
            "name": definition.name,
            "description": definition.description,
            "enabled": definition.enabled,
            "trigger": definition.trigger,
            "entity_type": definition.entity_type,
            "filters": definition.filters,
            "enabled_tools": definition.enabled_tools,
            "steps": definition.steps,
            "max_steps": definition.max_steps,
            "execution_timeout_seconds": definition.execution_timeout_seconds,
            "client_id": definition.client_id,
            "run_once_per_entity": definition.run_once_per_entity,
            "depends_on_agent_ids": definition.depends_on_agent_ids,
        }
    )


def _agent_run_from_row(row: sqlite3.Row) -> AgentRun:
    payload = dict(row)
    payload["client_id"] = _normalize_client_id(payload.get("client_id"))
    return AgentRun(**payload)


def _json_dumps(payload: dict[str, object]) -> str:
    return _json_dumps_value(payload)


def _json_dumps_value(payload: object) -> str:
    from wait_local_agent.reports.renderers import redact_value

    return json.dumps(redact_value(payload), sort_keys=True, separators=(",", ":"))


def _json_value_or_empty(payload: object) -> object:
    try:
        return json.loads(str(payload))
    except (TypeError, json.JSONDecodeError):
        return {}


def _json_object_or_empty(payload: object) -> dict[str, object]:
    value = _json_value_or_empty(payload)
    return value if isinstance(value, dict) else {}


def _json_list_or_empty(payload: object) -> list[object]:
    value = _json_value_or_empty(payload)
    return value if isinstance(value, list) else []


def _json_string_list(payload: object) -> list[str]:
    return [item for item in _json_list_or_empty(payload) if isinstance(item, str)]


def _redact_json_text(payload_json: str) -> str:
    try:
        payload = json.loads(payload_json)
    except json.JSONDecodeError:
        return payload_json
    return _json_dumps_value(payload)


def _redact_text(value: str) -> str:
    from wait_local_agent.reports.renderers import redact_text

    return redact_text(value)


def _event_history_from_row(row: sqlite3.Row) -> EventHistoryEntry:
    payload = dict(row)
    payload["message"] = _redact_text(str(payload["message"]))
    payload["payload_json"] = _redact_json_text(str(payload["payload_json"]))
    return EventHistoryEntry(**payload)


def _execution_run_from_row(row: sqlite3.Row) -> ExecutionRun:
    return ExecutionRun(**dict(row))


def _execution_step_from_row(row: sqlite3.Row) -> ExecutionStep:
    payload = dict(row)
    # Redact at read time as well so rows written before redaction existed
    # (legacy rows) never surface secrets.
    payload["input_json"] = _redact_json_text(str(payload["input_json"]))
    payload["output_json"] = _redact_json_text(str(payload["output_json"]))
    payload["error_detail"] = _redact_text(str(payload["error_detail"]))
    return ExecutionStep(**payload)


def _execution_artifact_from_row(row: sqlite3.Row) -> ExecutionArtifact:
    return ExecutionArtifact(**dict(row))


def _execution_range_filters(
    started_from: str | None,
    started_to: str | None,
    client_id: str | None,
) -> tuple[str, list[object]]:
    clauses: list[str] = []
    params: list[object] = []
    normalized_client_id = _normalize_client_id(client_id)
    if normalized_client_id is not None:
        clauses.append("er.client_id = ?")
        params.append(normalized_client_id)
    if started_from:
        clauses.append("date(er.started_at) >= date(?)")
        params.append(started_from)
    if started_to:
        clauses.append("date(er.started_at) <= date(?)")
        params.append(started_to)
    where = f" where {' and '.join(clauses)}" if clauses else ""
    return where, params


def _normalize_client_id(client_id: str | None) -> str | None:
    if client_id is None:
        return None
    normalized = client_id.strip()
    return normalized or None
