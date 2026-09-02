from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from fastapi import HTTPException, Request

if TYPE_CHECKING:
    from wait_local_agent.rbac import AuthContext


@dataclass(frozen=True, slots=True)
class BoundClients:
    """A tenant scope containing one or more explicitly bound client IDs."""

    client_ids: frozenset[str]

    def __post_init__(self) -> None:
        if not self.client_ids or any(not client_id for client_id in self.client_ids):
            raise ValueError("BoundClients requires at least one non-empty client_id")

    @property
    def client_id(self) -> str | None:
        """Return the sole client ID; singular-only consumers fail closed for multi-client scopes."""

        if len(self.client_ids) != 1:
            raise HTTPException(status_code=403, detail="operation requires a single client scope")
        return next(iter(self.client_ids))


@dataclass(frozen=True, slots=True)
class AllClients:
    """An explicit all-client scope, created only by resolve_client_scope."""

    @property
    def client_id(self) -> None:
        return None


ClientScope = BoundClients | AllClients


def requested_client_from(
    request: Request,
    explicit_client_id: str | None = None,
    *,
    conflict_detail: str = "conflicting client scopes",
) -> str | None:
    """Resolve an explicit client parameter and the UI scope hint.

    The returned value remains untrusted input. Callers must pass it to
    ``resolve_client_scope`` before using it for any data access.
    """

    explicit = explicit_client_id.strip() if explicit_client_id else None
    header = request.headers.get("X-WAIT-Client-ID", "").strip() or None
    if explicit == "":
        explicit = None
    if explicit and header and explicit != header:
        raise HTTPException(status_code=400, detail=conflict_detail)
    return explicit or header


def resolve_client_scope(
    context: AuthContext,
    requested_client_id: str | None = None,
) -> ClientScope:
    """Resolve a request's client scope without treating None as an implicit wildcard.

    Demo mode and MSP administrators are deliberate single-operator scopes.
    They may request a specific client, otherwise they receive an all-client
    scope. Every other principal is restricted to its persisted client
    memberships.
    """

    requested = requested_client_id.strip() if requested_client_id else None
    if requested == "":
        requested = None

    if context.demo_mode:
        return BoundClients(frozenset({requested})) if requested else AllClients()

    if context.is_msp_admin:
        if requested:
            return BoundClients(frozenset({requested}))
        # An appliance operator is cross-client even for entity-scoped calls
        # that do not explicitly opt into list-wide access.  The requested
        # client branch above remains an explicit single-client bound scope.
        return AllClients()

    bound_clients = frozenset(client_id.strip() for client_id in context.client_ids if client_id.strip())
    if not bound_clients:
        raise HTTPException(status_code=403, detail="authenticated principal has no tenant")
    if requested and requested not in bound_clients:
        raise HTTPException(status_code=403, detail="requested tenant is outside authenticated scope")
    return BoundClients(frozenset({requested})) if requested else BoundClients(bound_clients)
