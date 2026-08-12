from __future__ import annotations

from typing import Any, cast

import pytest

from wait_local_agent.power_apps import PowerAppsPlanError, build_power_apps_artifact, build_power_apps_plan


def _plan(**overrides: object) -> dict[str, Any]:
    payload: dict[str, object] = {
        "client_id": "acme",
        "app_name": "Onboarding workspace",
        "entities": [
            {
                "logical_name": "employee",
                "display_name": "Employee",
                "fields": [
                    {"name": "display_name", "type": "string", "required": True},
                    {"name": "start_date", "type": "date"},
                ],
            }
        ],
        "screens": [{"id": "employee_browse", "title": "Employees", "entity": "employee", "mode": "browse"}],
        "actions": [{"id": "employee_lookup", "connector_id": "m365", "method": "GET"}],
    }
    payload.update(overrides)
    return payload


def test_power_apps_plan_is_metadata_only_and_approval_aware() -> None:
    payload = _plan(
        actions=[
            {"id": "employee_lookup", "connector_id": "m365", "method": "GET"},
            {"id": "employee_create", "connector_id": "m365", "method": "POST", "approval_required": True},
        ]
    )
    result = build_power_apps_plan(**payload)

    assert result["format"] == "wait-local-agent.power-apps-plan"
    assert result["dataverse"]["tables"][0]["logical_name"] == "employee"
    assert result["canvas_app"]["screens"][0]["entity"] == "employee"
    assert result["requires_approval"] is True
    assert result["deployment_started"] is False
    assert result["dataverse_write_started"] is False


def test_power_apps_artifact_builds_bounded_reviewable_files_without_deployment() -> None:
    payload = _plan(
        screens=[
            {"id": "employee_browse", "title": "Employees", "entity": "employee", "mode": "browse"},
            {"id": "employee_edit", "title": "Edit employee", "entity": "employee", "mode": "edit"},
        ],
        actions=[
            {"id": "employee_lookup", "connector_id": "m365", "method": "GET"},
            {"id": "employee_create", "connector_id": "m365", "method": "POST", "approval_required": True},
        ],
    )
    result = build_power_apps_artifact(
        client_id=cast(str, payload["client_id"]),
        app_name=cast(str, payload["app_name"]),
        entities=cast(list[dict[str, object]], payload["entities"]),
        screens=cast(list[dict[str, object]], payload["screens"]),
        actions=cast(list[dict[str, object]], payload["actions"]),
    )
    solution = cast(dict[str, object], result["solution"])
    dataverse = cast(dict[str, object], result["dataverse"])
    tables = cast(list[dict[str, object]], dataverse["tables"])
    first_table = tables[0]
    columns = cast(list[dict[str, object]], first_table["columns"])
    canvas_app = cast(dict[str, object], result["canvas_app"])
    screens = cast(list[dict[str, object]], canvas_app["screens"])
    files = cast(list[dict[str, object]], result["files"])

    assert result["format"] == "wait-local-agent.power-apps-artifact"
    assert solution["publisher_prefix"] == "wait"
    assert columns[0]["type"] == "String"
    assert cast(list[dict[str, object]], screens[0]["controls"])[0]["type"] == "gallery"
    assert cast(list[dict[str, object]], screens[1]["controls"])[0]["type"] == "form"
    assert len(files) == 3
    assert result["credentials_included"] is False
    assert result["build_started"] is True
    assert result["deployment_started"] is False


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (
            lambda value: value.update(
                {"entities": [{"logical_name": "employee", "fields": [{"name": "api_token"}]}]}
            ),
            "secret material",
        ),
        (lambda value: value.update({"screens": [{"id": "home", "entity": "missing"}]}), "unknown entity"),
        (
            lambda value: value.update(
                {"actions": [{"id": "update", "connector_id": "m365", "method": "POST"}]}
            ),
            "requires approval",
        ),
        (
            lambda value: value.update(
                {"entities": [{"logical_name": "employee", "fields": [{"name": "status", "type": "object"}]}]}
            ),
            "field type",
        ),
        (lambda value: value.update({"screens": [{"id": "home", "entity": "employee", "mode": "run"}]}), "screen mode"),
    ],
)
def test_power_apps_plan_rejects_unsafe_or_incomplete_shapes(change, message) -> None:
    payload = _plan()
    change(payload)
    with pytest.raises(PowerAppsPlanError, match=message):
        build_power_apps_plan(**payload)


def test_power_apps_plan_rejects_duplicate_and_bounded_shapes() -> None:
    payload = _plan(entities=[{"logical_name": "employee", "fields": []}, {"logical_name": "employee", "fields": []}])
    with pytest.raises(PowerAppsPlanError, match="duplicate entity"):
        build_power_apps_plan(**payload)
    payload = _plan(entities=[{"logical_name": "employee", "fields": [{"name": "name"}, {"name": "name"}]}])
    with pytest.raises(PowerAppsPlanError, match="duplicate field"):
        build_power_apps_plan(**payload)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (
            lambda value: value.update(
                {"screens": [{"id": "home", "entity": "employee"}, {"id": "home", "entity": "employee"}]}
            ),
            "duplicate screen",
        ),
        (
            lambda value: value.update(
                {"actions": [{"id": "read", "connector_id": "m365"}, {"id": "read", "connector_id": "m365"}]}
            ),
            "duplicate action",
        ),
        (
            lambda value: value.update(
                {"actions": [{"id": "read", "connector_id": "m365", "method": "TRACE"}]}
            ),
            "action method",
        ),
        (
            lambda value: value.update(
                {"actions": [{"id": "read", "connector_id": "m365", "approval_required": "yes"}]}
            ),
            "approval_required",
        ),
        (lambda value: value.update({"entities": "bad"}), "entities must contain"),
        (lambda value: value.update({"entities": ["bad"]}), "entities must contain objects"),
        (
            lambda value: value.update({"entities": [{"logical_name": "Bad Name", "fields": []}]}),
            "lowercase identifier",
        ),
        (lambda value: value.update({"app_name": 42}), "non-empty text"),
        (lambda value: value.update({"app_name": "bad\napp"}), "control characters"),
    ],
)
def test_power_apps_plan_rejects_additional_boundaries(change, message) -> None:
    payload = _plan()
    change(payload)
    with pytest.raises(PowerAppsPlanError, match=message):
        build_power_apps_plan(**payload)
