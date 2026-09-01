from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import IntEnum
from secrets import compare_digest
from typing import TYPE_CHECKING, Annotated, Literal

from fastapi import Header, HTTPException, Request, status

from wait_local_agent.capabilities import MICROSOFT_ADMIN_CAPABILITY, active_capability_grants
from wait_local_agent.client_scope import AllClients, BoundClients, ClientScope, resolve_client_scope
from wait_local_agent.config import Settings

__all__ = [
    "AllClients",
    "AuthContext",
    "BoundClients",
    "ClientScope",
    "Role",
    "require_capability",
    "require_capability_scope",
    "resolve_client_scope",
]

if TYPE_CHECKING:
    from wait_local_agent.store import PrincipalAuthRecord, Store


class Role(IntEnum):
    END_USER = 0
    VIEWER = 1
    TECHNICIAN = 2
    ADMIN = 3

    def label(self) -> str:
        return self.name.lower()


CapabilityFailureReason = Literal["no_principal", "no_grant", "client_scope_mismatch"]


_CAPABILITY_REMEDIATIONS: dict[CapabilityFailureReason, str] = {
    "no_principal": (
        "Environment bootstrap tokens carry no capability grants; create a database principal and grant "
        "microsoft_admin, or enable demo mode."
    ),
    "no_grant": "Grant microsoft_admin to this database principal for the requested client.",
    "client_scope_mismatch": (
        "Use a client covered by this principal's microsoft_admin grant or add a grant for the requested client."
    ),
}


@dataclass(frozen=True)
class AuthContext:
    role: Role
    presented_token: str | None
    client_id: str | None = None
    principal_id: str | None = None
    client_ids: frozenset[str] = frozenset()
    is_msp_admin: bool = False
    demo_mode: bool = False
    capability_grants: frozenset[tuple[str, str | None]] = frozenset()

    @property
    def approver_id(self) -> str | None:
        if not self.presented_token:
            return None
        return hashlib.sha256(self.presented_token.encode("utf-8")).hexdigest()[:16]

    def has_capability(self, capability_key: str, client_id: str | None = None) -> bool:
        normalized_key = capability_key.strip().lower()
        if (normalized_key, None) in self.capability_grants:
            return True
        return client_id is not None and (normalized_key, client_id) in self.capability_grants


def tokens_configured(settings: Settings) -> bool:
    return bool(
        settings.api_token
        or settings.admin_token
        or settings.tech_token
        or settings.viewer_token
        or (settings.end_user_support_enabled and settings.end_user_token)
    )


def admin_credential_configured(settings: Settings, store: Store) -> bool:
    """Return whether non-demo startup has an admin bootstrap or principal credential."""

    return bool(
        settings.api_token.strip()
        or settings.admin_token.strip()
        or store.has_msp_admin_credential()
    )


def resolve_auth_context(
    settings: Settings,
    authorization: str | None,
    store: Store | None = None,
) -> AuthContext:
    configured_client_id = settings.client_id.strip() or None
    if settings.demo_mode:
        demo_client_id = configured_client_id or "demo"
        return AuthContext(
            role=Role.ADMIN,
            presented_token=None,
            client_id=demo_client_id,
            principal_id="demo",
            client_ids=frozenset({demo_client_id}),
            demo_mode=True,
            capability_grants=frozenset({(MICROSOFT_ADMIN_CAPABILITY, demo_client_id)}),
        )

    token = _extract_bearer_token(authorization)
    if settings.end_user_support_enabled and settings.end_user_token and compare_digest(
        token, settings.end_user_token
    ):
        return AuthContext(
            role=Role.END_USER,
            presented_token=token,
            client_id=settings.end_user_client_id.strip() or None,
            principal_id=settings.end_user_user_id.strip() or None,
            client_ids=frozenset({settings.end_user_client_id.strip()})
            if settings.end_user_client_id.strip()
            else frozenset(),
            demo_mode=False,
        )
    for candidate, role in (
        (settings.api_token, Role.ADMIN),
        (settings.admin_token, Role.ADMIN),
        (settings.tech_token, Role.TECHNICIAN),
        (settings.viewer_token, Role.VIEWER),
    ):
        if candidate and compare_digest(token, candidate):
            return AuthContext(
                role=role,
                presented_token=token,
                client_id=configured_client_id,
                client_ids=frozenset({configured_client_id}) if configured_client_id else frozenset(),
                # Bootstrap credentials authenticate the single-appliance
                # operator. The role still governs write authority; this
                # flag only grants the operator cross-client read scope.
                is_msp_admin=True,
                demo_mode=False,
            )

    principal_store = store or _store_for_settings(settings)
    principal = principal_store.find_principal_by_credential_hash(_hash_credential(token))
    if principal is not None:
        return _principal_auth_context(settings, token, principal, principal_store)
    raise _unauthorized("invalid bearer token")


def require_end_user(request: Request, authorization: Annotated[str | None, Header()] = None) -> AuthContext:
    context = resolve_auth_context(request.app.state.settings, authorization, request.app.state.store)
    if context.role != Role.END_USER:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="end-user access required")
    return context


def require_role(minimum: Role):
    def dependency(
        request: Request,
        authorization: Annotated[str | None, Header()] = None,
    ) -> AuthContext:
        settings = request.app.state.settings
        context = resolve_auth_context(settings, authorization, request.app.state.store)
        if context.role < minimum:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="insufficient role")
        return context

    return dependency


def require_capability(capability_key: str, minimum: Role = Role.VIEWER):
    """Require both the normal role boundary and an explicit capability grant."""

    def dependency(
        request: Request,
        authorization: Annotated[str | None, Header()] = None,
        selected_client_id: Annotated[str | None, Header(alias="X-WAIT-Client-ID")] = None,
    ) -> AuthContext:
        settings = request.app.state.settings
        context = resolve_auth_context(settings, authorization, request.app.state.store)
        if context.role < minimum:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="insufficient role")
        query_client_id = request.query_params.get("client_id")
        if query_client_id and selected_client_id and query_client_id != selected_client_id:
            raise HTTPException(status_code=400, detail="conflicting Microsoft Admin client scopes")
        requested_client_id = query_client_id or selected_client_id
        client_id = context.client_id
        if (
            requested_client_id
            and not context.demo_mode
            and not context.is_msp_admin
            and requested_client_id.strip() not in context.client_ids
        ):
            raise _capability_required(capability_key, "client_scope_mismatch")
        if requested_client_id is not None:
            client_id = resolve_client_scope(context, requested_client_id).client_id
        if not context.has_capability(capability_key, client_id):
            raise _capability_required(capability_key, _capability_failure_reason(context, capability_key))
        return context

    return dependency


def require_capability_scope(
    context: AuthContext,
    capability_key: str,
    requested_client_id: str | None,
) -> str:
    """Resolve one authorized client and require a grant for that exact scope."""

    if (
        requested_client_id
        and not context.demo_mode
        and not context.is_msp_admin
        and requested_client_id.strip() not in context.client_ids
    ):
        raise _capability_required(capability_key, "client_scope_mismatch")
    client_id = resolve_client_scope(context, requested_client_id).client_id
    if client_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="capability operation requires one explicit client",
        )
    if not context.has_capability(capability_key, client_id):
        raise _capability_required(capability_key, _capability_failure_reason(context, capability_key))
    return client_id


def _capability_failure_reason(context: AuthContext, capability_key: str) -> CapabilityFailureReason:
    if context.principal_id is None:
        return "no_principal"
    if not any(granted_key == capability_key for granted_key, _ in context.capability_grants):
        return "no_grant"
    return "client_scope_mismatch"


def _capability_required(
    capability_key: str,
    reason: CapabilityFailureReason,
) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={
            "code": "capability_required",
            "capability": capability_key,
            "reason": reason,
            "remediation": _CAPABILITY_REMEDIATIONS[reason],
        },
    )


def _extract_bearer_token(authorization: str | None) -> str:
    if not authorization:
        raise _unauthorized("missing bearer token")
    scheme, separator, token = authorization.partition(" ")
    if not separator or scheme.lower() != "bearer" or not token:
        raise _unauthorized("invalid bearer token")
    return token


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def _principal_auth_context(
    settings: Settings,
    token: str,
    principal: PrincipalAuthRecord,
    store: Store | None = None,
) -> AuthContext:
    client_roles = {client_id: _role_from_label(role) for client_id, role in principal.client_roles}
    client_ids = frozenset(client_roles)
    if principal.principal_kind == "customer" and len(client_ids) != 1:
        raise _unauthorized("principal has an invalid client membership")
    if not client_ids and "msp_admin" not in principal.global_roles:
        raise _unauthorized("principal has no client membership")

    configured_client_id = settings.client_id.strip() or None
    primary_client_id = (
        configured_client_id
        if configured_client_id in client_ids
        else next(iter(sorted(client_ids)), None)
    )
    is_msp_admin = "msp_admin" in principal.global_roles
    primary_role = client_roles.get(primary_client_id) if primary_client_id is not None else None
    role = Role.ADMIN if is_msp_admin else primary_role
    if role is None:
        raise _unauthorized("principal has no usable role")
    principal_store = store or _store_for_settings(settings)
    return AuthContext(
        role=role,
        presented_token=token,
        client_id=primary_client_id,
        principal_id=principal.principal_id,
        client_ids=client_ids,
        is_msp_admin=is_msp_admin,
        demo_mode=False,
        capability_grants=active_capability_grants(principal_store, principal.principal_id),
    )


def _role_from_label(label: str) -> Role:
    try:
        return Role[str(label).strip().upper()]
    except KeyError as exc:
        raise _unauthorized("principal has an invalid role") from exc


def _store_for_settings(settings: Settings) -> Store:
    from wait_local_agent.store import Store

    return Store(settings.data_path)


def _hash_credential(credential: str) -> str:
    from wait_local_agent.store import hash_credential

    return hash_credential(credential)
