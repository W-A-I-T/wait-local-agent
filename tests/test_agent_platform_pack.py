from __future__ import annotations

import base64
from pathlib import Path

from fastapi.testclient import TestClient

from packs.agent_platform.iterations import IterationService
from packs.agent_platform.memory import MemoryService
from packs.agent_platform.skills import SkillService
from packs.agent_platform.technicians import TechnicianService
from packs.agent_platform.vision import AttachmentService
from tests.support import ensure_test_client, ingest_local
from wait_local_agent.agents import AgentService
from wait_local_agent.api.app import create_app
from wait_local_agent.config import Settings
from wait_local_agent.rbac import Role
from wait_local_agent.smart_actions import SmartActionService
from wait_local_agent.store import Store


_SAMPLE_TICKETS = Path("examples/sample_tickets/tickets.json")
_ONE_PIXEL_PNG = base64.b64encode(
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
    b"\x00\x00\x00\rIDAT\x08\xd7c\xf8\xcf\xc0\xf0\x1f\x00\x05\x00\x01\xff\x89\x99=\x1d"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
).decode("ascii")


def _runtime(
    settings: Settings,
    *,
    client_id: str = "acme",
) -> tuple[Store, SmartActionService, AgentService, MemoryService, SkillService]:
    store = Store(settings.data_path)
    ensure_test_client(store, client_id)
    ingest_local(store, _SAMPLE_TICKETS, client_id=client_id)
    actions = SmartActionService(store, settings)
    agents = AgentService(store, settings, actions)
    memories = MemoryService(store)
    skills = SkillService(store, actions)
    return store, actions, agents, memories, skills


def test_memory_revisions_restore_and_context_are_tenant_scoped(settings) -> None:
    store = Store(settings.data_path)
    ensure_test_client(store, "acme")
    ensure_test_client(store, "beta")
    service = MemoryService(store)

    first = service.put(
        client_id="acme",
        scope_type="client",
        scope_id="ignored-for-client",
        key="preferred-reboot-window",
        value={"window": "Saturday 22:00"},
        summary="Customer maintenance preference",
        provenance="approved client onboarding record",
        actor="admin",
    )
    second = service.put(
        client_id="acme",
        scope_type="client",
        scope_id="acme",
        key="preferred-reboot-window",
        value={"window": "Sunday 01:00"},
        summary="Updated maintenance preference",
        provenance="change review CR-100",
        actor="admin",
        pinned=True,
    )

    assert first.version == 1
    assert second.version == 2
    assert service.get(client_id="acme", memory_id=first.id, include_history=True).status == "superseded"
    assert service.list(client_id="beta") == []
    context = service.resolve_context(client_id="acme")
    assert context[0]["value"] == {"window": "Sunday 01:00"}
    assert context[0]["pinned"] is True

    restored = service.restore(client_id="acme", memory_id=first.id, actor="admin")
    assert restored.version == 3
    assert restored.value == {"window": "Saturday 22:00"}
    assert restored.provenance == f"restored:{first.id}"


def test_versioned_skill_validation_is_side_effect_free(settings) -> None:
    store, actions, _, _, skills = _runtime(settings)

    skill = skills.create(
        client_id="acme",
        name="Ticket triage assistant",
        slug="ticket-triage-assistant",
        description="Renders a bounded triage instruction.",
        instructions="Triage {{input.ticket_id}} using {{memory.priority_policy}}.",
        allowed_tools=["ticket-triage"],
        input_schema={
            "type": "object",
            "required": ["ticket_id"],
            "additionalProperties": False,
            "properties": {
                "ticket_id": {"type": "string", "minLength": 1, "maxLength": 128}
            },
        },
        resources=[
            {
                "name": "notes.md",
                "media_type": "text/markdown",
                "content": "Use the client priority policy.",
            }
        ],
        actor="technician",
    )
    result = skills.test(
        client_id="acme",
        skill_id=skill.id,
        sample_input={"ticket_id": "TCK-1001"},
        memory={"priority_policy": "escalate P1 immediately"},
        actor="technician",
    )

    assert result.status == "passed"
    assert result.output["side_effects"] is False
    assert result.output["rendered_instructions"] == (
        "Triage TCK-1001 using escalate P1 immediately."
    )
    assert result.output["tool_plan"][0]["tool_id"] == "ticket-triage"  # type: ignore[index]
    assert store.list_smart_action_runs(client_id="acme") == []

    updated = skills.update(
        client_id="acme",
        skill_id=skill.id,
        actor="technician",
        instructions="Summarize and triage {{input.ticket_id}}.",
    )
    assert updated.current_version == 2
    assert [revision.version for revision in skills.revisions(client_id="acme", skill_id=skill.id)] == [2, 1]


def test_iteration_executes_one_governed_step_at_a_time(settings) -> None:
    store, actions, agents, _, skills = _runtime(settings)
    definition = agents.create(
        name="Triage one ticket",
        description="Runs one deterministic read action.",
        enabled=True,
        trigger="manual",
        entity_type="ticket",
        filters={},
        enabled_tools=["ticket-triage"],
        steps=[{"tool_id": "ticket-triage", "payload": {}}],
        max_steps=1,
        execution_timeout_seconds=30,
        client_id="acme",
    )
    iterations = IterationService(store, actions, agents, skills, MemoryService(store))
    session = iterations.create(
        client_id="acme",
        source_type="agent",
        source_id=definition.id,
        entity_id="TCK-1001",
        instruction="Pause after the triage result.",
        actor="technician",
    )

    assert session.status == "awaiting_continue"
    assert session.current_step == 0
    completed = iterations.continue_once(
        client_id="acme",
        session_id=session.id,
        actor="technician",
        actor_role=Role.TECHNICIAN,
    )
    assert completed.status == "completed"
    assert completed.current_step == 1
    assert len(completed.state["results"]) == 1  # type: ignore[arg-type]
    assert any(event.event_type == "step.completed" for event in completed.events)


def test_iteration_reuses_existing_approval_boundary(settings) -> None:
    store, actions, agents, _, skills = _runtime(settings)
    definition = agents.create(
        name="Dispatch review",
        description="Drafts a dispatch recommendation for approval.",
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
    iterations = IterationService(store, actions, agents, skills, MemoryService(store))
    session = iterations.create(
        client_id="acme",
        source_type="agent",
        source_id=definition.id,
        entity_id="TCK-1001",
        instruction="Review before assigning.",
        actor="requester",
    )

    pending = iterations.continue_once(
        client_id="acme",
        session_id=session.id,
        actor="requester",
        actor_role=Role.TECHNICIAN,
    )
    assert pending.status == "pending_approval"
    assert pending.current_step == 0
    assert pending.approval_id is not None
    approval = store.get_approval_request(pending.approval_id)
    assert approval is not None
    assert approval.status == "pending"


def test_technician_ranking_uses_expertise_availability_and_workload(settings) -> None:
    store, _, _, _, _ = _runtime(settings)
    technicians = TechnicianService(store)
    technicians.upsert_profile(
        client_id="acme",
        technician_id="identity-tech",
        display_name="Identity Tech",
        timezone="UTC",
        working_hours={},
        expertise=["mfa", "entra", "sign in"],
        client_familiarity=5,
        capacity=40,
        enabled=True,
        actor="admin",
    )
    technicians.record_workload(
        client_id="acme",
        technician_id="identity-tech",
        open_tickets=2,
        active_incidents=0,
        scheduled_changes=0,
        unavailable_until=None,
        source="manual",
        observed_at="2026-08-29T20:00:00+00:00",
        actor="admin",
    )
    technicians.upsert_profile(
        client_id="acme",
        technician_id="busy-generalist",
        display_name="Busy Generalist",
        timezone="UTC",
        working_hours={},
        expertise=["hardware"],
        client_familiarity=1,
        capacity=10,
        enabled=True,
        actor="admin",
    )
    technicians.record_workload(
        client_id="acme",
        technician_id="busy-generalist",
        open_tickets=20,
        active_incidents=2,
        scheduled_changes=1,
        unavailable_until=None,
        source="manual",
        observed_at="2026-08-29T20:00:00+00:00",
        actor="admin",
    )

    result = technicians.recommend(
        client_id="acme",
        ticket_id="TCK-1001",
        required_expertise=["mfa"],
        now="2026-08-29T21:00:00+00:00",
    )
    assert result["side_effects"] is False
    assert result["recommendation"]["technician_id"] == "identity-tech"  # type: ignore[index]
    assert result["dispatch_payload"]["ticket_id"] == "TCK-1001"  # type: ignore[index]


def test_attachment_storage_is_private_and_analysis_fails_closed(settings) -> None:
    store, _, _, memories, _ = _runtime(settings)
    attachments = AttachmentService(store, settings, memories)

    attachment = attachments.upload(
        client_id="acme",
        ticket_id="TCK-1001",
        filename="error.png",
        media_type="image/png",
        content_base64=_ONE_PIXEL_PNG,
        actor="technician",
    )
    assert attachment.byte_size > 0
    assert "storage_path" not in attachment.to_dict()

    analysis = attachments.analyze(
        client_id="acme",
        ticket_id="TCK-1001",
        attachment_id=attachment.id,
        prompt="Describe the visible error.",
        actor="technician",
    )
    assert analysis.status == "blocked"
    assert "WAIT_ALLOW_LLM_INFERENCE" in analysis.error_detail
    context = attachments.ticket_context(client_id="acme", ticket_id="TCK-1001")
    assert context["attachments"][0]["analysis"]["status"] == "blocked"  # type: ignore[index]
    assert context["limits"]["raw_attachment_bytes_returned"] is False  # type: ignore[index]


def test_pack_routes_are_mounted_and_use_demo_tenant_scope(settings) -> None:
    application = create_app(settings)
    ensure_test_client(application.state.store, "demo")
    client = TestClient(application)

    status_response = client.get("/packs/agent-platform/status")
    memory_response = client.post(
        "/packs/agent-platform/memories",
        json={
            "scope_type": "client",
            "scope_id": "demo",
            "key": "timezone",
            "value": {"name": "America/Vancouver"},
            "summary": "Customer timezone",
            "provenance": "administrator",
        },
    )
    foreign_response = client.get(
        "/packs/agent-platform/memories",
        params={"client_id": "another-client"},
    )

    assert status_response.status_code == 200
    assert status_response.json()["capabilities"]["durable_memory"] is True
    assert memory_response.status_code == 201
    assert memory_response.json()["client_id"] == "demo"
    assert foreign_response.status_code in {403, 404}


def test_pack_routes_exercise_persisted_capability_lifecycles(settings) -> None:
    application = create_app(settings)
    store = application.state.store
    ensure_test_client(store, "demo")
    ingest_local(store, _SAMPLE_TICKETS, client_id="demo")
    client = TestClient(application)
    headers = {"X-WAIT-Client-ID": "demo"}

    memory = client.post(
        "/packs/agent-platform/memories",
        headers=headers,
        json={
            "scope_type": "ticket",
            "scope_id": "TCK-1001",
            "key": "maintenance-window",
            "value": {"day": "Sunday"},
            "summary": "Approved window",
            "provenance": "change record",
        },
    )
    assert memory.status_code == 201
    memory_id = memory.json()["id"]
    assert client.get("/packs/agent-platform/memories", headers=headers).json()[0]["id"] == memory_id
    assert client.get(f"/packs/agent-platform/memories/{memory_id}", headers=headers).status_code == 200
    pinned = client.post(
        f"/packs/agent-platform/memories/{memory_id}/pin",
        headers=headers,
        json={"pinned": True},
    )
    assert pinned.json()["pinned"] is True
    context = client.get(
        "/packs/agent-platform/context",
        headers=headers,
        params={"ticket_id": "TCK-1001"},
    )
    assert context.json()["memories"][0]["key"] == "maintenance-window"
    assert client.delete(f"/packs/agent-platform/memories/{memory_id}", headers=headers).status_code == 200
    restored = client.post(
        f"/packs/agent-platform/memories/{memory_id}/restore",
        headers=headers,
        json={},
    )
    assert restored.json()["version"] == 2
    assert client.get(
        "/packs/agent-platform/memories/missing",
        headers=headers,
    ).status_code == 404
    assert client.post(
        "/packs/agent-platform/memories",
        headers=headers,
        json={
            "client_id": "another-client",
            "scope_type": "client",
            "scope_id": "",
            "key": "conflict",
            "value": {},
            "provenance": "test",
        },
    ).status_code == 400

    skill_response = client.post(
        "/packs/agent-platform/skills",
        headers=headers,
        json={
            "name": "Ticket triage",
            "slug": "ticket-triage",
            "description": "Bounded triage guidance.",
            "instructions": "Triage {{input.ticket_id}}.",
            "allowed_tools": ["ticket-triage"],
            "input_schema": {
                "type": "object",
                "required": ["ticket_id"],
                "additionalProperties": False,
                "properties": {"ticket_id": {"type": "string", "minLength": 1}},
            },
            "resources": [
                {
                    "name": "notes.md",
                    "media_type": "text/markdown",
                    "content": "Use bounded evidence.",
                }
            ],
        },
    )
    assert skill_response.status_code == 201
    skill_id = skill_response.json()["id"]
    assert client.get("/packs/agent-platform/skills", headers=headers).json()[0]["id"] == skill_id
    assert client.get(f"/packs/agent-platform/skills/{skill_id}", headers=headers).status_code == 200
    test_run = client.post(
        f"/packs/agent-platform/skills/{skill_id}/tests",
        headers=headers,
        json={"sample_input": {"ticket_id": "TCK-1001"}, "memory": {}},
    )
    assert test_run.status_code == 201
    assert test_run.json()["status"] == "passed"
    assert client.get(
        f"/packs/agent-platform/skills/{skill_id}/tests",
        headers=headers,
    ).json()[0]["id"] == test_run.json()["id"]
    updated = client.put(
        f"/packs/agent-platform/skills/{skill_id}",
        headers=headers,
        json={"instructions": "Summarize then triage {{input.ticket_id}}."},
    )
    assert updated.json()["current_version"] == 2
    revisions = client.get(
        f"/packs/agent-platform/skills/{skill_id}/revisions",
        headers=headers,
    )
    assert [item["version"] for item in revisions.json()] == [2, 1]
    assert client.post(
        f"/packs/agent-platform/skills/{skill_id}/archive",
        headers=headers,
        json={},
    ).json()["status"] == "archived"
    assert client.get(
        "/packs/agent-platform/skills",
        headers=headers,
        params={"include_archived": True},
    ).json()[0]["id"] == skill_id
    assert client.post(
        "/packs/agent-platform/skills",
        headers=headers,
        json={
            "name": "Bad tool",
            "slug": "bad-tool",
            "instructions": "Do work.",
            "allowed_tools": ["missing-tool"],
            "input_schema": {"type": "object"},
            "resources": [],
        },
    ).status_code == 422

    profile = client.put(
        "/packs/agent-platform/technicians/tech-a",
        headers=headers,
        json={
            "display_name": "Technician A",
            "timezone": "UTC",
            "working_hours": {},
            "expertise": ["mfa", "entra"],
            "client_familiarity": 4,
            "capacity": 20,
            "enabled": True,
        },
    )
    assert profile.status_code == 200
    workload = client.post(
        "/packs/agent-platform/technicians/tech-a/workloads",
        headers=headers,
        json={
            "open_tickets": 1,
            "active_incidents": 0,
            "scheduled_changes": 0,
            "source": "test",
        },
    )
    assert workload.status_code == 201
    assert client.get("/packs/agent-platform/technicians", headers=headers).json()[0][
        "technician_id"
    ] == "tech-a"
    recommendation = client.post(
        "/packs/agent-platform/technicians/recommend",
        headers=headers,
        json={"ticket_id": "TCK-1001", "required_expertise": ["mfa"]},
    )
    assert recommendation.json()["recommendation"]["technician_id"] == "tech-a"

    attachment = client.post(
        "/packs/agent-platform/tickets/TCK-1001/attachments",
        headers=headers,
        json={
            "filename": "error.png",
            "media_type": "image/png",
            "content_base64": _ONE_PIXEL_PNG,
        },
    )
    assert attachment.status_code == 201
    attachment_id = attachment.json()["id"]
    assert client.get(
        "/packs/agent-platform/tickets/TCK-1001/attachments",
        headers=headers,
    ).json()[0]["id"] == attachment_id
    analysis = client.post(
        f"/packs/agent-platform/tickets/TCK-1001/attachments/{attachment_id}/analyze",
        headers=headers,
        json={"prompt": "Describe visible evidence."},
    )
    assert analysis.status_code == 201
    assert analysis.json()["status"] == "blocked"
    assert client.get(
        "/packs/agent-platform/tickets/TCK-1001/attachments/analyses",
        headers=headers,
    ).json()[0]["attachment_id"] == attachment_id
    ticket_context = client.get(
        "/packs/agent-platform/tickets/TCK-1001/context",
        headers=headers,
    )
    assert ticket_context.json()["attachments"][0]["analysis"]["status"] == "blocked"


def test_pack_iteration_routes_pause_modify_continue_restart_and_finish(settings) -> None:
    application = create_app(settings)
    store = application.state.store
    ensure_test_client(store, "demo")
    ingest_local(store, _SAMPLE_TICKETS, client_id="demo")
    actions = SmartActionService(store, settings)
    agents = AgentService(store, settings, actions)
    definition = agents.create(
        name="Two-step route review",
        description="Two bounded deterministic steps.",
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
        client_id="demo",
    )
    client = TestClient(application)
    headers = {"X-WAIT-Client-ID": "demo"}

    created = client.post(
        "/packs/agent-platform/iterations",
        headers=headers,
        json={
            "source_type": "agent",
            "source_id": definition.id,
            "entity_id": "TCK-1001",
            "instruction": "Pause after each step.",
        },
    )
    assert created.status_code == 201
    session_id = created.json()["id"]
    assert client.get("/packs/agent-platform/iterations", headers=headers).json()[0][
        "id"
    ] == session_id
    assert client.get(
        f"/packs/agent-platform/iterations/{session_id}",
        headers=headers,
    ).status_code == 200
    modified = client.patch(
        f"/packs/agent-platform/iterations/{session_id}/steps/1",
        headers=headers,
        json={"tool_id": "ticket-triage", "payload": {}},
    )
    assert modified.json()["steps"][1]["tool_id"] == "ticket-triage"
    first = client.post(
        f"/packs/agent-platform/iterations/{session_id}/continue",
        headers=headers,
        json={},
    )
    assert first.json()["status"] == "awaiting_continue"
    second = client.post(
        f"/packs/agent-platform/iterations/{session_id}/continue",
        headers=headers,
        json={},
    )
    assert second.json()["status"] == "completed"
    restarted = client.post(
        f"/packs/agent-platform/iterations/{session_id}/restart",
        headers=headers,
        json={},
    )
    assert restarted.json()["current_step"] == 0
    finished = client.post(
        f"/packs/agent-platform/iterations/{session_id}/finish",
        headers=headers,
        json={"reason": "Review complete."},
    )
    assert finished.json()["status"] == "completed"
    assert client.get(
        "/packs/agent-platform/iterations/missing",
        headers=headers,
    ).status_code == 404
