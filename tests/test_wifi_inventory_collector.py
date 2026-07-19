"""Tests for the wifi-inventory collector module.

These exercise ``WifiInventoryCollectorModule`` against its concrete return
contract by building real temporary ``/proc/net/wireless`` and
``/sys/class/net`` trees and redirecting the module's path alias to them.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from wait_local_agent import collectors

Module = collectors.WifiInventoryCollectorModule


def _wireless_row(
    interface: str,
    *,
    link: str = "55.",
    level: str = "-45.",
    noise: str = "-256",
) -> str:
    return f"{interface}: 0000   {link}  {level}  {noise}        0      0      0\n"


def _write_wireless(proc_net_root: Path, rows: list[str]) -> None:
    header = (
        "Inter-| sta-|   Quality        |   Discarded packets               | Missed | WE\n"
        " face | tus | link level noise |  nwid  crypt   frag  retry   misc | beacon | 22\n"
    )
    (proc_net_root / "wireless").write_text(header + "".join(rows))


def _write_wifi_interface(
    sys_root: Path,
    interface: str,
    *,
    operstate: str = "up",
    address: str = "aa:bb:cc:dd:ee:ff",
) -> None:
    iface_root = sys_root / interface
    iface_root.mkdir()
    (iface_root / "wireless").mkdir()
    (iface_root / "operstate").write_text(f"{operstate}\n")
    (iface_root / "address").write_text(f"{address}\n")


@pytest.fixture()
def wifi_roots(tmp_path: Path) -> tuple[Path, Path]:
    proc_net_root = tmp_path / "proc-net"
    sys_net_root = tmp_path / "sys-class-net"
    proc_net_root.mkdir()
    sys_net_root.mkdir()
    return proc_net_root, sys_net_root


def _use_wifi_paths(
    monkeypatch: pytest.MonkeyPatch,
    proc_net_root: Path,
    sys_net_root: Path,
    system: str = "Linux",
) -> None:
    original = collectors._WifiInventoryPath

    def _mock_path(path: Path, *, _original: Any = original) -> Path:
        if str(path) == "/proc/net/wireless":
            return proc_net_root / "wireless"
        if str(path) == "/sys/class/net":
            return sys_net_root
        return _original(path)

    monkeypatch.setattr(collectors, "_WifiInventoryPath", _mock_path)
    monkeypatch.setattr(collectors._process_inventory_platform, "system", lambda: system)


def _collector() -> Any:
    return Module()


# --------------------------------------------------------------------------- #
# manifest / scope
# --------------------------------------------------------------------------- #


def test_manifest_advertises_read_only_linux_wifi_collector() -> None:
    manifest = _collector().manifest()
    assert manifest["module_id"] == "wifi-inventory"
    assert manifest["read_only"] is True
    assert manifest["platforms"] == ["linux"]
    assert manifest["asset_type"] == "wifi-interface"


def test_scope_is_read_only_stdlib_only_no_network_or_shell() -> None:
    scope = _collector().scope()
    assert scope["read_only"] is True
    assert scope["stdlib_only"] is True
    assert scope["network"] is False
    assert scope["shell"] is False
    assert scope["paths"] == ["/proc/net/wireless", "/sys/class/net"]


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


def test_collect_reads_proc_and_sys_wifi_metadata(
    monkeypatch: pytest.MonkeyPatch,
    wifi_roots: tuple[Path, Path],
) -> None:
    proc_net_root, sys_net_root = wifi_roots
    _write_wireless(proc_net_root, [_wireless_row("wlan0", link="70.", level="-39.")])
    _write_wifi_interface(
        sys_net_root,
        "wlan0",
        operstate="up",
        address="de:ad:be:ef:00:03",
    )
    _use_wifi_paths(monkeypatch, proc_net_root, sys_net_root)

    result = _collector().collect()
    assert result["module_id"] == "wifi-inventory"
    assert result["ok"] is True
    assert result["preview"] is False
    assert result["count"] == 1

    asset = result["items"][0]["canonical_asset"]
    assert asset["asset_type"] == "wifi-interface"
    assert asset["asset_id"] == "wifi:wlan0"
    attrs = asset["attributes"]
    assert attrs["interface"] == "wlan0"
    assert attrs["mac"] == "de:ad:be:ef:00:03"
    assert attrs["operstate"] == "up"
    assert attrs["link"] == "70."
    assert attrs["level"] == "-39."
    assert attrs["noise"] == "-256"

    observations = {item["key"]: item["value"] for item in result["items"][0]["observations"]}
    assert observations["wifi.interface"] == "wlan0"
    assert observations["wifi.mac"] == "de:ad:be:ef:00:03"
    assert observations["wifi.operstate"] == "up"
    assert observations["wifi.link"] == "70."
    assert observations["wifi.level"] == "-39."
    assert observations["wifi.noise"] == "-256"


def test_collect_skips_proc_wireless_header_lines(
    monkeypatch: pytest.MonkeyPatch,
    wifi_roots: tuple[Path, Path],
) -> None:
    proc_net_root, sys_net_root = wifi_roots
    (proc_net_root / "wireless").write_text(
        "fake0: 0000 99. -1. -2\n"
        "fake1: 0000 99. -1. -2\n"
        f"{_wireless_row('wlan0')}"
    )
    _write_wifi_interface(sys_net_root, "wlan0")
    _use_wifi_paths(monkeypatch, proc_net_root, sys_net_root)

    names = [
        item["canonical_asset"]["attributes"]["interface"]
        for item in _collector().collect()["items"]
    ]
    assert names == ["wlan0"]


def test_collect_includes_sys_wireless_interface_without_proc_row(
    monkeypatch: pytest.MonkeyPatch,
    wifi_roots: tuple[Path, Path],
) -> None:
    proc_net_root, sys_net_root = wifi_roots
    _write_wifi_interface(sys_net_root, "wlan1")
    _use_wifi_paths(monkeypatch, proc_net_root, sys_net_root)

    attrs = _collector().collect()["items"][0]["canonical_asset"]["attributes"]
    assert attrs["interface"] == "wlan1"
    assert attrs["link"] == ""
    assert attrs["level"] == ""
    assert attrs["noise"] == ""


def test_collect_sorts_interfaces_by_name(
    monkeypatch: pytest.MonkeyPatch,
    wifi_roots: tuple[Path, Path],
) -> None:
    proc_net_root, sys_net_root = wifi_roots
    _write_wireless(
        proc_net_root,
        [_wireless_row("wlan2"), _wireless_row("wlan0"), _wireless_row("wlan1")],
    )
    for interface in ("wlan2", "wlan0", "wlan1"):
        _write_wifi_interface(sys_net_root, interface)
    _use_wifi_paths(monkeypatch, proc_net_root, sys_net_root)

    names = [
        item["canonical_asset"]["attributes"]["interface"]
        for item in _collector().collect()["items"]
    ]
    assert names == ["wlan0", "wlan1", "wlan2"]


def test_collect_swallows_unreadable_metadata_file(
    monkeypatch: pytest.MonkeyPatch,
    wifi_roots: tuple[Path, Path],
) -> None:
    proc_net_root, sys_net_root = wifi_roots
    _write_wireless(proc_net_root, [_wireless_row("wlan0")])
    iface_root = sys_net_root / "wlan0"
    iface_root.mkdir()
    (iface_root / "wireless").mkdir()
    (iface_root / "address").mkdir()
    (iface_root / "operstate").write_text("down\n")
    _use_wifi_paths(monkeypatch, proc_net_root, sys_net_root)

    attrs = _collector().collect()["items"][0]["canonical_asset"]["attributes"]
    assert attrs["mac"] == ""
    assert attrs["operstate"] == "down"


def test_collect_returns_empty_on_non_linux(
    monkeypatch: pytest.MonkeyPatch,
    wifi_roots: tuple[Path, Path],
) -> None:
    proc_net_root, sys_net_root = wifi_roots
    _write_wireless(proc_net_root, [_wireless_row("wlan0")])
    _write_wifi_interface(sys_net_root, "wlan0")
    _use_wifi_paths(monkeypatch, proc_net_root, sys_net_root, system="Darwin")

    result = _collector().collect()
    assert result["ok"] is True
    assert result["items"] == []


def test_collect_returns_empty_when_proc_and_sys_paths_missing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _use_wifi_paths(monkeypatch, tmp_path / "missing-proc", tmp_path / "missing-sys")

    result = _collector().collect()
    assert result["ok"] is True
    assert result["items"] == []


def test_collect_honours_explicit_limit(
    monkeypatch: pytest.MonkeyPatch,
    wifi_roots: tuple[Path, Path],
) -> None:
    proc_net_root, sys_net_root = wifi_roots
    _write_wireless(proc_net_root, [_wireless_row(f"wlan{index}") for index in range(4)])
    for index in range(4):
        _write_wifi_interface(sys_net_root, f"wlan{index}")
    _use_wifi_paths(monkeypatch, proc_net_root, sys_net_root)

    result = _collector().collect({"limit": 2})
    assert result["ok"] is True
    assert result["count"] == 2
    assert [
        item["canonical_asset"]["attributes"]["interface"]
        for item in result["items"]
    ] == ["wlan0", "wlan1"]


def test_preview_marks_preview_and_caps_at_default_limit(
    monkeypatch: pytest.MonkeyPatch,
    wifi_roots: tuple[Path, Path],
) -> None:
    proc_net_root, sys_net_root = wifi_roots
    _write_wireless(proc_net_root, [_wireless_row(f"wlan{index}") for index in range(12)])
    for index in range(12):
        _write_wifi_interface(sys_net_root, f"wlan{index}")
    _use_wifi_paths(monkeypatch, proc_net_root, sys_net_root)

    result = _collector().preview()
    assert result["preview"] is True
    assert result["count"] == 10
    assert len(result["items"]) == 10


def test_collect_with_limit_zero_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
    wifi_roots: tuple[Path, Path],
) -> None:
    proc_net_root, sys_net_root = wifi_roots
    _write_wireless(proc_net_root, [_wireless_row("wlan0")])
    _write_wifi_interface(sys_net_root, "wlan0")
    _use_wifi_paths(monkeypatch, proc_net_root, sys_net_root)

    result = _collector().collect({"limit": 0})
    assert result["ok"] is True
    assert result["items"] == []
    assert result["count"] == 0


def test_collect_returns_not_ok_for_invalid_config(
    monkeypatch: pytest.MonkeyPatch,
    wifi_roots: tuple[Path, Path],
) -> None:
    proc_net_root, sys_net_root = wifi_roots
    _use_wifi_paths(monkeypatch, proc_net_root, sys_net_root)

    result = _collector().collect({"limit": -5})
    assert result["ok"] is False
    assert result["assets"] == []
    assert result["errors"]


def test_preview_returns_not_ok_for_invalid_config(
    monkeypatch: pytest.MonkeyPatch,
    wifi_roots: tuple[Path, Path],
) -> None:
    proc_net_root, sys_net_root = wifi_roots
    _use_wifi_paths(monkeypatch, proc_net_root, sys_net_root)

    result = _collector().preview({"limit": "bad"})
    assert result["ok"] is False
    assert result["assets"] == []


# --------------------------------------------------------------------------- #
# registration
# --------------------------------------------------------------------------- #


def test_register_wifi_inventory_collector_is_idempotent() -> None:
    collectors._register_wifi_inventory_collector()
    registry = collectors.__dict__.get("MODULE_REGISTRY")
    if isinstance(registry, dict):
        module = registry.get("wifi-inventory")
        assert module is not None
        assert module.module_id == "wifi-inventory"


def test_register_supports_list_set_tuple_and_register_object(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict[str, Any] = {}

    class RegistryObject:
        def register(self, module: Any) -> None:
            calls["register"] = module

    listed: list[Any] = []
    setted: set[Any] = set()
    monkeypatch.setattr(collectors, "COLLECTOR_MODULES", listed, raising=False)
    monkeypatch.setattr(collectors, "COLLECTORS", setted, raising=False)
    monkeypatch.setattr(collectors, "COLLECTOR_REGISTRY", RegistryObject(), raising=False)
    monkeypatch.setattr(collectors, "collector_registry", (), raising=False)
    monkeypatch.setattr(collectors, "__all__", [], raising=False)

    collectors._register_wifi_inventory_collector()
    collectors._register_wifi_inventory_collector()

    assert [getattr(m, "module_id", None) for m in listed].count("wifi-inventory") == 1
    assert any(getattr(m, "module_id", None) == "wifi-inventory" for m in setted)
    assert getattr(calls.get("register"), "module_id", None) == "wifi-inventory"
    registry_tuple = collectors.__dict__["collector_registry"]
    assert [
        getattr(m, "module_id", None) for m in registry_tuple
    ].count("wifi-inventory") == 1
    assert "WifiInventoryCollectorModule" in collectors.__dict__["__all__"]


# --------------------------------------------------------------------------- #
# read / parse helpers
# --------------------------------------------------------------------------- #


_M = collectors.WifiInventoryCollectorModule


def test_parse_wireless_row_extracts_interface_quality_fields() -> None:
    assert _M._parse_wireless_row("wlan0: 0000 55. -45. -256") == {
        "interface": "wlan0",
        "link": "55.",
        "level": "-45.",
        "noise": "-256",
    }


def test_parse_wireless_row_rejects_short_line() -> None:
    assert _M._parse_wireless_row("wlan0: 0000 55.") is None


def test_parse_wireless_row_rejects_empty_interface() -> None:
    assert _M._parse_wireless_row(": 0000 55. -45. -256") is None


def test_read_wifi_file_returns_empty_for_missing_file(tmp_path: Path) -> None:
    assert _M._read_wifi_file(tmp_path / "missing") == ""


def test_wireless_interfaces_from_sys_returns_empty_when_iterdir_raises(
    monkeypatch: pytest.MonkeyPatch,
    wifi_roots: tuple[Path, Path],
) -> None:
    _proc_net_root, sys_net_root = wifi_roots
    _write_wifi_interface(sys_net_root, "wlan0")

    real_iterdir = Path.iterdir

    def boom(self: Path) -> Any:
        if self == sys_net_root:
            raise OSError("boom")
        return real_iterdir(self)

    monkeypatch.setattr(Path, "iterdir", boom)
    assert _M._wireless_interfaces_from_sys(sys_net_root) == []
