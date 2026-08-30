"""Tenant-scoped durable memory with provenance and revision history."""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import asdict, dataclass
from typing import Any, Literal, cast

from wait_local_agent.reports.renderers import redact_text, redact_value
from wait_local_agent.store import Store

from .storage import (
    AgentPlatformConflictError,
    AgentPlatformError,
    AgentPlatformNotFoundError,
    actor_identifier,
    ensure_schema,
    json_dumps,
    json_loads_object,
    parse_iso_timestamp,
    require_client,
    safe_json_value,
    utc_now,
    validate_identifier,
    validate_key,
    validate_text,
)

MemoryScope = Literal["client", "agent", "technician", "ticket"]
_SCOPE_ORDER = {"client": 0, "technician": 1, "agent": 2, "ticket": 3}
MAX_CONTEXT_MEMORIES = 50


@dataclass(frozen=True)
class MemoryRecord:
    id: str
    client_id: str
    scope_type: str
    scope_id: str
    key: str
    value: object
    summary: str
    provenance: str
    pinned: bool
    status: str
    version: int
    supersedes_id: str | None
    expires_at: str | None
    created_by: str
    created_at: str
    updated_at: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class MemoryService:
    def __init__(self, store: Store) -> None:
        self.store = store
        ensure_schema(store)

    def put(
        self,
        *,
        client_id: str,
        scope_type: MemoryScope,
        scope_id: str,
        key: str,
        value: object,
        summary: str,
        provenance: str,
        actor: str,
        pinned: bool = False,
        expires_at: str | None = None,
    ) -> MemoryRecord:
        client_id = require_client(self.store, client_id)
        scope_type, scope_id = _scope(client_id, scope_type, scope_id)
        key = validate_key(key, "memory key")
        safe_value = safe_json_value(redact_value(value))
        summary = redact_text(validate_text(summary, "summary", maximum=1_000))
        provenance = redact_text(
            validate_text(provenance, "provenance", minimum=1, maximum=1_000)
        )
        actor = actor_identifier(actor)
        expires_at = parse_iso_timestamp(expires_at, "expires_at")
        now = utc_now()
        memory_id = str(uuid.uuid4())
        with self.store._connect() as connection:  # noqa: SLF001
            latest = connection.execute(
                """
                select id, version, status from agent_memories
                where client_id = ? and scope_type = ? and scope_id = ? and memory_key = ?
                order by version desc, created_at desc limit 1
                """,
                (client_id, scope_type, scope_id, key),
            ).fetchone()
            active = connection.execute(
                """
                select id from agent_memories
                where client_id = ? and scope_type = ? and scope_id = ?
                  and memory_key = ? and status = 'active'
                """,
                (client_id, scope_type, scope_id, key),
            ).fetchone()
            supersedes_id = str(latest["id"]) if latest is not None else None
            version = int(latest["version"]) + 1 if latest is not None else 1
            if active is not None:
                connection.execute(
                    """
                    update agent_memories
                    set status = 'superseded', updated_at = ?
                    where id = ? and client_id = ? and status = 'active'
                    """,
                    (now, str(active["id"]), client_id),
                )
            try:
                connection.execute(
                    """
                    insert into agent_memories (
                        id, client_id, scope_type, scope_id, memory_key, value_json,
                        summary, provenance, pinned, status, version, supersedes_id,
                        expires_at, created_by, created_at, updated_at
                    ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        memory_id,
                        client_id,
                        scope_type,
                        scope_id,
                        key,
                        json_dumps(safe_value),
                        summary,
                        provenance,
                        int(bool(pinned)),
                        version,
                        supersedes_id,
                        expires_at,
                        actor,
                        now,
                        now,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise AgentPlatformConflictError("memory was updated concurrently") from exc
        self.store.add_audit_event(
            "agent_memory.created",
            memory_id,
            f"{scope_type}:{scope_id}:{key} version={version}",
            client_id=client_id,
            approver_id=actor,
        )
        return self.get(client_id=client_id, memory_id=memory_id, include_history=True)

    def get(
        self,
        *,
        client_id: str,
        memory_id: str,
        include_history: bool = False,
    ) -> MemoryRecord:
        client_id = require_client(self.store, client_id)
        memory_id = validate_identifier(memory_id, "memory_id")
        status_clause = "" if include_history else "and status = 'active'"
        with self.store._connect() as connection:  # noqa: SLF001
            row = connection.execute(
                f"""
                select * from agent_memories
                where id = ? and client_id = ? {status_clause}
                """,  # nosec B608 - status clause is fixed locally
                (memory_id, client_id),
            ).fetchone()
        if row is None:
            raise AgentPlatformNotFoundError("memory was not found")
        return _record(row)

    def list(
        self,
        *,
        client_id: str,
        scope_type: MemoryScope | None = None,
        scope_id: str | None = None,
        key: str | None = None,
        include_history: bool = False,
        limit: int = 50,
    ) -> list[MemoryRecord]:
        client_id = require_client(self.store, client_id)
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 200:
            raise AgentPlatformError("limit must be an integer between 1 and 200")
        clauses = ["client_id = ?"]
        params: list[object] = [client_id]
        if not include_history:
            clauses.extend(["status = 'active'", "(expires_at is null or expires_at > ?)"])
            params.append(utc_now())
        if scope_type is not None:
            if scope_type not in _SCOPE_ORDER:
                raise AgentPlatformError("scope_type is invalid")
            clauses.append("scope_type = ?")
            params.append(scope_type)
        if scope_id is not None:
            clauses.append("scope_id = ?")
            params.append(validate_identifier(scope_id, "scope_id"))
        if key is not None:
            clauses.append("memory_key = ?")
            params.append(validate_key(key, "memory key"))
        params.append(limit)
        with self.store._connect() as connection:  # noqa: SLF001
            rows = connection.execute(
                f"""
                select * from agent_memories
                where {' and '.join(clauses)}
                order by pinned desc, updated_at desc, version desc
                limit ?
                """,  # nosec B608 - clauses are fixed strings; values are parameterized
                params,
            ).fetchall()
        return [_record(row) for row in rows]

    def pin(self, *, client_id: str, memory_id: str, pinned: bool, actor: str) -> MemoryRecord:
        record = self.get(client_id=client_id, memory_id=memory_id)
        now = utc_now()
        with self.store._connect() as connection:  # noqa: SLF001
            connection.execute(
                "update agent_memories set pinned = ?, updated_at = ? where id = ? and client_id = ?",
                (int(bool(pinned)), now, record.id, record.client_id),
            )
        actor = actor_identifier(actor)
        self.store.add_audit_event(
            "agent_memory.pinned" if pinned else "agent_memory.unpinned",
            record.id,
            record.key,
            client_id=record.client_id,
            approver_id=actor,
        )
        return self.get(client_id=record.client_id, memory_id=record.id)

    def restore(self, *, client_id: str, memory_id: str, actor: str) -> MemoryRecord:
        historic = self.get(
            client_id=client_id,
            memory_id=memory_id,
            include_history=True,
        )
        if historic.status == "active":
            raise AgentPlatformConflictError("memory is already the active revision")
        return self.put(
            client_id=historic.client_id,
            scope_type=cast(MemoryScope, historic.scope_type),
            scope_id=historic.scope_id,
            key=historic.key,
            value=historic.value,
            summary=historic.summary,
            provenance=f"restored:{historic.id}",
            actor=actor,
            pinned=historic.pinned,
            expires_at=historic.expires_at,
        )

    def delete(self, *, client_id: str, memory_id: str, actor: str) -> MemoryRecord:
        record = self.get(client_id=client_id, memory_id=memory_id)
        now = utc_now()
        with self.store._connect() as connection:  # noqa: SLF001
            connection.execute(
                """
                update agent_memories set status = 'deleted', pinned = 0, updated_at = ?
                where id = ? and client_id = ? and status = 'active'
                """,
                (now, record.id, record.client_id),
            )
        actor = actor_identifier(actor)
        self.store.add_audit_event(
            "agent_memory.deleted",
            record.id,
            record.key,
            client_id=record.client_id,
            approver_id=actor,
        )
        return self.get(
            client_id=record.client_id,
            memory_id=record.id,
            include_history=True,
        )

    def resolve_context(
        self,
        *,
        client_id: str,
        agent_id: str | None = None,
        technician_id: str | None = None,
        ticket_id: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, object]]:
        client_id = require_client(self.store, client_id)
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_CONTEXT_MEMORIES:
            raise AgentPlatformError(
                f"limit must be an integer between 1 and {MAX_CONTEXT_MEMORIES}"
            )
        scopes: list[tuple[str, str]] = [("client", client_id)]
        for scope_type, raw_scope_id in (
            ("technician", technician_id),
            ("agent", agent_id),
            ("ticket", ticket_id),
        ):
            if raw_scope_id is not None:
                scopes.append((scope_type, validate_identifier(raw_scope_id, f"{scope_type}_id")))
        predicates = " or ".join("(scope_type = ? and scope_id = ?)" for _ in scopes)
        params: list[object] = [client_id, utc_now()]
        for scope_type, scope_id in scopes:
            params.extend([scope_type, scope_id])
        with self.store._connect() as connection:  # noqa: SLF001
            rows = connection.execute(
                f"""
                select * from agent_memories
                where client_id = ? and status = 'active'
                  and (expires_at is null or expires_at > ?)
                  and ({predicates})
                order by pinned desc, updated_at desc, version desc
                limit 200
                """,  # nosec B608 - predicate shape is generated from bounded scopes
                params,
            ).fetchall()
        records = [_record(row) for row in rows]
        records.sort(
            key=lambda item: (
                _SCOPE_ORDER.get(item.scope_type, -1),
                int(item.pinned),
                item.updated_at,
            ),
            reverse=True,
        )
        selected: dict[str, MemoryRecord] = {}
        for record in records:
            selected.setdefault(record.key, record)
            if len(selected) >= limit:
                break
        return [
            {
                "id": record.id,
                "key": record.key,
                "value": record.value,
                "summary": record.summary,
                "scope_type": record.scope_type,
                "scope_id": record.scope_id,
                "pinned": record.pinned,
                "version": record.version,
                "provenance": record.provenance,
                "updated_at": record.updated_at,
            }
            for record in selected.values()
        ]


def _scope(client_id: str, scope_type: str, scope_id: str) -> tuple[MemoryScope, str]:
    if scope_type not in _SCOPE_ORDER:
        raise AgentPlatformError("scope_type must be client, agent, technician, or ticket")
    typed_scope = cast(MemoryScope, scope_type)
    if scope_type == "client":
        return typed_scope, client_id
    return typed_scope, validate_identifier(scope_id, "scope_id")


def _record(row: sqlite3.Row) -> MemoryRecord:
    return MemoryRecord(
        id=str(row["id"]),
        client_id=str(row["client_id"]),
        scope_type=str(row["scope_type"]),
        scope_id=str(row["scope_id"]),
        key=str(row["memory_key"]),
        value=json_loads_object(str(row["value_json"]))
        if str(row["value_json"]).startswith("{")
        else _json_scalar(str(row["value_json"])),
        summary=str(row["summary"]),
        provenance=str(row["provenance"]),
        pinned=bool(row["pinned"]),
        status=str(row["status"]),
        version=int(row["version"]),
        supersedes_id=str(row["supersedes_id"]) if row["supersedes_id"] is not None else None,
        expires_at=str(row["expires_at"]) if row["expires_at"] is not None else None,
        created_by=str(row["created_by"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


def _json_scalar(value: str) -> Any:
    import json

    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return None


__all__ = ["MAX_CONTEXT_MEMORIES", "MemoryRecord", "MemoryService", "MemoryScope"]
