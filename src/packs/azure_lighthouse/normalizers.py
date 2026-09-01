"""Azure Lighthouse provider payload normalization."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from .models import (
    AzureLighthouseProviderError,
    AzureLighthouseValidationError,
    LighthouseResource,
    SourceStatus,
)
from .validation import normalize_resource_group, normalize_uuid


def validate_definition_id(value: str) -> str:
    parsed = value.strip()
    if not parsed.startswith("/subscriptions/") or "?" in parsed or "#" in parsed or "\\" in parsed:
        raise AzureLighthouseProviderError(
            "Azure Lighthouse registration definition identifier is invalid."
        )
    lowered = parsed.casefold()
    marker = "/providers/microsoft.managedservices/registrationdefinitions/"
    if marker not in lowered:
        raise AzureLighthouseProviderError(
            "Azure Lighthouse registration definition identifier is invalid."
        )
    prefix, definition_name = parsed.rsplit("/", 1)
    try:
        normalize_uuid(definition_name, "registration definition ID")
        scope = prefix[: lowered.index(marker)]
        segments = [segment for segment in scope.split("/") if segment]
        if len(segments) not in {2, 4} or segments[0].casefold() != "subscriptions":
            raise AzureLighthouseProviderError(
                "Azure Lighthouse registration definition scope is invalid."
            )
        normalize_uuid(segments[1], "subscription ID")
        if len(segments) == 4:
            if segments[2].casefold() != "resourcegroups":
                raise AzureLighthouseProviderError(
                    "Azure Lighthouse registration definition scope is invalid."
                )
            normalize_resource_group(segments[3])
    except AzureLighthouseValidationError as exc:
        raise AzureLighthouseProviderError(
            "Azure Lighthouse registration definition identifier is invalid."
        ) from exc
    return parsed


def definition_scope(value: str) -> str:
    parsed = validate_definition_id(value)
    marker = "/providers/Microsoft.ManagedServices/registrationDefinitions/"
    index = parsed.casefold().find(marker.casefold())
    return parsed[:index] if index >= 0 else ""


def resource_from_payload(raw: Mapping[str, object]) -> LighthouseResource | None:
    resource_id = string(raw.get("id"))
    resource_type = string(raw.get("type"))
    name = string(raw.get("name"))
    if not resource_id or not resource_type or not name:
        return None
    sku = mapping(raw.get("sku"))
    tags = {
        str(key)[:128]: str(value)[:256]
        for key, value in mapping(raw.get("tags")).items()
        if isinstance(key, str) and isinstance(value, (str, int, float, bool))
    }
    return LighthouseResource(
        resource_id=resource_id,
        name=name,
        resource_type=resource_type,
        location=string(raw.get("location")),
        resource_group=resource_group_from_id(resource_id),
        kind=string(raw.get("kind")),
        sku_name=string(sku.get("name")),
        tags=tags,
    )


def resource_group_from_id(resource_id: str) -> str:
    segments = [segment for segment in resource_id.split("/") if segment]
    for index, segment in enumerate(segments[:-1]):
        if segment.casefold() == "resourcegroups":
            return segments[index + 1]
    return ""


def scope_from_assignment_id(assignment_id: str) -> str:
    marker = "/providers/Microsoft.ManagedServices/registrationAssignments/"
    index = assignment_id.casefold().find(marker.casefold())
    return assignment_id[:index] if index >= 0 else ""


def mapping(value: object) -> Mapping[str, object]:
    return cast(Mapping[str, object], value) if isinstance(value, Mapping) else {}


def list_of_mappings(value: object) -> list[Mapping[str, object]]:
    if not isinstance(value, list):
        return []
    return [cast(Mapping[str, object], item) for item in value if isinstance(item, Mapping)]


def string(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def normalized_optional_uuid(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        return ""
    try:
        return normalize_uuid(value, "identifier")
    except AzureLighthouseValidationError:
        return ""


def aggregate_status(has_records: bool, errors: list[dict[str, str]]) -> SourceStatus:
    if has_records and errors:
        return "partial"
    if has_records:
        return "ready"
    if errors:
        return "failed"
    return "ready"
