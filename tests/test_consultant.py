from __future__ import annotations

import json
from dataclasses import replace
from typing import cast

import pytest

from wait_local_agent.consultant import (
    BlueprintValidationError,
    blueprint_payload,
    blueprint_view,
    parse_solution_blueprint,
)
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
    assert reopened.get_solution_blueprint("bp_test-1") == blueprint
    assert [item.id for item in reopened.list_solution_blueprints()] == ["bp_test-1"]
    assert reopened.get_solution_blueprint("bp_test-1", client_id="beta") is None
    assert any(
        event.event_type == "consultant.blueprint_created" and event.client_id == "acme"
        for event in reopened.list_audit_events(client_id="acme")
    )

    with pytest.raises(ValueError, match="requires a client_id"):
        reopened.create_solution_blueprint(replace(blueprint, client_id=""))


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


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda payload: payload.update({"extra": True}), "unsupported blueprint fields"),
        (lambda payload: payload.pop("risk"), "missing blueprint fields"),
        (lambda payload: payload.update({"solution": "not-an-object"}), "solution must be an object"),
        (lambda payload: payload["solution"].update({"name": ""}), "solution.name must be non-empty"),
        (lambda payload: payload["solution"].update({"name": "x" * 241}), "solution.name exceeds"),
        (lambda payload: payload["solution"].update({"name": "safe\x01name"}), "control characters"),
        (lambda payload: payload["business_goal"].update({"nested": ["no"]}), "business_goal.nested"),
        (lambda payload: payload.update({"users": "not-an-array"}), "users must be an array"),
        (lambda payload: payload.update({"agents": "not-an-array"}), "agents must be an array"),
        (lambda payload: payload.update({"workflows": "not-an-array"}), "workflows must be an array"),
        (lambda payload: payload["approvals"].update({"x" * 65: "HR"}), "approval action"),
    ],
)
def test_blueprint_rejects_malformed_fields(mutate, message) -> None:
    payload = json.loads(json.dumps(_payload()))
    mutate(payload)

    with pytest.raises(BlueprintValidationError, match=message):
        parse_solution_blueprint(payload, client_id="acme", created_by="architect")


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("business_goal", {f"goal-{index}": True for index in range(33)}, "business_goal may contain"),
        ("agents", [_payload()["agents"][0] for _ in range(33)], "agents may contain"),
        ("workflows", [_payload()["workflows"][0] for _ in range(33)], "workflows may contain"),
        ("approvals", {f"action-{index}": "HR" for index in range(33)}, "approvals may contain"),
    ],
)
def test_blueprint_rejects_oversized_structured_fields(field, value, message) -> None:
    payload = _payload()
    payload[field] = value

    with pytest.raises(BlueprintValidationError, match=message):
        parse_solution_blueprint(payload, client_id="acme", created_by="architect")


def test_blueprint_accepts_text_business_goal() -> None:
    payload = _payload()
    payload["business_goal"] = {"description": "reduce manual work"}

    blueprint = parse_solution_blueprint(payload, client_id="acme", created_by="architect")

    assert blueprint.business_goal == {"description": "reduce manual work"}


def test_blueprint_view_includes_identity_and_payload() -> None:
    blueprint = parse_solution_blueprint(_payload(), client_id="acme", created_by="architect")

    view = blueprint_view(blueprint)

    assert view["id"] == blueprint.id
    assert view["solution"] == {"name": blueprint.solution_name}


def test_blueprint_store_rejects_malformed_legacy_row(tmp_path) -> None:
    store = Store(tmp_path / "state.db")
    blueprint = parse_solution_blueprint(_payload(), client_id="acme", created_by="architect")
    store.create_solution_blueprint(blueprint)
    with store._connect() as connection:  # noqa: SLF001
        connection.execute(
            "update solution_blueprints set payload_json = ? where id = ?",
            ("not-json", blueprint.id),
        )

    with pytest.raises(RuntimeError, match="malformed"):
        store.get_solution_blueprint(blueprint.id, client_id="acme")


def test_blueprint_store_reports_unexpected_missing_persistence(tmp_path, monkeypatch) -> None:
    store = Store(tmp_path / "state.db")
    blueprint = parse_solution_blueprint(_payload(), client_id="acme", created_by="architect")
    monkeypatch.setattr(store, "get_solution_blueprint", lambda *args, **kwargs: None)

    with pytest.raises(RuntimeError, match="was not persisted"):
        store.create_solution_blueprint(blueprint)


def test_blueprint_rejects_non_identifier_id_and_non_object_payload() -> None:
    with pytest.raises(BlueprintValidationError, match="JSON object"):
        parse_solution_blueprint(cast(object, []), client_id="acme", created_by="architect")
    with pytest.raises(BlueprintValidationError, match="lowercase identifier"):
        parse_solution_blueprint(
            _payload(), client_id="acme", created_by="architect", blueprint_id="Not Valid"
        )
