from __future__ import annotations

import base64
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from packs.agent_platform.iterations import IterationService
from packs.agent_platform.memory import MemoryService
from packs.agent_platform.skills import SkillRecord, SkillService
from packs.agent_platform.storage import (
    AgentPlatformConflictError,
    AgentPlatformError,
    AgentPlatformNotFoundError,
    digest_json,
    json_loads_list,
    json_loads_object,
    parse_iso_timestamp,
    safe_json_value,
    validate_identifier,
    validate_text,
)
from packs.agent_platform.technicians import TechnicianService
from packs.agent_platform.vision import (
    AttachmentService,
    _normalize_analysis,
    _request_analysis,
    _safe_base_url,
)
from tests.support import ensure_test_client, ingest_local
from wait_local_agent.agents import AgentService
from wait_local_agent.config import Settings
from wait_local_agent.rbac import Role
from wait_local_agent.smart_actions import SmartActionService
from wait_local_agent.store import Store

_SAMPLE_TICKETS = Path("examples/sample_tickets/tickets.json")
_ONE_PIXEL_PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
    b"\x00\x00\x00\rIDAT\x08\xd7c\xf8\xcf\xc0\xf0\x1f\x00\x05\x00\x01\xff\x89\x99=\x1d"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)
_ONE_PIXEL_PNG = base64.b64encode(_ONE_PIXEL_PNG_BYTES).decode("ascii")


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
    for index, client_id in enumerate(clients):
        ensure_test_client(store, client_id)
        if index == 0:
            ingest_local(store, _SAMPLE_TICKETS, client_id=client_id)
    actions = SmartActionService(store, settings)
    agents = AgentService(store, settings, actions)
    memories = MemoryService(store)
    skills = SkillService(store, actions)
    iterations = IterationService(store, actions, agents, skills, memories)
    return store, actions, agents, memories, skills, iterations


def _skill(
    skills: SkillService,
    *,
    client_id: str = "acme",
    instructions: str | None = None,
) -> SkillRecord:
    return skills.create(
        client_id=client_id,
        name="Reusable triage",
        slug="reusable-triage",
        description="A bounded read-only triage procedure.",
        instructions=instructions or "Triage {{input.ticket_id}} for {{memory.customer_tier}}.",
        allowed_tools=["ticket-triage"],
        input_schema={
            "type": "object",
            "required": ["ticket_id"],
            "additionalProperties": False,
            "properties": {
                "ticket_id": {"type": "string", "minLength": 1, "maxLength": 128},
            },
        },
        resources=[
            {
                "name": "procedure.json",
                "media_type": "application/json",
                "content": '{"order":["inspect","triage"]}',
            }
        ],
        actor="technician",
    )


def test_storage_validation_helpers_cover_bounded_inputs() -> None:
    assert validate_identifier("client-1", "client") == "client-1"
    assert validate_text("  value  ", "value", maximum=20) == "value"
    assert parse_iso_timestamp("2026-08-30T01:00:00Z", "timestamp") == (
        "2026-08-30T01:00:00+00:00"
    )
    assert parse_iso_timestamp("", "timestamp") is None
    assert safe_json_value({"ok": [1, True]}) == {"ok": [1, True]}
    assert len(digest_json({"ok": True})) == 64
    assert json_loads_object('{"a":1}') == {"a": 1}
    assert json_loads_object("[]") == {}
    assert json_loads_list("[1,2]") == [1, 2]
    assert json_loads_list("{}") == []

    with pytest.raises(AgentPlatformError):
        validate_identifier("../unsafe", "client")
    with pytest.raises(AgentPlatformError):
        validate_text("\x00", "value", maximum=20)
    with pytest.raises(AgentPlatformError):
        parse_iso_timestamp("not-a-date", "timestamp")
    with pytest.raises(AgentPlatformError):
        safe_json_value({"large": "x" * 100}, max_bytes=10)


def test_memory_lifecycle_filters_expiry_and_specificity(settings) -> None:
    store, _, _, memories, _, _ = _runtime(settings, clients=("acme", "beta"))
    client_memory = memories.put(
        client_id="acme",
        scope_type="client",
        scope_id="ignored",
        key="support-language",
        value="English",
        summary="Client default",
        provenance="onboarding",
        actor="admin",
    )
    memories.put(
        client_id="acme",
        scope_type="agent",
        scope_id="agent-a",
        key="support-language",
        value="French",
        summary="Agent override",
        provenance="approved workflow",
        actor="admin",
    )
    ticket_memory = memories.put(
        client_id="acme",
        scope_type="ticket",
        scope_id="TCK-1001",
        key="support-language",
        value="Spanish",
        summary="Ticket override",
        provenance="technician note",
        actor="tech",
        expires_at=(datetime.now(UTC) + timedelta(hours=1)).isoformat(),
    )
    expired = memories.put(
        client_id="acme",
        scope_type="ticket",
        scope_id="TCK-1001",
        key="temporary-code",
        value={"code": "redacted"},
        summary="Expired",
        provenance="temporary",
        actor="tech",
        expires_at=(datetime.now(UTC) - timedelta(hours=1)).isoformat(),
    )

    context = memories.resolve_context(
        client_id="acme", agent_id="agent-a", ticket_id="TCK-1001"
    )
    assert next(item for item in context if item["key"] == "support-language")["value"] == "Spanish"
    assert all(item["key"] != "temporary-code" for item in context)
    assert memories.list(client_id="acme", scope_type="ticket", scope_id="TCK-1001") == [
        ticket_memory
    ]
    history = memories.list(client_id="acme", include_history=True)
    assert expired.id in {item.id for item in history}

    pinned = memories.pin(client_id="acme", memory_id=client_memory.id, pinned=True, actor="admin")
    assert pinned.pinned is True
    deleted = memories.delete(client_id="acme", memory_id=client_memory.id, actor="admin")
    assert deleted.status == "deleted"
    with pytest.raises(AgentPlatformNotFoundError):
        memories.get(client_id="acme", memory_id=client_memory.id)
    restored = memories.restore(client_id="acme", memory_id=client_memory.id, actor="admin")
    assert restored.status == "active"
    assert restored.version == 2
    with pytest.raises(AgentPlatformConflictError):
        memories.restore(client_id="acme", memory_id=restored.id, actor="admin")
    assert memories.list(client_id="beta") == []
    assert store.list_audit_events(client_id="acme")


def test_memory_rejects_invalid_scope_limit_and_foreign_records(settings) -> None:
    _, _, _, memories, _, _ = _runtime(settings, clients=("acme", "beta"))
    record = memories.put(
        client_id="acme",
        scope_type="client",
        scope_id="acme",
        key="policy",
        value={"mode": "read"},
        summary="",
        provenance="admin",
        actor="admin",
    )
    with pytest.raises(AgentPlatformError):
        memories.put(
            client_id="acme",
            scope_type="ticket",
            scope_id="bad id",
            key="policy",
            value={},
            summary="",
            provenance="admin",
            actor="admin",
        )
    with pytest.raises(AgentPlatformError):
        memories.list(client_id="acme", limit=0)
    with pytest.raises(AgentPlatformError):
        memories.resolve_context(client_id="acme", limit=999)
    with pytest.raises(AgentPlatformNotFoundError):
        memories.get(client_id="beta", memory_id=record.id, include_history=True)


def test_skill_lifecycle_validation_history_and_archive(settings) -> None:
    store, _, _, _, skills, _ = _runtime(settings)
    skill = _skill(skills)
    assert skill.current_version == 1
    assert skills.list(client_id="acme") == [skill]
    assert skills.get(client_id="acme", skill_id=skill.id, version=1).revision.digest

    passed = skills.test(
        client_id="acme",
        skill_id=skill.id,
        sample_input={"ticket_id": "TCK-1001"},
        memory={"customer_tier": "priority"},
        actor="tech",
    )
    assert passed.status == "passed"
    assert passed.output["side_effects"] is False
    assert passed.output["resource_manifest"][0]["name"] == "procedure.json"  # type: ignore[index]

    failed = skills.test(
        client_id="acme",
        skill_id=skill.id,
        sample_input={},
        memory={},
        actor="tech",
    )
    assert failed.status == "failed"
    assert "input.ticket_id is required" in failed.error_detail
    assert "unresolved template values" in failed.error_detail
    assert [run.id for run in skills.test_runs(client_id="acme", skill_id=skill.id)] == [
        failed.id,
        passed.id,
    ]

    updated = skills.update(
        client_id="acme",
        skill_id=skill.id,
        actor="tech",
        name="Reusable triage v2",
        description="Updated",
        instructions="Triage {{input.ticket_id}}.",
        resources=[],
    )
    assert updated.current_version == 2
    assert updated.name == "Reusable triage v2"
    assert [revision.version for revision in skills.revisions(client_id="acme", skill_id=skill.id)] == [
        2,
        1,
    ]
    archived = skills.archive(client_id="acme", skill_id=skill.id, actor="admin")
    assert archived.status == "archived"
    assert skills.list(client_id="acme") == []
    assert skills.list(client_id="acme", include_archived=True)[0].id == skill.id
    assert skills.archive(client_id="acme", skill_id=skill.id, actor="admin").status == "archived"
    with pytest.raises(AgentPlatformConflictError):
        skills.update(client_id="acme", skill_id=skill.id, actor="tech", description="blocked")
    assert store.list_smart_action_runs(client_id="acme") == []


def test_skill_rejects_unknown_tools_bad_schemas_resources_and_duplicate_slug(settings) -> None:
    _, _, _, _, skills, _ = _runtime(settings)
    skill = _skill(skills)
    with pytest.raises(AgentPlatformConflictError):
        _skill(skills)
    with pytest.raises(AgentPlatformError, match="unknown tool"):
        skills.create(
            client_id="acme",
            name="Unknown tool",
            slug="unknown-tool",
            description="",
            instructions="Run safely.",
            allowed_tools=["not-a-real-tool"],
            input_schema={"type": "object"},
            resources=[],
            actor="tech",
        )
    with pytest.raises(AgentPlatformError, match="root type"):
        skills.update(
            client_id="acme",
            skill_id=skill.id,
            actor="tech",
            input_schema={"type": "string"},
        )
    with pytest.raises(AgentPlatformError, match="invalid JSON"):
        skills.update(
            client_id="acme",
            skill_id=skill.id,
            actor="tech",
            resources=[
                {"name": "bad.json", "media_type": "application/json", "content": "{"}
            ],
        )
    with pytest.raises(AgentPlatformError, match="plain filenames"):
        skills.update(
            client_id="acme",
            skill_id=skill.id,
            actor="tech",
            resources=[
                {"name": "../bad.txt", "media_type": "text/plain", "content": "bad"}
            ],
        )
    with pytest.raises(AgentPlatformNotFoundError):
        skills.get(client_id="acme", skill_id=skill.id, version=99)


def test_iteration_controls_capture_memory_and_one_step_semantics(settings) -> None:
    store, actions, agents, memories, skills, iterations = _runtime(settings)
    memories.put(
        client_id="acme",
        scope_type="ticket",
        scope_id="TCK-1001",
        key="change-window",
        value={"day": "Sunday"},
        summary="Ticket-specific window",
        provenance="approved change",
        actor="admin",
    )
    definition = agents.create(
        name="Two-step review",
        description="Two deterministic reads.",
        enabled=True,
        trigger="manual",
        entity_type="ticket",
        filters={},
        enabled_tools=["ticket-triage", "ticket-summary"],
        steps=[
            {"tool_id": "ticket-triage", "payload": {}},
            {"tool_id": "ticket-summary", "payload": {}},
        ],
        max_steps=2,
        execution_timeout_seconds=30,
        client_id="acme",
    )
    session = iterations.create(
        client_id="acme",
        source_type="agent",
        source_id=definition.id,
        entity_id="TCK-1001",
        instruction="Review each step.",
        actor="tech",
    )
    assert session.state["memory_context"][0]["key"] == "change-window"  # type: ignore[index]
    first = iterations.continue_once(
        client_id="acme",
        session_id=session.id,
        actor="tech",
        actor_role=Role.TECHNICIAN,
    )
    assert first.status == "awaiting_continue"
    assert first.current_step == 1
    assert len(first.state["results"]) == 1  # type: ignore[arg-type]

    modified = iterations.modify_step(
        client_id="acme",
        session_id=session.id,
        step_index=1,
        tool_id="ticket-triage",
        payload={},
        actor="tech",
        actor_role=Role.TECHNICIAN,
    )
    assert modified.steps[1]["tool_id"] == "ticket-triage"
    completed = iterations.continue_once(
        client_id="acme",
        session_id=session.id,
        actor="tech",
        actor_role=Role.TECHNICIAN,
    )
    assert completed.status == "completed"
    assert completed.current_step == 2
    assert len(store.list_smart_action_runs(client_id="acme")) == 2

    restarted = iterations.restart(client_id="acme", session_id=session.id, actor="tech")
    assert restarted.status == "awaiting_continue"
    assert restarted.current_step == 0
    assert restarted.state["restart_count"] == 1
    finished = iterations.finish(
        client_id="acme",
        session_id=session.id,
        actor="tech",
        reason="Enough evidence was collected.",
    )
    assert finished.status == "completed"
    assert any(event.event_type == "session.finished" for event in finished.events)
    assert iterations.list(client_id="acme", status="completed")[0].id == session.id


def test_skill_iteration_and_control_validation(settings) -> None:
    _, _, _, _, skills, iterations = _runtime(settings)
    skill = _skill(skills, instructions="Triage {{input.ticket_id}}.")
    session = iterations.create(
        client_id="acme",
        source_type="skill",
        source_id=skill.id,
        source_version=1,
        entity_id="TCK-1001",
        instruction="Validate the configured step.",
        steps=[{"tool_id": "ticket-triage", "payload": {}}],
        actor="tech",
    )
    assert iterations.get(client_id="acme", session_id=session.id).source_version == 1
    with pytest.raises(AgentPlatformError):
        iterations.modify_step(
            client_id="acme",
            session_id=session.id,
            step_index=0,
            tool_id="ticket-triage",
            payload={"_approval_completed": True},
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
    with pytest.raises(AgentPlatformError):
        iterations.create(
            client_id="acme",
            source_type="skill",
            source_id=skill.id,
            entity_id="TCK-1001",
            instruction="",
            steps=None,
            actor="tech",
        )
    with pytest.raises(AgentPlatformError):
        iterations.create(
            client_id="acme",
            source_type="unsupported",
            source_id=skill.id,
            entity_id="TCK-1001",
            instruction="",
            steps=[],
            actor="tech",
        )
    with pytest.raises(AgentPlatformNotFoundError):
        iterations.get(client_id="acme", session_id="missing")


def test_iteration_approval_can_complete_or_reject(settings) -> None:
    store, actions, agents, _, skills, iterations = _runtime(settings)
    definition = agents.create(
        name="Approval step",
        description="A bounded approval-required recommendation.",
        enabled=True,
        trigger="manual",
        entity_type="ticket",
        filters={},
        enabled_tools=["dispatch-suggestion"],
        steps=[
            {
                "tool_id": "dispatch-suggestion",
                "payload": {"technicians": [{"id": "tech-a", "workload": 1}]},
            }
        ],
        max_steps=1,
        execution_timeout_seconds=30,
        client_id="acme",
    )
    pending = iterations.continue_once(
        client_id="acme",
        session_id=iterations.create(
            client_id="acme",
            source_type="agent",
            source_id=definition.id,
            entity_id="TCK-1001",
            instruction="Review dispatch.",
            actor="requester",
        ).id,
        actor="requester",
        actor_role=Role.TECHNICIAN,
    )
    assert pending.status == "pending_approval"
    assert pending.approval_id is not None
    unchanged = iterations.continue_once(
        client_id="acme",
        session_id=pending.id,
        actor="reviewer",
        actor_role=Role.TECHNICIAN,
    )
    assert unchanged.status == "pending_approval"
    actions.update_approval(
        pending.approval_id,
        "approved",
        approver="reviewer",
        approver_role=Role.TECHNICIAN,
    )
    completed = iterations.continue_once(
        client_id="acme",
        session_id=pending.id,
        actor="reviewer",
        actor_role=Role.TECHNICIAN,
    )
    assert completed.status == "completed"

    rejected_pending = iterations.continue_once(
        client_id="acme",
        session_id=iterations.create(
            client_id="acme",
            source_type="agent",
            source_id=definition.id,
            entity_id="TCK-1002",
            instruction="Review dispatch.",
            actor="requester-2",
        ).id,
        actor="requester-2",
        actor_role=Role.TECHNICIAN,
    )
    assert rejected_pending.approval_id is not None
    actions.update_approval(
        rejected_pending.approval_id,
        "rejected",
        approver="reviewer",
        approver_role=Role.TECHNICIAN,
    )
    rejected = iterations.continue_once(
        client_id="acme",
        session_id=rejected_pending.id,
        actor="reviewer",
        actor_role=Role.TECHNICIAN,
    )
    assert rejected.status == "rejected"
    assert store.get_approval_request(rejected_pending.approval_id).status == "rejected"  # type: ignore[union-attr]


def test_technician_profiles_workloads_and_availability(settings) -> None:
    _, _, _, _, _, _ = _runtime(settings)
    store = Store(settings.data_path)
    technicians = TechnicianService(store)
    technicians.upsert_profile(
        client_id="acme",
        technician_id="day-tech",
        display_name="Day Tech",
        timezone="UTC",
        working_hours={"monday": [{"start": "09:00", "end": "17:00"}]},
        expertise=["MFA", "Entra"],
        client_familiarity=4,
        capacity=20,
        enabled=True,
        actor="admin",
    )
    technicians.upsert_profile(
        client_id="acme",
        technician_id="disabled-tech",
        display_name="Disabled Tech",
        timezone="UTC",
        working_hours={},
        expertise=["mfa"],
        client_familiarity=5,
        capacity=20,
        enabled=False,
        actor="admin",
    )
    workload = technicians.record_workload(
        client_id="acme",
        technician_id="day-tech",
        open_tickets=1,
        active_incidents=1,
        scheduled_changes=0,
        unavailable_until="2026-08-31T10:00:00Z",
        source="PSA",
        observed_at="2026-08-31T08:00:00Z",
        actor="admin",
    )
    assert workload.source == "PSA"
    assert len(technicians.list(client_id="acme")) == 1
    assert len(technicians.list(client_id="acme", include_disabled=True)) == 2
    result = technicians.recommend(
        client_id="acme",
        ticket_id="TCK-1001",
        required_expertise=["mfa"],
        now="2026-08-31T09:30:00Z",
    )
    assert result["recommendation"] is None
    assert result["dispatch_payload"]["technicians"] == []  # type: ignore[index]
    assert result["candidates"][0]["available"] is False  # type: ignore[index]
    assert "unavailable until" in result["candidates"][0]["reasons"][0]  # type: ignore[index]

    available = technicians.record_workload(
        client_id="acme",
        technician_id="day-tech",
        open_tickets=0,
        active_incidents=0,
        scheduled_changes=0,
        unavailable_until=None,
        source="manual",
        observed_at="2026-08-31T10:30:00Z",
        actor="admin",
    )
    assert available.open_tickets == 0
    inside = technicians.recommend(
        client_id="acme",
        ticket_id="TCK-1001",
        now="2026-08-31T12:00:00Z",
    )
    assert inside["recommendation"]["available"] is True  # type: ignore[index]
    outside = technicians.recommend(
        client_id="acme",
        ticket_id="TCK-1001",
        now="2026-09-01T02:00:00Z",
    )
    assert outside["recommendation"] is None
    assert outside["candidates"][0]["available"] is False  # type: ignore[index]


def test_technician_validation_rejects_bad_inputs(settings) -> None:
    store, _, _, _, _, _ = _runtime(settings)
    technicians = TechnicianService(store)
    with pytest.raises(AgentPlatformError):
        technicians.upsert_profile(
            client_id="acme",
            technician_id="bad",
            display_name="Bad",
            timezone="Not/AZone",
            working_hours={},
            expertise=[],
            client_familiarity=0,
            capacity=1,
            enabled=True,
            actor="admin",
        )
    with pytest.raises(AgentPlatformError):
        technicians.upsert_profile(
            client_id="acme",
            technician_id="bad",
            display_name="Bad",
            timezone="UTC",
            working_hours={"monday": [{"start": "17:00", "end": "09:00"}]},
            expertise=[],
            client_familiarity=0,
            capacity=1,
            enabled=True,
            actor="admin",
        )
    with pytest.raises(AgentPlatformNotFoundError):
        technicians.get(client_id="acme", technician_id="missing")


def test_attachment_upload_duplicate_validation_and_context(settings) -> None:
    store, _, _, memories, _, _ = _runtime(settings, clients=("acme", "beta"))
    attachments = AttachmentService(store, settings, memories)
    attachment = attachments.upload(
        client_id="acme",
        ticket_id="TCK-1001",
        filename="error.png",
        media_type="image/png",
        content_base64=_ONE_PIXEL_PNG,
        actor="tech",
    )
    duplicate = attachments.upload(
        client_id="acme",
        ticket_id="TCK-1001",
        filename="renamed.png",
        media_type="image/png",
        content_base64=_ONE_PIXEL_PNG,
        actor="tech",
    )
    assert duplicate.id == attachment.id
    assert attachments.get(
        client_id="acme", ticket_id="TCK-1001", attachment_id=attachment.id
    ) == attachment
    assert attachments.list(client_id="acme", ticket_id="TCK-1001") == [attachment]
    with pytest.raises(AgentPlatformNotFoundError):
        attachments.get(
            client_id="beta", ticket_id="TCK-1001", attachment_id=attachment.id
        )
    with pytest.raises(AgentPlatformError):
        attachments.upload(
            client_id="acme",
            ticket_id="TCK-1001",
            filename="bad.png",
            media_type="image/png",
            content_base64=base64.b64encode(b"not png").decode("ascii"),
            actor="tech",
        )
    with pytest.raises(AgentPlatformError):
        attachments.upload(
            client_id="acme",
            ticket_id="TCK-1001",
            filename="../bad.png",
            media_type="image/png",
            content_base64=_ONE_PIXEL_PNG,
            actor="tech",
        )

    blocked = attachments.analyze(
        client_id="acme",
        ticket_id="TCK-1001",
        attachment_id=attachment.id,
        prompt="",
        actor="tech",
    )
    assert blocked.status == "blocked"
    assert attachments.analyses(
        client_id="acme", ticket_id="TCK-1001", attachment_id=attachment.id
    )[0].id == blocked.id
    context = attachments.ticket_context(client_id="acme", ticket_id="TCK-1001")
    assert context["attachments"][0]["analysis"]["status"] == "blocked"  # type: ignore[index]


def test_attachment_analysis_ready_failed_and_integrity_paths(settings, monkeypatch) -> None:
    store, _, _, memories, _, _ = _runtime(settings)
    enabled = replace(
        settings,
        allow_llm_inference=True,
        local_model_provider="openai-compatible",
        local_model_base_url="http://127.0.0.1:11434/v1",
        local_model_name="vision-test",
    )
    attachments = AttachmentService(store, enabled, memories)
    attachment = attachments.upload(
        client_id="acme",
        ticket_id="TCK-1001",
        filename="dialog.png",
        media_type="image/png",
        content_base64=_ONE_PIXEL_PNG,
        actor="tech",
    )
    monkeypatch.setattr(
        "packs.agent_platform.vision._request_analysis",
        lambda **_: {
            "summary": "Visible access denied dialog",
            "visible_text": ["Access denied"],
            "indicators": ["error code 5"],
            "confidence": 0.8,
            "limitations": ["No hidden state"],
        },
    )
    ready = attachments.analyze(
        client_id="acme",
        ticket_id="TCK-1001",
        attachment_id=attachment.id,
        prompt="Describe the dialog.",
        actor="tech",
    )
    assert ready.status == "ready"
    assert ready.result["evidence_only"] is True
    assert ready.result["confidence"] == 0.8

    monkeypatch.setattr(
        "packs.agent_platform.vision._request_analysis",
        lambda **_: (_ for _ in ()).throw(AgentPlatformError("provider unavailable")),
    )
    failed = attachments.analyze(
        client_id="acme",
        ticket_id="TCK-1001",
        attachment_id=attachment.id,
        prompt="Try again.",
        actor="tech",
    )
    assert failed.status == "failed"
    assert failed.error_detail == "provider unavailable"

    with store._connect() as connection:
        path = Path(
            connection.execute(
                "select storage_path from ticket_attachments where id = ?", (attachment.id,)
            ).fetchone()[0]
        )
    path.write_bytes(b"tampered")
    integrity = attachments.analyze(
        client_id="acme",
        ticket_id="TCK-1001",
        attachment_id=attachment.id,
        prompt="Inspect.",
        actor="tech",
    )
    assert integrity.status == "failed"
    assert "integrity check failed" in integrity.error_detail


def test_multimodal_response_contract_and_url_validation() -> None:
    assert _safe_base_url("https://models.example.test/v1/") == "https://models.example.test/v1"
    with pytest.raises(AgentPlatformError):
        _safe_base_url("file:///tmp/model")
    with pytest.raises(AgentPlatformError):
        _safe_base_url("https://user:pass@example.test/v1")
    with pytest.raises(AgentPlatformError):
        _safe_base_url("http://models.example.test/v1")
    assert (
        _safe_base_url(
            "http://models.example.test/v1",
            allow_insecure_transport=True,
        )
        == "http://models.example.test/v1"
    )

    normalized = _normalize_analysis(
        {
            "summary": "Error dialog",
            "visible_text": ["Failure"],
            "indicators": ["code 5"],
            "confidence": 2.0,
            "limitations": ["partial"],
        }
    )
    assert normalized["confidence"] == 1.0
    assert normalized["evidence_only"] is True
    with pytest.raises(AgentPlatformError):
        _normalize_analysis({"summary": "", "visible_text": [], "indicators": []})


def test_request_analysis_parses_json_and_bounds_provider_failures(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["messages"][1]["content"][0]["text"].startswith("Attached ticket image")
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": (
                                "```json\n"
                                '{"summary":"Visible dialog","visible_text":[],"indicators":[],'
                                '"confidence":0.5,"limitations":[]}\n'
                                "```"
                            )
                        }
                    }
                ]
            },
        )

    original_client = httpx.Client

    def client_factory(*args, **kwargs):
        return original_client(
            timeout=kwargs.get("timeout", 1.0),
            transport=httpx.MockTransport(handler),
        )

    monkeypatch.setattr("packs.agent_platform.vision.build_pinned_client", client_factory)
    result = _request_analysis(
        base_url="https://models.example.test/v1",
        model="vision-test",
        api_key="secret",
        timeout=1.0,
        media_type="image/png",
        content=_ONE_PIXEL_PNG_BYTES,
        prompt="Summarize.",
    )
    assert result["summary"] == "Visible dialog"

    def unauthorized(_: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "no"})

    def unauthorized_client(*args, **kwargs):
        return original_client(
            timeout=kwargs.get("timeout", 1.0),
            transport=httpx.MockTransport(unauthorized),
        )

    monkeypatch.setattr("packs.agent_platform.vision.build_pinned_client", unauthorized_client)
    with pytest.raises(AgentPlatformError, match="unauthorized"):
        _request_analysis(
            base_url="https://models.example.test/v1",
            model="vision-test",
            api_key="secret",
            timeout=1.0,
            media_type="image/png",
            content=_ONE_PIXEL_PNG_BYTES,
            prompt="Summarize.",
        )
