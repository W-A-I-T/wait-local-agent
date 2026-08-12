from __future__ import annotations

import pytest

from wait_local_agent.consultant_use_cases import UseCaseCatalogError, list_consultant_use_cases


def test_use_case_catalog_is_bounded_and_review_only() -> None:
    result = list_consultant_use_cases()

    assert result["format"] == "wait-local-agent.consultant-use-cases"
    assert result["execution_started"] is False
    assert result["deployment_started"] is False
    assert {case["category"] for case in result["use_cases"]} == {
        "m365",
        "teams",
        "power-apps",
        "multi-agent",
    }


def test_use_case_catalog_filters_without_exposing_mutable_source() -> None:
    result = list_consultant_use_cases("TEAMS")
    result["use_cases"][0]["title"] = "changed"

    fresh = list_consultant_use_cases("teams")
    assert len(fresh["use_cases"]) == 1
    assert fresh["use_cases"][0]["title"] == "Teams service-desk triage"


def test_use_case_catalog_rejects_unknown_category() -> None:
    with pytest.raises(UseCaseCatalogError, match="category must be one of"):
        list_consultant_use_cases("unknown")
