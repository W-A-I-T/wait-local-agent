from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from fastapi.testclient import TestClient

import wait_local_agent.api.app as app_module
import wait_local_agent.api.routers.psa_connectors as psa_connectors_module
import wait_local_agent.api.routers.tickets as tickets_module
import wait_local_agent.power_platform_deployment as deployment_module
from tests.api_helpers import _auth, _provision_bound_principal
from tests.support import ensure_test_client, ensure_test_clients, ingest_local
from wait_local_agent.api.app import create_app
from wait_local_agent.models import (
    ConnectorReadResult,
)
from wait_local_agent.store import Store


def test_ticket_summary_and_approval_flow(settings) -> None:
    ingest_local(Store(settings.data_path), Path("examples/sample_tickets/tickets.json"))
    client = TestClient(create_app(settings))

    summary = client.get("/tickets/TCK-1001/summary")
    approval = client.post(
        "/tickets/TCK-1001/approvals",
        json={"status": "approved", "comment": "ship it"},
    )
    audit = client.get("/audit")

    assert summary.status_code == 200
    assert summary.json()["classification"] == "identity-access"
    assert approval.status_code == 200
    assert approval.json()["status"] == "approved"
    assert approval.json()["comment"] == "ship it"
    assert audit.status_code == 200
    assert any(event["event_type"] == "approval.updated" for event in audit.json())


def test_approval_missing_ticket_returns_404(settings) -> None:
    client = TestClient(create_app(settings))

    response = client.post("/tickets/NOPE/approvals", json={"status": "approved"})

    assert response.status_code == 404


def test_approval_requests_are_scoped_to_authenticated_tenant(settings, monkeypatch) -> None:
    secure_settings = settings.__class__(
        **{
            **settings.__dict__,
            "demo_mode": False,
            "client_id": "acme",
            "admin_token": "admin-token",
            "tech_token": "",
            "viewer_token": "",
        }
    )
    store = Store(secure_settings.data_path)
    ensure_test_clients(store, "acme", "beta")
    _provision_bound_principal(store, "acme-technician", "acme-technician-token", "acme", "technician")
    acme = store.create_approval_request(
        "TCK-ACME",
        "ticket.assign",
        {"ticket_id": "TCK-ACME"},
        client_id="acme",
    )
    globex = store.create_approval_request(
        "TCK-GLOBEX",
        "halopsa.add_note",
        {
            "connector": "halopsa",
            "ticket_id": "TCK-GLOBEX",
            "action_type": "add_note",
            "fields": {"note": "original"},
        },
        client_id="globex",
    )
    legacy = store.create_approval_request(
        "TCK-LEGACY",
        "ticket.assign",
        {"ticket_id": "TCK-LEGACY"},
    )
    acme_halopsa = store.create_approval_request(
        "TCK-ACME-HALO",
        "halopsa.add_note",
        {
            "connector": "halopsa",
            "ticket_id": "TCK-ACME-HALO",
            "action_type": "add_note",
            "fields": {"note": "ready"},
        },
        client_id="acme",
    )
    store.update_approval_request(acme_halopsa.id or 0, "approved")
    execute_calls: list[int] = []

    def fake_execute(store_arg, _client, request_id: int):
        execute_calls.append(request_id)
        return store_arg.get_approval_request(request_id)

    monkeypatch.setattr(psa_connectors_module, "execute_halopsa_approval_request", fake_execute)
    client = TestClient(create_app(secure_settings))

    scoped_list = client.get(
        "/approval-requests",
        params={"client_id": "globex"},
        headers=_auth("acme-technician-token"),
    )
    foreign_detail = client.get(f"/approval-requests/{globex.id}", headers=_auth("acme-technician-token"))
    foreign_patch = client.patch(
        f"/approval-requests/{globex.id}/payload",
        headers=_auth("acme-technician-token"),
        json={"fields": {"note": "tampered"}},
    )
    foreign_update = client.post(
        f"/approval-requests/{globex.id}",
        headers=_auth("acme-technician-token"),
        json={"status": "approved", "comment": "tampered"},
    )
    foreign_execute = client.post(
        f"/connectors/halopsa/approval-requests/{globex.id}/execute",
        headers=_auth("acme-technician-token"),
    )
    foreign_after_technician = store.get_approval_request(globex.id or 0)
    acme_detail = client.get(f"/approval-requests/{acme.id}", headers=_auth("acme-technician-token"))
    acme_update = client.post(
        f"/approval-requests/{acme.id}",
        headers=_auth("acme-technician-token"),
        json={"status": "approved", "comment": "approved"},
    )
    legacy_detail = client.get(f"/approval-requests/{legacy.id}", headers=_auth("acme-technician-token"))
    legacy_update = client.post(
        f"/approval-requests/{legacy.id}",
        headers=_auth("acme-technician-token"),
        json={"status": "approved", "comment": "approved"},
    )
    acme_execute = client.post(
        f"/connectors/halopsa/approval-requests/{acme_halopsa.id}/execute",
        headers=_auth("acme-technician-token"),
    )
    admin_list = client.get("/approval-requests", headers=_auth("admin-token"))
    admin_filtered = client.get(
        "/approval-requests",
        params={"client_id": "globex"},
        headers=_auth("admin-token"),
    )
    admin_detail = client.get(f"/approval-requests/{globex.id}", headers=_auth("admin-token"))
    admin_update = client.post(
        f"/approval-requests/{globex.id}",
        headers=_auth("admin-token"),
        json={"status": "rejected", "comment": "admin decision"},
    )

    assert scoped_list.status_code == 403
    assert foreign_detail.status_code == 404
    assert foreign_patch.status_code == 404
    assert foreign_update.status_code == 403
    assert foreign_execute.status_code == 404
    assert execute_calls == [acme_halopsa.id]
    assert acme_detail.status_code == 200
    assert acme_detail.json()["id"] == acme.id
    assert acme_update.status_code == 200
    assert acme_update.json()["status"] == "approved"
    assert legacy_detail.status_code == 404
    assert legacy_update.status_code == 404
    assert acme_execute.status_code == 200
    assert acme_execute.json()["id"] == acme_halopsa.id
    assert admin_list.status_code == 200
    assert {request["subject_id"] for request in admin_list.json()} == {
        "TCK-ACME",
        "TCK-GLOBEX",
        "TCK-LEGACY",
        "TCK-ACME-HALO",
    }
    assert [request["subject_id"] for request in admin_filtered.json()] == ["TCK-GLOBEX"]
    assert admin_detail.status_code == 200
    assert admin_detail.json()["id"] == globex.id
    assert admin_update.status_code == 200
    assert admin_update.json()["status"] == "rejected"
    assert foreign_after_technician is not None
    assert foreign_after_technician.status == "pending"
    assert foreign_after_technician.comment == ""
    foreign_after = store.get_approval_request(globex.id or 0)
    assert foreign_after is not None
    assert foreign_after.status == "rejected"
    assert foreign_after.comment == "admin decision"
    assert foreign_after.payload_json == globex.payload_json


def test_bound_technician_can_patch_in_scope_approval_payload(settings) -> None:
    secure_settings = settings.__class__(
        **{
            **settings.__dict__,
            "demo_mode": False,
            "client_id": "acme",
            "admin_token": "admin-token",
            "tech_token": "tech-token",
        }
    )
    store = Store(secure_settings.data_path)
    approval = store.create_approval_request(
        "TCK-ACME",
        "halopsa.add_note",
        {
            "connector": "halopsa",
            "ticket_id": "TCK-ACME",
            "action_type": "add_note",
            "fields": {"note": "before"},
        },
        client_id="acme",
    )
    client = TestClient(create_app(secure_settings))

    response = client.patch(
        f"/approval-requests/{approval.id}/payload",
        headers=_auth("tech-token"),
        json={"fields": {"note": "after"}, "comment": "updated in scope"},
    )

    assert response.status_code == 200
    assert response.json()["client_id"] == "acme"
    assert response.json()["payload"]["fields"] == {"note": "after"}
    assert response.json()["comment"] == "updated in scope"
    persisted = store.get_approval_request(approval.id or 0)
    assert persisted is not None
    assert persisted.status == "pending"
    assert persisted.client_id == "acme"


def test_bound_non_admin_approval_list_without_filter_is_tenant_scoped(settings) -> None:
    secure_settings = settings.__class__(
        **{
            **settings.__dict__,
            "demo_mode": False,
            "client_id": "acme",
            "admin_token": "admin-token",
            "tech_token": "tech-token",
        }
    )
    store = Store(secure_settings.data_path)
    _provision_bound_principal(store, "acme-technician", "acme-technician-token", "acme", "technician")
    store.create_approval_request(
        "TCK-ACME",
        "ticket.assign",
        {"ticket_id": "TCK-ACME"},
        client_id="acme",
    )
    store.create_approval_request(
        "TCK-GLOBEX",
        "ticket.assign",
        {"ticket_id": "TCK-GLOBEX"},
        client_id="globex",
    )
    client = TestClient(create_app(secure_settings))

    response = client.get("/approval-requests", headers=_auth("acme-technician-token"))

    assert response.status_code == 200
    assert [request["subject_id"] for request in response.json()] == ["TCK-ACME"]


def test_missing_ticket_returns_404(settings) -> None:
    client = TestClient(create_app(settings))

    response = client.get("/tickets/DOES-NOT-EXIST/summary")

    assert response.status_code == 404


def test_approval_detail_handles_invalid_payload_and_missing_write_health(settings, monkeypatch) -> None:
    class HaloClientWithoutWriteHealth:
        def __init__(self, _settings) -> None:
            pass

    store = Store(settings.data_path)
    ensure_test_client(store, "acme")
    approval = store.create_approval_request(
        "TCK-1002",
        "halopsa.add_note",
        {"fields": {"note": "ok"}},
    )
    store.update_approval_request(approval.id or 0, "approved", "ready")
    with store._connect() as connection:
        connection.execute(
            "update approval_requests set payload_json = ? where id = ?",
            ("not-json", approval.id),
        )
    monkeypatch.setattr(app_module, "HaloPSAClient", HaloClientWithoutWriteHealth)
    client = TestClient(app_module.create_app(settings))

    response = client.get(f"/approval-requests/{approval.id}")

    assert response.status_code == 200
    assert response.json()["payload"] == {}
    assert response.json()["block_reason"] == "HaloPSA write health is unavailable."


def test_approval_execution_state_covers_governed_connector_branches(settings, monkeypatch, tmp_path) -> None:
    class ReadyClient:
        def __init__(self, _settings) -> None:
            pass

        def write_health(self) -> ConnectorReadResult:
            return ConnectorReadResult("ready", "ready", 0)

    monkeypatch.setattr(app_module, "TeamsGraphClient", ReadyClient)
    monkeypatch.setattr(app_module, "M365GraphClient", ReadyClient)

    def detail(action_type: str, *, execution_status: str = "not_started", app_settings=settings) -> dict:
        store = Store(app_settings.data_path)
        approval = store.create_approval_request("TCK-STATE", action_type, {})
        store.update_approval_request(approval.id or 0, "approved")
        if execution_status != "not_started":
            store.record_approval_execution(
                approval.id or 0,
                status=execution_status,
                message="done",
                result={},
            )
        headers = {"Authorization": "Bearer admin-token"} if not app_settings.demo_mode else {}
        return TestClient(app_module.create_app(app_settings)).get(
            f"/approval-requests/{approval.id}", headers=headers
        ).json()

    assert detail("teams.message.send", execution_status="succeeded")["block_reason"] == (
        "Approval request has already executed successfully."
    )
    assert detail("m365.users.disable", execution_status="succeeded")["block_reason"] == (
        "Approval request has already executed successfully."
    )
    for execution_status in ("verified", "unverified", "submitted"):
        assert detail("halopsa.update_status", execution_status=execution_status)["block_reason"] == (
            "Approval request has already executed successfully."
        )
    assert detail("teams.message.send")["can_execute"] is True
    assert detail("m365.users.disable")["can_execute"] is True
    blocked = detail("power_platform.solution_stage")
    assert blocked["block_reason"] == "Power Platform execution is blocked until WAIT_ALLOW_WRITE_ACTIONS=true."
    deployment_blocked = detail(
        "power_platform.solution_stage",
        app_settings=replace(
            settings,
            demo_mode=False,
            api_token="admin-token",
            allow_write_actions=True,
            allow_power_platform_deployment=False,
        ),
    )
    assert deployment_blocked["block_reason"] == (
        "Power Platform deployment is blocked until WAIT_ALLOW_POWER_PLATFORM_DEPLOYMENT=true."
    )
    workspace_blocked = detail(
        "power_platform.solution_stage",
        app_settings=replace(
            settings,
            demo_mode=False,
            api_token="admin-token",
            allow_write_actions=True,
            allow_power_platform_deployment=True,
            power_platform_workspace=tmp_path,
            pac_path=tmp_path / "no-such-pac",
        ),
    )
    assert workspace_blocked["block_reason"] == (
        "WAIT_PAC_PATH is configured but is not an executable regular file."
    )

    empty_path = tmp_path / "empty-path"
    empty_path.mkdir()
    monkeypatch.setenv("PATH", str(empty_path))
    monkeypatch.setattr(deployment_module, "resolve_pac_executable", lambda _settings: None)
    pathless = detail(
        "power_platform.solution_stage",
        app_settings=replace(
            settings,
            demo_mode=False,
            api_token="admin-token",
            allow_write_actions=True,
            allow_power_platform_deployment=True,
            power_platform_workspace=tmp_path,
        ),
    )
    assert pathless["can_execute"] is False
    assert pathless["block_reason"] == "The pac executable is not available on the local PATH."

    fake_pac = tmp_path / "pac"
    fake_pac.write_text(
        "#!/bin/sh\nif [ \"$1\" = help ]; then printf '%s\\n' 'Version: 2.4.1'; fi\nexit 0\n",
        encoding="utf-8",
    )
    fake_pac.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setattr(deployment_module, "resolve_pac_executable", lambda _settings: str(fake_pac))
    path_settings = replace(
        settings,
        demo_mode=False,
        api_token="admin-token",
        allow_write_actions=True,
        allow_power_platform_deployment=True,
        power_platform_workspace=tmp_path,
    )
    path_store = Store(path_settings.data_path)
    path_approval = path_store.create_approval_request("TCK-STATE", "power_platform.solution_stage", {})
    path_store.update_approval_request(path_approval.id or 0, "approved")
    path_response = TestClient(app_module.create_app(path_settings)).get(
        f"/approval-requests/{path_approval.id}", headers=_auth("admin-token")
    )
    assert path_response.status_code == 200
    assert path_response.json()["can_execute"] is True
    assert path_response.json()["block_reason"] == ""


def test_api_exposes_expired_approval_and_rejects_late_approval(settings) -> None:
    store = Store(settings.data_path)
    approval = store.create_approval_request(
        "TCK-1002",
        "halopsa.add_note",
        {"fields": {"note": "ok"}},
        expires_in_seconds=60,
    )
    with store._connect() as connection:
        connection.execute(
            "update approval_requests set expires_at = ? where id = ?",
            ("2000-01-01T00:00:00+00:00", approval.id),
        )
    client = TestClient(create_app(settings))

    detail = client.get(f"/approval-requests/{approval.id}")
    late_approval = client.post(
        f"/approval-requests/{approval.id}",
        json={"status": "approved", "comment": "too late"},
    )

    assert detail.status_code == 200
    assert detail.json()["status"] == "expired"
    assert detail.json()["expires_at"] == "2000-01-01T00:00:00+00:00"
    assert late_approval.status_code == 403


def test_update_approval_request_recovers_from_runtime_error(settings, monkeypatch) -> None:
    store = Store(settings.data_path)
    approval = store.create_approval_request(
        "TCK-1002",
        "halopsa.add_note",
        {"fields": {"note": "ok"}},
    )
    client = TestClient(create_app(settings))

    def fail_execution(_store, _client, request_id: int):
        raise RuntimeError(f"execution failed for {request_id}")

    monkeypatch.setattr(tickets_module, "execute_halopsa_approval_request", fail_execution)
    response = client.post(
        f"/approval-requests/{approval.id}",
        json={"status": "approved", "comment": "try later"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "approved"
    assert response.json()["execution_status"] == "not_started"


def test_approval_detail_payload_edit_and_workflow_detail(settings) -> None:
    ingest_local(Store(settings.data_path), Path("examples/sample_tickets/tickets.json"))
    client = TestClient(create_app(settings))
    draft = client.post(
        "/connectors/halopsa/tickets/TCK-1002/drafts",
        json={"action_type": "add_note", "fields": {"note": "Original"}},
    )
    request_id = draft.json()["approval_request_id"]

    detail = client.get(f"/approval-requests/{request_id}")
    edited = client.patch(
        f"/approval-requests/{request_id}/payload",
        json={"fields": {"note": "Edited"}, "comment": "edited before approval"},
    )
    approved = client.post(
        f"/approval-requests/{request_id}",
        json={"status": "approved", "comment": "ready"},
    )
    rejected_edit = client.patch(
        f"/approval-requests/{request_id}/payload",
        json={"fields": {"note": "Too late"}},
    )
    events = client.get("/event-history")

    assert detail.status_code == 200
    assert detail.json()["payload"]["fields"]["note"] == "Original"
    assert detail.json()["block_reason"] == "Approval must be approved before execution."
    assert edited.status_code == 200
    assert edited.json()["payload"]["fields"]["note"] == "Edited"
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"
    assert rejected_edit.status_code == 409
    assert any(event["event_type"] == "approval_request.edited" for event in events.json())

    workflow = client.post(
        "/workflows/templates/documentation-assisted-response/runs",
        json={"ticket_id": "TCK-1002"},
    )
    workflow_detail = client.get(f"/workflow-runs/{workflow.json()['id']}")

    assert workflow_detail.status_code == 200
    assert workflow_detail.json()["template"]["risk_level"] == "medium"
    assert workflow_detail.json()["approval_request"]["workflow_run_id"] == workflow.json()["id"]


def test_legacy_approval_rows_are_redacted_in_api_views(settings) -> None:
    store = Store(settings.data_path)
    approval = store.create_approval_request("TCK-LEGACY", "halopsa.add_note", {})
    with store._connect() as connection:
        connection.execute(
            """
            update approval_requests
            set payload_json = ?, comment = ?, execution_result_json = ?
            where id = ?
            """,
            (
                '{"fields":{"api_key":"legacy-secret"}}',
                "token=legacy-comment-secret",
                '{"output":{"password":"legacy-output-secret"}}',
                approval.id,
            ),
        )
    client = TestClient(create_app(settings))

    response = client.get(f"/approval-requests/{approval.id}")
    payload = response.json()

    assert response.status_code == 200
    assert "legacy-secret" not in response.text
    assert "legacy-comment-secret" not in response.text
    assert "legacy-output-secret" not in response.text
    assert payload["payload"]["fields"]["api_key"] == "[redacted]"
    assert payload["output"]["output"]["password"] == "[redacted]"


def test_ticket_status_history_api_exposes_recorded_transitions(settings, tmp_path) -> None:
    ticket_file = tmp_path / "ticket.json"
    ticket_file.write_text(
        "[{\"id\":\"TCK-HISTORY\",\"client\":\"Acme\",\"subject\":\"History\","
        "\"body\":\"Status tracking\",\"priority\":\"normal\",\"status\":\"open\","
        "\"client_id\":\"acme\",\"created_at\":\"2026-08-08T10:00:00+00:00\","
        "\"updated_at\":\"2026-08-08T10:00:00+00:00\"}]",
        encoding="utf-8",
    )
    ingest_local(Store(settings.data_path), ticket_file)
    client = TestClient(create_app(settings))

    response = client.get("/tickets/TCK-HISTORY/status-history")

    assert response.status_code == 200
    assert response.json() == [{
        "id": 1,
        "ticket_id": "TCK-HISTORY",
        "client_id": "acme",
        "from_status": "",
        "to_status": "open",
        "changed_at": "2026-08-08T10:00:00+00:00",
        "source": "ticket_ingest",
    }]

