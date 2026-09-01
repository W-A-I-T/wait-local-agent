from __future__ import annotations

import base64
import json
from datetime import date, timedelta

import pytest
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from wait_local_agent.license_v2 import verify_license_v2


def _encoded(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _signed_license(private_key: Ed25519PrivateKey, payload: dict[str, object]) -> tuple[str, str]:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return _encoded(canonical), _encoded(private_key.sign(canonical))


def _payload(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "v": 2,
        "customer_id": "customer-example",
        "expires": (date.today() + timedelta(days=30)).isoformat(),
        "packs": ["msp-control"],
        "max_managed_clients": 4,
        "edition": "commercial",
    }
    value.update(overrides)
    return value


def test_verify_license_v2_accepts_rotation_and_returns_canonical_payload() -> None:
    first = Ed25519PrivateKey.generate()
    second = Ed25519PrivateKey.generate()
    payload_b64, signature_b64 = _signed_license(second, _payload())

    assert verify_license_v2(
        payload_b64,
        signature_b64,
        (_encoded(first.public_key().public_bytes_raw()), _encoded(second.public_key().public_bytes_raw())),
    ) == _payload()


@pytest.mark.parametrize(
    "payload_overrides",
    [
        {"v": 3},
        {"unexpected": True},
        {"expires": "2020-02-30"},
        {"packs": [" "]},
        {"max_managed_clients": True},
    ],
)
def test_verify_license_v2_rejects_malformed_payloads(payload_overrides: dict[str, object]) -> None:
    private_key = Ed25519PrivateKey.generate()
    payload_b64, signature_b64 = _signed_license(private_key, _payload(**payload_overrides))

    with pytest.raises(ValueError):
        verify_license_v2(payload_b64, signature_b64, (_encoded(private_key.public_key().public_bytes_raw()),))


def test_verify_license_v2_rejects_bad_signature_tampering_expiry_and_missing_key() -> None:
    private_key = Ed25519PrivateKey.generate()
    payload_b64, signature_b64 = _signed_license(private_key, _payload())

    with pytest.raises((ValueError, InvalidSignature)):
        verify_license_v2(payload_b64, _encoded(b"bad"), (_encoded(private_key.public_key().public_bytes_raw()),))
    tampered_payload, _ = _signed_license(private_key, _payload(customer_id="tampered"))
    with pytest.raises((ValueError, InvalidSignature)):
        verify_license_v2(tampered_payload, signature_b64, (_encoded(private_key.public_key().public_bytes_raw()),))
    expired_payload, expired_signature = _signed_license(private_key, _payload(expires="2020-01-01"))
    with pytest.raises(ValueError, match="expired"):
        verify_license_v2(expired_payload, expired_signature, (_encoded(private_key.public_key().public_bytes_raw()),))
    with pytest.raises(InvalidSignature):
        verify_license_v2(payload_b64, signature_b64, ())
