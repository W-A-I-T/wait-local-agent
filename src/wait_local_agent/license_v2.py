from __future__ import annotations

import base64
import binascii
import json
import re
from collections.abc import Iterable
from datetime import date
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

_BASE64URL_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_LICENSE_KEYS = {
    "v",
    "customer_id",
    "expires",
    "packs",
    "max_managed_clients",
    "edition",
}


def verify_license_v2(
    payload_b64: str,
    sig_b64: str,
    pubkeys: Iterable[str],
    *,
    today: date | None = None,
) -> dict[str, Any]:
    """Verify and return a strict, offline Ed25519 license-v2 payload."""

    payload = _decode_json(payload_b64, "payload")
    if set(payload) != _LICENSE_KEYS:
        raise ValueError("license payload fields do not match the public spec")
    if payload["v"] != 2 or isinstance(payload["v"], bool):
        raise ValueError("license payload version must be 2")

    customer_id = _non_empty_string(payload, "customer_id")
    expires = _non_empty_string(payload, "expires")
    if _DATE_RE.fullmatch(expires) is None:
        raise ValueError("expires must be a YYYY-MM-DD date")
    try:
        expires_date = date.fromisoformat(expires)
    except ValueError as exc:
        raise ValueError("expires must be a valid YYYY-MM-DD date") from exc
    if expires_date < (today or date.today()):
        raise ValueError("license has expired")

    packs = payload["packs"]
    if not isinstance(packs, list) or any(
        not isinstance(pack, str) or not pack.strip() for pack in packs
    ):
        raise ValueError("packs must be a list of non-empty strings")
    max_managed_clients = payload["max_managed_clients"]
    if max_managed_clients is not None and (
        not isinstance(max_managed_clients, int)
        or isinstance(max_managed_clients, bool)
        or max_managed_clients < 0
    ):
        raise ValueError("max_managed_clients must be a non-negative integer or null")
    edition = _non_empty_string(payload, "edition")

    canonical_payload = {
        "customer_id": customer_id,
        "edition": edition,
        "expires": expires,
        "max_managed_clients": max_managed_clients,
        "packs": packs,
        "v": 2,
    }
    canonical_bytes = json.dumps(
        canonical_payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    signature = _decode_base64url(sig_b64, "signature")
    for pubkey in pubkeys:
        try:
            key = Ed25519PublicKey.from_public_bytes(_decode_base64url(pubkey, "public key"))
            key.verify(signature, canonical_bytes)
            return canonical_payload
        except (InvalidSignature, ValueError):
            continue
    raise InvalidSignature("no pinned license key verified the payload")


def _decode_json(value: str, label: str) -> dict[str, Any]:
    raw = _decode_base64url(value, label)
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} must contain a JSON object") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must contain a JSON object")
    return payload


def _decode_base64url(value: str, label: str) -> bytes:
    if not isinstance(value, str) or not value or "=" in value or _BASE64URL_RE.fullmatch(value) is None:
        raise ValueError(f"{label} must be unpadded base64url")
    try:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except (ValueError, binascii.Error) as exc:
        raise ValueError(f"{label} must be valid base64url") from exc


def _non_empty_string(payload: dict[str, Any], key: str) -> str:
    value = payload[key]
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string")
    return value
