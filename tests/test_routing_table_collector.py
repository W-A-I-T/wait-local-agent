"""Tests for the routing-table collector module.

These exercise ``RoutingTableCollectorModule`` against its concrete return
contract by building temporary ``/proc/net`` route files and redirecting the
module's path alias at them.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from wait_local_agent import collectors

Module = collectors.RoutingTableCollectorModule


def _ipv4_route_row(
    interface: str,
    destination: str,
    gateway: str,
    *,
    flags: str = "0003",
    metric: int = 100,
    mask: str = "00000000",
) -> str:
    return f"{interface}\t{destination}\t{gateway}\t{flags}\t0\t0\t{metric}\t{mask}\t0\t0\t0\n"


def _write_ipv4_routes(proc_root: Path, rows: list[str]) -> None:
    header = "Iface\tDestination\tGateway\tFlags\tRefCnt\tUse\tMetric\tMask\tMTU\tWindow\tIRTT\n"
    (proc_root / "route").write_text(header + "".join(rows))


def _ipv6_route_row(
    destination: str,
    prefix: str,
    gateway: str,
    *,
    flags: str = "00000003",
    interface: str = "eth0",
) -> str:
    source = "00000000000000000000000000000000"
    return f"{destination} {prefix} {source} 00 {gateway} 00000000 00000000 00000000 {flags} {interface}\n"


def _write_ipv6_routes(proc_root: Path, rows: list[str]) -> None:
    (proc_root / "ipv6_route").write_text("".join(rows))


@pytest.fixture()
def proc_net_root(tmp_path: Path) -> Path:
    root = tmp_path / "proc-net"
    root.mkdir()
    return root


def _use_proc_net(monkeypatch: pytest.MonkeyPatch, proc_root: Path, system: str = "Linux") -> None:
    original = collectors._RoutingTablePath
    mapping = {
        "/proc/net/route": "route",
        "/proc/net/ipv6_route": "ipv6_route",
    }

    def _mock_path(path: Path, *, _root=proc_root, _original=original) -> Path:
        mapped = mapping.get(str(path))
        if mapped is None:
            return _original(path)
        return _root / mapped

    monkeypatch.setattr(collectors, "_RoutingTablePath", _mock_path)
    monkeypatch.setattr(collectors._process_inventory_platform, "system", lambda: system)


def _collector() -> Any:
    return Module()


# --------------------------------------------------------------------------- #
# manifest / scope
# --------------------------------------------------------------------------- #


def test_manifest_advertises_read_only_linux_routing_table_collector() -> None:
    manifest = _collector().manifest()
    assert manifest["module_id"] == "routing-table"
    assert manifest["read_only"] is True
    assert manifest["platforms"] == ["linux"]
    assert manifest["asset_type"] == "route"


def test_scope_is_read_only_stdlib_only_no_network_or_shell() -> None:
    scope = _collector().scope()
    assert scope["read_only"] is True
    assert scope["stdlib_only"] is True
    assert scope["network"] is False
    assert scope["shell"] is False
    assert scope["paths"] == ["/proc/net/route", "/proc/net/ipv6_route"]
    assert scope["operations"] == ["read-routing-table"]


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


def test_collect_parses_ipv4_and_ipv6_routes(
    monkeypatch: pytest.MonkeyPatch,
    proc_net_root: Path,
) -> None:
    _write_ipv4_routes(
        proc_net_root,
        [
            _ipv4_route_row(
                "eth0",
                "00000000",
                "0102A8C0",
                flags="0003",
                mask="00000000",
            ),
        ],
    )
    _write_ipv6_routes(
        proc_net_root,
        [
            _ipv6_route_row(
                "20010DB8000000000000000000000000",
                "40",
                "FE800000000000000000000000000001",
                interface="eth0",
            ),
        ],
    )
    _use_proc_net(monkeypatch, proc_net_root)

    result = _collector().collect()
    assert result["module_id"] == "routing-table"
    assert result["ok"] is True
    assert result["preview"] is False
    assert result["count"] == 2

    ipv4_asset = result["items"][0]["canonical_asset"]
    assert ipv4_asset["asset_type"] == "route"
    assert ipv4_asset["asset_id"] == "route:ipv4:eth0:0.0.0.0/0"
    assert ipv4_asset["name"] == "0.0.0.0 via 192.168.2.1 dev eth0"
    assert ipv4_asset["attributes"]["family"] == "ipv4"
    assert ipv4_asset["attributes"]["interface"] == "eth0"
    assert ipv4_asset["attributes"]["destination"] == "0.0.0.0"
    assert ipv4_asset["attributes"]["gateway"] == "192.168.2.1"
    assert ipv4_asset["attributes"]["mask"] == "0.0.0.0"
    assert ipv4_asset["attributes"]["flags"] == "0003"

    observations = {item["key"]: item["value"] for item in result["items"][0]["observations"]}
    assert observations["route.family"] == "ipv4"
    assert observations["route.interface"] == "eth0"
    assert observations["route.destination"] == "0.0.0.0"
    assert observations["route.gateway"] == "192.168.2.1"
    assert observations["route.mask"] == "0.0.0.0"
    assert observations["route.flags"] == "0003"

    ipv6_asset = result["items"][1]["canonical_asset"]
    assert ipv6_asset["asset_id"] == "route:ipv6:eth0:2001:db8::/0"
    assert ipv6_asset["name"] == "2001:db8:: via fe80::1 dev eth0"
    assert ipv6_asset["attributes"]["family"] == "ipv6"
    assert ipv6_asset["attributes"]["destination"] == "2001:db8::"
    assert ipv6_asset["attributes"]["gateway"] == "fe80::1"
    assert ipv6_asset["attributes"]["mask"] == 64
    assert ipv6_asset["attributes"]["flags"] == "00000003"


def test_collect_skips_ipv4_header_and_malformed_rows(
    monkeypatch: pytest.MonkeyPatch,
    proc_net_root: Path,
) -> None:
    _write_ipv4_routes(
        proc_net_root,
        [
            "bad row\n",
            _ipv4_route_row("eth0", "ZZZZZZZZ", "0102A8C0"),
            _ipv4_route_row("eth1", "0001A8C0", "00000000", mask="00FFFFFF"),
        ],
    )
    _write_ipv6_routes(
        proc_net_root,
        [
            "too short\n",
            _ipv6_route_row("Z" * 32, "40", "FE800000000000000000000000000001"),
        ],
    )
    _use_proc_net(monkeypatch, proc_net_root)

    result = _collector().collect()
    assert result["count"] == 1
    attrs = result["items"][0]["canonical_asset"]["attributes"]
    assert attrs["interface"] == "eth1"
    assert attrs["family"] == "ipv4"
    assert attrs["destination"] == "192.168.1.0"
    assert attrs["mask"] == "255.255.255.0"


def test_collect_sorts_by_family_interface_and_destination(
    monkeypatch: pytest.MonkeyPatch,
    proc_net_root: Path,
) -> None:
    _write_ipv4_routes(
        proc_net_root,
        [
            _ipv4_route_row("wlan0", "00000000", "0100A8C0"),
            _ipv4_route_row("eth0", "0002A8C0", "00000000", mask="00FFFFFF"),
            _ipv4_route_row("eth0", "0001A8C0", "00000000", mask="00FFFFFF"),
        ],
    )
    _write_ipv6_routes(
        proc_net_root,
        [
            _ipv6_route_row(
                "20010DB8000000000000000000000000",
                "40",
                "FE800000000000000000000000000001",
                interface="eth0",
            ),
        ],
    )
    _use_proc_net(monkeypatch, proc_net_root)

    order = [
        (
            item["canonical_asset"]["attributes"]["family"],
            item["canonical_asset"]["attributes"]["interface"],
            item["canonical_asset"]["attributes"]["destination"],
        )
        for item in _collector().collect()["items"]
    ]
    assert order == [
        ("ipv4", "eth0", "192.168.1.0"),
        ("ipv4", "eth0", "192.168.2.0"),
        ("ipv4", "wlan0", "0.0.0.0"),
        ("ipv6", "eth0", "2001:db8::"),
    ]


def test_collect_swallows_unreadable_file_as_directory(
    monkeypatch: pytest.MonkeyPatch,
    proc_net_root: Path,
) -> None:
    (proc_net_root / "route").mkdir()
    _write_ipv6_routes(
        proc_net_root,
        [_ipv6_route_row("20010DB8000000000000000000000000", "40", "FE800000000000000000000000000001")],
    )
    _use_proc_net(monkeypatch, proc_net_root)

    result = _collector().collect()
    assert result["count"] == 1
    assert result["items"][0]["canonical_asset"]["attributes"]["family"] == "ipv6"


def test_preview_marks_preview_and_caps_default_limit(
    monkeypatch: pytest.MonkeyPatch,
    proc_net_root: Path,
) -> None:
    rows = [
        _ipv4_route_row(f"eth{index:02d}", f"{index:02X}00A8C0", "00000000", mask="00FFFFFF")
        for index in range(12)
    ]
    _write_ipv4_routes(proc_net_root, rows)
    _use_proc_net(monkeypatch, proc_net_root)

    result = _collector().preview()
    assert result["preview"] is True
    assert result["count"] == 10
    assert len(result["items"]) == 10


def test_collect_honours_explicit_limit(
    monkeypatch: pytest.MonkeyPatch,
    proc_net_root: Path,
) -> None:
    rows = [
        _ipv4_route_row(f"eth{index}", f"{index:02X}00A8C0", "00000000", mask="00FFFFFF")
        for index in range(4)
    ]
    _write_ipv4_routes(proc_net_root, rows)
    _use_proc_net(monkeypatch, proc_net_root)

    result = _collector().collect({"limit": 2})
    assert result["ok"] is True
    assert result["count"] == 2


def test_collect_with_limit_zero_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
    proc_net_root: Path,
) -> None:
    _write_ipv4_routes(proc_net_root, [_ipv4_route_row("eth0", "00000000", "0102A8C0")])
    _use_proc_net(monkeypatch, proc_net_root)

    result = _collector().collect({"limit": 0})
    assert result["ok"] is True
    assert result["items"] == []
    assert result["count"] == 0


def test_collect_returns_not_ok_for_invalid_config(
    monkeypatch: pytest.MonkeyPatch,
    proc_net_root: Path,
) -> None:
    _use_proc_net(monkeypatch, proc_net_root)
    result = _collector().collect({"limit": -5})
    assert result["ok"] is False
    assert result["assets"] == []
    assert result["errors"]


def test_preview_returns_not_ok_for_invalid_config(
    monkeypatch: pytest.MonkeyPatch,
    proc_net_root: Path,
) -> None:
    _use_proc_net(monkeypatch, proc_net_root)
    result = _collector().preview({"limit": "bad"})
    assert result["ok"] is False
    assert result["assets"] == []


def test_collect_returns_empty_on_non_linux(
    monkeypatch: pytest.MonkeyPatch,
    proc_net_root: Path,
) -> None:
    _write_ipv4_routes(proc_net_root, [_ipv4_route_row("eth0", "00000000", "0102A8C0")])
    _use_proc_net(monkeypatch, proc_net_root, system="Darwin")

    result = _collector().collect()
    assert result["ok"] is True
    assert result["items"] == []


def test_collect_returns_empty_when_route_files_missing(
    monkeypatch: pytest.MonkeyPatch,
    proc_net_root: Path,
) -> None:
    _use_proc_net(monkeypatch, proc_net_root)

    result = _collector().collect()
    assert result["ok"] is True
    assert result["items"] == []


def test_collect_ignores_empty_ipv4_route_file(
    monkeypatch: pytest.MonkeyPatch,
    proc_net_root: Path,
) -> None:
    (proc_net_root / "route").write_text("")
    _write_ipv6_routes(
        proc_net_root,
        [_ipv6_route_row("20010DB8000000000000000000000000", "40", "FE800000000000000000000000000001")],
    )
    _use_proc_net(monkeypatch, proc_net_root)

    result = _collector().collect()
    assert result["count"] == 1
    assert result["items"][0]["canonical_asset"]["attributes"]["family"] == "ipv6"


# --------------------------------------------------------------------------- #
# registration
# --------------------------------------------------------------------------- #


def test_register_routing_table_collector_is_idempotent() -> None:
    collectors._register_routing_table_collector()
    registry = collectors.__dict__.get("MODULE_REGISTRY")
    if isinstance(registry, dict):
        module = registry.get("routing-table")
        assert module is not None
        assert module.module_id == "routing-table"


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

    collectors._register_routing_table_collector()
    collectors._register_routing_table_collector()

    assert [getattr(m, "module_id", None) for m in listed].count("routing-table") == 1
    assert any(getattr(m, "module_id", None) == "routing-table" for m in setted)
    assert getattr(calls.get("register"), "module_id", None) == "routing-table"
    registry_tuple = collectors.__dict__["collector_registry"]
    assert [
        getattr(m, "module_id", None) for m in registry_tuple
    ].count("routing-table") == 1
    assert "RoutingTableCollectorModule" in collectors.__dict__["__all__"]


# --------------------------------------------------------------------------- #
# parse / decode helpers
# --------------------------------------------------------------------------- #


_M = collectors.RoutingTableCollectorModule


def test_parse_ipv4_route_row_rejects_short_line() -> None:
    assert _M._parse_ipv4_route_row("eth0 00000000", 0) is None


def test_parse_ipv6_route_row_rejects_short_line_and_bad_prefix() -> None:
    assert _M._parse_ipv6_route_row("too short", 0) is None
    row = _ipv6_route_row("20010DB8000000000000000000000000", "XX", "FE800000000000000000000000000001")
    assert _M._parse_ipv6_route_row(row, 0) is None


def test_decode_ipv4_address_valid_and_error_paths() -> None:
    assert _M._decode_ipv4_address("0100007F") == "127.0.0.1"
    assert _M._decode_ipv4_address("ABCD") == ""
    assert _M._decode_ipv4_address("ZZZZZZZZ") == ""


def test_decode_ipv6_address_valid_and_error_paths() -> None:
    assert _M._decode_ipv6_address("20010DB8000000000000000000000000") == "2001:db8::"
    assert _M._decode_ipv6_address("00") == ""
    assert _M._decode_ipv6_address("Z" * 32) == ""
