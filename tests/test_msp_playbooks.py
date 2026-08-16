from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from fastapi.testclient import TestClient

import wait_local_agent.api.app as api_app_module
import wait_local_agent.msp_playbooks as msp_playbooks_module
from tests.support import ingest_local
from wait_local_agent.api.app import create_app
from wait_local_agent.models import WorkflowTemplate
from wait_local_agent.msp_playbooks import (
    MspPlaybookDefinition,
    MspPlaybookStep,
    create_msp_playbook_subscription,
    get_msp_playbook,
    list_msp_playbooks,
    preview_msp_playbook,
    publish_msp_playbook,
    run_msp_playbook,
    update_msp_playbook_subscription,
)
from wait_local_agent.smart_actions import SmartActionService
from wait_local_agent.store import Store
from wait_local_agent.workflows import run_workflow_template, validate_workflow_input


def _seed_client_ticket(store: Store) -> None:
    ingest_local(store, Path("examples/sample_tickets/tickets.json"))
    with store._connect() as connection:  # noqa: SLF001
        connection.execute("update tickets set client_id = ?", ("acme",))


def _steps(result: dict[str, object]) -> list[dict[str, object]]:
    return cast(list[dict[str, object]], result["steps"])


def test_msp_playbook_catalog_is_versioned_and_structured() -> None:
    playbooks = list_msp_playbooks()

    assert len(playbooks) >= 14
    assert all(playbook.version == 1 for playbook in playbooks)
    assert all(playbook.steps for playbook in playbooks)
    assert {
        "inactive-ticket-follow-up-review",
        "m365-password-reset-review",
        "m365-authentication-method-review",
        "m365-license-review",
        "m365-compliance-review",
        "m365-inactive-license-review",
        "software-inventory-review",
    }.issubset({playbook.id for playbook in playbooks})
    assert get_msp_playbook("ticket-intake-review") is not None
    assert get_msp_playbook("missing") is None


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


def test_software_inventory_playbook_reuses_scoped_n_sight_action(settings) -> None:
    store = Store(settings.data_path)
    _seed_client_ticket(store)
    smart_actions = SmartActionService(
        store,
        settings,
        rmm_provider=SimpleNamespace(
            adapter_id="n-sight",
            list_software=lambda device_id, client_id: [
                {"software_id": "sw-1", "name": "Example Agent", "version": "1.0"}
            ],
        ),
    )

    result = run_msp_playbook(
        store,
        "software-inventory-review",
        ticket_id="TCK-1001",
        client_id="acme",
        actor="technician",
        input_payload={"device_id": "server:1"},
        tool_executor=smart_actions,
        smart_action_service=smart_actions,
    )

    assert result["status"] == "completed"
    assert _steps(result)[0]["status"] == "completed"
    assert store.list_smart_action_runs()[0].status == "success"


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
            "inactive-ticket-follow-up-review",
            {"stale_after_minutes": 60, "channel": "ticket_note"},
            "TCK-1001",
        ),
        (
            "m365-password-reset-review",
            {"user_identity": "new.user@example.com", "temporary_vault_name": "m365-temp-new-user"},
            "TCK-1001",
        ),
        (
            "m365-authentication-method-review",
            {
                "user_identity": "new.user@example.com",
                "method_type": "microsoft_authenticator",
                "method_id": "method-1",
            },
            "TCK-1001",
        ),
        (
            "m365-license-review",
            {"user_id": "user-1", "sku_ids": ["sku-1"], "operation": "add"},
            "TCK-1001",
        ),
        ("m365-compliance-review", {"limit": 10}, "TCK-1001"),
        ("m365-inactive-license-review", {"limit": 10}, "TCK-1001"),
        ("software-inventory-review", {"device_id": "server:1"}, "TCK-1001"),
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


@pytest.mark.parametrize(
    ("playbook_id", "payload", "expected_status"),
    [
        (
            "inactive-ticket-follow-up-review",
            {"stale_after_minutes": 60, "channel": "ticket_note"},
            "pending_approval",
        ),
        (
            "m365-password-reset-review",
            {"user_identity": "new.user@example.com", "temporary_vault_name": "m365-temp-new-user"},
            "failed",
        ),
        (
            "m365-authentication-method-review",
            {
                "user_identity": "new.user@example.com",
                "method_type": "microsoft_authenticator",
                "method_id": "method-1",
            },
            "failed",
        ),
        (
            "m365-license-review",
            {"user_id": "user-1", "sku_ids": ["sku-1"], "operation": "add"},
            "failed",
        ),
    ],
)
def test_new_msp_playbooks_stop_at_existing_approval_boundary(
    settings, playbook_id: str, payload: dict[str, object], expected_status: str
) -> None:
    store = Store(settings.data_path)
    _seed_client_ticket(store)
    smart_actions = SmartActionService(store, settings)

    result = run_msp_playbook(
        store,
        playbook_id,
        ticket_id="TCK-1001",
        client_id="acme",
        actor="technician",
        input_payload=payload,
        tool_executor=smart_actions,
        smart_action_service=smart_actions,
    )

    assert result["status"] == expected_status
    assert result["stopped_after_step"] == _steps(result)[-1]["id"]
    if expected_status == "pending_approval":
        assert _steps(result)[-1]["approval_request_id"] is not None
    else:
        assert _steps(result)[-1]["status"] == "failed"
        assert _steps(result)[-1]["message"]
    assert all(step["status"] in {"completed", "pending_approval", "failed"} for step in _steps(result))


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


def test_event_subscription_requires_matching_workflow_trigger_and_bounded_mapping(settings) -> None:
    store = Store(settings.data_path)
    _seed_client_ticket(store)

    subscription = create_msp_playbook_subscription(
        store,
        "ticket-intake-review",
        event_type="ticket.created",
        client_id="acme",
        input_mapping={"priority": "priority"},
    )

    assert subscription.client_id == "acme"
    assert subscription.enabled is True
    assert json.loads(subscription.input_mapping_json) == {"priority": "priority"}
    with pytest.raises(ValueError, match="match the playbook trigger"):
        create_msp_playbook_subscription(
            store,
            "ticket-intake-review",
            event_type="ticket.updated",
            client_id="acme",
        )
    with pytest.raises(ValueError, match="event_type is not supported"):
        create_msp_playbook_subscription(
            store,
            "qbr-review",
            event_type="schedule.monthly",
            client_id="acme",
        )
    with pytest.raises(ValueError, match="at most"):
        create_msp_playbook_subscription(
            store,
            "ticket-intake-review",
            event_type="ticket.created",
            client_id="acme",
            input_mapping={str(index): "priority" for index in range(17)},
        )
    with pytest.raises(ValueError, match="keys and values"):
        create_msp_playbook_subscription(
            store,
            "ticket-intake-review",
            event_type="ticket.created",
            client_id="acme",
            input_mapping={"priority": 1},
        )
    with pytest.raises(ValueError, match="duplicate targets"):
        create_msp_playbook_subscription(
            store,
            "ticket-intake-review",
            event_type="ticket.created",
            client_id="acme",
            input_mapping={"priority": "priority", " priority ": "severity"},
        )


def test_event_subscription_rejects_report_steps(monkeypatch, settings) -> None:
    fake = MspPlaybookDefinition(
        id="report-event",
        name="Report event",
        version=1,
        trigger="ticket.created",
        description="fixture",
        risk_level="low",
        steps=(
            MspPlaybookStep(
                id="report",
                name="Report",
                kind="report",
                description="report",
                report_type="qbr",
            ),
        ),
        output_evidence=(),
    )
    monkeypatch.setattr(msp_playbooks_module, "resolve_msp_playbook", lambda *args, **kwargs: fake)
    with pytest.raises(ValueError, match="workflow playbooks only"):
        create_msp_playbook_subscription(
            Store(settings.data_path),
            "report-event",
            event_type="ticket.created",
            client_id="acme",
        )


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
    assert (
        client.post(
            "/msp/playbooks/security-response-review/runs",
            json={"client_id": "acme"},
        ).status_code
        == 422
    )

    secure = settings.__class__(
        **{
            **settings.__dict__,
            "demo_mode": False,
            "client_id": "",
            "admin_token": "admin-token",
            "tech_token": "tech-token",
            "viewer_token": "viewer-token",
        }
    )
    secure_client = TestClient(create_app(secure))
    headers = {"Authorization": "Bearer tech-token"}
    assert secure_client.post("/msp/playbooks/qbr-review/preview", headers=headers, json={}).status_code == 403
    assert secure_client.post("/msp/playbooks/qbr-review/runs", headers=headers, json={}).status_code == 403


def test_api_maps_playbook_runner_value_error(monkeypatch, settings) -> None:
    def raise_value_error(*args: object, **kwargs: object) -> dict[str, object]:
        raise ValueError("invalid playbook input")

    monkeypatch.setattr(api_app_module, "run_msp_playbook", raise_value_error)
    client = TestClient(create_app(settings))

    response = client.post(
        "/msp/playbooks/ticket-intake-review/runs",
        json={"ticket_id": "TCK-1001", "client_id": "acme"},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "invalid playbook input"


def test_api_exposes_tenant_scoped_playbook_subscriptions(settings) -> None:
    store = Store(settings.data_path)
    _seed_client_ticket(store)
    client = TestClient(create_app(settings))

    created = client.post(
        "/msp/playbook-subscriptions",
        json={
            "playbook_id": "ticket-intake-review",
            "event_type": "ticket.created",
            "client_id": "acme",
            "input_mapping": {"priority": "priority"},
        },
    )
    assert created.status_code == 201, created.text
    subscription = created.json()
    assert subscription["client_id"] == "acme"
    assert subscription["input_mapping"] == {"priority": "priority"}

    listed = client.get("/msp/playbook-subscriptions")
    assert listed.status_code == 200
    assert listed.json() == [subscription]

    detail = client.get(f"/msp/playbook-subscriptions/{subscription['id']}")
    assert detail.status_code == 200
    assert detail.json() == subscription

    updated = client.patch(
        f"/msp/playbook-subscriptions/{subscription['id']}",
        json={"input_mapping": {"priority": "priority"}, "enabled": True},
    )
    assert updated.status_code == 200
    assert updated.json()["enabled"] is True

    enabled = client.post(f"/msp/playbook-subscriptions/{subscription['id']}/enable")
    assert enabled.status_code == 200
    assert enabled.json()["enabled"] is True

    disabled = client.post(f"/msp/playbook-subscriptions/{subscription['id']}/disable")
    assert disabled.status_code == 200
    assert disabled.json()["enabled"] is False

    enabled = client.post(f"/msp/playbook-subscriptions/{subscription['id']}/enable")
    assert enabled.status_code == 200
    assert enabled.json()["enabled"] is True

    assert client.get("/msp/playbook-subscriptions/missing").status_code == 404
    assert client.post("/msp/playbook-subscriptions/missing/disable").status_code == 404

    invalid = client.post(
        "/msp/playbook-subscriptions",
        json={
            "playbook_id": "ticket-intake-review",
            "event_type": "ticket.updated",
            "client_id": "acme",
        },
    )
    assert invalid.status_code == 422
    missing_playbook = client.post(
        "/msp/playbook-subscriptions",
        json={
            "playbook_id": "missing",
            "event_type": "ticket.created",
            "client_id": "acme",
        },
    )
    assert missing_playbook.status_code == 404
    assert client.get("/msp/playbook-subscriptions/missing").status_code == 404
    disabled_entry = publish_msp_playbook(
        store,
        "ticket-intake-review",
        provenance="coverage",
        client_id="acme",
        enabled=False,
    )
    blocked_run = client.post(
        f"/msp/playbooks/{disabled_entry.id}/runs",
        json={"ticket_id": "TCK-1001", "client_id": "acme"},
    )
    assert blocked_run.status_code == 409
    with pytest.raises(KeyError):
        update_msp_playbook_subscription(store, "missing", client_id="acme", enabled=True)

    secure = settings.__class__(
        **{
            **settings.__dict__,
            "demo_mode": False,
            "client_id": "",
            "tech_token": "tech-token",
            "viewer_token": "viewer-token",
            "admin_token": "admin-token",
        }
    )
    store = Store(secure.data_path)
    store.create_principal("globex-viewer", kind="staff")
    store.add_principal_credential("globex-viewer", "globex-viewer-token")
    store.add_principal_client_role("globex-viewer", "globex", "viewer")
    store.create_principal("globex-technician", kind="staff")
    store.add_principal_credential("globex-technician", "globex-technician-token")
    store.add_principal_client_role("globex-technician", "globex", "technician")
    secure_client = TestClient(create_app(secure))
    viewer_headers = {"Authorization": "Bearer globex-viewer-token"}
    tech_headers = {"Authorization": "Bearer globex-technician-token"}
    admin_headers = {"Authorization": "Bearer admin-token"}
    assert secure_client.get("/msp/playbook-subscriptions", headers=viewer_headers).json() == []
    assert secure_client.get("/msp/playbook-subscriptions/missing", headers=viewer_headers).status_code == 404
    assert secure_client.post(
        "/msp/playbook-subscriptions",
        headers=tech_headers,
        json={"playbook_id": "ticket-intake-review", "event_type": "ticket.created", "client_id": "acme"},
    ).status_code == 403
    assert secure_client.patch(
        "/msp/playbook-subscriptions/missing",
        headers=tech_headers,
        json={"enabled": True},
    ).status_code == 404
    assert secure_client.patch(
        "/msp/playbook-subscriptions/missing",
        headers=admin_headers,
        json={"enabled": True},
    ).status_code == 404
