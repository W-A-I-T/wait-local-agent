from __future__ import annotations

import logging
from pathlib import Path

import pytest

from wait_local_agent.client_scope import AllClients
from wait_local_agent.store import Store


def test_quarantine_is_rejected_as_an_assignment_target(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.db")
    store.create_client("client-a", "Client A")
    store.create_principal("principal-a")
    instance = store.create_connector_instance("halopsa", "Primary")

    with pytest.raises(ValueError, match="__quarantine__ is reserved"):
        store.set_client_status(AllClients(), "__quarantine__", "archived")
    with pytest.raises(ValueError, match="__quarantine__ is reserved"):
        store.add_principal_client_role("principal-a", "__quarantine__", "viewer")
    with pytest.raises(ValueError, match="__quarantine__ is reserved"):
        store.create_connector_instance("halopsa", "Quarantine", client_id="__quarantine__")
    with pytest.raises(ValueError, match="__quarantine__ is reserved"):
        store.update_connector_instance(instance.connector_instance_id, client_id="__quarantine__")
    with pytest.raises(ValueError, match="__quarantine__ is reserved"):
        store.create_client_connector_mapping(
            AllClients(),
            instance.connector_instance_id,
            "external-company",
            "__quarantine__",
        )


def test_startup_logs_existing_quarantine_bindings_without_raising(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    db_path = tmp_path / "state.db"
    store = Store(db_path)
    store.create_principal("principal-a")
    instance = store.create_connector_instance("halopsa", "Primary")
    with store._connect() as connection:  # noqa: SLF001
        connection.execute(
            "insert into principal_client_roles (principal_id, client_id, role) values (?, ?, ?)",
            ("principal-a", "__quarantine__", "viewer"),
        )
        connection.execute(
            "update connector_instances set client_id = ? where connector_instance_id = ?",
            ("__quarantine__", instance.connector_instance_id),
        )
        connection.execute(
            """
            insert into client_connector_mappings
              (mapping_id, connector_instance_id, external_company_id, external_company_name,
               client_id, verified, created_at, updated_at)
            values ('mapping-a', ?, 'external-company', 'External Company', ?, 0, ?, ?)
            """,
            (
                instance.connector_instance_id,
                "__quarantine__",
                "2026-08-16T00:00:00+00:00",
                "2026-08-16T00:00:00+00:00",
            ),
        )

    with caplog.at_level(logging.WARNING, logger="wait_local_agent.store"):
        Store(db_path)

    messages = [record.getMessage() for record in caplog.records]
    assert any("principal_client_role" in message for message in messages)
    assert any("connector_instance" in message for message in messages)
    assert any("client_connector_mapping" in message for message in messages)


def test_all_clients_ticket_reads_and_analytics_hide_quarantine(tmp_path: Path) -> None:
    db_path = tmp_path / "state.db"
    store = Store(db_path)
    store.create_client("client-a", "Client A")
    with store._connect() as connection:  # noqa: SLF001
        for ticket_id, client_id in (("normal-ticket", "client-a"), ("quarantine-ticket", "__quarantine__")):
            connection.execute(
                """
                insert into tickets
                  (id, client, subject, body, priority, status, client_id, source_system)
                values (?, ?, ?, 'Body', 'low', 'new', ?, 'test')
                """,
                (ticket_id, client_id, ticket_id, client_id),
            )
        for ticket_id, client_id in (("normal-ticket", "client-a"), ("quarantine-ticket", "__quarantine__")):
            connection.execute(
                """
                insert into workflow_runs
                  (template_id, ticket_id, status, message, client_id, created_at, updated_at)
                values ('test-template', ?, 'completed', 'test', ?, ?, ?)
                """,
                (ticket_id, client_id, "2026-08-16T00:00:00+00:00", "2026-08-16T00:00:00+00:00"),
            )

    assert [ticket.id for ticket in store.list_tickets(AllClients())] == ["normal-ticket"]
    assert [ticket.id for ticket in store.list_tickets("client-a")] == ["normal-ticket"]
    assert [ticket.id for ticket in store.list_tickets(AllClients(), include_quarantine=True)] == [
        "normal-ticket",
        "quarantine-ticket",
    ]
    assert store.get_ticket("quarantine-ticket", AllClients()) is not None
    assert store.get_ticket("quarantine-ticket", AllClients(), include_quarantine=False) is None
    assert store.get_ticket("quarantine-ticket", AllClients(), include_quarantine=True) is not None
    assert store.get_ticket("quarantine-ticket", "__quarantine__") is not None
    assert store.get_ticket("normal-ticket", "client-a") is not None
    assert store.execution_ticket_activity(None, None, AllClients()) == [("normal-ticket", "new")]
