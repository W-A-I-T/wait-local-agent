from __future__ import annotations

import json
from dataclasses import replace
from typing import Any, cast

import pytest

from wait_local_agent.consultant import (
    BlueprintValidationError,
    _decision_for_component,
    architect_solution_blueprint,
    blueprint_payload,
    blueprint_view,
    parse_solution_blueprint,
    promote_discovery_candidate,
)
from wait_local_agent.discovery import build_solution_discovery
from wait_local_agent.store import Store
from wait_local_agent.workflows import list_workflow_templates


def _payload() -> dict[str, Any]:
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


def test_blueprint_round_trips_explicit_discovery_evidence_and_rejects_secrets() -> None:
    discovery = {
        "business_goal": "Reduce onboarding effort",
        "current_process": "HR emails IT",
        "owners": ["HR operations"],
        "approvers": ["IT manager"],
        "data_leaves_tenant": False,
    }
    blueprint = parse_solution_blueprint(
        {**_payload(), "discovery": discovery},
        client_id="acme",
        created_by="architect",
    )

    assert blueprint.discovery == discovery
    assert blueprint_payload(blueprint)["discovery"] == discovery
    with pytest.raises(BlueprintValidationError, match="secret material"):
        parse_solution_blueprint(
            {**_payload(), "discovery": {"business_goal": "token=secret"}},
            client_id="acme",
            created_by="architect",
        )


def test_discovery_candidate_promotion_normalizes_labels_and_preserves_evidence() -> None:
    answers = {
        "solution_name": "Employee onboarding",
        "business_goal": "Reduce manual onboarding work",
        "users": ["HR", "IT"],
        "knowledge": ["SharePoint HR policies"],
        "systems": ["Microsoft Entra", "Teams"],
        "reads": ["Employee record", "HR policy"],
        "changes": ["Create user", "Assign license"],
        "approvals": ["Assign license"],
        "failure_handling": "Pause and create an approval review",
        "licenses": ["Microsoft 365 E3"],
        "data_location": ["Tenant SharePoint"],
        "data_leaves_tenant": False,
    }
    candidate = build_solution_discovery(client_id="acme", answers=answers)["blueprint_candidate"]

    blueprint = promote_discovery_candidate(
        candidate,
        client_id="acme",
        solution_name="Employee onboarding review",
        risk="high",
        created_by="architect",
    )

    assert blueprint.solution_name == "Employee onboarding review"
    assert blueprint.risk == "high"
    assert blueprint.approvals == {"assign_license": "human_review_required"}
    assert blueprint.discovery["approvals"] == ["Assign license"]


@pytest.mark.parametrize(
    ("raw_action", "message"),
    [
        ("api_key", "secret material"),
        ("!!!", "usable identifier"),
        ("Assign\u0000license", "unsupported control characters"),
    ],
)
def test_discovery_candidate_promotion_rejects_unsafe_approval_labels(raw_action: str, message: str) -> None:
    candidate = {**_payload(), "approvals": {raw_action: "HR"}}
    with pytest.raises(BlueprintValidationError, match=message):
        promote_discovery_candidate(
            candidate,
            client_id="acme",
            solution_name="Onboarding",
            risk="medium",
            created_by="architect",
        )


@pytest.mark.parametrize(
    ("approvals", "message"),
    [
        ([], "must be an object"),
        ({1: "HR"}, "approval action must be text"),
        ({"Assign license": "HR", "assign_license": "IT"}, "identifiers collide"),
    ],
)
def test_discovery_candidate_promotion_rejects_invalid_approval_objects(
    approvals: object,
    message: str,
) -> None:
    candidate = {**_payload(), "approvals": approvals}
    with pytest.raises(BlueprintValidationError, match=message):
        promote_discovery_candidate(
            candidate,
            client_id="acme",
            solution_name="Onboarding",
            risk="medium",
            created_by="architect",
        )


def test_discovery_session_store_is_tenant_and_principal_scoped(tmp_path) -> None:
    store = Store(tmp_path / "state.db")
    session = store.create_consultant_discovery_session(
        client_id="acme",
        principal_id="technician-1",
        answers={"business_goal": "Reduce manual work"},
        transcript=[{"role": "user", "field": "business_goal", "content": "Reduce manual work"}],
    )

    reopened = Store(tmp_path / "state.db")
    loaded = reopened.get_consultant_discovery_session(
        session.id,
        client_id="acme",
        principal_id="technician-1",
    )
    assert loaded is not None
    assert json.loads(loaded.answers_json)["business_goal"] == "Reduce manual work"
    assert reopened.get_consultant_discovery_session(session.id, client_id="beta") is None
    assert (
        reopened.get_consultant_discovery_session(
            session.id,
            client_id="acme",
            principal_id="technician-2",
        )
        is None
    )
    updated = reopened.update_consultant_discovery_session(
        session.id,
        client_id="acme",
        principal_id="technician-1",
        status="completed",
        answers={"business_goal": "Reduce manual work", "users": ["HR"]},
        transcript=[{"role": "assistant", "content": "Who uses this?"}],
    )
    assert updated is not None
    assert updated.status == "completed"
    assert reopened.update_consultant_discovery_session(
        session.id,
        client_id="acme",
        principal_id="technician-1",
        status="active",
        answers={},
        transcript=[],
    ) is None

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
        (
            "agents",
            [cast(list[dict[str, object]], _payload()["agents"])[0] for _ in range(33)],
            "agents may contain",
        ),
        (
            "workflows",
            [cast(list[dict[str, object]], _payload()["workflows"])[0] for _ in range(33)],
            "workflows may contain",
        ),
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


def test_blueprint_supports_instructions_intents_skills_model_and_orchestration() -> None:
    payload = _payload()
    payload.update(
        {
            "instructions": "Use only grounded tenant evidence.",
            "intents": ["onboard_employee", "assign_license"],
            "skills": ["identity_lookup", "approval_request"],
            "model": "gpt-4.1",
            "orchestration": "supervisor",
        }
    )

    blueprint = parse_solution_blueprint(payload, client_id="acme", created_by="architect")

    assert blueprint.instructions == "Use only grounded tenant evidence."
    assert blueprint.intents == ("onboard_employee", "assign_license")
    assert blueprint.skills == ("identity_lookup", "approval_request")
    assert blueprint.model == "gpt-4.1"
    assert blueprint.orchestration == "supervisor"
    assert blueprint_payload(blueprint) == payload


def test_blueprint_rejects_unknown_orchestration_mode() -> None:
    payload = _payload()
    payload["orchestration"] = "unbounded"

    with pytest.raises(BlueprintValidationError, match="orchestration must be one of"):
        parse_solution_blueprint(payload, client_id="acme", created_by="architect")


def test_blueprint_view_includes_identity_and_payload() -> None:
    blueprint = parse_solution_blueprint(_payload(), client_id="acme", created_by="architect")

    view = blueprint_view(blueprint)

    assert view["id"] == blueprint.id
    assert view["solution"] == {"name": blueprint.solution_name}


def test_architect_resolves_existing_catalogs_and_reports_open_items() -> None:
    payload = _payload()
    payload["agents"][0]["tools"] = ["knowledge.search", "ticket-triage"]
    payload["workflows"][0]["id"] = "ticket-triage"
    payload["deployment"] = ["local", "Teams"]
    blueprint = parse_solution_blueprint(payload, client_id="acme", created_by="architect")

    architecture = architect_solution_blueprint(
        blueprint,
        available_tool_ids=["ticket-triage", "ticket-triage"],
        workflow_templates=list_workflow_templates(),
    )

    assert architecture["client_id"] == "acme"
    assert architecture["readiness"] == "needs_review"
    assert architecture["execution_started"] is False
    assert architecture["deployment_started"] is False
    assert architecture["supervisor"]["mode"] == "single_agent"
    agent = next(item for item in architecture["components"] if item["kind"] == "agent")
    assert agent["resolved_tool_ids"] == ["ticket-triage"]
    assert agent["unresolved_tool_ids"] == ["knowledge.search"]
    workflow = next(item for item in architecture["components"] if item["kind"] == "workflow")
    assert workflow["implementation"] == "existing_workflow_template"
    assert any(item["kind"] == "system_connector" for item in architecture["components"])
    assert any(item["component_id"] == "Teams" for item in architecture["open_items"])

    unresolved = architect_solution_blueprint(
        blueprint,
        available_tool_ids=[],
        workflow_templates=[],
    )
    assert any(
        item["kind"] == "workflow_template" and item["component_id"] == "ticket-triage"
        for item in unresolved["open_items"]
    )


def test_blueprint_round_trip_preserves_environment_evidence_and_architecture_boundary() -> None:
    payload = {
        **_payload(),
        "environment": [
            {
                "id": "m365",
                "name": "Microsoft 365 / Entra",
                "kind": "m365",
                "connector_id": "m365",
                "status": "configured",
                "evidence": ["local_connector_configuration"],
                "limitation": "provider authorization is unknown",
                "tenant_scope": "acme",
                "http_probing_enabled": False,
            }
        ],
    }
    blueprint = parse_solution_blueprint(payload, client_id="acme", created_by="architect")
    architecture = architect_solution_blueprint(
        blueprint,
        available_tool_ids=[],
        workflow_templates=[],
    )

    assert blueprint.environment[0]["status"] == "configured"
    environment_component = next(item for item in architecture["components"] if item["kind"] == "environment")
    assert environment_component["status"] == "needs_review"
    assert any(item["kind"] == "environment" for item in architecture["open_items"])


def test_architect_decisions_resolve_verified_environment_and_remain_reviewable() -> None:
    payload = {
        **_payload(),
        "knowledge": [],
        "systems": ["Microsoft 365"],
        "agents": [],
        "workflows": [],
        "deployment": ["local"],
        "environment": [
            {
                "id": "m365",
                "name": "Microsoft 365 / Entra",
                "kind": "m365",
                "connector_id": "m365",
                "status": "authorized",
                "evidence": ["provider_authorization_result"],
                "tenant_scope": "acme",
            }
        ],
    }
    blueprint = parse_solution_blueprint(payload, client_id="acme", created_by="architect")

    architecture = architect_solution_blueprint(
        blueprint,
        available_tool_ids=[],
        workflow_templates=[],
    )

    assert architecture["readiness"] == "ready"
    assert architecture["decision_engine"]["inference_started"] is False
    assert architecture["decision_engine"]["execution_started"] is False
    decisions = {item["component_id"]: item for item in architecture["decisions"]}
    assert decisions["Microsoft 365"]["chosen_target"] == "microsoft_graph"
    assert decisions["Microsoft 365"]["status"] == "ready"
    assert decisions["local"]["chosen_target"] == "wait_agent"
    for decision in architecture["decisions"]:
        assert "alternatives_considered" in decision
        assert "required_permissions" in decision
        assert "licenses" in decision
        assert "testing_requirements" in decision
        assert "deployment_requirements" in decision


def test_architect_decision_engine_maps_targets_and_unknowns() -> None:
    payload = {
        **_payload(),
        "knowledge": [],
        "systems": [],
        "agents": [],
        "workflows": [
            {
                "id": "inactive-ticket-follow-up",
                "name": "Follow up",
                "trigger": "schedule.daily",
                "steps": ["Prepare follow-up"],
            }
        ],
        "deployment": ["local", "Power Automate", "Power Apps", "Dataverse", "custom-cloud"],
    }
    blueprint = parse_solution_blueprint(payload, client_id="acme", created_by="architect")

    architecture = architect_solution_blueprint(
        blueprint,
        available_tool_ids=[],
        workflow_templates=list_workflow_templates(),
    )
    decisions = {item["component_id"]: item for item in architecture["decisions"]}

    assert "communication-send" in decisions["inactive-ticket-follow-up"]["dependencies"]
    assert "workflow_template: approval required by local template" in decisions[
        "inactive-ticket-follow-up"
    ]["approval_requirements"]
    assert decisions["Power Automate"]["chosen_target"] == "power_automate"
    assert decisions["Power Apps"]["chosen_target"] == "power_app"
    assert decisions["Dataverse"]["chosen_target"] == "dataverse"
    assert decisions["custom-cloud"]["status"] == "needs_review"

    fallback = _decision_for_component(
        blueprint,
        {"id": "unknown", "kind": "unknown", "name": "Unknown", "status": "needs_review"},
        {},
    )
    assert fallback["chosen_target"] == "unsupported"
    assert fallback["status"] == "needs_review"


def test_architect_decision_engine_maps_connector_families_and_unknown_target() -> None:
    payload = {
        **_payload(),
        "knowledge": [],
        "systems": ["ConnectWise", "NinjaOne", "Hudu", "Custom system"],
        "agents": [],
        "workflows": [],
        "deployment": ["local"],
        "environment": [
            {
                "id": "connectwise",
                "name": "ConnectWise",
                "kind": "psa",
                "connector_id": "connectwise",
                "status": "authorized",
                "evidence": ["provider_authorization_result"],
            },
            {
                "id": "rmm",
                "name": "NinjaOne",
                "kind": "rmm",
                "connector_id": "rmm",
                "status": "authorized",
                "evidence": ["provider_authorization_result"],
            },
            {
                "id": "hudu",
                "name": "Hudu",
                "kind": "documentation",
                "connector_id": "hudu",
                "status": "authorized",
                "evidence": ["provider_authorization_result"],
            },
            {
                "id": "custom",
                "name": "Custom system",
                "kind": "custom",
                "connector_id": "custom",
                "status": "authorized",
                "evidence": ["provider_authorization_result"],
            },
        ],
    }
    blueprint = parse_solution_blueprint(payload, client_id="acme", created_by="architect")

    architecture = architect_solution_blueprint(
        blueprint,
        available_tool_ids=[],
        workflow_templates=[],
    )
    decisions = {item["component_id"]: item for item in architecture["decisions"]}

    assert decisions["ConnectWise"]["chosen_target"] == "psa"
    assert decisions["NinjaOne"]["chosen_target"] == "rmm"
    assert decisions["Hudu"]["chosen_target"] == "mcp"
    assert decisions["Custom system"]["status"] == "needs_review"


def test_blueprint_environment_contract_rejects_malformed_records() -> None:
    cases = [
        ([{"id": "m365"}], r"environment\[0\].status"),
        ([{"id": "m365", "name": "M365", "kind": "m365", "status": "nope"}], "unsupported"),
        (
            [
                {
                    "id": "m365",
                    "name": "M365",
                    "kind": "m365",
                    "status": "configured",
                    "evidence": [],
                    "http_probing_enabled": "yes",
                }
            ],
            "must be boolean",
        ),
        (
            [
                {"id": "m365", "name": "M365", "kind": "m365", "status": "configured"},
                {"id": "m365", "name": "M365 again", "kind": "m365", "status": "configured"},
            ],
            "duplicate id",
        ),
        (
            [
                {
                    "id": "m365",
                    "name": "M365",
                    "kind": "m365",
                    "status": "configured",
                    "tenant_scope": "beta",
                }
            ],
            "outside the blueprint tenant",
        ),
    ]
    for environment, message in cases:
        payload = {**_payload(), "environment": environment}
        with pytest.raises(BlueprintValidationError, match=message):
            parse_solution_blueprint(payload, client_id="acme", created_by="architect")

    with pytest.raises(BlueprintValidationError, match="environment must be an array"):
        parse_solution_blueprint({**_payload(), "environment": {}}, client_id="acme", created_by="architect")
    with pytest.raises(BlueprintValidationError, match="at most 32"):
        oversized_environment = [
            {
                "id": f"env-{index}",
                "name": "M365",
                "kind": "m365",
                "status": "configured",
            }
            for index in range(33)
        ]
        parse_solution_blueprint(
            {**_payload(), "environment": oversized_environment},
            client_id="acme",
            created_by="architect",
        )


def test_architect_can_be_ready_for_empty_local_design() -> None:
    payload = _payload()
    payload.update(
        {
            "knowledge": [],
            "systems": [],
            "agents": [],
            "workflows": [],
            "deployment": ["local", "api", "cli", "agents", "mcp"],
        }
    )
    blueprint = parse_solution_blueprint(payload, client_id="acme", created_by="architect")

    architecture = architect_solution_blueprint(
        blueprint,
        available_tool_ids=[],
        workflow_templates=[],
    )

    assert architecture["readiness"] == "ready"
    assert architecture["open_items"] == []


def test_architect_describes_multi_agent_supervisor_boundary() -> None:
    payload = _payload()
    payload["agents"].append(
        {
            "id": "security-reviewer",
            "name": "Security reviewer",
            "purpose": "Review onboarding risk",
            "tools": [],
            "knowledge": ["Employee Handbook"],
        }
    )
    blueprint = parse_solution_blueprint(payload, client_id="acme", created_by="architect")

    architecture = architect_solution_blueprint(
        blueprint,
        available_tool_ids=[],
        workflow_templates=[],
    )

    supervisor = architecture["supervisor"]
    assert supervisor["mode"] == "supervisor"
    assert [child["kind"] for child in supervisor["children"]] == ["child_agent", "child_agent"]
    assert all(
        child["context_policy"] == "tenant_scoped_structured_result_only"
        for child in supervisor["children"]
    )
    assert supervisor["execution_started"] is False


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
        parse_solution_blueprint(cast(dict[str, object], []), client_id="acme", created_by="architect")
    with pytest.raises(BlueprintValidationError, match="lowercase identifier"):
        parse_solution_blueprint(
            _payload(), client_id="acme", created_by="architect", blueprint_id="Not Valid"
        )
