from __future__ import annotations

import ipaddress
import os
import platform
import platform as _process_inventory_platform
import socket
from dataclasses import asdict, dataclass, field
from pathlib import Path as _ProcessInventoryPath
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

_ListeningPortsPath = _ProcessInventoryPath
_NetworkInterfacesPath = _ProcessInventoryPath
_FirewallRulesPath = _ProcessInventoryPath
_DatabaseInventoryPath = _ProcessInventoryPath
_WifiInventoryPath = _ProcessInventoryPath
_RoutingTablePath = _ProcessInventoryPath


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
 




class ProcessInventoryCollectorModule:
    """Read-only collector that inventories local processes from /proc."""

    module_id = "process-inventory"
    id = module_id
    collector_id = module_id
    slug = module_id
    name = "Process Inventory"
    version = "1.0"

    def manifest(self):
        return {
            "module_id": self.module_id,
            "name": self.name,
            "version": self.version,
            "description": "Read-only inventory of local running processes.",
            "asset_type": "process",
            "read_only": True,
            "dependencies": [],
            "platforms": ["linux"],
        }

    def scope(self, config=None):
        return {
            "read_only": True,
            "stdlib_only": True,
            "paths": ["/proc"],
            "operations": ["read-process-metadata"],
            "network": False,
            "shell": False,
        }

    def validate_config(self, config=None):
        errors = []
        if config not in (None, {}) and not isinstance(config, dict):
            errors.append("config must be a mapping when provided")

        if isinstance(config, dict) and "limit" in config:
            limit = config["limit"]
            if not isinstance(limit, int) or limit < 0:
                errors.append("limit must be a non-negative integer")

        return {"ok": not errors, "errors": errors}

    def preview(self, config=None):
        validation = self.validate_config(config)
        if not validation["ok"]:
            return {
                "module_id": self.module_id,
                "ok": False,
                "errors": validation["errors"],
                "assets": [],
                "observations": [],
            }

        limit = self._config_limit(config, default=10)
        records = self._process_records(limit=limit)
        return self._result(records, preview=True)

    def collect(self, config=None):
        validation = self.validate_config(config)
        if not validation["ok"]:
            return {
                "module_id": self.module_id,
                "ok": False,
                "errors": validation["errors"],
                "assets": [],
                "observations": [],
            }

        limit = self._config_limit(config, default=None)
        records = self._process_records(limit=limit)
        return self._result(records, preview=False)

    @staticmethod
    def _config_limit(config, default):
        if isinstance(config, dict) and "limit" in config:
            return config["limit"]
        return default

    def _result(self, records, preview):
        assets = [self._asset(record) for record in records]
        observations = [
            observation
            for record in records
            for observation in self._observations(record)
        ]
        return {
            "module_id": self.module_id,
            "ok": True,
            "preview": preview,
            "assets": assets,
            "observations": observations,
            "items": [
                {
                    "canonical_asset": asset,
                    "observations": self._observations(record),
                }
                for asset, record in zip(assets, records, strict=False)
            ],
            "count": len(assets),
        }

    @staticmethod
    def _asset(record):
        pid = record["pid"]
        return {
            "asset_type": "process",
            "asset_id": f"process:{pid}",
            "name": record.get("name") or record.get("cmdline") or str(pid),
            "attributes": {
                "pid": pid,
                "name": record.get("name", ""),
                "cmdline": record.get("cmdline", ""),
                "state": record.get("state", ""),
            },
        }

    @staticmethod
    def _observations(record):
        pid = record["pid"]
        return [
            {
                "asset_type": "process",
                "asset_id": f"process:{pid}",
                "key": "process.pid",
                "value": pid,
            },
            {
                "asset_type": "process",
                "asset_id": f"process:{pid}",
                "key": "process.name",
                "value": record.get("name", ""),
            },
            {
                "asset_type": "process",
                "asset_id": f"process:{pid}",
                "key": "process.cmdline",
                "value": record.get("cmdline", ""),
            },
            {
                "asset_type": "process",
                "asset_id": f"process:{pid}",
                "key": "process.state",
                "value": record.get("state", ""),
            },
        ]

    def _process_records(self, limit=None):
        if limit == 0:
            return []

        if _process_inventory_platform.system() != "Linux":
            return []

        proc_path = _ProcessInventoryPath("/proc")
        if not proc_path.exists() or not proc_path.is_dir():
            return []

        records: list[dict[str, Any]] = []
        try:
            entries = list(proc_path.iterdir())
        except OSError:
            return []

        for entry in entries:
            if not entry.name.isdigit():
                continue

            record = self._read_proc_entry(entry)
            if record is None:
                continue

            records.append(record)
            if limit is not None and len(records) >= limit:
                break

        records.sort(key=lambda item: item["pid"])
        return records

    @staticmethod
    def _read_proc_entry(entry):
        try:
            pid = int(entry.name)
        except ValueError:
            return None

        status = _read_process_inventory_text(entry / "status")
        name = ""
        state = ""
        for line in status.splitlines():
            if line.startswith("Name:"):
                name = line.split(":", 1)[1].strip()
            elif line.startswith("State:"):
                state = line.split(":", 1)[1].strip()

        cmdline = _read_process_inventory_cmdline(entry / "cmdline")
        if not name:
            comm = _read_process_inventory_text(entry / "comm").strip()
            name = comm

        if not name and not cmdline:
            return None

        return {
            "pid": pid,
            "name": name,
            "cmdline": cmdline,
            "state": state,
        }


class ListeningPortsCollectorModule:
    """Read-only collector that inventories local listening sockets from /proc/net."""

    module_id = "listening-ports"
    id = module_id
    collector_id = module_id
    slug = module_id
    name = "Listening Ports"
    version = "1.0"

    def manifest(self):
        return {
            "module_id": self.module_id,
            "name": self.name,
            "version": self.version,
            "description": "Read-only inventory of local listening sockets.",
            "asset_type": "network-socket",
            "read_only": True,
            "dependencies": [],
            "platforms": ["linux"],
        }

    def scope(self, config=None):
        return {
            "read_only": True,
            "stdlib_only": True,
            "paths": [
                "/proc/net/tcp",
                "/proc/net/tcp6",
                "/proc/net/udp",
                "/proc/net/udp6",
            ],
            "operations": ["read-socket-table"],
            "network": False,
            "shell": False,
        }

    def validate_config(self, config=None):
        errors = []
        if config not in (None, {}) and not isinstance(config, dict):
            errors.append("config must be a mapping when provided")

        if isinstance(config, dict) and "limit" in config:
            limit = config["limit"]
            if not isinstance(limit, int) or limit < 0:
                errors.append("limit must be a non-negative integer")

        return {"ok": not errors, "errors": errors}

    def preview(self, config=None):
        validation = self.validate_config(config)
        if not validation["ok"]:
            return {
                "module_id": self.module_id,
                "ok": False,
                "errors": validation["errors"],
                "assets": [],
                "observations": [],
            }

        limit = self._config_limit(config, default=10)
        records = self._socket_records(limit=limit)
        return self._result(records, preview=True)

    def collect(self, config=None):
        validation = self.validate_config(config)
        if not validation["ok"]:
            return {
                "module_id": self.module_id,
                "ok": False,
                "errors": validation["errors"],
                "assets": [],
                "observations": [],
            }

        limit = self._config_limit(config, default=None)
        records = self._socket_records(limit=limit)
        return self._result(records, preview=False)

    @staticmethod
    def _config_limit(config, default):
        if isinstance(config, dict) and "limit" in config:
            return config["limit"]
        return default

    def _result(self, records, preview):
        assets = [self._asset(record) for record in records]
        observations = [
            observation
            for record in records
            for observation in self._observations(record)
        ]
        return {
            "module_id": self.module_id,
            "ok": True,
            "preview": preview,
            "assets": assets,
            "observations": observations,
            "items": [
                {
                    "canonical_asset": asset,
                    "observations": self._observations(record),
                }
                for asset, record in zip(assets, records, strict=False)
            ],
            "count": len(assets),
        }

    @staticmethod
    def _asset(record):
        protocol = record["protocol"]
        local_port = record["local_port"]
        local_ip = record["local_ip"]
        return {
            "asset_type": "network-socket",
            "asset_id": f"socket:{protocol}:{local_ip}:{local_port}",
            "name": f"{protocol}/{local_port}",
            "attributes": {
                "protocol": protocol,
                "local_ip": local_ip,
                "local_port": local_port,
                "state": record.get("state", ""),
            },
        }

    @staticmethod
    def _observations(record):
        protocol = record["protocol"]
        local_port = record["local_port"]
        local_ip = record["local_ip"]
        state = record.get("state", "")
        return [
            {
                "asset_type": "network-socket",
                "asset_id": f"socket:{protocol}:{local_ip}:{local_port}",
                "key": "socket.protocol",
                "value": protocol,
            },
            {
                "asset_type": "network-socket",
                "asset_id": f"socket:{protocol}:{local_ip}:{local_port}",
                "key": "socket.local_ip",
                "value": local_ip,
            },
            {
                "asset_type": "network-socket",
                "asset_id": f"socket:{protocol}:{local_ip}:{local_port}",
                "key": "socket.local_port",
                "value": local_port,
            },
            {
                "asset_type": "network-socket",
                "asset_id": f"socket:{protocol}:{local_ip}:{local_port}",
                "key": "socket.state",
                "value": state,
            },
        ]

    def _socket_records(self, limit=None):
        if limit == 0:
            return []

        if _process_inventory_platform.system() != "Linux":
            return []

        files = (
            ("tcp", "/proc/net/tcp"),
            ("tcp6", "/proc/net/tcp6"),
            ("udp", "/proc/net/udp"),
            ("udp6", "/proc/net/udp6"),
        )
        records: list[dict[str, Any]] = []

        for protocol, path in files:
            records.extend(self._read_socket_file(_ListeningPortsPath(path), protocol))
            if limit is not None and len(records) >= limit:
                break

        records.sort(key=lambda item: (item["protocol"], item["local_port"]))
        if limit is None:
            return records
        return records[:limit]

    def _read_socket_file(self, path, protocol):
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except (FileNotFoundError, PermissionError, OSError):
            return []

        if not lines:
            return []

        records = []
        for line in lines[1:]:
            record = self._parse_socket_row(line, protocol)
            if record is not None:
                records.append(record)
        return records

    @staticmethod
    def _parse_socket_row(line, protocol):
        fields = line.split()
        if len(fields) < 4:
            return None

        local_address = fields[1]
        state = fields[3]

        parsed = ListeningPortsCollectorModule._parse_socket_address(local_address, protocol)
        if parsed is None:
            return None

        local_ip, local_port = parsed
        if protocol in {"tcp", "tcp6"}:
            mapped_state = ListeningPortsCollectorModule._tcp_state_name(state)
            if mapped_state != "LISTEN":
                return None
            return {
                "protocol": protocol,
                "local_ip": local_ip,
                "local_port": local_port,
                "state": mapped_state,
            }

        return {
            "protocol": protocol,
            "local_ip": local_ip,
            "local_port": local_port,
            "state": "udp",
        }

    @staticmethod
    def _parse_socket_address(address, protocol):
        try:
            ip_hex, port_hex = address.rsplit(":", 1)
            local_port = int(port_hex, 16)
        except (TypeError, ValueError):
            return None

        if protocol in {"tcp", "udp"}:
            local_ip = ListeningPortsCollectorModule._decode_ipv4_address(ip_hex)
        elif protocol in {"tcp6", "udp6"}:
            local_ip = ListeningPortsCollectorModule._decode_ipv6_address(ip_hex)
        else:
            return None

        if not local_ip:
            return None

        return local_ip, local_port

    @staticmethod
    def _decode_ipv4_address(ip_hex):
        if len(ip_hex) != 8:
            return ""
        try:
            pairs = [int(ip_hex[index : index + 2], 16) for index in range(0, 8, 2)]
        except ValueError:
            return ""
        return ".".join(str(byte) for byte in reversed(pairs))

    @staticmethod
    def _decode_ipv6_address(ip_hex):
        if len(ip_hex) != 32:
            return ""
        try:
            bytes_value = bytes.fromhex(ip_hex)
        except ValueError:
            return ""
        return str(ipaddress.IPv6Address(bytes_value[::-1]))

    @staticmethod
    def _tcp_state_name(raw_state):
        state = raw_state.upper()
        if state == "0A":
            return "LISTEN"
        if state == "01":
            return "ESTABLISHED"
        return state


class NetworkInterfacesCollectorModule:
    """Read-only collector that inventories local network interfaces from /sys/class/net."""

    module_id = "network-interfaces"
    id = module_id
    collector_id = module_id
    slug = module_id
    name = "Network Interfaces"
    version = "1.0"

    def manifest(self):
        return {
            "module_id": self.module_id,
            "name": self.name,
            "version": self.version,
            "description": "Read-only inventory of local network interface metadata.",
            "asset_type": "network-interface",
            "read_only": True,
            "dependencies": [],
            "platforms": ["linux"],
        }

    def scope(self, config=None):
        return {
            "read_only": True,
            "stdlib_only": True,
            "paths": ["/sys/class/net"],
            "operations": ["read-interface-metadata"],
            "network": False,
            "shell": False,
        }

    def validate_config(self, config=None):
        errors = []
        if config not in (None, {}) and not isinstance(config, dict):
            errors.append("config must be a mapping when provided")

        if isinstance(config, dict) and "limit" in config:
            limit = config["limit"]
            if not isinstance(limit, int) or limit < 0:
                errors.append("limit must be a non-negative integer")

        return {"ok": not errors, "errors": errors}

    def preview(self, config=None):
        validation = self.validate_config(config)
        if not validation["ok"]:
            return {
                "module_id": self.module_id,
                "ok": False,
                "errors": validation["errors"],
                "assets": [],
                "observations": [],
            }

        limit = self._config_limit(config, default=10)
        records = self._interface_records(limit=limit)
        return self._result(records, preview=True)

    def collect(self, config=None):
        validation = self.validate_config(config)
        if not validation["ok"]:
            return {
                "module_id": self.module_id,
                "ok": False,
                "errors": validation["errors"],
                "assets": [],
                "observations": [],
            }

        limit = self._config_limit(config, default=None)
        records = self._interface_records(limit=limit)
        return self._result(records, preview=False)

    @staticmethod
    def _config_limit(config, default):
        if isinstance(config, dict) and "limit" in config:
            return config["limit"]
        return default

    def _result(self, records, preview):
        assets = [self._asset(record) for record in records]
        observations = [
            observation
            for record in records
            for observation in self._observations(record)
        ]
        return {
            "module_id": self.module_id,
            "ok": True,
            "preview": preview,
            "assets": assets,
            "observations": observations,
            "items": [
                {
                    "canonical_asset": asset,
                    "observations": self._observations(record),
                }
                for asset, record in zip(assets, records, strict=False)
            ],
            "count": len(assets),
        }

    @staticmethod
    def _asset(record):
        interface_name = record["interface"]
        return {
            "asset_type": "network-interface",
            "asset_id": f"netif:{interface_name}",
            "name": interface_name,
            "attributes": {
                "interface": interface_name,
                "mac": record.get("mac", ""),
                "operstate": record.get("operstate", ""),
                "mtu": record.get("mtu", ""),
                "type": record.get("type", ""),
                "flags": record.get("flags", ""),
            },
        }

    @staticmethod
    def _observations(record):
        interface_name = record["interface"]
        return [
            {
                "asset_type": "network-interface",
                "asset_id": f"netif:{interface_name}",
                "key": "netif.name",
                "value": interface_name,
            },
            {
                "asset_type": "network-interface",
                "asset_id": f"netif:{interface_name}",
                "key": "netif.mac",
                "value": record.get("mac", ""),
            },
            {
                "asset_type": "network-interface",
                "asset_id": f"netif:{interface_name}",
                "key": "netif.operstate",
                "value": record.get("operstate", ""),
            },
            {
                "asset_type": "network-interface",
                "asset_id": f"netif:{interface_name}",
                "key": "netif.mtu",
                "value": record.get("mtu", ""),
            },
            {
                "asset_type": "network-interface",
                "asset_id": f"netif:{interface_name}",
                "key": "netif.type",
                "value": record.get("type", ""),
            },
            {
                "asset_type": "network-interface",
                "asset_id": f"netif:{interface_name}",
                "key": "netif.flags",
                "value": record.get("flags", ""),
            },
        ]

    def _interface_records(self, limit=None):
        if limit == 0:
            return []

        if _process_inventory_platform.system() != "Linux":
            return []

        sys_net_root = _NetworkInterfacesPath("/sys/class/net")
        if not sys_net_root.exists() or not sys_net_root.is_dir():
            return []

        try:
            entries = list(sys_net_root.iterdir())
        except OSError:
            return []

        records = []
        for entry in entries:
            interface_name = entry.name
            if not interface_name:
                continue

            record = self._read_interface_record(entry)
            if record is None:
                continue

            records.append(record)

        records.sort(key=lambda item: item["interface"])
        if limit is None:
            return records
        return records[:limit]

    def _read_interface_record(self, entry):
        interface_name = entry.name
        if not interface_name:
            return None

        mtu_raw = self._read_interface_file(entry / "mtu")
        return {
            "interface": interface_name,
            "operstate": self._read_interface_file(entry / "operstate"),
            "mac": self._read_interface_file(entry / "address"),
            "mtu": self._coerce_mtu(mtu_raw),
            "type": self._read_interface_file(entry / "type"),
            "flags": self._read_interface_file(entry / "flags"),
        }

    @staticmethod
    def _read_interface_file(path):
        try:
            return path.read_text(encoding="utf-8", errors="replace").strip()
        except (FileNotFoundError, PermissionError, OSError):
            return ""

    @staticmethod
    def _coerce_mtu(value):
        value = value.strip()
        try:
            return int(value)
        except (ValueError, TypeError):
            return value


class FirewallRulesCollectorModule:
    """Read-only collector that inventories host firewall rules from config files."""

    module_id = "firewall-rules"
    id = module_id
    collector_id = module_id
    slug = module_id
    name = "Firewall Rules"
    version = "1.0"

    _config_paths = (
        "/etc/nftables.conf",
        "/etc/iptables/rules.v4",
        "/etc/iptables/rules.v6",
        "/etc/ufw/user.rules",
        "/etc/ufw/user6.rules",
    )

    def manifest(self):
        return {
            "module_id": self.module_id,
            "name": self.name,
            "version": self.version,
            "description": "Read-only inventory of host firewall rules from local config files.",
            "asset_type": "firewall-rule",
            "read_only": True,
            "dependencies": [],
            "platforms": ["linux"],
        }

    def scope(self, config=None):
        return {
            "read_only": True,
            "stdlib_only": True,
            "paths": list(self._config_paths),
            "operations": ["read-firewall-config"],
            "network": False,
            "shell": False,
        }

    def validate_config(self, config=None):
        errors = []
        if config not in (None, {}) and not isinstance(config, dict):
            errors.append("config must be a mapping when provided")

        if isinstance(config, dict) and "limit" in config:
            limit = config["limit"]
            if not isinstance(limit, int) or limit < 0:
                errors.append("limit must be a non-negative integer")

        return {"ok": not errors, "errors": errors}

    def preview(self, config=None):
        validation = self.validate_config(config)
        if not validation["ok"]:
            return {
                "module_id": self.module_id,
                "ok": False,
                "errors": validation["errors"],
                "assets": [],
                "observations": [],
            }

        limit = self._config_limit(config, default=10)
        records = self._firewall_rule_records(limit=limit)
        return self._result(records, preview=True)

    def collect(self, config=None):
        validation = self.validate_config(config)
        if not validation["ok"]:
            return {
                "module_id": self.module_id,
                "ok": False,
                "errors": validation["errors"],
                "assets": [],
                "observations": [],
            }

        limit = self._config_limit(config, default=None)
        records = self._firewall_rule_records(limit=limit)
        return self._result(records, preview=False)

    @staticmethod
    def _config_limit(config, default):
        if isinstance(config, dict) and "limit" in config:
            return config["limit"]
        return default

    def _result(self, records, preview):
        assets = [self._asset(record) for record in records]
        observations = [
            observation
            for record in records
            for observation in self._observations(record)
        ]
        return {
            "module_id": self.module_id,
            "ok": True,
            "preview": preview,
            "assets": assets,
            "observations": observations,
            "items": [
                {
                    "canonical_asset": asset,
                    "observations": self._observations(record),
                }
                for asset, record in zip(assets, records, strict=False)
            ],
            "count": len(assets),
        }

    @staticmethod
    def _asset(record):
        source_basename = record["source_basename"]
        index = record["index"]
        return {
            "asset_type": "firewall-rule",
            "asset_id": f"fwrule:{source_basename}:{index}",
            "name": f"{source_basename}:{index}",
            "attributes": {
                "source_file": record["source_file"],
                "chain": record.get("chain", ""),
                "action": record.get("action", ""),
                "rule_text": record.get("rule_text", ""),
            },
        }

    @staticmethod
    def _observations(record):
        source_basename = record["source_basename"]
        index = record["index"]
        return [
            {
                "asset_type": "firewall-rule",
                "asset_id": f"fwrule:{source_basename}:{index}",
                "key": "firewall.source_file",
                "value": record["source_file"],
            },
            {
                "asset_type": "firewall-rule",
                "asset_id": f"fwrule:{source_basename}:{index}",
                "key": "firewall.chain",
                "value": record.get("chain", ""),
            },
            {
                "asset_type": "firewall-rule",
                "asset_id": f"fwrule:{source_basename}:{index}",
                "key": "firewall.action",
                "value": record.get("action", ""),
            },
            {
                "asset_type": "firewall-rule",
                "asset_id": f"fwrule:{source_basename}:{index}",
                "key": "firewall.rule_text",
                "value": record.get("rule_text", ""),
            },
        ]

    def _firewall_rule_records(self, limit=None):
        if limit == 0:
            return []

        if _process_inventory_platform.system() != "Linux":
            return []

        records: list[dict[str, Any]] = []
        for config_path in self._config_paths:
            path = _FirewallRulesPath(config_path)
            records.extend(self._read_firewall_rule_file(path, config_path))
            if limit is not None and len(records) >= limit:
                break

        records.sort(key=lambda item: (item["source_file"], item["index"]))
        if limit is None:
            return records
        return records[:limit]

    def _read_firewall_rule_file(self, path, source_file):
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except (FileNotFoundError, PermissionError, OSError):
            return []

        records: list[dict[str, Any]] = []
        source_basename = _FirewallRulesPath(source_file).name
        for line in lines:
            record = self._parse_firewall_rule_line(line, source_file, source_basename, len(records) + 1)
            if record is not None:
                records.append(record)
        return records

    @staticmethod
    def _parse_firewall_rule_line(line, source_file, source_basename, index):
        rule_text = line.strip()
        if not rule_text or rule_text.startswith("#"):
            return None

        tokens = rule_text.split()
        chain = ""
        action = FirewallRulesCollectorModule._extract_action(tokens)
        if FirewallRulesCollectorModule._is_nft_rule(tokens):
            chain = FirewallRulesCollectorModule._extract_nft_chain(tokens)
        elif FirewallRulesCollectorModule._is_iptables_rule(tokens):
            chain = FirewallRulesCollectorModule._extract_iptables_chain(tokens)
        elif not FirewallRulesCollectorModule._is_ufw_rule(tokens):
            return None

        return {
            "source_file": source_file,
            "source_basename": source_basename,
            "index": index,
            "chain": chain,
            "action": action,
            "rule_text": rule_text[:300],
        }

    @staticmethod
    def _is_nft_rule(tokens):
        return (
            len(tokens) >= 2
            and ((tokens[0] == "add" and tokens[1] == "rule") or tokens[0] == "chain")
        )

    @staticmethod
    def _is_iptables_rule(tokens):
        return len(tokens) >= 2 and tokens[0] in {"-A", "-I"}

    @staticmethod
    def _is_ufw_rule(tokens):
        return bool(tokens) and tokens[0].lower() in {"allow", "deny", "reject"}

    @staticmethod
    def _extract_nft_chain(tokens):
        if len(tokens) >= 2 and tokens[0] == "chain":
            return tokens[1]

        try:
            rule_index = tokens.index("rule")
        except ValueError:
            return ""

        if len(tokens) > rule_index + 3:
            return tokens[rule_index + 3]
        if len(tokens) > rule_index + 2:
            return tokens[rule_index + 2]
        return ""

    @staticmethod
    def _extract_iptables_chain(tokens):
        if len(tokens) >= 2 and tokens[0] in {"-A", "-I"}:
            return tokens[1]
        return ""

    @staticmethod
    def _extract_action(tokens):
        for index, token in enumerate(tokens):
            if token in {"-j", "--jump", "-g", "--goto"} and len(tokens) > index + 1:
                return tokens[index + 1]

        for token in tokens:
            lowered = token.lower().rstrip(";")
            if lowered in {"accept", "drop", "reject"}:
                return token.rstrip(";")
            if lowered in {"allow", "deny"}:
                return lowered
        return ""


class DatabaseInventoryCollectorModule:
    """Read-only collector that inventories local database engines from config files."""

    module_id = "database-inventory"
    id = module_id
    collector_id = module_id
    slug = module_id
    name = "Database Inventory"
    version = "1.0"

    def manifest(self):
        return {
            "module_id": self.module_id,
            "name": self.name,
            "version": self.version,
            "description": "Read-only inventory of local database engine configuration files.",
            "asset_type": "database-instance",
            "read_only": True,
            "dependencies": [],
            "platforms": ["linux"],
        }

    def scope(self, config=None):
        return {
            "read_only": True,
            "stdlib_only": True,
            "paths": [
                "/etc/postgresql/*/main/postgresql.conf",
                "/etc/mysql/my.cnf",
                "/etc/mysql/mariadb.conf.d/*.cnf",
                "/etc/mongod.conf",
                "/etc/redis/redis.conf",
            ],
            "operations": ["read-database-config"],
            "network": False,
            "shell": False,
        }

    def validate_config(self, config=None):
        errors = []
        if config not in (None, {}) and not isinstance(config, dict):
            errors.append("config must be a mapping when provided")

        if isinstance(config, dict) and "limit" in config:
            limit = config["limit"]
            if not isinstance(limit, int) or limit < 0:
                errors.append("limit must be a non-negative integer")

        return {"ok": not errors, "errors": errors}

    def preview(self, config=None):
        validation = self.validate_config(config)
        if not validation["ok"]:
            return {
                "module_id": self.module_id,
                "ok": False,
                "errors": validation["errors"],
                "assets": [],
                "observations": [],
            }

        limit = self._config_limit(config, default=10)
        records = self._database_records(limit=limit)
        return self._result(records, preview=True)

    def collect(self, config=None):
        validation = self.validate_config(config)
        if not validation["ok"]:
            return {
                "module_id": self.module_id,
                "ok": False,
                "errors": validation["errors"],
                "assets": [],
                "observations": [],
            }

        limit = self._config_limit(config, default=None)
        records = self._database_records(limit=limit)
        return self._result(records, preview=False)

    @staticmethod
    def _config_limit(config, default):
        if isinstance(config, dict) and "limit" in config:
            return config["limit"]
        return default

    def _result(self, records, preview):
        assets = [self._asset(record) for record in records]
        observations = [
            observation
            for record in records
            for observation in self._observations(record)
        ]
        return {
            "module_id": self.module_id,
            "ok": True,
            "preview": preview,
            "assets": assets,
            "observations": observations,
            "items": [
                {
                    "canonical_asset": asset,
                    "observations": self._observations(record),
                }
                for asset, record in zip(assets, records, strict=False)
            ],
            "count": len(assets),
        }

    @staticmethod
    def _asset(record):
        engine = record["engine"]
        return {
            "asset_type": "database-instance",
            "asset_id": f"db:{engine}",
            "name": engine,
            "attributes": {
                "engine": engine,
                "config_file": record.get("config_file", ""),
                "port": record.get("port", ""),
                "data_dir": record.get("data_dir", ""),
                "bind": record.get("bind", ""),
            },
        }

    @staticmethod
    def _observations(record):
        engine = record["engine"]
        return [
            {
                "asset_type": "database-instance",
                "asset_id": f"db:{engine}",
                "key": "database.engine",
                "value": engine,
            },
            {
                "asset_type": "database-instance",
                "asset_id": f"db:{engine}",
                "key": "database.config_file",
                "value": record.get("config_file", ""),
            },
            {
                "asset_type": "database-instance",
                "asset_id": f"db:{engine}",
                "key": "database.port",
                "value": record.get("port", ""),
            },
            {
                "asset_type": "database-instance",
                "asset_id": f"db:{engine}",
                "key": "database.data_dir",
                "value": record.get("data_dir", ""),
            },
            {
                "asset_type": "database-instance",
                "asset_id": f"db:{engine}",
                "key": "database.bind",
                "value": record.get("bind", ""),
            },
        ]

    def _database_records(self, limit=None):
        if limit == 0:
            return []

        if _process_inventory_platform.system() != "Linux":
            return []

        records = []
        for record in (
            self._postgresql_record(),
            self._mysql_record(),
            self._mariadb_record(),
            self._mongodb_record(),
            self._redis_record(),
        ):
            if record is not None:
                records.append(record)

        records.sort(key=lambda item: item["engine"])
        if limit is None:
            return records
        return records[:limit]

    def _postgresql_record(self):
        paths = self._glob_paths("/etc/postgresql", "*/main/postgresql.conf")
        settings = self._read_first_assignment_settings(paths, ("port", "data_directory", "listen_addresses"))
        if settings is None:
            return None

        return self._record(
            "postgresql",
            settings["config_file"],
            port=settings.get("port", ""),
            data_dir=settings.get("data_directory", ""),
            bind=settings.get("listen_addresses", ""),
        )

    def _mysql_record(self):
        paths = [_DatabaseInventoryPath("/etc/mysql/my.cnf")]
        settings = self._read_first_assignment_settings(paths, ("port", "datadir", "bind-address"))
        if settings is None:
            return None

        return self._record(
            "mysql",
            settings["config_file"],
            port=settings.get("port", ""),
            data_dir=settings.get("datadir", ""),
            bind=settings.get("bind-address", ""),
        )

    def _mariadb_record(self):
        paths = self._glob_paths("/etc/mysql/mariadb.conf.d", "*.cnf")
        settings = self._read_first_assignment_settings(paths, ("port", "datadir", "bind-address"))
        if settings is None:
            return None

        return self._record(
            "mariadb",
            settings["config_file"],
            port=settings.get("port", ""),
            data_dir=settings.get("datadir", ""),
            bind=settings.get("bind-address", ""),
        )

    def _mongodb_record(self):
        path = _DatabaseInventoryPath("/etc/mongod.conf")
        settings = self._read_first_colon_settings([path], ("port", "dbpath", "bindip"))
        if settings is None:
            return None

        return self._record(
            "mongodb",
            settings["config_file"],
            port=settings.get("port", ""),
            data_dir=settings.get("dbpath", ""),
            bind=settings.get("bindip", ""),
        )

    def _redis_record(self):
        path = _DatabaseInventoryPath("/etc/redis/redis.conf")
        settings = self._read_first_assignment_settings([path], ("port", "dir", "bind"))
        if settings is None:
            return None

        return self._record(
            "redis",
            settings["config_file"],
            port=settings.get("port", ""),
            data_dir=settings.get("dir", ""),
            bind=settings.get("bind", ""),
        )

    @staticmethod
    def _record(engine, config_file, *, port="", data_dir="", bind=""):
        return {
            "engine": engine,
            "config_file": config_file,
            "port": str(port),
            "data_dir": data_dir,
            "bind": bind,
        }

    @staticmethod
    def _glob_paths(root, pattern):
        try:
            return sorted(_DatabaseInventoryPath(root).glob(pattern), key=lambda path: str(path))
        except OSError:
            return []

    def _read_first_assignment_settings(self, paths, keys):
        for path in paths:
            text = self._read_database_config(path)
            if text is None:
                continue
            settings = self._parse_assignment_settings(text, keys)
            settings["config_file"] = str(path)
            return settings
        return None

    def _read_first_colon_settings(self, paths, keys):
        for path in paths:
            text = self._read_database_config(path)
            if text is None:
                continue
            settings = self._parse_colon_settings(text, keys)
            settings["config_file"] = str(path)
            return settings
        return None

    @staticmethod
    def _read_database_config(path):
        try:
            if not path.exists() or not path.is_file():
                return None
            return path.read_text(encoding="utf-8", errors="replace")
        except (FileNotFoundError, PermissionError, OSError):
            return None

    @classmethod
    def _parse_assignment_settings(cls, text, keys):
        wanted = {key.lower() for key in keys}
        settings = {}
        for line in text.splitlines():
            stripped = cls._strip_config_comment(line).strip()
            if not stripped or stripped.startswith("["):
                continue

            if "=" in stripped:
                key, value = stripped.split("=", 1)
            else:
                parts = stripped.split(None, 1)
                if len(parts) != 2:
                    continue
                key, value = parts

            normalized_key = key.strip().lower()
            if normalized_key in wanted:
                settings[normalized_key] = cls._clean_config_value(value)
        return settings

    @classmethod
    def _parse_colon_settings(cls, text, keys):
        wanted = {key.lower() for key in keys}
        settings = {}
        for line in text.splitlines():
            stripped = cls._strip_config_comment(line).strip()
            if ":" not in stripped:
                continue
            key, value = stripped.split(":", 1)
            normalized_key = key.strip().lower()
            if normalized_key in wanted:
                settings[normalized_key] = cls._clean_config_value(value)
        return settings

    @staticmethod
    def _strip_config_comment(line):
        in_single = False
        in_double = False
        for index, character in enumerate(line):
            if character == "'" and not in_double:
                in_single = not in_single
            elif character == '"' and not in_single:
                in_double = not in_double
            elif character == "#" and not in_single and not in_double:
                return line[:index]
        return line

    @staticmethod
    def _clean_config_value(value):
        cleaned = value.strip().strip(",")
        if len(cleaned) >= 2 and cleaned[0] == cleaned[-1] and cleaned[0] in {"'", '"'}:
            cleaned = cleaned[1:-1]
        return cleaned.strip()

class WifiInventoryCollectorModule:
    """Read-only collector that inventories local Wi-Fi interfaces."""

    module_id = "wifi-inventory"
    id = module_id
    collector_id = module_id
    slug = module_id
    name = "Wi-Fi Inventory"
    version = "1.0"

    def manifest(self):
        return {
            "module_id": self.module_id,
            "name": self.name,
            "version": self.version,
            "description": "Read-only inventory of local wireless interface metadata.",
            "asset_type": "wifi-interface",
            "read_only": True,
            "dependencies": [],
            "platforms": ["linux"],
        }

    def scope(self, config=None):
        return {
            "read_only": True,
            "stdlib_only": True,
            "paths": ["/proc/net/wireless", "/sys/class/net"],
            "operations": ["read-wireless-interface-metadata"],
            "network": False,
            "shell": False,
        }

    def validate_config(self, config=None):
        errors = []
        if config not in (None, {}) and not isinstance(config, dict):
            errors.append("config must be a mapping when provided")

        if isinstance(config, dict) and "limit" in config:
            limit = config["limit"]
            if not isinstance(limit, int) or limit < 0:
                errors.append("limit must be a non-negative integer")

        return {"ok": not errors, "errors": errors}

    def preview(self, config=None):
        validation = self.validate_config(config)
        if not validation["ok"]:
            return {
                "module_id": self.module_id,
                "ok": False,
                "errors": validation["errors"],
                "assets": [],
                "observations": [],
            }

        limit = self._config_limit(config, default=10)
        records = self._wifi_records(limit=limit)
        return self._result(records, preview=True)

    def collect(self, config=None):
        validation = self.validate_config(config)
        if not validation["ok"]:
            return {
                "module_id": self.module_id,
                "ok": False,
                "errors": validation["errors"],
                "assets": [],
                "observations": [],
            }

        limit = self._config_limit(config, default=None)
        records = self._wifi_records(limit=limit)
        return self._result(records, preview=False)

    @staticmethod
    def _config_limit(config, default):
        if isinstance(config, dict) and "limit" in config:
            return config["limit"]
        return default

    def _result(self, records, preview):
        assets = [self._asset(record) for record in records]
        observations = [
            observation
            for record in records
            for observation in self._observations(record)
        ]
        return {
            "module_id": self.module_id,
            "ok": True,
            "preview": preview,
            "assets": assets,
            "observations": observations,
            "items": [
                {
                    "canonical_asset": asset,
                    "observations": self._observations(record),
                }
                for asset, record in zip(assets, records, strict=False)
            ],
            "count": len(assets),
        }

    @staticmethod
    def _asset(record):
        interface_name = record["interface"]
        return {
            "asset_type": "wifi-interface",
            "asset_id": f"wifi:{interface_name}",
            "name": interface_name,
            "attributes": {
                "interface": interface_name,
                "mac": record.get("mac", ""),
                "operstate": record.get("operstate", ""),
                "link": record.get("link", ""),
                "level": record.get("level", ""),
                "noise": record.get("noise", ""),
            },
        }

    @staticmethod
    def _observations(record):
        interface_name = record["interface"]
        return [
            {
                "asset_type": "wifi-interface",
                "asset_id": f"wifi:{interface_name}",
                "key": "wifi.interface",
                "value": interface_name,
            },
            {
                "asset_type": "wifi-interface",
                "asset_id": f"wifi:{interface_name}",
                "key": "wifi.mac",
                "value": record.get("mac", ""),
            },
            {
                "asset_type": "wifi-interface",
                "asset_id": f"wifi:{interface_name}",
                "key": "wifi.operstate",
                "value": record.get("operstate", ""),
            },
            {
                "asset_type": "wifi-interface",
                "asset_id": f"wifi:{interface_name}",
                "key": "wifi.link",
                "value": record.get("link", ""),
            },
            {
                "asset_type": "wifi-interface",
                "asset_id": f"wifi:{interface_name}",
                "key": "wifi.level",
                "value": record.get("level", ""),
            },
            {
                "asset_type": "wifi-interface",
                "asset_id": f"wifi:{interface_name}",
                "key": "wifi.noise",
                "value": record.get("noise", ""),
            },
        ]

    def _wifi_records(self, limit=None):
        if limit == 0:
            return []

        if _process_inventory_platform.system() != "Linux":
            return []

        wireless_path = _WifiInventoryPath("/proc/net/wireless")
        sys_net_root = _WifiInventoryPath("/sys/class/net")
        proc_records = self._wireless_rows(wireless_path)
        interface_names = set(proc_records)

        interface_names.update(self._wireless_interfaces_from_sys(sys_net_root))
        if not interface_names:
            return []

        records = []
        for interface_name in sorted(interface_names):
            sys_record = self._read_sys_wifi_record(sys_net_root / interface_name)
            record = {
                "interface": interface_name,
                "mac": sys_record.get("mac", ""),
                "operstate": sys_record.get("operstate", ""),
                "link": proc_records.get(interface_name, {}).get("link", ""),
                "level": proc_records.get(interface_name, {}).get("level", ""),
                "noise": proc_records.get(interface_name, {}).get("noise", ""),
            }
            records.append(record)

        if limit is None:
            return records
        return records[:limit]

    def _wireless_rows(self, path):
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except (FileNotFoundError, PermissionError, OSError):
            return {}

        records = {}
        for line in lines[2:]:
            record = self._parse_wireless_row(line)
            if record is not None:
                records[record["interface"]] = record
        return records

    @staticmethod
    def _parse_wireless_row(line):
        fields = line.split()
        if len(fields) < 5:
            return None

        interface_name = fields[0].rstrip(":")
        if not interface_name:
            return None

        return {
            "interface": interface_name,
            "link": fields[2],
            "level": fields[3],
            "noise": fields[4],
        }

    @staticmethod
    def _wireless_interfaces_from_sys(sys_net_root):
        if not sys_net_root.exists() or not sys_net_root.is_dir():
            return []

        try:
            entries = list(sys_net_root.iterdir())
        except OSError:
            return []

        interfaces = []
        for entry in entries:
            if entry.name and (entry / "wireless").is_dir():
                interfaces.append(entry.name)
        return interfaces

    def _read_sys_wifi_record(self, entry):
        return {
            "mac": self._read_wifi_file(entry / "address"),
            "operstate": self._read_wifi_file(entry / "operstate"),
        }

    @staticmethod
    def _read_wifi_file(path):
        try:
            return path.read_text(encoding="utf-8", errors="replace").strip()
        except (FileNotFoundError, PermissionError, OSError):
            return ""

class RoutingTableCollectorModule:
    """Read-only collector that inventories local IPv4 and IPv6 routes from /proc/net."""

    module_id = "routing-table"
    id = module_id
    collector_id = module_id
    slug = module_id
    name = "Routing Table"
    version = "1.0"

    def manifest(self):
        return {
            "module_id": self.module_id,
            "name": self.name,
            "version": self.version,
            "description": "Read-only inventory of local IPv4 and IPv6 routing table entries.",
            "asset_type": "route",
            "read_only": True,
            "dependencies": [],
            "platforms": ["linux"],
        }

    def scope(self, config=None):
        return {
            "read_only": True,
            "stdlib_only": True,
            "paths": ["/proc/net/route", "/proc/net/ipv6_route"],
            "operations": ["read-routing-table"],
            "network": False,
            "shell": False,
        }

    def validate_config(self, config=None):
        errors = []
        if config not in (None, {}) and not isinstance(config, dict):
            errors.append("config must be a mapping when provided")

        if isinstance(config, dict) and "limit" in config:
            limit = config["limit"]
            if not isinstance(limit, int) or limit < 0:
                errors.append("limit must be a non-negative integer")

        return {"ok": not errors, "errors": errors}

    def preview(self, config=None):
        validation = self.validate_config(config)
        if not validation["ok"]:
            return {
                "module_id": self.module_id,
                "ok": False,
                "errors": validation["errors"],
                "assets": [],
                "observations": [],
            }

        limit = self._config_limit(config, default=10)
        records = self._route_records(limit=limit)
        return self._result(records, preview=True)

    def collect(self, config=None):
        validation = self.validate_config(config)
        if not validation["ok"]:
            return {
                "module_id": self.module_id,
                "ok": False,
                "errors": validation["errors"],
                "assets": [],
                "observations": [],
            }

        limit = self._config_limit(config, default=None)
        records = self._route_records(limit=limit)
        return self._result(records, preview=False)

    @staticmethod
    def _config_limit(config, default):
        if isinstance(config, dict) and "limit" in config:
            return config["limit"]
        return default

    def _result(self, records, preview):
        assets = [self._asset(record) for record in records]
        observations = [
            observation
            for record in records
            for observation in self._observations(record)
        ]
        return {
            "module_id": self.module_id,
            "ok": True,
            "preview": preview,
            "assets": assets,
            "observations": observations,
            "items": [
                {
                    "canonical_asset": asset,
                    "observations": self._observations(record),
                }
                for asset, record in zip(assets, records, strict=False)
            ],
            "count": len(assets),
        }

    @staticmethod
    def _asset(record):
        family = record["family"]
        interface = record["interface"]
        destination = record["destination"]
        gateway = record["gateway"]
        index = record["index"]
        return {
            "asset_type": "route",
            "asset_id": f"route:{family}:{interface}:{destination}/{index}",
            "name": f"{destination} via {gateway} dev {interface}",
            "attributes": {
                "family": family,
                "interface": interface,
                "destination": destination,
                "gateway": gateway,
                "mask": record["mask"],
                "flags": record["flags"],
            },
        }

    @staticmethod
    def _observations(record):
        family = record["family"]
        interface = record["interface"]
        destination = record["destination"]
        index = record["index"]
        asset_id = f"route:{family}:{interface}:{destination}/{index}"
        return [
            {
                "asset_type": "route",
                "asset_id": asset_id,
                "key": "route.family",
                "value": family,
            },
            {
                "asset_type": "route",
                "asset_id": asset_id,
                "key": "route.interface",
                "value": interface,
            },
            {
                "asset_type": "route",
                "asset_id": asset_id,
                "key": "route.destination",
                "value": destination,
            },
            {
                "asset_type": "route",
                "asset_id": asset_id,
                "key": "route.gateway",
                "value": record["gateway"],
            },
            {
                "asset_type": "route",
                "asset_id": asset_id,
                "key": "route.mask",
                "value": record["mask"],
            },
            {
                "asset_type": "route",
                "asset_id": asset_id,
                "key": "route.flags",
                "value": record["flags"],
            },
        ]

    def _route_records(self, limit=None):
        if limit == 0:
            return []

        if _process_inventory_platform.system() != "Linux":
            return []

        records = []
        records.extend(self._read_ipv4_route_file(_RoutingTablePath("/proc/net/route")))
        records.extend(self._read_ipv6_route_file(_RoutingTablePath("/proc/net/ipv6_route")))
        records.sort(key=lambda item: (item["family"], item["interface"], item["destination"]))
        if limit is None:
            return records
        return records[:limit]

    def _read_ipv4_route_file(self, path):
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except (FileNotFoundError, PermissionError, OSError):
            return []

        if not lines:
            return []

        records = []
        for index, line in enumerate(lines[1:]):
            record = self._parse_ipv4_route_row(line, index)
            if record is not None:
                records.append(record)
        return records

    def _read_ipv6_route_file(self, path):
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except (FileNotFoundError, PermissionError, OSError):
            return []

        records = []
        for index, line in enumerate(lines):
            record = self._parse_ipv6_route_row(line, index)
            if record is not None:
                records.append(record)
        return records

    @staticmethod
    def _parse_ipv4_route_row(line, index):
        fields = line.split()
        if len(fields) < 8:
            return None

        destination = RoutingTableCollectorModule._decode_ipv4_address(fields[1])
        gateway = RoutingTableCollectorModule._decode_ipv4_address(fields[2])
        mask = RoutingTableCollectorModule._decode_ipv4_address(fields[7])
        if not destination or not gateway or not mask:
            return None

        return {
            "family": "ipv4",
            "interface": fields[0],
            "destination": destination,
            "gateway": gateway,
            "mask": mask,
            "flags": fields[3],
            "index": index,
        }

    @staticmethod
    def _parse_ipv6_route_row(line, index):
        fields = line.split()
        if len(fields) < 10:
            return None

        destination = RoutingTableCollectorModule._decode_ipv6_address(fields[0])
        gateway = RoutingTableCollectorModule._decode_ipv6_address(fields[4])
        if not destination or not gateway:
            return None

        try:
            mask = int(fields[1], 16)
        except ValueError:
            return None

        return {
            "family": "ipv6",
            "interface": fields[-1],
            "destination": destination,
            "gateway": gateway,
            "mask": mask,
            "flags": fields[8],
            "index": index,
        }

    @staticmethod
    def _decode_ipv4_address(ip_hex):
        if len(ip_hex) != 8:
            return ""
        try:
            pairs = [int(ip_hex[index : index + 2], 16) for index in range(0, 8, 2)]
        except ValueError:
            return ""
        return ".".join(str(byte) for byte in reversed(pairs))

    @staticmethod
    def _decode_ipv6_address(ip_hex):
        if len(ip_hex) != 32:
            return ""
        try:
            bytes_value = bytes.fromhex(ip_hex)
        except ValueError:
            return ""
        return str(ipaddress.IPv6Address(bytes_value))


def _read_process_inventory_text(path):
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except (FileNotFoundError, PermissionError, ProcessLookupError, OSError):
        return ""


def _read_process_inventory_cmdline(path):
    try:
        raw = path.read_bytes()
    except (FileNotFoundError, PermissionError, ProcessLookupError, OSError):
        return ""

    parts = [part.decode("utf-8", errors="replace") for part in raw.split(b"\0") if part]
    return " ".join(parts)


def _register_process_inventory_collector():
    module = ProcessInventoryCollectorModule()
    registered = False

    registry_names = set(
        (
        "MODULE_REGISTRY",
        "COLLECTOR_MODULES",
        "COLLECTOR_REGISTRY",
        "COLLECTORS",
        "collector_registry",
        )
    )
    registry_names.update(
        name
        for name, value in globals().items()
        if isinstance(value, (dict, list, set))
        and any(token in name.upper() for token in ("COLLECT", "MODULE", "REGISTRY"))
    )

    for registry_name in registry_names:
        registry = globals().get(registry_name)
        if isinstance(registry, dict):
            registry[module.module_id] = module
            registered = True
            continue

        if isinstance(registry, list):
            if not any(getattr(item, "module_id", None) == module.module_id for item in registry):
                registry.append(module)
            registered = True
            continue

        if isinstance(registry, set):
            registry.add(module)
            registered = True
            continue

        if isinstance(registry, tuple):
            if not any(getattr(item, "module_id", None) == module.module_id for item in registry):
                globals()[registry_name] = registry + (module,)
            registered = True
            continue

        register = getattr(registry, "register", None)
        if callable(register):
            try:
                register(module.module_id, module)
            except TypeError:
                register(module)
            registered = True

    if not registered:
        globals()["MODULE_REGISTRY"] = {module.module_id: module}

    exported = globals().get("__all__")
    if isinstance(exported, list) and "ProcessInventoryCollectorModule" not in exported:
        exported.append("ProcessInventoryCollectorModule")


_register_process_inventory_collector()


def _register_listening_ports_collector():
    module = ListeningPortsCollectorModule()
    registered = False

    registry_names = set(
        (
        "MODULE_REGISTRY",
        "COLLECTOR_MODULES",
        "COLLECTOR_REGISTRY",
        "COLLECTORS",
        "collector_registry",
        )
    )
    registry_names.update(
        name
        for name, value in globals().items()
        if isinstance(value, (dict, list, set))
        and any(token in name.upper() for token in ("COLLECT", "MODULE", "REGISTRY"))
    )

    for registry_name in registry_names:
        registry = globals().get(registry_name)
        if isinstance(registry, dict):
            registry[module.module_id] = module
            registered = True
            continue

        if isinstance(registry, list):
            if not any(getattr(item, "module_id", None) == module.module_id for item in registry):
                registry.append(module)
            registered = True
            continue

        if isinstance(registry, set):
            registry.add(module)
            registered = True
            continue

        if isinstance(registry, tuple):
            if not any(getattr(item, "module_id", None) == module.module_id for item in registry):
                globals()[registry_name] = registry + (module,)
            registered = True
            continue

        register = getattr(registry, "register", None)
        if callable(register):
            try:
                register(module.module_id, module)
            except TypeError:
                register(module)
            registered = True

    if not registered:
        globals()["MODULE_REGISTRY"] = {module.module_id: module}

    exported = globals().get("__all__")
    if isinstance(exported, list) and "ListeningPortsCollectorModule" not in exported:
        exported.append("ListeningPortsCollectorModule")


_register_listening_ports_collector()


def _register_network_interfaces_collector():
    module = NetworkInterfacesCollectorModule()
    registered = False

    registry_names = set(
        (
            "MODULE_REGISTRY",
            "COLLECTOR_MODULES",
            "COLLECTOR_REGISTRY",
            "COLLECTORS",
            "collector_registry",
        )
    )
    registry_names.update(
        name
        for name, value in globals().items()
        if isinstance(value, (dict, list, set))
        and any(token in name.upper() for token in ("COLLECT", "MODULE", "REGISTRY"))
    )

    for registry_name in registry_names:
        registry = globals().get(registry_name)
        if isinstance(registry, dict):
            registry[module.module_id] = module
            registered = True
            continue

        if isinstance(registry, list):
            if not any(getattr(item, "module_id", None) == module.module_id for item in registry):
                registry.append(module)
            registered = True
            continue

        if isinstance(registry, set):
            registry.add(module)
            registered = True
            continue

        if isinstance(registry, tuple):
            if not any(getattr(item, "module_id", None) == module.module_id for item in registry):
                globals()[registry_name] = registry + (module,)
            registered = True
            continue

        register = getattr(registry, "register", None)
        if callable(register):
            try:
                register(module.module_id, module)
            except TypeError:
                register(module)
            registered = True

    if not registered:
        globals()["MODULE_REGISTRY"] = {module.module_id: module}

    exported = globals().get("__all__")
    if isinstance(exported, list) and "NetworkInterfacesCollectorModule" not in exported:
        exported.append("NetworkInterfacesCollectorModule")


_register_network_interfaces_collector()


def _register_firewall_rules_collector():
    module = FirewallRulesCollectorModule()
    registered = False

    registry_names = set(
        (
            "MODULE_REGISTRY",
            "COLLECTOR_MODULES",
            "COLLECTOR_REGISTRY",
            "COLLECTORS",
            "collector_registry",
        )
    )
    registry_names.update(
        name
        for name, value in globals().items()
        if isinstance(value, (dict, list, set))
        and any(token in name.upper() for token in ("COLLECT", "MODULE", "REGISTRY"))
    )

    for registry_name in registry_names:
        registry = globals().get(registry_name)
        if isinstance(registry, dict):
            registry[module.module_id] = module
            registered = True
            continue

        if isinstance(registry, list):
            if not any(getattr(item, "module_id", None) == module.module_id for item in registry):
                registry.append(module)
            registered = True
            continue

        if isinstance(registry, set):
            registry.add(module)
            registered = True
            continue

        if isinstance(registry, tuple):
            if not any(getattr(item, "module_id", None) == module.module_id for item in registry):
                globals()[registry_name] = registry + (module,)
            registered = True
            continue

        register = getattr(registry, "register", None)
        if callable(register):
            try:
                register(module.module_id, module)
            except TypeError:
                register(module)
            registered = True

    if not registered:
        globals()["MODULE_REGISTRY"] = {module.module_id: module}

    exported = globals().get("__all__")
    if isinstance(exported, list) and "FirewallRulesCollectorModule" not in exported:
        exported.append("FirewallRulesCollectorModule")


_register_firewall_rules_collector()


def _register_database_inventory_collector():
    module = DatabaseInventoryCollectorModule()
    registered = False

    registry_names = set(
        (
            "MODULE_REGISTRY",
            "COLLECTOR_MODULES",
            "COLLECTOR_REGISTRY",
            "COLLECTORS",
            "collector_registry",
        )
    )
    registry_names.update(
        name
        for name, value in globals().items()
        if isinstance(value, (dict, list, set))
        and any(token in name.upper() for token in ("COLLECT", "MODULE", "REGISTRY"))
    )

    for registry_name in registry_names:
        registry = globals().get(registry_name)
        if isinstance(registry, dict):
            registry[module.module_id] = module
            registered = True
            continue

        if isinstance(registry, list):
            if not any(getattr(item, "module_id", None) == module.module_id for item in registry):
                registry.append(module)
            registered = True
            continue

        if isinstance(registry, set):
            registry.add(module)
            registered = True
            continue

        if isinstance(registry, tuple):
            if not any(getattr(item, "module_id", None) == module.module_id for item in registry):
                globals()[registry_name] = registry + (module,)
            registered = True
            continue

        register = getattr(registry, "register", None)
        if callable(register):
            try:
                register(module.module_id, module)
            except TypeError:
                register(module)
            registered = True

    if not registered:
        globals()["MODULE_REGISTRY"] = {module.module_id: module}

    exported = globals().get("__all__")
    if isinstance(exported, list) and "DatabaseInventoryCollectorModule" not in exported:
        exported.append("DatabaseInventoryCollectorModule")


_register_database_inventory_collector()


def _register_wifi_inventory_collector():
    module = WifiInventoryCollectorModule()
    registered = False

    registry_names = set(
        (
            "MODULE_REGISTRY",
            "COLLECTOR_MODULES",
            "COLLECTOR_REGISTRY",
            "COLLECTORS",
            "collector_registry",
        )
    )
    registry_names.update(
        name
        for name, value in globals().items()
        if isinstance(value, (dict, list, set))
        and any(token in name.upper() for token in ("COLLECT", "MODULE", "REGISTRY"))
    )

    for registry_name in registry_names:
        registry = globals().get(registry_name)
        if isinstance(registry, dict):
            registry[module.module_id] = module
            registered = True
            continue

        if isinstance(registry, list):
            if not any(getattr(item, "module_id", None) == module.module_id for item in registry):
                registry.append(module)
            registered = True
            continue

        if isinstance(registry, set):
            registry.add(module)
            registered = True
            continue

        if isinstance(registry, tuple):
            if not any(getattr(item, "module_id", None) == module.module_id for item in registry):
                globals()[registry_name] = registry + (module,)
            registered = True
            continue

        register = getattr(registry, "register", None)
        if callable(register):
            try:
                register(module.module_id, module)
            except TypeError:
                register(module)
            registered = True

    if not registered:
        globals()["MODULE_REGISTRY"] = {module.module_id: module}

    exported = globals().get("__all__")
    if isinstance(exported, list) and "WifiInventoryCollectorModule" not in exported:
        exported.append("WifiInventoryCollectorModule")


_register_wifi_inventory_collector()


def _register_routing_table_collector():
    module = RoutingTableCollectorModule()
    registered = False

    registry_names = set(
        (
            "MODULE_REGISTRY",
            "COLLECTOR_MODULES",
            "COLLECTOR_REGISTRY",
            "COLLECTORS",
            "collector_registry",
        )
    )
    registry_names.update(
        name
        for name, value in globals().items()
        if isinstance(value, (dict, list, set))
        and any(token in name.upper() for token in ("COLLECT", "MODULE", "REGISTRY"))
    )

    for registry_name in registry_names:
        registry = globals().get(registry_name)
        if isinstance(registry, dict):
            registry[module.module_id] = module
            registered = True
            continue

        if isinstance(registry, list):
            if not any(getattr(item, "module_id", None) == module.module_id for item in registry):
                registry.append(module)
            registered = True
            continue

        if isinstance(registry, set):
            registry.add(module)
            registered = True
            continue

        if isinstance(registry, tuple):
            if not any(getattr(item, "module_id", None) == module.module_id for item in registry):
                globals()[registry_name] = registry + (module,)
            registered = True
            continue

        register = getattr(registry, "register", None)
        if callable(register):
            try:
                register(module.module_id, module)
            except TypeError:
                register(module)
            registered = True

    if not registered:
        globals()["MODULE_REGISTRY"] = {module.module_id: module}

    exported = globals().get("__all__")
    if isinstance(exported, list) and "RoutingTableCollectorModule" not in exported:
        exported.append("RoutingTableCollectorModule")


_register_routing_table_collector()
