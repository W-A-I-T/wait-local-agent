"""FastAPI routes for Azure Lighthouse delegated customer management."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict
from typing import Annotated, Literal, NoReturn, cast

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from wait_local_agent.client_scope import resolve_client_scope
from wait_local_agent.config import Settings
from wait_local_agent.rbac import AuthContext, Role, require_role
from wait_local_agent.store import Store

from .client import AzureLighthouseClient
from .credentials import credential_from_vault
from .models import (
    MAX_RECORDS,
    AzureLighthouseAuthorizationError,
    AzureLighthouseBlockedError,
    AzureLighthouseCredentialError,
    AzureLighthouseProviderError,
    AzureLighthouseValidationError,
    TokenCredential,
)
from .onboarding import build_onboarding_bundle, validate_onboarding_bundle

AdminAccess = Annotated[AuthContext, Depends(require_role(Role.ADMIN))]
CredentialFactory = Callable[[Settings, str, str], TokenCredential]


class LighthouseConnectionRequest(BaseModel):
    client_id: str | None = Field(default=None, min_length=1, max_length=128)
    credential_ref: str = Field(min_length=1, max_length=256)
    managing_tenant_id: str = Field(min_length=36, max_length=36)
    expected_customer_tenant_id: str = Field(min_length=36, max_length=36)

    model_config = ConfigDict(extra="forbid")


class LighthouseInventoryRequest(LighthouseConnectionRequest):
    subscription_id: str = Field(min_length=36, max_length=36)
    resource_group: str | None = Field(default=None, max_length=90)
    limit: int = Field(default=200, ge=1, le=MAX_RECORDS)


class LighthouseOnboardingRequest(BaseModel):
    offer_name: str = Field(min_length=1, max_length=128)
    offer_description: str = Field(min_length=1, max_length=512)
    managing_tenant_id: str = Field(min_length=36, max_length=36)
    principal_id: str = Field(min_length=36, max_length=36)
    principal_display_name: str = Field(min_length=1, max_length=128)
    deployment_scope: Literal["subscription", "resource_group"] = "subscription"
    client_id: str | None = Field(default=None, min_length=1, max_length=128)

    model_config = ConfigDict(extra="forbid")


def create_router() -> APIRouter:
    router = APIRouter(tags=["Azure Lighthouse"])

    @router.get("/status")
    def status(request: Request) -> dict[str, object]:
        settings = cast(Settings, request.app.state.settings)
        return {
            "status": "ready" if settings.allow_http_probing else "blocked",
            "message": (
                "Azure Lighthouse read-only discovery is enabled."
                if settings.allow_http_probing
                else "Azure Lighthouse live reads are blocked until WAIT_ALLOW_HTTP_PROBING=true."
            ),
            "read_only": True,
            "customer_onboarding_deployed_by_wait": False,
            "supported_scopes": ["subscription", "resource_group"],
            "supported_operations": [
                "discover delegated subscriptions",
                "verify registration assignments",
                "inventory delegated Azure resources",
                "generate Reader-only customer onboarding artifacts",
            ],
        }

    @router.post("/discover")
    def discover(
        payload: LighthouseConnectionRequest,
        request: Request,
        context: AdminAccess,
    ) -> dict[str, object]:
        client_id = _scoped_client_id(context, payload.client_id)
        try:
            client = _client(
                request,
                payload.credential_ref,
                payload.managing_tenant_id,
            )
            result = client.discover(
                client_id=client_id,
                managing_tenant_id=payload.managing_tenant_id,
                expected_customer_tenant_id=payload.expected_customer_tenant_id,
            )
        except Exception as exc:
            _raise_http(exc)
        _audit(
            request,
            "azure_lighthouse.delegations_discovered",
            client_id,
            f"status={result.status} subscriptions={len(result.subscriptions)}",
            client_id=client_id,
        )
        return result.to_dict()

    @router.post("/inventory")
    def inventory(
        payload: LighthouseInventoryRequest,
        request: Request,
        context: AdminAccess,
    ) -> dict[str, object]:
        client_id = _scoped_client_id(context, payload.client_id)
        try:
            client = _client(
                request,
                payload.credential_ref,
                payload.managing_tenant_id,
            )
            result = client.inventory(
                client_id=client_id,
                managing_tenant_id=payload.managing_tenant_id,
                expected_customer_tenant_id=payload.expected_customer_tenant_id,
                subscription_id=payload.subscription_id,
                resource_group=payload.resource_group,
                limit=payload.limit,
            )
        except Exception as exc:
            _raise_http(exc)
        _audit(
            request,
            "azure_lighthouse.inventory_collected",
            result.scope,
            f"resources={len(result.resources)} delegation_verified={result.delegation_verified}",
            client_id=client_id,
        )
        return result.to_dict()

    @router.post("/onboarding/plan")
    def onboarding_plan(
        payload: LighthouseOnboardingRequest,
        request: Request,
        context: AdminAccess,
    ) -> dict[str, object]:
        client_id = _scoped_client_id(context, payload.client_id)
        try:
            bundle = build_onboarding_bundle(
                offer_name=payload.offer_name,
                offer_description=payload.offer_description,
                managing_tenant_id=payload.managing_tenant_id,
                principal_id=payload.principal_id,
                principal_display_name=payload.principal_display_name,
                deployment_scope=payload.deployment_scope,
            )
            validate_onboarding_bundle(bundle)
        except Exception as exc:
            _raise_http(exc)
        _audit(
            request,
            "azure_lighthouse.onboarding_plan_generated",
            client_id,
            f"scope={bundle.deployment_scope} digest={bundle.bundle_sha256}",
            client_id=client_id,
        )
        return {"client_id": client_id, **asdict(bundle)}

    return router


def _client(
    request: Request,
    credential_ref: str,
    managing_tenant_id: str,
) -> AzureLighthouseClient:
    settings = cast(Settings, request.app.state.settings)
    injected_factory = cast(
        CredentialFactory | None,
        getattr(request.app.state, "azure_lighthouse_credential_factory", None),
    )
    if injected_factory is not None:
        credential = injected_factory(settings, credential_ref, managing_tenant_id)
    else:
        credential = credential_from_vault(
            settings,
            credential_ref,
            managing_tenant_id,
        )
    transport = cast(
        httpx.BaseTransport | None,
        getattr(request.app.state, "azure_lighthouse_transport", None),
    )
    return AzureLighthouseClient(settings, credential, transport=transport)


def _scoped_client_id(context: AuthContext, requested_client_id: str | None) -> str:
    scope = resolve_client_scope(context, requested_client_id)
    client_id = scope.client_id
    if client_id is None:
        raise HTTPException(
            status_code=403,
            detail="Azure Lighthouse operations require one explicit WAIT client.",
        )
    return client_id


def _audit(
    request: Request,
    event_type: str,
    entity_id: str,
    message: str,
    *,
    client_id: str | None = None,
) -> None:
    store = cast(Store | None, getattr(request.app.state, "store", None))
    if store is not None:
        store.add_audit_event(
            event_type,
            entity_id,
            message,
            client_id=client_id,
        )


def _raise_http(exc: Exception) -> NoReturn:
    if isinstance(exc, AzureLighthouseBlockedError):
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    if isinstance(exc, AzureLighthouseCredentialError):
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if isinstance(exc, AzureLighthouseValidationError):
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if isinstance(exc, AzureLighthouseAuthorizationError):
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    if isinstance(exc, AzureLighthouseProviderError):
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    raise HTTPException(
        status_code=500,
        detail="Azure Lighthouse operation failed before a safe result was returned.",
    ) from exc
