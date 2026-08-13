"""Tenant-scoped, evidence-bound environment discovery projections."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Literal

from wait_local_agent.models import ConnectorStatus

EnvironmentStatus = Literal[
    "configured",
    "detected",
    "reachable",
    "authenticated",
    "authorized",
    "permission-limited",
    "unavailable",
    "not_configured",
    "unknown",
]

MAX_ENVIRONMENT_SYSTEMS = 32
MAX_ENVIRONMENT_TEXT = 160
_SECRET_MARKERS = ("key=", "token=", "secret=", "password=", "credential=", "bearer=")

# Names are intentionally limited to the connector catalog already owned by
# WAIT. Matching a name never performs a provider call or invents support for a
# vendor that is not represented by a local connector boundary.
_ALIASES: dict[str, tuple[str, ...]] = {
    "halopsa": ("halo", "halopsa"),
    "hudu": ("hudu",),
    "itglue": ("it glue", "itglue"),
    "confluence": ("confluence",),
    "notion": ("notion",),
    "sharepoint": ("sharepoint",),
    "connectwise": ("connectwise", "connectwise psa"),
    "syncro": ("syncro",),
    "servicenow": ("servicenow", "service now"),
    "autotask": ("autotask",),
    "m365": ("m365", "microsoft 365", "microsoft 365 / entra", "entra", "microsoft entra"),
    "timezest": ("timezest",),
    "scalepad": ("scalepad",),
    "rmm": ("rmm", "ninjaone", "datto rmm", "n-able n-sight", "n-able n-central", "kaseya vsa x", "screenconnect"),
}


class EnvironmentDiscoveryError(ValueError):
    """Raised when environment evidence is malformed or unsafe."""


def discover_environment(
    *,
    client_id: str,
    requested_systems: Sequence[object],
    connector_statuses: Iterable[ConnectorStatus],
    configured_client_id: str | None = None,
    probe_results: Mapping[str, Mapping[str, object]] | None = None,
) -> dict[str, Any]:
    """Project connector configuration, declarations, and optional health evidence.

    A configured local credential is reported as ``configured`` only when it is
    bound to the requested tenant. It is promoted to ``authorized`` only when
    an explicitly supplied provider health result passed. A disabled HTTP probe
    is reported as ``permission-limited`` with the local policy limitation
    stated explicitly.
    """

    tenant = _text(client_id, "client_id", 128)
    requested = _text_list(requested_systems, "requested_systems")
    statuses = list(connector_statuses)
    normalized_probes = _normalize_probe_results(probe_results)
    by_alias: dict[str, ConnectorStatus] = {}
    for status in statuses:
        aliases = _ALIASES.get(status.id, (status.id, status.name))
        for alias in aliases:
            by_alias[_normalize(alias)] = status

    systems: list[dict[str, object]] = []
    seen: set[str] = set()
    for name in requested:
        key = _normalize(name)
        if key in seen:
            continue
        matched_status: ConnectorStatus | None = by_alias.get(key)
        if matched_status is not None and matched_status.id in seen:
            continue
        seen.add(key)
        if matched_status is not None:
            seen.add(matched_status.id)
        systems.append(
            _declared_system(
                name,
                matched_status,
                tenant,
                configured_client_id,
                normalized_probes.get(matched_status.id) if matched_status is not None else None,
            )
        )

    for connector_status in statuses:
        if connector_status.id in seen or connector_status.status == "not_configured":
            continue
        if connector_status.status in {"configured", "blocked", "ready"}:
            seen.add(connector_status.id)
            systems.append(
                _configured_system(
                    connector_status,
                    tenant,
                    configured_client_id,
                    normalized_probes.get(connector_status.id),
                )
            )

    unresolved = [
        {
            "system": item["name"],
            "reason": "no local connector boundary matched the customer declaration",
        }
        for item in systems
        if item["status"] == "detected"
    ]
    limitations = [
        {
            "system": item["name"],
            "reason": item["limitation"],
        }
        for item in systems
        if item.get("limitation")
    ]
    return {
        "format": "wait-local-agent.environment-discovery",
        "format_version": 1,
        "client_id": tenant,
        "source": (
            "customer_declarations_local_connector_configuration_and_provider_health"
            if normalized_probes
            else "customer_declarations_and_local_connector_configuration"
        ),
        "probe_requested": probe_results is not None,
        "probe_performed": bool(normalized_probes),
        "systems": systems,
        "unresolved": unresolved,
        "limitations": limitations,
        "readiness": "needs_environment_verification"
        if unresolved or limitations or any(item["status"] not in {"authorized"} for item in systems)
        else "ready_for_architecture",
        "inference_started": False,
        "execution_started": False,
        "deployment_started": False,
    }


def _declared_system(
    name: str,
    status: ConnectorStatus | None,
    client_id: str,
    configured_client_id: str | None,
    probe_result: Mapping[str, object] | None,
) -> dict[str, object]:
    if status is None:
        return {
            "id": _safe_id(name),
            "name": name,
            "kind": "unknown",
            "connector_id": None,
            "status": "detected",
            "evidence": ["customer_declared"],
            "limitation": "customer declaration is not provider verification",
            "tenant_scope": client_id,
        }
    return _status_view(
        status,
        name=name,
        client_id=client_id,
        configured_client_id=configured_client_id,
        probe_result=probe_result,
    )


def _configured_system(
    status: ConnectorStatus,
    client_id: str,
    configured_client_id: str | None,
    probe_result: Mapping[str, object] | None,
) -> dict[str, object]:
    return _status_view(
        status,
        name=status.name,
        client_id=client_id,
        configured_client_id=configured_client_id,
        probe_result=probe_result,
    )


def _status_view(
    status: ConnectorStatus,
    *,
    name: str,
    client_id: str,
    configured_client_id: str | None,
    probe_result: Mapping[str, object] | None,
) -> dict[str, object]:
    tenant_bound = bool(configured_client_id and configured_client_id.strip() == client_id)
    evidence = ["customer_declared", "local_connector_configuration"]
    limitation: str | None = None
    projected: EnvironmentStatus
    probe_view = _probe_view(probe_result)
    if status.status == "not_configured":
        projected = "not_configured"
        limitation = "no complete local connector configuration was found"
    elif not tenant_bound:
        projected = "permission-limited"
        limitation = "local connector configuration is not explicitly bound to the requested tenant"
    elif status.status == "blocked":
        projected = "permission-limited"
        limitation = "local policy prevents provider probing; provider authorization is unknown"
    elif status.status == "failed":
        projected = "unavailable"
        limitation = (
            "connector health reported a failure; provider availability is not being treated "
            "as an empty environment"
        )
    elif status.status in {"configured", "ready"} and probe_result is not None:
        passed = probe_result.get("passed") is True
        layer = probe_view["layer"]
        if passed:
            projected = "authorized"
            limitation = None
            evidence.append("provider_health_response")
        elif layer == "auth":
            projected = "permission-limited"
            limitation = "provider health check failed authorization; the environment is not treated as empty"
        elif layer == "connectivity":
            projected = "unavailable"
            limitation = "provider health check could not reach the configured service"
        elif layer == "safety":
            projected = "permission-limited"
            limitation = "local policy prevented provider health probing; authorization is unknown"
        elif layer == "config":
            projected = "not_configured"
            limitation = "provider health check reported incomplete connector configuration"
        else:
            projected = "unknown"
            limitation = "provider health check returned no usable authorization evidence"
    elif status.status in {"configured", "ready"}:
        projected = "configured"
        limitation = "provider reachability, authentication, and authorization have not been probed"
    else:
        projected = "unknown"
        limitation = f"connector returned unsupported local status '{status.status}'"
    return {
        "id": status.id,
        "name": name,
        "kind": status.kind,
        "connector_id": status.id,
        "status": projected,
        "evidence": evidence,
        "limitation": limitation,
        "tenant_scope": client_id,
        "provider_status": status.status,
        "http_probing_enabled": status.http_probing_enabled,
        "write_actions_enabled": status.write_actions_enabled,
        "probe": probe_view,
    }


def _normalize_probe_results(
    probe_results: Mapping[str, Mapping[str, object]] | None,
) -> dict[str, dict[str, object]]:
    if probe_results is None:
        return {}
    normalized: dict[str, dict[str, object]] = {}
    for connector_id, raw in probe_results.items():
        if not isinstance(connector_id, str) or not connector_id.strip() or not isinstance(raw, Mapping):
            continue
        layer = raw.get("layer")
        message = raw.get("message", "")
        normalized[connector_id.strip()] = {
            "passed": raw.get("passed") is True,
            "layer": layer.strip() if isinstance(layer, str) and layer.strip() else "unknown",
            "message": message.strip()[:240] if isinstance(message, str) else "",
        }
    return normalized


def _probe_view(probe_result: Mapping[str, object] | None) -> dict[str, object]:
    if probe_result is None:
        return {"status": "not_run", "layer": "not_run", "message": "provider health was not requested"}
    return {
        "status": "passed" if probe_result.get("passed") is True else "failed",
        "layer": probe_result.get("layer", "unknown"),
        "message": probe_result.get("message", ""),
    }


def _text_list(values: Sequence[object], field: str) -> list[str]:
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
        raise EnvironmentDiscoveryError(f"{field} must be an array")
    if len(values) > MAX_ENVIRONMENT_SYSTEMS:
        raise EnvironmentDiscoveryError(f"{field} may contain at most {MAX_ENVIRONMENT_SYSTEMS} items")
    return [_text(value, f"{field}[{index}]", MAX_ENVIRONMENT_TEXT) for index, value in enumerate(values)]


def _text(value: object, field: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        raise EnvironmentDiscoveryError(f"{field} must be non-empty text of at most {maximum} characters")
    normalized = value.strip()
    lowered = normalized.casefold()
    if any(marker in lowered for marker in _SECRET_MARKERS):
        raise EnvironmentDiscoveryError("environment evidence may not contain secret material")
    if any(ord(character) < 32 for character in normalized):
        raise EnvironmentDiscoveryError(f"{field} contains unsupported control characters")
    return normalized


def _normalize(value: str) -> str:
    return " ".join(value.casefold().replace("/", " ").split())


def _safe_id(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9-]+", "-", _normalize(value).replace(" ", "-")).strip("-")
    return normalized[:64] or "unknown-system"


__all__ = ["EnvironmentDiscoveryError", "EnvironmentStatus", "discover_environment"]
