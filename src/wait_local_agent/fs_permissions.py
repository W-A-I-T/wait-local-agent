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


def _configure_windows_api(windll: Any) -> None:
    """Declare pointer-sized signatures for the Win32 calls used below."""

    kernel32 = windll.kernel32
    advapi32 = windll.advapi32
    kernel32.GetCurrentProcess.argtypes = []
    kernel32.GetCurrentProcess.restype = ctypes.wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [ctypes.wintypes.HANDLE]
    kernel32.CloseHandle.restype = ctypes.wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.wintypes.HLOCAL]
    kernel32.LocalFree.restype = ctypes.wintypes.HLOCAL
    advapi32.OpenProcessToken.argtypes = [
        ctypes.wintypes.HANDLE,
        ctypes.wintypes.DWORD,
        ctypes.POINTER(ctypes.wintypes.HANDLE),
    ]
    advapi32.OpenProcessToken.restype = ctypes.wintypes.BOOL
    advapi32.GetTokenInformation.argtypes = [
        ctypes.wintypes.HANDLE,
        ctypes.wintypes.DWORD,
        ctypes.wintypes.LPVOID,
        ctypes.wintypes.DWORD,
        ctypes.POINTER(ctypes.wintypes.DWORD),
    ]
    advapi32.GetTokenInformation.restype = ctypes.wintypes.BOOL
    advapi32.ConvertSidToStringSidW.argtypes = [
        ctypes.wintypes.LPVOID,
        ctypes.POINTER(ctypes.wintypes.LPWSTR),
    ]
    advapi32.ConvertSidToStringSidW.restype = ctypes.wintypes.BOOL
    advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
        ctypes.wintypes.LPCWSTR,
        ctypes.wintypes.DWORD,
        ctypes.POINTER(ctypes.wintypes.LPVOID),
        ctypes.POINTER(ctypes.wintypes.DWORD),
    ]
    advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = ctypes.wintypes.BOOL
    advapi32.GetSecurityDescriptorDacl.argtypes = [
        ctypes.wintypes.LPVOID,
        ctypes.POINTER(ctypes.wintypes.BOOL),
        ctypes.POINTER(ctypes.wintypes.LPVOID),
        ctypes.POINTER(ctypes.wintypes.BOOL),
    ]
    advapi32.GetSecurityDescriptorDacl.restype = ctypes.wintypes.BOOL
    advapi32.SetNamedSecurityInfoW.argtypes = [
        ctypes.wintypes.LPCWSTR,
        ctypes.wintypes.DWORD,
        ctypes.wintypes.DWORD,
        ctypes.wintypes.LPVOID,
        ctypes.wintypes.LPVOID,
        ctypes.wintypes.LPVOID,
        ctypes.wintypes.LPVOID,
    ]
    advapi32.SetNamedSecurityInfoW.restype = ctypes.wintypes.DWORD


def open_private(path: Path, flags: int, *, exclusive: bool) -> int:
    """Open a private file with platform-compatible no-follow/binary flags."""

    safe_flags = flags | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    if exclusive:
        safe_flags |= os.O_EXCL
    file_descriptor = os.open(path, safe_flags, 0o600)
    if not platform_support.posix_permissions_supported():
        # The file is now present but no caller has written secret bytes yet.
        # ACL failures are deliberately logged by the shared helper and do not
        # destroy the otherwise usable artifact path.
        restrict_existing_file(path)
    return file_descriptor


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
        except (FileNotFoundError, PermissionError):
            pass


def create_private_directory(
    path: Path,
    *,
    backend: _PermissionBackend | None = None,
    restrict_existing: bool = False,
) -> None:
    """Create a private directory and optionally restrict an existing one."""

    if path.exists():
        if restrict_existing and not platform_support.posix_permissions_supported():
            restrict_existing_directory(path, backend=backend)
        return
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not platform_support.posix_permissions_supported():
        restrict_existing_directory(path, backend=backend)


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
    _configure_windows_api(windll)
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
    _configure_windows_api(windll)
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
