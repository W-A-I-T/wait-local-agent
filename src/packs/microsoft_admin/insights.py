"""Cross-surface Microsoft administration posture and access diagnostics."""

from __future__ import annotations

from datetime import UTC, datetime

from wait_local_agent.m365_graph import M365GraphClient

from .client import _bounded_identity
from .models import (
    _CLOSED_INCIDENT_STATUSES,
    _LOW_RISK_LEVELS,
    _OPERATIONAL_SERVICE_STATUSES,
    _STALE_DEVICE_DAYS,
    _SUCCESS_STATUSES,
    MicrosoftAdminDiagnostic,
    MicrosoftAdminError,
    MicrosoftAdminFinding,
    MicrosoftAdminProvider,
)
from .normalizers import (
    _aggregate_status,
    _dashboard_recommendations,
    _is_stale,
    _latest_secure_score,
    _lower,
    _severity_rank,
    _sign_in_failed,
)


def build_dashboard(
    provider: MicrosoftAdminProvider,
    core_client: M365GraphClient,
    *,
    now: datetime | None = None,
) -> dict[str, object]:
    generated_at = (now or datetime.now(UTC)).astimezone(UTC)
    service_health = provider.list_service_health(page_size=50)
    service_issues = provider.list_service_issues(page_size=50)
    secure_scores = provider.list_secure_scores(page_size=1)
    sign_ins = provider.list_sign_ins(page_size=50)
    conditional_access = provider.list_conditional_access_policies(page_size=100)
    risky_users = provider.list_risky_users(page_size=100)
    intune_apps = provider.list_intune_apps(page_size=100)
    compliance_policies = provider.list_compliance_policies(page_size=100)
    autopilot_devices = provider.list_autopilot_devices(page_size=100)
    incidents = provider.list_defender_incidents(page_size=100)
    alerts = provider.list_defender_alerts(page_size=100)
    managed_devices = core_client.list_managed_devices(page_size=100)

    surfaces = {
        "service_health": service_health,
        "service_issues": service_issues,
        "secure_scores": secure_scores,
        "sign_ins": sign_ins,
        "conditional_access": conditional_access,
        "risky_users": risky_users,
        "intune_apps": intune_apps,
        "compliance_policies": compliance_policies,
        "autopilot_devices": autopilot_devices,
        "defender_incidents": incidents,
        "defender_alerts": alerts,
    }
    source_statuses = {name: response.result.status for name, response in surfaces.items()}
    source_statuses["managed_devices"] = managed_devices.result.status

    non_operational_services = sum(
        1
        for item in service_health.items
        if _lower(item.get("status")) not in _OPERATIONAL_SERVICE_STATUSES
    )
    open_service_issues = sum(
        1
        for item in service_issues.items
        if _lower(item.get("status")) not in {"servicerestored", "postincidentreviewpublished"}
    )
    failed_sign_ins = sum(1 for item in sign_ins.items if _sign_in_failed(item))
    risky_sign_ins = sum(
        1
        for item in sign_ins.items
        if _lower(item.get("risk_level")) not in _LOW_RISK_LEVELS
    )
    conditional_access_disabled = sum(
        1 for item in conditional_access.items if _lower(item.get("state")) == "disabled"
    )
    conditional_access_report_only = sum(
        1 for item in conditional_access.items if _lower(item.get("state")) == "enabledforreportingbutnotenforced"
    )
    active_incidents = sum(
        1 for item in incidents.items if _lower(item.get("status")) not in _CLOSED_INCIDENT_STATUSES
    )
    high_severity_incidents = sum(
        1
        for item in incidents.items
        if _lower(item.get("status")) not in _CLOSED_INCIDENT_STATUSES
        and _lower(item.get("severity")) == "high"
    )
    active_alerts = sum(
        1 for item in alerts.items if _lower(item.get("status")) not in {"resolved", "dismissed"}
    )
    noncompliant_devices = sum(
        1 for item in managed_devices.items if item.compliance_state.casefold() not in {"compliant", "unknown"}
    )
    unencrypted_devices = sum(1 for item in managed_devices.items if item.is_encrypted is False)
    stale_devices = sum(
        1
        for item in managed_devices.items
        if _is_stale(item.last_sync_date_time, generated_at, days=_STALE_DEVICE_DAYS)
    )
    score = _latest_secure_score(secure_scores.items)

    summary: dict[str, object] = {
        "non_operational_services": non_operational_services,
        "open_service_issues": open_service_issues,
        "secure_score_percent": score,
        "failed_sign_ins": failed_sign_ins,
        "risky_sign_ins": risky_sign_ins,
        "risky_users": len(risky_users.items),
        "conditional_access_policies": len(conditional_access.items),
        "conditional_access_disabled": conditional_access_disabled,
        "conditional_access_report_only": conditional_access_report_only,
        "managed_devices": len(managed_devices.items),
        "noncompliant_devices": noncompliant_devices,
        "unencrypted_devices": unencrypted_devices,
        "stale_devices": stale_devices,
        "intune_apps": len(intune_apps.items),
        "compliance_policies": len(compliance_policies.items),
        "autopilot_devices": len(autopilot_devices.items),
        "active_defender_incidents": active_incidents,
        "high_severity_incidents": high_severity_incidents,
        "active_defender_alerts": active_alerts,
    }
    recommendations = _dashboard_recommendations(summary)
    return {
        "generated_at": generated_at.isoformat(),
        "status": _aggregate_status(source_statuses.values()),
        "summary": summary,
        "recommendations": recommendations,
        "source_statuses": source_statuses,
        "evidence": {
            "service_health": service_health.items,
            "service_issues": service_issues.items,
            "secure_scores": secure_scores.items,
            "recent_sign_ins": sign_ins.items,
            "conditional_access": conditional_access.items,
            "risky_users": risky_users.items,
            "defender_incidents": incidents.items,
            "defender_alerts": alerts.items,
        },
    }


def diagnose_access(
    provider: MicrosoftAdminProvider,
    core_client: M365GraphClient,
    *,
    user_identity: str,
    device_name: str | None = None,
    now: datetime | None = None,
) -> MicrosoftAdminDiagnostic:
    identity = _bounded_identity(user_identity)
    requested_device = (device_name or "").strip()
    if len(requested_device) > 256:
        raise MicrosoftAdminError("Device name is too long.")

    user_response = core_client.list_users(identity=identity, page_size=5)
    license_response = core_client.list_license_details(identity=identity, page_size=50)
    sign_ins = provider.list_sign_ins(identity=identity, page_size=25)
    service_issues = provider.list_service_issues(page_size=50)
    risky_users = provider.list_risky_users(page_size=100)
    conditional_access = provider.list_conditional_access_policies(page_size=100)
    devices_response = core_client.list_managed_devices(page_size=100)

    statuses = {
        "user": user_response.result.status,
        "licenses": license_response.result.status,
        "sign_ins": sign_ins.result.status,
        "service_issues": service_issues.result.status,
        "risky_users": risky_users.result.status,
        "conditional_access": conditional_access.result.status,
        "managed_devices": devices_response.result.status,
    }
    ready_sources = sum(1 for status in statuses.values() if status in _SUCCESS_STATUSES)
    completeness = round(ready_sources / len(statuses), 2)
    findings: list[MicrosoftAdminFinding] = []

    user = user_response.items[0] if user_response.items else None
    if user_response.result.status == "ready" and user is None:
        findings.append(
            MicrosoftAdminFinding(
                "user-not-found",
                "high",
                "The requested Microsoft Entra user was not returned by the authorized Graph lookup.",
                {"user_identity": identity},
                "Verify the user principal name and tenant mapping.",
            )
        )
    elif user is not None and user.account_enabled is False:
        findings.append(
            MicrosoftAdminFinding(
                "account-disabled",
                "high",
                "The Microsoft Entra account is disabled.",
                {"user_id": user.id, "user_principal_name": user.user_principal_name},
                "Review the offboarding or account-disable evidence before enabling the account manually.",
                approval_required=True,
            )
        )

    if license_response.result.status == "ready" and not license_response.items:
        findings.append(
            MicrosoftAdminFinding(
                "no-license-details",
                "medium",
                "No assigned Microsoft 365 license details were returned for the user.",
                {"user_identity": identity},
                "Review tenant subscriptions and assign an approved SKU when appropriate.",
                action_id="m365-license-change",
                approval_required=True,
            )
        )

    failed_sign_ins = [item for item in sign_ins.items if _sign_in_failed(item)]
    ca_failures = [
        item
        for item in failed_sign_ins
        if _lower(item.get("conditional_access_status")) == "failure"
    ]
    if ca_failures:
        latest = ca_failures[0]
        findings.append(
            MicrosoftAdminFinding(
                "conditional-access-sign-in-failure",
                "high",
                "Recent sign-in evidence shows a failure associated with Conditional Access evaluation.",
                {
                    "created_date_time": latest.get("created_date_time", ""),
                    "application": latest.get("application", ""),
                    "failure_reason": latest.get("failure_reason", ""),
                    "conditional_access_status": latest.get("conditional_access_status", ""),
                },
                (
                    "Review the matching Conditional Access policy and device/user conditions; "
                    "do not bypass policy automatically."
                ),
            )
        )
    elif failed_sign_ins:
        latest = failed_sign_ins[0]
        findings.append(
            MicrosoftAdminFinding(
                "recent-sign-in-failure",
                "medium",
                "Recent Microsoft Entra sign-in evidence contains an authentication failure.",
                {
                    "created_date_time": latest.get("created_date_time", ""),
                    "application": latest.get("application", ""),
                    "failure_reason": latest.get("failure_reason", ""),
                    "error_code": latest.get("error_code", 0),
                },
                "Correlate the error code with MFA, credentials, service health, and device state.",
            )
        )

    risky_user = next(
        (
            item
            for item in risky_users.items
            if _lower(item.get("user_principal_name")) == identity.casefold()
            and _lower(item.get("risk_level")) not in _LOW_RISK_LEVELS
        ),
        None,
    )
    if risky_user is not None:
        findings.append(
            MicrosoftAdminFinding(
                "risky-user",
                "high",
                "Microsoft Entra Identity Protection reports elevated user risk.",
                {
                    "risk_level": risky_user.get("risk_level", ""),
                    "risk_state": risky_user.get("risk_state", ""),
                    "risk_last_updated_date_time": risky_user.get("risk_last_updated_date_time", ""),
                },
                (
                    "Investigate the identity and use the existing approval-gated session revocation "
                    "or authentication remediation flow."
                ),
                action_id="m365-session-revoke",
                approval_required=True,
            )
        )

    matching_devices = [
        device
        for device in devices_response.items
        if (
            requested_device
            and device.device_name.casefold() == requested_device.casefold()
        )
        or (
            not requested_device
            and device.user_principal_name.casefold() == identity.casefold()
        )
    ]
    for device in matching_devices[:5]:
        if device.compliance_state.casefold() not in {"compliant", "unknown"}:
            findings.append(
                MicrosoftAdminFinding(
                    "device-noncompliant",
                    "high",
                    f"Managed device {device.device_name or device.id} is not compliant.",
                    {
                        "device_id": device.id,
                        "device_name": device.device_name,
                        "compliance_state": device.compliance_state,
                        "last_sync_date_time": device.last_sync_date_time,
                    },
                    "Use the existing approval-gated Intune sync action, then re-evaluate compliance.",
                    action_id="m365-managed-device-sync",
                    approval_required=True,
                )
            )
        if device.is_encrypted is False:
            findings.append(
                MicrosoftAdminFinding(
                    "device-unencrypted",
                    "medium",
                    f"Managed device {device.device_name or device.id} is reported as unencrypted.",
                    {"device_id": device.id, "device_name": device.device_name},
                    "Verify BitLocker policy, key escrow, and endpoint health before changing access policy.",
                )
            )

    relevant_services = {
        "exchange online",
        "identity service",
        "microsoft intune",
        "sharepoint online",
        "microsoft teams",
    }
    open_issues = [
        item
        for item in service_issues.items
        if _lower(item.get("service")) in relevant_services
        and _lower(item.get("status")) not in {"servicerestored", "postincidentreviewpublished"}
    ]
    if open_issues:
        findings.append(
            MicrosoftAdminFinding(
                "microsoft-service-issue",
                "medium",
                "Microsoft reports an active service issue that may affect authentication or collaboration access.",
                {
                    "issues": [
                        {
                            "id": item.get("id", ""),
                            "service": item.get("service", ""),
                            "title": item.get("title", ""),
                            "status": item.get("status", ""),
                        }
                        for item in open_issues[:5]
                    ]
                },
                "Correlate the incident scope before applying tenant or endpoint changes.",
            )
        )

    if conditional_access.result.status == "ready" and not conditional_access.items:
        findings.append(
            MicrosoftAdminFinding(
                "no-conditional-access-policies",
                "low",
                "No Conditional Access policies were returned by the authorized lookup.",
                {},
                "Verify licensing and Graph permissions before concluding that the tenant has no policies.",
            )
        )

    if not findings:
        findings.append(
            MicrosoftAdminFinding(
                "no-direct-cause-observed",
                "info",
                "The bounded evidence gathered by this diagnostic did not identify a direct cause.",
                {"ready_sources": ready_sources, "total_sources": len(statuses)},
                "Continue with mailbox, application-specific, network, and endpoint log review.",
            )
        )

    ranked = sorted(findings, key=lambda item: _severity_rank(item.severity), reverse=True)
    probable_root_cause = ranked[0].summary if ranked and ranked[0].severity in {"high", "critical"} else ""
    generated_at = (now or datetime.now(UTC)).astimezone(UTC).isoformat()
    return MicrosoftAdminDiagnostic(
        user_identity=identity,
        device_name=requested_device,
        generated_at=generated_at,
        evidence_completeness=completeness,
        probable_root_cause=probable_root_cause,
        findings=tuple(ranked),
        source_statuses=statuses,
    )


def remediation_catalog() -> list[dict[str, object]]:
    """Describe existing core actions that the pack may recommend, not execute directly."""

    return [
        {
            "action_id": "m365-managed-device-sync",
            "risk_level": 2,
            "approval_required": True,
            "description": "Trigger an Intune managed-device synchronization through the core approval flow.",
        },
        {
            "action_id": "m365-session-revoke",
            "risk_level": 3,
            "approval_required": True,
            "description": "Revoke Microsoft Entra sign-in sessions through the core approval flow.",
        },
        {
            "action_id": "m365-license-change",
            "risk_level": 3,
            "approval_required": True,
            "description": "Add or remove explicit Microsoft 365 SKUs through the core approval flow.",
        },
        {
            "action_id": "m365-authentication-method-delete",
            "risk_level": 4,
            "approval_required": True,
            "description": "Remove one explicit MFA method through the core approval flow.",
        },
        {
            "action_id": "m365-user-disable",
            "risk_level": 4,
            "approval_required": True,
            "description": "Disable a Microsoft Entra account through the core approval flow.",
        },
        {
            "action_id": "m365-managed-device-retire",
            "risk_level": 4,
            "approval_required": True,
            "description": "Retire one Intune managed device through the core approval flow.",
        },
    ]
