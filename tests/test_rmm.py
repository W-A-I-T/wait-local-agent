from __future__ import annotations

from dataclasses import replace

import httpx

from wait_local_agent.connectors import list_connector_statuses, validate_connector_credentials
from wait_local_agent.rmm import NinjaOneClient


def _configured(settings, *, allow_http_probing: bool = True):
    return replace(
        settings,
        allow_http_probing=allow_http_probing,
        ninjaone_base_url="https://app.ninjarmm.com",
        ninjaone_client_id="client-id",
        ninjaone_client_secret="client-secret",
        ninjaone_scope="monitoring",
    )


def test_ninjaone_defaults_block_and_missing_credentials(settings) -> None:
    blocked = NinjaOneClient(settings).list_devices()
    assert blocked.result.status == "blocked"
    assert blocked.items == []

    missing = NinjaOneClient(replace(settings, allow_http_probing=True)).health()
    assert missing.status == "not_configured"
    assert "WAIT_NINJAONE_BASE_URL" in missing.message


def test_ninjaone_read_contract_normalizes_inventory_and_caches_token(settings) -> None:
    calls: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if request.url.path == "/ws/oauth/token":
            assert b"client_secret=client-secret" in request.content
            return httpx.Response(200, json={"access_token": "access-token", "expires_in": 3600})
        if request.url.path == "/api/v2/devices":
            assert request.headers["Authorization"] == "Bearer access-token"
            assert request.url.params["pageSize"] == "2"
            return httpx.Response(
                200,
                json=[
                    {
                        "id": 17,
                        "organizationId": 8,
                        "locationId": 9,
                        "displayName": "Workstation 17",
                        "systemName": "WS-17",
                        "nodeClass": "WINDOWS_WORKSTATION",
                        "offline": False,
                        "approvalStatus": "APPROVED",
                        "lastContact": "2026-08-07T20:00:00Z",
                    },
                    {"displayName": "missing id"},
                ],
            )
        if request.url.path == "/api/v2/alerts":
            return httpx.Response(
                200,
                json={"data": [{"uid": "alert-1", "deviceId": 17, "severity": "critical", "message": "Offline"}]},
            )
        if request.url.path == "/api/v2/automation/scripts":
            return httpx.Response(
                200,
                json={"scripts": [{"id": 4, "name": "Collect logs", "language": "powershell"}]},
            )
        raise AssertionError(f"unexpected request: {request.url}")

    client = NinjaOneClient(_configured(settings), transport=httpx.MockTransport(handler))

    assert client.health().status == "ready"
    devices = client.list_devices(page_size=2, after="16")
    alerts = client.list_alerts(page_size=2)
    scripts = client.list_scripts()

    assert devices.result.count == 1
    assert devices.items[0]["display_name"] == "Workstation 17"
    assert devices.items[0]["offline"] is False
    assert alerts.items == [
        {
            "id": "alert-1",
            "device_id": "17",
            "organization_id": "",
            "severity": "critical",
            "message": "Offline",
            "created_at": "",
        }
    ]
    assert scripts.items[0]["name"] == "Collect logs"
    assert calls.count(("POST", "/ws/oauth/token")) == 1
    assert ("GET", "/api/v2/devices") in calls
    assert ("GET", "/api/v2/alerts") in calls
    assert ("GET", "/api/v2/automation/scripts") in calls


def test_ninjaone_script_preview_never_echoes_variable_values(settings) -> None:
    response = NinjaOneClient(_configured(settings)).preview_script(
        "17",
        "4",
        {"api_token": "do-not-return", "Path": "/tmp/logs"},
    )

    assert response.result.status == "ready"
    assert response.items[0] == {
        "device_id": "17",
        "script_id": "4",
        "operation": "script.run",
        "approval_required": True,
        "execution_enabled": False,
        "variable_names": ["Path", "api_token"],
    }
    assert "do-not-return" not in str(response.items)
    assert NinjaOneClient(_configured(settings)).preview_script("17/escape", "4").result.status == "failed"


def test_ninjaone_sanitizes_http_and_json_failures(settings) -> None:
    def unauthorized(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/ws/oauth/token":
            return httpx.Response(401, text="secret response body")
        raise AssertionError

    client = NinjaOneClient(_configured(settings), transport=httpx.MockTransport(unauthorized))
    result = client.health()
    assert result.status == "failed"
    assert "HTTP 401" in result.message
    assert "secret response body" not in result.message

    def malformed(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/ws/oauth/token":
            return httpx.Response(200, json={"access_token": "token", "expires_in": 3600})
        return httpx.Response(200, text="not-json")

    malformed_result = NinjaOneClient(
        _configured(settings), transport=httpx.MockTransport(malformed)
    ).list_devices()
    assert malformed_result.result.status == "failed"
    assert "malformed JSON" in malformed_result.result.message


def test_ninjaone_connector_status_and_validation(settings) -> None:
    blocked = list_connector_statuses(_configured(settings, allow_http_probing=False))
    ninjaone = next(item for item in blocked if item.id == "ninjaone")
    assert ninjaone.status == "blocked"

    class FakeClient:
        def health(self):
            from wait_local_agent.models import ConnectorReadResult

            return ConnectorReadResult("ready", "ok")

    result = validate_connector_credentials(
        "ninjaone",
        _configured(settings),
        ninjaone_client=FakeClient(),  # type: ignore[arg-type]
    )
    assert result.passed is True
    assert result.layer == "connector"
