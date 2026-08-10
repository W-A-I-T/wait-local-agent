from __future__ import annotations

import json
from dataclasses import replace

import httpx
import pytest

from wait_local_agent.connectors import list_connector_statuses, list_secret_records
from wait_local_agent.rmm import rmm_provider_from_settings
from wait_local_agent.screenconnect import (
    ScreenConnectRmmAdapter,
    ScreenConnectRmmError,
    _extension_id,
    _safe_base_url,
    _safe_origin,
    _safe_scalar,
    _session_rows,
)
from wait_local_agent.store import Store

SESSION_ID = "11111111-2222-3333-4444-555555555555"
EXTENSION_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
AUTH_SECRET = "screenconnect-auth-secret"


def _adapter(settings, handler, **overrides) -> ScreenConnectRmmAdapter:
    values = {
        "allow_http_probing": True,
        "screenconnect_base_url": "https://screenconnect.example.test",
        "screenconnect_extension_id": EXTENSION_ID,
        "screenconnect_auth_secret": AUTH_SECRET,
        "screenconnect_origin": "https://screenconnect.example.test",
        "screenconnect_client_sessions_map_json": json.dumps({"acme": [SESSION_ID]}),
        **overrides,
    }
    return ScreenConnectRmmAdapter(
        replace(settings, **values),
        transport=httpx.MockTransport(handler),
    )


def test_screenconnect_calls_are_blocked_by_default(settings) -> None:
    active = replace(
        settings,
        screenconnect_base_url="https://screenconnect.example.test",
        screenconnect_extension_id=EXTENSION_ID,
        screenconnect_auth_secret=AUTH_SECRET,
        screenconnect_origin="https://screenconnect.example.test",
        screenconnect_client_sessions_map_json=json.dumps({"acme": [SESSION_ID]}),
    )

    with pytest.raises(ScreenConnectRmmError, match="WAIT_ALLOW_HTTP_PROBING"):
        ScreenConnectRmmAdapter(active).list_devices("acme")


def test_screenconnect_is_selected_and_reported_without_exposing_credentials(settings) -> None:
    active = replace(
        settings,
        allow_http_probing=True,
        screenconnect_base_url="https://screenconnect.example.test",
        screenconnect_extension_id=EXTENSION_ID,
        screenconnect_auth_secret=AUTH_SECRET,
        screenconnect_origin="https://screenconnect.example.test",
        screenconnect_client_sessions_map_json=json.dumps({"acme": [SESSION_ID]}),
    )

    provider = rmm_provider_from_settings(active, Store(active.data_path))
    status = next(item for item in list_connector_statuses(active) if item.id == "rmm")
    records = {item.key: item for item in list_secret_records(active)}

    assert provider.adapter_id == "screenconnect"
    assert status.name == "ScreenConnect"
    assert status.status == "configured"
    assert AUTH_SECRET not in status.message
    assert records["WAIT_SCREENCONNECT_AUTH_SECRET"].configured is True
    assert records["WAIT_SCREENCONNECT_CLIENT_SESSIONS_MAP_JSON"].configured is True


def test_screenconnect_session_reads_use_documented_extension_request_and_scope(settings) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        assert request.method == "POST"
        assert request.url.path == (
            f"/App_Extensions/{EXTENSION_ID}/Service.ashx/GetSessionDetailsBySessionID"
        )
        assert json.loads(request.content) == [SESSION_ID]
        assert request.headers["CTRLAuthHeader"] == AUTH_SECRET
        assert request.headers["Origin"] == "https://screenconnect.example.test"
        return httpx.Response(
            200,
            json={
                "SessionID": SESSION_ID,
                "Name": "Acme workstation",
                "SessionType": "Access",
                "Host": "tech.example.test",
                "IsPublic": False,
                "HostConnectedCount": 1,
                "GuestConnectedCount": 0,
                "IgnoredObject": {"secret": "not persisted"},
            },
        )

    devices = _adapter(settings, handler).list_devices("acme")

    assert [device.device_id for device in devices] == [SESSION_ID]
    assert devices[0].name == "Acme workstation"
    assert devices[0].category == "screenconnect-session"
    assert devices[0].attributes == {
        "SessionID": SESSION_ID,
        "SessionType": "Access",
        "Host": "tech.example.test",
        "IsPublic": False,
        "HostConnectedCount": 1,
        "GuestConnectedCount": 0,
    }
    assert len(seen) == 1


def test_screenconnect_reads_multiple_mapped_sessions_and_normalizes_wrappers(settings) -> None:
    second_id = "22222222-3333-4444-5555-666666666666"
    requests: list[list[str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests.append(body)
        session_id = body[0]
        return httpx.Response(
            200,
            json={"Data": [{"sessionID": session_id, "sessionName": f"Host {session_id[:4]}"}]},
        )

    adapter = _adapter(
        settings,
        handler,
        screenconnect_client_sessions_map_json=json.dumps(
            {"acme": [SESSION_ID, second_id]}
        ),
    )
    devices = adapter.list_devices("acme")

    assert requests == [[SESSION_ID], [second_id]]
    assert [device.device_id for device in devices] == [SESSION_ID, second_id]


def test_screenconnect_unsupported_operations_are_explicit(settings) -> None:
    adapter = _adapter(settings, lambda request: httpx.Response(200, json={}))

    with pytest.raises(ScreenConnectRmmError, match="alert lookup is unavailable"):
        adapter.list_alerts("acme")
    with pytest.raises(ScreenConnectRmmError, match="script catalog is unavailable"):
        adapter.list_scripts("acme")
    with pytest.raises(ScreenConnectRmmError, match="command execution is unavailable"):
        adapter.preview_script("script", "device", {}, client_id="acme")
    with pytest.raises(ScreenConnectRmmError, match="command execution is unavailable"):
        adapter.execute_script("script", "device", {}, client_id="acme")
    with pytest.raises(ScreenConnectRmmError, match="command polling is unavailable"):
        adapter.get_execution("execution", client_id="acme")


@pytest.mark.parametrize(
    ("mapping", "message"),
    [
        ("", "mapping is missing"),
        ("not-json", "is malformed"),
        ("[]", "must be an object"),
        ('{"acme": true}', "mapping is missing"),
        ('{"acme": []}', "mapping is missing"),
        ('{"acme": ["not-a-uuid"]}', "must be UUIDs"),
    ],
)
def test_screenconnect_rejects_invalid_tenant_maps(settings, mapping, message) -> None:
    adapter = _adapter(
        settings,
        lambda request: httpx.Response(200, json={}),
        screenconnect_client_sessions_map_json=mapping,
    )

    with pytest.raises(ScreenConnectRmmError, match=message):
        adapter.list_devices("acme")


def test_screenconnect_requires_scope_and_bounds_session_map(settings) -> None:
    adapter = _adapter(settings, lambda request: httpx.Response(200, json={}))
    with pytest.raises(ScreenConnectRmmError, match="explicit tenant scope"):
        adapter.list_devices(None)

    many_ids = [f"{index:08x}-1111-2222-3333-444444444444" for index in range(101)]
    with pytest.raises(ScreenConnectRmmError, match="exceeds 100"):
        _adapter(
            settings,
            lambda request: httpx.Response(200, json={}),
            screenconnect_client_sessions_map_json=json.dumps({"acme": many_ids}),
        ).list_devices("acme")


def test_screenconnect_http_errors_are_safe(settings) -> None:
    with pytest.raises(ScreenConnectRmmError, match="unauthorized") as error:
        _adapter(
            settings,
            lambda request: httpx.Response(401, text=AUTH_SECRET),
        ).list_devices("acme")
    assert AUTH_SECRET not in str(error.value)

    with pytest.raises(ScreenConnectRmmError, match="HTTP 500"):
        _adapter(settings, lambda request: httpx.Response(500, text="provider secret")).list_devices("acme")
    with pytest.raises(ScreenConnectRmmError, match="before receiving"):
        _adapter(
            settings,
            lambda request: (_ for _ in ()).throw(httpx.TimeoutException("offline")),
        ).list_devices("acme")
    with pytest.raises(ScreenConnectRmmError, match="malformed JSON"):
        _adapter(settings, lambda request: httpx.Response(200, text="not-json")).list_devices("acme")


def test_screenconnect_rejects_unsafe_connection_settings(settings) -> None:
    with pytest.raises(ScreenConnectRmmError, match=r"HTTP\(S\)"):
        _adapter(settings, lambda request: httpx.Response(200, json={}), screenconnect_base_url="ftp://host").list_devices("acme")
    with pytest.raises(ScreenConnectRmmError, match="query data"):
        _adapter(settings, lambda request: httpx.Response(200, json={}), screenconnect_base_url="https://host?secret=x").list_devices("acme")
    with pytest.raises(ScreenConnectRmmError, match="credentials"):
        _adapter(settings, lambda request: httpx.Response(200, json={}), screenconnect_base_url="https://user:pass@host").list_devices("acme")
    with pytest.raises(ScreenConnectRmmError, match=r"HTTP\(S\) origin"):
        _adapter(
            settings,
            lambda request: httpx.Response(200, json={}),
            screenconnect_origin="file://host",
        ).list_devices("acme")
    with pytest.raises(ScreenConnectRmmError, match="path"):
        _adapter(settings, lambda request: httpx.Response(200, json={}), screenconnect_origin="https://host/path").list_devices("acme")
    with pytest.raises(ScreenConnectRmmError, match="extension ID"):
        _adapter(
            settings,
            lambda request: httpx.Response(200, json={}),
            screenconnect_extension_id="not-a-uuid",
        ).list_devices("acme")
    with pytest.raises(ScreenConnectRmmError, match="AUTH_SECRET"):
        _adapter(
            settings,
            lambda request: httpx.Response(200, json={}),
            screenconnect_auth_secret="",
        ).list_devices("acme")


def test_screenconnect_normalizers_fail_closed() -> None:
    assert _session_rows([{"Name": "host"}, "ignored"]) == [{"Name": "host"}]
    assert _session_rows({"sessions": [{"SessionID": SESSION_ID}]}) == [{"SessionID": SESSION_ID}]
    assert _session_rows({"SessionID": SESSION_ID}) == [{"SessionID": SESSION_ID}]
    assert _session_rows({"data": "ignored"}) == []
    assert _session_rows("ignored") == []
    assert _safe_scalar({"secret": "value"}) is None
    assert _safe_scalar("value") == "value"
    assert _extension_id(EXTENSION_ID) == EXTENSION_ID
    assert _safe_base_url("https://host/") == "https://host"
    assert _safe_origin("https://host/") == "https://host"
