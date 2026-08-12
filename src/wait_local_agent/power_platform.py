"""Bounded Power Platform custom-connector artifact generation."""

from __future__ import annotations

import json
import re
from typing import cast
from urllib.parse import urlsplit

from wait_local_agent.reports.renderers import redact_text, redact_value

MAX_OPENAPI_DEFINITION_BYTES = 950_000
MAX_OPENAPI_PATHS = 128
MAX_OPENAPI_OPERATIONS = 256
MAX_OPENAPI_PARAMETERS = 64
MAX_OPENAPI_DEPTH = 24
MAX_OPENAPI_COLLECTION_ITEMS = 512
SUPPORTED_HTTP_METHODS = frozenset({"get", "post", "put", "patch", "delete", "head", "options"})
OPERATION_ID_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,79}$")
HEX_COLOR_PATTERN = re.compile(r"^#[0-9A-Fa-f]{6}$")


class PowerPlatformConnectorError(ValueError):
    """Raised when an OpenAPI definition cannot become a safe connector artifact."""


def build_power_platform_connector(
    definition: object,
    *,
    name: str | None = None,
    publisher: str = "WAIT",
    stack_owner: str = "WAIT",
    icon_brand_color: str = "#1f6f55",
) -> dict[str, object]:
    """Build deterministic ``apiDefinition.json`` and ``apiProperties.json`` artifacts.

    The factory only transforms a supplied OpenAPI 2.0 document. It never
    fetches a URL, resolves a remote reference, probes an API, or stores a
    credential.
    """

    source = _object(definition, "OpenAPI definition")
    _validate_tree(source)
    _validate_size(source)
    if source.get("swagger") != "2.0":
        raise PowerPlatformConnectorError("Power Platform custom connectors require OpenAPI 2.0")
    info = _object(source.get("info"), "OpenAPI info")
    source_paths = _object(source.get("paths"), "OpenAPI paths")
    if not source_paths:
        raise PowerPlatformConnectorError("OpenAPI paths must not be empty")
    if len(source_paths) > MAX_OPENAPI_PATHS:
        raise PowerPlatformConnectorError(f"OpenAPI may contain at most {MAX_OPENAPI_PATHS} paths")

    _validate_info(info)
    connector_name = _text(name if name is not None else info.get("title"), "connector name", 80)
    safe_publisher = _text(publisher, "publisher", 120)
    safe_stack_owner = _text(stack_owner, "stack owner", 120)
    if not HEX_COLOR_PATTERN.fullmatch(icon_brand_color):
        raise PowerPlatformConnectorError("icon brand color must be a six-digit hex color")
    host = _host(source.get("host"))
    base_path = _base_path(source.get("basePath", "/"))
    _validate_schemes(source.get("schemes", ["https"]))
    operation_count = _validate_paths(source_paths)
    security_name, security_definition, security_warnings = _select_security(source.get("securityDefinitions"))

    safe_definition = cast(dict[str, object], redact_value(source))
    safe_info = cast(dict[str, object], safe_definition["info"])
    safe_info["title"] = connector_name
    safe_definition["info"] = safe_info
    safe_definition["host"] = host
    safe_definition["basePath"] = base_path
    safe_definition["schemes"] = ["https"]

    api_properties = _api_properties(
        security_name,
        security_definition,
        publisher=safe_publisher,
        stack_owner=safe_stack_owner,
        icon_brand_color=icon_brand_color,
    )
    warnings = list(security_warnings)
    if security_name is None:
        warnings.append("The generated connector has no authentication definition; review before import.")
    if security_definition is not None and security_definition.get("type") == "oauth2":
        warnings.append("OAuth client ID and client secret must be configured in Power Platform; none were generated.")

    return {
        "format": "wait-local-agent.power-platform-connector",
        "format_version": 1,
        "name": connector_name,
        "auth_type": str(security_definition.get("type")) if security_definition else "none",
        "operation_count": operation_count,
        "warnings": warnings,
        "api_definition": safe_definition,
        "api_properties": api_properties,
    }


def _object(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise PowerPlatformConnectorError(f"{field} must be an object")
    return cast(dict[str, object], value)


def _text(value: object, field: str, limit: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PowerPlatformConnectorError(f"{field} must be non-empty text")
    normalized = redact_text(value.strip())
    if len(normalized) > limit:
        raise PowerPlatformConnectorError(f"{field} exceeds {limit} characters")
    if any(ord(character) < 32 and character not in "\t\n" for character in normalized):
        raise PowerPlatformConnectorError(f"{field} contains unsupported control characters")
    return normalized


def _validate_tree(value: object, *, depth: int = 0) -> None:
    if depth > MAX_OPENAPI_DEPTH:
        raise PowerPlatformConnectorError("OpenAPI definition nesting is too deep")
    if isinstance(value, dict):
        if len(value) > MAX_OPENAPI_COLLECTION_ITEMS:
            raise PowerPlatformConnectorError("OpenAPI object contains too many fields")
        for key, child in value.items():
            if not isinstance(key, str):
                raise PowerPlatformConnectorError("OpenAPI object keys must be text")
            if key == "$ref":
                if not isinstance(child, str) or not child.startswith("#/"):
                    raise PowerPlatformConnectorError("OpenAPI references must be local #/ references")
            _validate_tree(child, depth=depth + 1)
    elif isinstance(value, list):
        if len(value) > MAX_OPENAPI_COLLECTION_ITEMS:
            raise PowerPlatformConnectorError("OpenAPI array contains too many items")
        for child in value:
            _validate_tree(child, depth=depth + 1)
    elif isinstance(value, str):
        if len(value) > MAX_OPENAPI_DEFINITION_BYTES:
            raise PowerPlatformConnectorError("OpenAPI text value is too large")
    elif value is not None and not isinstance(value, (bool, int, float)):
        raise PowerPlatformConnectorError("OpenAPI definition contains a non-JSON value")


def _validate_size(definition: dict[str, object]) -> None:
    try:
        encoded = json.dumps(definition, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise PowerPlatformConnectorError("OpenAPI definition must be JSON serializable") from exc
    if len(encoded.encode("utf-8")) >= 1_000_000:
        raise PowerPlatformConnectorError("OpenAPI definition must be smaller than 1 MB")
    if len(encoded.encode("utf-8")) > MAX_OPENAPI_DEFINITION_BYTES:
        raise PowerPlatformConnectorError(
            f"OpenAPI definition exceeds the local {MAX_OPENAPI_DEFINITION_BYTES}-byte safety limit"
        )


def _validate_info(info: dict[str, object]) -> None:
    _text(info.get("title"), "OpenAPI info.title", 160)
    _text(info.get("version"), "OpenAPI info.version", 64)
    description = info.get("description")
    if description is not None:
        _text(description, "OpenAPI info.description", 4000)


def _host(value: object) -> str:
    host = _text(value, "OpenAPI host", 253)
    if (
        any(character in host for character in "/?#@{}")
        or "://" in host
        or any(character.isspace() for character in host)
    ):
        raise PowerPlatformConnectorError("OpenAPI host must be a host name without credentials or a URL")
    try:
        parsed = urlsplit(f"https://{host}")
        if not parsed.hostname:
            raise ValueError
        _ = parsed.port
    except ValueError as exc:
        raise PowerPlatformConnectorError("OpenAPI host is invalid") from exc
    return host


def _base_path(value: object) -> str:
    base_path = _text(value, "OpenAPI basePath", 256)
    if not base_path.startswith("/") or any(character in base_path for character in "?#"):
        raise PowerPlatformConnectorError("OpenAPI basePath must be a path beginning with /")
    return base_path.rstrip("/") or "/"


def _validate_schemes(value: object) -> None:
    if not isinstance(value, list) or not value:
        raise PowerPlatformConnectorError("OpenAPI schemes must be a non-empty array")
    if any(scheme != "https" for scheme in value):
        raise PowerPlatformConnectorError("Power Platform connector definitions must use HTTPS only")


def _validate_paths(paths: dict[str, object]) -> int:
    operation_ids: set[str] = set()
    operation_count = 0
    for path, path_item in paths.items():
        if not isinstance(path, str) or not path.startswith("/") or any(character in path for character in "?#"):
            raise PowerPlatformConnectorError("OpenAPI path keys must be URL paths beginning with /")
        item = _object(path_item, f"OpenAPI path {path}")
        for method, operation in item.items():
            if method == "parameters":
                _validate_parameters(operation, f"OpenAPI path {path}.parameters")
                continue
            if method.startswith("x-"):
                continue
            if method not in SUPPORTED_HTTP_METHODS:
                raise PowerPlatformConnectorError(f"OpenAPI path {path} uses unsupported method {method}")
            operation_count += 1
            if operation_count > MAX_OPENAPI_OPERATIONS:
                raise PowerPlatformConnectorError(
                    f"OpenAPI may contain at most {MAX_OPENAPI_OPERATIONS} operations"
                )
            operation_object = _object(operation, f"OpenAPI operation {method.upper()} {path}")
            operation_id = _text(
                operation_object.get("operationId"),
                f"OpenAPI operation {method.upper()} {path}.operationId",
                80,
            )
            if not OPERATION_ID_PATTERN.fullmatch(operation_id):
                raise PowerPlatformConnectorError(f"OpenAPI operationId is invalid: {operation_id}")
            if operation_id in operation_ids:
                raise PowerPlatformConnectorError(f"OpenAPI operationIds must be unique: {operation_id}")
            operation_ids.add(operation_id)
            responses = _object(operation_object.get("responses"), f"OpenAPI operation {operation_id}.responses")
            if not responses:
                raise PowerPlatformConnectorError(f"OpenAPI operation {operation_id} must define a response")
            for response_code, response in responses.items():
                response_object = _object(response, f"OpenAPI response {operation_id}.{response_code}")
                if set(response_object) == {"$ref"}:
                    continue
                _text(response_object.get("description"), f"OpenAPI response {operation_id}.description", 1000)
            if "parameters" in operation_object:
                _validate_parameters(operation_object["parameters"], f"OpenAPI operation {operation_id}.parameters")
    if operation_count == 0:
        raise PowerPlatformConnectorError("OpenAPI paths must define at least one operation")
    return operation_count


def _validate_parameters(value: object, field: str) -> None:
    if not isinstance(value, list) or len(value) > MAX_OPENAPI_PARAMETERS:
        raise PowerPlatformConnectorError(f"{field} must be an array of at most {MAX_OPENAPI_PARAMETERS} parameters")
    for index, parameter in enumerate(value):
        parameter_object = _object(parameter, f"{field}[{index}]")
        if "$ref" not in parameter_object:
            _text(parameter_object.get("name"), f"{field}[{index}].name", 160)
            _text(parameter_object.get("in"), f"{field}[{index}].in", 32)


def _select_security(
    value: object,
) -> tuple[str | None, dict[str, object] | None, tuple[str, ...]]:
    if value is None:
        return None, None, ()
    definitions = _object(value, "OpenAPI securityDefinitions")
    if not definitions:
        return None, None, ()
    name, raw_definition = next(iter(definitions.items()))
    safe_name = _text(name, "security definition name", 120)
    selected = _object(raw_definition, f"OpenAPI security definition {safe_name}")
    auth_type = selected.get("type")
    if auth_type not in {"apiKey", "basic", "oauth2"}:
        raise PowerPlatformConnectorError(f"security definition {safe_name} uses unsupported auth type")
    if auth_type == "apiKey":
        if selected.get("in") not in {"header", "query"}:
            raise PowerPlatformConnectorError(f"security definition {safe_name} apiKey location is unsupported")
        _text(selected.get("name"), f"security definition {safe_name}.name", 160)
    elif auth_type == "oauth2":
        _validate_oauth(safe_name, selected)
    warnings: tuple[str, ...] = ()
    if len(definitions) > 1:
        remaining = ", ".join(item for item in definitions if item != name)
        warnings = (
            f"Power Platform will use the first security definition ({safe_name}); "
            f"review the remaining definitions: {remaining}.",
        )
    return safe_name, selected, warnings


def _validate_oauth(name: str, definition: dict[str, object]) -> None:
    flow = definition.get("flow")
    if flow == "application":
        raise PowerPlatformConnectorError(
            f"security definition {name} uses OAuth application flow, which custom connectors do not support"
        )
    if flow not in {"implicit", "accessCode", "password"}:
        raise PowerPlatformConnectorError(f"security definition {name} OAuth flow is unsupported")
    if flow in {"implicit", "accessCode"}:
        _https_url(definition.get("authorizationUrl"), f"security definition {name}.authorizationUrl")
    if flow in {"accessCode", "password"}:
        _https_url(definition.get("tokenUrl"), f"security definition {name}.tokenUrl")
    scopes = definition.get("scopes", {})
    if not isinstance(scopes, dict) or len(scopes) > 64:
        raise PowerPlatformConnectorError(f"security definition {name}.scopes must be a bounded object")
    for scope, description in scopes.items():
        _text(scope, f"security definition {name}.scope", 160)
        _text(description, f"security definition {name}.scope description", 400)


def _https_url(value: object, field: str) -> str:
    url = _text(value, field, 2048)
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        raise PowerPlatformConnectorError(f"{field} must be an HTTPS URL without credentials")
    return url


def _api_properties(
    security_name: str | None,
    security_definition: dict[str, object] | None,
    *,
    publisher: str,
    stack_owner: str,
    icon_brand_color: str,
) -> dict[str, object]:
    connection_parameters: dict[str, object] = {}
    if security_name is not None and security_definition is not None:
        auth_type = security_definition.get("type")
        if auth_type == "apiKey":
            connection_parameters[security_name] = {
                "type": "securestring",
                "uiDefinition": _ui_definition(
                    str(security_definition.get("name")),
                    "API key used to authenticate the custom connector.",
                ),
            }
        elif auth_type == "basic":
            connection_parameters = {
                "username": {"type": "securestring", "uiDefinition": _ui_definition("Username", "API username.")},
                "password": {"type": "securestring", "uiDefinition": _ui_definition("Password", "API password.")},
            }
        elif auth_type == "oauth2":
            scopes = security_definition.get("scopes", {})
            connection_parameters[security_name] = {
                "type": "oauthSetting",
                "oAuthSettings": {
                    "identityProvider": "oauth2",
                    "scopes": " ".join(str(scope) for scope in cast(dict[object, object], scopes)),
                    "clientId": "",
                    "clientSecret": "",
                    "authorizationUrl": security_definition.get("authorizationUrl", ""),
                    "tokenUrl": security_definition.get("tokenUrl", ""),
                    "redirectMode": "GlobalPerConnector",
                },
                "uiDefinition": _ui_definition("OAuth 2.0", "OAuth settings for the custom connector."),
            }
    return {
        "properties": {
            "connectionParameters": connection_parameters,
            "iconBrandColor": icon_brand_color,
            "capabilities": ["actions"],
            "publisher": publisher,
            "stackOwner": stack_owner,
        }
    }


def _ui_definition(display_name: str, description: str) -> dict[str, object]:
    return {
        "displayName": display_name,
        "description": description,
        "tooltip": description,
        "constraints": {"tabIndex": 2, "clearText": False, "required": True},
    }
