from __future__ import annotations

import inspect
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from wait_local_agent.api.app import create_app
from wait_local_agent.client_scope import AllClients, BoundClients, resolve_client_scope
from wait_local_agent.rbac import AuthContext, Role, resolve_auth_context
from wait_local_agent.store import Store


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _seed_cross_client_state(store: Store) -> int:
    with store._connect() as connection:  # noqa: SLF001
        connection.execute(
            """
            insert into tickets (id, client, subject, body, priority, status, client_id)
            values ('TCK-ALPHA', 'Alpha', 'Alpha subject', 'Alpha body', 'High', 'Open', 'alpha')
            """
        )
        connection.execute(
            """
            insert into tickets (id, client, subject, body, priority, status, client_id)
            values ('TCK-BETA', 'Beta', 'Beta subject', 'Beta body', 'Low', 'Open', 'beta')
            """
        )
    store.create_approval_request(
        "TCK-BETA",
        "ticket.assign",
        {"ticket_id": "TCK-BETA"},
        client_id="beta",
    )
    store.add_audit_event("cross-client.beta", "TCK-BETA", "beta event", client_id="beta")
    store.upsert_knowledge_document(
        path="examples/sample_docs/beta.md",
        title="Beta runbook",
        kind="markdown",
        checksum="beta-client-scope",
        modified_at="2026-08-15T00:00:00+00:00",
        chunks=["beta mailbox permissions"],
        client_id="beta",
    )
    store.create_workflow_run(
        "documentation-assisted-response",
        "TCK-BETA",
        "pending_approval",
        "beta workflow",
        client_id="beta",
    )
    collector_run = store.create_collector_run(
        module_id="fixture",
        source_id=None,
        status="completed",
        mode="run",
        scope={"kind": "host"},
        preview={},
        client_id="beta",
    )
    assert collector_run.id is not None
    return collector_run.id


def test_client_scope_resolver_is_demo_permissive_and_non_demo_fail_closed(settings) -> None:
    demo = AuthContext(
        role=Role.ADMIN,
        presented_token=None,
        client_id="alpha",
        client_ids=frozenset({"alpha"}),
        demo_mode=True,
    )
    bound = AuthContext(
        role=Role.VIEWER,
        presented_token="viewer",
        client_id="alpha",
        client_ids=frozenset({"alpha"}),
    )
    msp = replace(bound, role=Role.ADMIN, is_msp_admin=True, client_ids=frozenset({"alpha", "beta"}))
    generic_admin = replace(bound, role=Role.ADMIN)
    multi_client = replace(bound, client_ids=frozenset({"alpha", "beta"}))

    assert isinstance(resolve_client_scope(demo), AllClients)
    assert isinstance(resolve_client_scope(demo, "beta"), BoundClients)
    with pytest.raises(HTTPException) as bound_error:
        resolve_client_scope(bound, "beta")
    with pytest.raises(HTTPException) as admin_error:
        resolve_client_scope(generic_admin, "beta")
    assert bound_error.value.status_code == 403
    assert admin_error.value.status_code == 403
    assert isinstance(resolve_client_scope(msp, allow_all=True), AllClients)
    assert isinstance(resolve_client_scope(msp), BoundClients)
    with pytest.raises(HTTPException) as multi_error:
        _ = resolve_client_scope(multi_client).client_id
    assert multi_error.value.status_code == 403


def test_cross_client_negative_matrix(settings) -> None:
    secure_settings = replace(
        settings,
        demo_mode=False,
        client_id="alpha",
        admin_token="admin-token",
        tech_token="tech-token",
        viewer_token="viewer-token",
    )
    store = Store(secure_settings.data_path)
    store.create_principal("alpha-technician", kind="staff")
    store.add_principal_credential("alpha-technician", "alpha-technician-token")
    store.add_principal_client_role("alpha-technician", "alpha", "technician")
    collector_run_id = _seed_cross_client_state(store)
    client = TestClient(create_app(secure_settings))
    principal_context = resolve_auth_context(
        secure_settings,
        "Bearer alpha-technician-token",
        store,
    )
    assert principal_context.client_ids == frozenset({"alpha"})
    assert principal_context.is_msp_admin is False
    headers = _auth("alpha-technician-token")

    responses = {
        "tickets_list": client.get("/tickets", params={"client_id": "beta"}, headers=headers),
        "ticket_summary": client.get("/tickets/TCK-BETA/summary", headers=headers),
        "ticket_approval": client.post(
            "/tickets/TCK-BETA/approvals",
            headers=headers,
            json={"status": "approved"},
        ),
        "knowledge_documents": client.get(
            "/knowledge/documents", params={"client_id": "beta"}, headers=headers
        ),
        "knowledge_search": client.get(
            "/knowledge/search", params={"q": "beta", "client_id": "beta"}, headers=headers
        ),
        "knowledge_ingest": client.post(
            "/knowledge/ingest",
            headers=headers,
            json={"path": "examples/sample_docs", "client_id": "beta"},
        ),
        "collector_list": client.get(
            "/collectors/runs", params={"client_id": "beta"}, headers=headers
        ),
        "collector_detail": client.get(f"/collectors/runs/{collector_run_id}", headers=headers),
        "collector_export": client.post(f"/collectors/runs/{collector_run_id}/export", headers=headers),
        "collector_module_run": client.post(
            "/collectors/modules/fixture/run",
            headers=headers,
            json={"config": {}, "confirm": True, "client_id": "beta"},
        ),
        "workflow_list": client.get("/workflow-runs", params={"client_id": "beta"}, headers=headers),
        "event_history": client.get("/event-history", params={"client_id": "beta"}, headers=headers),
        "audit": client.get("/audit", params={"client_id": "beta"}, headers=headers),
        "halopsa_draft": client.post(
            "/connectors/halopsa/tickets/TCK-BETA/drafts",
            headers=headers,
            json={"action_type": "add_note", "fields": {"note": "nope"}, "client_id": "beta"},
        ),
    }

    assert responses
    for name, response in responses.items():
        assert response.status_code in {403, 404}, name
        assert "TCK-BETA" not in response.text, name


def test_route_walk_requires_scope_for_client_bearing_routes(settings) -> None:
    app = create_app(settings)
    required_path_prefixes = (
        "/tickets",
        "/collectors/runs",
        "/workflow-runs",
        "/knowledge",
        "/audit",
        "/event-history",
        "/approval-requests",
    )
    required_exact_paths = {"/connectors/halopsa/tickets/{ticket_id}/drafts"}
    fixed_scope_allowlist = {"/mcp"}
    indirect_scope_helpers = {"_approval_scope_visible", "_backfill_scope"}

    checked = 0
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        signature = inspect.signature(route.endpoint)
        has_client_parameter = "client_id" in signature.parameters
        has_client_path = route.path.startswith(required_path_prefixes) or route.path in required_exact_paths
        if not (has_client_parameter or has_client_path) or route.path in fixed_scope_allowlist:
            continue
        checked += 1
        source = inspect.getsource(route.endpoint)
        assert (
            "resolve_client_scope" in source
            or any(helper in source for helper in indirect_scope_helpers)
        ), f"unscoped client-bearing route: {route.path}"
    for helper_name in indirect_scope_helpers:
        helper = getattr(__import__("wait_local_agent.api.app", fromlist=[helper_name]), helper_name)
        assert "resolve_client_scope" in inspect.getsource(helper)
    assert checked >= 20


def test_store_tenant_filters_reject_none_and_empty_and_fail_open_sql_is_gone(settings) -> None:
    store = Store(settings.data_path)
    store_source = (Path(__file__).parents[1] / "src/wait_local_agent/store.py").read_text(encoding="utf-8")
    assert "(? is null or client_id = ?)" not in store_source
    assert "(? is null or d.client_id = ?)" not in store_source

    invalid_calls = (
        lambda value: store.get_technician_chat_session("missing", client_id=value),
        lambda value: store.list_technician_chat_sessions(client_id=value),
        lambda value: store.has_event_agent_run(
            agent_id="agent", event_type="ticket.created", entity_id="TCK-1", client_id=value
        ),
        lambda value: store.has_completed_event_agent_run(
            agent_id="agent", event_type="ticket.created", entity_id="TCK-1", client_id=value
        ),
        lambda value: store.get_consultant_discovery_session("missing", client_id=value),
        lambda value: store.search_knowledge_chunks("missing", client_id=value),
        lambda value: store.get_collector_run(404, client_id=value),
        lambda value: store.list_canonical_assets(client_id=value),
    )
    for invalid in (None, ""):
        for call in invalid_calls:
            with pytest.raises(ValueError, match="client"):
                call(invalid)
