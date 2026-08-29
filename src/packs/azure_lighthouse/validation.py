"""Identifier and scope validation for Azure Lighthouse."""

from __future__ import annotations

import re
from uuid import UUID

from .models import (
    MAX_DESCRIPTION_LENGTH,
    MAX_NAME_LENGTH,
    MAX_RESOURCE_GROUP_LENGTH,
    AzureLighthouseValidationError,
)

_RESOURCE_GROUP_PATTERN = re.compile(r"^[\w.()\- ]{1,90}$", re.UNICODE)


def normalize_uuid(value: str, label: str) -> str:
    candidate = value.strip()
    try:
        return str(UUID(candidate))
    except (ValueError, AttributeError) as exc:
        raise AzureLighthouseValidationError(f"Azure Lighthouse {label} is invalid.") from exc


def normalize_resource_group(value: str | None) -> str:
    candidate = (value or "").strip()
    if not candidate:
        return ""
    if len(candidate) > MAX_RESOURCE_GROUP_LENGTH or not _RESOURCE_GROUP_PATTERN.fullmatch(candidate):
        raise AzureLighthouseValidationError("Azure Lighthouse resource group name is invalid.")
    if candidate.endswith("."):
        raise AzureLighthouseValidationError("Azure Lighthouse resource group name cannot end with a period.")
    return candidate


def normalize_name(value: str, label: str, *, maximum: int = MAX_NAME_LENGTH) -> str:
    candidate = value.strip()
    if not candidate or len(candidate) > maximum:
        raise AzureLighthouseValidationError(f"Azure Lighthouse {label} is invalid.")
    if any(ord(character) < 32 for character in candidate):
        raise AzureLighthouseValidationError(f"Azure Lighthouse {label} is invalid.")
    return candidate


def normalize_description(value: str) -> str:
    candidate = value.strip()
    if not candidate or len(candidate) > MAX_DESCRIPTION_LENGTH:
        raise AzureLighthouseValidationError("Azure Lighthouse offer description is invalid.")
    if any(ord(character) < 32 and character not in {"\n", "\t"} for character in candidate):
        raise AzureLighthouseValidationError("Azure Lighthouse offer description is invalid.")
    return candidate


def scope_path(subscription_id: str, resource_group: str | None = None) -> str:
    subscription = normalize_uuid(subscription_id, "subscription ID")
    group = normalize_resource_group(resource_group)
    if group:
        return f"/subscriptions/{subscription}/resourceGroups/{group}"
    return f"/subscriptions/{subscription}"
