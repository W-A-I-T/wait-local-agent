"""Small, bounded agent definitions built on the existing smart-action runtime.

This module intentionally does not introduce a general-purpose agent framework.
Definitions contain a short, explicit list of existing smart actions. The
executor validates that list, delegates action execution (including approvals)
to ``SmartActionService``, and groups the resulting steps in the existing
execution-observability tables.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import cast
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from wait_local_agent.config import Settings
from wait_local_agent.models import AgentDefinition, AgentRun, utc_now
from wait_local_agent.observability import ExecutionRecorder, StepRecord
from wait_local_agent.rbac import Role
from wait_local_agent.reports.renderers import redact_value
from wait_local_agent.smart_actions import ActionResult, SmartActionService
from wait_local_agent.store import Store, _normalize_client_id

MAX_AGENT_STEPS = 8
MAX_AGENT_TIMEOUT_SECONDS = 120.0
SUPPORTED_AGENT_TRIGGERS = frozenset({"manual", "scheduled", "event"})
SUPPORTED_ENTITY_TYPE = "ticket"
SUPPORTED_EVENT_TYPES = frozenset(
    {
        "ticket.created",
        "ticket.updated",
        "ticket.priority_changed",
        "ticket.status_changed",
        "ticket.closed",
        "time_entry.added",
        "workflow.completed",
    }
)
EVENT_FILTER_FIELDS = frozenset({"event_type", "client_id", "priority", "status", "ticket_id"})


@dataclass(frozen=True)
class ToolDefinition:
    id: str
    name: str
    description: str
    input_schema: dict[str, object]
    output_schema: dict[str, object]
    risk_level: str
    required_role: str
    approval_required: bool
    access_mode: str


@dataclass(frozen=True)
class AgentExecutionResult:
    run_id: int
    agent_id: str
    status: str
    current_step: int
    steps: list[dict[str, object]]
    approval_id: int | None = None
    error_detail: str = ""
    revision_version: int | None = None


class AgentDefinitionError(ValueError):
    """Raised when an agent definition is unsafe or cannot be executed."""


class AgentService:
    def __init__(
        self,
        store: Store,
        settings: Settings,
        smart_actions: SmartActionService,
    ) -> None:
        self.store = store
        self.settings = settings
        self.smart_actions = smart_actions

    def list_tools(self) -> list[ToolDefinition]:
        return [
            ToolDefinition(
                id=manifest.action_id,
                name=manifest.title,
                description=manifest.description,
                input_schema=manifest.input_schema,
                output_schema=manifest.output_schema,
                risk_level=manifest.risk_level,
                required_role=manifest.required_role,
                approval_required=manifest.requires_approval,
                access_mode=manifest.access_mode,
            )
            for manifest in self.smart_actions.list()
        ]

    def get(self, agent_id: str, client_id: str | None = None) -> AgentDefinition | None:
        return self.store.get_agent_definition(agent_id, client_id=client_id)

    def list_definitions(self, client_id: str | None = None) -> list[AgentDefinition]:
        return self.store.list_agent_definitions(client_id=client_id)

    def create(
        self,
        *,
        name: str,
        description: str,
        enabled: bool,
        trigger: str,
        entity_type: str,
        filters: dict[str, object],
        enabled_tools: list[str],
        steps: list[dict[str, object]],
        max_steps: int,
        execution_timeout_seconds: float,
        client_id: str | None,
        run_once_per_entity: bool = True,
        depends_on_agent_ids: list[str] | None = None,
        execution_window_start: str | None = None,
        execution_window_end: str | None = None,
        execution_timezone: str = "UTC",
    ) -> AgentDefinition:
        agent_id = f"agent-{uuid.uuid4().hex}"
        self._validate_definition(
            name=name,
            description=description,
            trigger=trigger,
            entity_type=entity_type,
            filters=filters,
            enabled_tools=enabled_tools,
            steps=steps,
            max_steps=max_steps,
            execution_timeout_seconds=execution_timeout_seconds,
            depends_on_agent_ids=depends_on_agent_ids or [],
            agent_id=agent_id,
            client_id=client_id,
            execution_window_start=execution_window_start,
            execution_window_end=execution_window_end,
            execution_timezone=execution_timezone,
        )
        now = utc_now()
        definition = AgentDefinition(
            id=agent_id,
            name=name.strip(),
            description=description.strip(),
            enabled=enabled,
            trigger=trigger,
            entity_type=entity_type,
            filters=redact_value(filters),
            enabled_tools=list(enabled_tools),
            steps=redact_value(steps),
            max_steps=max_steps,
            execution_timeout_seconds=execution_timeout_seconds,
            client_id=_normalize_client_id(client_id),
            version=1,
            created_at=now,
            updated_at=now,
            run_once_per_entity=run_once_per_entity,
            depends_on_agent_ids=list(depends_on_agent_ids or []),
            execution_window_start=execution_window_start,
            execution_window_end=execution_window_end,
            execution_timezone=execution_timezone,
        )
        return self.store.create_agent_definition(definition)

    def update(
        self,
        existing: AgentDefinition,
        *,
        name: str,
        description: str,
        enabled: bool,
        trigger: str,
        entity_type: str,
        filters: dict[str, object],
        enabled_tools: list[str],
        steps: list[dict[str, object]],
        max_steps: int,
        execution_timeout_seconds: float,
        run_once_per_entity: bool = True,
        depends_on_agent_ids: list[str] | None = None,
        execution_window_start: str | None = None,
        execution_window_end: str | None = None,
        execution_timezone: str = "UTC",
    ) -> AgentDefinition:
        self._validate_definition(
            name=name,
            description=description,
            trigger=trigger,
            entity_type=entity_type,
            filters=filters,
            enabled_tools=enabled_tools,
            steps=steps,
            max_steps=max_steps,
            execution_timeout_seconds=execution_timeout_seconds,
            depends_on_agent_ids=depends_on_agent_ids or [],
            agent_id=existing.id,
            client_id=existing.client_id,
            execution_window_start=execution_window_start,
            execution_window_end=execution_window_end,
            execution_timezone=execution_timezone,
        )
        updated = AgentDefinition(
            id=existing.id,
            name=name.strip(),
            description=description.strip(),
            enabled=enabled,
            trigger=trigger,
            entity_type=entity_type,
            filters=redact_value(filters),
            enabled_tools=list(enabled_tools),
            steps=redact_value(steps),
            max_steps=max_steps,
            execution_timeout_seconds=execution_timeout_seconds,
            client_id=existing.client_id,
            version=existing.version + 1,
            created_at=existing.created_at,
            updated_at=utc_now(),
            run_once_per_entity=run_once_per_entity,
            depends_on_agent_ids=list(depends_on_agent_ids or []),
            execution_window_start=execution_window_start,
            execution_window_end=execution_window_end,
            execution_timezone=execution_timezone,
        )
        return self.store.update_agent_definition(updated)

    def run(
        self,
        definition: AgentDefinition,
        *,
        entity_id: str,
        actor: str,
        input_payload: dict[str, object],
    ) -> AgentExecutionResult:
        if not definition.enabled:
            raise AgentDefinitionError("agent is disabled")
        if definition.entity_type != SUPPORTED_ENTITY_TYPE:
            raise AgentDefinitionError("agent entity_type is not supported")
        if definition.trigger != "manual" and not _within_execution_window(definition):
            raise AgentDefinitionError("agent execution is outside its configured execution window")
        client_id = _normalize_client_id(definition.client_id)
        if self.store.get_ticket(entity_id, client_id=client_id) is None:
            raise AgentDefinitionError("ticket was not found in the agent scope")
        state: dict[str, object] = {
            "entity_id": entity_id,
            "input": redact_value(input_payload),
            "steps": [],
            "pending_approval_step": None,
        }
        run = self.store.create_agent_run(
            definition.id,
            entity_id,
            actor,
            "queued",
            0,
            state,
            revision_version=definition.version,
            client_id=client_id,
        )
        return self._continue(definition, run, actor, start_step=0, state=state)

    def resume(
        self,
        definition: AgentDefinition,
        run: AgentRun,
        *,
        approver: str,
        approver_role: Role,
    ) -> AgentExecutionResult:
        if run.status != "pending_approval":
            return self._result(run)
        definition = self._definition_for_run(definition, run)
        if approver == run.actor:
            raise PermissionError("approver cannot approve the requesting actor's run")
        state = _state_object(run.state_json)
        pending_index = state.get("pending_approval_step")
        steps = _state_steps(state)
        if not isinstance(pending_index, int) or pending_index < 0 or pending_index >= len(steps):
            raise AgentDefinitionError("agent approval state is malformed")
        pending_step = steps[pending_index]
        approval_id = pending_step.get("approval_id")
        if not isinstance(approval_id, int):
            raise AgentDefinitionError("agent approval id is missing")
        approval = self.store.get_approval_request(approval_id)
        if approval is None:
            raise AgentDefinitionError("agent approval could not be found")
        if approval.status == "pending":
            self.smart_actions.update_approval(
                approval_id,
                "approved",
                approver=approver,
                approver_role=approver_role,
            )
        action_result = self.smart_actions.complete_approval(
            approval_id,
            approver=approver,
            approver_role=approver_role,
        )
        if action_result is None:
            raise AgentDefinitionError("agent approval could not be completed")
        self._apply_result(pending_step, action_result)
        state["pending_approval_step"] = None
        if action_result.status != "success":
            return self._finish(
                definition,
                run,
                "rejected" if action_result.status == "rejected" else "failed",
                run.current_step,
                state,
                actor=run.actor,
            )
        return self._continue(
            definition,
            run,
            run.actor,
            start_step=run.current_step + 1,
            state=state,
        )

    def cancel(
        self,
        definition: AgentDefinition,
        run: AgentRun,
        *,
        actor: str,
        approver_role: Role,
    ) -> AgentExecutionResult:
        if run.status not in {"queued", "pending_approval"}:
            raise AgentDefinitionError("only queued or approval-paused runs can be cancelled")
        definition = self._definition_for_run(definition, run)
        state = _state_object(run.state_json)
        pending_index = state.get("pending_approval_step")
        if isinstance(pending_index, int):
            steps = _state_steps(state)
            if 0 <= pending_index < len(steps):
                approval_id = steps[pending_index].get("approval_id")
                if isinstance(approval_id, int):
                    approval = self.store.get_approval_request(approval_id)
                    if approval is not None and approval.status == "pending":
                        self.smart_actions.update_approval(
                            approval_id,
                            "rejected",
                            comment="Agent run cancelled",
                            approver=f"{actor}:cancel",
                            approver_role=approver_role,
                        )
                steps[pending_index]["status"] = "cancelled"
                steps[pending_index]["error_detail"] = "agent run cancelled"
                state["steps"] = steps
        state["pending_approval_step"] = None
        state["error_detail"] = "agent run cancelled"
        return self._finish(
            definition,
            run,
            "cancelled",
            run.current_step,
            state,
            actor=actor,
        )

    def retry(
        self,
        definition: AgentDefinition,
        run: AgentRun,
        *,
        actor: str,
    ) -> AgentExecutionResult:
        if run.status not in {"failed", "rejected", "cancelled"}:
            raise AgentDefinitionError("only failed, rejected, or cancelled runs can be retried")
        definition = self._definition_for_run(definition, run)
        state = _state_object(run.state_json)
        input_payload = _state_object(state.get("input"))
        return self.run(
            definition,
            entity_id=run.entity_id,
            actor=actor,
            input_payload=input_payload,
        )

    def _definition_for_run(self, definition: AgentDefinition, run: AgentRun) -> AgentDefinition:
        if run.revision_version is None or run.revision_version == definition.version:
            return definition
        revision = self.store.get_agent_definition_revision(
            run.agent_id,
            run.revision_version,
            run.client_id,
        )
        if revision is None and definition.client_id == run.client_id:
            revision = self.store.get_agent_definition_revision(
                run.agent_id,
                run.revision_version,
                None,
            )
        if revision is None:
            raise AgentDefinitionError("agent run definition revision is no longer available")
        try:
            payload = json.loads(revision.definition_json)
        except json.JSONDecodeError as exc:
            raise AgentDefinitionError("agent run definition revision is malformed") from exc
        if not isinstance(payload, dict):
            raise AgentDefinitionError("agent run definition revision is malformed")
        filters = payload.get("filters", {})
        enabled_tools = payload.get("enabled_tools", [])
        steps = payload.get("steps", [])
        dependencies = payload.get("depends_on_agent_ids", [])
        if not isinstance(filters, dict) or not isinstance(enabled_tools, list):
            raise AgentDefinitionError("agent run definition revision is malformed")
        if not isinstance(steps, list) or not isinstance(dependencies, list):
            raise AgentDefinitionError("agent run definition revision is malformed")
        return AgentDefinition(
            id=definition.id,
            name=str(payload.get("name", definition.name)),
            description=str(payload.get("description", definition.description)),
            enabled=bool(payload.get("enabled", definition.enabled)),
            trigger=str(payload.get("trigger", definition.trigger)),
            entity_type=str(payload.get("entity_type", definition.entity_type)),
            filters=cast(dict[str, object], filters),
            enabled_tools=cast(list[str], enabled_tools),
            steps=cast(list[dict[str, object]], steps),
            max_steps=int(payload.get("max_steps", definition.max_steps)),
            execution_timeout_seconds=float(
                payload.get("execution_timeout_seconds", definition.execution_timeout_seconds)
            ),
            client_id=run.client_id,
            version=run.revision_version,
            created_at=definition.created_at,
            updated_at=revision.created_at,
            run_once_per_entity=bool(payload.get("run_once_per_entity", definition.run_once_per_entity)),
            depends_on_agent_ids=cast(list[str], dependencies),
            execution_window_start=_optional_string(payload.get("execution_window_start")),
            execution_window_end=_optional_string(payload.get("execution_window_end")),
            execution_timezone=str(payload.get("execution_timezone", definition.execution_timezone)),
        )

    def _continue(
        self,
        definition: AgentDefinition,
        run: AgentRun,
        actor: str,
        *,
        start_step: int,
        state: dict[str, object],
    ) -> AgentExecutionResult:
        started = time.monotonic()
        steps = _state_steps(state)
        input_payload = _state_object(state.get("input"))
        for index in range(start_step, min(len(definition.steps), definition.max_steps)):
            if time.monotonic() - started >= definition.execution_timeout_seconds:
                return self._finish(
                    definition,
                    run,
                    "failed",
                    index,
                    {**state, "error_detail": "agent execution timed out"},
                    actor=actor,
                )
            configured_step = definition.steps[index]
            tool_id = configured_step.get("tool_id")
            configured_payload = configured_step.get("payload", {})
            if not isinstance(tool_id, str) or not isinstance(configured_payload, dict):
                return self._finish(
                    definition,
                    run,
                    "failed",
                    index,
                    {**state, "error_detail": "agent step is malformed"},
                    actor=actor,
                )
            payload = dict(input_payload)
            payload.update(configured_payload)
            payload.setdefault("ticket_id", run.entity_id)
            if tool_id not in definition.enabled_tools:
                return self._finish(
                    definition,
                    run,
                    "failed",
                    index,
                    {**state, "error_detail": f"tool {tool_id} is not enabled for this agent"},
                    actor=actor,
                )
            try:
                action_result = self.smart_actions.invoke(
                    tool_id,
                    payload,
                    actor,
                    client_id=definition.client_id,
                )
            except KeyError:
                action_result = ActionResult(status="failed", error_detail=f"tool {tool_id} is not registered")
            step = {
                "index": index,
                "tool_id": tool_id,
                "input": redact_value(payload),
            }
            self._apply_result(step, action_result)
            steps.append(step)
            state["steps"] = steps
            if action_result.status == "pending_approval":
                state["pending_approval_step"] = index
                return self._finish(
                    definition,
                    run,
                    "pending_approval",
                    index,
                    state,
                    actor=actor,
                )
            if action_result.status != "success":
                return self._finish(definition, run, "failed", index, state, actor=actor)
            state["pending_approval_step"] = None
            run = self.store.update_agent_run(run.id or 0, "queued", index + 1, state)
        return self._finish(
            definition,
            run,
            "completed",
            len(definition.steps),
            state,
            actor=actor,
        )

    def _finish(
        self,
        definition: AgentDefinition,
        run: AgentRun,
        status: str,
        current_step: int,
        state: dict[str, object],
        *,
        actor: str,
    ) -> AgentExecutionResult:
        final = self.store.update_agent_run(run.id or 0, status, current_step, state)
        steps = _state_steps(state)
        recorder_steps = tuple(
            StepRecord(
                kind="agent.tool",
                name=str(step.get("tool_id", "unknown")),
                status=str(step.get("status", "failed")),
                input=step.get("input"),
                output=step.get("output"),
                error_detail=str(step.get("error_detail", "")),
            )
            for step in steps
        )
        ExecutionRecorder(self.store).record_execution(
            run_kind="agent",
            source_run_id=final.id,
            actor=actor,
            status=status,
            trigger_source=f"agent:{definition.trigger}",
            client_id=definition.client_id,
            steps=recorder_steps,
        )
        return self._result(final)

    @staticmethod
    def _apply_result(step: dict[str, object], result: ActionResult) -> None:
        step["status"] = result.status
        step["output"] = redact_value(result.output)
        step["evidence"] = redact_value(result.evidence)
        step["error_detail"] = result.error_detail
        step["action_run_id"] = result.run_id
        step["approval_id"] = result.approval_id

    @staticmethod
    def _result(run: AgentRun) -> AgentExecutionResult:
        state = _state_object(run.state_json)
        steps = _state_steps(state)
        approval_id = None
        pending_value = state.get("pending_approval_step")
        if isinstance(pending_value, int):
            pending = pending_value
            if pending < len(steps) and isinstance(steps[pending].get("approval_id"), int):
                approval_id = cast(int, steps[pending]["approval_id"])
        return AgentExecutionResult(
            run_id=run.id or 0,
            agent_id=run.agent_id,
            status=run.status,
            current_step=run.current_step,
            steps=steps,
            approval_id=approval_id,
            error_detail=str(state.get("error_detail", "")),
            revision_version=run.revision_version,
        )

    def _validate_definition(
        self,
        *,
        name: str,
        description: str,
        trigger: str,
        entity_type: str,
        filters: dict[str, object],
        enabled_tools: list[str],
        steps: list[dict[str, object]],
        max_steps: int,
        execution_timeout_seconds: float,
        depends_on_agent_ids: list[str],
        agent_id: str | None,
        client_id: str | None,
        execution_window_start: str | None,
        execution_window_end: str | None,
        execution_timezone: str,
    ) -> None:
        if not name.strip() or len(name.strip()) > 120:
            raise AgentDefinitionError("name must contain 1-120 characters")
        if len(description) > 4000:
            raise AgentDefinitionError("description is too long")
        if trigger not in SUPPORTED_AGENT_TRIGGERS:
            raise AgentDefinitionError("only manual, scheduled, or event agents are supported")
        if entity_type != SUPPORTED_ENTITY_TYPE:
            raise AgentDefinitionError("only ticket agents are supported in this slice")
        if not isinstance(filters, dict):
            raise AgentDefinitionError("filters must be an object")
        if trigger == "event":
            _validate_event_filters(filters)
        elif filters:
            raise AgentDefinitionError("filters are reserved for event-triggered agents")
        self._validate_dependencies(agent_id, depends_on_agent_ids, client_id)
        if not enabled_tools or len(enabled_tools) > MAX_AGENT_STEPS:
            raise AgentDefinitionError(f"enabled_tools must contain 1-{MAX_AGENT_STEPS} tools")
        if len(set(enabled_tools)) != len(enabled_tools):
            raise AgentDefinitionError("enabled_tools must not contain duplicates")
        available = {tool.id for tool in self.list_tools()}
        unknown = sorted(set(enabled_tools) - available)
        if unknown:
            raise AgentDefinitionError(f"unknown tools: {', '.join(unknown)}")
        if not steps or len(steps) > MAX_AGENT_STEPS:
            raise AgentDefinitionError(f"steps must contain 1-{MAX_AGENT_STEPS} steps")
        if max_steps < 1 or max_steps > MAX_AGENT_STEPS or len(steps) > max_steps:
            raise AgentDefinitionError(f"max_steps must be between 1 and {MAX_AGENT_STEPS} and cover steps")
        if execution_timeout_seconds <= 0 or execution_timeout_seconds > MAX_AGENT_TIMEOUT_SECONDS:
            raise AgentDefinitionError(
                f"execution_timeout_seconds must be between 0 and {MAX_AGENT_TIMEOUT_SECONDS:g}"
            )
        _validate_execution_window(execution_window_start, execution_window_end, execution_timezone)
        for step in steps:
            if set(step) - {"tool_id", "payload"}:
                raise AgentDefinitionError("agent steps may only contain tool_id and payload")
            tool_id = step.get("tool_id")
            if not isinstance(tool_id, str) or tool_id not in enabled_tools:
                raise AgentDefinitionError("every step tool_id must be an enabled tool")
            if not isinstance(step.get("payload", {}), dict):
                raise AgentDefinitionError("agent step payload must be an object")

    def _validate_dependencies(
        self,
        agent_id: str | None,
        dependency_ids: list[str],
        client_id: str | None,
    ) -> None:
        if len(dependency_ids) > MAX_AGENT_STEPS:
            raise AgentDefinitionError(f"depends_on_agent_ids must contain 0-{MAX_AGENT_STEPS} agents")
        if any(not isinstance(dependency_id, str) or not dependency_id.strip() for dependency_id in dependency_ids):
            raise AgentDefinitionError("depends_on_agent_ids must contain non-empty strings")
        if len(set(dependency_ids)) != len(dependency_ids):
            raise AgentDefinitionError("depends_on_agent_ids must not contain duplicates")
        normalized_client_id = _normalize_client_id(client_id)
        graph = {
            definition.id: definition.depends_on_agent_ids
            for definition in self.store.list_agent_definitions()
        }
        if agent_id is not None:
            graph[agent_id] = list(dependency_ids)
        for dependency_id in dependency_ids:
            if dependency_id == agent_id:
                raise AgentDefinitionError("an agent cannot depend on itself")
            dependency = self.get(dependency_id)
            if dependency is None:
                raise AgentDefinitionError(f"dependency agent not found: {dependency_id}")
            if dependency.client_id is not None and dependency.client_id != normalized_client_id:
                raise AgentDefinitionError("dependency agent is outside the tenant scope")

        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(node: str) -> None:
            if node in visiting:
                raise AgentDefinitionError("agent dependency cycle detected")
            if node in visited:
                return
            visiting.add(node)
            for dependency_id in graph.get(node, []):
                visit(dependency_id)
            visiting.remove(node)
            visited.add(node)

        if agent_id is not None:
            visit(agent_id)


def _state_object(value: object) -> dict[str, object]:
    if isinstance(value, dict):
        return cast(dict[str, object], value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _validate_event_filters(filters: dict[str, object]) -> None:
    unknown = sorted(set(filters) - EVENT_FILTER_FIELDS)
    if unknown:
        raise AgentDefinitionError(f"unsupported event filter fields: {', '.join(unknown)}")
    event_type = filters.get("event_type")
    if not isinstance(event_type, str) or event_type not in SUPPORTED_EVENT_TYPES:
        raise AgentDefinitionError("event filters require a supported event_type")
    for field, value in filters.items():
        if field == "event_type":
            continue
        if not isinstance(value, str) or not value.strip():
            raise AgentDefinitionError(f"event filter {field} must be a non-empty string")


def _validate_execution_window(start: str | None, end: str | None, timezone: str) -> None:
    if (start is None) != (end is None):
        raise AgentDefinitionError("execution window requires both start and end")
    try:
        ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, TypeError) as exc:
        raise AgentDefinitionError("execution_timezone must be a valid IANA timezone") from exc
    if start is None or end is None:
        return
    for value, label in ((start, "start"), (end, "end")):
        try:
            datetime.strptime(value, "%H:%M")
        except ValueError as exc:
            raise AgentDefinitionError(f"execution_window_{label} must use HH:MM") from exc
    if start >= end:
        raise AgentDefinitionError("execution window must end after it starts")


def _within_execution_window(definition: AgentDefinition) -> bool:
    _validate_execution_window(
        definition.execution_window_start,
        definition.execution_window_end,
        definition.execution_timezone,
    )
    if definition.execution_window_start is None or definition.execution_window_end is None:
        return True
    now = datetime.now(ZoneInfo(definition.execution_timezone)).strftime("%H:%M")
    return definition.execution_window_start <= now < definition.execution_window_end


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _state_steps(state: dict[str, object]) -> list[dict[str, object]]:
    steps = state.get("steps", [])
    if not isinstance(steps, list):
        return []
    return [cast(dict[str, object], item) for item in steps if isinstance(item, dict)]
