from __future__ import annotations

import io
import json
import time
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urlsplit

import httpx

from wait_local_agent.founder_bundle import sanitize_bundle


class LaunchPassportError(RuntimeError):
    """Base error for Launch Passport requests."""


class LaunchPassportUnauthorized(LaunchPassportError):
    """The configured bearer token was rejected."""


class LaunchPassportForbidden(LaunchPassportError):
    """The token is valid but lacks the requested capability."""


class LaunchPassportInsufficientCredits(LaunchPassportError):
    """The remote project has insufficient credits for the requested operation."""


class LaunchPassportRateLimited(LaunchPassportError):
    """The remote endpoint asked the caller to retry later."""

    def __init__(self, message: str, *, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class LaunchPassportPayloadTooLarge(LaunchPassportError):
    """The remote endpoint rejected an artifact because it is too large."""


class LaunchPassportRequestError(LaunchPassportError):
    """A request failed without exposing remote response content."""


@dataclass(frozen=True)
class UploadResult:
    artifact_id: str
    status: str
    payload: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {"artifact_id": self.artifact_id, "status": self.status, **self.payload}


class LaunchPassportClient:
    """Small synchronous client for the Launch Passport collector API."""

    JSON_LIMIT_BYTES = int(9.5 * 1024 * 1024)

    def __init__(
        self,
        base_url: str,
        token_provider: Callable[[], str | None],
        timeout: float = 30.0,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        normalized = base_url.strip().rstrip("/")
        validate_launch_passport_base_url(normalized)
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        self.base_url = normalized
        self.token_provider = token_provider
        self.timeout = timeout
        self._client = httpx.Client(timeout=timeout, transport=transport)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> LaunchPassportClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def upload_bundle(self, project_id: str, bundle: dict[str, Any]) -> UploadResult:
        self._validate_project_id(project_id)
        bundle = sanitize_bundle(bundle)
        serialized = json.dumps(bundle, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        if len(serialized.encode("utf-8")) <= self.JSON_LIMIT_BYTES:
            payload = self._post_json(
                f"/api/projects/{project_id}/artifacts/collector-bundle",
                serialized,
            )
            return self._upload_result(payload)
        return self._upload_zip(project_id, serialized.encode("utf-8"))

    def list_scans(self, project_id: str) -> dict[str, Any] | list[Any]:
        return self._get(f"/api/projects/{self._safe_project_id(project_id)}/scans")

    def get_scan(self, scan_id: str) -> dict[str, Any]:
        return self._get_object(f"/api/scans/{self._safe_scan_id(scan_id)}")

    def latest_report(self, project_id: str) -> dict[str, Any] | list[Any]:
        return self._get(f"/api/projects/{self._safe_project_id(project_id)}/reports/latest")

    def launch_scan(self, project_id: str) -> dict[str, Any]:
        path = f"/api/projects/{self._safe_project_id(project_id)}/scans"
        try:
            return self._post_json(path, "{}")
        except LaunchPassportForbidden:
            return {"status": "not_authorized", "capability": "launch_scan"}
        except LaunchPassportInsufficientCredits:
            return {"status": "insufficient_credits", "capability": "launch_scan"}
        except LaunchPassportRateLimited as exc:
            return {
                "status": "rate_limited",
                "capability": "launch_scan",
                "retry_after": exc.retry_after,
            }

    def status(self) -> dict[str, Any]:
        try:
            response = self._get("/api/health")
        except LaunchPassportError as exc:
            return {"status": "unreachable", "error": str(exc)}
        if isinstance(response, dict):
            return {"status": "connected", **response}
        return {"status": "connected", "response": response}

    def _upload_zip(self, project_id: str, bundle_bytes: bytes) -> UploadResult:
        zipped = self._zip_bytes(bundle_bytes)
        init = self._post_json(
            f"/api/collector/projects/{project_id}/artifacts/zip/init",
            json.dumps(
                {
                    "fileName": "collector-bundle.zip",
                    "contentType": "application/zip",
                    "byteSize": len(zipped),
                }
            ),
        )
        upload = init.get("upload")
        upload_url = upload.get("signedUrl") if isinstance(upload, dict) else None
        artifact_stub = init.get("artifact")
        if not isinstance(upload_url, str) or not upload_url:
            raise LaunchPassportRequestError("Launch Passport zip init did not return a signed upload URL")
        if not isinstance(artifact_stub, dict):
            raise LaunchPassportRequestError("Launch Passport zip init did not return an artifact stub")
        artifact_id = _artifact_id_from_payload(artifact_stub) or _string_payload_value(init, "artifactId")
        bucket = init.get("storageBucket") or init.get("bucket") or artifact_stub.get("storageBucket")
        path = init.get("storagePath") or init.get("path") or artifact_stub.get("storagePath")
        if not artifact_id or not isinstance(bucket, str) or not bucket or not isinstance(path, str) or not path:
            raise LaunchPassportRequestError("Launch Passport zip init did not return artifact and storage details")

        method = upload.get("method", "PUT") if isinstance(upload, dict) else "PUT"
        if not isinstance(method, str) or method.upper() not in {"PUT", "POST"}:
            raise LaunchPassportRequestError("Launch Passport zip init returned an unsupported upload method")
        try:
            response = self._client.request(
                method.upper(),
                upload_url,
                content=zipped,
                headers={"Content-Type": "application/zip"},
            )
        except httpx.RequestError as exc:
            raise LaunchPassportRequestError("Launch Passport zip upload request failed") from exc
        self._raise_for_status(response)

        complete = self._post_json(
            f"/api/collector/projects/{project_id}/artifacts/zip/complete",
            json.dumps(
                {
                    "artifactId": artifact_id,
                    "storageBucket": bucket,
                    "storagePath": path,
                    "fileName": "collector-bundle.zip",
                    "contentType": "application/zip",
                    "byteSize": len(zipped),
                }
            ),
        )
        return self._upload_result(complete, fallback=artifact_stub)

    def _get(self, path: str) -> dict[str, Any] | list[Any]:
        last_error: LaunchPassportRequestError | None = None
        for attempt in range(3):
            try:
                response = self._client.get(self._url(path), headers=self._headers())
            except httpx.RequestError as exc:
                last_error = LaunchPassportRequestError("Launch Passport GET request failed")
                if attempt < 2:
                    time.sleep(0.1 * (2**attempt))
                    continue
                raise last_error from exc
            if response.status_code >= 500 and attempt < 2:
                time.sleep(0.1 * (2**attempt))
                continue
            self._raise_for_status(response)
            return self._json_payload(response)
        raise last_error or LaunchPassportRequestError("Launch Passport GET request failed")

    def _get_object(self, path: str) -> dict[str, Any]:
        response = self._get(path)
        if not isinstance(response, dict):
            raise LaunchPassportRequestError("Launch Passport returned an object payload")
        return response

    def _post_json(self, path: str, serialized: str) -> dict[str, Any]:
        try:
            response = self._client.post(
                self._url(path),
                content=serialized,
                headers={**self._headers(), "Content-Type": "application/json"},
            )
        except httpx.RequestError as exc:
            raise LaunchPassportRequestError("Launch Passport POST request failed") from exc
        self._raise_for_status(response)
        return self._json_object(response)

    def _headers(self) -> dict[str, str]:
        token = self.token_provider()
        if not token:
            raise LaunchPassportUnauthorized("Launch Passport token is not configured")
        return {"Authorization": f"Bearer {token}"}

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    @staticmethod
    def _safe_project_id(project_id: str) -> str:
        LaunchPassportClient._validate_project_id(project_id)
        return project_id.strip()

    @staticmethod
    def _validate_project_id(project_id: str) -> None:
        if not project_id.strip() or "/" in project_id or "\\" in project_id:
            raise ValueError("project id must be a non-empty path segment")

    @staticmethod
    def _safe_scan_id(scan_id: str) -> str:
        if not scan_id.strip() or "/" in scan_id or "\\" in scan_id:
            raise ValueError("scan id must be a non-empty path segment")
        return scan_id.strip()

    @staticmethod
    def _zip_bytes(bundle_bytes: bytes) -> bytes:
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("collector-bundle.json", bundle_bytes)
        return output.getvalue()

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        if response.status_code in {401, 402, 403, 413, 429}:
            errors = {
                401: LaunchPassportUnauthorized,
                402: LaunchPassportInsufficientCredits,
                403: LaunchPassportForbidden,
                413: LaunchPassportPayloadTooLarge,
            }
            if response.status_code == 429:
                raise LaunchPassportRateLimited(
                    "Launch Passport request was rate limited",
                    retry_after=_retry_after_seconds(response.headers.get("Retry-After")),
                )
            raise errors[response.status_code](f"Launch Passport request returned {response.status_code}")
        if response.is_error:
            raise LaunchPassportRequestError(f"Launch Passport request returned {response.status_code}")

    @staticmethod
    def _json_payload(response: httpx.Response) -> dict[str, Any] | list[Any]:
        try:
            payload = response.json()
        except (ValueError, json.JSONDecodeError) as exc:
            raise LaunchPassportRequestError("Launch Passport returned invalid JSON") from exc
        if not isinstance(payload, (dict, list)):
            raise LaunchPassportRequestError("Launch Passport returned an invalid payload")
        return payload

    @classmethod
    def _json_object(cls, response: httpx.Response) -> dict[str, Any]:
        payload = cls._json_payload(response)
        if not isinstance(payload, dict):
            raise LaunchPassportRequestError("Launch Passport returned an object payload")
        return payload

    @staticmethod
    def _upload_result(payload: dict[str, Any], *, fallback: dict[str, Any] | None = None) -> UploadResult:
        artifact = payload.get("artifact")
        artifact_payload = artifact if isinstance(artifact, dict) else {}
        fallback_payload = fallback if isinstance(fallback, dict) else {}
        artifact_id = (
            payload.get("artifact_id")
            or payload.get("artifactId")
            or payload.get("id")
            or artifact_payload.get("artifact_id")
            or artifact_payload.get("artifactId")
            or artifact_payload.get("id")
            or fallback_payload.get("artifact_id")
            or fallback_payload.get("artifactId")
            or fallback_payload.get("id")
            or ""
        )
        status = payload.get("status") or artifact_payload.get("status") or fallback_payload.get("status") or "uploaded"
        return UploadResult(str(artifact_id), str(status), payload)


def validate_launch_passport_base_url(base_url: str) -> None:
    """Reject malformed or credential-bearing Launch Passport endpoints."""
    try:
        parsed = urlsplit(base_url)
        _ = parsed.port
    except ValueError as exc:
        raise ValueError("Launch Passport base URL is invalid") from exc
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError("Launch Passport base URL must use http or https without embedded credentials")


def _artifact_id_from_payload(payload: dict[str, Any]) -> str:
    value = payload.get("artifactId") or payload.get("artifact_id") or payload.get("id")
    return value.strip() if isinstance(value, str) else ""


def _string_payload_value(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    return value.strip() if isinstance(value, str) else ""


def _retry_after_seconds(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        retry_at = parsedate_to_datetime(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if retry_at.tzinfo is None:
        retry_at = retry_at.replace(tzinfo=UTC)
    return max(0.0, (retry_at - datetime.now(UTC)).total_seconds())
