from __future__ import annotations

import base64
import hashlib
import hmac
import io
import json
import sys
import tarfile
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

import pytest
import typer
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient
from typer.testing import CliRunner

import wait_local_agent.api.app as app_module
import wait_local_agent.api.packs.loader as loader_module
import wait_local_agent.cli as cli_module
from wait_local_agent.api.packs.loader import (
    PackInstallError,
    configure_pack_routes,
    get_pack,
    install_pack_tarball,
    load_pack_registry,
)
from wait_local_agent.vault import SecretVault


@pytest.fixture(autouse=True)
def clear_pack_modules() -> Iterator[None]:
    original_modules = dict(sys.modules)
    yield
    for name in list(sys.modules):
        if name == "packs" or name.startswith("packs.") or name == "sync" or name.startswith("sync."):
            sys.modules.pop(name, None)
    for name, module in original_modules.items():
        if name == "packs" or name.startswith("packs.") or name == "sync" or name.startswith("sync."):
            sys.modules[name] = module
    cli_module.sync_pack_cli([])


def test_load_pack_registry_tracks_locked_and_unlocked_packs(settings) -> None:
    candidates = _install_fake_pack_modules(licensed=True)

    unlocked = load_pack_registry(
        settings.__class__(**{**settings.__dict__, "license_key": "valid-licensed-license"}),
        candidates,
    )
    locked = load_pack_registry(settings, candidates)

    assert [status.name for status in unlocked.statuses] == ["demo", "licensed"]
    assert unlocked.get_pack("licensed") is not None
    assert locked.get_pack("licensed") is None
    assert locked.statuses[1].locked is True


def test_pack_routes_mount_and_cli_register_for_unlocked_pack(settings, monkeypatch) -> None:
    candidates = _install_fake_pack_modules()
    monkeypatch.setattr(loader_module, "_discover_candidate_modules", lambda _: candidates)
    monkeypatch.setattr(
        app_module,
        "configure_pack_routes",
        lambda app, active_settings, route_dependencies=None: configure_pack_routes(
            app,
            active_settings,
            candidates,
            route_dependencies=route_dependencies,
        ),
    )
    cli_module.sync_pack_cli(candidates)
    client = TestClient(app_module.create_app(settings))
    runner = CliRunner()

    response = client.get("/packs/demo/ping")
    cli_result = runner.invoke(cli_module.app, ["demo", "ping"])

    assert response.status_code == 200
    assert response.json() == {"pack": "demo"}
    assert cli_result.exit_code == 0
    assert "demo-cli" in cli_result.output
    assert get_pack("demo") is not None


def test_pack_routes_inherit_viewer_auth(settings, monkeypatch) -> None:
    candidates = _install_fake_pack_modules()
    secure_settings = settings.__class__(
        **{
            **settings.__dict__,
            "demo_mode": False,
            "viewer_token": "viewer-token",
        }
    )
    monkeypatch.setattr(loader_module, "_discover_candidate_modules", lambda _: candidates)
    monkeypatch.setattr(
        app_module,
        "configure_pack_routes",
        lambda app, active_settings, route_dependencies=None: configure_pack_routes(
            app,
            active_settings,
            candidates,
            route_dependencies=route_dependencies,
        ),
    )
    client = TestClient(app_module.create_app(secure_settings))

    unauthorized = client.get("/packs/demo/ping")
    authorized = client.get("/packs/demo/ping", headers={"Authorization": "Bearer viewer-token"})

    assert unauthorized.status_code == 401
    assert authorized.status_code == 200


def test_locked_pack_is_listed_but_not_mounted(settings, monkeypatch) -> None:
    candidates = _install_fake_pack_modules(licensed=True)
    monkeypatch.setattr(loader_module, "_discover_candidate_modules", lambda _: candidates)
    monkeypatch.setattr(
        app_module,
        "configure_pack_routes",
        lambda app, active_settings, route_dependencies=None: configure_pack_routes(
            app,
            active_settings,
            candidates,
            route_dependencies=route_dependencies,
        ),
    )
    cli_module.sync_pack_cli(candidates)
    client = TestClient(app_module.create_app(settings))
    runner = CliRunner()

    list_result = runner.invoke(cli_module.app, ["packs", "list"])
    response = client.get("/packs/licensed/ping")
    cli_result = runner.invoke(cli_module.app, ["licensed", "ping"])

    assert list_result.exit_code == 0
    assert "licensed 2.0.0 locked" in list_result.output
    assert response.status_code == 404
    assert cli_result.exit_code != 0


def test_broken_pack_import_and_router_failure_do_not_crash_startup(settings, caplog) -> None:
    candidates = _install_fake_pack_modules(include_broken_router=True)
    app = FastAPI()

    with caplog.at_level("WARNING"):
        registry = configure_pack_routes(
            app,
            settings,
            [*candidates, "packs.does_not_exist"],
        )

    client = TestClient(app)

    assert client.get("/packs/demo/ping").status_code == 200
    assert client.get("/packs/broken/ping").status_code == 404
    assert registry.get_pack("broken") is None
    assert "Skipping pack router for broken" in caplog.text
    assert "Skipping pack module packs.does_not_exist" in caplog.text


def test_founder_router_is_not_auto_mounted(settings) -> None:
    candidates = _install_founder_pack()
    app = FastAPI()

    configure_pack_routes(app, settings, candidates)
    client = TestClient(app)

    assert client.get("/packs/founder/ping").status_code == 404
    assert get_pack("founder") is not None


def test_install_pack_tarball_validates_signature_and_paths(settings, tmp_path) -> None:
    tarball = _write_pack_tarball(tmp_path, {"packs/demo/__init__.py": b"print('ok')\n"})
    signed_settings = settings.__class__(
        **{
            **settings.__dict__,
            "pack_signing_secret": "signing-secret",
            "secrets_backend": "fernet",
            "vault_path": tmp_path / "vault",
        }
    )

    result = install_pack_tarball(
        tarball,
        license_key="license-value",
        settings=signed_settings,
        install_root=tmp_path / "install",
    )

    assert result.pack_name == "demo"
    assert (tmp_path / "install" / "packs" / "demo" / "__init__.py").exists()
    assert result.license_stored_in_vault is True
    assert SecretVault(signed_settings.vault_path).get("license_key") == "license-value"


def test_install_pack_tarball_rejects_tampering_and_traversal(settings, tmp_path) -> None:
    signed_settings = settings.__class__(
        **{**settings.__dict__, "pack_signing_secret": "signing-secret"}
    )
    valid_tarball = _write_pack_tarball(tmp_path, {"packs/demo/__init__.py": b"print('ok')\n"})
    tampered_sig = Path(f"{valid_tarball}.sig")
    tampered_sig.write_text("invalid-signature", encoding="utf-8")

    with pytest.raises(PackInstallError):
        install_pack_tarball(valid_tarball, license_key=None, settings=signed_settings, install_root=tmp_path / "x")

    traversal_tarball = _write_pack_tarball(
        tmp_path,
        {"../evil.py": b"x"},
        filename="wait-pack-demo-2.0.0.tar.gz",
    )

    with pytest.raises(PackInstallError):
        install_pack_tarball(
            traversal_tarball,
            license_key=None,
            settings=signed_settings,
            install_root=tmp_path / "y",
        )


def test_install_pack_tarball_requires_secret_and_signature(settings, tmp_path, caplog) -> None:
    tarball = _write_pack_tarball(tmp_path, {"packs/demo/__init__.py": b"print('ok')\n"})

    with pytest.raises(PackInstallError, match="WAIT_PACK_SIGNING_SECRET is required"):
        install_pack_tarball(tarball, license_key=None, settings=settings, install_root=tmp_path / "install")

    Path(f"{tarball}.sig").unlink()
    signed_settings = settings.__class__(
        **{**settings.__dict__, "pack_signing_secret": "signing-secret"}
    )
    with pytest.raises(PackInstallError, match="missing signature file"):
        install_pack_tarball(tarball, license_key=None, settings=signed_settings, install_root=tmp_path / "install")

    tarball = _write_pack_tarball(tmp_path, {"packs/demo/__init__.py": b"print('ok')\n"})
    with caplog.at_level("WARNING"):
        result = install_pack_tarball(
            tarball,
            license_key="manual-license",
            settings=signed_settings,
            install_root=tmp_path / "install-2",
        )

    assert result.license_stored_in_vault is False
    assert "set WAIT_LICENSE_KEY manually" in caplog.text


def test_loader_internal_helpers_cover_error_paths(monkeypatch, settings) -> None:
    _install_package("packs")
    _install_license_module()
    broken_manifest_module = ModuleType("packs.invalid_manifest")
    broken_manifest_module.__dict__["PACK_MANIFEST"] = "not-a-dict"
    sys.modules["packs.invalid_manifest"] = broken_manifest_module
    collision_pack = ModuleType("packs.tickets")
    collision_pack.__dict__["cli_app"] = typer.Typer()
    collision_pack.__dict__["PACK_MANIFEST"] = {
        "name": "tickets",
        "version": "1.0.0",
        "requires_license": False,
        "api_router_factory": None,
        "cli_app": "packs.tickets.cli_app",
    }
    sys.modules["packs.tickets"] = collision_pack
    bad_cli = ModuleType("packs.bad_cli")

    def bad_cli_factory() -> str:
        return "nope"

    bad_cli.__dict__["bad_cli_factory"] = bad_cli_factory
    bad_cli.__dict__["PACK_MANIFEST"] = {
        "name": "bad-cli",
        "version": "1.0.0",
        "requires_license": False,
        "api_router_factory": None,
        "cli_app": "packs.bad_cli.bad_cli_factory",
    }
    sys.modules["packs.bad_cli"] = bad_cli
    bad_router = ModuleType("packs.bad_router")
    bad_router.__dict__["not_callable"] = "router"
    bad_router.__dict__["PACK_MANIFEST"] = {
        "name": "bad-router",
        "version": "1.0.0",
        "requires_license": False,
        "api_router_factory": "packs.bad_router.not_callable",
        "cli_app": None,
    }
    sys.modules["packs.bad_router"] = bad_router

    typer_app = typer.Typer()
    typer_app.add_typer(typer.Typer(), name="tickets")
    registry = loader_module.configure_pack_cli(
        typer_app,
        settings,
        ["packs.invalid_manifest", "packs.tickets", "packs.bad_cli"],
    )
    route_registry = configure_pack_routes(
        app=FastAPI(),
        settings=settings,
        candidate_module_names=["packs.bad_router"],
    )
    statuses = {status.name: status for status in registry.statuses}

    assert registry.get_pack("tickets") is not None
    assert statuses["tickets"].error == "command collision"
    assert statuses["bad-cli"].error == "cli_app must produce a Typer app"
    assert registry.get_pack("bad-cli") is None
    assert route_registry.get_pack("bad-router") is None

    with pytest.raises(PackInstallError, match="unexpected tar member root"):
        loader_module._safe_member_path("other/demo.py")
    with pytest.raises(PackInstallError, match="unsafe tar member"):
        loader_module._safe_member_path("/etc/passwd")
    with pytest.raises(ValueError, match="PACK_MANIFEST\\['name'\\]"):
        loader_module._validate_manifest({"name": "", "version": "1.0.0", "requires_license": False})
    with pytest.raises(ValueError, match="requires_license"):
        loader_module._validate_manifest({"name": "demo", "version": "1.0.0", "requires_license": "yes"})
    with pytest.raises(ValueError, match="cli_app"):
        loader_module._validate_manifest(
            {
                "name": "demo",
                "version": "1.0.0",
                "requires_license": False,
                "api_router_factory": None,
                "cli_app": 1,
            }
        )
    assert loader_module._resolve_dotted_ref(123) == 123
    with pytest.raises(ValueError, match="invalid dotted path"):
        loader_module._resolve_dotted_ref("missingdot")
    with pytest.raises(TypeError, match="api_router_factory must resolve to a callable"):
        loader_module._resolve_router("packs.bad_router.not_callable")
    with pytest.raises(TypeError, match="cli_app must produce a Typer app"):
        loader_module._resolve_typer("packs.bad_cli.bad_cli_factory")


def test_loader_discovers_sync_and_handles_pack_enabled_failures(monkeypatch, settings, caplog) -> None:
    packs_module = _install_package("packs")
    sync_module = ModuleType("sync")
    sync_module.__dict__["PACK_MANIFEST"] = {
        "name": "sync",
        "version": "1.0.0",
        "requires_license": False,
        "api_router_factory": None,
        "cli_app": None,
    }
    sys.modules["sync"] = sync_module

    class FakeModuleInfo:
        name = "alpha"

    alpha_module = ModuleType("packs.alpha")
    alpha_module.__dict__["PACK_MANIFEST"] = {
        "name": "alpha",
        "version": "1.0.0",
        "requires_license": True,
        "api_router_factory": None,
        "cli_app": None,
    }
    sys.modules["packs.alpha"] = alpha_module
    license_module = ModuleType("packs.license.keys")

    def explode(_pack_name: str, _license_key: str | None) -> bool:
        raise RuntimeError("boom")

    license_module.__dict__["pack_enabled"] = explode
    sys.modules["packs.license.keys"] = license_module

    monkeypatch.setattr(loader_module.pkgutil, "iter_modules", lambda _paths: [FakeModuleInfo()])
    monkeypatch.setattr(loader_module.importlib.util, "find_spec", lambda name: object() if name == "sync" else None)
    packs_module.__dict__["__path__"] = ["fake"]

    with caplog.at_level("WARNING"):
        discovered = loader_module._discover_candidate_modules(None)
        registry = load_pack_registry(settings, None)

    assert discovered == ["packs.alpha", "sync"]
    assert [status.name for status in registry.statuses] == ["alpha", "sync"]
    assert registry.get_pack("alpha") is None
    assert "License validation failed for pack alpha" in caplog.text


def test_manifest_reading_and_helper_error_branches(settings) -> None:
    empty_module = ModuleType("packs.empty")
    assert loader_module._load_manifest(empty_module) is None

    missing_manifest = io.BytesIO()
    with tarfile.open(fileobj=missing_manifest, mode="w:gz"):
        pass
    missing_manifest.seek(0)
    with tarfile.open(fileobj=missing_manifest, mode="r:gz") as archive:
        with pytest.raises(PackInstallError, match="manifest.json is missing"):
            loader_module._read_manifest(archive)

    malformed_manifest = io.BytesIO()
    with tarfile.open(fileobj=malformed_manifest, mode="w:gz") as archive:
        payload = b"[]"
        info = tarfile.TarInfo("manifest.json")
        info.size = len(payload)
        archive.addfile(info, io.BytesIO(payload))
    malformed_manifest.seek(0)
    with tarfile.open(fileobj=malformed_manifest, mode="r:gz") as archive:
        with pytest.raises(PackInstallError, match="payload is malformed"):
            loader_module._read_manifest(archive)

    missing_sha_manifest = io.BytesIO()
    with tarfile.open(fileobj=missing_sha_manifest, mode="w:gz") as archive:
        payload = json.dumps(
            {
                "name": "demo",
                "version": "1.0.0",
                "requires_license": False,
                "api_router_factory": None,
                "cli_app": None,
            }
        ).encode("utf-8")
        info = tarfile.TarInfo("manifest.json")
        info.size = len(payload)
        archive.addfile(info, io.BytesIO(payload))
    missing_sha_manifest.seek(0)
    with tarfile.open(fileobj=missing_sha_manifest, mode="r:gz") as archive:
        with pytest.raises(PackInstallError, match="sha256 is required"):
            loader_module._read_manifest(archive)

    assert loader_module._pack_enabled("demo", settings) is False


def test_prepare_installation_and_resolver_edge_cases(tmp_path) -> None:
    tampered_archive = io.BytesIO()
    with tarfile.open(fileobj=tampered_archive, mode="w:gz") as archive:
        manifest = {
            "name": "demo",
            "version": "1.0.0",
            "requires_license": False,
            "api_router_factory": None,
            "cli_app": None,
            "sha256": "wrong",
        }
        manifest_bytes = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
        manifest_info = tarfile.TarInfo("manifest.json")
        manifest_info.size = len(manifest_bytes)
        archive.addfile(manifest_info, io.BytesIO(manifest_bytes))
        content = b"print('ok')\n"
        info = tarfile.TarInfo("packs/demo/__init__.py")
        info.size = len(content)
        archive.addfile(info, io.BytesIO(content))
    tampered_bytes = tampered_archive.getvalue()
    with pytest.raises(PackInstallError, match="manifest digest mismatch"):
        loader_module._prepare_installation(tampered_bytes, tmp_path / "install")

    not_router = ModuleType("packs.not_router")

    def not_router_factory() -> str:
        return "no-router"

    not_router.__dict__["not_router_factory"] = not_router_factory
    not_router.__dict__["not_callable"] = "not-a-callable"
    sys.modules["packs.not_router"] = not_router

    with pytest.raises(TypeError, match="api_router_factory must return an APIRouter"):
        loader_module._resolve_router("packs.not_router.not_router_factory")
    assert isinstance(loader_module._resolve_typer(typer.Typer()), typer.Typer)
    with pytest.raises(TypeError, match="resolve to a Typer app or zero-arg factory"):
        loader_module._resolve_typer("packs.not_router.not_callable")


def _install_fake_pack_modules(*, licensed: bool = False, include_broken_router: bool = False) -> list[str]:
    _install_package("packs")
    _install_license_module()
    _install_demo_pack("packs.demo", "demo", "1.0.0", requires_license=False)
    candidates = ["packs.demo"]
    if licensed:
        _install_demo_pack("packs.licensed", "licensed", "2.0.0", requires_license=True)
        candidates.append("packs.licensed")
    if include_broken_router:
        _install_demo_pack(
            "packs.broken",
            "broken",
            "3.0.0",
            requires_license=False,
            broken_router=True,
        )
        candidates.append("packs.broken")
    return candidates


def _install_founder_pack() -> list[str]:
    _install_package("packs")
    _install_license_module()
    _install_demo_pack("packs.founder", "founder", "1.0.0", requires_license=False)
    return ["packs.founder"]


def _install_package(name: str) -> ModuleType:
    module = ModuleType(name)
    module.__dict__["__path__"] = []
    sys.modules[name] = module
    return module


def _install_license_module() -> None:
    _install_package("packs.license")
    module = ModuleType("packs.license.keys")

    def pack_enabled(pack_name: str, license_key: str | None) -> bool:
        return bool(license_key) and f"valid-{pack_name}-license" == license_key

    module.pack_enabled = pack_enabled  # type: ignore[attr-defined]
    sys.modules["packs.license.keys"] = module


def _install_demo_pack(
    module_name: str,
    pack_name: str,
    version: str,
    *,
    requires_license: bool,
    broken_router: bool = False,
) -> None:
    module = ModuleType(module_name)

    def build_router() -> APIRouter:
        if broken_router:
            raise RuntimeError("router exploded")
        router = APIRouter()

        @router.get("/ping")
        def ping() -> dict[str, str]:
            return {"pack": pack_name}

        return router

    cli_app = typer.Typer()

    @cli_app.command("ping")
    def ping_cli() -> None:
        typer.echo(f"{pack_name}-cli")

    module.__dict__["build_router"] = build_router
    module.__dict__["cli_app"] = cli_app
    module.__dict__["PACK_MANIFEST"] = {
        "name": pack_name,
        "version": version,
        "requires_license": requires_license,
        "api_router_factory": f"{module_name}.build_router",
        "cli_app": f"{module_name}.cli_app",
    }
    sys.modules[module_name] = module


def _write_pack_tarball(
    directory: Path,
    members: dict[str, bytes],
    *,
    filename: str = "wait-pack-demo-1.0.0.tar.gz",
) -> Path:
    tarball = directory / filename
    manifest = {
        "name": "demo",
        "version": "1.0.0",
        "requires_license": False,
        "api_router_factory": None,
        "cli_app": None,
    }
    digests = [hashlib.sha256(content).hexdigest() for content in members.values()]
    manifest["sha256"] = hashlib.sha256("".join(sorted(digests)).encode("utf-8")).hexdigest()
    with tarfile.open(tarball, "w:gz") as archive:
        manifest_bytes = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
        manifest_info = tarfile.TarInfo("manifest.json")
        manifest_info.size = len(manifest_bytes)
        archive.addfile(manifest_info, io.BytesIO(manifest_bytes))
        for member_name, content in members.items():
            info = tarfile.TarInfo(member_name)
            info.size = len(content)
            archive.addfile(info, io.BytesIO(content))
    signature = _urlsafe_b64encode(
        hmac.new(b"signing-secret", tarball.read_bytes(), hashlib.sha256).digest()
    )
    Path(f"{tarball}.sig").write_text(signature, encoding="utf-8")
    return tarball


def _urlsafe_b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("utf-8").rstrip("=")
