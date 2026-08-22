"""Read-only platform predicates used by runtime portability boundaries.

Consumers must import this module and resolve predicates through the module,
for example ``platform_support.is_windows()``.  Do not import a predicate
directly: tests cover platform branches on Linux by monkeypatching this module.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import os
from pathlib import Path
from typing import Any


def _configure_windows_api(windll: Any) -> None:
    """Declare the pointer-safe signature for the drive-type probe."""

    get_drive_type = windll.kernel32.GetDriveTypeW
    get_drive_type.argtypes = [ctypes.wintypes.LPCWSTR]
    get_drive_type.restype = ctypes.wintypes.UINT


def is_windows() -> bool:
    """Return whether the current Python runtime uses Windows semantics."""

    return os.name == "nt"


def posix_permissions_supported() -> bool:
    """Return whether POSIX mode bits are meaningful for local files."""

    return os.name == "posix"


def is_network_path(path: Path) -> bool | None:
    """Return Windows network-path status, or ``None`` when unknown on POSIX.

    POSIX mount inspection is intentionally not attempted because overlayfs
    and container mount layouts make it unreliable.  Windows uses the UNC
    prefix and the Win32 drive-type probe instead.
    """

    if not is_windows():
        return None
    value = str(path)
    if value.startswith("\\\\"):
        return True
    drive_root = path.anchor
    if not drive_root:
        return False
    windll = ctypes.windll  # type: ignore[attr-defined]
    _configure_windows_api(windll)
    return windll.kernel32.GetDriveTypeW(drive_root) == 4
