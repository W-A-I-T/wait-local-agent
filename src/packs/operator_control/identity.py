"""Governed local principal and credential lifecycle operations."""

from __future__ import annotations

import re
import secrets
import sqlite3
from dataclasses import asdict, dataclass
from typing import Literal

from wait_local_agent.capabilities import ensure_capability_schema, list_principals
from wait_local_agent.models import utc_now
from wait_local_agent.reports.renderers import redact_text
from wait_local_agent.store import Store, hash_credential

PrincipalKind = Literal["customer", "staff"]
ClientRole = Literal["end_user", "viewer", "technician", "admin"]

_PRINCIPAL_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$")
_VALID_ROLES = frozenset({"end_user", "viewer", "technician", "admin"})


class IdentityConflictError(RuntimeError):
    """Raised when a requested identity change would create an unsafe state."""


@dataclass(frozen=True)
class CredentialSummary:
    fingerprint: str
    active: bool
    created_at: str


@dataclass(frozen=True)
class PrincipalDetail:
    principal_id: str
    kind: str
    display_name: str
    active: bool
    client_roles: tuple[tuple[str, str], ...]
    global_roles: tuple[str, ...]
    credentials: tuple[CredentialSummary, ...]


def list_principal_details(store: Store) -> list[PrincipalDetail]:
    """Return principals and non-secret credential metadata."""

    ensure_capability_schema(store)
    summaries = list_principals(store)
    with store._connect() as connection:  # noqa: SLF001 - same canonical store extension
        credentials = connection.execute(
            """
            select principal_id, credential_hash, active, created_at
            from principal_credentials
            order by principal_id, created_at desc
            """
        ).fetchall()
    by_principal: dict[str, list[CredentialSummary]] = {}
    for row in credentials:
        by_principal.setdefault(str(row["principal_id"]), []).append(
            CredentialSummary(
                fingerprint=_fingerprint(str(row["credential_hash"])),
                active=bool(row["active"]),
                created_at=str(row["created_at"]),
            )
        )
    return [
        PrincipalDetail(
            principal_id=summary.principal_id,
            kind=summary.kind,
            display_name=summary.display_name,
            active=summary.active,
            client_roles=summary.client_roles,
            global_roles=summary.global_roles,
            credentials=tuple(by_principal.get(summary.principal_id, [])),
        )
        for summary in summaries
    ]


def get_principal_detail(store: Store, principal_id: str) -> PrincipalDetail:
    normalized = _principal_id(principal_id)
    for principal in list_principal_details(store):
        if principal.principal_id == normalized:
            return principal
    raise KeyError(normalized)


def create_principal(
    store: Store,
    *,
    principal_id: str,
    kind: PrincipalKind,
    display_name: str,
    client_roles: tuple[tuple[str, ClientRole], ...],
    msp_admin: bool,
    issue_credential: bool,
) -> tuple[PrincipalDetail, str | None]:
    """Create one principal atomically and optionally issue a one-time credential."""

    ensure_capability_schema(store)
    normalized_id = _principal_id(principal_id)
    normalized_kind = _principal_kind(kind)
    safe_name = redact_text(_bounded_text(display_name, "display_name", 200))
    roles = _normalize_roles(client_roles)
    _validate_principal_shape(normalized_kind, roles, msp_admin)
    token = _new_token() if issue_credential else None
    now = utc_now()

    with store._connect() as connection:  # noqa: SLF001 - same canonical store extension
        _validate_role_clients(connection, roles)
        try:
            connection.execute(
                """
                insert into principals (principal_id, kind, display_name, active, created_at)
                values (?, ?, ?, 1, ?)
                """,
                (normalized_id, normalized_kind, safe_name, now),
            )
            for client_id, role in roles:
                connection.execute(
                    """
                    insert into principal_client_roles (principal_id, client_id, role)
                    values (?, ?, ?)
                    """,
                    (normalized_id, client_id, role),
                )
            if msp_admin:
                connection.execute(
                    "insert into principal_global_roles (principal_id, role) values (?, 'msp_admin')",
                    (normalized_id,),
                )
            if token is not None:
                connection.execute(
                    """
                    insert into principal_credentials (principal_id, credential_hash, active, created_at)
                    values (?, ?, 1, ?)
                    """,
                    (normalized_id, hash_credential(token), now),
                )
        except sqlite3.IntegrityError as exc:
            raise IdentityConflictError("principal already exists or its role bindings conflict") from exc

    return get_principal_detail(store, normalized_id), token


def update_principal(
    store: Store,
    *,
    principal_id: str,
    display_name: str | None,
    active: bool | None,
    actor_principal_id: str | None,
) -> PrincipalDetail:
    ensure_capability_schema(store)
    normalized_id = _principal_id(principal_id)
    with store._connect() as connection:  # noqa: SLF001
        row = connection.execute(
            "select active from principals where principal_id = ?",
            (normalized_id,),
        ).fetchone()
        if row is None:
            raise KeyError(normalized_id)
        if active is False:
            _guard_self_deactivation(normalized_id, actor_principal_id)
            _guard_last_msp_admin(connection, normalized_id)
        if display_name is not None:
            safe_name = redact_text(_bounded_text(display_name, "display_name", 200))
            connection.execute(
                "update principals set display_name = ? where principal_id = ?",
                (safe_name, normalized_id),
            )
        if active is not None:
            connection.execute(
                "update principals set active = ? where principal_id = ?",
                (int(active), normalized_id),
            )
            if not active:
                connection.execute(
                    "update principal_credentials set active = 0 where principal_id = ?",
                    (normalized_id,),
                )
                connection.execute(
                    "update principal_capability_grants set active = 0, updated_at = ? where principal_id = ?",
                    (utc_now(), normalized_id),
                )
    return get_principal_detail(store, normalized_id)


def deactivate_principal(store: Store, *, principal_id: str, actor_principal_id: str | None) -> PrincipalDetail:
    return update_principal(
        store,
        principal_id=principal_id,
        display_name=None,
        active=False,
        actor_principal_id=actor_principal_id,
    )


def rotate_credential(store: Store, *, principal_id: str) -> tuple[PrincipalDetail, str]:
    """Revoke prior credentials and return a new secret exactly once."""

    normalized_id = _principal_id(principal_id)
    token = _new_token()
    now = utc_now()
    with store._connect() as connection:  # noqa: SLF001
        principal = connection.execute(
            "select active from principals where principal_id = ?",
            (normalized_id,),
        ).fetchone()
        if principal is None:
            raise KeyError(normalized_id)
        if not bool(principal["active"]):
            raise IdentityConflictError("inactive principals cannot receive credentials")
        connection.execute(
            "update principal_credentials set active = 0 where principal_id = ?",
            (normalized_id,),
        )
        connection.execute(
            """
            insert into principal_credentials (principal_id, credential_hash, active, created_at)
            values (?, ?, 1, ?)
            """,
            (normalized_id, hash_credential(token), now),
        )
    return get_principal_detail(store, normalized_id), token


def revoke_credentials(
    store: Store,
    *,
    principal_id: str,
    actor_principal_id: str | None,
) -> PrincipalDetail:
    normalized_id = _principal_id(principal_id)
    _guard_self_deactivation(normalized_id, actor_principal_id)
    with store._connect() as connection:  # noqa: SLF001
        principal = connection.execute(
            "select 1 from principals where principal_id = ?",
            (normalized_id,),
        ).fetchone()
        if principal is None:
            raise KeyError(normalized_id)
        _guard_last_msp_admin(connection, normalized_id)
        connection.execute(
            "update principal_credentials set active = 0 where principal_id = ?",
            (normalized_id,),
        )
    return get_principal_detail(store, normalized_id)


def set_client_role(
    store: Store,
    *,
    principal_id: str,
    client_id: str,
    role: ClientRole,
) -> PrincipalDetail:
    ensure_capability_schema(store)
    normalized_id = _principal_id(principal_id)
    normalized_client = _client_id(client_id)
    normalized_role = _role(role)
    with store._connect() as connection:  # noqa: SLF001
        principal = connection.execute(
            "select kind from principals where principal_id = ?",
            (normalized_id,),
        ).fetchone()
        if principal is None:
            raise KeyError(normalized_id)
        _validate_role_clients(connection, ((normalized_client, normalized_role),))
        if str(principal["kind"]) == "customer":
            existing = connection.execute(
                "select distinct client_id from principal_client_roles where principal_id = ? and client_id <> ?",
                (normalized_id, normalized_client),
            ).fetchall()
            if existing:
                raise IdentityConflictError("customer principals can belong to exactly one client")
        connection.execute(
            "delete from principal_client_roles where principal_id = ? and client_id = ?",
            (normalized_id, normalized_client),
        )
        connection.execute(
            "insert into principal_client_roles (principal_id, client_id, role) values (?, ?, ?)",
            (normalized_id, normalized_client, normalized_role),
        )
    return get_principal_detail(store, normalized_id)


def remove_client_role(
    store: Store,
    *,
    principal_id: str,
    client_id: str,
    actor_principal_id: str | None,
) -> PrincipalDetail:
    ensure_capability_schema(store)
    normalized_id = _principal_id(principal_id)
    normalized_client = _client_id(client_id)
    with store._connect() as connection:  # noqa: SLF001
        principal = connection.execute(
            "select kind, active from principals where principal_id = ?",
            (normalized_id,),
        ).fetchone()
        if principal is None:
            raise KeyError(normalized_id)
        remaining = connection.execute(
            "select count(distinct client_id) from principal_client_roles where principal_id = ? and client_id <> ?",
            (normalized_id, normalized_client),
        ).fetchone()
        is_msp_admin = _is_msp_admin(connection, normalized_id)
        if bool(principal["active"]) and int(remaining[0]) == 0 and not is_msp_admin:
            raise IdentityConflictError("an active principal must retain a client role or the msp_admin role")
        if normalized_id == actor_principal_id and int(remaining[0]) == 0 and not is_msp_admin:
            raise IdentityConflictError("the authenticated principal cannot remove its final access scope")
        cursor = connection.execute(
            "delete from principal_client_roles where principal_id = ? and client_id = ?",
            (normalized_id, normalized_client),
        )
        if cursor.rowcount == 0:
            raise KeyError((normalized_id, normalized_client))
        connection.execute(
            """
            update principal_capability_grants
            set active = 0, updated_at = ?
            where principal_id = ? and client_scope = ?
            """,
            (utc_now(), normalized_id, normalized_client),
        )
    return get_principal_detail(store, normalized_id)


def set_msp_admin(
    store: Store,
    *,
    principal_id: str,
    enabled: bool,
    actor_principal_id: str | None,
) -> PrincipalDetail:
    ensure_capability_schema(store)
    normalized_id = _principal_id(principal_id)
    with store._connect() as connection:  # noqa: SLF001
        principal = connection.execute(
            "select kind, active from principals where principal_id = ?",
            (normalized_id,),
        ).fetchone()
        if principal is None:
            raise KeyError(normalized_id)
        if str(principal["kind"]) != "staff":
            raise IdentityConflictError("only staff principals can receive the msp_admin role")
        if not enabled:
            if normalized_id == actor_principal_id:
                raise IdentityConflictError("the authenticated principal cannot remove its own msp_admin role")
            _guard_last_msp_admin(connection, normalized_id)
            remaining = connection.execute(
                "select count(*) from principal_client_roles where principal_id = ?",
                (normalized_id,),
            ).fetchone()
            if bool(principal["active"]) and int(remaining[0]) == 0:
                raise IdentityConflictError("an active principal must retain a client role or the msp_admin role")
            connection.execute(
                "delete from principal_global_roles where principal_id = ? and role = 'msp_admin'",
                (normalized_id,),
            )
            connection.execute(
                """
                update principal_capability_grants
                set active = 0, updated_at = ?
                where principal_id = ? and client_scope = ''
                """,
                (utc_now(), normalized_id),
            )
        else:
            connection.execute(
                """
                insert into principal_global_roles (principal_id, role)
                values (?, 'msp_admin')
                on conflict (principal_id, role) do nothing
                """,
                (normalized_id,),
            )
    return get_principal_detail(store, normalized_id)


def principal_to_dict(principal: PrincipalDetail) -> dict[str, object]:
    payload = asdict(principal)
    payload["client_roles"] = [list(role) for role in principal.client_roles]
    payload["global_roles"] = list(principal.global_roles)
    payload["credentials"] = [asdict(credential) for credential in principal.credentials]
    return payload


def _principal_id(value: str) -> str:
    normalized = value.strip()
    if not _PRINCIPAL_ID_RE.fullmatch(normalized):
        raise ValueError("principal_id must be 1-128 characters using letters, numbers, '.', '_', ':', '@', or '-'")
    return normalized


def _principal_kind(value: str) -> PrincipalKind:
    normalized = value.strip().lower()
    if normalized not in {"customer", "staff"}:
        raise ValueError("kind must be customer or staff")
    return normalized  # type: ignore[return-value]


def _client_id(value: str) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > 128:
        raise ValueError("client_id must be 1-128 characters")
    if normalized == "__quarantine__":
        raise ValueError("the quarantine client cannot be assigned to a principal")
    return normalized


def _role(value: str) -> ClientRole:
    normalized = value.strip().lower()
    if normalized not in _VALID_ROLES:
        raise ValueError("role must be end_user, viewer, technician, or admin")
    return normalized  # type: ignore[return-value]


def _normalize_roles(client_roles: tuple[tuple[str, ClientRole], ...]) -> tuple[tuple[str, ClientRole], ...]:
    normalized: dict[str, ClientRole] = {}
    for client_id, role in client_roles:
        normalized[_client_id(client_id)] = _role(role)
    return tuple(sorted(normalized.items()))


def _validate_principal_shape(
    kind: PrincipalKind,
    roles: tuple[tuple[str, ClientRole], ...],
    msp_admin: bool,
) -> None:
    if kind == "customer":
        if msp_admin:
            raise IdentityConflictError("customer principals cannot receive the msp_admin role")
        if len(roles) != 1:
            raise IdentityConflictError("customer principals require exactly one client role")
    elif not roles and not msp_admin:
        raise IdentityConflictError("staff principals require a client role or the msp_admin role")


def _validate_role_clients(connection: sqlite3.Connection, roles: tuple[tuple[str, str], ...]) -> None:
    for client_id, _ in roles:
        row = connection.execute(
            "select status from clients where client_id = ?",
            (client_id,),
        ).fetchone()
        if row is None:
            raise KeyError(client_id)
        if str(row["status"]) == "quarantine":
            raise ValueError("the quarantine client cannot be assigned to a principal")


def _guard_self_deactivation(principal_id: str, actor_principal_id: str | None) -> None:
    if actor_principal_id and principal_id == actor_principal_id:
        raise IdentityConflictError("the authenticated principal cannot revoke or deactivate itself")


def _guard_last_msp_admin(connection: sqlite3.Connection, principal_id: str) -> None:
    if not _is_msp_admin(connection, principal_id):
        return
    remaining = connection.execute(
        """
        select count(distinct p.principal_id)
        from principals p
        join principal_global_roles pgr on pgr.principal_id = p.principal_id and pgr.role = 'msp_admin'
        join principal_credentials pc on pc.principal_id = p.principal_id and pc.active = 1
        where p.active = 1
        """
    ).fetchone()
    if int(remaining[0]) <= 1:
        raise IdentityConflictError("the final active msp_admin credential cannot be removed")


def _is_msp_admin(connection: sqlite3.Connection, principal_id: str) -> bool:
    return connection.execute(
        "select 1 from principal_global_roles where principal_id = ? and role = 'msp_admin'",
        (principal_id,),
    ).fetchone() is not None


def _bounded_text(value: str, label: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be text")
    normalized = value.strip()
    if len(normalized) > maximum:
        raise ValueError(f"{label} must be at most {maximum} characters")
    if any(ord(character) < 32 and character not in "\t\n\r" for character in normalized):
        raise ValueError(f"{label} contains unsupported control characters")
    return normalized


def _new_token() -> str:
    return f"wait_{secrets.token_urlsafe(32)}"


def _fingerprint(credential_hash: str) -> str:
    return f"sha256:{credential_hash[:12]}"


__all__ = [
    "ClientRole",
    "CredentialSummary",
    "IdentityConflictError",
    "PrincipalDetail",
    "PrincipalKind",
    "create_principal",
    "deactivate_principal",
    "get_principal_detail",
    "list_principal_details",
    "principal_to_dict",
    "remove_client_role",
    "revoke_credentials",
    "rotate_credential",
    "set_client_role",
    "set_msp_admin",
    "update_principal",
]
