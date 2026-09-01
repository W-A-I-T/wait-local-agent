from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

import pytest
from microsoft_admin_support import (
    FakeM365Core,
    FakeMicrosoftAdminProvider,
    _device,
    _license,
    _response,
    _user,
)

from packs.microsoft_admin.core import MicrosoftAdminError, build_dashboard, diagnose_access
from wait_local_agent.m365_graph import (
    M365GraphClient,
    M365GraphLicenseDetailReadResponse,
    M365GraphManagedDeviceReadResponse,
    M365GraphReadResponse,
)
from wait_local_agent.models import ConnectorReadResult


def test_dashboard_correlates_cloud_identity_endpoint_and_security_evidence() -> None:
    provider = FakeMicrosoftAdminProvider(
        {
            "service_health": _response(
                [{"id": "Exchange", "service": "Exchange Online", "status": "serviceDegradation"}]
            ),
            "service_issues": _response(
                [{"id": "EX123", "service": "Exchange Online", "status": "serviceDegradation"}]
            ),
            "secure_scores": _response([{"current_score": 40.0, "max_score": 100.0}]),
            "sign_ins": _response(
                [
                    {
                        "error_code": 53003,
                        "risk_level": "medium",
                        "conditional_access_status": "failure",
                    }
                ]
            ),
            "conditional_access": _response(
                [
                    {"id": "ca-1", "state": "disabled"},
                    {"id": "ca-2", "state": "enabledForReportingButNotEnforced"},
                ]
            ),
            "risky_users": _response([{"id": "user-1", "risk_level": "high"}]),
            "intune_apps": _response([{"id": "app-1"}]),
            "compliance_policies": _response([{"id": "policy-1"}]),
            "autopilot_devices": _response([{"id": "auto-1"}]),
            "defender_incidents": _response(
                [{"id": "incident-1", "status": "active", "severity": "high"}]
            ),
            "defender_alerts": _response([{"id": "alert-1", "status": "new"}]),
        }
    )
    core = FakeM365Core(
        devices=M365GraphManagedDeviceReadResponse(
            ConnectorReadResult("ready", "ready", 1),
            [_device(compliance="noncompliant", encrypted=False, last_sync="2026-08-01T00:00:00Z")],
        )
    )

    dashboard = build_dashboard(
        provider,
        cast(M365GraphClient, core),
        now=datetime(2026, 8, 25, tzinfo=UTC),
    )

    assert dashboard["status"] == "ready"
    summary = cast(dict[str, object], dashboard["summary"])
    assert summary["secure_score_percent"] == 40.0
    assert summary["noncompliant_devices"] == 1
    assert summary["unencrypted_devices"] == 1
    assert summary["stale_devices"] == 1
    assert summary["high_severity_incidents"] == 1
    codes = {item["code"] for item in cast(list[dict[str, object]], dashboard["recommendations"])}
    assert codes == {
        "defender-high-severity-incidents",
        "intune-noncompliant-devices",
        "m365-service-health",
        "entra-identity-risk",
        "secure-score-review",
    }
    recommendations = cast(list[dict[str, object]], dashboard["recommendations"])
    assert all(item["automatic_execution"] is False for item in recommendations)


def test_dashboard_preserves_partial_and_failed_source_states() -> None:
    provider = FakeMicrosoftAdminProvider(
        {
            "service_health": _response(status="failed"),
            "service_issues": _response(status="blocked"),
            "secure_scores": _response(status="not_configured"),
            "sign_ins": _response(status="ready"),
        }
    )
    core = FakeM365Core(
        devices=M365GraphManagedDeviceReadResponse(
            ConnectorReadResult("not_configured", "missing", 0),
            [],
        )
    )
    dashboard = build_dashboard(provider, cast(M365GraphClient, core))
    assert dashboard["status"] == "partial"
    assert cast(dict[str, object], dashboard["summary"])["secure_score_percent"] is None


def test_access_diagnostic_finds_identity_license_ca_risk_service_and_endpoint_causes() -> None:
    provider = FakeMicrosoftAdminProvider(
        {
            "sign_ins": _response(
                [
                    {
                        "created_date_time": "2026-08-24T00:00:00Z",
                        "application": "SharePoint Online",
                        "conditional_access_status": "failure",
                        "failure_reason": "Device is not compliant",
                        "error_code": 53003,
                        "risk_level": "medium",
                    }
                ]
            ),
            "service_issues": _response(
                [
                    {
                        "id": "SP123",
                        "service": "SharePoint Online",
                        "title": "Access issue",
                        "status": "serviceDegradation",
                    }
                ]
            ),
            "risky_users": _response(
                [
                    {
                        "user_principal_name": "adele@example.test",
                        "risk_level": "high",
                        "risk_state": "atRisk",
                        "risk_last_updated_date_time": "2026-08-24T00:00:00Z",
                    }
                ]
            ),
            "conditional_access": _response([{"id": "ca-1", "state": "enabled"}]),
        }
    )
    core = FakeM365Core(
        users=M365GraphReadResponse(
            ConnectorReadResult("ready", "ready", 1),
            [_user(enabled=False)],
        ),
        licenses=M365GraphLicenseDetailReadResponse(
            ConnectorReadResult("ready", "ready", 0),
            [],
        ),
        devices=M365GraphManagedDeviceReadResponse(
            ConnectorReadResult("ready", "ready", 1),
            [_device(compliance="noncompliant", encrypted=False)],
        ),
    )

    diagnostic = diagnose_access(
        provider,
        cast(M365GraphClient, core),
        user_identity=" adele@example.test ",
        device_name="LAPTOP-001",
        now=datetime(2026, 8, 25, tzinfo=UTC),
    )

    codes = {finding.code for finding in diagnostic.findings}
    assert diagnostic.evidence_completeness == 1.0
    assert diagnostic.probable_root_cause
    assert {
        "account-disabled",
        "no-license-details",
        "conditional-access-sign-in-failure",
        "risky-user",
        "device-noncompliant",
        "device-unencrypted",
        "microsoft-service-issue",
    }.issubset(codes)
    assert {finding.action_id for finding in diagnostic.findings if finding.action_id} == {
        "m365-license-change",
        "m365-session-revocation",
        "m365-managed-device-sync",
    }
    assert diagnostic.to_dict()["user_identity"] == "adele@example.test"


def test_access_diagnostic_handles_no_direct_cause_user_not_found_and_missing_ca() -> None:
    ready_user = FakeM365Core(
        users=M365GraphReadResponse(ConnectorReadResult("ready", "ready", 1), [_user()]),
        licenses=M365GraphLicenseDetailReadResponse(
            ConnectorReadResult("ready", "ready", 1),
            [_license()],
        ),
        devices=M365GraphManagedDeviceReadResponse(
            ConnectorReadResult("ready", "ready", 1),
            [_device()],
        ),
    )
    normal = diagnose_access(
        FakeMicrosoftAdminProvider(
            {"conditional_access": _response([{"id": "ca-1", "state": "enabled"}])}
        ),
        cast(M365GraphClient, ready_user),
        user_identity="adele@example.test",
    )
    assert [finding.code for finding in normal.findings] == ["no-direct-cause-observed"]
    assert normal.probable_root_cause == ""

    missing_user = FakeM365Core(
        users=M365GraphReadResponse(ConnectorReadResult("ready", "ready", 0), []),
        licenses=M365GraphLicenseDetailReadResponse(
            ConnectorReadResult("failed", "permission denied", 0),
            [],
        ),
        devices=M365GraphManagedDeviceReadResponse(ConnectorReadResult("ready", "ready", 0), []),
    )
    missing = diagnose_access(
        FakeMicrosoftAdminProvider({"conditional_access": _response()}),
        cast(M365GraphClient, missing_user),
        user_identity="missing@example.test",
    )
    assert {finding.code for finding in missing.findings} == {
        "user-not-found",
        "no-conditional-access-policies",
    }
    assert missing.evidence_completeness < 1.0

    with pytest.raises(MicrosoftAdminError, match="identity"):
        diagnose_access(FakeMicrosoftAdminProvider({}), cast(M365GraphClient, ready_user), user_identity=" ")
    with pytest.raises(MicrosoftAdminError, match="Device name"):
        diagnose_access(
            FakeMicrosoftAdminProvider({}),
            cast(M365GraphClient, ready_user),
            user_identity="adele@example.test",
            device_name="d" * 257,
        )
