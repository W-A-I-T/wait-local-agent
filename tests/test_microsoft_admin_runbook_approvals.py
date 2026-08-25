from __future__ import annotations

import json
import subprocess
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest

from packs.microsoft_admin.runbooks import (
    RUNBOOK_ACTION_TYPE,
    RunbookApprovalError,
    create_runbook_approval,
    execute_approved_runbook,
)
from tests.microsoft_admin_runbook_support import (
    FakeRunbookStore,
    _execution_settings,
    _fake_powershell,
)
from wait_local_agent.store import Store


def test_approved_runbook_uses_stored_plan_exactly_once(
    settings,
    tmp_path: Path,
) -> None:
    configured = _execution_settings(settings, tmp_path)
    executable = _fake_powershell(tmp_path)
    fake = FakeRunbookStore()
    store = cast(Store, fake)
    approval, plan = create_runbook_approval(
        store,
        client_id="client-1",
        runbook_id="windows.service_restart",
        parameters={"service_name": "wuauserv", "wait_seconds": 7},
    )
    assert approval.action_type == RUNBOOK_ACTION_TYPE
    fake.approvals[approval.id] = replace(approval, status="approved", approver_id="admin")

    updated, result = execute_approved_runbook(
        store,
        approval.id,
        configured,
        expected_client_id="client-1",
        runner=lambda argv, cwd, timeout_seconds, environment: subprocess.CompletedProcess(
            argv,
            0,
            stdout=json.dumps(
                {
                    "runbook_id": "windows.service_restart",
                    "service_name": "wuauserv",
                    "before_status": "Running",
                    "after_status": "Running",
                }
            ),
            stderr="",
        ),
        executable_resolver=lambda: executable,
        platform_is_windows=lambda: True,
    )
    assert result.status == "succeeded"
    assert updated.execution_status == "succeeded"
    assert fake.recorded[0]["audit_event_type"] == "microsoft_admin.powershell_runbook"
    assert json.loads(approval.payload_json) == plan

    with pytest.raises(RunbookApprovalError, match="already"):
        execute_approved_runbook(
            store,
            approval.id,
            configured,
            expected_client_id="client-1",
            executable_resolver=lambda: executable,
            platform_is_windows=lambda: True,
        )


def test_approved_runbook_rejects_wrong_type_tenant_status_and_malformed_payload(
    settings,
    tmp_path: Path,
) -> None:
    configured = _execution_settings(settings, tmp_path)
    fake = FakeRunbookStore()
    store = cast(Store, fake)
    approval, _ = create_runbook_approval(
        store,
        client_id="client-1",
        runbook_id="windows.endpoint_health",
        parameters={},
    )

    with pytest.raises(RunbookApprovalError, match="not approved"):
        execute_approved_runbook(
            store,
            approval.id,
            configured,
            expected_client_id="client-1",
        )

    fake.approvals[approval.id] = replace(approval, action_type="other", status="approved")
    with pytest.raises(RunbookApprovalError, match="not a PowerShell"):
        execute_approved_runbook(
            store,
            approval.id,
            configured,
            expected_client_id="client-1",
        )

    fake.approvals[approval.id] = replace(approval, status="approved")
    with pytest.raises(RunbookApprovalError, match="different tenant"):
        execute_approved_runbook(
            store,
            approval.id,
            configured,
            expected_client_id="client-2",
        )

    fake.approvals[approval.id] = replace(
        approval,
        status="approved",
        payload_json="{",
    )
    with pytest.raises(RunbookApprovalError, match="malformed"):
        execute_approved_runbook(
            store,
            approval.id,
            configured,
            expected_client_id="client-1",
        )

    fake.approvals[approval.id] = replace(
        approval,
        status="approved",
        payload_json="[]",
    )
    with pytest.raises(RunbookApprovalError, match="malformed"):
        execute_approved_runbook(
            store,
            approval.id,
            configured,
            expected_client_id="client-1",
        )

    with pytest.raises(RunbookApprovalError, match="not found"):
        execute_approved_runbook(
            store,
            999,
            configured,
            expected_client_id="client-1",
        )


def test_approved_runbook_does_not_consume_approval_when_runtime_is_blocked(
    settings,
    tmp_path: Path,
) -> None:
    configured = _execution_settings(settings, tmp_path)
    fake = FakeRunbookStore()
    store = cast(Store, fake)
    approval, _ = create_runbook_approval(
        store,
        client_id="client-1",
        runbook_id="windows.endpoint_health",
        parameters={},
    )
    fake.approvals[approval.id] = replace(approval, status="approved")
    with pytest.raises(RunbookApprovalError, match="not found on the Windows host"):
        execute_approved_runbook(
            store,
            approval.id,
            configured,
            expected_client_id="client-1",
            executable_resolver=lambda: None,
            platform_is_windows=lambda: True,
        )
    assert fake.approvals[approval.id].execution_status == "not_started"
    assert fake.recorded == []
