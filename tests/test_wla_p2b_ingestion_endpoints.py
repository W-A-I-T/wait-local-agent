from __future__ import annotations

from dataclasses import replace

from fastapi.testclient import TestClient

from wait_local_agent.api.app import create_app
from wait_local_agent.store import Store


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_ingestion_operator_endpoints_list_filter_scope_and_resolve(settings) -> None:
    secure_settings = replace(
        settings,
        demo_mode=False,
        client_id="client-a",
        admin_token="bootstrap-admin",
        api_token="",
    )
    store = Store(secure_settings.data_path)
    store.create_client("client-a", "Acme")
    store.create_client("client-b", "Beta")
    connector_a = store.create_connector_instance("halopsa", "Acme", client_id="client-a")
    connector_b = store.create_connector_instance("halopsa", "Beta", client_id="client-b")
    cursor_a = store.upsert_sync_cursor(
        connector_a.connector_instance_id,
        "tickets",
        cursor_value="cursor-a",
        status="idle",
        last_synced_at="2026-08-16T00:00:00+00:00",
    )
    cursor_b = store.upsert_sync_cursor(
        connector_b.connector_instance_id,
        "tickets",
        cursor_value="cursor-b",
        status="degraded",
    )
    record_a = store.record_unmapped(
        connector_a.connector_instance_id,
        "company-a",
        "ticket-a",
        "ticket",
        "digest-a",
        "no_verified_mapping",
    )
    record_b = store.record_unmapped(
        connector_b.connector_instance_id,
        "company-b",
        "ticket-b",
        "ticket",
        "digest-b",
        "ambiguous_mapping",
    )
    store.create_principal("bound-admin", kind="staff")
    store.add_principal_credential("bound-admin", "bound-secret")
    store.add_principal_client_role("bound-admin", "client-a", "admin")

    client = TestClient(create_app(secure_settings))
    operator_headers = _auth("bootstrap-admin")
    bound_headers = _auth("bound-secret")

    cursors = client.get("/ingestion/sync-cursors", headers=operator_headers)
    assert cursors.status_code == 200
    assert {
        item["connector_instance_id"]: item
        for item in cursors.json()
    } == {
        cursor.connector_instance_id: {
            "connector_instance_id": cursor.connector_instance_id,
            "cursor_type": cursor.cursor_type,
            "cursor_value": cursor.cursor_value,
            "status": cursor.status,
            "last_synced_at": cursor.last_synced_at,
            "updated_at": cursor.updated_at,
        }
        for cursor in (cursor_a, cursor_b)
    }
    assert client.get("/ingestion/sync-cursors", headers=bound_headers).status_code == 403

    all_records = client.get("/ingestion/unmapped", headers=operator_headers)
    assert all_records.status_code == 200
    assert [item["record_id"] for item in all_records.json()] == [record_a.record_id, record_b.record_id]

    filtered = client.get(
        "/ingestion/unmapped",
        params={"connector_instance_id": connector_b.connector_instance_id},
        headers=operator_headers,
    )
    assert filtered.status_code == 200
    assert [item["record_id"] for item in filtered.json()] == [record_b.record_id]

    empty_filter = client.get(
        "/ingestion/unmapped",
        params={"connector_instance_id": " "},
        headers=operator_headers,
    )
    assert empty_filter.status_code == 400
    assert empty_filter.json()["detail"] == "connector_instance_id must be non-empty"

    bound_records = client.get("/ingestion/unmapped", headers=bound_headers)
    assert bound_records.status_code == 200
    assert [item["record_id"] for item in bound_records.json()] == [record_a.record_id]

    assert (
        client.post(
            f"/ingestion/unmapped/{record_a.record_id}/resolve",
            headers=bound_headers,
        ).status_code
        == 403
    )
    resolved = client.post(
        f"/ingestion/unmapped/{record_a.record_id}/resolve",
        headers=operator_headers,
    )
    assert resolved.status_code == 200
    assert resolved.json()["record_id"] == record_a.record_id
    assert resolved.json()["resolved_at"] is not None

    missing = client.post("/ingestion/unmapped/missing/resolve", headers=operator_headers)
    assert missing.status_code == 404
    assert missing.json()["detail"] == "unmapped record not found"
