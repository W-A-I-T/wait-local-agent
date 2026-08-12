from __future__ import annotations

import pytest

from wait_local_agent.environment import EnvironmentDiscoveryError, discover_environment
from wait_local_agent.models import ConnectorStatus


def _status(
    connector_id: str,
    name: str,
    status: str,
    *,
    probing: bool = False,
) -> ConnectorStatus:
    return ConnectorStatus(
        id=connector_id,
        kind="m365" if connector_id == "m365" else "psa",
        name=name,
        status=status,  # type: ignore[arg-type]
        message="fixture",
        http_probing_enabled=probing,
    )


def test_environment_discovery_preserves_unknown_and_local_policy_boundaries() -> None:
    result = discover_environment(
        client_id="acme",
        requested_systems=["Microsoft 365", "HaloPSA", "NinjaOne", "Customer custom API"],
        connector_statuses=[
            _status("m365", "Microsoft 365 / Entra", "configured"),
            _status("halopsa", "HaloPSA", "blocked"),
            _status("rmm", "NinjaOne RMM", "not_configured"),
        ],
        configured_client_id="acme",
    )

    systems = {item["name"]: item for item in result["systems"]}
    assert len(result["systems"]) == 4
    assert systems["Microsoft 365"]["status"] == "configured"
    assert "not been probed" in systems["Microsoft 365"]["limitation"]
    assert systems["HaloPSA"]["status"] == "permission-limited"
    assert "provider authorization is unknown" in systems["HaloPSA"]["limitation"]
    assert systems["NinjaOne"]["status"] == "not_configured"
    assert systems["Customer custom API"]["status"] == "detected"
    assert result["probe_performed"] is False
    assert result["readiness"] == "needs_environment_verification"


def test_environment_discovery_does_not_claim_other_tenant_configuration() -> None:
    result = discover_environment(
        client_id="acme",
        requested_systems=["Microsoft 365"],
        connector_statuses=[_status("m365", "Microsoft 365 / Entra", "configured")],
        configured_client_id="beta",
    )

    system = result["systems"][0]
    assert system["status"] == "permission-limited"
    assert "not explicitly bound" in system["limitation"]


def test_environment_discovery_preserves_failed_connector_as_unavailable() -> None:
    result = discover_environment(
        client_id="acme",
        requested_systems=["ConnectWise"],
        connector_statuses=[_status("connectwise", "ConnectWise", "failed")],
        configured_client_id="acme",
    )

    system = result["systems"][0]
    assert system["status"] == "unavailable"
    assert "not being treated as an empty environment" in system["limitation"]
    assert result["readiness"] == "needs_environment_verification"


def test_environment_discovery_deduplicates_aliases_and_projects_unrequested_ready_connector() -> None:
    result = discover_environment(
        client_id="acme",
        requested_systems=["Microsoft 365", "Microsoft 365", "IT Glue"],
        connector_statuses=[
            _status("m365", "Microsoft 365 / Entra", "configured"),
            _status("hudu", "Hudu", "ready"),
            _status("itglue", "IT Glue", "offline"),
            _status("connectwise", "ConnectWise", "offline"),
            _status("syncro", "Syncro", "not_configured"),
        ],
        configured_client_id="acme",
    )

    assert [item["name"] for item in result["systems"]] == [
        "Microsoft 365",
        "IT Glue",
        "Hudu",
    ]
    assert result["systems"][1]["status"] == "unknown"
    assert result["systems"][2]["status"] == "configured"
    assert result["systems"][2]["provider_status"] == "ready"


@pytest.mark.parametrize(
    "systems",
    ["Microsoft 365", list(range(33)), [""]],
)
def test_environment_discovery_rejects_invalid_system_declarations(systems) -> None:
    with pytest.raises(EnvironmentDiscoveryError):
        discover_environment(
            client_id="acme",
            requested_systems=systems,
            connector_statuses=[],
        )


@pytest.mark.parametrize("systems", [["api_key=secret"], ["bad\nvalue"]])
def test_environment_discovery_rejects_secret_or_control_material(systems) -> None:
    with pytest.raises(EnvironmentDiscoveryError):
        discover_environment(
            client_id="acme",
            requested_systems=systems,
            connector_statuses=[],
        )
