from __future__ import annotations

import json
from dataclasses import replace

import httpx
import pytest

from wait_local_agent.ninjaone import (
    NinjaOneRmmAdapter,
    NinjaOneRmmError,
    _first_string,
    _int_string,
    _int_value,
    _job_status,
    _rows,
    _safe_base_url,
    _safe_endpoint,
)


def _adapter(settings, handler, **overrides) -> NinjaOneRmmAdapter:
    values = {
        "allow_http_probing": True,
        "ninjaone_base_url": "https://ninja.example.test/api/v2",
        "ninjaone_access_token": "ninja-secret-token",
        "ninjaone_organization_map_json": json.dumps({"acme": 42}),
        **overrides,
    }
    active = replace(settings, **values)
    return NinjaOneRmmAdapter(active, transport=httpx.MockTransport(handler))


def test_ninjaone_calls_are_blocked_by_default(settings) -> None:
    active = replace(
        settings,
        ninjaone_base_url="https://ninja.example.test/api/v2",
        ninjaone_access_token="secret",
        ninjaone_organization_map_json='{"acme": 42}',
    )
    adapter = NinjaOneRmmAdapter(active)

    with pytest.raises(NinjaOneRmmError, match="WAIT_ALLOW_HTTP_PROBING"):
        adapter.list_devices("acme")


@pytest.mark.parametrize(
    ("mapping", "message"),
    [
        ("", "tenant organization mapping is missing"),
        ("not-json", "is malformed"),
        ("[]", "must be an object"),
        ('{"acme": 0}', "must be positive"),
    ],
)
def test_ninjaone_requires_explicit_valid_tenant_map(settings, mapping, message) -> None:
    adapter = _adapter(settings, lambda request: httpx.Response(200, json=[]), ninjaone_organization_map_json=mapping)

    with pytest.raises(NinjaOneRmmError, match=message):
        adapter.list_devices("acme")


def test_ninjaone_inventory_filters_rows_to_mapped_organization(settings) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path.endswith("/devices"):
            return httpx.Response(
                200,
                json=[
                    {"id": 7, "organizationId": 42, "displayName": "Acme laptop"},
                    {"id": 8, "organizationId": 99, "displayName": "Other laptop"},
                ],
            )
        if request.url.path.endswith("/alerts"):
            return httpx.Response(
                200,
                json=[
                    {"uid": "a-1", "deviceId": 7, "organizationId": 42, "severity": "high", "message": "Disk"},
                    {"uid": "a-2", "deviceId": 8, "organizationId": 99, "severity": "critical", "message": "Other"},
                ],
            )
        if request.url.path.endswith("/automation/scripts"):
            return httpx.Response(200, json={"data": [{"id": 12, "name": "Collect logs"}]})
        raise AssertionError(request.url)

    adapter = _adapter(settings, handler)
    devices = adapter.list_devices("acme")
    alerts = adapter.list_alerts("acme")
    scripts = adapter.list_scripts("acme")

    assert [device.device_id for device in devices] == ["7"]
    assert [alert.alert_id for alert in alerts] == ["a-1"]
    assert scripts[0].script_id == "12"
    assert all(
        request.headers["authorization"] == "Bearer ninja-secret-token"
        for request in seen
    )
    assert all(
        request.url.params["df"] == "org = 42"
        for request in seen
        if request.url.path.endswith(("/devices", "/alerts"))
    )


def test_ninjaone_preview_checks_device_and_script_scope(settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/devices"):
            return httpx.Response(200, json=[{"id": 7, "organizationId": 42, "displayName": "Acme laptop"}])
        return httpx.Response(200, json=[{"id": 12, "name": "Collect logs"}])

    preview = _adapter(settings, handler).preview_script(
        "12", "7", {"days": "7"}, client_id="acme"
    )

    assert preview.status == "preview"
    assert preview.arguments == {"days": "7"}


def test_ninjaone_approved_execution_uses_documented_run_endpoint(settings) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path.endswith("/devices"):
            return httpx.Response(200, json=[{"id": 7, "organizationId": 42, "displayName": "Acme laptop"}])
        if request.url.path.endswith("/automation/scripts"):
            return httpx.Response(200, json=[{"id": 12, "name": "Collect logs"}])
        if request.url.path.endswith("/script/run"):
            return httpx.Response(202, json={"jobId": "job-1", "token": "do-not-return"})
        raise AssertionError(request.url)

    execution = _adapter(settings, handler).execute_script(
        "12", "7", {"days": "7"}, client_id="acme"
    )
    run_request = next(request for request in seen if request.url.path.endswith("/script/run"))

    assert run_request.method == "POST"
    assert run_request.url.path == "/api/v2/device/7/script/run"
    assert run_request.content == b'{"type":"SCRIPT","id":12,"parameters":"{\\"days\\":\\"7\\"}"}'
    assert execution.status == "queued"
    assert execution.execution_id == "job-1"
    assert "do-not-return" not in execution.message


def test_ninjaone_execution_lookup_requires_tenant_proof(settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/jobs"):
            return httpx.Response(
                200,
                json=[
                    {"id": "wrong", "organizationId": 99, "status": "completed", "deviceId": 8},
                    {"id": "job-1", "deviceId": 7, "status": "completed", "scriptId": 12},
                ],
            )
        if request.url.path.endswith("/devices"):
            return httpx.Response(200, json=[{"id": 7, "organizationId": 42}])
        raise AssertionError(request.url)

    result = _adapter(settings, handler).get_execution("job-1", client_id="acme")

    assert result.status == "succeeded"
    assert result.device_id == "7"


@pytest.mark.parametrize("status", [401, 403, 500])
def test_ninjaone_http_errors_are_sanitized(settings, status) -> None:
    adapter = _adapter(
        settings,
        lambda request: httpx.Response(status, text="ninja-secret-token leaked"),
    )

    with pytest.raises(NinjaOneRmmError) as error:
        adapter.list_devices("acme")

    assert "ninja-secret-token" not in str(error.value)
    assert "unauthorized" in str(error.value) if status in {401, 403} else "HTTP 500" in str(error.value)


def test_ninjaone_handles_timeout_malformed_json_and_unsafe_url(settings) -> None:
    timeout_adapter = _adapter(
        settings,
        lambda request: (_ for _ in ()).throw(httpx.ReadTimeout("timed out")),
    )
    with pytest.raises(NinjaOneRmmError, match="before receiving"):
        timeout_adapter.list_devices("acme")

    malformed_adapter = _adapter(
        settings,
        lambda request: httpx.Response(200, text="not-json"),
    )
    with pytest.raises(NinjaOneRmmError, match="malformed JSON"):
        malformed_adapter.list_devices("acme")

    unsafe_adapter = _adapter(settings, lambda request: httpx.Response(200, json=[]), ninjaone_base_url="https://user:pass@example.test/api/v2")
    with pytest.raises(NinjaOneRmmError, match="must not contain credentials"):
        unsafe_adapter.list_devices("acme")


def test_ninjaone_parser_helpers_bound_untrusted_shapes() -> None:
    assert _rows([{"id": 1}, "ignored"]) == [{"id": 1}]
    assert _rows({"items": [{"id": 1}, "ignored"]}) == [{"id": 1}]
    assert _rows({"unknown": []}) == []
    assert _first_string({"name": "  Acme  "}, "missing", "name") == "Acme"
    assert _first_string({"id": 4}, "id") == "4"
    assert _first_string({"id": True}, "id") == ""
    assert _int_value(True) is None
    assert _int_value("bad") is None
    assert _int_string(0) == ""
    assert _job_status({"status": "completed"}) == "succeeded"
    assert _job_status({"status": "cancelled"}) == "failed"
    assert _job_status({"status": "running"}) == "queued"


def test_ninjaone_rejects_unscoped_or_missing_inventory_rows(settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/devices"):
            return httpx.Response(200, json=[{}, {"id": 0, "organizationId": 42}, {"id": 7, "organizationId": 42}])
        if request.url.path.endswith("/alerts"):
            return httpx.Response(200, json=[{"uid": "missing-device", "organizationId": 42}])
        return httpx.Response(200, json=[{}, {"id": 12, "displayName": "Fallback"}])

    adapter = _adapter(settings, handler)
    assert adapter.list_devices("acme")[0].name == "7"
    assert adapter.list_alerts("acme") == []
    assert adapter.list_scripts("acme")[0].name == "Fallback"


def test_ninjaone_preview_rejects_unknown_device_or_script(settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/devices"):
            return httpx.Response(200, json=[])
        return httpx.Response(200, json=[])

    adapter = _adapter(settings, handler)
    with pytest.raises(NinjaOneRmmError, match="outside"):
        adapter.preview_script("12", "7", {}, client_id="acme")

    def known_device(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/devices"):
            return httpx.Response(200, json=[{"id": 7, "organizationId": 42}])
        return httpx.Response(200, json=[])

    with pytest.raises(NinjaOneRmmError, match="not found"):
        _adapter(settings, known_device).preview_script("12", "7", {}, client_id="acme")


def test_ninjaone_execution_rejects_invalid_or_unproven_jobs(settings) -> None:
    with pytest.raises(NinjaOneRmmError, match="execution ID is invalid"):
        _adapter(settings, lambda request: httpx.Response(200, json=[])).get_execution("", client_id="acme")

    def unproven(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/jobs"):
            return httpx.Response(200, json=[{"id": "job-1", "deviceId": 99}])
        return httpx.Response(200, json=[])

    with pytest.raises(NinjaOneRmmError, match="not found"):
        _adapter(settings, unproven).get_execution("job-1", client_id="acme")

    def mismatched(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[{"id": "job-1", "organizationId": 99}])

    with pytest.raises(NinjaOneRmmError, match="not found"):
        _adapter(settings, mismatched).get_execution("job-1", client_id="acme")


def test_ninjaone_missing_credentials_and_empty_post_are_safe(settings) -> None:
    missing = replace(
        settings,
        allow_http_probing=True,
        ninjaone_base_url="https://ninja.example.test/api/v2",
        ninjaone_organization_map_json='{"acme":42}',
    )
    with pytest.raises(NinjaOneRmmError, match="credentials are incomplete"):
        NinjaOneRmmAdapter(missing).list_devices("acme")

    def empty_post(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(204)
        if request.url.path.endswith("/devices"):
            return httpx.Response(200, json=[{"id": 7, "organizationId": 42}])
        return httpx.Response(200, json=[{"id": 12}])

    result = _adapter(settings, empty_post).execute_script("12", "7", {}, client_id="acme")
    assert result.execution_id == ""


def test_ninjaone_rejects_unsafe_urls_and_endpoints() -> None:
    for value in ("", "ftp://ninja.example.test", "https://ninja.example.test?x=1"):
        with pytest.raises(NinjaOneRmmError):
            _safe_base_url(value)
    for value in ("", "../devices", "devices?x=1"):
        with pytest.raises(NinjaOneRmmError):
            _safe_endpoint(value)


def test_ninjaone_validates_script_inputs_and_provider_map(settings) -> None:
    adapter = _adapter(settings, lambda request: httpx.Response(200, json=[]))
    with pytest.raises(NinjaOneRmmError, match="must be integers"):
        adapter.preview_script("not-id", "7", {}, client_id="acme")
    with pytest.raises(NinjaOneRmmError, match="limited"):
        adapter.preview_script("12", "7", {str(index): "x" for index in range(21)}, client_id="acme")
    with pytest.raises(NinjaOneRmmError, match="bounded text"):
        adapter.preview_script("12", "7", {"bad\nkey": "x"}, client_id="acme")

    non_integer = _adapter(
        settings,
        lambda request: httpx.Response(200, json=[]),
        ninjaone_organization_map_json='{"acme":"nope"}',
    )
    with pytest.raises(NinjaOneRmmError, match="must be integers"):
        non_integer.list_devices("acme")
    with pytest.raises(NinjaOneRmmError, match="explicit tenant"):
        adapter.list_devices(None)


def test_ninjaone_handles_generic_http_error_and_mapping_payloads(settings) -> None:
    broken = _adapter(
        settings,
        lambda request: (_ for _ in ()).throw(httpx.WriteError("write failed")),
    )
    with pytest.raises(NinjaOneRmmError, match="request failed$"):
        broken.list_devices("acme")

    adapter = _adapter(settings, lambda request: httpx.Response(200, json={"data": "bad", "items": [{"id": 1}]}))
    assert adapter.list_scripts("acme")[0].script_id == "1"
    adapter.settings = replace(adapter.settings, ninjaone_page_size=1000)
    assert adapter._page_size() == 100
