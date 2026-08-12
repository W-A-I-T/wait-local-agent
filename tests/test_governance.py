from __future__ import annotations

import pytest

from wait_local_agent.governance import GovernanceValidationError, evaluate_solution_governance


def _architecture(*, ready: bool = True, with_system: bool = False) -> dict[str, object]:
    return {
        "client_id": "acme",
        "readiness": "ready" if ready else "needs_review",
        "components": [{"id": "entra", "kind": "system_connector"}] if with_system else [],
        "open_items": [] if ready else [{"kind": "tool", "component_id": "agent", "detail": "review"}],
    }


def _connector(*, write: bool = False, credentials: bool = False) -> dict[str, object]:
    return {
        "connector_id": "example",
        "host": "api.example.test",
        "credentials_included": credentials,
        "authentication": [{"type": "apiKey"}],
        "actions": [{"id": "read", "method": "GET"}]
        + ([{"id": "update", "method": "POST"}] if write else []),
    }


def test_governance_passes_reviewed_read_only_architecture() -> None:
    result = evaluate_solution_governance(
        _architecture(),
        [
            {
                "connector_id": "example",
                "host": "api.example.test",
                "actions": [{"id": "read", "method": "GET"}],
                "authentication": [],
                "credentials_included": False,
            }
        ],
    )

    assert result["status"] == "pass"
    assert result["finding_counts"] == {"high": 0, "medium": 0, "info": 0}
    assert result["authorization_changed"] is False
    assert result["execution_started"] is False
    assert result["connectors"][0]["review_status"] == "reviewed_read_only"


def test_governance_flags_open_system_auth_write_and_credentials() -> None:
    result = evaluate_solution_governance(
        _architecture(ready=False, with_system=True),
        [_connector(write=True, credentials=True)],
    )

    codes = {finding["code"] for finding in result["findings"]}
    assert result["status"] == "needs_review"
    assert {
        "architecture_review_required",
        "external_boundary_review",
        "credential_material_present",
        "write_approval_boundary_required",
    } <= codes
    assert result["finding_counts"]["high"] == 2
    assert result["connectors"][0]["write_action_ids"] == ["update"]


@pytest.mark.parametrize(
    ("architecture", "connectors", "message"),
    [
        ({"components": "bad"}, [], "client_id"),
        ({"client_id": "acme", "components": "bad"}, [], "components must be an array"),
        ({"client_id": "acme", "components": ["bad"]}, [], "components must contain objects"),
        (_architecture(), [{"actions": []}], "connector_id"),
    ],
)
def test_governance_rejects_malformed_inputs(architecture, connectors, message) -> None:
    with pytest.raises(GovernanceValidationError, match=message):
        evaluate_solution_governance(architecture, connectors)


def test_governance_rejects_unbounded_inputs() -> None:
    with pytest.raises(GovernanceValidationError, match="exceeds"):
        evaluate_solution_governance({"client_id": "acme", "components": [{"x": "x" * 100_001}]})


def test_governance_rejects_connector_count_and_non_json_inputs() -> None:
    with pytest.raises(GovernanceValidationError, match="at most"):
        evaluate_solution_governance(_architecture(), [{"connector_id": str(index)} for index in range(17)])
    with pytest.raises(GovernanceValidationError, match="JSON serializable"):
        evaluate_solution_governance({"client_id": object()})


def test_governance_covers_non_system_components_and_unsafe_hosts() -> None:
    result = evaluate_solution_governance(
        {"client_id": "acme", "readiness": "ready", "components": [{"kind": "agent"}]},
        [
            {"connector_id": "example", "host": "bad\nhost", "actions": [], "authentication": []},
            {"connector_id": "missing-host", "actions": [], "authentication": []},
        ],
    )
    assert result["connectors"][0]["host"] is None
    assert result["connectors"][1]["host"] is None
