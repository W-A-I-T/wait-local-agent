"""Private file and directory creation plus platform-specific restrictions."""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import logging
import os
import uuid
from pathlib import Path
from typing import Any, Protocol, cast

from wait_local_agent import platform_support

LOGGER = logging.getLogger(__name__)

_DACL_SECURITY_INFORMATION = 0x00000004
_PROTECTED_DACL_SECURITY_INFORMATION = 0x80000000
_SE_FILE_OBJECT = 1
_SDDL_REVISION_1 = 1


class _PermissionBackend(Protocol):
    def restrict_file(self, path: Path) -> bool: ...

    def restrict_directory(self, path: Path) -> bool: ...


class _PosixBackend:
    @staticmethod
    def restrict_file(path: Path) -> bool:
        try:
            os.chmod(path, 0o600)
        except OSError:
            LOGGER.warning("could not restrict file permissions: %s", path)
            return False
        return True

    @staticmethod
    def restrict_directory(path: Path) -> bool:
        try:
            os.chmod(path, 0o700)
        except OSError:
            LOGGER.warning("could not restrict directory permissions: %s", path)
            return False
        return True


class _WindowsBackend:
    @staticmethod
    def restrict_file(path: Path) -> bool:
        return _apply_windows_dacl(path)

    @staticmethod
    def restrict_directory(path: Path) -> bool:
        return _apply_windows_dacl(path)


def _default_backend() -> _PermissionBackend:
    if platform_support.posix_permissions_supported():
        return _PosixBackend()
    return _WindowsBackend()


def open_private(path: Path, flags: int, *, exclusive: bool) -> int:
    """Open a private file with platform-compatible no-follow/binary flags."""

    safe_flags = flags | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    if exclusive:
        safe_flags |= os.O_EXCL
    return os.open(path, safe_flags, 0o600)


def write_private_bytes(path: Path, data: bytes, *, replace_existing: bool) -> None:
    """Write bytes with mode 0600, atomically replacing only when requested."""

    if not replace_existing:
        file_descriptor = open_private(path, os.O_WRONLY | os.O_CREAT, exclusive=True)
        try:
            with os.fdopen(file_descriptor, "wb") as handle:
                file_descriptor = -1
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
        finally:
            if file_descriptor >= 0:
                os.close(file_descriptor)
        return

    temporary_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    file_descriptor = -1
    try:
        file_descriptor = open_private(
            temporary_path, os.O_WRONLY | os.O_CREAT, exclusive=True
        )
        with os.fdopen(file_descriptor, "wb") as handle:
            file_descriptor = -1
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        if file_descriptor >= 0:
            os.close(file_descriptor)
        try:
            os.unlink(temporary_path)
        except FileNotFoundError:
            pass


def create_private_directory(path: Path, *, backend: _PermissionBackend | None = None) -> None:
    """Create a new private directory and apply a Windows DACL when needed."""

    if path.exists():
        return
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not platform_support.posix_permissions_supported():
        (backend or _default_backend()).restrict_directory(path)


def restrict_existing_file(
    path: Path, *, missing_ok: bool = False, backend: _PermissionBackend | None = None
) -> bool:
    """Restrict an existing file, logging and returning false on OS errors."""

    if missing_ok and not path.exists():
        return False
    try:
        return (backend or _default_backend()).restrict_file(path)
    except FileNotFoundError:
        if missing_ok:
            return False
        LOGGER.warning("could not restrict file permissions: %s", path)
        return False
    except OSError:
        LOGGER.warning("could not restrict file permissions: %s", path)
        return False


def restrict_existing_directory(
    path: Path, *, backend: _PermissionBackend | None = None
) -> bool:
    """Restrict an existing directory, logging and returning false on OS errors."""

    try:
        return (backend or _default_backend()).restrict_directory(path)
    except OSError:
        LOGGER.warning("could not restrict directory permissions: %s", path)
        return False


def _private_sddl(sid: str) -> str:
    return f"D:PAI(A;;FA;;;{sid})"


def _current_user_sid() -> str:  # pragma: no cover - raw Win32 SID syscall body
    """Resolve the current Windows token SID as an SDDL string."""

    windll = ctypes.windll  # type: ignore[attr-defined]
    win_error = cast(Any, ctypes.WinError)  # type: ignore[attr-defined]
    advapi32 = windll.advapi32
    kernel32 = windll.kernel32
    token = ctypes.wintypes.HANDLE()
    if not advapi32.OpenProcessToken(
        kernel32.GetCurrentProcess(), 0x0008, ctypes.byref(token)
    ):
        raise win_error()
    try:
        required = ctypes.wintypes.DWORD()
        advapi32.GetTokenInformation(token, 1, None, 0, ctypes.byref(required))
        buffer = ctypes.create_string_buffer(required.value)
        if not advapi32.GetTokenInformation(
            token, 1, buffer, required.value, ctypes.byref(required)
        ):
            raise win_error()
        sid_pointer = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_void_p))[0]
        sid_text = ctypes.wintypes.LPWSTR()
        if not advapi32.ConvertSidToStringSidW(sid_pointer, ctypes.byref(sid_text)):
            raise win_error()
        try:
            if sid_text.value is None:
                raise RuntimeError("Windows returned an empty user SID")
            return sid_text.value
        finally:
            kernel32.LocalFree(sid_text)
    finally:
        kernel32.CloseHandle(token)


def _apply_windows_dacl(path: Path) -> bool:  # pragma: no cover - raw Win32 ACL syscall body
    windll = ctypes.windll  # type: ignore[attr-defined]
    win_error = cast(Any, ctypes.WinError)  # type: ignore[attr-defined]
    sid = _current_user_sid()
    descriptor = ctypes.wintypes.LPVOID()
    if not windll.advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW(
        _private_sddl(sid), _SDDL_REVISION_1, ctypes.byref(descriptor), None
    ):
        raise win_error()
    try:
        dacl = ctypes.wintypes.LPVOID()
        dacl_present = ctypes.wintypes.BOOL()
        dacl_defaulted = ctypes.wintypes.BOOL()
        if not windll.advapi32.GetSecurityDescriptorDacl(
            descriptor, ctypes.byref(dacl_present), ctypes.byref(dacl), ctypes.byref(dacl_defaulted)
        ):
            raise win_error()
        result = windll.advapi32.SetNamedSecurityInfoW(
            str(path), _SE_FILE_OBJECT,
            _DACL_SECURITY_INFORMATION | _PROTECTED_DACL_SECURITY_INFORMATION,
            None, None, dacl, None,
        )
        if result:
            raise win_error(result)
    finally:
        windll.kernel32.LocalFree(descriptor)
    return True
