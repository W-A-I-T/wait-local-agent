"""Compose consultant artifacts into a review-only delivery handoff."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

from wait_local_agent.power_platform_package import (
    PowerPlatformPackageError,
    validate_power_platform_package,
)
from wait_local_agent.reports.renderers import redact_value

MAX_DELIVERY_TARGETS = 8
MAX_DELIVERY_CONNECTORS = 16
MAX_DELIVERY_REVIEW_ARTIFACTS = 16
MAX_DELIVERY_REVIEW_PACKAGE_BYTES = 256_000
MAX_DELIVERY_BUNDLE_FILES = 32


class DeliveryPlanError(ValueError):
    """Raised when a consultant delivery handoff is incomplete or unscoped."""


def build_consultant_delivery_plan(
    *,
    client_id: str,
    architecture: Mapping[str, object],
    evaluation: Mapping[str, object],
    governance: Mapping[str, object],
    deployment_targets: Sequence[str],
    connector_artifacts: Sequence[Mapping[str, object]] = (),
    review_artifacts: Sequence[Mapping[str, object]] = (),
    deployable_package: Mapping[str, object] | None = None,
) -> dict[str, Any]:
    tenant = _text(client_id, "client_id", 128)
    if architecture.get("client_id") != tenant:
        raise DeliveryPlanError("architecture is outside the requested tenant")
    if governance.get("client_id") not in {None, tenant}:
        raise DeliveryPlanError("governance is outside the requested tenant")
    targets = _text_list(deployment_targets, "deployment_targets", MAX_DELIVERY_TARGETS)
    connectors = list(connector_artifacts)
    if len(connectors) > MAX_DELIVERY_CONNECTORS:
        raise DeliveryPlanError(f"connector_artifacts may contain at most {MAX_DELIVERY_CONNECTORS} items")
    if any(not isinstance(item, Mapping) for item in connectors):
        raise DeliveryPlanError("connector_artifacts must contain objects")
    review_items = list(review_artifacts)
    if len(review_items) > MAX_DELIVERY_REVIEW_ARTIFACTS:
        raise DeliveryPlanError(f"review_artifacts may contain at most {MAX_DELIVERY_REVIEW_ARTIFACTS} items")
    if any(not isinstance(item, Mapping) for item in review_items):
        raise DeliveryPlanError("review_artifacts must contain objects")
    checks = {
        "architecture": architecture.get("readiness") == "ready",
        "evaluation": evaluation.get("production_readiness") == "pass",
        "governance": governance.get("status") == "pass",
        "credentials": all(
            item.get("credentials_included") is not True for item in [*connectors, *review_items]
        ),
    }
    components = architecture.get("components", [])
    if not isinstance(components, list):
        raise DeliveryPlanError("architecture.components must be an array")
    approval_policy = architecture.get("approval_policy", {})
    if not isinstance(approval_policy, Mapping):
        raise DeliveryPlanError("architecture.approval_policy must be an object")
    case_count = evaluation.get("case_count", 0)
    if isinstance(case_count, bool) or not isinstance(case_count, int) or case_count < 0:
        raise DeliveryPlanError("evaluation.case_count must be a non-negative integer")
    review_package, review_package_digest = build_consultant_artifact_review_package(
        client_id=tenant,
        artifacts=[*connectors, *review_items],
    )
    delivery_bundle, delivery_bundle_digest = build_consultant_delivery_bundle(
        client_id=tenant,
        architecture=architecture,
        evaluation=evaluation,
        governance=governance,
        deployment_targets=targets,
        review_package=review_package,
    )
    deployable_digest: str | None = None
    if deployable_package is not None:
        try:
            deployable_digest = validate_power_platform_package(deployable_package, client_id=tenant)
        except PowerPlatformPackageError as exc:
            raise DeliveryPlanError(str(exc)) from exc
    return {
        "format": "wait-local-agent.consultant-delivery-plan",
        "format_version": 1,
        "client_id": tenant,
        "summary": {
            "requirements_analyzed": True,
            "agents_designed": sum(item.get("kind") == "agent" for item in components if isinstance(item, Mapping)),
            "workflows_generated": sum(
                item.get("kind") == "workflow" for item in components if isinstance(item, Mapping)
            ),
            "approval_boundaries_configured": len(approval_policy),
            "knowledge_sources_configured": sum(
                item.get("kind") == "knowledge_source" for item in components if isinstance(item, Mapping)
            ),
            "connectors_prepared": len(connectors),
            "review_artifacts_prepared": len(review_items),
            "test_scenarios": case_count,
            "security_evaluation": governance.get("status", "needs_review"),
        },
        "checks": checks,
        "production_readiness": "pass" if all(checks.values()) else "needs_review",
        "deployment_targets": targets,
        "review_package": review_package,
        "review_package_generated": review_package is not None,
        "review_package_digest": review_package_digest,
        "delivery_bundle": delivery_bundle,
        "delivery_bundle_generated": delivery_bundle is not None,
        "delivery_bundle_digest": delivery_bundle_digest,
        "delivery_bundle_status": "review_only" if delivery_bundle is not None else "not_generated",
        "deployable_source_package": dict(deployable_package) if deployable_package is not None else None,
        "deployable_source_package_generated": deployable_package is not None,
        "deployable_source_package_digest": deployable_digest,
        "deployment_package_generated": False,
        "deployment_package_status": "not_generated",
        "production_deployment_requires_approval": True,
        "execution_started": False,
        "deployment_started": False,
        "authorization_changed": False,
    }


def _text_list(value: Sequence[str], field: str, maximum: int) -> list[str]:
    if not isinstance(value, (list, tuple)) or not value or len(value) > maximum:
        raise DeliveryPlanError(f"{field} must contain 1-{maximum} items")
    result = [_text(item, f"{field} item", 120) for item in value]
    if len(set(result)) != len(result):
        raise DeliveryPlanError(f"{field} must not contain duplicates")
    return result


def _text(value: object, field: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        raise DeliveryPlanError(f"{field} must be non-empty text of at most {maximum} characters")
    normalized = value.strip()
    if any(ord(character) < 32 for character in normalized):
        raise DeliveryPlanError(f"{field} contains unsupported control characters")
    return normalized


def build_consultant_artifact_review_package(
    *,
    client_id: str,
    artifacts: Sequence[Mapping[str, object]],
) -> tuple[dict[str, Any] | None, str | None]:
    """Build a bounded deterministic review manifest, never a deployable package."""

    tenant = _text(client_id, "client_id", 128)
    if not artifacts:
        return None, None
    if len(artifacts) > MAX_DELIVERY_CONNECTORS + MAX_DELIVERY_REVIEW_ARTIFACTS:
        raise DeliveryPlanError(
            f"review package may contain at most "
            f"{MAX_DELIVERY_CONNECTORS + MAX_DELIVERY_REVIEW_ARTIFACTS} artifacts"
        )

    safe_artifacts: list[dict[str, Any]] = []
    for artifact in artifacts:
        if not isinstance(artifact, Mapping):
            raise DeliveryPlanError("review_artifacts must contain objects")
        if artifact.get("client_id") not in {None, tenant}:
            raise DeliveryPlanError("review artifact is outside the requested tenant")
        if artifact.get("execution_started") is True or artifact.get("deployment_started") is True:
            raise DeliveryPlanError("review artifacts must not report execution or deployment started")
        redacted = redact_value(dict(artifact))
        if not isinstance(redacted, dict):
            raise DeliveryPlanError("review_artifacts must contain JSON objects")
        # ``redact_value`` treats credential-related keys as sensitive. Preserve
        # this required safety assertion when it is explicitly supplied as false.
        if artifact.get("credentials_included") is False:
            redacted["credentials_included"] = False
        safe_artifacts.append(redacted)

    package: dict[str, Any] = {
        "format": "wait-local-agent.consultant-review-package",
        "format_version": 1,
        "client_id": tenant,
        "artifact_count": len(safe_artifacts),
        "artifacts": safe_artifacts,
        "package_status": "review_only",
        "credentials_included": False,
        "deployment_started": False,
    }
    try:
        serialized = json.dumps(
            package,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise DeliveryPlanError("review_artifacts must contain JSON-compatible values") from exc
    if len(serialized) > MAX_DELIVERY_REVIEW_PACKAGE_BYTES:
        raise DeliveryPlanError(
            f"review_artifacts review package may be at most {MAX_DELIVERY_REVIEW_PACKAGE_BYTES} bytes"
        )
    return package, f"sha256:{hashlib.sha256(serialized).hexdigest()}"


def build_consultant_delivery_bundle(
    *,
    client_id: str,
    architecture: Mapping[str, object],
    evaluation: Mapping[str, object],
    governance: Mapping[str, object],
    deployment_targets: Sequence[str],
    review_package: Mapping[str, object] | None,
) -> tuple[dict[str, Any] | None, str | None]:
    """Assemble a bounded handoff bundle without claiming deployability.

    This is the deterministic handoff between consultant planning and a
    provider-specific packager. It contains redacted JSON files and their
    digests for operator review. It is not a Power Platform solution ZIP, does
    not invoke PAC, and cannot prove provider deployment.
    """

    tenant = _text(client_id, "client_id", 128)
    targets = _text_list(deployment_targets, "deployment_targets", MAX_DELIVERY_TARGETS)
    if architecture.get("client_id") != tenant:
        raise DeliveryPlanError("architecture is outside the requested tenant")
    if evaluation.get("client_id") not in {None, tenant}:
        raise DeliveryPlanError("evaluation is outside the requested tenant")
    if governance.get("client_id") not in {None, tenant}:
        raise DeliveryPlanError("governance is outside the requested tenant")
    if review_package is None:
        return None, None
    if review_package.get("client_id") != tenant:
        raise DeliveryPlanError("review package is outside the requested tenant")
    if review_package.get("package_status") != "review_only":
        raise DeliveryPlanError("review package must remain review_only")
    if review_package.get("credentials_included") is True:
        raise DeliveryPlanError("review package must not contain credentials")
    if review_package.get("deployment_started") is True:
        raise DeliveryPlanError("review package must not report deployment started")
    raw_artifacts = review_package.get("artifacts")
    if not isinstance(raw_artifacts, list):
        raise DeliveryPlanError("review package artifacts must be an array")
    if len(raw_artifacts) + 3 > MAX_DELIVERY_BUNDLE_FILES:
        raise DeliveryPlanError(f"delivery bundle may contain at most {MAX_DELIVERY_BUNDLE_FILES} files")

    source_files: list[tuple[str, object]] = [
        ("architecture.json", architecture),
        ("evaluation.json", evaluation),
        ("governance.json", governance),
    ]
    source_files.extend(
        (f"artifacts/artifact-{index + 1:02d}.json", artifact)
        for index, artifact in enumerate(raw_artifacts)
    )
    files: list[dict[str, object]] = []
    for path, value in source_files:
        redacted = redact_value(value)
        try:
            serialized = json.dumps(
                redacted,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
                allow_nan=False,
            ).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise DeliveryPlanError("delivery bundle sources must contain JSON-compatible values") from exc
        files.append(
            {
                "path": path,
                "media_type": "application/json",
                "digest": f"sha256:{hashlib.sha256(serialized).hexdigest()}",
                "content": redacted,
            }
        )

    manifest: dict[str, object] = {
        "format": "wait-local-agent.consultant-delivery-bundle",
        "format_version": 1,
        "client_id": tenant,
        "bundle_status": "review_only",
        "deployable": False,
        "credentials_included": False,
        "execution_started": False,
        "deployment_started": False,
        "deployment_targets": targets,
        "source_review_package_digest": _review_package_digest(review_package),
        "files": [
            {key: value for key, value in file.items() if key != "content"}
            for file in files
        ],
        "open_items": [
            "A provider-specific packager must produce and validate the official Power Platform solution format.",
            "Environment, credentials, licensing, permissions, and tenant authorization require operator evidence.",
            "PAC execution and deployment remain separate approval-gated operations.",
        ],
    }
    bundle: dict[str, Any] = {"manifest": manifest, "files": files}
    try:
        serialized_bundle = json.dumps(
            bundle,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise DeliveryPlanError("delivery bundle must contain JSON-compatible values") from exc
    if len(serialized_bundle) > MAX_DELIVERY_REVIEW_PACKAGE_BYTES:
        raise DeliveryPlanError(f"delivery bundle may be at most {MAX_DELIVERY_REVIEW_PACKAGE_BYTES} bytes")
    return bundle, f"sha256:{hashlib.sha256(serialized_bundle).hexdigest()}"


def _review_package_digest(review_package: Mapping[str, object]) -> str:
    try:
        serialized = json.dumps(
            review_package,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise DeliveryPlanError("review package must contain JSON-compatible values") from exc
    if len(serialized) > MAX_DELIVERY_REVIEW_PACKAGE_BYTES:
        raise DeliveryPlanError("review package exceeds the bounded size limit")
    return f"sha256:{hashlib.sha256(serialized).hexdigest()}"
