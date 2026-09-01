"""Deterministic, local-only Power Platform YAML source packages.

The package in this module is a source handoff, not a solution ZIP and not a
provider operation.  It deliberately uses the YAML source-control layout that
the Power Platform CLI can pack, while keeping all source material in memory
until the caller explicitly requests gated materialization.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from collections.abc import Mapping, Sequence
from pathlib import Path, PureWindowsPath
from typing import Any, cast

from wait_local_agent.config import Settings

PACKAGE_FORMAT = "wait-local-agent.power-platform.deployable-source"
PACKAGE_VERSION = 1
PAC_YAML_MINIMUM_VERSION = "2.4.1"
MAX_PACKAGE_FILES = 96
MAX_PACKAGE_FILE_BYTES = 64_000
MAX_PACKAGE_BYTES = 512_000
MAX_INPUT_ARTIFACTS = 32
MAX_FLOW_ACTIONS = 32
MAX_INPUT_ARTIFACT_BYTES = 256_000
MAX_PATH_LENGTH = 240
MAX_TEXT_LENGTH = 240
_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_SECRET_KEY = re.compile(
    r"(?:password|passwd|secret|credential|api[_-]?key|access[_-]?key|private[_-]?key|client[_-]?secret|bearer|authorization|token)",
    re.IGNORECASE,
)
_SECRET_SOURCE = re.compile(
    r"(?im)^\s*(?:password|passwd|secret|credential|api[_-]?key|access[_-]?key|private[_-]?key|client[_-]?secret|authorization|token)\s*:\s*(?![\"']?(?:false|null|none)[\"']?\s*$).+"
)
# Newline and tab are valid in source content; path and scalar validation uses
# ``_text`` below for the stricter no-control-character contract.
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_PACKAGE_NAMESPACE = uuid.UUID("6a7b1e95-0b7a-5cf2-9274-85d96b2b6cf4")


class PowerPlatformPackageError(ValueError):
    """Raised when a source package is invalid, unsafe, or out of bounds."""


def build_power_platform_package(
    *,
    client_id: str,
    solution_name: str,
    publisher_name: str,
    publisher_prefix: str,
    output_directory: str,
    artifacts: Sequence[Mapping[str, object]] = (),
    connector_artifacts: Sequence[Mapping[str, object]] = (),
    review_artifacts: Sequence[Mapping[str, object]] | None = None,
) -> dict[str, Any]:
    """Build a deterministic Power Platform YAML source package.

    ``artifacts`` is the preferred input.  ``review_artifacts`` is accepted as
    an integration-friendly alias and ``connector_artifacts`` may be supplied
    separately by delivery callers.  All inputs are validated before any
    source is emitted.  No filesystem, PAC, network, clock, or random source
    is consulted.
    """

    tenant = _text(client_id, "client_id", 128)
    solution = _identifier(solution_name, "solution_name")
    publisher = _publisher_name(publisher_name)
    prefix = _publisher_prefix(publisher_prefix)
    output = _safe_output_directory(output_directory)

    primary = list(artifacts)
    if review_artifacts is not None:
        if primary:
            raise PowerPlatformPackageError("provide artifacts or review_artifacts, not both")
        primary = list(review_artifacts)
    combined = [*primary, *list(connector_artifacts)]
    normalized_artifacts = _validate_input_artifacts(combined, tenant)

    publisher_unique_name = _publisher_identifier(publisher)
    files: dict[str, tuple[str, str]] = {}
    component_paths: set[str] = set()
    root_components: list[dict[str, object]] = []
    unsupported: list[dict[str, object]] = []

    _add_file(
        files,
        f"publishers/{publisher_unique_name}/publisher.yml",
        _yaml(
            {
                "Publisher": {
                    "UniqueName": publisher_unique_name,
                    "LocalizedNames": {
                        "LocalizedName": {
                            "@description": publisher,
                            "@languagecode": "1033",
                        }
                    },
                    "Descriptions": None,
                    "EMailAddress": None,
                    "SupportingWebsiteUrl": None,
                    "CustomizationPrefix": prefix,
                    "CustomizationOptionValuePrefix": "10000",
                    "Addresses": None,
                }
            },
        ),
    )
    component_paths.add(f"publishers/{publisher_unique_name}")

    for artifact_index, artifact in enumerate(normalized_artifacts, start=1):
        artifact_format = str(artifact.get("format", ""))
        if artifact_format == "wait-local-agent.power-apps-artifact":
            _emit_power_apps_artifact(artifact, files, component_paths, root_components, unsupported, tenant)
        elif artifact_format == "wait-local-agent.power-automate-flow-plan":
            _emit_flow_artifact(artifact, files, component_paths, root_components, tenant)
        elif artifact_format == "wait-local-agent.power-platform.custom-connector":
            _emit_connector_artifact(artifact, files, component_paths, root_components, tenant)
        else:
            unsupported.append(
                {
                    "id": str(_component_id(tenant, f"unsupported:{artifact_index}:{artifact_format}")),
                    "format": artifact_format or "unknown",
                    "reason": "artifact format has no supported YAML source mapping",
                }
            )

    solution_path = f"solutions/{solution}"
    component_list = sorted(component_paths)
    root_components = sorted(root_components, key=lambda item: (str(item.get("type")), str(item.get("schema_name"))))
    _add_file(
        files,
        f"{solution_path}/solution.yml",
        _yaml(
            {
                "Solution": {
                    "UniqueName": solution,
                    "LocalizedNames": {
                        "LocalizedName": {
                            "@description": solution,
                            "@languagecode": "1033",
                        }
                    },
                    "Descriptions": None,
                    "Version": "1.0.0.0",
                    "Managed": False,
                    "Publisher": publisher_unique_name,
                }
            }
        ),
    )
    _add_file(files, f"{solution_path}/solutioncomponents.yml", _yaml([{"Path": path} for path in component_list]))
    _add_file(files, f"{solution_path}/rootcomponents.yml", _yaml(root_components))
    _add_file(files, f"{solution_path}/missingdependencies.yml", _yaml([]))

    if unsupported:
        unsupported.sort(key=lambda item: str(item["id"]))
        _add_file(files, "unsupported/components.json", _canonical_json_bytes({"components": unsupported}).decode())

    if len(files) > MAX_PACKAGE_FILES:
        raise PowerPlatformPackageError(f"package may contain at most {MAX_PACKAGE_FILES} files")
    file_views = [
        {
            "path": path,
            "media_type": media_type,
            "digest": _digest(content.encode("utf-8")),
            "content": content,
        }
        for path, (media_type, content) in sorted(files.items())
    ]
    package: dict[str, Any] = {
        "format": PACKAGE_FORMAT,
        "format_version": PACKAGE_VERSION,
        "client_id": tenant,
        "solution": {
            "unique_name": solution,
            "publisher_name": publisher,
            "publisher_unique_name": publisher_unique_name,
            "publisher_prefix": prefix,
        },
        "output_directory": output,
        "files": file_views,
        "file_count": len(file_views),
        "deployable": True,
        "package_status": "deployable_source",
        "credentials_included": False,
        "unsupported_components": unsupported,
        "pac": {
            "minimum_cli_version": PAC_YAML_MINIMUM_VERSION,
            "format": "yaml_source_control",
            "commands": [
                [
                    "pac",
                    "solution",
                    "pack",
                    "--folder",
                    output,
                    "--zipfile",
                    _pack_zip_path(output, solution),
                ]
            ],
        },
        "execution_started": False,
        "deployment_started": False,
    }
    serialized = _canonical_json_bytes(package)
    if len(serialized) > MAX_PACKAGE_BYTES:
        raise PowerPlatformPackageError(f"package exceeds the bounded size limit of {MAX_PACKAGE_BYTES} bytes")
    package["package_digest"] = _digest(serialized)
    return package


def validate_power_platform_package(
    package: Mapping[str, object],
    *,
    client_id: str | None = None,
) -> str:
    """Re-validate a package and return its recomputed package digest."""

    if not isinstance(package, Mapping):
        raise PowerPlatformPackageError("package must be an object")
    if package.get("format") != PACKAGE_FORMAT or package.get("format_version") != PACKAGE_VERSION:
        raise PowerPlatformPackageError("unsupported Power Platform package format")
    tenant = _text(package.get("client_id"), "package.client_id", 128)
    if client_id is not None and tenant != _text(client_id, "client_id", 128):
        raise PowerPlatformPackageError("package is outside the requested tenant")
    if package.get("deployable") is not True or package.get("package_status") != "deployable_source":
        raise PowerPlatformPackageError("package must be marked deployable_source")
    if package.get("credentials_included") is not False:
        raise PowerPlatformPackageError("package must not contain credentials")
    if package.get("execution_started") is not False or package.get("deployment_started") is not False:
        raise PowerPlatformPackageError("package must not report execution or deployment started")
    output = _safe_output_directory(package.get("output_directory"))
    if package.get("output_directory") != output:
        raise PowerPlatformPackageError("package.output_directory is not canonical")
    solution = package.get("solution")
    if not isinstance(solution, Mapping):
        raise PowerPlatformPackageError("package.solution must be an object")
    _identifier(solution.get("unique_name"), "solution.unique_name")
    publisher_name = _publisher_name(solution.get("publisher_name"))
    publisher_unique_name = _identifier(solution.get("publisher_unique_name"), "solution.publisher_unique_name")
    if publisher_unique_name != _publisher_identifier(publisher_name):
        raise PowerPlatformPackageError("solution publisher identity is inconsistent")
    _publisher_prefix(solution.get("publisher_prefix"))
    unsupported_components = package.get("unsupported_components")
    if not isinstance(unsupported_components, list) or len(unsupported_components) > MAX_INPUT_ARTIFACTS:
        raise PowerPlatformPackageError("package.unsupported_components is outside the bounded limit")
    _validate_value(unsupported_components, tenant, "package.unsupported_components")
    files = package.get("files")
    if not isinstance(files, list) or not 1 <= len(files) <= MAX_PACKAGE_FILES:
        raise PowerPlatformPackageError(f"package.files must contain 1-{MAX_PACKAGE_FILES} items")
    if package.get("file_count") != len(files):
        raise PowerPlatformPackageError("package.file_count does not match package.files")
    seen: set[str] = set()
    total = 0
    normalized_files: list[dict[str, object]] = []
    for raw in files:
        if not isinstance(raw, Mapping):
            raise PowerPlatformPackageError("package files must contain objects")
        path = _safe_relative_path(raw.get("path"), "package file path")
        if path in seen:
            raise PowerPlatformPackageError(f"duplicate package file path: {path}")
        seen.add(path)
        content = raw.get("content")
        if not isinstance(content, str) or _CONTROL.search(content):
            raise PowerPlatformPackageError(f"package file {path} contains invalid content")
        encoded = content.encode("utf-8")
        if len(encoded) > MAX_PACKAGE_FILE_BYTES:
            raise PowerPlatformPackageError(f"package file {path} exceeds the bounded size limit")
        total += len(encoded)
        if total > MAX_PACKAGE_BYTES:
            raise PowerPlatformPackageError("package files exceed the bounded size limit")
        media_type = raw.get("media_type")
        if not isinstance(media_type, str) or media_type not in {"text/yaml", "application/json", "text/markdown"}:
            raise PowerPlatformPackageError(f"package file {path} has an unsupported media type")
        if _contains_secret_like_source(content):
            raise PowerPlatformPackageError(f"package file {path} contains secret-like material")
        digest = raw.get("digest")
        if not isinstance(digest, str) or not _DIGEST.fullmatch(digest) or digest != _digest(encoded):
            raise PowerPlatformPackageError(f"package file digest mismatch: {path}")
        normalized_files.append({"path": path, "media_type": media_type, "digest": digest, "content": content})
    required_paths = {
        f"solutions/{cast(str, solution['unique_name'])}/solution.yml",
        f"solutions/{cast(str, solution['unique_name'])}/solutioncomponents.yml",
        f"solutions/{cast(str, solution['unique_name'])}/rootcomponents.yml",
        f"solutions/{cast(str, solution['unique_name'])}/missingdependencies.yml",
        f"publishers/{cast(str, solution['publisher_unique_name'])}/publisher.yml",
    }
    if not required_paths.issubset(seen):
        raise PowerPlatformPackageError("package is missing an official YAML source manifest")
    expected = dict(package)
    supplied_digest = expected.pop("package_digest", None)
    expected["output_directory"] = output
    expected["files"] = sorted(normalized_files, key=lambda item: cast(str, item["path"]))
    expected["file_count"] = len(normalized_files)
    serialized = _canonical_json_bytes(expected)
    if len(serialized) > MAX_PACKAGE_BYTES:
        raise PowerPlatformPackageError("package exceeds the bounded size limit")
    recomputed = _digest(serialized)
    if supplied_digest != recomputed:
        raise PowerPlatformPackageError("package digest mismatch")
    pac = package.get("pac")
    if (
        not isinstance(pac, Mapping)
        or pac.get("minimum_cli_version") != PAC_YAML_MINIMUM_VERSION
        or pac.get("format") != "yaml_source_control"
    ):
        raise PowerPlatformPackageError("package PAC compatibility metadata is invalid")
    commands = pac.get("commands")
    if commands != [
        [
            "pac",
            "solution",
            "pack",
            "--folder",
            output,
            "--zipfile",
            _pack_zip_path(output, cast(str, solution["unique_name"])),
        ]
    ]:
        raise PowerPlatformPackageError("package PAC folder is not digest-bound to output_directory")
    return recomputed


def materialize_power_platform_package(
    package: Mapping[str, object],
    settings: Settings,
    *,
    client_id: str | None = None,
) -> dict[str, object]:
    """Materialize a validated package below the configured local workspace."""

    try:
        digest = validate_power_platform_package(package, client_id=client_id)
    except PowerPlatformPackageError as exc:
        return _materialization_result("failed", str(exc))
    if not settings.allow_write_actions:
        return _materialization_result(
            "blocked",
            "Power Platform source materialization is blocked until WAIT_ALLOW_WRITE_ACTIONS=true.",
            digest,
        )
    try:
        workspace = _safe_workspace(settings.power_platform_workspace)
        raw_output = cast(str, package["output_directory"])
        _reject_symlink_components(Path(raw_output).expanduser(), workspace)
        output = _confined_path(raw_output, workspace, "materialization output directory")
        _reject_symlink_components(output, workspace)
        if output.exists() and not output.is_dir():
            raise PowerPlatformPackageError("materialization output directory is not a directory")
        output.mkdir(parents=True, exist_ok=True)
        _reject_symlink_components(output, workspace)
        files = cast(list[Mapping[str, object]], package["files"])
        written: list[str] = []
        for file in files:
            relative = cast(str, file["path"])
            lexical_target = output / relative
            _reject_symlink_components(lexical_target, workspace)
            target = _confined_path(str(lexical_target), workspace, "materialization file")
            if lexical_target.is_symlink() or target.is_symlink():
                raise PowerPlatformPackageError(f"materialization refuses symlink: {relative}")
            target.parent.mkdir(parents=True, exist_ok=True)
            _reject_symlink_components(target, workspace)
            content = cast(str, file["content"]).encode("utf-8")
            flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0)
            try:
                descriptor = os.open(target, flags, 0o600)
            except OSError as exc:
                if lexical_target.is_symlink():
                    raise PowerPlatformPackageError(f"materialization refuses symlink: {relative}") from exc
                raise
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(content)
            if lexical_target.is_symlink() or target.is_symlink() or _digest(target.read_bytes()) != file["digest"]:
                raise PowerPlatformPackageError(f"on-disk digest verification failed: {relative}")
            written.append(relative)
    except (OSError, PowerPlatformPackageError) as exc:
        return _materialization_result("failed", str(exc), digest)
    solution_metadata = cast(Mapping[str, object], package["solution"])
    zipfile = _pack_zip_path(str(output), cast(str, solution_metadata["unique_name"]))
    return {
        "format": "wait-local-agent.power-platform.materialization-result",
        "format_version": 1,
        "status": "succeeded",
        "message": "Power Platform YAML source was materialized locally.",
        "package_digest": digest,
        "materialization_directory": str(output),
        "files": sorted(written),
        "file_count": len(written),
        "pac_plan": {
            "commands": [
                [
                    "pac",
                    "solution",
                    "pack",
                    "--folder",
                    str(output),
                    "--zipfile",
                    zipfile,
                ]
            ],
            "folder": str(output),
            "zipfile": zipfile,
            "minimum_cli_version": PAC_YAML_MINIMUM_VERSION,
        },
        "materialization_started": True,
        "execution_started": False,
        "deployment_started": False,
    }


def package_validation_result(package: Mapping[str, object], *, client_id: str | None = None) -> dict[str, object]:
    """Return a bounded JSON result for API and CLI validation surfaces."""

    digest = validate_power_platform_package(package, client_id=client_id)
    return {
        "format": "wait-local-agent.power-platform.package-validation",
        "format_version": 1,
        "valid": True,
        "package_digest": digest,
        "client_id": package["client_id"],
        "file_count": package["file_count"],
        "deployable": True,
        "execution_started": False,
        "deployment_started": False,
    }


# The deployable-blueprint names are the stable public contract. Keep the
# Power Platform names as compatibility aliases for existing integrations.
build_deployable_blueprint_package = build_power_platform_package
validate_deployable_blueprint_package = validate_power_platform_package
materialize_deployable_blueprint_package = materialize_power_platform_package


def _emit_power_apps_artifact(
    artifact: Mapping[str, object],
    files: dict[str, tuple[str, str]],
    component_paths: set[str],
    root_components: list[dict[str, object]],
    unsupported: list[dict[str, object]],
    tenant: str,
) -> None:
    dataverse = artifact.get("dataverse")
    if not isinstance(dataverse, Mapping) or not isinstance(dataverse.get("tables"), list):
        raise PowerPlatformPackageError("Power Apps artifact dataverse.tables is required")
    canvas = artifact.get("canvas_app")
    app_name = artifact.get("app_name", "canvas_app")
    app_id = _component_id(tenant, f"canvas:{app_name}")
    unsupported.append(
        {
            "id": str(app_id),
            "format": "canvas_app",
            "source": str(app_name),
            "reason": "binary .msapp synthesis is unsupported; no canvas component is claimed packable",
        }
    )
    for table in cast(list[object], dataverse["tables"]):
        if not isinstance(table, Mapping):
            raise PowerPlatformPackageError("Power Apps artifact tables must contain objects")
        logical = _identifier(table.get("logical_name"), "Dataverse table logical_name")
        base = f"entities/{logical}"
        component_paths.add(base)
        root_components.append({"type": "Entity", "schema_name": logical, "id": str(_component_id(tenant, base))})
        attributes: list[object] = []
        for field in cast(list[object], table.get("columns", [])):
            if not isinstance(field, Mapping):
                raise PowerPlatformPackageError("Dataverse table columns must contain objects")
            field_name = _identifier(field.get("logical_name"), f"{logical}.column.logical_name")
            attributes.append(
                {
                    "LogicalName": field_name,
                    "DisplayName": field.get("display_name", field_name),
                    "AttributeType": field.get("type", "String"),
                    "RequiredLevel": "Required" if field.get("required") is True else "None",
                }
            )
            _add_file(
                files,
                f"{base}/attributes/{field_name}.yml",
                _yaml({"Attribute": attributes[-1]}),
            )
        _add_file(
            files,
            f"{base}/entity.yml",
            _yaml(
                {
                    "Entity": {
                        "SchemaName": logical,
                        "LogicalName": logical,
                        "DisplayName": table.get("display_name", logical),
                        "Attributes": attributes,
                    }
                }
            ),
        )
    if canvas is not None and not isinstance(canvas, Mapping):
        raise PowerPlatformPackageError("Power Apps artifact canvas_app must be an object")


def _emit_flow_artifact(
    artifact: Mapping[str, object],
    files: dict[str, tuple[str, str]],
    component_paths: set[str],
    root_components: list[dict[str, object]],
    tenant: str,
) -> None:
    flow_id = _identifier(artifact.get("workflow_id"), "workflow_id")
    name = _text(artifact.get("workflow_name", flow_id), "workflow_name", MAX_TEXT_LENGTH)
    payload = artifact.get("power_automate")
    if payload is None and ("trigger" in artifact or "steps" in artifact):
        raise PowerPlatformPackageError(
            "Power Automate flow artifact must nest trigger and actions under power_automate; "
            "the flat trigger/steps shape is not supported"
        )
    if not isinstance(payload, Mapping):
        raise PowerPlatformPackageError("Power Automate flow artifact requires a power_automate object")
    trigger = payload.get("trigger")
    if not isinstance(trigger, Mapping):
        raise PowerPlatformPackageError("Power Automate flow artifact requires a power_automate.trigger object")
    trigger_name = _text(trigger.get("name"), "power_automate.trigger.name", MAX_TEXT_LENGTH)
    trigger_type = _identifier(trigger.get("type"), "power_automate.trigger.type")
    steps = _flow_actions(payload.get("actions"))
    declared = artifact.get("requires_approval")
    if declared is not None and not isinstance(declared, bool):
        raise PowerPlatformPackageError("Power Automate flow artifact requires_approval must be boolean")
    approval_required = bool(declared) or any(step["ApprovalRequired"] is True for step in steps)
    base = f"modernflows/{flow_id}"
    component_paths.add(base)
    component_id = _component_id(tenant, base)
    root_components.append({"type": "ModernFlow", "schema_name": flow_id, "id": str(component_id)})
    metadata = {
        "ModernFlow": {
            "Name": name,
            "UniqueName": flow_id,
            "ComponentId": str(component_id),
            "Trigger": {"Type": trigger_type, "Name": trigger_name},
            "Steps": steps,
            "ApprovalRequired": approval_required,
        }
    }
    _add_file(files, f"{base}/flow.yml", _yaml(metadata))


def _flow_actions(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list) or not 1 <= len(value) <= MAX_FLOW_ACTIONS:
        raise PowerPlatformPackageError(
            f"Power Automate flow artifact requires 1-{MAX_FLOW_ACTIONS} power_automate.actions"
        )
    result: list[dict[str, object]] = []
    seen: set[str] = set()
    for raw in value:
        if not isinstance(raw, Mapping):
            raise PowerPlatformPackageError("power_automate.actions must contain objects")
        action_id = _identifier(raw.get("id"), "power_automate.action.id")
        if action_id in seen:
            raise PowerPlatformPackageError(f"duplicate power_automate.action id: {action_id}")
        seen.add(action_id)
        name = _text(raw.get("name"), "power_automate.action.name", MAX_TEXT_LENGTH)
        kind = _text(raw.get("kind"), "power_automate.action.kind", MAX_TEXT_LENGTH)
        action_type = _text(raw.get("type"), "power_automate.action.type", MAX_TEXT_LENGTH)
        method = _text(raw.get("method"), "power_automate.action.method", MAX_TEXT_LENGTH)
        approval_required = raw.get("approval_required")
        if not isinstance(approval_required, bool):
            raise PowerPlatformPackageError("power_automate.action approval_required must be boolean")
        raw_tool_id = raw.get("tool_id")
        tool_id = None if raw_tool_id is None else _identifier(raw_tool_id, "power_automate.action.tool_id")
        result.append(
            {
                "UniqueName": action_id,
                "Name": name,
                "Kind": kind,
                "Type": action_type,
                "Method": method,
                "ToolId": tool_id,
                "ApprovalRequired": approval_required,
            }
        )
    return result


def _emit_connector_artifact(
    artifact: Mapping[str, object],
    files: dict[str, tuple[str, str]],
    component_paths: set[str],
    root_components: list[dict[str, object]],
    tenant: str,
) -> None:
    connector_id = _identifier(artifact.get("connector_id"), "connector_id")
    base = f"connectors/{connector_id}"
    component_paths.add(base)
    component_id = _component_id(tenant, base)
    root_components.append({"type": "Connector", "schema_name": connector_id, "id": str(component_id)})
    source = {
        "Connector": {
            "Id": connector_id,
            "ComponentId": str(component_id),
            "DisplayName": artifact.get("display_name", connector_id),
            "Host": artifact.get("host", ""),
            "BasePath": artifact.get("base_path", ""),
            "Actions": artifact.get("actions", []),
            "CredentialsIncluded": False,
        }
    }
    _add_file(files, f"{base}/connector.yml", _yaml(source))


def _validate_input_artifacts(value: Sequence[Mapping[str, object]], tenant: str) -> list[dict[str, object]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or len(value) > MAX_INPUT_ARTIFACTS:
        raise PowerPlatformPackageError(f"artifacts must contain at most {MAX_INPUT_ARTIFACTS} items")
    result: list[dict[str, object]] = []
    for artifact in value:
        if not isinstance(artifact, Mapping):
            raise PowerPlatformPackageError("artifacts must contain objects")
        copied = _validate_value(dict(artifact), tenant, "artifact")
        if not isinstance(copied, dict):
            raise PowerPlatformPackageError("artifact must be a JSON object")
        if copied.get("credentials_included") is True:
            raise PowerPlatformPackageError("artifacts containing credentials are not accepted")
        if copied.get("execution_started") is True or copied.get("deployment_started") is True:
            raise PowerPlatformPackageError("artifacts must not report execution or deployment started")
        serialized = _canonical_json_bytes(copied)
        if len(serialized) > MAX_INPUT_ARTIFACT_BYTES:
            raise PowerPlatformPackageError("artifact exceeds the bounded input size")
        result.append(copied)
    return result


def _validate_value(value: object, tenant: str, field: str) -> object:
    if isinstance(value, Mapping):
        result: dict[str, object] = {}
        for raw_key, raw_value in value.items():
            if not isinstance(raw_key, str) or not raw_key or _CONTROL.search(raw_key):
                raise PowerPlatformPackageError(f"{field} contains an unsafe key")
            if raw_key.casefold() in {"client_id", "tenant_id"}:
                if raw_value is not None and (not isinstance(raw_value, str) or raw_value != tenant):
                    raise PowerPlatformPackageError("artifact is outside the requested tenant")
            if _SECRET_KEY.search(raw_key):
                if raw_key.casefold() == "credentials_included" and isinstance(raw_value, bool):
                    result[raw_key] = raw_value
                    continue
                if raw_value not in (None, "", False, [], {}):
                    raise PowerPlatformPackageError(f"{field}.{raw_key} contains secret-like material")
            result[raw_key] = _validate_value(raw_value, tenant, f"{field}.{raw_key}")
        return result
    if isinstance(value, list):
        if len(value) > MAX_PACKAGE_FILES * 8:
            raise PowerPlatformPackageError(f"{field} contains too many items")
        return [_validate_value(item, tenant, f"{field}[]") for item in value]
    if isinstance(value, str):
        if _CONTROL.search(value) or len(value) > MAX_TEXT_LENGTH * 16:
            raise PowerPlatformPackageError(f"{field} contains unsafe or oversized text")
        if re.search(r"(?:Bearer\s+|-----BEGIN [A-Z ]+-----|(?:api[_-]?key|client[_-]?secret)\s*=)", value, re.I):
            raise PowerPlatformPackageError(f"{field} contains secret-like material")
        return value
    if value is None or isinstance(value, (bool, int, float)):
        if isinstance(value, float) and (value != value or value in {float("inf"), float("-inf")}):
            raise PowerPlatformPackageError(f"{field} contains a non-finite number")
        return value
    raise PowerPlatformPackageError(f"{field} contains an unsupported value")


def _add_file(files: dict[str, tuple[str, str]], path: str, content: str, media_type: str | None = None) -> None:
    safe_path = _safe_relative_path(path, "generated file path")
    encoded = content.encode("utf-8")
    if len(encoded) > MAX_PACKAGE_FILE_BYTES:
        raise PowerPlatformPackageError(f"generated file {safe_path} exceeds the bounded size limit")
    if safe_path in files and files[safe_path][1] != content:
        raise PowerPlatformPackageError(f"generated file path collision: {safe_path}")
    files[safe_path] = (media_type or ("application/json" if safe_path.endswith(".json") else "text/yaml"), content)


def _yaml(value: object, indent: int = 0) -> str:
    """Serialize the small JSON-shaped subset used by solution source files."""

    lines: list[str] = []
    prefix = " " * indent
    if isinstance(value, Mapping):
        if not value:
            return f"{prefix}{{}}\n"
        for key in sorted(value, key=str):
            rendered_key = _yaml_scalar(str(key))
            if value[key] is None:
                lines.append(f"{prefix}{rendered_key}:")
            elif isinstance(value[key], (Mapping, list)):
                if not value[key]:
                    empty = "{}" if isinstance(value[key], Mapping) else "[]"
                    lines.append(f"{prefix}{rendered_key}: {empty}")
                else:
                    lines.append(f"{prefix}{rendered_key}:")
                    lines.extend(_yaml(value[key], indent + 2).splitlines())
            else:
                lines.append(f"{prefix}{rendered_key}: {_yaml_scalar(value[key])}")
    elif isinstance(value, list):
        if not value:
            return f"{prefix}[]\n"
        for item in value:
            if isinstance(item, Mapping):
                if not item:
                    lines.append(f"{prefix}- {{}}")
                    continue
                first = True
                for key in sorted(item, key=str):
                    rendered_key = _yaml_scalar(str(key))
                    item_value = item[key]
                    marker = f"{prefix}- " if first else f"{prefix}  "
                    first = False
                    if isinstance(item_value, (Mapping, list)):
                        if not item_value:
                            empty = "{}" if isinstance(item_value, Mapping) else "[]"
                            lines.append(f"{marker}{rendered_key}: {empty}")
                        else:
                            lines.append(f"{marker}{rendered_key}:")
                            lines.extend(_yaml(item_value, indent + 4).splitlines())
                    elif item_value is None:
                        lines.append(f"{marker}{rendered_key}:")
                    else:
                        lines.append(f"{marker}{rendered_key}: {_yaml_scalar(item_value)}")
            elif isinstance(item, list):
                lines.append(f"{prefix}-")
                lines.extend(_yaml(item, indent + 2).splitlines())
            else:
                lines.append(f"{prefix}- {_yaml_scalar(item)}")
    else:
        lines.append(f"{prefix}{_yaml_scalar(value)}")
    return "\n".join(lines) + "\n"


def _yaml_scalar(value: object) -> str:
    if value is None:
        return ""
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    # ``@`` is a YAML indicator and cannot begin an unquoted plain scalar;
    # publisher manifests use keys such as ``@description`` and
    # ``@languagecode``. Keep ordinary protocol/path values readable while
    # quoting indicator-leading values for valid YAML source.
    numeric_string = re.fullmatch(r"[+-]?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?", text) is not None
    if (
        re.fullmatch(r"[A-Za-z0-9_./:+-]+", text)
        and text.casefold() not in {"null", "true", "false", "yes", "no", "on", "off", "y", "n", "~"}
        and not numeric_string
    ):
        return text
    return json.dumps(text, ensure_ascii=True)


def _canonical_json_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise PowerPlatformPackageError("package values must be JSON-compatible") from exc


def _digest(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _pack_zip_path(output: str, solution: str) -> str:
    """Return a deterministic PAC output path for both POSIX and Windows paths."""

    if "\\" in output or PureWindowsPath(output).drive:
        return str(PureWindowsPath(output) / f"{solution}.zip")
    return str(Path(output) / f"{solution}.zip")


def _component_id(tenant: str, name: str) -> uuid.UUID:
    return uuid.uuid5(_PACKAGE_NAMESPACE, f"{tenant}:{name}")


def _publisher_identifier(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", value.casefold()).strip("_")
    return _identifier(normalized or "waitpublisher", "publisher_unique_name")


def _publisher_name(value: object) -> str:
    publisher = _text(value, "publisher_name", 100)
    if not re.fullmatch(r"[A-Za-z0-9_]+", publisher):
        raise PowerPlatformPackageError("publisher_name may contain only letters, numbers, and underscores")
    return publisher


def _publisher_prefix(value: object) -> str:
    prefix = _text(value, "publisher_prefix", 8)
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9]{1,7}", prefix):
        raise PowerPlatformPackageError("publisher_prefix must be 2-8 alphanumeric characters and start with a letter")
    return prefix


def _identifier(value: object, field: str) -> str:
    normalized = _text(value, field, 64).casefold()
    if not _IDENTIFIER.fullmatch(normalized):
        raise PowerPlatformPackageError(f"{field} must be a lowercase identifier")
    return normalized


def _text(value: object, field: str, maximum: int) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value.strip()) > maximum
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise PowerPlatformPackageError(f"{field} must be non-empty text of at most {maximum} characters")
    return value.strip()


def _safe_output_directory(value: object) -> str:
    text = _text(value, "output_directory", MAX_PATH_LENGTH)
    path = Path(text)
    windows_path = PureWindowsPath(text)
    if any(part == ".." for part in (*path.parts, *windows_path.parts)):
        raise PowerPlatformPackageError("output_directory may not contain traversal")
    return text


def _safe_relative_path(value: object, field: str) -> str:
    text = _text(value, field, MAX_PATH_LENGTH)
    path = Path(text)
    if path.is_absolute() or "\\" in text or any(part in {"", ".", ".."} for part in path.parts):
        raise PowerPlatformPackageError(f"{field} must be a safe relative path")
    return "/".join(path.parts)


def _safe_workspace(value: str | Path) -> Path:
    raw = Path(value).expanduser()
    if raw.exists() and raw.is_symlink():
        raise PowerPlatformPackageError("WAIT_POWER_PLATFORM_WORKSPACE may not be a symlink")
    workspace = raw.resolve()
    if not workspace.is_dir():
        raise PowerPlatformPackageError("WAIT_POWER_PLATFORM_WORKSPACE must already exist")
    return workspace


def _confined_path(raw: str, workspace: Path, field: str) -> Path:
    candidate = Path(raw).expanduser()
    resolved = candidate.resolve(strict=False)
    if resolved == workspace or workspace not in resolved.parents:
        raise PowerPlatformPackageError(f"{field} must be inside WAIT_POWER_PLATFORM_WORKSPACE")
    return resolved


def _contains_secret_like_source(content: str) -> bool:
    if _SECRET_SOURCE.search(content):
        return True
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        return False
    return _contains_secret_like_value(parsed)


def _contains_secret_like_value(value: object) -> bool:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if isinstance(key, str) and _SECRET_KEY.search(key) and item not in (None, "", False, [], {}):
                return True
            if _contains_secret_like_value(item):
                return True
    elif isinstance(value, list):
        return any(_contains_secret_like_value(item) for item in value)
    return False


def _reject_symlink_components(path: Path, workspace: Path) -> None:
    current = path
    components: list[Path] = []
    while current != workspace and workspace in current.parents:
        components.append(current)
        current = current.parent
    for component in components:
        if component.exists() and component.is_symlink():
            raise PowerPlatformPackageError(f"materialization refuses symlink: {component.name}")


def _materialization_result(status: str, message: str, digest: str | None = None) -> dict[str, object]:
    result: dict[str, object] = {
        "format": "wait-local-agent.power-platform.materialization-result",
        "format_version": 1,
        "status": status,
        "message": message,
        "materialization_started": False,
        "execution_started": False,
        "deployment_started": False,
    }
    if digest is not None:
        result["package_digest"] = digest
    return result


__all__ = [
    "MAX_PACKAGE_BYTES",
    "MAX_PACKAGE_FILES",
    "PAC_YAML_MINIMUM_VERSION",
    "PACKAGE_FORMAT",
    "PowerPlatformPackageError",
    "build_deployable_blueprint_package",
    "build_power_platform_package",
    "materialize_deployable_blueprint_package",
    "materialize_power_platform_package",
    "package_validation_result",
    "validate_deployable_blueprint_package",
    "validate_power_platform_package",
]
