"""Fixed runbook definitions and canonical approval plans."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import cast

from wait_local_agent.models import ApprovalRequest
from wait_local_agent.store import Store

from .runbook_scripts import (
    ENDPOINT_HEALTH_SCRIPT,
    ENDPOINT_HEALTH_SHA256,
    SERVICE_RESTART_SCRIPT,
    SERVICE_RESTART_SHA256,
)
from .runbook_types import (
    MAX_CLIENT_ID_LENGTH,
    MAX_PARAMETER_COUNT,
    MAX_STRING_PARAMETER_LENGTH,
    RUNBOOK_ACTION_TYPE,
    RUNBOOK_PLAN_FORMAT,
    RunbookDefinition,
    RunbookError,
    RunbookParameter,
)


def _definitions() -> dict[str, RunbookDefinition]:
    definitions = (
        RunbookDefinition(
            runbook_id="windows.endpoint_health",
            version="1.0.0",
            title="Windows endpoint health",
            description=(
                "Collect bounded Windows, service, BitLocker, TPM, reboot, and "
                "critical-event evidence without changing the endpoint."
            ),
            effect="read",
            risk_level=1,
            timeout_seconds=60,
            script=ENDPOINT_HEALTH_SCRIPT,
            script_sha256=ENDPOINT_HEALTH_SHA256,
            parameters=(
                RunbookParameter(
                    name="include_event_logs",
                    kind="boolean",
                    description="Include a bounded System/Application critical-event summary.",
                    default=True,
                ),
                RunbookParameter(
                    name="event_hours",
                    kind="integer",
                    description="Lookback interval for critical events.",
                    default=24,
                    minimum=1,
                    maximum=72,
                ),
                RunbookParameter(
                    name="max_events",
                    kind="integer",
                    description="Maximum number of event records returned.",
                    default=25,
                    minimum=1,
                    maximum=100,
                ),
            ),
        ),
        RunbookDefinition(
            runbook_id="windows.service_restart",
            version="1.0.0",
            title="Restart an allowlisted Windows service",
            description=(
                "Restart one explicitly allowlisted endpoint-management service and "
                "verify that it returns to Running."
            ),
            effect="write",
            risk_level=3,
            timeout_seconds=45,
            script=SERVICE_RESTART_SCRIPT,
            script_sha256=SERVICE_RESTART_SHA256,
            parameters=(
                RunbookParameter(
                    name="service_name",
                    kind="choice",
                    description="The fixed Windows service to restart.",
                    default="IntuneManagementExtension",
                    choices=("IntuneManagementExtension", "wuauserv", "BITS"),
                ),
                RunbookParameter(
                    name="wait_seconds",
                    kind="integer",
                    description="Maximum wait for the service to reach Running.",
                    default=15,
                    minimum=1,
                    maximum=30,
                ),
            ),
        ),
    )
    catalog: dict[str, RunbookDefinition] = {}
    for definition in definitions:
        actual_digest = hashlib.sha256(definition.script.encode("utf-8")).hexdigest()
        if actual_digest != definition.script_sha256:
            raise RunbookError(f"Embedded script digest mismatch for {definition.runbook_id}.")
        if definition.runbook_id in catalog:
            raise RunbookError(f"Duplicate runbook definition: {definition.runbook_id}.")
        catalog[definition.runbook_id] = definition
    return catalog


def runbook_catalog() -> list[dict[str, object]]:
    """Return reviewable metadata without exposing caller-controlled execution."""

    return [
        definition.catalog_view()
        for definition in sorted(_definitions().values(), key=lambda item: item.runbook_id)
    ]


def build_runbook_plan(
    runbook_id: str,
    parameters: Mapping[str, object] | None,
    *,
    client_id: str,
) -> dict[str, object]:
    """Build a canonical, digest-bound approval payload."""

    definition = _definition(runbook_id)
    normalized_client_id = _bounded_client_id(client_id)
    normalized_parameters = _normalize_parameters(definition, parameters or {})
    plan: dict[str, object] = {
        "format": RUNBOOK_PLAN_FORMAT,
        "runbook_id": definition.runbook_id,
        "runbook_version": definition.version,
        "title": definition.title,
        "client_id": normalized_client_id,
        "effect": definition.effect,
        "risk_level": definition.risk_level,
        "approval_required": True,
        "parameters": normalized_parameters,
        "script_sha256": f"sha256:{definition.script_sha256}",
        "timeout_seconds": definition.timeout_seconds,
        "credentials_included": False,
    }
    plan["plan_digest"] = f"sha256:{_sha256_json(plan)}"
    return plan


def validate_runbook_plan(
    payload: Mapping[str, object],
    *,
    expected_client_id: str | None = None,
) -> dict[str, object]:
    """Rebuild and exactly compare a stored approval payload before execution."""

    required_keys = {
        "format",
        "runbook_id",
        "runbook_version",
        "title",
        "client_id",
        "effect",
        "risk_level",
        "approval_required",
        "parameters",
        "script_sha256",
        "timeout_seconds",
        "credentials_included",
        "plan_digest",
    }
    if set(payload) != required_keys:
        raise RunbookError("Stored runbook plan has an unsupported schema.")
    if payload.get("format") != RUNBOOK_PLAN_FORMAT:
        raise RunbookError("Stored runbook plan format is unsupported.")
    runbook_id = payload.get("runbook_id")
    client_id = payload.get("client_id")
    parameters = payload.get("parameters")
    if not isinstance(runbook_id, str):
        raise RunbookError("Stored runbook ID is invalid.")
    if not isinstance(client_id, str):
        raise RunbookError("Stored runbook client ID is invalid.")
    if not isinstance(parameters, Mapping):
        raise RunbookError("Stored runbook parameters are invalid.")
    rebuilt = build_runbook_plan(runbook_id, cast(Mapping[str, object], parameters), client_id=client_id)
    if _canonical_json(dict(payload)) != _canonical_json(rebuilt):
        raise RunbookError("Stored runbook plan no longer matches the reviewed definition.")
    if expected_client_id is not None and rebuilt["client_id"] != _bounded_client_id(expected_client_id):
        raise RunbookError("Stored runbook plan belongs to a different tenant.")
    return rebuilt


def create_runbook_approval(
    store: Store,
    *,
    client_id: str,
    runbook_id: str,
    parameters: Mapping[str, object] | None,
) -> tuple[ApprovalRequest, dict[str, object]]:
    """Persist a pending approval for a canonical runbook plan."""

    plan = build_runbook_plan(runbook_id, parameters, client_id=client_id)
    digest = cast(str, plan["plan_digest"]).removeprefix("sha256:")[:16]
    approval = store.create_approval_request(
        subject_id=f"powershell-runbook:{digest}",
        action_type=RUNBOOK_ACTION_TYPE,
        payload=plan,
        client_id=client_id,
    )
    return approval, plan


def _definition(runbook_id: str) -> RunbookDefinition:
    candidate = runbook_id.strip()
    definition = _definitions().get(candidate)
    if definition is None:
        raise RunbookError("Unknown Microsoft administrator PowerShell runbook.")
    return definition


def _normalize_parameters(
    definition: RunbookDefinition,
    parameters: Mapping[str, object],
) -> dict[str, object]:
    if len(parameters) > MAX_PARAMETER_COUNT:
        raise RunbookError("Too many PowerShell runbook parameters were supplied.")
    if any(not isinstance(name, str) for name in parameters):
        raise RunbookError("PowerShell runbook parameter names must be strings.")
    descriptors = {parameter.name: parameter for parameter in definition.parameters}
    unknown = sorted(set(parameters) - set(descriptors))
    if unknown:
        raise RunbookError(f"Unsupported PowerShell runbook parameters: {', '.join(unknown)}.")
    normalized: dict[str, object] = {}
    for name, descriptor in descriptors.items():
        value = parameters.get(name, descriptor.default)
        if descriptor.kind == "boolean":
            if not isinstance(value, bool):
                raise RunbookError(f"PowerShell runbook parameter {name} must be boolean.")
            normalized[name] = value
        elif descriptor.kind == "integer":
            if not isinstance(value, int) or isinstance(value, bool):
                raise RunbookError(f"PowerShell runbook parameter {name} must be an integer.")
            if descriptor.minimum is not None and value < descriptor.minimum:
                raise RunbookError(f"PowerShell runbook parameter {name} is below its minimum.")
            if descriptor.maximum is not None and value > descriptor.maximum:
                raise RunbookError(f"PowerShell runbook parameter {name} exceeds its maximum.")
            normalized[name] = value
        elif descriptor.kind == "choice":
            if not isinstance(value, str) or not value or len(value) > MAX_STRING_PARAMETER_LENGTH:
                raise RunbookError(f"PowerShell runbook parameter {name} must be a bounded string.")
            if value not in descriptor.choices:
                raise RunbookError(f"PowerShell runbook parameter {name} is not allowlisted.")
            normalized[name] = value
        else:  # pragma: no cover - definitions are static and checked in.
            raise RunbookError(f"PowerShell runbook parameter {name} has an unsupported type.")
    return normalized


def _bounded_client_id(value: str) -> str:
    candidate = value.strip()
    if not candidate or len(candidate) > MAX_CLIENT_ID_LENGTH:
        raise RunbookError("PowerShell runbook client ID is invalid.")
    if any(ord(character) < 32 for character in candidate):
        raise RunbookError("PowerShell runbook client ID is invalid.")
    return candidate


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _sha256_json(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()
