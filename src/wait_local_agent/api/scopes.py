"""Shared client-scope resolution helpers for API routes."""

from __future__ import annotations

from fastapi import HTTPException, Request

from wait_local_agent.client_scope import (
    AllClients,
    BoundClients,
    ClientScope,
    requested_client_from,
    resolve_client_scope,
)
from wait_local_agent.config import (
    Settings,
)
from wait_local_agent.connector_factory import (
    ConnectorFactoryError,
    build_read_client_for_client,
)
from wait_local_agent.diagnostics import (
    valid_correlation_id,
)
from wait_local_agent.m365_auth import M365ConnectionResolver, M365ProfileResolutionError
from wait_local_agent.m365_graph import (
    M365GraphClient,
)
from wait_local_agent.rbac import (
    AuthContext,
    Role,
)
from wait_local_agent.store import (
    Store,
    _normalize_client_id,
)
from wait_local_agent.teams_graph import TeamsGraphClient
from wait_local_agent.vault import SecretVault


def _connector_read_client(
    request: Request,
    context: AuthContext,
    connector_type: str,
    appliance_client: object,
    *,
    requested_client_id: str | None = None,
    m365_teams: bool = False,
    settings: Settings,
    store: Store,
    vault: SecretVault,
    m365_connection_resolver: M365ConnectionResolver,
) -> object:
    """Resolve a provider read client without widening a tenant scope."""
    scope = resolve_client_scope(context, requested_client_from(request, requested_client_id))
    if isinstance(scope, AllClients):
        return appliance_client
    client_id = scope.client_id
    if client_id is None:  # pragma: no cover - BoundClients rejects empty scopes
        raise HTTPException(status_code=403, detail="client scope is required")
    if connector_type == "m365":
        transport = getattr(
            request.app.state,
            f"{connector_type}_transport",
            getattr(appliance_client, "transport", None),
        )
        try:
            connection = m365_connection_resolver.resolve(client_id)
            if m365_teams:
                return TeamsGraphClient(
                    settings,
                    transport=transport,
                    connection=connection,
                )
            return M365GraphClient(
                settings,
                transport=transport,
                connection=connection,
                client_id=client_id,
            )
        except M365ProfileResolutionError as exc:
            raise HTTPException(
                status_code=409,
                detail={"code": "client_scope_unavailable", "client_id": client_id},
            ) from exc
    if connector_type not in {"halopsa", "connectwise", "syncro", "servicenow", "autotask"}:
        raise HTTPException(status_code=409, detail={"code": "client_scope_unsupported"})
    transport = getattr(
        request.app.state,
        f"{connector_type}_transport",
        getattr(appliance_client, "transport", None),
    )
    try:
        return build_read_client_for_client(
            store,
            connector_type,
            client_id,
            base_settings=settings,
            vault=vault,
            inner_transport=transport,
        )
    except ConnectorFactoryError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "client_scope_unavailable", "client_id": client_id},
        ) from exc


def _resolve_detail_scope(
    context: AuthContext,
    requested_client_id: str | None,
) -> ClientScope:
    """Resolve an entity lookup scope while hiding foreign-resource existence."""

    try:
        return resolve_client_scope(context, requested_client_id)
    except HTTPException as exc:
        if exc.status_code == 403 and exc.detail in {
            "requested tenant is outside authenticated scope",
            "authenticated principal has no tenant",
        }:
            raise HTTPException(status_code=404, detail="resource not found") from exc
        raise


def _resolve_client_target_scope(context: AuthContext, requested_client_id: str) -> ClientScope:
    """Resolve a client target without disclosing missing versus foreign IDs."""

    try:
        return resolve_client_scope(context, requested_client_id)
    except HTTPException as exc:
        if exc.status_code == 403 and exc.detail in {
            "requested tenant is outside authenticated scope",
            "authenticated principal has no tenant",
        }:
            raise HTTPException(status_code=404, detail="client not found") from exc
        raise


def _backfill_scope(context: AuthContext, requested_client_id: str | None) -> ClientScope:
    """Resolve the scope used by agent-backfill list and entity routes."""

    scope = resolve_client_scope(context, requested_client_id)
    if isinstance(scope, AllClients) and context.role < Role.ADMIN and not context.demo_mode:
        raise HTTPException(status_code=403, detail="agent backfills require a client scope")
    return scope


def _scope_contains_client(scope: ClientScope, client_id: str | None) -> bool:
    normalized_client_id = _normalize_client_id(client_id)
    if normalized_client_id is None:
        return False
    if isinstance(scope, AllClients):
        return True
    return normalized_client_id in scope.client_ids


def _required_client_id(context: AuthContext, requested_client_id: str | None) -> str:
    """Resolve a single tenant for a non-entity operation."""

    scope = resolve_client_scope(context, requested_client_id)
    try:
        client_id = scope.client_id
    except HTTPException:
        raise
    if client_id is None:
        raise HTTPException(status_code=403, detail="client scope is required")
    return client_id


def _require_msp_operator(context: AuthContext) -> None:
    """Require the appliance operator scope used for authority-estate changes."""

    if not context.demo_mode and not context.is_msp_admin:
        raise HTTPException(status_code=403, detail="msp operator access required")


def _require_commercial_activation_access(context: AuthContext) -> None:
    if context.demo_mode:
        raise HTTPException(status_code=403, detail="commercial activation is unavailable in demo mode")
    _require_msp_operator(context)


def _request_correlation_id(request: Request) -> str | None:
    candidate = getattr(request.state, "correlation_id", None)
    return str(candidate) if valid_correlation_id(candidate) else None


def _operator_scope(
    context: AuthContext,
    configured_client_id: str | None,
    requested_client_id: str | None = None,
) -> ClientScope:
    """Use an appliance operator's configured tenant for singular portal views.

    Bootstrap credentials intentionally resolve to ``AllClients`` globally.  A
    non-admin operator route that is anchored to one stored tenant can still
    use the appliance's configured primary client without changing that global
    resolver contract.
    """

    requested = _normalize_client_id(requested_client_id)
    if requested is None and context.is_msp_admin and context.role < Role.ADMIN:
        requested = _normalize_client_id(configured_client_id)
    return resolve_client_scope(context, requested)


def _end_user_client_id(context: AuthContext) -> str:
    """Resolve the end-user's own bound client rather than trusting a field."""

    if not context.principal_id:
        raise HTTPException(status_code=403, detail="end-user identity is not fully scoped")
    scope = resolve_client_scope(context, None)
    if not isinstance(scope, BoundClients):  # pragma: no cover - end users are single-client principals
        raise HTTPException(status_code=403, detail="end-user identity is not fully scoped")
    client_id = scope.client_id
    if client_id is None:  # pragma: no cover - BoundClients rejects empty scopes
        raise HTTPException(status_code=403, detail="end-user identity is not fully scoped")
    return client_id


def _end_user_read_client_id(context: AuthContext) -> str:
    """Hide unreadable end-user resources instead of disclosing scope state."""

    try:
        return _end_user_client_id(context)
    except HTTPException as exc:
        if exc.status_code == 403:
            raise HTTPException(status_code=404, detail="end-user ticket not found") from exc
        raise


def _singular_action_client(
    store: Store,
    context: AuthContext,
    requested_client_id: str | None,
    payload: dict[str, object],
) -> str | None:
    """Choose an action tenant from a stored ticket or the operator's primary tenant."""

    scope = resolve_client_scope(context, requested_client_id)
    ticket_id = payload.get("ticket_id")
    if isinstance(ticket_id, str) and ticket_id.strip():
        ticket = store.get_ticket(ticket_id.strip(), client_id=scope)
        if ticket is not None:
            return ticket.client_id
    if isinstance(scope, BoundClients):
        client_id = scope.client_id
        if client_id is None:  # pragma: no cover - BoundClients rejects empty scopes
            raise HTTPException(status_code=403, detail="client scope is required")
        return client_id
    configured_client_id = _normalize_client_id(context.client_id)
    if context.demo_mode and configured_client_id is None:
        return None
    if configured_client_id is None:
        raise HTTPException(status_code=403, detail="client scope is required")
    return configured_client_id


def _approval_scope_visible(context: AuthContext, approval) -> bool:
    """Apply the same resolver to approval detail and mutation checks."""

    approval_client_id = _normalize_client_id(approval.client_id)
    if approval_client_id is None:
        return context.demo_mode or context.is_msp_admin
    try:
        resolve_client_scope(context, approval_client_id)
    except HTTPException:
        return False
    return True


def _scheduled_job_for_context(store: Store, job_id: int, context: AuthContext):
    scope = resolve_client_scope(context, None)
    job = store.get_scheduled_job(job_id)
    if job is None or not _scope_contains_client(scope, job.client_id):
        raise HTTPException(status_code=404, detail="scheduled job not found")
    return job

