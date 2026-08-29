from __future__ import annotations

import json
import subprocess
from dataclasses import replace
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from packs.microsoft_admin.cli import app as microsoft_admin_cli
from packs.microsoft_admin.router import create_router
from packs.microsoft_admin.runbooks import RunbookRuntimeStatus
from tests.microsoft_admin_runbook_support import (
    FakeRunbookStore,
    _execution_settings,
    _fake_powershell,
)


def test_runbook_router_creates_tenant_approval_and_executes_as_admin(
    settings,
    tmp_path: Path,
) -> None:
    configured = _execution_settings(settings, tmp_path)
    executable = _fake_powershell(tmp_path)
    fake = FakeRunbookStore()
    app = FastAPI()
    app.state.settings = configured
    app.state.store = fake
    app.state.microsoft_admin_windows_predicate = lambda: True
    app.state.microsoft_admin_powershell_resolver = lambda: executable
    app.state.microsoft_admin_runbook_runner = (
        lambda argv, cwd, timeout_seconds, environment: subprocess.CompletedProcess(
            argv,
            0,
            stdout=json.dumps(
                {
                    "runbook_id": "windows.service_restart",
                    "service_name": "BITS",
                    "before_status": "Running",
                    "after_status": "Running",
                }
            ),
            stderr="",
        )
    )
    app.include_router(create_router(), prefix="/packs/microsoft-admin")
    client = TestClient(app)

    assert client.get("/packs/microsoft-admin/runbooks").status_code == 200
    assert client.get("/packs/microsoft-admin/runbooks/status").json()["status"] == "ready"

    viewer = client.post(
        "/packs/microsoft-admin/runbooks/plan",
        headers={"Authorization": "Bearer viewer-token"},
        json={
            "runbook_id": "windows.service_restart",
            "parameters": {"service_name": "BITS"},
            "client_id": "client-1",
        },
    )
    assert viewer.status_code == 403

    invalid_plan = client.post(
        "/packs/microsoft-admin/runbooks/plan",
        headers={"Authorization": "Bearer tech-token"},
        json={
            "runbook_id": "windows.service_restart",
            "parameters": {"service_name": "Spooler"},
            "client_id": "client-1",
        },
    )
    assert invalid_plan.status_code == 422

    missing_approval = client.post(
        "/packs/microsoft-admin/runbooks/approvals/999/execute",
        headers={"Authorization": "Bearer admin-token"},
    )
    assert missing_approval.status_code == 404

    draft = client.post(
        "/packs/microsoft-admin/runbooks/drafts",
        headers={"Authorization": "Bearer tech-token"},
        json={
            "runbook_id": "windows.service_restart",
            "parameters": {"service_name": "BITS", "wait_seconds": 5},
            "client_id": "client-1",
        },
    )
    assert draft.status_code == 200
    request_id = draft.json()["approval"]["id"]
    fake.approvals[request_id] = replace(
        fake.approvals[request_id],
        status="approved",
        approver_id="admin",
    )

    execute = client.post(
        f"/packs/microsoft-admin/runbooks/approvals/{request_id}/execute",
        headers={"Authorization": "Bearer admin-token"},
    )
    assert execute.status_code == 200
    assert execute.json()["result"]["status"] == "succeeded"

    replay = client.post(
        f"/packs/microsoft-admin/runbooks/approvals/{request_id}/execute",
        headers={"Authorization": "Bearer admin-token"},
    )
    assert replay.status_code == 409


def test_runbook_cli_catalog_status_plan_and_validation(settings, tmp_path: Path, monkeypatch) -> None:
    import packs.microsoft_admin.cli as cli_module

    configured = _execution_settings(settings, tmp_path)
    monkeypatch.setattr(cli_module, "load_settings", lambda: configured)
    monkeypatch.setattr(
        cli_module,
        "runbook_runtime_status",
        lambda active_settings: RunbookRuntimeStatus("ready", "ready", "C:/pwsh.exe"),
    )
    runner = CliRunner()

    catalog = runner.invoke(microsoft_admin_cli, ["runbooks"])
    status = runner.invoke(microsoft_admin_cli, ["runbook-status"])
    plan = runner.invoke(
        microsoft_admin_cli,
        [
            "plan-runbook",
            "windows.endpoint_health",
            "--client",
            "client-1",
            "--parameters",
            '{"event_hours": 12}',
        ],
    )
    invalid_json = runner.invoke(
        microsoft_admin_cli,
        [
            "plan-runbook",
            "windows.endpoint_health",
            "--client",
            "client-1",
            "--parameters",
            "{",
        ],
    )
    invalid_shape = runner.invoke(
        microsoft_admin_cli,
        [
            "plan-runbook",
            "windows.endpoint_health",
            "--client",
            "client-1",
            "--parameters",
            "[]",
        ],
    )

    assert catalog.exit_code == 0
    assert json.loads(catalog.output)[0]["runbook_id"] == "windows.endpoint_health"
    assert status.exit_code == 0
    assert json.loads(status.output)["status"] == "ready"
    assert plan.exit_code == 0
    assert json.loads(plan.output)["parameters"]["event_hours"] == 12
    assert invalid_json.exit_code == 2
    assert invalid_shape.exit_code == 2
