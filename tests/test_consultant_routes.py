from __future__ import annotations

import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute

from wait_local_agent.api.app import (
    DeliveryPlanRequest,
    DiscoveryRequest,
    PowerAppsPlanRequest,
    PowerAutomatePlanRequest,
    create_app,
)
from wait_local_agent.rbac import AuthContext, Role


def _endpoint(settings, path: str):
    app = create_app(settings)
    return next(
        route.endpoint
        for route in app.routes
        if isinstance(route, APIRoute) and route.path == path and route.methods and "POST" in route.methods
    )


def _technician(client_id: str = "acme") -> AuthContext:
    return AuthContext(role=Role.TECHNICIAN, presented_token="tech-token", client_id=client_id)


def test_consultant_planning_routes_are_directly_callable_and_review_only(settings) -> None:
    discovery = _endpoint(settings, "/consultant/discovery")(
        DiscoveryRequest(
            client_id="acme",
            answers={
                "business_goal": "Reduce onboarding effort",
                "users": ["HR"],
                "knowledge": ["Handbook"],
                "systems": ["Entra"],
                "reads": ["Employee"],
                "changes": ["Create user"],
                "approvals": ["Create user"],
                "failure_handling": "Pause",
                "data_location": ["SharePoint"],
                "data_leaves_tenant": False,
            },
        ),
        _technician(),
    )
    power_apps = _endpoint(settings, "/consultant/power-apps/plan")(
        PowerAppsPlanRequest(
            client_id="acme",
            app_name="Onboarding",
            entities=[{"logical_name": "employee", "fields": []}],
            screens=[{"id": "browse", "entity": "employee"}],
            actions=[{"id": "lookup", "connector_id": "m365", "method": "GET"}],
        ),
        _technician(),
    )
    flow = _endpoint(settings, "/consultant/workflows/power-automate/plan")(
        PowerAutomatePlanRequest(
            client_id="acme",
            workflow_id="onboarding",
            workflow_name="Onboarding",
            trigger="HR request",
            steps=[{"id": "review", "name": "Review", "kind": "approval"}],
        ),
        _technician(),
    )
    delivery = _endpoint(settings, "/consultant/delivery-plan")(
        DeliveryPlanRequest(
            client_id="acme",
            architecture={"client_id": "acme", "readiness": "ready", "components": [], "approval_policy": {}},
            evaluation={"production_readiness": "pass", "case_count": 1},
            governance={"client_id": "acme", "status": "pass"},
            deployment_targets=["Teams"],
        ),
        _technician(),
    )

    assert discovery["readiness"] == "ready_for_architecture"
    assert power_apps["dataverse_write_started"] is False
    assert flow["export_status"] == "review_only"
    assert delivery["production_deployment_requires_approval"] is True


def test_consultant_planning_routes_reject_foreign_tenant(settings) -> None:
    with pytest.raises(HTTPException, match="outside authenticated scope"):
        _endpoint(settings, "/consultant/discovery")(
            DiscoveryRequest(client_id="beta", answers={}),
            _technician("acme"),
        )
