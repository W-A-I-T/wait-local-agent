from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from wait_local_agent.observability import (
    ESTIMATED_MINUTES_SAVED_DERIVATION,
    MODEL_COST_DERIVATION,
    build_analytics_summary,
)
from wait_local_agent.smart_actions import SmartActionService
from wait_local_agent.store import Store


def _seed_tickets(store: Store) -> None:
    store.ingest_ticket_file(Path("examples/sample_tickets/tickets.json"))


def _seed_executions(store: Store) -> None:
    store.create_execution_run(
        "workflow", 1, "a", "completed", "2026-08-01T09:00:00+00:00",
        "2026-08-01T09:01:00+00:00", "api", client_id="acme",
    )
    store.create_execution_run(
        "workflow", 2, "a", "failed", "2026-08-01T10:00:00+00:00",
        "2026-08-01T10:01:00+00:00", "api", client_id="acme",
    )
    store.create_execution_run(
        "workflow", 3, "b", "pending_approval", "2026-08-02T09:00:00+00:00",
        "2026-08-02T09:01:00+00:00", "scheduler", client_id="beta",
    )


def test_analytics_summary_returns_all_metric_groups(settings) -> None:
    store = Store(settings.data_path)
    _seed_executions(store)

    summary = cast(dict[str, Any], build_analytics_summary(store, {}))

    assert summary["range"] == {"from": None, "to": None}
    assert summary["success_rate"] == {"total": 3, "succeeded": 1, "rate": 1 / 3}
    daily = summary["executions_over_time"]
    assert daily == [
        {"date": "2026-08-01", "count": 2, "succeeded": 1, "not_succeeded": 1},
        {"date": "2026-08-02", "count": 1, "succeeded": 0, "not_succeeded": 1},
    ]
    assert summary["failures_by_status"] == [
        {"status": "failed", "count": 1},
        {"status": "pending_approval", "count": 1},
    ]
    assert summary["activity_breakdown"] == [
        {"run_kind": "workflow", "trigger_source": "api", "status": "completed", "count": 1},
        {"run_kind": "workflow", "trigger_source": "api", "status": "failed", "count": 1},
        {"run_kind": "workflow", "trigger_source": "scheduler", "status": "pending_approval", "count": 1},
    ]


def test_analytics_summary_labels_time_saved_as_estimate(settings) -> None:
    store = Store(settings.data_path)
    _seed_tickets(store)
    service = SmartActionService(store, settings)
    first = service.invoke("ticket-triage", {"ticket_id": "TCK-1001"}, "tech")
    second = service.invoke("ticket-triage", {"ticket_id": "TCK-1002"}, "tech")
    assert first.status == second.status == "success"

    summary = cast(dict[str, Any], build_analytics_summary(store, {"ticket-triage": 4}))

    time_saved = summary["estimated_minutes_saved"]
    assert time_saved["estimate"] is True
    assert time_saved["minutes"] == 8
    assert time_saved["derivation"] == ESTIMATED_MINUTES_SAVED_DERIVATION
    # Failures must appear in the counts, never silently omitted.
    service.invoke("ticket-triage", {"ticket_id": "NOPE"}, "tech")
    with_failures = cast(dict[str, Any], build_analytics_summary(store, {"ticket-triage": 4}))
    assert {item["status"] for item in with_failures["failures_by_status"]} == {"failed"}
    assert with_failures["estimated_minutes_saved"]["minutes"] == 8


def test_analytics_summary_filters_date_range(settings) -> None:
    store = Store(settings.data_path)
    _seed_executions(store)

    summary = cast(dict[str, Any], build_analytics_summary(
        store, {}, started_from="2026-08-02", started_to="2026-08-02"
    ))

    assert summary["success_rate"]["total"] == 1
    assert summary["executions_over_time"] == [
        {"date": "2026-08-02", "count": 1, "succeeded": 0, "not_succeeded": 1}
    ]
    assert summary["failures_by_status"] == [{"status": "pending_approval", "count": 1}]


def test_analytics_summary_scopes_to_client(settings) -> None:
    store = Store(settings.data_path)
    _seed_executions(store)

    acme = cast(dict[str, Any], build_analytics_summary(store, {}, client_id="acme"))
    beta = cast(dict[str, Any], build_analytics_summary(store, {}, client_id="beta"))

    assert acme["success_rate"] == {"total": 2, "succeeded": 1, "rate": 0.5}
    assert beta["success_rate"] == {"total": 1, "succeeded": 0, "rate": 0.0}
    assert beta["failures_by_status"] == [{"status": "pending_approval", "count": 1}]


def test_analytics_summary_aggregates_configured_model_cost_by_client(settings) -> None:
    store = Store(settings.data_path)
    store.create_execution_run(
        "smart_action", 1, "tech", "completed", "2026-08-01T09:00:00+00:00",
        "2026-08-01T09:01:00+00:00", "api", client_id="acme",
        metadata={
            "usage_status": "reported",
            "input_tokens": 1000,
            "output_tokens": 500,
            "cost_status": "configured_estimate",
            "cost_usd": 0.0125,
        },
    )
    store.create_execution_run(
        "smart_action", 2, "tech", "completed", "2026-08-01T09:00:00+00:00",
        "2026-08-01T09:01:00+00:00", "api", client_id="beta",
        metadata={
            "usage_status": "reported",
            "input_tokens": 9000,
            "output_tokens": 1000,
            "cost_status": "not_configured",
            "cost_usd": None,
        },
    )

    summary = cast(dict[str, Any], build_analytics_summary(store, {}, client_id="acme"))

    assert summary["model_usage"] == {
        "runs_with_usage": 1,
        "runs_with_cost": 1,
        "input_tokens": 1000,
        "output_tokens": 500,
        "estimated_cost_usd": 0.0125,
        "estimate": True,
        "derivation": MODEL_COST_DERIVATION,
    }
    beta = cast(dict[str, Any], build_analytics_summary(store, {}, client_id="beta"))
    assert beta["model_usage"]["runs_with_cost"] == 0
    assert beta["model_usage"]["input_tokens"] == 9000


def test_analytics_summary_empty_range_is_zeroed(settings) -> None:
    store = Store(settings.data_path)

    summary = cast(
        dict[str, Any],
        build_analytics_summary(store, {}, started_from="2026-01-01", started_to="2026-01-02"),
    )

    assert summary["executions_over_time"] == []
    assert summary["success_rate"] == {"total": 0, "succeeded": 0, "rate": 0.0}
    assert summary["failures_by_status"] == []
    assert summary["estimated_minutes_saved"]["minutes"] == 0
    assert summary["estimated_minutes_saved"]["estimate"] is True
    assert summary["activity_breakdown"] == []


def test_analytics_summary_reports_approvals_tickets_and_workflow_views(settings, tmp_path) -> None:
    store = Store(settings.data_path)
    ticket_file = tmp_path / "tickets.json"
    ticket_file.write_text(
        json.dumps(
            [
                {
                    "id": "TCK-OPEN",
                    "client": "Acme",
                    "subject": "Open ticket",
                    "body": "Needs work",
                    "priority": "normal",
                    "status": "open",
                    "client_id": "acme",
                },
                {
                    "id": "TCK-RESOLVED",
                    "client": "Acme",
                    "subject": "Resolved ticket",
                    "body": "Fixed",
                    "priority": "normal",
                    "status": "resolved",
                    "client_id": "acme",
                },
                {
                    "id": "TCK-BETA",
                    "client": "Beta",
                    "subject": "Other tenant",
                    "body": "Private",
                    "priority": "normal",
                    "status": "closed",
                    "client_id": "beta",
                },
            ]
        ),
        encoding="utf-8",
    )
    store.ingest_ticket_file(ticket_file)

    workflow = store.create_workflow_run(
        "ticket-triage", "TCK-OPEN", "completed", "done", client_id="acme"
    )
    store.create_execution_run(
        "workflow", workflow.id, "tech", "completed", "2026-08-08T09:00:00+00:00",
        "2026-08-08T09:01:00+00:00", "api", client_id="acme",
    )
    agent = store.create_agent_run(
        "ticket-agent", "TCK-RESOLVED", "tech", "completed", 1, {}, client_id="acme"
    )
    store.create_execution_run(
        "agent", agent.id, "tech", "completed", "2026-08-08T09:02:00+00:00",
        "2026-08-08T09:03:00+00:00", "event", client_id="acme",
    )
    beta_workflow = store.create_workflow_run(
        "beta-template", "TCK-BETA", "completed", "done", client_id="beta"
    )
    store.create_execution_run(
        "workflow", beta_workflow.id, "tech", "completed", "2026-08-08T09:04:00+00:00",
        "2026-08-08T09:05:00+00:00", "api", client_id="beta",
    )

    approved = store.create_approval_request("TCK-OPEN", "test.write", {}, client_id="acme")
    rejected = store.create_approval_request("TCK-RESOLVED", "test.write", {}, client_id="acme")
    store.create_approval_request("TCK-OPEN", "test.write", {}, client_id="acme")
    store.update_approval_request(approved.id or 0, "approved", approver_id="admin")
    store.update_approval_request(rejected.id or 0, "rejected", approver_id="admin")

    summary = cast(dict[str, Any], build_analytics_summary(store, {}, client_id="acme"))

    assert summary["approval_rate"] == {
        "requested": 3,
        "decided": 2,
        "approved": 1,
        "rejected": 1,
        "pending": 1,
        "rate": 0.5,
        "derivation": summary["approval_rate"]["derivation"],
    }
    assert summary["ticket_metrics"]["touched"] == 2
    assert summary["ticket_metrics"]["resolved"] == 1
    assert summary["ticket_metrics"]["resolution_rate"] == 0.5
    assert summary["ticket_metrics"]["historical_resolution"] == {
        "resolved_with_history": 0,
        "with_duration": 0,
        "average_minutes": None,
        "derivation": summary["ticket_metrics"]["historical_resolution"]["derivation"],
    }
    assert summary["activity_by_workflow"] == [
        {
            "run_kind": "agent",
            "workflow_id": "ticket-agent",
            "total": 1,
            "succeeded": 1,
            "status_counts": [{"status": "completed", "count": 1}],
        },
        {
            "run_kind": "workflow",
            "workflow_id": "ticket-triage",
            "total": 1,
            "succeeded": 1,
            "status_counts": [{"status": "completed", "count": 1}],
        },
    ]


def test_ticket_lifecycle_metrics_use_explicit_status_transitions(settings, tmp_path) -> None:
    store = Store(settings.data_path)
    ticket_file = tmp_path / "ticket.json"
    ticket_file.write_text(
        json.dumps([{
            "id": "TCK-LIFECYCLE",
            "client": "Acme",
            "subject": "Lifecycle",
            "body": "Track this ticket",
            "priority": "normal",
            "status": "open",
            "client_id": "acme",
            "created_at": "2026-08-08T10:00:00+00:00",
            "updated_at": "2026-08-08T10:00:00+00:00",
        }]),
        encoding="utf-8",
    )
    store.ingest_ticket_file(ticket_file)
    ticket_file.write_text(
        json.dumps([{
            "id": "TCK-LIFECYCLE",
            "client": "Acme",
            "subject": "Lifecycle",
            "body": "Track this ticket",
            "priority": "normal",
            "status": "resolved",
            "created_at": "2026-08-08T10:00:00+00:00",
            "updated_at": "2026-08-08T11:00:00+00:00",
        }]),
        encoding="utf-8",
    )
    store.ingest_ticket_file(ticket_file)
    store.ingest_ticket_file(ticket_file)

    history = store.list_ticket_status_history("TCK-LIFECYCLE", client_id="acme")
    assert [(item["from_status"], item["to_status"], item["source"]) for item in history] == [
        ("", "open", "ticket_ingest"),
        ("open", "resolved", "ticket_ingest"),
    ]
    assert store.list_ticket_status_history("TCK-LIFECYCLE") == history
    summary = cast(
        dict[str, Any],
        build_analytics_summary(
            store,
            {},
            started_from="2026-08-08",
            started_to="2026-08-08",
            client_id="acme",
        ),
    )
    assert summary["ticket_metrics"]["historical_resolution"]["resolved_with_history"] == 1
    assert summary["ticket_metrics"]["historical_resolution"]["with_duration"] == 1
    assert summary["ticket_metrics"]["historical_resolution"]["average_minutes"] == 60.0


def test_ticket_lifecycle_metrics_bound_duration_and_deduplicate_reopened_tickets(settings) -> None:
    store = Store(settings.data_path)
    store.ingest_ticket_file(
        Path("examples/sample_tickets/tickets.json")
    )
    with store._connect() as connection:  # noqa: SLF001
        connection.execute(
            "update tickets set created_at = ?, updated_at = ? where id = ?",
            ("2026-08-08T10:00:00", "2026-08-08T10:00:00", "TCK-1001"),
        )
        connection.execute(
            """
            insert into ticket_status_history
              (ticket_id, client_id, from_status, to_status, changed_at, source)
            values (?, ?, ?, ?, ?, ?)
            """,
            ("TCK-1001", None, "open", "resolved", "2026-08-08T11:00:00", "test"),
        )
        connection.execute(
            """
            insert into ticket_status_history
              (ticket_id, client_id, from_status, to_status, changed_at, source)
            values (?, ?, ?, ?, ?, ?)
            """,
            ("TCK-1001", None, "resolved", "open", "2026-08-08T12:00:00", "test"),
        )
        connection.execute(
            """
            insert into ticket_status_history
              (ticket_id, client_id, from_status, to_status, changed_at, source)
            values (?, ?, ?, ?, ?, ?)
            """,
            ("TCK-1001", None, "open", "closed", "2026-08-08T13:00:00", "test"),
        )
    metrics = store.ticket_lifecycle_metrics("2026-08-08", "2026-08-08")
    assert metrics == {
        "resolved_with_history": 1,
        "with_duration": 1,
        "average_minutes": 60.0,
    }
