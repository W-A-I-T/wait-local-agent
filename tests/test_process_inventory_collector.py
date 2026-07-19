from __future__ import annotations

import builtins
import errno
import glob
import os
import platform
from pathlib import Path
from typing import Any

import pytest

from wait_local_agent.collectors import ProcessInventoryCollector


def _collector(config: dict[str, Any] | None = None) -> ProcessInventoryCollector:
    config = config or {}
    try:
        return ProcessInventoryCollector(config)
    except TypeError:
        collector = ProcessInventoryCollector()
        if hasattr(collector, "config"):
            collector.config = config
        return collector


def _call_validate_config(
    collector: ProcessInventoryCollector,
    config: dict[str, Any] | None = None,
) -> Any:
    if not hasattr(collector, "validate_config"):
        pytest.skip("collector has no validate_config method")

    if config is None:
        try:
            return collector.validate_config()
        except TypeError:
            return collector.validate_config({})

    try:
        return collector.validate_config(config)
    except TypeError:
        if hasattr(collector, "config"):
            collector.config = config
        return collector.validate_config()


def _unwrap_items(result: Any) -> list[Any]:
    if result is None:
        return []
    if isinstance(result, list):
        return result
    if isinstance(result, tuple):
        return list(result)
    if isinstance(result, dict):
        for key in ("processes", "items", "data", "results"):
            value = result.get(key)
            if isinstance(value, list):
                return value
        return [result]
    for attr in ("processes", "items", "data", "results"):
        value = getattr(result, attr, None)
        if isinstance(value, list):
            return value
    return [result]


def _item_value(item: Any, *names: str) -> Any:
    for name in names:
        if isinstance(item, dict) and name in item:
            return item[name]
        if hasattr(item, name):
            return getattr(item, name)
    return None


def _assert_valid_config_result(result: Any) -> None:
    if isinstance(result, dict) and "valid" in result:
        assert result["valid"] is True
        return

    assert result is None or result is True or result in ({}, [])


def _write_proc_entry(
    proc_root: Path,
    pid: int,
    *,
    stat_name: str,
    comm: str,
    cmdline: bytes,
    state: str = "S",
    status: str | None = None,
) -> Path:
    process_dir = proc_root / str(pid)
    process_dir.mkdir()
    (process_dir / "stat").write_text(
        f"{pid} ({stat_name}) {state} 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15\n",
        encoding="utf-8",
    )
    (process_dir / "comm").write_text(f"{comm}\n", encoding="utf-8")
    (process_dir / "cmdline").write_bytes(cmdline)
    (process_dir / "status").write_text(
        status
        or (
            f"Name:\t{comm}\n"
            f"State:\t{state} (sleeping)\n"
            f"Pid:\t{pid}\n"
            "PPid:\t1\n"
        ),
        encoding="utf-8",
    )
    return process_dir


def _patch_proc_root(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    proc_root = tmp_path / "proc"
    proc_root.mkdir()

    original_listdir = os.listdir
    original_scandir = os.scandir
    original_glob = glob.glob
    original_path_exists = os.path.exists
    original_path_isdir = os.path.isdir
    original_iterdir = Path.iterdir
    original_exists = Path.exists
    original_is_dir = Path.is_dir
    original_path_open = Path.open
    original_open = builtins.open

    def remap(value: Any) -> Any:
        if isinstance(value, int):
            return value
        path = os.fspath(value)
        if path == "/proc":
            return proc_root
        if path.startswith("/proc/"):
            return proc_root / path.removeprefix("/proc/")
        return value

    def fake_listdir(path: Any) -> list[str]:
        return original_listdir(remap(path))

    def fake_scandir(path: Any) -> os.ScandirIterator[str]:
        return original_scandir(remap(path))

    def fake_glob(pathname: Any, *args: Any, **kwargs: Any) -> list[str]:
        matches = original_glob(os.fspath(remap(pathname)), *args, **kwargs)
        return [
            f"/proc/{Path(match).relative_to(proc_root)}"
            if Path(match).is_relative_to(proc_root)
            else match
            for match in matches
        ]

    def fake_path_exists(path: Any) -> bool:
        return original_path_exists(remap(path))

    def fake_path_isdir(path: Any) -> bool:
        return original_path_isdir(remap(path))

    def fake_iterdir(self: Path) -> Any:
        return original_iterdir(remap(self))

    def fake_exists(self: Path) -> bool:
        return original_exists(remap(self))

    def fake_is_dir(self: Path) -> bool:
        return original_is_dir(remap(self))

    def fake_path_open(self: Path, *args: Any, **kwargs: Any) -> Any:
        return original_path_open(remap(self), *args, **kwargs)

    def fake_open(file: Any, *args: Any, **kwargs: Any) -> Any:
        return original_open(remap(file), *args, **kwargs)

    monkeypatch.setattr(os, "listdir", fake_listdir)
    monkeypatch.setattr(os, "scandir", fake_scandir)
    monkeypatch.setattr(glob, "glob", fake_glob)
    monkeypatch.setattr(os.path, "exists", fake_path_exists)
    monkeypatch.setattr(os.path, "isdir", fake_path_isdir)
    monkeypatch.setattr(Path, "iterdir", fake_iterdir)
    monkeypatch.setattr(Path, "exists", fake_exists)
    monkeypatch.setattr(Path, "is_dir", fake_is_dir)
    monkeypatch.setattr(Path, "open", fake_path_open)
    monkeypatch.setattr(builtins, "open", fake_open)
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    return proc_root


def test_process_inventory_validate_config_accepts_default_config() -> None:
    result = _call_validate_config(_collector())

    _assert_valid_config_result(result)


@pytest.mark.parametrize(
    "config",
    [
        {"enabled": True},
    ],
)
def test_process_inventory_validate_config_accepts_common_options(
    config: dict[str, Any],
) -> None:
    result = _call_validate_config(_collector(config), config)

    _assert_valid_config_result(result)


def test_process_inventory_preview_reads_mocked_proc_without_cmdline(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    proc_root = _patch_proc_root(monkeypatch, tmp_path)
    _write_proc_entry(
        proc_root,
        101,
        stat_name="python3",
        comm="python3",
        cmdline=b"",
        state="S",
    )
    (proc_root / "self").mkdir()

    result = _collector().preview()
    items = _unwrap_items(result)

    assert items
    item = items[0]
    pid = _item_value(item, "pid")
    if pid is not None:
        assert pid in (101, "101")
    name = _item_value(item, "name", "comm", "process_name")
    if name is not None:
        assert name == "python3"
    cmdline = _item_value(item, "cmdline", "command", "command_line", "args")
    assert cmdline in ("", [], None)


def test_process_inventory_collect_parses_pid_name_cmdline_and_state(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    proc_root = _patch_proc_root(monkeypatch, tmp_path)
    _write_proc_entry(
        proc_root,
        4242,
        stat_name="worker",
        comm="worker",
        cmdline=b"/usr/bin/worker\x00--queue\x00critical\x00",
        state="R",
        status=(
            "Name:\tworker\n"
            "State:\tR (running)\n"
            "Pid:\t4242\n"
            "PPid:\t7\n"
        ),
    )
    _write_proc_entry(
        proc_root,
        77,
        stat_name="name with spaces",
        comm="spacey",
        cmdline=b"spacey\x00--flag\x00",
        state="T",
    )
    (proc_root / "not-a-pid").mkdir()

    result = _collector().collect()
    items = _unwrap_items(result)

    by_pid = {str(_item_value(item, "pid")): item for item in items}
    assert set(by_pid) == {"4242", "77"}

    worker = by_pid["4242"]
    assert _item_value(worker, "name", "comm", "process_name") == "worker"
    worker_cmdline = str(_item_value(worker, "cmdline", "command", "command_line", "args"))
    assert "worker" in worker_cmdline
    assert "critical" in worker_cmdline
    assert _item_value(worker, "state", "status") in ("R", "running", "R (running)", None)

    spaced = by_pid["77"]
    assert _item_value(spaced, "name", "comm", "process_name") in (
        "spacey",
        "name with spaces",
    )
    assert _item_value(spaced, "state", "status") in ("T", "stopped", "T (stopped)", None)


def test_process_inventory_collect_skips_missing_process_files(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    proc_root = _patch_proc_root(monkeypatch, tmp_path)
    _write_proc_entry(
        proc_root,
        10,
        stat_name="alive",
        comm="alive",
        cmdline=b"alive\x00",
        state="S",
    )
    disappearing = _write_proc_entry(
        proc_root,
        11,
        stat_name="gone",
        comm="gone",
        cmdline=b"gone\x00",
        state="S",
    )
    (disappearing / "stat").unlink()

    result = _collector().collect()
    pids = [str(_item_value(item, "pid")) for item in _unwrap_items(result)]

    assert pids == ["10"]


def test_process_inventory_collect_skips_permission_denied_process(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    proc_root = _patch_proc_root(monkeypatch, tmp_path)
    _write_proc_entry(
        proc_root,
        20,
        stat_name="visible",
        comm="visible",
        cmdline=b"visible\x00",
        state="S",
    )
    _write_proc_entry(
        proc_root,
        21,
        stat_name="private",
        comm="private",
        cmdline=b"private\x00",
        state="S",
    )

    fake_proc_open = builtins.open
    fake_proc_path_open = Path.open

    def permission_error_for_private(file: Any, *args: Any, **kwargs: Any) -> Any:
        path = os.fspath(file)
        if "/21/" in path:
            raise PermissionError(errno.EACCES, os.strerror(errno.EACCES), path)
        return fake_proc_open(file, *args, **kwargs)

    def permission_error_for_private_path(
        self: Path,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        path = os.fspath(self)
        if "/21/" in path:
            raise PermissionError(errno.EACCES, os.strerror(errno.EACCES), path)
        return fake_proc_path_open(self, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", permission_error_for_private)
    monkeypatch.setattr(Path, "open", permission_error_for_private_path)

    result = _collector().collect()
    pids = [str(_item_value(item, "pid")) for item in _unwrap_items(result)]

    assert pids == ["20"]


def test_process_inventory_collect_returns_empty_without_proc(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    proc_root = _patch_proc_root(monkeypatch, tmp_path)
    proc_root.rmdir()

    assert _unwrap_items(_collector().collect()) == []


def test_process_inventory_preview_and_collect_return_empty_on_non_linux(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(platform, "system", lambda: "Darwin")

    def fail_real_proc_access(path: Any, *args: Any, **kwargs: Any) -> Any:
        if os.fspath(path).startswith("/proc"):
            pytest.fail("non-Linux path must not read /proc")
        return []

    monkeypatch.setattr(os, "listdir", fail_real_proc_access)
    monkeypatch.setattr(os, "scandir", fail_real_proc_access)

    assert _unwrap_items(_collector().preview()) == []
    assert _unwrap_items(_collector().collect()) == []
