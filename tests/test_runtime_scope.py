from __future__ import annotations

from pathlib import Path

import pytest

import wait_local_agent.runtime_scope as runtime_scope
from wait_local_agent.runtime_scope import collection_path, detect_collection_scope


def _write_marker(root: Path, relative_path: str, text: str) -> None:
    path = root / relative_path.lstrip("/")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_detect_collection_scope_is_unknown_without_positive_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("WAIT_COLLECTION_SCOPE", raising=False)
    monkeypatch.delenv("container", raising=False)
    monkeypatch.delenv("CONTAINER", raising=False)

    assert detect_collection_scope(root=tmp_path) == "unknown"


@pytest.mark.parametrize(
    ("relative_path", "content"),
    [
        (".dockerenv", ""),
        ("proc/1/cgroup", "0::/docker/abc123"),
        ("proc/1/cgroup", "0::/kubepods.slice/pod"),
        ("proc/1/sched", "docker-init (1, #threads: 1)"),
        ("proc/1/sched", "containerd-shim (1, #threads: 1)"),
        ("run/.containerenv", ""),
        ("proc/1/environ", "PATH=/usr/bin\0container=podman\0"),
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


def test_non_host_pid_one_process_name_is_container_evidence(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("WAIT_COLLECTION_SCOPE", raising=False)
    _write_marker(tmp_path, "proc/1/sched", "custom-init (1, #threads: 1)")

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

    assert detect_collection_scope(root=tmp_path) == "unknown"


@pytest.mark.parametrize("relative_path", ["proc/1/mountinfo", "proc/self/mountinfo"])
def test_detect_collection_scope_finds_overlay_root_mount(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    relative_path: str,
) -> None:
    monkeypatch.delenv("WAIT_COLLECTION_SCOPE", raising=False)
    _write_marker(
        tmp_path,
        relative_path,
        "36 25 0:32 / / rw,relatime - overlay overlay rw,lowerdir=/lower\n",
    )

    assert detect_collection_scope(root=tmp_path) == "container"


def test_cgroup_v2_root_without_other_evidence_is_unknown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("WAIT_COLLECTION_SCOPE", raising=False)
    _write_marker(tmp_path, "proc/1/cgroup", "0::/\n")

    assert detect_collection_scope(root=tmp_path) == "unknown"


def test_current_process_container_environment_is_detected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("WAIT_COLLECTION_SCOPE", raising=False)
    monkeypatch.setenv("container", "podman")

    assert detect_collection_scope(root=tmp_path) == "container"


def test_collection_path_applies_absolute_host_root_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("WAIT_HOST_ROOT", raising=False)
    assert collection_path("relative/file") == Path("relative/file")

    monkeypatch.setenv("WAIT_HOST_ROOT", str(tmp_path))

    assert collection_path("/etc/hosts") == tmp_path / "etc/hosts"
    with pytest.raises(ValueError, match="relative collector path"):
        collection_path("relative/file")
    monkeypatch.setenv("WAIT_HOST_ROOT", "relative-root")
    with pytest.raises(ValueError, match="absolute path"):
        collection_path("/etc/hosts")


@pytest.mark.parametrize("path", ["relative", "/tmp/../etc/passwd", "/../../etc/passwd"])
def test_rooted_path_rejects_unsafe_paths(tmp_path: Path, path: str) -> None:
    with pytest.raises(ValueError):
        runtime_scope._rooted_path(tmp_path, path)


def test_rooted_path_rejects_symlink_escape(tmp_path: Path) -> None:
    outside = tmp_path.parent / "wla-wp08-outside"
    outside.mkdir()
    (tmp_path / "etc").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="escapes"):
        runtime_scope._rooted_path(tmp_path, "/etc/passwd")


def test_host_override_with_relative_host_root_is_unknown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("WAIT_COLLECTION_SCOPE", "host")
    monkeypatch.setenv("WAIT_HOST_ROOT", "relative-root")

    assert detect_collection_scope(root=tmp_path) == "unknown"


def test_scope_helpers_tolerate_unreadable_marker_paths() -> None:
    class UnreadablePath:
        def is_file(self) -> bool:
            raise OSError("permission denied")

        def read_text(self, **_: object) -> str:
            raise OSError("permission denied")

    unreadable = UnreadablePath()
    assert runtime_scope._is_file(unreadable) is False  # type: ignore[arg-type]
    assert runtime_scope._read_text(unreadable) == ""  # type: ignore[arg-type]
