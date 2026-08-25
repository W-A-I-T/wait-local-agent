from __future__ import annotations

from dataclasses import replace
from typing import Any, cast

import httpx
from microsoft_admin_support import _configured

from packs.microsoft_admin import PACK_MANIFEST
from packs.microsoft_admin.core import MicrosoftAdminGraphClient, remediation_catalog


def test_pack_manifest_and_remediation_catalog_are_runtime_capabilities() -> None:
    assert PACK_MANIFEST == {
        "name": "microsoft-admin",
        "version": "0.1.0",
        "requires_license": False,
        "api_router_factory": "packs.microsoft_admin.router.create_router",
        "cli_app": "packs.microsoft_admin.cli.app",
    }
    actions = remediation_catalog()
    assert {item["action_id"] for item in actions} == {
        "m365-managed-device-sync",
        "m365-session-revoke",
        "m365-license-change",
        "m365-authentication-method-delete",
        "m365-user-disable",
        "m365-managed-device-retire",
    }
    assert all(item["approval_required"] is True for item in actions)


def test_microsoft_admin_client_blocks_and_reports_missing_configuration(settings) -> None:
    blocked = MicrosoftAdminGraphClient(settings)
    assert blocked.health().status == "blocked"
    assert blocked.list_service_health().result.status == "blocked"

    missing = MicrosoftAdminGraphClient(replace(settings, allow_http_probing=True))
    assert missing.health().status == "not_configured"
    assert "WAIT_M365_ACCESS_TOKEN" in missing.list_service_issues().result.message


def test_microsoft_admin_graph_reads_normalize_all_supported_surfaces(settings) -> None:
    next_link = (
        "https://graph.microsoft.com/v1.0/example?%24top=25&%24select=id&"
        "%24skiptoken=abc%2B123"
    )
    payloads: dict[str, dict[str, object]] = {
        "/v1.0/admin/serviceAnnouncement/healthOverviews": {
            "value": [{"id": "Exchange", "service": "Exchange Online", "status": "serviceOperational"}, {}],
            "@odata.nextLink": next_link,
        },
        "/v1.0/admin/serviceAnnouncement/issues": {
            "value": [
                {
                    "id": "EX123",
                    "title": "Mail delay",
                    "service": "Exchange Online",
                    "status": "serviceDegradation",
                    "classification": "incident",
                    "origin": "microsoft",
                    "impactDescription": "Some users are affected.",
                    "startDateTime": "2026-08-24T00:00:00Z",
                    "endDateTime": "",
                    "lastModifiedDateTime": "2026-08-24T01:00:00Z",
                    "feature": "Mail flow",
                    "featureGroup": "Transport",
                },
                {},
            ],
            "@odata.nextLink": next_link,
        },
        "/v1.0/security/secureScores": {
            "value": [
                {
                    "id": "score-1",
                    "createdDateTime": "2026-08-24T00:00:00Z",
                    "currentScore": 42,
                    "maxScore": 100,
                    "enabledServices": ["Microsoft Defender", 7],
                    "licensedUserCount": 50,
                    "activeUserCount": 47,
                    "averageComparativeScores": [
                        {"basis": "AllTenants", "averageScore": 37.5},
                        "ignored",
                    ],
                },
                {},
            ],
            "@odata.nextLink": next_link,
        },
        "/v1.0/auditLogs/signIns": {
            "value": [
                {
                    "id": "signin-1",
                    "userDisplayName": "Adele Vance",
                    "userPrincipalName": "adele@example.test",
                    "createdDateTime": "2026-08-24T00:00:00Z",
                    "status": {
                        "errorCode": 53003,
                        "failureReason": "Blocked by Conditional Access",
                        "additionalDetails": "Policy evaluated",
                    },
                    "appDisplayName": "Office 365 Exchange Online",
                    "conditionalAccessStatus": "failure",
                    "riskLevelAggregated": "medium",
                    "riskState": "atRisk",
                    "deviceDetail": {
                        "displayName": "LAPTOP-001",
                        "operatingSystem": "Windows",
                        "browser": "Edge",
                        "isCompliant": False,
                        "isManaged": True,
                        "trustType": "Azure AD joined",
                    },
                    "location": {"city": "Vancouver", "state": "BC", "countryOrRegion": "CA"},
                },
                {},
            ],
            "@odata.nextLink": next_link,
        },
        "/v1.0/identity/conditionalAccess/policies": {
            "value": [
                {
                    "id": "ca-1",
                    "displayName": "Require compliant device",
                    "state": "enabled",
                    "createdDateTime": "2026-01-01T00:00:00Z",
                    "modifiedDateTime": "2026-08-01T00:00:00Z",
                    "conditions": {
                        "users": {"includeUsers": ["All"], "includeGroups": ["group-1"]},
                        "applications": {"includeApplications": ["Office365"]},
                        "platforms": {"includePlatforms": ["windows"]},
                        "clientAppTypes": ["browser"],
                    },
                    "grantControls": {"operator": "AND", "builtInControls": ["compliantDevice"]},
                    "sessionControls": {"signInFrequency": {"value": 8}, "persistentBrowser": None},
                },
                {},
            ],
            "@odata.nextLink": next_link,
        },
        "/v1.0/identityProtection/riskyUsers": {
            "value": [
                {
                    "id": "user-1",
                    "userDisplayName": "Adele Vance",
                    "userPrincipalName": "adele@example.test",
                    "riskDetail": "none",
                    "riskLevel": "high",
                    "riskState": "atRisk",
                    "riskLastUpdatedDateTime": "2026-08-24T00:00:00Z",
                    "isDeleted": False,
                    "isProcessing": False,
                },
                {},
            ],
            "@odata.nextLink": next_link,
        },
        "/v1.0/deviceAppManagement/mobileApps": {
            "value": [
                {
                    "id": "app-1",
                    "displayName": "Microsoft 365 Apps",
                    "publisher": "Microsoft",
                    "createdDateTime": "2026-01-01T00:00:00Z",
                    "lastModifiedDateTime": "2026-08-01T00:00:00Z",
                    "isFeatured": True,
                    "owner": "IT",
                    "developer": "Microsoft",
                },
                {},
            ],
            "@odata.nextLink": next_link,
        },
        "/v1.0/deviceManagement/deviceCompliancePolicies": {
            "value": [
                {
                    "id": "policy-1",
                    "displayName": "Windows baseline",
                    "description": "Require encryption",
                    "createdDateTime": "2026-01-01T00:00:00Z",
                    "lastModifiedDateTime": "2026-08-01T00:00:00Z",
                    "version": 3,
                },
                {},
            ],
            "@odata.nextLink": next_link,
        },
        "/v1.0/deviceManagement/windowsAutopilotDeviceIdentities": {
            "value": [
                {
                    "id": "auto-1",
                    "displayName": "LAPTOP-001",
                    "groupTag": "Corporate",
                    "manufacturer": "Dell",
                    "model": "Latitude",
                    "enrollmentState": "enrolled",
                    "lastContactedDateTime": "2026-08-24T00:00:00Z",
                    "azureActiveDirectoryDeviceId": "aad-device-1",
                    "managedDeviceId": "device-1",
                },
                {},
            ],
            "@odata.nextLink": next_link,
        },
        "/v1.0/security/incidents": {
            "value": [
                {
                    "id": "incident-1",
                    "displayName": "Suspicious sign-in",
                    "status": "active",
                    "severity": "high",
                    "classification": "unknown",
                    "determination": "unknown",
                    "assignedTo": "soc@example.test",
                    "createdDateTime": "2026-08-24T00:00:00Z",
                    "lastUpdateDateTime": "2026-08-24T01:00:00Z",
                    "redirectIncidentId": "",
                    "customTags": ["identity", 9],
                },
                {},
            ],
            "@odata.nextLink": next_link,
        },
        "/v1.0/security/alerts_v2": {
            "value": [
                {
                    "id": "alert-1",
                    "title": "Impossible travel",
                    "status": "new",
                    "severity": "high",
                    "category": "InitialAccess",
                    "serviceSource": "microsoftDefenderForIdentity",
                    "detectionSource": "microsoftDefenderForIdentity",
                    "createdDateTime": "2026-08-24T00:00:00Z",
                    "lastUpdateDateTime": "2026-08-24T01:00:00Z",
                    "incidentId": "incident-1",
                },
                {},
            ],
            "@odata.nextLink": next_link,
        },
    }
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.headers["Authorization"] == "Bearer access-token"
        return httpx.Response(200, json=payloads[request.url.path])

    client = MicrosoftAdminGraphClient(
        _configured(settings),
        transport=httpx.MockTransport(handler),
    )
    responses = [
        client.list_service_health(),
        client.list_service_issues(),
        client.list_secure_scores(),
        client.list_sign_ins(identity="adele@example.test"),
        client.list_conditional_access_policies(),
        client.list_risky_users(),
        client.list_intune_apps(),
        client.list_compliance_policies(),
        client.list_autopilot_devices(),
        client.list_defender_incidents(),
        client.list_defender_alerts(),
    ]

    assert all(response.result.status == "ready" for response in responses)
    assert all(len(response.items) == 1 for response in responses)
    assert all(response.next_cursor == "$skiptoken=abc%2B123" for response in responses)
    assert responses[2].items[0]["average_comparative_scores"] == [
        {"basis": "AllTenants", "average_score": 37.5}
    ]
    assert responses[3].items[0]["device"] == {
        "display_name": "LAPTOP-001",
        "operating_system": "Windows",
        "browser": "Edge",
        "is_compliant": False,
        "is_managed": True,
        "trust_type": "Azure AD joined",
    }
    sign_in_request = next(request for request in requests if request.url.path.endswith("/auditLogs/signIns"))
    assert sign_in_request.url.params["$filter"] == "userPrincipalName eq 'adele@example.test'"

    client.list_service_health(cursor=responses[0].next_cursor)
    last_request = requests[-1]
    assert last_request.url.params["$skiptoken"] == "abc+123"
    assert last_request.url.params["$select"] == "id,service,status"


def test_client_health_and_error_paths_are_sanitized(settings) -> None:
    healthy = MicrosoftAdminGraphClient(
        _configured(settings),
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={"value": [{"id": "Exchange", "service": "Exchange Online", "status": "ok"}]},
            )
        ),
    )
    assert healthy.health().status == "ready"

    failures = [
        httpx.MockTransport(lambda request: httpx.Response(500, json={"error": "secret"})),
        httpx.MockTransport(lambda request: httpx.Response(200, content=b"{")),
        httpx.MockTransport(lambda request: httpx.Response(200, json=[])),
        httpx.MockTransport(lambda request: httpx.Response(200, json={})),
    ]
    for transport in failures:
        response = MicrosoftAdminGraphClient(_configured(settings), transport=transport).list_service_health()
        assert response.result.status == "failed"
        assert "access-token" not in response.result.message
        assert "secret" not in response.result.message

    def timeout_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timeout", request=request)

    timeout = MicrosoftAdminGraphClient(
        _configured(settings),
        transport=httpx.MockTransport(timeout_handler),
    ).list_service_health()
    assert timeout.result.status == "failed"
    assert "before receiving a response" in timeout.result.message


def test_client_validation_fails_closed_without_broadening_graph_queries(settings) -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"value": []}))
    client = MicrosoftAdminGraphClient(_configured(settings), transport=transport)

    assert client.list_service_health(page_size=0).result.status == "failed"
    assert client.list_service_health(page_size=cast(Any, True)).result.status == "failed"
    assert client.list_sign_ins(identity="\n").result.status == "failed"
    assert client.list_sign_ins(identity="a" * 321).result.status == "failed"
    assert client.list_service_health(cursor="https://evil.example/?$skiptoken=x").result.status == "failed"
    assert client.list_service_health(cursor="$select=mail,password").result.status == "failed"
    assert client.list_service_health(cursor="\x01$skiptoken=x").result.status == "failed"
    assert client.list_service_health(cursor=" ").result.status == "failed"

    invalid_base = MicrosoftAdminGraphClient(
        replace(_configured(settings), m365_graph_base_url="https://graph.microsoft.com/beta"),
        transport=transport,
    ).list_service_health()
    assert invalid_base.result.status == "failed"
    assert "v1.0" in invalid_base.result.message
