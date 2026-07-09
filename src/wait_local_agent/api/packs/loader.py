from __future__ import annotations

import base64
import hashlib
import hmac
import importlib
import io
import json
import logging
import pkgutil
import tarfile
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from types import ModuleType
from typing import Any, cast

import typer
from fastapi import APIRouter, FastAPI

from wait_local_agent.config import Settings
from wait_local_agent.vault import SecretVault

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class LoadedPack:
    manifest: dict[str, Any]
    module: ModuleType


@dataclass(frozen=True)
class PackStatus:
    name: str
    version: str
    locked: bool
    requires_license: bool
    cli_available: bool
    router_available: bool
    mounted_cli: bool = False
    mounted_router: bool = False
    error: str | None = None


@dataclass
class PackRegistry:
    loaded: dict[str, LoadedPack] = field(default_factory=dict)
    statuses: list[PackStatus] = field(default_factory=list)

    def get_pack(self, name: str) -> LoadedPack | None:
        return self.loaded.get(name)


@dataclass(frozen=True)
class PackInstallResult:
    pack_name: str
    version: str
    extracted_files: tuple[Path, ...]
    license_stored_in_vault: bool


class PackInstallError(RuntimeError):
    """Raised when pack discovery or installation cannot proceed safely."""


_ACTIVE_REGISTRY = PackRegistry()


def get_pack(name: str) -> LoadedPack | None:
    return _ACTIVE_REGISTRY.get_pack(name)


def load_pack_registry(
    settings: Settings,
    candidate_module_names: Iterable[str] | None = None,
) -> PackRegistry:
    registry = PackRegistry()
    for module_name in _discover_candidate_modules(candidate_module_names):
        try:
            module = importlib.import_module(module_name)
            manifest = _load_manifest(module)
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("Skipping pack module %s: %s", module_name, exc)
            continue
        if manifest is None:
            continue
        locked = bool(manifest["requires_license"]) and not _pack_enabled(
            cast(str, manifest["name"]),
            settings,
        )
        registry.statuses.append(
            PackStatus(
                name=cast(str, manifest["name"]),
                version=cast(str, manifest["version"]),
                locked=locked,
                requires_license=cast(bool, manifest["requires_license"]),
                cli_available=manifest["cli_app"] is not None,
                router_available=manifest["api_router_factory"] is not None,
            )
        )
        if not locked:
            registry.loaded[cast(str, manifest["name"])] = LoadedPack(manifest=manifest, module=module)
    registry.statuses.sort(key=lambda status: status.name)
    _set_active_registry(registry)
    return registry


def configure_pack_routes(
    app: FastAPI,
    settings: Settings,
    candidate_module_names: Iterable[str] | None = None,
) -> PackRegistry:
    registry = load_pack_registry(settings, candidate_module_names)
    updated_statuses: list[PackStatus] = []
    for status in registry.statuses:
        mounted_router = False
        error: str | None = None
        if not status.locked and status.router_available and status.name != "founder":
            try:
                loaded_pack = registry.loaded[status.name]
                router = _resolve_router(loaded_pack.manifest["api_router_factory"])
                app.include_router(router, prefix=f"/packs/{status.name}")
                mounted_router = True
            except Exception as exc:  # noqa: BLE001
                LOGGER.warning("Skipping pack router for %s: %s", status.name, exc)
                registry.loaded.pop(status.name, None)
                error = str(exc)
        updated_statuses.append(
            PackStatus(
                name=status.name,
                version=status.version,
                locked=status.locked,
                requires_license=status.requires_license,
                cli_available=status.cli_available,
                router_available=status.router_available,
                mounted_cli=status.mounted_cli,
                mounted_router=mounted_router,
                error=error,
            )
        )
    registry.statuses = updated_statuses
    app.state.pack_registry = registry
    _set_active_registry(registry)
    return registry


def configure_pack_cli(
    typer_app: typer.Typer,
    settings: Settings,
    candidate_module_names: Iterable[str] | None = None,
) -> PackRegistry:
    registry = load_pack_registry(settings, candidate_module_names)
    updated_statuses: list[PackStatus] = []
    collisions = _existing_top_level_commands(typer_app)
    for status in registry.statuses:
        mounted_cli = False
        error: str | None = None
        if not status.locked and status.cli_available:
            if status.name in collisions:
                LOGGER.warning("Skipping pack CLI for %s due to command collision", status.name)
                error = "command collision"
            else:
                try:
                    loaded_pack = registry.loaded[status.name]
                    typer_app.add_typer(_resolve_typer(loaded_pack.manifest["cli_app"]), name=status.name)
                    collisions.add(status.name)
                    mounted_cli = True
                except Exception as exc:  # noqa: BLE001
                    LOGGER.warning("Skipping pack CLI for %s: %s", status.name, exc)
                    registry.loaded.pop(status.name, None)
                    error = str(exc)
        updated_statuses.append(
            PackStatus(
                name=status.name,
                version=status.version,
                locked=status.locked,
                requires_license=status.requires_license,
                cli_available=status.cli_available,
                router_available=status.router_available,
                mounted_cli=mounted_cli,
                mounted_router=status.mounted_router,
                error=error,
            )
        )
    registry.statuses = updated_statuses
    _set_active_registry(registry)
    return registry


def install_pack_tarball(
    tarball_path: Path,
    *,
    license_key: str | None,
    settings: Settings,
    install_root: Path | None = None,
) -> PackInstallResult:
    if not settings.pack_signing_secret:
        raise PackInstallError("WAIT_PACK_SIGNING_SECRET is required")

    tarball = Path(tarball_path)
    signature_path = Path(f"{tarball}.sig")
    if not signature_path.exists():
        raise PackInstallError(f"missing signature file: {signature_path}")

    tarball_bytes = tarball.read_bytes()
    expected_signature = _urlsafe_b64encode(
        hmac.new(
            settings.pack_signing_secret.encode("utf-8"),
            tarball_bytes,
            hashlib.sha256,
        ).digest()
    )
    actual_signature = signature_path.read_text(encoding="utf-8").strip()
    if not hmac.compare_digest(actual_signature, expected_signature):
        raise PackInstallError("tarball signature mismatch")

    target_root = install_root or Path.cwd()
    manifest, files_to_write = _prepare_installation(tarball_bytes, target_root)
    for target_path, content in files_to_write:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(content)

    stored_in_vault = False
    if license_key:
        if settings.secrets_backend == "fernet":
            SecretVault.initialize(settings.vault_path).set("license_key", license_key)
            stored_in_vault = True
        else:
            LOGGER.warning("License key provided but vault is disabled; set WAIT_LICENSE_KEY manually")

    return PackInstallResult(
        pack_name=cast(str, manifest["name"]),
        version=cast(str, manifest["version"]),
        extracted_files=tuple(path.relative_to(target_root) for path, _ in files_to_write),
        license_stored_in_vault=stored_in_vault,
    )


def _prepare_installation(
    tarball_bytes: bytes,
    install_root: Path,
) -> tuple[dict[str, Any], list[tuple[Path, bytes]]]:
    try:
        with tarfile.open(fileobj=io.BytesIO(tarball_bytes), mode="r:gz") as archive:
            manifest = _read_manifest(archive)
            files_to_write: list[tuple[Path, bytes]] = []
            member_digests: list[str] = []
            for member in archive.getmembers():
                if member.name == "manifest.json" or not member.isfile():
                    continue
                member_path = _safe_member_path(member.name)
                extracted = archive.extractfile(member)
                if extracted is None:
                    raise PackInstallError(f"missing tar member contents for {member.name}")
                content = extracted.read()
                member_digests.append(hashlib.sha256(content).hexdigest())
                files_to_write.append((install_root / member_path, content))
    except tarfile.TarError as exc:
        raise PackInstallError("invalid pack tarball") from exc

    aggregate = hashlib.sha256("".join(sorted(member_digests)).encode("utf-8")).hexdigest()
    if manifest.get("sha256") != aggregate:
        raise PackInstallError("manifest digest mismatch")
    return manifest, files_to_write


def _read_manifest(archive: tarfile.TarFile) -> dict[str, Any]:
    try:
        manifest_member = archive.getmember("manifest.json")
    except KeyError as exc:
        raise PackInstallError("manifest.json is missing from tarball") from exc
    extracted = archive.extractfile(manifest_member)
    if extracted is None:
        raise PackInstallError("manifest.json could not be read")
    manifest = json.loads(extracted.read().decode("utf-8"))
    if not isinstance(manifest, dict):
        raise PackInstallError("manifest.json payload is malformed")
    _validate_manifest(manifest)
    sha256_value = manifest.get("sha256")
    if not isinstance(sha256_value, str) or not sha256_value:
        raise PackInstallError("manifest.json sha256 is required")
    return manifest


def _safe_member_path(member_name: str) -> Path:
    path = PurePosixPath(member_name)
    if path.is_absolute() or ".." in path.parts:
        raise PackInstallError(f"unsafe tar member: {member_name}")
    if not path.parts or path.parts[0] not in {"packs", "sync"}:
        raise PackInstallError(f"unexpected tar member root: {member_name}")
    return Path(*path.parts)


def _discover_candidate_modules(candidate_module_names: Iterable[str] | None) -> list[str]:
    if candidate_module_names is not None:
        return list(dict.fromkeys(candidate_module_names))
    candidates: list[str] = []
    try:
        packs_module = importlib.import_module("packs")
    except ImportError:
        packs_module = None
    if packs_module is not None:
        package_paths = getattr(packs_module, "__path__", None)
        if package_paths is not None:
            for module_info in pkgutil.iter_modules(package_paths):
                candidates.append(f"packs.{module_info.name}")
    if importlib.util.find_spec("sync") is not None:
        candidates.append("sync")
    return list(dict.fromkeys(candidates))


def _load_manifest(module: ModuleType) -> dict[str, Any] | None:
    manifest = getattr(module, "PACK_MANIFEST", None)
    if manifest is None:
        return None
    if not isinstance(manifest, dict):
        raise TypeError(f"{module.__name__}.PACK_MANIFEST must be a dict")
    _validate_manifest(manifest)
    return manifest


def _validate_manifest(manifest: dict[str, Any]) -> None:
    for key in ("name", "version"):
        value = manifest.get(key)
        if not isinstance(value, str) or not value:
            raise ValueError(f"PACK_MANIFEST[{key!r}] must be a non-empty string")
    if not isinstance(manifest.get("requires_license"), bool):
        raise ValueError("PACK_MANIFEST['requires_license'] must be a bool")
    for key in ("api_router_factory", "cli_app"):
        value = manifest.get(key)
        if value is not None and not isinstance(value, str):
            raise ValueError(f"PACK_MANIFEST[{key!r}] must be a string or None")


def _pack_enabled(pack_name: str, settings: Settings) -> bool:
    try:
        pack_keys = importlib.import_module("packs.license.keys")
    except ImportError:
        return False
    try:
        pack_enabled = pack_keys.pack_enabled
        return bool(pack_enabled(pack_name, settings.license_key or None))
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("License validation failed for pack %s: %s", pack_name, exc)
        return False


def _resolve_router(target: Any) -> APIRouter:
    resolved = _resolve_dotted_ref(target)
    if not callable(resolved):
        raise TypeError("api_router_factory must resolve to a callable")
    router = resolved()
    if not isinstance(router, APIRouter):
        raise TypeError("api_router_factory must return an APIRouter")
    return router


def _resolve_typer(target: Any) -> typer.Typer:
    resolved = _resolve_dotted_ref(target)
    if isinstance(resolved, typer.Typer):
        return resolved
    if not callable(resolved):
        raise TypeError("cli_app must resolve to a Typer app or zero-arg factory")
    app = resolved()
    if not isinstance(app, typer.Typer):
        raise TypeError("cli_app must produce a Typer app")
    return app


def _resolve_dotted_ref(target: Any) -> Any:
    if not isinstance(target, str):
        return target
    module_name, separator, attribute = target.rpartition(".")
    if not separator:
        raise ValueError(f"invalid dotted path: {target}")
    module = importlib.import_module(module_name)
    return getattr(module, attribute)


def _existing_top_level_commands(typer_app: typer.Typer) -> set[str]:
    names = {
        cast(str, group.name)
        for group in getattr(typer_app, "registered_groups", [])
        if getattr(group, "name", None)
    }
    names.update(
        cast(str, command.name)
        for command in getattr(typer_app, "registered_commands", [])
        if getattr(command, "name", None)
    )
    return names


def _set_active_registry(registry: PackRegistry) -> None:
    global _ACTIVE_REGISTRY
    _ACTIVE_REGISTRY = registry


def _urlsafe_b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("utf-8").rstrip("=")
