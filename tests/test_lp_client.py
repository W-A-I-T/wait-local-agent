from __future__ import annotations

import hashlib
import json

import httpx
import pytest

from wait_local_agent.lp_client import (
    LaunchPassportClient,
    LaunchPassportForbidden,
    LaunchPassportPayloadTooLarge,
    LaunchPassportUnauthorized,
)


def _client(handler):
    return LaunchPassportClient(
        "https://lp.test",
        lambda: "vault-token",
        transport=httpx.MockTransport(handler),
    )


@pytest.mark.parametrize(
    ("code", "error"),
    [
        (401, LaunchPassportUnauthorized),
        (403, LaunchPassportForbidden),
        (413, LaunchPassportPayloadTooLarge),
    ],
)
def test_upload_maps_auth_and_size_errors(code, error) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(code)

    with _client(handler) as client:
        with pytest.raises(error):
            client.upload_bundle("project-1", {"metadata": {"sourceCode": False}})


def test_launch_scan_turns_forbidden_into_capability_state() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403)

    with _client(handler) as client:
        assert client.launch_scan("project-1") == {
            "status": "not_authorized",
            "capability": "launch_scan",
        }


def test_get_retries_transient_failures_and_preserves_bearer_header(monkeypatch) -> None:
    attempts = 0
    headers: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        headers.append(request.headers.get("authorization"))
        if attempts < 3:
            return httpx.Response(503)
        return httpx.Response(200, json={"ok": True})

    monkeypatch.setattr("wait_local_agent.lp_client.time.sleep", lambda _seconds: None)
    with _client(handler) as client:
        assert client.list_scans("project-1") == {"ok": True}
    assert attempts == 3
    assert headers == ["Bearer vault-token"] * 3


def test_small_bundle_posts_json_to_collector_bundle_endpoint() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.host == "lp.test"
        assert request.url.path == "/api/projects/project-1/artifacts/collector-bundle"
        assert request.headers["authorization"] == "Bearer vault-token"
        assert request.headers["content-type"] == "application/json"
        return httpx.Response(201, json={"artifactId": "artifact-json", "status": "uploaded"})

    with _client(handler) as client:
        result = client.upload_bundle("project-1", {"metadata": {"sourceCode": False}})
    assert result.artifact_id == "artifact-json"
    assert result.status == "uploaded"


def test_large_bundle_uses_collector_zip_flow_with_signed_storage_upload(monkeypatch) -> None:
    calls: list[tuple[str, str, str | None]] = []
    signed_zip: bytes | None = None
    complete_body: dict[str, str] | None = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal complete_body, signed_zip
        calls.append((request.method, request.url.host, request.headers.get("authorization")))
        if request.url.host == "lp.test" and request.url.path.endswith("/zip/init"):
            assert request.headers["authorization"] == "Bearer vault-token"
            init_body = json.loads(request.content)
            assert init_body["fileName"] == "collector-bundle.zip"
            assert init_body["contentType"] == "application/zip"
            assert init_body["byteSize"] > 0
            return httpx.Response(
                201,
                json={
                    "artifactId": "artifact-1",
                    "bucket": "artifacts",
                    "path": "org/projects/project-1/artifacts/zip/artifact-1/collector-bundle.zip",
                    "upload": {"signedUrl": "https://storage.test/upload/artifact-1", "method": "PUT"},
                    "artifact": {"artifactId": "artifact-1", "status": "pending_upload"},
                },
            )
        if request.url.host == "storage.test":
            assert request.url.path == "/upload/artifact-1"
            assert request.headers.get("authorization") is None
            assert request.headers["content-type"] == "application/zip"
            signed_zip = request.content
            return httpx.Response(200)
        if request.url.host == "lp.test" and request.url.path.endswith("/zip/complete"):
            assert request.headers["authorization"] == "Bearer vault-token"
            complete_body = json.loads(request.content)
            return httpx.Response(201, json={"artifact": {"artifactId": "artifact-1", "status": "uploaded"}})
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    monkeypatch.setattr("wait_local_agent.lp_client.time.sleep", lambda _seconds: None)
    large_bundle = {"metadata": {"sourceCode": False}, "files": ["x" * LaunchPassportClient.JSON_LIMIT_BYTES]}
    with _client(handler) as client:
        result = client.upload_bundle("project-1", large_bundle)
    assert result.artifact_id == "artifact-1"
    assert result.status == "uploaded"
    assert signed_zip is not None
    assert complete_body == {
        "storageBucket": "artifacts",
        "storagePath": "org/projects/project-1/artifacts/zip/artifact-1/collector-bundle.zip",
        "sha256": hashlib.sha256(signed_zip).hexdigest(),
    }
    assert calls == [
        ("POST", "lp.test", "Bearer vault-token"),
        ("PUT", "storage.test", None),
        ("POST", "lp.test", "Bearer vault-token"),
    ]
