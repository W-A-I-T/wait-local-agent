from __future__ import annotations

import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import cast

import pytest
from fastapi import Request
from fastapi.testclient import TestClient
from typer.testing import CliRunner

import wait_local_agent.api.app as app_module
import wait_local_agent.api.packs.loader as loader_module
import wait_local_agent.cli as cli_module
from wait_local_agent.api.app import create_app
from wait_local_agent.api.founder import (
    FounderPackContractError,
    build_upload_preview,
    ensure_list,
    json_object,
    json_value,
    previewed_artifacts,
    render_json,
    resolve_founder_member,
)
from wait_local_agent.api.packs.loader import LoadedPack, configure_pack_routes


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


def test_founder_routes_return_stable_501_without_pack(settings) -> None:
    client = TestClient(create_app(settings))

    responses = [
        client.post("/founder/scan", json={"path": "/tmp/project"}),
        client.get("/founder/vault"),
        client.get("/founder/preflight/latest"),
        client.get("/founder/upload-preview/art-1"),
        client.post("/founder/upload/art-1", json={"confirm": True}),
        client.get("/founder/lp-status"),
    ]

    for response in responses:
        assert response.status_code == 501
        assert response.json() == {"error": "founder pack not installed"}


def test_founder_cli_commands_exit_with_install_hint_without_pack(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("WAIT_DATA_PATH", str(tmp_path / "state.db"))
    cli_module.sync_pack_cli([])
    runner = CliRunner()

    commands = [
        ["founder", "scan", str(tmp_path)],
        ["founder", "preflight"],
        ["founder", "handoff", "--output", str(tmp_path / "handoff.md")],
        ["founder", "export-bundle", "--artifact-id", "art-1", "--output", str(tmp_path / "bundle.json")],
        ["founder", "upload", "--artifact-id", "art-1"],
    ]

    for command in commands:
        result = runner.invoke(cli_module.app, command)
        assert result.exit_code == 1
        assert "founder pack not installed; install the founder pack to use this command" in result.output


def test_founder_surfaces_delegate_to_fake_pack_and_enforce_preview_gating(monkeypatch, settings, tmp_path) -> None:
    monkeypatch.setenv("WAIT_DATA_PATH", str(tmp_path / "state.db"))
    monkeypatch.setenv("WAIT_LICENSE_KEY", "valid-founder-license")
    secure_settings = settings.__class__(
        **{
            **settings.__dict__,
            "demo_mode": False,
            "admin_token": "admin-token",
            "tech_token": "tech-token",
            "viewer_token": "viewer-token",
            "license_key": "valid-founder-license",
        }
    )
    candidates = _install_founder_pack()
    original_sync_pack_cli = cli_module.sync_pack_cli
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
    monkeypatch.setattr(
        cli_module,
        "sync_pack_cli",
        lambda *args, **kwargs: original_sync_pack_cli(candidates),
    )
    cli_module.sync_pack_cli(candidates)
    client = TestClient(create_app(secure_settings))
    runner = CliRunner()
    output_dir = tmp_path / "out"

    scan = client.post("/founder/scan", json={"path": str(tmp_path)}, headers=_auth("admin-token"))
    vault = client.get("/founder/vault", headers=_auth("admin-token"))
    preflight = client.get("/founder/preflight/latest", headers=_auth("admin-token"))
    lp_status = client.get("/founder/lp-status", headers=_auth("admin-token"))
    forbidden_viewer = client.get("/founder/vault", headers=_auth("viewer-token"))
    forbidden_technician = client.get("/founder/vault", headers=_auth("tech-token"))
    upload_without_preview = client.post(
        "/founder/upload/art-1",
        json={"confirm": True},
        headers=_auth("admin-token"),
    )
    upload_without_confirm = client.post(
        "/founder/upload/art-1",
        json={"confirm": False},
        headers=_auth("admin-token"),
    )
    preview = client.get("/founder/upload-preview/art-1", headers=_auth("admin-token"))
    upload = client.post(
        "/founder/upload/art-1",
        json={"confirm": True},
        headers=_auth("admin-token"),
    )
    other_upload = client.post(
        "/founder/upload/art-2",
        json={"confirm": True},
        headers=_auth("admin-token"),
    )

    doctor = runner.invoke(cli_module.app, ["doctor"])
    handoff = runner.invoke(
        cli_module.app,
        ["founder", "handoff", "--output", str(output_dir / "handoff.md")],
    )
    export_bundle = runner.invoke(
        cli_module.app,
        ["founder", "export-bundle", "--artifact-id", "art-1", "--output", str(output_dir / "bundle.json")],
    )
    cli_scan = runner.invoke(cli_module.app, ["founder", "scan", str(tmp_path)])
    cli_preflight = runner.invoke(cli_module.app, ["founder", "preflight"])
    cli_upload_confirm = runner.invoke(
        cli_module.app,
        ["founder", "upload", "--artifact-id", "art-1", "--yes"],
    )
    cli_upload_without_yes = runner.invoke(
        cli_module.app,
        ["founder", "upload", "--artifact-id", "art-1"],
    )

    assert scan.status_code == 200
    assert scan.json()["artifact_id"] == "art-1"
    assert vault.status_code == 200
    assert vault.json()["artifacts"] == [{"artifact_id": "art-1"}]
    assert preflight.status_code == 200
    assert preflight.json()["status"] == "ready"
    assert lp_status.status_code == 200
    assert lp_status.json()["status"] == "ready"
    assert forbidden_viewer.status_code == 403
    assert forbidden_technician.status_code == 403
    assert upload_without_preview.status_code == 409
    assert upload_without_confirm.status_code == 400
    assert preview.status_code == 200
    assert preview.json() == {
        "artifact_id": "art-1",
        "schema_version": "1.0",
        "project_name": "fixture-project",
        "file_count": 2,
        "manifest_count": 2,
        "route_count": 2,
        "env_key_names": ["WAIT_API_TOKEN", "WAIT_DB_URL"],
        "finding_types": ["auth", "secret"],
    }
    assert "file_body" not in preview.text
    assert "hunter2" not in preview.text
    assert upload.status_code == 200
    assert upload.json() == {"artifact_id": "art-1", "status": "uploaded"}
    assert other_upload.status_code == 409

    assert doctor.exit_code == 0
    assert "founder_lp_status=ready" in doctor.output
    assert handoff.exit_code == 0
    assert (output_dir / "handoff.md").read_text(encoding="utf-8") == "# Founder Handoff\n"
    assert export_bundle.exit_code == 0
    bundle_text = (output_dir / "bundle.json").read_text(encoding="utf-8")
    assert '"artifact_id": "art-1"' not in bundle_text
    assert '"project_name": "fixture-project"' in bundle_text
    assert cli_scan.exit_code == 0
    assert '"artifact_id": "art-1"' in cli_scan.output
    assert cli_preflight.exit_code == 0
    assert '"status": "ready"' in cli_preflight.output
    assert cli_upload_confirm.exit_code == 0
    assert '"status": "uploaded"' in cli_upload_confirm.output
    assert '"env_key_names": [' in cli_upload_confirm.output
    assert cli_upload_without_yes.exit_code == 1
    assert "re-run with --yes to confirm upload" in cli_upload_without_yes.output


def test_founder_helper_branches_raise_clear_contract_errors() -> None:
    module = ModuleType("packs.founder")
    pack = LoadedPack(manifest={"name": "founder"}, module=module)

    with pytest.raises(FounderPackContractError, match="missing upload"):
        resolve_founder_member(pack, "upload")
    with pytest.raises(FounderPackContractError, match="must return an object"):
        json_object(["not", "an", "object"], operation="scan")
    with pytest.raises(FounderPackContractError, match="unsupported type complex"):
        json_value(1 + 2j, operation="scan")
    with pytest.raises(FounderPackContractError, match="env_keys entries must be strings"):
        build_upload_preview("art-1", {"file_tree": [], "manifests": [], "routes": [], "env_keys": [1], "findings": []})
    with pytest.raises(FounderPackContractError, match="findings entries must be objects"):
        build_upload_preview(
            "art-1",
            {"file_tree": [], "manifests": [], "routes": [], "env_keys": [], "findings": ["bad"]},
        )
    with pytest.raises(FounderPackContractError, match="file_tree must be a list"):
        ensure_list("bad", key="file_tree")


def test_founder_helper_serialization_and_preview_cache_cover_dataclass_path_and_tuple() -> None:
    @dataclass
    class Payload:
        artifact_id: str
        path: Path

    value = json_value(
        {
            "payload": Payload("art-1", Path("demo")),
            "items": (Path("alpha"), "beta"),
        },
        operation="scan",
    )

    assert value == {
        "payload": {"artifact_id": "art-1", "path": "demo"},
        "items": ["alpha", "beta"],
    }
    assert render_json({"value": Path("demo")}) == '{\n  "value": "demo"\n}'
    request = cast(Request, SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace())))

    first = previewed_artifacts(request)
    second = previewed_artifacts(request)

    assert first is second
    assert first == set()


def test_founder_cli_edge_branches_cover_contract_and_json_status(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("WAIT_DATA_PATH", str(tmp_path / "state.db"))
    monkeypatch.setattr(
        cli_module,
        "_invoke_founder_cli",
        lambda operation, *args: {"status": 1} if operation == "lp_status" else {"markdown": True},
    )
    runner = CliRunner()

    handoff = runner.invoke(
        cli_module.app,
        ["founder", "handoff", "--output", str(tmp_path / "handoff.json")],
    )

    assert handoff.exit_code == 0
    assert (tmp_path / "handoff.json").read_text(encoding="utf-8") == '{\n  "markdown": true\n}\n'

    module = ModuleType("packs.founder")
    pack = LoadedPack(manifest={"name": "founder"}, module=module)
    monkeypatch.setattr(cli_module, "require_founder_pack", lambda: pack)
    monkeypatch.setattr(cli_module, "invoke_founder", lambda _pack, _operation: {"status": 1})

    assert cli_module._doctor_founder_lp_status() == '{"status": 1}'

    monkeypatch.setattr(
        cli_module,
        "_invoke_founder_cli",
        lambda _operation, *_args: ["bad"],
    )
    bad_preflight = runner.invoke(cli_module.app, ["founder", "preflight"])

    assert bad_preflight.exit_code != 0
    assert isinstance(bad_preflight.exception, FounderPackContractError)
    assert "must return an object" in str(bad_preflight.exception)


def test_founder_doctor_contract_error_branch() -> None:
    module = ModuleType("packs.founder")
    module.__dict__["PACK_MANIFEST"] = {"name": "founder"}
    pack = LoadedPack(manifest={"name": "founder"}, module=module)
    original_require = cli_module.require_founder_pack

    try:
        cli_module.require_founder_pack = lambda: pack
        assert cli_module._doctor_founder_lp_status() == "contract_error"
    finally:
        cli_module.require_founder_pack = original_require

def _install_founder_pack() -> list[str]:
    _install_package("packs")
    _install_package("packs.license")
    _install_license_module()
    module = ModuleType("packs.founder")

    def scan_path(path: Path) -> dict[str, object]:
        return {"artifact_id": "art-1", "path": str(path)}

    def list_vault() -> dict[str, object]:
        return {"artifacts": [{"artifact_id": "art-1"}]}

    def get_latest_preflight() -> dict[str, object]:
        return {"status": "ready", "score": 92}

    def generate_handoff() -> str:
        return "# Founder Handoff\n"

    def export_bundle(artifact_id: str) -> dict[str, object]:
        assert artifact_id in {"art-1", "art-2"}
        return {
            "schema_version": "1.0",
            "generated_at": "2026-07-08T00:00:00Z",
            "project_name": "fixture-project",
            "sourceCode": False,
            "file_tree": [
                {"path": "src/app.py", "size_bytes": 10},
                {"path": "README.md", "size_bytes": 20},
            ],
            "manifests": [
                {"path": "package.json", "kind": "npm", "dependency_names": ["react"]},
                {"path": "pyproject.toml", "kind": "pip", "dependency_names": ["fastapi"]},
            ],
            "ci": {"present": True, "workflow_count": 1, "workflow_paths": [".github/workflows/test.yml"]},
            "tests": {"framework_hints": ["pytest"], "test_file_count": 4},
            "routes": [
                {"pattern": "/health", "source_path": "src/api.py"},
                {"pattern": "/tickets", "source_path": "src/api.py"},
            ],
            "env_keys": ["WAIT_API_TOKEN", "WAIT_DB_URL"],
            "findings": [
                {"type": "secret", "path": ".env.example", "severity": "medium"},
                {"type": "auth", "path": "src/auth.py", "severity": "high"},
            ],
            "content_hash": "abc123",
            "file_body": "hunter2",
        }

    def upload_bundle(artifact_id: str) -> dict[str, object]:
        return {"artifact_id": artifact_id, "status": "uploaded"}

    def get_lp_status() -> dict[str, object]:
        return {"status": "ready", "base_url": "https://lp.example.test"}

    module.__dict__["scan_path"] = scan_path
    module.__dict__["list_vault"] = list_vault
    module.__dict__["get_latest_preflight"] = get_latest_preflight
    module.__dict__["generate_handoff"] = generate_handoff
    module.__dict__["export_bundle"] = export_bundle
    module.__dict__["upload_bundle"] = upload_bundle
    module.__dict__["get_lp_status"] = get_lp_status
    module.__dict__["PACK_MANIFEST"] = {
        "name": "founder",
        "version": "1.0.0",
        "requires_license": True,
        "api_router_factory": None,
        "cli_app": None,
    }
    sys.modules["packs.founder"] = module
    return ["packs.founder"]


def _install_package(name: str) -> None:
    module = ModuleType(name)
    module.__dict__["__path__"] = []
    sys.modules[name] = module


def _install_license_module() -> None:
    module = ModuleType("packs.license.keys")

    def pack_enabled(pack_name: str, license_key: str | None) -> bool:
        return bool(license_key) and license_key == f"valid-{pack_name}-license"

    module.pack_enabled = pack_enabled  # type: ignore[attr-defined]
    sys.modules["packs.license.keys"] = module


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
