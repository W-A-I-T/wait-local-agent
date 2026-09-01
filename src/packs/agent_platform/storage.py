"""Shared persistence and validation primitives for agent platform extensions."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from wait_local_agent.client_scope import BoundClients
from wait_local_agent.migrations import Migration, MigrationRunner
from wait_local_agent.store import Store

AGENT_PLATFORM_MIGRATION_VERSION = 1100
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class AgentPlatformError(ValueError):
    """Safe validation or state-transition error."""


class AgentPlatformNotFoundError(LookupError):
    """Raised when a tenant-scoped record does not exist."""


class AgentPlatformConflictError(RuntimeError):
    """Raised when a requested transition conflicts with current persisted state."""


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def ensure_schema(store: Store) -> None:
    """Install the extension schema into the canonical local SQLite store."""

    with store._connect() as connection:  # noqa: SLF001 - canonical extension migration
        MigrationRunner(connection).run(
            (
                Migration(
                    AGENT_PLATFORM_MIGRATION_VERSION,
                    "agent_platform_foundation",
                    _apply_schema,
                ),
            )
        )


def _apply_schema(connection: sqlite3.Connection) -> None:
    schema = """
        create table if not exists agent_memories (
            id text primary key,
            client_id text not null references clients(client_id) on delete cascade,
            scope_type text not null
              check (scope_type in ('client', 'agent', 'technician', 'ticket')),
            scope_id text not null,
            memory_key text not null,
            value_json text not null,
            summary text not null default '',
            provenance text not null,
            pinned integer not null default 0 check (pinned in (0, 1)),
            status text not null default 'active'
              check (status in ('active', 'superseded', 'deleted')),
            version integer not null check (version >= 1),
            supersedes_id text references agent_memories(id),
            expires_at text,
            created_by text not null,
            created_at text not null,
            updated_at text not null
        );

        create unique index if not exists ux_agent_memories_active
        on agent_memories (client_id, scope_type, scope_id, memory_key)
        where status = 'active';

        create index if not exists idx_agent_memories_lookup
        on agent_memories (client_id, scope_type, scope_id, pinned desc, updated_at desc);

        create table if not exists agent_skills (
            id text primary key,
            client_id text not null references clients(client_id) on delete cascade,
            name text not null,
            slug text not null,
            description text not null default '',
            status text not null default 'active' check (status in ('active', 'archived')),
            current_version integer not null default 1 check (current_version >= 1),
            created_by text not null,
            created_at text not null,
            updated_at text not null,
            unique (client_id, slug)
        );

        create table if not exists agent_skill_revisions (
            skill_id text not null references agent_skills(id) on delete cascade,
            version integer not null check (version >= 1),
            instructions text not null,
            allowed_tools_json text not null,
            input_schema_json text not null,
            resources_json text not null,
            digest text not null,
            created_by text not null,
            created_at text not null,
            primary key (skill_id, version)
        );

        create table if not exists agent_skill_test_runs (
            id integer primary key autoincrement,
            skill_id text not null references agent_skills(id) on delete cascade,
            skill_version integer not null,
            client_id text not null references clients(client_id) on delete cascade,
            actor text not null,
            input_digest text not null,
            status text not null check (status in ('passed', 'failed')),
            output_json text not null,
            error_detail text not null default '',
            created_at text not null
        );

        create index if not exists idx_agent_skill_test_runs
        on agent_skill_test_runs (client_id, skill_id, created_at desc);

        create table if not exists agent_iteration_sessions (
            id text primary key,
            client_id text not null references clients(client_id) on delete cascade,
            source_type text not null check (source_type in ('agent', 'skill')),
            source_id text not null,
            source_version integer not null check (source_version >= 1),
            entity_id text not null,
            instruction text not null default '',
            status text not null
              check (status in (
                'awaiting_continue', 'pending_approval', 'completed',
                'failed', 'rejected', 'cancelled'
              )),
            current_step integer not null default 0 check (current_step >= 0),
            steps_json text not null,
            state_json text not null default '{}',
            approval_id integer,
            created_by text not null,
            created_at text not null,
            updated_at text not null
        );

        create index if not exists idx_agent_iteration_sessions
        on agent_iteration_sessions (client_id, status, updated_at desc);

        create table if not exists agent_iteration_events (
            id integer primary key autoincrement,
            session_id text not null references agent_iteration_sessions(id) on delete cascade,
            ordinal integer not null check (ordinal >= 0),
            event_type text not null,
            step_index integer,
            tool_id text,
            status text not null,
            input_json text not null default '{}',
            output_json text not null default '{}',
            approval_id integer,
            actor text not null,
            created_at text not null,
            unique (session_id, ordinal)
        );

        create table if not exists technician_profiles (
            client_id text not null references clients(client_id) on delete cascade,
            technician_id text not null,
            display_name text not null,
            timezone text not null default 'UTC',
            working_hours_json text not null default '{}',
            expertise_json text not null default '[]',
            client_familiarity integer not null default 0
              check (client_familiarity between 0 and 5),
            capacity integer not null default 40 check (capacity between 1 and 100),
            enabled integer not null default 1 check (enabled in (0, 1)),
            created_by text not null,
            created_at text not null,
            updated_at text not null,
            primary key (client_id, technician_id)
        );

        create table if not exists technician_workloads (
            id integer primary key autoincrement,
            client_id text not null references clients(client_id) on delete cascade,
            technician_id text not null,
            open_tickets integer not null default 0 check (open_tickets >= 0),
            active_incidents integer not null default 0 check (active_incidents >= 0),
            scheduled_changes integer not null default 0 check (scheduled_changes >= 0),
            unavailable_until text,
            source text not null,
            observed_at text not null,
            created_by text not null,
            foreign key (client_id, technician_id)
              references technician_profiles(client_id, technician_id) on delete cascade
        );

        create index if not exists idx_technician_workloads_latest
        on technician_workloads (client_id, technician_id, observed_at desc, id desc);

        create table if not exists ticket_attachments (
            id text primary key,
            client_id text not null references clients(client_id) on delete cascade,
            ticket_id text not null,
            filename text not null,
            media_type text not null,
            byte_size integer not null check (byte_size > 0),
            sha256 text not null,
            storage_path text not null,
            status text not null default 'stored' check (status in ('stored', 'deleted')),
            uploaded_by text not null,
            created_at text not null
        );

        create index if not exists idx_ticket_attachments
        on ticket_attachments (client_id, ticket_id, created_at desc);

        create table if not exists ticket_attachment_analyses (
            id integer primary key autoincrement,
            attachment_id text not null references ticket_attachments(id) on delete cascade,
            client_id text not null references clients(client_id) on delete cascade,
            ticket_id text not null,
            status text not null check (status in ('ready', 'blocked', 'failed')),
            provider text not null,
            model text not null,
            result_json text not null,
            error_detail text not null default '',
            requested_by text not null,
            created_at text not null
        );

        create index if not exists idx_ticket_attachment_analyses
        on ticket_attachment_analyses (client_id, ticket_id, attachment_id, created_at desc);
        """
    for statement in schema.split(";"):
        if statement.strip():
            connection.execute(statement)


def require_client(store: Store, client_id: str) -> str:
    normalized = validate_identifier(client_id, "client_id")
    scope = BoundClients(frozenset({normalized}))
    if store.get_client(scope, normalized) is None:
        raise AgentPlatformNotFoundError("client was not found")
    return normalized


def validate_identifier(value: str, label: str, *, max_length: int = 128) -> str:
    if not isinstance(value, str):
        raise AgentPlatformError(f"{label} must be text")
    normalized = value.strip()
    if not normalized or len(normalized) > max_length or not _ID_RE.fullmatch(normalized):
        raise AgentPlatformError(
            f"{label} must be 1-{max_length} characters using letters, numbers, '.', '_', ':', or '-'"
        )
    return normalized


def validate_key(value: str, label: str = "key") -> str:
    if not isinstance(value, str):
        raise AgentPlatformError(f"{label} must be text")
    normalized = value.strip()
    if not normalized or not _KEY_RE.fullmatch(normalized):
        raise AgentPlatformError(
            f"{label} must be 1-128 characters using letters, numbers, '.', '_', ':', or '-'"
        )
    return normalized


def validate_text(
    value: str,
    label: str,
    *,
    minimum: int = 0,
    maximum: int,
    strip: bool = True,
) -> str:
    if not isinstance(value, str):
        raise AgentPlatformError(f"{label} must be text")
    normalized = value.strip() if strip else value
    if len(normalized) < minimum or len(normalized) > maximum:
        raise AgentPlatformError(f"{label} must contain {minimum}-{maximum} characters")
    if any(ord(character) < 32 and character not in "\n\r\t" for character in normalized):
        raise AgentPlatformError(f"{label} contains unsupported control characters")
    return normalized


def json_dumps(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def json_loads_object(value: str) -> dict[str, Any]:
    try:
        payload = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {}
    return dict(payload) if isinstance(payload, Mapping) else {}


def json_loads_list(value: str) -> list[Any]:
    try:
        payload = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return []
    return list(payload) if isinstance(payload, Sequence) and not isinstance(payload, (str, bytes)) else []


def digest_json(value: object) -> str:
    return hashlib.sha256(json_dumps(value).encode("utf-8")).hexdigest()


def safe_json_value(value: object, *, max_bytes: int = 32_768) -> object:
    try:
        encoded = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise AgentPlatformError("value must be JSON serializable") from exc
    if len(encoded) > max_bytes:
        raise AgentPlatformError(f"value exceeds the {max_bytes}-byte limit")
    return json.loads(encoded.decode("utf-8"))


def actor_identifier(value: str | None) -> str:
    if value is None:
        return "api"
    normalized = value.strip()
    if not normalized:
        return "api"
    return normalized[:128]


def parse_iso_timestamp(value: str | None, label: str) -> str | None:
    if value is None or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise AgentPlatformError(f"{label} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).isoformat()


__all__ = [
    "AGENT_PLATFORM_MIGRATION_VERSION",
    "AgentPlatformConflictError",
    "AgentPlatformError",
    "AgentPlatformNotFoundError",
    "actor_identifier",
    "digest_json",
    "ensure_schema",
    "json_dumps",
    "json_loads_list",
    "json_loads_object",
    "parse_iso_timestamp",
    "require_client",
    "safe_json_value",
    "utc_now",
    "validate_identifier",
    "validate_key",
    "validate_text",
]
