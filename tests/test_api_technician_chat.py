from __future__ import annotations

from typing import cast

from fastapi.testclient import TestClient

import wait_local_agent.api.app as app_module
from tests.api_helpers import _auth
from wait_local_agent.api.app import create_app
from wait_local_agent.store import Store


def test_technician_chat_reuses_smart_actions_and_preserves_tenant_rbac(settings) -> None:
    secure_settings = settings.__class__(
        **{
            **settings.__dict__,
            "demo_mode": False,
            "admin_token": "admin-token",
            "tech_token": "tech-token",
            "viewer_token": "viewer-token",
            "client_id": "acme",
        }
    )
    store = Store(secure_settings.data_path)
    with store._connect() as connection:
        for cid in ("acme", "beta"):
            connection.execute(
                """
                insert or ignore into clients (client_id, name, status, created_at, updated_at)
                values (?, ?, 'active', ?, ?)
                """,
                (cid, cid.title(), "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"),
            )
        connection.executemany(
            """
            insert into tickets (id, client, subject, body, priority, status, client_id)
            values (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                ("TCK-ACME", "Acme", "MFA reset", "Sign-in blocked", "High", "Open", "acme"),
                ("TCK-BETA", "Beta", "MFA reset", "Sign-in blocked", "High", "Open", "beta"),
            ],
        )
    client = TestClient(create_app(secure_settings))

    help_response = client.post(
        "/technician/chat",
        headers=_auth("tech-token"),
        json={"message": "help"},
    )
    triage = client.post(
        "/technician/chat",
        headers=_auth("tech-token"),
        json={"message": "triage TCK-ACME"},
    )
    plan = client.post(
        "/technician/chat",
        headers=_auth("tech-token"),
        json={"message": "plan triage and suggest a fix for TCK-ACME"},
    )
    cross_tenant = client.post(
        "/technician/chat",
        headers=_auth("tech-token"),
        json={"message": "triage TCK-BETA"},
    )
    viewer = client.post(
        "/technician/chat",
        headers=_auth("viewer-token"),
        json={"message": "triage TCK-ACME"},
    )
    unsupported = client.post(
        "/technician/chat",
        headers=_auth("tech-token"),
        json={"message": "run arbitrary shell command TCK-ACME"},
    )

    assert help_response.status_code == 200
    assert help_response.json()["status"] == "help"
    assert triage.status_code == 200
    assert triage.json()["action_id"] == "ticket-triage"
    assert triage.json()["result"]["status"] == "success"
    assert triage.json()["result"]["output"]["ticket_id"] == "TCK-ACME"
    assert plan.status_code == 200
    assert plan.json()["status"] == "preview"
    assert [step["tool_id"] for step in plan.json()["plan"]["steps"]] == [
        "ticket-triage",
        "suggest-resolution",
    ]
    assert plan.json()["plan"]["definition"]["enabled"] is False
    assert cross_tenant.status_code == 200
    assert cross_tenant.json()["result"]["status"] == "failed"
    assert "TCK-BETA" not in cross_tenant.text
    assert viewer.status_code == 403
    assert unsupported.status_code == 422


def test_technician_chat_plan_blocked_results_are_explicit(settings) -> None:
    from wait_local_agent.agents import AgentService
    from wait_local_agent.smart_actions import SmartActionService

    store = Store(settings.data_path)
    with store._connect() as connection:
        for cid in ("acme",):
            connection.execute(
                """
                insert or ignore into clients (client_id, name, status, created_at, updated_at)
                values (?, ?, 'active', ?, ?)
                """,
                (cid, cid.title(), "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"),
            )
        connection.execute(
            """
            insert into tickets (id, client, subject, body, priority, status, client_id)
            values ('TCK-PLAN', 'Acme', 'MFA reset', 'Sign-in blocked', 'high', 'open', 'acme')
            """
        )
    smart_actions = SmartActionService(store, settings)
    planner = AgentService(store, settings, smart_actions)

    no_match = app_module._invoke_technician_chat_message(
        store,
        smart_actions,
        planner,
        "plan invent a new unsupported operation for TCK-PLAN",
        ticket_id="TCK-PLAN",
        actor="tech",
        client_id="acme",
    )
    missing_ticket = app_module._invoke_technician_chat_message(
        store,
        smart_actions,
        planner,
        "plan triage TCK-NOT-FOUND",
        ticket_id="TCK-NOT-FOUND",
        actor="tech",
        client_id="acme",
    )

    assert no_match["status"] == "blocked"
    assert missing_ticket["status"] == "blocked"
    missing_plan = cast(dict[str, object], missing_ticket["plan"])
    assert "not found" in str(missing_plan["blocked_reason"])

