from __future__ import annotations

import json
import re
from base64 import urlsafe_b64decode, urlsafe_b64encode
from pathlib import Path

import httpx
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient
from typer.testing import CliRunner

import wait_local_agent.api.app as api_app_module
import wait_local_agent.update_channel as update_channel_module
from wait_local_agent.cli import app as cli_app
from wait_local_agent.update_channel import (
    UpdateStatus,
    UpdateStatusCache,
    check_for_updates,
    fetch_update_metadata_bytes,
    parse_semver,
    parse_update_metadata_document,
)

PRIMARY_PRIVATE_KEY = "_HgEKFU9nf0pCJrITm1-D4L-Bd3BH1iD2FuCUmqDo3s"
PRIMARY_PUBLIC_KEY = "RxufBDDrBAMp3Xd3G1Yi8nyecpWJk0crThuiY9OYr1k"
SECONDARY_PRIVATE_KEY = "nRDbuCJEDmk9CuESLLvnHDdUfbvivETTLBygQPNUnys"
SECONDARY_PUBLIC_KEY = "os6ChGW5TXE830cQ41hr_IuLVRwJc4UfVvNFCYbtsbE"
DOC_PUBLIC_KEY = "rXDiKqNRWypA4fPkhLUzlTc7xIwzlgGuGdy8f8JAt4I"


def test_check_for_updates_reports_available_for_trusted_newer_release(settings) -> None:
    document = _signed_document(
        version="0.1.1",
        private_key=PRIMARY_PRIVATE_KEY,
        notes_url="https://updates.wait.example.test/releases/0.1.1",
        pretty=True,
    )
    active_settings = settings.__class__(
        **{
            **settings.__dict__,
            "update_channel_url": "https://updates.wait.example.test/channel.json",
            "update_pubkeys": (PRIMARY_PUBLIC_KEY,),
        }
    )

    status = check_for_updates(
        active_settings,
        transport=httpx.MockTransport(lambda request: httpx.Response(200, content=document)),
    )

    assert status.status == "update_available"
    assert status.remote_version == "0.1.1"
    assert status.notes_url == "https://updates.wait.example.test/releases/0.1.1"


def test_update_check_cli_invalid_signature_exits_zero_and_redacts_metadata(monkeypatch, tmp_path) -> None:
    base = json.loads(_signed_document(version="0.9.9", private_key=PRIMARY_PRIVATE_KEY).decode("utf-8"))
    base["notes_url"] = "https://updates.wait.example.test/releases/0.9.9-tampered"
    tampered = json.dumps(base, indent=2).encode("utf-8")
    monkeypatch.setenv("WAIT_DATA_PATH", str(tmp_path / "state.db"))
    monkeypatch.setenv("WAIT_UPDATE_CHANNEL_URL", "https://updates.wait.example.test/channel.json")
    monkeypatch.setenv("WAIT_UPDATE_PUBKEYS", PRIMARY_PUBLIC_KEY)
    monkeypatch.setattr(update_channel_module, "fetch_update_metadata_bytes", lambda *args, **kwargs: tampered)
    runner = CliRunner()

    result = runner.invoke(cli_app, ["update", "check"])

    assert result.exit_code == 0
    assert "status=invalid_signature" in result.output
    assert "0.9.9" not in result.output
    assert "notes_url" not in result.output


def test_update_check_cli_reports_unknown_for_disabled_and_unreachable(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("WAIT_DATA_PATH", str(tmp_path / "state.db"))
    runner = CliRunner()

    disabled = runner.invoke(cli_app, ["update", "check"])

    monkeypatch.setenv("WAIT_UPDATE_CHANNEL_URL", "https://updates.wait.example.test/channel.json")
    monkeypatch.setenv("WAIT_UPDATE_PUBKEYS", PRIMARY_PUBLIC_KEY)

    def unreachable(*args, **kwargs):
        request = httpx.Request("GET", "https://updates.wait.example.test/channel.json")
        raise httpx.ConnectError("boom", request=request)

    monkeypatch.setattr(update_channel_module, "fetch_update_metadata_bytes", unreachable)
    unreachable_result = runner.invoke(cli_app, ["update", "check"])

    assert disabled.exit_code == 0
    assert "status=unknown detail=disabled" in disabled.output
    assert unreachable_result.exit_code == 0
    assert "status=unknown detail=unreachable" in unreachable_result.output


def test_second_pinned_key_verifies_rotation(settings) -> None:
    document = _signed_document(version="0.1.2", private_key=SECONDARY_PRIVATE_KEY)
    active_settings = settings.__class__(
        **{
            **settings.__dict__,
            "update_channel_url": "https://updates.wait.example.test/channel.json",
            "update_pubkeys": (PRIMARY_PUBLIC_KEY, SECONDARY_PUBLIC_KEY),
        }
    )

    status = check_for_updates(
        active_settings,
        transport=httpx.MockTransport(lambda request: httpx.Response(200, content=document)),
    )

    assert status.status == "update_available"
    assert status.remote_version == "0.1.2"


def test_remote_equal_version_is_up_to_date(settings) -> None:
    document = _signed_document(version="0.1.0", private_key=PRIMARY_PRIVATE_KEY)
    active_settings = settings.__class__(
        **{
            **settings.__dict__,
            "update_channel_url": "https://updates.wait.example.test/channel.json",
            "update_pubkeys": (PRIMARY_PUBLIC_KEY,),
        }
    )

    status = check_for_updates(
        active_settings,
        transport=httpx.MockTransport(lambda request: httpx.Response(200, content=document)),
    )

    assert status.status == "up_to_date"
    assert status.remote_version == "0.1.0"


def test_update_status_route_requires_admin_and_caches_results(settings, monkeypatch) -> None:
    secure_settings = settings.__class__(
        **{
            **settings.__dict__,
            "demo_mode": False,
            "admin_token": "admin-token",
            "tech_token": "tech-token",
            "viewer_token": "viewer-token",
        }
    )
    calls = {"count": 0}

    def fake_check(_settings) -> UpdateStatus:
        calls["count"] += 1
        return UpdateStatus(
            status="up_to_date",
            current_version="0.1.0",
            checked_at="2026-07-08T12:00:00Z",
            detail="trusted",
            remote_version="0.1.0",
            min_supported="0.1.0",
            notes_url="https://updates.wait.example.test/releases/0.1.0",
        )

    monkeypatch.setattr(api_app_module, "check_for_updates", fake_check)
    client = TestClient(api_app_module.create_app(secure_settings))

    viewer = client.get("/update-status", headers=_auth("viewer-token"))
    technician = client.get("/update-status", headers=_auth("tech-token"))
    first = client.get("/update-status", headers=_auth("admin-token"))
    second = client.get("/update-status", headers=_auth("admin-token"))

    assert viewer.status_code == 403
    assert technician.status_code == 403
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["status"] == "up_to_date"
    assert second.json() == first.json()
    assert calls["count"] == 1


def test_doc_example_matches_implementation(settings) -> None:
    doc = Path("docs/update-channel.md").read_text(encoding="utf-8")
    match = re.search(r"```json\n(\{.*?\})\n```", doc, re.DOTALL)
    assert match is not None
    document = match.group(1).encode("utf-8")
    active_settings = settings.__class__(
        **{
            **settings.__dict__,
            "update_channel_url": "https://updates.wait.example.test/channel.json",
            "update_pubkeys": (DOC_PUBLIC_KEY,),
        }
    )

    status = check_for_updates(
        active_settings,
        transport=httpx.MockTransport(lambda request: httpx.Response(200, content=document)),
    )

    assert status.status == "update_available"
    assert status.remote_version == "0.1.1"
    assert status.notes_url == "https://updates.wait.example.test/releases/0.1.1"


def test_check_for_updates_reports_unknown_when_pinned_keys_missing(settings) -> None:
    active_settings = settings.__class__(
        **{
            **settings.__dict__,
            "update_channel_url": "https://updates.wait.example.test/channel.json",
            "update_pubkeys": (),
        }
    )

    status = check_for_updates(active_settings)

    assert status.status == "unknown"
    assert status.detail == "misconfigured"
    assert status.warning == "update checks require at least one pinned public key"


def test_update_status_cache_reuses_cached_value_until_ttl_expires() -> None:
    cache = UpdateStatusCache(ttl_seconds=10.0)
    calls = {"count": 0}

    def loader() -> UpdateStatus:
        calls["count"] += 1
        return UpdateStatus(
            status="up_to_date",
            current_version="0.1.0",
            checked_at=f"2026-07-08T12:00:0{calls['count']}Z",
            detail="trusted",
        )

    first = cache.get_status(loader, now=100.0)
    second = cache.get_status(loader, now=105.0)
    third = cache.get_status(loader, now=111.0)

    assert first == second
    assert third != first
    assert calls["count"] == 2


def test_parse_semver_handles_prerelease_precedence_and_rejects_bad_values() -> None:
    assert parse_semver("1.0.0-alpha.1") < parse_semver("1.0.0-alpha.beta")
    assert parse_semver("1.0.0-alpha.beta") < parse_semver("1.0.0-beta")
    assert parse_semver("1.0.0-beta") < parse_semver("1.0.0")

    for invalid in ("1.0", "1.0.0-01", "01.0.0"):
        try:
            parse_semver(invalid)
        except ValueError:
            continue
        raise AssertionError(f"{invalid} should be rejected")


def test_fetch_and_parse_helpers_enforce_public_spec() -> None:
    fetched = fetch_update_metadata_bytes(
        "https://updates.wait.example.test/channel.json",
        timeout_seconds=20.0,
        transport=httpx.MockTransport(lambda request: httpx.Response(200, content=b'{"ok":true}')),
    )

    assert fetched == b'{"ok":true}'

    invalid_documents = [
        b"[]",
        json.dumps({"version": "0.1.1"}).encode("utf-8"),
        json.dumps(
            {
                "version": "",
                "released": "2026-07-08T12:00:00Z",
                "sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
                "signature": "sig",
                "min_supported": "0.1.0",
                "notes_url": "https://updates.wait.example.test/releases/0.1.1",
            }
        ).encode("utf-8"),
        json.dumps(
            {
                "version": "0.1.1",
                "released": "2026-07-08 12:00:00",
                "sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
                "signature": "sig",
                "min_supported": "0.1.0",
                "notes_url": "https://updates.wait.example.test/releases/0.1.1",
            }
        ).encode("utf-8"),
        json.dumps(
            {
                "version": "0.1.1",
                "released": "2026-07-08T12:00:00Z",
                "sha256": "not-hex",
                "signature": "sig",
                "min_supported": "0.1.0",
                "notes_url": "https://updates.wait.example.test/releases/0.1.1",
            }
        ).encode("utf-8"),
        json.dumps(
            {
                "version": "0.1.1",
                "released": "2026-07-08T12:00:00Z",
                "sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
                "signature": "bad=",
                "min_supported": "0.1.0",
                "notes_url": "https://updates.wait.example.test/releases/0.1.1",
            }
        ).encode("utf-8"),
        json.dumps(
            {
                "version": "0.1.1",
                "released": "2026-07-08T12:00:00Z",
                "sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
                "signature": "sig",
                "min_supported": "0.1.0",
                "notes_url": "http://updates.wait.example.test/releases/0.1.1",
            }
        ).encode("utf-8"),
    ]

    for document in invalid_documents:
        try:
            parse_update_metadata_document(document)
        except ValueError:
            continue
        raise AssertionError(f"{document!r} should be rejected")


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _signed_document(
    *,
    version: str,
    private_key: str,
    notes_url: str | None = None,
    min_supported: str = "0.1.0",
    pretty: bool = False,
) -> bytes:
    unsigned = {
        "version": version,
        "released": "2026-07-08T12:00:00Z",
        "sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        "min_supported": min_supported,
        "notes_url": notes_url or f"https://updates.wait.example.test/releases/{version}",
    }
    canonical = json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode("utf-8")
    signer = Ed25519PrivateKey.from_private_bytes(_decode(private_key))
    signature = _encode(signer.sign(canonical))
    payload = {
        "signature": signature,
        "notes_url": unsigned["notes_url"],
        "min_supported": unsigned["min_supported"],
        "version": unsigned["version"],
        "released": unsigned["released"],
        "sha256": unsigned["sha256"],
    }
    if pretty:
        return json.dumps(payload, indent=2).encode("utf-8")
    return json.dumps(payload, separators=(",", ":")).encode("utf-8")


def _decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return urlsafe_b64decode(value + padding)


def _encode(value: bytes) -> str:
    return urlsafe_b64encode(value).decode("utf-8").rstrip("=")
