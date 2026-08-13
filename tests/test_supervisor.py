from __future__ import annotations

from dataclasses import replace
from typing import cast

import pytest

from wait_local_agent.agents import AgentExecutionResult
from wait_local_agent.models import AgentDefinition, AgentRun
from wait_local_agent.rbac import Role
from wait_local_agent.store import Store
from wait_local_agent.supervisor import (
    SupervisorPlanError,
    _bounded_final_result,
    _bounded_payload,
    _dependency_order,
    _identifier,
    _scoped_definition,
    _text,
    build_supervisor_delegation_plan,
    execute_supervisor_delegation,
)


def _definition(agent_id: str, *, client_id: str | None = "acme") -> AgentDefinition:
    return AgentDefinition(
        id=agent_id,
        name=agent_id.title(),
        description="bounded child",
        enabled=True,
        trigger="manual",
        entity_type="ticket",
        filters={},
        enabled_tools=["ticket-triage"],
        steps=[{"tool_id": "ticket-triage", "payload": {}}],
        max_steps=1,
        execution_timeout_seconds=30,
        client_id=client_id,
        version=1,
        created_at="2026-08-11T00:00:00Z",
        updated_at="2026-08-11T00:00:00Z",
        depends_on_agent_ids=[],
    )


def test_supervisor_plan_selects_explicit_children_and_bounds_context() -> None:
    child = replace(_definition("security"), depends_on_agent_ids=["identity"])
    result = build_supervisor_delegation_plan(
        client_id="acme",
        task="Review onboarding security prerequisites",
        child_agent_ids=["identity", "security"],
        definitions=[_definition("identity"), child],
    )

    assert result["format"] == "wait-local-agent.supervisor-delegation-plan"
    assert result["supervisor"]["children"][1]["depends_on_agent_ids"] == ["identity"]
    assert result["assignments"][0]["input_contract"]["client_id"] == "acme"
    assert result["delegation_started"] is False
    assert result["execution_started"] is False
    assert result["cross_tenant_context"] is False


def test_supervisor_execution_orders_children_and_passes_bounded_prior_results(settings) -> None:
    identity = _definition("identity")
    security = replace(identity, id="security", depends_on_agent_ids=["identity"])

    class FakeAgentService:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, object]]] = []

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
            assert supervisor_context is not None
            self.calls.append((definition.id, supervisor_context))
            return AgentExecutionResult(
                run_id=len(self.calls),
                agent_id=definition.id,
                status="completed",
                current_step=1,
                steps=[],
                final_result={"summary": f"{definition.id} complete"},
            )

    service = FakeAgentService()
    result = execute_supervisor_delegation(
        client_id="acme",
        entity_id="TCK-1001",
        task="Review onboarding",
        child_agent_ids=["security", "identity"],
        definitions=[identity, security],
        agent_service=service,
        store=Store(settings.data_path),
        actor="technician",
        actor_role=Role.TECHNICIAN,
        input_payload={"ticket_id": "TCK-1001"},
    )

    assert result["status"] == "completed"
    assert result["delegation_started"] is True
    assert result["execution_started"] is True
    supervisor_result = cast(dict[str, object], result["supervisor"])
    assert supervisor_result["ordered_child_agent_ids"] == ["identity", "security"]
    assert [call[0] for call in service.calls] == ["identity", "security"]
    prior_results = cast(list[dict[str, object]], service.calls[1][1]["prior_results"])
    assert prior_results[0]["agent_id"] == "identity"
    assert result["cross_tenant_context"] is False


@pytest.mark.parametrize(
    ("child_ids", "definitions", "message"),
    [
        (["missing"], [_definition("identity")], "not found"),
        (["identity", "identity"], [_definition("identity")], "duplicates"),
        ([], [_definition("identity")], "contain 1-8"),
        (["identity"], [replace(_definition("identity"), client_id="beta")], "outside the tenant"),
    ],
)
def test_supervisor_plan_rejects_missing_duplicate_or_foreign_children(child_ids, definitions, message) -> None:
    with pytest.raises(SupervisorPlanError, match=message):
        build_supervisor_delegation_plan(
            client_id="acme",
            task="Review request",
            child_agent_ids=child_ids,
            definitions=definitions,
        )


def test_supervisor_execution_handles_authority_disabled_children_and_dependency_errors(settings) -> None:
    identity = _definition("identity")
    disabled = replace(identity, id="disabled", enabled=False)

    class Runner:
        def run(self, *_args, **_kwargs):
            return AgentExecutionResult(1, "identity", "completed", 1, [], final_result={})

    with pytest.raises(SupervisorPlanError, match="technician authority"):
        execute_supervisor_delegation(
            client_id="acme", entity_id="TCK-1", task="task", child_agent_ids=["identity"],
            definitions=[identity], agent_service=Runner(), store=Store(settings.data_path),
            actor="viewer", actor_role=Role.VIEWER,
        )
    with pytest.raises(SupervisorPlanError, match="disabled"):
        execute_supervisor_delegation(
            client_id="acme", entity_id="TCK-1", task="task", child_agent_ids=["disabled"],
            definitions=[disabled], agent_service=Runner(), store=Store(settings.data_path),
            actor="tech", actor_role=Role.TECHNICIAN,
        )
    with pytest.raises(SupervisorPlanError, match="dependency cycle"):
        execute_supervisor_delegation(
            client_id="acme", entity_id="TCK-1", task="task", child_agent_ids=["a", "b"],
            definitions=[
                replace(_definition("a"), depends_on_agent_ids=["b"]),
                replace(_definition("b"), depends_on_agent_ids=["a"]),
            ],
            agent_service=Runner(), store=Store(settings.data_path), actor="tech", actor_role=Role.TECHNICIAN,
        )
    with pytest.raises(SupervisorPlanError, match="dependency agent"):
        execute_supervisor_delegation(
            client_id="acme", entity_id="TCK-1", task="task", child_agent_ids=["b"],
            definitions=[replace(_definition("b"), depends_on_agent_ids=["a"])],
            agent_service=Runner(), store=Store(settings.data_path), actor="tech", actor_role=Role.TECHNICIAN,
        )


@pytest.mark.parametrize("status", ["pending_approval", "failed"])
def test_supervisor_execution_preserves_pending_and_failure_results(settings, status: str) -> None:
    child = _definition("identity")

    class Runner:
        def run(self, *_args, **_kwargs):
            if status == "failed":
                raise RuntimeError("provider secret should be redacted")
            return AgentExecutionResult(9, "identity", status, 1, [], approval_id=7, error_detail="blocked")

    result = execute_supervisor_delegation(
        client_id="acme", entity_id="TCK-1", task="task", child_agent_ids=["identity"],
        definitions=[child], agent_service=Runner(), store=Store(settings.data_path),
        actor="tech", actor_role=Role.TECHNICIAN,
    )
    assert result["status"] == status
    assert result["approval_requests_created"] is (status == "pending_approval")
    assert result["resumption"]["next_child_agent_id"] == "identity"


def test_supervisor_retries_failed_child_with_bounded_lineage(settings, monkeypatch) -> None:
    child = _definition("identity")
    store = Store(settings.data_path)
    failed_run = AgentRun(
        id=41, agent_id="identity", entity_id="TCK-1", actor="tech", status="failed",
        current_step=1, state_json='{"input": {"ticket_id": "TCK-1"}, "retry_count": 0}',
        started_at="", finished_at="", revision_version=1, client_id="acme",
    )
    monkeypatch.setattr(store, "get_agent_run", lambda run_id, _client_id: failed_run if run_id == 41 else None)

    class Runner:
        def __init__(self) -> None:
            self.retry_context: dict[str, object] | None = None

        def run(self, *_args, **_kwargs):
            return AgentExecutionResult(41, "identity", "failed", 1, [], error_detail="temporary")

        def retry(self, _definition, _run, *, actor, actor_role, supervisor_context=None):
            assert actor == "tech"
            assert actor_role == Role.TECHNICIAN
            self.retry_context = supervisor_context
            return AgentExecutionResult(42, "identity", "completed", 1, [], final_result={"summary": "ok"})

    service = Runner()
    result = execute_supervisor_delegation(
        client_id="acme", entity_id="TCK-1", task="task", child_agent_ids=["identity"],
        definitions=[child], agent_service=service, store=store, actor="tech", actor_role=Role.TECHNICIAN,
        max_retries=1,
    )

    child_result = result["children"][0]
    assert result["status"] == "completed"
    assert child_result["run_id"] == 42
    assert child_result["retry_count"] == 1
    assert [attempt["status"] for attempt in child_result["attempts"]] == ["failed", "completed"]
    assert child_result["lineage"]["retry_of_run_id"] == 41
    assert service.retry_context is not None
    assert service.retry_context["supervisor_id"] == "consultant-supervisor"
    assert service.retry_context["retry_of_run_id"] == 41


def test_supervisor_cancels_only_scoped_approval_paused_child(settings, monkeypatch) -> None:
    child = _definition("identity")
    store = Store(settings.data_path)
    pending_run = AgentRun(
        id=52, agent_id="identity", entity_id="TCK-1", actor="tech", status="pending_approval",
        current_step=1, state_json='{"pending_approval_step": 0}',
        started_at="", finished_at="", revision_version=1, client_id="acme",
    )
    monkeypatch.setattr(store, "get_agent_run", lambda run_id, _client_id: pending_run if run_id == 52 else None)

    class Runner:
        def run(self, *_args, **_kwargs):
            raise AssertionError("cancelled child must not execute")

        def cancel(self, _definition, run, *, actor, approver_role):
            assert run.id == 52
            assert actor == "tech"
            assert approver_role == Role.TECHNICIAN
            return AgentExecutionResult(52, "identity", "cancelled", 1, [], error_detail="cancelled")

    result = execute_supervisor_delegation(
        client_id="acme", entity_id="TCK-1", task="task", child_agent_ids=["identity"],
        definitions=[child], agent_service=Runner(), store=store, actor="tech", actor_role=Role.TECHNICIAN,
        cancel_run_id=52,
    )

    assert result["status"] == "cancelled"
    assert result["cancellation"] == {"requested_run_id": 52, "applied": True}
    assert result["children"][0]["status"] == "cancelled"


def test_supervisor_resumes_completed_run_and_rejects_malformed_or_foreign_state(settings, monkeypatch) -> None:
    child = _definition("identity")
    store = Store(settings.data_path)
    completed = AgentRun(
        id=12, agent_id="identity", entity_id="TCK-1", actor="tech", status="completed",
        current_step=1, state_json='{"final_result":{"summary":"done"}}',
        started_at="", finished_at="", revision_version=1, client_id="acme",
    )
    monkeypatch.setattr(store, "get_agent_run", lambda _run_id, _client_id: completed)

    class Runner:
        def run(self, *_args, **_kwargs):
            raise AssertionError("resumed child must not execute")

    result = execute_supervisor_delegation(
        client_id="acme", entity_id="TCK-1", task="task", child_agent_ids=["identity"],
        definitions=[child], agent_service=Runner(), store=store, actor="tech", actor_role=Role.TECHNICIAN,
        completed_run_ids=[12],
    )
    assert result["execution_started"] is True
    assert result["children"][0]["resumed"] is True

    monkeypatch.setattr(store, "get_agent_run", lambda _run_id, _client_id: replace(completed, state_json="not-json"))
    with pytest.raises(SupervisorPlanError, match="malformed"):
        execute_supervisor_delegation(
            client_id="acme", entity_id="TCK-1", task="task", child_agent_ids=["identity"],
            definitions=[child], agent_service=Runner(), store=store, actor="tech", actor_role=Role.TECHNICIAN,
            completed_run_ids=[12],
        )


def test_supervisor_private_bounds_and_dependency_guards() -> None:
    identity = _definition("identity")
    dependent = replace(identity, id="dependent", depends_on_agent_ids=["identity"])
    assert _dependency_order(["dependent", "identity"], {"identity": identity, "dependent": dependent}) == [
        "identity",
        "dependent",
    ]
    with pytest.raises(SupervisorPlanError, match="not found"):
        _dependency_order(["missing"], {})
    assert _scoped_definition(replace(identity, client_id=None), "acme").client_id == "acme"
    with pytest.raises(SupervisorPlanError, match="outside"):
        _scoped_definition(replace(identity, client_id="beta"), "acme")

    assert _bounded_payload({"note": "token=secret"})["note"] == "token=[redacted]"
    with pytest.raises(SupervisorPlanError, match="at most 16"):
        _bounded_payload({str(index): index for index in range(17)})
    with pytest.raises(SupervisorPlanError, match="field names"):
        _bounded_payload({"": "value"})
    with pytest.raises(SupervisorPlanError, match="JSON-compatible"):
        _bounded_payload({"value": object()})
    with pytest.raises(SupervisorPlanError, match="at most 16000"):
        _bounded_payload({"value": "x" * 16_001})

    assert _bounded_final_result("not-an-object") == {}
    assert _bounded_final_result({"summary": "ok"}) == {"summary": "ok"}
    assert _bounded_final_result({"value": object()}) == {"truncated": True}
    assert _bounded_final_result({"value": "x" * 8_001}) == {"truncated": True}
    with pytest.raises(SupervisorPlanError, match="identifier"):
        _identifier("not valid", "agent_id")
    with pytest.raises(SupervisorPlanError, match="non-empty"):
        _text("", "task", 10)
    with pytest.raises(SupervisorPlanError, match="control"):
        _text("bad\nvalue", "task", 10)
