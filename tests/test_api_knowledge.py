from __future__ import annotations

import hashlib
from dataclasses import replace

from fastapi.testclient import TestClient

from tests.api_helpers import _auth, _provision_bound_principal
from tests.support import ensure_test_clients
from wait_local_agent.api.app import create_app
from wait_local_agent.store import Store


def test_knowledge_authority_route_is_admin_scoped_and_records_authenticated_actor(settings) -> None:
    secure_settings = replace(
        settings,
        demo_mode=False,
        admin_token="bootstrap-admin-token",
        tech_token="technician-token",
        viewer_token="viewer-token",
    )
    store = Store(secure_settings.data_path)
    ensure_test_clients(store, "acme", "beta")
    _provision_bound_principal(store, "acme-admin", "acme-admin-token", "acme", "admin")
    first = store.upsert_knowledge_document(
        path="examples/sample_docs/authority-first.md",
        title="First SOP",
        kind="markdown",
        checksum="authority-first-sum",
        modified_at="2026-08-31T00:00:00+00:00",
        chunks=["first"],
        client_id="acme",
    )
    replacement = store.upsert_knowledge_document(
        path="examples/sample_docs/authority-replacement.md",
        title="Replacement SOP",
        kind="markdown",
        checksum="authority-replacement-sum",
        modified_at="2026-08-31T00:00:00+00:00",
        chunks=["replacement"],
        client_id="acme",
    )
    foreign = store.upsert_knowledge_document(
        path="examples/sample_docs/authority-foreign.md",
        title="Foreign SOP",
        kind="markdown",
        checksum="authority-foreign-sum",
        modified_at="2026-08-31T00:00:00+00:00",
        chunks=["foreign"],
        client_id="beta",
    )
    client = TestClient(create_app(secure_settings))

    denied = client.patch(
        f"/knowledge/documents/{first.id}/authority",
        headers=_auth("technician-token"),
        json={"authority": "REFERENCE"},
    )
    rejected_body = client.patch(
        f"/knowledge/documents/{first.id}/authority",
        headers=_auth("acme-admin-token"),
        json={"authority": "APPROVED_SOP", "approved_by": "request-body-actor"},
    )
    promoted = client.patch(
        f"/knowledge/documents/{first.id}/authority",
        headers=_auth("acme-admin-token"),
        json={"authority": "APPROVED_SOP", "sop_version": "2026.08", "superseded_by": replacement.id},
    )
    invalid_superseded_scope = client.patch(
        f"/knowledge/documents/{first.id}/authority",
        headers=_auth("acme-admin-token"),
        json={"authority": "APPROVED_SOP", "superseded_by": foreign.id},
    )
    foreign_mutation = client.patch(
        f"/knowledge/documents/{foreign.id}/authority",
        headers=_auth("acme-admin-token"),
        json={"authority": "REFERENCE"},
    )
    demoted = client.patch(
        f"/knowledge/documents/{first.id}/authority",
        headers=_auth("acme-admin-token"),
        json={"authority": "REFERENCE"},
    )
    listed = client.get("/knowledge/documents", headers=_auth("acme-admin-token"))
    audit = client.get("/audit", params={"client_id": "acme"}, headers=_auth("acme-admin-token"))

    assert denied.status_code == 403
    assert rejected_body.status_code == 422
    assert promoted.status_code == 200
    assert promoted.json()["authority"] == "APPROVED_SOP"
    assert promoted.json()["approved_by"] == hashlib.sha256(b"acme-admin-token").hexdigest()[:16]
    assert promoted.json()["approved_at"]
    assert promoted.json()["sop_version"] == "2026.08"
    assert promoted.json()["superseded_by"] == replacement.id
    assert invalid_superseded_scope.status_code == 400
    assert foreign_mutation.status_code == 404
    assert demoted.status_code == 200
    assert demoted.json()["authority"] == "REFERENCE"
    assert demoted.json()["approved_by"] is None
    assert demoted.json()["approved_at"] is None
    listed_documents = listed.json()
    assert [document["authority"] for document in listed_documents] == ["REFERENCE", "UNTRUSTED"]
    # The beta document must not appear in an acme-scoped listing.
    assert foreign.id not in {document["id"] for document in listed_documents}
    assert {"authority", "sop_version", "approved_by", "approved_at", "superseded_by"} <= set(listed_documents[0])
    authority_events = [event for event in audit.json() if event["event_type"] == "knowledge.authority.changed"]
    assert len(authority_events) == 2
    expected_actor = hashlib.sha256(b"acme-admin-token").hexdigest()[:16]
    # Audit events are returned newest-first by Store.list_audit_events (order by id desc).
    assert authority_events[0]["detail"] == (
        f"actor={expected_actor} document_id={first.id} "
        "old_authority=APPROVED_SOP new_authority=REFERENCE"
    )
    assert authority_events[0]["approver_id"] == expected_actor
    assert authority_events[1]["detail"] == (
        f"actor={expected_actor} document_id={first.id} "
        "old_authority=UNTRUSTED new_authority=APPROVED_SOP"
    )
    assert authority_events[1]["approver_id"] == expected_actor

def test_knowledge_api_ingest_list_and_search(settings) -> None:
    client = TestClient(create_app(settings))

    ingest = client.post("/knowledge/ingest", json={"path": "examples/sample_docs"})
    documents = client.get("/knowledge/documents")
    search = client.get("/knowledge/search", params={"q": "mailbox permissions"})

    assert ingest.status_code == 200
    assert len(ingest.json()) == 3
    assert documents.status_code == 200
    assert len(documents.json()) == 3
    assert search.status_code == 200
    assert search.json()[0]["title"] == "Shared Mailbox Runbook"

def test_knowledge_search_scopes_results_by_client_id(settings) -> None:
    store = Store(settings.data_path)
    ensure_test_clients(store, "acme", "beta")
    store.upsert_knowledge_document(
        path="examples/sample_docs/acme.md",
        title="Acme Runbook",
        kind="markdown",
        checksum="acme-checksum",
        modified_at="2026-07-08T00:00:00+00:00",
        chunks=["mailbox permissions for acme"],
        client_id="acme",
    )
    store.upsert_knowledge_document(
        path="examples/sample_docs/beta.md",
        title="Beta Runbook",
        kind="markdown",
        checksum="beta-checksum",
        modified_at="2026-07-08T00:00:00+00:00",
        chunks=["mailbox permissions for beta"],
        client_id="beta",
    )
    client = TestClient(create_app(settings))

    filtered = client.get("/knowledge/search", params={"q": "mailbox permissions", "client_id": "acme"})
    unfiltered = client.get("/knowledge/search", params={"q": "mailbox permissions"})

    assert filtered.status_code == 200
    assert [chunk["title"] for chunk in filtered.json()] == ["Acme Runbook"]
    assert len(unfiltered.json()) == 2

def test_knowledge_api_rejects_outside_allowed_root(settings, tmp_path) -> None:
    outside = tmp_path / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    client = TestClient(create_app(settings))

    response = client.post("/knowledge/ingest", json={"path": str(outside)})

    assert response.status_code == 400

def test_knowledge_api_missing_path_returns_400(settings) -> None:
    client = TestClient(create_app(settings))

    response = client.post("/knowledge/ingest", json={"path": "examples/sample_docs/missing.md"})

    assert response.status_code == 400

