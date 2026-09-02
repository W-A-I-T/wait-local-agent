from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest

import wait_local_agent.power_platform_package as package_module
from wait_local_agent.delivery_plan import DeliveryPlanError, build_consultant_delivery_plan
from wait_local_agent.employee_onboarding_demo import _build_review_artifacts
from wait_local_agent.power_apps import build_power_apps_artifact
from wait_local_agent.power_automate import build_power_automate_flow_plan
from wait_local_agent.power_platform_package import (
    MAX_PACKAGE_FILE_BYTES,
    PowerPlatformPackageError,
    build_deployable_blueprint_package,
    build_power_platform_package,
    materialize_deployable_blueprint_package,
    materialize_power_platform_package,
    package_validation_result,
    validate_deployable_blueprint_package,
    validate_power_platform_package,
)


def _artifacts(client_id: str = "acme") -> list[dict[str, object]]:
    return [
        {
            "format": "wait-local-agent.power-apps-artifact",
            "format_version": 1,
            "client_id": client_id,
            "app_name": "Onboarding",
            "dataverse": {
                "tables": [
                    {
                        "logical_name": "wait_employee",
                        "display_name": "Employee",
                        "primary_name_column": "wait_display_name",
                        "columns": [
                            {
                                "logical_name": "wait_display_name",
                                "display_name": "Display name",
                                "type": "String",
                                "required": True,
                            }
                        ],
                    }
                ]
            },
            "canvas_app": {"screens": []},
            "credentials_included": False,
            "execution_started": False,
            "deployment_started": False,
        },
        {
            "format": "wait-local-agent.power-automate-flow-plan",
            "format_version": 1,
            "client_id": client_id,
            "workflow_id": "employee_onboarding",
            "workflow_name": "Employee onboarding",
            "power_automate": {
                "trigger": {"type": "manual_review_trigger", "name": "HR request"},
                "actions": [
                    {
                        "id": "review",
                        "name": "Review",
                        "kind": "approval",
                        "type": "Approval",
                        "tool_id": None,
                        "method": "GET",
                        "approval_required": True,
                    }
                ],
            },
            "requires_approval": True,
            "credentials_included": False,
            "execution_started": False,
            "deployment_started": False,
        },
        {
            "format": "wait-local-agent.power-platform.custom-connector",
            "format_version": 1,
            "client_id": client_id,
            "connector_id": "hr_api",
            "display_name": "HR API",
            "host": "api.example.invalid",
            "base_path": "/v1",
            "actions": [{"id": "health", "method": "GET"}],
            "credentials_included": False,
            "deployment_started": False,
        },
    ]


def _package(tmp_path: Path, artifacts: list[dict[str, object]] | None = None) -> dict[str, object]:
    return build_power_platform_package(
        client_id="acme",
        solution_name="employee_onboarding",
        publisher_name="WAITConsulting",
        publisher_prefix="wait",
        output_directory=str(tmp_path / "source"),
        artifacts=_artifacts() if artifacts is None else artifacts,
    )


def _entity_artifact(client_id: str = "acme") -> dict[str, object]:
    return {
        "format": "wait-local-agent.power-apps-artifact",
        "format_version": 1,
        "client_id": client_id,
        "app_name": "Dataverse entities",
        "dataverse": {
            "tables": [
                {
                    "logical_name": "wait_employee",
                    "display_name": "Employee",
                    "primary_name_column": "wait_display_name",
                    "columns": [{"logical_name": "wait_display_name", "display_name": "Display name"}],
                }
            ]
        },
        "credentials_included": False,
        "execution_started": False,
        "deployment_started": False,
    }


def _flow_plan() -> dict[str, object]:
    return build_power_automate_flow_plan(
        client_id="acme",
        workflow_id="employee_onboarding",
        workflow_name="Employee onboarding",
        trigger="HR onboarding request",
        steps=[{"id": "review", "name": "Review", "kind": "approval"}],
    )


def _redigest(package: dict[str, object]) -> None:
    unsigned = dict(package)
    unsigned.pop("package_digest", None)
    package["package_digest"] = package_module._digest(package_module._canonical_json_bytes(unsigned))


def test_package_emits_the_xml_solution_layout(tmp_path: Path) -> None:
    first = _package(tmp_path)
    second = _package(tmp_path)

    assert first == second
    assert first["deployable"] is True
    assert first["package_status"] == "partial_source"
    assert first["execution_started"] is False
    assert first["deployment_started"] is False
    files = cast(list[dict[str, object]], first["files"])
    paths = {item["path"] for item in files}
    assert paths == {
        "Other/Solution.xml",
        "Other/Customizations.xml",
        "Other/Relationships.xml",
        "unsupported/components.json",
        "design_only/components.json",
    }
    assert not any(str(path).endswith(".yml") for path in paths)
    solution_xml = cast(str, next(item["content"] for item in files if item["path"] == "Other/Solution.xml"))
    customizations_xml = cast(
        str,
        next(item["content"] for item in files if item["path"] == "Other/Customizations.xml"),
    )
    assert '<RootComponent type="1" schemaName="wait_employee" behavior="0" />' in solution_xml
    assert "<EntitySetName>wait_employees</EntitySetName>" in customizations_xml
    assert "<MaxLength>100</MaxLength>" in customizations_xml
    design_only = cast(list[dict[str, object]], first["design_only_components"])
    assert {item["path"] for item in design_only} == {"modernflows/employee_onboarding", "connectors/hr_api"}
    assert all(item["reason"] for item in design_only)

    changed = _package(tmp_path, [{**_artifacts()[0], "app_name": "Changed"}])
    assert changed["package_digest"] != first["package_digest"]
    assert build_deployable_blueprint_package is build_power_platform_package
    assert validate_deployable_blueprint_package is validate_power_platform_package
    assert materialize_deployable_blueprint_package is materialize_power_platform_package


def test_package_is_deterministic(tmp_path: Path) -> None:
    first = _package(tmp_path, [_entity_artifact(), _flow_plan()])
    second = _package(tmp_path, [_entity_artifact(), _flow_plan()])

    assert first["package_digest"] == second["package_digest"]
    assert first["files"] == second["files"]


def test_real_power_apps_artifact_is_import_complete_when_packaged(tmp_path: Path) -> None:
    artifact = build_power_apps_artifact(
        client_id="acme",
        app_name="Employee onboarding workspace",
        entities=[
            {
                "logical_name": "wait_employee",
                "display_name": "Employee",
                "primary_name_column": "wait_display_name",
                "fields": [
                    {"name": "wait_display_name", "type": "string", "required": True},
                    {"name": "wait_start_date", "type": "date", "required": True},
                ],
            }
        ],
        screens=[],
        actions=[],
    )

    package = build_power_platform_package(
        client_id="acme",
        solution_name="employee_onboarding",
        publisher_name="WAITConsulting",
        publisher_prefix="wait",
        output_directory=str(tmp_path / "source"),
        artifacts=[artifact],
    )

    assert package["deployable"] is True
    assert package["package_status"] == "partial_source"
    files = cast(list[dict[str, object]], package["files"])
    solution_xml = cast(str, next(item["content"] for item in files if item["path"] == "Other/Solution.xml"))
    customizations_xml = cast(
        str,
        next(item["content"] for item in files if item["path"] == "Other/Customizations.xml"),
    )
    assert '<RootComponent type="1" schemaName="wait_employee" behavior="0" />' in solution_xml
    assert '<attribute PhysicalName="wait_display_name">' in customizations_xml
    assert "<Name>wait_display_name</Name>" in customizations_xml
    design_only = cast(list[dict[str, object]], package["design_only_components"])
    assert any(
        item["path"] == "entities/wait_employee"
        and "wait_start_date" in str(item["reason"])
        for item in design_only
    )

    string_only_artifact = build_power_apps_artifact(
        client_id="acme",
        app_name="Employee onboarding workspace",
        entities=[
            {
                "logical_name": "wait_employee",
                "display_name": "Employee",
                "primary_name_column": "wait_display_name",
                "fields": [
                    {"name": "wait_display_name", "type": "string", "required": True},
                    {"name": "wait_department", "type": "string"},
                ],
            }
        ],
        screens=[],
        actions=[],
    )
    string_only_package = build_power_platform_package(
        client_id="acme",
        solution_name="employee_onboarding",
        publisher_name="WAITConsulting",
        publisher_prefix="wait",
        output_directory=str(tmp_path / "string-only-source"),
        artifacts=[string_only_artifact],
    )
    assert string_only_package["deployable"] is True
    assert string_only_package["package_status"] == "deployable_source"
    assert string_only_package["design_only_components"] == []


def test_employee_onboarding_demo_artifacts_yield_deployable_entity(tmp_path: Path) -> None:
    package = build_power_platform_package(
        client_id="acme",
        solution_name="employee_onboarding",
        publisher_name="WAITConsulting",
        publisher_prefix="wait",
        output_directory=str(tmp_path / "source"),
        artifacts=_build_review_artifacts("acme"),
    )

    assert package["deployable"] is True
    assert package["package_status"] == "partial_source"
    files = cast(list[dict[str, object]], package["files"])
    solution_xml = cast(str, next(item["content"] for item in files if item["path"] == "Other/Solution.xml"))
    customizations_xml = cast(
        str,
        next(item["content"] for item in files if item["path"] == "Other/Customizations.xml"),
    )
    assert '<RootComponent type="1" schemaName="wait_employee" behavior="0" />' in solution_xml
    assert '<attribute PhysicalName="wait_display_name">' in customizations_xml
    assert "<Name>wait_display_name</Name>" in customizations_xml
    assert any(item["path"] == "modernflows/employee_onboarding" for item in package["design_only_components"])
    assert not any(
        item["path"] == "entities/wait_employee"
        and "entity was omitted" in str(item["reason"])
        for item in package["design_only_components"]
    )


def test_entity_is_declared_as_a_numeric_root_component(tmp_path: Path) -> None:
    package = _package(tmp_path, [_entity_artifact()])
    files = cast(list[dict[str, object]], package["files"])
    solution_xml = cast(str, next(item["content"] for item in files if item["path"] == "Other/Solution.xml"))

    assert '<RootComponent type="1" schemaName="wait_employee" behavior="0" />' in solution_xml
    assert 'type="Entity"' not in solution_xml


def test_string_attribute_emits_max_length(tmp_path: Path) -> None:
    package = _package(tmp_path, [_entity_artifact()])
    customizations_xml = cast(
        str,
        next(
            item["content"]
            for item in cast(list[dict[str, object]], package["files"])
            if item["path"] == "Other/Customizations.xml"
        ),
    )

    assert "<Type>nvarchar</Type>" in customizations_xml
    assert "<MaxLength>100</MaxLength>" in customizations_xml
    assert "<Length>100</Length>" in customizations_xml
    assert "<Format>text</Format>" in customizations_xml


def test_entity_display_name_is_xml_escaped_in_every_emitted_xml_file(tmp_path: Path) -> None:
    display_name = 'Employee "& <records>'
    artifact = _entity_artifact()
    table = cast(list[dict[str, object]], cast(dict[str, object], artifact["dataverse"])["tables"])[0]
    table["display_name"] = display_name

    package = _package(tmp_path, [artifact])
    xml_files = [
        item
        for item in cast(list[dict[str, object]], package["files"])
        if str(item["path"]).endswith(".xml")
    ]

    assert xml_files
    for item in xml_files:
        content = cast(str, item["content"])
        ET.fromstring(content)
        assert f'description="{display_name}"' not in content

    customizations_xml = cast(
        str,
        next(item["content"] for item in xml_files if item["path"] == "Other/Customizations.xml"),
    )
    escaped_display_name = "Employee &quot;&amp; &lt;records&gt;"
    assert f'description="{escaped_display_name}"' in customizations_xml
    assert 'LocalizedName="Employee &quot;&amp; &lt;records&gt;"' in customizations_xml


def test_declared_primary_name_is_used_independently_of_sorted_emission(tmp_path: Path) -> None:
    artifact = _entity_artifact()
    tables = cast(list[dict[str, object]], cast(dict[str, object], artifact["dataverse"])["tables"])
    table = tables[0]
    table["columns"] = [
        {"logical_name": "wait_aa_email", "display_name": "Email"},
        {"logical_name": "wait_zz_name", "display_name": "Name"},
    ]
    table["primary_name_column"] = "wait_zz_name"

    package = _package(tmp_path, [artifact])
    customizations_xml = cast(
        str,
        next(
            item["content"]
            for item in cast(list[dict[str, object]], package["files"])
            if item["path"] == "Other/Customizations.xml"
        ),
    )

    assert "<PrimaryNameAttribute>wait_zz_name</PrimaryNameAttribute>" in customizations_xml
    assert 'PhysicalName="wait_aa_email"' in customizations_xml
    assert "<DisplayMask>PrimaryName|" in customizations_xml
    assert customizations_xml.index('PhysicalName="wait_aa_email"') < customizations_xml.index(
        'PhysicalName="wait_zz_name"'
    )


def test_column_marked_primary_is_honoured_and_missing_primary_is_design_only(tmp_path: Path) -> None:
    artifact = _entity_artifact()
    tables = cast(list[dict[str, object]], cast(dict[str, object], artifact["dataverse"])["tables"])
    table = tables[0]
    table.pop("primary_name_column")
    cast(list[dict[str, object]], table["columns"])[0]["primary"] = True
    package = _package(tmp_path, [artifact])
    assert package["deployable"] is True
    assert package["design_only_components"] == []

    table.pop("columns")
    table["columns"] = [{"logical_name": "wait_display_name", "display_name": "Display name"}]
    package = _package(tmp_path, [artifact])
    assert package["deployable"] is False
    design_only = cast(list[dict[str, object]], package["design_only_components"])
    assert any("does not declare a primary name column" in str(item["reason"]) for item in design_only)

    table["primary_name_column"] = "wait_missing_name"
    package = _package(tmp_path, [artifact])
    files = cast(list[dict[str, object]], package["files"])
    solution_xml = cast(str, next(item["content"] for item in files if item["path"] == "Other/Solution.xml"))
    design_only = cast(list[dict[str, object]], package["design_only_components"])

    assert package["deployable"] is False
    assert "<RootComponents />" in solution_xml
    assert any(
        "entity was omitted because its primary name column wait_missing_name could not be mapped" in str(
            item["reason"]
        )
        and "absent from columns" in str(item["reason"])
        for item in design_only
    )


def test_entity_with_multiple_marked_primary_columns_is_withheld_from_both_xml_sources(
    tmp_path: Path,
) -> None:
    artifact = _entity_artifact()
    table = cast(list[dict[str, object]], cast(dict[str, object], artifact["dataverse"])["tables"])[0]
    table.pop("primary_name_column")
    table["columns"] = [
        {
            "logical_name": "wait_display_name",
            "display_name": "Display name",
            "primary": True,
        },
        {"logical_name": "wait_legal_name", "display_name": "Legal name", "primary": True},
    ]

    package = _package(tmp_path, [artifact])
    files = cast(list[dict[str, object]], package["files"])
    solution_xml = cast(str, next(item["content"] for item in files if item["path"] == "Other/Solution.xml"))
    customizations_xml = cast(
        str,
        next(item["content"] for item in files if item["path"] == "Other/Customizations.xml"),
    )
    design_only = cast(list[dict[str, object]], package["design_only_components"])

    assert "schemaName=\"wait_employee\"" not in solution_xml
    assert "<RootComponents />" in solution_xml
    assert "<Entities />" in customizations_xml
    assert any(
        item["path"] == "entities/wait_employee"
        and "entity declares multiple primary columns" in str(item["reason"])
        for item in design_only
    )


def test_entity_without_any_declared_columns_has_no_xml_source_or_root_component(tmp_path: Path) -> None:
    artifact = _entity_artifact()
    table = cast(list[dict[str, object]], cast(dict[str, object], artifact["dataverse"])["tables"])[0]
    table["columns"] = []

    package = _package(tmp_path, [artifact])
    files = cast(list[dict[str, object]], package["files"])
    solution_xml = cast(str, next(item["content"] for item in files if item["path"] == "Other/Solution.xml"))
    customizations_xml = cast(
        str,
        next(item["content"] for item in files if item["path"] == "Other/Customizations.xml"),
    )
    design_only = cast(list[dict[str, object]], package["design_only_components"])

    assert "schemaName=\"wait_employee\"" not in solution_xml
    assert "<RootComponents />" in solution_xml
    assert "<Entities />" in customizations_xml
    assert any(
        item["path"] == "entities/wait_employee"
        and "primary name column wait_display_name" in str(item["reason"])
        for item in design_only
    )


def test_entity_rejects_non_boolean_primary_markers_and_invalid_string_lengths(tmp_path: Path) -> None:
    artifact = _entity_artifact()
    table = cast(list[dict[str, object]], cast(dict[str, object], artifact["dataverse"])["tables"])[0]
    column = cast(list[dict[str, object]], table["columns"])[0]

    column["primary"] = "yes"
    with pytest.raises(PowerPlatformPackageError, match="primary must be boolean"):
        _package(tmp_path, [artifact])

    column.pop("primary")
    column["max_length"] = 0
    with pytest.raises(PowerPlatformPackageError, match="max_length must be an integer"):
        _package(tmp_path, [artifact])


def test_entity_prefix_mismatch_is_design_only_without_rewriting(tmp_path: Path) -> None:
    artifact = _entity_artifact()
    tables = cast(list[dict[str, object]], cast(dict[str, object], artifact["dataverse"])["tables"])
    table = tables[0]
    table["logical_name"] = "employee"
    table["primary_name_column"] = "display_name"
    cast(list[dict[str, object]], table["columns"])[0]["logical_name"] = "display_name"

    package = _package(tmp_path, [artifact])
    files = cast(list[dict[str, object]], package["files"])
    solution_xml = cast(str, next(item["content"] for item in files if item["path"] == "Other/Solution.xml"))
    design_only = cast(list[dict[str, object]], package["design_only_components"])

    assert package["deployable"] is False
    assert "schemaName=\"employee\"" not in solution_xml
    assert any(item["path"] == "entities/employee" and "wait_" in str(item["reason"]) for item in design_only)


def test_declared_max_length_is_emitted(tmp_path: Path) -> None:
    artifact = _entity_artifact()
    tables = cast(list[dict[str, object]], cast(dict[str, object], artifact["dataverse"])["tables"])
    table = tables[0]
    cast(list[dict[str, object]], table["columns"])[0]["max_length"] = 240
    package = _package(tmp_path, [artifact])
    customizations_xml = cast(
        str,
        next(
            item["content"]
            for item in cast(list[dict[str, object]], package["files"])
            if item["path"] == "Other/Customizations.xml"
        ),
    )

    assert "<MaxLength>240</MaxLength>" in customizations_xml
    assert "<Length>240</Length>" in customizations_xml


def test_dataverse_only_package_has_no_phantom_canvas_component(tmp_path: Path) -> None:
    package = _package(tmp_path, [_entity_artifact()])

    assert package["unsupported_components"] == []
    assert "unsupported/components.json" not in {
        item["path"] for item in cast(list[dict[str, object]], package["files"])
    }


def test_unmappable_non_primary_attribute_is_omitted_and_reported(tmp_path: Path) -> None:
    artifact = _entity_artifact()
    dataverse = cast(dict[str, object], artifact["dataverse"])
    tables = cast(list[dict[str, object]], dataverse["tables"])
    table = tables[0]
    table["columns"] = [
        {"logical_name": "wait_display_name", "display_name": "Display name", "type": "String"},
        {"logical_name": "wait_department", "display_name": "Department", "type": "DateOnly"},
    ]
    package = _package(tmp_path, [artifact])
    files = cast(list[dict[str, object]], package["files"])
    customizations_xml = cast(
        str,
        next(item["content"] for item in files if item["path"] == "Other/Customizations.xml"),
    )
    design_only = cast(list[dict[str, object]], package["design_only_components"])

    solution_xml = cast(
        str,
        next(item["content"] for item in files if item["path"] == "Other/Solution.xml"),
    )

    assert package["deployable"] is True
    assert '<RootComponent type="1" schemaName="wait_employee" behavior="0" />' in solution_xml
    assert 'PhysicalName="wait_display_name"' in customizations_xml
    assert 'PhysicalName="wait_department"' not in customizations_xml
    assert any(
        item["path"] == "entities/wait_employee"
        and "wait_department" in str(item["reason"])
        and "DateOnly" in str(item["reason"])
        for item in design_only
    )


def test_unmappable_primary_attribute_omits_entity_and_root_component(tmp_path: Path) -> None:
    artifact = _entity_artifact()
    dataverse = cast(dict[str, object], artifact["dataverse"])
    tables = cast(list[dict[str, object]], dataverse["tables"])
    table = tables[0]
    table["columns"] = [
        {"logical_name": "wait_display_name", "display_name": "Display name", "type": "DateOnly"},
        {"logical_name": "wait_department", "display_name": "Department", "type": "String"},
    ]
    package = _package(tmp_path, [artifact])
    files = cast(list[dict[str, object]], package["files"])
    solution_xml = cast(
        str,
        next(item["content"] for item in files if item["path"] == "Other/Solution.xml"),
    )
    customizations_xml = cast(
        str,
        next(item["content"] for item in files if item["path"] == "Other/Customizations.xml"),
    )
    design_only = cast(list[dict[str, object]], package["design_only_components"])

    assert package["deployable"] is False
    assert "<RootComponents />" in solution_xml
    assert 'schemaName="wait_employee"' not in solution_xml
    assert "<Entities />" in customizations_xml
    assert "<PrimaryNameAttribute>" not in customizations_xml
    assert any(
        item["path"] == "entities/wait_employee"
        and "entity was omitted because its primary name column wait_display_name could not be mapped" in str(
            item["reason"]
        )
        and "unmapped WAIT type DateOnly" in str(item["reason"])
        for item in design_only
    )


def test_connector_package_is_design_only(tmp_path: Path) -> None:
    package = _package(tmp_path, [_artifacts()[2]])

    assert package["deployable"] is False
    assert package["package_status"] == "partial_source"
    design_only = cast(list[dict[str, object]], package["design_only_components"])
    assert design_only[0]["path"] == "connectors/hr_api"
    assert "not a Power Platform custom connector definition" in str(design_only[0]["reason"])


def test_entity_only_package_reports_deployable_source(tmp_path: Path) -> None:
    package = _package(tmp_path, [_entity_artifact()])

    assert package["deployable"] is True
    assert package["package_status"] == "deployable_source"
    assert package["design_only_components"] == []


def test_flow_bearing_package_reports_partial_source_and_names_the_design_only_flow(tmp_path: Path) -> None:
    package = _package(tmp_path, [_entity_artifact(), _flow_plan()])
    files = cast(list[dict[str, object]], package["files"])
    design_only = cast(list[dict[str, object]], package["design_only_components"])

    assert package["deployable"] is True
    assert package["package_status"] == "partial_source"
    assert any(item["path"] == "modernflows/employee_onboarding" for item in design_only)
    assert any(item["reason"] for item in design_only)
    assert "design_only/components.json" in {item["path"] for item in files}


def test_package_without_any_import_complete_component_is_not_deployable(tmp_path: Path) -> None:
    package = _package(tmp_path, [_flow_plan()])

    assert package["deployable"] is False
    with pytest.raises(PowerPlatformPackageError, match="contains no component that will import"):
        validate_power_platform_package(package)


def test_package_validation_accepts_partial_source(tmp_path: Path) -> None:
    package = _package(tmp_path, [_entity_artifact(), _flow_plan()])

    assert validate_power_platform_package(package) == package["package_digest"]


def test_xml_sources_preserve_reference_empty_collections(tmp_path: Path) -> None:
    package = _package(tmp_path, [])
    files = cast(list[dict[str, object]], package["files"])
    assert {item["path"] for item in files} == {
        "Other/Solution.xml",
        "Other/Customizations.xml",
        "Other/Relationships.xml",
    }
    customizations_xml = cast(
        str,
        next(item["content"] for item in files if item["path"] == "Other/Customizations.xml"),
    )
    assert "<Roles />" in customizations_xml
    assert "<Workflows />" in customizations_xml
    assert "<EntityRelationships />" in customizations_xml
    assert "<optionsets />" in customizations_xml
    assert "<Languages>" in customizations_xml


def test_real_flow_plan_is_retained_as_design_only_without_fake_source(tmp_path: Path) -> None:
    flow_plan = build_power_automate_flow_plan(
        client_id="acme",
        workflow_id="employee_onboarding",
        workflow_name="Employee onboarding",
        trigger="HR onboarding request",
        steps=[
            {"id": "validate_manager", "name": "Validate manager", "kind": "condition"},
            {
                "id": "prepare_identity",
                "name": "Prepare Entra identity",
                "tool_id": "m365_user_create",
                "method": "POST",
                "approval_required": True,
            },
            {
                "id": "assign_license",
                "name": "Assign Microsoft 365 license",
                "tool_id": "m365_license_assign",
                "method": "POST",
                "approval_required": True,
            },
            {
                "id": "notify_manager",
                "name": "Notify manager in Teams",
                "tool_id": "m365_teams_message",
                "method": "POST",
                "approval_required": True,
            },
        ],
    )
    first = _package(tmp_path, [flow_plan])
    second = _package(tmp_path, [flow_plan])
    design_only = cast(list[dict[str, object]], first["design_only_components"])
    assert any(item["path"] == "modernflows/employee_onboarding" for item in design_only)
    assert "modernflows/employee_onboarding/flow.yml" not in {
        item["path"] for item in cast(list[dict[str, object]], first["files"])
    }
    assert first["package_digest"] == second["package_digest"]


def test_flow_artifact_rejects_malformed_or_legacy_trigger_and_action_shapes(tmp_path: Path) -> None:
    valid = _artifacts()[1]
    valid_payload = cast(dict[str, object], valid["power_automate"])
    valid_actions = cast(list[dict[str, object]], valid_payload["actions"])

    def flow_with(actions: object, trigger: object = valid_payload["trigger"]) -> dict[str, object]:
        return {**valid, "power_automate": {"trigger": trigger, "actions": actions}}

    cases: list[tuple[dict[str, object], str]] = [
        ({**valid, "power_automate": None, "trigger": "HR request", "steps": []}, "flat trigger/steps shape"),
        ({key: value for key, value in valid.items() if key != "power_automate"}, "requires a power_automate object"),
        ({**valid, "power_automate": "invalid"}, "requires a power_automate object"),
        ({**valid, "power_automate": {}}, "requires a power_automate.trigger object"),
        (flow_with(valid_actions, "invalid"), "requires a power_automate.trigger object"),
        (flow_with(valid_actions, {"type": "manual_review_trigger"}), "power_automate.trigger.name"),
        (flow_with(valid_actions, {"type": "not-valid", "name": "HR request"}), "power_automate.trigger.type"),
        (flow_with([]), "requires 1-32 power_automate.actions"),
        (flow_with("invalid"), "requires 1-32 power_automate.actions"),
        (flow_with(valid_actions * 33), "requires 1-32 power_automate.actions"),
        (flow_with([None]), "actions must contain objects"),
        (flow_with([valid_actions[0], {**valid_actions[0]}]), "duplicate power_automate.action id"),
        *[
            (
                {
                    **valid,
                    "power_automate": {
                        "trigger": valid_payload["trigger"],
                        "actions": [{key: value for key, value in valid_actions[0].items() if key != field}],
                    },
                },
                f"power_automate.action.{field}",
            )
            for field in ("name", "kind", "type", "method")
        ],
        (flow_with([{**valid_actions[0], "approval_required": "yes"}]), "approval_required must be boolean"),
        (flow_with([{**valid_actions[0], "tool_id": "not-valid"}]), "power_automate.action.tool_id"),
        ({**valid, "requires_approval": "yes"}, "requires_approval must be boolean"),
        ({**valid, "workflow_name": 42}, "workflow_name must be non-empty text"),
    ]
    for candidate, message in cases:
        with pytest.raises(PowerPlatformPackageError, match=message):
            _package(tmp_path, [candidate])

    without_tool_ids = {
        **valid,
        "power_automate": {
            "trigger": valid_payload["trigger"],
            "actions": [{**action, "tool_id": None} for action in valid_actions],
        },
    }
    package = _package(tmp_path, [without_tool_ids])
    design_only = cast(list[dict[str, object]], package["design_only_components"])
    assert any(item["path"] == "modernflows/employee_onboarding" for item in design_only)

    action_approval_only = {
        key: value for key, value in valid.items() if key != "requires_approval"
    }
    package = _package(tmp_path, [action_approval_only])
    design_only = cast(list[dict[str, object]], package["design_only_components"])
    assert any(item["path"] == "modernflows/employee_onboarding" for item in design_only)


def test_package_validation_rederives_file_and_package_digests(tmp_path: Path) -> None:
    package = _package(tmp_path)
    assert validate_power_platform_package(package, client_id="acme") == package["package_digest"]
    assert package_validation_result(package)["valid"] is True

    tampered = json.loads(json.dumps(package))
    tampered["files"][0]["content"] += "tampered"
    with pytest.raises(PowerPlatformPackageError, match="file digest mismatch"):
        validate_power_platform_package(tampered)

    tampered = json.loads(json.dumps(package))
    tampered["client_id"] = "other"
    with pytest.raises(PowerPlatformPackageError, match="outside"):
        validate_power_platform_package(tampered, client_id="acme")

    tampered = json.loads(json.dumps(package))
    tampered["file_count"] = 0
    with pytest.raises(PowerPlatformPackageError, match="file_count"):
        validate_power_platform_package(tampered)

    tampered = json.loads(json.dumps(package))
    tampered["solution"]["publisher_prefix"] = "!"
    with pytest.raises(PowerPlatformPackageError, match="publisher_prefix"):
        validate_power_platform_package(tampered)

    tampered = json.loads(json.dumps(package))
    tampered["unsupported_components"] = [{"secret_value": "leaked"}]
    with pytest.raises(PowerPlatformPackageError, match="secret-like"):
        validate_power_platform_package(tampered)

    tampered = json.loads(json.dumps(package))
    tampered["design_only_components"] = [{"secret_value": "leaked"}]
    with pytest.raises(PowerPlatformPackageError, match="secret-like"):
        validate_power_platform_package(tampered)

    tampered = json.loads(json.dumps(package))
    json_file = next(item for item in tampered["files"] if item["path"] == "unsupported/components.json")
    json_file["content"] = '{"password":"leaked"}'
    json_file["digest"] = f"sha256:{__import__('hashlib').sha256(json_file['content'].encode()).hexdigest()}"
    with pytest.raises(PowerPlatformPackageError, match="secret-like"):
        validate_power_platform_package(tampered)


def test_package_rejects_tenant_secrets_and_unsafe_output(tmp_path: Path) -> None:
    with pytest.raises(PowerPlatformPackageError, match="outside"):
        _package(tmp_path, [{**_artifacts()[0], "client_id": "other"}])
    with pytest.raises(PowerPlatformPackageError, match="secret-like"):
        _package(tmp_path, [{**_artifacts()[0], "api_key": "not-a-test-secret"}])
    with pytest.raises(PowerPlatformPackageError, match="traversal|unsafe path"):
        build_power_platform_package(
            client_id="acme",
            solution_name="employee_onboarding",
            publisher_name="WAITConsulting",
            publisher_prefix="wait",
            output_directory=str(tmp_path / ".." / "escape"),
        )


def test_materialization_is_write_gated_confined_and_digest_verified(settings, tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    package = build_power_platform_package(
        client_id="acme",
        solution_name="employee_onboarding",
        publisher_name="WAITConsulting",
        publisher_prefix="wait",
        output_directory=str(workspace / "source"),
        artifacts=_artifacts(),
    )
    blocked = materialize_power_platform_package(package, replace(settings, power_platform_workspace=workspace))
    assert blocked["status"] == "blocked"
    assert blocked["execution_started"] is False
    assert not (workspace / "source").exists()

    enabled = replace(settings, allow_write_actions=True, power_platform_workspace=workspace)
    result = materialize_power_platform_package(package, enabled, client_id="acme")
    assert result["status"] == "succeeded"
    assert result["deployment_started"] is False
    assert (workspace / "source" / "Other/Solution.xml").is_file()
    pac_plan = cast(dict[str, object], result["pac_plan"])
    assert pac_plan["commands"] == [
        [
            "pac",
            "solution",
            "pack",
            "--folder",
            str(workspace / "source"),
            "--zipfile",
            str(workspace / "source" / "employee_onboarding.zip"),
            "--packagetype",
            "Unmanaged",
        ]
    ]
    # The materialization result is the single source of truth for the pack command.
def test_materialization_rejects_symlink_output(settings, tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    link = workspace / "source"
    link.symlink_to(outside, target_is_directory=True)
    package = build_power_platform_package(
        client_id="acme",
        solution_name="employee_onboarding",
        publisher_name="WAITConsulting",
        publisher_prefix="wait",
        output_directory=str(link),
        artifacts=_artifacts(),
    )
    result = materialize_power_platform_package(
        package,
        replace(settings, allow_write_actions=True, power_platform_workspace=workspace),
    )
    assert result["status"] == "failed"
    assert "digest mismatch" not in str(result["message"])


def test_materialization_rejects_symlink_file(settings, tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("keep", encoding="utf-8")
    output = workspace / "source"
    output.mkdir()
    target = output / "Other/Solution.xml"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.symlink_to(outside)

    package = build_power_platform_package(
        client_id="acme",
        solution_name="employee_onboarding",
        publisher_name="WAITConsulting",
        publisher_prefix="wait",
        output_directory=str(output),
        artifacts=_artifacts(),
    )
    result = materialize_power_platform_package(
        package,
        replace(settings, allow_write_actions=True, power_platform_workspace=workspace),
    )
    assert result["status"] == "failed"
    assert outside.read_text(encoding="utf-8") == "keep"


def test_input_limits_and_unhashable_tenant_values_are_bounded(tmp_path: Path) -> None:
    with pytest.raises(PowerPlatformPackageError, match="at most"):
        _package(tmp_path, _artifacts() * 11)
    with pytest.raises(PowerPlatformPackageError, match="outside"):
        _package(tmp_path, [{"format": "unknown", "client_id": []}])
    package = _package(tmp_path)
    files = cast(list[dict[str, object]], package["files"])
    files[0]["media_type"] = []
    with pytest.raises(PowerPlatformPackageError, match="media type"):
        validate_power_platform_package(package)
    package = _package(tmp_path)
    files = cast(list[dict[str, object]], package["files"])
    files[0]["content"] = "x" * (MAX_PACKAGE_FILE_BYTES + 1)
    with pytest.raises(PowerPlatformPackageError, match="exceeds"):
        validate_power_platform_package(package)


def test_build_and_artifact_validation_failure_branches(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(PowerPlatformPackageError, match="artifacts or review_artifacts"):
        build_power_platform_package(
            client_id="acme",
            solution_name="employee_onboarding",
            publisher_name="WAITConsulting",
            publisher_prefix="wait",
            output_directory=str(tmp_path / "source"),
            artifacts=[{"format": "unknown"}],
            review_artifacts=[{"format": "unknown"}],
        )

    monkeypatch.setattr(package_module, "MAX_PACKAGE_FILES", 1)
    with pytest.raises(PowerPlatformPackageError, match="may contain at most"):
        _package(tmp_path, [])
    monkeypatch.setattr(package_module, "MAX_PACKAGE_FILES", 96)
    monkeypatch.setattr(package_module, "MAX_PACKAGE_BYTES", 1)
    with pytest.raises(PowerPlatformPackageError, match="exceeds the bounded size"):
        _package(tmp_path, [])
    monkeypatch.setattr(package_module, "MAX_PACKAGE_FILE_BYTES", 1)
    with pytest.raises(PowerPlatformPackageError, match="generated file"):
        _package(tmp_path, [])
    monkeypatch.setattr(package_module, "MAX_PACKAGE_FILE_BYTES", 64_000)
    monkeypatch.setattr(package_module, "MAX_PACKAGE_BYTES", 512_000)

    with pytest.raises(PowerPlatformPackageError, match="objects"):
        _package(tmp_path, cast(list[dict[str, object]], [None]))
    with pytest.raises(PowerPlatformPackageError, match="credentials"):
        _package(tmp_path, [{"format": "unknown", "credentials_included": True}])
    with pytest.raises(PowerPlatformPackageError, match="execution"):
        _package(tmp_path, [{"format": "unknown", "execution_started": True}])
    with pytest.raises(PowerPlatformPackageError, match="too many items"):
        _package(tmp_path, [{"format": "unknown", "items": list(range(769))}])
    with pytest.raises(PowerPlatformPackageError, match="secret-like"):
        _package(tmp_path, [{"format": "unknown", "value": "Bearer abc"}])
    with pytest.raises(PowerPlatformPackageError, match="non-finite"):
        _package(tmp_path, [{"format": "unknown", "value": float("inf")}])
    with pytest.raises(PowerPlatformPackageError, match="unsupported value"):
        _package(tmp_path, [{"format": "unknown", "value": object()}])
    with pytest.raises(PowerPlatformPackageError, match="unsafe key"):
        _package(tmp_path, [{"format": "unknown", "\x01": "value"}])
    with pytest.raises(PowerPlatformPackageError, match="unsafe or oversized"):
        _package(tmp_path, [{"format": "unknown", "value": "x" * (240 * 16 + 1)}])
    with pytest.raises(PowerPlatformPackageError, match="credentials"):
        _package(tmp_path, [{"format": "unknown", "credentials_included": True}])
    assert _package(tmp_path, [{"format": "unknown", "password": None}])["deployable"] is False

    oversized: dict[str, object] = {"format": "unknown", "items": ["x" * 380 for _ in range(768)]}
    with pytest.raises(PowerPlatformPackageError, match="input size"):
        _package(tmp_path, [oversized])

    bad_apps = _artifacts()[0]
    for field, value, message in (
        ("dataverse", {}, "dataverse.tables"),
        ("canvas_app", "binary", "canvas_app"),
    ):
        candidate = dict(bad_apps)
        candidate[field] = value
        with pytest.raises(PowerPlatformPackageError, match=message):
            _package(tmp_path, [candidate])
    candidate = dict(bad_apps)
    candidate["dataverse"] = {"tables": [None]}
    with pytest.raises(PowerPlatformPackageError, match="tables"):
        _package(tmp_path, [candidate])
    candidate = dict(bad_apps)
    candidate["dataverse"] = {"tables": [{"logical_name": "wait_employee", "columns": [None]}]}
    with pytest.raises(PowerPlatformPackageError, match="columns"):
        _package(tmp_path, [candidate])


def test_package_validation_rejects_malformed_metadata_and_caps(tmp_path: Path) -> None:
    base = _package(tmp_path)
    with pytest.raises(PowerPlatformPackageError, match="object"):
        validate_power_platform_package(cast(dict[str, object], []))
    invalid_cases: list[tuple[str, object, str]] = [
        ("format", "wrong", "unsupported"),
        ("deployable", False, "contains no component that will import"),
        ("credentials_included", True, "credentials"),
        ("execution_started", True, "execution"),
        ("output_directory", f"{base['output_directory']} ", "canonical"),
        ("solution", [], "solution"),
        ("unsupported_components", {}, "unsupported_components"),
        ("design_only_components", {}, "design_only_components"),
        ("files", [], "package.files"),
    ]
    for key, value, message in invalid_cases:
        candidate = json.loads(json.dumps(base))
        candidate[key] = value
        with pytest.raises(PowerPlatformPackageError, match=message):
            validate_power_platform_package(candidate)

    candidate = json.loads(json.dumps(base))
    candidate["solution"]["publisher_unique_name"] = "different"
    with pytest.raises(PowerPlatformPackageError, match="publisher identity"):
        validate_power_platform_package(candidate)

    candidate = json.loads(json.dumps(base))
    candidate["files"] = [None]
    candidate["file_count"] = 1
    with pytest.raises(PowerPlatformPackageError, match="contain objects"):
        validate_power_platform_package(candidate)

    candidate = json.loads(json.dumps(base))
    candidate["files"].append(dict(candidate["files"][0]))
    candidate["file_count"] = len(candidate["files"])
    with pytest.raises(PowerPlatformPackageError, match="duplicate"):
        validate_power_platform_package(candidate)

    candidate = json.loads(json.dumps(base))
    candidate["files"][0]["content"] = "bad\x01content"
    with pytest.raises(PowerPlatformPackageError, match="invalid content"):
        validate_power_platform_package(candidate)

    candidate = json.loads(json.dumps(base))
    candidate["files"].extend(
        {
            "path": f"extra/{index}.json",
            "media_type": "application/json",
            "content": "x" * 63_000,
            "digest": package_module._digest(("x" * 63_000).encode()),
        }
        for index in range(9)
    )
    candidate["file_count"] = len(candidate["files"])
    with pytest.raises(PowerPlatformPackageError, match="files exceed"):
        validate_power_platform_package(candidate)

    candidate = json.loads(json.dumps(base))
    candidate["extra"] = "x" * 513_000
    with pytest.raises(PowerPlatformPackageError, match="exceeds the bounded size"):
        validate_power_platform_package(candidate)

    candidate = json.loads(json.dumps(base))
    candidate["package_digest"] = "sha256:" + "0" * 64
    with pytest.raises(PowerPlatformPackageError, match="package digest"):
        validate_power_platform_package(candidate)

    candidate = json.loads(json.dumps(base))
    candidate["pac"]["format"] = "xml"
    _redigest(candidate)
    with pytest.raises(PowerPlatformPackageError, match="PAC compatibility"):
        validate_power_platform_package(candidate)

    candidate = json.loads(json.dumps(base))
    candidate["pac"]["commands"][0][4] = "/other"
    _redigest(candidate)
    with pytest.raises(PowerPlatformPackageError, match="digest-bound"):
        validate_power_platform_package(candidate)

    missing = json.loads(json.dumps(base))
    missing["files"] = [item for item in missing["files"] if item["path"] != "Other/Solution.xml"]
    missing["file_count"] = len(missing["files"])
    with pytest.raises(PowerPlatformPackageError, match="official XML"):
        validate_power_platform_package(missing)


def test_materialization_failure_branches(settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    failed = materialize_power_platform_package({}, settings)
    assert failed["status"] == "failed"

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    output_file = workspace / "source"
    output_file.write_text("not a directory", encoding="utf-8")
    output_package = build_power_platform_package(
        client_id="acme",
        solution_name="employee_onboarding",
        publisher_name="WAITConsulting",
        publisher_prefix="wait",
        output_directory=str(output_file),
        artifacts=_artifacts(),
    )
    result = materialize_power_platform_package(
        output_package,
        replace(settings, allow_write_actions=True, power_platform_workspace=workspace),
    )
    assert result["status"] == "failed"
    assert "not a directory" in str(result["message"])

    workspace_link = tmp_path / "workspace-link"
    workspace_link.symlink_to(workspace, target_is_directory=True)
    package = build_power_platform_package(
        client_id="acme",
        solution_name="employee_onboarding",
        publisher_name="WAITConsulting",
        publisher_prefix="wait",
        output_directory=str(workspace / "source"),
        artifacts=_artifacts(),
    )
    result = materialize_power_platform_package(
        package,
        replace(settings, allow_write_actions=True, power_platform_workspace=workspace_link),
    )
    assert result["status"] == "failed"
    assert "may not be a symlink" in str(result["message"])

    result = materialize_power_platform_package(
        package,
        replace(settings, allow_write_actions=True, power_platform_workspace=tmp_path / "missing"),
    )
    assert result["status"] == "failed"
    assert "must already exist" in str(result["message"])

    equal_package = build_power_platform_package(
        client_id="acme",
        solution_name="employee_onboarding",
        publisher_name="WAITConsulting",
        publisher_prefix="wait",
        output_directory=str(workspace),
        artifacts=[],
    )
    result = materialize_power_platform_package(
        equal_package,
        replace(settings, allow_write_actions=True, power_platform_workspace=workspace),
    )
    assert result["status"] == "failed"
    assert "inside" in str(result["message"])

    open_package = build_power_platform_package(
        client_id="acme",
        solution_name="employee_onboarding",
        publisher_name="WAITConsulting",
        publisher_prefix="wait",
        output_directory=str(workspace / "open-source"),
        artifacts=_artifacts(),
    )
    original_open = package_module.os.open

    def fail_open(*args: object, **kwargs: object) -> int:
        raise OSError("open failed")

    monkeypatch.setattr(package_module.os, "open", fail_open)
    result = materialize_power_platform_package(
        open_package,
        replace(settings, allow_write_actions=True, power_platform_workspace=workspace),
    )
    assert result["status"] == "failed"
    assert "open failed" in str(result["message"])
    monkeypatch.setattr(package_module.os, "open", original_open)
    monkeypatch.setattr(Path, "read_bytes", lambda self: b"tampered")
    result = materialize_power_platform_package(
        open_package,
        replace(settings, allow_write_actions=True, power_platform_workspace=workspace),
    )
    assert result["status"] == "failed"
    assert "digest verification" in str(result["message"])


def test_low_level_defensive_branches(monkeypatch: pytest.MonkeyPatch) -> None:
    assert package_module._pack_zip_path(r"C:\source", "solution") == r"C:\source\solution.zip"

    with pytest.raises(PowerPlatformPackageError, match="JSON-compatible"):
        package_module._canonical_json_bytes(object())
    with pytest.raises(PowerPlatformPackageError, match="collision"):
        package_module._add_file({"a.json": ("application/json", "one")}, "a.json", "two")
    with pytest.raises(PowerPlatformPackageError, match="exceeds"):
        package_module._add_file({}, "large.json", "x" * (package_module.MAX_PACKAGE_FILE_BYTES + 1))
    files: dict[str, tuple[str, str]] = {}
    for path, media_type in (
        ("metadata.json", "application/json"),
        ("source.xml", "application/xml"),
        ("notes.md", "text/markdown"),
    ):
        package_module._add_file(files, path, "content")
        assert files[path][0] == media_type
    with pytest.raises(PowerPlatformPackageError, match="no supported media type"):
        package_module._add_file(files, "source.txt", "content")
    assert package_module._contains_secret_like_source("password: leaked") is True
    assert package_module._contains_secret_like_source('{"nested": {"token": "leaked"}}') is True
    assert package_module._contains_secret_like_source("not json") is False

    with pytest.raises(PowerPlatformPackageError, match="publisher_name"):
        package_module._publisher_name("bad-name")
    with pytest.raises(PowerPlatformPackageError, match="lowercase identifier"):
        package_module._identifier("Bad-Name", "identifier")
    with pytest.raises(PowerPlatformPackageError, match="non-empty text"):
        package_module._text("\x01", "value", 10)
    with pytest.raises(PowerPlatformPackageError, match="safe relative"):
        package_module._safe_relative_path("../escape", "path")

    monkeypatch.setattr(package_module, "_validate_value", lambda *_args: [])
    with pytest.raises(PowerPlatformPackageError, match="must be a JSON object"):
        package_module._validate_input_artifacts([{"format": "unknown"}], "acme")


def test_delivery_keeps_review_bundle_non_deployable_and_links_source_digest(tmp_path: Path) -> None:
    package = _package(tmp_path)
    result = build_consultant_delivery_plan(
        client_id="acme",
        architecture={"client_id": "acme", "readiness": "ready", "components": [], "approval_policy": {}},
        evaluation={"production_readiness": "pass", "case_count": 1},
        governance={"client_id": "acme", "status": "pass"},
        deployment_targets=["Teams"],
        review_artifacts=[{"client_id": "acme", "credentials_included": False}],
        deployable_package=package,
    )
    assert result["delivery_bundle"]["manifest"]["deployable"] is False
    assert result["deployable_source_package_digest"] == package["package_digest"]
    assert result["deployment_package_generated"] is False

    foreign = dict(package)
    foreign["client_id"] = "other"
    with pytest.raises(DeliveryPlanError, match="outside"):
        build_consultant_delivery_plan(
            client_id="acme",
            architecture={"client_id": "acme", "readiness": "ready", "components": [], "approval_policy": {}},
            evaluation={"production_readiness": "pass", "case_count": 1},
            governance={"client_id": "acme", "status": "pass"},
            deployment_targets=["Teams"],
            review_artifacts=[{"client_id": "acme", "credentials_included": False}],
            deployable_package=foreign,
        )
