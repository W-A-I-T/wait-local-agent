from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, cast

import httpx
import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from typer.testing import CliRunner

import wait_local_agent.api.founder as founder_module
import wait_local_agent.cli as cli_module
import wait_local_agent.founder_bundle as bundle_module
from wait_local_agent.api.app import create_app
from wait_local_agent.api.founder import (
    FounderNotConfiguredError,
    FounderPackContractError,
    FounderPackUnavailableError,
    FounderUploadConflictError,
    build_upload_preview,
    json_object,
    json_value,
    require_fresh_preview,
    resolve_founder_member,
    resolve_open_config,
)
from wait_local_agent.api.packs.loader import LoadedPack
from wait_local_agent.founder_bundle import (
    PrivacyViolation,
    build_founder_bundle,
    compute_bundle_delta,
    sanitize_bundle,
)
from wait_local_agent.lp_client import (
    LaunchPassportClient,
    LaunchPassportForbidden,
    LaunchPassportPayloadTooLarge,
    LaunchPassportRequestError,
    LaunchPassportUnauthorized,
)
from wait_local_agent.store import Store
from wait_local_agent.vault import SecretVaultError


def test_unconfigured_open_routes_return_clear_optional_state(settings) -> None:
    client = TestClient(create_app(settings))

    responses = [
        client.post("/founder/scan", json={"path": "/tmp/project"}),
        client.get("/founder/vault"),
        client.get("/founder/preflight/latest"),
        client.get("/founder/upload-preview/art-1"),
        client.post("/founder/upload/art-1", json={"confirm": True}),
        client.get("/founder/lp-status"),
        client.get("/founder/results"),
    ]

    for response in responses:
        assert response.status_code == 409
        assert response.json()["error"] == "launch passport not configured"


def test_open_flow_is_pack_free_and_preview_gated(monkeypatch, settings, tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "src").mkdir()
    (project / "src" / "main.py").write_text("private source", encoding="utf-8")
    (project / ".env.example").write_text("DATABASE_URL=example-value\nPUBLIC_NAME=ok\n", encoding="utf-8")
    (project / "package.json").write_text('{"dependencies":{"httpx":"1.0"}}', encoding="utf-8")

    store = Store(settings.data_path)
    founder_module.configure_founder(settings, store, "https://lp.test", "project-1", "bearer-secret")
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "POST" and request.url.path.endswith("collector-bundle"):
            return httpx.Response(200, json={"artifact_id": "remote-1", "status": "bearer-secret"})
        if request.url.path == "/api/health":
            return httpx.Response(200, json={"capabilities": {"launch_scan": True}})
        if request.url.path.endswith("/scans"):
            return httpx.Response(200, json=[{"status": "bearer-secret", "message": "sk_live_UPSTREAM_SECRET"}])
        if request.url.path.endswith("/reports/latest"):
            return httpx.Response(200, json={"message": "bearer-secret"})
        return httpx.Response(200, json=[])

    transport_client = LaunchPassportClient(
        "https://lp.test",
        lambda: "bearer-secret",
        transport=httpx.MockTransport(handler),
    )
    monkeypatch.setattr(founder_module, "_open_client", lambda _settings, _config: transport_client)
    client = TestClient(create_app(settings))

    scan = client.post("/founder/scan", json={"path": str(project)})
    artifact_id = scan.json()["artifact_id"]
    assert scan.status_code == 200
    assert scan.json()["status"] == "preview_ready"

    blocked = client.post(f"/founder/upload/{artifact_id}", json={"confirm": True})
    assert blocked.status_code == 409

    preview = client.get(f"/founder/upload-preview/{artifact_id}")
    assert preview.status_code == 200
    assert preview.json()["sourceCode"] is False
    assert preview.json()["env_key_names"] == ["DATABASE_URL", "PUBLIC_NAME"]

    uploaded = client.post(f"/founder/upload/{artifact_id}", json={"confirm": True})
    assert uploaded.status_code == 200
    assert uploaded.json()["status"] == "unknown"
    assert "bearer-secret" not in uploaded.text
    wire = json.loads(requests[0].content)
    assert wire["metadata"]["sourceCode"] is False
    assert "private source" not in json.dumps(wire)
    assert "bearer-secret" not in json.dumps(wire)
    results = client.get("/founder/results")
    assert results.status_code == 200
    assert "bearer-secret" not in results.text
    assert "sk_live_UPSTREAM_SECRET" not in results.text
    assert results.json()["scans"] == {"count": 1, "states": ["unknown"]}
    transport_client.close()


def test_founder_api_projections_redact_token_and_close_upstream_states() -> None:
    token = "launch-passport-token"
    upload = founder_module.project_founder_upload(
        {"status": token, "message": token, "secret": "sk_live_UPSTREAM_SECRET"}, token=token
    )
    results = founder_module.project_founder_results(
        {
            "scans": [{"state": token, "message": token}],
            "latest_report": {"message": token},
        },
        token=token,
    )
    body = json.dumps({"upload": upload, "results": results})

    assert upload["status"] == "unknown"
    assert results["scans"] == {"count": 1, "states": ["unknown"]}
    assert token not in body
    assert "sk_live_UPSTREAM_SECRET" not in body


def test_founder_projection_contract_and_shape_edges(monkeypatch) -> None:
    with monkeypatch.context() as isolated:
        isolated.setattr(founder_module, "scrub_upstream_value", lambda *_args, **_kwargs: "scalar")
        with pytest.raises(FounderPackContractError, match="scan must return an object"):
            founder_module.project_founder_scan({})
        with pytest.raises(FounderPackContractError, match="upload must return an object"):
            founder_module.project_founder_upload({})

    assert founder_module.project_founder_scan(
        {
            "status": "completed",
            "artifactId": "artifact-1",
            "projectId": "project-1",
            "file_count": 3,
            "dependency_count": 0,
            "env_key_count": 2,
            "ignored": -1,
        }
    ) == {
        "status": "completed",
        "artifact_id": "artifact-1",
        "project_id": "project-1",
        "file_count": 3,
        "dependency_count": 0,
        "env_key_count": 2,
    }
    assert founder_module.project_founder_status({"status": "connected"}) == {
        "status": "connected",
        "token_configured": True,
        "capabilities": {},
    }
    assert founder_module.project_founder_results(
        {"scans": {"items": [], "count": -4}, "latest_report": []}
    ) == {
        "scans": {"count": 0, "states": []},
        "latest_report": {"available": False},
    }


def test_pack_status_passthrough_does_not_bypass_http_projection(monkeypatch, settings) -> None:
    module = ModuleType("packs.founder")
    pack_status = {
        "status": "connected",
        "capabilities": {"pack_only": True},
        "token_configured": True,
    }
    module.get_lp_status = lambda: pack_status  # type: ignore[attr-defined]
    pack = LoadedPack(manifest={"name": "founder"}, module=module)
    monkeypatch.setattr(founder_module, "get_pack", lambda name: pack if name == "founder" else None)
    application = FastAPI()
    application.state.settings = settings
    application.state.store = Store(settings.data_path)
    request = Request(
        {"type": "http", "method": "GET", "path": "/", "headers": [], "query_string": b"", "app": application}
    )
    endpoints = {
        route.path: route.endpoint
        for route in founder_module.create_router().routes
        if isinstance(route, APIRoute)
    }

    assert endpoints["/founder/lp-status"](request, None) == pack_status
    assert founder_module.project_founder_status(
        {"status": "not-a-real-state", "capabilities": {"pack_only": True}},
        project_id="project-1",
    ) == {
        "status": "unknown",
        "token_configured": True,
        "capabilities": {},
        "lp_project_id": "project-1",
    }


def test_configuration_stores_token_only_in_encrypted_vault(settings) -> None:
    store = Store(settings.data_path)
    result = founder_module.configure_founder(settings, store, "https://lp.test/", "project-1", "top-secret-token")
    config = store.get_founder_config()
    assert result["token_stored_in_vault"] is True
    assert config is not None
    assert config["token_vault_ref"] != "top-secret-token"
    assert b"top-secret-token" not in settings.data_path.read_bytes()
    assert settings.vault_path.joinpath("secrets.json.enc").read_bytes().find(b"top-secret-token") == -1


def test_configure_cli_prefers_hidden_prompt(monkeypatch, settings, tmp_path: Path) -> None:
    captured: dict[str, str] = {}
    monkeypatch.setattr(cli_module, "load_settings", lambda: settings)
    monkeypatch.setattr(cli_module, "_store", lambda: Store(tmp_path / "cli-state.db"))

    def fake_configure(_settings, _store, base_url, project_id, token):
        captured.update(base_url=base_url, project_id=project_id, token=token)
        return {"status": "configured"}

    monkeypatch.setattr(cli_module, "configure_founder", fake_configure)
    result = CliRunner().invoke(
        cli_module.app,
        ["founder", "configure", "--base-url", "https://lp.test", "--project-id", "project-1"],
        input="prompt-token\n",
    )

    assert result.exit_code == 0
    assert captured["token"] == "prompt-token"


def test_configure_rejects_credential_bearing_base_url(settings) -> None:
    with pytest.raises(ValueError, match="embedded credentials"):
        founder_module.configure_founder(
            settings,
            Store(settings.data_path),
            "https://user:pass@lp.test",
            "project-1",
            "t",
        )


@pytest.mark.parametrize(
    ("project_id", "token", "message"),
    [("", "token", "path segment"), ("project/id", "token", "path segment"), ("project", "", "must not be empty")],
)
def test_configure_rejects_invalid_project_and_token(settings, project_id, token, message) -> None:
    with pytest.raises(ValueError, match=message):
        founder_module.configure_founder(settings, Store(settings.data_path), "https://lp.test", project_id, token)


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"metadata": {"sourceCode": True}}, "sourceCode"),
        ({"metadata": {"secret_value": "hidden"}}, "private value"),
        ({"environment": {"keys": ["DB_URL"], "values": {"DB_URL": "hidden"}}}, "environment"),
        ({"connector_credentials": {"api_key": "hidden"}}, "private value"),
    ],
)
def test_privacy_gates_reject_each_forbidden_input(payload, message) -> None:
    with pytest.raises(PrivacyViolation, match=message):
        sanitize_bundle(payload)


def test_bundle_builder_uses_hashes_and_never_file_contents(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("private source", encoding="utf-8")
    (tmp_path / ".env").write_text("SECRET_VALUE=hidden", encoding="utf-8")
    bundle = build_founder_bundle(tmp_path)
    serialized = json.dumps(bundle)
    assert "private source" not in serialized
    assert "hidden" not in serialized
    assert bundle["metadata"]["sourceCode"] is False
    assert bundle["schemaVersion"] == "collector_bundle_v1"
    assert bundle["files"][0] == {"path": "app.py", "ext": ".py", "sizeBytes": len("private source")}
    assert len(bundle["hashes"][0]["sha256"]) == 64
    assert isinstance(bundle["dependencies"], dict)
    assert isinstance(bundle["findings"], dict)
    assert bundle["environment"]["keys"] == {}


def test_compute_bundle_delta_is_deterministic_and_tracks_module_changes() -> None:
    previous = {
        "dependencies": {"productionDependencies": ["zeta", "same", "removed"]},
        "manifests": [{"path": "z.json", "sha256": "old-z"}, {"path": "same.json", "sha256": "same"}],
        "hashes": [{"path": "z.py", "sha256": "old-z"}, {"path": "same.py", "sha256": "same"}],
    }
    current = {
        "dependencies": {"productionDependencies": ["same", "added"]},
        "manifests": [{"path": "same.json", "sha256": "same"}, {"path": "z.json", "sha256": "new-z"}],
        "hashes": [{"path": "same.py", "sha256": "same"}, {"path": "added.py", "sha256": "new-a"}],
    }
    shuffled = {
        "dependencies": {"productionDependencies": ["added", "same"]},
        "manifests": [{"sha256": "same", "path": "same.json"}, {"sha256": "new-z", "path": "z.json"}],
        "hashes": [{"sha256": "new-a", "path": "added.py"}, {"sha256": "same", "path": "same.py"}],
    }
    delta = compute_bundle_delta(previous, current)
    assert delta == compute_bundle_delta(previous, shuffled)
    assert delta["modules"]["dependencies"] == {
        "added": ["added"], "removed": ["removed", "zeta"], "changed": [], "unknown": [], "unchanged_count": 1
    }
    assert delta["modules"]["manifests"]["changed"] == [{"subject": "z.json", "from": "old-z", "to": "new-z"}]
    assert delta["modules"]["files"]["added"] == ["added.py"]
    assert delta["modules"]["files"]["removed"] == ["z.py"]
    assert delta["modules"]["files"]["unchanged_count"] == 1
    assert delta["counts"] == {"added": 2, "removed": 3, "changed": 1, "unknown": 0}


def test_compute_bundle_delta_first_scan_and_unknown_modules() -> None:
    first = compute_bundle_delta(None, {"dependencies": {"productionDependencies": ["new"]}})
    assert first["first_scan"] is True
    assert all(module["added"] == [] and module["unchanged_count"] == 0 for module in first["modules"].values())

    unknown = compute_bundle_delta(
        {
            "dependencies": {"productionDependencies": ["dep"]},
            "manifests": [{"path": "a", "sha256": "1"}],
            "hashes": [{"path": "a", "sha256": "1"}],
        },
        {"dependencies": {"productionDependencies": []}, "manifests": [], "hashes": []},
    )
    unknown_modules = cast(dict[str, dict[str, Any]], unknown["modules"])
    assert unknown_modules["dependencies"]["unknown"] == ["dep"]
    assert unknown_modules["manifests"]["unknown"] == ["a"]
    assert unknown_modules["files"]["unknown"] == ["a"]
    assert unknown["counts"] == {"added": 0, "removed": 0, "changed": 0, "unknown": 3}


def test_open_founder_scan_returns_delta_and_predecessor(settings, tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    target = project / "app.py"
    target.write_text("one", encoding="utf-8")
    store = Store(settings.data_path)
    config = {"lp_project_id": "project-1"}

    first = founder_module.open_founder_scan(store, settings, config, project)
    assert first["predecessor"] is None
    first_delta = cast(dict[str, Any], first["delta"])
    assert first_delta["first_scan"] is True
    target.write_text("two", encoding="utf-8")
    second = founder_module.open_founder_scan(store, settings, config, project)
    predecessor = cast(dict[str, str], second["predecessor"])
    assert predecessor["artifact_id"] == first["artifact_id"]
    assert predecessor["bundle_hash"] == first["bundle_hash"]
    second_delta = cast(dict[str, Any], second["delta"])
    assert second_delta["first_scan"] is False
    assert cast(dict[str, Any], second_delta["modules"])["files"]["changed"]


def test_sanitize_bundle_scrubs_finding_text_and_dependency_url_credentials() -> None:
    sanitized = sanitize_bundle(
        {
            "findings": [
                {
                    "message": "stripe sk_live_SUPERSECRET",
                    "description": "Authorization: Bearer very-secret-token",
                    "file": "config/password=hunter2",
                }
            ],
            "dependencies": {
                "productionDependencies": ["git+https://user:password@example.test/repo.git"],
            },
            "files": [{"path": "docs/api_key=FILESECRET.txt", "ext": ".txt", "sizeBytes": 1}],
        }
    )
    wire = json.dumps(sanitized)
    assert "sk_live_SUPERSECRET" not in wire
    assert "very-secret-token" not in wire
    assert "hunter2" not in wire
    assert "FILESECRET" not in wire
    assert "user:password@" not in wire
    assert sanitized["dependencies"]["productionDependencies"] == ["git+https://example.test/repo.git"]


def test_sanitize_bundle_scrubs_aws_access_key_in_finding_text() -> None:
    sanitized = sanitize_bundle({"findings": [{"message": "AWS key AKIA1234567890123456"}]})

    assert "AKIA1234567890123456" not in json.dumps(sanitized)


def test_builder_emits_environment_key_map_and_structured_findings(tmp_path: Path) -> None:
    (tmp_path / ".env.example").write_text("DATABASE_URL=example\nPUBLIC_NAME=ok\n", encoding="utf-8")
    bundle = build_founder_bundle(tmp_path, findings=[{"type": "warning", "message": "safe"}])

    assert bundle["environment"]["keys"] == {".env.example": ["DATABASE_URL", "PUBLIC_NAME"]}
    assert bundle["environment"]["entries"] == [
        {"file": ".env.example", "keyNames": ["DATABASE_URL", "PUBLIC_NAME"]}
    ]
    assert bundle["findings"]["items"] == [{"type": "warning", "message": "safe"}]


def test_pack_bundle_boundary_sanitizes_before_delegated_upload(monkeypatch) -> None:
    module = ModuleType("packs.founder")
    module.export_bundle = lambda artifact_id: {  # type: ignore[attr-defined]
        "findings": [{"message": "sk_live_PACK_SECRET"}],
    }
    pack = LoadedPack(manifest={"name": "founder"}, module=module)
    calls: list[dict[str, object]] = []
    original = founder_module.sanitize_bundle

    def spy(bundle):
        calls.append(bundle)
        return original(bundle)

    monkeypatch.setattr(founder_module, "sanitize_bundle", spy)

    sanitized = founder_module.sanitized_pack_bundle(pack, "artifact-1")

    assert calls
    assert "sk_live_PACK_SECRET" not in json.dumps(sanitized)


def test_pack_upload_receives_sanitized_bundle_only() -> None:
    module = ModuleType("packs.founder")
    received: dict[str, object] = {}

    module.export_bundle = lambda artifact_id: {  # type: ignore[attr-defined]
        "findings": [{"message": "sk_live_PACK_SECRET"}],
    }

    def upload(artifact_id, bundle):
        received.update(artifact_id=artifact_id, bundle=bundle)
        return {"status": "uploaded"}

    module.upload = upload  # type: ignore[attr-defined]
    pack = LoadedPack(manifest={"name": "founder"}, module=module)
    bundle = founder_module.sanitized_pack_bundle(pack, "artifact-1")

    response = founder_module.json_object(
        founder_module.invoke_founder(pack, "upload", "artifact-1", bundle),
        operation="upload",
    )

    assert response["status"] == "uploaded"
    assert received["artifact_id"] == "artifact-1"
    assert "sk_live_PACK_SECRET" not in json.dumps(received["bundle"])


def test_preview_marker_is_persisted_and_stale_markers_conflict(settings) -> None:
    store = Store(settings.data_path)
    store.mark_founder_artifact_previewed("pack-artifact")
    second_store = Store(settings.data_path)
    assert second_store.get_founder_artifact_previewed_at("pack-artifact")
    with pytest.raises(FounderUploadConflictError, match="preview"):
        founder_module.require_fresh_preview(second_store, "missing-artifact")
    with second_store._connect() as connection:  # noqa: SLF001
        connection.execute(
            "update founder_artifact_previews set previewed_at = ? where artifact_id = ?",
            ("2000-01-01T00:00:00+00:00", "pack-artifact"),
        )
    with pytest.raises(FounderUploadConflictError, match="stale"):
        founder_module.require_fresh_preview(second_store, "pack-artifact")


def test_cross_project_upload_is_rejected_before_network(settings, monkeypatch) -> None:
    store = Store(settings.data_path)
    founder_module.configure_founder(settings, store, "https://lp.test", "project-B", "vault-token")
    bundle = sanitize_bundle({"metadata": {"sourceCode": False}})
    store.save_founder_artifact(
        artifact_id="artifact-project-a",
        project_id="project-A",
        bundle_hash=founder_module.bundle_hash(bundle),
        bundle=bundle,
    )
    store.mark_founder_artifact_previewed("artifact-project-a")
    monkeypatch.setattr(founder_module, "_open_client", lambda *_args: pytest.fail("network must not be reached"))

    with pytest.raises(FounderUploadConflictError, match="project"):
        founder_module.open_founder_upload(settings, store, store.get_founder_config() or {}, "artifact-project-a")


def test_pack_behavior_takes_precedence(monkeypatch, settings) -> None:
    module = ModuleType("packs.founder")
    module.scan = lambda path: {"source": str(path), "status": "pack"}  # type: ignore[attr-defined]
    pack = LoadedPack(manifest={"name": "founder"}, module=module)
    monkeypatch.setattr(founder_module, "get_pack", lambda name: pack if name == "founder" else None)
    client = TestClient(create_app(settings))
    response = client.post("/founder/scan", json={"path": "/tmp/project"})
    assert response.status_code == 200
    assert response.json()["status"] == "unknown"


def test_pack_founder_routes_cover_delegated_operations_and_errors(monkeypatch, settings) -> None:
    module = ModuleType("packs.founder")
    module.scan = lambda path: {"status": "pack", "path": str(path)}  # type: ignore[attr-defined]
    module.list_vault = lambda: ["vault-entry"]  # type: ignore[attr-defined]
    module.get_latest_preflight = lambda: {"status": "ready"}  # type: ignore[attr-defined]
    module.export_bundle = lambda artifact_id: {  # type: ignore[attr-defined]
        "files": ["app.py"],
        "manifests": [],
        "routes": [],
        "env_keys": ["PUBLIC_NAME"],
        "findings": [{"type": "warning"}],
        "artifact_id": artifact_id,
    }
    module.upload = (  # type: ignore[attr-defined]
        lambda artifact_id, bundle: {"status": "uploaded", "artifact_id": artifact_id}
    )
    module.get_lp_status = lambda: {"status": "connected"}  # type: ignore[attr-defined]
    module.get_results = lambda: {"results": ["report-1"]}  # type: ignore[attr-defined]
    pack = LoadedPack(manifest={"name": "founder"}, module=module)
    monkeypatch.setattr(founder_module, "get_pack", lambda name: pack if name == "founder" else None)
    router = founder_module.create_router()
    endpoints = {route.path: route.endpoint for route in router.routes if isinstance(route, APIRoute)}
    application = FastAPI()
    application.state.settings = settings
    application.state.store = Store(settings.data_path)
    request = Request(
        {"type": "http", "method": "GET", "path": "/", "headers": [], "query_string": b"", "app": application}
    )

    assert endpoints["/founder/vault"](request, None) == ["vault-entry"]
    assert endpoints["/founder/preflight/latest"](request, None) == {"status": "ready"}
    preview = endpoints["/founder/upload-preview/{artifact_id}"]("pack-artifact", request, None)
    assert preview["artifact_id"] == "pack-artifact"
    with pytest.raises(HTTPException) as not_confirmed:
        endpoints["/founder/upload/{artifact_id}"](
            "pack-artifact", founder_module.FounderUploadRequest(confirm=False), request, None
        )
    assert not_confirmed.value.status_code == 400
    uploaded = endpoints["/founder/upload/{artifact_id}"](
        "pack-artifact", founder_module.FounderUploadRequest(confirm=True), request, None
    )
    assert uploaded["status"] == "uploaded"
    assert endpoints["/founder/lp-status"](request, None) == {"status": "connected"}
    assert endpoints["/founder/results"](request, None) == {
        "scans": {"count": 0, "states": []},
        "latest_report": {"available": False},
    }

    monkeypatch.setattr(founder_module, "get_pack", lambda _name: None)
    configured_store = application.state.store
    founder_module.configure_founder(settings, configured_store, "https://lp.test", "project-1", "token")
    with pytest.raises(HTTPException, match="artifact not found"):
        endpoints["/founder/upload-preview/{artifact_id}"]("missing", request, None)
    with pytest.raises(HTTPException, match="artifact not found"):
        endpoints["/founder/upload/{artifact_id}"](
            "missing", founder_module.FounderUploadRequest(confirm=True), request, None
        )


def test_founder_cli_covers_pack_and_open_command_paths(monkeypatch, settings, tmp_path: Path) -> None:
    module = ModuleType("packs.founder")
    module.scan = lambda path: {"status": "pack", "path": str(path)}  # type: ignore[attr-defined]
    module.get_latest_preflight = lambda: {"status": "ready"}  # type: ignore[attr-defined]
    module.generate_handoff = lambda: "handoff text"  # type: ignore[attr-defined]
    module.export_bundle = lambda artifact_id: {  # type: ignore[attr-defined]
        "files": ["app.py"], "manifests": [], "routes": [], "env_keys": [], "findings": [], "artifact_id": artifact_id
    }
    module.upload = (  # type: ignore[attr-defined]
        lambda artifact_id, bundle: {"status": "uploaded", "artifact_id": artifact_id}
    )
    module.get_lp_status = lambda: {"status": "connected"}  # type: ignore[attr-defined]
    module.get_results = lambda: {"results": ["report-1"]}  # type: ignore[attr-defined]
    pack = LoadedPack(manifest={"name": "founder"}, module=module)
    runner = CliRunner()
    store = Store(tmp_path / "cli.db")
    monkeypatch.setattr(cli_module, "require_founder_pack", lambda: pack)
    monkeypatch.setattr(cli_module, "load_settings", lambda: settings)
    monkeypatch.setattr(cli_module, "_store", lambda: store)

    assert runner.invoke(cli_module.app, ["founder", "scan", str(tmp_path)]).exit_code == 0
    assert runner.invoke(cli_module.app, ["founder", "preflight"]).exit_code == 0
    handoff_path = tmp_path / "nested" / "handoff.txt"
    handoff = runner.invoke(cli_module.app, ["founder", "handoff", "--output", str(handoff_path)])
    assert handoff.exit_code == 0 and handoff_path.read_text(encoding="utf-8") == "handoff text"
    bundle_path = tmp_path / "bundle.json"
    exported = runner.invoke(
        cli_module.app, ["founder", "export-bundle", "--artifact-id", "a1", "--output", str(bundle_path)]
    )
    assert exported.exit_code == 0 and bundle_path.exists()
    preview_upload = runner.invoke(cli_module.app, ["founder", "upload", "--artifact-id", "a1"])
    assert preview_upload.exit_code == 1 and "re-run with --yes" in preview_upload.output
    store.mark_founder_artifact_previewed("a1")
    uploaded = runner.invoke(cli_module.app, ["founder", "upload", "--artifact-id", "a1", "--yes"])
    assert uploaded.exit_code == 0 and '"status": "uploaded"' in uploaded.output
    assert runner.invoke(cli_module.app, ["founder", "status"]).exit_code == 0
    assert runner.invoke(cli_module.app, ["founder", "results"]).exit_code == 0

    monkeypatch.setattr(cli_module, "_founder_pack_or_none", lambda: None)
    monkeypatch.setattr(cli_module, "_open_cli_config", lambda: (settings, store, {"lp_project_id": "p"}))
    monkeypatch.setattr(cli_module, "open_founder_scan", lambda *_args: {"status": "preview_ready"})
    monkeypatch.setattr(cli_module, "open_founder_status", lambda *_args: {"status": "connected"})
    monkeypatch.setattr(cli_module, "open_founder_results", lambda *_args: {"results": []})
    monkeypatch.setattr(cli_module, "open_founder_upload", lambda *_args: {"status": "uploaded"})
    monkeypatch.setattr(cli_module, "open_founder_preview", lambda *_args: {"artifact_id": "a2"})
    assert runner.invoke(cli_module.app, ["founder", "scan", str(tmp_path)]).exit_code == 0
    assert runner.invoke(cli_module.app, ["founder", "preview", "a2"]).exit_code == 0
    assert runner.invoke(cli_module.app, ["founder", "status"]).exit_code == 0
    assert runner.invoke(cli_module.app, ["founder", "results"]).exit_code == 0
    assert runner.invoke(cli_module.app, ["founder", "upload", "--artifact-id", "a2"]).exit_code == 1
    monkeypatch.setattr(cli_module, "require_fresh_preview", lambda *_args, **_kwargs: None)
    assert runner.invoke(cli_module.app, ["founder", "upload", "--artifact-id", "a2", "--yes"]).exit_code == 0

    monkeypatch.setattr(cli_module, "configure_founder", lambda *_args: (_ for _ in ()).throw(ValueError("bad config")))
    configure_error = runner.invoke(
        cli_module.app,
        ["founder", "configure", "--base-url", "https://lp.test", "--project-id", "p", "--token", "t"],
    )
    assert configure_error.exit_code != 0 and "bad config" in configure_error.output


def test_founder_cli_helpers_report_pack_and_config_errors(monkeypatch) -> None:
    monkeypatch.setattr(
        cli_module, "require_founder_pack", lambda: (_ for _ in ()).throw(FounderPackUnavailableError())
    )
    missing = CliRunner().invoke(cli_module.app, ["founder", "preflight"])
    assert missing.exit_code == 1 and "founder pack not installed" in missing.output
    monkeypatch.setattr(
        cli_module, "require_founder_pack", lambda: (_ for _ in ()).throw(FounderPackContractError("missing"))
    )
    contract = CliRunner().invoke(cli_module.app, ["founder", "preflight"])
    assert contract.exit_code != 0 and "missing" in contract.output


def test_cli_doctor_reports_optional_state_when_unconfigured(monkeypatch, settings, tmp_path: Path) -> None:
    monkeypatch.setenv("WAIT_DATA_PATH", str(tmp_path / "state.db"))
    monkeypatch.setattr(cli_module, "load_settings", lambda: settings)
    monkeypatch.setattr(cli_module, "sync_pack_cli", lambda *args, **kwargs: None)
    result = CliRunner().invoke(cli_module.app, ["doctor"])
    assert result.exit_code == 0
    assert "founder_lp_status=not_configured" in result.output


def test_bundle_builder_handles_invalid_manifests_requirements_and_skipped_files(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text("not-json", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text("[project\ndependencies = [", encoding="utf-8")
    (tmp_path / "requirements.txt").write_text("# comment\nhttpx>=1\n\n", encoding="utf-8")
    (tmp_path / ".env.example").write_text("GOOD=1\nnot-valid=2\n# ignored\nGOOD=3\n", encoding="utf-8")
    (tmp_path / ".env").write_text("SECRET=never", encoding="utf-8")
    (tmp_path / "private.key").write_text("never", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "ignored.js").write_text("ignored", encoding="utf-8")
    bundle = build_founder_bundle(tmp_path)
    assert bundle["dependencies"]["productionDependencies"] == ["httpx"]
    assert bundle["environment"]["keys"] == {".env.example": ["GOOD"]}
    assert all(item["path"] not in {".env", "private.key", "node_modules/ignored.js"} for item in bundle["files"])


def test_founder_bundle_handles_non_objects_and_read_failures(monkeypatch, tmp_path: Path) -> None:
    with pytest.raises(PrivacyViolation, match="object"):
        sanitize_bundle(cast(dict[str, Any], []))

    (tmp_path / "unreadable.txt").write_text("safe", encoding="utf-8")
    (tmp_path / "requirements.txt").write_text("httpx\n", encoding="utf-8")
    (tmp_path / ".env.example").write_text("PUBLIC_NAME=ok\n", encoding="utf-8")
    original_read_bytes = Path.read_bytes
    original_read_text = Path.read_text

    def fail_file_read(path: Path) -> bytes:
        if path.name == "unreadable.txt":
            raise OSError("simulated read failure")
        return original_read_bytes(path)

    def fail_metadata_read(path: Path, *args, **kwargs) -> str:
        if path.name in {"requirements.txt", ".env.example"}:
            raise OSError("simulated read failure")
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_bytes", fail_file_read)
    monkeypatch.setattr(Path, "read_text", fail_metadata_read)
    bundle = build_founder_bundle(tmp_path)
    assert all(item["path"] != "unreadable.txt" for item in bundle["files"])
    assert bundle["dependencies"]["productionDependencies"] == []
    assert bundle["environment"]["keys"] == {}


def test_founder_bundle_normalizer_rejects_privacy_and_environment_values() -> None:
    with pytest.raises(PrivacyViolation, match="privacy flags"):
        sanitize_bundle({"privacy": {"secret_values_included": True}})
    with pytest.raises(PrivacyViolation, match="environment keys"):
        sanitize_bundle({"environment": {"keys": {".env": ["not-valid-name"]}}})

    assert bundle_module._normalize_manifests(
        [{"path": "package.json", "sizeBytes": 4}, {"path": "README.md", "sha256": "abc"}], []
    ) == [
        {"path": "package.json", "kind": "manifest", "sizeBytes": 4},
        {"path": "README.md", "kind": "manifest", "sha256": "abc"},
    ]
    assert bundle_module._normalize_environment({"keys": {1: ["IGNORED"], "bad": "IGNORED"}}) == {"keys": {}}
    assert bundle_module._dependency_strings("not-a-list") == []


def test_founder_bundle_scrubs_base64_entropy_and_selects_python_manager(tmp_path: Path) -> None:
    high_entropy = "AbCdEfGhIjKlMnOpQrStUvWxYz0123456789+/=="
    sanitized = sanitize_bundle({"findings": [{"message": high_entropy}]})
    assert high_entropy not in json.dumps(sanitized)
    assert bundle_module._scrub_string(f"token {high_entropy}", free_text=True).endswith("[redacted]")
    (tmp_path / "requirements-dev.txt").write_text("pytest\n", encoding="utf-8")
    assert bundle_module._package_manager(tmp_path) == "python"


def test_founder_json_and_count_helpers_cover_dataclass_and_list_shapes() -> None:
    @dataclass
    class Result:
        status: str

    assert json_value(Result("ok"), operation="test") == {"status": "ok"}
    assert founder_module._finding_count({"findings": ["one", "two"]}) == 2


def test_bundle_normalization_covers_fallback_shapes_and_privacy_edges() -> None:
    digest = "A" * 64
    result = sanitize_bundle(
        {
            "metadata": {},
            "files": ["src/main.py", {"path": "README.md", "sizeBytes": 3}, 42],
            "hashes": [{"path": "src/main.py", "sha256": digest}, {"path": "bad", "sha256": "no"}],
            "manifests": [{"path": "package.json", "kind": "manifest", "sizeBytes": 1}, "bad"],
            "routes": ["/", "relative", "/", 3],
            "apiRoutes": ["/api/items"],
            "environment": {"keys": ["B", "A", "A"]},
            "dependencies": ["git+https://user:pass@example.test/repo.git"],
            "testing": {"jestConfig": ["jest.config.js", 1], "vitestConfig": ["vitest.config.ts"], "pytestIni": True},
            "ci": {"githubWorkflows": ["ci.yml", 1]},
            "findings": [{"type": "warning", "message": "safe"}],
            "privacy": {"upload_requires_confirmation": True},
        }
    )
    assert result["routes"] == ["/"]
    assert result["environment"]["keys"] == {".env.example": ["A", "B"]}
    assert result["dependencies"]["productionDependencies"] == ["git+https://example.test/repo.git"]
    assert result["manifest"]["envKeyNames"] == ["A", "B"]

    with pytest.raises(PrivacyViolation, match="relative"):
        sanitize_bundle({"files": [{"path": "/absolute/path"}]})
    with pytest.raises(PrivacyViolation, match="relative"):
        sanitize_bundle({"files": [{"path": "../outside"}]})
    with pytest.raises(PrivacyViolation, match="confirmation"):
        sanitize_bundle({"privacy": {"upload_requires_confirmation": False}})
    with pytest.raises(PrivacyViolation, match="sourceCode"):
        sanitize_bundle({"metadata": {"sourceCode": None}})


def test_bundle_scrubber_covers_free_text_entropy_and_hash_exceptions() -> None:
    safe_digest = "a" * 64
    high_entropy = "AbCdEfGhIjKlMnOpQrStUvWxYz0123456789_~"
    result = sanitize_bundle(
        {
            "findings": [{"message": f"secret={high_entropy} digest={safe_digest}"}],
            "scannerResults": {"raw": high_entropy},
            "dependencies": {"npmAudit": {"note": safe_digest}},
        }
    )
    wire = json.dumps(result)
    assert high_entropy not in wire
    assert safe_digest in wire


def test_bundle_builder_rejects_missing_root_and_hashes_are_stable(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        build_founder_bundle(tmp_path / "missing")
    bundle = sanitize_bundle({"metadata": {"sourceCode": False}})
    assert founder_module.bundle_hash(bundle) == founder_module.bundle_hash(bundle)


def test_open_config_reports_missing_fields_and_vault_failures(settings) -> None:
    store = Store(settings.data_path)
    with pytest.raises(FounderNotConfiguredError):
        resolve_open_config(settings, store)

    store.save_founder_config(lp_base_url="https://lp.test", lp_project_id="project", token_vault_ref="ref")
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(founder_module.SecretVault, "get", lambda *_args: None)
    with pytest.raises(FounderNotConfiguredError):
        resolve_open_config(settings, store)
    monkeypatch.undo()
    store.save_founder_config(lp_base_url="", lp_project_id="project", token_vault_ref="ref")
    with pytest.raises(FounderNotConfiguredError):
        resolve_open_config(settings, store)
    store.save_founder_config(lp_base_url="https://lp.test", lp_project_id="project", token_vault_ref="missing")
    with pytest.raises(FounderNotConfiguredError):
        resolve_open_config(settings, store)


def test_founder_contract_and_json_conversion_edges() -> None:
    pack = LoadedPack(manifest={"name": "founder"}, module=ModuleType("empty"))
    with pytest.raises(FounderPackContractError, match="missing scan"):
        resolve_founder_member(pack, "scan")
    with pytest.raises(FounderPackContractError, match="unsupported"):
        json_value(object(), operation="test")
    with pytest.raises(FounderPackContractError, match="must return an object"):
        json_object(["not", "an", "object"], operation="results")
    assert json_value((Path("x"), 1), operation="test") == ["x", 1]
    assert founder_module._open_env_keys(
        {"environment": {"keys": {".env": ["B", "A"], "bad": "ignored"}}}
    ) == ["A", "B"]
    assert founder_module._open_env_keys({}) == []
    assert founder_module._dependency_count({"dependencies": ["a", "b"]}) == 2
    assert founder_module._finding_count({"findings": {"other": True}}) == 1


def test_upload_preview_contract_and_fresh_preview_edges(tmp_path: Path) -> None:
    bundle: dict[str, object] = {
        "schema_version": "v1",
        "project_name": "demo",
        "file_tree": ["a.py"],
        "manifests": [],
        "routes": [],
        "env_keys": ["PUBLIC_NAME"],
        "findings": [{"type": "warning"}],
    }
    preview = build_upload_preview("artifact", bundle)
    assert preview["file_count"] == 1
    assert preview["env_key_names"] == ["PUBLIC_NAME"]
    assert build_upload_preview(
        "artifact", {"files": [], "manifests": [], "routes": [], "env_keys": [], "findings": [{"type": 1}]}
    )["finding_types"] == []
    with pytest.raises(FounderPackContractError, match="files must be a list"):
        build_upload_preview("artifact", {"files": "bad"})
    with pytest.raises(FounderPackContractError, match="env_keys entries"):
        build_upload_preview(
            "artifact", {"files": [], "manifests": [], "routes": [], "env_keys": [1], "findings": []}
        )
    with pytest.raises(FounderPackContractError, match="findings entries"):
        build_upload_preview(
            "artifact",
            {"files": [], "manifests": [], "routes": [], "env_keys": [], "findings": ["bad"]},
        )

    store = Store(tmp_path / "state.db")
    with pytest.raises(FounderUploadConflictError, match="required"):
        require_fresh_preview(store, "artifact")
    with pytest.raises(FounderUploadConflictError, match="stale"):
        require_fresh_preview(store, "artifact", record={"previewed_at": "not-a-date"})
    with pytest.raises(FounderUploadConflictError, match="stale"):
        require_fresh_preview(store, "artifact", record={"previewed_at": "2000-01-01T00:00:00+00:00"})


def test_open_founder_operations_cover_persistence_and_remote_results(monkeypatch, settings, tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "app.py").write_text("print('safe')", encoding="utf-8")
    store = Store(settings.data_path)
    config = {"lp_project_id": "project-1", "lp_base_url": "https://lp.test", "token_vault_ref": "ref"}
    scanned = founder_module.open_founder_scan(store, settings, config, project)
    artifact_id = str(scanned["artifact_id"])
    assert scanned["status"] == "preview_ready"
    preview = founder_module.open_founder_preview(store, artifact_id)
    assert preview["sourceCode"] is False
    with pytest.raises(KeyError):
        founder_module.open_founder_preview(store, "missing")

    store.mark_founder_artifact_previewed(artifact_id)

    class FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def upload_bundle(self, project_id, bundle):
            assert project_id == "project-1"
            return type("Upload", (), {"as_dict": lambda self: {"status": "uploaded"}})()

        def status(self):
            return ["connected"]

        def list_scans(self, project_id):
            return [{"project": project_id}]

        def latest_report(self, project_id):
            return {"project": project_id, "report": "latest"}

    monkeypatch.setattr(founder_module, "_open_client", lambda *_args: FakeClient())
    uploaded = founder_module.open_founder_upload(settings, store, config, artifact_id)
    assert uploaded == {"status": "uploaded"}
    status_payload = founder_module.open_founder_status(settings, config)
    assert status_payload["status"] == "unknown"
    results = founder_module.open_founder_results(settings, config)
    latest_report = results["latest_report"]
    assert isinstance(latest_report, dict)
    assert latest_report["available"] is True


def test_open_http_operations_use_and_close_the_launch_passport_client(monkeypatch, settings) -> None:
    events: list[str] = []

    class TrackingClient:
        def __enter__(self):
            events.append("enter")
            return self

        def __exit__(self, *_args):
            events.append("exit")
            return None

        def sanitize_upstream(self, value):
            events.append("sanitize")
            return founder_module.scrub_upstream_value(value, token="remote-token")

        def status(self):
            return {"status": "connected", "capabilities": {"launch_scan": True}, "token": "remote-token"}

        def list_scans(self, project_id):
            return [{"status": "running", "project": project_id, "token": "remote-token"}]

        def latest_report(self, project_id):
            return {"project": project_id, "token": "remote-token"}

    monkeypatch.setattr(founder_module, "_open_client", lambda *_args: TrackingClient())
    config = {"lp_project_id": "project-1", "lp_base_url": "https://lp.test", "token_vault_ref": "ref"}

    status_payload = founder_module.open_founder_status(settings, config)
    results = founder_module.open_founder_results(settings, config)

    assert status_payload == {
        "status": "connected",
        "token_configured": True,
        "capabilities": {"launch_scan": True},
        "lp_project_id": "project-1",
    }
    assert results == {
        "scans": {"count": 1, "states": ["running"]},
        "latest_report": {"available": True},
        "project_id": "project-1",
    }
    assert events == ["enter", "sanitize", "exit", "enter", "sanitize", "sanitize", "exit"]


def test_open_upload_checks_project_hash_and_remote_error_passthrough(monkeypatch, settings, tmp_path: Path) -> None:
    store = Store(settings.data_path)
    bundle = sanitize_bundle({"metadata": {"sourceCode": False}})
    store.save_founder_artifact(
        artifact_id="artifact", project_id="project-1", bundle_hash=founder_module.bundle_hash(bundle), bundle=bundle
    )
    store.mark_founder_artifact_previewed("artifact")
    config = {"lp_project_id": "project-1", "lp_base_url": "https://lp.test", "token_vault_ref": "ref"}
    with pytest.raises(PrivacyViolation, match="hash"):
        store.save_founder_artifact(artifact_id="bad-hash", project_id="project-1", bundle_hash="wrong", bundle=bundle)
        store.mark_founder_artifact_previewed("bad-hash")
        founder_module.open_founder_upload(settings, store, config, "bad-hash")
    with pytest.raises(FounderUploadConflictError, match="project"):
        founder_module.open_founder_upload(settings, store, {**config, "lp_project_id": "other"}, "artifact")

    class ErrorClient:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def upload_bundle(self, *_args):
            raise LaunchPassportUnauthorized("bad token")

    monkeypatch.setattr(founder_module, "_open_client", lambda *_args: ErrorClient())
    with pytest.raises(LaunchPassportUnauthorized):
        founder_module.open_founder_upload(settings, store, config, "artifact")


@pytest.mark.parametrize(
    ("error", "code"),
    [(LaunchPassportUnauthorized("x"), 401), (LaunchPassportForbidden("x"), 403),
     (LaunchPassportPayloadTooLarge("x"), 413), (LaunchPassportRequestError("x"), 502)],
)
def test_founder_error_handlers_map_remote_failures(error, code) -> None:
    request = Request({"type": "http", "method": "GET", "path": "/", "headers": [], "query_string": b""})
    response = founder_module.launch_passport_error_handler(request, error)
    assert response.status_code == code
    assert response.body == json.dumps({"error": "x"}, separators=(",", ":")).encode()


def test_open_routes_and_handlers_cover_optional_config_fallbacks(monkeypatch, settings) -> None:
    monkeypatch.setattr(founder_module, "get_pack", lambda _name: None)
    monkeypatch.setattr(founder_module, "open_founder_status", lambda _settings, _config: {"status": "ok"})
    monkeypatch.setattr(founder_module, "open_founder_results", lambda _settings, _config: {"scans": []})
    store = Store(settings.data_path)
    founder_module.configure_founder(settings, store, "https://lp.test", "project-1", "token")
    application = FastAPI()
    application.state.settings = settings
    application.state.store = store
    request = Request(
        {"type": "http", "method": "GET", "path": "/", "headers": [], "query_string": b"", "app": application}
    )
    endpoints = {
        route.path: route.endpoint
        for route in founder_module.create_router().routes
        if isinstance(route, APIRoute)
    }
    assert endpoints["/founder/lp-status"](request, None) == {"status": "ok"}
    assert endpoints["/founder/results"](request, None) == {"scans": []}

    request = Request({"type": "http", "method": "GET", "path": "/", "headers": [], "query_string": b""})
    assert founder_module.founder_pack_unavailable_handler(request, RuntimeError()).status_code == 501
    assert founder_module.founder_not_configured_handler(request, RuntimeError()).status_code == 409
    assert founder_module.founder_privacy_handler(request, PrivacyViolation("private")).status_code == 400
    assert founder_module.launch_passport_error_handler(request, RuntimeError("unknown")).status_code == 502


def test_open_config_and_client_token_provider_handle_vault_errors(monkeypatch, settings) -> None:
    store = Store(settings.data_path)
    store.save_founder_config(lp_base_url="https://lp.test", lp_project_id="project", token_vault_ref="ref")
    monkeypatch.setattr(founder_module.SecretVault, "get", lambda *_args: (_ for _ in ()).throw(SecretVaultError()))
    with pytest.raises(FounderNotConfiguredError):
        resolve_open_config(settings, store)
    client = founder_module._open_client(
        settings, {"lp_base_url": "https://lp.test", "token_vault_ref": "ref", "lp_project_id": "project"}
    )
    try:
        assert client.token_provider() is None
    finally:
        client.close()


def test_configured_founder_token_returns_none_on_vault_error(monkeypatch, settings) -> None:
    store = Store(settings.data_path)
    store.save_founder_config(lp_base_url="https://lp.test", lp_project_id="project", token_vault_ref="ref")
    application = FastAPI()
    application.state.settings = settings
    application.state.store = store
    request = Request(
        {"type": "http", "method": "GET", "path": "/", "headers": [], "query_string": b"", "app": application}
    )
    monkeypatch.setattr(founder_module.SecretVault, "get", lambda *_args: (_ for _ in ()).throw(SecretVaultError()))
    assert founder_module._configured_founder_token(request) is None
