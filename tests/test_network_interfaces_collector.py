"""Tests for the network-interfaces collector module.

These exercise ``NetworkInterfacesCollectorModule`` against its concrete return
contract by building a real temporary ``/sys/class/net`` tree and redirecting
the module's path alias to it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from wait_local_agent import collectors
from wait_local_agent.collectors import CollectionStatus, CollectorRegistry, CollectorService
from wait_local_agent.reports.models import ReportType
from wait_local_agent.store import Store

Module = collectors.NetworkInterfacesCollectorModule


def _write_interface(
    sys_root: Path,
    interface: str,
    *,
    operstate: str = "up",
    address: str = "aa:bb:cc:dd:ee:ff",
    mtu: str | int = "1500",
    type: str = "1",
    flags: str = "0x1003",
    include_mtu: bool = True,
    include_type: bool = True,
    include_flags: bool = True,
) -> None:
    iface_root = sys_root / interface
    iface_root.mkdir()
    (iface_root / "operstate").write_text(f"{operstate}\n")
    (iface_root / "address").write_text(f"{address}\n")
    if include_mtu:
        (iface_root / "mtu").write_text(f"{mtu}\n")
    if include_type:
        (iface_root / "type").write_text(f"{type}\n")
    if include_flags:
        (iface_root / "flags").write_text(f"{flags}\n")


@pytest.fixture()
def sys_net_root(tmp_path: Path) -> Path:
    root = tmp_path / "sys-class-net"
    root.mkdir()
    return root


def _use_sys_class_net(monkeypatch: pytest.MonkeyPatch, sys_root: Path, system: str = "Linux") -> None:
    original = collectors._NetworkInterfacesPath

    def _mock_path(path: Path, *, _root=sys_root, _original=original) -> Path:
        if str(path) == "/sys/class/net":
            return _root
        return _original(path)

    monkeypatch.setattr(collectors, "_NetworkInterfacesPath", _mock_path)
    monkeypatch.setattr(collectors._process_inventory_platform, "system", lambda: system)


def _collector() -> Any:
    return Module()


# --------------------------------------------------------------------------- #
# manifest / scope
# --------------------------------------------------------------------------- #


def test_manifest_advertises_read_only_linux_network_interfaces_collector() -> None:
    manifest = _collector().manifest()
    assert manifest["module_id"] == "network-interfaces"
    assert manifest["read_only"] is True
    assert manifest["platforms"] == ["linux"]
    assert manifest["asset_type"] == "network-interface"


def test_scope_is_read_only_stdlib_only_no_network_or_shell() -> None:
    scope = _collector().scope()
    assert scope["read_only"] is True
    assert scope["stdlib_only"] is True
    assert scope["network"] is False
    assert scope["shell"] is False
    assert scope["paths"] == ["/sys/class/net"]
    assert scope["operations"] == ["read-interface-metadata"]


# --------------------------------------------------------------------------- #
# validate_config
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("config", [None, {}, {"limit": 0}, {"limit": 5}])
def test_validate_config_accepts_valid_config(config: Any) -> None:
    result = _collector().validate_config(config)
    assert result["ok"] is True
    assert result["errors"] == []


@pytest.mark.parametrize("config", [{"limit": -1}, {"limit": "x"}, {"limit": 1.5}])
def test_validate_config_rejects_bad_limit(config: Any) -> None:
    result = _collector().validate_config(config)
    assert result["ok"] is False
    assert any("limit" in error for error in result["errors"])


def test_validate_config_rejects_non_mapping() -> None:
    result = _collector().validate_config(["not", "a", "mapping"])
    assert result["ok"] is False
    assert any("mapping" in error for error in result["errors"])


# --------------------------------------------------------------------------- #
# collect / preview — concrete return contract
# --------------------------------------------------------------------------- #


def test_collect_reads_interface_metadata_and_returns_expected_contract(
    monkeypatch: pytest.MonkeyPatch,
    sys_net_root: Path,
) -> None:
    _write_interface(
        sys_net_root,
        "eth0",
        operstate="down",
        address="de:ad:be:ef:00:01",
        mtu=1500,
        type="1",
        flags="0x1003",
    )
    _write_interface(
        sys_net_root,
        "lo",
        operstate="unknown",
        address="00:00:00:00:00:00",
        mtu="65536",
        type="772",
        flags="0x1002",
    )
    _use_sys_class_net(monkeypatch, sys_net_root)

    result = _collector().collect()
    assert result["module_id"] == "network-interfaces"
    assert result["ok"] is True
    assert result["preview"] is False
    assert result["count"] == 2
    assert len(result["items"]) == 2

    assert [item["canonical_asset"]["attributes"]["interface"] for item in result["items"]] == [
        "eth0",
        "lo",
    ]

    eth0 = result["items"][0]["canonical_asset"]
    assert eth0["asset_type"] == "network-interface"
    assert eth0["asset_id"] == "netif:eth0"
    assert eth0["attributes"]["mac"] == "de:ad:be:ef:00:01"
    assert eth0["attributes"]["operstate"] == "down"
    assert eth0["attributes"]["mtu"] == 1500
    assert eth0["attributes"]["type"] == "1"
    assert eth0["attributes"]["flags"] == "0x1003"

    observations = {item["key"]: item["value"] for item in result["items"][0]["observations"]}
    assert observations["netif.name"] == "eth0"
    assert observations["netif.mac"] == "de:ad:be:ef:00:01"
    assert observations["netif.mtu"] == 1500
    assert observations["netif.type"] == "1"
    assert observations["netif.flags"] == "0x1003"


def test_collect_sorts_interfaces_by_name(
    monkeypatch: pytest.MonkeyPatch,
    sys_net_root: Path,
) -> None:
    _write_interface(sys_net_root, "wlan0")
    _write_interface(sys_net_root, "eth0")
    _write_interface(sys_net_root, "lo")
    _use_sys_class_net(monkeypatch, sys_net_root)

    names = [
        item["canonical_asset"]["attributes"]["interface"]
        for item in _collector().collect()["items"]
    ]
    assert names == ["eth0", "lo", "wlan0"]


def test_collect_swallows_missing_metadata_files_with_empty_defaults(
    monkeypatch: pytest.MonkeyPatch,
    sys_net_root: Path,
) -> None:
    iface_root = sys_net_root / "eth0"
    iface_root.mkdir()
    (iface_root / "operstate").write_text("up\n")
    (iface_root / "address").write_text("de:ad:be:ef:00:02\n")
    _use_sys_class_net(monkeypatch, sys_net_root)

    result = _collector().collect()
    attrs = result["items"][0]["canonical_asset"]["attributes"]
    assert attrs["interface"] == "eth0"
    assert attrs["operstate"] == "up"
    assert attrs["mac"] == "de:ad:be:ef:00:02"
    assert attrs["mtu"] == ""
    assert attrs["type"] == ""
    assert attrs["flags"] == ""


def test_collect_returns_empty_on_non_linux(
    monkeypatch: pytest.MonkeyPatch,
    sys_net_root: Path,
) -> None:
    _write_interface(sys_net_root, "lo")
    _use_sys_class_net(monkeypatch, sys_net_root, system="Darwin")

    result = _collector().collect()
    assert result["ok"] is True
    assert result["items"] == []

    typed_result = collectors.NetworkInterfacesCollector().collect({})
    assert typed_result.status is CollectionStatus.EMPTY
    assert typed_result.source_outcomes[0].remediation_hint is not None


def test_typed_collect_maps_interface_permission_error(
    monkeypatch: pytest.MonkeyPatch,
    sys_net_root: Path,
) -> None:
    _write_interface(sys_net_root, "eth0")
    _use_sys_class_net(monkeypatch, sys_net_root)

    real_read_text = Path.read_text

    def deny_address(self: Path, *args: Any, **kwargs: Any) -> str:
        if self.name == "address":
            raise PermissionError("interface metadata denied")
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", deny_address)

    result = collectors.NetworkInterfacesCollector().collect({})

    assert result.status is CollectionStatus.NOT_AUTHORIZED
    assert result.source_outcomes[0].error_code == "permission_denied"


def test_typed_network_interfaces_collect_returns_partial_when_one_interface_is_denied(
    monkeypatch: pytest.MonkeyPatch,
    sys_net_root: Path,
) -> None:
    _write_interface(sys_net_root, "eth0")
    _write_interface(sys_net_root, "eth1")
    _use_sys_class_net(monkeypatch, sys_net_root)
    real_read_text = Path.read_text

    def deny_eth1(self: Path, *args: Any, **kwargs: Any) -> str:
        if self == sys_net_root / "eth1" / "address":
            raise PermissionError("interface metadata denied")
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", deny_eth1)
    result = collectors.NetworkInterfacesCollector().collect({})

    assert result.status is CollectionStatus.PARTIAL
    assert [asset.canonical_id for asset in result.assets] == ["netif:eth0"]
    assert any(outcome.status is CollectionStatus.NOT_AUTHORIZED for outcome in result.source_outcomes)


def test_network_interfaces_round_trips_through_governed_service(
    monkeypatch: pytest.MonkeyPatch,
    sys_net_root: Path,
    settings,
) -> None:
    _write_interface(sys_net_root, "eth0")
    _use_sys_class_net(monkeypatch, sys_net_root)
    registry = CollectorRegistry()
    registry.register(collectors.NetworkInterfacesCollector())
    store = Store(settings.data_path)
    service = CollectorService(store, registry)

    assert service.validate("network-interfaces", {}).passed is True
    preview = service.preview("network-interfaces", {})
    run = service.run("network-interfaces", {}, confirm=True)
    report = service.export_report(run.id or 0, ReportType.COLLECTOR_BUNDLE)

    assert preview.estimated_assets == 1
    assert run.status == "completed"
    assert '"status":"success"' in run.result_json
    assert len(store.list_canonical_assets(run_id=run.id)) == 1
    assert len(store.list_asset_observations(run_id=run.id)) == 6
    assert report.report_type is ReportType.COLLECTOR_BUNDLE


def test_collect_returns_empty_when_path_missing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _use_sys_class_net(monkeypatch, tmp_path / "does-not-exist")
    result = _collector().collect()
    assert result["ok"] is True
    assert result["items"] == []


def test_collect_honours_explicit_limit(
    monkeypatch: pytest.MonkeyPatch,
    sys_net_root: Path,
) -> None:
    for index in range(4):
        _write_interface(sys_net_root, f"eth{index}")
    _use_sys_class_net(monkeypatch, sys_net_root)

    result = _collector().collect({"limit": 2})
    assert result["ok"] is True
    assert result["count"] == 2


def test_preview_marks_preview_and_caps_at_default_limit(
    monkeypatch: pytest.MonkeyPatch,
    sys_net_root: Path,
) -> None:
    for index in range(12):
        _write_interface(sys_net_root, f"eth{index}")
    _use_sys_class_net(monkeypatch, sys_net_root)

    result = _collector().preview()
    assert result["preview"] is True
    assert result["count"] == 10
    assert len(result["items"]) == 10


def test_collect_with_limit_zero_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
    sys_net_root: Path,
) -> None:
    _write_interface(sys_net_root, "lo")
    _use_sys_class_net(monkeypatch, sys_net_root)

    result = _collector().collect({"limit": 0})
    assert result["ok"] is True
    assert result["items"] == []
    assert result["count"] == 0


def test_collect_returns_not_ok_for_invalid_config(
    monkeypatch: pytest.MonkeyPatch,
    sys_net_root: Path,
) -> None:
    _write_interface(sys_net_root, "lo")
    _use_sys_class_net(monkeypatch, sys_net_root)

    result = _collector().collect({"limit": -5})
    assert result["ok"] is False
    assert result["assets"] == []
    assert result["errors"]


def test_preview_returns_not_ok_for_invalid_config(
    monkeypatch: pytest.MonkeyPatch,
    sys_net_root: Path,
) -> None:
    _write_interface(sys_net_root, "lo")
    _use_sys_class_net(monkeypatch, sys_net_root)

    result = _collector().preview({"limit": "bad"})
    assert result["ok"] is False
    assert result["assets"] == []


# --------------------------------------------------------------------------- #
# read helpers
# --------------------------------------------------------------------------- #


_M = collectors.NetworkInterfacesCollectorModule


def test_coerce_mtu_returns_int_for_numeric() -> None:
    assert _M._coerce_mtu("1500") == 1500


def test_coerce_mtu_returns_raw_for_non_numeric() -> None:
    assert _M._coerce_mtu("15xx") == "15xx"


def test_read_interface_file_returns_empty_for_unreadable_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    file_path = tmp_path / "missing"
    file_path.write_text("x")

    real_read_text = Path.read_text

    def deny_read_text(self: Path, *args: Any, **kwargs: Any) -> str:
        if self == file_path:
            raise PermissionError("denied")
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", deny_read_text)
    assert _M._read_interface_file(file_path) == ""


def test_collect_returns_empty_when_iterdir_raises(
    monkeypatch: pytest.MonkeyPatch, sys_net_root: Path
) -> None:
    _write_interface(sys_net_root, "eth0")
    _use_sys_class_net(monkeypatch, sys_net_root)

    real_iterdir = Path.iterdir

    def boom(self: Path) -> Any:
        if self == sys_net_root:
            raise OSError("boom")
        return real_iterdir(self)

    monkeypatch.setattr(Path, "iterdir", boom)
    assert _collector().collect()["items"] == []


def test_read_interface_record_returns_none_for_empty_name() -> None:
    from types import SimpleNamespace

    assert _M()._read_interface_record(SimpleNamespace(name="")) is None
