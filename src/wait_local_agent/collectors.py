from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Protocol

from wait_local_agent.models import (
    AssetObservationWrite,
    CollectorAssetWrite,
    CollectorRun,
    ConfigDiffWrite,
    ConfigSnapshotWrite,
    RestoreExerciseWrite,
)
from wait_local_agent.reports.builders import (
    build_appliance_hardening_report,
    build_collector_bundle_report,
    build_restore_evidence_report,
)
from wait_local_agent.reports.models import GeneratedReport, ReportType
from wait_local_agent.reports.service import ReportService
from wait_local_agent.store import Store


@dataclass(frozen=True)
class CollectorManifest:
    id: str
    name: str
    version: str
    description: str
    capabilities: tuple[str, ...] = ()
    scopes: tuple[str, ...] = ()
    report_types: tuple[str, ...] = ("collector_bundle",)


@dataclass(frozen=True)
class CollectorValidationResult:
    module_id: str
    passed: bool
    message: str
    errors: list[str] = field(default_factory=list)
    normalized_config: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CollectorPreview:
    module_id: str
    source_name: str
    scopes: list[str]
    estimated_assets: int
    estimated_observations: int
    expected_reports: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CollectorResult:
    assets: list[CollectorAssetWrite] = field(default_factory=list)
    observations: list[AssetObservationWrite] = field(default_factory=list)
    config_snapshots: list[ConfigSnapshotWrite] = field(default_factory=list)
    config_diffs: list[ConfigDiffWrite] = field(default_factory=list)
    restore_exercises: list[RestoreExerciseWrite] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class CollectorModule(Protocol):
    manifest: CollectorManifest

    def validate_config(self, config: dict[str, Any]) -> CollectorValidationResult:
        """Validate and normalize module-specific source config."""

    def preview(self, config: dict[str, Any]) -> CollectorPreview:
        """Return a dry-run collection preview without persisting collected evidence."""

    def collect(self, config: dict[str, Any]) -> CollectorResult:
        """Collect and normalize evidence after explicit operator confirmation."""


class CollectorRegistry:
    def __init__(self) -> None:
        self._modules: dict[str, CollectorModule] = {}

    def register(self, module: CollectorModule) -> None:
        module_id = _clean_module_id(module.manifest.id)
        if module_id != module.manifest.id:
            raise ValueError("collector module id must be lowercase id text")
        if module_id in self._modules:
            raise ValueError(f"collector module {module_id} is already registered")
        self._modules[module_id] = module

    def clear(self) -> None:
        self._modules.clear()

    def list(self) -> list[CollectorModule]:
        return [self._modules[key] for key in sorted(self._modules)]

    def get(self, module_id: str) -> CollectorModule:
        try:
            return self._modules[module_id]
        except KeyError as exc:
            raise KeyError(f"collector module {module_id} is not registered") from exc


class CollectorService:
    def __init__(self, store: Store, registry: CollectorRegistry | None = None) -> None:
        self.store = store
        self.registry = registry or default_registry

    def list_modules(self) -> list[CollectorManifest]:
        return [module.manifest for module in self.registry.list()]

    def validate(self, module_id: str, config: dict[str, Any]) -> CollectorValidationResult:
        module = self.registry.get(module_id)
        result = module.validate_config(config)
        self.store.add_audit_event(
            "collector.config_validated",
            module_id,
            "passed" if result.passed else "failed",
        )
        return result

    def preview(self, module_id: str, config: dict[str, Any]) -> CollectorPreview:
        module = self.registry.get(module_id)
        validation = module.validate_config(config)
        if not validation.passed:
            raise ValueError(validation.message)
        preview = module.preview(validation.normalized_config or config)
        self.store.add_audit_event(
            "collector.previewed",
            module_id,
            f"{preview.source_name} assets={preview.estimated_assets}",
        )
        return preview

    def run(
        self,
        module_id: str,
        config: dict[str, Any],
        *,
        confirm: bool,
        client_id: str | None = None,
        actor_id: str | None = None,
    ) -> CollectorRun:
        if not confirm:
            raise PermissionError("collector runs require confirm=true")
        module = self.registry.get(module_id)
        validation = module.validate_config(config)
        if not validation.passed:
            raise ValueError(validation.message)
        normalized_config = validation.normalized_config or config
        preview = module.preview(normalized_config)
        source = self.store.upsert_collector_source(
            module_id=module_id,
            name=preview.source_name,
            config=normalized_config,
            client_id=client_id,
        )
        run = self.store.create_collector_run(
            module_id=module_id,
            source_id=source.id,
            status="running",
            mode="confirmed",
            scope={"scopes": preview.scopes, "capabilities": list(module.manifest.capabilities)},
            preview=asdict(preview),
            client_id=client_id,
            actor_id=actor_id,
        )
        if run.id is None:
            raise RuntimeError("collector run was not persisted")
        try:
            result = module.collect(normalized_config)
            self.store.persist_collector_result(
                run.id,
                source.id,
                module_id,
                result,
                client_id=client_id,
            )
            return self.store.complete_collector_run(
                run.id,
                "completed",
                result=asdict(result),
            )
        except Exception as exc:
            self.store.complete_collector_run(
                run.id,
                "failed",
                result={"error": str(exc)},
            )
            raise

    def export_report(
        self,
        run_id: int,
        report_type: ReportType = ReportType.COLLECTOR_BUNDLE,
        *,
        created_by: str = "",
    ) -> GeneratedReport:
        run = self.store.get_collector_run(run_id)
        if run is None:
            raise KeyError(run_id)
        if report_type is ReportType.COLLECTOR_BUNDLE:
            sections, metadata = build_collector_bundle_report(self.store, run_id)
            title = f"Collector Bundle {run_id}"
        elif report_type is ReportType.APPLIANCE_HARDENING:
            sections, metadata = build_appliance_hardening_report(self.store, run_id)
            title = f"Appliance Hardening Evidence {run_id}"
        elif report_type is ReportType.RESTORE_EVIDENCE:
            sections, metadata = build_restore_evidence_report(self.store, run_id)
            title = f"Restore Evidence {run_id}"
        else:
            raise ValueError(f"report type {report_type.value} is not a collector export")
        report = ReportService(self.store).create_report(
            report_type,
            title,
            sections,
            created_by=created_by,
            client_id=run.client_id or "",
            project_id=f"collector-run-{run_id}",
            metadata=metadata,
        )
        self.store.set_collector_run_report(run_id, report.id)
        self.store.add_audit_event(
            "collector.report_exported",
            str(run_id),
            f"{report_type.value} report_id={report.id}",
            client_id=run.client_id,
        )
        return report


default_registry = CollectorRegistry()


def _clean_module_id(module_id: str) -> str:
    return module_id.strip().lower()
