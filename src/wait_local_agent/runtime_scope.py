"""Runtime and filesystem scope helpers for local collection."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Literal, cast

CollectionScope = Literal["host", "container", "unknown"]

_CONTAINER_MARKERS = ("container", "docker", "kubepods", "libpod", "crio", "nerdctl", "podman")
_HOST_PROCESS_NAMES = {"init", "systemd"}


def detect_collection_scope(*, root: str | os.PathLike[str] = "/") -> CollectionScope:
    """Detect whether collection is running on a host or in a container.

    ``WAIT_COLLECTION_SCOPE`` is an explicit operator assertion used by the
    host-collection Compose profile. Invalid values are ignored so they cannot
    make an execution claim that the detector does not understand.
    """

    override = os.environ.get("WAIT_COLLECTION_SCOPE", "").strip().lower()
    if override in {"host", "container"}:
        if override == "host" and not _host_root_configuration_is_safe():
            return "unknown"
        return cast(CollectionScope, override)

    filesystem_root = Path(root)
    if any(
        _is_file(_rooted_path(filesystem_root, marker_path))
        for marker_path in ("/.dockerenv", "/run/.containerenv")
    ):
        return "container"

    if _environment_has_container_hint(os.environ):
        return "container"
    if _environment_has_container_hint(
        _split_environment(_read_text(_rooted_path(filesystem_root, "/proc/1/environ")))
    ):
        return "container"

    for marker_path in ("/proc/1/cgroup", "/proc/1/sched"):
        if _has_container_marker(_read_text(_rooted_path(filesystem_root, marker_path))):
            return "container"

    if _root_mount_is_overlay(filesystem_root):
        return "container"

    sched_name = _sched_process_name(_read_text(_rooted_path(filesystem_root, "/proc/1/sched")))
    if sched_name and sched_name not in _HOST_PROCESS_NAMES:
        return "container"

    # cgroup v2's 0::/ and a non-overlay root are also possible on a host.
    # Without a positive host assertion, fail closed instead of claiming host.
    return "unknown"


def collection_path(path: str | os.PathLike[str]) -> Path:
    """Return a collector path, optionally rooted at ``WAIT_HOST_ROOT``."""

    candidate = Path(path)
    prefix = os.environ.get("WAIT_HOST_ROOT", "").strip()
    if not prefix:
        return candidate
    if not candidate.is_absolute():
        raise ValueError("WAIT_HOST_ROOT cannot safely rebase a relative collector path")
    prefix_path = Path(prefix)
    if not prefix_path.is_absolute():
        raise ValueError("WAIT_HOST_ROOT must be an absolute path")
    return _rooted_path(prefix_path, candidate)


def _rooted_path(root: Path, absolute_path: str | os.PathLike[str]) -> Path:
    candidate = Path(absolute_path)
    if not candidate.is_absolute():
        raise ValueError("rooted paths must be absolute")
    if ".." in candidate.parts:
        raise ValueError("rooted paths must not contain '..' segments")

    resolved_root = root.resolve(strict=False)
    resolved_candidate = (resolved_root / candidate.relative_to("/")).resolve(strict=False)
    try:
        resolved_candidate.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError("rooted path escapes the configured root") from exc
    return resolved_candidate


def _host_root_configuration_is_safe() -> bool:
    prefix = os.environ.get("WAIT_HOST_ROOT", "").strip()
    return not prefix or Path(prefix).is_absolute()


def _split_environment(text: str) -> dict[str, str]:
    return {
        key_value.split("=", 1)[0]: key_value.split("=", 1)[1]
        for key_value in text.split("\0")
        if "=" in key_value
    }


def _environment_has_container_hint(environment: Mapping[str, str]) -> bool:
    return any(key.lower() == "container" and value.strip() for key, value in environment.items())


def _root_mount_is_overlay(root: Path) -> bool:
    for marker_path in ("/proc/self/mountinfo", "/proc/1/mountinfo"):
        for line in _read_text(_rooted_path(root, marker_path)).splitlines():
            before_separator, separator, after_separator = line.partition(" - ")
            fields = before_separator.split()
            if separator and len(fields) > 4 and fields[4] == "/":
                filesystem_type = after_separator.split(maxsplit=1)[0]
                if filesystem_type == "overlay":
                    return True
    return False


def _sched_process_name(text: str) -> str:
    lines = text.splitlines()
    first_line = lines[0] if lines else ""
    return first_line.split(" ", 1)[0].strip().lower()


def _is_file(path: Path) -> bool:
    try:
        return path.is_file()
    except OSError:
        return False


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _has_container_marker(text: str) -> bool:
    normalized = text.lower()
    return any(marker in normalized for marker in _CONTAINER_MARKERS)
