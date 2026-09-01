"""Bounded normalization and deterministic insight helpers."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from typing import cast


def _string(value: object) -> str:
    return value if isinstance(value, str) else ""


def _integer(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _number(value: object) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _boolean(value: object) -> bool | None:
    return value if isinstance(value, bool) else None


def _string_list(value: object, *, limit: int = 20) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)][:limit]


def _mapping(value: object) -> Mapping[str, object]:
    return cast(Mapping[str, object], value) if isinstance(value, Mapping) else {}


def _normalize_service_health(row: Mapping[str, object]) -> dict[str, object] | None:
    record_id = _string(row.get("id"))
    service = _string(row.get("service"))
    if not record_id and not service:
        return None
    return {"id": record_id, "service": service, "status": _string(row.get("status"))}


def _normalize_service_issue(row: Mapping[str, object]) -> dict[str, object] | None:
    record_id = _string(row.get("id"))
    title = _string(row.get("title"))
    if not record_id and not title:
        return None
    return {
        "id": record_id,
        "title": title,
        "service": _string(row.get("service")),
        "status": _string(row.get("status")),
        "classification": _string(row.get("classification")),
        "origin": _string(row.get("origin")),
        "impact_description": _string(row.get("impactDescription")),
        "start_date_time": _string(row.get("startDateTime")),
        "end_date_time": _string(row.get("endDateTime")),
        "last_modified_date_time": _string(row.get("lastModifiedDateTime")),
        "feature": _string(row.get("feature")),
        "feature_group": _string(row.get("featureGroup")),
    }


def _normalize_secure_score(row: Mapping[str, object]) -> dict[str, object] | None:
    record_id = _string(row.get("id"))
    created = _string(row.get("createdDateTime"))
    if not record_id and not created:
        return None
    comparative_scores: list[dict[str, object]] = []
    raw_comparative = row.get("averageComparativeScores")
    if isinstance(raw_comparative, list):
        for item in raw_comparative[:20]:
            if not isinstance(item, Mapping):
                continue
            comparative_scores.append(
                {
                    "basis": _string(item.get("basis")),
                    "average_score": _number(item.get("averageScore")),
                }
            )
    return {
        "id": record_id,
        "created_date_time": created,
        "current_score": _number(row.get("currentScore")),
        "max_score": _number(row.get("maxScore")),
        "enabled_services": _string_list(row.get("enabledServices")),
        "licensed_user_count": _integer(row.get("licensedUserCount")),
        "active_user_count": _integer(row.get("activeUserCount")),
        "average_comparative_scores": comparative_scores,
    }


def _normalize_sign_in(row: Mapping[str, object]) -> dict[str, object] | None:
    record_id = _string(row.get("id"))
    created = _string(row.get("createdDateTime"))
    if not record_id and not created:
        return None
    status = _mapping(row.get("status"))
    device = _mapping(row.get("deviceDetail"))
    location = _mapping(row.get("location"))
    return {
        "id": record_id,
        "user_display_name": _string(row.get("userDisplayName")),
        "user_principal_name": _string(row.get("userPrincipalName")),
        "created_date_time": created,
        "application": _string(row.get("appDisplayName")),
        "conditional_access_status": _string(row.get("conditionalAccessStatus")),
        "risk_level": _string(row.get("riskLevelAggregated")),
        "risk_state": _string(row.get("riskState")),
        "error_code": _integer(status.get("errorCode")) or 0,
        "failure_reason": _string(status.get("failureReason")),
        "additional_details": _string(status.get("additionalDetails")),
        "device": {
            "display_name": _string(device.get("displayName")),
            "operating_system": _string(device.get("operatingSystem")),
            "browser": _string(device.get("browser")),
            "is_compliant": _boolean(device.get("isCompliant")),
            "is_managed": _boolean(device.get("isManaged")),
            "trust_type": _string(device.get("trustType")),
        },
        "location": {
            "city": _string(location.get("city")),
            "state": _string(location.get("state")),
            "country_or_region": _string(location.get("countryOrRegion")),
        },
    }


def _normalize_conditional_access_policy(row: Mapping[str, object]) -> dict[str, object] | None:
    record_id = _string(row.get("id"))
    display_name = _string(row.get("displayName"))
    if not record_id and not display_name:
        return None
    conditions = _mapping(row.get("conditions"))
    users = _mapping(conditions.get("users"))
    applications = _mapping(conditions.get("applications"))
    platforms = _mapping(conditions.get("platforms"))
    grant_controls = _mapping(row.get("grantControls"))
    session_controls = _mapping(row.get("sessionControls"))
    return {
        "id": record_id,
        "display_name": display_name,
        "state": _string(row.get("state")),
        "created_date_time": _string(row.get("createdDateTime")),
        "modified_date_time": _string(row.get("modifiedDateTime")),
        "conditions": {
            "included_users": len(_string_list(users.get("includeUsers"), limit=500)),
            "included_groups": len(_string_list(users.get("includeGroups"), limit=500)),
            "included_applications": len(_string_list(applications.get("includeApplications"), limit=500)),
            "included_platforms": _string_list(platforms.get("includePlatforms")),
            "client_app_types": _string_list(conditions.get("clientAppTypes")),
        },
        "grant_controls": {
            "operator": _string(grant_controls.get("operator")),
            "built_in_controls": _string_list(grant_controls.get("builtInControls")),
        },
        "session_control_names": sorted(
            key for key, value in session_controls.items() if value is not None
        )[:20],
    }


def _normalize_risky_user(row: Mapping[str, object]) -> dict[str, object] | None:
    record_id = _string(row.get("id"))
    upn = _string(row.get("userPrincipalName"))
    if not record_id and not upn:
        return None
    return {
        "id": record_id,
        "user_display_name": _string(row.get("userDisplayName")),
        "user_principal_name": upn,
        "risk_detail": _string(row.get("riskDetail")),
        "risk_level": _string(row.get("riskLevel")),
        "risk_state": _string(row.get("riskState")),
        "risk_last_updated_date_time": _string(row.get("riskLastUpdatedDateTime")),
        "is_deleted": _boolean(row.get("isDeleted")),
        "is_processing": _boolean(row.get("isProcessing")),
    }


def _normalize_intune_app(row: Mapping[str, object]) -> dict[str, object] | None:
    record_id = _string(row.get("id"))
    display_name = _string(row.get("displayName"))
    if not record_id and not display_name:
        return None
    return {
        "id": record_id,
        "display_name": display_name,
        "publisher": _string(row.get("publisher")),
        "created_date_time": _string(row.get("createdDateTime")),
        "last_modified_date_time": _string(row.get("lastModifiedDateTime")),
        "is_featured": _boolean(row.get("isFeatured")),
        "owner": _string(row.get("owner")),
        "developer": _string(row.get("developer")),
    }


def _normalize_compliance_policy(row: Mapping[str, object]) -> dict[str, object] | None:
    record_id = _string(row.get("id"))
    display_name = _string(row.get("displayName"))
    if not record_id and not display_name:
        return None
    return {
        "id": record_id,
        "display_name": display_name,
        "description": _string(row.get("description")),
        "created_date_time": _string(row.get("createdDateTime")),
        "last_modified_date_time": _string(row.get("lastModifiedDateTime")),
        "version": _integer(row.get("version")),
    }


def _normalize_autopilot_device(row: Mapping[str, object]) -> dict[str, object] | None:
    record_id = _string(row.get("id"))
    display_name = _string(row.get("displayName"))
    if not record_id and not display_name:
        return None
    return {
        "id": record_id,
        "display_name": display_name,
        "group_tag": _string(row.get("groupTag")),
        "manufacturer": _string(row.get("manufacturer")),
        "model": _string(row.get("model")),
        "enrollment_state": _string(row.get("enrollmentState")),
        "last_contacted_date_time": _string(row.get("lastContactedDateTime")),
        "azure_ad_device_id": _string(row.get("azureActiveDirectoryDeviceId")),
        "managed_device_id": _string(row.get("managedDeviceId")),
    }


def _normalize_security_incident(row: Mapping[str, object]) -> dict[str, object] | None:
    record_id = _string(row.get("id"))
    display_name = _string(row.get("displayName"))
    if not record_id and not display_name:
        return None
    return {
        "id": record_id,
        "display_name": display_name,
        "status": _string(row.get("status")),
        "severity": _string(row.get("severity")),
        "classification": _string(row.get("classification")),
        "determination": _string(row.get("determination")),
        "assigned_to": _string(row.get("assignedTo")),
        "created_date_time": _string(row.get("createdDateTime")),
        "last_update_date_time": _string(row.get("lastUpdateDateTime")),
        "redirect_incident_id": _string(row.get("redirectIncidentId")),
        "custom_tags": _string_list(row.get("customTags")),
    }


def _normalize_security_alert(row: Mapping[str, object]) -> dict[str, object] | None:
    record_id = _string(row.get("id"))
    title = _string(row.get("title"))
    if not record_id and not title:
        return None
    return {
        "id": record_id,
        "title": title,
        "status": _string(row.get("status")),
        "severity": _string(row.get("severity")),
        "category": _string(row.get("category")),
        "service_source": _string(row.get("serviceSource")),
        "detection_source": _string(row.get("detectionSource")),
        "created_date_time": _string(row.get("createdDateTime")),
        "last_update_date_time": _string(row.get("lastUpdateDateTime")),
        "incident_id": _string(row.get("incidentId")),
    }


def _sign_in_failed(item: Mapping[str, object]) -> bool:
    error_code = item.get("error_code")
    return isinstance(error_code, int) and not isinstance(error_code, bool) and error_code != 0


def _latest_secure_score(items: list[dict[str, object]]) -> float | None:
    if not items:
        return None
    current = items[0].get("current_score")
    maximum = items[0].get("max_score")
    if not isinstance(current, (int, float)) or isinstance(current, bool):
        return None
    if not isinstance(maximum, (int, float)) or isinstance(maximum, bool) or maximum <= 0:
        return None
    return round(float(current) / float(maximum) * 100, 1)


def _is_stale(value: str, now: datetime, *, days: int) -> bool:
    if not value:
        return False
    candidate = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return False
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return (now - parsed.astimezone(UTC)).days >= days


def _dashboard_recommendations(summary: Mapping[str, object]) -> list[dict[str, object]]:
    recommendations: list[dict[str, object]] = []
    if _positive_int(summary.get("high_severity_incidents")):
        recommendations.append(
            {
                "priority": "critical",
                "code": "defender-high-severity-incidents",
                "summary": "Review high-severity active Microsoft Defender incidents.",
                "automatic_execution": False,
            }
        )
    if _positive_int(summary.get("noncompliant_devices")):
        recommendations.append(
            {
                "priority": "high",
                "code": "intune-noncompliant-devices",
                "summary": "Investigate noncompliant Intune devices before relaxing Conditional Access.",
                "automatic_execution": False,
            }
        )
    if _positive_int(summary.get("open_service_issues")):
        recommendations.append(
            {
                "priority": "medium",
                "code": "m365-service-health",
                "summary": "Correlate active Microsoft service issues before tenant-side remediation.",
                "automatic_execution": False,
            }
        )
    if _positive_int(summary.get("risky_users")) or _positive_int(summary.get("risky_sign_ins")):
        recommendations.append(
            {
                "priority": "high",
                "code": "entra-identity-risk",
                "summary": "Investigate elevated identity risk and use approval-gated containment where warranted.",
                "automatic_execution": False,
            }
        )
    score = summary.get("secure_score_percent")
    if isinstance(score, (int, float)) and not isinstance(score, bool) and score < 60:
        recommendations.append(
            {
                "priority": "medium",
                "code": "secure-score-review",
                "summary": "Review Secure Score controls; the pack does not treat score alone as compliance evidence.",
                "automatic_execution": False,
            }
        )
    return recommendations


def _aggregate_status(statuses: Iterable[str]) -> str:
    values = list(statuses)
    if values and all(status == "ready" for status in values):
        return "ready"
    if any(status == "ready" for status in values):
        return "partial"
    if any(status == "failed" for status in values):
        return "failed"
    if any(status == "blocked" for status in values):
        return "blocked"
    return "not_configured"


def _severity_rank(value: str) -> int:
    return {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}.get(value.casefold(), 0)


def _lower(value: object) -> str:
    return value.casefold() if isinstance(value, str) else ""


def _positive_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0
