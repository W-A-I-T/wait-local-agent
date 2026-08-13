from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest
from fastapi.testclient import TestClient

from wait_local_agent.api.app import create_app
from wait_local_agent.models import WorkflowRun, WorkflowTemplate
from wait_local_agent.msp_playbooks import (
    _json_object,
    compare_tenant_playbook_revisions,
    create_tenant_msp_playbook,
    get_msp_playbook,
    list_msp_playbooks,
    playbook_definition_payload,
    preview_msp_playbook,
    run_msp_playbook,
    tenant_playbook_revision_view,
    update_tenant_msp_playbook,
)
from wait_local_agent.smart_actions import SmartActionService
from wait_local_agent.store import Store
from wait_local_agent.workflows import run_workflow_template, validate_workflow_input


def _seed_client_ticket(store: Store) -> None:
    store.ingest_ticket_file(Path("examples/sample_tickets/tickets.json"))
    with store._connect() as connection:  # noqa: SLF001
        connection.execute("update tickets set client_id = ?", ("acme",))


def _steps(result: dict[str, object]) -> list[dict[str, object]]:
    return cast(list[dict[str, object]], result["steps"])


def test_msp_playbook_catalog_is_versioned_and_structured() -> None:
    playbooks = list_msp_playbooks()

    assert len(playbooks) >= 10
    assert all(playbook.version == 1 for playbook in playbooks)
    assert all(playbook.steps for playbook in playbooks)
    assert get_msp_playbook("ticket-intake-review") is not None
    assert get_msp_playbook("missing") is None


def test_tenant_playbook_lifecycle_is_scoped_versioned_and_disabled_by_default(settings) -> None:
    store = Store(settings.data_path)
    _seed_client_ticket(store)
    source = get_msp_playbook("ticket-intake-review")
    assert source is not None

    created = create_tenant_msp_playbook(
        store,
        client_id="acme",
        source_playbook_id=source.id,
        name="Acme intake policy",
        trigger=source.trigger,
        description="Tenant-owned intake composition.",
        risk_level=source.risk_level,
        definition=playbook_definition_payload(source),
    )
    entry_id = str(created["id"])
    assert created["enabled"] is False
    assert created["version"] == 1
    assert store.get_msp_playbook_entry(entry_id, "other") is None

    with pytest.raises(KeyError):
        preview_msp_playbook(store, entry_id, ticket_id="TCK-1001", client_id="acme")
    with pytest.raises(KeyError):
        preview_msp_playbook(store, entry_id, ticket_id="TCK-1001")

    updated = update_tenant_msp_playbook(
        store,
        entry_id,
        client_id="acme",
        name="Acme intake policy v2",
        enabled=True,
    )
    assert updated["enabled"] is True
    assert updated["version"] == 2
    preview = preview_msp_playbook(store, entry_id, ticket_id="TCK-1001", client_id="acme")
    preview_playbook = cast(dict[str, object], preview["playbook"])
    assert preview_playbook["id"] == entry_id
    assert preview_playbook["version"] == 2

    revisions = store.list_msp_playbook_revisions(entry_id, "acme")
    assert [revision.version for revision in revisions] == [2, 1]
    assert tenant_playbook_revision_view(revisions[0])["version"] == 2
    diff = compare_tenant_playbook_revisions(revisions[1], revisions[0])
    assert diff["left_version"] == 1
    assert any(change["field"] == "name" for change in cast(list[dict[str, object]], diff["changes"]))

    restored = store.restore_msp_playbook_revision(entry_id, 1, "acme")
    assert restored.version == 3
    assert restored.enabled is False
    assert restored.name == "Acme intake policy"
    assert len(store.list_msp_playbook_revisions(entry_id, "acme")) == 3


def test_enabled_tenant_playbook_runs_through_existing_executor(settings) -> None:
    store = Store(settings.data_path)
    _seed_client_ticket(store)
    source = get_msp_playbook("ticket-intake-review")
    assert source is not None
    created = create_tenant_msp_playbook(
        store,
        client_id="acme",
        source_playbook_id=source.id,
        name="Acme executable intake",
        trigger=source.trigger,
        description="Tenant-owned executable intake.",
        risk_level=source.risk_level,
        definition=playbook_definition_payload(source),
        enabled=True,
    )
    runs: list[WorkflowRun] = []
    result = run_msp_playbook(
        store,
        str(created["id"]),
        ticket_id="TCK-1001",
        client_id="acme",
        tool_executor=SmartActionService(store, settings),
        on_workflow_run=runs.append,
    )
    assert result["status"] == "completed"
    assert len(runs) == 6


def test_tenant_playbook_definition_validation_is_fail_closed(settings) -> None:
    store = Store(settings.data_path)
    source = get_msp_playbook("ticket-intake-review")
    assert source is not None
    valid = playbook_definition_payload(source)
    valid_steps = cast(list[dict[str, object]], valid["steps"])
    first_step = dict(valid_steps[0])

    invalid_definitions = [
        ({**valid, "format": "wrong"}, "format must be"),
        ({**valid, "format_version": 2}, "format_version"),
        ({**valid, "steps": []}, "at least one step"),
        ({**valid, "steps": valid_steps * 5}, "at most 24 steps"),
        ({**valid, "steps": ["not-an-object"]}, "steps must be objects"),
        (
            {
                **valid,
                "steps": [
                    dict(first_step),
                    dict(first_step),
                ],
            },
            "duplicated",
        ),
    ]
    invalid_definitions.extend(
        [
            ({**valid, "steps": [{**first_step, "kind": "shell"}]}, "kind is unsupported"),
            ({**valid, "steps": [{**first_step, "required_inputs": [""]}]}, "required_inputs"),
            ({**valid, "steps": [{**first_step, "required_inputs": ["x"] * 17}]}, "too many required"),
            (
                {
                    **valid,
                    "steps": [{**first_step, "kind": "report", "report_type": "missing"}],
                },
                "unsupported report type",
            ),
            ({**valid, "output_evidence": "not-a-list"}, "output_evidence is invalid"),
            ({**valid, "output_evidence": ["x"] * 25}, "at most 24 labels"),
            ({**valid, "local_fixture": "yes"}, "local_fixture must be boolean"),
            (
                {
                    **valid,
                    "steps": [{**first_step, "kind": "report", "report_type": "qbr"}],
                },
                "__valid_report__",
            ),
            ({**valid, "steps": [{**first_step, "id": ""}]}, "step id is required"),
            ({**valid, "steps": [{**first_step, "id": "x" * 81}]}, "step id is too long"),
        ]
    )
    for definition, message in invalid_definitions:
        if message == "__valid_report__":
            create_tenant_msp_playbook(
                store,
                client_id="acme",
                name="Valid report",
                trigger="manual",
                description="Accepted report definition.",
                risk_level="low",
                definition=cast(dict[str, object], definition),
            )
            continue
        with pytest.raises(ValueError, match=message):
            create_tenant_msp_playbook(
                store,
                client_id="acme",
                name="Invalid",
                trigger="manual",
                description="Rejected definition.",
                risk_level="low",
                definition=cast(dict[str, object], definition),
            )

    with pytest.raises(ValueError, match="source_playbook_id"):
        create_tenant_msp_playbook(
            store,
            client_id="acme",
            source_playbook_id="unknown",
            name="Invalid source",
            trigger="manual",
            description="Rejected source.",
            risk_level="low",
            definition=valid,
        )
    with pytest.raises(ValueError, match="risk_level"):
        create_tenant_msp_playbook(
            store,
            client_id="acme",
            name="Invalid risk",
            trigger="manual",
            description="Rejected risk.",
            risk_level="critical",
            definition=valid,
        )
    with pytest.raises(ValueError, match="stored MSP playbook definition is invalid"):
        _json_object("not-json")
    with pytest.raises(ValueError, match="must be an object"):
        _json_object("[]")


def test_tenant_playbook_definition_rejects_unknown_execution_targets(settings) -> None:
    store = Store(settings.data_path)
    with pytest.raises(ValueError, match="unknown workflow template"):
        create_tenant_msp_playbook(
            store,
            client_id="acme",
            name="Unsafe",
            trigger="manual",
            description="Should not persist.",
            risk_level="high",
            definition={
                "format": "wait-local-agent.msp-playbook-definition",
                "format_version": 1,
                "steps": [
                    {
                        "id": "shell",
                        "name": "Shell",
                        "kind": "workflow",
                        "description": "Not an allowed target.",
                        "workflow_template_id": "arbitrary-shell",
                    }
                ],
                "output_evidence": [],
                "local_fixture": True,
            },
        )
    assert store.list_msp_playbook_entries("acme") == []


def test_preview_is_dry_run_and_exposes_ordered_approval_boundaries(settings) -> None:
    store = Store(settings.data_path)
    _seed_client_ticket(store)

    result = preview_msp_playbook(
        store,
        "security-response-review",
        ticket_id="TCK-1001",
        client_id="acme",
    )

    assert result["execution_started"] is False
    assert result["execution_mode"] == "preview"
    steps = _steps(result)
    assert [step["id"] for step in steps] == ["assessment", "alert"]
    assert steps[0]["approval_required"] is False
    assert steps[1]["approval_required"] is True
    assert store.list_workflow_runs() == []
    assert not [event for event in store.list_audit_events() if event.event_type.startswith("msp.playbook.")]


def test_playbook_run_stops_at_first_approval_and_records_audit(settings) -> None:
    store = Store(settings.data_path)
    _seed_client_ticket(store)
    smart_actions = SmartActionService(store, settings)

    result = run_msp_playbook(
        store,
        "security-response-review",
        ticket_id="TCK-1001",
        client_id="acme",
        actor="technician",
        tool_executor=smart_actions,
        smart_action_service=smart_actions,
    )

    assert result["execution_started"] is True
    assert result["status"] == "pending_approval"
    assert result["stopped_after_step"] == "alert"
    steps = _steps(result)
    assert [step["id"] for step in steps] == ["assessment", "alert"]
    assert steps[1]["approval_request_id"] is not None
    assert len(store.list_workflow_runs(client_id="acme")) == 2
    event_types = [event.event_type for event in store.list_audit_events(client_id="acme")]
    assert "msp.playbook.started" in event_types
    assert "msp.playbook.stopped" in event_types


def test_playbook_run_composes_local_reviews(settings) -> None:
    store = Store(settings.data_path)
    _seed_client_ticket(store)
    smart_actions = SmartActionService(store, settings)

    result = run_msp_playbook(
        store,
        "ticket-intake-review",
        ticket_id="TCK-1001",
        client_id="acme",
        tool_executor=smart_actions,
        smart_action_service=smart_actions,
    )

    assert result["status"] == "completed"
    assert result["stopped_after_step"] is None
    steps = _steps(result)
    assert len(steps) == 6
    assert all(step["status"] == "completed" for step in steps)
    assert all(step["workflow_run_id"] is not None for step in steps)


@pytest.mark.parametrize(
    ("playbook_id", "payload", "ticket_id"),
    [
        ("resolution-review", {}, "TCK-1001"),
        ("dispatch-review", {}, "TCK-1001"),
        (
            "stale-sla-review",
            {"stale_after_minutes": 60, "thresholds_minutes": {"high": 120}},
            "TCK-1001",
        ),
        (
            "m365-onboarding-review",
            {
                "user_principal_name": "new.user@example.com",
                "display_name": "New User",
                "mail_nickname": "new.user",
                "temporary_vault_name": "m365-temp-new-user",
                "user_id": "user-1",
                "sku_ids": ["sku-1"],
                "operation": "add",
            },
            "TCK-1001",
        ),
        (
            "m365-offboarding-review",
            {"user_identity": "new.user@example.com", "user_id": "user-1"},
            "TCK-1001",
        ),
        (
            "automation-opportunity-review",
            {"period_start": "2026-01-01", "period_end": "2026-03-31"},
            None,
        ),
        (
            "recurring-service-review",
            {"period_start": "2026-01-01", "period_end": "2026-03-31", "follow_up_after_days": 21},
            None,
        ),
    ],
)
def test_all_built_in_playbooks_preview_with_explicit_inputs(
    settings, playbook_id: str, payload: dict[str, object], ticket_id: str | None
) -> None:
    store = Store(settings.data_path)
    _seed_client_ticket(store)

    result = preview_msp_playbook(
        store,
        playbook_id,
        ticket_id=ticket_id,
        client_id="acme",
        input_payload=payload,
    )

    assert result["execution_started"] is False
    assert all(step["status"] == "planned" for step in _steps(result))
    assert all("required_inputs" in step for step in _steps(result))


def test_report_and_payload_validation_boundaries(settings) -> None:
    store = Store(settings.data_path)
    _seed_client_ticket(store)

    with pytest.raises(ValueError, match="ISO dates"):
        preview_msp_playbook(
            store,
            "qbr-review",
            client_id="acme",
            input_payload={"period_start": "not-a-date", "period_end": "2026-03-31"},
        )
    with pytest.raises(ValueError, match="not be after"):
        preview_msp_playbook(
            store,
            "qbr-review",
            client_id="acme",
            input_payload={"period_start": "2026-04-01", "period_end": "2026-03-31"},
        )
    with pytest.raises(ValueError, match="follow_up_after_days"):
        preview_msp_playbook(
            store,
            "recurring-service-review",
            client_id="acme",
            input_payload={
                "period_start": "2026-01-01",
                "period_end": "2026-03-31",
                "follow_up_after_days": 0,
            },
        )
    with pytest.raises(ValueError, match="JSON-compatible"):
        preview_msp_playbook(
            store,
            "qbr-review",
            client_id="acme",
            input_payload={"value": object()},
        )
    with pytest.raises(ValueError, match="at most"):
        preview_msp_playbook(
            store,
            "qbr-review",
            client_id="acme",
            input_payload={"value": "x" * 12_001},
        )
    with pytest.raises(KeyError):
        preview_msp_playbook(store, "missing", client_id="acme")
    with pytest.raises(KeyError):
        validate_workflow_input("missing")
    with pytest.raises(ValueError, match="follow_up_after_days"):
        validate_workflow_input(
            "recurring-service-review",
            {
                "period_start": "2026-01-01",
                "period_end": "2026-03-31",
                "follow_up_after_days": 0,
            },
        )


def test_workflow_message_has_bounded_fallback_for_custom_read_only_template(settings) -> None:
    store = Store(settings.data_path)
    _seed_client_ticket(store)
    template = WorkflowTemplate(
        id="custom-read-only",
        name="Custom Read Only",
        trigger="manual",
        description="test-only read-only template",
        action_type="ticket.triage",
        approval_required=False,
        risk_level="low",
        preview_fields=("ticket_id",),
        tool_id=None,
    )

    result = run_workflow_template(
        store,
        "custom-read-only",
        "TCK-1001",
        client_id="acme",
        template_override=template,
    )

    assert "documentation-assisted response" in result.message
    with pytest.raises(ValueError, match="requires ticket_id"):
        preview_msp_playbook(store, "ticket-intake-review", client_id="acme")
    with pytest.raises(ValueError, match="require client_id"):
        preview_msp_playbook(
            store,
            "qbr-review",
            input_payload={"period_start": "2026-01-01", "period_end": "2026-03-31"},
        )


@pytest.mark.parametrize("playbook_id", ["automation-opportunity-review", "recurring-service-review"])
def test_report_playbook_variants_execute(settings, playbook_id: str) -> None:
    store = Store(settings.data_path)
    _seed_client_ticket(store)
    smart_actions = SmartActionService(store, settings)

    result = run_msp_playbook(
        store,
        playbook_id,
        client_id="acme",
        input_payload={
            "period_start": "2026-01-01",
            "period_end": "2026-03-31",
            "follow_up_after_days": 21,
        },
        actor="technician",
        smart_action_service=smart_actions,
    )

    assert result["status"] == "completed"
    assert _steps(result)[0]["report_id"]


def test_report_playbook_persists_local_evidence_report(settings) -> None:
    store = Store(settings.data_path)
    _seed_client_ticket(store)
    smart_actions = SmartActionService(store, settings)

    result = run_msp_playbook(
        store,
        "qbr-review",
        client_id="acme",
        input_payload={"period_start": "2026-01-01", "period_end": "2026-03-31"},
        smart_action_service=smart_actions,
    )

    assert result["status"] == "completed"
    step = _steps(result)[0]
    assert step["report_id"]
    report = store.get_report(str(step["report_id"]))
    assert report is not None
    assert report.client_id == "acme"
    assert report.metadata["evidence_status"] in {"no_evidence", "partial", "completed"}

    without_action_service = run_msp_playbook(
        store,
        "qbr-review",
        client_id="acme",
        input_payload={"period_start": "2026-01-01", "period_end": "2026-03-31"},
    )
    assert without_action_service["status"] == "completed"


def test_playbook_rejects_cross_tenant_and_invalid_inputs(settings) -> None:
    store = Store(settings.data_path)
    _seed_client_ticket(store)

    with pytest.raises(LookupError):
        preview_msp_playbook(store, "ticket-intake-review", ticket_id="TCK-1001", client_id="other")
    with pytest.raises(ValueError, match="requires period_start"):
        preview_msp_playbook(store, "qbr-review", client_id="acme")
    with pytest.raises(ValueError, match="at most"):
        preview_msp_playbook(
            store,
            "ticket-intake-review",
            ticket_id="TCK-1001",
            client_id="acme",
            input_payload={str(index): index for index in range(25)},
        )


def test_failed_playbook_result_is_bounded_and_redacted(settings) -> None:
    store = Store(settings.data_path)
    _seed_client_ticket(store)

    class BrokenExecutor:
        def invoke(self, action_id, payload, actor, *, confirm=False, client_id=None):
            raise RuntimeError("provider access_token=super-secret")

    result = run_msp_playbook(
        store,
        "ticket-intake-review",
        ticket_id="TCK-1001",
        client_id="acme",
        tool_executor=BrokenExecutor(),
    )

    assert result["status"] == "failed"
    assert "super-secret" not in json.dumps(result)
    assert "[redacted]" in json.dumps(result)


def test_api_exposes_playbook_catalog_preview_and_run(settings) -> None:
    store = Store(settings.data_path)
    _seed_client_ticket(store)
    client = TestClient(create_app(settings))

    catalog = client.get("/msp/playbooks")
    assert catalog.status_code == 200
    assert any(item["id"] == "ticket-intake-review" for item in catalog.json())

    preview = client.post(
        "/msp/playbooks/security-response-review/preview",
        json={"ticket_id": "TCK-1001", "client_id": "acme"},
    )
    assert preview.status_code == 200
    assert preview.json()["execution_started"] is False

    run = client.post(
        "/msp/playbooks/security-response-review/runs",
        json={"ticket_id": "TCK-1001", "client_id": "acme"},
    )
    assert run.status_code == 200
    assert run.json()["status"] == "pending_approval"

    assert client.post("/msp/playbooks/missing/preview", json={"client_id": "acme"}).status_code == 404
    assert client.post("/msp/playbooks/missing/runs", json={"client_id": "acme"}).status_code == 404
    assert (
        client.post(
            "/msp/playbooks/qbr-review/preview",
            json={"client_id": "acme", "payload": {"period_start": "bad"}},
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/msp/playbooks/qbr-review/runs",
            json={"client_id": "acme", "payload": {"period_start": "bad"}},
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/msp/playbooks/security-response-review/preview",
            json={"ticket_id": "missing", "client_id": "acme"},
        ).status_code
        == 404
    )
    assert (
        client.post(
            "/msp/playbooks/security-response-review/runs",
            json={"ticket_id": "missing", "client_id": "acme"},
        ).status_code
        == 404
    )

    secure = settings.__class__(
        **{
            **settings.__dict__,
            "demo_mode": False,
            "client_id": "",
            "tech_token": "tech-token",
            "viewer_token": "viewer-token",
        }
    )
    secure_client = TestClient(create_app(secure))
    headers = {"Authorization": "Bearer tech-token"}
    assert secure_client.post("/msp/playbooks/qbr-review/preview", headers=headers, json={}).status_code == 403
    assert secure_client.post("/msp/playbooks/qbr-review/runs", headers=headers, json={}).status_code == 403


def test_api_exposes_tenant_playbook_lifecycle_and_scope(settings) -> None:
    store = Store(settings.data_path)
    _seed_client_ticket(store)
    client = TestClient(create_app(settings))
    source = get_msp_playbook("ticket-intake-review")
    assert source is not None
    definition = playbook_definition_payload(source)

    created = client.post(
        "/msp/playbooks/custom",
        json={
            "source_playbook_id": source.id,
            "name": "Acme custom intake",
            "trigger": source.trigger,
            "description": "A tenant-owned intake policy.",
            "risk_level": source.risk_level,
            "definition": definition,
            "client_id": "acme",
        },
    )
    assert created.status_code == 201, created.text
    entry_id = created.json()["id"]
    assert created.json()["enabled"] is False

    catalog = client.get("/msp/playbooks", params={"client_id": "acme"})
    assert any(item["id"] == entry_id for item in catalog.json())
    assert client.get(f"/msp/playbooks/custom/{entry_id}").status_code == 200
    assert (
        client.post(
            f"/msp/playbooks/{entry_id}/preview",
            json={"ticket_id": "TCK-1001", "client_id": "acme"},
        ).status_code
        == 404
    )

    enabled = client.patch(
        f"/msp/playbooks/custom/{entry_id}",
        json={"enabled": True, "client_id": "acme"},
    )
    assert enabled.status_code == 200, enabled.text
    preview = client.post(
        f"/msp/playbooks/{entry_id}/preview",
        json={"ticket_id": "TCK-1001", "client_id": "acme"},
    )
    assert preview.status_code == 200, preview.text

    revisions = client.get(f"/msp/playbooks/custom/{entry_id}/revisions", params={"client_id": "acme"})
    assert revisions.status_code == 200
    assert [revision["version"] for revision in revisions.json()] == [2, 1]
    diff = client.get(
        f"/msp/playbooks/custom/{entry_id}/revisions/1/diff/2",
        params={"client_id": "acme"},
    )
    assert diff.status_code == 200
    assert diff.json()["left_version"] == 1
    restored = client.post(
        f"/msp/playbooks/custom/{entry_id}/revisions/1/restore",
        json={"client_id": "acme"},
    )
    assert restored.status_code == 200
    assert restored.json()["version"] == 3

    other = client.get(f"/msp/playbooks/custom/{entry_id}", params={"client_id": "other"})
    assert other.status_code == 404
