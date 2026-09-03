from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest

from tests.support import ingest_local
from wait_local_agent.copilot_studio import build_copilot_studio_plan
from wait_local_agent.employee_onboarding_demo import (
    CANONICAL_EMPLOYEE_ONBOARDING_REQUEST,
    EmployeeOnboardingDemoError,
    _blueprint_request,
    _derive_fixture_children,
    _fixture_dependencies,
    _FixtureChildSpec,
    _format_value,
    _service_slug,
    _system_category,
    run_employee_onboarding_demo,
)
from wait_local_agent.models import BlueprintAgent, SolutionBlueprint
from wait_local_agent.store import Store


def _make_blueprint(
    *,
    solution_name: str = "Fixture solution",
    business_goal: dict[str, str | bool | int] | None = None,
    users: tuple[str, ...] = (),
    systems: tuple[str, ...] = (),
    agents: tuple[BlueprintAgent, ...] = (),
    discovery: dict[str, object] | None = None,
) -> SolutionBlueprint:
    return SolutionBlueprint(
        id="bp-test",
        client_id="acme",
        created_by="tester",
        created_at="2026-08-31T00:00:00+00:00",
        updated_at="2026-08-31T00:00:00+00:00",
        solution_name=solution_name,
        business_goal={} if business_goal is None else business_goal,
        users=users,
        knowledge=(),
        systems=systems,
        agents=agents,
        workflows=(),
        approvals={},
        deployment=(),
        risk="low",
        discovery={} if discovery is None else discovery,
    )


def test_employee_onboarding_demo_composes_local_fixture_stages(settings) -> None:
    store = Store(settings.data_path)
    ingest_local(store, Path("examples/sample_tickets/tickets.json"))
    with store._connect() as connection:  # noqa: SLF001 - bind the isolated fixture tenant.
        connection.execute(
            "update tickets set client_id = ? where id = ?",
            ("acme", "TCK-1001"),
        )
    blueprint = json.loads(Path("examples/consultant/employee-onboarding-blueprint.json").read_text(encoding="utf-8"))

    result = run_employee_onboarding_demo(
        store=store,
        settings=settings,
        blueprint_payload=blueprint,
    )

    assert result["format"] == "wait-local-agent.employee-onboarding-demo"
    assert result["mode"] == "local_fixture"
    stages = result["stages"]
    assert stages["discovery"]["status"] == "complete"
    assert stages["environment"]["probe_performed"] is False
    assert stages["supervisor"]["status"] == "completed"
    assert len(stages["supervisor"]["children"]) == len(result["fixture_child_agents"]) == 5
    assert {child["role"] for child in result["fixture_child_agents"]} == {
        "identity-microsoft-365-entra",
        "endpoint-intune-ninjaone",
        "documentation-sharepoint-hudu",
        "communications-teams",
        "psa-connectwise",
    }
    assert "Employee onboarding supervisor" in result["request"]
    assert (
        "Systems/services: Microsoft 365, Entra, Intune, SharePoint, Teams, ConnectWise, NinjaOne, Hudu"
        in result["request"]
    )
    assert stages["evaluation"]["execution_started"] is True
    assert stages["evaluation"]["production_readiness"] == "pass"
    assert stages["governance"]["status"] == "needs_review"
    assert stages["delivery"]["production_readiness"] == "needs_review"
    assert stages["artifacts"]["status"] == "review_only"
    assert len(stages["artifacts"]["items"]) == 2
    assert len(result["design_handoffs"]) == 1
    handoff = cast(dict[str, object], result["design_handoffs"][0])
    assert handoff["format"] == build_copilot_studio_plan(
        client_id="acme",
        copilot_name="Test copilot",
        business_goal="Test business goal",
        topics=[],
        knowledge_sources=[],
        actions=[],
    )["format"]
    assert stages["artifacts"]["package"]["package_status"] == "review_only"
    assert stages["artifacts"]["package_digest"].startswith("sha256:")
    assert stages["artifacts"]["delivery_bundle"]["manifest"]["deployable"] is False
    assert stages["artifacts"]["delivery_bundle_digest"].startswith("sha256:")
    assert stages["artifacts"]["deployment_package_generated"] is False
    assert stages["delivery"]["review_package_generated"] is True
    assert stages["delivery"]["delivery_bundle_generated"] is True
    assert stages["delivery"]["delivery_bundle_status"] == "review_only"
    assert stages["delivery"]["deployment_package_generated"] is False
    assert result["boundaries"] == {
        "live_provider_execution": False,
        "artifact_generation": True,
        "artifact_generation_status": "review_only",
        "review_package_generated": True,
        "delivery_bundle_generated": True,
        "delivery_bundle_status": "review_only",
        "deployable_package_generated": True,
        "deployable_package_deployable": stages["artifacts"]["deployable_source_package"]["deployable"],
        "deployable_package_status": stages["artifacts"]["deployable_source_package"]["package_status"],
        "deployable_package_digest": stages["artifacts"]["deployable_source_package_digest"],
        "deployment_started": False,
        "production_deployment_requires_approval": True,
        "external_systems_require_environment_verification": True,
        "sensitive_operations_require_human_approval": True,
    }
    assert result["audit"]["agent_run_count"] == len(result["fixture_child_agents"]) + 1
    assert result["audit"]["audit_event_count"] > 0


def test_employee_onboarding_demo_uses_selected_blueprint_content(settings, tmp_path) -> None:
    store = Store(settings.data_path)
    ingest_local(store, Path("examples/sample_tickets/tickets.json"))
    with store._connect() as connection:  # noqa: SLF001 - bind the isolated fixture tenant.
        connection.execute(
            "update tickets set client_id = ? where id = ?",
            ("acme", "TCK-1001"),
        )
    first = json.loads(Path("examples/consultant/employee-onboarding-blueprint.json").read_text(encoding="utf-8"))
    second = {
        **first,
        "solution": {"name": "Employee offboarding supervisor"},
        "business_goal": {"statement": "Automate auditable employee offboarding"},
        "systems": ["Okta", "Jamf", "ServiceNow"],
        "discovery": {
            "solution_name": "Employee offboarding supervisor",
            "business_goal": "Automate auditable employee offboarding",
            "systems": ["Okta", "Jamf", "ServiceNow"],
        },
    }

    first_result = run_employee_onboarding_demo(
        store=store,
        settings=settings,
        blueprint_payload=first,
        persist_blueprint=False,
        output_directory=str(tmp_path / "first"),
    )
    second_result = run_employee_onboarding_demo(
        store=store,
        settings=settings,
        blueprint_payload=second,
        persist_blueprint=False,
        output_directory=str(tmp_path / "second"),
    )

    assert first_result["request"] != second_result["request"]
    assert {child["role"] for child in first_result["fixture_child_agents"]} != {
        child["role"] for child in second_result["fixture_child_agents"]
    }
    assert {child["role"] for child in second_result["fixture_child_agents"]} == {
        "identity-okta",
        "endpoint-jamf",
        "psa-servicenow",
    }


def test_employee_onboarding_demo_requires_a_scoped_fixture_ticket(settings) -> None:
    with pytest.raises(EmployeeOnboardingDemoError, match="tenant-scoped ticket"):
        run_employee_onboarding_demo(
            store=Store(settings.data_path),
            settings=settings,
            blueprint_payload={},
        )


def test_employee_onboarding_demo_rejects_non_object_blueprint(settings) -> None:
    store = Store(settings.data_path)
    ingest_local(store, Path("examples/sample_tickets/tickets.json"))
    with store._connect() as connection:  # noqa: SLF001 - bind the isolated fixture tenant.
        connection.execute(
            "update tickets set client_id = ? where id = ?",
            ("acme", "TCK-1001"),
        )

    with pytest.raises(EmployeeOnboardingDemoError, match="blueprint must be an object"):
        run_employee_onboarding_demo(
            store=store,
            settings=settings,
            blueprint_payload=cast(dict[str, object], ["not", "an", "object"]),
        )


def test_employee_onboarding_demo_maps_blueprint_validation_errors(settings) -> None:
    store = Store(settings.data_path)
    ingest_local(store, Path("examples/sample_tickets/tickets.json"))
    with store._connect() as connection:  # noqa: SLF001 - bind the isolated fixture tenant.
        connection.execute(
            "update tickets set client_id = ? where id = ?",
            ("acme", "TCK-1001"),
        )

    with pytest.raises(EmployeeOnboardingDemoError):
        run_employee_onboarding_demo(
            store=store,
            settings=settings,
            blueprint_payload={},
        )


def test_derive_fixture_children_uses_declared_agent_names_when_systems_are_empty() -> None:
    blueprint = _make_blueprint(
        agents=(BlueprintAgent(id="finance-agent", name="Finance workflow specialist", purpose="Review finance"),)
    )

    specs = _derive_fixture_children(blueprint)

    assert len(specs) == 1
    assert specs[0].systems == ("Finance workflow specialist",)


def test_derive_fixture_children_falls_back_to_solution_name() -> None:
    specs = _derive_fixture_children(_make_blueprint(solution_name="Fallback solution"))

    assert len(specs) == 1
    assert specs[0].systems == ("Fallback solution",)


def test_system_category_defaults_to_service_for_unmatched_system() -> None:
    assert _system_category("Payroll orchestration") == "service"


def test_service_slug_hashes_long_system_lists() -> None:
    slug = _service_slug(["A" * 32, "B" * 32])
    digest = slug.rsplit("-", 1)[-1]

    assert len(slug) == 54
    assert len(digest) == 8
    assert all(character in "0123456789abcdef" for character in digest)


def test_fixture_dependencies_cover_empty_prerequisite_paths() -> None:
    assert _fixture_dependencies("licensing", [], {}) == ()
    assert _fixture_dependencies("endpoint", [], {}) == ()


def test_fixture_dependencies_service_uses_previous_spec() -> None:
    previous = _FixtureChildSpec(
        key="identity-1",
        role="identity-entra",
        category="identity",
        systems=("Entra",),
        dependencies=(),
    )

    assert _fixture_dependencies("service", [previous], {}) == ("identity-1",)


def test_blueprint_request_uses_canonical_request_for_empty_blueprint() -> None:
    blueprint = _make_blueprint(solution_name="", business_goal={}, systems=(), users=(), discovery={})

    assert _blueprint_request(blueprint) == CANONICAL_EMPLOYEE_ONBOARDING_REQUEST


def test_format_value_formats_nested_mapping() -> None:
    assert _format_value({"region": "North", "department": "HR"}) == "department=HR; region=North"
