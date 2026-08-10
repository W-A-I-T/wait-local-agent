from __future__ import annotations

import json
from dataclasses import replace

import httpx
import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute
from starlette.requests import Request
from typer.testing import CliRunner

import wait_local_agent.api.app as app_module
import wait_local_agent.cli as cli_module
from wait_local_agent.api.app import create_app
from wait_local_agent.connectors import list_connector_statuses, list_secret_records, validate_connector_credentials
from wait_local_agent.models import ConnectorReadResult
from wait_local_agent.rbac import AuthContext, Role
from wait_local_agent.scalepad import (
    ScalePadClient,
    ScalePadClientResponse,
    ScalePadGoalResponse,
    ScalePadReadError,
    ScalePadRiskSummaryResponse,
    _bound_risk_value,
    _bounded_provider_id,
    _endpoint_url,
    _normalize_client,
    _normalize_goal,
    _optional_cursor,
    _optional_nonnegative_int,
    _optional_provider_id,
    _safe_client_id,
)
from wait_local_agent.smart_actions import SmartActionService
from wait_local_agent.store import Store

CLIENTS_JSON = {
    "data": [
        {
            "id": "sp-client-1",
            "name": "Acme Corporation",
            "lifecycle": "active",
            "num_contacts": 12,
            "num_hardware_assets": 48,
            "record_created_at": "2026-01-01T00:00:00Z",
            "record_updated_at": "2026-08-01T00:00:00Z",
        },
        {"id": "sp-other", "name": "Other Tenant"},
        "malformed row",
    ],
    "total_count": 1,
    "next_cursor": "cursor-next",
}

RISK_SUMMARIES_JSON = {
    "data": [
        {
            "client": {"tenant_id": "sp-tenant-1", "name": "Acme Corporation"},
            "summary": {"open": 2, "closed": 4},
            "api_key": "scalepad-secret-token",
        },
        {"client": {"tenant_id": "sp-other-tenant"}, "summary": {"open": 99}},
        "malformed row",
    ],
    "total_count": 1,
    "next_cursor": "Y3Vyc29yLTI=",
}

GOALS_JSON = {
    "data": [
        {
            "id": "goal-1",
            "title": "Improve security posture",
            "status": "AtRisk",
            "client": {"id": "sp-lifecycle-client-1", "name": "Acme Corporation"},
            "secret": "scalepad-secret-token",
        },
        {"id": "goal-other", "client": {"id": "sp-other-client"}},
        "malformed row",
    ],
    "total_count": 1,
    "next_cursor": "Y3Vyc29yLWdvYWxz",
}


def _client(settings, handler, **overrides) -> ScalePadClient:
    values = {
        "allow_http_probing": True,
        "scalepad_base_url": "https://api.scalepad.com",
        "scalepad_api_key": "scalepad-secret-token",
        "scalepad_client_map_json": json.dumps({"acme": "sp-client-1"}),
    }
    values.update(overrides)
    active = replace(settings, **values)
    return ScalePadClient(active, transport=httpx.MockTransport(handler))


def test_scalepad_client_read_is_filtered_and_rechecked(settings) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        assert request.url.path == "/core/v1/clients"
        assert request.headers["x-api-key"] == "scalepad-secret-token"
        assert request.url.params["filter[id]"] == "eq:sp-client-1"
        assert request.url.params["page_size"] == "1"
        return httpx.Response(200, json=CLIENTS_JSON)

    response = _client(settings, handler).get_client(client_id="acme")

    assert response.result.status == "ready"
    assert [item.id for item in response.items] == ["sp-client-1"]
    assert response.items[0].num_hardware_assets == 48
    assert response.next_cursor == "cursor-next"
    assert len(seen) == 1


def test_scalepad_risk_summary_uses_separate_tenant_mapping_and_rechecks_scope(settings) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        assert request.url.path == "/controlmap/v1/clients/risks-summary"
        assert request.headers["x-api-key"] == "scalepad-secret-token"
        assert request.url.params["filter[client.tenant_id]"] == "eq:sp-tenant-1"
        assert request.url.params["page_size"] == "20"
        return httpx.Response(200, json=RISK_SUMMARIES_JSON)

    response = _client(
        settings,
        handler,
        scalepad_risk_tenant_map_json=json.dumps({"acme": "sp-tenant-1"}),
    ).get_risk_summary(client_id="acme")

    assert response.result.status == "ready"
    assert response.result.count == 1
    assert response.total_count == 1
    assert response.next_cursor == "Y3Vyc29yLTI="
    assert response.items[0]["client"]["tenant_id"] == "sp-tenant-1"  # type: ignore[index]
    assert "scalepad-secret-token" not in json.dumps(response.items)
    assert len(seen) == 1


def test_scalepad_goals_use_separate_mapping_filters_and_recheck_scope(settings) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        assert request.url.path == "/lifecycle-manager/v1/goals"
        assert request.headers["x-api-key"] == "scalepad-secret-token"
        assert request.url.params["filter[client.id]"] == "eq:sp-lifecycle-client-1"
        assert request.url.params["filter[status]"] == "eq:AtRisk"
        assert request.url.params["filter[title]"] == "cont:security"
        assert request.url.params["cursor"] == "Y3Vyc29yLW9sZA=="
        assert request.url.params["page_size"] == "20"
        return httpx.Response(200, json=GOALS_JSON)

    response = _client(
        settings,
        handler,
        scalepad_lifecycle_client_map_json=json.dumps({"acme": "sp-lifecycle-client-1"}),
    ).get_goals(
        client_id="acme",
        status="AtRisk",
        title="security",
        cursor="Y3Vyc29yLW9sZA==",
    )

    assert response.result.status == "ready"
    assert response.result.count == 1
    assert response.total_count == 1
    assert response.next_cursor == "Y3Vyc29yLWdvYWxz"
    assert response.items[0]["client"]["id"] == "sp-lifecycle-client-1"  # type: ignore[index]
    assert "scalepad-secret-token" not in json.dumps(response.items)
    assert len(seen) == 1


def test_scalepad_goals_require_mapping_and_reject_invalid_filters(settings) -> None:
    client = _client(settings, lambda request: httpx.Response(200, json=GOALS_JSON))
    missing = client.get_goals(client_id="acme")
    assert missing.result.status == "not_configured"
    assert "WAIT_SCALEPAD_LIFECYCLE_CLIENT_MAP_JSON" in missing.result.message

    mapped = _client(
        settings,
        lambda request: httpx.Response(200, json=GOALS_JSON),
        scalepad_lifecycle_client_map_json=json.dumps({"acme": "sp-lifecycle-client-1"}),
    )
    assert "goal status" in mapped.get_goals(client_id="acme", status="Unknown").result.message
    assert "goal title" in mapped.get_goals(client_id="acme", title=" ").result.message
    assert "Base64" in mapped.get_goals(client_id="acme", cursor="invalid cursor").result.message
    outside = mapped.get_goals(client_id="other")
    assert outside.result.status == "failed"
    assert "tenant scope" in outside.result.message

    malformed = _client(
        settings,
        lambda request: httpx.Response(200, json={"data": {}}),
        scalepad_lifecycle_client_map_json=json.dumps({"acme": "sp-lifecycle-client-1"}),
    ).get_goals(client_id="acme")
    assert malformed.result.status == "failed"
    assert "malformed goal data" in malformed.result.message

    blocked = _client(
        settings,
        lambda request: httpx.Response(200, json=GOALS_JSON),
        allow_http_probing=False,
        scalepad_lifecycle_client_map_json=json.dumps({"acme": "sp-lifecycle-client-1"}),
    ).get_goals(client_id="acme")
    assert blocked.result.status == "blocked"


def test_scalepad_risk_summary_requires_separate_mapping_and_handles_malformed_data(settings) -> None:
    client = _client(settings, lambda request: httpx.Response(200, json=RISK_SUMMARIES_JSON))
    missing = client.get_risk_summary(client_id="acme")
    assert missing.result.status == "not_configured"
    assert "WAIT_SCALEPAD_RISK_TENANT_MAP_JSON" in missing.result.message

    malformed = _client(
        settings,
        lambda request: httpx.Response(200, json={"data": {}}),
        scalepad_risk_tenant_map_json=json.dumps({"acme": "sp-tenant-1"}),
    ).get_risk_summary(client_id="acme")
    assert malformed.result.status == "failed"
    assert "malformed risk-summary data" in malformed.result.message

    outside = _client(
        settings,
        lambda request: httpx.Response(200, json=RISK_SUMMARIES_JSON),
        scalepad_risk_tenant_map_json=json.dumps({"acme": "sp-tenant-1"}),
    ).get_risk_summary(client_id="other")
    assert outside.result.status == "failed"
    assert "tenant scope" in outside.result.message

    invalid_object = _client(
        settings,
        lambda request: httpx.Response(200, json=[]),
        scalepad_risk_tenant_map_json=json.dumps({"acme": "sp-tenant-1"}),
    ).get_risk_summary(client_id="acme")
    assert invalid_object.result.status == "failed"
    assert "malformed response object" in invalid_object.result.message

    blocked = _client(
        settings,
        lambda request: httpx.Response(200, json=RISK_SUMMARIES_JSON),
        allow_http_probing=False,
        scalepad_risk_tenant_map_json=json.dumps({"acme": "sp-tenant-1"}),
    ).get_risk_summary(client_id="acme")
    assert blocked.result.status == "blocked"

    for mapping, expected in [
        ("not-json", "malformed"),
        ("[]", "must be an object"),
        ('{"acme": 1}', "non-empty strings"),
    ]:
        invalid_mapping = _client(
            settings,
            lambda request: httpx.Response(200, json=RISK_SUMMARIES_JSON),
            scalepad_risk_tenant_map_json=mapping,
        ).get_risk_summary(client_id="acme")
        assert invalid_mapping.result.status == "failed"
        assert expected in invalid_mapping.result.message

    assert _optional_cursor(None) == ""
    assert _optional_cursor("invalid cursor") == ""
    assert _optional_cursor("x" * 201) == ""
    assert isinstance(_bound_risk_value(object(), depth=0), str)
    assert _bound_risk_value("value", depth=5) == "[truncated]"


def test_scalepad_health_action_and_connector_surfaces(settings) -> None:
    client = _client(settings, lambda request: httpx.Response(200, json=CLIENTS_JSON))
    assert client.health().status == "ready"
    lifecycle_only = _client(
        settings,
        lambda request: httpx.Response(200, json=GOALS_JSON),
        scalepad_client_map_json="",
        scalepad_lifecycle_client_map_json=json.dumps({"acme": "sp-lifecycle-client-1"}),
    )
    assert lifecycle_only.health().status == "ready"
    assert validate_connector_credentials(
        "scalepad", lifecycle_only.settings, scalepad_client=lifecycle_only
    ).passed is True
    assert _client(
        settings,
        lambda request: httpx.Response(200, json=CLIENTS_JSON),
        scalepad_client_map_json="{}",
    ).health().status == "failed"
    status = next(item for item in list_connector_statuses(client.settings) if item.id == "scalepad")
    validation = validate_connector_credentials("scalepad", client.settings, scalepad_client=client)
    secret_keys = {item.key for item in list_secret_records(client.settings)}

    service = SmartActionService(Store(client.settings.data_path), client.settings, scalepad_client=client)
    result = service.invoke(
        "scalepad-client-lookup",
        {"client_id": "acme"},
        "tech",
        client_id="acme",
    )

    assert status.status == "configured"
    assert validation.passed is True
    assert {"WAIT_SCALEPAD_API_KEY", "WAIT_SCALEPAD_CLIENT_MAP_JSON"} <= secret_keys
    assert "WAIT_SCALEPAD_LIFECYCLE_CLIENT_MAP_JSON" in secret_keys
    assert result.status == "success"
    assert result.output["count"] == 1
    assert result.evidence[0]["operation"] == "clients.get"

    risk_client = _client(
        settings,
        lambda request: httpx.Response(200, json=RISK_SUMMARIES_JSON),
        scalepad_risk_tenant_map_json=json.dumps({"acme": "sp-tenant-1"}),
    )
    risk_service = SmartActionService(
        Store(risk_client.settings.data_path),
        risk_client.settings,
        scalepad_client=risk_client,
    )
    risk_result = risk_service.invoke(
        "scalepad-risk-summary",
        {"client_id": "acme"},
        "tech",
        client_id="acme",
    )
    assert risk_result.status == "success"
    assert risk_result.output["count"] == 1
    assert risk_result.evidence[0]["operation"] == "clients.risks-summary"

    goal_client = _client(
        settings,
        lambda request: httpx.Response(200, json=GOALS_JSON),
        scalepad_lifecycle_client_map_json=json.dumps({"acme": "sp-lifecycle-client-1"}),
    )
    goal_service = SmartActionService(
        Store(goal_client.settings.data_path),
        goal_client.settings,
        scalepad_client=goal_client,
    )
    goal_result = goal_service.invoke(
        "scalepad-goal-lookup",
        {"client_id": "acme", "status": "AtRisk"},
        "tech",
        client_id="acme",
    )
    assert goal_result.status == "success"
    assert goal_result.output["count"] == 1
    assert goal_result.evidence[0]["operation"] == "lifecycle-manager.goals"


def test_scalepad_api_routes_are_reachable_and_tenant_scoped(settings) -> None:
    active = replace(settings, allow_http_probing=True)
    routes = {getattr(route, "path", "") for route in create_app(active).routes}
    assert "/connectors/scalepad/health" in routes
    assert "/connectors/scalepad/clients" in routes
    assert "/connectors/scalepad/risk-summaries" in routes
    assert "/connectors/scalepad/goals" in routes


def test_scalepad_risk_summary_api_executes_scoped_and_denied_paths(settings, monkeypatch) -> None:
    class FakeScalePadClient:
        def __init__(self, active_settings) -> None:
            self.settings = active_settings

        def health(self):
            return ConnectorReadResult("ready", "ready")

        def get_client(self, *, client_id: str):
            return ScalePadClientResponse(ConnectorReadResult("ready", "ready"), [])

        def get_risk_summary(self, *, client_id: str) -> ScalePadRiskSummaryResponse:
            assert client_id == "acme"
            return ScalePadRiskSummaryResponse(
                ConnectorReadResult("ready", "risk summary ready", 1),
                [{"client": {"tenant_id": "sp-tenant-1"}, "open": 2}],
                "Y3Vyc29yLTI=",
                1,
            )

        def get_goals(
            self,
            *,
            client_id: str,
            status: str | None = None,
            title: str | None = None,
            cursor: str | None = None,
        ) -> ScalePadGoalResponse:
            assert client_id == "acme"
            assert status is None
            assert title is None
            assert cursor is None
            return ScalePadGoalResponse(
                ConnectorReadResult("ready", "goals ready", 1),
                [{"client": {"id": "sp-lifecycle-client-1"}, "title": "Goal"}],
                "Y3Vyc29yLWdvYWxz",
                1,
            )

    monkeypatch.setattr(app_module, "ScalePadClient", FakeScalePadClient)
    app = app_module.create_app(replace(settings, demo_mode=True, client_id=""))
    route = next(
        route
        for route in app.routes
        if getattr(route, "path", "") == "/connectors/scalepad/risk-summaries"
    )
    assert isinstance(route, APIRoute)
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/connectors/scalepad/risk-summaries",
            "query_string": b"",
            "headers": [],
            "scheme": "http",
            "server": ("test", 80),
            "client": ("test", 1),
            "root_path": "",
        }
    )
    scoped = route.endpoint(request, AuthContext(Role.ADMIN, None), "acme")
    assert scoped["result"]["status"] == "ready"
    assert scoped["total_count"] == 1
    with pytest.raises(HTTPException) as denied_error:
        route.endpoint(request, AuthContext(Role.ADMIN, None), None)
    assert getattr(denied_error.value, "status_code", None) == 403


def test_scalepad_goals_api_executes_scoped_and_denied_paths(settings, monkeypatch) -> None:
    class FakeScalePadClient:
        def __init__(self, active_settings) -> None:
            self.settings = active_settings

        def health(self):
            return ConnectorReadResult("ready", "ready")

        def get_client(self, *, client_id: str):
            return ScalePadClientResponse(ConnectorReadResult("ready", "ready"), [])

        def get_risk_summary(self, *, client_id: str):
            return ScalePadRiskSummaryResponse(ConnectorReadResult("ready", "ready"), [])

        def get_goals(self, *, client_id: str, status=None, title=None, cursor=None):
            assert client_id == "acme"
            return ScalePadGoalResponse(
                ConnectorReadResult("ready", "goals ready", 1),
                [{"client": {"id": "sp-lifecycle-client-1"}, "title": "Goal"}],
                "Y3Vyc29yLWdvYWxz",
                1,
            )

    monkeypatch.setattr(app_module, "ScalePadClient", FakeScalePadClient)
    app = app_module.create_app(replace(settings, demo_mode=True, client_id=""))
    route = next(route for route in app.routes if getattr(route, "path", "") == "/connectors/scalepad/goals")
    assert isinstance(route, APIRoute)
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/connectors/scalepad/goals",
            "query_string": b"",
            "headers": [],
            "scheme": "http",
            "server": ("test", 80),
            "client": ("test", 1),
            "root_path": "",
        }
    )
    scoped = route.endpoint(request, AuthContext(Role.ADMIN, None), "acme")
    assert scoped["result"]["status"] == "ready"
    assert scoped["total_count"] == 1
    with pytest.raises(HTTPException) as denied_error:
        route.endpoint(request, AuthContext(Role.ADMIN, None), None)
    assert getattr(denied_error.value, "status_code", None) == 403


def test_scalepad_risk_summary_cli_is_reachable(settings, monkeypatch) -> None:
    client = _client(
        settings,
        lambda request: httpx.Response(200, json=RISK_SUMMARIES_JSON),
        scalepad_risk_tenant_map_json=json.dumps({"acme": "sp-tenant-1"}),
    )
    monkeypatch.setattr(cli_module, "_scalepad_client", lambda: client)
    monkeypatch.setattr(cli_module, "_store", lambda: Store(client.settings.data_path))

    result = CliRunner().invoke(cli_module.app, ["connectors", "scalepad-risk-summaries", "acme"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["result"]["status"] == "ready"
    assert payload["total_count"] == 1


def test_scalepad_goals_cli_is_reachable(settings, monkeypatch) -> None:
    client = _client(
        settings,
        lambda request: httpx.Response(200, json=GOALS_JSON),
        scalepad_lifecycle_client_map_json=json.dumps({"acme": "sp-lifecycle-client-1"}),
    )
    monkeypatch.setattr(cli_module, "_scalepad_client", lambda: client)
    monkeypatch.setattr(cli_module, "_store", lambda: Store(client.settings.data_path))

    result = CliRunner().invoke(cli_module.app, ["connectors", "scalepad-goals", "acme"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["result"]["status"] == "ready"
    assert payload["total_count"] == 1


@pytest.mark.parametrize(
    ("mapping", "expected"),
    [
        ("", "not_configured"),
        ("not-json", "malformed"),
        ("[]", "must be an object"),
        ('{"acme": ""}', "non-empty strings"),
        ('{"acme": 123}', "non-empty strings"),
    ],
)
def test_scalepad_requires_explicit_client_mapping(settings, mapping, expected) -> None:
    client = _client(
        settings,
        lambda request: httpx.Response(200, json=CLIENTS_JSON),
        scalepad_client_map_json=mapping,
    )
    response = client.get_client(client_id="acme")
    assert response.result.status == ("not_configured" if mapping == "" else "failed")
    assert expected in response.result.status or expected in response.result.message


def test_scalepad_blocks_missing_scope_and_http(settings) -> None:
    blocked = _client(
        settings,
        lambda request: httpx.Response(200, json=CLIENTS_JSON),
        allow_http_probing=False,
    )
    assert blocked.health().status == "blocked"
    assert blocked.get_client(client_id="acme").result.status == "blocked"
    assert blocked.get_client(client_id="other").result.status == "blocked"

    client = _client(settings, lambda request: httpx.Response(200, json=CLIENTS_JSON))
    outside = client.get_client(client_id="other")
    assert outside.result.status == "failed"
    assert "tenant scope" in outside.result.message

    missing = ScalePadClient(replace(settings, allow_http_probing=True))
    assert missing.health().status == "not_configured"
    with pytest.raises(ScalePadReadError, match="blocked"):
        blocked._get("core/v1/clients")
    with pytest.raises(ScalePadReadError, match="incomplete"):
        missing._get("core/v1/clients")


@pytest.mark.parametrize(
    ("status_code", "message"),
    [
        (401, "unauthorized"),
        (403, "unauthorized"),
        (402, "subscription"),
        (429, "rate limited"),
        (500, "HTTP 500"),
    ],
)
def test_scalepad_handles_provider_errors(settings, status_code, message) -> None:
    client = _client(settings, lambda request: httpx.Response(status_code, text="scalepad-secret-token"))
    response = client.get_client(client_id="acme")
    assert response.result.status == "failed"
    assert message in response.result.message
    assert "scalepad-secret-token" not in response.result.message


def test_scalepad_handles_malformed_transport_and_action_scope(settings) -> None:
    malformed_json = _client(settings, lambda request: httpx.Response(200, text="not-json"))
    assert "malformed JSON" in malformed_json.get_client(client_id="acme").result.message

    invalid_data = _client(settings, lambda request: httpx.Response(200, json={"data": {}}))
    assert "malformed client data" in invalid_data.get_client(client_id="acme").result.message

    invalid_object = _client(settings, lambda request: httpx.Response(200, json=[]))
    assert "malformed response object" in invalid_object.get_client(client_id="acme").result.message

    def transport_error(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection failed", request=request)

    failed_transport = _client(settings, transport_error)
    assert "before receiving" in failed_transport.get_client(client_id="acme").result.message

    def generic_transport_error(request: httpx.Request) -> httpx.Response:
        raise httpx.WriteError("write failed", request=request)

    generic = _client(settings, generic_transport_error)
    assert generic.get_client(client_id="acme").result.message == "ScalePad request failed."

    client = _client(settings, lambda request: httpx.Response(200, json=CLIENTS_JSON))
    service = SmartActionService(Store(client.settings.data_path), client.settings, scalepad_client=client)
    outside = service.invoke(
        "scalepad-client-lookup",
        {"client_id": "other"},
        "tech",
        client_id="acme",
    )
    assert outside.status == "failed"
    assert "tenant scope" in outside.error_detail


def test_scalepad_unsafe_urls_and_normalizers(settings) -> None:
    with pytest.raises(ScalePadReadError, match="HTTPS"):
        _endpoint_url("http://api.scalepad.com", "core/v1/clients")
    with pytest.raises(ScalePadReadError, match="credentials"):
        _endpoint_url("https://user:pass@api.scalepad.com", "core/v1/clients")
    with pytest.raises(ScalePadReadError, match="not supported"):
        _endpoint_url("https://api.scalepad.com", "core/v1/other")
    with pytest.raises(ScalePadReadError, match="tenant scope"):
        _safe_client_id(None)  # type: ignore[arg-type]
    with pytest.raises(ScalePadReadError, match="tenant scope"):
        _safe_client_id("")
    with pytest.raises(ScalePadReadError, match="tenant scope"):
        _safe_client_id("x" * 121)
    with pytest.raises(ScalePadReadError, match="non-empty strings"):
        _client(
            settings,
            lambda request: httpx.Response(200, json=CLIENTS_JSON),
            scalepad_client_map_json='{"acme": 1}',
        )._client_mapping("acme")
    with pytest.raises(ScalePadReadError, match="bounded strings"):
        _client(
            settings,
            lambda request: httpx.Response(200, json=CLIENTS_JSON),
            scalepad_client_map_json='{"acme": "' + ("x" * 201) + '"}',
        )._client_mapping("acme")
    with pytest.raises(ScalePadReadError, match="control characters"):
        _client(
            settings,
            lambda request: httpx.Response(200, json=CLIENTS_JSON),
            scalepad_client_map_json='{"acme": "bad\\nvalue"}',
        )._client_mapping("acme")
    with pytest.raises(ScalePadReadError, match="non-empty strings"):
        _bounded_provider_id(1)
    with pytest.raises(ScalePadReadError, match="bounded strings"):
        _bounded_provider_id("")
    with pytest.raises(ScalePadReadError, match="control characters"):
        _bounded_provider_id("bad\nvalue")
    with pytest.raises(ScalePadReadError, match="invalid"):
        _endpoint_url("https://" + ("x" * 250), "core/v1/clients")
    with pytest.raises(ScalePadReadError, match="invalid"):
        _endpoint_url("https://api.scalepad.com\n", "core/v1/clients")
    assert _normalize_client(None, "sp-client-1") is None
    assert _normalize_client({"name": "missing id"}, "sp-client-1") is None
    assert _optional_nonnegative_int(None) is None
    assert _optional_nonnegative_int("") is None
    assert _optional_nonnegative_int("not-an-int") is None
    assert _optional_nonnegative_int(-1) is None
    assert _optional_provider_id(None) == ""
    assert _normalize_client({"id": "wrong"}, "sp-client-1") is None
    assert _normalize_goal({"client": {"id": "wrong"}}, "sp-client-1") is None


class _FailedScalePadProvider:
    def health(self) -> ConnectorReadResult:
        return ConnectorReadResult("failed", "provider unavailable")

    def get_client(self, *, client_id: str) -> ScalePadClientResponse:
        return ScalePadClientResponse(ConnectorReadResult("failed", "provider unavailable"), [])

    def get_risk_summary(self, *, client_id: str) -> ScalePadRiskSummaryResponse:
        return ScalePadRiskSummaryResponse(ConnectorReadResult("failed", "provider unavailable"), [])

    def get_goals(
        self,
        *,
        client_id: str,
        status: str | None = None,
        title: str | None = None,
        cursor: str | None = None,
    ) -> ScalePadGoalResponse:
        return ScalePadGoalResponse(ConnectorReadResult("failed", "provider unavailable"), [])
