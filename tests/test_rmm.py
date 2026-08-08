from __future__ import annotations

import json
from dataclasses import replace

import httpx

from wait_local_agent.connectors import (
    _classify_validation_result,
    list_connector_statuses,
    validate_connector_credentials,
)
from wait_local_agent.rmm import (
    NinjaOneClient,
    RmmReadError,
    _api_base_url,
    _bounded_page_size,
    _payload_rows,
    _safe_endpoint,
    _safe_segment,
    _token_url,
)


def _configured(
    settings,
    *,
    allow_http_probing: bool = True,
    allow_write_actions: bool = False,
):
    return replace(
        settings,
        allow_http_probing=allow_http_probing,
        allow_write_actions=allow_write_actions,
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


def test_ninjaone_script_execution_requires_both_safety_gates_and_records_remote_job(settings) -> None:
    blocked = NinjaOneClient(_configured(settings)).execute_script("17", "4")
    assert blocked.status == "blocked"
    assert "WAIT_ALLOW_WRITE_ACTIONS" in blocked.message

    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.path == "/ws/oauth/token":
            return httpx.Response(200, json={"access_token": "access-token", "expires_in": 3600})
        assert request.url.path == "/api/v2/device/17/script/run"
        assert request.headers["Authorization"] == "Bearer access-token"
        assert json.loads(request.content)["parameters"] == '{"Path":"/tmp/logs"}'
        assert json.loads(request.content)["id"] == 4
        assert json.loads(request.content)["runAs"] == "system"
        return httpx.Response(202, json={"jobId": "job-17"})

    client = NinjaOneClient(
        _configured(settings, allow_write_actions=True),
        transport=httpx.MockTransport(handler),
    )
    result = client.execute_script("17", "4", {"Path": "/tmp/logs"}, run_as=" system ")
    assert result.status == "succeeded"
    assert result.status_code == 202
    assert result.remote_id == "job-17"
    assert [request.method for request in calls] == ["POST", "POST"]


def test_ninjaone_script_execution_rejects_unsafe_or_unbounded_inputs(settings) -> None:
    client = NinjaOneClient(_configured(settings, allow_write_actions=True))
    assert client.execute_script("17/escape", "4").status == "failed"
    assert "positive numeric" in client.execute_script("17", "script-name").message
    assert "single-line" in client.execute_script("17", "4", run_as="bad\nvalue").message
    assert "serializable" in client.execute_script("17", "4", {"value": object()}).message


def test_ninjaone_script_execution_maps_gate_http_and_response_failures(settings) -> None:
    http_blocked = NinjaOneClient(
        _configured(settings, allow_http_probing=False, allow_write_actions=True)
    ).execute_script("17", "4")
    assert http_blocked.status == "blocked"
    assert "WAIT_ALLOW_HTTP_PROBING" in http_blocked.message

    def token(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/ws/oauth/token":
            return httpx.Response(200, json={"access_token": "token"})
        return httpx.Response(503, text="private body")

    failed = NinjaOneClient(
        _configured(settings, allow_write_actions=True),
        transport=httpx.MockTransport(token),
    ).execute_script("17", "4")
    assert failed.status == "failed"
    assert "HTTP 503" in failed.message
    assert "private body" not in failed.message

    def malformed(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/ws/oauth/token":
            return httpx.Response(200, json={"access_token": "token"})
        return httpx.Response(202, text="accepted")

    malformed_result = NinjaOneClient(
        _configured(settings, allow_write_actions=True),
        transport=httpx.MockTransport(malformed),
    ).execute_script("17", "4")
    assert malformed_result.status == "succeeded"
    assert malformed_result.remote_id == ""

    def read_error(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/ws/oauth/token":
            return httpx.Response(200, json={"access_token": "token"})
        raise httpx.ReadError("read failed")

    assert (
        NinjaOneClient(
            _configured(settings, allow_write_actions=True),
            transport=httpx.MockTransport(read_error),
        ).execute_script("17", "4").message
        == "NinjaOne script request failed."
    )


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

    malformed_result = NinjaOneClient(_configured(settings), transport=httpx.MockTransport(malformed)).list_devices()
    assert malformed_result.result.status == "failed"
    assert "malformed JSON" in malformed_result.result.message


def test_ninjaone_helper_edges_and_single_reads(settings) -> None:
    assert _api_base_url("https://ninja.test/api/v2/") == "https://ninja.test/api/v2"
    assert _api_base_url("https://ninja.test/v2") == "https://ninja.test/v2"
    assert _api_base_url("https://ninja.test/api") == "https://ninja.test/api/v2"
    assert _token_url("https://ninja.test/api/v2") == "https://ninja.test/ws/oauth/token"
    assert _token_url("https://ninja.test/v2") == "https://ninja.test/ws/oauth/token"
    assert _bounded_page_size(0) == 1
    assert _bounded_page_size(1000) == 100
    assert _payload_rows({"data": []}) == []
    assert _payload_rows({"unexpected": "object"}) == [{"unexpected": "object"}]
    assert _payload_rows("not-an-object") == []
    for value in ("", "device/17", "device?bad", "//remote"):
        helper = _safe_segment if value != "//remote" else _safe_endpoint
        try:
            helper(value)
        except RmmReadError:
            pass
        else:
            raise AssertionError(f"unsafe value accepted: {value}")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/ws/oauth/token":
            return httpx.Response(200, json={"access_token": "token", "expires_in": "invalid"})
        if request.url.path == "/api/v2/device/17":
            return httpx.Response(200, json={"id": 17, "offline": "yes"})
        if request.url.path == "/api/v2/alerts":
            assert request.url.params["after"] == "cursor"
            return httpx.Response(200, json=[{"id": "alert-2", "priority": 2}])
        raise AssertionError(f"unexpected request: {request.url}")

    client = NinjaOneClient(_configured(settings), transport=httpx.MockTransport(handler))
    device = client.get_device("17")
    alerts = client.list_alerts(after="cursor")
    assert device.items[0]["offline"] is True
    assert alerts.items[0]["severity"] == "2"


def test_ninjaone_maps_transport_and_token_failures(settings) -> None:
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out")

    timeout_client = NinjaOneClient(_configured(settings), transport=httpx.MockTransport(timeout))
    assert "before receiving a response" in timeout_client.health().message

    def token_read_error(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadError("read failed")

    read_client = NinjaOneClient(_configured(settings), transport=httpx.MockTransport(token_read_error))
    assert read_client.health().message == "NinjaOne token request failed."

    def token_bad_json(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not-json")

    bad_json = NinjaOneClient(_configured(settings), transport=httpx.MockTransport(token_bad_json))
    assert bad_json.health().message == "NinjaOne token response was malformed JSON."

    def token_missing_access(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"expires_in": 10})

    missing_access = NinjaOneClient(_configured(settings), transport=httpx.MockTransport(token_missing_access))
    assert missing_access.health().message == "NinjaOne token response did not contain an access token."

    def token_connect_error(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connect failed")

    connect_client = NinjaOneClient(_configured(settings), transport=httpx.MockTransport(token_connect_error))
    assert "before receiving a response" in connect_client.health().message


def test_ninjaone_guard_and_get_error_edges(settings) -> None:
    blocked = NinjaOneClient(settings)
    assert blocked.get_device("17").result.status == "blocked"

    missing_settings = replace(settings, allow_http_probing=True)
    missing = NinjaOneClient(missing_settings)
    assert missing.list_devices().result.status == "not_configured"
    assert missing.get_device("17").result.status == "not_configured"
    try:
        missing._access_token()  # noqa: SLF001
    except RmmReadError as exc:
        assert "credentials are incomplete" in str(exc)
    else:
        raise AssertionError("missing credentials unexpectedly returned a token")

    def get_timeout(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/ws/oauth/token":
            return httpx.Response(200, json={"access_token": "token"})
        raise httpx.ReadTimeout("timed out")

    timeout = NinjaOneClient(_configured(settings), transport=httpx.MockTransport(get_timeout))
    assert "before receiving a response" in timeout.list_devices().result.message

    def get_read_error(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/ws/oauth/token":
            return httpx.Response(200, json={"access_token": "token"})
        raise httpx.ReadError("read failed")

    read_error = NinjaOneClient(_configured(settings), transport=httpx.MockTransport(get_read_error))
    assert read_error.list_devices().result.message == "NinjaOne request failed."

    def get_http_failure(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/ws/oauth/token":
            return httpx.Response(200, json={"access_token": "token"})
        return httpx.Response(503, text="private body")

    http_failure = NinjaOneClient(_configured(settings), transport=httpx.MockTransport(get_http_failure))
    failed = http_failure.list_devices()
    assert failed.result.message == "NinjaOne GET devices failed with HTTP 503."
    assert "private body" not in failed.result.message

    def normalizer_edge(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/ws/oauth/token":
            return httpx.Response(200, json={"access_token": "token"})
        if request.url.path == "/api/v2/alerts":
            return httpx.Response(200, json=[{"message": "missing id"}, {"id": "alert-2", "priority": 2}])
        if request.url.path == "/api/v2/automation/scripts":
            return httpx.Response(200, json=[{"name": "missing id"}, {"id": "script-2"}])
        return httpx.Response(200, json=[{"id": 17, "offline": 0}])

    client = NinjaOneClient(_configured(settings), transport=httpx.MockTransport(normalizer_edge))
    assert client.list_alerts().items[0]["id"] == "alert-2"
    assert client.list_scripts().items[0]["id"] == "script-2"
    assert client.list_devices().items[0]["offline"] is False


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


def test_connector_validation_edges_remain_explicit(settings) -> None:
    configured_hudu = replace(
        settings,
        allow_http_probing=False,
        hudu_base_url="https://hudu.example.test",
        hudu_api_key="api-key",
    )
    assert next(item for item in list_connector_statuses(configured_hudu) if item.id == "hudu").status == "blocked"
    assert validate_connector_credentials("halopsa", settings).layer == "config"
    assert validate_connector_credentials("ninjaone", settings).layer == "config"

    ready = _classify_validation_result("ninjaone", "ready", "ready")
    configured = _classify_validation_result("ninjaone", "not_configured", "missing")
    blocked_result = _classify_validation_result("ninjaone", "blocked", "blocked")
    unknown = _classify_validation_result("ninjaone", "failed", "unexpected failure")
    assert ready.passed is True
    assert configured.layer == "config"
    assert blocked_result.layer == "safety"
    assert unknown.layer == "connector"

    try:
        validate_connector_credentials("unknown", settings)
    except ValueError as exc:
        assert "unsupported connector" in str(exc)
    else:
        raise AssertionError("unsupported connector was accepted")
