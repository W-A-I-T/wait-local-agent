from __future__ import annotations

from typing import cast

import pytest

from wait_local_agent.rmm import (
    LocalCollectorRmmAdapter,
    RmmAlert,
    RmmDevice,
    RmmScript,
    RmmScriptExecution,
    RmmScriptPreview,
)
from wait_local_agent.smart_actions import (
    ActionContext,
    RmmAlertLookupAction,
    RmmScriptCatalogAction,
    RmmScriptExecuteAction,
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


def test_rmm_alerts_and_script_catalog_are_bounded(settings) -> None:
    provider = _Provider()
    alerts = RmmAlertLookupAction().run(_context(settings, provider), {})
    scripts = RmmScriptCatalogAction().run(_context(settings, provider), {})
    assert alerts.status == "success"
    assert cast(list[dict[str, object]], alerts.output["alerts"])[0]["alert_id"] == "alert-1"
    assert scripts.status == "success"
    assert cast(list[dict[str, object]], scripts.output["scripts"])[0]["script_id"] == "script-1"


def test_rmm_script_preview_and_approved_execution(settings) -> None:
    provider = _Provider()
    context = _context(settings, provider)
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
