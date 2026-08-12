"""Tenant-scoped supervisor and child-agent delegation plans."""

from __future__ import annotations

import re
from collections.abc import Sequence

from wait_local_agent.models import AgentDefinition

MAX_CHILD_AGENTS = 8
MAX_TASK_TEXT = 2_000
_IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9_.:-]{0,63}$")


class SupervisorPlanError(ValueError):
    """Raised when a supervisor delegation request is unsafe."""


def build_supervisor_delegation_plan(
    *,
    client_id: str,
    task: str,
    child_agent_ids: list[str],
    definitions: Sequence[AgentDefinition],
) -> dict[str, object]:
    tenant = _text(client_id, "client_id", 128)
    normalized_task = _text(task, "task", MAX_TASK_TEXT)
    if not isinstance(child_agent_ids, list) or not 1 <= len(child_agent_ids) <= MAX_CHILD_AGENTS:
        raise SupervisorPlanError(f"child_agent_ids must contain 1-{MAX_CHILD_AGENTS} items")
    normalized_ids = [_identifier(value, "child_agent_id") for value in child_agent_ids]
    if len(set(normalized_ids)) != len(normalized_ids):
        raise SupervisorPlanError("child_agent_ids must not contain duplicates")
    available = {definition.id: definition for definition in definitions}
    children: list[dict[str, object]] = []
    for child_id in normalized_ids:
        definition = available.get(child_id)
        if definition is None:
            raise SupervisorPlanError(f"child agent was not found in tenant scope: {child_id}")
        if definition.client_id not in {None, tenant}:
            raise SupervisorPlanError("child agent is outside the tenant scope")
        children.append(
            {
                "id": definition.id,
                "name": definition.name,
                "enabled": definition.enabled,
                "tool_ids": list(definition.enabled_tools),
                "depends_on_agent_ids": [
                    dependency_id
                    for dependency_id in definition.depends_on_agent_ids
                    if dependency_id in normalized_ids
                ],
                "context_policy": "tenant_scoped_task_and_structured_prior_results",
                "result_contract": {
                    "status": "completed|needs_approval|failed",
                    "evidence_refs": "bounded opaque references",
                    "summary": "bounded text",
                },
            }
        )
    return {
        "format": "wait-local-agent.supervisor-delegation-plan",
        "format_version": 1,
        "client_id": tenant,
        "supervisor": {
            "id": "consultant-supervisor",
            "mode": "supervisor",
            "task": normalized_task,
            "children": children,
            "selection": "explicit_child_agent_ids",
        },
        "assignments": [
            {
                "sequence": index,
                "child_agent_id": child["id"],
                "input_contract": {
                    "client_id": tenant,
                    "task": "bounded supervisor task",
                    "prior_results": "structured results from completed dependencies only",
                },
            }
            for index, child in enumerate(children, start=1)
        ],
        "context_policy": "pass only bounded structured results within the blueprint tenant",
        "delegation_started": False,
        "execution_started": False,
        "approval_requests_created": False,
        "cross_tenant_context": False,
    }


def _identifier(value: object, field: str) -> str:
    normalized = _text(value, field, 64).casefold()
    if not _IDENTIFIER.fullmatch(normalized):
        raise SupervisorPlanError(f"{field} must be a bounded identifier")
    return normalized


def _text(value: object, field: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        raise SupervisorPlanError(f"{field} must be non-empty text of at most {maximum} characters")
    normalized = value.strip()
    if any(ord(character) < 32 for character in normalized):
        raise SupervisorPlanError(f"{field} contains unsupported control characters")
    return normalized
