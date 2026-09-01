from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from packs.automation_discovery.service import (
    HistoricalTimeEntry,
    _connector_family,
    _playbook_match,
    _prerequisite_status,
    _subject_signature,
    _timestamp,
    _workflow_match,
    build_historical_discovery,
    build_mapping_readiness,
    import_time_entries,
)
from tests.support import ensure_test_client
from wait_local_agent.api.app import create_app
from wait_local_agent.client_scope import BoundClients
from wait_local_agent.store import Store


def _seed_tickets(store: Store, tmp_path: Path, client_id: str) -> None:
    tickets = [
        {
            "id": f"AUTH-{index}",
            "client": "Acme",
            "subject": "Password reset and MFA unlock",
            "body": "User cannot sign in after replacing Microsoft Authenticator phone.",
            "priority": "medium",
            "status": "closed",
        }
        for index in range(1, 5)
    ]
    tickets.extend(
        [
            {
                "id": f"PRN-{index}",
                "client": "Acme",
                "subject": "Printer spooler stopped",
                "body": "Office printer queue is stuck and users cannot print.",
                "priority": "low",
                "status": "resolved",
            }
            for index in range(1, 4)
        ]
    )
    source = tmp_path / "historical-tickets.json"
    source.write_text(json.dumps(tickets), encoding="utf-8")
    store.ingest_ticket_file(source, client_id=client_id)


def _verified_mapping(store: Store, client_id: str, connector_type: str) -> str:
    scope = BoundClients(frozenset({client_id}))
    instance = store.create_connector_instance(
        connector_type,
        f"{connector_type} test",
        client_id=client_id,
    )
    mapping = store.create_client_connector_mapping(
        scope,
        instance.connector_instance_id,
        f"external-{connector_type}",
        client_id,
        external_company_name="Acme",
    )
    store.verify_client_connector_mapping(scope, mapping.mapping_id)
    return instance.connector_instance_id


def test_historical_discovery_ranks_recurring_psa_work_without_enabling_automation(settings, tmp_path) -> None:
    store = Store(settings.data_path)
    client_id = ensure_test_client(store)
    _seed_tickets(store, tmp_path, client_id)
    _verified_mapping(store, client_id, "m365")
    _verified_mapping(store, client_id, "halopsa")
    _verified_mapping(store, client_id, "ninja-rmm")

    report = build_historical_discovery(store, client_id=client_id, days=60, min_tickets=3)

    assert report["side_effects"] is False
    assert report["automation_enabled"] is False
    assert report["ticket_count"] == 7
    opportunities = report["opportunities"]
    assert isinstance(opportunities, list)
    auth = next(item for item in opportunities if item["category_id"] == "password-mfa-authentication")
    printer = next(item for item in opportunities if item["category_id"] == "disk-printer-endpoint-alert")
    assert auth["ticket_count"] == 4
    assert auth["readiness"] == "ready_for_review"
    assert any(item["id"] == "m365-password-reset-review" for item in auth["workflow_matches"])
    assert printer["ticket_count"] == 3
    assert set(auth["source_ticket_ids"]) == {"AUTH-1", "AUTH-2", "AUTH-3", "AUTH-4"}


def test_normalized_time_entries_are_idempotent_and_reported_as_measured(settings, tmp_path) -> None:
    store = Store(settings.data_path)
    client_id = ensure_test_client(store)
    _seed_tickets(store, tmp_path, client_id)
    connector_id = _verified_mapping(store, client_id, "m365")
    entry = HistoricalTimeEntry(
        client_id=client_id,
        ticket_id="AUTH-1",
        connector_instance_id=connector_id,
        external_time_entry_id="time-1",
        minutes=25,
        work_type="remote support",
        occurred_at="2026-08-30T18:00:00+00:00",
        source_system="test-psa",
    )

    first = import_time_entries(store, [entry])
    second = import_time_entries(store, [entry])
    report = build_historical_discovery(store, client_id=client_id, days=60, min_tickets=3)

    assert first == {"inserted": 1, "duplicate": 0, "rejected": 0}
    assert second == {"inserted": 0, "duplicate": 1, "rejected": 0}
    auth = next(item for item in report["opportunities"] if item["category_id"] == "password-mfa-authentication")
    assert auth["measured_labor_available"] is True
    assert auth["measured_labor_minutes"] == 25
    assert report["labor"]["measured"] is True
    assert report["labor"]["measured_minutes"] == 25


def test_time_entry_import_rejects_invalid_evidence_and_discovery_bounds(settings) -> None:
    store = Store(settings.data_path)
    client_id = ensure_test_client(store)
    common = {
        "client_id": client_id,
        "connector_instance_id": "connector-1",
        "work_type": "remote support",
        "occurred_at": "2026-08-30T18:00:00+00:00",
        "source_system": "test-psa",
    }
    rejected = import_time_entries(
        store,
        [
            HistoricalTimeEntry(ticket_id="T-1", external_time_entry_id="time-1", minutes=-1, **common),
            HistoricalTimeEntry(ticket_id="T-2", external_time_entry_id="time-2", minutes=1441, **common),
            HistoricalTimeEntry(ticket_id="  ", external_time_entry_id="time-3", minutes=10, **common),
            HistoricalTimeEntry(ticket_id="T-4", external_time_entry_id="  ", minutes=10, **common),
        ],
    )

    assert rejected == {"inserted": 0, "duplicate": 0, "rejected": 4}
    with pytest.raises(ValueError, match="days must be between"):
        build_historical_discovery(store, client_id=client_id, days=6)
    with pytest.raises(ValueError, match="min_tickets must be between"):
        build_historical_discovery(store, client_id=client_id, min_tickets=1)
    with pytest.raises(ValueError, match="occurred_at must be"):
        import_time_entries(
            store,
            [
                HistoricalTimeEntry(
                    ticket_id="T-5",
                    external_time_entry_id="time-5",
                    minutes=10,
                    **{**common, "occurred_at": "not-a-date"},
                )
            ],
        )


def test_discovery_helpers_keep_unknown_and_unclassified_values_explicit() -> None:
    assert _workflow_match("missing-workflow") == {"id": "missing-workflow", "available": False}
    assert _playbook_match("missing-playbook") == {"id": "missing-playbook", "available": False}
    assert _prerequisite_status(
        ("psa", "rmm", "documentation"),
        {"families": {"psa": {"unverified": 1}, "rmm": {"verified": 1}}},
    ) == [
        {"family": "psa", "status": "review_mapping"},
        {"family": "rmm", "status": "verified"},
        {"family": "documentation", "status": "missing"},
    ]
    assert _connector_family("unknown-system") == "other"
    assert _subject_signature("VPN") == ""
    assert _timestamp("").year == 1
    assert _timestamp("not-a-date").year == 1
    assert _timestamp("2026-08-30T18:00:00").tzinfo is not None


def test_mapping_readiness_reports_cross_system_families(settings) -> None:
    store = Store(settings.data_path)
    client_id = ensure_test_client(store)
    _verified_mapping(store, client_id, "halopsa")
    _verified_mapping(store, client_id, "ninja-rmm")
    _verified_mapping(store, client_id, "hudu")
    _verified_mapping(store, client_id, "m365")
    _verified_mapping(store, client_id, "huntress")

    readiness = build_mapping_readiness(store, client_id=client_id)

    assert readiness["verified_count"] == 5
    families = readiness["families"]
    assert families["psa"]["verified"] == 1
    assert families["rmm"]["verified"] == 1
    assert families["documentation"]["verified"] == 1
    assert families["m365"]["verified"] == 1
    assert families["security"]["verified"] == 1


def test_historical_discovery_reports_unclassified_recurring_subjects(settings, tmp_path) -> None:
    store = Store(settings.data_path)
    client_id = ensure_test_client(store)
    tickets = [
        {
            "id": f"VPN-{index}",
            "client": "Acme",
            "subject": "VPN timeout issue",
            "body": "Remote access stops after the connection is established.",
            "priority": "high",
            "status": "open",
        }
        for index in range(1, 4)
    ]
    tickets.append(
        {
            "id": "ODD-1",
            "client": "Acme",
            "subject": "Odd request pending",
            "body": "A one-off request is waiting for review.",
            "priority": "low",
            "status": "open",
        }
    )
    source = tmp_path / "unclassified-tickets.json"
    source.write_text(json.dumps(tickets), encoding="utf-8")
    store.ingest_ticket_file(source, client_id=client_id)

    report = build_historical_discovery(store, client_id=client_id, days=60, min_tickets=3)

    assert report["ticket_count"] == 4
    recurring = next(item for item in report["opportunities"] if item["category_id"] == "recurring:vpn-timeout-issue")
    assert recurring["label"] == "Recurring ticket family: vpn timeout issue"
    assert recurring["ticket_count"] == 3
    assert recurring["resolved_or_closed"] == 0
    assert recurring["readiness"] == "needs_workflow_design"
    assert recurring["workflow_matches"] == []
    assert recurring["playbook_matches"] == []
    assert recurring["source_ticket_ids"] == ["VPN-1", "VPN-2", "VPN-3"]
    assert recurring["source_ticket_ids_truncated"] is False


def test_discovery_routes_are_scoped_and_import_only_permitted_evidence(settings, tmp_path) -> None:
    store = Store(settings.data_path)
    client_id = ensure_test_client(store)
    _seed_tickets(store, tmp_path, client_id)
    connector_id = _verified_mapping(store, client_id, "halopsa")
    client = TestClient(create_app(settings))

    status = client.get("/packs/automation-discovery/status")
    categories = client.get("/packs/automation-discovery/categories")
    historical = client.get(
        "/packs/automation-discovery/historical",
        params={"client_id": client_id, "days": 30, "min_tickets": 3},
    )
    readiness = client.get(
        "/packs/automation-discovery/mapping-readiness",
        params={"client_id": client_id},
    )

    assert status.status_code == 200
    assert status.json()["external_writes"] is False
    assert categories.status_code == 200
    assert {item["category_id"] for item in categories.json()} >= {
        "password-mfa-authentication",
        "security-alert",
    }
    assert historical.status_code == 200
    assert historical.json()["client_id"] == client_id
    assert readiness.status_code == 200
    assert readiness.json()["verified_count"] == 1

    entry: dict[str, object] = {
        "ticket_id": "AUTH-1",
        "connector_instance_id": connector_id,
        "external_time_entry_id": "route-time-1",
        "minutes": 20,
        "work_type": "remote support",
        "occurred_at": "2026-08-30T18:00:00Z",
        "source_system": "test-psa",
    }
    payload: dict[str, object] = {
        "client_id": client_id,
        "entries": [entry],
    }
    imported = client.post("/packs/automation-discovery/time-entries/import", json=payload)
    duplicate = client.post("/packs/automation-discovery/time-entries/import", json=payload)

    assert imported.status_code == 200
    assert imported.json() == {
        "client_id": client_id,
        "inserted": 1,
        "duplicate": 0,
        "rejected": 0,
        "external_writes": False,
    }
    assert duplicate.status_code == 200
    assert duplicate.json()["duplicate"] == 1

    unknown_ticket = client.post(
        "/packs/automation-discovery/time-entries/import",
        json={**payload, "entries": [{**entry, "ticket_id": "not-in-acme"}]},
    )
    unknown_connector = client.post(
        "/packs/automation-discovery/time-entries/import",
        json={
            **payload,
            "entries": [{**entry, "connector_instance_id": "not-in-acme"}],
        },
    )

    assert unknown_ticket.status_code == 400
    assert "selected client scope" in unknown_ticket.json()["detail"]
    assert unknown_connector.status_code == 400
    assert "client-bound" in unknown_connector.json()["detail"]


def test_discovery_routes_require_one_explicit_client(settings) -> None:
    client = TestClient(create_app(settings))

    historical = client.get("/packs/automation-discovery/historical")
    readiness = client.get("/packs/automation-discovery/mapping-readiness")

    assert historical.status_code == 400
    assert readiness.status_code == 400
    assert historical.json()["detail"] == "automation discovery requires one explicit client"
    assert readiness.json()["detail"] == "automation discovery requires one explicit client"
