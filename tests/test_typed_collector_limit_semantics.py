"""Regression tests for typed collector source scanning and limit semantics."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from wait_local_agent import collectors
from wait_local_agent.collectors import CollectionStatus, SourceOutcome


def _failure(source_id: str) -> SourceOutcome:
    return SourceOutcome(
        source_id=source_id,
        status=CollectionStatus.UNAVAILABLE,
        error_code="collection_unavailable",
        error_detail="source failed",
    )


def test_process_limit_scans_later_sources(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    (tmp_path / "1").mkdir()
    (tmp_path / "2").mkdir()
    monkeypatch.setattr(collectors, "_ProcessInventoryPath", lambda _path: tmp_path)
    monkeypatch.setattr(collectors._process_inventory_platform, "system", lambda: "Linux")
    module = collectors.ProcessInventoryCollectorModule()

    def read(entry: Path, *, strict: bool = False) -> dict[str, object]:
        if entry.name == "2":
            raise PermissionError("later process source failed")
        return {"pid": 1, "name": "first", "cmdline": "", "state": "R"}

    monkeypatch.setattr(module, "_read_proc_entry", read)
    collection = module._process_records_with_outcomes(limit=1, strict=True)
    typed = collectors.ProcessInventoryCollector()
    typed._legacy_module = module
    result = typed.collect({"limit": 1})

    assert len(collection.records) == 1
    assert collection.source_outcomes[0].status is CollectionStatus.NOT_AUTHORIZED
    assert result.status is CollectionStatus.PARTIAL


def test_listening_ports_limit_scans_later_sources(monkeypatch: pytest.MonkeyPatch) -> None:
    module = collectors.ListeningPortsCollectorModule()
    record = {"protocol": "tcp", "local_ip": "127.0.0.1", "local_port": 22, "state": "LISTEN"}

    def read(_path: Path, protocol: str, *, strict: bool = False) -> list[dict[str, object]]:
        if protocol == "tcp6":
            raise OSError("later socket source failed")
        return [record] if protocol == "tcp" else []

    monkeypatch.setattr(module, "_read_socket_file", read)
    collection = module._socket_records_with_outcomes(limit=1, strict=True)
    typed = collectors.ListeningPortsCollector()
    typed._legacy_module = module
    result = typed.collect({"limit": 1})

    assert len(collection.records) == 1
    assert collection.source_outcomes[0].status is CollectionStatus.UNAVAILABLE
    assert result.status is CollectionStatus.PARTIAL


def test_network_interfaces_limit_scans_later_sources(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / "eth0").mkdir()
    (tmp_path / "eth1").mkdir()
    monkeypatch.setattr(collectors, "_NetworkInterfacesPath", lambda _path: tmp_path)
    monkeypatch.setattr(collectors._process_inventory_platform, "system", lambda: "Linux")
    module = collectors.NetworkInterfacesCollectorModule()

    def read(entry: Path, *, strict: bool = False) -> dict[str, object]:
        if entry.name == "eth1":
            raise PermissionError("later interface source failed")
        return {
            "interface": "eth0",
            "operstate": "up",
            "mac": "00:00:00:00:00:01",
            "mtu": 1500,
            "type": "1",
            "flags": "1",
        }

    monkeypatch.setattr(module, "_read_interface_record", read)
    collection = module._interface_records_with_outcomes(limit=1, strict=True)
    typed = collectors.NetworkInterfacesCollector()
    typed._legacy_module = module
    result = typed.collect({"limit": 1})

    assert len(collection.records) == 1
    assert collection.source_outcomes[0].status is CollectionStatus.NOT_AUTHORIZED
    assert result.status is CollectionStatus.PARTIAL


def test_firewall_limit_scans_later_sources(monkeypatch: pytest.MonkeyPatch) -> None:
    module = collectors.FirewallRulesCollectorModule()
    monkeypatch.setattr(module, "_config_paths", ("first.conf", "later.conf"))
    record = {
        "source_file": "first.conf",
        "source_basename": "first.conf",
        "chain": "INPUT",
        "action": "ACCEPT",
        "rule_text": "-A INPUT -j ACCEPT",
        "index": 1,
    }

    def read(_path: Path, source_file: str, *, strict: bool = False) -> list[dict[str, object]]:
        if source_file == "later.conf":
            raise OSError("later firewall source failed")
        return [record]

    monkeypatch.setattr(module, "_read_firewall_rule_file", read)
    collection = module._firewall_rule_records_with_outcomes(limit=1, strict=True)
    typed = collectors.FirewallRulesCollector()
    typed._legacy_module = module
    result = typed.collect({"limit": 1})

    assert len(collection.records) == 1
    assert collection.source_outcomes[0].status is CollectionStatus.UNAVAILABLE
    assert result.status is CollectionStatus.PARTIAL


def test_database_limit_scans_later_sources(monkeypatch: pytest.MonkeyPatch) -> None:
    module = collectors.DatabaseInventoryCollectorModule()
    record = {"engine": "postgresql", "config_file": "/etc/postgresql.conf", "port": "5432", "data_dir": "", "bind": ""}
    monkeypatch.setattr(module, "_postgresql_record", lambda *, strict=False: record)
    monkeypatch.setattr(
        module,
        "_mysql_record",
        lambda *, strict=False: (_ for _ in ()).throw(OSError("later database source failed")),
    )

    collection = module._database_records_with_outcomes(limit=1, strict=True)
    typed = collectors.DatabaseInventoryCollector()
    typed._legacy_module = module
    result = typed.collect({"limit": 1})

    assert len(collection.records) == 1
    assert collection.source_outcomes[0].status is CollectionStatus.UNAVAILABLE
    assert result.status is CollectionStatus.PARTIAL


def test_wifi_limit_scans_later_sources(monkeypatch: pytest.MonkeyPatch) -> None:
    module = collectors.WifiInventoryCollectorModule()
    monkeypatch.setattr(module, "_wireless_rows", lambda _path, *, strict=False: {"wlan0": {}, "wlan1": {}})
    monkeypatch.setattr(module, "_wireless_interfaces_from_sys", lambda _path, *, strict=False: [])

    def read(entry: Path, *, strict: bool = False) -> dict[str, str]:
        if entry.name == "wlan1":
            raise PermissionError("later wifi source failed")
        return {"mac": "00:00:00:00:00:01", "operstate": "up"}

    monkeypatch.setattr(module, "_read_sys_wifi_record", read)
    collection = module._wifi_records_with_outcomes(limit=1, strict=True)
    typed = collectors.WifiInventoryCollector()
    typed._legacy_module = module
    result = typed.collect({"limit": 1})

    assert len(collection.records) == 1
    assert collection.source_outcomes[0].status is CollectionStatus.NOT_AUTHORIZED
    assert result.status is CollectionStatus.PARTIAL


def test_routing_table_limit_scans_later_sources(monkeypatch: pytest.MonkeyPatch) -> None:
    module = collectors.RoutingTableCollectorModule()
    record = {
        "family": "ipv4",
        "interface": "eth0",
        "destination": "0.0.0.0",
        "gateway": "192.168.1.1",
        "mask": "0.0.0.0",
        "flags": "0003",
        "index": 0,
    }
    monkeypatch.setattr(module, "_read_ipv4_route_file", lambda *args, **kwargs: [record])
    monkeypatch.setattr(
        module,
        "_read_ipv6_route_file",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("later route source failed")),
    )

    collection = module._route_records_with_outcomes(limit=1, strict=True)
    typed = collectors.RoutingTableCollector()
    typed._legacy_module = module
    result = typed.collect({"limit": 1})

    assert len(collection.records) == 1
    assert collection.source_outcomes[0].status is CollectionStatus.UNAVAILABLE
    assert result.status is CollectionStatus.PARTIAL


def test_endpoint_agents_limit_scans_later_sources(monkeypatch: pytest.MonkeyPatch) -> None:
    module = collectors.EndpointAgentsCollectorModule()
    first_markers = module._AGENT_MARKERS[0][2]

    def detect(markers: tuple[str, ...], *, strict: bool = False) -> str:
        if markers == first_markers:
            return "/opt/CrowdStrike"
        raise PermissionError("later endpoint-agent source failed")

    monkeypatch.setattr(module, "_first_existing_marker", detect)
    collection = module._agent_records_with_outcomes(limit=1, strict=True)
    typed = collectors.EndpointAgentsCollector()
    typed._legacy_module = module
    result = typed.collect({"limit": 1})

    assert len(collection.records) == 1
    assert collection.source_outcomes[0].status is CollectionStatus.NOT_AUTHORIZED
    assert result.status is CollectionStatus.PARTIAL


def test_web_services_limit_scans_later_sources(monkeypatch: pytest.MonkeyPatch) -> None:
    module = collectors.WebServicesCollectorModule()
    record = {
        "config_file": "/etc/nginx/nginx.conf",
        "server_name": "example.test",
        "port": "443",
        "document_root": "/srv/www",
    }

    def read(path: Path, *, strict: bool = False) -> str:
        if str(path) == "/etc/nginx/nginx.conf":
            return "server { listen 443; server_name example.test; }"
        raise OSError("later web-service source failed")

    monkeypatch.setattr(module, "_read_web_config", read)
    monkeypatch.setattr(module, "_parse_nginx_config", lambda text, config_file: [record])
    collection = module._web_service_records_with_outcomes(limit=1, strict=True)
    typed = collectors.WebServicesCollector()
    typed._legacy_module = module
    result = typed.collect({"limit": 1})

    assert len(collection.records) == 1
    assert collection.source_outcomes
    assert collection.source_outcomes[0].status is CollectionStatus.UNAVAILABLE
    assert result.status is CollectionStatus.PARTIAL


@pytest.mark.parametrize(
    "collector_type",
    [
        collectors.ProcessInventoryCollector,
        collectors.ListeningPortsCollector,
        collectors.NetworkInterfacesCollector,
        collectors.FirewallRulesCollector,
        collectors.DatabaseInventoryCollector,
        collectors.WifiInventoryCollector,
        collectors.RoutingTableCollector,
        collectors.EndpointAgentsCollector,
        collectors.WebServicesCollector,
    ],
    ids=lambda collector_type: collector_type.manifest.id,
)
def test_typed_collect_maps_unexpected_exception_for_every_collector(
    monkeypatch: pytest.MonkeyPatch,
    collector_type: type[Any],
) -> None:
    monkeypatch.setattr(collectors._process_inventory_platform, "system", lambda: "Linux")
    module = collector_type()

    def explode(*args: object, **kwargs: object) -> object:
        raise RuntimeError("unexpected collector parser failure")

    monkeypatch.setattr(module, "_records_with_outcomes", explode)
    result = module.collect({})

    assert result.status is CollectionStatus.UNAVAILABLE
    assert len(result.source_outcomes) == 1
    outcome = result.source_outcomes[0]
    assert outcome.source_id == module.manifest.id
    assert outcome.error_code == "collection_unavailable"
    assert outcome.error_detail == "unexpected collector parser failure"


def test_routing_table_legacy_path_propagates_unexpected_parser_error(monkeypatch: pytest.MonkeyPatch) -> None:
    module = collectors.RoutingTableCollectorModule()
    monkeypatch.setattr(
        module,
        "_read_ipv4_route_file",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("parser bug")),
    )

    with pytest.raises(RuntimeError, match="parser bug"):
        module._route_records()


def test_endpoint_agents_legacy_path_propagates_unexpected_parser_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = collectors.EndpointAgentsCollectorModule()
    monkeypatch.setattr(
        module,
        "_first_existing_marker",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("parser bug")),
    )

    with pytest.raises(RuntimeError, match="parser bug"):
        module._agent_records()


def test_web_services_legacy_path_propagates_unexpected_parser_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = collectors.WebServicesCollectorModule()
    monkeypatch.setattr(
        module,
        "_parse_nginx_config",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("parser bug")),
    )
    monkeypatch.setattr(module, "_read_web_config", lambda *args, **kwargs: "server {}")

    with pytest.raises(RuntimeError, match="parser bug"):
        module._web_service_records()


def test_firewall_legacy_path_propagates_unexpected_parser_error(monkeypatch: pytest.MonkeyPatch) -> None:
    module = collectors.FirewallRulesCollectorModule()
    monkeypatch.setattr(module, "_config_paths", ("rules.conf",))
    monkeypatch.setattr(
        module,
        "_read_firewall_rule_file",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("parser bug")),
    )

    with pytest.raises(RuntimeError, match="parser bug"):
        module._firewall_rule_records()


def test_database_legacy_path_propagates_unexpected_parser_error(monkeypatch: pytest.MonkeyPatch) -> None:
    module = collectors.DatabaseInventoryCollectorModule()
    monkeypatch.setattr(
        module,
        "_postgresql_record",
        lambda *, strict=False: (_ for _ in ()).throw(RuntimeError("parser bug")),
    )

    with pytest.raises(RuntimeError, match="parser bug"):
        module._database_records()


def test_wifi_legacy_path_propagates_unexpected_parser_error(monkeypatch: pytest.MonkeyPatch) -> None:
    module = collectors.WifiInventoryCollectorModule()
    monkeypatch.setattr(
        module,
        "_wireless_rows",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("parser bug")),
    )

    with pytest.raises(RuntimeError, match="parser bug"):
        module._wifi_records()
