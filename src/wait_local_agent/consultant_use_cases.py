"""Read-only Microsoft consultant use-case catalog."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

MAX_USE_CASES = 16
_CATEGORIES = {"m365", "teams", "power-apps", "multi-agent"}

_USE_CASES: tuple[dict[str, object], ...] = (
    {
        "id": "m365-employee-onboarding",
        "title": "Employee onboarding coordinator",
        "category": "m365",
        "business_goal": "Coordinate identity, license, and knowledge steps for a new employee.",
        "services": ["Microsoft Entra", "Microsoft Graph", "SharePoint"],
        "agent_roles": ["intake", "identity", "knowledge", "supervisor"],
        "outputs": ["tenant-scoped plan", "approval requests", "audit evidence"],
        "approval_boundaries": ["identity writes", "license changes", "external notifications"],
    },
    {
        "id": "teams-ticket-triage",
        "title": "Teams service-desk triage",
        "category": "teams",
        "business_goal": "Turn a technician request into a bounded ticket triage and response plan.",
        "services": ["Microsoft Teams", "PSA", "Microsoft Graph"],
        "agent_roles": ["intake", "ticket-triage", "knowledge", "supervisor"],
        "outputs": ["ticket classification", "draft response", "approval preview"],
        "approval_boundaries": ["ticket writes", "message delivery", "device actions"],
    },
    {
        "id": "sharepoint-knowledge-assistant",
        "title": "SharePoint knowledge assistant",
        "category": "m365",
        "business_goal": "Answer operational questions from bounded SharePoint and local evidence.",
        "services": ["SharePoint", "Microsoft Graph", "local knowledge"],
        "agent_roles": ["retrieval", "citation", "supervisor"],
        "outputs": ["evidence-backed answer", "source references", "review status"],
        "approval_boundaries": ["document writes", "external sharing", "message delivery"],
    },
    {
        "id": "power-apps-approval-workflow",
        "title": "Power Apps approval workspace",
        "category": "power-apps",
        "business_goal": "Design a Canvas App and Dataverse metadata plan around a governed approval process.",
        "services": ["Power Apps", "Dataverse", "Power Platform connectors"],
        "agent_roles": ["architect", "dataverse", "connector", "governance"],
        "outputs": ["table plan", "screen plan", "connector references", "governance findings"],
        "approval_boundaries": ["Dataverse writes", "connector writes", "solution deployment"],
    },
    {
        "id": "multi-agent-service-desk",
        "title": "Multi-agent service-desk supervisor",
        "category": "multi-agent",
        "business_goal": "Coordinate specialist agents while retaining one bounded supervisor decision point.",
        "services": ["WAIT Local Agent", "PSA", "Microsoft 365"],
        "agent_roles": ["supervisor", "triage", "knowledge", "executor"],
        "outputs": ["delegation plan", "specialist results", "approval queue", "audit trail"],
        "approval_boundaries": ["all state-changing tools", "cross-tenant access", "deployment"],
    },
)


class UseCaseCatalogError(ValueError):
    """Raised when a use-case catalog request is invalid."""


def list_consultant_use_cases(category: str | None = None) -> dict[str, Any]:
    """Return a bounded, static catalog without tenant data or execution."""

    if category is not None:
        normalized = category.strip().casefold()
        if normalized not in _CATEGORIES:
            raise UseCaseCatalogError(f"category must be one of: {', '.join(sorted(_CATEGORIES))}")
    else:
        normalized = None
    cases = [
        deepcopy(case)
        for case in _USE_CASES
        if normalized is None or case["category"] == normalized
    ]
    if len(cases) > MAX_USE_CASES:
        raise UseCaseCatalogError("use-case catalog exceeds the configured bound")
    return {
        "format": "wait-local-agent.consultant-use-cases",
        "format_version": 1,
        "category": normalized,
        "execution_started": False,
        "deployment_started": False,
        "use_cases": cases,
    }
