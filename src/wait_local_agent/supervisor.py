"""Tenant-scoped supervisor plans and bounded child-agent delegation."""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import replace
from typing import Any, Protocol, cast

from wait_local_agent.agents import AgentExecutionResult
from wait_local_agent.models import AgentDefinition, AgentRun
from wait_local_agent.rbac import Role
from wait_local_agent.reports.renderers import redact_text, redact_value
from wait_local_agent.store import Store

MAX_CHILD_AGENTS = 8
MAX_TASK_TEXT = 2_000
MAX_INPUT_KEYS = 16
MAX_INPUT_BYTES = 16_000
MAX_PRIOR_RESULTS = 3
MAX_RESULT_BYTES = 8_000
MAX_SUPERVISOR_RETRIES = 3
_IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9_.:-]{0,63}$")


class SupervisorPlanError(ValueError):
    """Raised when a supervisor delegation request is unsafe."""


class SupervisorAgentRunner(Protocol):
    def run(
        self,
        definition: AgentDefinition,
        *,
        entity_id: str,
        actor: str,
        input_payload: dict[str, object],
        supervisor_context: dict[str, object] | None = None,
        actor_role: Role | None = None,
    ) -> AgentExecutionResult:
        """Run one child through the existing bounded agent runtime."""

    def retry(
        self,
        definition: AgentDefinition,
        run: AgentRun,
        *,
        actor: str,
        actor_role: Role | None = None,
        supervisor_context: dict[str, object] | None = None,
    ) -> AgentExecutionResult:
        """Retry one failed child through the existing bounded runtime."""

    def cancel(
        self,
        definition: AgentDefinition,
        run: AgentRun,
        *,
        actor: str,
        approver_role: Role,
    ) -> AgentExecutionResult:
        """Cancel one queued or approval-paused child through the runtime."""


def build_supervisor_delegation_plan(
    *,
    client_id: str,
    task: str,
    child_agent_ids: list[str],
    definitions: Sequence[AgentDefinition],
    max_retries: int = 0,
) -> dict[str, Any]:
    tenant = _text(client_id, "client_id", 128)
    normalized_task = _text(task, "task", MAX_TASK_TEXT)
    retry_limit = _retry_limit(max_retries)
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
        "retry_policy": {
            "max_retries_per_child": retry_limit,
            "retryable_statuses": ["failed"],
            "attempts_are_lineage_bound": True,
        },
        "cancellation_policy": {
            "supported": True,
            "target": "queued_or_approval_paused_child_run_id",
            "stops_before_next_child": True,
        },
        "delegation_started": False,
        "execution_started": False,
        "approval_requests_created": False,
        "cross_tenant_context": False,
    }


def execute_supervisor_delegation(
    *,
    client_id: str,
    entity_id: str,
    task: str,
    child_agent_ids: list[str],
    definitions: Sequence[AgentDefinition],
    agent_service: SupervisorAgentRunner,
    store: Store,
    actor: str,
    actor_role: Role,
    input_payload: dict[str, object] | None = None,
    completed_run_ids: list[int] | None = None,
    max_retries: int = 0,
    cancel_run_id: int | None = None,
) -> dict[str, Any]:
    """Run selected child agents in dependency order using AgentService.

    The supervisor owns selection, ordering, bounded context passing, and
    stop/resume metadata. Child execution, approvals, persistence, retries,
    and audit records remain owned by the existing AgentService runtime.
    """

    if actor_role < Role.TECHNICIAN:
        raise SupervisorPlanError("supervisor execution requires technician authority")
    tenant = _text(client_id, "client_id", 128)
    normalized_entity_id = _text(entity_id, "entity_id", 100)
    normalized_task = _text(task, "task", MAX_TASK_TEXT)
    retry_limit = _retry_limit(max_retries)
    payload = _bounded_payload({} if input_payload is None else input_payload)
    plan = build_supervisor_delegation_plan(
        client_id=tenant,
        task=normalized_task,
        child_agent_ids=child_agent_ids,
        definitions=definitions,
        max_retries=retry_limit,
    )
    supervisor = cast(dict[str, object], plan["supervisor"])
    children = cast(list[dict[str, object]], supervisor["children"])
    selected_ids = [cast(str, child["id"]) for child in children]
    available = {definition.id: definition for definition in definitions}
    ordered_ids = _dependency_order(selected_ids, available)
    scoped_definitions = {
        agent_id: _scoped_definition(available[agent_id], tenant)
        for agent_id in selected_ids
    }
    for definition in scoped_definitions.values():
        if not definition.enabled:
            raise SupervisorPlanError(f"child agent is disabled: {definition.id}")

    cancellation_target: AgentRun | None = None
    if cancel_run_id is not None:
        if isinstance(cancel_run_id, bool) or not isinstance(cancel_run_id, int) or cancel_run_id < 1:
            raise SupervisorPlanError("cancel_run_id must be a positive integer")
        cancellation_target = store.get_agent_run(cancel_run_id, tenant)
        if (
            cancellation_target is None
            or cancellation_target.entity_id != normalized_entity_id
            or cancellation_target.agent_id not in selected_ids
        ):
            raise SupervisorPlanError("cancellation target is outside the supervisor scope")
        if cancellation_target.status not in {"queued", "pending_approval"}:
            raise SupervisorPlanError("cancellation target must be queued or approval-paused")

    completed = _load_completed_runs(
        completed_run_ids or [],
        store=store,
        selected_ids=set(selected_ids),
        entity_id=normalized_entity_id,
        client_id=tenant,
        definitions=scoped_definitions,
    )
    child_results: list[dict[str, object]] = []
    prior_by_agent: dict[str, dict[str, object]] = {}
    executed_count = 0
    approval_requests_created = False
    pending_run_id: int | None = None
    next_child_agent_id: str | None = None
    status = "completed"

    for index, agent_id in enumerate(ordered_ids):
        definition = scoped_definitions[agent_id]
        if agent_id in completed:
            summary = completed[agent_id]
            resumed_summary = {
                **summary,
                "sequence": index + 1,
                "resumed": True,
                "attempt": 1,
                "retry_of_run_id": None,
                "lineage": _lineage(agent_id, index + 1, 1),
            }
            child_results.append(resumed_summary)
            prior_by_agent[agent_id] = resumed_summary
            continue
        if cancellation_target is not None and cancellation_target.agent_id == agent_id:
            try:
                result = agent_service.cancel(
                    definition,
                    cancellation_target,
                    actor=actor,
                    approver_role=actor_role,
                )
            except Exception as exc:  # noqa: BLE001 - return a bounded orchestration failure
                message = redact_text(str(exc))[:500]
                child_results.append(
                    {
                        "agent_id": agent_id,
                        "sequence": index + 1,
                        "status": "failed",
                        "error_detail": message,
                        "resumed": False,
                        "lineage": _lineage(agent_id, index + 1, 1),
                    }
                )
                status = "failed"
                next_child_agent_id = agent_id
                break
            summary = _execution_summary(agent_id, result, index + 1, attempt=1)
            summary["attempts"] = [summary.copy()]
            summary["retry_count"] = 0
            child_results.append(summary)
            executed_count += 1
            status = "cancelled" if result.status == "cancelled" else "failed"
            next_child_agent_id = agent_id
            pending_run_id = result.run_id if result.status == "pending_approval" else None
            if result.approval_id is not None:
                approval_requests_created = True
            break
        supervisor_context: dict[str, object] = {
            "client_id": tenant,
            "task": normalized_task,
            "supervisor_id": "consultant-supervisor",
            "child_agent_id": agent_id,
            "sequence": index + 1,
            "attempt": 1,
            "prior_results": [
                prior_by_agent[dependency_id]
                for dependency_id in definition.depends_on_agent_ids
                if dependency_id in prior_by_agent
            ][:MAX_PRIOR_RESULTS],
        }
        try:
            result = agent_service.run(
                definition,
                entity_id=normalized_entity_id,
                actor=actor,
                input_payload=payload,
                supervisor_context=supervisor_context,
                actor_role=actor_role,
            )
        except Exception as exc:  # noqa: BLE001 - return a bounded orchestration failure
            message = redact_text(str(exc))[:500]
            summary = {
                "agent_id": agent_id,
                "sequence": index + 1,
                "status": "failed",
                "error_detail": message,
                "resumed": False,
                "attempt": 1,
                "retry_of_run_id": None,
                "lineage": _lineage(agent_id, index + 1, 1),
            }
            child_results.append(summary)
            status = "failed"
            next_child_agent_id = agent_id
            break
        executed_count += 1
        attempts = [_execution_summary(agent_id, result, index + 1, attempt=1)]
        if result.approval_id is not None:
            approval_requests_created = True
        while result.status == "failed" and len(attempts) <= retry_limit:
            prior_run = store.get_agent_run(result.run_id, tenant)
            if prior_run is None:
                attempts.append(
                    {
                        "agent_id": agent_id,
                        "run_id": result.run_id,
                        "sequence": index + 1,
                        "attempt": len(attempts) + 1,
                        "status": "failed",
                        "error_detail": "failed child run was not found for retry",
                        "resumed": False,
                        "lineage": _lineage(agent_id, index + 1, len(attempts) + 1, result.run_id),
                    }
                )
                break
            retry_context = {
                **supervisor_context,
                "attempt": len(attempts) + 1,
                "retry_of_run_id": prior_run.id,
            }
            try:
                result = agent_service.retry(
                    definition,
                    prior_run,
                    actor=actor,
                    actor_role=actor_role,
                    supervisor_context=retry_context,
                )
            except Exception as exc:  # noqa: BLE001 - return a bounded orchestration failure
                attempts.append(
                    {
                        "agent_id": agent_id,
                        "run_id": prior_run.id,
                        "sequence": index + 1,
                        "attempt": len(attempts) + 1,
                        "status": "failed",
                        "error_detail": redact_text(str(exc))[:500],
                        "resumed": False,
                        "retry_of_run_id": prior_run.id,
                        "lineage": _lineage(agent_id, index + 1, len(attempts) + 1, prior_run.id),
                    }
                )
                break
            executed_count += 1
            if result.approval_id is not None:
                approval_requests_created = True
            attempts.append(
                _execution_summary(
                    agent_id,
                    result,
                    index + 1,
                    attempt=len(attempts) + 1,
                    retry_of_run_id=prior_run.id,
                )
            )
        summary = {**attempts[-1], "attempts": attempts, "retry_count": len(attempts) - 1}
        child_results.append(summary)
        if result.status == "completed":
            prior_by_agent[agent_id] = summary
            continue
        status = "pending_approval" if result.status == "pending_approval" else "failed"
        if result.status == "cancelled":
            status = "cancelled"
        pending_run_id = result.run_id if result.status == "pending_approval" else None
        next_child_agent_id = agent_id
        break

    completed_ids = [
        cast(int, summary["run_id"])
        for summary in child_results
        if summary.get("status") == "completed" and isinstance(summary.get("run_id"), int)
    ]
    return {
        "format": "wait-local-agent.supervisor-execution",
        "format_version": 1,
        "client_id": tenant,
        "entity_id": normalized_entity_id,
        "status": status,
        "supervisor": {
            "id": "consultant-supervisor",
            "mode": "supervisor",
            "task": normalized_task,
            "ordered_child_agent_ids": ordered_ids,
            "lineage_contract": "supervisor_id, child_agent_id, sequence, attempt, and retry_of_run_id",
        },
        "children": child_results,
        "resumption": {
            "completed_run_ids": completed_ids,
            "pending_run_id": pending_run_id,
            "next_child_agent_id": next_child_agent_id,
        },
        "delegation_started": True,
        "execution_started": bool(executed_count or completed),
        "approval_requests_created": approval_requests_created,
        "retry_policy": {"max_retries_per_child": retry_limit, "retryable_statuses": ["failed"]},
        "cancellation": {
            "requested_run_id": cancel_run_id,
            "applied": status == "cancelled",
        },
        "cross_tenant_context": False,
    }


def _dependency_order(
    selected_ids: list[str],
    definitions: dict[str, AgentDefinition],
) -> list[str]:
    selected = set(selected_ids)
    order: list[str] = []
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(agent_id: str) -> None:
        if agent_id in visiting:
            raise SupervisorPlanError("selected child agents contain a dependency cycle")
        if agent_id in visited:
            return
        definition = definitions.get(agent_id)
        if definition is None:
            raise SupervisorPlanError(f"child agent was not found in tenant scope: {agent_id}")
        visiting.add(agent_id)
        for dependency_id in definition.depends_on_agent_ids:
            if dependency_id not in selected:
                raise SupervisorPlanError(
                    f"dependency agent must be selected for supervisor execution: {dependency_id}"
                )
            visit(dependency_id)
        visiting.remove(agent_id)
        visited.add(agent_id)
        order.append(agent_id)

    for agent_id in selected_ids:
        visit(agent_id)
    return order


def _scoped_definition(definition: AgentDefinition, client_id: str) -> AgentDefinition:
    if definition.client_id not in {None, client_id}:
        raise SupervisorPlanError("child agent is outside the tenant scope")
    return replace(definition, client_id=client_id) if definition.client_id is None else definition


def _bounded_payload(payload: dict[str, object]) -> dict[str, object]:
    if not isinstance(payload, dict) or len(payload) > MAX_INPUT_KEYS:
        raise SupervisorPlanError(f"input must contain at most {MAX_INPUT_KEYS} fields")
    if any(not isinstance(key, str) or not key.strip() or len(key) > 80 for key in payload):
        raise SupervisorPlanError("input field names must be non-empty text of at most 80 characters")
    safe = cast(dict[str, object], redact_value(payload))
    try:
        encoded = json.dumps(safe, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise SupervisorPlanError("input must contain JSON-compatible values") from exc
    if len(encoded) > MAX_INPUT_BYTES:
        raise SupervisorPlanError(f"input must be at most {MAX_INPUT_BYTES} bytes")
    return safe


def _load_completed_runs(
    run_ids: list[int],
    *,
    store: Store,
    selected_ids: set[str],
    entity_id: str,
    client_id: str,
    definitions: dict[str, AgentDefinition],
) -> dict[str, dict[str, object]]:
    if len(run_ids) > MAX_CHILD_AGENTS or any(
        isinstance(run_id, bool) or not isinstance(run_id, int) or run_id < 1 for run_id in run_ids
    ):
        raise SupervisorPlanError(f"completed_run_ids must contain 0-{MAX_CHILD_AGENTS} positive integers")
    if len(set(run_ids)) != len(run_ids):
        raise SupervisorPlanError("completed_run_ids must not contain duplicates")
    completed: dict[str, dict[str, object]] = {}
    for run_id in run_ids:
        run = store.get_agent_run(run_id, client_id)
        if run is None or run.entity_id != entity_id or run.agent_id not in selected_ids:
            raise SupervisorPlanError("completed child run is outside the supervisor scope")
        if run.status != "completed":
            raise SupervisorPlanError("completed child run must have completed status")
        definition = definitions[run.agent_id]
        if run.revision_version is not None and run.revision_version != definition.version:
            raise SupervisorPlanError("completed child run uses an outdated agent revision")
        try:
            state = json.loads(run.state_json)
        except json.JSONDecodeError as exc:
            raise SupervisorPlanError("completed child run state is malformed") from exc
        final_result = state.get("final_result", {}) if isinstance(state, dict) else {}
        summary: dict[str, object] = {
            "agent_id": run.agent_id,
            "run_id": run.id,
            "status": "completed",
            "current_step": run.current_step,
            "final_result": _bounded_final_result(final_result),
            "resumed": True,
        }
        completed[run.agent_id] = summary
    return completed


def _execution_summary(
    agent_id: str,
    result: AgentExecutionResult,
    sequence: int,
    *,
    attempt: int,
    retry_of_run_id: int | None = None,
) -> dict[str, object]:
    return {
        "agent_id": agent_id,
        "run_id": result.run_id,
        "sequence": sequence,
        "status": result.status,
        "current_step": result.current_step,
        "final_result": _bounded_final_result(result.final_result),
        "approval_id": result.approval_id,
        "error_detail": redact_text(result.error_detail)[:500],
        "resumed": False,
        "attempt": attempt,
        "retry_of_run_id": retry_of_run_id,
        "lineage": _lineage(agent_id, sequence, attempt, retry_of_run_id),
    }


def _lineage(
    agent_id: str,
    sequence: int,
    attempt: int,
    retry_of_run_id: int | None = None,
) -> dict[str, object]:
    return {
        "supervisor_id": "consultant-supervisor",
        "child_agent_id": agent_id,
        "sequence": sequence,
        "attempt": attempt,
        "retry_of_run_id": retry_of_run_id,
    }


def _retry_limit(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= MAX_SUPERVISOR_RETRIES:
        raise SupervisorPlanError(f"max_retries must be between 0 and {MAX_SUPERVISOR_RETRIES}")
    return value


def _bounded_final_result(value: object) -> dict[str, object]:
    safe = redact_value(value) if isinstance(value, dict) else {}
    if not isinstance(safe, dict):
        return {}
    try:
        encoded = json.dumps(safe, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError):
        return {"truncated": True}
    return safe if len(encoded) <= MAX_RESULT_BYTES else {"truncated": True}


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
