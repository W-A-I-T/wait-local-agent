from __future__ import annotations

import json

import httpx
import pytest

import wait_local_agent.lp_client as lp_client_module
from wait_local_agent.lp_client import (
    LaunchPassportClient,
    LaunchPassportForbidden,
    LaunchPassportPayloadTooLarge,
    LaunchPassportRequestError,
    LaunchPassportUnauthorized,
    validate_launch_passport_base_url,
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
        "artifactId": "artifact-1",
        "storageBucket": "artifacts",
        "storagePath": "org/projects/project-1/artifacts/zip/artifact-1/collector-bundle.zip",
        "fileName": "collector-bundle.zip",
        "contentType": "application/zip",
        "byteSize": len(signed_zip),
    }
    assert calls == [
        ("POST", "lp.test", "Bearer vault-token"),
        ("PUT", "storage.test", None),
        ("POST", "lp.test", "Bearer vault-token"),
    ]


def test_client_validates_timeout_project_id_and_base_url() -> None:
    with pytest.raises(ValueError, match="timeout"):
        LaunchPassportClient("https://lp.test", lambda: "token", timeout=0)
    with pytest.raises(ValueError, match="path segment"):
        LaunchPassportClient("https://lp.test", lambda: "token").list_scans("bad/id")
    with pytest.raises(ValueError, match="http or https"):
        validate_launch_passport_base_url("ftp://lp.test")
    with pytest.raises(ValueError, match="invalid"):
        validate_launch_passport_base_url("https://lp.test:bad")


def test_status_handles_unreachable_and_list_payloads(monkeypatch) -> None:
    monkeypatch.setattr("wait_local_agent.lp_client.time.sleep", lambda _seconds: None)

    def failing(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline")

    with _client(failing) as client:
        result = client.status()
    assert result["status"] == "unreachable"
    assert "GET request failed" in result["error"]

    with _client(lambda _request: httpx.Response(200, json=[{"id": "scan"}])) as client:
        assert client.status() == {"status": "connected", "capabilities": {}}


def test_get_and_post_map_request_and_payload_errors(monkeypatch) -> None:
    monkeypatch.setattr("wait_local_agent.lp_client.time.sleep", lambda _seconds: None)

    def failing(_request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow")

    with _client(failing) as client:
        with pytest.raises(LaunchPassportRequestError, match="GET request failed"):
            client.list_scans("project-1")

    with _client(lambda _request: httpx.Response(200, content=b"not-json")) as client:
        with pytest.raises(LaunchPassportRequestError, match="invalid JSON"):
            client.latest_report("project-1")

    with _client(lambda _request: httpx.Response(200, json=[])) as client:
        with pytest.raises(LaunchPassportRequestError, match="object payload"):
            client.upload_bundle("project-1", {"metadata": {"sourceCode": False}})


def test_zip_init_rejects_missing_details_and_upload_failures(monkeypatch) -> None:
    monkeypatch.setattr("wait_local_agent.lp_client.LaunchPassportClient.JSON_LIMIT_BYTES", 1)

    cases = [
        ({"upload": {"signedUrl": "https://storage.test/u"}}, "artifact stub"),
        ({"artifact": {}, "upload": {}}, "signed upload URL"),
        (
            {
                "artifact": {"artifactId": "a"},
                "upload": {"signedUrl": "https://storage.test/u", "method": "PATCH"},
                "bucket": "b",
                "path": "p",
            },
            "unsupported upload method",
        ),
    ]
    for init_payload, message in cases:
        def handler(request: httpx.Request, payload=init_payload) -> httpx.Response:
            return httpx.Response(201, json=payload)

        with _client(handler) as client:
            with pytest.raises(LaunchPassportRequestError, match=message):
                client.upload_bundle("project-1", {"files": ["x" * 20]})

    def upload_error(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/zip/init"):
            return httpx.Response(
                201,
                json={
                    "artifactId": "a",
                    "bucket": "b",
                    "path": "p",
                    "artifact": {"id": "a"},
                    "upload": {"signedUrl": "https://storage.test/u"},
                },
            )
        return httpx.Response(413)

    with _client(upload_error) as client:
        with pytest.raises(LaunchPassportPayloadTooLarge):
            client.upload_bundle("project-1", {"files": ["x" * 20]})


def test_upload_result_fallback_and_token_configuration() -> None:
    result = LaunchPassportClient._upload_result({}, fallback={"id": "fallback", "status": "pending"})
    assert result.as_dict() == {"artifact_id": "fallback", "status": "pending"}
    with LaunchPassportClient("https://lp.test", lambda: None) as client:
        assert client.status() == {"status": "unreachable", "error": "Launch Passport token is not configured"}


def test_lp_client_covers_status_error_and_invalid_payload_shapes(monkeypatch) -> None:
    with _client(lambda _request: httpx.Response(200, json={"status": "ok"})) as client:
        assert client.status() == {"status": "unknown", "capabilities": {}}

    with _client(lambda _request: httpx.Response(500)) as client:
        with pytest.raises(LaunchPassportRequestError, match="500"):
            client.latest_report("project-1")

    with _client(lambda _request: httpx.Response(200, json="scalar")) as client:
        with pytest.raises(LaunchPassportRequestError, match="invalid payload"):
            client.list_scans("project-1")

    with _client(lambda _request: (_ for _ in ()).throw(httpx.ConnectError("offline"))) as client:
        with pytest.raises(LaunchPassportRequestError, match="POST request failed"):
            client._post_json("/path", "{}")

    assert LaunchPassportClient._safe_project_id(" project-1 ") == "project-1"
    assert lp_client_module._string_payload_value({"artifactId": 4}, "artifactId") == ""


def test_get_has_defensive_fallback_when_retry_loop_is_empty(monkeypatch) -> None:
    monkeypatch.setattr(lp_client_module, "range", lambda _count: [], raising=False)
    with _client(lambda _request: httpx.Response(200, json={})) as client:
        with pytest.raises(LaunchPassportRequestError, match="GET request failed"):
            client._get("/path")


def test_upload_result_redacts_configured_token_and_secret_shaped_text() -> None:
    token = "launch-passport-token"

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            201,
            json={
                "artifactId": "artifact-1",
                "status": token,
                "message": f"echo={token} sk_live_EXPOSED_VALUE",
            },
        )

    with LaunchPassportClient(
        "https://lp.test", lambda: token, transport=httpx.MockTransport(handler)
    ) as client:
        result = client.upload_bundle("project-1", {"metadata": {"sourceCode": False}})

    assert result.status == "unknown"
    assert token not in json.dumps(result.payload)
    assert "sk_live_EXPOSED_VALUE" not in json.dumps(result.payload)
    assert token not in json.dumps(result.as_dict())


def test_upstream_projection_scrubs_nested_sensitive_values_and_collections() -> None:
    with _client(lambda _request: httpx.Response(200, json={"status": "completed"})) as client:
        projected = client.sanitize_upstream(
            {
                "api_key": "hidden",
                "items": [{"message": "safe"}],
                "details": ("safe", {"password": "hidden"}),
            }
        )

    assert projected == {
        "api_key": "[redacted]",
        "items": [{"message": "safe"}],
        "details": ["safe", {"password": "[redacted]"}],
    }


def test_client_maps_only_known_upstream_statuses() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/scans"):
            return httpx.Response(200, json={"status": "completed"})
        if request.url.path.endswith("/health"):
            return httpx.Response(200, json={"status": "not-a-state", "capabilities": {"launch_scan": True}})
        raise AssertionError(f"unexpected request: {request.url}")

    with _client(handler) as client:
        assert client.launch_scan("project-1")["status"] == "completed"
        assert client.status() == {
            "status": "unknown",
            "capabilities": {"launch_scan": True},
        }


def test_lp_client_zip_flow_rejects_missing_storage_and_upload_request_errors(monkeypatch) -> None:
    monkeypatch.setattr("wait_local_agent.lp_client.LaunchPassportClient.JSON_LIMIT_BYTES", 1)

    def missing_storage(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            201,
            json={"artifact": {"id": "a"}, "upload": {"signedUrl": "https://storage.test/u"}},
        )

    with _client(missing_storage) as client:
        with pytest.raises(LaunchPassportRequestError, match="storage details"):
            client.upload_bundle("project-1", {"files": ["x" * 20]})

    def failing_upload(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/zip/init"):
            return httpx.Response(
                201,
                json={
                    "artifactId": "a",
                    "bucket": "b",
                    "path": "p",
                    "artifact": {"id": "a"},
                    "upload": {"signedUrl": "https://storage.test/u"},
                },
            )
        raise httpx.ConnectError("storage unavailable", request=request)

    with _client(failing_upload) as client:
        with pytest.raises(LaunchPassportRequestError, match="zip upload"):
            client.upload_bundle("project-1", {"files": ["x" * 20]})
