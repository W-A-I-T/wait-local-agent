from __future__ import annotations

import json
import re
import uuid
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest

from wait_local_agent.delivery_plan import DeliveryPlanError, build_consultant_delivery_plan
from wait_local_agent.power_platform_deployment import (
    PowerPlatformDeploymentError,
    build_power_platform_source_pack_plan,
)
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
                        "logical_name": "employee",
                        "display_name": "Employee",
                        "columns": [
                            {
                                "logical_name": "display_name",
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
            "trigger": "HR request",
            "steps": [{"id": "review", "name": "Review", "kind": "approval"}],
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
        artifacts=artifacts or _artifacts(),
    )


def test_package_is_deterministic_and_emits_official_yaml_layout(tmp_path: Path) -> None:
    first = _package(tmp_path)
    second = _package(tmp_path)

    assert first == second
    assert first["deployable"] is True
    assert first["execution_started"] is False
    assert first["deployment_started"] is False
    files = cast(list[dict[str, object]], first["files"])
    paths = {item["path"] for item in files}
    assert "solutions/employee_onboarding/solution.yml" in paths
    assert "solutions/employee_onboarding/solutioncomponents.yml" in paths
    assert "solutions/employee_onboarding/rootcomponents.yml" in paths
    assert "publishers/waitconsulting/publisher.yml" in paths
    publisher_manifest = cast(
        str,
        next(item["content"] for item in files if item["path"] == "publishers/waitconsulting/publisher.yml"),
    )
    assert '"@description": WAITConsulting' in publisher_manifest
    assert '"@languagecode": "1033"' in publisher_manifest
    assert "entities/employee/entity.yml" in paths
    assert "entities/employee/attributes/display_name.yml" in paths
    assert "modernflows/employee_onboarding/flow.yml" in paths
    assert "connectors/hr_api/connector.yml" in paths
    assert "unsupported/components.json" in paths
    solution_components = cast(
        str,
        next(
            item["content"]
            for item in files
            if item["path"] == "solutions/employee_onboarding/solutioncomponents.yml"
        ),
    )
    assert "solutions/employee_onboarding" not in solution_components
    root_components = cast(
        str,
        next(
            item["content"]
            for item in files
            if item["path"] == "solutions/employee_onboarding/rootcomponents.yml"
        ),
    )
    assert str(uuid.UUID(str(next(iter(re.findall(r"[0-9a-f-]{36}", root_components)))))) in root_components

    changed = _package(tmp_path, [{**_artifacts()[0], "app_name": "Changed"}])
    assert changed["package_digest"] != first["package_digest"]
    assert build_deployable_blueprint_package is build_power_platform_package
    assert validate_deployable_blueprint_package is validate_power_platform_package
    assert materialize_deployable_blueprint_package is materialize_power_platform_package


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
    assert (workspace / "source" / "solutions/employee_onboarding/solution.yml").is_file()
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
        ]
    ]
    source_pack_plan = build_power_platform_source_pack_plan(package)
    assert source_pack_plan["folder"] == str((workspace / "source").resolve())
    assert source_pack_plan["zipfile"] == str((workspace / "source" / "employee_onboarding.zip").resolve())
    with pytest.raises(PowerPlatformDeploymentError, match="must match"):
        build_power_platform_source_pack_plan(package, materialization_directory=str(workspace / "other"))

    escaped = dict(package)
    escaped["output_directory"] = str(tmp_path / "outside")
    with pytest.raises(PowerPlatformDeploymentError):
        build_power_platform_source_pack_plan(escaped)


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
    target = output / "publishers/waitconsulting/publisher.yml"
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
