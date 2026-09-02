from __future__ import annotations

import copy
import subprocess
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from wait_local_agent.power_platform import (
    OpenApiDefinitionError,
    build_solution_command_plan,
    compare_pac_versions,
    definition_size_bytes,
    generate_power_platform_connector,
    pac_cli_version,
    power_platform_cli_status,
    resolve_pac_executable,
)


def _definition() -> dict[str, Any]:
    return {
        "swagger": "2.0",
        "info": {"title": "Halo API", "version": "1"},
        "host": "api.example.test",
        "basePath": "/v1",
        "schemes": ["https"],
        "securityDefinitions": {
            "apiKey": {"type": "apiKey", "name": "X-Api-Key", "in": "header"},
            "oauth": {"type": "oauth2", "flow": "accessCode", "authorizationUrl": "https://login.example.test/authorize"},
        },
        "paths": {
            "/tickets/{ticketId}": {
                "parameters": [{"name": "ticketId", "in": "path", "required": True, "type": "string"}],
                "get": {
                    "operationId": "get-ticket",
                    "summary": "Get a ticket",
                    "parameters": [{"name": "includeNotes", "in": "query", "type": "boolean"}],
                    "responses": {"200": {"description": "ok"}},
                },
            }
        },
    }


def test_connector_generation_is_bounded_and_metadata_only() -> None:
    artifact = generate_power_platform_connector("halo", _definition())

    assert artifact["format"] == "wait-local-agent.power-platform.custom-connector"
    assert artifact["connector_id"] == "halo"
    assert artifact["host"] == "api.example.test"
    assert artifact["credentials_included"] is False
    assert artifact["deployment_started"] is False
    assert artifact["authentication"] == [
        {"name": "apiKey", "type": "apiKey", "in": "header", "authorization_url_present": False},
        {"name": "oauth", "type": "oauth2", "in": None, "authorization_url_present": True},
    ]
    assert artifact["actions"] == [
        {
            "id": "get-ticket",
            "method": "GET",
            "path": "/tickets/{ticketId}",
            "summary": "Get a ticket",
            "parameters": [
                {"name": "ticketId", "in": "path", "required": True, "type": "string"},
                {"name": "includeNotes", "in": "query", "required": False, "type": "boolean"},
            ],
            "response_statuses": ["200"],
        }
    ]


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda value: value.update({"swagger": "3.0"}), "OpenAPI 2.0"),
        (lambda value: value.update({"schemes": ["http"]}), "https only"),
        (
            lambda value: value["paths"]["/tickets/{ticketId}"]["get"].update({"operationId": "get-ticket"}),
            "duplicate operationId",
        ),
        (
            lambda value: value["paths"]["/tickets/{ticketId}"]["get"]["parameters"][0].update({"name": "api_key"}),
            "secret material",
        ),
        (
            lambda value: value["paths"]["/tickets/{ticketId}"]["get"]["parameters"][0].update({"default": "x"}),
            "default values",
        ),
        (lambda value: value["paths"]["/tickets/{ticketId}"]["get"].update({"responses": {}}), "must contain a status"),
    ],
)
def test_connector_generation_rejects_unsafe_or_unsupported_definitions(change, message) -> None:
    value = copy.deepcopy(_definition())
    change(value)
    if "duplicate" in message:
        value["paths"]["/other"] = value["paths"]["/tickets/{ticketId}"]
    with pytest.raises(OpenApiDefinitionError, match=message):
        generate_power_platform_connector("halo", value)


def test_connector_generation_rejects_shape_limits_and_invalid_identifiers() -> None:
    with pytest.raises(OpenApiDefinitionError, match="connector_id"):
        generate_power_platform_connector("Not Valid", _definition())
    with pytest.raises(OpenApiDefinitionError, match="host"):
        generate_power_platform_connector("halo", {**_definition(), "host": "https://api.example.test"})
    with pytest.raises(OpenApiDefinitionError, match="paths must contain"):
        generate_power_platform_connector("halo", {**_definition(), "paths": {}})
    with pytest.raises(OpenApiDefinitionError, match="at least one"):
        generate_power_platform_connector("halo", {**_definition(), "paths": {"/health": {}}})

    oversized = _definition()
    oversized["info"] = {"title": "x" * 240, "version": "1"}
    oversized["paths"] = {
        f"/path-{index}": {"get": {"operationId": f"get-{index}", "responses": {"200": {}}}}
        for index in range(64)
    }
    assert definition_size_bytes(oversized) < 1_000_000


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda value: value.update({"basePath": "relative"}), "basePath must be"),
        (
            lambda value: value.update(
                {"paths": {"../unsafe": value["paths"]["/tickets/{ticketId}"]}}
            ),
            "safe absolute path",
        ),
        (
            lambda value: value["paths"].update(
                {
                    f"/extra-{index}": {
                        "get": {"operationId": f"extra-{index}", "responses": {"200": {}}}
                    }
                    for index in range(64)
                }
            ),
            "paths must contain",
        ),
        (
            lambda value: value["paths"]["/tickets/{ticketId}"]["get"]["parameters"][0].update(
                {"in": "cookie"}
            ),
            "unsupported parameter location",
        ),
        (
            lambda value: value["paths"]["/tickets/{ticketId}"]["get"]["parameters"].extend(
                {"name": f"q-{index}", "in": "query"} for index in range(32)
            ),
            "parameters exceeds",
        ),
        (
            lambda value: value["securityDefinitions"].update({"custom": {"type": "mutualTLS"}}),
            "unsupported security definition type",
        ),
    ],
)
def test_connector_generation_rejects_more_boundaries(change, message) -> None:
    value = copy.deepcopy(_definition())
    change(value)
    with pytest.raises(OpenApiDefinitionError, match=message):
        generate_power_platform_connector("halo", value)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda value: value.update({"info": []}), "info must be an object"),
        (lambda value: value.update({"schemes": "https"}), "https only"),
        (lambda value: value["paths"]["/tickets/{ticketId}"].update({"parameters": {}}), "must be an array"),
        (lambda value: value["paths"]["/tickets/{ticketId}"]["get"].update({"parameters": {}}), "must be an array"),
        (
            lambda value: value["paths"]["/tickets/{ticketId}"]["get"]["parameters"][0].update(
                {"name": ""}
            ),
            "must be non-empty text",
        ),
        (lambda value: value["info"].update({"title": "x" * 241}), "too long"),
    ],
)
def test_connector_generation_rejects_malformed_shapes(change, message) -> None:
    value = copy.deepcopy(_definition())
    change(value)
    with pytest.raises(OpenApiDefinitionError, match=message):
        generate_power_platform_connector("halo", value)


def test_connector_generation_rejects_large_documents() -> None:
    value = _definition()
    value["x-padding"] = "x" * 1_000_001
    with pytest.raises(OpenApiDefinitionError, match="1 MB"):
        generate_power_platform_connector("halo", value)


def test_solution_plan_is_reviewable_and_does_not_execute(monkeypatch, settings) -> None:
    monkeypatch.setattr("wait_local_agent.power_platform.shutil.which", lambda _: "/usr/bin/pac")
    monkeypatch.setattr("wait_local_agent.power_platform.pac_cli_version", lambda _: "2.4.1")
    assert power_platform_cli_status(settings) == {
        "available": True,
        "path": "/usr/bin/pac",
        "version": "2.4.1",
        "commands_executed": True,
    }
    plan = build_solution_command_plan("onboarding", "WAIT_Dev", "wait", "/tmp/onboarding")
    assert plan["execution_started"] is False
    assert plan["deployment_started"] is False
    assert plan["commands"][0][:3] == ["pac", "solution", "pack"]
    assert all(command[3] != "init" for command in plan["commands"])
    assert "--packagetype" in plan["commands"][0]
    assert all(command[:3] != ["pac", "solution", "check"] for command in plan["commands"])


def test_power_platform_cli_status_reports_probe_execution(settings, monkeypatch) -> None:
    probe_calls: list[str] = []

    def probe(executable: str) -> str:
        probe_calls.append(executable)
        return "2.4.1"

    monkeypatch.setattr("wait_local_agent.power_platform.pac_cli_version", probe)
    monkeypatch.setattr("wait_local_agent.power_platform.shutil.which", lambda _: None)
    unavailable = power_platform_cli_status(settings)

    assert unavailable["commands_executed"] is False
    assert probe_calls == []

    monkeypatch.setattr("wait_local_agent.power_platform.shutil.which", lambda _: "/usr/bin/pac")
    available = power_platform_cli_status(settings)

    assert available["commands_executed"] is True
    assert probe_calls == ["/usr/bin/pac"]


def test_pac_resolver_uses_configured_executable_without_path_fallback(settings, tmp_path: Path, monkeypatch) -> None:
    executable = tmp_path / "pac"
    executable.write_text("fake pac", encoding="utf-8")
    executable.chmod(0o755)
    monkeypatch.setattr(
        "wait_local_agent.power_platform.shutil.which",
        lambda _: pytest.fail("PATH lookup must not run for an explicit path"),
    )

    assert resolve_pac_executable(replace(settings, pac_path=executable)) == str(executable.resolve())


def test_pac_resolver_falls_back_to_path_when_unconfigured(settings, monkeypatch) -> None:
    monkeypatch.setattr("wait_local_agent.power_platform.shutil.which", lambda _: "/usr/bin/pac")

    assert resolve_pac_executable(settings) == "/usr/bin/pac"


def test_pac_resolver_rejects_invalid_configured_paths_without_path_fallback(
    settings, tmp_path: Path, monkeypatch
) -> None:
    executable = tmp_path / "pac"
    executable.write_text("fake pac", encoding="utf-8")
    executable.chmod(0o755)
    non_executable = tmp_path / "not-executable"
    non_executable.write_text("fake pac", encoding="utf-8")
    symlink = tmp_path / "pac-link"
    symlink.symlink_to(executable)
    monkeypatch.setattr(
        "wait_local_agent.power_platform.shutil.which",
        lambda _: pytest.fail("PATH lookup must not run for an invalid explicit path"),
    )

    for path in (tmp_path / "missing", non_executable, symlink):
        assert resolve_pac_executable(replace(settings, pac_path=path)) is None


def test_pac_resolver_fails_closed_when_path_resolution_raises(settings, monkeypatch) -> None:
    def raise_os_error(_path: Path) -> Path:
        raise OSError("path resolution failed")

    monkeypatch.setattr(Path, "expanduser", raise_os_error)

    assert resolve_pac_executable(replace(settings, pac_path=Path("/fake/pac"))) is None


def test_pac_cli_version_parses_real_output_with_injected_runner() -> None:
    def runner(command, **kwargs):
        assert command == ["/fake/pac", "help"]
        assert kwargs["shell"] is False
        return subprocess.CompletedProcess(
            command,
            0,
            "Microsoft PowerPlatform CLI\nVersion: 2.4.1+g3799f3e (.NET 10.0.11)\n",
            "",
        )

    assert pac_cli_version("/fake/pac", run=runner) == "2.4.1"


def test_pac_cli_version_fails_closed_for_bad_probe_results() -> None:
    assert pac_cli_version(
        "/fake/pac",
        run=lambda *_args, **_kwargs: subprocess.CompletedProcess([], 0, "not a version", ""),
    ) is None
    assert pac_cli_version(
        "/fake/pac",
        run=lambda *_args, **_kwargs: subprocess.CompletedProcess([], 1, "Version: 2.4.1", ""),
    ) is None

    def timeout_runner(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(["/fake/pac", "help"], 5)

    assert pac_cli_version("/fake/pac", run=timeout_runner) is None


def test_pac_versions_use_integer_tuple_comparison() -> None:
    assert compare_pac_versions("2.10.0", "2.9.0") > 0


def test_pac_version_comparison_rejects_non_numeric_components() -> None:
    with pytest.raises(ValueError, match="dotted numeric components"):
        compare_pac_versions("2.invalid", "2.0")


@pytest.mark.parametrize(
    ("prefix", "message"),
    [("w", "2-8"), ("1wait", "2-8"), ("wait!", "2-8")],
)
def test_solution_plan_rejects_unsafe_publisher_prefix(prefix, message) -> None:
    with pytest.raises(OpenApiDefinitionError, match=message):
        build_solution_command_plan("onboarding", "WAIT_Dev", prefix, "/tmp/onboarding")


def test_solution_plan_rejects_unsafe_publisher_and_output() -> None:
    with pytest.raises(OpenApiDefinitionError, match="publisher_name"):
        build_solution_command_plan("onboarding", "WAIT Dev", "wait", "/tmp/onboarding")
    with pytest.raises(OpenApiDefinitionError, match="too long or contains control"):
        build_solution_command_plan("onboarding", "WAIT_Dev", "wait", "/tmp/onboard\ning")
