from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from wait_local_agent.migrations import Migration, MigrationRunner
from wait_local_agent.models import utc_now

if TYPE_CHECKING:
    from wait_local_agent.store import Store

MICROSOFT_ADMIN_CAPABILITY = "microsoft_admin"
SUPPORTED_CAPABILITIES = frozenset({MICROSOFT_ADMIN_CAPABILITY})
CAPABILITY_MIGRATION_VERSION = 1000
_GLOBAL_SCOPE = ""
_CAPABILITY_KEY_RE = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")


@dataclass(frozen=True)
class CapabilityGrant:
    principal_id: str
    capability_key: str
    client_id: str | None
    active: bool
    granted_by: str
    updated_by: str
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class PrincipalSummary:
    principal_id: str
    kind: str
    display_name: str
    active: bool
    client_roles: tuple[tuple[str, str], ...]
    global_roles: tuple[str, ...]


def ensure_capability_schema(store: Store) -> None:
    """Apply the capability-grant migration to the canonical local SQLite store."""

    with store._connect() as connection:  # noqa: SLF001 - same-store extension migration
        MigrationRunner(connection).run(
            (
                Migration(
                    CAPABILITY_MIGRATION_VERSION,
                    "principal_capability_grants",
                    _apply_capability_migration,
                ),
            )
        )


def active_capability_grants(store: Store, principal_id: str) -> frozenset[tuple[str, str | None]]:
    ensure_capability_schema(store)
    normalized_principal = _principal_id(principal_id)
    with store._connect() as connection:  # noqa: SLF001 - canonical store connection
        rows = connection.execute(
            """
            select capability_key, client_scope
            from principal_capability_grants
            where principal_id = ? and active = 1
            order by capability_key, client_scope
            """,
            (normalized_principal,),
        ).fetchall()
    return frozenset((str(row[0]), _scope_to_client_id(str(row[1]))) for row in rows)


def list_capability_grants(
    store: Store,
    *,
    principal_id: str | None = None,
    capability_key: str | None = None,
) -> list[CapabilityGrant]:
    ensure_capability_schema(store)
    clauses: list[str] = []
    params: list[object] = []
    if principal_id is not None:
        clauses.append("principal_id = ?")
        params.append(_principal_id(principal_id))
    if capability_key is not None:
        clauses.append("capability_key = ?")
        params.append(_capability_key(capability_key))
    where = f"where {' and '.join(clauses)}" if clauses else ""
    with store._connect() as connection:  # noqa: SLF001 - canonical store connection
        rows = connection.execute(
            f"""
            select principal_id, capability_key, client_scope, active,
                   granted_by, updated_by, created_at, updated_at
            from principal_capability_grants
            {where}
            order by principal_id, capability_key, client_scope
            """,  # nosec B608 - WHERE fragments are fixed strings; values are parameters
            params,
        ).fetchall()
    return [_grant_from_row(row) for row in rows]


def grant_capability(
    store: Store,
    *,
    principal_id: str,
    capability_key: str,
    client_id: str | None,
    actor_id: str,
) -> CapabilityGrant:
    ensure_capability_schema(store)
    normalized_principal = _principal_id(principal_id)
    normalized_capability = _capability_key(capability_key)
    normalized_client = _client_id(client_id)
    normalized_actor = _actor_id(actor_id)
    now = utc_now()
    scope = normalized_client or _GLOBAL_SCOPE
    with store._connect() as connection:  # noqa: SLF001 - canonical store connection
        _validate_grant_target(connection, normalized_principal, normalized_client)
        connection.execute(
            """
            insert into principal_capability_grants (
                principal_id, capability_key, client_scope, active,
                granted_by, updated_by, created_at, updated_at
            ) values (?, ?, ?, 1, ?, ?, ?, ?)
            on conflict (principal_id, capability_key, client_scope) do update set
                active = 1,
                updated_by = excluded.updated_by,
                updated_at = excluded.updated_at
            """,
            (
                normalized_principal,
                normalized_capability,
                scope,
                normalized_actor,
                normalized_actor,
                now,
                now,
            ),
        )
        row = connection.execute(
            """
            select principal_id, capability_key, client_scope, active,
                   granted_by, updated_by, created_at, updated_at
            from principal_capability_grants
            where principal_id = ? and capability_key = ? and client_scope = ?
            """,
            (normalized_principal, normalized_capability, scope),
        ).fetchone()
    if row is None:  # pragma: no cover - protected by the preceding upsert
        raise RuntimeError("capability grant was not persisted")
    return _grant_from_row(row)


def revoke_capability(
    store: Store,
    *,
    principal_id: str,
    capability_key: str,
    client_id: str | None,
    actor_id: str,
) -> CapabilityGrant:
    ensure_capability_schema(store)
    normalized_principal = _principal_id(principal_id)
    normalized_capability = _capability_key(capability_key)
    normalized_client = _client_id(client_id)
    normalized_actor = _actor_id(actor_id)
    scope = normalized_client or _GLOBAL_SCOPE
    with store._connect() as connection:  # noqa: SLF001 - canonical store connection
        cursor = connection.execute(
            """
            update principal_capability_grants
            set active = 0, updated_by = ?, updated_at = ?
            where principal_id = ? and capability_key = ? and client_scope = ?
            """,
            (normalized_actor, utc_now(), normalized_principal, normalized_capability, scope),
        )
        if cursor.rowcount != 1:
            raise KeyError((normalized_principal, normalized_capability, normalized_client))
        row = connection.execute(
            """
            select principal_id, capability_key, client_scope, active,
                   granted_by, updated_by, created_at, updated_at
            from principal_capability_grants
            where principal_id = ? and capability_key = ? and client_scope = ?
            """,
            (normalized_principal, normalized_capability, scope),
        ).fetchone()
    if row is None:  # pragma: no cover - protected by the update row count
        raise RuntimeError("capability grant disappeared after revoke")
    return _grant_from_row(row)


def list_principals(store: Store) -> list[PrincipalSummary]:
    ensure_capability_schema(store)
    with store._connect() as connection:  # noqa: SLF001 - canonical store connection
        principals = connection.execute(
            """
            select principal_id, kind, display_name, active
            from principals
            order by display_name, principal_id
            """
        ).fetchall()
        result: list[PrincipalSummary] = []
        for principal in principals:
            principal_id = str(principal[0])
            client_roles = tuple(
                (str(row[0]), str(row[1]))
                for row in connection.execute(
                    """
                    select client_id, role from principal_client_roles
                    where principal_id = ? order by client_id, role
                    """,
                    (principal_id,),
                )
            )
            global_roles = tuple(
                str(row[0])
                for row in connection.execute(
                    """
                    select role from principal_global_roles
                    where principal_id = ? order by role
                    """,
                    (principal_id,),
                )
            )
            result.append(
                PrincipalSummary(
                    principal_id=principal_id,
                    kind=str(principal[1]),
                    display_name=str(principal[2]),
                    active=bool(principal[3]),
                    client_roles=client_roles,
                    global_roles=global_roles,
                )
            )
    return result


def _apply_capability_migration(connection) -> None:
    connection.execute(
        """
        create table if not exists principal_capability_grants (
            principal_id text not null references principals(principal_id) on delete cascade,
            capability_key text not null,
            client_scope text not null default '',
            active integer not null default 1 check (active in (0, 1)),
            granted_by text not null,
            updated_by text not null,
            created_at text not null,
            updated_at text not null,
            primary key (principal_id, capability_key, client_scope)
        )
        """
    )
    connection.execute(
        """
        create index if not exists idx_principal_capability_grants_active
        on principal_capability_grants (principal_id, capability_key, active, client_scope)
        """
    )


def _validate_grant_target(connection, principal_id: str, client_id: str | None) -> None:
    principal = connection.execute(
        "select active from principals where principal_id = ?",
        (principal_id,),
    ).fetchone()
    if principal is None:
        raise KeyError(principal_id)
    if not bool(principal[0]):
        raise ValueError("capability grants require an active principal")
    if client_id is None:
        is_msp_admin = connection.execute(
            """
            select 1 from principal_global_roles
            where principal_id = ? and role = 'msp_admin'
            """,
            (principal_id,),
        ).fetchone()
        if is_msp_admin is None:
            raise ValueError("global capability grants require the msp_admin role")
        return
    client_exists = connection.execute(
        "select 1 from clients where client_id = ? and status <> 'quarantine'",
        (client_id,),
    ).fetchone()
    if client_exists is None:
        raise KeyError(client_id)
    has_client_role = connection.execute(
        "select 1 from principal_client_roles where principal_id = ? and client_id = ?",
        (principal_id, client_id),
    ).fetchone()
    is_msp_admin = connection.execute(
        "select 1 from principal_global_roles where principal_id = ? and role = 'msp_admin'",
        (principal_id,),
    ).fetchone()
    if has_client_role is None and is_msp_admin is None:
        raise ValueError("principal has no role for the requested client")


def _grant_from_row(row) -> CapabilityGrant:
    return CapabilityGrant(
        principal_id=str(row[0]),
        capability_key=str(row[1]),
        client_id=_scope_to_client_id(str(row[2])),
        active=bool(row[3]),
        granted_by=str(row[4]),
        updated_by=str(row[5]),
        created_at=str(row[6]),
        updated_at=str(row[7]),
    )


def _principal_id(value: str) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > 128:
        raise ValueError("principal_id must be 1-128 characters")
    return normalized


def _actor_id(value: str) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > 128:
        raise ValueError("actor_id must be 1-128 characters")
    return normalized


def _capability_key(value: str) -> str:
    normalized = value.strip().lower()
    if not _CAPABILITY_KEY_RE.fullmatch(normalized):
        raise ValueError("capability_key is invalid")
    if normalized not in SUPPORTED_CAPABILITIES:
        raise ValueError("unsupported capability_key")
    return normalized


def _client_id(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized or len(normalized) > 128 or normalized == "__quarantine__":
        raise ValueError("client_id is invalid")
    return normalized


def _scope_to_client_id(scope: str) -> str | None:
    return scope or None
