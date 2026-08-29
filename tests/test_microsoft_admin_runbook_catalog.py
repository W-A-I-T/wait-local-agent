from __future__ import annotations

from collections.abc import Callable
from typing import cast

import pytest

from packs.microsoft_admin.runbooks import (
    RunbookError,
    build_runbook_plan,
    runbook_catalog,
    validate_runbook_plan,
)


def test_runbook_catalog_and_plan_are_fixed_digest_bound_and_deterministic() -> None:
    catalog = runbook_catalog()
    assert [item["runbook_id"] for item in catalog] == [
        "windows.endpoint_health",
        "windows.service_restart",
    ]
    assert all(item["approval_required"] is True for item in catalog)
    assert all("script" not in item for item in catalog)

    first = build_runbook_plan(
        "windows.endpoint_health",
        {"event_hours": 12},
        client_id="client-1",
    )
    second = build_runbook_plan(
        "windows.endpoint_health",
        {"event_hours": 12},
        client_id="client-1",
    )
    assert first == second
    assert first["parameters"] == {
        "include_event_logs": True,
        "event_hours": 12,
        "max_events": 25,
    }
    assert cast(str, first["plan_digest"]).startswith("sha256:")
    assert validate_runbook_plan(first, expected_client_id="client-1") == first

    tampered = dict(first)
    tampered["risk_level"] = 5
    with pytest.raises(RunbookError, match="no longer matches"):
        validate_runbook_plan(tampered)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda plan: plan.pop("title"), "unsupported schema"),
        (lambda plan: plan.__setitem__("format", "unsupported"), "format is unsupported"),
        (lambda plan: plan.__setitem__("runbook_id", 7), "runbook ID is invalid"),
        (lambda plan: plan.__setitem__("client_id", 7), "client ID is invalid"),
        (lambda plan: plan.__setitem__("parameters", []), "parameters are invalid"),
    ],
)
def test_validate_runbook_plan_rejects_malformed_stored_payloads(
    mutation: Callable[[dict[str, object]], object],
    message: str,
) -> None:
    plan = build_runbook_plan("windows.endpoint_health", {}, client_id="client-1")
    mutation(plan)
    with pytest.raises(RunbookError, match=message):
        validate_runbook_plan(plan)


def test_validate_runbook_plan_rejects_cross_tenant_reuse() -> None:
    plan = build_runbook_plan("windows.endpoint_health", {}, client_id="client-1")
    with pytest.raises(RunbookError, match="different tenant"):
        validate_runbook_plan(plan, expected_client_id="client-2")


@pytest.mark.parametrize(
    ("runbook_id", "parameters", "client_id", "message"),
    [
        ("unknown", {}, "client-1", "Unknown"),
        ("windows.endpoint_health", {f"p{index}": index for index in range(17)}, "client-1", "Too many"),
        ("windows.endpoint_health", {"unknown": True}, "client-1", "Unsupported"),
        ("windows.endpoint_health", {"include_event_logs": "yes"}, "client-1", "must be boolean"),
        ("windows.endpoint_health", {"event_hours": True}, "client-1", "must be an integer"),
        ("windows.endpoint_health", {"event_hours": 0}, "client-1", "below its minimum"),
        ("windows.endpoint_health", {"max_events": 101}, "client-1", "exceeds its maximum"),
        ("windows.service_restart", {"service_name": 7}, "client-1", "bounded string"),
        ("windows.service_restart", {"service_name": "Spooler"}, "client-1", "not allowlisted"),
        ("windows.endpoint_health", {}, "", "client ID is invalid"),
        ("windows.endpoint_health", {}, "x" * 129, "client ID is invalid"),
        ("windows.endpoint_health", {}, "client\n1", "client ID is invalid"),
    ],
)
def test_runbook_parameter_validation_fails_closed(
    runbook_id: str,
    parameters: dict[str, object],
    client_id: str,
    message: str,
) -> None:
    with pytest.raises(RunbookError, match=message):
        build_runbook_plan(runbook_id, parameters, client_id=client_id)


def test_runbook_parameter_names_must_be_strings() -> None:
    with pytest.raises(RunbookError, match="names must be strings"):
        build_runbook_plan(
            "windows.endpoint_health",
            cast(dict[str, object], {1: True}),
            client_id="client-1",
        )
