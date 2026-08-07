"""Runtime and filesystem scope helpers for local collection."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal, cast

CollectionScope = Literal["host", "container"]

_CONTAINER_MARKERS = ("container", "docker", "kubepods")


def detect_collection_scope(*, root: str | os.PathLike[str] = "/") -> CollectionScope:
    """Detect whether collection is running on a host or in a container.

    ``WAIT_COLLECTION_SCOPE`` is an explicit operator assertion used by the
    host-collection Compose profile. Invalid values are ignored so they cannot
    make an execution claim that the detector does not understand.
    """

    override = os.environ.get("WAIT_COLLECTION_SCOPE", "").strip().lower()
    if override in {"host", "container"}:
        return cast(CollectionScope, override)

    filesystem_root = Path(root)
    if _is_file(_rooted_path(filesystem_root, "/.dockerenv")):
        return "container"

    for marker_path in ("/proc/1/cgroup", "/proc/1/sched"):
        if _has_container_marker(_read_text(_rooted_path(filesystem_root, marker_path))):
            return "container"
    return "host"


def collection_path(path: str | os.PathLike[str]) -> Path:
    """Return a collector path, optionally rooted at ``WAIT_HOST_ROOT``."""

    candidate = Path(path)
    prefix = os.environ.get("WAIT_HOST_ROOT", "").strip()
    if not prefix or not candidate.is_absolute():
        return candidate
    prefix_path = Path(prefix)
    if not prefix_path.is_absolute():
        return candidate
    return _rooted_path(prefix_path, candidate)


def _rooted_path(root: Path, absolute_path: str | os.PathLike[str]) -> Path:
    return root / Path(absolute_path).relative_to("/")


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
