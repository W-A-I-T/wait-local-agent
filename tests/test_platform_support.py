from __future__ import annotations

from pathlib import Path
from typing import cast

import wait_local_agent.platform_support as platform_support


def test_network_path_is_unknown_on_posix(monkeypatch) -> None:
    monkeypatch.setattr(platform_support.os, "name", "posix")

    assert platform_support.is_network_path(Path("/tmp/state.db")) is None


def test_unc_path_is_network_path_on_windows(monkeypatch) -> None:
    monkeypatch.setattr(platform_support, "is_windows", lambda: True)

    assert platform_support.is_network_path(Path(r"\\server\share\state.db")) is True


def test_drive_type_probe_identifies_windows_network_drive(monkeypatch) -> None:
    class DrivePath:
        anchor = "Z:\\"

        def __str__(self) -> str:
            return r"Z:\state.db"

    class Kernel32:
        @staticmethod
        def GetDriveTypeW(root: str) -> int:
            assert root == "Z:\\"
            return 4

    class WinDll:
        kernel32 = Kernel32()

    monkeypatch.setattr(platform_support, "is_windows", lambda: True)
    monkeypatch.setattr(platform_support.ctypes, "windll", WinDll(), raising=False)

    assert platform_support.is_network_path(cast(Path, DrivePath())) is True


def test_windows_local_path_without_drive_anchor_is_not_network(monkeypatch) -> None:
    class LocalPath:
        anchor = ""

        def __str__(self) -> str:
            return "relative-state.db"

    monkeypatch.setattr(platform_support, "is_windows", lambda: True)

    assert platform_support.is_network_path(cast(Path, LocalPath())) is False


def test_platform_predicates_follow_os_name(monkeypatch) -> None:
    monkeypatch.setattr(platform_support.os, "name", "nt")

    assert platform_support.is_windows() is True
    assert platform_support.posix_permissions_supported() is False
