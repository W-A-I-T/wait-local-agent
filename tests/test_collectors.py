from __future__ import annotations

import json
from typing import Any

from fastapi.testclient import TestClient
from typer.testing import CliRunner

from wait_local_agent.api.app import create_app
from wait_local_agent.cli import app
from wait_local_agent.collectors import (
    CollectorManifest,
    CollectorPreview,
    CollectorRegistry,
    CollectorResult,
    CollectorService,
    CollectorValidationResult,
    default_registry,
)
from wait_local_agent.models import (
    AssetObservationWrite,
    CollectorAssetWrite,
    ConfigSnapshotWrite,
    RestoreExerciseWrite,
)
from wait_local_agent.reports.models import ReportType
from wait_local_agent.store import Store


class FakeCollectorModule:
    manifest = CollectorManifest(
        id="fake-fixture",
        name="Fake Fixture Collector",
        version="0.1.0",
        description="Unit-test collector module.",
        capabilities=("fixture_import",),
        scopes=("local_fixture",),
        report_types=("collector_bundle", "restore_evidence"),
    )

    def validate_config(self, config: dict[str, Any]) -> CollectorValidationResult:
        if config.get("source_name") == "bad":
            return CollectorValidationResult(
                module_id=self.manifest.id,
                passed=False,
                message="bad source",
                errors=["source_name cannot be bad"],
            )
        normalized = {"source_name": config.get("source_name", "fixture")}
        return CollectorValidationResult(
            module_id=self.manifest.id,
            passed=True,
            message="ok",
            normalized_config=normalized,
        )

    def preview(self, config: dict[str, Any]) -> CollectorPreview:
        return CollectorPreview(
            module_id=self.manifest.id,
            source_name=str(config["source_name"]),
            scopes=["local_fixture"],
            estimated_assets=1,
            estimated_observations=1,
            expected_reports=["collector_bundle", "restore_evidence"],
            metadata={"pack_boundary": "test-only"},
        )

    def collect(self, config: dict[str, Any]) -> CollectorResult:
        source_name = str(config["source_name"])
        return CollectorResult(
            assets=[
                CollectorAssetWrite(
                    canonical_id=f"asset:{source_name}:endpoint-1",
                    asset_type="endpoint",
                    display_name="Endpoint 1",
                    attributes={"os": "linux", "source": source_name},
                    source_id="endpoint-1",
                )
            ],
            observations=[
                AssetObservationWrite(
                    canonical_id=f"asset:{source_name}:endpoint-1",
                    observation_type="inventory",
                    payload={"hostname": "endpoint-1", "state": "present"},
                )
            ],
            config_snapshots=[
                ConfigSnapshotWrite(
                    canonical_id=f"asset:{source_name}:endpoint-1",
                    snapshot_type="appliance_hardening",
                    payload={"ssh_password_login": False},
                )
            ],
            restore_exercises=[
                RestoreExerciseWrite(
                    canonical_id=f"asset:{source_name}:endpoint-1",
                    exercise_id="restore-1",
                    status="passed",
                    target="local-appliance",
                    backup_artifact_id="backup-1",
                    validation={"state_db": "opened"},
                    evidence={"log": "restore succeeded"},
                )
            ],
            metadata={"collected": True},
        )


def test_fake_module_preview_run_persists_asset_observation_and_exports_bundle(settings) -> None:
    registry = CollectorRegistry()
    registry.register(FakeCollectorModule())
    store = Store(settings.data_path)
    service = CollectorService(store, registry)

    preview = service.preview("fake-fixture", {"source_name": "unit"})
    run = service.run("fake-fixture", {"source_name": "unit"}, confirm=True, client_id="acme")
    report = service.export_report(run.id or 0, ReportType.COLLECTOR_BUNDLE)

    assert preview.estimated_assets == 1
    assert run.status == "completed"
    assert store.list_collector_sources(client_id="acme")[0].name == "unit"
    assert store.list_canonical_assets()[0].canonical_id == "asset:unit:endpoint-1"
    assert store.list_asset_observations(run_id=run.id or 0)[0].observation_type == "inventory"
    assert store.list_config_snapshots(run_id=run.id or 0)[0].snapshot_type == "appliance_hardening"
    assert store.list_restore_exercises(run_id=run.id or 0)[0].status == "passed"
    assert report.report_type is ReportType.COLLECTOR_BUNDLE
    assert report.metadata["collector_run_id"] == run.id
    assert any(event.event_type == "collector.run_completed" for event in store.list_audit_events())


def test_collector_api_surfaces_preview_run_and_export(settings) -> None:
    default_registry.clear()
    default_registry.register(FakeCollectorModule())
    try:
        client = TestClient(create_app(settings))

        modules = client.get("/collectors/modules")
        preview = client.post(
            "/collectors/modules/fake-fixture/preview",
            json={"config": {"source_name": "api"}},
        )
        run = client.post(
            "/collectors/modules/fake-fixture/run",
            json={"confirm": True, "client_id": "api-client", "config": {"source_name": "api"}},
        )
        run_id = run.json()["id"]
        detail = client.get(f"/collectors/runs/{run_id}")
        export = client.post(f"/collectors/runs/{run_id}/export")

        assert modules.status_code == 200
        assert modules.json()[0]["id"] == "fake-fixture"
        assert preview.status_code == 200
        assert preview.json()["estimated_assets"] == 1
        assert run.status_code == 200
        assert run.json()["status"] == "completed"
        assert detail.status_code == 200
        assert detail.json()["assets"][0]["display_name"] == "Endpoint 1"
        assert export.status_code == 200
        assert export.json()["report_type"] == "collector_bundle"
    finally:
        default_registry.clear()


def test_collector_cli_surfaces_preview_run_and_bundle_export(monkeypatch, tmp_path) -> None:
    default_registry.clear()
    default_registry.register(FakeCollectorModule())
    monkeypatch.setenv("WAIT_DATA_PATH", str(tmp_path / "state.db"))
    config_path = tmp_path / "collector-config.json"
    output_path = tmp_path / "bundle.json"
    config_path.write_text(json.dumps({"source_name": "cli"}), encoding="utf-8")
    runner = CliRunner()
    try:
        listing = runner.invoke(app, ["collectors", "list"])
        preview = runner.invoke(
            app,
            ["collectors", "preview", "fake-fixture", "--config", str(config_path)],
        )
        run = runner.invoke(
            app,
            ["collectors", "run", "fake-fixture", "--config", str(config_path), "--confirm"],
        )
        run_id = _run_id_from_output(run.output)
        export = runner.invoke(
            app,
            ["collectors", "bundle", "export", str(run_id), "--output", str(output_path)],
        )

        assert listing.exit_code == 0
        assert "fake-fixture" in listing.output
        assert preview.exit_code == 0
        assert json.loads(preview.output)["source_name"] == "cli"
        assert run.exit_code == 0
        assert "status=completed" in run.output
        assert export.exit_code == 0
        assert output_path.exists()
        assert json.loads(output_path.read_text(encoding="utf-8"))["report_type"] == "collector_bundle"
    finally:
        default_registry.clear()


def _run_id_from_output(output: str) -> int:
    fields = dict(item.split("=", 1) for item in output.split() if "=" in item)
    return int(fields["run_id"])
