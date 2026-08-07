"""Shared safe outcome helpers for cloud connector boundaries."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


def provider_outcome(source_id: str, exc: BaseException, *, permission_hint: str) -> dict[str, Any]:
    """Return a classified outcome without copying exception data into it."""
    if _is_not_authorized(exc):
        return {
            "source_id": source_id,
            "status": "not_authorized",
            "error_code": "permission_denied",
            "error_detail": "provider authorization was rejected",
            "remediation_hint": permission_hint,
        }
    if isinstance(exc, (ImportError, ModuleNotFoundError)):
        return {
            "source_id": source_id,
            "status": "unavailable",
            "error_code": "sdk_unavailable",
            "error_detail": "the provider SDK is not installed",
            "remediation_hint": "Install the optional provider SDK and retry.",
        }
    return {
        "source_id": source_id,
        "status": "unavailable",
        "error_code": "collection_unavailable",
        "error_detail": "provider service was unavailable",
        "remediation_hint": "Verify provider connectivity and retry.",
    }


def truncation_outcome(source_id: str, *, limit: int) -> dict[str, Any]:
    return {
        "source_id": source_id,
        "status": "partial",
        "error_code": "truncated",
        "error_detail": f"collection was capped at {limit} assets; additional assets were not returned",
        "remediation_hint": "Increase the collection limit and retry for a complete inventory.",
    }


def result_status(record_count: int, outcomes: Sequence[Mapping[str, Any]]) -> str:
    failures = [outcome for outcome in outcomes if str(outcome.get("status")) not in {"success", "empty"}]
    if not failures:
        return "success" if record_count else "empty"
    if record_count:
        return "partial"
    statuses = {str(outcome.get("status")) for outcome in failures}
    if statuses == {"not_authorized"}:
        return "not_authorized"
    if statuses == {"unavailable"}:
        return "unavailable"
    return "partial"


def result_errors(outcomes: Sequence[Mapping[str, Any]]) -> list[str]:
    return [
        f"{outcome.get('error_code')}: {outcome.get('error_detail')}"
        for outcome in outcomes
        if outcome.get("error_code") and outcome.get("error_detail")
    ]


def _is_not_authorized(exc: BaseException) -> bool:
    if isinstance(exc, PermissionError):
        return True
    name = exc.__class__.__name__.lower()
    if any(token in name for token in ("auth", "credential", "permission", "accessdenied", "unauthorized")):
        return True
    status_code = getattr(exc, "status_code", None) or getattr(exc, "response_status_code", None)
    if status_code in {401, 403}:
        return True
    code = getattr(exc, "code", None)
    nested_error = getattr(exc, "error", None)
    if code is None and nested_error is not None:
        code = getattr(nested_error, "code", None)
    if str(code) in {"401", "403", "AccessDenied", "UnauthorizedOperation", "InvalidClientTokenId"}:
        return True
    response = getattr(exc, "response", None)
    if isinstance(response, Mapping):
        error = response.get("Error") or response.get("error")
        if isinstance(error, Mapping) and str(error.get("Code")) in {
            "401",
            "403",
            "AccessDenied",
            "UnauthorizedOperation",
            "InvalidClientTokenId",
        }:
            return True
    return False
