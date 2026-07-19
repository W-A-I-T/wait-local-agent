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

        records = []
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
