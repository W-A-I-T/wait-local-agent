from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from wait_local_agent.observability import (
    ESTIMATED_MINUTES_SAVED_DERIVATION,
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
