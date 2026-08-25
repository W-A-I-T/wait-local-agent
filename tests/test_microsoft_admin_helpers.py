from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

import httpx
import pytest

from packs.microsoft_admin.core import (
    MAX_CURSOR_LENGTH,
    MicrosoftAdminError,
    MicrosoftAdminGraphClient,
    _aggregate_status,
    _bounded_identity,
    _bounded_page_size,
    _cursor_params,
    _graph_base_url,
    _is_stale,
    _latest_secure_score,
    _mapping,
    _next_cursor,
    _normalize_autopilot_device,
    _normalize_compliance_policy,
    _normalize_conditional_access_policy,
    _normalize_intune_app,
    _normalize_risky_user,
    _normalize_secure_score,
    _normalize_security_alert,
    _normalize_security_incident,
    _normalize_service_health,
    _normalize_service_issue,
    _normalize_sign_in,
    _number,
    _payload_rows,
    _safe_endpoint,
    _string_list,
    diagnose_access,
)
from microsoft_admin_support import (
    FakeM365Core,
    FakeMicrosoftAdminProvider,
    _configured,
    _license,
    _response,
    _user,
)
from wait_local_agent.m365_graph import (
    M365GraphClient,
    M365GraphLicenseDetailReadResponse,
    M365GraphManagedDeviceReadResponse,
    M365GraphReadResponse,
)
from wait_local_agent.models import ConnectorReadResult


def test_helper_boundaries_cover_cursor_payload_normalization_and_aggregation() -> None:
    assert _bounded_page_size(250) == 100
    with pytest.raises(MicrosoftAdminError):
        _bounded_page_size(-1)
    assert _bounded_identity(" user@example.test ") == "user@example.test"
    with pytest.raises(MicrosoftAdminError):
        _bounded_identity("\x00")

    assert _cursor_params("$skip=25&$skiptoken=abc") == {"$skip": "25", "$skiptoken": "abc"}
    for invalid in ["", "x" * (MAX_CURSOR_LENGTH + 1), "$top=10", "/path?$skip=1", "$skip=1#x"]:
        with pytest.raises(MicrosoftAdminError):
            _cursor_params(invalid)

    assert _next_cursor({"@odata.nextLink": "https://graph.test/v1.0/x?$top=5"}) == ""
    assert _next_cursor({"@odata.nextLink": 3}) == ""
    assert _next_cursor([]) == ""
    assert _payload_rows({"value": [{"id": "x"}, "ignore"]}) == [{"id": "x"}]
    with pytest.raises(MicrosoftAdminError):
        _payload_rows([])
    with pytest.raises(MicrosoftAdminError):
        _payload_rows({})

    assert _aggregate_status(["ready", "ready"]) == "ready"
    assert _aggregate_status(["ready", "failed"]) == "partial"
    assert _aggregate_status(["failed"]) == "failed"
    assert _aggregate_status(["blocked"]) == "blocked"
    assert _aggregate_status(["not_configured"]) == "not_configured"
    assert _aggregate_status([]) == "not_configured"

    now = datetime(2026, 8, 25, tzinfo=UTC)
    assert _is_stale("2026-08-01T00:00:00Z", now, days=7) is True
    assert _is_stale("not-a-date", now, days=7) is False
    assert _is_stale("", now, days=7) is False
    assert _latest_secure_score([{"current_score": 50, "max_score": 100}]) == 50.0
    assert _latest_secure_score([]) is None
    assert _latest_secure_score([{"current_score": True, "max_score": 100}]) is None
    assert _latest_secure_score([{"current_score": 50, "max_score": 0}]) is None


def test_private_normalizers_drop_unusable_records_and_bound_types() -> None:
    normalizers = [
        _normalize_service_health,
        _normalize_service_issue,
        _normalize_secure_score,
        _normalize_sign_in,
        _normalize_conditional_access_policy,
        _normalize_risky_user,
        _normalize_intune_app,
        _normalize_compliance_policy,
        _normalize_autopilot_device,
        _normalize_security_incident,
        _normalize_security_alert,
    ]
    assert all(normalizer({}) is None for normalizer in normalizers)
    assert _number(True) is None
    assert _number(3) == 3.0
    assert _string_list("not-a-list") == []
    assert _string_list(["a", 2, "b"], limit=1) == ["a"]
    assert _mapping("not-a-map") == {}
    with pytest.raises(MicrosoftAdminError):
        _safe_endpoint("users")
    assert _safe_endpoint("/security/incidents/") == "security/incidents"
    assert _graph_base_url("https://graph.microsoft.com/v1.0/", allow_insecure_transport=False).endswith("v1.0")
    with pytest.raises(MicrosoftAdminError):
        _graph_base_url("ftp://graph.microsoft.com/v1.0", allow_insecure_transport=False)
    with pytest.raises(MicrosoftAdminError):
        _graph_base_url("https://graph.microsoft.com/v1.0?q=x", allow_insecure_transport=False)


def test_remaining_core_branches_use_safe_transport_and_non_ca_failure(settings, monkeypatch) -> None:
    import packs.microsoft_admin.client as client_module

    failed_health = MicrosoftAdminGraphClient(
        _configured(settings),
        transport=httpx.MockTransport(lambda request: httpx.Response(503)),
    ).health()
    assert failed_health.status == "failed"

    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={"value": [{"id": "Exchange", "service": "Exchange", "status": "ok"}]},
        )
    )
    monkeypatch.setattr(
        client_module,
        "build_pinned_client",
        lambda **kwargs: httpx.Client(transport=transport, trust_env=False),
    )
    production_path = MicrosoftAdminGraphClient(_configured(settings)).list_service_health()
    assert production_path.result.status == "ready"

    monkeypatch.setattr(client_module, "_graph_base_url", lambda *args, **kwargs: "https:///v1.0")
    invalid_host = MicrosoftAdminGraphClient(_configured(settings)).list_service_health()
    assert invalid_host.result.status == "failed"

    monkeypatch.setattr(
        client_module,
        "_graph_base_url",
        lambda *args, **kwargs: (_ for _ in ()).throw(MicrosoftAdminError("safe failure")),
    )
    direct_failure = MicrosoftAdminGraphClient(_configured(settings)).list_service_health()
    assert direct_failure.result.status == "failed"

    provider = FakeMicrosoftAdminProvider(
        {
            "sign_ins": _response(
                [
                    {
                        "created_date_time": "2026-08-24T00:00:00Z",
                        "application": "Outlook",
                        "conditional_access_status": "success",
                        "failure_reason": "Invalid credentials",
                        "error_code": 50126,
                    }
                ]
            ),
            "conditional_access": _response([{"id": "ca-1"}]),
        }
    )
    normal_core = FakeM365Core(
        users=M365GraphReadResponse(ConnectorReadResult("ready", "ready", 1), [_user()]),
        licenses=M365GraphLicenseDetailReadResponse(
            ConnectorReadResult("ready", "ready", 1),
            [_license()],
        ),
        devices=M365GraphManagedDeviceReadResponse(ConnectorReadResult("ready", "ready", 0), []),
    )
    diagnostic = diagnose_access(
        provider,
        cast(M365GraphClient, normal_core),
        user_identity="adele@example.test",
    )
    assert "recent-sign-in-failure" in {finding.code for finding in diagnostic.findings}

    assert _next_cursor({"@odata.nextLink": "https://graph.test/v1.0/items"}) == ""
    assert _is_stale("2026-08-01T00:00:00", datetime(2026, 8, 25, tzinfo=UTC), days=7) is True
