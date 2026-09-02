"""Authenticated API routes for durable agent-platform capabilities."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, Any, Literal, TypeVar, cast

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field

from wait_local_agent.agents import AgentService
from wait_local_agent.client_scope import requested_client_from, resolve_client_scope
from wait_local_agent.rbac import AuthContext, Role, require_role
from wait_local_agent.smart_actions import SmartActionService
from wait_local_agent.store import Store

from .iterations import IterationService
from .memory import MemoryService
from .skills import SkillService
from .storage import (
    AGENT_PLATFORM_MIGRATION_VERSION,
    AgentPlatformConflictError,
    AgentPlatformError,
    AgentPlatformNotFoundError,
    ensure_schema,
)
from .technicians import TechnicianService
from .vision import AttachmentService, MAX_ATTACHMENT_BYTES

ViewerAccess = Annotated[AuthContext, Depends(require_role(Role.VIEWER))]
TechnicianAccess = Annotated[AuthContext, Depends(require_role(Role.TECHNICIAN))]
AdminAccess = Annotated[AuthContext, Depends(require_role(Role.ADMIN))]
T = TypeVar("T")


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MemoryCreateRequest(StrictModel):
    client_id: str | None = None
    scope_type: Literal["client", "agent", "technician", "ticket"]
    scope_id: str = ""
    key: str = Field(min_length=1, max_length=128)
    value: Any
    summary: str = Field(default="", max_length=1_000)
    provenance: str = Field(min_length=1, max_length=1_000)
    pinned: bool = False
    expires_at: str | None = None


class MemoryPinRequest(StrictModel):
    pinned: bool = True
    client_id: str | None = None


class MemoryRestoreRequest(StrictModel):
    client_id: str | None = None


class SkillResourceRequest(StrictModel):
    name: str = Field(min_length=1, max_length=120)
    media_type: Literal["text/plain", "text/markdown", "application/json"] = "text/plain"
    content: str = Field(default="", max_length=20_000)


class SkillCreateRequest(StrictModel):
    client_id: str | None = None
    name: str = Field(min_length=1, max_length=120)
    slug: str = Field(min_length=1, max_length=63)
    description: str = Field(default="", max_length=2_000)
    instructions: str = Field(min_length=1, max_length=20_000)
    allowed_tools: list[str] = Field(default_factory=list, max_length=16)
    input_schema: dict[str, object] = Field(default_factory=lambda: cast(dict[str, object], {"type": "object"}))
    resources: list[SkillResourceRequest] = Field(default_factory=list, max_length=10)


class SkillUpdateRequest(StrictModel):
    client_id: str | None = None
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2_000)
    instructions: str | None = Field(default=None, min_length=1, max_length=20_000)
    allowed_tools: list[str] | None = Field(default=None, max_length=16)
    input_schema: dict[str, object] | None = None
    resources: list[SkillResourceRequest] | None = Field(default=None, max_length=10)


class SkillTestRequest(StrictModel):
    client_id: str | None = None
    version: int | None = Field(default=None, ge=1)
    sample_input: dict[str, object] = Field(default_factory=dict)
    memory: dict[str, object] = Field(default_factory=dict)


class IterationStepRequest(StrictModel):
    tool_id: str = Field(min_length=1, max_length=128)
    payload: dict[str, object] = Field(default_factory=dict)


class IterationCreateRequest(StrictModel):
    client_id: str | None = None
    source_type: Literal["agent", "skill"]
    source_id: str = Field(min_length=1, max_length=128)
    source_version: int | None = Field(default=None, ge=1)
    entity_id: str = Field(min_length=1, max_length=128)
    instruction: str = Field(default="", max_length=2_000)
    steps: list[IterationStepRequest] | None = Field(default=None, max_length=8)


class IterationControlRequest(StrictModel):
    client_id: str | None = None


class IterationModifyRequest(StrictModel):
    client_id: str | None = None
    tool_id: str = Field(min_length=1, max_length=128)
    payload: dict[str, object] = Field(default_factory=dict)


class IterationFinishRequest(StrictModel):
    client_id: str | None = None
    reason: str = Field(default="", max_length=1_000)


class TechnicianProfileRequest(StrictModel):
    client_id: str | None = None
    display_name: str = Field(min_length=1, max_length=160)
    timezone: str = Field(default="UTC", min_length=1, max_length=80)
    working_hours: dict[str, object] = Field(default_factory=dict)
    expertise: list[str] = Field(default_factory=list, max_length=32)
    client_familiarity: int = Field(default=0, ge=0, le=5)
    capacity: int = Field(default=40, ge=1, le=100)
    enabled: bool = True


class TechnicianWorkloadRequest(StrictModel):
    client_id: str | None = None
    open_tickets: int = Field(default=0, ge=0)
    active_incidents: int = Field(default=0, ge=0)
    scheduled_changes: int = Field(default=0, ge=0)
    unavailable_until: str | None = None
    source: str = Field(min_length=1, max_length=120)
    observed_at: str | None = None


class TechnicianRecommendRequest(StrictModel):
    client_id: str | None = None
    ticket_id: str = Field(min_length=1, max_length=128)
    required_expertise: list[str] = Field(default_factory=list, max_length=32)
    limit: int = Field(default=5, ge=1, le=20)
    now: str | None = None


class AttachmentUploadRequest(StrictModel):
    client_id: str | None = None
    filename: str = Field(min_length=1, max_length=180)
    media_type: Literal["image/png", "image/jpeg", "image/webp"]
    content_base64: str = Field(
        min_length=1,
        max_length=(MAX_ATTACHMENT_BYTES * 4 // 3) + 64,
    )


class AttachmentAnalyzeRequest(StrictModel):
    client_id: str | None = None
    prompt: str = Field(default="", max_length=2_000)


@dataclass(frozen=True)
class _Services:
    memories: MemoryService
    skills: SkillService
    iterations: IterationService
    technicians: TechnicianService
    attachments: AttachmentService


def create_router() -> APIRouter:
    router = APIRouter()

    @router.get("/status")
    def platform_status(request: Request, _: ViewerAccess) -> dict[str, object]:
        services = _services(request)
        return {
            "status": "ready",
            "migration_version": AGENT_PLATFORM_MIGRATION_VERSION,
            "capabilities": {
                "durable_memory": True,
                "versioned_skills": True,
                "skill_validation_harness": True,
                "step_iteration": True,
                "technician_ranking": True,
                "ticket_image_context": True,
            },
            "attachment_max_bytes": MAX_ATTACHMENT_BYTES,
            "write_actions_enabled": request.app.state.settings.allow_write_actions,
            "llm_inference_enabled": request.app.state.settings.allow_llm_inference,
            "initialized": services is not None,
        }

    @router.get("/memories")
    def list_memories(
        request: Request,
        context: ViewerAccess,
        client_id: str | None = None,
        scope_type: Literal["client", "agent", "technician", "ticket"] | None = None,
        scope_id: str | None = None,
        key: str | None = None,
        include_history: bool = False,
        limit: int = 50,
    ) -> list[dict[str, object]]:
        scoped_client = _scope(request, context, client_id)
        return [
            record.to_dict()
            for record in _call(
                lambda: _services(request).memories.list(
                    client_id=scoped_client,
                    scope_type=scope_type,
                    scope_id=scope_id,
                    key=key,
                    include_history=include_history,
                    limit=limit,
                )
            )
        ]

    @router.post("/memories", status_code=201)
    def create_memory(
        payload: MemoryCreateRequest,
        request: Request,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        scoped_client = _scope(request, context, payload.client_id)
        record = _call(
            lambda: _services(request).memories.put(
                client_id=scoped_client,
                scope_type=payload.scope_type,
                scope_id=payload.scope_id,
                key=payload.key,
                value=payload.value,
                summary=payload.summary,
                provenance=payload.provenance,
                actor=_actor(context),
                pinned=payload.pinned,
                expires_at=payload.expires_at,
            )
        )
        return record.to_dict()

    @router.get("/memories/{memory_id}")
    def get_memory(
        memory_id: str,
        request: Request,
        context: ViewerAccess,
        client_id: str | None = None,
        include_history: bool = False,
    ) -> dict[str, object]:
        scoped_client = _scope(request, context, client_id)
        record = _call(
            lambda: _services(request).memories.get(
                client_id=scoped_client,
                memory_id=memory_id,
                include_history=include_history,
            )
        )
        return record.to_dict()

    @router.post("/memories/{memory_id}/pin")
    def pin_memory(
        memory_id: str,
        payload: MemoryPinRequest,
        request: Request,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        scoped_client = _scope(request, context, payload.client_id)
        record = _call(
            lambda: _services(request).memories.pin(
                client_id=scoped_client,
                memory_id=memory_id,
                pinned=payload.pinned,
                actor=_actor(context),
            )
        )
        return record.to_dict()

    @router.post("/memories/{memory_id}/restore")
    def restore_memory(
        memory_id: str,
        payload: MemoryRestoreRequest,
        request: Request,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        scoped_client = _scope(request, context, payload.client_id)
        record = _call(
            lambda: _services(request).memories.restore(
                client_id=scoped_client,
                memory_id=memory_id,
                actor=_actor(context),
            )
        )
        return record.to_dict()

    @router.delete("/memories/{memory_id}")
    def delete_memory(
        memory_id: str,
        request: Request,
        context: TechnicianAccess,
        client_id: str | None = None,
    ) -> dict[str, object]:
        scoped_client = _scope(request, context, client_id)
        record = _call(
            lambda: _services(request).memories.delete(
                client_id=scoped_client,
                memory_id=memory_id,
                actor=_actor(context),
            )
        )
        return record.to_dict()

    @router.get("/context")
    def memory_context(
        request: Request,
        context: ViewerAccess,
        client_id: str | None = None,
        agent_id: str | None = None,
        technician_id: str | None = None,
        ticket_id: str | None = None,
        limit: int = 20,
    ) -> dict[str, object]:
        scoped_client = _scope(request, context, client_id)
        memories = _call(
            lambda: _services(request).memories.resolve_context(
                client_id=scoped_client,
                agent_id=agent_id,
                technician_id=technician_id,
                ticket_id=ticket_id,
                limit=limit,
            )
        )
        return {"client_id": scoped_client, "memories": memories, "count": len(memories)}

    @router.get("/skills")
    def list_skills(
        request: Request,
        context: ViewerAccess,
        client_id: str | None = None,
        include_archived: bool = False,
    ) -> list[dict[str, object]]:
        scoped_client = _scope(request, context, client_id)
        return [
            skill.to_dict()
            for skill in _call(
                lambda: _services(request).skills.list(
                    client_id=scoped_client,
                    include_archived=include_archived,
                )
            )
        ]

    @router.post("/skills", status_code=201)
    def create_skill(
        payload: SkillCreateRequest,
        request: Request,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        scoped_client = _scope(request, context, payload.client_id)
        skill = _call(
            lambda: _services(request).skills.create(
                client_id=scoped_client,
                name=payload.name,
                slug=payload.slug,
                description=payload.description,
                instructions=payload.instructions,
                allowed_tools=payload.allowed_tools,
                input_schema=payload.input_schema,
                resources=[resource.model_dump() for resource in payload.resources],
                actor=_actor(context),
            )
        )
        return skill.to_dict()

    @router.get("/skills/{skill_id}")
    def get_skill(
        skill_id: str,
        request: Request,
        context: ViewerAccess,
        client_id: str | None = None,
        version: int | None = None,
    ) -> dict[str, object]:
        scoped_client = _scope(request, context, client_id)
        skill = _call(
            lambda: _services(request).skills.get(
                client_id=scoped_client,
                skill_id=skill_id,
                version=version,
            )
        )
        return skill.to_dict()

    @router.put("/skills/{skill_id}")
    def update_skill(
        skill_id: str,
        payload: SkillUpdateRequest,
        request: Request,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        scoped_client = _scope(request, context, payload.client_id)
        skill = _call(
            lambda: _services(request).skills.update(
                client_id=scoped_client,
                skill_id=skill_id,
                actor=_actor(context),
                name=payload.name,
                description=payload.description,
                instructions=payload.instructions,
                allowed_tools=payload.allowed_tools,
                input_schema=payload.input_schema,
                resources=(
                    [resource.model_dump() for resource in payload.resources]
                    if payload.resources is not None
                    else None
                ),
            )
        )
        return skill.to_dict()

    @router.get("/skills/{skill_id}/revisions")
    def skill_revisions(
        skill_id: str,
        request: Request,
        context: ViewerAccess,
        client_id: str | None = None,
    ) -> list[dict[str, object]]:
        scoped_client = _scope(request, context, client_id)
        return [
            revision.to_dict()
            for revision in _call(
                lambda: _services(request).skills.revisions(
                    client_id=scoped_client,
                    skill_id=skill_id,
                )
            )
        ]

    @router.post("/skills/{skill_id}/tests", status_code=201)
    def test_skill(
        skill_id: str,
        payload: SkillTestRequest,
        request: Request,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        scoped_client = _scope(request, context, payload.client_id)
        result = _call(
            lambda: _services(request).skills.test(
                client_id=scoped_client,
                skill_id=skill_id,
                sample_input=payload.sample_input,
                memory=payload.memory,
                actor=_actor(context),
                version=payload.version,
            )
        )
        return result.to_dict()

    @router.get("/skills/{skill_id}/tests")
    def skill_test_runs(
        skill_id: str,
        request: Request,
        context: ViewerAccess,
        client_id: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, object]]:
        scoped_client = _scope(request, context, client_id)
        return [
            run.to_dict()
            for run in _call(
                lambda: _services(request).skills.test_runs(
                    client_id=scoped_client,
                    skill_id=skill_id,
                    limit=limit,
                )
            )
        ]

    @router.post("/skills/{skill_id}/archive")
    def archive_skill(
        skill_id: str,
        payload: IterationControlRequest,
        request: Request,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        scoped_client = _scope(request, context, payload.client_id)
        skill = _call(
            lambda: _services(request).skills.archive(
                client_id=scoped_client,
                skill_id=skill_id,
                actor=_actor(context),
            )
        )
        return skill.to_dict()

    @router.get("/iterations")
    def list_iterations(
        request: Request,
        context: ViewerAccess,
        client_id: str | None = None,
        iteration_status: str | None = None,
    ) -> list[dict[str, object]]:
        scoped_client = _scope(request, context, client_id)
        return [
            session.to_dict()
            for session in _call(
                lambda: _services(request).iterations.list(
                    client_id=scoped_client,
                    status=iteration_status,
                )
            )
        ]

    @router.post("/iterations", status_code=201)
    def create_iteration(
        payload: IterationCreateRequest,
        request: Request,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        scoped_client = _scope(request, context, payload.client_id)
        session = _call(
            lambda: _services(request).iterations.create(
                client_id=scoped_client,
                source_type=payload.source_type,
                source_id=payload.source_id,
                source_version=payload.source_version,
                entity_id=payload.entity_id,
                instruction=payload.instruction,
                steps=(
                    [step.model_dump() for step in payload.steps]
                    if payload.steps is not None
                    else None
                ),
                actor=_actor(context),
            )
        )
        return session.to_dict()

    @router.get("/iterations/{session_id}")
    def get_iteration(
        session_id: str,
        request: Request,
        context: ViewerAccess,
        client_id: str | None = None,
    ) -> dict[str, object]:
        scoped_client = _scope(request, context, client_id)
        session = _call(
            lambda: _services(request).iterations.get(
                client_id=scoped_client,
                session_id=session_id,
            )
        )
        return session.to_dict()

    @router.post("/iterations/{session_id}/continue")
    def continue_iteration(
        session_id: str,
        payload: IterationControlRequest,
        request: Request,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        scoped_client = _scope(request, context, payload.client_id)
        session = _call(
            lambda: _services(request).iterations.continue_once(
                client_id=scoped_client,
                session_id=session_id,
                actor=_actor(context),
                actor_role=context.role,
            )
        )
        return session.to_dict()

    @router.patch("/iterations/{session_id}/steps/{step_index}")
    def modify_iteration_step(
        session_id: str,
        step_index: int,
        payload: IterationModifyRequest,
        request: Request,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        scoped_client = _scope(request, context, payload.client_id)
        session = _call(
            lambda: _services(request).iterations.modify_step(
                client_id=scoped_client,
                session_id=session_id,
                step_index=step_index,
                tool_id=payload.tool_id,
                payload=payload.payload,
                actor=_actor(context),
                actor_role=context.role,
            )
        )
        return session.to_dict()

    @router.post("/iterations/{session_id}/restart")
    def restart_iteration(
        session_id: str,
        payload: IterationControlRequest,
        request: Request,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        scoped_client = _scope(request, context, payload.client_id)
        session = _call(
            lambda: _services(request).iterations.restart(
                client_id=scoped_client,
                session_id=session_id,
                actor=_actor(context),
            )
        )
        return session.to_dict()

    @router.post("/iterations/{session_id}/finish")
    def finish_iteration(
        session_id: str,
        payload: IterationFinishRequest,
        request: Request,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        scoped_client = _scope(request, context, payload.client_id)
        session = _call(
            lambda: _services(request).iterations.finish(
                client_id=scoped_client,
                session_id=session_id,
                actor=_actor(context),
                reason=payload.reason,
            )
        )
        return session.to_dict()

    @router.get("/technicians")
    def list_technicians(
        request: Request,
        context: ViewerAccess,
        client_id: str | None = None,
        include_disabled: bool = False,
    ) -> list[dict[str, object]]:
        scoped_client = _scope(request, context, client_id)
        return [
            profile.to_dict()
            for profile in _call(
                lambda: _services(request).technicians.list(
                    client_id=scoped_client,
                    include_disabled=include_disabled,
                )
            )
        ]

    @router.put("/technicians/{technician_id}")
    def upsert_technician(
        technician_id: str,
        payload: TechnicianProfileRequest,
        request: Request,
        context: AdminAccess,
    ) -> dict[str, object]:
        scoped_client = _scope(request, context, payload.client_id)
        profile = _call(
            lambda: _services(request).technicians.upsert_profile(
                client_id=scoped_client,
                technician_id=technician_id,
                display_name=payload.display_name,
                timezone=payload.timezone,
                working_hours=payload.working_hours,
                expertise=payload.expertise,
                client_familiarity=payload.client_familiarity,
                capacity=payload.capacity,
                enabled=payload.enabled,
                actor=_actor(context),
            )
        )
        return profile.to_dict()

    @router.post("/technicians/{technician_id}/workloads", status_code=201)
    def record_technician_workload(
        technician_id: str,
        payload: TechnicianWorkloadRequest,
        request: Request,
        context: AdminAccess,
    ) -> dict[str, object]:
        scoped_client = _scope(request, context, payload.client_id)
        workload = _call(
            lambda: _services(request).technicians.record_workload(
                client_id=scoped_client,
                technician_id=technician_id,
                open_tickets=payload.open_tickets,
                active_incidents=payload.active_incidents,
                scheduled_changes=payload.scheduled_changes,
                unavailable_until=payload.unavailable_until,
                source=payload.source,
                observed_at=payload.observed_at,
                actor=_actor(context),
            )
        )
        return workload.to_dict()

    @router.post("/technicians/recommend")
    def recommend_technician(
        payload: TechnicianRecommendRequest,
        request: Request,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        scoped_client = _scope(request, context, payload.client_id)
        return _call(
            lambda: _services(request).technicians.recommend(
                client_id=scoped_client,
                ticket_id=payload.ticket_id,
                required_expertise=payload.required_expertise,
                limit=payload.limit,
                now=payload.now,
            )
        )

    @router.get("/tickets/{ticket_id}/attachments")
    def list_ticket_attachments(
        ticket_id: str,
        request: Request,
        context: ViewerAccess,
        client_id: str | None = None,
    ) -> list[dict[str, object]]:
        scoped_client = _scope(request, context, client_id)
        return [
            attachment.to_dict()
            for attachment in _call(
                lambda: _services(request).attachments.list(
                    client_id=scoped_client,
                    ticket_id=ticket_id,
                )
            )
        ]

    @router.post("/tickets/{ticket_id}/attachments", status_code=201)
    def upload_ticket_attachment(
        ticket_id: str,
        payload: AttachmentUploadRequest,
        request: Request,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        scoped_client = _scope(request, context, payload.client_id)
        attachment = _call(
            lambda: _services(request).attachments.upload(
                client_id=scoped_client,
                ticket_id=ticket_id,
                filename=payload.filename,
                media_type=payload.media_type,
                content_base64=payload.content_base64,
                actor=_actor(context),
            )
        )
        return attachment.to_dict()

    @router.get("/tickets/{ticket_id}/attachments/analyses")
    def list_attachment_analyses(
        ticket_id: str,
        request: Request,
        context: ViewerAccess,
        client_id: str | None = None,
        attachment_id: str | None = None,
    ) -> list[dict[str, object]]:
        scoped_client = _scope(request, context, client_id)
        return [
            analysis.to_dict()
            for analysis in _call(
                lambda: _services(request).attachments.analyses(
                    client_id=scoped_client,
                    ticket_id=ticket_id,
                    attachment_id=attachment_id,
                )
            )
        ]

    @router.post("/tickets/{ticket_id}/attachments/{attachment_id}/analyze", status_code=201)
    def analyze_ticket_attachment(
        ticket_id: str,
        attachment_id: str,
        payload: AttachmentAnalyzeRequest,
        request: Request,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        scoped_client = _scope(request, context, payload.client_id)
        analysis = _call(
            lambda: _services(request).attachments.analyze(
                client_id=scoped_client,
                ticket_id=ticket_id,
                attachment_id=attachment_id,
                prompt=payload.prompt,
                actor=_actor(context),
            )
        )
        return analysis.to_dict()

    @router.get("/tickets/{ticket_id}/context")
    def ticket_agent_context(
        ticket_id: str,
        request: Request,
        context: ViewerAccess,
        client_id: str | None = None,
        agent_id: str | None = None,
        technician_id: str | None = None,
    ) -> dict[str, object]:
        scoped_client = _scope(request, context, client_id)
        return _call(
            lambda: _services(request).attachments.ticket_context(
                client_id=scoped_client,
                ticket_id=ticket_id,
                agent_id=agent_id,
                technician_id=technician_id,
            )
        )

    return router


def _services(request: Request) -> _Services:
    cached = getattr(request.app.state, "agent_platform_services", None)
    if isinstance(cached, _Services):
        return cached
    store = cast(Store, request.app.state.store)
    settings = request.app.state.settings
    ensure_schema(store)
    scheduler = getattr(request.app.state, "scheduler", None)
    scheduled_smart_actions = getattr(scheduler, "_smart_action_service", None)
    scheduled_agents = getattr(scheduler, "_agent_service", None)
    smart_actions = (
        scheduled_smart_actions
        if isinstance(scheduled_smart_actions, SmartActionService)
        else SmartActionService(store, settings)
    )
    agents = (
        scheduled_agents
        if isinstance(scheduled_agents, AgentService)
        else AgentService(store, settings, smart_actions)
    )
    memories = MemoryService(store)
    skills = SkillService(store, smart_actions)
    services = _Services(
        memories=memories,
        skills=skills,
        iterations=IterationService(store, smart_actions, agents, skills, memories),
        technicians=TechnicianService(store),
        attachments=AttachmentService(store, settings, memories),
    )
    request.app.state.agent_platform_services = services
    return services


def _scope(
    request: Request,
    context: AuthContext,
    requested_client_id: str | None,
) -> str:
    selected_client_id = requested_client_from(request, requested_client_id) or context.client_id
    scope = resolve_client_scope(context, selected_client_id)
    if scope.client_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="one explicit client scope is required",
        )
    return scope.client_id


def _actor(context: AuthContext) -> str:
    return context.principal_id or context.approver_id or ("demo" if context.demo_mode else "api")


def _call(operation: Callable[[], T]) -> T:
    try:
        return operation()
    except (AgentPlatformNotFoundError, KeyError) as exc:
        detail = str(exc) if isinstance(exc, AgentPlatformNotFoundError) else "referenced resource was not found"
        raise HTTPException(status_code=404, detail=detail) from exc
    except AgentPlatformConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except AgentPlatformError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


__all__ = ["create_router"]
