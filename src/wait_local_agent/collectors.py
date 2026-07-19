from __future__ import annotations

import os
import platform
import socket
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


class HostRuntimeCollector:
    manifest = CollectorManifest(
        id="host-runtime",
        name="Host Runtime Inventory",
        version="0.1.0",
        description="Read-only inventory of the local host runtime using Python standard library APIs.",
        capabilities=("local_host_inventory", "safe_read_only"),
        scopes=("local_host", "os_runtime", "network_interfaces", "capacity"),
        report_types=("collector_bundle",),
    )

    def validate_config(self, config: dict[str, Any]) -> CollectorValidationResult:
        unsupported_keys = sorted(set(config) - {"source_name"})
        errors: list[str] = []
        if unsupported_keys:
            errors.append(f"unsupported config keys: {', '.join(unsupported_keys)}")
        source_name = config.get("source_name", "local-host")
        if not isinstance(source_name, str) or not source_name.strip():
            errors.append("source_name must be a non-empty string when provided")
        if errors:
            return CollectorValidationResult(
                module_id=self.manifest.id,
                passed=False,
                message="host-runtime collector only supports read-only local host inventory",
                errors=errors,
            )
        return CollectorValidationResult(
            module_id=self.manifest.id,
            passed=True,
            message="ok",
            normalized_config={"source_name": source_name.strip()},
        )

    def scope(self, config: dict[str, Any]) -> dict[str, Any]:
        normalized = self.validate_config(config).normalized_config or config
        return {
            "source_name": normalized.get("source_name", "local-host"),
            "scopes": list(self.manifest.scopes),
            "capabilities": list(self.manifest.capabilities),
            "safety": {
                "read_only": True,
                "external_network_scanning": False,
                "remote_hosts": False,
                "dependencies": "python-stdlib-only",
            },
        }

    def preview(self, config: dict[str, Any]) -> CollectorPreview:
        inventory = _collect_host_runtime_inventory()
        return CollectorPreview(
            module_id=self.manifest.id,
            source_name=str(config.get("source_name", "local-host")),
            scopes=list(self.manifest.scopes),
            estimated_assets=1,
            estimated_observations=3,
            expected_reports=list(self.manifest.report_types),
            metadata={
                "hostname": inventory["hostname"],
                "interface_count": len(inventory["network_interfaces"]),
                "safe_read_only": True,
                "external_network_scanning": False,
            },
        )

    def collect(self, config: dict[str, Any]) -> CollectorResult:
        inventory = _collect_host_runtime_inventory()
        canonical_id = _host_canonical_id(inventory["hostname"])
        return CollectorResult(
            assets=[
                CollectorAssetWrite(
                    canonical_id=canonical_id,
                    asset_type="host",
                    display_name=inventory["hostname"] or "Local host",
                    attributes={
                        "source": str(config.get("source_name", "local-host")),
                        "hostname": inventory["hostname"],
                        "fqdn": inventory["fqdn"],
                        "system": inventory["system"],
                        "kernel": inventory["kernel"],
                        "kernel_version": inventory["kernel_version"],
                        "machine": inventory["machine"],
                        "processor": inventory["processor"],
                        "python_runtime": inventory["python_runtime"],
                    },
                    source_module=self.manifest.id,
                    source_id=inventory["hostname"],
                )
            ],
            observations=[
                AssetObservationWrite(
                    canonical_id=canonical_id,
                    observation_type="host_runtime_inventory",
                    payload={
                        "hostname": inventory["hostname"],
                        "fqdn": inventory["fqdn"],
                        "platform": inventory["platform"],
                        "system": inventory["system"],
                        "release": inventory["kernel"],
                        "version": inventory["kernel_version"],
                        "machine": inventory["machine"],
                        "processor": inventory["processor"],
                        "python_runtime": inventory["python_runtime"],
                    },
                ),
                AssetObservationWrite(
                    canonical_id=canonical_id,
                    observation_type="host_capacity",
                    payload={
                        "cpu_count": inventory["cpu_count"],
                        "memory_total_bytes": inventory["memory_total_bytes"],
                    },
                ),
                AssetObservationWrite(
                    canonical_id=canonical_id,
                    observation_type="network_interfaces",
                    payload={
                        "interfaces": inventory["network_interfaces"],
                        "hostname_addresses": inventory["hostname_addresses"],
                        "external_network_scanning": False,
                    },
                ),
            ],
            metadata={
                "safe_read_only": True,
                "external_network_scanning": False,
                "stdlib_only": True,
            },
        )


def _clean_module_id(module_id: str) -> str:
    return module_id.strip().lower()


def _collect_host_runtime_inventory() -> dict[str, Any]:
    hostname = socket.gethostname()
    fqdn = platform.node() or hostname
    return {
        "hostname": hostname,
        "fqdn": fqdn,
        "platform": platform.platform(),
        "system": platform.system(),
        "kernel": platform.release(),
        "kernel_version": platform.version(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "python_runtime": platform.python_implementation(),
        "cpu_count": os.cpu_count(),
        "memory_total_bytes": _memory_total_bytes(),
        "network_interfaces": _network_interfaces(),
        "hostname_addresses": _hostname_addresses(hostname, fqdn),
    }


def _memory_total_bytes() -> int | None:
    if not hasattr(os, "sysconf"):
        return None
    try:
        page_size = os.sysconf("SC_PAGE_SIZE")
        page_count = os.sysconf("SC_PHYS_PAGES")
    except (OSError, ValueError):
        return None
    if not isinstance(page_size, int) or not isinstance(page_count, int):
        return None
    if page_size <= 0 or page_count <= 0:
        return None
    return page_size * page_count


def _network_interfaces() -> list[dict[str, Any]]:
    interfaces: list[dict[str, Any]] = []
    if hasattr(socket, "if_nameindex"):
        try:
            for index, name in socket.if_nameindex():
                interfaces.append({"index": index, "name": name, "addresses": []})
        except OSError:
            interfaces = []
    if interfaces:
        return sorted(interfaces, key=lambda item: (str(item["name"]), int(item["index"])))
    return [{"index": None, "name": name, "addresses": []} for name in _network_interface_names_from_sys()]


def _network_interface_names_from_sys() -> list[str]:
    sys_net = "/sys/class/net"
    try:
        names = os.listdir(sys_net)
    except OSError:
        return []
    return sorted(name for name in names if name and "/" not in name)


def _hostname_addresses(hostname: str, fqdn: str) -> list[str]:
    addresses: set[str] = set()
    for name in {hostname, fqdn}:
        if not name:
            continue
        try:
            infos = socket.getaddrinfo(name, None, type=socket.SOCK_STREAM)
        except OSError:
            continue
        for family, _socktype, _proto, _canonname, sockaddr in infos:
            if family in {socket.AF_INET, socket.AF_INET6} and sockaddr:
                addresses.add(str(sockaddr[0]))
    return sorted(addresses)


def _host_canonical_id(hostname: str) -> str:
    normalized = "".join(character.lower() if character.isalnum() else "-" for character in hostname)
    normalized = "-".join(part for part in normalized.split("-") if part)
    return f"host-runtime:host:{normalized or 'local-host'}"


default_registry = CollectorRegistry()
default_registry.register(HostRuntimeCollector())
