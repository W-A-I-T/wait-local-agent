from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from tests.api_helpers import _auth
from tests.support import ensure_test_clients, ingest_local
from wait_local_agent.api.app import create_app
from wait_local_agent.api.schemas import ScheduledJobCreateRequest
from wait_local_agent.rbac import AuthContext, Role
from wait_local_agent.store import Store


def test_scheduled_job_inherits_ticket_client_id_when_request_omits_it(settings) -> None:
    secure_settings = settings.__class__(
        **{
            **settings.__dict__,
            "demo_mode": False,
            "scheduler_enabled": True,
            "client_id": "acme",
            "admin_token": "admin-token",
            "tech_token": "tech-token",
            "viewer_token": "viewer-token",
        }
    )
    store = Store(secure_settings.data_path)
    ensure_test_clients(store, "acme", "beta")
    ingest_local(store, Path("examples/sample_tickets/tickets.json"))
    with store._connect() as connection:
        connection.execute(
            "update tickets set client_id = ? where id = ?",
            ("acme", "TCK-1001"),
        )
    client = TestClient(create_app(secure_settings))

    created = client.post(
        "/scheduled-jobs",
        headers=_auth("tech-token"),
        json={
            "template_id": "documentation-assisted-response",
            "cron": "0 9 * * *",
            "params": {"ticket_id": "TCK-1001"},
        },
    )
    filtered = client.get(
        "/scheduled-jobs",
        params={"client_id": "acme"},
        headers=_auth("viewer-token"),
    )

    assert created.status_code == 200
    assert created.json()["client_id"] == "acme"
    assert created.json()["params"]["client_id"] == "acme"
    assert [job["id"] for job in filtered.json()] == [created.json()["id"]]


def test_scheduled_report_job_is_tenant_scoped_and_validated(settings) -> None:
    secure_settings = settings.__class__(
        **{
            **settings.__dict__,
            "demo_mode": False,
            "scheduler_enabled": False,
            "client_id": "acme",
            "admin_token": "admin-token",
            "tech_token": "tech-token",
            "viewer_token": "viewer-token",
        }
    )
    app = create_app(secure_settings)
    endpoint = next(
        route.endpoint
        for route in app.routes
        if isinstance(route, APIRoute)
        and route.path == "/scheduled-jobs"
        and route.methods is not None
        and "POST" in route.methods
    )
    technician = AuthContext(
        role=Role.TECHNICIAN,
        presented_token="tech-token",
        client_id="acme",
        client_ids=frozenset({"acme"}),
    )
    created = endpoint(
        ScheduledJobCreateRequest(
            report_type="qbr",
            cron="0 9 * * *",
            params={"client_id": "acme", "period_days": 90},
        ),
        technician,
    )
    with pytest.raises(HTTPException, match="outside authenticated scope"):
        endpoint(
            ScheduledJobCreateRequest(
                report_type="qbr",
                cron="0 9 * * *",
                params={"client_id": "globex", "period_days": 90},
            ),
            technician,
        )

    with pytest.raises(HTTPException, match="period_days or period_start"):
        endpoint(
            ScheduledJobCreateRequest(report_type="qbr", cron="0 9 * * *", params={"client_id": "acme"}),
            technician,
        )
    with pytest.raises(HTTPException, match="cannot include"):
        endpoint(
            ScheduledJobCreateRequest(
                report_type="qbr",
                template_id="ticket-triage",
                cron="0 9 * * *",
                params={"client_id": "acme", "period_days": 30},
            ),
            technician,
        )

    assert created["job_kind"] == "report"
    assert created["template_id"] == "qbr"
    assert created["client_id"] == "acme"
    assert created["params"]["client_id"] == "acme"


def test_scheduled_job_inherits_ticket_client_id_when_request_has_blank_client_id(settings) -> None:
    secure_settings = settings.__class__(
        **{
            **settings.__dict__,
            "demo_mode": False,
            "scheduler_enabled": True,
            "client_id": "acme",
            "admin_token": "admin-token",
            "tech_token": "tech-token",
            "viewer_token": "viewer-token",
        }
    )
    store = Store(secure_settings.data_path)
    ensure_test_clients(store, "acme", "beta")
    ingest_local(store, Path("examples/sample_tickets/tickets.json"))
    with store._connect() as connection:
        connection.execute(
            "update tickets set client_id = ? where id = ?",
            ("acme", "TCK-1001"),
        )
    client = TestClient(create_app(secure_settings))

    blank = client.post(
        "/scheduled-jobs",
        headers=_auth("tech-token"),
        json={
            "template_id": "documentation-assisted-response",
            "cron": "0 9 * * *",
            "params": {"ticket_id": "TCK-1001", "client_id": ""},
        },
    )
    nullish = client.post(
        "/scheduled-jobs",
        headers=_auth("tech-token"),
        json={
            "template_id": "documentation-assisted-response",
            "cron": "15 9 * * *",
            "params": {"ticket_id": "TCK-1001", "client_id": None},
        },
    )
    filtered = client.get(
        "/scheduled-jobs",
        params={"client_id": "acme"},
        headers=_auth("viewer-token"),
    )

    assert blank.status_code == 200
    assert nullish.status_code == 200
    assert blank.json()["client_id"] == "acme"
    assert blank.json()["params"]["client_id"] == "acme"
    assert nullish.json()["client_id"] == "acme"
    assert nullish.json()["params"]["client_id"] == "acme"
    assert [job["id"] for job in filtered.json()] == [nullish.json()["id"], blank.json()["id"]]


def test_scheduled_job_api_validation_and_missing_jobs(settings) -> None:
    ingest_local(Store(settings.data_path), Path("examples/sample_tickets/tickets.json"))
    client = TestClient(create_app(settings))

    missing_template = client.post(
        "/scheduled-jobs",
        json={"template_id": "missing", "cron": "0 1 * * *", "params": {"ticket_id": "TCK-1002"}},
    )
    missing_ticket = client.post(
        "/scheduled-jobs",
        json={"template_id": "documentation-assisted-response", "cron": "0 1 * * *", "params": {"ticket_id": "NOPE"}},
    )
    missing_param = client.post(
        "/scheduled-jobs",
        json={"template_id": "documentation-assisted-response", "cron": "0 1 * * *", "params": {}},
    )
    pause = client.post("/scheduled-jobs/999/pause")
    resume = client.post("/scheduled-jobs/999/resume")
    reschedule = client.post("/scheduled-jobs/999/reschedule", json={"cron": "0 2 * * *"})
    delete = client.delete("/scheduled-jobs/999")

    assert missing_template.status_code == 404
    assert missing_ticket.status_code == 404
    assert missing_param.status_code == 422
    assert pause.status_code == 404
    assert resume.status_code == 404
    assert reschedule.status_code == 404
    assert delete.status_code == 404


def test_scheduled_job_routes_cover_rbac_validation_and_live_scheduler_registration(settings) -> None:
    secure_settings = settings.__class__(
        **{
            **settings.__dict__,
            "demo_mode": False,
            "scheduler_enabled": True,
            "client_id": "acme",
            "admin_token": "admin-token",
            "tech_token": "tech-token",
            "viewer_token": "viewer-token",
        }
    )
    store = Store(secure_settings.data_path)
    ingest_local(store, Path("examples/sample_tickets/tickets.json"))
    with store._connect() as connection:
        connection.execute("update tickets set client_id = 'acme'")

    app = create_app(secure_settings)

    with TestClient(app) as client:
        viewer_create = client.post(
            "/scheduled-jobs",
            headers=_auth("viewer-token"),
            json={
                "template_id": "documentation-assisted-response",
                "cron": "0 9 * * *",
                "timezone": "America/Vancouver",
                "params": {"ticket_id": "TCK-1001", "client_id": "acme"},
            },
        )
        invalid_cron = client.post(
            "/scheduled-jobs",
            headers=_auth("tech-token"),
            json={
                "template_id": "documentation-assisted-response",
                "cron": "bad cron",
                "params": {"ticket_id": "TCK-1001", "client_id": "acme"},
            },
        )
        created = client.post(
            "/scheduled-jobs",
            headers=_auth("tech-token"),
            json={
                "template_id": "documentation-assisted-response",
                "cron": "0 9 * * *",
                "timezone": "America/Vancouver",
                "params": {"ticket_id": "TCK-1001", "client_id": "acme"},
            },
        )
        listed = client.get("/scheduled-jobs", headers=_auth("viewer-token"))
        job_id = created.json()["id"]

        assert viewer_create.status_code == 403
        assert invalid_cron.status_code == 422
        assert "invalid cron expression" in invalid_cron.json()["detail"]
        assert created.status_code == 200
        assert created.json()["next_run_at"] is not None
        assert created.json()["params"]["ticket_id"] == "TCK-1001"
        assert created.json()["timezone"] == "America/Vancouver"
        assert app.state.scheduler._scheduler is not None
        job_ids = {job.id for job in app.state.scheduler._scheduler.get_jobs()}
        assert job_ids == {
            "event-delivery-retry-worker",
            "founder-scan-poll-worker",
            f"scheduled-job:{job_id}",
        }
        assert listed.status_code == 200
        assert listed.json()[0]["id"] == job_id

        interval = client.post(
            "/scheduled-jobs",
            headers=_auth("tech-token"),
            json={
                "template_id": "documentation-assisted-response",
                "schedule_type": "interval",
                "interval_seconds": 60,
                "params": {"ticket_id": "TCK-1001", "client_id": "acme"},
            },
        )
        once = client.post(
            "/scheduled-jobs",
            headers=_auth("tech-token"),
            json={
                "template_id": "documentation-assisted-response",
                "schedule_type": "once",
                "run_at": "2099-01-01T00:00:00+00:00",
                "params": {"ticket_id": "TCK-1001", "client_id": "acme"},
            },
        )
        assert interval.status_code == 200
        assert interval.json()["schedule_type"] == "interval"
        assert interval.json()["interval_seconds"] == 60
        assert once.status_code == 200
        assert once.json()["schedule_type"] == "once"
        assert once.json()["run_at"] == "2099-01-01T00:00:00+00:00"

        rescheduled = client.post(
            f"/scheduled-jobs/{job_id}/reschedule",
            headers=_auth("tech-token"),
            json={"schedule_type": "interval", "interval_seconds": 120},
        )
        assert rescheduled.status_code == 200
        assert rescheduled.json()["schedule_type"] == "interval"
        assert rescheduled.json()["interval_seconds"] == 120
        paused = client.post(f"/scheduled-jobs/{job_id}/pause", headers=_auth("tech-token"))
        resumed = client.post(f"/scheduled-jobs/{job_id}/resume", headers=_auth("tech-token"))
        rescheduled = client.post(
            f"/scheduled-jobs/{job_id}/reschedule",
            headers=_auth("tech-token"),
            json={"schedule_type": "interval", "interval_seconds": 120, "timezone": "America/Vancouver"},
        )
        invalid_reschedule = client.post(
            f"/scheduled-jobs/{job_id}/reschedule",
            headers=_auth("tech-token"),
            json={"cron": "bad cron"},
        )
        deleted = client.delete(f"/scheduled-jobs/{job_id}", headers=_auth("tech-token"))

        assert paused.status_code == 200
        assert paused.json()["paused"] is True
        assert paused.json()["next_run_at"] is None
        assert resumed.status_code == 200
        assert resumed.json()["paused"] is False
        assert resumed.json()["next_run_at"] is not None
        assert rescheduled.status_code == 200
        assert rescheduled.json()["schedule_type"] == "interval"
        assert rescheduled.json()["interval_seconds"] == 120
        assert rescheduled.json()["timezone"] == "America/Vancouver"
        assert invalid_reschedule.status_code == 422
        assert deleted.status_code == 200
        assert deleted.json()["id"] == job_id
        assert client.delete(
            f"/scheduled-jobs/{interval.json()['id']}", headers=_auth("tech-token")
        ).status_code == 200
        assert client.delete(
            f"/scheduled-jobs/{once.json()['id']}", headers=_auth("tech-token")
        ).status_code == 200
        assert sorted(job.id for job in app.state.scheduler._scheduler.get_jobs()) == [
            "event-delivery-retry-worker",
            "founder-scan-poll-worker",
        ]
        assert client.get("/scheduled-jobs", headers=_auth("viewer-token")).json() == []


def test_scheduled_playbook_route_validates_and_persists_report_target(settings) -> None:
    store = Store(settings.data_path)
    client = TestClient(create_app(settings))

    created = client.post(
        "/scheduled-jobs",
        json={
            "playbook_id": "qbr-review",
            "schedule_type": "interval",
            "interval_seconds": 3600,
            "params": {
                "client_id": "acme",
                "input": {"period_start": "2026-01-01", "period_end": "2026-01-31"},
            },
        },
    )
    listed = client.get("/scheduled-jobs")
    missing_input = client.post(
        "/scheduled-jobs",
        json={"playbook_id": "qbr-review", "params": {"client_id": "acme"}},
    )
    mixed_targets = client.post(
        "/scheduled-jobs",
        json={
            "playbook_id": "qbr-review",
            "report_type": "qbr",
            "params": {
                "client_id": "acme",
                "input": {"period_start": "2026-01-01", "period_end": "2026-01-31"},
            },
        },
    )

    assert created.status_code == 200
    assert created.json()["job_kind"] == "playbook"
    assert created.json()["playbook_id"] == "qbr-review"
    assert created.json()["template_id"] == "qbr-review"
    assert listed.json()[0]["playbook_id"] == "qbr-review"
    assert missing_input.status_code == 422
    assert mixed_targets.status_code == 422
    assert store.get_scheduled_job(created.json()["id"]) is not None


def test_scheduled_agent_route_requires_scheduled_definition_and_persists_target(settings) -> None:
    store = Store(settings.data_path)
    ingest_local(store, Path("examples/sample_tickets/tickets.json"))
    with store._connect() as connection:
        connection.execute("update tickets set client_id = ?", ("acme",))
    client = TestClient(create_app(settings))

    created = client.post(
        "/agents",
        json={
            "name": "Scheduled triage",
            "trigger": "scheduled",
            "enabled_tools": ["ticket-triage"],
            "steps": [{"tool_id": "ticket-triage", "payload": {}}],
            "max_steps": 1,
            "client_id": "acme",
        },
    )
    assert created.status_code == 200
    agent_id = created.json()["id"]

    scheduled = client.post(
        "/scheduled-jobs",
        json={
            "agent_id": agent_id,
            "entity_id": "TCK-1001",
            "cron": "0 9 * * *",
            "params": {"client_id": "acme", "input": {"instruction": "triage"}},
        },
    )
    assert scheduled.status_code == 200
    assert scheduled.json()["job_kind"] == "agent"
    assert scheduled.json()["agent_id"] == agent_id
    assert scheduled.json()["entity_id"] == "TCK-1001"

    manual = client.post(
        "/agents",
        json={
            "name": "Manual triage",
            "enabled_tools": ["ticket-triage"],
            "steps": [{"tool_id": "ticket-triage", "payload": {}}],
            "max_steps": 1,
            "client_id": "acme",
        },
    )
    assert manual.status_code == 200
    rejected = client.post(
        "/scheduled-jobs",
        json={
            "agent_id": manual.json()["id"],
            "entity_id": "TCK-1001",
            "cron": "0 9 * * *",
            "params": {"client_id": "acme"},
        },
    )
    assert rejected.status_code == 422
