from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from wait_local_agent.api.packs.loader import LoadedPack, get_pack
from wait_local_agent.rbac import AuthContext, Role, require_role

FOUNDER_PACK_NOT_INSTALLED = {"error": "founder pack not installed"}
FOUNDER_INSTALL_HINT = "founder pack not installed; install the founder pack to use this command"

AdminAccess = Annotated[AuthContext, Depends(require_role(Role.ADMIN))]


class FounderPackUnavailableError(RuntimeError):
    """Raised when the founder pack is not installed or is unavailable."""


class FounderPackContractError(RuntimeError):
    """Raised when the founder pack does not implement the expected surface."""


class FounderScanRequest(BaseModel):
    path: str


class FounderUploadRequest(BaseModel):
    confirm: bool


def create_router() -> APIRouter:
    router = APIRouter(tags=["founder"])

    @router.post("/founder/scan")
    def founder_scan(payload: FounderScanRequest, _: AdminAccess) -> dict[str, object]:
        pack = require_founder_pack()
        response = invoke_founder(pack, "scan", Path(payload.path))
        return json_object(response, operation="scan")

    @router.get("/founder/vault")
    def founder_vault(_: AdminAccess) -> object:
        pack = require_founder_pack()
        return json_value(invoke_founder(pack, "vault"), operation="vault")

    @router.get("/founder/preflight/latest")
    def founder_preflight_latest(_: AdminAccess) -> dict[str, object]:
        pack = require_founder_pack()
        return json_object(invoke_founder(pack, "preflight_latest"), operation="preflight_latest")

    @router.get("/founder/upload-preview/{artifact_id}")
    def founder_upload_preview(
        artifact_id: str,
        request: Request,
        _: AdminAccess,
    ) -> dict[str, object]:
        pack = require_founder_pack()
        bundle = json_object(invoke_founder(pack, "export_bundle", artifact_id), operation="export_bundle")
        preview = build_upload_preview(artifact_id, bundle)
        previewed_artifacts(request).add(artifact_id)
        return preview

    @router.post("/founder/upload/{artifact_id}")
    def founder_upload(
        artifact_id: str,
        payload: FounderUploadRequest,
        request: Request,
        _: AdminAccess,
    ) -> dict[str, object]:
        pack = require_founder_pack()
        if not payload.confirm:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="confirm must be true")
        if artifact_id not in previewed_artifacts(request):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="upload preview required before upload",
            )
        response = invoke_founder(pack, "upload", artifact_id)
        return json_object(response, operation="upload")

    @router.get("/founder/lp-status")
    def founder_lp_status(_: AdminAccess) -> dict[str, object]:
        pack = require_founder_pack()
        return json_object(invoke_founder(pack, "lp_status"), operation="lp_status")

    return router


def founder_pack_unavailable_handler(_: Request, __: Exception) -> JSONResponse:
    return JSONResponse(status_code=status.HTTP_501_NOT_IMPLEMENTED, content=FOUNDER_PACK_NOT_INSTALLED)


def require_founder_pack() -> LoadedPack:
    pack = get_pack("founder")
    if pack is None:
        raise FounderPackUnavailableError()
    return pack


def invoke_founder(pack: LoadedPack, operation: str, *args: object) -> object:
    member = resolve_founder_member(pack, operation)
    return member(*args)


def resolve_founder_member(pack: LoadedPack, operation: str):
    candidate_names = {
        "scan": ("scan_path", "scan"),
        "vault": ("list_vault", "get_vault", "vault"),
        "preflight_latest": ("get_latest_preflight", "preflight_latest", "latest_preflight"),
        "handoff": ("generate_handoff", "handoff"),
        "export_bundle": ("export_bundle", "get_bundle", "bundle"),
        "upload": ("upload_bundle", "upload"),
        "lp_status": ("get_lp_status", "lp_status"),
    }
    for name in candidate_names[operation]:
        candidate = getattr(pack.module, name, None)
        if callable(candidate):
            return candidate
    raise FounderPackContractError(f"founder pack is missing {operation}")


def json_object(value: object, *, operation: str) -> dict[str, object]:
    normalized = json_value(value, operation=operation)
    if not isinstance(normalized, dict):
        raise FounderPackContractError(f"founder pack {operation} must return an object")
    return normalized


def json_value(value: object, *, operation: str) -> object:
    if not isinstance(value, type) and is_dataclass(value):
        return json_value(asdict(cast(Any, value)), operation=operation)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): json_value(item, operation=operation) for key, item in value.items()}
    if isinstance(value, list):
        return [json_value(item, operation=operation) for item in value]
    if isinstance(value, tuple):
        return [json_value(item, operation=operation) for item in value]
    if value is None or isinstance(value, str | int | float | bool):
        return value
    raise FounderPackContractError(
        f"founder pack {operation} returned unsupported type {type(value).__name__}"
    )


def build_upload_preview(artifact_id: str, bundle: dict[str, object]) -> dict[str, object]:
    file_tree = ensure_list(bundle.get("file_tree"), key="file_tree")
    manifests = ensure_list(bundle.get("manifests"), key="manifests")
    routes = ensure_list(bundle.get("routes"), key="routes")
    env_keys = ensure_list(bundle.get("env_keys"), key="env_keys")
    findings = ensure_list(bundle.get("findings"), key="findings")

    env_key_names: list[str] = []
    for item in env_keys:
        if not isinstance(item, str):
            raise FounderPackContractError("founder bundle env_keys entries must be strings")
        env_key_names.append(item)

    finding_types: list[str] = []
    for item in findings:
        if not isinstance(item, dict):
            raise FounderPackContractError("founder bundle findings entries must be objects")
        finding_type = item.get("type")
        if isinstance(finding_type, str):
            finding_types.append(finding_type)

    return {
        "artifact_id": artifact_id,
        "schema_version": bundle.get("schema_version"),
        "project_name": bundle.get("project_name"),
        "file_count": len(file_tree),
        "manifest_count": len(manifests),
        "route_count": len(routes),
        "env_key_names": env_key_names,
        "finding_types": sorted(set(finding_types)),
    }


def previewed_artifacts(request: Request) -> set[str]:
    cached = getattr(request.app.state, "founder_previewed_artifacts", None)
    if cached is None:
        cached = set()
        request.app.state.founder_previewed_artifacts = cached
    return cached


def ensure_list(value: object, *, key: str) -> list[object]:
    if isinstance(value, list):
        return value
    raise FounderPackContractError(f"founder bundle {key} must be a list")


def render_json(value: object) -> str:
    return json.dumps(json_value(value, operation="render"), sort_keys=True, indent=2)
