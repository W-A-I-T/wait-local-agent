from __future__ import annotations

import hashlib
import io
import json
import time
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx

from wait_local_agent.founder_bundle import sanitize_bundle


class LaunchPassportError(RuntimeError):
    """Base error for Launch Passport requests."""


class LaunchPassportUnauthorized(LaunchPassportError):
    """The configured bearer token was rejected."""


class LaunchPassportForbidden(LaunchPassportError):
    """The token is valid but lacks the requested capability."""


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
        if not normalized.startswith(("http://", "https://")):
            raise ValueError("Launch Passport base URL must use http or https")
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

    def latest_report(self, project_id: str) -> dict[str, Any] | list[Any]:
        return self._get(f"/api/projects/{self._safe_project_id(project_id)}/reports/latest")

    def launch_scan(self, project_id: str) -> dict[str, Any]:
        path = f"/api/projects/{self._safe_project_id(project_id)}/scans"
        try:
            return self._post_json(path, "{}")
        except LaunchPassportForbidden:
            return {"status": "not_authorized", "capability": "launch_scan"}

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
        digest = hashlib.sha256(zipped).hexdigest()
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
        bucket = init.get("bucket")
        path = init.get("path")
        artifact_stub = init.get("artifact")
        if not isinstance(upload_url, str) or not upload_url:
            raise LaunchPassportRequestError("Launch Passport zip init did not return a signed upload URL")
        if not isinstance(bucket, str) or not bucket or not isinstance(path, str) or not path:
            raise LaunchPassportRequestError("Launch Passport zip init did not return storage details")
        if not isinstance(artifact_stub, dict):
            raise LaunchPassportRequestError("Launch Passport zip init did not return an artifact stub")

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
            json.dumps({"storageBucket": bucket, "storagePath": path, "sha256": digest}),
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
    def _zip_bytes(bundle_bytes: bytes) -> bytes:
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("collector-bundle.json", bundle_bytes)
        return output.getvalue()

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        if response.status_code in {401, 403, 413}:
            errors = {
                401: LaunchPassportUnauthorized,
                403: LaunchPassportForbidden,
                413: LaunchPassportPayloadTooLarge,
            }
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
