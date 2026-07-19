"""Tests for the process-inventory collector module.

These exercise ``ProcessInventoryCollectorModule`` against its concrete return
contract by building a real temporary ``/proc`` tree and redirecting the
module's ``_ProcessInventoryPath`` alias at it, rather than mocking stdlib
scandir/glob (which the module never calls).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from wait_local_agent import collectors

Module = collectors.ProcessInventoryCollectorModule


def _write_process(
    proc_root: Path,
    pid: int,
    *,
    name: str = "bash",
    state: str = "S (sleeping)",
    cmdline: bytes = b"/bin/bash\x00-i\x00",
    with_status: bool = True,
    comm: str | None = None,
) -> None:
    """Create a single ``/proc/<pid>`` entry under ``proc_root``."""
    entry = proc_root / str(pid)
    entry.mkdir()
    if with_status:
        (entry / "status").write_text(f"Name:\t{name}\nState:\t{state}\n")
    if cmdline is not None:
        (entry / "cmdline").write_bytes(cmdline)
    if comm is not None:
        (entry / "comm").write_text(comm)


@pytest.fixture()
def proc_root(tmp_path: Path) -> Path:
    root = tmp_path / "proc"
    root.mkdir()
    return root


def _use_proc(monkeypatch: pytest.MonkeyPatch, proc_root: Path, system: str = "Linux") -> None:
    """Point the module's ``/proc`` reader at ``proc_root`` on ``system``."""
    original = collectors._ProcessInventoryPath
    monkeypatch.setattr(
        collectors,
        "_ProcessInventoryPath",
        lambda p, _root=proc_root, _orig=original: _root if str(p) == "/proc" else _orig(p),
    )
    monkeypatch.setattr(collectors._process_inventory_platform, "system", lambda: system)


def _collector() -> Any:
    return Module()


# --------------------------------------------------------------------------- #
# manifest / scope
# --------------------------------------------------------------------------- #


def test_manifest_advertises_read_only_linux_process_collector() -> None:
    manifest = _collector().manifest()
    assert manifest["module_id"] == "process-inventory"
    assert manifest["read_only"] is True
    assert manifest["platforms"] == ["linux"]
    assert manifest["asset_type"] == "process"


def test_scope_is_read_only_stdlib_only_no_network_or_shell() -> None:
    scope = _collector().scope()
    assert scope["read_only"] is True
    assert scope["stdlib_only"] is True
    assert scope["network"] is False
    assert scope["shell"] is False
    assert scope["paths"] == ["/proc"]


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


def test_collect_parses_pid_name_cmdline_and_state(
    monkeypatch: pytest.MonkeyPatch, proc_root: Path
) -> None:
    _write_process(proc_root, 20, name="python", state="R (running)", cmdline=b"python\x00app.py\x00")
    _use_proc(monkeypatch, proc_root)

    result = _collector().collect()

    assert result["module_id"] == "process-inventory"
    assert result["ok"] is True
    assert result["preview"] is False
    assert result["count"] == 1

    asset = result["items"][0]["canonical_asset"]
    assert asset["asset_id"] == "process:20"
    attrs = asset["attributes"]
    assert attrs["pid"] == 20
    assert attrs["name"] == "python"
    assert attrs["cmdline"] == "python app.py"
    assert attrs["state"] == "R (running)"

    observations = {obs["key"]: obs["value"] for obs in result["items"][0]["observations"]}
    assert observations["process.pid"] == 20
    assert observations["process.name"] == "python"
    assert observations["process.cmdline"] == "python app.py"
    assert observations["process.state"] == "R (running)"


def test_collect_sorts_records_by_pid_and_ignores_non_numeric_entries(
    monkeypatch: pytest.MonkeyPatch, proc_root: Path
) -> None:
    _write_process(proc_root, 30)
    _write_process(proc_root, 4)
    _write_process(proc_root, 200)
    # non-numeric siblings that must be ignored
    (proc_root / "acpi").mkdir()
    (proc_root / "cpuinfo").write_text("x")
    _use_proc(monkeypatch, proc_root)

    result = _collector().collect()
    pids = [item["canonical_asset"]["attributes"]["pid"] for item in result["items"]]
    assert pids == [4, 30, 200]


def test_collect_falls_back_to_comm_when_status_name_missing(
    monkeypatch: pytest.MonkeyPatch, proc_root: Path
) -> None:
    _write_process(proc_root, 7, with_status=False, cmdline=b"", comm="worker\n")
    _use_proc(monkeypatch, proc_root)

    result = _collector().collect()
    assert result["items"][0]["canonical_asset"]["attributes"]["name"] == "worker"


def test_collect_skips_entries_with_no_name_and_no_cmdline(
    monkeypatch: pytest.MonkeyPatch, proc_root: Path
) -> None:
    # empty entry: no status, empty cmdline, no comm -> record is None -> skipped
    _write_process(proc_root, 9, with_status=False, cmdline=b"")
    _write_process(proc_root, 10)
    _use_proc(monkeypatch, proc_root)

    result = _collector().collect()
    pids = [item["canonical_asset"]["attributes"]["pid"] for item in result["items"]]
    assert pids == [10]


def test_collect_swallows_permission_error_reading_status(
    monkeypatch: pytest.MonkeyPatch, proc_root: Path
) -> None:
    _write_process(proc_root, 11, comm="guarded\n")
    _use_proc(monkeypatch, proc_root)

    real_read_text = Path.read_text

    def deny_status(self: Path, *args: Any, **kwargs: Any) -> str:
        if self.name == "status":
            raise PermissionError("denied")
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", deny_status)

    result = _collector().collect()
    # status unreadable -> name comes from comm fallback, no crash
    assert result["items"][0]["canonical_asset"]["attributes"]["name"] == "guarded"


def test_preview_marks_preview_and_caps_at_default_limit(
    monkeypatch: pytest.MonkeyPatch, proc_root: Path
) -> None:
    for pid in range(1, 16):  # 15 processes
        _write_process(proc_root, pid)
    _use_proc(monkeypatch, proc_root)

    result = _collector().preview()
    assert result["preview"] is True
    assert result["count"] == 10  # preview default limit


def test_collect_honours_explicit_limit(
    monkeypatch: pytest.MonkeyPatch, proc_root: Path
) -> None:
    for pid in range(1, 6):
        _write_process(proc_root, pid)
    _use_proc(monkeypatch, proc_root)

    result = _collector().collect({"limit": 2})
    assert result["count"] == 2


def test_collect_with_limit_zero_returns_empty(
    monkeypatch: pytest.MonkeyPatch, proc_root: Path
) -> None:
    _write_process(proc_root, 1)
    _use_proc(monkeypatch, proc_root)

    result = _collector().collect({"limit": 0})
    assert result["ok"] is True
    assert result["items"] == []
    assert result["count"] == 0


def test_collect_returns_not_ok_for_invalid_config(
    monkeypatch: pytest.MonkeyPatch, proc_root: Path
) -> None:
    _use_proc(monkeypatch, proc_root)
    result = _collector().collect({"limit": -5})
    assert result["ok"] is False
    assert result["assets"] == []
    assert result["errors"]


def test_preview_returns_not_ok_for_invalid_config(
    monkeypatch: pytest.MonkeyPatch, proc_root: Path
) -> None:
    _use_proc(monkeypatch, proc_root)
    result = _collector().preview({"limit": "bad"})
    assert result["ok"] is False
    assert result["assets"] == []


# --------------------------------------------------------------------------- #
# platform / path guards
# --------------------------------------------------------------------------- #


def test_collect_returns_empty_on_non_linux(
    monkeypatch: pytest.MonkeyPatch, proc_root: Path
) -> None:
    _write_process(proc_root, 1)
    _use_proc(monkeypatch, proc_root, system="Darwin")

    result = _collector().collect()
    assert result["ok"] is True
    assert result["items"] == []


def test_collect_returns_empty_when_proc_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    missing = tmp_path / "does-not-exist"
    _use_proc(monkeypatch, missing, system="Linux")

    result = _collector().collect()
    assert result["ok"] is True
    assert result["items"] == []


# --------------------------------------------------------------------------- #
# registration
# --------------------------------------------------------------------------- #


def test_register_process_inventory_collector_is_idempotent() -> None:
    # Runs at import; calling again must not raise and must keep the module known.
    collectors._register_process_inventory_collector()
    registry = collectors.__dict__.get("MODULE_REGISTRY")
    if isinstance(registry, dict):
        module = registry.get("process-inventory")
        assert module is not None
        assert module.module_id == "process-inventory"


def test_register_supports_list_set_tuple_and_register_object(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict[str, Any] = {}

    class RegistryObject:
        # Rejects the 2-arg form so the module falls back to register(module).
        def register(self, module: Any) -> None:
            calls["register"] = module

    listed: list[Any] = []
    setted: set[Any] = set()
    monkeypatch.setattr(collectors, "COLLECTOR_MODULES", listed, raising=False)
    monkeypatch.setattr(collectors, "COLLECTORS", setted, raising=False)
    monkeypatch.setattr(collectors, "COLLECTOR_REGISTRY", RegistryObject(), raising=False)
    monkeypatch.setattr(collectors, "collector_registry", (), raising=False)
    monkeypatch.setattr(collectors, "__all__", [], raising=False)

    # First registration populates every shape.
    collectors._register_process_inventory_collector()
    # Second registration exercises the "already present" guards (list/tuple).
    collectors._register_process_inventory_collector()

    assert [getattr(m, "module_id", None) for m in listed].count("process-inventory") == 1
    assert any(getattr(m, "module_id", None) == "process-inventory" for m in setted)
    assert getattr(calls.get("register"), "module_id", None) == "process-inventory"
    assert (
        [getattr(m, "module_id", None) for m in collectors.collector_registry].count(
            "process-inventory"
        )
        == 1
    )
    assert "ProcessInventoryCollectorModule" in collectors.__all__


# --------------------------------------------------------------------------- #
# defensive read paths
# --------------------------------------------------------------------------- #


def test_collect_returns_empty_when_iterdir_raises(
    monkeypatch: pytest.MonkeyPatch, proc_root: Path
) -> None:
    _write_process(proc_root, 1)
    _use_proc(monkeypatch, proc_root)

    real_iterdir = Path.iterdir

    def boom(self: Path) -> Any:
        if self.name == "proc":
            raise OSError("boom")
        return real_iterdir(self)

    monkeypatch.setattr(Path, "iterdir", boom)
    assert _collector().collect()["items"] == []


def test_collect_handles_unreadable_cmdline(
    monkeypatch: pytest.MonkeyPatch, proc_root: Path
) -> None:
    entry = proc_root / "12"
    entry.mkdir()
    # Includes a non-Name/State line so the status parser exercises its skip branch.
    (entry / "status").write_text("Name:\tsvc\nPid:\t12\nState:\tS (sleeping)\n")
    (entry / "cmdline").mkdir()  # read_bytes -> IsADirectoryError (OSError) -> ""
    _use_proc(monkeypatch, proc_root)

    attrs = _collector().collect()["items"][0]["canonical_asset"]["attributes"]
    assert attrs["name"] == "svc"
    assert attrs["cmdline"] == ""


def test_read_proc_entry_returns_none_for_non_numeric_name(tmp_path: Path) -> None:
    entry = tmp_path / "notapid"
    entry.mkdir()
    assert Module._read_proc_entry(entry) is None
