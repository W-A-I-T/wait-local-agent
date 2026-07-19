"""Tests for the listening-ports collector module.

These exercise ``ListeningPortsCollectorModule`` against its concrete return
contract by building a real temporary ``/proc`` tree and redirecting the module's
``/proc/net`` reader at it, rather than mocking stdlib parsing helpers.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from wait_local_agent import collectors

Module = collectors.ListeningPortsCollectorModule


def _socket_row(index: int, local_address: str, state: str) -> str:
    return (
        f"   {index}: {local_address} 00000000:0000 {state}"
        " 00000000:00000000 00000000:00000000 00 00000000:00000000 0 0 0 0000000000000000 0 0\n"
    )


def _write_socket_table(proc_root: Path, filename: str, rows: list[str]) -> None:
    file_path = proc_root / filename
    header = "  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt uid timeout inode\n"
    file_path.write_text(header + "".join(rows))


@pytest.fixture()
def proc_root(tmp_path: Path) -> Path:
    root = tmp_path / "proc-net"
    root.mkdir()
    return root


def _use_proc_net(monkeypatch: pytest.MonkeyPatch, proc_root: Path, system: str = "Linux") -> None:
    original = collectors._ListeningPortsPath
    mapping = {
        "/proc/net/tcp": "tcp",
        "/proc/net/tcp6": "tcp6",
        "/proc/net/udp": "udp",
        "/proc/net/udp6": "udp6",
    }

    def _mock_path(path: Path, *, _root=proc_root, _original=original) -> Path:
        mapped = mapping.get(str(path))
        if mapped is None:
            return _original(path)
        return _root / mapped

    monkeypatch.setattr(collectors, "_ListeningPortsPath", _mock_path)
    monkeypatch.setattr(collectors._process_inventory_platform, "system", lambda: system)


def _collector() -> Any:
    return Module()


# --------------------------------------------------------------------------- #
# manifest / scope
# --------------------------------------------------------------------------- #


def test_manifest_advertises_read_only_linux_listening_ports_collector() -> None:
    manifest = _collector().manifest()
    assert manifest["module_id"] == "listening-ports"
    assert manifest["read_only"] is True
    assert manifest["platforms"] == ["linux"]
    assert manifest["asset_type"] == "network-socket"


def test_scope_is_read_only_stdlib_only_no_network_or_shell() -> None:
    scope = _collector().scope()
    assert scope["read_only"] is True
    assert scope["stdlib_only"] is True
    assert scope["network"] is False
    assert scope["shell"] is False
    assert scope["paths"] == [
        "/proc/net/tcp",
        "/proc/net/tcp6",
        "/proc/net/udp",
        "/proc/net/udp6",
    ]


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


def test_collect_parses_tcp_and_udp_rows_and_filters_non_listening_tcp(
    monkeypatch: pytest.MonkeyPatch,
    proc_root: Path,
) -> None:
    _write_socket_table(
        proc_root,
        "tcp",
        [
            _socket_row(0, "0100007F:1F90", "0A"),
            _socket_row(1, "0100007F:1F91", "01"),
        ],
    )
    _write_socket_table(
        proc_root,
        "udp",
        [
            _socket_row(0, "00000000:1388", "07"),
        ],
    )
    _use_proc_net(monkeypatch, proc_root)

    result = _collector().collect()
    assert result["module_id"] == "listening-ports"
    assert result["ok"] is True
    assert result["preview"] is False
    assert result["count"] == 2

    assets = result["items"]
    assert len(assets) == 2
    assert assets[0]["canonical_asset"]["attributes"]["protocol"] == "tcp"
    assert assets[0]["canonical_asset"]["attributes"]["local_port"] == 8080
    assert assets[0]["canonical_asset"]["attributes"]["state"] == "LISTEN"
    assert assets[0]["canonical_asset"]["attributes"]["local_ip"] == "127.0.0.1"

    assert assets[1]["canonical_asset"]["attributes"]["protocol"] == "udp"
    assert assets[1]["canonical_asset"]["attributes"]["local_port"] == 5000
    assert assets[1]["canonical_asset"]["attributes"]["state"] == "udp"
    assert assets[1]["canonical_asset"]["attributes"]["local_ip"] == "0.0.0.0"

    observed_protocols = [item["canonical_asset"]["attributes"]["protocol"] for item in assets]
    assert "01" not in [
        item["canonical_asset"]["attributes"]["state"]
        for item in assets
    ]
    assert observed_protocols == ["tcp", "udp"]


def test_collect_parses_ipv6_rows_and_sorts_by_protocol_then_port(
    monkeypatch: pytest.MonkeyPatch,
    proc_root: Path,
) -> None:
    _write_socket_table(
        proc_root,
        "tcp",
        [_socket_row(0, "0100007F:2328", "0A")],
    )
    _write_socket_table(
        proc_root,
        "tcp6",
        [_socket_row(0, "00000000000000000000000000000000:03E8", "0A")],
    )
    _write_socket_table(
        proc_root,
        "udp",
        [_socket_row(0, "0A00007F:1388", "07")],
    )
    _write_socket_table(
        proc_root,
        "udp6",
        [_socket_row(0, "00000000000000000000000000000000:002A", "07")],
    )
    _use_proc_net(monkeypatch, proc_root)

    result = _collector().collect()
    order = [
        (
            item["canonical_asset"]["attributes"]["protocol"],
            item["canonical_asset"]["attributes"]["local_port"],
        )
        for item in result["items"]
    ]
    assert order == [
        ("tcp", 9000),
        ("tcp6", 1000),
        ("udp", 5000),
        ("udp6", 42),
    ]

    tcp6_item = result["items"][1]["canonical_asset"]
    assert tcp6_item["attributes"]["local_ip"] == "::"
    assert tcp6_item["attributes"]["state"] == "LISTEN"


def test_collect_swallows_unreadable_file_as_directory(monkeypatch: pytest.MonkeyPatch, proc_root: Path) -> None:
    _write_socket_table(proc_root, "udp", [_socket_row(0, "00000000:1388", "07")])
    (proc_root / "tcp").mkdir()
    _use_proc_net(monkeypatch, proc_root)

    result = _collector().collect()
    assert result["items"][0]["canonical_asset"]["attributes"]["protocol"] == "udp"
    assert result["items"][0]["canonical_asset"]["attributes"]["local_port"] == 5000


def test_preview_marks_preview_and_caps_default_limit(
    monkeypatch: pytest.MonkeyPatch,
    proc_root: Path,
) -> None:
    rows = [_socket_row(index, f"00000000:{index + 3000:04X}", "0A") for index in range(1, 16)]
    _write_socket_table(proc_root, "tcp", rows)
    _use_proc_net(monkeypatch, proc_root)

    result = _collector().preview()
    assert result["preview"] is True
    assert result["count"] == 10
    assert len(result["items"]) == 10


def test_collect_honours_explicit_limit(
    monkeypatch: pytest.MonkeyPatch,
    proc_root: Path,
) -> None:
    rows = [_socket_row(index, f"00000000:{index + 4000:04X}", "0A") for index in range(1, 6)]
    _write_socket_table(proc_root, "tcp", rows)
    _use_proc_net(monkeypatch, proc_root)

    result = _collector().collect({"limit": 2})
    assert result["count"] == 2
    assert [item["canonical_asset"]["attributes"]["local_port"] for item in result["items"]] == [4001, 4002]


def test_collect_with_limit_zero_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
    proc_root: Path,
) -> None:
    _write_socket_table(proc_root, "tcp", [_socket_row(0, "00000000:1388", "0A")])
    _use_proc_net(monkeypatch, proc_root)

    result = _collector().collect({"limit": 0})
    assert result["ok"] is True
    assert result["items"] == []
    assert result["count"] == 0


def test_collect_returns_not_ok_for_invalid_config(
    monkeypatch: pytest.MonkeyPatch,
    proc_root: Path,
) -> None:
    _use_proc_net(monkeypatch, proc_root)
    result = _collector().collect({"limit": -5})
    assert result["ok"] is False
    assert result["assets"] == []
    assert result["errors"]


def test_preview_returns_not_ok_for_invalid_config(
    monkeypatch: pytest.MonkeyPatch,
    proc_root: Path,
) -> None:
    _use_proc_net(monkeypatch, proc_root)
    result = _collector().preview({"limit": "bad"})
    assert result["ok"] is False
    assert result["assets"] == []


def test_collect_returns_empty_on_non_linux(
    monkeypatch: pytest.MonkeyPatch,
    proc_root: Path,
) -> None:
    _write_socket_table(proc_root, "tcp", [_socket_row(0, "00000000:1388", "0A")])
    _use_proc_net(monkeypatch, proc_root, system="Darwin")

    result = _collector().collect()
    assert result["ok"] is True
    assert result["items"] == []


def test_collect_returns_empty_when_socket_files_missing(
    monkeypatch: pytest.MonkeyPatch,
    proc_root: Path,
) -> None:
    _use_proc_net(monkeypatch, proc_root)

    result = _collector().collect()
    assert result["ok"] is True
    assert result["items"] == []


# --------------------------------------------------------------------------- #
# registration
# --------------------------------------------------------------------------- #


def test_register_listening_ports_collector_is_idempotent() -> None:
    collectors._register_listening_ports_collector()
    registry = collectors.__dict__.get("MODULE_REGISTRY")
    if isinstance(registry, dict):
        module = registry.get("listening-ports")
        assert module is not None
        assert module.module_id == "listening-ports"


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

    collectors._register_listening_ports_collector()
    collectors._register_listening_ports_collector()

    assert [getattr(m, "module_id", None) for m in listed].count("listening-ports") == 1
    assert any(getattr(m, "module_id", None) == "listening-ports" for m in setted)
    assert getattr(calls.get("register"), "module_id", None) == "listening-ports"
    registry_tuple = collectors.__dict__["collector_registry"]
    assert [
        getattr(m, "module_id", None) for m in registry_tuple
    ].count("listening-ports") == 1
    assert "ListeningPortsCollectorModule" in collectors.__dict__["__all__"]


# --------------------------------------------------------------------------- #
# parse / decode helpers (white-box)
# --------------------------------------------------------------------------- #

_M = collectors.ListeningPortsCollectorModule


def test_parse_socket_row_rejects_short_line() -> None:
    assert _M._parse_socket_row("0: 00000000:0000", "tcp") is None


def test_parse_socket_row_rejects_unparseable_address() -> None:
    # Four columns, but the address field has no port separator.
    assert _M._parse_socket_row("0: badaddress 00 0A", "tcp") is None


def test_parse_socket_address_error_paths() -> None:
    assert _M._parse_socket_address("no-separator", "tcp") is None  # rsplit -> ValueError
    assert _M._parse_socket_address("0100007F:1388", "sctp") is None  # unknown protocol
    assert _M._parse_socket_address("XYZ:1388", "tcp") is None  # bad ipv4 -> "" -> None


def test_decode_ipv4_address_valid_and_error_paths() -> None:
    assert _M._decode_ipv4_address("0100007F") == "127.0.0.1"
    assert _M._decode_ipv4_address("ABCD") == ""  # wrong length
    assert _M._decode_ipv4_address("ZZZZZZZZ") == ""  # non-hex


def test_decode_ipv6_address_valid_and_error_paths() -> None:
    assert _M._decode_ipv6_address("Z" * 32) == ""  # non-hex
    assert _M._decode_ipv6_address("00") == ""  # wrong length
    assert ":" in _M._decode_ipv6_address("0" * 31 + "1")  # valid -> IPv6 string


def test_tcp_state_name_mapping() -> None:
    assert _M._tcp_state_name("0a") == "LISTEN"
    assert _M._tcp_state_name("01") == "ESTABLISHED"
    assert _M._tcp_state_name("06") == "06"


def test_collect_ignores_empty_socket_file(
    monkeypatch: pytest.MonkeyPatch, proc_root: Path
) -> None:
    # An empty /proc/net file (no header, no rows) yields no records.
    (proc_root / "tcp").write_text("")
    _write_socket_table(proc_root, "udp", [_socket_row(0, "00000000:1388", "07")])
    _use_proc_net(monkeypatch, proc_root)

    result = _collector().collect()
    ports = [item["canonical_asset"]["attributes"]["local_port"] for item in result["items"]]
    assert ports == [5000]  # 0x1388, from the udp table only
