from __future__ import annotations

import json
from pathlib import Path
from types import ModuleType

import httpx
import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

import wait_local_agent.api.founder as founder_module
import wait_local_agent.cli as cli_module
from wait_local_agent.api.app import create_app
from wait_local_agent.api.founder import FounderUploadConflictError
from wait_local_agent.api.packs.loader import LoadedPack
from wait_local_agent.founder_bundle import PrivacyViolation, build_founder_bundle, sanitize_bundle
from wait_local_agent.lp_client import LaunchPassportClient
from wait_local_agent.store import Store


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
            return httpx.Response(200, json={"artifact_id": "remote-1", "status": "uploaded"})
        if request.url.path == "/api/health":
            return httpx.Response(200, json={"capabilities": {"launch_scan": True}})
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
    assert uploaded.json()["status"] == "uploaded"
    wire = json.loads(requests[0].content)
    assert wire["metadata"]["sourceCode"] is False
    assert "private source" not in json.dumps(wire)
    assert "bearer-secret" not in json.dumps(wire)
    transport_client.close()


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

    def upload(artifact_id, bundle):  # type: ignore[no-untyped-def]
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
    assert response.json()["status"] == "pack"


def test_cli_doctor_reports_optional_state_when_unconfigured(monkeypatch, settings, tmp_path: Path) -> None:
    monkeypatch.setenv("WAIT_DATA_PATH", str(tmp_path / "state.db"))
    monkeypatch.setattr(cli_module, "load_settings", lambda: settings)
    monkeypatch.setattr(cli_module, "sync_pack_cli", lambda *args, **kwargs: None)
    result = CliRunner().invoke(cli_module.app, ["doctor"])
    assert result.exit_code == 0
    assert "founder_lp_status=not_configured" in result.output
