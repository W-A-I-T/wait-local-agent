"""Bounded Power Apps and Dataverse plans and local build artifacts."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any, cast

MAX_APP_ENTITIES = 16
MAX_APP_FIELDS = 32
MAX_APP_SCREENS = 16
MAX_APP_ACTIONS = 32
MAX_ARTIFACT_BYTES = 256_000
_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_FIELD_TYPES = {"string", "integer", "boolean", "date", "datetime", "choice", "lookup"}
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
) -> dict[str, Any]:
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


def build_power_apps_artifact(
    *,
    client_id: str,
    app_name: str,
    entities: list[dict[str, object]],
    screens: list[dict[str, object]],
    actions: list[dict[str, object]],
) -> dict[str, Any]:
    """Build a local, reviewable Power Platform artifact manifest.

    This produces deterministic JSON payloads that can be reviewed or handed
    to a later Power Platform packager. It is not an ``.msapp`` or Dataverse
    solution zip and never calls Microsoft services or ``pac``.
    """

    plan = build_power_apps_plan(
        client_id=client_id,
        app_name=app_name,
        entities=entities,
        screens=screens,
        actions=actions,
    )
    dataverse_tables = cast(dict[str, object], plan["dataverse"])["tables"]
    canvas = cast(dict[str, object], plan["canvas_app"])
    tables = cast(list[dict[str, object]], dataverse_tables)
    canvas_screens = cast(list[dict[str, object]], canvas["screens"])
    canvas_actions = cast(list[dict[str, object]], canvas["actions"])
    schema_tables: list[dict[str, object]] = []
    for table in tables:
        columns: list[dict[str, object]] = []
        for field in cast(list[dict[str, object]], table["fields"]):
            column: dict[str, object] = {
                "logical_name": field["name"],
                "display_name": field["display_name"],
                "type": _dataverse_type(field["type"]),
                "required": field["required"],
            }
            if field.get("type") == "lookup":
                column["target_entity"] = field["target_entity"]
            columns.append(column)
        schema_table: dict[str, object] = {
            "logical_name": table["logical_name"],
            "display_name": table["display_name"],
            "columns": columns,
        }
        if "primary_name_column" in table:
            schema_table["primary_name_column"] = table["primary_name_column"]
        schema_tables.append(schema_table)
    schema = {
        "schema_version": 1,
        "tables": schema_tables,
    }
    manifest = {
        "manifest_version": 1,
        "name": plan["app_name"],
        "data_sources": [table["logical_name"] for table in tables],
        "screens": [
            {
                "name": screen["id"],
                "display_name": screen["title"],
                "mode": screen["mode"],
                "data_source": screen["entity"],
                "controls": _screen_controls(screen),
            }
            for screen in canvas_screens
        ],
        "connector_references": [
            {
                "id": action["id"],
                "connector_id": action["connector_id"],
                "method": action["method"],
                "approval_required": action["approval_required"],
            }
            for action in canvas_actions
        ],
    }
    solution_name = _solution_identifier(cast(str, plan["client_id"]), cast(str, plan["app_name"]))
    files = [
        {
            "path": "dataverse/schema.json",
            "media_type": "application/json",
            "content": schema,
        },
        {
            "path": "canvas-app/manifest.json",
            "media_type": "application/json",
            "content": manifest,
        },
        {
            "path": "README.md",
            "media_type": "text/markdown",
            "content": (
                f"# {plan['app_name']}\n\n"
                "Generated locally for review. This artifact contains no credentials, "
                "does not call Microsoft services, and has not been deployed.\n"
            ),
        },
    ]
    artifact: dict[str, object] = {
        "format": "wait-local-agent.power-apps-artifact",
        "format_version": 1,
        "client_id": plan["client_id"],
        "app_name": plan["app_name"],
        "solution": {"unique_name": solution_name, "publisher_prefix": "wait"},
        "dataverse": schema,
        "canvas_app": manifest,
        "files": files,
        "requires_approval": plan["requires_approval"],
        "credentials_included": False,
        "build_started": True,
        "dataverse_write_started": False,
        "execution_started": False,
        "deployment_started": False,
        "package_status": "review_only",
    }
    if len(json.dumps(artifact, sort_keys=True, separators=(",", ":"))) > MAX_ARTIFACT_BYTES:
        raise PowerAppsPlanError("Power Apps artifact exceeds the bounded output size")
    return artifact


def _dataverse_type(value: object) -> str:
    return {
        "string": "String",
        "integer": "Integer",
        "boolean": "Boolean",
        "date": "DateOnly",
        "datetime": "DateTime",
        "choice": "Choice",
        "lookup": "Lookup",
    }.get(str(value), "String")


def _screen_controls(screen: dict[str, object]) -> list[dict[str, object]]:
    mode = str(screen["mode"])
    if mode == "browse":
        return [{"name": f"{screen['id']}_gallery", "type": "gallery", "data_source": screen["entity"]}]
    return [{"name": f"{screen['id']}_form", "type": "form", "mode": mode, "data_source": screen["entity"]}]


def _solution_identifier(client_id: str, app_name: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "_", f"{client_id}_{app_name}".casefold()).strip("_")
    return f"wait_{value[:72]}" if value else "wait_solution"


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
        primary_name_column: str | None = None
        if "primary_name_column" in entity:
            primary_name_column = _identifier(
                entity.get("primary_name_column"),
                f"{logical_name}.primary_name_column",
            )
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
                    "display_name": _text(
                        field.get("display_name", field_name),
                        f"{logical_name}.{field_name}.display_name",
                        120,
                    ),
                    "required": bool(field.get("required", False)),
                }
            )
            if field_type == "lookup":
                field_views[-1]["target_entity"] = _identifier(
                    field.get("target_entity"),
                    f"{logical_name}.{field_name}.target_entity",
                )
        if primary_name_column is not None and primary_name_column not in field_names:
            raise PowerAppsPlanError(
                f"{logical_name}.primary_name_column must name a declared field: {primary_name_column}"
            )
        entity_view: dict[str, object] = {
            "logical_name": logical_name,
            "display_name": _text(entity.get("display_name", logical_name), "entity.display_name", 120),
            "fields": field_views,
        }
        if primary_name_column is not None:
            entity_view["primary_name_column"] = primary_name_column
        result.append(entity_view)
    entity_names = {cast(str, entity["logical_name"]) for entity in result}
    for entity in result:
        logical_name = cast(str, entity["logical_name"])
        for field in cast(list[dict[str, object]], entity["fields"]):
            if field.get("type") == "lookup" and field["target_entity"] not in entity_names:
                raise PowerAppsPlanError(
                    f"{logical_name}.{field['name']}.target_entity references unknown entity: "
                    f"{field['target_entity']}"
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
