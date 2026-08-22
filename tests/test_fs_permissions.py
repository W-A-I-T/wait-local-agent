from __future__ import annotations

import logging
import os
import stat
from pathlib import Path

import pytest

import wait_local_agent.fs_permissions as fs_permissions
import wait_local_agent.platform_support as platform_support


@pytest.mark.skipif(os.name != "posix", reason="POSIX mode bits are not Windows permissions")
def test_create_private_directory_uses_mode_700(tmp_path: Path) -> None:
    directory = tmp_path / "private" / "nested"

    fs_permissions.create_private_directory(directory)

    assert stat.S_IMODE(directory.stat().st_mode) == 0o700


def test_create_private_directory_dispatches_to_fake_windows_backend(tmp_path: Path, monkeypatch) -> None:
    calls: list[Path] = []

    class FakeBackend:
        def restrict_file(self, path: Path) -> bool:
            return True

        def restrict_directory(self, path: Path) -> bool:
            calls.append(path)
            return True

    monkeypatch.setattr(platform_support, "posix_permissions_supported", lambda: False)
    directory = tmp_path / "windows-private"

    fs_permissions.create_private_directory(directory, backend=FakeBackend())

    assert calls == [directory]


def test_create_private_directory_logs_backend_failure(
    tmp_path: Path, monkeypatch, caplog
) -> None:
    class FailingBackend:
        def restrict_file(self, _path: Path) -> bool:
            return True

        def restrict_directory(self, _path: Path) -> bool:
            raise OSError("ACL failed")

    monkeypatch.setattr(platform_support, "posix_permissions_supported", lambda: False)
    directory = tmp_path / "windows-private"
    with caplog.at_level(logging.WARNING, logger=fs_permissions.LOGGER.name):
        fs_permissions.create_private_directory(directory, backend=FailingBackend())

    assert directory.is_dir()
    assert str(directory) in caplog.text


def test_create_private_directory_returns_for_existing_path(tmp_path: Path) -> None:
    directory = tmp_path / "existing"
    directory.mkdir()

    fs_permissions.create_private_directory(directory)

    assert directory.is_dir()


def test_existing_private_directory_requires_explicit_windows_restriction(
    tmp_path: Path, monkeypatch
) -> None:
    calls: list[Path] = []

    class FakeBackend:
        def restrict_file(self, _path: Path) -> bool:
            return True

        def restrict_directory(self, path: Path) -> bool:
            calls.append(path)
            return True

    directory = tmp_path / "existing"
    directory.mkdir()
    monkeypatch.setattr(platform_support, "posix_permissions_supported", lambda: False)

    fs_permissions.create_private_directory(directory, backend=FakeBackend())
    assert calls == []

    fs_permissions.create_private_directory(
        directory, backend=FakeBackend(), restrict_existing=True
    )
    assert calls == [directory]


def test_restrict_existing_file_logs_os_error(tmp_path: Path, monkeypatch, caplog) -> None:
    path = tmp_path / "secret"
    path.write_bytes(b"secret")

    def fail_chmod(*_args) -> None:
        raise OSError("permission denied")

    monkeypatch.setattr(fs_permissions.os, "chmod", fail_chmod)
    with caplog.at_level(logging.WARNING, logger=fs_permissions.LOGGER.name):
        assert (
            fs_permissions.restrict_existing_file(
                path, backend=fs_permissions._PosixBackend()
            )
            is False
        )

    assert str(path) in caplog.text


@pytest.mark.skipif(os.name != "posix", reason="POSIX mode bits are not Windows permissions")
def test_posix_backend_restricts_file(tmp_path: Path) -> None:
    path = tmp_path / "file"
    path.write_bytes(b"secret")

    assert fs_permissions._PosixBackend.restrict_file(path) is True
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_posix_backend_logs_directory_chmod_error(tmp_path: Path, monkeypatch, caplog) -> None:
    path = tmp_path / "directory"
    path.mkdir()

    def fail_chmod(*_args) -> None:
        raise OSError("permission denied")

    monkeypatch.setattr(fs_permissions.os, "chmod", fail_chmod)
    with caplog.at_level(logging.WARNING, logger=fs_permissions.LOGGER.name):
        assert fs_permissions._PosixBackend.restrict_directory(path) is False

    assert str(path) in caplog.text


def test_posix_backend_logs_file_chmod_error(tmp_path: Path, monkeypatch, caplog) -> None:
    path = tmp_path / "file"
    path.write_bytes(b"secret")

    def fail_chmod(*_args) -> None:
        raise OSError("permission denied")

    monkeypatch.setattr(fs_permissions.os, "chmod", fail_chmod)
    with caplog.at_level(logging.WARNING, logger=fs_permissions.LOGGER.name):
        assert fs_permissions._PosixBackend.restrict_file(path) is False

    assert str(path) in caplog.text


def test_default_backend_selects_posix_and_windows(monkeypatch) -> None:
    monkeypatch.setattr(platform_support, "posix_permissions_supported", lambda: True)
    assert isinstance(fs_permissions._default_backend(), fs_permissions._PosixBackend)

    monkeypatch.setattr(platform_support, "posix_permissions_supported", lambda: False)
    assert isinstance(fs_permissions._default_backend(), fs_permissions._WindowsBackend)


def test_windows_backend_dispatches_file_and_directory(monkeypatch, tmp_path: Path) -> None:
    calls: list[Path] = []

    def apply_dacl(path: Path) -> bool:
        calls.append(path)
        return True

    monkeypatch.setattr(
        fs_permissions, "_apply_windows_dacl", apply_dacl
    )
    backend = fs_permissions._WindowsBackend()
    file_path = tmp_path / "file"
    directory_path = tmp_path / "directory"

    assert backend.restrict_file(file_path) is True
    assert backend.restrict_directory(directory_path) is True
    assert calls == [file_path, directory_path]


def test_open_private_adds_optional_flags_and_exclusive(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "private"
    monkeypatch.delattr(fs_permissions.os, "O_NOFOLLOW", raising=False)
    monkeypatch.delattr(fs_permissions.os, "O_BINARY", raising=False)

    descriptor = fs_permissions.open_private(path, os.O_WRONLY | os.O_CREAT, exclusive=True)
    os.close(descriptor)

    with pytest.raises(FileExistsError):
        fs_permissions.open_private(path, os.O_WRONLY | os.O_CREAT, exclusive=True)


def test_open_private_nonexclusive_does_not_require_exclusive(tmp_path: Path) -> None:
    path = tmp_path / "private"
    path.write_bytes(b"existing")

    descriptor = fs_permissions.open_private(path, os.O_WRONLY, exclusive=False)
    os.close(descriptor)


def test_open_private_dispatches_to_windows_backend_before_write(
    tmp_path: Path, monkeypatch
) -> None:
    calls: list[Path] = []

    class FakeBackend:
        def restrict_file(self, path: Path) -> bool:
            calls.append(path)
            return True

        def restrict_directory(self, _path: Path) -> bool:
            return True

    monkeypatch.setattr(platform_support, "posix_permissions_supported", lambda: False)
    monkeypatch.setattr(fs_permissions, "_default_backend", lambda: FakeBackend())
    path = tmp_path / "private"

    descriptor = fs_permissions.open_private(path, os.O_WRONLY | os.O_CREAT, exclusive=True)
    os.close(descriptor)

    assert calls == [path]


def test_write_private_bytes_closes_descriptor_when_open_fails(
    tmp_path: Path, monkeypatch
) -> None:
    path = tmp_path / "secret"

    def fail_fdopen(*_args, **_kwargs):
        raise OSError("fdopen failed")

    monkeypatch.setattr(fs_permissions.os, "fdopen", fail_fdopen)
    with pytest.raises(OSError, match="fdopen failed"):
        fs_permissions.write_private_bytes(path, b"secret", replace_existing=False)

    path.unlink()


def test_write_private_bytes_rejects_existing_file(tmp_path: Path) -> None:
    path = tmp_path / "secret"
    fs_permissions.write_private_bytes(path, b"first", replace_existing=False)

    with pytest.raises(FileExistsError):
        fs_permissions.write_private_bytes(path, b"second", replace_existing=False)


def test_replace_existing_private_bytes_closes_descriptor_when_open_fails(
    tmp_path: Path, monkeypatch
) -> None:
    path = tmp_path / "secret"

    def fail_fdopen(*_args, **_kwargs):
        raise OSError("fdopen failed")

    monkeypatch.setattr(fs_permissions.os, "fdopen", fail_fdopen)
    with pytest.raises(OSError, match="fdopen failed"):
        fs_permissions.write_private_bytes(path, b"secret", replace_existing=True)

    assert list(tmp_path.glob(".secret.*.tmp")) == []


def test_replace_existing_private_bytes_cleans_temp_on_write_error(
    tmp_path: Path, monkeypatch
) -> None:
    path = tmp_path / "secret"
    fs_permissions.write_private_bytes(path, b"first", replace_existing=False)

    def fail_fsync(*_args) -> None:
        raise OSError("fsync failed")

    monkeypatch.setattr(fs_permissions.os, "fsync", fail_fsync)
    with pytest.raises(OSError, match="fsync failed"):
        fs_permissions.write_private_bytes(path, b"second", replace_existing=True)

    assert path.read_bytes() == b"first"
    assert list(tmp_path.glob(".secret.*.tmp")) == []


def test_restrict_existing_file_missing_paths_and_backend_errors(tmp_path: Path, caplog) -> None:
    missing = tmp_path / "missing"

    assert fs_permissions.restrict_existing_file(missing, missing_ok=True) is False
    with caplog.at_level(logging.WARNING, logger=fs_permissions.LOGGER.name):
        assert fs_permissions.restrict_existing_file(missing) is False
    assert str(missing) in caplog.text

    class MissingBackend:
        def restrict_file(self, _path: Path) -> bool:
            raise FileNotFoundError

        def restrict_directory(self, _path: Path) -> bool:
            return True

    class ErrorBackend:
        def restrict_file(self, _path: Path) -> bool:
            raise OSError("permission denied")

        def restrict_directory(self, _path: Path) -> bool:
            return True

    existing = tmp_path / "existing"
    existing.write_bytes(b"data")
    assert (
        fs_permissions.restrict_existing_file(
            existing, missing_ok=True, backend=MissingBackend()
        )
        is False
    )
    assert fs_permissions.restrict_existing_file(missing, backend=MissingBackend()) is False
    assert fs_permissions.restrict_existing_file(existing, backend=ErrorBackend()) is False


def test_restrict_existing_directory_success_and_error(tmp_path: Path, caplog) -> None:
    directory = tmp_path / "directory"
    directory.mkdir()
    assert fs_permissions.restrict_existing_directory(directory) is True

    class FailingBackend:
        def restrict_file(self, _path: Path) -> bool:
            return True

        def restrict_directory(self, _path: Path) -> bool:
            raise OSError("permission denied")

    with caplog.at_level(logging.WARNING, logger=fs_permissions.LOGGER.name):
        assert (
            fs_permissions.restrict_existing_directory(
                directory, backend=FailingBackend()
            )
            is False
        )
    assert str(directory) in caplog.text


def test_private_sddl_protects_inherited_acl() -> None:
    assert fs_permissions._private_sddl("S-1-5-21-1-1-1-1000") == "D:PAI(A;;FA;;;S-1-5-21-1-1-1-1000)"


def test_windows_api_signatures_are_pointer_safe() -> None:
    class Function:
        restype: object
        argtypes: object

    class Dll:
        class Kernel32:
            GetCurrentProcess = Function()
            CloseHandle = Function()
            LocalFree = Function()

        class Advapi32:
            OpenProcessToken = Function()
            GetTokenInformation = Function()
            ConvertSidToStringSidW = Function()
            ConvertStringSecurityDescriptorToSecurityDescriptorW = Function()
            GetSecurityDescriptorDacl = Function()
            SetNamedSecurityInfoW = Function()

        kernel32 = Kernel32()
        advapi32 = Advapi32()

    fs_permissions._configure_windows_api(Dll())
    assert Dll.Kernel32.GetCurrentProcess.restype is fs_permissions.ctypes.wintypes.HANDLE
    assert Dll.Advapi32.OpenProcessToken.restype is fs_permissions.ctypes.wintypes.BOOL
    assert Dll.Advapi32.SetNamedSecurityInfoW.restype is fs_permissions.ctypes.wintypes.DWORD


@pytest.mark.skipif(
    not platform_support.posix_permissions_supported(),
    reason="POSIX mode bits are not Windows permissions",
)
def test_replace_existing_private_bytes_is_atomic(tmp_path: Path) -> None:
    path = tmp_path / "secret"
    fs_permissions.write_private_bytes(path, b"first", replace_existing=False)
    fs_permissions.write_private_bytes(path, b"second", replace_existing=True)

    assert path.read_bytes() == b"second"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
