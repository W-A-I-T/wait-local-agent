from __future__ import annotations

import json
import re
import uuid
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest

import wait_local_agent.power_platform_package as package_module
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
        artifacts=_artifacts() if artifacts is None else artifacts,
    )


def _redigest(package: dict[str, object]) -> None:
    unsigned = dict(package)
    unsigned.pop("package_digest", None)
    package["package_digest"] = package_module._digest(package_module._canonical_json_bytes(unsigned))


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


def test_yaml_sources_preserve_empty_collections_and_quote_yaml_boolean_words(tmp_path: Path) -> None:
    package = _package(tmp_path, [])
    files = cast(list[dict[str, object]], package["files"])
    missing_dependencies = next(
        item["content"]
        for item in files
        if item["path"] == "solutions/employee_onboarding/missingdependencies.yml"
    )
    assert missing_dependencies == "[]\n"

    flow = _package(
        tmp_path,
        [
            {
                **_artifacts()[1],
                "trigger": "on",
                "steps": [],
            }
        ],
    )
    flow_content = cast(
        str,
        next(
            item["content"]
            for item in cast(list[dict[str, object]], flow["files"])
            if item["path"] == "modernflows/employee_onboarding/flow.yml"
        ),
    )
    assert 'Trigger: "on"' in flow_content
    assert "Steps: []" in flow_content


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
    with pytest.raises(PowerPlatformDeploymentError, match="required"):
        build_power_platform_source_pack_plan(package, materialization_directory="")

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
    assert _package(tmp_path, [{"format": "unknown", "password": None}])["deployable"] is True

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
    candidate["dataverse"] = {"tables": [{"logical_name": "employee", "columns": [None]}]}
    with pytest.raises(PowerPlatformPackageError, match="columns"):
        _package(tmp_path, [candidate])


def test_package_validation_rejects_malformed_metadata_and_caps(tmp_path: Path) -> None:
    base = _package(tmp_path)
    with pytest.raises(PowerPlatformPackageError, match="object"):
        validate_power_platform_package(cast(dict[str, object], []))
    invalid_cases: list[tuple[str, object, str]] = [
        ("format", "wrong", "unsupported"),
        ("deployable", False, "deployable_source"),
        ("credentials_included", True, "credentials"),
        ("execution_started", True, "execution"),
        ("output_directory", f"{base['output_directory']} ", "canonical"),
        ("solution", [], "solution"),
        ("unsupported_components", {}, "unsupported_components"),
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
            "path": f"extra/{index}.yml",
            "media_type": "text/yaml",
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
    missing["files"] = [item for item in missing["files"] if not item["path"].endswith("solution.yml")]
    missing["file_count"] = len(missing["files"])
    with pytest.raises(PowerPlatformPackageError, match="official YAML"):
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


def test_yaml_and_low_level_defensive_branches(monkeypatch: pytest.MonkeyPatch) -> None:
    assert package_module._yaml({}) == "{}\n"
    assert package_module._yaml([{}]) == "- {}\n"
    assert "Empty: {}" in package_module._yaml({"Empty": {}})
    assert "Empty: []" in package_module._yaml({"Empty": []})
    rendered = package_module._yaml(
        [{"empty_map": {}, "empty_list": [], "none": None, "nested": {"value": 1}}, [[1]], "text", None, 2]
    )
    assert "empty_map: {}" in rendered
    assert "empty_list: []" in rendered
    assert "nested:" in rendered
    assert "-" in rendered
    assert package_module._yaml("scalar") == "scalar\n"
    assert package_module._yaml_scalar(None) == ""
    assert package_module._yaml_scalar(2) == "2"
    assert package_module._yaml_scalar(True) == "true"
    assert package_module._yaml_scalar("on") == '"on"'
    assert package_module._pack_zip_path(r"C:\source", "solution") == r"C:\source\solution.zip"

    with pytest.raises(PowerPlatformPackageError, match="JSON-compatible"):
        package_module._canonical_json_bytes(object())
    with pytest.raises(PowerPlatformPackageError, match="collision"):
        package_module._add_file({"a.yml": ("text/yaml", "one")}, "a.yml", "two")
    with pytest.raises(PowerPlatformPackageError, match="exceeds"):
        package_module._add_file({}, "large.yml", "x" * (package_module.MAX_PACKAGE_FILE_BYTES + 1))
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
