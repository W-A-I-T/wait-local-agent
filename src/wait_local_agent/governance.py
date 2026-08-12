"""Deterministic governance and DLP review for consultant artifacts."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import cast

MAX_GOVERNANCE_INPUT_BYTES = 100_000
MAX_GOVERNANCE_CONNECTORS = 16


class GovernanceValidationError(ValueError):
    """Raised when a governance review input is malformed or unbounded."""


def evaluate_solution_governance(
    architecture: Mapping[str, object],
    connector_artifacts: Sequence[Mapping[str, object]] | None = None,
) -> dict[str, object]:
    """Return a review-only governance report for generated consultant artifacts."""

    if _json_size(architecture) + _json_size(connector_artifacts or []) > MAX_GOVERNANCE_INPUT_BYTES:
        raise GovernanceValidationError("governance input exceeds 100000 bytes")
    client_id = architecture.get("client_id")
    if not isinstance(client_id, str) or not client_id.strip():
        raise GovernanceValidationError("architecture.client_id is required")
    components = _mapping_list(architecture.get("components", []), "architecture.components")
    open_items = _mapping_list(architecture.get("open_items", []), "architecture.open_items")
    connectors = connector_artifacts or []
    if len(connectors) > MAX_GOVERNANCE_CONNECTORS:
        raise GovernanceValidationError(f"connector_artifacts may contain at most {MAX_GOVERNANCE_CONNECTORS} items")

    findings: list[dict[str, object]] = []
    if architecture.get("readiness") != "ready":
        findings.append(
            _finding(
                "medium",
                "architecture_review_required",
                "The architecture contains unresolved design or binding items.",
            )
        )
    if open_items:
        findings.append(
            _finding(
                "medium",
                "open_items_present",
                f"{len(open_items)} architecture review item(s) remain open.",
            )
        )
    for component in components:
        if component.get("kind") == "system_connector":
            findings.append(
                _finding(
                    "medium",
                    "external_boundary_review",
                    "External system access requires an explicit connector, tenant, and permission review.",
                    component.get("id"),
                )
            )

    connector_summary: list[dict[str, object]] = []
    for artifact in connectors:
        connector_summary.append(_review_connector(artifact, findings))

    high_count = sum(finding["severity"] == "high" for finding in findings)
    medium_count = sum(finding["severity"] == "medium" for finding in findings)
    return {
        "client_id": client_id,
        "status": "needs_review" if findings else "pass",
        "finding_counts": {"high": high_count, "medium": medium_count, "info": 0},
        "findings": findings,
        "connectors": connector_summary,
        "authorization_changed": False,
        "execution_started": False,
        "deployment_started": False,
    }


def _review_connector(
    artifact: Mapping[str, object],
    findings: list[dict[str, object]],
) -> dict[str, object]:
    connector_id = artifact.get("connector_id")
    if not isinstance(connector_id, str) or not connector_id.strip():
        raise GovernanceValidationError("connector artifact connector_id is required")
    actions = _mapping_list(artifact.get("actions", []), f"connector.{connector_id}.actions")
    authentication = _mapping_list(
        artifact.get("authentication", []), f"connector.{connector_id}.authentication"
    )
    if artifact.get("credentials_included") is True:
        findings.append(
            _finding(
                "high",
                "credential_material_present",
                "Connector artifacts must not contain credentials.",
                connector_id,
            )
        )
    if authentication:
        findings.append(
            _finding(
                "medium",
                "authentication_review_required",
                "Authentication scheme and tenant consent require operator review.",
                connector_id,
            )
        )
    write_actions = [
        str(action.get("id"))
        for action in actions
        if str(action.get("method", "")).upper() not in {"GET", "HEAD"}
    ]
    if write_actions:
        findings.append(
            _finding(
                "high",
                "write_approval_boundary_required",
                "Non-read connector actions require an explicit approval boundary before use.",
                connector_id,
            )
        )
    return {
        "connector_id": connector_id,
        "host": _safe_host(artifact.get("host")),
        "action_count": len(actions),
        "write_action_ids": write_actions,
        "authentication_types": [auth.get("type") for auth in authentication],
        "review_status": "needs_review" if authentication or write_actions else "reviewed_read_only",
    }


def _finding(
    severity: str,
    code: str,
    message: str,
    component_id: object | None = None,
) -> dict[str, object]:
    result: dict[str, object] = {"severity": severity, "code": code, "message": message}
    if isinstance(component_id, str) and component_id:
        result["component_id"] = component_id
    return result


def _mapping_list(value: object, field: str) -> list[Mapping[str, object]]:
    if not isinstance(value, list):
        raise GovernanceValidationError(f"{field} must be an array")
    if any(not isinstance(item, Mapping) for item in value):
        raise GovernanceValidationError(f"{field} must contain objects")
    return [cast(Mapping[str, object], item) for item in value]


def _safe_host(value: object) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    return value[:253] if "\n" not in value and "\r" not in value else None


def _json_size(value: object) -> int:
    try:
        return len(json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    except (TypeError, ValueError) as exc:
        raise GovernanceValidationError("governance input must be JSON serializable") from exc
