"""Deterministic, local-only Power Platform XML source packages.

The package in this module is a source handoff, not a solution ZIP and not a
provider operation.  It deliberately uses the XML solution layout that
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
from xml.sax.saxutils import (
    escape as _xml_escape,  # nosec B406 - escape only encodes emitted XML; it never parses input
)

from wait_local_agent.config import Settings

PACKAGE_FORMAT = "wait-local-agent.power-platform.deployable-source"
PACKAGE_VERSION = 1
PAC_YAML_MINIMUM_VERSION = "2.4.1"
PAC_XML_MINIMUM_VERSION = PAC_YAML_MINIMUM_VERSION
MAX_PACKAGE_FILES = 96
MAX_PACKAGE_FILE_BYTES = 64_000
MAX_PACKAGE_BYTES = 512_000
MAX_INPUT_ARTIFACTS = 32
MAX_FLOW_ACTIONS = 32
MAX_INPUT_ARTIFACT_BYTES = 256_000
MAX_PATH_LENGTH = 240
MAX_TEXT_LENGTH = 240
DEFAULT_STRING_MAX_LENGTH = 100
MAX_STRING_MAX_LENGTH = 4_000
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
    """Build a deterministic Power Platform XML source package.

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
    root_components: list[dict[str, object]] = []
    entities: list[dict[str, object]] = []
    relationships: list[dict[str, object]] = []
    unsupported: list[dict[str, object]] = []
    design_only: list[dict[str, object]] = []
    emitted_component_classes = {"publisher", "solution_manifest"}
    import_complete_component_classes = {"publisher", "solution_manifest"}
    artifact_component_classes: set[str] = set()

    for artifact_index, artifact in enumerate(normalized_artifacts, start=1):
        artifact_format = str(artifact.get("format", ""))
        if artifact_format == "wait-local-agent.power-apps-artifact":
            _emit_power_apps_artifact(
                artifact,
                files,
                root_components,
                unsupported,
                tenant,
                entities,
                relationships,
                emitted_component_classes,
                import_complete_component_classes,
                artifact_component_classes,
                design_only,
                prefix,
            )
        elif artifact_format == "wait-local-agent.power-automate-flow-plan":
            _emit_flow_artifact(
                artifact,
                files,
                tenant,
                emitted_component_classes,
                artifact_component_classes,
                design_only,
            )
        elif artifact_format == "wait-local-agent.power-platform.custom-connector":
            _emit_connector_artifact(
                artifact,
                files,
                tenant,
                emitted_component_classes,
                artifact_component_classes,
                design_only,
            )
        else:
            artifact_component_classes.add("unsupported")
            unsupported.append(
                {
                    "id": str(_component_id(tenant, f"unsupported:{artifact_index}:{artifact_format}")),
                    "format": artifact_format or "unknown",
                    "reason": "artifact format has no supported XML source mapping",
                }
            )

    root_components = sorted(root_components, key=lambda item: (str(item.get("type")), str(item.get("schema_name"))))
    _add_file(
        files,
        "Other/Solution.xml",
        _solution_xml(solution, publisher, publisher_unique_name, prefix, root_components),
    )
    _add_file(files, "Other/Customizations.xml", _customizations_xml(entities, relationships))
    _add_file(files, "Other/Relationships.xml", _relationships_xml())

    if unsupported:
        unsupported.sort(key=lambda item: str(item["id"]))
        _add_file(files, "unsupported/components.json", _canonical_json_bytes({"components": unsupported}).decode())
    if design_only:
        design_only.sort(key=lambda item: str(item["id"]))
        _add_file(files, "design_only/components.json", _canonical_json_bytes({"components": design_only}).decode())

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
        "deployable": bool(artifact_component_classes & import_complete_component_classes)
        if normalized_artifacts
        else bool(import_complete_component_classes),
        "package_status": (
            "deployable_source"
            if emitted_component_classes <= import_complete_component_classes
            else "partial_source"
        ),
        "credentials_included": False,
        "unsupported_components": unsupported,
        "design_only_components": design_only,
        "pac": {
            "minimum_cli_version": PAC_XML_MINIMUM_VERSION,
            "format": "xml_solution",
            "commands": [
                [
                    "pac",
                    "solution",
                    "pack",
                    "--folder",
                    output,
                    "--zipfile",
                    _pack_zip_path(output, solution),
                    "--packagetype",
                    "Unmanaged",
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
    if package.get("package_status") not in {
        "deployable_source",
        "partial_source",
    }:
        raise PowerPlatformPackageError(
            "package_status must be deployable_source or partial_source"
        )
    if package.get("deployable") is not True:
        raise PowerPlatformPackageError(
            "package contains no component that will import, so it cannot be deployed; "
            "it contains only design-only or unsupported components"
        )
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
    design_only_components = package.get("design_only_components")
    if not isinstance(design_only_components, list) or len(design_only_components) > MAX_INPUT_ARTIFACTS:
        raise PowerPlatformPackageError("package.design_only_components is outside the bounded limit")
    _validate_value(design_only_components, tenant, "package.design_only_components")
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
        if not isinstance(media_type, str) or media_type not in {
            "application/xml",
            "application/json",
            "text/markdown",
        }:
            raise PowerPlatformPackageError(f"package file {path} has an unsupported media type")
        if _contains_secret_like_source(content):
            raise PowerPlatformPackageError(f"package file {path} contains secret-like material")
        digest = raw.get("digest")
        if not isinstance(digest, str) or not _DIGEST.fullmatch(digest) or digest != _digest(encoded):
            raise PowerPlatformPackageError(f"package file digest mismatch: {path}")
        normalized_files.append({"path": path, "media_type": media_type, "digest": digest, "content": content})
    required_paths = {"Other/Solution.xml", "Other/Customizations.xml", "Other/Relationships.xml"}
    if not required_paths.issubset(seen):
        raise PowerPlatformPackageError("package is missing the official XML solution manifest")
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
        or pac.get("minimum_cli_version") != PAC_XML_MINIMUM_VERSION
        or pac.get("format") != "xml_solution"
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
            "--packagetype",
            "Unmanaged",
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
        "message": "Power Platform XML source was materialized locally.",
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
                    "--packagetype",
                    "Unmanaged",
                ]
            ],
            "folder": str(output),
            "zipfile": zipfile,
            "minimum_cli_version": PAC_XML_MINIMUM_VERSION,
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


def _xml_attribute(value: object) -> str:
    return _xml_escape(str(value), {'"': "&quot;", "'": "&apos;"})


def _xml_text(value: object) -> str:
    return _xml_escape(str(value))


def _solution_xml(
    solution: str,
    publisher: str,
    publisher_unique_name: str,
    publisher_prefix: str,
    root_components: list[dict[str, object]],
) -> str:
    lines = [
        '<?xml version="1.0" encoding="utf-8"?>',
        '<ImportExportXml version="9.1.0.643" SolutionPackageVersion="9.1" languagecode="1033" generatedBy="CrmLive" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">',
        "  <SolutionManifest>",
        "    <!-- Unique Name of Cds Solution-->",
        f"    <UniqueName>{_xml_text(solution)}</UniqueName>",
        "    <LocalizedNames>",
        "      <!-- Localized Solution Name in language code -->",
        f'      <LocalizedName description="{_xml_attribute(solution)}" languagecode="1033" />',
        "    </LocalizedNames>",
        "    <Descriptions />",
        # Version and CustomizationOptionValuePrefix are copied from the proven
        # ``wait`` reference and remain unverified for other publisher prefixes.
        "    <Version>1.0</Version>",
        "    <!-- Solution Package Type: Unmanaged(0)/Managed(1)/Both(2)-->",
        "    <Managed>0</Managed>",
        "    <Publisher>",
        "      <!-- Unique Publisher Name of Cds Solution -->",
        f"      <UniqueName>{_xml_text(publisher_unique_name)}</UniqueName>",
        "      <LocalizedNames>",
        "        <!-- Localized Cds Publisher Name in language code-->",
        f'        <LocalizedName description="{_xml_attribute(publisher)}" languagecode="1033" />',
        "      </LocalizedNames>",
        "      <Descriptions>",
        "        <!-- Description of Cds Publisher in language code -->",
        f'        <Description description="{_xml_attribute(publisher)}" languagecode="1033" />',
        "      </Descriptions>",
        '      <EMailAddress xsi:nil="true"></EMailAddress>',
        '      <SupportingWebsiteUrl xsi:nil="true"></SupportingWebsiteUrl>',
        "      <!-- Customization Prefix for the Cds Publisher-->",
        f"      <CustomizationPrefix>{_xml_text(publisher_prefix)}</CustomizationPrefix>",
        "      <!-- Derived Option Value Prefix for the Customization Prefix of Cds Publisher -->",
        "      <CustomizationOptionValuePrefix>89859</CustomizationOptionValuePrefix>",
        "      <Addresses>",
        "        <!-- Address of the Publisher-->",
        "        <Address>",
        "          <AddressNumber>1</AddressNumber>",
        "          <AddressTypeCode>1</AddressTypeCode>",
        '          <City xsi:nil="true"></City>',
        '          <County xsi:nil="true"></County>',
        '          <Country xsi:nil="true"></Country>',
        '          <Fax xsi:nil="true"></Fax>',
        '          <FreightTermsCode xsi:nil="true"></FreightTermsCode>',
        '          <ImportSequenceNumber xsi:nil="true"></ImportSequenceNumber>',
        '          <Latitude xsi:nil="true"></Latitude>',
        '          <Line1 xsi:nil="true"></Line1>',
        '          <Line2 xsi:nil="true"></Line2>',
        '          <Line3 xsi:nil="true"></Line3>',
        '          <Longitude xsi:nil="true"></Longitude>',
        '          <Name xsi:nil="true"></Name>',
        '          <PostalCode xsi:nil="true"></PostalCode>',
        '          <PostOfficeBox xsi:nil="true"></PostOfficeBox>',
        '          <PrimaryContactName xsi:nil="true"></PrimaryContactName>',
        "          <ShippingMethodCode>1</ShippingMethodCode>",
        '          <StateOrProvince xsi:nil="true"></StateOrProvince>',
        '          <Telephone1 xsi:nil="true"></Telephone1>',
        '          <Telephone2 xsi:nil="true"></Telephone2>',
        '          <Telephone3 xsi:nil="true"></Telephone3>',
        '          <TimeZoneRuleVersionNumber xsi:nil="true"></TimeZoneRuleVersionNumber>',
        '          <UPSZone xsi:nil="true"></UPSZone>',
        '          <UTCOffset xsi:nil="true"></UTCOffset>',
        '          <UTCConversionTimeZoneCode xsi:nil="true"></UTCConversionTimeZoneCode>',
        "        </Address>",
        "        <Address>",
        "          <AddressNumber>2</AddressNumber>",
        "          <AddressTypeCode>1</AddressTypeCode>",
        '          <City xsi:nil="true"></City>',
        '          <County xsi:nil="true"></County>',
        '          <Country xsi:nil="true"></Country>',
        '          <Fax xsi:nil="true"></Fax>',
        '          <FreightTermsCode xsi:nil="true"></FreightTermsCode>',
        '          <ImportSequenceNumber xsi:nil="true"></ImportSequenceNumber>',
        '          <Latitude xsi:nil="true"></Latitude>',
        '          <Line1 xsi:nil="true"></Line1>',
        '          <Line2 xsi:nil="true"></Line2>',
        '          <Line3 xsi:nil="true"></Line3>',
        '          <Longitude xsi:nil="true"></Longitude>',
        '          <Name xsi:nil="true"></Name>',
        '          <PostalCode xsi:nil="true"></PostalCode>',
        '          <PostOfficeBox xsi:nil="true"></PostOfficeBox>',
        '          <PrimaryContactName xsi:nil="true"></PrimaryContactName>',
        "          <ShippingMethodCode>1</ShippingMethodCode>",
        '          <StateOrProvince xsi:nil="true"></StateOrProvince>',
        '          <Telephone1 xsi:nil="true"></Telephone1>',
        '          <Telephone2 xsi:nil="true"></Telephone2>',
        '          <Telephone3 xsi:nil="true"></Telephone3>',
        '          <TimeZoneRuleVersionNumber xsi:nil="true"></TimeZoneRuleVersionNumber>',
        '          <UPSZone xsi:nil="true"></UPSZone>',
        '          <UTCOffset xsi:nil="true"></UTCOffset>',
        '          <UTCConversionTimeZoneCode xsi:nil="true"></UTCConversionTimeZoneCode>',
        "        </Address>",
        "      </Addresses>",
        "    </Publisher>",
    ]
    if root_components:
        lines.append("    <RootComponents>")
        for component in root_components:
            lines.append(
                f'      <RootComponent type="{_xml_attribute(component["type"])}" '
                f'schemaName="{_xml_attribute(component["schema_name"])}" behavior="0" />'
            )
        lines.append("    </RootComponents>")
    else:
        lines.append("    <RootComponents />")
    lines.extend(
        [
            "    <MissingDependencies />",
            "  </SolutionManifest>",
            "</ImportExportXml>",
        ]
    )
    return "\n".join(lines) + "\n"


def _customizations_xml(entities: list[dict[str, object]], relationships: list[dict[str, object]]) -> str:
    lines = [
        '\ufeff<?xml version="1.0" encoding="utf-8"?>',
        '<ImportExportXml xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">',
    ]
    if entities:
        lines.append("  <Entities>")
        for entity in sorted(entities, key=lambda item: str(item["logical_name"])):
            lines.extend(_xml_entity(entity))
        lines.append("  </Entities>")
    else:
        lines.append("  <Entities />")
    lines.extend(
        [
            "  <Roles />",
            "  <Workflows />",
            "  <FieldSecurityProfiles />",
            "  <Templates />",
            "  <EntityMaps />",
            *_xml_relationships(relationships),
            "  <OrganizationSettings />",
            "  <optionsets />",
            "  <CustomControls />",
            "  <SolutionPluginAssemblies />",
            "  <EntityDataProviders />",
            "  <Languages>",
            "    <Language>1033</Language>",
            "  </Languages>",
            "</ImportExportXml>",
        ]
    )
    return "\n".join(lines) + "\n"


def _xml_entity(entity: dict[str, object]) -> list[str]:
    logical = cast(str, entity["logical_name"])
    display_name = cast(str, entity["display_name"])
    attributes = sorted(
        cast(list[dict[str, object]], entity["attributes"]),
        key=lambda item: str(item["logical_name"]),
    )
    primary = cast(str, entity["primary_name_column"])
    lines = [
        "    <Entity>",
        (
            f'      <Name LocalizedName="{_xml_attribute(display_name)}" '
            f'OriginalName="{_xml_attribute(display_name)}">{_xml_text(logical)}</Name>'
        ),
        "      <EntityInfo>",
        f'        <entity Name="{_xml_attribute(logical)}">',
        (
            f'          <LocalizedNames><LocalizedName description="{_xml_attribute(display_name)}" '
            'languagecode="1033" /></LocalizedNames>'
        ),
        (
            f'          <LocalizedCollectionNames><LocalizedCollectionName '
            f'description="{_xml_attribute(display_name + "s")}" languagecode="1033" />'
            "</LocalizedCollectionNames>"
        ),
        (
            f'          <Descriptions><Description description="{_xml_attribute(display_name + " record")}" '
            'languagecode="1033" /></Descriptions>'
        ),
        "          <attributes>",
    ]
    for attribute in attributes:
        lines.extend(_xml_attribute_block(attribute, str(attribute["logical_name"]) == primary))
    lines.extend(
        [
            "          </attributes>",
            f"          <EntitySetName>{_xml_text(logical + 's')}</EntitySetName>",
            "          <IsCustomEntity>1</IsCustomEntity><OwnershipTypeMask>UserOwned</OwnershipTypeMask>",
            f"          <PrimaryNameAttribute>{_xml_text(primary)}</PrimaryNameAttribute>",
            "          <IntroducedVersion>1.0</IntroducedVersion>",
            "        </entity>",
            "      </EntityInfo>",
            "    </Entity>",
        ]
    )
    return lines


def _xml_attribute_block(attribute: dict[str, object], primary: bool) -> list[str]:
    logical = cast(str, attribute["logical_name"])
    display_name = cast(str, attribute["display_name"])
    field_type = cast(str, attribute["type"])
    if field_type == "lookup":
        return [
            f'            <attribute PhysicalName="{_xml_attribute(logical)}">',
            "              <Type>lookup</Type>",
            f"              <Name>{_xml_text(logical)}</Name><LogicalName>{_xml_text(logical)}</LogicalName>",
            "              <RequiredLevel>none</RequiredLevel>",
            "              <DisplayMask>ValidForAdvancedFind|ValidForForm|ValidForGrid</DisplayMask>",
            (
                "              <ImeMode>auto</ImeMode><ValidForCreateApi>1</ValidForCreateApi>"
                "<ValidForReadApi>1</ValidForReadApi>"
            ),
            (
                "              <ValidForUpdateApi>1</ValidForUpdateApi><IsCustomField>1</IsCustomField>"
                "<IsAuditEnabled>0</IsAuditEnabled>"
            ),
            (
                "              <IsSecured>0</IsSecured><IntroducedVersion>1.0</IntroducedVersion>"
                "<IsCustomizable>1</IsCustomizable>"
            ),
            "              <IsRenameable>1</IsRenameable><LookupStyle>single</LookupStyle><LookupTypes />",
            (
                f'              <displaynames><displayname description="{_xml_attribute(display_name)}" '
                'languagecode="1033" /></displaynames>'
            ),
            "            </attribute>",
        ]
    display_mask = (
        "PrimaryName|ValidForAdvancedFind|ValidForForm|ValidForGrid"
        if primary
        else "ValidForAdvancedFind|ValidForForm|ValidForGrid"
    )
    # DateOnly is verified against a real Dataverse round-trip; DateTime remains
    # unmapped because its Format and Behavior values have not been verified.
    if field_type == "dateonly":
        type_line = "              <Type>datetime</Type>"
        format_line = "              <IsRenameable>1</IsRenameable><Format>date</Format><Behavior>1</Behavior>"
    else:
        max_length = attribute["max_length"]
        type_line = "              <Type>nvarchar</Type>"
        format_line = (
            f"              <IsRenameable>1</IsRenameable><MaxLength>{max_length}</MaxLength>"
            f"<Length>{max_length}</Length><Format>text</Format>"
        )
    return [
        f'            <attribute PhysicalName="{_xml_attribute(logical)}">',
        type_line,
        f"              <Name>{_xml_text(logical)}</Name><LogicalName>{_xml_text(logical)}</LogicalName>",
        "              <RequiredLevel>none</RequiredLevel>",
        f"              <DisplayMask>{display_mask}</DisplayMask>",
        (
            "              <ImeMode>auto</ImeMode><ValidForCreateApi>1</ValidForCreateApi>"
            "<ValidForReadApi>1</ValidForReadApi>"
        ),
        (
            "              <ValidForUpdateApi>1</ValidForUpdateApi><IsCustomField>1</IsCustomField>"
            "<IsAuditEnabled>0</IsAuditEnabled>"
        ),
        (
            "              <IsSecured>0</IsSecured><IntroducedVersion>1.0</IntroducedVersion>"
            "<IsCustomizable>1</IsCustomizable>"
        ),
        format_line,
        (
            f'              <displaynames><displayname description="{_xml_attribute(display_name)}" '
            'languagecode="1033" /></displaynames>'
        ),
        "            </attribute>",
    ]


def _xml_relationships(relationships: list[dict[str, object]]) -> list[str]:
    if not relationships:
        return ["  <EntityRelationships />"]
    lines = ["  <EntityRelationships>"]
    for relationship in sorted(relationships, key=lambda item: str(item["name"])):
        name = cast(str, relationship["name"])
        referencing = cast(str, relationship["referencing_entity"])
        referenced = cast(str, relationship["referenced_entity"])
        lookup = cast(str, relationship["referencing_attribute"])
        description = cast(str, relationship["description"])
        lines.extend(
            [
                f'    <EntityRelationship Name="{_xml_attribute(name)}">',
                "      <EntityRelationshipType>OneToMany</EntityRelationshipType>",
                "      <IsCustomizable>1</IsCustomizable>",
                f"      <ReferencingEntityName>{_xml_text(referencing)}</ReferencingEntityName>",
                f"      <ReferencedEntityName>{_xml_text(referenced)}</ReferencedEntityName>",
                "      <CascadeAssign>NoCascade</CascadeAssign><CascadeDelete>RemoveLink</CascadeDelete>",
                "      <CascadeReparent>NoCascade</CascadeReparent><CascadeShare>NoCascade</CascadeShare>",
                "      <CascadeUnshare>NoCascade</CascadeUnshare>",
                "      <IsValidForAdvancedFind>1</IsValidForAdvancedFind>",
                f"      <ReferencingAttributeName>{_xml_text(lookup)}</ReferencingAttributeName>",
                "      <EntityRelationshipRoles>",
                "        <EntityRelationshipRole>",
                "          <NavPaneDisplayOption>UseCollectionName</NavPaneDisplayOption>",
                "          <NavPaneAreaDisplayOption>Details</NavPaneAreaDisplayOption>",
                "          <NavPaneAreaOrder>10000</NavPaneAreaOrder>",
                f"          <NavigationPropertyName>{_xml_text(name)}</NavigationPropertyName>",
                "          <RelationshipRoleType>1</RelationshipRoleType>",
                "        </EntityRelationshipRole>",
                "      </EntityRelationshipRoles>",
                (
                    f"      <RelationshipDescription><Descriptions><Description "
                    f'description="{_xml_attribute(description)}" languagecode="1033" /></Descriptions>'
                    "</RelationshipDescription>"
                ),
                "    </EntityRelationship>",
            ]
        )
    lines.append("  </EntityRelationships>")
    return lines


def _relationships_xml() -> str:
    return (
        '\ufeff<?xml version="1.0" encoding="utf-8"?>\n'
        '<EntityRelationships xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" />\n'
    )


def _remove_lookup_attribute(entities: list[dict[str, object]], entity_name: str, attribute_name: str) -> None:
    for entity in entities:
        if entity["logical_name"] == entity_name:
            entity["attributes"] = [
                field
                for field in cast(list[dict[str, object]], entity["attributes"])
                if field["logical_name"] != attribute_name
            ]


def _emit_power_apps_artifact(
    artifact: Mapping[str, object],
    files: dict[str, tuple[str, str]],
    root_components: list[dict[str, object]],
    unsupported: list[dict[str, object]],
    tenant: str,
    entities: list[dict[str, object]],
    relationships: list[dict[str, object]],
    emitted_component_classes: set[str],
    import_complete_component_classes: set[str],
    artifact_component_classes: set[str],
    design_only: list[dict[str, object]],
    publisher_prefix: str,
) -> None:
    dataverse = artifact.get("dataverse")
    if not isinstance(dataverse, Mapping) or not isinstance(dataverse.get("tables"), list):
        raise PowerPlatformPackageError("Power Apps artifact dataverse.tables is required")
    canvas = artifact.get("canvas_app")
    if canvas is not None and not isinstance(canvas, Mapping):
        raise PowerPlatformPackageError("Power Apps artifact canvas_app must be an object")
    if canvas is not None:
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
    tables = cast(list[object], dataverse["tables"])
    table_names: set[str] = set()
    table_display_names: dict[str, str] = {}
    for raw_table in tables:
        if not isinstance(raw_table, Mapping):
            raise PowerPlatformPackageError("Power Apps artifact tables must contain objects")
        table_name = _identifier(raw_table.get("logical_name"), "Dataverse table logical_name")
        table_names.add(table_name)
        table_display_names[table_name] = str(raw_table.get("display_name", table_name))
    raw_relationships = dataverse.get("relationships", artifact.get("relationships"))
    if raw_relationships is not None and not isinstance(raw_relationships, list):
        raise PowerPlatformPackageError("Power Apps artifact relationships must contain objects")
    explicit_relationships = raw_relationships is not None
    relationship_candidates: list[dict[str, object]] = []
    lookup_columns: dict[tuple[str, str], dict[str, object]] = {}
    emitted_artifact_entity_names: set[str] = set()
    for table in tables:
        if not isinstance(table, Mapping):
            raise PowerPlatformPackageError("Power Apps artifact tables must contain objects")
        logical = _identifier(table.get("logical_name"), "Dataverse table logical_name")
        emitted_component_classes.add("entity")
        expected_prefix = f"{publisher_prefix}_"
        if not logical.startswith(expected_prefix):
            design_only.append(
                {
                    "id": str(_component_id(tenant, f"entities/{logical}")),
                    "path": f"entities/{logical}",
                    "format": str(artifact.get("format")),
                    "reason": (
                        f"entity logical_name {logical} does not use the expected publisher prefix "
                        f"{expected_prefix}; the name was not rewritten"
                    ),
                }
            )
            continue
        attributes: list[dict[str, object]] = []
        unmapped_fields: list[str] = []
        unmapped_types: dict[str, str] = {}
        marked_primary: list[str] = []
        column_names: set[str] = set()
        table_primary = table.get("primary_name_column")
        declared_primary = (
            _identifier(table_primary, f"{logical}.primary_name_column")
            if table_primary is not None
            else None
        )
        for field in cast(list[object], table.get("columns", [])):
            if not isinstance(field, Mapping):
                raise PowerPlatformPackageError("Dataverse table columns must contain objects")
            field_name = _identifier(field.get("logical_name"), f"{logical}.column.logical_name")
            field_primary = field.get("primary")
            if field_primary is not None and not isinstance(field_primary, bool):
                raise PowerPlatformPackageError(f"{logical}.{field_name}.primary must be boolean")
            if field_primary is True:
                marked_primary.append(field_name)
            column_names.add(field_name)
            field_type = str(field.get("type", "String"))
            normalized_field_type = field_type.casefold()
            if normalized_field_type == "lookup":
                target_value = field.get("target_entity")
                if target_value is None:
                    design_only.append(
                        {
                            "id": str(_component_id(tenant, f"entities/{logical}/relationships/{field_name}")),
                            "path": f"entities/{logical}",
                            "format": str(artifact.get("format")),
                            "reason": (
                                f"relationship for lookup column {field_name} was omitted because "
                                "target_entity is missing"
                            ),
                        }
                    )
                    continue
                target = _identifier(target_value, f"{logical}.{field_name}.target_entity")
                lookup_columns[(logical, field_name)] = {"target_entity": target}
                if target not in table_names:
                    design_only.append(
                        {
                            "id": str(_component_id(tenant, f"entities/{logical}/relationships/{field_name}")),
                            "path": f"entities/{logical}",
                            "format": str(artifact.get("format")),
                            "reason": (
                                f"relationship for lookup column {field_name} was omitted because "
                                f"target entity {target} is absent from the package"
                            ),
                        }
                    )
                    continue
                lookup_display_name = _text(
                    field.get("display_name", field_name),
                    f"{logical}.{field_name}.display_name",
                    MAX_TEXT_LENGTH,
                )
                attributes.append(
                    {
                        "logical_name": field_name,
                        "display_name": lookup_display_name,
                        "required": field.get("required") is True,
                        "type": "lookup",
                        "target_entity": target,
                    }
                )
                if not explicit_relationships:
                    relationship_candidates.append(
                        {
                            "referencing_entity": logical,
                            "referenced_entity": target,
                            "referencing_attribute": field_name,
                            "description": (
                                f"{table_display_names.get(target, target)} to "
                                f"{logical.removeprefix(f'{publisher_prefix}_')}"
                            ),
                        }
                    )
                continue
            if normalized_field_type not in {"string", "dateonly"}:
                unmapped_fields.append(field_name)
                unmapped_types[field_name] = field_type
                design_only.append(
                    {
                        "id": str(_component_id(tenant, f"entities/{logical}/attributes/{field_name}")),
                        "path": f"entities/{logical}",
                        "format": str(artifact.get("format")),
                        "reason": (
                            f"attribute {field_name} has unmapped WAIT type {field_type}; "
                            "the field was omitted rather than guessing a Dataverse type"
                        ),
                    }
                )
                continue
            attribute = {
                "logical_name": field_name,
                "display_name": _text(
                    field.get("display_name", field_name),
                    f"{logical}.{field_name}.display_name",
                    MAX_TEXT_LENGTH,
                ),
                "type": normalized_field_type,
                "required": field.get("required") is True,
            }
            if normalized_field_type == "string":
                max_length = field.get("max_length", DEFAULT_STRING_MAX_LENGTH)
                if (
                    not isinstance(max_length, int)
                    or isinstance(max_length, bool)
                    or not 1 <= max_length <= MAX_STRING_MAX_LENGTH
                ):
                    raise PowerPlatformPackageError(
                        f"{logical}.{field_name}.max_length must be an integer from 1-{MAX_STRING_MAX_LENGTH}"
                    )
                attribute["max_length"] = max_length
            attributes.append(attribute)
        if declared_primary is None:
            if len(marked_primary) == 1:
                declared_primary = marked_primary[0]
            elif len(marked_primary) > 1:
                design_only.append(
                    {
                        "id": str(_component_id(tenant, f"entities/{logical}")),
                        "path": f"entities/{logical}",
                        "format": str(artifact.get("format")),
                        "reason": (
                            "entity declares multiple primary columns; exactly one primary name "
                            "column is required"
                        ),
                    }
                )
                continue
        if declared_primary is None:
            design_only.append(
                {
                    "id": str(_component_id(tenant, f"entities/{logical}")),
                    "path": f"entities/{logical}",
                    "format": str(artifact.get("format")),
                    "reason": "entity does not declare a primary name column",
                }
            )
            continue
        if declared_primary in unmapped_types:
            design_only.append(
                {
                    "id": str(_component_id(tenant, f"entities/{logical}")),
                    "path": f"entities/{logical}",
                    "format": str(artifact.get("format")),
                    "reason": (
                        f"entity was omitted because its primary name column {declared_primary} "
                        f"could not be mapped: unmapped WAIT type {unmapped_types[declared_primary]}"
                    ),
                }
            )
            continue
        if declared_primary not in column_names:
            design_only.append(
                {
                    "id": str(_component_id(tenant, f"entities/{logical}")),
                    "path": f"entities/{logical}",
                    "format": str(artifact.get("format")),
                    "reason": (
                        f"entity was omitted because its primary name column {declared_primary} "
                        "could not be mapped: column is absent from columns"
                    ),
                }
            )
            continue
        display_name = _text(table.get("display_name", logical), f"{logical}.display_name", MAX_TEXT_LENGTH)
        emitted_component_classes.add("entity")
        import_complete_component_classes.add("entity")
        artifact_component_classes.add("entity")
        if unmapped_fields:
            emitted_component_classes.add("partially_mapped_entity")
        root_components.append({"type": "1", "schema_name": logical})
        entities.append(
            {
                "logical_name": logical,
                "display_name": display_name,
                "attributes": attributes,
                "primary_name_column": declared_primary,
            }
        )
        emitted_artifact_entity_names.add(logical)
    if explicit_relationships:
        for relationship_index, raw_relationship in enumerate(cast(list[object], raw_relationships), start=1):
            if not isinstance(raw_relationship, Mapping):
                raise PowerPlatformPackageError("Power Apps artifact relationships must contain objects")
            relationship_id = f"relationships/{relationship_index}"
            raw_referencing = raw_relationship.get("referencing_entity")
            raw_referenced = raw_relationship.get("referenced_entity")
            if raw_referencing is None or raw_referenced is None:
                design_only.append(
                    {
                        "id": str(_component_id(tenant, relationship_id)),
                        "path": "relationships",
                        "format": str(artifact.get("format")),
                        "reason": "relationship was omitted because both entities are required",
                    }
                )
                continue
            referencing = _identifier(raw_referencing, "relationship.referencing_entity")
            referenced = _identifier(raw_referenced, "relationship.referenced_entity")
            raw_name = raw_relationship.get("name")
            name = _identifier(
                raw_name
                if raw_name is not None
                else (
                    f"{publisher_prefix}_{referenced.removeprefix(f'{publisher_prefix}_')}_"
                    f"{referencing.removeprefix(f'{publisher_prefix}_')}"
                ),
                "relationship.name",
            )
            raw_attribute = raw_relationship.get(
                "lookup_column",
                raw_relationship.get("referencing_attribute", raw_relationship.get("referencing_attribute_name")),
            )
            if raw_attribute is None:
                design_only.append(
                    {
                        "id": str(_component_id(tenant, f"{relationship_id}/{name}")),
                        "path": f"entities/{referencing}",
                        "format": str(artifact.get("format")),
                        "reason": (
                            f"relationship {name} was omitted because its referencing lookup column "
                            "is missing"
                        ),
                    }
                )
                continue
            attribute = _identifier(raw_attribute, "relationship.lookup_column")
            lookup = lookup_columns.get((referencing, attribute))
            if lookup is None:
                design_only.append(
                    {
                        "id": str(_component_id(tenant, f"{relationship_id}/{name}")),
                        "path": f"entities/{referencing}",
                        "format": str(artifact.get("format")),
                        "reason": (
                            f"relationship {name} was omitted because referencing lookup column "
                            f"{attribute} is not declared"
                        ),
                    }
                )
                continue
            if lookup["target_entity"] != referenced:
                design_only.append(
                    {
                        "id": str(_component_id(tenant, f"{relationship_id}/{name}")),
                        "path": f"entities/{referencing}",
                        "format": str(artifact.get("format")),
                        "reason": (
                            f"relationship {name} was omitted because lookup column {attribute} "
                            f"targets {lookup['target_entity']}, not {referenced}"
                        ),
                    }
                )
                continue
            if referencing not in emitted_artifact_entity_names or referenced not in emitted_artifact_entity_names:
                _remove_lookup_attribute(entities, referencing, attribute)
                design_only.append(
                    {
                        "id": str(_component_id(tenant, f"{relationship_id}/{name}")),
                        "path": f"entities/{referencing}",
                        "format": str(artifact.get("format")),
                        "reason": (
                            f"relationship {name} was omitted because referencing or referenced entity "
                            f"is not importable in this package ({referencing} -> {referenced})"
                        ),
                    }
                )
                continue
            relationships.append(
                {
                    "name": name,
                    "referencing_entity": referencing,
                    "referenced_entity": referenced,
                    "referencing_attribute": attribute,
                    "description": (
                        f"{table_display_names.get(referenced, referenced)} to "
                        f"{referencing.removeprefix(f'{publisher_prefix}_')}"
                    ),
                }
            )
            root_components.append({"type": "10", "schema_name": name})
    for candidate in relationship_candidates:
        referencing = cast(str, candidate["referencing_entity"])
        referenced = cast(str, candidate["referenced_entity"])
        attribute = cast(str, candidate["referencing_attribute"])
        if referencing not in emitted_artifact_entity_names or referenced not in emitted_artifact_entity_names:
            _remove_lookup_attribute(entities, referencing, attribute)
            design_only.append(
                {
                    "id": str(_component_id(tenant, f"entities/{referencing}/relationships/{attribute}")),
                    "path": f"entities/{referencing}",
                    "format": str(artifact.get("format")),
                    "reason": (
                        f"relationship for lookup column {attribute} was omitted because "
                        f"referencing or referenced entity is not importable in this package "
                        f"({referencing} -> {referenced})"
                    ),
                }
            )
            continue
        name = (
            f"{publisher_prefix}_{referenced.removeprefix(f'{publisher_prefix}_')}_"
            f"{referencing.removeprefix(f'{publisher_prefix}_')}"
        )
        relationships.append(
            {
                "name": name,
                "referencing_entity": referencing,
                "referenced_entity": referenced,
                "referencing_attribute": attribute,
                "description": candidate["description"],
            }
        )
        root_components.append({"type": "10", "schema_name": name})


def _emit_flow_artifact(
    artifact: Mapping[str, object],
    files: dict[str, tuple[str, str]],
    tenant: str,
    emitted_component_classes: set[str],
    artifact_component_classes: set[str],
    design_only: list[dict[str, object]],
) -> None:
    flow_id = _identifier(artifact.get("workflow_id"), "workflow_id")
    _text(artifact.get("workflow_name", flow_id), "workflow_name", MAX_TEXT_LENGTH)
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
    _text(trigger.get("name"), "power_automate.trigger.name", MAX_TEXT_LENGTH)
    _identifier(trigger.get("type"), "power_automate.trigger.type")
    _flow_actions(payload.get("actions"))
    declared = artifact.get("requires_approval")
    if declared is not None and not isinstance(declared, bool):
        raise PowerPlatformPackageError("Power Automate flow artifact requires_approval must be boolean")
    base = f"modernflows/{flow_id}"
    emitted_component_classes.add("modern_flow")
    artifact_component_classes.add("modern_flow")
    component_id = _component_id(tenant, base)
    design_only.append(
        {
            "id": str(component_id),
            "path": base,
            "format": str(artifact.get("format")),
            "reason": (
                "the emitted flow source has no Logic Apps clientdata definition "
                "or connectionReferences"
            ),
        }
    )


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
    tenant: str,
    emitted_component_classes: set[str],
    artifact_component_classes: set[str],
    design_only: list[dict[str, object]],
) -> None:
    connector_id = _identifier(artifact.get("connector_id"), "connector_id")
    base = f"connectors/{connector_id}"
    emitted_component_classes.add("custom_connector")
    artifact_component_classes.add("custom_connector")
    component_id = _component_id(tenant, base)
    design_only.append(
        {
            "id": str(component_id),
            "path": base,
            "format": str(artifact.get("format")),
            "reason": "the emitted connector source is not a Power Platform custom connector definition",
        }
    )


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
    if media_type is None:
        if safe_path.endswith(".json"):
            media_type = "application/json"
        elif safe_path.endswith(".xml"):
            media_type = "application/xml"
        elif safe_path.endswith(".md"):
            media_type = "text/markdown"
        else:
            raise PowerPlatformPackageError(f"generated file {safe_path} has no supported media type")
    files[safe_path] = (media_type, content)


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
    "PAC_XML_MINIMUM_VERSION",
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
