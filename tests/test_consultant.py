from __future__ import annotations

import json

import pytest

from wait_local_agent.consultant import BlueprintValidationError, blueprint_payload, parse_solution_blueprint
from wait_local_agent.store import Store


def _payload() -> dict[str, object]:
    return {
        "solution": {"name": "Employee Onboarding Agent"},
        "business_goal": {"reduce_manual_onboarding": True, "target_users": 500},
        "users": ["HR", "IT"],
        "knowledge": ["SharePoint HR Policies", "Employee Handbook"],
        "systems": ["Microsoft Entra", "Exchange Online", "Teams"],
        "agents": [
            {
                "id": "onboarding-supervisor",
                "name": "Onboarding supervisor",
                "purpose": "Coordinate the onboarding design",
                "tools": ["knowledge.search"],
                "knowledge": ["Employee Handbook"],
            }
        ],
        "workflows": [
            {
                "id": "create-user",
                "name": "Create user",
                "trigger": "HR submission",
                "steps": ["Validate manager", "Prepare account request"],
            }
        ],
        "approvals": {"create_user": "HR", "assign_license": "IT"},
        "deployment": ["Teams", "Microsoft 365 Copilot"],
        "risk": "medium",
    }


def test_blueprint_validation_and_store_round_trip(tmp_path) -> None:
    blueprint = parse_solution_blueprint(
        _payload(),
        client_id="acme",
        created_by="architect",
        blueprint_id="bp_test-1",
        now="2026-08-11T00:00:00+00:00",
    )
    store = Store(tmp_path / "state.db")
    persisted = store.create_solution_blueprint(blueprint)

    reopened = Store(tmp_path / "state.db")
    loaded = reopened.get_solution_blueprint("bp_test-1", client_id="acme")

    assert persisted == blueprint
    assert loaded is not None
    assert loaded == blueprint
    assert blueprint_payload(loaded) == _payload()
    assert [item.id for item in reopened.list_solution_blueprints(client_id="acme")] == ["bp_test-1"]
    assert reopened.get_solution_blueprint("bp_test-1", client_id="beta") is None
    assert any(
        event.event_type == "consultant.blueprint_created" and event.client_id == "acme"
        for event in reopened.list_audit_events(client_id="acme")
    )


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda payload: payload.update({"risk": "critical"}), "risk must be one of"),
        (lambda payload: payload["solution"].update({"secret": "nope"}), "unsupported solution fields"),
        (lambda payload: payload["approvals"].update({"bearer": "HR"}), "cannot contain secret material"),
        (lambda payload: payload["agents"].append(payload["agents"][0]), "agents ids must be unique"),
    ],
)
def test_blueprint_rejects_unsafe_or_ambiguous_shapes(change, message) -> None:
    payload = json.loads(json.dumps(_payload()))
    change(payload)

    with pytest.raises(BlueprintValidationError, match=message):
        parse_solution_blueprint(payload, client_id="acme", created_by="architect")


def test_blueprint_rejects_unbounded_collection_without_persisting(tmp_path) -> None:
    payload = _payload()
    payload["systems"] = [f"system-{index}" for index in range(33)]

    with pytest.raises(BlueprintValidationError, match="at most 32"):
        parse_solution_blueprint(payload, client_id="acme", created_by="architect")

    store = Store(tmp_path / "state.db")
    assert store.list_solution_blueprints(client_id="acme") == []
