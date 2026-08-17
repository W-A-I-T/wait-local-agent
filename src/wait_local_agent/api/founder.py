from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, cast
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from wait_local_agent.api.packs.loader import LoadedPack, get_pack
from wait_local_agent.config import Settings
from wait_local_agent.founder_bundle import (
    PrivacyViolation,
    build_founder_bundle,
    bundle_hash,
    compute_bundle_delta,
    sanitize_bundle,
)
from wait_local_agent.lp_client import (
    LAUNCH_PASSPORT_CONNECTION_STATES,
    LAUNCH_PASSPORT_SCAN_STATES,
    LAUNCH_PASSPORT_UPLOAD_STATES,
    LaunchPassportClient,
    LaunchPassportForbidden,
    LaunchPassportInsufficientCredits,
    LaunchPassportPayloadTooLarge,
    LaunchPassportRateLimited,
    LaunchPassportRequestError,
    LaunchPassportUnauthorized,
    normalize_upstream_state,
    scrub_upstream_value,
    validate_launch_passport_base_url,
)
from wait_local_agent.lp_polling import PollOutcome, poll_scan
from wait_local_agent.rbac import AuthContext, Role, require_role
from wait_local_agent.store import Store
from wait_local_agent.vault import SecretVault, SecretVaultError

FOUNDER_PACK_NOT_INSTALLED = {"error": "founder pack not installed"}
FOUNDER_INSTALL_HINT = "founder pack not installed; install the founder pack to use this command"
FOUNDER_NOT_CONFIGURED = {
    "error": "launch passport not configured",
    "hint": "configure a Launch Passport base URL, project id, and vault token first",
}
OPERATION_CONFIRMED = True
PREVIEW_MAX_AGE_SECONDS = 3600

AdminAccess = Annotated[AuthContext, Depends(require_role(Role.ADMIN))]


class FounderPackUnavailableError(RuntimeError):
    """Raised when the founder pack is not installed or is unavailable."""


class FounderPackContractError(RuntimeError):
    """Raised when the founder pack does not implement the expected surface."""


class FounderNotConfiguredError(RuntimeError):
    """Raised when the optional Launch Passport integration has no safe config."""


class FounderUploadConflictError(RuntimeError):
    """Raised when an artifact is not eligible for the requested upload."""


class FounderScanRequest(BaseModel):
    path: str


class FounderUploadRequest(BaseModel):
    confirm: bool


class FounderLaunchRequest(BaseModel):
    artifact_id: str | None = None


def create_router() -> APIRouter:
    router = APIRouter(tags=["founder"])

    @router.post("/founder/scan")
    def founder_scan(payload: FounderScanRequest, request: Request, _: AdminAccess) -> dict[str, object]:
        pack = get_pack("founder")
        if pack is not None:
            return project_founder_scan(
                invoke_founder(pack, "scan", Path(payload.path)), token=_configured_founder_token(request)
            )
        settings, store, config = require_open_config(request)
        return open_founder_scan(store, settings, config, Path(payload.path))

    @router.get("/founder/vault")
    def founder_vault(request: Request, _: AdminAccess) -> object:
        if get_pack("founder") is None:
            require_open_config(request)
        pack = require_founder_pack()
        return json_value(invoke_founder(pack, "vault"), operation="vault")

    @router.get("/founder/preflight/latest")
    def founder_preflight_latest(request: Request, _: AdminAccess) -> dict[str, object]:
        if get_pack("founder") is None:
            require_open_config(request)
        pack = require_founder_pack()
        return json_object(invoke_founder(pack, "preflight_latest"), operation="preflight_latest")

    @router.get("/founder/upload-preview/{artifact_id}")
    def founder_upload_preview(
        artifact_id: str,
        request: Request,
        _: AdminAccess,
    ) -> dict[str, object]:
        pack = get_pack("founder")
        store = cast(Store, request.app.state.store)
        if pack is not None:
            bundle = sanitized_pack_bundle(pack, artifact_id)
            preview = build_upload_preview(artifact_id, bundle)
        else:
            _settings, store, _config = require_open_config(request)
            try:
                preview = open_founder_preview(store, artifact_id)
            except KeyError as exc:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="artifact not found") from exc
        store.mark_founder_artifact_previewed(artifact_id)
        return preview

    @router.post("/founder/upload/{artifact_id}")
    def founder_upload(
        artifact_id: str,
        payload: FounderUploadRequest,
        request: Request,
        _: AdminAccess,
    ) -> dict[str, object]:
        pack = get_pack("founder")
        store = cast(Store, request.app.state.store)
        if pack is None:
            settings, store, config = require_open_config(request)
        if not payload.confirm:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="confirm must be true")
        if pack is not None:
            bundle = sanitized_pack_bundle(pack, artifact_id)
            require_fresh_preview(store, artifact_id)
            return project_founder_upload(
                invoke_founder(pack, "upload", artifact_id, bundle), token=_configured_founder_token(request)
            )
        try:
            return open_founder_upload(settings, store, config, artifact_id)
        except KeyError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="artifact not found") from exc

    @router.get("/founder/lp-status")
    def founder_lp_status(request: Request, _: AdminAccess) -> dict[str, object]:
        pack = get_pack("founder")
        if pack is not None:
            # A locally installed founder pack is trusted code with its own
            # response contract.  Only values returned by the HTTP client are
            # treated as untrusted Launch Passport responses and projected.
            return json_object(invoke_founder(pack, "lp_status"), operation="lp_status")
        settings, _store, config = require_open_config(request)
        return open_founder_status(settings, config)

    @router.get("/founder/results")
    def founder_results(request: Request, _: AdminAccess) -> dict[str, object]:
        pack = get_pack("founder")
        if pack is not None:
            return project_founder_results(
                invoke_founder(pack, "results"), token=_configured_founder_token(request)
            )
        settings, _store, config = require_open_config(request)
        return open_founder_results(settings, config)

    @router.post("/founder/launch-scan")
    def founder_launch_scan(
        request: Request,
        _: AdminAccess,
        payload: FounderLaunchRequest | None = None,
    ) -> dict[str, object]:
        pack = get_pack("founder")
        if pack is not None:
            return json_object(invoke_founder(pack, "launch_scan"), operation="launch_scan")
        settings, store, config = require_open_config(request)
        return open_founder_launch_scan(settings, store, config, payload.artifact_id if payload else None)

    return router


def founder_pack_unavailable_handler(_: Request, __: Exception) -> JSONResponse:
    return JSONResponse(status_code=status.HTTP_501_NOT_IMPLEMENTED, content=FOUNDER_PACK_NOT_INSTALLED)


def founder_not_configured_handler(_: Request, __: Exception) -> JSONResponse:
    return JSONResponse(status_code=status.HTTP_409_CONFLICT, content=FOUNDER_NOT_CONFIGURED)


def founder_upload_conflict_handler(_: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=status.HTTP_409_CONFLICT, content={"error": str(exc)})


def founder_privacy_handler(_: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content={"error": str(exc)})


def launch_passport_error_handler(_: Request, exc: Exception) -> JSONResponse:
    if isinstance(exc, LaunchPassportUnauthorized):
        code = status.HTTP_401_UNAUTHORIZED
    elif isinstance(exc, LaunchPassportForbidden):
        code = status.HTTP_403_FORBIDDEN
    elif isinstance(exc, LaunchPassportInsufficientCredits):
        code = status.HTTP_402_PAYMENT_REQUIRED
    elif isinstance(exc, LaunchPassportRateLimited):
        code = status.HTTP_429_TOO_MANY_REQUESTS
    elif isinstance(exc, LaunchPassportPayloadTooLarge):
        code = status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
    elif isinstance(exc, LaunchPassportRequestError):
        code = status.HTTP_502_BAD_GATEWAY
    else:
        code = status.HTTP_502_BAD_GATEWAY
    return JSONResponse(status_code=code, content={"error": str(exc)})


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
        "results": ("get_results", "results", "list_results"),
        "launch_scan": ("launch_scan", "start_scan"),
    }
    for name in candidate_names[operation]:
        candidate = getattr(pack.module, name, None)
        if callable(candidate):
            return candidate
    raise FounderPackContractError(f"founder pack is missing {operation}")


def require_open_config(request: Request) -> tuple[Settings, Store, dict[str, str]]:
    settings = cast(Settings, request.app.state.settings)
    store = cast(Store, request.app.state.store)
    return settings, store, resolve_open_config(settings, store)


def _configured_founder_token(request: Request) -> str | None:
    settings = cast(Settings, getattr(request.app.state, "settings", None))
    store = cast(Store, getattr(request.app.state, "store", None))
    config = store.get_founder_config() if store is not None else None
    token_ref = config.get("token_vault_ref") if config else None
    if not isinstance(token_ref, str) or not token_ref:
        return None
    try:
        return SecretVault(settings.vault_path).get(token_ref) if settings is not None else None
    except SecretVaultError:
        return None


def resolve_open_config(settings: Settings, store: Store) -> dict[str, str]:
    config = store.get_founder_config()
    if config is None:
        raise FounderNotConfiguredError()
    required = ("lp_base_url", "lp_project_id", "token_vault_ref")
    if any(not config.get(key, "").strip() for key in required):
        raise FounderNotConfiguredError()
    try:
        token = SecretVault(settings.vault_path).get(config["token_vault_ref"])
    except SecretVaultError as exc:
        raise FounderNotConfiguredError() from exc
    if not token:
        raise FounderNotConfiguredError()
    return config


def configure_founder(
    settings: Settings,
    store: Store,
    base_url: str,
    project_id: str,
    token: str,
) -> dict[str, object]:
    normalized_base_url = base_url.strip().rstrip("/")
    validate_launch_passport_base_url(normalized_base_url)
    if not project_id.strip() or "/" in project_id or "\\" in project_id:
        raise ValueError("project id must be a non-empty path segment")
    if not token.strip():
        raise ValueError("Launch Passport token must not be empty")
    token_ref = f"founder.lp.{uuid4().hex}"
    SecretVault.initialize(settings.vault_path).set(token_ref, token)
    store.save_founder_config(
        lp_base_url=normalized_base_url,
        lp_project_id=project_id.strip(),
        token_vault_ref=token_ref,
    )
    return {
        "status": "configured",
        "lp_base_url": normalized_base_url,
        "lp_project_id": project_id.strip(),
        "token_stored_in_vault": OPERATION_CONFIRMED,
    }


def open_founder_scan(
    store: Store,
    settings: Settings,
    config: dict[str, str],
    project_root: Path,
) -> dict[str, object]:
    del settings
    bundle = build_founder_bundle(project_root)
    artifact_id = f"artifact-{uuid4().hex}"
    digest = bundle_hash(bundle)
    store.save_founder_artifact(
        artifact_id=artifact_id,
        project_id=config["lp_project_id"],
        bundle_hash=digest,
        bundle=bundle,
    )
    prior = [
        artifact
        for artifact in store.list_founder_artifacts(config["lp_project_id"])
        if artifact["artifact_id"] != artifact_id
    ]
    predecessor = prior[0] if prior else None
    delta = compute_bundle_delta(cast(dict[str, Any], predecessor["bundle"]) if predecessor else None, bundle)
    return {
        "artifact_id": artifact_id,
        "project_id": config["lp_project_id"],
        "bundle_hash": digest,
        "status": "preview_ready",
        "file_count": len(cast(list[object], bundle.get("files", []))),
        "dependency_count": _dependency_count(bundle),
        "env_key_count": len(cast(list[object], bundle.get("environment", {}).get("keys", [])))
        if isinstance(bundle.get("environment"), dict)
        else 0,
        "delta": delta,
        "predecessor": (
            {"artifact_id": predecessor["artifact_id"], "bundle_hash": predecessor["bundle_hash"]}
            if predecessor
            else None
        ),
    }


def open_founder_preview(store: Store, artifact_id: str) -> dict[str, object]:
    record = store.get_founder_artifact(artifact_id)
    if record is None:
        raise KeyError(artifact_id)
    bundle = sanitize_bundle(cast(dict[str, Any], record["bundle"]))
    return {
        "artifact_id": artifact_id,
        "project_id": record["project_id"],
        "bundle_hash": record["bundle_hash"],
        "schemaVersion": bundle.get("schemaVersion"),
        "sourceCode": False,
        "file_count": len(cast(list[object], bundle.get("files", []))),
        "dependency_count": _dependency_count(bundle),
        "env_key_names": _open_env_keys(bundle),
        "finding_count": _finding_count(bundle),
    }


def open_founder_upload(
    settings: Settings,
    store: Store,
    config: dict[str, str],
    artifact_id: str,
) -> dict[str, object]:
    record = store.get_founder_artifact(artifact_id)
    if record is None:
        raise KeyError(artifact_id)
    if record["project_id"] != config["lp_project_id"]:
        raise FounderUploadConflictError("artifact does not belong to the configured Launch Passport project")
    require_fresh_preview(store, artifact_id, record=record)
    bundle = sanitize_bundle(cast(dict[str, Any], record["bundle"]))
    if bundle_hash(bundle) != record["bundle_hash"]:
        raise PrivacyViolation("stored bundle hash does not match")
    with _open_client(settings, config) as client:
        try:
            result = client.upload_bundle(config["lp_project_id"], bundle)
        except (LaunchPassportUnauthorized, LaunchPassportForbidden, LaunchPassportPayloadTooLarge):
            raise
        raw_result = getattr(result, "payload", None)
        result_payload = _sanitize_client_value(
            client,
            raw_result if isinstance(raw_result, dict) else result.as_dict(),
        )
        if not isinstance(result_payload, dict):
            result_payload = result.as_dict()
    store.mark_founder_artifact_uploaded(artifact_id)
    scan_id = _scan_id_from_payload(result_payload)
    if scan_id:
        store.update_founder_artifact_remote(
            artifact_id,
            scan_id=scan_id,
            scan_status=_scan_status_from_payload(result_payload),
            scan=result_payload,
            polling_status="queued",
        )
    return project_founder_upload(result_payload)


def open_founder_status(settings: Settings, config: dict[str, str]) -> dict[str, object]:
    with _open_client(settings, config) as client:
        status_payload = _sanitize_client_value(client, client.status())
        return project_founder_status(status_payload, project_id=config["lp_project_id"])


def open_founder_results(settings: Settings, config: dict[str, str]) -> dict[str, object]:
    with _open_client(settings, config) as client:
        scans = _safe_remote_call(
            lambda: _sanitize_client_value(client, client.list_scans(config["lp_project_id"])),
            capability="scan_results",
        )
        latest_report = _safe_remote_call(
            lambda: _sanitize_client_value(client, client.latest_report(config["lp_project_id"])),
            capability="latest_report",
        )
        status_payload = client.status()
    projected = project_founder_results(
        {"scans": scans, "latest_report": latest_report},
        project_id=config["lp_project_id"],
    )
    if _is_remote_result_error(scans):
        projected["scans"] = scans
    if _is_remote_result_error(latest_report):
        projected["latest_report"] = latest_report
    latest_report_reference = _report_reference(latest_report)
    if latest_report_reference:
        projected["latest_report_reference"] = latest_report_reference
    capability = _launch_capability(status_payload)
    if capability.get("status") != "available":
        projected["capability"] = capability
    return projected


def _sanitize_client_value(client: object, value: object) -> object:
    sanitizer = getattr(client, "sanitize_upstream", None)
    return sanitizer(value) if callable(sanitizer) else scrub_upstream_value(value)


def _is_remote_result_error(value: object) -> bool:
    return isinstance(value, dict) and value.get("status") in {
        "not_authorized",
        "unavailable",
        "insufficient_credits",
        "rate_limited",
    }


def open_founder_launch_scan(
    settings: Settings,
    store: Store,
    config: dict[str, str],
    artifact_id: str | None = None,
) -> dict[str, object]:
    with _open_client(settings, config) as client:
        result = _sanitize_client_value(client, client.launch_scan(config["lp_project_id"]))
    if not isinstance(result, dict):
        raise FounderPackContractError("Launch Passport launch scan must return an object")
    response = {"project_id": config["lp_project_id"], **result}
    if result.get("status") == "not_authorized":
        response["guidance"] = "This token cannot launch scans; finish the scan in Launch Passport."
    scan_id = _scan_id_from_payload(result)
    if artifact_id and scan_id:
        store.update_founder_artifact_remote(
            artifact_id,
            scan_id=scan_id,
            scan_status=_scan_status_from_payload(result),
            scan=result,
            polling_status="queued",
        )
    return response


def watch_founder_scan(
    settings: Settings,
    store: Store,
    config: dict[str, str],
    scan_id: str,
    *,
    artifact_id: str | None = None,
    max_duration: float = 3600.0,
    max_attempts: int = 120,
) -> dict[str, object]:
    with _open_client(settings, config) as client:
        outcome = poll_scan(
            client,
            config["lp_project_id"],
            scan_id,
            max_duration=max_duration,
            max_attempts=max_attempts,
        )
    _persist_poll_outcome(store, artifact_id, outcome)
    return outcome.as_dict()


def _open_client(settings: Settings, config: dict[str, str]) -> LaunchPassportClient:
    token_ref = config["token_vault_ref"]

    def token_provider() -> str | None:
        try:
            return SecretVault(settings.vault_path).get(token_ref)
        except SecretVaultError:
            return None

    return LaunchPassportClient(config["lp_base_url"], token_provider)


def _persist_poll_outcome(store: Store, artifact_id: str | None, outcome: PollOutcome) -> None:
    if not artifact_id:
        return
    report_reference = _report_reference(outcome.report)
    store.update_founder_artifact_remote(
        artifact_id,
        scan_id=outcome.scan_id,
        scan_status=_scan_status_from_payload(outcome.scan or {}),
        scan=outcome.scan,
        report_reference=report_reference,
        report=outcome.report,
        polling_status=outcome.status,
    )


def _safe_remote_call(call: Any, *, capability: str) -> object:
    try:
        return call()
    except LaunchPassportForbidden:
        return {"status": "not_authorized", "capability": capability}
    except LaunchPassportUnauthorized:
        return {"status": "unavailable", "error": "Launch Passport token was rejected"}
    except LaunchPassportInsufficientCredits:
        return {"status": "insufficient_credits", "capability": capability}
    except LaunchPassportRateLimited as exc:
        return {"status": "rate_limited", "retry_after": exc.retry_after, "capability": capability}
    except LaunchPassportRequestError:
        return {"status": "unavailable", "error": "Launch Passport request failed"}


def _launch_capability(status_payload: object) -> dict[str, object]:
    if not isinstance(status_payload, dict):
        return {"status": "unknown"}
    capabilities = status_payload.get("capabilities")
    if not isinstance(capabilities, dict):
        return {"status": "unknown"}
    available = capabilities.get("launch_scan", capabilities.get("scan:launch"))
    if available is True:
        return {"status": "available", "scope": "scan:launch"}
    if available is False:
        return {
            "status": "not_authorized",
            "scope": "scan:launch",
            "guidance": "This token cannot launch scans; finish the scan in Launch Passport.",
        }
    return {"status": "unknown", "scope": "scan:launch"}


def _scan_id_from_payload(payload: dict[str, Any]) -> str:
    nested = payload.get("scan")
    if isinstance(nested, dict):
        for key in ("scanId", "scan_id", "id"):
            value = nested.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    for key in ("scanId", "scan_id"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _scan_status_from_payload(payload: dict[str, Any]) -> str:
    nested = payload.get("scan")
    candidate = nested if isinstance(nested, dict) else payload
    value = candidate.get("status") or candidate.get("state")
    return value.strip().lower() if isinstance(value, str) else ""


def _report_reference(payload: object) -> str:
    if not isinstance(payload, dict):
        return ""
    for key in ("reportId", "report_id", "id"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    report = payload.get("report")
    if isinstance(report, dict):
        return _report_reference(report)
    return ""


def _open_env_keys(bundle: dict[str, Any]) -> list[str]:
    environment = bundle.get("environment")
    if isinstance(environment, dict) and isinstance(environment.get("keys"), dict):
        return sorted(
            str(key)
            for values in environment["keys"].values()
            if isinstance(values, list)
            for key in values
        )
    return []


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


def project_founder_scan(value: object, *, token: str | None = None) -> dict[str, object]:
    safe = scrub_upstream_value(json_object(value, operation="scan"), token=token)
    if not isinstance(safe, dict):
        raise FounderPackContractError("founder pack scan must return an object")
    projected: dict[str, object] = {
        "status": normalize_upstream_state(
            safe.get("status", safe.get("state")), LAUNCH_PASSPORT_SCAN_STATES
        )
    }
    artifact_id = safe.get("artifact_id") or safe.get("artifactId")
    if isinstance(artifact_id, str) and artifact_id:
        projected["artifact_id"] = artifact_id
    project_id = safe.get("project_id") or safe.get("projectId")
    if isinstance(project_id, str) and project_id:
        projected["project_id"] = project_id
    for key in ("file_count", "dependency_count", "env_key_count"):
        count = safe.get(key)
        if isinstance(count, int) and count >= 0:
            projected[key] = count
    return projected


def project_founder_upload(value: object, *, token: str | None = None) -> dict[str, object]:
    safe = scrub_upstream_value(json_object(value, operation="upload"), token=token)
    if not isinstance(safe, dict):
        raise FounderPackContractError("founder pack upload must return an object")
    artifact_id = safe.get("artifact_id") or safe.get("artifactId")
    projected: dict[str, object] = {
        "status": normalize_upstream_state(
            safe.get("status", safe.get("state")), LAUNCH_PASSPORT_UPLOAD_STATES, default="unknown"
        )
    }
    if isinstance(artifact_id, str) and artifact_id:
        projected["artifact_id"] = artifact_id
    return projected


def project_founder_status(
    value: object,
    *,
    project_id: str | None = None,
    token: str | None = None,
) -> dict[str, object]:
    safe = scrub_upstream_value(value, token=token)
    source = safe if isinstance(safe, dict) else {}
    capabilities = source.get("capabilities")
    projected_capabilities = (
        {"launch_scan": capabilities["launch_scan"]}
        if isinstance(capabilities, dict) and isinstance(capabilities.get("launch_scan"), bool)
        else {}
    )
    result: dict[str, object] = {
        "status": normalize_upstream_state(
            source.get("status", source.get("state")),
            LAUNCH_PASSPORT_CONNECTION_STATES,
            default="unknown",
        ),
        "token_configured": OPERATION_CONFIRMED,
        "capabilities": projected_capabilities,
    }
    if project_id:
        result["lp_project_id"] = project_id
    return result


def project_founder_results(
    value: object,
    *,
    project_id: str | None = None,
    token: str | None = None,
) -> dict[str, object]:
    safe = scrub_upstream_value(value, token=token)
    source = safe if isinstance(safe, dict) else {}
    raw_scans = source.get("scans")
    scan_items: list[object]
    if isinstance(raw_scans, list):
        scan_items = raw_scans
    elif isinstance(raw_scans, dict) and isinstance(raw_scans.get("items"), list):
        scan_items = cast(list[object], raw_scans["items"])
    else:
        scan_items = []
    states = [
        normalize_upstream_state(
            item.get("status", item.get("state")) if isinstance(item, dict) else None,
            LAUNCH_PASSPORT_SCAN_STATES,
        )
        for item in scan_items
    ]
    count = len(scan_items)
    if not scan_items and isinstance(raw_scans, dict) and isinstance(raw_scans.get("count"), int):
        count = max(0, raw_scans["count"])
    latest_report = source.get("latest_report")
    report_available = latest_report is not None and latest_report not in ({}, [])
    result: dict[str, object] = {
        "scans": {"count": count, "states": states},
        "latest_report": {"available": report_available},
    }
    if project_id:
        result["project_id"] = project_id
    return result


def build_upload_preview(artifact_id: str, bundle: dict[str, object]) -> dict[str, object]:
    file_tree = ensure_list(bundle.get("files", bundle.get("file_tree")), key="files")
    manifests = ensure_list(bundle.get("manifests"), key="manifests")
    routes = ensure_list(bundle.get("routes"), key="routes")
    environment = bundle.get("environment")
    if isinstance(environment, dict) and isinstance(environment.get("keys"), dict):
        env_keys = [key for values in environment["keys"].values() if isinstance(values, list) for key in values]
    else:
        env_keys = ensure_list(bundle.get("env_keys"), key="env_keys")
    raw_findings = bundle.get("findings")
    findings = (
        list(raw_findings.get("items", []))
        if isinstance(raw_findings, dict) and isinstance(raw_findings.get("items", []), list)
        else ensure_list(raw_findings, key="findings")
    )

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
        "schema_version": bundle.get("schemaVersion", bundle.get("schema_version")),
        "project_name": bundle.get("project_name"),
        "file_count": len(file_tree),
        "manifest_count": len(manifests),
        "route_count": len(routes),
        "env_key_names": env_key_names,
        "finding_types": sorted(set(finding_types)),
    }


def sanitized_pack_bundle(pack: LoadedPack, artifact_id: str) -> dict[str, Any]:
    raw_bundle = json_object(invoke_founder(pack, "export_bundle", artifact_id), operation="export_bundle")
    return sanitize_bundle(raw_bundle)


def require_fresh_preview(
    store: Store,
    artifact_id: str,
    *,
    record: dict[str, object] | None = None,
) -> None:
    previewed_at = (
        str(record.get("previewed_at", ""))
        if record is not None
        else store.get_founder_artifact_previewed_at(artifact_id)
    )
    if not previewed_at:
        raise FounderUploadConflictError("upload preview required before upload; run founder preview first")
    try:
        preview_time = datetime.fromisoformat(previewed_at)
    except ValueError as exc:
        raise FounderUploadConflictError("upload preview is stale; run founder preview again") from exc
    age = (datetime.now(UTC) - preview_time).total_seconds()
    if age < 0 or age > PREVIEW_MAX_AGE_SECONDS:
        raise FounderUploadConflictError("upload preview is stale; run founder preview again")


def _dependency_count(bundle: dict[str, Any]) -> int:
    dependencies = bundle.get("dependencies")
    if isinstance(dependencies, dict):
        return sum(
            len(values)
            for key in ("productionDependencies", "developmentDependencies")
            if isinstance(values := dependencies.get(key), list)
        )
    return len(cast(list[object], dependencies)) if isinstance(dependencies, list) else 0


def _finding_count(bundle: dict[str, Any]) -> int:
    findings = bundle.get("findings")
    if isinstance(findings, dict):
        items = findings.get("items")
        return len(items) if isinstance(items, list) else len(findings)
    return len(findings) if isinstance(findings, list) else 0


def ensure_list(value: object, *, key: str) -> list[object]:
    if isinstance(value, list):
        return value
    raise FounderPackContractError(f"founder bundle {key} must be a list")


def render_json(value: object) -> str:
    return json.dumps(json_value(value, operation="render"), sort_keys=True, indent=2)
