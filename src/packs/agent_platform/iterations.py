"""Pause-after-each-step execution sessions built on the governed Smart Action runtime."""

from __future__ import annotations

import builtins
import sqlite3
import uuid
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import cast

from wait_local_agent.agents import AgentService
from wait_local_agent.rbac import Role
from wait_local_agent.reports.renderers import redact_text, redact_value
from wait_local_agent.smart_actions import ActionResult, SmartActionService
from wait_local_agent.store import Store

from .memory import MemoryService
from .skills import SkillService
from .storage import (
    AgentPlatformConflictError,
    AgentPlatformError,
    AgentPlatformNotFoundError,
    actor_identifier,
    digest_json,
    ensure_schema,
    json_dumps,
    json_loads_list,
    json_loads_object,
    require_client,
    safe_json_value,
    utc_now,
    validate_identifier,
    validate_text,
)

MAX_ITERATION_STEPS = 8
MAX_ITERATION_EVENTS = 200
_TERMINAL_STATUSES = frozenset({"completed", "failed", "rejected", "cancelled"})


@dataclass(frozen=True)
class IterationEvent:
    id: int
    session_id: str
    ordinal: int
    event_type: str
    step_index: int | None
    tool_id: str | None
    status: str
    input: dict[str, object]
    output: dict[str, object]
    approval_id: int | None
    actor: str
    created_at: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class IterationSession:
    id: str
    client_id: str
    source_type: str
    source_id: str
    source_version: int
    entity_id: str
    instruction: str
    status: str
    current_step: int
    steps: list[dict[str, object]]
    state: dict[str, object]
    approval_id: int | None
    created_by: str
    created_at: str
    updated_at: str
    events: list[IterationEvent]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class IterationService:
    def __init__(
        self,
        store: Store,
        smart_actions: SmartActionService,
        agents: AgentService,
        skills: SkillService,
        memories: MemoryService,
    ) -> None:
        self.store = store
        self.smart_actions = smart_actions
        self.agents = agents
        self.skills = skills
        self.memories = memories
        ensure_schema(store)

    def create(
        self,
        *,
        client_id: str,
        source_type: str,
        source_id: str,
        entity_id: str,
        instruction: str,
        actor: str,
        steps: list[dict[str, object]] | None = None,
        source_version: int | None = None,
    ) -> IterationSession:
        client_id = require_client(self.store, client_id)
        source_id = validate_identifier(source_id, "source_id")
        entity_id = validate_identifier(entity_id, "entity_id")
        instruction = redact_text(
            validate_text(instruction, "instruction", maximum=2_000, strip=True)
        )
        actor = actor_identifier(actor)
        if self.store.get_ticket(entity_id, client_id=client_id) is None:
            raise AgentPlatformNotFoundError("ticket was not found")
        if source_type == "agent":
            definition = self.agents.get(source_id, client_id)
            if definition is None:
                definition = self.agents.get(source_id)
            if definition is None or (
                definition.client_id is not None and definition.client_id != client_id
            ):
                raise AgentPlatformNotFoundError("agent was not found in the tenant scope")
            if not definition.enabled:
                raise AgentPlatformConflictError("disabled agents cannot start iteration sessions")
            source_version = definition.version
            allowed_tools = list(definition.enabled_tools)
            normalized_steps = _steps(definition.steps, allowed_tools)
        elif source_type == "skill":
            skill = self.skills.get(
                client_id=client_id,
                skill_id=source_id,
                version=source_version,
            )
            if skill.status != "active":
                raise AgentPlatformConflictError("archived skills cannot start iteration sessions")
            source_version = skill.revision.version
            allowed_tools = list(skill.revision.allowed_tools)
            if steps is None:
                raise AgentPlatformError("skill iteration requires an explicit bounded step list")
            normalized_steps = _steps(steps, allowed_tools)
        else:
            raise AgentPlatformError("source_type must be agent or skill")
        session_id = str(uuid.uuid4())
        now = utc_now()
        memory_context = self.memories.resolve_context(
            client_id=client_id,
            agent_id=source_id if source_type == "agent" else None,
            ticket_id=entity_id,
            limit=20,
        )
        state: dict[str, object] = {
            "allowed_tools": allowed_tools,
            "memory_context": memory_context,
            "results": [],
            "restart_count": 0,
        }
        with self.store._connect() as connection:  # noqa: SLF001
            connection.execute(
                """
                insert into agent_iteration_sessions (
                    id, client_id, source_type, source_id, source_version,
                    entity_id, instruction, status, current_step, steps_json,
                    state_json, approval_id, created_by, created_at, updated_at
                ) values (?, ?, ?, ?, ?, ?, ?, 'awaiting_continue', 0, ?, ?, null, ?, ?, ?)
                """,
                (
                    session_id,
                    client_id,
                    source_type,
                    source_id,
                    source_version,
                    entity_id,
                    instruction,
                    json_dumps(normalized_steps),
                    json_dumps(state),
                    actor,
                    now,
                    now,
                ),
            )
            self._append_event(
                connection,
                session_id=session_id,
                event_type="session.created",
                step_index=None,
                tool_id=None,
                status="awaiting_continue",
                input_payload={
                    "source_type": source_type,
                    "source_id": source_id,
                    "source_version": source_version,
                    "entity_id": entity_id,
                    "steps": len(normalized_steps),
                },
                output_payload={},
                approval_id=None,
                actor=actor,
            )
        self.store.add_audit_event(
            "agent_iteration.created",
            session_id,
            f"source={source_type}:{source_id}@{source_version} steps={len(normalized_steps)}",
            client_id=client_id,
            approver_id=actor,
        )
        return self.get(client_id=client_id, session_id=session_id)

    def list(self, *, client_id: str, status: str | None = None) -> list[IterationSession]:
        client_id = require_client(self.store, client_id)
        clauses = ["client_id = ?"]
        params: list[object] = [client_id]
        if status is not None:
            normalized = validate_text(status, "status", minimum=1, maximum=40)
            clauses.append("status = ?")
            params.append(normalized)
        with self.store._connect() as connection:  # noqa: SLF001
            rows = connection.execute(
                f"""
                select id from agent_iteration_sessions
                where {' and '.join(clauses)}
                order by updated_at desc, id
                limit 200
                """,  # nosec B608 - clauses are fixed strings
                params,
            ).fetchall()
        return [self.get(client_id=client_id, session_id=str(row["id"])) for row in rows]

    def get(self, *, client_id: str, session_id: str) -> IterationSession:
        client_id = require_client(self.store, client_id)
        session_id = validate_identifier(session_id, "session_id")
        with self.store._connect() as connection:  # noqa: SLF001
            row = connection.execute(
                "select * from agent_iteration_sessions where id = ? and client_id = ?",
                (session_id, client_id),
            ).fetchone()
            events = connection.execute(
                """
                select * from agent_iteration_events
                where session_id = ? order by ordinal asc limit ?
                """,
                (session_id, MAX_ITERATION_EVENTS),
            ).fetchall()
        if row is None:
            raise AgentPlatformNotFoundError("iteration session was not found")
        return _session(row, [_event(event) for event in events])

    def continue_once(
        self,
        *,
        client_id: str,
        session_id: str,
        actor: str,
        actor_role: Role,
    ) -> IterationSession:
        session = self.get(client_id=client_id, session_id=session_id)
        actor = actor_identifier(actor)
        if session.status in _TERMINAL_STATUSES:
            raise AgentPlatformConflictError("iteration session is already terminal")
        if session.status == "pending_approval":
            return self._consume_approval(session, actor=actor, actor_role=actor_role)
        if session.current_step >= len(session.steps):
            return self._set_terminal(
                session,
                status="completed",
                event_type="session.completed",
                actor=actor,
                output={"reason": "all steps were already processed"},
            )
        step = session.steps[session.current_step]
        tool_id = validate_identifier(str(step.get("tool_id", "")), "tool_id")
        manifest = self.smart_actions.describe(tool_id)
        _require_role(actor_role, manifest.required_role)
        allowed_tools = _string_list(session.state.get("allowed_tools"))
        if tool_id not in allowed_tools:
            raise AgentPlatformConflictError("step tool is outside the source allowlist")
        payload = _step_payload(step, manifest.input_schema, session.entity_id)
        try:
            result = self.smart_actions.invoke(
                tool_id,
                payload,
                actor,
                client_id=session.client_id,
            )
        except Exception as exc:  # persist a safe terminal state
            safe_error = redact_text(str(exc))[:2_000]
            return self._record_result(
                session,
                tool_id=tool_id,
                payload=payload,
                result=ActionResult(status="failed", error_detail=safe_error),
                actor=actor,
            )
        return self._record_result(
            session,
            tool_id=tool_id,
            payload=payload,
            result=result,
            actor=actor,
        )

    def modify_step(
        self,
        *,
        client_id: str,
        session_id: str,
        step_index: int,
        tool_id: str,
        payload: dict[str, object],
        actor: str,
        actor_role: Role,
    ) -> IterationSession:
        session = self.get(client_id=client_id, session_id=session_id)
        actor = actor_identifier(actor)
        if session.status != "awaiting_continue":
            raise AgentPlatformConflictError("steps can be modified only while awaiting continuation")
        if (
            isinstance(step_index, bool)
            or not isinstance(step_index, int)
            or step_index < session.current_step
            or step_index >= len(session.steps)
        ):
            raise AgentPlatformError("step_index must identify the current or a future step")
        tool_id = validate_identifier(tool_id, "tool_id")
        allowed_tools = _string_list(session.state.get("allowed_tools"))
        if tool_id not in allowed_tools:
            raise AgentPlatformError("tool_id is outside the source allowlist")
        manifest = self.smart_actions.describe(tool_id)
        _require_role(actor_role, manifest.required_role)
        payload = cast(dict[str, object], safe_json_value(redact_value(payload), max_bytes=16_384))
        if "_approval_completed" in payload:
            raise AgentPlatformError("reserved approval fields are not permitted")
        steps = [dict(step) for step in session.steps]
        steps[step_index] = {"tool_id": tool_id, "payload": payload}
        with self.store._connect() as connection:  # noqa: SLF001
            self._update_session(
                connection,
                session=session,
                status="awaiting_continue",
                current_step=session.current_step,
                steps=steps,
                state=session.state,
                approval_id=None,
            )
            self._append_event(
                connection,
                session_id=session.id,
                event_type="step.modified",
                step_index=step_index,
                tool_id=tool_id,
                status="awaiting_continue",
                input_payload={"payload": payload},
                output_payload={},
                approval_id=None,
                actor=actor,
            )
        self.store.add_audit_event(
            "agent_iteration.step_modified",
            session.id,
            f"step={step_index} tool={tool_id}",
            client_id=session.client_id,
            approver_id=actor,
        )
        return self.get(client_id=session.client_id, session_id=session.id)

    def restart(self, *, client_id: str, session_id: str, actor: str) -> IterationSession:
        session = self.get(client_id=client_id, session_id=session_id)
        actor = actor_identifier(actor)
        if session.status == "pending_approval":
            raise AgentPlatformConflictError("a pending approval must be decided before restart")
        raw_restart_count = session.state.get("restart_count", 0)
        restart_count = (
            raw_restart_count if isinstance(raw_restart_count, int) and not isinstance(raw_restart_count, bool) else 0
        ) + 1
        state = {
            **session.state,
            "results": [],
            "restart_count": restart_count,
        }
        with self.store._connect() as connection:  # noqa: SLF001
            self._update_session(
                connection,
                session=session,
                status="awaiting_continue",
                current_step=0,
                steps=session.steps,
                state=state,
                approval_id=None,
            )
            self._append_event(
                connection,
                session_id=session.id,
                event_type="session.restarted",
                step_index=None,
                tool_id=None,
                status="awaiting_continue",
                input_payload={"restart_count": restart_count},
                output_payload={},
                approval_id=None,
                actor=actor,
            )
        self.store.add_audit_event(
            "agent_iteration.restarted",
            session.id,
            f"restart_count={restart_count}",
            client_id=session.client_id,
            approver_id=actor,
        )
        return self.get(client_id=session.client_id, session_id=session.id)

    def finish(
        self,
        *,
        client_id: str,
        session_id: str,
        actor: str,
        reason: str,
    ) -> IterationSession:
        session = self.get(client_id=client_id, session_id=session_id)
        if session.status == "pending_approval":
            raise AgentPlatformConflictError("a pending approval must be decided before finishing")
        if session.status in _TERMINAL_STATUSES:
            return session
        actor = actor_identifier(actor)
        reason = redact_text(validate_text(reason, "reason", maximum=1_000))
        return self._set_terminal(
            session,
            status="completed",
            event_type="session.finished",
            actor=actor,
            output={
                "reason": reason,
                "skipped_steps": max(0, len(session.steps) - session.current_step),
            },
        )

    def _record_result(
        self,
        session: IterationSession,
        *,
        tool_id: str,
        payload: dict[str, object],
        result: ActionResult,
        actor: str,
    ) -> IterationSession:
        safe_result = _bounded_result(result)
        if result.status == "pending_approval":
            status = "pending_approval"
            next_step = session.current_step
            approval_id = result.approval_id
        elif result.status == "success":
            next_step = session.current_step + 1
            status = "completed" if next_step >= len(session.steps) else "awaiting_continue"
            approval_id = None
        elif result.status == "rejected":
            next_step = session.current_step
            status = "rejected"
            approval_id = result.approval_id
        else:
            next_step = session.current_step
            status = "failed"
            approval_id = result.approval_id
        results = _mapping_list(session.state.get("results"))
        if result.status != "pending_approval":
            results.append(
                {
                    "step_index": session.current_step,
                    "tool_id": tool_id,
                    "result": safe_result,
                }
            )
        state = {**session.state, "results": results[-MAX_ITERATION_STEPS:]}
        with self.store._connect() as connection:  # noqa: SLF001
            self._update_session(
                connection,
                session=session,
                status=status,
                current_step=next_step,
                steps=session.steps,
                state=state,
                approval_id=approval_id,
            )
            self._append_event(
                connection,
                session_id=session.id,
                event_type=(
                    "step.pending_approval"
                    if result.status == "pending_approval"
                    else "step.completed"
                    if result.status == "success"
                    else "step.rejected"
                    if result.status == "rejected"
                    else "step.failed"
                ),
                step_index=session.current_step,
                tool_id=tool_id,
                status=result.status,
                input_payload=payload,
                output_payload=safe_result,
                approval_id=approval_id,
                actor=actor,
            )
        self.store.add_audit_event(
            "agent_iteration.step",
            session.id,
            f"step={session.current_step} tool={tool_id} status={result.status}",
            client_id=session.client_id,
            approver_id=actor,
        )
        return self.get(client_id=session.client_id, session_id=session.id)

    def _consume_approval(
        self,
        session: IterationSession,
        *,
        actor: str,
        actor_role: Role,
    ) -> IterationSession:
        if session.approval_id is None:
            raise AgentPlatformConflictError("iteration session has no approval reference")
        approval = self.store.get_approval_request(session.approval_id)
        if approval is None or approval.client_id != session.client_id:
            return self._set_terminal(
                session,
                status="failed",
                event_type="approval.missing",
                actor=actor,
                output={"approval_id": session.approval_id},
            )
        if approval.status == "pending":
            return session
        if approval.status in {"rejected", "expired"}:
            return self._set_terminal(
                session,
                status="rejected",
                event_type=f"approval.{approval.status}",
                actor=actor,
                output={"approval_id": approval.id, "status": approval.status},
            )
        runs = [
            run
            for run in self.store.list_smart_action_runs(client_id=session.client_id)
            if run.approval_id == session.approval_id
        ]
        if not runs:
            return self._set_terminal(
                session,
                status="failed",
                event_type="approval.execution_missing",
                actor=actor,
                output={"approval_id": session.approval_id},
            )
        run = runs[-1]
        if run.status == "pending_approval":
            if approval.approver_id:
                try:
                    self.smart_actions.complete_approval(
                        session.approval_id,
                        approver=approval.approver_id,
                        approver_role=actor_role,
                    )
                except (PermissionError, ValueError):
                    return session
                runs = [
                    item
                    for item in self.store.list_smart_action_runs(client_id=session.client_id)
                    if item.approval_id == session.approval_id
                ]
                run = runs[-1]
            else:
                return session
        result = ActionResult(
            status=(
                "success"
                if run.status == "success"
                else "rejected"
                if run.status == "rejected"
                else "failed"
            ),
            output=cast(dict[str, object], json_loads_object(run.output_json)),
            evidence=[
                cast(dict[str, object], item)
                for item in json_loads_list(run.evidence_json)
                if isinstance(item, Mapping)
            ],
            approval_id=session.approval_id,
        )
        tool_id = str(session.steps[session.current_step].get("tool_id", ""))
        return self._record_result(
            session,
            tool_id=tool_id,
            payload={"approval_id": session.approval_id},
            result=result,
            actor=actor,
        )

    def _set_terminal(
        self,
        session: IterationSession,
        *,
        status: str,
        event_type: str,
        actor: str,
        output: dict[str, object],
    ) -> IterationSession:
        with self.store._connect() as connection:  # noqa: SLF001
            self._update_session(
                connection,
                session=session,
                status=status,
                current_step=session.current_step,
                steps=session.steps,
                state=session.state,
                approval_id=None,
            )
            self._append_event(
                connection,
                session_id=session.id,
                event_type=event_type,
                step_index=session.current_step,
                tool_id=None,
                status=status,
                input_payload={},
                output_payload=output,
                approval_id=None,
                actor=actor,
            )
        self.store.add_audit_event(
            f"agent_iteration.{status}",
            session.id,
            f"status={status}",
            client_id=session.client_id,
            approver_id=actor,
        )
        return self.get(client_id=session.client_id, session_id=session.id)

    def _update_session(
        self,
        connection: sqlite3.Connection,
        *,
        session: IterationSession,
        status: str,
        current_step: int,
        steps: builtins.list[dict[str, object]],
        state: dict[str, object],
        approval_id: int | None,
    ) -> None:
        cursor = connection.execute(
            """
            update agent_iteration_sessions
            set status = ?, current_step = ?, steps_json = ?, state_json = ?,
                approval_id = ?, updated_at = ?
            where id = ? and client_id = ? and updated_at = ?
            """,
            (
                status,
                current_step,
                json_dumps(steps),
                json_dumps(state),
                approval_id,
                utc_now(),
                session.id,
                session.client_id,
                session.updated_at,
            ),
        )
        if cursor.rowcount != 1:
            raise AgentPlatformConflictError("iteration session was updated concurrently")

    def _append_event(
        self,
        connection: sqlite3.Connection,
        *,
        session_id: str,
        event_type: str,
        step_index: int | None,
        tool_id: str | None,
        status: str,
        input_payload: dict[str, object],
        output_payload: dict[str, object],
        approval_id: int | None,
        actor: str,
    ) -> None:
        row = connection.execute(
            "select coalesce(max(ordinal), -1) + 1 from agent_iteration_events where session_id = ?",
            (session_id,),
        ).fetchone()
        ordinal = int(row[0]) if row is not None else 0
        connection.execute(
            """
            insert into agent_iteration_events (
                session_id, ordinal, event_type, step_index, tool_id, status,
                input_json, output_json, approval_id, actor, created_at
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                ordinal,
                event_type,
                step_index,
                tool_id,
                status,
                json_dumps(redact_value(input_payload)),
                json_dumps(redact_value(output_payload)),
                approval_id,
                actor,
                utc_now(),
            ),
        )


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _mapping_list(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, Mapping)]


def _session(row: sqlite3.Row, events: list[IterationEvent]) -> IterationSession:
    return IterationSession(
        id=str(row["id"]),
        client_id=str(row["client_id"]),
        source_type=str(row["source_type"]),
        source_id=str(row["source_id"]),
        source_version=int(row["source_version"]),
        entity_id=str(row["entity_id"]),
        instruction=str(row["instruction"]),
        status=str(row["status"]),
        current_step=int(row["current_step"]),
        steps=[
            cast(dict[str, object], item)
            for item in json_loads_list(str(row["steps_json"]))
            if isinstance(item, Mapping)
        ],
        state=cast(dict[str, object], json_loads_object(str(row["state_json"]))),
        approval_id=int(row["approval_id"]) if row["approval_id"] is not None else None,
        created_by=str(row["created_by"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
        events=events,
    )


def _event(row: sqlite3.Row) -> IterationEvent:
    return IterationEvent(
        id=int(row["id"]),
        session_id=str(row["session_id"]),
        ordinal=int(row["ordinal"]),
        event_type=str(row["event_type"]),
        step_index=int(row["step_index"]) if row["step_index"] is not None else None,
        tool_id=str(row["tool_id"]) if row["tool_id"] is not None else None,
        status=str(row["status"]),
        input=cast(dict[str, object], json_loads_object(str(row["input_json"]))),
        output=cast(dict[str, object], json_loads_object(str(row["output_json"]))),
        approval_id=int(row["approval_id"]) if row["approval_id"] is not None else None,
        actor=str(row["actor"]),
        created_at=str(row["created_at"]),
    )


def _steps(values: list[dict[str, object]], allowed_tools: list[str]) -> list[dict[str, object]]:
    if not isinstance(values, list) or not 1 <= len(values) <= MAX_ITERATION_STEPS:
        raise AgentPlatformError(
            f"steps must contain between 1 and {MAX_ITERATION_STEPS} entries"
        )
    normalized: list[dict[str, object]] = []
    for index, raw in enumerate(values):
        if not isinstance(raw, Mapping):
            raise AgentPlatformError(f"step {index} must be an object")
        tool_id = validate_identifier(str(raw.get("tool_id", "")), f"steps[{index}].tool_id")
        if tool_id not in allowed_tools:
            raise AgentPlatformError(f"step {index} tool is outside the source allowlist")
        payload = raw.get("payload", {})
        if not isinstance(payload, Mapping):
            raise AgentPlatformError(f"steps[{index}].payload must be an object")
        safe_payload = cast(
            dict[str, object], safe_json_value(redact_value(dict(payload)), max_bytes=16_384)
        )
        if "_approval_completed" in safe_payload:
            raise AgentPlatformError("reserved approval fields are not permitted")
        normalized.append({"tool_id": tool_id, "payload": safe_payload})
    return normalized


def _step_payload(
    step: Mapping[str, object],
    input_schema: Mapping[str, object],
    entity_id: str,
) -> dict[str, object]:
    raw = step.get("payload", {})
    payload = dict(raw) if isinstance(raw, Mapping) else {}
    properties = input_schema.get("properties", {})
    required = input_schema.get("required", [])
    ticket_supported = (
        isinstance(properties, Mapping) and "ticket_id" in properties
    ) or (isinstance(required, list) and "ticket_id" in required)
    if ticket_supported and "ticket_id" not in payload:
        payload["ticket_id"] = entity_id
    return cast(dict[str, object], safe_json_value(redact_value(payload), max_bytes=16_384))


def _require_role(role: Role, required_role: str) -> None:
    required = {
        "end_user": Role.END_USER,
        "viewer": Role.VIEWER,
        "technician": Role.TECHNICIAN,
        "admin": Role.ADMIN,
    }.get(required_role.strip().lower(), Role.TECHNICIAN)
    if role < required:
        raise PermissionError(f"tool requires {required.label()} authority")


def _bounded_result(result: ActionResult) -> dict[str, object]:
    payload = cast(dict[str, object], redact_value(asdict(result)))
    encoded = json_dumps(payload).encode("utf-8")
    if len(encoded) <= 64_000:
        return payload
    return {
        "status": result.status,
        "approval_id": result.approval_id,
        "run_id": result.run_id,
        "truncated": True,
        "sha256": digest_json(payload),
        "error_detail": redact_text(result.error_detail)[:2_000],
    }


__all__ = ["IterationEvent", "IterationService", "IterationSession"]
