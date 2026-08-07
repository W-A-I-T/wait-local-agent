from __future__ import annotations

from pathlib import Path

import pytest

import wait_local_agent.runtime_scope as runtime_scope
from wait_local_agent.runtime_scope import collection_path, detect_collection_scope


def _write_marker(root: Path, relative_path: str, text: str) -> None:
    path = root / relative_path.lstrip("/")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_detect_collection_scope_defaults_to_host_without_markers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("WAIT_COLLECTION_SCOPE", raising=False)

    assert detect_collection_scope(root=tmp_path) == "host"


@pytest.mark.parametrize(
    ("relative_path", "content"),
    [
        (".dockerenv", ""),
        ("proc/1/cgroup", "0::/docker/abc123"),
        ("proc/1/cgroup", "0::/kubepods.slice/pod"),
        ("proc/1/sched", "docker-init (1, #threads: 1)"),
        ("proc/1/sched", "containerd-shim (1, #threads: 1)"),
    ],
)
def test_detect_collection_scope_finds_container_markers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    relative_path: str,
    content: str,
) -> None:
    monkeypatch.delenv("WAIT_COLLECTION_SCOPE", raising=False)
    _write_marker(tmp_path, relative_path, content)

    assert detect_collection_scope(root=tmp_path) == "container"


def test_collection_scope_override_wins_over_filesystem_detection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_marker(tmp_path, ".dockerenv", "")

    monkeypatch.setenv("WAIT_COLLECTION_SCOPE", "host")
    assert detect_collection_scope(root=tmp_path) == "host"
    monkeypatch.setenv("WAIT_COLLECTION_SCOPE", "container")
    assert detect_collection_scope(root=tmp_path) == "container"


def test_invalid_scope_override_is_ignored(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WAIT_COLLECTION_SCOPE", "not-a-scope")

    assert detect_collection_scope(root=tmp_path) == "host"


def test_collection_path_applies_absolute_host_root_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("WAIT_HOST_ROOT", str(tmp_path))

    assert collection_path("/etc/hosts") == tmp_path / "etc/hosts"
    assert collection_path("relative/file") == Path("relative/file")
    monkeypatch.setenv("WAIT_HOST_ROOT", "relative-root")
    assert collection_path("/etc/hosts") == Path("/etc/hosts")


def test_scope_helpers_tolerate_unreadable_marker_paths() -> None:
    class UnreadablePath:
        def is_file(self) -> bool:
            raise OSError("permission denied")

        def read_text(self, **_: object) -> str:
            raise OSError("permission denied")

    unreadable = UnreadablePath()
    assert runtime_scope._is_file(unreadable) is False  # type: ignore[arg-type]
    assert runtime_scope._read_text(unreadable) == ""  # type: ignore[arg-type]
