from __future__ import annotations

import json
from typing import Any

import pytest
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
    HostRuntimeCollector,
    default_registry,
)
from wait_local_agent.models import (
    AssetObservationWrite,
    CollectorAssetWrite,
    ConfigDiffWrite,
    ConfigSnapshotWrite,
    RestoreExerciseWrite,
)
from wait_local_agent.reports.builders import (
    build_appliance_hardening_report,
    build_collector_bundle_report,
    build_restore_evidence_report,
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
            config_diffs=[
                ConfigDiffWrite(
                    canonical_id=f"asset:{source_name}:endpoint-1",
                    diff_type="hardening",
                    severity="info",
                    summary="SSH password login remains disabled.",
                    payload={"ssh_password_login": {"current": False, "expected": False}},
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


class ExplodingCollectorModule(FakeCollectorModule):
    manifest = CollectorManifest(
        id="exploding-fixture",
        name="Exploding Fixture Collector",
        version="0.1.0",
        description="Raises during collection after preview/run persistence.",
    )

    def collect(self, config: dict[str, Any]) -> CollectorResult:
        raise RuntimeError(f"collector failure for {config['source_name']}")


def test_host_runtime_preview_run_persists_host_asset_observations_and_exports(settings) -> None:
    registry = CollectorRegistry()
    registry.register(HostRuntimeCollector())
    store = Store(settings.data_path)
    service = CollectorService(store, registry)

    preview = service.preview("host-runtime", {})
    run = service.run("host-runtime", {}, confirm=True, client_id="local")
    report = service.export_report(run.id or 0, ReportType.COLLECTOR_BUNDLE)

    assets = store.list_canonical_assets()
    observations = store.list_asset_observations(run_id=run.id or 0)
    observation_types = {observation.observation_type for observation in observations}

    assert preview.module_id == "host-runtime"
    assert preview.estimated_assets == 1
    assert preview.estimated_observations == 3
    assert preview.metadata["external_network_scanning"] is False
    assert run.status == "completed"
    assert len(assets) == 1
    assert assets[0].asset_type == "host"
    assert assets[0].canonical_id.startswith("host-runtime:host:")
    assert len(observations) == 3
    assert observation_types == {
        "host_runtime_inventory",
        "host_capacity",
        "network_interfaces",
    }
    assert report.report_type is ReportType.COLLECTOR_BUNDLE


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
    assert store.list_config_diffs()[0].severity == "info"
    assert store.list_restore_exercises(run_id=run.id or 0)[0].status == "passed"
    assert report.report_type is ReportType.COLLECTOR_BUNDLE
    assert report.metadata["collector_run_id"] == run.id
    hardening_report = service.export_report(run.id or 0, ReportType.APPLIANCE_HARDENING)
    assert hardening_report.report_type is ReportType.APPLIANCE_HARDENING
    restore_report = service.export_report(run.id or 0, ReportType.RESTORE_EVIDENCE)
    assert restore_report.report_type is ReportType.RESTORE_EVIDENCE
    assert restore_report.sections[0].recommendations == []
    assert any(event.event_type == "collector.run_completed" for event in store.list_audit_events())


def test_collector_registry_service_validation_and_guard_branches(settings) -> None:
    registry = CollectorRegistry()
    registry.register(FakeCollectorModule())
    store = Store(settings.data_path)
    service = CollectorService(store, registry)

    assert service.list_modules()[0].id == "fake-fixture"
    assert service.validate("fake-fixture", {"source_name": "unit"}).passed is True
    failed_validation = service.validate("fake-fixture", {"source_name": "bad"})

    with pytest.raises(ValueError, match="bad source"):
        service.preview("fake-fixture", {"source_name": "bad"})
    with pytest.raises(PermissionError, match="confirm=true"):
        service.run("fake-fixture", {"source_name": "unit"}, confirm=False)
    with pytest.raises(KeyError, match="not registered"):
        service.validate("missing-fixture", {})
    with pytest.raises(KeyError):
        service.export_report(404)

    run = service.run("fake-fixture", {"source_name": "unit"}, confirm=True)
    with pytest.raises(ValueError, match="not a collector export"):
        service.export_report(run.id or 0, ReportType.TICKET_INTELLIGENCE)

    assert failed_validation.passed is False
    assert failed_validation.errors == ["source_name cannot be bad"]
    assert any(
        event.event_type == "collector.config_validated" and event.detail == "failed"
        for event in store.list_audit_events()
    )


def test_collector_registry_rejects_invalid_duplicate_and_missing_modules() -> None:
    registry = CollectorRegistry()
    registry.register(FakeCollectorModule())

    with pytest.raises(ValueError, match="already registered"):
        registry.register(FakeCollectorModule())
    with pytest.raises(ValueError, match="lowercase"):
        registry.register(_module_with_id("Bad Id"))
    with pytest.raises(KeyError, match="missing is not registered"):
        registry.get("missing")

    registry.clear()
    assert registry.list() == []


def test_collector_service_marks_run_failed_when_module_collect_raises(settings) -> None:
    registry = CollectorRegistry()
    registry.register(ExplodingCollectorModule())
    store = Store(settings.data_path)
    service = CollectorService(store, registry)

    with pytest.raises(RuntimeError, match="collector failure"):
        service.run("exploding-fixture", {"source_name": "boom"}, confirm=True, client_id="acme", actor_id="tech-1")

    failed_run = store.list_collector_runs(client_id="acme")[0]
    assert failed_run.status == "failed"
    assert json.loads(failed_run.result_json) == {"error": "collector failure for boom"}
    assert any(event.event_type == "collector.run_failed" for event in store.list_audit_events(client_id="acme"))


def test_collector_api_surfaces_preview_run_and_export(settings) -> None:
    default_registry.clear()
    default_registry.register(FakeCollectorModule())
    try:
        client = TestClient(create_app(settings))

        modules = client.get("/collectors/modules")
        validate = client.post(
            "/collectors/modules/fake-fixture/validate",
            json={"config": {"source_name": "api"}},
        )
        validate_bad = client.post(
            "/collectors/modules/fake-fixture/validate",
            json={"config": {"source_name": "bad"}},
        )
        preview_bad = client.post(
            "/collectors/modules/fake-fixture/preview",
            json={"config": {"source_name": "bad"}},
        )
        preview = client.post(
            "/collectors/modules/fake-fixture/preview",
            json={"config": {"source_name": "api"}},
        )
        unconfirmed = client.post(
            "/collectors/modules/fake-fixture/run",
            json={"confirm": False, "config": {"source_name": "api"}},
        )
        run = client.post(
            "/collectors/modules/fake-fixture/run",
            json={"confirm": True, "client_id": "api-client", "config": {"source_name": "api"}},
        )
        run_id = run.json()["id"]
        runs = client.get("/collectors/runs", params={"client_id": "api-client"})
        detail = client.get(f"/collectors/runs/{run_id}")
        export = client.post(f"/collectors/runs/{run_id}/export")
        unsupported_export = client.post(
            f"/collectors/runs/{run_id}/export",
            params={"report_type": "ticket_intelligence"},
        )
        missing_module = client.post("/collectors/modules/missing-fixture/validate", json={"config": {}})
        missing_run = client.get("/collectors/runs/404")
        missing_export = client.post("/collectors/runs/404/export")

        assert modules.status_code == 200
        assert modules.json()[0]["id"] == "fake-fixture"
        assert validate.status_code == 200
        assert validate.json()["passed"] is True
        assert validate_bad.status_code == 200
        assert validate_bad.json()["passed"] is False
        assert preview_bad.status_code == 400
        assert preview.status_code == 200
        assert preview.json()["estimated_assets"] == 1
        assert unconfirmed.status_code == 409
        assert run.status_code == 200
        assert run.json()["status"] == "completed"
        assert runs.status_code == 200
        assert runs.json()[0]["id"] == run_id
        assert detail.status_code == 200
        assert detail.json()["assets"][0]["display_name"] == "Endpoint 1"
        assert export.status_code == 200
        assert export.json()["report_type"] == "collector_bundle"
        assert unsupported_export.status_code == 400
        assert missing_module.status_code == 404
        assert missing_run.status_code == 404
        assert missing_export.status_code == 404
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
        validate = runner.invoke(
            app,
            ["collectors", "validate", "fake-fixture", "--config", str(config_path)],
        )
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
        assert validate.exit_code == 0
        assert json.loads(validate.output)["passed"] is True
        assert preview.exit_code == 0
        assert json.loads(preview.output)["source_name"] == "cli"
        assert run.exit_code == 0
        assert "status=completed" in run.output
        assert export.exit_code == 0
        assert output_path.exists()
        assert json.loads(output_path.read_text(encoding="utf-8"))["report_type"] == "collector_bundle"
    finally:
        default_registry.clear()


def test_collector_cli_validation_and_guard_branches(monkeypatch, tmp_path) -> None:
    default_registry.clear()
    default_registry.register(FakeCollectorModule())
    monkeypatch.setenv("WAIT_DATA_PATH", str(tmp_path / "state.db"))
    bad_config_path = tmp_path / "bad-config.json"
    list_config_path = tmp_path / "list-config.json"
    bad_config_path.write_text(json.dumps({"source_name": "bad"}), encoding="utf-8")
    list_config_path.write_text(json.dumps(["not", "an", "object"]), encoding="utf-8")
    runner = CliRunner()
    try:
        validation = runner.invoke(
            app,
            ["collectors", "validate", "fake-fixture", "--config", str(bad_config_path)],
        )
        preview = runner.invoke(
            app,
            ["collectors", "preview", "fake-fixture", "--config", str(bad_config_path)],
        )
        run = runner.invoke(app, ["collectors", "run", "fake-fixture"])
        missing = runner.invoke(app, ["collectors", "validate", "missing-fixture"])
        invalid_config = runner.invoke(
            app,
            ["collectors", "preview", "fake-fixture", "--config", str(list_config_path)],
        )

        assert validation.exit_code == 1
        assert json.loads(validation.output)["passed"] is False
        assert preview.exit_code != 0
        assert "bad source" in preview.output
        assert run.exit_code != 0
        assert "confirm=true" in run.output
        assert missing.exit_code != 0
        assert "collector module not found" in missing.output
        assert invalid_config.exit_code != 0
        assert "collector config must be a JSON object" in invalid_config.output
    finally:
        default_registry.clear()


def test_collector_cli_lists_empty_registry() -> None:
    default_registry.clear()
    runner = CliRunner()

    listing = runner.invoke(app, ["collectors", "list"])

    assert listing.exit_code == 0
    assert "no collector modules registered" in listing.output


def test_store_collector_methods_cover_crud_filters_and_guards(settings) -> None:
    store = Store(settings.data_path)
    acme_source = store.upsert_collector_source(
        module_id="fake-fixture",
        name="Acme fixture",
        config={"source_name": "acme"},
        client_id="acme",
    )
    updated_source = store.upsert_collector_source(
        module_id="fake-fixture",
        name="Acme renamed",
        config={"source_name": "acme"},
        client_id="acme",
    )
    beta_source = store.upsert_collector_source(
        module_id="fake-fixture",
        name="Beta fixture",
        config={"source_name": "beta"},
        client_id="beta",
    )
    acme_run = store.create_collector_run(
        module_id="fake-fixture",
        source_id=acme_source.id,
        status="running",
        mode="confirmed",
        scope={"scopes": ["local_fixture"]},
        preview={"source_name": "acme"},
        client_id="acme",
        actor_id="tech-1",
    )
    beta_run = store.create_collector_run(
        module_id="fake-fixture",
        source_id=beta_source.id,
        status="running",
        mode="confirmed",
        scope={},
        preview={},
        client_id="beta",
    )
    completed = store.complete_collector_run(acme_run.id or 0, "completed", result={"ok": True})
    linked = store.set_collector_run_report(acme_run.id or 0, "report-1")
    asset = store.upsert_canonical_asset(
        canonical_id="asset:acme:endpoint-1",
        asset_type="endpoint",
        display_name="Endpoint 1",
        attributes={"hostname": "endpoint-1"},
        client_id="acme",
        owner="ops",
        source_module="fake-fixture",
        source_id="endpoint-1",
        confidence=0.9,
    )
    updated_asset = store.upsert_canonical_asset(
        canonical_id="asset:acme:endpoint-1",
        asset_type="server",
        display_name="Endpoint 1 renamed",
        attributes={"hostname": "endpoint-1", "role": "server"},
        source_module="fake-fixture",
        source_id="endpoint-1",
        confidence=0.8,
    )
    observation = store.add_asset_observation(
        asset_id=asset.id or 0,
        run_id=acme_run.id or 0,
        source_id=acme_source.id,
        observation_type="inventory",
        payload={"state": "present"},
        confidence=0.75,
    )
    baseline = store.add_config_snapshot(
        run_id=acme_run.id or 0,
        asset_id=asset.id,
        source_id=acme_source.id,
        snapshot_type="appliance_hardening",
        payload={"ssh_password_login": True},
    )
    candidate = store.add_config_snapshot(
        run_id=acme_run.id or 0,
        asset_id=asset.id,
        source_id=acme_source.id,
        snapshot_type="appliance_hardening",
        payload={"ssh_password_login": False},
        checksum="fixed-checksum",
    )
    diff = store.add_config_diff(
        baseline_snapshot_id=baseline.id,
        candidate_snapshot_id=candidate.id,
        asset_id=asset.id,
        diff_type="hardening",
        severity="medium",
        summary="SSH password login changed.",
        payload={"before": True, "after": False},
    )
    restore = store.add_restore_exercise(
        run_id=acme_run.id,
        asset_id=asset.id,
        source_id=acme_source.id,
        exercise_id="restore-1",
        status="failed",
        target="local-appliance",
        backup_artifact_id="backup-1",
        validation={"state_db": "missing"},
        evidence={"log": "restore failed"},
        client_id="acme",
    )
    ad_hoc_restore = store.add_restore_exercise(
        run_id=None,
        asset_id=None,
        source_id=None,
        exercise_id="restore-adhoc",
        status="passed",
        target="lab",
        backup_artifact_id="backup-adhoc",
        validation={},
        evidence={},
    )

    assert acme_source.id == updated_source.id
    assert updated_source.name == "Acme renamed"
    assert store.get_collector_source(acme_source.id or 0) == updated_source
    assert store.get_collector_source(404) is None
    assert [source.name for source in store.list_collector_sources(client_id="acme")] == ["Acme renamed"]
    assert {source.name for source in store.list_collector_sources(client_id="")} == {"Acme renamed", "Beta fixture"}
    assert completed.status == "completed"
    assert linked.report_id == "report-1"
    assert [run.id for run in store.list_collector_runs(client_id="acme")] == [acme_run.id]
    assert [run.id for run in store.list_collector_runs(client_id="")] == [beta_run.id, acme_run.id]
    assert store.get_collector_run(404) is None
    assert store.get_canonical_asset(asset.id or 0) is not None
    assert store.get_canonical_asset(404) is None
    assert store.get_canonical_asset_by_canonical_id("asset:acme:endpoint-1") == updated_asset
    assert store.get_canonical_asset_by_canonical_id("missing") is None
    assert updated_asset.asset_type == "server"
    assert updated_asset.client_id == "acme"
    assert json.loads(updated_asset.attributes_json)["role"] == "server"
    assert [item.canonical_id for item in store.list_canonical_assets(client_id="acme")] == ["asset:acme:endpoint-1"]
    assert [item.canonical_id for item in store.list_canonical_assets(run_id=acme_run.id or 0)] == [
        "asset:acme:endpoint-1"
    ]
    assert store.get_asset_observation(observation.id or 0) == observation
    assert store.get_asset_observation(404) is None
    assert store.list_asset_observations(run_id=acme_run.id or 0) == [observation]
    assert store.get_config_snapshot(candidate.id or 0) == candidate
    assert store.get_config_snapshot(404) is None
    assert store.list_config_snapshots(run_id=acme_run.id or 0) == [baseline, candidate]
    assert candidate.checksum == "fixed-checksum"
    assert baseline.checksum != ""
    assert store.get_config_diff(diff.id or 0) == diff
    assert store.get_config_diff(404) is None
    assert store.list_config_diffs(run_id=acme_run.id or 0) == [diff]
    assert store.get_restore_exercise(restore.id or 0) == restore
    assert store.get_restore_exercise(404) is None
    assert store.list_restore_exercises(run_id=acme_run.id or 0) == [restore]
    assert ad_hoc_restore.run_id is None

    with pytest.raises(KeyError):
        store.complete_collector_run(404, "failed", result={"error": "missing"})
    with pytest.raises(KeyError):
        store.set_collector_run_report(404, "report-missing")
    with pytest.raises(KeyError, match="asset missing not found"):
        store.persist_collector_result(
            acme_run.id or 0,
            acme_source.id,
            "fake-fixture",
            CollectorResult(
                observations=[
                    AssetObservationWrite(
                        canonical_id="missing",
                        observation_type="inventory",
                        payload={},
                    )
                ]
            ),
        )


def test_report_builders_cover_collector_hardening_restore_and_missing_run(settings) -> None:
    store = Store(settings.data_path)
    source = store.upsert_collector_source(
        module_id="fake-fixture",
        name="report fixture",
        config={"source_name": "report"},
    )
    run = store.create_collector_run(
        module_id="fake-fixture",
        source_id=source.id,
        status="completed",
        mode="confirmed",
        scope={"scopes": ["local_fixture"]},
        preview={"source_name": "report"},
    )
    asset = store.upsert_canonical_asset(
        canonical_id="asset:report:endpoint-1",
        asset_type="endpoint",
        display_name="Endpoint 1",
        attributes={"hostname": "endpoint-1"},
    )
    store.add_asset_observation(
        asset_id=asset.id or 0,
        run_id=run.id or 0,
        source_id=source.id,
        observation_type="inventory",
        payload={"hostname": "endpoint-1"},
    )
    baseline = store.add_config_snapshot(
        run_id=run.id or 0,
        asset_id=asset.id,
        source_id=source.id,
        snapshot_type="appliance_hardening",
        payload={"ssh_password_login": True},
    )
    candidate = store.add_config_snapshot(
        run_id=run.id or 0,
        asset_id=asset.id,
        source_id=source.id,
        snapshot_type="appliance_hardening",
        payload={"ssh_password_login": False},
    )
    store.add_config_diff(
        baseline_snapshot_id=baseline.id,
        candidate_snapshot_id=candidate.id,
        asset_id=asset.id,
        diff_type="regression",
        severity="high",
        summary="Password login drift.",
        payload={"before": True, "after": False},
    )
    store.add_restore_exercise(
        run_id=run.id,
        asset_id=asset.id,
        source_id=source.id,
        exercise_id="restore-1",
        status="failed",
        target="local-appliance",
        backup_artifact_id="backup-1",
        validation={"state_db": "missing"},
        evidence={"log": "restore failed"},
    )

    bundle_sections, bundle_metadata = build_collector_bundle_report(store, run.id or 0)
    hardening_sections, hardening_metadata = build_appliance_hardening_report(store, run.id or 0)
    restore_sections, restore_metadata = build_restore_evidence_report(store, run.id or 0)

    assert bundle_metadata == {
        "collector_run_id": run.id,
        "module_id": "fake-fixture",
        "asset_count": 1,
        "observation_count": 1,
    }
    assert bundle_sections[0].title == "Collector Run Manifest"
    assert bundle_sections[1].summary == "1 canonical asset records persisted."
    assert "1 observations, 2 snapshots, 1 diffs, 1 restore exercises." in bundle_sections[2].summary
    assert hardening_metadata["collector_run_id"] == run.id
    assert hardening_sections[0].summary == "2 configuration snapshots are attached to this run."
    assert hardening_sections[1].recommendations == [
        "Review unknown or regression-classified diffs before relying on the bundle."
    ]
    assert restore_metadata["module_id"] == "fake-fixture"
    assert restore_sections[0].summary == "1 restore exercises are attached to this run."
    assert restore_sections[0].recommendations == ["Repeat failed restore exercises after remediation."]

    with pytest.raises(KeyError):
        build_collector_bundle_report(store, 404)
    with pytest.raises(KeyError):
        build_appliance_hardening_report(store, 404)
    with pytest.raises(KeyError):
        build_restore_evidence_report(store, 404)


def _run_id_from_output(output: str) -> int:
    fields = dict(item.split("=", 1) for item in output.split() if "=" in item)
    return int(fields["run_id"])


def _module_with_id(module_id: str) -> FakeCollectorModule:
    class ModuleWithId(FakeCollectorModule):
        manifest = CollectorManifest(
            id=module_id,
            name="Fixture Collector With Custom Id",
            version="0.1.0",
            description="Unit-test collector module with caller-provided id.",
        )

    return ModuleWithId()
