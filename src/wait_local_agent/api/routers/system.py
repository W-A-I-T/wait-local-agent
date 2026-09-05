"""System, settings, update, and pack API routes."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

from wait_local_agent.api.context import AdminAccess, ApiContext, ViewerAccess
from wait_local_agent.api.packs.loader import PackInstallError, get_entitlement_status, install_pack_tarball
from wait_local_agent.api.schemas import PackInstallRequest
from wait_local_agent.providers import (
    PROVIDER_CONFIGURATION_SCOPE,
    PROVIDER_REQUEST_CONTEXT_SCOPE,
    probe_model_providers,
)
from wait_local_agent.security import auth_required
from wait_local_agent.update_channel import check_for_updates


def create_system_router(ctx: ApiContext) -> APIRouter:
    router = APIRouter()
    active_settings = ctx.active_settings
    store = ctx.store
    limiter = ctx.limiter
    app = ctx.app
    update_status_cache = ctx.update_status_cache
    _m365_health_configured = ctx.m365_health_configured

    @router.get("/health")
    @limiter.exempt
    def health(request: Request, _: ViewerAccess) -> dict[str, object]:
        return {
            "status": "ok",
            "write_actions_enabled": active_settings.allow_write_actions,
            "http_probing_enabled": active_settings.allow_http_probing,
            "cloud_fallback_enabled": active_settings.allow_cloud_fallback,
            "offline_mode": active_settings.offline_mode,
            "llm_inference_enabled": active_settings.allow_llm_inference,
            "api_auth_required": auth_required(active_settings),
            "demo_mode": active_settings.demo_mode,
            "secrets_backend": active_settings.secrets_backend,
            "scheduler_enabled": active_settings.scheduler_enabled,
            "halopsa_configured": bool(
                active_settings.halopsa_base_url
                and active_settings.halopsa_client_id
                and active_settings.halopsa_client_secret
                and active_settings.halopsa_tenant
            ),
            "hudu_configured": bool(active_settings.hudu_base_url and active_settings.hudu_api_key),
            "syncro_configured": bool(active_settings.syncro_base_url and active_settings.syncro_api_token),
            "servicenow_configured": bool(
                active_settings.servicenow_base_url
                and active_settings.servicenow_username
                and active_settings.servicenow_password
            ),
            "autotask_configured": bool(
                active_settings.autotask_base_url
                and active_settings.autotask_username
                and active_settings.autotask_secret
                and active_settings.autotask_integration_code
            ),
            "itglue_configured": bool(active_settings.itglue_base_url and active_settings.itglue_api_key),
            "confluence_configured": bool(
                active_settings.confluence_base_url
                and active_settings.confluence_email
                and active_settings.confluence_api_token
            ),
            "sharepoint_configured": bool(
                active_settings.sharepoint_base_url and active_settings.sharepoint_access_token
            ),
            "m365_configured": _m365_health_configured(),
        }

    @router.get("/healthz", include_in_schema=False)
    @limiter.exempt
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @router.get("/auth/role")
    def auth_role(context: ViewerAccess) -> dict[str, object]:
        return {
            "role": context.role.label(),
            "client_id": context.client_id,
            "client_ids": sorted(context.membership_client_ids),
            "principal_id": context.principal_id,
            "auth_method": context.auth_method,
            "is_msp_admin": context.is_msp_admin,
            "api_auth_required": auth_required(active_settings),
            "demo_mode": active_settings.demo_mode,
            "allow_write_actions": active_settings.allow_write_actions,
            "end_user_support_enabled": active_settings.end_user_support_enabled,
        }

    @router.get("/settings/security")
    def security_settings(_: AdminAccess) -> dict[str, object]:
        return {
            "api_token_configured": bool(active_settings.api_token),
            "admin_token_configured": bool(active_settings.admin_token),
            "tech_token_configured": bool(active_settings.tech_token),
            "viewer_token_configured": bool(active_settings.viewer_token),
            "api_auth_required": auth_required(active_settings),
            "demo_mode": active_settings.demo_mode,
        }

    @router.get("/settings/providers")
    def providers(_: ViewerAccess) -> dict[str, object]:
        return {
            "local_model_provider": active_settings.local_model_provider,
            "local_model_base_url": active_settings.local_model_base_url,
            "local_model_name": active_settings.local_model_name,
            "local_model_timeout_seconds": active_settings.local_model_timeout_seconds,
            "provider_scope": PROVIDER_CONFIGURATION_SCOPE,
            "context_scope": PROVIDER_REQUEST_CONTEXT_SCOPE,
            "llm_inference_enabled": active_settings.allow_llm_inference,
            "cloud_fallback_enabled": active_settings.allow_cloud_fallback,
            "offline_mode": active_settings.offline_mode,
            "remote_model_provider": active_settings.remote_model_provider,
            "remote_model_configured": bool(
                active_settings.remote_model_provider
                and active_settings.remote_model_base_url
                and active_settings.remote_model_name
                and active_settings.remote_model_api_key
            ),
            "remote_model_enabled": bool(
                active_settings.allow_llm_inference
                and active_settings.allow_cloud_fallback
                and not active_settings.offline_mode
                and active_settings.remote_model_provider
                and active_settings.remote_model_base_url
                and active_settings.remote_model_name
                and active_settings.remote_model_api_key
            ),
            "model_input_cost_usd_per_million_tokens": active_settings.model_input_cost_usd_per_million_tokens,
            "model_output_cost_usd_per_million_tokens": active_settings.model_output_cost_usd_per_million_tokens,
            "vector_backend": active_settings.vector_backend,
            "document_parser": active_settings.document_parser,
            "ocr_enabled": active_settings.allow_ocr,
            "embedding_provider": active_settings.embedding_provider,
            "embedding_model": active_settings.embedding_model,
            "qdrant_collection": active_settings.qdrant_collection,
        }

    @router.get("/settings/providers/health")
    def provider_health(_: AdminAccess) -> dict[str, object]:
        result = probe_model_providers(active_settings)
        for name, status in result.items():
            if isinstance(status, dict):
                store.add_audit_event(
                    "model_provider.health",
                    str(name),
                    str(status.get("status", "unknown")),
                )
        return result

    @router.get("/update-status")
    def update_status(_: AdminAccess) -> dict[str, object]:
        return update_status_cache.get_status(lambda: check_for_updates(active_settings)).to_dict()

    @router.post("/update-check")
    def update_check(_: AdminAccess) -> dict[str, object]:
        return check_for_updates(active_settings).to_dict()

    @router.get("/packs")
    def packs(_: ViewerAccess) -> list[dict[str, object]]:
        registry = app.state.pack_registry
        return [
            {
                "name": status.name,
                "version": status.version,
                "locked": status.locked,
                "requires_license": status.requires_license,
                "signature_status": "not_recorded",
            }
            for status in registry.statuses
        ]

    @router.get("/packs/status")
    def pack_status(_: ViewerAccess) -> list[dict[str, object]]:
        registry = app.state.pack_registry
        return [{**asdict(status), "signature_status": "not_recorded"} for status in registry.statuses]

    @router.get("/entitlement")
    def entitlement(_: ViewerAccess) -> dict[str, object | None]:
        return {"commercial": get_entitlement_status(app.state.pack_registry)}

    @router.post("/packs/install")
    def pack_install(payload: PackInstallRequest, _: AdminAccess) -> dict[str, object]:
        try:
            result = install_pack_tarball(
                Path(payload.tarball_path),
                license_key=payload.license_key,
                settings=active_settings,
            )
        except PackInstallError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except OSError as exc:
            raise HTTPException(status_code=400, detail="pack tarball could not be read") from exc
        return {
            "pack_name": result.pack_name,
            "version": result.version,
            "files": len(result.extracted_files),
            "license_stored_in_vault": result.license_stored_in_vault,
        }

    return router


__all__ = ["create_system_router"]
