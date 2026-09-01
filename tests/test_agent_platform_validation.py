from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import httpx
import pytest

from packs.agent_platform.iterations import (
    IterationEvent,
    IterationService,
    IterationSession,
    _bounded_result,
    _mapping_list,
    _require_role,
    _step_payload,
    _steps,
    _string_list,
)
from packs.agent_platform.memory import MemoryService, _scope
from packs.agent_platform.router import _services
from packs.agent_platform.skills import (
    SkillRecord,
    SkillService,
    _render,
    _resources,
    _schema,
    _slug,
    _tools,
    _validate_schema,
    _version,
)
from packs.agent_platform.storage import (
    AgentPlatformConflictError,
    AgentPlatformError,
    AgentPlatformNotFoundError,
    actor_identifier,
    json_loads_list,
    json_loads_object,
    parse_iso_timestamp,
    require_client,
    safe_json_value,
    validate_identifier,
    validate_key,
    validate_text,
)
from packs.agent_platform.technicians import (
    TechnicianProfile,
    TechnicianService,
    _availability,
    _expertise,
    _expertise_score,
    _timestamp,
    _working_hours,
)
from packs.agent_platform.vision import (
    AttachmentService,
    _bounded_strings,
    _normalize_analysis,
    _request_analysis,
    _safe_base_url,
)
from tests.support import ensure_test_client, ingest_local
from wait_local_agent.agents import AgentService
from wait_local_agent.config import Settings
from wait_local_agent.rbac import Role
from wait_local_agent.smart_actions import ActionResult, SmartActionService
from wait_local_agent.store import Store

_SAMPLE_TICKETS = Path("examples/sample_tickets/tickets.json")
_PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
    b"\x00\x00\x00\rIDAT\x08\xd7c\xf8\xcf\xc0\xf0\x1f\x00\x05\x00\x01\xff\x89\x99=\x1d"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)
_PNG = base64.b64encode(_PNG_BYTES).decode("ascii")


def _runtime(
    settings: Settings,
    *,
    clients: tuple[str, ...] = ("acme",),
) -> tuple[
    Store,
    SmartActionService,
    AgentService,
    MemoryService,
    SkillService,
    IterationService,
]:
    store = Store(settings.data_path)
    for client_id in clients:
        ensure_test_client(store, client_id)
        ingest_local(store, _SAMPLE_TICKETS, client_id=client_id)
    actions = SmartActionService(store, settings)
    agents = AgentService(store, settings, actions)
    memories = MemoryService(store)
    skills = SkillService(store, actions)
    iterations = IterationService(store, actions, agents, skills, memories)
    return store, actions, agents, memories, skills, iterations


def _create_skill(skills: SkillService, *, client_id: str = "acme") -> SkillRecord:
    return skills.create(
        client_id=client_id,
        name="Validation skill",
        slug="validation-skill",
        description="Exercises bounded validation.",
        instructions="Inspect {{input.ticket_id}} using {{memory.policy}}.",
        allowed_tools=["ticket-triage"],
        input_schema={
            "type": "object",
            "required": ["ticket_id"],
            "additionalProperties": False,
            "properties": {
                "ticket_id": {"type": "string", "minLength": 1, "maxLength": 128},
            },
        },
        resources=[],
        actor="technician",
    )


def _create_agent(
    agents: AgentService,
    *,
    client_id: str | None = "acme",
    enabled: bool = True,
    tools: list[str] | None = None,
):
    selected_tools = tools or ["ticket-triage"]
    return agents.create(
        name="Iteration validation agent",
        description="Exercises bounded iteration controls.",
        enabled=enabled,
        trigger="manual",
        entity_type="ticket",
        filters={},
        enabled_tools=selected_tools,
        steps=[{"tool_id": selected_tools[0], "payload": {}}],
        max_steps=1,
        execution_timeout_seconds=30,
        client_id=client_id,
    )


def test_router_services_reuse_runtime_and_fall_back(settings) -> None:
    store, actions, agents, _, _, _ = _runtime(settings)
    state = SimpleNamespace(
        store=store,
        settings=settings,
        scheduler=SimpleNamespace(
            _smart_action_service=actions,
            _agent_service=agents,
        ),
    )
    request = SimpleNamespace(app=SimpleNamespace(state=state))
    shared = _services(cast(Any, request))
    assert shared.iterations.smart_actions is actions
    assert shared.iterations.agents is agents
    assert _services(cast(Any, request)) is shared

    fallback_state = SimpleNamespace(store=store, settings=settings)
    fallback_request = SimpleNamespace(app=SimpleNamespace(state=fallback_state))
    fallback = _services(cast(Any, fallback_request))
    assert fallback.iterations.smart_actions is not actions
    assert fallback.iterations.agents is not agents


def test_storage_defensive_validation_and_actor_normalization(settings) -> None:
    store = Store(settings.data_path)
    ensure_test_client(store, "acme")
    assert require_client(store, "acme") == "acme"
    with pytest.raises(AgentPlatformNotFoundError):
        require_client(store, "missing")
    with pytest.raises(AgentPlatformError):
        validate_identifier(cast(str, 123), "identifier")
    with pytest.raises(AgentPlatformError):
        validate_key(cast(str, 123))
    with pytest.raises(AgentPlatformError):
        validate_key("bad/key")
    with pytest.raises(AgentPlatformError):
        validate_text(cast(str, 123), "text", maximum=10)
    with pytest.raises(AgentPlatformError):
        validate_text("", "text", minimum=1, maximum=10)
    with pytest.raises(AgentPlatformError):
        safe_json_value(object())
    assert json_loads_object("not-json") == {}
    assert json_loads_list("not-json") == []
    assert actor_identifier(None) == "api"
    assert actor_identifier("   ") == "api"
    assert len(actor_identifier("a" * 200)) == 128
    timestamp = parse_iso_timestamp("2026-08-30T10:00:00", "timestamp")
    assert timestamp is not None
    assert timestamp.endswith("+00:00")


def test_memory_active_restore_scalar_history_and_filters(settings) -> None:
    store, _, _, memories, _, _ = _runtime(settings)
    scalar = memories.put(
        client_id="acme",
        scope_type="client",
        scope_id="ignored",
        key="scalar-value",
        value=["one", "two"],
        summary="Scalar JSON branch",
        provenance="test",
        actor="admin",
    )
    assert scalar.to_dict()["value"] == ["one", "two"]
    pinned = memories.pin(client_id="acme", memory_id=scalar.id, pinned=True, actor="admin")
    assert pinned.pinned is True
    with pytest.raises(AgentPlatformConflictError):
        memories.restore(client_id="acme", memory_id=pinned.id, actor="admin")
    with pytest.raises(AgentPlatformError):
        memories.list(client_id="acme", limit=0)
    with pytest.raises(AgentPlatformError):
        memories.list(client_id="acme", scope_type=cast(Any, "invalid"))
    with pytest.raises(AgentPlatformError):
        memories.resolve_context(client_id="acme", limit=0)

    with store._connect() as connection:  # noqa: SLF001
        connection.execute(
            "update agent_memories set value_json = 'not-json' where id = ?",
            (scalar.id,),
        )
    corrupted = memories.get(client_id="acme", memory_id=scalar.id)
    assert corrupted.value is None


def test_skill_private_validators_cover_supported_schema_subset() -> None:
    assert _slug("VALID-SLUG") == "valid-slug"
    with pytest.raises(AgentPlatformError):
        _slug("bad_slug")
    assert _version(1) == 1
    for invalid_version in (0, True, cast(int, "1")):
        with pytest.raises(AgentPlatformError):
            _version(invalid_version)
    assert _tools(["ticket-triage", "ticket-triage"]) == ["ticket-triage"]
    with pytest.raises(AgentPlatformError):
        _tools(cast(list[str], "not-a-list"))
    with pytest.raises(AgentPlatformError):
        _tools(["tool"] * 17)

    valid_schema = _schema(
        {
            "type": "object",
            "required": ["items"],
            "additionalProperties": False,
            "properties": {
                "items": {
                    "type": "array",
                    "items": {"type": "string"},
                }
            },
        }
    )
    assert valid_schema["type"] == "object"
    invalid_schemas: list[object] = [
        [],
        {"type": "string"},
        {"type": "object", "minimum": 1},
        {"type": "object", "properties": [], "required": []},
        {"type": "object", "properties": {}, "required": "bad"},
        {"type": "object", "properties": {}, "required": ["missing"]},
        {"type": "object", "properties": {"bad": "value"}},
        {"type": "object", "properties": {"bad": {"type": "null"}}},
        {
            "type": "object",
            "properties": {"items": {"type": "array", "items": "bad"}},
        },
    ]
    for invalid_schema in invalid_schemas:
        with pytest.raises(AgentPlatformError):
            _schema(cast(dict[str, object], invalid_schema))


def test_skill_resource_and_sample_validation_branches() -> None:
    with pytest.raises(AgentPlatformError):
        _resources(cast(list[dict[str, object]], "bad"))
    with pytest.raises(AgentPlatformError):
        _resources([{}] * 11)
    invalid_resources: list[list[object]] = [
        ["bad"],
        [{"name": "../bad", "content": "x"}],
        [
            {"name": "same.txt", "content": "x"},
            {"name": "SAME.TXT", "content": "y"},
        ],
        [{"name": "bad.bin", "media_type": "application/octet-stream", "content": "x"}],
        [{"name": "bad.json", "media_type": "application/json", "content": "{"}],
        [{"name": "large.txt", "content": "😀" * 6_000}],
    ]
    for resources in invalid_resources:
        with pytest.raises(AgentPlatformError):
            _resources(cast(list[dict[str, object]], resources))

    schema = {
        "type": "object",
        "required": ["name", "items"],
        "additionalProperties": False,
        "properties": {
            "name": {
                "type": "string",
                "minLength": 2,
                "maxLength": 4,
                "enum": ["good"],
            },
            "items": {
                "type": "array",
                "minItems": 2,
                "maxItems": 3,
                "items": {"type": "integer"},
            },
        },
    }
    errors = _validate_schema(
        schema,
        {"name": "x", "items": [1, "bad", 3, 4], "extra": True},
        path="input",
    )
    assert any("enum" in error for error in errors)
    assert any("at least 2 characters" in error for error in errors)
    assert any("at most 3 items" in error for error in errors)
    assert any("must be integer" in error for error in errors)
    assert any("is not allowed" in error for error in errors)
    assert _validate_schema(schema, [], path="input") == ["input must be object"]
    assert "required" in _validate_schema(schema, {}, path="input")[0]
    rendered = _render(
        "Ticket {{input.ticket.id}} tags {{memory.tags}} missing {{memory.none}}",
        {"ticket": {"id": "TCK-1001"}},
        {"tags": ["mfa", "entra"]},
    )
    assert "TCK-1001" in rendered
    assert '["mfa","entra"]' in rendered
    assert "{{memory.none}}" in rendered


def test_skill_service_defensive_paths(settings, monkeypatch) -> None:
    _, _, _, _, skills, _ = _runtime(settings)
    skill = _create_skill(skills)
    assert skill.to_dict()["revision"]["version"] == 1  # type: ignore[index]
    assert skill.revision.to_dict()["skill_id"] == skill.id
    with pytest.raises(AgentPlatformNotFoundError):
        skills.get(client_id="acme", skill_id="missing")
    with pytest.raises(AgentPlatformNotFoundError):
        skills.get(client_id="acme", skill_id=skill.id, version=99)
    assert skills.archive(client_id="acme", skill_id=skill.id, actor="admin").status == "archived"
    assert skills.archive(client_id="acme", skill_id=skill.id, actor="admin").status == "archived"
    with pytest.raises(AgentPlatformConflictError):
        skills.update(client_id="acme", skill_id=skill.id, actor="admin", name="No")

    active = skills.create(
        client_id="acme",
        name="Missing catalog",
        slug="missing-catalog",
        description="",
        instructions="Inspect {{input.ticket_id}}.",
        allowed_tools=["ticket-triage"],
        input_schema={"type": "object", "properties": {}},
        resources=[],
        actor="admin",
    )
    monkeypatch.setattr(skills.smart_actions, "list", lambda: [])
    failed = skills.test(
        client_id="acme",
        skill_id=active.id,
        sample_input={},
        memory={},
        actor="admin",
    )
    assert failed.status == "failed"
    assert "tool catalog" in failed.error_detail
    assert failed.to_dict()["status"] == "failed"
    with pytest.raises(AgentPlatformError):
        skills.test_runs(client_id="acme", skill_id=active.id, limit=0)


def test_iteration_private_helpers_cover_bounds_and_roles() -> None:
    event = IterationEvent(
        id=1,
        session_id="session",
        ordinal=0,
        event_type="created",
        step_index=None,
        tool_id=None,
        status="ready",
        input={},
        output={},
        approval_id=None,
        actor="tech",
        created_at="now",
    )
    session = IterationSession(
        id="session",
        client_id="acme",
        source_type="agent",
        source_id="agent",
        source_version=1,
        entity_id="TCK-1001",
        instruction="",
        status="awaiting_continue",
        current_step=0,
        steps=[],
        state={},
        approval_id=None,
        created_by="tech",
        created_at="now",
        updated_at="now",
        events=[event],
    )
    assert event.to_dict()["id"] == 1
    assert session.to_dict()["events"][0]["id"] == 1  # type: ignore[index]
    assert _string_list("bad") == []
    assert _string_list(["a", 1]) == ["a"]
    assert _mapping_list("bad") == []
    assert _mapping_list([{"a": 1}, "bad"]) == [{"a": 1}]

    invalid_steps: list[object] = [
        [],
        ["bad"],
        [{"tool_id": "other", "payload": {}}],
        [{"tool_id": "ticket-triage", "payload": []}],
        [{"tool_id": "ticket-triage", "payload": {"_approval_completed": True}}],
    ]
    for steps in invalid_steps:
        with pytest.raises(AgentPlatformError):
            _steps(cast(list[dict[str, object]], steps), ["ticket-triage"])
    assert _step_payload(
        {"payload": {}},
        {"required": ["ticket_id"]},
        "TCK-1001",
    )["ticket_id"] == "TCK-1001"
    assert _step_payload({"payload": "bad"}, {}, "TCK-1001") == {}
    with pytest.raises(PermissionError):
        _require_role(Role.VIEWER, "admin")
    _require_role(Role.TECHNICIAN, "unknown-role")
    large = _bounded_result(ActionResult(status="failed", output={"body": "x" * 70_000}))
    assert large["truncated"] is True


def test_iteration_creation_and_control_defensive_paths(settings, monkeypatch) -> None:
    store, actions, agents, memories, skills, iterations = _runtime(settings)
    agent = _create_agent(agents)
    with pytest.raises(AgentPlatformNotFoundError):
        iterations.create(
            client_id="acme",
            source_type="agent",
            source_id=agent.id,
            entity_id="missing",
            instruction="",
            actor="tech",
        )
    with pytest.raises(AgentPlatformNotFoundError):
        iterations.create(
            client_id="acme",
            source_type="agent",
            source_id="missing-agent",
            entity_id="TCK-1001",
            instruction="",
            actor="tech",
        )
    disabled = _create_agent(agents, enabled=False)
    with pytest.raises(AgentPlatformConflictError):
        iterations.create(
            client_id="acme",
            source_type="agent",
            source_id=disabled.id,
            entity_id="TCK-1001",
            instruction="",
            actor="tech",
        )
    with pytest.raises(AgentPlatformError):
        iterations.create(
            client_id="acme",
            source_type="other",
            source_id="source",
            entity_id="TCK-1001",
            instruction="",
            actor="tech",
        )

    skill = _create_skill(skills)
    with pytest.raises(AgentPlatformError):
        iterations.create(
            client_id="acme",
            source_type="skill",
            source_id=skill.id,
            entity_id="TCK-1001",
            instruction="",
            actor="tech",
        )
    skills.archive(client_id="acme", skill_id=skill.id, actor="admin")
    with pytest.raises(AgentPlatformConflictError):
        iterations.create(
            client_id="acme",
            source_type="skill",
            source_id=skill.id,
            entity_id="TCK-1001",
            instruction="",
            actor="tech",
            steps=[{"tool_id": "ticket-triage", "payload": {}}],
        )

    session = iterations.create(
        client_id="acme",
        source_type="agent",
        source_id=agent.id,
        entity_id="TCK-1001",
        instruction="",
        actor="tech",
    )
    with pytest.raises(AgentPlatformError):
        iterations.modify_step(
            client_id="acme",
            session_id=session.id,
            step_index=2,
            tool_id="ticket-triage",
            payload={},
            actor="tech",
            actor_role=Role.TECHNICIAN,
        )
    with pytest.raises(AgentPlatformError):
        iterations.modify_step(
            client_id="acme",
            session_id=session.id,
            step_index=0,
            tool_id="ticket-summary",
            payload={},
            actor="tech",
            actor_role=Role.TECHNICIAN,
        )

    monkeypatch.setattr(actions, "invoke", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")))
    failed = iterations.continue_once(
        client_id="acme",
        session_id=session.id,
        actor="tech",
        actor_role=Role.TECHNICIAN,
    )
    assert failed.status == "failed"
    with pytest.raises(AgentPlatformConflictError):
        iterations.continue_once(
            client_id="acme",
            session_id=session.id,
            actor="tech",
            actor_role=Role.TECHNICIAN,
        )
    assert iterations.finish(
        client_id="acme",
        session_id=session.id,
        actor="tech",
        reason="already terminal",
    ).status == "failed"
    assert memories.resolve_context(client_id="acme") == []


def test_iteration_rejected_failed_and_pending_control_paths(settings, monkeypatch) -> None:
    store, actions, agents, _, _, iterations = _runtime(settings)
    agent = _create_agent(agents)

    rejected_session = iterations.create(
        client_id="acme",
        source_type="agent",
        source_id=agent.id,
        entity_id="TCK-1001",
        instruction="",
        actor="tech",
    )
    monkeypatch.setattr(actions, "invoke", lambda *args, **kwargs: ActionResult(status="rejected"))
    rejected = iterations.continue_once(
        client_id="acme",
        session_id=rejected_session.id,
        actor="tech",
        actor_role=Role.TECHNICIAN,
    )
    assert rejected.status == "rejected"

    pending_agent = _create_agent(agents, tools=["dispatch-suggestion"])
    pending_session = iterations.create(
        client_id="acme",
        source_type="agent",
        source_id=pending_agent.id,
        entity_id="TCK-1001",
        instruction="",
        actor="requester",
    )
    monkeypatch.undo()
    pending = iterations.continue_once(
        client_id="acme",
        session_id=pending_session.id,
        actor="requester",
        actor_role=Role.TECHNICIAN,
    )
    assert pending.status == "pending_approval"
    with pytest.raises(AgentPlatformConflictError):
        iterations.restart(client_id="acme", session_id=pending.id, actor="tech")
    with pytest.raises(AgentPlatformConflictError):
        iterations.finish(
            client_id="acme",
            session_id=pending.id,
            actor="tech",
            reason="stop",
        )

    monkeypatch.setattr(store, "get_approval_request", lambda _: None)
    missing = iterations.continue_once(
        client_id="acme",
        session_id=pending.id,
        actor="tech",
        actor_role=Role.TECHNICIAN,
    )
    assert missing.status == "failed"


def test_technician_private_validation_and_scoring(settings) -> None:
    store, _, _, _, _, _ = _runtime(settings)
    service = TechnicianService(store)
    with pytest.raises(AgentPlatformError):
        _working_hours({"nonday": []})
    with pytest.raises(AgentPlatformError):
        _working_hours({"monday": "bad"})
    with pytest.raises(AgentPlatformError):
        _working_hours({"monday": ["bad"]})
    with pytest.raises(AgentPlatformError):
        _working_hours({"monday": [{"start": "9:00", "end": "17:00"}]})
    assert _expertise(["MFA", "mfa"]) == ["mfa"]
    with pytest.raises(AgentPlatformError):
        _expertise(cast(list[str], "bad"))
    with pytest.raises(AgentPlatformError):
        _expertise(["x"] * 33)
    assert _timestamp("2026-08-31T10:00:00Z").tzinfo is not None
    assert _timestamp(None).tzinfo is not None
    score, matched = _expertise_score(["mfa", "hardware"], [], "mfa failure", {"mfa", "failure"})
    assert score == 0.5
    assert matched == ["mfa"]
    assert _expertise_score([], [], "", set()) == (0.5, [])

    with pytest.raises(AgentPlatformError):
        service.upsert_profile(
            client_id="acme",
            technician_id="bad-familiarity",
            display_name="Bad",
            timezone="UTC",
            working_hours={},
            expertise=[],
            client_familiarity=6,
            capacity=1,
            enabled=True,
            actor="admin",
        )
    with pytest.raises(AgentPlatformError):
        service.upsert_profile(
            client_id="acme",
            technician_id="bad-capacity",
            display_name="Bad",
            timezone="UTC",
            working_hours={},
            expertise=[],
            client_familiarity=0,
            capacity=0,
            enabled=True,
            actor="admin",
        )
    with pytest.raises(AgentPlatformNotFoundError):
        service.recommend(client_id="acme", ticket_id="missing")
    with pytest.raises(AgentPlatformError):
        service.recommend(client_id="acme", ticket_id="TCK-1001", limit=0)


def test_technician_workload_and_availability_defensive_paths(settings) -> None:
    store, _, _, _, _, _ = _runtime(settings)
    service = TechnicianService(store)
    profile = service.upsert_profile(
        client_id="acme",
        technician_id="tech",
        display_name="Tech",
        timezone="UTC",
        working_hours={},
        expertise=[],
        client_familiarity=0,
        capacity=10,
        enabled=True,
        actor="admin",
    )
    for field in ("open_tickets", "active_incidents", "scheduled_changes"):
        values = {"open_tickets": 0, "active_incidents": 0, "scheduled_changes": 0}
        values[field] = -1
        with pytest.raises(AgentPlatformError):
            service.record_workload(
                client_id="acme",
                technician_id="tech",
                unavailable_until=None,
                source="test",
                observed_at=None,
                actor="admin",
                **values,
            )
    workload = service.record_workload(
        client_id="acme",
        technician_id="tech",
        open_tickets=1,
        active_incidents=0,
        scheduled_changes=0,
        unavailable_until=None,
        source="test",
        observed_at=None,
        actor="admin",
    )
    assert workload.to_dict()["open_tickets"] == 1
    assert profile.to_dict()["technician_id"] == "tech"
    with pytest.raises(AgentPlatformNotFoundError):
        service._get_workload(999, "acme")  # noqa: SLF001

    no_window = replace(
        profile,
        working_hours={"monday": ["bad"]},
        workload=workload,
    )
    available, reason = _availability(no_window, workload, _timestamp("2026-08-31T12:00:00Z"))
    assert available == 0.0
    assert "outside working hours" in reason


def test_attachment_model_configuration_matrix(settings) -> None:
    store, _, _, memories, _, _ = _runtime(settings)
    variants = [
        (
            replace(
                settings,
                allow_llm_inference=True,
                local_model_provider="openai-compatible",
                local_model_base_url="",
                local_model_name="",
            ),
            "blocked",
        ),
        (
            replace(
                settings,
                allow_llm_inference=True,
                local_model_provider="unsupported",
                offline_mode=True,
            ),
            "blocked",
        ),
        (
            replace(
                settings,
                allow_llm_inference=True,
                local_model_provider="unsupported",
                offline_mode=False,
                allow_cloud_fallback=False,
            ),
            "blocked",
        ),
        (
            replace(
                settings,
                allow_llm_inference=True,
                local_model_provider="unsupported",
                offline_mode=False,
                allow_cloud_fallback=True,
                remote_model_provider="anthropic",
            ),
            "blocked",
        ),
        (
            replace(
                settings,
                allow_llm_inference=True,
                local_model_provider="unsupported",
                offline_mode=False,
                allow_cloud_fallback=True,
                remote_model_provider="openai-compatible",
                remote_model_base_url="",
                remote_model_name="",
                remote_model_api_key="",
            ),
            "blocked",
        ),
        (
            replace(
                settings,
                allow_llm_inference=True,
                local_model_provider="unsupported",
                offline_mode=False,
                allow_cloud_fallback=True,
                remote_model_provider="openai-compatible",
                remote_model_base_url="https://models.example.test/v1",
                remote_model_name="vision",
                remote_model_api_key="token",
            ),
            "ready",
        ),
    ]
    for configured, expected in variants:
        service = AttachmentService(store, configured, memories)
        assert service._model_configuration()["status"] == expected  # noqa: SLF001


def test_attachment_upload_and_private_storage_defensive_paths(settings, monkeypatch, tmp_path) -> None:
    store, _, _, memories, _, _ = _runtime(settings)
    service = AttachmentService(store, settings, memories)
    with pytest.raises(AgentPlatformNotFoundError):
        service.upload(
            client_id="acme",
            ticket_id="missing",
            filename="x.png",
            media_type="image/png",
            content_base64=_PNG,
            actor="tech",
        )
    with pytest.raises(AgentPlatformError):
        service.upload(
            client_id="acme",
            ticket_id="TCK-1001",
            filename="x.gif",
            media_type="image/gif",
            content_base64=_PNG,
            actor="tech",
        )
    with pytest.raises(AgentPlatformError):
        service.upload(
            client_id="acme",
            ticket_id="TCK-1001",
            filename="x.png",
            media_type="image/png",
            content_base64="not-base64",
            actor="tech",
        )
    with pytest.raises(AgentPlatformError):
        service.upload(
            client_id="acme",
            ticket_id="TCK-1001",
            filename="x.png",
            media_type="image/png",
            content_base64="",
            actor="tech",
        )

    client_directory = service.root / hashlib.sha256(b"acme").hexdigest()[:16]
    outside = tmp_path / "outside"
    outside.mkdir()
    client_directory.symlink_to(outside, target_is_directory=True)
    with pytest.raises(AgentPlatformError, match="directory is invalid"):
        service.upload(
            client_id="acme",
            ticket_id="TCK-1001",
            filename="x.png",
            media_type="image/png",
            content_base64=_PNG,
            actor="tech",
        )
    client_directory.unlink()

    attachment = service.upload(
        client_id="acme",
        ticket_id="TCK-1001",
        filename="x.png",
        media_type="image/png",
        content_base64=_PNG,
        actor="tech",
    )
    monkeypatch.setattr(
        "packs.agent_platform.vision._request_analysis",
        lambda **_: (_ for _ in ()).throw(RuntimeError("private failure")),
    )
    enabled = AttachmentService(
        store,
        replace(
            settings,
            allow_llm_inference=True,
            local_model_provider="openai-compatible",
            local_model_base_url="http://127.0.0.1:11434/v1",
            local_model_name="vision",
        ),
        memories,
    )
    analysis = enabled.analyze(
        client_id="acme",
        ticket_id="TCK-1001",
        attachment_id=attachment.id,
        prompt="inspect",
        actor="tech",
    )
    assert analysis.status == "failed"
    assert analysis.error_detail == "multimodal provider request failed"


def test_attachment_verified_file_failure_paths(settings, monkeypatch, tmp_path) -> None:
    store, _, _, memories, _, _ = _runtime(settings)
    service = AttachmentService(store, settings, memories)
    attachment = service.upload(
        client_id="acme",
        ticket_id="TCK-1001",
        filename="x.png",
        media_type="image/png",
        content_base64=_PNG,
        actor="tech",
    )
    with store._connect() as connection:  # noqa: SLF001
        original_path = Path(
            connection.execute(
                "select storage_path from ticket_attachments where id = ?",
                (attachment.id,),
            ).fetchone()[0]
        )
        connection.execute(
            "update ticket_attachments set storage_path = ? where id = ?",
            (str(tmp_path / "missing.png"), attachment.id),
        )
    with pytest.raises(AgentPlatformError, match="unavailable"):
        service._read_verified_content(attachment)  # noqa: SLF001

    outside = tmp_path / "outside.png"
    outside.write_bytes(_PNG_BYTES)
    with store._connect() as connection:  # noqa: SLF001
        connection.execute(
            "update ticket_attachments set storage_path = ? where id = ?",
            (str(outside), attachment.id),
        )
    with pytest.raises(AgentPlatformError, match="invalid"):
        service._read_verified_content(attachment)  # noqa: SLF001

    with store._connect() as connection:  # noqa: SLF001
        connection.execute(
            "update ticket_attachments set storage_path = ? where id = ?",
            (str(original_path), attachment.id),
        )
    monkeypatch.setattr(Path, "read_bytes", lambda _: (_ for _ in ()).throw(OSError("read")))
    with pytest.raises(AgentPlatformError, match="could not be read"):
        service._read_verified_content(attachment)  # noqa: SLF001


def test_multimodal_http_error_contracts(monkeypatch) -> None:
    original_client = httpx.Client

    def run(response: httpx.Response) -> None:
        def handler(_: httpx.Request) -> httpx.Response:
            return response

        def factory(*args, **kwargs):
            return original_client(
                timeout=kwargs.get("timeout", 1.0),
                transport=httpx.MockTransport(handler),
            )

        monkeypatch.setattr("packs.agent_platform.vision.build_pinned_client", factory)
        _request_analysis(
            base_url="https://models.example.test/v1",
            model="vision",
            api_key="token",
            timeout=1.0,
            media_type="image/png",
            content=_PNG_BYTES,
            prompt="inspect",
        )

    error_cases = [
        (httpx.Response(400, json={}), "HTTP 400"),
        (httpx.Response(200, content=b"x" * 64_001), "bounded limit"),
        (httpx.Response(200, content=b"not-json"), "malformed JSON"),
        (httpx.Response(200, json=[]), "malformed response"),
        (httpx.Response(200, json={"choices": []}), "no completion"),
        (httpx.Response(200, json={"choices": [{}]}), "malformed message"),
        (
            httpx.Response(200, json={"choices": [{"message": {"content": ""}}]}),
            "empty content",
        ),
        (
            httpx.Response(200, json={"choices": [{"message": {"content": "x" * 20_001}}]}),
            "bounded limit",
        ),
        (
            httpx.Response(200, json={"choices": [{"message": {"content": "not-json"}}]}),
            "valid JSON",
        ),
        (
            httpx.Response(200, json={"choices": [{"message": {"content": "[]"}}]}),
            "must be an object",
        ),
    ]
    for response, message in error_cases:
        monkeypatch.undo()
        with pytest.raises(AgentPlatformError, match=message):
            run(response)

    monkeypatch.undo()

    class FailingClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args) -> None:
            return None

        def post(self, *args, **kwargs):
            raise httpx.ConnectError("offline")

    monkeypatch.setattr("packs.agent_platform.vision.build_pinned_client", FailingClient)
    with pytest.raises(AgentPlatformError, match="before receiving"):
        _request_analysis(
            base_url="https://models.example.test/v1",
            model="vision",
            api_key="",
            timeout=1.0,
            media_type="image/png",
            content=_PNG_BYTES,
            prompt="inspect",
        )


def test_multimodal_normalization_and_base_url_edge_cases() -> None:
    assert _bounded_strings(["a", 1, None], limit=2, item_limit=10) == ["a", "1"]
    assert _bounded_strings("bad", limit=2, item_limit=10) == []
    assert _normalize_analysis(
        {
            "summary": "Summary",
            "visible_text": "bad",
            "indicators": [1],
            "confidence": "bad",
            "limitations": [],
        }
    )["confidence"] == 0.0
    with pytest.raises(AgentPlatformError):
        _safe_base_url("https://models.example.test/v1?token=bad")
    with pytest.raises(AgentPlatformError):
        _safe_base_url("https://models.example.test/v1#fragment")


def test_memory_key_filter_scope_helper_and_context_limit(settings) -> None:
    _, _, _, memories, _, _ = _runtime(settings)
    first = memories.put(
        client_id="acme",
        scope_type="client",
        scope_id="ignored",
        key="one",
        value=1,
        summary="",
        provenance="test",
        actor="admin",
    )
    memories.put(
        client_id="acme",
        scope_type="ticket",
        scope_id="TCK-1001",
        key="two",
        value=2,
        summary="",
        provenance="test",
        actor="admin",
    )
    assert memories.list(client_id="acme", key="one")[0].id == first.id
    assert len(
        memories.resolve_context(
            client_id="acme",
            ticket_id="TCK-1001",
            limit=1,
        )
    ) == 1
    with pytest.raises(AgentPlatformError):
        _scope("acme", "invalid", "value")


def test_iteration_corrupt_state_and_approval_recovery_paths(settings, monkeypatch) -> None:
    store, actions, agents, _, _, iterations = _runtime(settings)
    agent = _create_agent(agents)

    completed_defensively = iterations.create(
        client_id="acme",
        source_type="agent",
        source_id=agent.id,
        entity_id="TCK-1001",
        instruction="",
        actor="tech",
    )
    with store._connect() as connection:  # noqa: SLF001
        connection.execute(
            "update agent_iteration_sessions set current_step = 1 where id = ?",
            (completed_defensively.id,),
        )
    completed = iterations.continue_once(
        client_id="acme",
        session_id=completed_defensively.id,
        actor="tech",
        actor_role=Role.TECHNICIAN,
    )
    assert completed.status == "completed"

    mismatched = iterations.create(
        client_id="acme",
        source_type="agent",
        source_id=agent.id,
        entity_id="TCK-1001",
        instruction="",
        actor="tech",
    )
    with store._connect() as connection:  # noqa: SLF001
        connection.execute(
            "update agent_iteration_sessions set state_json = ? where id = ?",
            (json.dumps({"allowed_tools": [], "results": []}), mismatched.id),
        )
    with pytest.raises(AgentPlatformConflictError, match="outside the source allowlist"):
        iterations.continue_once(
            client_id="acme",
            session_id=mismatched.id,
            actor="tech",
            actor_role=Role.TECHNICIAN,
        )

    corrupt_pending = iterations.create(
        client_id="acme",
        source_type="agent",
        source_id=agent.id,
        entity_id="TCK-1001",
        instruction="",
        actor="tech",
    )
    with store._connect() as connection:  # noqa: SLF001
        connection.execute(
            "update agent_iteration_sessions set status = 'pending_approval', approval_id = null where id = ?",
            (corrupt_pending.id,),
        )
    with pytest.raises(AgentPlatformConflictError, match="no approval reference"):
        iterations.continue_once(
            client_id="acme",
            session_id=corrupt_pending.id,
            actor="tech",
            actor_role=Role.TECHNICIAN,
        )

    pending_agent = _create_agent(agents, tools=["dispatch-suggestion"])
    pending_session = iterations.create(
        client_id="acme",
        source_type="agent",
        source_id=pending_agent.id,
        entity_id="TCK-1001",
        instruction="",
        actor="requester",
    )
    pending = iterations.continue_once(
        client_id="acme",
        session_id=pending_session.id,
        actor="requester",
        actor_role=Role.TECHNICIAN,
    )
    with pytest.raises(AgentPlatformConflictError):
        iterations.modify_step(
            client_id="acme",
            session_id=pending.id,
            step_index=0,
            tool_id="dispatch-suggestion",
            payload={},
            actor="tech",
            actor_role=Role.TECHNICIAN,
        )

    approval = store.get_approval_request(pending.approval_id or 0)
    assert approval is not None
    approved = replace(approval, status="approved", approver_id=None)
    monkeypatch.setattr(store, "get_approval_request", lambda _: approved)
    monkeypatch.setattr(store, "list_smart_action_runs", lambda **_: [])
    no_execution = iterations.continue_once(
        client_id="acme",
        session_id=pending.id,
        actor="tech",
        actor_role=Role.TECHNICIAN,
    )
    assert no_execution.status == "failed"


def test_iteration_pending_run_waits_or_completes_with_approver(settings, monkeypatch) -> None:
    store, actions, agents, _, _, iterations = _runtime(settings)
    pending_agent = _create_agent(agents, tools=["dispatch-suggestion"])
    session = iterations.create(
        client_id="acme",
        source_type="agent",
        source_id=pending_agent.id,
        entity_id="TCK-1001",
        instruction="",
        actor="requester",
    )
    pending = iterations.continue_once(
        client_id="acme",
        session_id=session.id,
        actor="requester",
        actor_role=Role.TECHNICIAN,
    )
    approval = store.get_approval_request(pending.approval_id or 0)
    assert approval is not None
    run = next(
        item
        for item in store.list_smart_action_runs(client_id="acme")
        if item.approval_id == pending.approval_id
    )

    monkeypatch.setattr(
        store,
        "get_approval_request",
        lambda _: replace(approval, status="approved", approver_id=None),
    )
    monkeypatch.setattr(store, "list_smart_action_runs", lambda **_: [run])
    waiting = iterations.continue_once(
        client_id="acme",
        session_id=pending.id,
        actor="tech",
        actor_role=Role.TECHNICIAN,
    )
    assert waiting.status == "pending_approval"

    completed_run = SimpleNamespace(
        approval_id=pending.approval_id,
        status="success",
        output_json='{"approved":true}',
        evidence_json="[]",
    )
    calls = iter([[run], [completed_run]])
    monkeypatch.setattr(
        store,
        "get_approval_request",
        lambda _: replace(approval, status="approved", approver_id="approver"),
    )
    monkeypatch.setattr(store, "list_smart_action_runs", lambda **_: next(calls))
    monkeypatch.setattr(actions, "complete_approval", lambda *args, **kwargs: None)
    completed = iterations.continue_once(
        client_id="acme",
        session_id=pending.id,
        actor="tech",
        actor_role=Role.TECHNICIAN,
    )
    assert completed.status == "completed"


def test_attachment_oversize_list_missing_and_http_retry_paths(settings, monkeypatch) -> None:
    store, _, _, memories, _, _ = _runtime(settings)
    service = AttachmentService(store, settings, memories)
    with pytest.raises(AgentPlatformError, match="base64 content"):
        service.upload(
            client_id="acme",
            ticket_id="TCK-1001",
            filename="x.png",
            media_type="image/png",
            content_base64="a" * 5_600_000,
            actor="tech",
        )
    with pytest.raises(AgentPlatformNotFoundError):
        service.list(client_id="acme", ticket_id="missing")

    attempts = 0
    original_client = httpx.Client

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(503, json={})
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"summary":"ok","visible_text":[],"indicators":[],'
                                '"confidence":0.5,"limitations":[]}'
                            )
                        }
                    }
                ]
            },
        )

    def factory(*args, **kwargs):
        return original_client(
            timeout=kwargs.get("timeout", 1.0),
            transport=httpx.MockTransport(handler),
        )

    monkeypatch.setattr("packs.agent_platform.vision.build_pinned_client", factory)
    result = _request_analysis(
        base_url="https://models.example.test/v1",
        model="vision",
        api_key="",
        timeout=1.0,
        media_type="image/png",
        content=_PNG_BYTES,
        prompt="inspect",
    )
    assert result["summary"] == "ok"
    assert attempts == 2


def test_multimodal_generic_http_error(monkeypatch) -> None:
    class GenericFailureClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args) -> None:
            return None

        def post(self, *args, **kwargs):
            raise httpx.ProtocolError("broken")

    monkeypatch.setattr("packs.agent_platform.vision.build_pinned_client", GenericFailureClient)
    with pytest.raises(AgentPlatformError, match="provider request failed$"):
        _request_analysis(
            base_url="https://models.example.test/v1",
            model="vision",
            api_key="",
            timeout=1.0,
            media_type="image/png",
            content=_PNG_BYTES,
            prompt="inspect",
        )
