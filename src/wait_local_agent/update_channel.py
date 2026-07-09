from __future__ import annotations

import json
import re
import time
from base64 import urlsafe_b64decode
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, cast

import httpx
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from wait_local_agent import __version__
from wait_local_agent.config import Settings

_SEMVER_RE = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_BASE64URL_RE = re.compile(r"^[A-Za-z0-9_-]+$")

UpdateState = Literal["update_available", "up_to_date", "unknown", "invalid_signature"]


@dataclass(frozen=True, order=True)
class _PrereleaseToken:
    numeric: bool
    value: int | str


@dataclass(frozen=True)
class SemVer:
    major: int
    minor: int
    patch: int
    prerelease: tuple[_PrereleaseToken, ...] = ()

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, SemVer):
            return NotImplemented
        if (self.major, self.minor, self.patch) != (other.major, other.minor, other.patch):
            return (self.major, self.minor, self.patch) < (other.major, other.minor, other.patch)
        if not self.prerelease and not other.prerelease:
            return False
        if not self.prerelease:
            return False
        if not other.prerelease:
            return True
        for left, right in zip(self.prerelease, other.prerelease, strict=False):
            if left == right:
                continue
            if left.numeric and right.numeric:
                return cast(int, left.value) < cast(int, right.value)
            if left.numeric != right.numeric:
                return left.numeric
            return cast(str, left.value) < cast(str, right.value)
        return len(self.prerelease) < len(other.prerelease)


@dataclass(frozen=True)
class UpdateMetadata:
    version: str
    released: str
    sha256: str
    signature: str
    min_supported: str
    notes_url: str


@dataclass(frozen=True)
class UpdateStatus:
    status: UpdateState
    current_version: str
    checked_at: str
    detail: str = ""
    remote_version: str | None = None
    min_supported: str | None = None
    notes_url: str | None = None
    warning: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "current_version": self.current_version,
            "checked_at": self.checked_at,
            "detail": self.detail,
            "remote_version": self.remote_version,
            "min_supported": self.min_supported,
            "notes_url": self.notes_url,
            "warning": self.warning,
        }


@dataclass
class _CachedStatus:
    status: UpdateStatus
    expires_at: float


class UpdateStatusCache:
    def __init__(self, ttl_seconds: float = 3600.0) -> None:
        self._ttl_seconds = ttl_seconds
        self._cached: _CachedStatus | None = None

    def get_status(
        self,
        loader: Callable[[], UpdateStatus],
        *,
        now: float | None = None,
    ) -> UpdateStatus:
        current_time = time.time() if now is None else now
        if self._cached is not None and current_time < self._cached.expires_at:
            return self._cached.status
        status = loader()
        self._cached = _CachedStatus(status=status, expires_at=current_time + self._ttl_seconds)
        return status


def check_for_updates(
    settings: Settings,
    *,
    transport: httpx.BaseTransport | None = None,
    now: datetime | None = None,
) -> UpdateStatus:
    checked_at = _checked_at(now)
    current_version = __version__
    if not settings.update_channel_url:
        return UpdateStatus(
            status="unknown",
            current_version=current_version,
            checked_at=checked_at,
            detail="disabled",
        )
    if not settings.update_pubkeys:
        return UpdateStatus(
            status="unknown",
            current_version=current_version,
            checked_at=checked_at,
            detail="misconfigured",
            warning="update checks require at least one pinned public key",
        )

    try:
        document = fetch_update_metadata_bytes(
            settings.update_channel_url,
            timeout_seconds=settings.connector_timeout_seconds,
            transport=transport,
        )
    except (httpx.TimeoutException, httpx.ConnectError, httpx.HTTPError):
        return UpdateStatus(
            status="unknown",
            current_version=current_version,
            checked_at=checked_at,
            detail="unreachable",
        )

    try:
        metadata, canonical_bytes = parse_update_metadata_document(document)
        verify_update_signature(metadata, canonical_bytes, settings.update_pubkeys)
        remote_version = parse_semver(metadata.version)
        installed_version = parse_semver(current_version)
        if installed_version < remote_version:
            return UpdateStatus(
                status="update_available",
                current_version=current_version,
                checked_at=checked_at,
                detail="trusted",
                remote_version=metadata.version,
                min_supported=metadata.min_supported,
                notes_url=metadata.notes_url,
            )
        return UpdateStatus(
            status="up_to_date",
            current_version=current_version,
            checked_at=checked_at,
            detail="trusted",
            remote_version=metadata.version,
            min_supported=metadata.min_supported,
            notes_url=metadata.notes_url,
        )
    except (ValueError, InvalidSignature):
        return UpdateStatus(
            status="invalid_signature",
            current_version=current_version,
            checked_at=checked_at,
            detail="rejected",
            warning="update metadata signature invalid",
        )


def fetch_update_metadata_bytes(
    url: str,
    *,
    timeout_seconds: float,
    transport: httpx.BaseTransport | None = None,
) -> bytes:
    with httpx.Client(timeout=timeout_seconds, transport=transport, follow_redirects=True) as client:
        response = client.get(url, headers={"Accept": "application/json"})
        response.raise_for_status()
        return response.content


def parse_update_metadata_document(document: bytes) -> tuple[UpdateMetadata, bytes]:
    payload = json.loads(document)
    if not isinstance(payload, dict):
        raise ValueError("update metadata must be a JSON object")
    expected_keys = {"version", "released", "sha256", "signature", "min_supported", "notes_url"}
    if set(payload) != expected_keys:
        raise ValueError("update metadata fields do not match the public spec")
    metadata = UpdateMetadata(
        version=_require_semver(payload, "version"),
        released=_require_timestamp(payload, "released"),
        sha256=_require_sha256(payload, "sha256"),
        signature=_require_base64url(payload, "signature"),
        min_supported=_require_semver(payload, "min_supported"),
        notes_url=_require_https_url(payload, "notes_url"),
    )
    unsigned_payload = {
        "min_supported": metadata.min_supported,
        "notes_url": metadata.notes_url,
        "released": metadata.released,
        "sha256": metadata.sha256,
        "version": metadata.version,
    }
    canonical = json.dumps(
        unsigned_payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return metadata, canonical


def verify_update_signature(
    metadata: UpdateMetadata,
    canonical_bytes: bytes,
    pubkeys: tuple[str, ...],
) -> None:
    signature = _decode_base64url(metadata.signature)
    for pubkey in pubkeys:
        try:
            key = Ed25519PublicKey.from_public_bytes(_decode_base64url(pubkey))
            key.verify(signature, canonical_bytes)
            return
        except (InvalidSignature, ValueError):
            continue
    raise InvalidSignature("no pinned update key verified the metadata")


def parse_semver(value: str) -> SemVer:
    match = _SEMVER_RE.fullmatch(value)
    if match is None:
        raise ValueError(f"invalid semver: {value}")
    prerelease = match.group(4)
    tokens: list[_PrereleaseToken] = []
    if prerelease:
        for identifier in prerelease.split("."):
            if identifier.isdigit():
                if identifier.startswith("0") and identifier != "0":
                    raise ValueError(f"invalid semver prerelease: {value}")
                tokens.append(_PrereleaseToken(numeric=True, value=int(identifier)))
            else:
                tokens.append(_PrereleaseToken(numeric=False, value=identifier))
    return SemVer(
        major=int(match.group(1)),
        minor=int(match.group(2)),
        patch=int(match.group(3)),
        prerelease=tuple(tokens),
    )


def _checked_at(now: datetime | None) -> str:
    instant = now or datetime.now(UTC)
    return instant.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _decode_base64url(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return urlsafe_b64decode(value + padding)


def _require_string(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{key} must be a non-empty string")
    return value


def _require_semver(payload: dict[str, Any], key: str) -> str:
    value = _require_string(payload, key)
    parse_semver(value)
    return value


def _require_timestamp(payload: dict[str, Any], key: str) -> str:
    value = _require_string(payload, key)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{key} must be a valid ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{key} must include a timezone")
    return parsed.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _require_sha256(payload: dict[str, Any], key: str) -> str:
    value = _require_string(payload, key)
    if _SHA256_RE.fullmatch(value) is None:
        raise ValueError(f"{key} must be a lowercase sha256 hex digest")
    return value


def _require_base64url(payload: dict[str, Any], key: str) -> str:
    value = _require_string(payload, key)
    if _BASE64URL_RE.fullmatch(value) is None or "=" in value:
        raise ValueError(f"{key} must be unpadded base64url")
    return value


def _require_https_url(payload: dict[str, Any], key: str) -> str:
    value = _require_string(payload, key)
    if not value.startswith("https://"):
        raise ValueError(f"{key} must be an https url")
    return value
