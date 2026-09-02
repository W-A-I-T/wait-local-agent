from __future__ import annotations

from dataclasses import replace
from typing import Any, cast

import pytest

from wait_local_agent.models import CanonicalAsset, ConnectorInstance
from wait_local_agent.rmm import (
    LocalCollectorRmmAdapter,
    RmmAlert,
    RmmDevice,
    RmmProviderResolutionError,
    RmmScript,
    RmmScriptExecution,
    RmmScriptPreview,
    rmm_provider_from_settings,
)
from wait_local_agent.smart_actions import (
    ActionContext,
    NSightAntivirusThreatsAction,
    NSightAssetDetailsAction,
    NSightBackupHistoryAction,
    NSightBackupSessionsAction,
    NSightCheckInventoryAction,
    NSightMonitoringDetailsAction,
    NSightOutageLookupAction,
    NSightPatchApproveAction,
    NSightPatchLookupAction,
    NSightPatchPolicyAction,
    NSightPatchReprocessAction,
    NSightPerformanceHistoryAction,
    NSightRunTaskNowAction,
    RmmAlertLookupAction,
    RmmScriptCatalogAction,
    RmmScriptExecuteAction,
    RmmScriptExecutionLookupAction,
    RmmScriptPreviewAction,
)
from wait_local_agent.store import Store


class _Provider:
    adapter_id = "fake-rmm"

    def list_devices(self, client_id=None):
        return [RmmDevice("device-1", "Workstation 1")]

    def list_alerts(self, client_id=None):
        return [RmmAlert("alert-1", "device-1", "high", "Disk full")]

    def list_scripts(self, client_id=None):
        return [RmmScript("script-1", "Collect logs", "Collect bounded logs")]

    def preview_script(self, script_id, device_id, arguments, *, client_id=None):
        return RmmScriptPreview(script_id, device_id, arguments, "preview", "ready")

    def execute_script(self, script_id, device_id, arguments, *, client_id=None):
        return RmmScriptExecution(script_id, device_id, "queued", "queued", "exec-1")

    def get_execution(self, execution_id, *, client_id=None):
        return RmmScriptExecution("script-1", "device-1", "succeeded", "done", execution_id)


class _NSightProvider(_Provider):
    adapter_id = "n-sight"

    def list_patches(self, device_id, *, client_id=None):
        assert client_id == "acme"
        return [{"patch_id": 681806, "status_label": "Installed", "device_id": device_id}]

    def list_antivirus_threats(self, device_id, *, client_id=None):
        assert client_id == "acme"
        return [{"name": "Example.Malware", "category": "Trojan", "device_id": device_id}]

    def list_outages(self, device_id, *, client_id=None):
        assert client_id == "acme"
        return [{"outage_id": 103725102, "state": "OPEN", "device_id": device_id}]

    def list_backup_sessions(self, device_id, *, client_id=None):
        assert client_id == "acme"
        return [{"session_id": 12345, "status": "COMPLETED", "device_id": device_id}]

    def list_backup_history(self, device_id, *, client_id=None):
        assert client_id == "acme"
        return {
            "checks": ["Backup Check - Example"],
            "days": [{"date": "2026-08-10", "status": "PASS"}],
        }

    def list_checks(self, device_id, *, client_id=None):
        assert client_id == "acme"
        return [
            {
                "check_id": 1304847,
                "check_type": 1023,
                "description": "Automated Task",
                "device_id": device_id,
            }
        ]

    def run_task_now(self, device_id, check_id, *, client_id=None):
        assert client_id == "acme"
        return {
            "status": "accepted",
            "device_id": device_id,
            "check_id": check_id,
            "minutes_until_run": 15,
            "message": "15 minutes",
        }

    def list_performance_history(self, device_id, *, client_id=None):
        assert client_id == "acme"
        return [
            {
                "category": "cpu_load",
                "check_id": 102,
                "history": [{"start": "2026-08-10 10:00:00"}],
                "device_id": device_id,
            }
        ]

    def list_asset_details(self, device_id, *, client_id=None):
        assert client_id == "acme"
        return {
            "details": {"os": "Linux"},
            "hardware": [{"hardware_id": 123456, "name": "Ethernet Adapter"}],
            "software": [{"software_id": 654321, "name": "Agent"}],
        }

    def list_monitoring_details(self, device_id, *, client_id=None):
        assert client_id == "acme"
        return {
            "device": {"id": 49324, "type": "server"},
            "checks": [{"check_id": 2089484}],
            "outages": [{"id": 103725102}],
            "notes": [{"note_id": 117575, "note": "Maintenance complete"}],
            "features": {"patch": True},
        }

    def approve_patches(self, device_id, patch_ids, *, client_id=None):
        assert client_id == "acme"
        return {
            "status": "accepted",
            "message": "approved",
            "device_id": device_id,
            "patch_ids": patch_ids,
        }

    def reprocess_patches(self, device_id, patch_ids, *, client_id=None):
        assert client_id == "acme"
        return {
            "status": "accepted",
            "message": "reprocessed",
            "device_id": device_id,
            "patch_ids": patch_ids,
        }

    def apply_patch_policy(self, device_id, patch_ids, operation, *, client_id=None):
        assert client_id == "acme"
        return {
            "status": "accepted",
            "operation": operation,
            "message": "policy applied",
            "device_id": device_id,
            "patch_ids": patch_ids,
        }


class _FailingNSightProvider(_NSightProvider):
    def approve_patches(self, device_id, patch_ids, *, client_id=None):
        raise RuntimeError("provider failure")


class _FailingTaskNSightProvider(_NSightProvider):
    def run_task_now(self, device_id, check_id, *, client_id=None):
        raise RuntimeError("provider failure")


class _MalformedTaskNSightProvider(_NSightProvider):
    def run_task_now(self, device_id, check_id, *, client_id=None):
        return []


class _RejectedTaskNSightProvider(_NSightProvider):
    def run_task_now(self, device_id, check_id, *, client_id=None):
        return {"status": "rejected", "device_id": device_id, "check_id": check_id}


class _MalformedNSightProvider(_NSightProvider):
    def approve_patches(self, device_id, patch_ids, *, client_id=None):
        return []


class _FailingBackupNSightProvider(_NSightProvider):
    def list_backup_sessions(self, device_id, *, client_id=None):
        raise RuntimeError("provider failure")


class _MalformedBackupNSightProvider(_NSightProvider):
    def list_backup_sessions(self, device_id, *, client_id=None):
        return {"session_id": 12345}


class _FailingBackupHistoryNSightProvider(_NSightProvider):
    def list_backup_history(self, device_id, *, client_id=None):
        raise RuntimeError("provider failure")


class _MalformedBackupHistoryNSightProvider(_NSightProvider):
    def list_backup_history(self, device_id, *, client_id=None):
        return {"checks": ["Backup Check - Example"], "days": "invalid"}


class _FailingCheckInventoryNSightProvider(_NSightProvider):
    def list_checks(self, device_id, *, client_id=None):
        raise RuntimeError("provider failure")


class _MalformedCheckInventoryNSightProvider(_NSightProvider):
    def list_checks(self, device_id, *, client_id=None):
        return {"check_id": 1304847}


class _FailingPerformanceHistoryNSightProvider(_NSightProvider):
    def list_performance_history(self, device_id, *, client_id=None):
        raise RuntimeError("provider failure")


class _MalformedPerformanceHistoryNSightProvider(_NSightProvider):
    def list_performance_history(self, device_id, *, client_id=None):
        return {"category": "cpu_load"}


class _FailingAssetDetailsNSightProvider(_NSightProvider):
    def list_asset_details(self, device_id, *, client_id=None):
        raise RuntimeError("provider failure")


class _MalformedAssetDetailsNSightProvider(_NSightProvider):
    def list_asset_details(self, device_id, *, client_id=None):
        return {"details": {}, "hardware": "invalid", "software": []}


class _FailingMonitoringDetailsNSightProvider(_NSightProvider):
    def list_monitoring_details(self, device_id, *, client_id=None):
        raise RuntimeError("provider failure")


class _MalformedMonitoringDetailsNSightProvider(_NSightProvider):
    def list_monitoring_details(self, device_id, *, client_id=None):
        return {"device": {}, "checks": ["invalid"], "outages": [], "notes": [], "features": {}}


class _NonDictMonitoringDetailsNSightProvider(_NSightProvider):
    def list_monitoring_details(self, device_id, *, client_id=None):
        return []


class _MalformedChecksBackupHistoryNSightProvider(_NSightProvider):
    def list_backup_history(self, device_id, *, client_id=None):
        return {"checks": ["Backup Check - Example", 123], "days": []}


def _context(settings, provider=None):
    return ActionContext(
        store=Store(settings.data_path),
        settings=settings,
        client_id="acme",
        rmm_provider=provider or LocalCollectorRmmAdapter(Store(settings.data_path)),
    )


def test_local_rmm_adapter_is_inventory_only(settings) -> None:
    adapter = LocalCollectorRmmAdapter(Store(settings.data_path))
    assert adapter.list_alerts("acme") == []
    assert adapter.list_scripts("acme") == []
    preview = adapter.preview_script("script-1", "device-1", {}, client_id="acme")
    execution = adapter.execute_script("script-1", "device-1", {}, client_id="acme")
    assert preview.status == "blocked"
    assert execution.status == "blocked"


def test_local_rmm_adapter_filters_malformed_and_non_endpoint_assets() -> None:
    class AssetStore:
        def list_canonical_assets(self, *, client_id):
            assert client_id == "acme"
            return [
                CanonicalAsset(
                    id=1,
                    canonical_id="endpoint-1",
                    asset_type="endpoint-agent",
                    display_name="Workstation 1",
                    attributes_json='{"category":"workstation","os":"Linux"}',
                    first_seen="",
                    last_seen="",
                ),
                CanonicalAsset(
                    id=2,
                    canonical_id="server-1",
                    asset_type="server",
                    display_name="Server 1",
                    attributes_json="{}",
                    first_seen="",
                    last_seen="",
                ),
                CanonicalAsset(
                    id=3,
                    canonical_id="bad-json",
                    asset_type="endpoint-agent",
                    display_name="Bad JSON",
                    attributes_json="not-json",
                    first_seen="",
                    last_seen="",
                ),
                CanonicalAsset(
                    id=4,
                    canonical_id="bad-shape",
                    asset_type="endpoint-agent",
                    display_name="Bad shape",
                    attributes_json="[]",
                    first_seen="",
                    last_seen="",
                ),
            ]

    devices = LocalCollectorRmmAdapter(cast(Store, AssetStore())).list_devices("acme")

    assert devices == [
        RmmDevice(
            device_id="endpoint-1",
            name="Workstation 1",
            category="workstation",
            attributes={"category": "workstation", "os": "Linux"},
        )
    ]


def test_local_rmm_adapter_reports_missing_execution_provider() -> None:
    adapter = LocalCollectorRmmAdapter(cast(Store, object()))

    result = adapter.get_execution("execution-1")

    assert result.status == "blocked"
    assert result.execution_id == "execution-1"
    assert result.message == "local collector RMM adapter has no execution provider"


def test_rmm_alerts_and_script_catalog_are_bounded(settings) -> None:
    provider = _Provider()
    alerts = RmmAlertLookupAction().run(_context(settings, provider), {})
    scripts = RmmScriptCatalogAction().run(_context(settings, provider), {})
    assert alerts.status == "success"
    assert cast(list[dict[str, object]], alerts.output["alerts"])[0]["alert_id"] == "alert-1"
    assert scripts.status == "success"
    assert cast(list[dict[str, object]], scripts.output["scripts"])[0]["script_id"] == "script-1"


def test_nsight_patch_lookup_uses_mapped_provider_surface(settings) -> None:
    result = NSightPatchLookupAction().run(
        _context(settings, _NSightProvider()), {"device_id": "server:49324"}
    )

    assert result.status == "success"
    assert result.output["count"] == 1
    assert cast(list[dict[str, object]], result.output["patches"])[0]["patch_id"] == 681806
    assert NSightPatchLookupAction().run(
        _context(settings, _Provider()), {"device_id": "server:49324"}
    ).error_detail == "N-sight patch lookup requires the N-sight RMM adapter"


def test_nsight_antivirus_threat_lookup_is_read_only_and_bounded(settings) -> None:
    result = NSightAntivirusThreatsAction().run(
        _context(settings, _NSightProvider()), {"device_id": "server:49324"}
    )
    assert result.status == "success"
    assert result.output["count"] == 1
    threats = cast(list[dict[str, object]], result.output["threats"])
    assert threats[0]["name"] == "Example.Malware"
    wrong = NSightAntivirusThreatsAction().run(
        _context(settings, _Provider()), {"device_id": "server:49324"}
    )
    assert wrong.error_detail == "N-sight antivirus lookup requires the N-sight RMM adapter"


def test_nsight_outage_lookup_is_read_only_and_bounded(settings) -> None:
    result = NSightOutageLookupAction().run(
        _context(settings, _NSightProvider()), {"device_id": "server:49324"}
    )
    assert result.status == "success"
    assert result.output["count"] == 1
    outages = cast(list[dict[str, object]], result.output["outages"])
    assert outages[0]["outage_id"] == 103725102
    wrong = NSightOutageLookupAction().run(
        _context(settings, _Provider()), {"device_id": "server:49324"}
    )
    assert wrong.error_detail == "N-sight outage lookup requires the N-sight RMM adapter"


def test_nsight_backup_lookup_is_read_only_and_bounded(settings) -> None:
    result = NSightBackupSessionsAction().run(
        _context(settings, _NSightProvider()), {"device_id": "server:49324"}
    )
    assert result.status == "success"
    assert result.output["count"] == 1
    sessions = cast(list[dict[str, object]], result.output["sessions"])
    assert sessions[0]["session_id"] == 12345
    wrong = NSightBackupSessionsAction().run(
        _context(settings, _Provider()), {"device_id": "server:49324"}
    )
    assert wrong.error_detail == "N-sight backup lookup requires the N-sight RMM adapter"
    failed = NSightBackupSessionsAction().run(
        _context(settings, _FailingBackupNSightProvider()), {"device_id": "server:49324"}
    )
    assert failed.error_detail == "N-sight backup sessions are unavailable"
    malformed = NSightBackupSessionsAction().run(
        _context(settings, _MalformedBackupNSightProvider()), {"device_id": "server:49324"}
    )
    assert malformed.error_detail == "N-sight returned malformed backup session data"


def test_nsight_backup_history_lookup_is_read_only_and_bounded(settings) -> None:
    result = NSightBackupHistoryAction().run(
        _context(settings, _NSightProvider()), {"device_id": "server:49324"}
    )
    assert result.status == "success"
    assert result.output["count"] == 1
    assert cast(list[dict[str, object]], result.output["days"])[0]["status"] == "PASS"
    wrong = NSightBackupHistoryAction().run(
        _context(settings, _Provider()), {"device_id": "server:49324"}
    )
    assert wrong.error_detail == "N-sight backup history requires the N-sight RMM adapter"
    failed = NSightBackupHistoryAction().run(
        _context(settings, _FailingBackupHistoryNSightProvider()), {"device_id": "server:49324"}
    )
    assert failed.error_detail == "N-sight backup history is unavailable"
    malformed = NSightBackupHistoryAction().run(
        _context(settings, _MalformedBackupHistoryNSightProvider()), {"device_id": "server:49324"}
    )
    assert malformed.error_detail == "N-sight returned malformed backup history data"
    malformed_checks = NSightBackupHistoryAction().run(
        _context(settings, _MalformedChecksBackupHistoryNSightProvider()),
        {"device_id": "server:49324"},
    )
    assert malformed_checks.error_detail == "N-sight returned malformed backup history data"


def test_nsight_check_inventory_lookup_is_read_only_and_bounded(settings) -> None:
    result = NSightCheckInventoryAction().run(
        _context(settings, _NSightProvider()), {"device_id": "server:49324"}
    )
    assert result.status == "success"
    assert result.output["count"] == 1
    checks = cast(list[dict[str, object]], result.output["checks"])
    assert checks[0]["check_id"] == 1304847
    wrong = NSightCheckInventoryAction().run(
        _context(settings, _Provider()), {"device_id": "server:49324"}
    )
    assert wrong.error_detail == "N-sight check inventory requires the N-sight RMM adapter"
    failed = NSightCheckInventoryAction().run(
        _context(settings, _FailingCheckInventoryNSightProvider()),
        {"device_id": "server:49324"},
    )
    assert failed.error_detail == "N-sight check inventory is unavailable"
    malformed = NSightCheckInventoryAction().run(
        _context(settings, _MalformedCheckInventoryNSightProvider()),
        {"device_id": "server:49324"},
    )
    assert malformed.error_detail == "N-sight returned malformed check inventory data"


def test_nsight_performance_history_lookup_is_read_only_and_bounded(settings) -> None:
    result = NSightPerformanceHistoryAction().run(
        _context(settings, _NSightProvider()), {"device_id": "server:49324"}
    )
    assert result.status == "success"
    assert result.output["count"] == 1
    records = cast(list[dict[str, object]], result.output["records"])
    assert records[0]["check_id"] == 102
    wrong = NSightPerformanceHistoryAction().run(
        _context(settings, _Provider()), {"device_id": "server:49324"}
    )
    assert wrong.error_detail == "N-sight performance history requires the N-sight RMM adapter"
    failed = NSightPerformanceHistoryAction().run(
        _context(settings, _FailingPerformanceHistoryNSightProvider()),
        {"device_id": "server:49324"},
    )
    assert failed.error_detail == "N-sight performance history is unavailable"
    malformed = NSightPerformanceHistoryAction().run(
        _context(settings, _MalformedPerformanceHistoryNSightProvider()),
        {"device_id": "server:49324"},
    )
    assert malformed.error_detail == "N-sight returned malformed performance history data"


def test_nsight_asset_details_lookup_is_read_only_and_bounded(settings) -> None:
    result = NSightAssetDetailsAction().run(
        _context(settings, _NSightProvider()), {"device_id": "server:49324"}
    )
    assert result.status == "success"
    assert result.output["source"] == "n-sight"
    assert result.output["hardware"] == [{"hardware_id": 123456, "name": "Ethernet Adapter"}]
    wrong = NSightAssetDetailsAction().run(
        _context(settings, _Provider()), {"device_id": "server:49324"}
    )
    assert wrong.error_detail == "N-sight asset details requires the N-sight RMM adapter"
    failed = NSightAssetDetailsAction().run(
        _context(settings, _FailingAssetDetailsNSightProvider()),
        {"device_id": "server:49324"},
    )
    assert failed.error_detail == "N-sight asset details are unavailable"
    malformed = NSightAssetDetailsAction().run(
        _context(settings, _MalformedAssetDetailsNSightProvider()),
        {"device_id": "server:49324"},
    )
    assert malformed.error_detail == "N-sight returned malformed asset details"


def test_nsight_monitoring_details_lookup_is_read_only_and_bounded(settings) -> None:
    invalid = NSightMonitoringDetailsAction().run(
        _context(settings, _NSightProvider()), {"device_id": ""}
    )
    assert invalid.error_detail == "device_id must be a non-empty string of at most 80 characters"
    result = NSightMonitoringDetailsAction().run(
        _context(settings, _NSightProvider()), {"device_id": "server:49324"}
    )
    assert result.status == "success"
    assert result.output["source"] == "n-sight"
    assert result.output["checks"] == [{"check_id": 2089484}]
    assert result.evidence[0]["type"] == "rmm_monitoring_device"
    wrong = NSightMonitoringDetailsAction().run(
        _context(settings, _Provider()), {"device_id": "server:49324"}
    )
    assert wrong.error_detail == "N-sight monitoring details requires the N-sight RMM adapter"
    failed = NSightMonitoringDetailsAction().run(
        _context(settings, _FailingMonitoringDetailsNSightProvider()),
        {"device_id": "server:49324"},
    )
    assert failed.error_detail == "N-sight monitoring details are unavailable"
    malformed = NSightMonitoringDetailsAction().run(
        _context(settings, _MalformedMonitoringDetailsNSightProvider()),
        {"device_id": "server:49324"},
    )
    assert malformed.error_detail == "N-sight returned malformed monitoring details"
    non_dict = NSightMonitoringDetailsAction().run(
        _context(settings, _NonDictMonitoringDetailsNSightProvider()),
        {"device_id": "server:49324"},
    )
    assert non_dict.error_detail == "N-sight returned malformed monitoring details"


def test_nsight_patch_approval_previews_and_requires_write_flag(settings) -> None:
    provider = _NSightProvider()
    context = _context(settings, provider)
    payload: dict[str, object] = {"device_id": "server:49324", "patch_ids": ["681806"]}
    preview = NSightPatchApproveAction().run(context, payload)
    assert preview.status == "success"
    assert preview.output["approval_required"] is True
    blocked = NSightPatchApproveAction().run(
        context, {**payload, "_approval_completed": True}
    )
    assert blocked.error_detail == "N-sight patch approval is blocked until WAIT_ALLOW_WRITE_ACTIONS=true"
    approved = NSightPatchApproveAction().run(
        _context(replace(settings, allow_write_actions=True), provider),
        {**payload, "_approval_completed": True},
    )
    assert approved.status == "success"
    assert approved.output["status"] == "accepted"


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"unexpected": True}, "unsupported fields"),
        ({"device_id": "", "patch_ids": ["681806"]}, "device_id"),
        ({"device_id": "server:49324", "patch_ids": []}, "between 1 and 20"),
        ({"device_id": "server:49324", "patch_ids": [681806]}, "only strings"),
        ({"device_id": "server:49324", "patch_ids": ["0"]}, "positive integers"),
    ],
)
def test_nsight_patch_approval_rejects_invalid_payloads(settings, payload, message) -> None:
    result = NSightPatchApproveAction().run(
        _context(settings, _NSightProvider()), payload
    )
    assert result.status == "failed"
    assert message in result.error_detail


def test_nsight_patch_approval_handles_provider_boundaries(settings) -> None:
    payload = {"device_id": "server:49324", "patch_ids": ["681806"], "_approval_completed": True}
    wrong_adapter = NSightPatchApproveAction().run(_context(settings, _Provider()), payload)
    assert wrong_adapter.error_detail == "N-sight patch approval requires the N-sight RMM adapter"

    enabled = replace(settings, allow_write_actions=True)
    failed = NSightPatchApproveAction().run(_context(enabled, _FailingNSightProvider()), payload)
    assert failed.error_detail == "N-sight patch approval failed"
    malformed = NSightPatchApproveAction().run(_context(enabled, _MalformedNSightProvider()), payload)
    assert malformed.error_detail == "N-sight returned malformed patch approval data"


def test_nsight_patch_reprocess_is_approval_gated(settings) -> None:
    payload: dict[str, object] = {"device_id": "server:49324", "patch_ids": ["681806"]}
    context = _context(settings, _NSightProvider())
    preview = NSightPatchReprocessAction().run(context, payload)
    assert preview.status == "success"
    assert preview.output["approval_required"] is True
    blocked = NSightPatchReprocessAction().run(
        context, {**payload, "_approval_completed": True}
    )
    assert blocked.error_detail == "N-sight patch reprocessing is blocked until WAIT_ALLOW_WRITE_ACTIONS=true"
    approved = NSightPatchReprocessAction().run(
        _context(replace(settings, allow_write_actions=True), _NSightProvider()),
        {**payload, "_approval_completed": True},
    )
    assert approved.status == "success"
    assert approved.output["status"] == "accepted"


def test_nsight_patch_policy_is_allowlisted_and_approval_gated(settings) -> None:
    payload: dict[str, object] = {
        "device_id": "server:49324",
        "patch_ids": ["681806"],
        "operation": "ignore",
    }
    provider = _NSightProvider()
    preview = NSightPatchPolicyAction().run(_context(settings, provider), payload)
    assert preview.status == "success"
    assert preview.output["approval_required"] is True
    assert preview.output["operation"] == "ignore"

    blocked = NSightPatchPolicyAction().run(
        _context(settings, provider), {**payload, "_approval_completed": True}
    )
    assert blocked.error_detail == "N-sight patch policy is blocked until WAIT_ALLOW_WRITE_ACTIONS=true"

    approved = NSightPatchPolicyAction().run(
        _context(replace(settings, allow_write_actions=True), provider),
        {**payload, "_approval_completed": True},
    )
    assert approved.status == "success"
    assert approved.output["operation"] == "ignore"

    invalid = NSightPatchPolicyAction().run(
        _context(settings, provider), {**payload, "operation": "execute"}
    )
    assert invalid.status == "failed"
    assert "do_nothing" in invalid.error_detail


def test_nsight_automated_task_is_approval_gated_and_scoped(settings) -> None:
    payload: dict[str, object] = {"device_id": "server:49324", "check_id": "1304847"}
    provider = _NSightProvider()
    preview = NSightRunTaskNowAction().run(_context(settings, provider), payload)
    assert preview.status == "success"
    assert preview.output["approval_required"] is True
    blocked = NSightRunTaskNowAction().run(
        _context(settings, provider), {**payload, "_approval_completed": True}
    )
    assert blocked.error_detail == (
        "N-sight task execution is blocked until WAIT_ALLOW_WRITE_ACTIONS=true"
    )
    approved = NSightRunTaskNowAction().run(
        _context(replace(settings, allow_write_actions=True), provider),
        {**payload, "_approval_completed": True},
    )
    assert approved.status == "success"
    assert approved.output["status"] == "accepted"
    assert approved.output["minutes_until_run"] == 15


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"device_id": "", "check_id": "1304847"}, "device_id"),
        ({"device_id": "server:49324", "check_id": ""}, "check_id"),
        ({"device_id": "server:49324", "check_id": "-1"}, "positive integer"),
        ({"device_id": "server:49324", "check_id": 1304847}, "positive integer string"),
        (
            {"device_id": "server:49324", "check_id": "1304847", "extra": True},
            "unsupported fields",
        ),
    ],
)
def test_nsight_automated_task_rejects_invalid_payloads(settings, payload, message) -> None:
    result = NSightRunTaskNowAction().run(_context(settings, _NSightProvider()), payload)
    assert result.status == "failed"
    assert message in result.error_detail


@pytest.mark.parametrize(
    ("provider", "message"),
    [
        (_Provider(), "N-sight RMM adapter"),
        (_FailingTaskNSightProvider(), "execution failed"),
        (_MalformedTaskNSightProvider(), "malformed"),
    ],
)
def test_nsight_automated_task_rejects_provider_failures(settings, provider, message) -> None:
    result = NSightRunTaskNowAction().run(
        _context(replace(settings, allow_write_actions=True), provider),
        {"device_id": "server:49324", "check_id": "1304847", "_approval_completed": True},
    )
    assert result.status == "failed"
    assert message in result.error_detail


def test_nsight_automated_task_reports_provider_rejection(settings) -> None:
    result = NSightRunTaskNowAction().run(
        _context(replace(settings, allow_write_actions=True), _RejectedTaskNSightProvider()),
        {"device_id": "server:49324", "check_id": "1304847", "_approval_completed": True},
    )
    assert result.status == "failed"
    assert result.output["approved"] is True
    assert result.error_detail == "N-sight automated task execution failed"


def test_rmm_script_preview_and_approved_execution(settings) -> None:
    provider = _Provider()
    context = _context(replace(settings, allow_write_actions=True), provider)
    payload: dict[str, object] = {
        "script_id": "script-1",
        "device_id": "device-1",
        "arguments": {"days": "7"},
    }
    preview = RmmScriptPreviewAction().run(context, payload)
    pending = RmmScriptExecuteAction().run(context, payload)
    executed = RmmScriptExecuteAction().run(
        context, {**payload, "_approval_completed": True}
    )
    assert preview.status == "success"
    assert pending.status == "success"
    assert pending.output["approval_required"] is True
    assert executed.status == "success"
    assert executed.output["execution_id"] == "exec-1"
    tracked = RmmScriptExecutionLookupAction().run(
        context, {"execution_id": "exec-1"}
    )
    assert tracked.status == "success"
    assert tracked.output["status"] == "succeeded"


def test_rmm_script_execution_requires_write_flag(settings) -> None:
    payload = {"script_id": "script-1", "device_id": "device-1"}
    result = RmmScriptExecuteAction().run(
        _context(settings, _Provider()), {**payload, "_approval_completed": True}
    )

    assert result.status == "failed"
    assert result.error_detail == "RMM script execution is blocked until WAIT_ALLOW_WRITE_ACTIONS=true"


@pytest.mark.parametrize(
    "payload",
    [
        {"script_id": "", "device_id": "device"},
        {"script_id": "script", "device_id": ""},
        {"script_id": "script", "device_id": "device", "arguments": []},
        {
            "script_id": "script",
            "device_id": "device",
            "arguments": {"bad\nkey": "value"},
        },
    ],
)
def test_rmm_script_request_validation(settings, payload) -> None:
    result = RmmScriptPreviewAction().run(_context(settings, _Provider()), payload)
    assert result.status == "failed"


def test_rmm_provider_failures_are_safe(settings) -> None:
    class Broken(_Provider):
        def list_alerts(self, client_id=None):
            raise RuntimeError("secret")

        def preview_script(self, *args, **kwargs):
            raise RuntimeError("secret")

    context = _context(settings, Broken())
    assert RmmAlertLookupAction().run(context, {}).error_detail == "RMM alerts are unavailable"
    assert RmmScriptPreviewAction().run(
        context, {"script_id": "s", "device_id": "d"}
    ).error_detail == "RMM script preview failed"


def test_rmm_provider_selects_configured_ninjaone_without_network_calls(settings) -> None:
    provider = rmm_provider_from_settings(
        replace(settings, ninjaone_base_url="https://ninjaone.example.test"),
        Store(settings.data_path),
    )

    assert provider.adapter_id == "ninjaone"


class _InstanceStore:
    def __init__(self, instances: list[ConnectorInstance]) -> None:
        self.instances = instances

    def list_connector_instances(self) -> list[ConnectorInstance]:
        return self.instances

    def get_connector_instance(self, connector_instance_id: str) -> ConnectorInstance | None:
        return next(
            (instance for instance in self.instances if instance.connector_instance_id == connector_instance_id),
            None,
        )


def _rmm_instance(
    instance_id: str,
    *,
    client_id: str | None = None,
    connector_type: str = "ninjaone",
    status: str = "active",
) -> ConnectorInstance:
    return ConnectorInstance(
        connector_instance_id=instance_id,
        connector_type=connector_type,
        display_name=instance_id,
        client_id=client_id,
        credential_ref="fixture-ref",
        config_json="{}",
        status=status,
        created_at="",
        updated_at="",
    )


def test_rmm_provider_instance_precedence_and_env_fallback(settings, monkeypatch) -> None:
    import wait_local_agent.connector_factory as factory

    built: list[str] = []

    class Provider:
        def __init__(self, adapter_id: str) -> None:
            self.adapter_id = adapter_id

    def build(_store, instance_id, **_kwargs):
        built.append(instance_id)
        return Provider(instance_id)

    monkeypatch.setattr(factory, "build_read_client_for", build)
    store = _InstanceStore(
        [
            _rmm_instance("msp-wide"),
            _rmm_instance("client-scoped", client_id="acme"),
        ]
    )
    configured = replace(settings, ninjaone_base_url="https://ninjaone.example.test")
    assert rmm_provider_from_settings(configured, store, "acme").adapter_id == "client-scoped"
    msp_provider = rmm_provider_from_settings(
        configured,
        _InstanceStore([_rmm_instance("msp-wide")]),
        "acme",
        allow_msp_wide=True,
    )
    assert msp_provider.adapter_id == "msp-wide"
    assert cast(Any, msp_provider).tier == "MSP-wide"
    environment_provider = rmm_provider_from_settings(
        configured,
        _InstanceStore([]),
        "acme",
        allow_msp_wide=True,
    )
    assert environment_provider.adapter_id == "ninjaone"
    assert cast(Any, environment_provider).tier == "environment"
    assert built == ["client-scoped", "msp-wide"]


def test_rmm_provider_instance_ambiguity_fails_closed(settings) -> None:
    store = _InstanceStore([_rmm_instance("one", client_id="acme"), _rmm_instance("two", client_id="acme")])
    with pytest.raises(RmmProviderResolutionError, match="ambiguous active RMM connector instances"):
        rmm_provider_from_settings(settings, store, "acme")


def test_rmm_provider_instance_resolution_errors_fail_closed(settings, monkeypatch) -> None:
    import wait_local_agent.connector_factory as factory

    class BrokenStore(_InstanceStore):
        def list_connector_instances(self):
            raise RuntimeError("fixture store failure")

    with pytest.raises(RmmProviderResolutionError, match="could not be loaded"):
        rmm_provider_from_settings(settings, BrokenStore([]), "acme")

    monkeypatch.setattr(
        factory,
        "build_read_client_for",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            factory.ConnectorFactoryError("fixture instance failure")
        ),
    )
    with pytest.raises(RmmProviderResolutionError, match="fixture instance failure"):
        rmm_provider_from_settings(
            settings,
            _InstanceStore([_rmm_instance("client-scoped", client_id="acme")]),
            "acme",
        )


def test_rmm_provider_rejects_provider_without_tier_attribute(settings, monkeypatch) -> None:
    import wait_local_agent.connector_factory as factory

    class ImmutableProvider:
        __slots__ = ()
        adapter_id = "immutable-rmm"

    monkeypatch.setattr(factory, "build_read_client_for", lambda *_args, **_kwargs: ImmutableProvider())

    with pytest.raises(RmmProviderResolutionError, match="does not expose a resolution tier"):
        rmm_provider_from_settings(
            settings,
            _InstanceStore([_rmm_instance("client-scoped", client_id="acme")]),
            "acme",
        )


def test_rmm_provider_msp_ambiguity_fails_closed(settings) -> None:
    store = _InstanceStore([_rmm_instance("one"), _rmm_instance("two")])

    with pytest.raises(RmmProviderResolutionError, match="at the MSP-wide tier"):
        rmm_provider_from_settings(settings, store, "acme", allow_msp_wide=True)


@pytest.mark.parametrize(
    ("field", "value", "adapter_id"),
    [
        ("datto_rmm_base_url", "https://datto.example.test", "dattormm"),
        ("ncentral_base_url", "https://ncentral.example.test", "ncentral"),
        ("n_sight_base_url", "https://nsight.example.test", "n-sight"),
        ("kaseya_rmm_base_url", "https://kaseya.example.test", "kaseya-vsa-x"),
        ("screenconnect_base_url", "https://screenconnect.example.test", "screenconnect"),
    ],
)
def test_rmm_provider_legacy_environment_precedence(settings, field, value, adapter_id) -> None:
    provider = rmm_provider_from_settings(replace(settings, **{field: value}), Store(settings.data_path))

    assert provider.adapter_id == adapter_id


def test_rmm_provider_ignores_inactive_and_non_rmm_instances(settings) -> None:
    store = _InstanceStore(
        [
            _rmm_instance("inactive", client_id="acme", status="inactive"),
            _rmm_instance("psa", client_id="acme", connector_type="halopsa"),
        ]
    )
    with pytest.raises(RmmProviderResolutionError, match="client-scoped.*acme"):
        rmm_provider_from_settings(settings, store, "acme")
