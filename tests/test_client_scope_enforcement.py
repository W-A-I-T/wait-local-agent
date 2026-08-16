from __future__ import annotations

import ast
import inspect
import textwrap
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from wait_local_agent.api.app import (
    EndUserMessageRequest,
    _backfill_scope,
    _operator_scope,
    _required_client_id,
    _resolve_detail_scope,
    create_app,
)
from wait_local_agent.client_scope import AllClients, BoundClients, resolve_client_scope
from wait_local_agent.rbac import AuthContext, Role, resolve_auth_context
from wait_local_agent.store import Store


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _has_entity_derived_scope(source: str) -> bool:
    """Recognize a scoped store lookup whose tenant is derived from a scoped entity."""

    tree = ast.parse(textwrap.dedent(source))
    entity_names: set[str] = set()
    derived_client_names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        targets = {target.id for target in node.targets if isinstance(target, ast.Name)}
        value = node.value
        if (
            isinstance(value, ast.Call)
            and isinstance(value.func, ast.Attribute)
            and value.func.attr == "get_ticket"
            and any(keyword.arg == "client_id" for keyword in value.keywords)
        ):
            entity_names.update(targets)
        if targets and _contains_entity_client_attribute(value, entity_names):
            derived_client_names.update(targets)

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if not isinstance(node.func.value, ast.Name) or node.func.value.id != "store":
            continue
        if any(
            keyword.arg == "client_id"
            and isinstance(keyword.value, ast.Name)
            and keyword.value.id in derived_client_names
            for keyword in node.keywords
        ):
            return True
    return False


def _contains_entity_client_attribute(node: ast.AST, entity_names: set[str]) -> bool:
    return any(
        isinstance(item, ast.Attribute)
        and item.attr == "client_id"
        and isinstance(item.value, ast.Name)
        and item.value.id in entity_names
        for item in ast.walk(node)
    )


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
    assert isinstance(resolve_client_scope(msp), AllClients)
    with pytest.raises(HTTPException) as detail_error:
        _resolve_detail_scope(bound, "beta")
    assert detail_error.value.status_code == 404
    with pytest.raises(HTTPException) as multi_error:
        _ = resolve_client_scope(multi_client).client_id
    assert multi_error.value.status_code == 403


def test_client_scope_resolver_covers_empty_bound_and_tenantless_principals() -> None:
    with pytest.raises(ValueError, match="at least one"):
        BoundClients(frozenset())

    demo = AuthContext(
        role=Role.ADMIN,
        presented_token=None,
        client_id="demo",
        client_ids=frozenset({"demo"}),
        demo_mode=True,
    )
    msp_admin = AuthContext(
        role=Role.ADMIN,
        presented_token="msp-admin",
        client_id=None,
        client_ids=frozenset(),
        is_msp_admin=True,
    )
    bound = AuthContext(
        role=Role.ADMIN,
        presented_token="bound-admin",
        client_id="acme",
        client_ids=frozenset({"acme"}),
    )
    tenantless = replace(bound, client_id=None, client_ids=frozenset())

    assert isinstance(resolve_client_scope(demo), AllClients)
    assert resolve_client_scope(demo, "acme").client_id == "acme"
    assert isinstance(resolve_client_scope(msp_admin), AllClients)
    assert resolve_client_scope(msp_admin).client_id is None
    assert resolve_client_scope(msp_admin, "acme").client_id == "acme"
    assert resolve_client_scope(bound).client_id == "acme"
    assert resolve_client_scope(bound, " ").client_id == "acme"
    with pytest.raises(HTTPException) as foreign:
        resolve_client_scope(bound, "beta")
    assert foreign.value.status_code == 403
    with pytest.raises(HTTPException) as missing_tenant:
        resolve_client_scope(tenantless)
    assert missing_tenant.value.status_code == 403


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
        "end_user_messages": client.get(
            "/tickets/TCK-BETA/end-user-messages",
            headers=headers,
        ),
        "end_user_message_reply": client.post(
            "/tickets/TCK-BETA/end-user-messages",
            headers=headers,
            json={"body": "nope"},
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
    indirect_scope_helpers = {
        "_approval_scope_visible",
        "_backfill_scope",
        "_operator_scope",
        "_resolve_detail_scope",
    }

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
            or _has_entity_derived_scope(source)
        ), f"unscoped client-bearing route: {route.path}"
    for helper_name in indirect_scope_helpers:
        helper = getattr(__import__("wait_local_agent.api.app", fromlist=[helper_name]), helper_name)
        assert "resolve_client_scope" in inspect.getsource(helper)
    assert checked >= 20


def test_entity_derived_scope_detection_requires_scoped_entity_lookup() -> None:
    scoped = """
    ticket = store.get_ticket(ticket_id, client_id=scope)
    ticket_client_id = _normalize_client_id(ticket.client_id) if ticket is not None else None
    return store.list_end_user_messages_for_operator(ticket_id, client_id=ticket_client_id)
    """
    unscoped = """
    ticket = store.get_ticket(ticket_id)
    ticket_client_id = _normalize_client_id(ticket.client_id) if ticket is not None else None
    return store.list_end_user_messages_for_operator(ticket_id, client_id=ticket_client_id)
    """

    assert _has_entity_derived_scope(scoped)
    assert not _has_entity_derived_scope(unscoped)


def test_operator_end_user_routes_hide_foreign_ticket_scope(settings) -> None:
    secure_settings = replace(
        settings,
        demo_mode=False,
        client_id="alpha",
        admin_token="admin-token",
        tech_token="tech-token",
        viewer_token="viewer-token",
    )
    store = Store(secure_settings.data_path)
    _seed_cross_client_state(store)
    app = create_app(secure_settings)
    viewer_context = AuthContext(
        role=Role.VIEWER,
        presented_token="viewer-token",
        client_id="alpha",
        client_ids=frozenset({"alpha"}),
    )
    technician_context = replace(viewer_context, role=Role.TECHNICIAN, presented_token="tech-token")
    get_endpoint = next(
        route.endpoint
        for route in app.routes
        if isinstance(route, APIRoute)
        and route.path == "/tickets/{ticket_id}/end-user-messages"
        and route.methods is not None
        and "GET" in route.methods
    )
    post_endpoint = next(
        route.endpoint
        for route in app.routes
        if isinstance(route, APIRoute)
        and route.path == "/tickets/{ticket_id}/end-user-messages"
        and route.methods is not None
        and "POST" in route.methods
    )

    with pytest.raises(HTTPException) as get_error:
        get_endpoint("TCK-BETA", None, viewer_context)
    with pytest.raises(HTTPException) as post_error:
        post_endpoint("TCK-BETA", EndUserMessageRequest(body="nope"), None, technician_context)

    assert get_error.value.status_code == 404
    assert post_error.value.status_code == 404


def test_scope_helpers_cover_m365_report_and_backfill_tenant_branches() -> None:
    bound = AuthContext(
        role=Role.TECHNICIAN,
        presented_token="tech-token",
        client_id="alpha",
        client_ids=frozenset({"alpha"}),
    )
    msp_technician = replace(bound, is_msp_admin=True)
    msp_admin = replace(msp_technician, role=Role.ADMIN)

    assert _required_client_id(bound, None) == "alpha"
    with pytest.raises(HTTPException, match="outside authenticated scope"):
        _required_client_id(bound, "beta")
    assert _operator_scope(msp_technician, "alpha").client_id == "alpha"
    assert isinstance(_operator_scope(msp_admin, "alpha"), AllClients)
    assert _backfill_scope(bound, None).client_id == "alpha"
    with pytest.raises(HTTPException, match="require a client scope"):
        _backfill_scope(msp_technician, None)
    assert isinstance(_backfill_scope(msp_admin, None), AllClients)


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
