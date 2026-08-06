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
    assert bundle["files"][0]["path"] == "app.py"
    assert len(bundle["files"][0]["sha256"]) == 64


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
