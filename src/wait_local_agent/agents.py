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
from dataclasses import dataclass, field
from datetime import datetime
from typing import cast
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from wait_local_agent.config import Settings
from wait_local_agent.models import (
    MAX_APPROVAL_EXPIRY_SECONDS,
    AgentDefinition,
    AgentRun,
    Ticket,
    utc_now,
)
from wait_local_agent.observability import ExecutionRecorder, StepRecord
from wait_local_agent.rbac import Role
from wait_local_agent.reports.renderers import redact_text, redact_value
from wait_local_agent.retrieval import retrieve_sources
from wait_local_agent.smart_actions import ActionResult, SmartActionService
from wait_local_agent.store import Store, _normalize_client_id

MAX_AGENT_STEPS = 8
MAX_AGENT_TIMEOUT_SECONDS = 120.0
MAX_AGENT_RETRIES = 3
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
EVENT_FILTER_FIELDS = frozenset(
    {
        "event_type",
        "client_id",
        "priority",
        "status",
        "ticket_id",
        "workflow_template_id",
        "workflow_run_id",
    }
)
SUPPORTED_CONTEXT_SOURCES = frozenset({"ticket", "client", "knowledge"})
MAX_CONTEXT_SOURCES = 3
EXECUTION_WINDOW_TIME_FORMAT = "%H:%M"
MAX_APPROVAL_RULES = MAX_AGENT_STEPS
MAX_APPROVAL_RULE_VALUES = MAX_AGENT_STEPS
APPROVAL_RULE_FIELDS = frozenset({"priority", "status", "actor_role"})
APPROVAL_RULE_ROLE_VALUES = frozenset(role.label() for role in Role)


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
    approval_expiry_seconds: int


@dataclass(frozen=True)
class AgentExecutionResult:
    run_id: int
    agent_id: str
    status: str
    current_step: int
    steps: list[dict[str, object]]
    approval_id: int | None = None
    error_detail: str = ""
    final_result: dict[str, object] = field(default_factory=dict)
    revision_version: int | None = None


@dataclass(frozen=True)
class AgentPlanResult:
    instruction: str
    entity_id: str
    client_id: str | None
    status: str
    steps: list[dict[str, object]]
    context: dict[str, object]
    definition: dict[str, object] = field(default_factory=dict)
    blocked_reason: str = ""
    selection_mode: str = "deterministic"


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
                approval_expiry_seconds=manifest.approval_expiry_seconds,
            )
            for manifest in self.smart_actions.list()
        ]

    def get(self, agent_id: str, client_id: str | None = None) -> AgentDefinition | None:
        return self.store.get_agent_definition(agent_id, client_id=client_id)

    def list_definitions(self, client_id: str | None = None) -> list[AgentDefinition]:
        return self.store.list_agent_definitions(client_id=client_id)

    def plan(
        self,
        instruction: str,
        *,
        entity_id: str,
        client_id: str | None,
        max_steps: int = MAX_AGENT_STEPS,
    ) -> AgentPlanResult:
        """Preview a bounded plan using only the existing approved tool catalog."""
        normalized = " ".join(instruction.split()).strip()
        if not normalized or len(normalized) > 2_000:
            raise AgentDefinitionError("instruction must contain 1-2000 characters")
        if max_steps < 1 or max_steps > MAX_AGENT_STEPS:
            raise AgentDefinitionError(f"max_steps must be between 1 and {MAX_AGENT_STEPS}")
        normalized_client_id = _normalize_client_id(client_id)
        ticket = self.store.get_ticket(entity_id, client_id=normalized_client_id)
        if ticket is None:
            raise AgentDefinitionError("ticket was not found in the requested scope")

        tools = {tool.id: tool for tool in self.list_tools()}
        deterministic_ids = _plan_tool_ids(normalized)
        selected_ids = deterministic_ids
        selection_mode = "deterministic"
        model_ids = self._model_plan_tool_ids(
            normalized,
            ticket,
            list(tools.values()),
            max_steps=max_steps,
        )
        if model_ids:
            selected_ids = model_ids
            selection_mode = "model"
        selected_ids = [tool_id for tool_id in selected_ids if tool_id in tools][:max_steps]
        context_sources = ["ticket", "client", "knowledge"]
        context = self._build_context(
            AgentDefinition(
                id="plan-preview",
                name="Plan preview",
                description="",
                enabled=True,
                trigger="manual",
                entity_type="ticket",
                filters={},
                enabled_tools=selected_ids or ["ticket-triage"],
                steps=[{"tool_id": selected_ids[0] if selected_ids else "ticket-triage", "payload": {}}],
                max_steps=1,
                execution_timeout_seconds=1,
                client_id=normalized_client_id,
                version=1,
                created_at=utc_now(),
                updated_at=utc_now(),
                context_sources=context_sources,
            ),
            entity_id,
        )
        if not selected_ids:
            return AgentPlanResult(
                instruction=normalized,
                entity_id=entity_id,
                client_id=normalized_client_id,
                status="blocked",
                steps=[],
                context=context,
                blocked_reason=(
                    "No approved tool matched this request. Choose a supported service-desk "
                    "operation and review the tool catalog before running it."
                ),
                selection_mode=selection_mode,
            )
        return AgentPlanResult(
            instruction=normalized,
            entity_id=entity_id,
            client_id=normalized_client_id,
            status="preview",
            steps=[
                {
                    "index": index,
                    "tool_id": tool_id,
                    "name": tools[tool_id].name,
                    "reason": _plan_reason(tool_id),
                    "risk_level": tools[tool_id].risk_level,
                    "required_role": tools[tool_id].required_role,
                    "approval_required": tools[tool_id].approval_required,
                    "access_mode": tools[tool_id].access_mode,
                    "payload": {"ticket_id": entity_id},
                }
                for index, tool_id in enumerate(selected_ids)
            ],
            context=context,
            selection_mode=selection_mode,
            definition={
                "name": f"Plan for {entity_id}",
                "description": normalized,
                "enabled": False,
                "trigger": "manual",
                "entity_type": "ticket",
                "filters": {},
                "enabled_tools": selected_ids,
                "steps":[{"tool_id": tool_id, "payload": {}} for tool_id in selected_ids],
                "max_steps": len(selected_ids),
                "execution_timeout_seconds": 30.0,
                "client_id": normalized_client_id,
                "context_sources": context_sources,
            },
        )

    def _model_plan_tool_ids(
        self,
        instruction: str,
        ticket: Ticket,
        tools: list[ToolDefinition],
        *,
        max_steps: int,
    ) -> list[str]:
        if not self.smart_actions.provider_configured:
            return []
        selector = getattr(self.smart_actions.provider, "select_tools", None)
        if not callable(selector):
            return []
        try:
            sources = retrieve_sources(
                ticket,
                self.settings.allowed_doc_root,
                self.store,
                self.settings,
                client_id=ticket.client_id,
            )
            selected = selector(
                instruction,
                ticket,
                sources,
                [
                    {
                        "id": tool.id,
                        "name": tool.name,
                        "description": tool.description,
                    }
                    for tool in tools
                ],
                max_tools=max_steps,
            )
        except Exception:
            # Planner selection is advisory; any provider or retrieval failure
            # returns control to the deterministic, catalog-scoped rules.
            return []
        allowed = {tool.id for tool in tools}
        return [tool_id for tool_id in selected if tool_id in allowed][:max_steps]

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
        execution_window_timezone: str = "UTC",
        context_sources: list[str] | None = None,
        approval_expiry_seconds: int | None = None,
        result_aware: bool = False,
        approval_required_tools: list[str] | None = None,
        approval_rules: list[dict[str, object]] | None = None,
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
            execution_window_timezone=execution_window_timezone,
            context_sources=context_sources or [],
            approval_expiry_seconds=approval_expiry_seconds,
            approval_required_tools=approval_required_tools or [],
            approval_rules=approval_rules or [],
        )
        window_start, window_end, window_timezone = _normalized_execution_window(
            execution_window_start,
            execution_window_end,
            execution_window_timezone,
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
            execution_window_start=window_start,
            execution_window_end=window_end,
            execution_window_timezone=window_timezone,
            context_sources=list(context_sources or []),
            approval_expiry_seconds=approval_expiry_seconds,
            result_aware=result_aware,
            approval_required_tools=list(approval_required_tools or []),
            approval_rules=_normalize_approval_rules(approval_rules or []),
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
        execution_window_timezone: str = "UTC",
        context_sources: list[str] | None = None,
        approval_expiry_seconds: int | None = None,
        result_aware: bool = False,
        approval_required_tools: list[str] | None = None,
        approval_rules: list[dict[str, object]] | None = None,
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
            execution_window_timezone=execution_window_timezone,
            context_sources=context_sources or [],
            approval_expiry_seconds=approval_expiry_seconds,
            approval_required_tools=approval_required_tools or [],
            approval_rules=approval_rules or [],
        )
        window_start, window_end, window_timezone = _normalized_execution_window(
            execution_window_start,
            execution_window_end,
            execution_window_timezone,
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
            execution_window_start=window_start,
            execution_window_end=window_end,
            execution_window_timezone=window_timezone,
            context_sources=list(context_sources or []),
            approval_expiry_seconds=approval_expiry_seconds,
            result_aware=result_aware,
            approval_required_tools=list(approval_required_tools or []),
            approval_rules=_normalize_approval_rules(approval_rules or []),
        )
        return self.store.update_agent_definition(updated)

    def run(
        self,
        definition: AgentDefinition,
        *,
        entity_id: str,
        actor: str,
        input_payload: dict[str, object],
        supervisor_context: dict[str, object] | None = None,
        retry_count: int = 0,
        retry_of_run_id: int | None = None,
        actor_role: Role | None = None,
    ) -> AgentExecutionResult:
        if not definition.enabled:
            raise AgentDefinitionError("agent is disabled")
        if not self.execution_window_open(definition):
            raise AgentDefinitionError("agent execution window is closed")
        if definition.entity_type != SUPPORTED_ENTITY_TYPE:
            raise AgentDefinitionError("agent entity_type is not supported")
        client_id = _normalize_client_id(definition.client_id)
        if self.store.get_ticket(entity_id, client_id=client_id) is None:
            raise AgentDefinitionError("ticket was not found in the agent scope")
        execution_context = self._build_context(definition, entity_id)
        if supervisor_context:
            execution_context = {
                **execution_context,
                "supervisor": redact_value(supervisor_context),
            }
        state: dict[str, object] = {
            "entity_id": entity_id,
            "input": redact_value(input_payload),
            "context": execution_context,
            "steps": [],
            "pending_approval_step": None,
            "retry_count": retry_count,
            "actor_role": actor_role.label() if actor_role is not None else None,
        }
        if retry_of_run_id is not None:
            state["retry_of_run_id"] = retry_of_run_id
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
        return self._continue(
            definition,
            run,
            actor,
            start_step=0,
            state=state,
            actor_role=actor_role,
        )

    @staticmethod
    def execution_window_open(
        definition: AgentDefinition,
        *,
        now: datetime | None = None,
    ) -> bool:
        if definition.execution_window_start is None:
            return True
        try:
            timezone = ZoneInfo(definition.execution_window_timezone)
            start = _window_minutes(definition.execution_window_start)
            end = _window_minutes(cast(str, definition.execution_window_end))
        except (TypeError, ValueError, ZoneInfoNotFoundError) as exc:
            raise AgentDefinitionError("agent execution window is invalid") from exc
        current = now or datetime.now(timezone)
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone)
        else:
            current = current.astimezone(timezone)
        current_minutes = current.hour * 60 + current.minute
        if start < end:
            return start <= current_minutes < end
        return current_minutes >= start or current_minutes < end

    def retry(
        self,
        definition: AgentDefinition,
        run: AgentRun,
        *,
        actor: str,
        actor_role: Role | None = None,
        supervisor_context: dict[str, object] | None = None,
    ) -> AgentExecutionResult:
        """Retry a failed or cancelled run with a small persisted attempt cap."""
        if run.status not in {"failed", "cancelled"}:
            raise AgentDefinitionError("only failed or cancelled runs can be retried")
        if run.revision_version is not None and run.revision_version != definition.version:
            raise AgentDefinitionError("agent definition changed; retry requires the run's revision")
        state = _state_object(run.state_json)
        retry_count = state.get("retry_count", 0)
        if not isinstance(retry_count, int) or retry_count < 0:
            raise AgentDefinitionError("agent retry state is malformed")
        if retry_count >= MAX_AGENT_RETRIES:
            raise AgentDefinitionError(f"agent retry limit of {MAX_AGENT_RETRIES} has been reached")
        input_payload = _state_object(state.get("input"))
        return self.run(
            definition,
            entity_id=run.entity_id,
            actor=actor,
            input_payload=input_payload,
            retry_count=retry_count + 1,
            retry_of_run_id=run.id,
            actor_role=actor_role,
            supervisor_context=supervisor_context,
        )

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
        state["final_result"] = _final_result_from_action(pending_step["tool_id"], action_result)
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
            actor_role=_actor_role_from_state(state),
        )

    def cancel(
        self,
        definition: AgentDefinition,
        run: AgentRun,
        *,
        actor: str,
        approver_role: Role,
    ) -> AgentExecutionResult:
        if run.status == "cancelled":
            return self._result(run)
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
                            approver=actor if actor != run.actor else "system:cancellation",
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
        approval_required_tools = payload.get("approval_required_tools", [])
        approval_rules = payload.get("approval_rules", [])
        if not isinstance(filters, dict) or not isinstance(enabled_tools, list):
            raise AgentDefinitionError("agent run definition revision is malformed")
        if not isinstance(steps, list) or not isinstance(dependencies, list):
            raise AgentDefinitionError("agent run definition revision is malformed")
        if not isinstance(approval_required_tools, list):
            raise AgentDefinitionError("agent run definition revision is malformed")
        if not isinstance(approval_rules, list):
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
            execution_window_start=(
                payload.get("execution_window_start")
                if isinstance(payload.get("execution_window_start"), str)
                else None
            ),
            execution_window_end=(
                payload.get("execution_window_end")
                if isinstance(payload.get("execution_window_end"), str)
                else None
            ),
            execution_window_timezone=str(
                payload.get("execution_window_timezone", definition.execution_window_timezone)
            ),
            context_sources=cast(
                list[str], payload.get("context_sources", definition.context_sources)
            ),
            approval_expiry_seconds=(
                int(payload["approval_expiry_seconds"])
                if isinstance(payload.get("approval_expiry_seconds"), int)
                else definition.approval_expiry_seconds
            ),
            result_aware=bool(payload.get("result_aware", definition.result_aware)),
            approval_required_tools=cast(list[str], approval_required_tools),
            approval_rules=cast(list[dict[str, object]], approval_rules),
        )

    def _continue(
        self,
        definition: AgentDefinition,
        run: AgentRun,
        actor: str,
        *,
        start_step: int,
        state: dict[str, object],
        actor_role: Role | None,
    ) -> AgentExecutionResult:
        if definition.result_aware:
            return self._continue_result_aware(
                definition,
                run,
                actor,
                state=state,
                actor_role=actor_role,
            )
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
            if state.get("context"):
                payload["_agent_context"] = state["context"]
            if tool_id not in definition.enabled_tools:
                return self._finish(
                    definition,
                    run,
                    "failed",
                    index,
                    {**state, "error_detail": f"tool {tool_id} is not enabled for this agent"},
                    actor=actor,
                )
            approval_policy = _approval_policy_for_ticket(
                definition,
                tool_id,
                run.entity_id,
                self.store,
                actor_role=actor_role,
            )
            try:
                action_result = self.smart_actions.invoke(
                    tool_id,
                    payload,
                    actor,
                    client_id=definition.client_id,
                    approval_expiry_seconds=definition.approval_expiry_seconds,
                    require_approval=approval_policy is not None,
                )
            except KeyError:
                action_result = ActionResult(status="failed", error_detail=f"tool {tool_id} is not registered")
            step = {
                "index": index,
                "tool_id": tool_id,
                "input": redact_value(payload),
            }
            if approval_policy is not None:
                step["approval_policy"] = approval_policy
            self._apply_result(step, action_result)
            state["final_result"] = _final_result_from_action(tool_id, action_result)
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

    def _continue_result_aware(
        self,
        definition: AgentDefinition,
        run: AgentRun,
        actor: str,
        *,
        state: dict[str, object],
        actor_role: Role | None,
    ) -> AgentExecutionResult:
        """Execute a reviewed definition one bounded, result-aware step at a time."""
        started = time.monotonic()
        steps = _state_steps(state)
        input_payload = _state_object(state.get("input"))
        while len(steps) < definition.max_steps:
            ordinal = len(steps)
            if time.monotonic() - started >= definition.execution_timeout_seconds:
                return self._finish(
                    definition,
                    run,
                    "failed",
                    ordinal,
                    {**state, "error_detail": "agent execution timed out"},
                    actor=actor,
                )
            configured_step, selection_mode = self._select_result_aware_step(
                definition,
                run.entity_id,
                steps,
            )
            if configured_step is None:
                state["continuation"] = {
                    "status": "complete",
                    "selection_mode": selection_mode,
                    "reason": "no remaining approved tool matched the bounded run",
                }
                return self._finish(definition, run, "completed", ordinal, state, actor=actor)
            tool_id = configured_step.get("tool_id")
            configured_payload = configured_step.get("payload", {})
            if not isinstance(tool_id, str) or not isinstance(configured_payload, dict):
                return self._finish(
                    definition,
                    run,
                    "failed",
                    ordinal,
                    {**state, "error_detail": "agent step is malformed"},
                    actor=actor,
                )
            payload = dict(input_payload)
            payload.update(configured_payload)
            payload.setdefault("ticket_id", run.entity_id)
            if state.get("context"):
                payload["_agent_context"] = state["context"]
            if tool_id not in definition.enabled_tools:
                return self._finish(
                    definition,
                    run,
                    "failed",
                    ordinal,
                    {**state, "error_detail": f"tool {tool_id} is not enabled for this agent"},
                    actor=actor,
                )
            approval_policy = _approval_policy_for_ticket(
                definition,
                tool_id,
                run.entity_id,
                self.store,
                actor_role=actor_role,
            )
            try:
                action_result = self.smart_actions.invoke(
                    tool_id,
                    payload,
                    actor,
                    client_id=definition.client_id,
                    approval_expiry_seconds=definition.approval_expiry_seconds,
                    require_approval=approval_policy is not None,
                )
            except KeyError:
                action_result = ActionResult(status="failed", error_detail=f"tool {tool_id} is not registered")
            step = {
                "index": ordinal,
                "tool_id": tool_id,
                "input": redact_value(payload),
                "continuation": {
                    "selection_mode": selection_mode,
                    "reason": "selected from the remaining reviewed tool catalog",
                    "lineage": _continuation_lineage(steps[-1] if steps else None),
                },
            }
            if approval_policy is not None:
                step["approval_policy"] = approval_policy
            self._apply_result(step, action_result)
            state["final_result"] = _final_result_from_action(tool_id, action_result)
            steps.append(step)
            state["steps"] = steps
            if action_result.status == "pending_approval":
                state["pending_approval_step"] = ordinal
                return self._finish(
                    definition,
                    run,
                    "pending_approval",
                    ordinal,
                    state,
                    actor=actor,
                )
            if action_result.status != "success":
                return self._finish(definition, run, "failed", ordinal, state, actor=actor)
            state["pending_approval_step"] = None
            run = self.store.update_agent_run(run.id or 0, "queued", ordinal + 1, state)
        return self._finish(
            definition,
            run,
            "completed",
            len(steps),
            state,
            actor=actor,
        )

    def _select_result_aware_step(
        self,
        definition: AgentDefinition,
        entity_id: str,
        steps: list[dict[str, object]],
    ) -> tuple[dict[str, object] | None, str]:
        completed = [
            tool_id
            for step in steps
            if isinstance((tool_id := step.get("tool_id")), str)
        ]
        candidates = [
            step
            for step in definition.steps
            if isinstance(step.get("tool_id"), str)
            and step["tool_id"] in definition.enabled_tools
            and step["tool_id"] not in completed
        ]
        if not candidates:
            return None, "deterministic"
        tools_by_id = {tool.id: tool for tool in self.list_tools()}
        catalog = [
            {
                "id": str(step["tool_id"]),
                "name": tools_by_id[str(step["tool_id"])].name,
                "description": tools_by_id[str(step["tool_id"])].description,
            }
            for step in candidates
            if str(step["tool_id"]) in tools_by_id
        ]
        selected = self._model_next_tool_id(
            definition,
            entity_id,
            catalog,
            steps[-1] if steps else None,
            completed,
        )
        if selected:
            for step in candidates:
                if step.get("tool_id") == selected:
                    return step, "model"
        return candidates[0], "deterministic-fallback" if selected is None else "deterministic-rejected-model"

    def _model_next_tool_id(
        self,
        definition: AgentDefinition,
        entity_id: str,
        tools: list[dict[str, str]],
        previous_step: dict[str, object] | None,
        completed_tool_ids: list[str],
    ) -> str | None:
        if not self.smart_actions.provider_configured or not tools:
            return None
        selector = getattr(self.smart_actions.provider, "select_next_tool", None)
        if not callable(selector):
            return None
        ticket = self.store.get_ticket(entity_id, client_id=definition.client_id)
        if ticket is None:
            return None
        try:
            sources = retrieve_sources(
                ticket,
                self.settings.allowed_doc_root,
                self.store,
                self.settings,
                client_id=ticket.client_id,
            )
            selected = selector(
                definition.description,
                ticket,
                sources,
                tools,
                _bounded_step_result(previous_step),
                completed_tool_ids,
            )
        except Exception:
            return None
        return selected if isinstance(selected, str) else None

    def _build_context(self, definition: AgentDefinition, entity_id: str) -> dict[str, object]:
        if not definition.context_sources:
            return {}
        ticket = self.store.get_ticket(entity_id, client_id=definition.client_id)
        if ticket is None:
            raise AgentDefinitionError("ticket was not found in the agent scope")
        context: dict[str, object] = {}
        if "ticket" in definition.context_sources:
            context["ticket"] = {
                "id": ticket.id,
                "client": _bounded_context_text(ticket.client, 200),
                "subject": _bounded_context_text(ticket.subject, 500),
                "body": _bounded_context_text(ticket.body, 4000),
                "priority": _bounded_context_text(ticket.priority, 40),
                "status": _bounded_context_text(ticket.status, 40),
                "requester_id": _bounded_context_text(ticket.requester_id or "", 200),
            }
        if "client" in definition.context_sources:
            context["client"] = {
                "id": _normalize_client_id(ticket.client_id),
                "name": _bounded_context_text(ticket.client, 200),
            }
        if "knowledge" in definition.context_sources:
            knowledge_status = "ready"
            try:
                sources = retrieve_sources(
                    ticket,
                    self.settings.allowed_doc_root,
                    self.store,
                    self.settings,
                    client_id=ticket.client_id,
                )
            except Exception:
                sources = []
                knowledge_status = "unavailable"
            context["knowledge"] = {
                "status": knowledge_status,
                "sources": [
                    {
                        "title": _bounded_context_text(source.title, 200),
                        "path": _bounded_context_text(source.path, 500),
                        "excerpt": _bounded_context_text(source.excerpt, 1000),
                        "document_id": source.document_id,
                        "chunk_id": source.chunk_id,
                    }
                    for source in sources[:3]
                ],
                "count": min(len(sources), 3),
            }
        return cast(dict[str, object], redact_value(context))

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
        final_state = cast(dict[str, object], redact_value(state))
        final_state["final_result"] = _normalized_final_result(final_state, status)
        final = self.store.update_agent_run(run.id or 0, status, current_step, final_state)
        steps = _state_steps(final_state)
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
        final_result = state.get("final_result")
        if not isinstance(final_result, dict):
            final_result = _final_result_from_step(steps[-1]) if steps else {}
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
            final_result=cast(dict[str, object], redact_value(final_result)),
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
        execution_window_timezone: str,
        context_sources: list[str],
        approval_expiry_seconds: int | None,
        approval_required_tools: list[str],
        approval_rules: list[dict[str, object]],
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
        if not isinstance(approval_required_tools, list) or len(approval_required_tools) > MAX_AGENT_STEPS:
            raise AgentDefinitionError(
                f"approval_required_tools must contain 0-{MAX_AGENT_STEPS} tools"
            )
        if any(not isinstance(tool_id, str) or not tool_id.strip() for tool_id in approval_required_tools):
            raise AgentDefinitionError("approval_required_tools must contain non-empty strings")
        if len(set(approval_required_tools)) != len(approval_required_tools):
            raise AgentDefinitionError("approval_required_tools must not contain duplicates")
        outside_enabled = sorted(set(approval_required_tools) - set(enabled_tools))
        if outside_enabled:
            raise AgentDefinitionError(
                "approval_required_tools must be enabled tools: " + ", ".join(outside_enabled)
            )
        _normalize_approval_rules(approval_rules, enabled_tools=enabled_tools)
        if not steps or len(steps) > MAX_AGENT_STEPS:
            raise AgentDefinitionError(f"steps must contain 1-{MAX_AGENT_STEPS} steps")
        if max_steps < 1 or max_steps > MAX_AGENT_STEPS or len(steps) > max_steps:
            raise AgentDefinitionError(f"max_steps must be between 1 and {MAX_AGENT_STEPS} and cover steps")
        if execution_timeout_seconds <= 0 or execution_timeout_seconds > MAX_AGENT_TIMEOUT_SECONDS:
            raise AgentDefinitionError(
                f"execution_timeout_seconds must be between 0 and {MAX_AGENT_TIMEOUT_SECONDS:g}"
            )
        _normalized_execution_window(
            execution_window_start,
            execution_window_end,
            execution_window_timezone,
        )
        _validate_context_sources(context_sources)
        if approval_expiry_seconds is not None and (
            isinstance(approval_expiry_seconds, bool)
            or not isinstance(approval_expiry_seconds, int)
            or approval_expiry_seconds < 1
            or approval_expiry_seconds > MAX_APPROVAL_EXPIRY_SECONDS
        ):
            raise AgentDefinitionError(
                "approval_expiry_seconds must be between 1 and "
                f"{MAX_APPROVAL_EXPIRY_SECONDS} seconds"
            )
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


def _normalized_execution_window(
    start: str | None,
    end: str | None,
    timezone_name: str,
) -> tuple[str | None, str | None, str]:
    if (start is None) != (end is None):
        raise AgentDefinitionError(
            "execution_window_start and execution_window_end must be provided together"
        )
    if not isinstance(timezone_name, str) or not timezone_name.strip():
        raise AgentDefinitionError("execution_window_timezone must be a valid IANA timezone")
    try:
        ZoneInfo(timezone_name.strip())
    except ZoneInfoNotFoundError as exc:
        raise AgentDefinitionError("execution_window_timezone must be a valid IANA timezone") from exc
    if start is None and end is None:
        return None, None, timezone_name.strip()
    normalized_start = _normalized_window_value(start, "execution_window_start")
    normalized_end = _normalized_window_value(end, "execution_window_end")
    if normalized_start == normalized_end:
        raise AgentDefinitionError("execution window start and end must differ")
    return normalized_start, normalized_end, timezone_name.strip()


def _normalized_window_value(value: str | None, field_name: str) -> str:
    if not isinstance(value, str):
        raise AgentDefinitionError(f"{field_name} must use HH:MM format")
    stripped = value.strip()
    if (
        len(stripped) != 5
        or stripped[2] != ":"
        or not stripped[:2].isdigit()
        or not stripped[3:].isdigit()
    ):
        raise AgentDefinitionError(f"{field_name} must use HH:MM format")
    try:
        parsed = datetime.strptime(stripped, EXECUTION_WINDOW_TIME_FORMAT)
    except ValueError as exc:
        raise AgentDefinitionError(f"{field_name} must use HH:MM format") from exc
    return parsed.strftime(EXECUTION_WINDOW_TIME_FORMAT)


def _window_minutes(value: str) -> int:
    parsed = datetime.strptime(value, EXECUTION_WINDOW_TIME_FORMAT)
    return parsed.hour * 60 + parsed.minute


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


_PLAN_RULES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("similar", "duplicate", "related ticket"), "find-similar-tickets"),
    (("documentation", "runbook", "knowledge"), "knowledge-search"),
    (("triage", "classify", "classification"), "ticket-triage"),
    (("summary", "summarize", "overview"), "ticket-summary"),
    (("resolution", "resolve", "fix", "solution"), "suggest-resolution"),
    (("quality", "qa"), "ticket-quality"),
    (("sentiment", "tone"), "ticket-sentiment"),
    (("escalat", "sla", "urgent"), "ticket-escalation"),
    (("dispatch", "assign", "technician"), "dispatch-suggestion"),
)


def _plan_tool_ids(instruction: str) -> list[str]:
    lowered = instruction.casefold()
    selected: list[str] = []
    for terms, tool_id in _PLAN_RULES:
        if any(term in lowered for term in terms) and tool_id not in selected:
            selected.append(tool_id)
    if not selected and any(term in lowered for term in ("help", "investigate", "ticket")):
        selected = ["ticket-triage", "ticket-summary"]
    return selected


def _plan_reason(tool_id: str) -> str:
    reasons = {
        "find-similar-tickets": "Compare the ticket with prior local tickets for duplicate or related work.",
        "knowledge-search": "Search the permitted tenant-scoped knowledge sources before proposing work.",
        "ticket-triage": "Classify the request using the deterministic ticket triage rules.",
        "ticket-summary": "Prepare a bounded operational summary from the ticket and permitted sources.",
        "suggest-resolution": "Prepare a resolution suggestion without claiming that a change was executed.",
        "ticket-quality": "Check required ticket fields and identify actionable quality gaps.",
        "ticket-sentiment": "Assess customer-facing sentiment for escalation handling.",
        "ticket-escalation": "Assess escalation urgency and SLA-related signals.",
        "dispatch-suggestion": "Prepare a technician dispatch suggestion; any assignment remains approval-gated.",
    }
    return reasons.get(tool_id, "Use the selected approved tool for this ticket.")


def _validate_event_filters(filters: dict[str, object]) -> None:
    unknown = sorted(set(filters) - EVENT_FILTER_FIELDS)
    if unknown:
        raise AgentDefinitionError(f"unsupported event filter fields: {', '.join(unknown)}")
    event_type = filters.get("event_type")
    if not isinstance(event_type, str) or event_type not in SUPPORTED_EVENT_TYPES:
        raise AgentDefinitionError("event filters require a supported event_type")
    for filter_name, value in filters.items():
        if filter_name == "event_type":
            continue
        if not isinstance(value, str) or not value.strip():
            raise AgentDefinitionError(f"event filter {filter_name} must be a non-empty string")


def _validate_context_sources(context_sources: list[str]) -> None:
    if not isinstance(context_sources, list) or len(context_sources) > MAX_CONTEXT_SOURCES:
        raise AgentDefinitionError(
            f"context_sources must contain 0-{MAX_CONTEXT_SOURCES} sources"
        )
    if any(not isinstance(source, str) or not source.strip() for source in context_sources):
        raise AgentDefinitionError("context_sources must contain non-empty strings")
    if len(set(context_sources)) != len(context_sources):
        raise AgentDefinitionError("context_sources must not contain duplicates")
    unknown = sorted(set(context_sources) - SUPPORTED_CONTEXT_SOURCES)
    if unknown:
        raise AgentDefinitionError(f"unsupported context sources: {', '.join(unknown)}")


def _normalize_approval_rules(
    rules: list[dict[str, object]],
    *,
    enabled_tools: list[str] | None = None,
) -> list[dict[str, object]]:
    """Normalize a small, additive approval policy for explicit ticket fields."""
    if not isinstance(rules, list) or len(rules) > MAX_APPROVAL_RULES:
        raise AgentDefinitionError(
            f"approval_rules must contain 0-{MAX_APPROVAL_RULES} rules"
        )
    normalized: list[dict[str, object]] = []
    seen_tools: set[str] = set()
    enabled = set(enabled_tools or [])
    for rule in rules:
        if not isinstance(rule, dict) or set(rule) - {"tool_id", "when"}:
            raise AgentDefinitionError("approval rules may only contain tool_id and when")
        tool_id = rule.get("tool_id")
        if not isinstance(tool_id, str) or not tool_id.strip():
            raise AgentDefinitionError("approval rule tool_id must be a non-empty string")
        tool_id = tool_id.strip()
        if enabled_tools is not None and tool_id not in enabled:
            raise AgentDefinitionError(f"approval rule tool must be enabled: {tool_id}")
        if tool_id in seen_tools:
            raise AgentDefinitionError(f"approval rules must not duplicate tool: {tool_id}")
        seen_tools.add(tool_id)
        conditions = rule.get("when")
        if not isinstance(conditions, dict) or not conditions:
            raise AgentDefinitionError("approval rule when must contain at least one condition")
        unknown_fields = sorted(set(conditions) - APPROVAL_RULE_FIELDS)
        if unknown_fields:
            raise AgentDefinitionError(
                "unsupported approval rule fields: " + ", ".join(unknown_fields)
            )
        normalized_conditions: dict[str, object] = {}
        for field_name, raw_values in conditions.items():
            if not isinstance(raw_values, list) or not raw_values or len(raw_values) > MAX_APPROVAL_RULE_VALUES:
                raise AgentDefinitionError(
                    f"approval rule {field_name} must contain 1-{MAX_APPROVAL_RULE_VALUES} values"
                )
            values: list[str] = []
            for raw_value in raw_values:
                if not isinstance(raw_value, str) or not raw_value.strip() or len(raw_value.strip()) > 40:
                    raise AgentDefinitionError(
                        f"approval rule {field_name} values must be non-empty strings of at most 40 characters"
                    )
                value = raw_value.strip().casefold()
                if field_name == "actor_role" and value not in APPROVAL_RULE_ROLE_VALUES:
                    raise AgentDefinitionError(
                        "approval rule actor_role values must be one of: "
                        + ", ".join(sorted(APPROVAL_RULE_ROLE_VALUES))
                    )
                if value not in values:
                    values.append(value)
            normalized_conditions[field_name] = values
        normalized.append({"tool_id": tool_id, "when": normalized_conditions})
    return normalized


def _approval_policy_for_ticket(
    definition: AgentDefinition,
    tool_id: str,
    entity_id: str,
    store: Store,
    *,
    actor_role: Role | None = None,
) -> dict[str, object] | None:
    if tool_id in definition.approval_required_tools:
        return {"type": "agent", "mode": "always"}
    if not definition.approval_rules:
        return None
    ticket = store.get_ticket(entity_id, client_id=definition.client_id)
    if ticket is None:
        return None
    for rule in _normalize_approval_rules(definition.approval_rules):
        if rule["tool_id"] != tool_id:
            continue
        conditions = cast(dict[str, list[str]], rule["when"])
        if all(
            (
                actor_role is not None and actor_role.label() in values
                if field_name == "actor_role"
                else str(getattr(ticket, field_name, "")).strip().casefold() in values
            )
            for field_name, values in conditions.items()
        ):
            return {"type": "conditional", "tool_id": tool_id, "when": conditions}
    return None


def _actor_role_from_state(state: dict[str, object]) -> Role | None:
    value = state.get("actor_role")
    if not isinstance(value, str):
        return None
    return next((role for role in Role if role.label() == value), None)


def _bounded_context_text(value: str, limit: int) -> str:
    return value[:limit]


def _state_steps(state: dict[str, object]) -> list[dict[str, object]]:
    steps = state.get("steps", [])
    if not isinstance(steps, list):
        return []
    return [cast(dict[str, object], item) for item in steps if isinstance(item, dict)]


def _final_result_from_action(tool_id: object, result: ActionResult) -> dict[str, object]:
    return cast(
        dict[str, object],
        redact_value(
            {
                "status": result.status,
                "tool_id": tool_id,
                "output": result.output,
                "evidence": result.evidence,
                "error_detail": result.error_detail,
            }
        ),
    )


def _final_result_from_step(step: dict[str, object]) -> dict[str, object]:
    return cast(
        dict[str, object],
        redact_value(
            {
                "status": step.get("status", "failed"),
                "tool_id": step.get("tool_id", "unknown"),
                "output": step.get("output", {}),
                "evidence": step.get("evidence", []),
                "error_detail": step.get("error_detail", ""),
            }
        ),
    )


def _bounded_step_result(step: dict[str, object] | None) -> dict[str, object]:
    if not step:
        return {}
    return cast(
        dict[str, object],
        redact_value(
            {
                "tool_id": step.get("tool_id", ""),
                "status": step.get("status", ""),
                "output": step.get("output", {}),
                "evidence": step.get("evidence", []),
                "error_detail": step.get("error_detail", ""),
            }
        ),
    )


def _continuation_lineage(step: dict[str, object] | None) -> dict[str, object]:
    """Persist bounded decision lineage without duplicating tool output."""

    if not step:
        return {
            "previous_step_index": None,
            "previous_tool_id": None,
            "previous_status": None,
            "previous_error": "",
        }
    index = step.get("index")
    return {
        "previous_step_index": index if isinstance(index, int) and not isinstance(index, bool) else None,
        "previous_tool_id": step.get("tool_id") if isinstance(step.get("tool_id"), str) else None,
        "previous_status": step.get("status") if isinstance(step.get("status"), str) else "",
        "previous_error": redact_text(str(step.get("error_detail", "")))[:240],
    }


def _normalized_final_result(state: dict[str, object], status: str) -> dict[str, object]:
    current = state.get("final_result")
    final_result = _final_result_from_step(current) if isinstance(current, dict) else {}
    if not final_result:
        final_result = {"status": status, "output": {}, "evidence": [], "error_detail": ""}
    steps = _state_steps(state)
    completed_steps = sum(1 for step in steps if step.get("status") == "success")
    failed_step = next(
        (step for step in reversed(steps) if step.get("status") not in {"success", "pending_approval"}),
        None,
    )
    final_result["history"] = {
        "attempted_steps": len(steps),
        "completed_steps": completed_steps,
        "partial": bool(completed_steps and status in {"failed", "rejected", "cancelled"}),
    }
    retry_count = state.get("retry_count")
    if isinstance(retry_count, int) and retry_count > 0:
        final_result["retry_count"] = retry_count
    retry_of_run_id = state.get("retry_of_run_id")
    if isinstance(retry_of_run_id, int):
        final_result["retry_of_run_id"] = retry_of_run_id
    if status in {"failed", "rejected", "cancelled"}:
        final_result["status"] = status
        error_detail = state.get("error_detail", "")
        if error_detail:
            final_result["error_detail"] = redact_value(str(error_detail))
        final_result["exception"] = _exception_lineage(
            status,
            str(error_detail or (failed_step or {}).get("error_detail", "")),
        )
    elif status == "pending_approval":
        final_result["exception"] = _exception_lineage("pending_approval", "")
    return cast(dict[str, object], redact_value(final_result))


def _exception_lineage(status: str, error_detail: str) -> dict[str, object]:
    """Return a small, deterministic recovery hint without exposing model reasoning."""
    normalized = error_detail.lower()
    if status == "pending_approval":
        return {
            "kind": "approval_required",
            "recoverable": True,
            "next_action": "human_approval",
        }
    if status == "cancelled":
        return {
            "kind": "cancelled",
            "recoverable": True,
            "next_action": "explicit_retry",
        }
    if status == "rejected":
        return {
            "kind": "approval_denied",
            "recoverable": False,
            "next_action": "technician_review",
        }
    if "timeout" in normalized:
        return {
            "kind": "timeout",
            "recoverable": True,
            "next_action": "explicit_retry",
        }
    if any(term in normalized for term in ("provider", "offline", "unavailable", "not configured")):
        return {
            "kind": "provider_failure",
            "recoverable": True,
            "next_action": "provider_check_or_retry",
        }
    if "malformed" in normalized or "invalid" in normalized:
        return {
            "kind": "malformed_output",
            "recoverable": False,
            "next_action": "technician_review",
        }
    if "author" in normalized or "permission" in normalized:
        return {
            "kind": "authorization_denied",
            "recoverable": False,
            "next_action": "technician_escalation",
        }
    return {
        "kind": "execution_failure",
        "recoverable": True,
        "next_action": "technician_review_or_retry",
    }
