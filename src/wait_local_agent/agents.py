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
from typing import cast

from wait_local_agent.config import Settings
from wait_local_agent.models import AgentDefinition, AgentRun, utc_now
from wait_local_agent.observability import ExecutionRecorder, StepRecord
from wait_local_agent.rbac import Role
from wait_local_agent.reports.renderers import redact_value
from wait_local_agent.smart_actions import ActionResult, SmartActionService
from wait_local_agent.store import Store, _normalize_client_id

MAX_AGENT_STEPS = 8
MAX_AGENT_TIMEOUT_SECONDS = 120.0
SUPPORTED_AGENT_TRIGGER = "manual"
SUPPORTED_ENTITY_TYPE = "ticket"


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
        )
        now = utc_now()
        definition = AgentDefinition(
            id=f"agent-{uuid.uuid4().hex}",
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
    ) -> None:
        if not name.strip() or len(name.strip()) > 120:
            raise AgentDefinitionError("name must contain 1-120 characters")
        if len(description) > 4000:
            raise AgentDefinitionError("description is too long")
        if trigger != SUPPORTED_AGENT_TRIGGER:
            raise AgentDefinitionError("only manual agents are supported in this slice")
        if entity_type != SUPPORTED_ENTITY_TYPE:
            raise AgentDefinitionError("only ticket agents are supported in this slice")
        if not isinstance(filters, dict):
            raise AgentDefinitionError("filters must be an object")
        if filters:
            raise AgentDefinitionError("filters are reserved until event triggers are supported")
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
        for step in steps:
            if set(step) - {"tool_id", "payload"}:
                raise AgentDefinitionError("agent steps may only contain tool_id and payload")
            tool_id = step.get("tool_id")
            if not isinstance(tool_id, str) or tool_id not in enabled_tools:
                raise AgentDefinitionError("every step tool_id must be an enabled tool")
            if not isinstance(step.get("payload", {}), dict):
                raise AgentDefinitionError("agent step payload must be an object")


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


def _state_steps(state: dict[str, object]) -> list[dict[str, object]]:
    steps = state.get("steps", [])
    if not isinstance(steps, list):
        return []
    return [cast(dict[str, object], item) for item in steps if isinstance(item, dict)]
