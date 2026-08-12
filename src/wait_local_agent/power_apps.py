"""Metadata-only Power Apps and Dataverse builder plans."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import cast

MAX_APP_ENTITIES = 16
MAX_APP_FIELDS = 32
MAX_APP_SCREENS = 16
MAX_APP_ACTIONS = 32
_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_FIELD_TYPES = {"string", "integer", "boolean", "date", "datetime", "choice"}
_SCREEN_MODES = {"browse", "display", "edit"}
_SECRET_TOKENS = ("key", "token", "secret", "password", "credential")


class PowerAppsPlanError(ValueError):
    """Raised when a Power Apps plan is malformed or unsafe."""


def build_power_apps_plan(
    *,
    client_id: str,
    app_name: str,
    entities: list[dict[str, object]],
    screens: list[dict[str, object]],
    actions: list[dict[str, object]],
) -> dict[str, object]:
    tenant = _text(client_id, "client_id", 128)
    normalized_app_name = _text(app_name, "app_name", 120)
    entity_views = _entities(entities)
    entity_names: set[str] = {cast(str, entity["logical_name"]) for entity in entity_views}
    screen_views = _screens(screens, entity_names)
    action_views = _actions(actions)
    return {
        "format": "wait-local-agent.power-apps-plan",
        "format_version": 1,
        "client_id": tenant,
        "app_name": normalized_app_name,
        "dataverse": {"tables": entity_views},
        "canvas_app": {"screens": screen_views, "actions": action_views},
        "requires_approval": any(action["approval_required"] for action in action_views),
        "deployment_started": False,
        "dataverse_write_started": False,
    }


def _entities(value: object) -> list[dict[str, object]]:
    items = _objects(value, "entities", MAX_APP_ENTITIES)
    result: list[dict[str, object]] = []
    seen: set[str] = set()
    for entity in items:
        logical_name = _identifier(entity.get("logical_name"), "entity.logical_name")
        if logical_name in seen:
            raise PowerAppsPlanError(f"duplicate entity logical_name: {logical_name}")
        seen.add(logical_name)
        fields = _objects(entity.get("fields", []), f"{logical_name}.fields", MAX_APP_FIELDS)
        field_views: list[dict[str, object]] = []
        field_names: set[str] = set()
        for field in fields:
            field_name = _identifier(field.get("name"), f"{logical_name}.field.name")
            if field_name in field_names:
                raise PowerAppsPlanError(f"duplicate field name: {logical_name}.{field_name}")
            field_names.add(field_name)
            field_type = field.get("type", "string")
            if field_type not in _FIELD_TYPES:
                raise PowerAppsPlanError(f"unsupported field type: {field_type}")
            if any(token in field_name for token in _SECRET_TOKENS):
                raise PowerAppsPlanError("field names may not contain secret material")
            field_views.append(
                {
                    "name": field_name,
                    "type": field_type,
                    "required": bool(field.get("required", False)),
                }
            )
        result.append(
            {
                "logical_name": logical_name,
                "display_name": _text(entity.get("display_name", logical_name), "entity.display_name", 120),
                "fields": field_views,
            }
        )
    return result


def _screens(value: object, entity_names: set[str]) -> list[dict[str, object]]:
    items = _objects(value, "screens", MAX_APP_SCREENS)
    result: list[dict[str, object]] = []
    seen: set[str] = set()
    for screen in items:
        screen_id = _identifier(screen.get("id"), "screen.id")
        if screen_id in seen:
            raise PowerAppsPlanError(f"duplicate screen id: {screen_id}")
        seen.add(screen_id)
        entity = _identifier(screen.get("entity"), "screen.entity")
        if entity not in entity_names:
            raise PowerAppsPlanError(f"screen references unknown entity: {entity}")
        mode = screen.get("mode", "browse")
        if mode not in _SCREEN_MODES:
            raise PowerAppsPlanError(f"unsupported screen mode: {mode}")
        result.append(
            {
                "id": screen_id,
                "title": _text(screen.get("title", screen_id), "screen.title", 120),
                "entity": entity,
                "mode": mode,
            }
        )
    return result


def _actions(value: object) -> list[dict[str, object]]:
    items = _objects(value, "actions", MAX_APP_ACTIONS)
    result: list[dict[str, object]] = []
    seen: set[str] = set()
    for action in items:
        action_id = _identifier(action.get("id"), "action.id")
        if action_id in seen:
            raise PowerAppsPlanError(f"duplicate action id: {action_id}")
        seen.add(action_id)
        method = action.get("method", "GET")
        if method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
            raise PowerAppsPlanError(f"unsupported action method: {method}")
        approval_required = action.get("approval_required", False)
        if not isinstance(approval_required, bool):
            raise PowerAppsPlanError("action approval_required must be boolean")
        if method != "GET" and not approval_required:
            raise PowerAppsPlanError(f"write action requires approval: {action_id}")
        result.append(
            {
                "id": action_id,
                "connector_id": _identifier(action.get("connector_id"), "action.connector_id"),
                "method": method,
                "approval_required": approval_required,
            }
        )
    return result


def _objects(value: object, field: str, maximum: int) -> list[dict[str, object]]:
    if not isinstance(value, list) or len(value) > maximum:
        raise PowerAppsPlanError(f"{field} must contain 0-{maximum} objects")
    if any(not isinstance(item, Mapping) for item in value):
        raise PowerAppsPlanError(f"{field} must contain objects")
    return [cast(dict[str, object], dict(item)) for item in value]


def _identifier(value: object, field: str) -> str:
    normalized = _text(value, field, 64).casefold()
    if not _IDENTIFIER.fullmatch(normalized):
        raise PowerAppsPlanError(f"{field} must be a lowercase identifier")
    return normalized


def _text(value: object, field: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        raise PowerAppsPlanError(f"{field} must be non-empty text of at most {maximum} characters")
    normalized = value.strip()
    if any(ord(character) < 32 for character in normalized):
        raise PowerAppsPlanError(f"{field} contains unsupported control characters")
    return normalized
