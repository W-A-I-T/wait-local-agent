"""Regression tests for typed collector source scanning and limit semantics."""

from __future__ import annotations

from pathlib import Path

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
