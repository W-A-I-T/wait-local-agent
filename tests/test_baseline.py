from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest

from packs.microsoft_admin.models import MicrosoftAdminProvider
from wait_local_agent import baseline as baseline_module
from wait_local_agent.baseline import (
    BaselineService,
    _aggregate_coverage,
    _coverage_status,
    _matching_approval,
    _safe_json_object,
    compare_normalized_sections,
    compose_baseline,
    diff_baseline,
    normalized_hash,
)
from wait_local_agent.client_scope import BoundClients
from wait_local_agent.m365_graph import M365GraphClient
from wait_local_agent.models import ApprovalRequest, ApprovalStatus, ClientBaseline
from wait_local_agent.scheduler import SchedulerManager
from wait_local_agent.store import Store


def _sections(**summary: object) -> dict[str, object]:
    return {
        "microsoft_posture": {"summary": summary},
        "environment_graph": {"entity_type_counts": {"device": 1}},
        "canonical_assets": {"asset_type_counts": {"server": 1}},
        "connector_readiness": {"instances": {"m365": "ready"}},
    }


def _coverage(status: str = "ready") -> dict[str, object]:
    return {
        "microsoft_posture": status,
        "environment_graph": "ready",
        "canonical_assets": "ready",
        "connector_readiness": "ready",
    }


def test_baseline_versions_and_acceptance_are_atomic(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.db")
    store.create_client("acme", "Acme")

    first = store.create_client_baseline(
        "acme",
        generated_at="2026-09-01T00:00:00+00:00",
        source_coverage=_coverage(),
        summary={"hash": "first"},
        sections=_sections(noncompliant_devices=2),
    )
    second = store.create_client_baseline(
        "acme",
        generated_at="2026-09-01T01:00:00+00:00",
        source_coverage=_coverage(),
        summary={"hash": "second"},
        sections=_sections(noncompliant_devices=1),
    )

    assert (first.version, first.accepted) == (1, True)
    assert (second.version, second.accepted) == (2, False)
    accepted = store.accept_client_baseline("acme", 2)
    assert accepted is not None and accepted.accepted
    versions = store.list_client_baselines("acme")
    assert [item.version for item in versions] == [2, 1]
    assert [item.accepted for item in versions] == [True, False]
    assert store.get_accepted_client_baseline("acme") == accepted


def test_normalized_diff_is_order_insensitive_and_applies_polarity() -> None:
    before = _sections(noncompliant_devices=2, secure_score_percent=70)
    after = _sections(secure_score_percent=80, noncompliant_devices=0)
    after["canonical_assets"] = {"asset_type_counts": {"server": 1}, "assets": {"a": {"asset_type": "server"}}}
    findings = compare_normalized_sections(before, after, _coverage(), _coverage())
    classifications = {finding["path"]: finding["classification"] for finding in findings}
    assert classifications["microsoft_posture.summary.noncompliant_devices"] == "resolved"
    assert classifications["microsoft_posture.summary.secure_score_percent"] == "improved"
    assert classifications["canonical_assets.assets.a"] == "new"


@pytest.mark.parametrize("status", ["blocked", "not_configured"])
def test_unavailable_sources_are_not_compared_as_zeroes(status: str) -> None:
    findings = compare_normalized_sections(
        _sections(noncompliant_devices=4),
        _sections(noncompliant_devices=0),
        _coverage(status),
        _coverage(status),
    )
    assert any(
        finding == {
            "domain": "microsoft_posture",
            "path": "microsoft_posture",
            "classification": "verification_unavailable",
            "previous": status,
            "current": status,
        }
        for finding in findings
    )


def test_service_records_not_configured_coverage_and_never_reports_healthy_zero_drift(
    tmp_path: Path,
) -> None:
    store = Store(tmp_path / "coverage.db")
    store.create_client("acme", "Acme")
    service = BaselineService(store)

    baseline = service.create_baseline("acme")
    coverage = json.loads(baseline.source_coverage_json)
    assert coverage["microsoft_posture"] == "not_configured"

    result = service.diff_baseline("acme")
    assert result["unchanged"] is False
    findings = cast(list[dict[str, object]], result["findings"])
    assert any(item["classification"] == "verification_unavailable" for item in findings)


def test_blocked_source_coverage_is_persisted_and_excluded_from_numeric_drift(tmp_path: Path) -> None:
    store = Store(tmp_path / "blocked-coverage.db")
    store.create_client("acme", "Acme")
    baseline = store.create_client_baseline(
        "acme",
        generated_at="2026-09-01T00:00:00+00:00",
        source_coverage=_coverage("blocked"),
        summary={"hash": "blocked"},
        sections=_sections(noncompliant_devices=4),
    )

    assert json.loads(baseline.source_coverage_json)["microsoft_posture"] == "blocked"
    result = BaselineService(store).diff_baseline("acme")
    findings = cast(list[dict[str, object]], result["findings"])
    microsoft_finding = next(item for item in findings if item["domain"] == "microsoft_posture")
    assert microsoft_finding["classification"] == "verification_unavailable"
    assert microsoft_finding["previous"] == "blocked"


@pytest.mark.parametrize(
    ("before", "after", "classification", "path"),
    [
        ({}, {"new_control": "enabled"}, "new", "microsoft_posture.summary.new_control"),
        ({"removed_control": "enabled"}, {}, "removed", "microsoft_posture.summary.removed_control"),
        ({"mode": "old"}, {"mode": "new"}, "changed", "microsoft_posture.summary.mode"),
        (
            {"noncompliant_devices": 1},
            {"noncompliant_devices": 3},
            "worsened",
            "microsoft_posture.summary.noncompliant_devices",
        ),
        (
            {"noncompliant_devices": 3},
            {"noncompliant_devices": 1},
            "improved",
            "microsoft_posture.summary.noncompliant_devices",
        ),
        (
            {"noncompliant_devices": 3},
            {"noncompliant_devices": 0},
            "resolved",
            "microsoft_posture.summary.noncompliant_devices",
        ),
    ],
)
def test_normalized_drift_matrix(
    before: dict[str, object],
    after: dict[str, object],
    classification: str,
    path: str,
) -> None:
    findings = compare_normalized_sections(_sections(**before), _sections(**after), _coverage(), _coverage())

    assert {(finding["path"], finding["classification"]) for finding in findings} == {(path, classification)}


def test_normalized_hash_short_circuits_order_only_list_changes() -> None:
    before = _sections(
        tags=["zeta", "alpha"],
        controls=[{"id": "two", "enabled": True}, {"id": "one", "enabled": False}],
    )
    after = _sections(
        controls=[{"enabled": False, "id": "one"}, {"enabled": True, "id": "two"}],
        tags=["alpha", "zeta"],
    )

    assert normalized_hash(before) == normalized_hash(after)
    assert compare_normalized_sections(before, after, _coverage(), _coverage()) == []


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("ready", "ready"),
        ("configured", "partial"),
        ("syncing", "partial"),
        ("degraded", "partial"),
        ("inactive", "not_configured"),
        ("disabled", "not_configured"),
        ("missing", "not_configured"),
        ("not_run", "not_configured"),
        ("unexpected", "failed"),
    ],
)
def test_coverage_status_normalizes_provider_and_connector_states(raw: str, expected: str) -> None:
    assert _coverage_status(raw) == expected


def test_baseline_store_collects_graph_assets_and_all_connector_cursor_states(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = Store(tmp_path / "sections.db")
    store.create_client("acme", "Acme")
    ref = store.upsert_entity_ref(
        "acme",
        entity_type="device",
        source_system="inventory",
        external_id="device-1",
        provenance="test",
    )
    asset = store.upsert_canonical_asset(
        canonical_id="asset-1",
        asset_type="endpoint",
        display_name="Laptop",
        attributes={},
        client_id="acme",
    )
    ready_without_cursor = store.create_connector_instance("m365", "No cursor", client_id="acme")
    failed_cursor = store.create_connector_instance("m365", "Failed", client_id="acme")
    partial_cursor = store.create_connector_instance("m365", "Partial", client_id="acme")
    inactive = store.create_connector_instance("m365", "Inactive", client_id="acme")
    store.upsert_sync_cursor(failed_cursor.connector_instance_id, "tickets", cursor_value=None, status="failed")
    store.upsert_sync_cursor(partial_cursor.connector_instance_id, "tickets", cursor_value=None, status="degraded")

    instances = [
        replace(ready_without_cursor, status="ready"),
        replace(failed_cursor, status="ready"),
        replace(partial_cursor, status="ready"),
        inactive,
    ]
    monkeypatch.setattr(store, "list_connector_instances", lambda: instances)

    snapshot = BaselineService(store).compose_baseline(" acme ")
    sections = cast(dict[str, object], snapshot["sections"])
    graph = cast(dict[str, object], sections["environment_graph"])
    assets = cast(dict[str, object], sections["canonical_assets"])
    readiness = cast(dict[str, object], sections["connector_readiness"])

    assert graph["entity_type_counts"] == {ref.entity_type: 1}
    assert assets["asset_type_counts"] == {asset.asset_type: 1}
    asset_map = cast(dict[str, dict[str, object]], assets["assets"])
    assert asset_map[asset.canonical_id]["asset_type"] == "endpoint"
    assert cast(dict[str, object], readiness["instances"]) == {
        ready_without_cursor.connector_instance_id: "ready",
        failed_cursor.connector_instance_id: "failed",
        partial_cursor.connector_instance_id: "partial",
        inactive.connector_instance_id: "not_configured",
    }
    cursor_keys = cast(dict[str, object], readiness["cursors"])
    assert set(cursor_keys) == {
        f"{failed_cursor.connector_instance_id}:tickets",
        f"{partial_cursor.connector_instance_id}:tickets",
    }


def test_baseline_provider_failures_and_malformed_status_payload_are_coverage_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = Store(tmp_path / "provider-failure.db")
    store.create_client("acme", "Acme")
    with pytest.raises(ValueError, match="client_id"):
        BaselineService(store).compose_baseline(" ")

    def fail_summary(*args: object, **kwargs: object) -> dict[str, object]:
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(baseline_module, "build_dashboard_summary", fail_summary)
    failed = BaselineService(
        store,
        microsoft_provider_factory=lambda _client_id: cast(MicrosoftAdminProvider, object()),
        core_client_factory=lambda _client_id: cast(M365GraphClient, object()),
    ).compose_baseline("acme")
    assert cast(dict[str, object], failed["source_coverage"])["microsoft_posture"] == "failed"
    assert cast(dict[str, object], failed["summary"])["microsoft_summary"] == {}

    monkeypatch.setattr(
        baseline_module,
        "build_dashboard_summary",
        lambda *_args, **_kwargs: {"summary": {"noncompliant_devices": 4}, "source_statuses": []},
    )
    malformed = BaselineService(
        store,
        microsoft_provider_factory=lambda _client_id: cast(MicrosoftAdminProvider, object()),
        core_client_factory=lambda _client_id: cast(M365GraphClient, object()),
    ).compose_baseline("acme")
    assert cast(dict[str, object], malformed["source_coverage"])["microsoft_posture"] == "not_configured"
    assert cast(dict[str, object], malformed["sections"])["microsoft_posture"] == {"summary": {}}

    monkeypatch.setattr(
        baseline_module,
        "build_dashboard_summary",
        lambda *_args, **_kwargs: {
            "summary": {"managed_devices": 2, "intune_apps": 3},
            "source_statuses": {"managed_devices": "ready", "intune_apps": "configured"},
        },
    )
    partial = BaselineService(
        store,
        microsoft_provider_factory=lambda _client_id: cast(MicrosoftAdminProvider, object()),
        core_client_factory=lambda _client_id: cast(M365GraphClient, object()),
    ).compose_baseline("acme")
    assert cast(dict[str, object], partial["source_coverage"]) == {
        "microsoft:managed_devices": "ready",
        "microsoft:intune_apps": "partial",
        "microsoft_posture": "partial",
        "environment_graph": "ready",
        "canonical_assets": "ready",
        "connector_readiness": "not_configured",
    }
    assert cast(dict[str, object], partial["summary"])["microsoft_summary"] == {"managed_devices": 2}


def test_baseline_fallback_and_functional_entry_points(tmp_path: Path) -> None:
    store = Store(tmp_path / "entry-points.db")
    store.create_client("acme", "Acme")
    baseline = store.create_client_baseline(
        "acme",
        generated_at="2026-09-01T00:00:00+00:00",
        source_coverage=_coverage(),
        summary={"hash": "before"},
        sections=_sections(noncompliant_devices=1),
    )
    with store._connect() as connection:  # noqa: SLF001
        connection.execute("update client_baselines set accepted = 0 where baseline_id = ?", (baseline.baseline_id,))

    composed = compose_baseline("acme", store=store)
    result = diff_baseline("acme", store=store)
    assert composed["client_id"] == "acme"
    assert result["baseline_version"] == baseline.version


def test_baseline_comparison_covers_empty_coverage_entity_maps_and_unknown_numeric_polarity() -> None:
    before = _sections(unknown_metric=1, removed_map={"entry": {"value": 1}})
    after = _sections(unknown_metric=2)
    cast(dict[str, object], before["canonical_assets"])["assets"] = {
        "changed": {"asset_type": "server"},
        "removed": {"asset_type": "laptop"},
        "same": {"asset_type": "server"},
    }
    cast(dict[str, object], after["canonical_assets"])["assets"] = {
        "changed": {"asset_type": "endpoint"},
        "new": {"asset_type": "server"},
        "same": {"asset_type": "server"},
    }

    findings = compare_normalized_sections(before, after, _coverage(), _coverage())
    classifications = {finding["path"]: finding["classification"] for finding in findings}
    assert classifications["microsoft_posture.summary.unknown_metric"] == "changed"
    assert classifications["microsoft_posture.summary.removed_map.entry"] == "removed"
    assert classifications["canonical_assets.assets.changed"] == "changed"
    assert classifications["canonical_assets.assets.new"] == "new"
    assert classifications["canonical_assets.assets.removed"] == "removed"

    unavailable = compare_normalized_sections(
        before,
        after,
        {"unrelated": "ready"},
        {"unrelated": "ready"},
    )
    assert {finding["domain"] for finding in unavailable} == {
        "microsoft_posture",
        "environment_graph",
        "canonical_assets",
        "connector_readiness",
    }


@pytest.mark.parametrize(
    ("statuses", "expected"),
    [
        ([], "not_configured"),
        (["ready"], "ready"),
        (["failed"], "failed"),
        (["blocked"], "blocked"),
        (["partial"], "partial"),
    ],
)
def test_aggregate_coverage_returns_each_terminal_state(statuses: list[str], expected: str) -> None:
    assert _aggregate_coverage(cast(list[object], statuses)) == expected


def test_safe_json_and_correlation_parsing_cover_invalid_and_boundary_timestamps(tmp_path: Path) -> None:
    assert _safe_json_object("not-json") == {}
    assert _safe_json_object("[]") == {}

    def approval(
        request_id: int | None,
        *,
        status: str = "approved",
        executed_at: str = "",
        action_type: str = "m365.device.update",
    ) -> ApprovalRequest:
        return ApprovalRequest(
            id=request_id,
            subject_id="subject",
            action_type=action_type,
            payload_json=json.dumps({"resource": "device"}),
            status=cast(ApprovalStatus, status),
            comment="",
            created_at="2026-09-01T00:00:00+00:00",
            updated_at="2026-09-01T00:00:00+00:00",
            executed_at=executed_at,
        )

    start = datetime(2026, 9, 1, tzinfo=UTC)
    end = start + timedelta(minutes=10)
    at_start = approval(1, executed_at=start.isoformat())
    at_end = approval(2, executed_at=end.isoformat())
    naive = approval(3, executed_at="2026-09-01T00:05:00")
    assert _matching_approval([at_start], "microsoft_posture", start, end) == at_start
    assert _matching_approval([at_end], "microsoft_posture", start, end) == at_end
    assert _matching_approval([naive], "microsoft_posture", start, end) == naive
    assert _matching_approval(
        [
            approval(None, executed_at=start.isoformat()),
            approval(4, status="pending", executed_at=start.isoformat()),
            approval(5, executed_at="bad timestamp"),
            approval(6, executed_at=(start - timedelta(seconds=1)).isoformat()),
        ],
        "microsoft_posture",
        start,
        end,
    ) is None

    store = Store(tmp_path / "correlation-parse.db")
    service = BaselineService(store)
    finding = cast(list[dict[str, object]], [{"domain": "microsoft_posture"}])
    invalid = ClientBaseline("id", "acme", 1, "bad timestamp", True, "{}", "{}", "{}")
    service._correlate_findings(finding, invalid, "acme", now=end)  # noqa: SLF001
    assert finding[0]["correlation"] == "no_matching_approved_change"
    naive_baseline = ClientBaseline("id", "acme", 1, "2026-09-01T00:00:00", True, "{}", "{}", "{}")
    service._correlate_findings(finding, naive_baseline, "acme", now=end)  # noqa: SLF001


@pytest.mark.parametrize(
    ("approval_client", "expected_correlation"),
    [
        ("acme", "expected_change"),
        (None, "no_matching_approved_change"),
        ("beta", "no_matching_approved_change"),
    ],
)
def test_drift_correlation_is_time_bounded_and_client_isolated(
    tmp_path: Path,
    approval_client: str | None,
    expected_correlation: str,
) -> None:
    store = Store(tmp_path / f"correlation-{approval_client or 'none'}.db")
    store.create_client("acme", "Acme")
    if approval_client == "beta":
        store.create_client("beta", "Beta")
    baseline_time = datetime.now(UTC) - timedelta(hours=1)
    store.create_client_baseline(
        "acme",
        generated_at=baseline_time.isoformat(),
        source_coverage=_coverage(),
        summary={"hash": "before"},
        sections=_sections(noncompliant_devices=1),
    )

    approval_id: int | None = None
    if approval_client is not None:
        approval = store.create_approval_request(
            "change-subject",
            "m365.device.update",
            {"resource": "device"},
            client_id=approval_client,
        )
        approval_id = approval.id
        store.update_approval_request(approval.id or 0, "approved", approver_id="operator")
        store.record_approval_execution(
            approval.id or 0,
            status="succeeded",
            message="completed",
            result={"status": "succeeded"},
        )

    result = BaselineService(store).diff_baseline("acme", now=datetime.now(UTC) + timedelta(minutes=1))
    findings = cast(list[dict[str, object]], result["findings"])
    microsoft_finding = next(item for item in findings if item["domain"] == "microsoft_posture")
    assert microsoft_finding["correlation"] == expected_correlation
    if expected_correlation == "expected_change":
        assert microsoft_finding["approval_id"] == approval_id
    else:
        assert "approval_id" not in microsoft_finding


def test_baseline_store_crud_fails_closed_for_wrong_client_scope(tmp_path: Path) -> None:
    store = Store(tmp_path / "scope.db")
    store.create_client("acme", "Acme")
    store.create_client("beta", "Beta")
    store.create_client_baseline(
        "acme",
        generated_at="2026-09-01T00:00:00+00:00",
        source_coverage=_coverage(),
        summary={"hash": "acme"},
        sections=_sections(),
    )
    store.create_client_baseline(
        "beta",
        generated_at="2026-09-01T00:00:00+00:00",
        source_coverage=_coverage(),
        summary={"hash": "beta-1"},
        sections=_sections(),
    )
    beta_second = store.create_client_baseline(
        "beta",
        generated_at="2026-09-01T01:00:00+00:00",
        source_coverage=_coverage(),
        summary={"hash": "beta-2"},
        sections=_sections(),
    )
    acme_scope = BoundClients(frozenset({"acme"}))

    assert store.get_client_baseline(acme_scope, beta_second.version) is None
    assert store.get_accepted_client_baseline(acme_scope) is not None
    assert [item.client_id for item in store.list_client_baselines(acme_scope)] == ["acme"]
    assert store.accept_client_baseline(acme_scope, beta_second.version) is None
    assert store.get_client_baseline("beta", beta_second.version) is not None
    beta_accepted = store.get_accepted_client_baseline("beta")
    assert beta_accepted is not None
    assert beta_accepted.version == 1


def test_service_persists_only_normalized_sections(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.db")
    store.create_client("acme", "Acme")
    baseline = BaselineService(store).create_baseline("acme")
    sections = json.loads(baseline.sections_json)
    assert set(sections) == {"microsoft_posture", "environment_graph", "canonical_assets", "connector_readiness"}
    assert "access_token" not in baseline.sections_json


def test_baseline_snapshot_scheduler_job_is_validated_triggered_and_audited(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.db")
    store.create_client("acme", "Acme")
    manager = SchedulerManager(
        store,
        enabled=False,
        baseline_snapshot_runner=lambda client_id: BaselineService(store).create_baseline(client_id),
    )
    job = manager.register(
        "",
        "0 9 * * *",
        {"client_id": "acme"},
        job_kind="baseline_snapshot",
        entity_id="acme",
    )
    asyncio.run(manager._run_job(job))  # noqa: SLF001
    assert store.list_client_baselines("acme")[0].version == 1
    assert any(event.event_type == "scheduled_job.baseline_snapshot" for event in store.list_audit_events("acme"))
