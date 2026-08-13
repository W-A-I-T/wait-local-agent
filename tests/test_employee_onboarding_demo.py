from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest

from wait_local_agent.employee_onboarding_demo import (
    EmployeeOnboardingDemoError,
    run_employee_onboarding_demo,
)
from wait_local_agent.store import Store


def test_employee_onboarding_demo_composes_local_fixture_stages(settings) -> None:
    store = Store(settings.data_path)
    store.ingest_ticket_file(Path("examples/sample_tickets/tickets.json"))
    with store._connect() as connection:  # noqa: SLF001 - bind the isolated fixture tenant.
        connection.execute(
            "update tickets set client_id = ? where id = ?",
            ("acme", "TCK-1001"),
        )
    blueprint = json.loads(
        Path("examples/consultant/employee-onboarding-blueprint.json").read_text(encoding="utf-8")
    )

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
    assert len(stages["supervisor"]["children"]) == 7
    assert stages["evaluation"]["execution_started"] is True
    assert stages["evaluation"]["production_readiness"] == "pass"
    assert stages["governance"]["status"] == "needs_review"
    assert stages["delivery"]["production_readiness"] == "needs_review"
    assert stages["artifacts"]["status"] == "review_only"
    assert len(stages["artifacts"]["items"]) == 3
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
        "deployable_package_generated": False,
        "deployment_started": False,
        "production_deployment_requires_approval": True,
        "external_systems_require_environment_verification": True,
        "sensitive_operations_require_human_approval": True,
    }
    assert result["audit"]["agent_run_count"] == 8
    assert result["audit"]["audit_event_count"] > 0


def test_employee_onboarding_demo_requires_a_scoped_fixture_ticket(settings) -> None:
    with pytest.raises(EmployeeOnboardingDemoError, match="tenant-scoped ticket"):
        run_employee_onboarding_demo(
            store=Store(settings.data_path),
            settings=settings,
            blueprint_payload={},
        )


def test_employee_onboarding_demo_rejects_non_object_blueprint(settings) -> None:
    store = Store(settings.data_path)
    store.ingest_ticket_file(Path("examples/sample_tickets/tickets.json"))
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
    store.ingest_ticket_file(Path("examples/sample_tickets/tickets.json"))
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
