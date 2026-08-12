"""Bounded Power Platform custom-connector definition preparation."""

from __future__ import annotations

import json
import re
import shutil
from collections.abc import Mapping
from typing import cast

MAX_CONNECTOR_DEFINITION_BYTES = 1_000_000
MAX_CONNECTOR_ACTIONS = 64
MAX_CONNECTOR_PARAMETERS = 32
MAX_CONNECTOR_TEXT = 240
_IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,63}$")
_SECRET_TOKENS = ("key", "token", "secret", "password", "credential", "authorization")
_HTTP_METHODS = ("get", "post", "put", "patch", "delete")


class OpenApiDefinitionError(ValueError):
    """Raised when an OpenAPI definition cannot be safely prepared."""


def generate_power_platform_connector(
    connector_id: str,
    definition: Mapping[str, object],
) -> dict[str, object]:
    """Return a metadata-only custom connector preparation artifact.

    The result is suitable for review or a later Power Platform import. It does
    not acquire credentials, call an API, invoke ``pac``, or deploy anything.
    """

    identifier = _identifier(connector_id, "connector_id")
    document = _object(definition, "definition")
    if definition_size_bytes(document) > MAX_CONNECTOR_DEFINITION_BYTES:
        raise OpenApiDefinitionError("definition exceeds the 1 MB connector import limit")
    if document.get("swagger") != "2.0":
        raise OpenApiDefinitionError("definition must use OpenAPI 2.0 (swagger=2.0)")
    info = _object(document.get("info"), "info")
    title = _text(info.get("title"), "info.title")
    version = _text(info.get("version"), "info.version", max_length=40)
    host = _text(document.get("host"), "host", max_length=253).lower()
    if any(character in host for character in "/\\:@\x00\r\n"):
        raise OpenApiDefinitionError("host must be a hostname without a scheme or path")
    schemes = document.get("schemes", ["https"])
    if not isinstance(schemes, list) or not schemes or any(item not in {"https"} for item in schemes):
        raise OpenApiDefinitionError("connector definitions must use https only")
    base_path = document.get("basePath", "/")
    base_path = _text(base_path, "basePath", max_length=200)
    if not base_path.startswith("/") or ".." in base_path or any(ord(char) < 32 for char in base_path):
        raise OpenApiDefinitionError("basePath must be a safe absolute path")

    paths = _object(document.get("paths"), "paths")
    if not paths or len(paths) > MAX_CONNECTOR_ACTIONS:
        raise OpenApiDefinitionError(f"paths must contain 1-{MAX_CONNECTOR_ACTIONS} entries")
    actions: list[dict[str, object]] = []
    seen_operation_ids: set[str] = set()
    for path, raw_path in paths.items():
        if not isinstance(path, str) or not path.startswith("/") or ".." in path:
            raise OpenApiDefinitionError("each path must be a safe absolute path")
        path_item = _object(raw_path, f"paths.{path}")
        path_parameters = path_item.get("parameters", [])
        for method in _HTTP_METHODS:
            operation = path_item.get(method)
            if operation is None:
                continue
            operation_object = _object(operation, f"paths.{path}.{method}")
            operation_id = _identifier(operation_object.get("operationId"), "operationId")
            if operation_id in seen_operation_ids:
                raise OpenApiDefinitionError(f"duplicate operationId: {operation_id}")
            seen_operation_ids.add(operation_id)
            parameters = _parameters(
                [
                    *(_array(path_parameters, f"paths.{path}.parameters")),
                    *(_array(operation_object.get("parameters", []), f"{operation_id}.parameters")),
                ],
                operation_id,
            )
            responses = _responses(operation_object.get("responses"), operation_id)
            actions.append(
                {
                    "id": operation_id,
                    "method": method.upper(),
                    "path": path,
                    "summary": _text(operation_object.get("summary", operation_id), f"{operation_id}.summary"),
                    "parameters": parameters,
                    "response_statuses": responses,
                }
            )
    if not actions:
        raise OpenApiDefinitionError("definition must contain at least one supported HTTP action")

    authentication = _authentication(document.get("securityDefinitions", {}))
    return {
        "format": "wait-local-agent.power-platform.custom-connector",
        "format_version": 1,
        "connector_id": identifier,
        "display_name": title,
        "api_version": version,
        "host": host,
        "base_path": base_path,
        "authentication": authentication,
        "actions": actions,
        "credentials_included": False,
        "deployment_started": False,
    }


def _parameters(value: list[object], operation_id: str) -> list[dict[str, object]]:
    if len(value) > MAX_CONNECTOR_PARAMETERS:
        raise OpenApiDefinitionError(f"{operation_id}.parameters exceeds {MAX_CONNECTOR_PARAMETERS} items")
    result: list[dict[str, object]] = []
    for raw in value:
        parameter = _object(raw, f"{operation_id}.parameter")
        name = _text(parameter.get("name"), f"{operation_id}.parameter.name", max_length=120)
        location = parameter.get("in")
        if location not in {"query", "path", "header", "body", "formData"}:
            raise OpenApiDefinitionError(f"{operation_id} has an unsupported parameter location")
        if any(token in name.casefold() for token in _SECRET_TOKENS):
            raise OpenApiDefinitionError(f"{operation_id} parameter names may not contain secret material")
        if any(key in parameter for key in ("default", "example", "x-ms-example")):
            raise OpenApiDefinitionError(f"{operation_id} parameters may not include example or default values")
        result.append(
            {
                "name": name,
                "in": location,
                "required": bool(parameter.get("required", False)),
                "type": parameter.get("type", "object"),
            }
        )
    return result


def _responses(value: object, operation_id: str) -> list[str]:
    responses = _object(value, f"{operation_id}.responses")
    statuses = [status for status in responses if isinstance(status, str) and status.isdigit()]
    if not statuses:
        raise OpenApiDefinitionError(f"{operation_id}.responses must contain a status")
    return sorted(statuses)


def _authentication(value: object) -> list[dict[str, object]]:
    definitions = _object(value, "securityDefinitions")
    result: list[dict[str, object]] = []
    for name, raw in definitions.items():
        definition = _object(raw, f"securityDefinitions.{name}")
        auth_type = definition.get("type")
        if auth_type not in {"apiKey", "oauth2", "basic"}:
            raise OpenApiDefinitionError(f"unsupported security definition type: {auth_type}")
        result.append(
            {
                "name": _text(name, "security definition name", max_length=80),
                "type": auth_type,
                "in": definition.get("in") if auth_type == "apiKey" else None,
                "authorization_url_present": bool(definition.get("authorizationUrl"))
                if auth_type == "oauth2"
                else False,
            }
        )
    return result


def _object(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise OpenApiDefinitionError(f"{field} must be an object")
    return cast(dict[str, object], dict(value))


def _array(value: object, field: str) -> list[object]:
    if not isinstance(value, list):
        raise OpenApiDefinitionError(f"{field} must be an array")
    return value


def _text(value: object, field: str, *, max_length: int = MAX_CONNECTOR_TEXT) -> str:
    if not isinstance(value, str) or not value.strip():
        raise OpenApiDefinitionError(f"{field} must be non-empty text")
    normalized = value.strip()
    if len(normalized) > max_length or any(ord(character) < 32 for character in normalized):
        raise OpenApiDefinitionError(f"{field} is too long or contains control characters")
    return normalized


def _identifier(value: object, field: str) -> str:
    normalized = _text(value, field, max_length=64).casefold()
    if not _IDENTIFIER.fullmatch(normalized):
        raise OpenApiDefinitionError(f"{field} must be a lowercase identifier")
    return normalized


def definition_size_bytes(definition: Mapping[str, object]) -> int:
    return len(json.dumps(definition, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def power_platform_cli_status() -> dict[str, object]:
    """Report local ``pac`` availability without starting a process."""

    path = shutil.which("pac")
    return {
        "available": path is not None,
        "path": path,
        "commands_executed": False,
    }


def build_solution_command_plan(
    solution_name: str,
    publisher_name: str,
    publisher_prefix: str,
    output_directory: str,
) -> dict[str, object]:
    """Build a reviewable ``pac solution`` plan without filesystem side effects."""

    name = _identifier(solution_name, "solution_name")
    publisher = _text(publisher_name, "publisher_name", max_length=100)
    if not re.fullmatch(r"[A-Za-z0-9_]+", publisher):
        raise OpenApiDefinitionError("publisher_name may contain only letters, numbers, and underscores")
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9]{1,7}", publisher_prefix):
        raise OpenApiDefinitionError("publisher_prefix must be 2-8 alphanumeric characters and start with a letter")
    directory = _text(output_directory, "output_directory", max_length=240)
    return {
        "solution_name": name,
        "publisher_name": publisher,
        "publisher_prefix": publisher_prefix,
        "output_directory": directory,
        "commands": [
            [
                "pac",
                "solution",
                "init",
                "--publisher-name",
                publisher,
                "--publisher-prefix",
                publisher_prefix,
                "--outputDirectory",
                directory,
            ],
            ["pac", "solution", "pack", "--folder", directory, "--zipfile", f"{directory}/{name}.zip"],
            ["pac", "solution", "check", "--path", f"{directory}/{name}.zip"],
        ],
        "execution_started": False,
        "deployment_started": False,
    }
