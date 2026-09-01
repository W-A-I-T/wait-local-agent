"""Persistent client baselines and normalized posture drift comparison."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Literal, cast

from packs.microsoft_admin.insights import build_dashboard_summary
from packs.microsoft_admin.models import MicrosoftAdminProvider
from wait_local_agent.m365_graph import M365GraphClient
from wait_local_agent.models import ApprovalRequest, ClientBaseline, ConnectorInstance, SyncCursor
from wait_local_agent.store import Store

CoverageStatus = Literal["ready", "partial", "blocked", "not_configured", "failed"]

_COVERAGE_STATUSES = {"ready", "partial", "blocked", "not_configured", "failed"}
_POSTURE_POLARITY: dict[str, Literal["bad_up", "good_up"]] = {
    "non_operational_services": "bad_up",
    "open_service_issues": "bad_up",
    "failed_sign_ins": "bad_up",
    "risky_sign_ins": "bad_up",
    "risky_users": "bad_up",
    "conditional_access_disabled": "bad_up",
    "conditional_access_report_only": "bad_up",
    "noncompliant_devices": "bad_up",
    "unencrypted_devices": "bad_up",
    "stale_devices": "bad_up",
    "active_defender_incidents": "bad_up",
    "high_severity_incidents": "bad_up",
    "active_defender_alerts": "bad_up",
    "secure_score_percent": "good_up",
}
_POSTURE_COUNTER_SOURCES = {
    "non_operational_services": "service_health",
    "open_service_issues": "service_issues",
    "secure_score_percent": "secure_scores",
    "failed_sign_ins": "sign_ins",
    "risky_sign_ins": "sign_ins",
    "risky_users": "risky_users",
    "conditional_access_policies": "conditional_access",
    "conditional_access_disabled": "conditional_access",
    "conditional_access_report_only": "conditional_access",
    "managed_devices": "managed_devices",
    "noncompliant_devices": "managed_devices",
    "unencrypted_devices": "managed_devices",
    "stale_devices": "managed_devices",
    "intune_apps": "intune_apps",
    "compliance_policies": "compliance_policies",
    "autopilot_devices": "autopilot_devices",
    "active_defender_incidents": "defender_incidents",
    "high_severity_incidents": "defender_incidents",
    "active_defender_alerts": "defender_alerts",
}
_SECTION_COVERAGE_PREFIXES = {
    "microsoft_posture": ("microsoft:", "microsoft_posture"),
    "environment_graph": ("environment_graph",),
    "canonical_assets": ("canonical_assets",),
    "connector_readiness": ("connector:", "connector_readiness"),
}


def _json_sort_key(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _canonicalize(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _canonicalize(value[key]) for key in sorted(value, key=str)}
    if isinstance(value, (list, tuple)):
        return sorted((_canonicalize(item) for item in value), key=_json_sort_key)
    return value


def normalized_hash(sections: Mapping[str, object]) -> str:
    """Hash canonical sections so ordering-only changes are not drift."""

    canonical = _canonicalize(sections)
    return hashlib.sha256(_json_sort_key(canonical).encode("utf-8")).hexdigest()


def _coverage_status(value: object) -> CoverageStatus:
    status = str(value).strip().lower()
    if status in _COVERAGE_STATUSES:
        return status  # type: ignore[return-value]
    if status in {"configured", "syncing", "degraded"}:
        return "partial"
    if status in {"inactive", "disabled", "missing", "not_run"}:
        return "not_configured"
    return "failed"


def _safe_json_object(value: str) -> dict[str, object]:
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _group_counts(values: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))


def _instance_status(instance: ConnectorInstance, cursors: list[SyncCursor]) -> CoverageStatus:
    instance_status = _coverage_status(instance.status)
    if instance_status != "ready":
        return instance_status
    cursor_statuses = [_coverage_status(cursor.status) for cursor in cursors]
    if any(status == "failed" for status in cursor_statuses):
        return "failed"
    if any(status != "ready" for status in cursor_statuses):
        return "partial"
    return "ready"


class BaselineService:
    """Build and compare client observations using injected provider factories."""

    def __init__(
        self,
        store: Store,
        *,
        microsoft_provider_factory: Callable[[str], MicrosoftAdminProvider] | None = None,
        core_client_factory: Callable[[str], M365GraphClient] | None = None,
    ) -> None:
        self.store = store
        self.microsoft_provider_factory = microsoft_provider_factory
        self.core_client_factory = core_client_factory

    def compose_baseline(
        self, client_id: str, *, now: datetime | None = None
    ) -> dict[str, object]:
        normalized_client_id = client_id.strip()
        if not normalized_client_id:
            raise ValueError("client_id must be non-empty")
        generated_at = (now or datetime.now(UTC)).astimezone(UTC).isoformat()
        source_coverage: dict[str, CoverageStatus] = {}
        microsoft_summary: dict[str, object] = {}
        microsoft_factory = self.microsoft_provider_factory
        core_factory = self.core_client_factory
        if microsoft_factory is None or core_factory is None:
            source_coverage["microsoft_posture"] = "not_configured"
        else:
            try:
                posture = build_dashboard_summary(
                    microsoft_factory(normalized_client_id),
                    core_factory(normalized_client_id),
                    now=now,
                )
                raw_summary = posture.get("summary")
                microsoft_summary = (
                    {str(key): value for key, value in raw_summary.items()}
                    if isinstance(raw_summary, dict)
                    else {}
                )
                raw_statuses = posture.get("source_statuses", {})
                if isinstance(raw_statuses, dict):
                    for source, status in raw_statuses.items():
                        source_coverage[f"microsoft:{source}"] = _coverage_status(status)
                microsoft_summary = {
                    key: value
                    for key, value in microsoft_summary.items()
                    if source_coverage.get(f"microsoft:{_POSTURE_COUNTER_SOURCES.get(key, key)}") == "ready"
                }
                source_coverage["microsoft_posture"] = _aggregate_coverage(
                    [status for key, status in source_coverage.items() if key.startswith("microsoft:")]
                )
            except Exception:  # provider failures become coverage, never healthy zeroes
                source_coverage["microsoft_posture"] = "failed"

        refs = self.store.list_entity_refs(normalized_client_id)
        source_coverage["environment_graph"] = "ready"
        source_coverage["canonical_assets"] = "ready"
        assets = self.store.list_canonical_assets(client_id=normalized_client_id)
        instances = [
            instance
            for instance in self.store.list_connector_instances()
            if instance.client_id == normalized_client_id
        ]
        cursors = self.store.list_sync_cursors()
        cursors_by_instance: dict[str, list[SyncCursor]] = {}
        for cursor in cursors:
            cursors_by_instance.setdefault(cursor.connector_instance_id, []).append(cursor)
        connector_statuses: dict[str, str] = {}
        for instance in instances:
            status = _instance_status(instance, cursors_by_instance.get(instance.connector_instance_id, []))
            connector_statuses[instance.connector_instance_id] = status
            source_coverage[f"connector:{instance.connector_instance_id}"] = status
        source_coverage["connector_readiness"] = _aggregate_coverage(
            list(connector_statuses.values()) or ["not_configured"]
        )

        sections: dict[str, object] = {
            "microsoft_posture": {"summary": microsoft_summary},
            "environment_graph": {
                "entity_type_counts": _group_counts([ref.entity_type for ref in refs]),
                "source_counts": _group_counts([ref.source_system for ref in refs]),
            },
            "canonical_assets": {
                "asset_type_counts": _group_counts([asset.asset_type for asset in assets]),
                "assets": {
                    asset.canonical_id: {"asset_type": asset.asset_type}
                    for asset in assets
                    if asset.canonical_id
                },
            },
            "connector_readiness": {
                "instances": connector_statuses,
                "cursors": {
                    f"{cursor.connector_instance_id}:{cursor.cursor_type}": {
                        "status": cursor.status,
                        "last_synced_at": cursor.last_synced_at,
                    }
                    for cursor in cursors
                    if cursor.connector_instance_id in connector_statuses
                },
            },
        }
        return {
            "client_id": normalized_client_id,
            "generated_at": generated_at,
            "source_coverage": source_coverage,
            "summary": {
                "hash": normalized_hash(sections),
                "section_hashes": {
                    name: normalized_hash({name: section}) for name, section in sections.items()
                },
                "microsoft_summary": microsoft_summary,
            },
            "sections": sections,
        }

    def create_baseline(self, client_id: str, *, now: datetime | None = None) -> ClientBaseline:
        snapshot = self.compose_baseline(client_id, now=now)
        return self.store.create_client_baseline(
            client_id,
            generated_at=str(snapshot["generated_at"]),
            source_coverage=cast(dict[str, object], snapshot["source_coverage"]),
            summary=cast(dict[str, object], snapshot["summary"]),
            sections=cast(dict[str, object], snapshot["sections"]),
        )

    def diff_baseline(
        self,
        client_id: str,
        *,
        baseline_version: int | None = None,
        now: datetime | None = None,
    ) -> dict[str, object]:
        baseline = (
            self.store.get_client_baseline(client_id, baseline_version)
            if baseline_version is not None
            else self.store.get_accepted_client_baseline(client_id)
        )
        if baseline is None and baseline_version is None:
            versions = self.store.list_client_baselines(client_id)
            baseline = versions[0] if versions else None
        if baseline is None:
            raise LookupError("client baseline not found")
        fresh = self.compose_baseline(client_id, now=now)
        old_sections = _safe_json_object(baseline.sections_json)
        old_coverage = _safe_json_object(baseline.source_coverage_json)
        fresh_sections = cast(dict[str, object], fresh["sections"])
        fresh_coverage = cast(dict[str, object], fresh["source_coverage"])
        findings = compare_normalized_sections(old_sections, fresh_sections, old_coverage, fresh_coverage)
        self._correlate_findings(findings, baseline, client_id, now=now)
        return {
            "client_id": client_id,
            "baseline_version": baseline.version,
            "baseline_generated_at": baseline.generated_at,
            "generated_at": fresh["generated_at"],
            "unchanged": not findings,
            "findings": findings,
            "source_coverage": fresh["source_coverage"],
            "fresh_summary": fresh["summary"],
        }

    def _correlate_findings(
        self,
        findings: list[dict[str, object]],
        baseline: ClientBaseline,
        client_id: str,
        *,
        now: datetime | None,
    ) -> None:
        end = (now or datetime.now(UTC)).astimezone(UTC)
        try:
            start = datetime.fromisoformat(baseline.generated_at)
        except ValueError:
            start = end
        if start.tzinfo is None:
            start = start.replace(tzinfo=UTC)
        approvals = self.store.list_approval_requests(client_id)
        for finding in findings:
            approval = _matching_approval(approvals, str(finding["domain"]), start, end)
            if approval is None:
                finding["correlation"] = "no_matching_approved_change"
                finding["correlation_label"] = "no matching approved change found"
            else:
                finding["correlation"] = "expected_change"
                finding["approval_id"] = approval.id
                finding["correlation_label"] = f"expected change — approval #{approval.id}"


def compose_baseline(
    client_id: str,
    *,
    store: Store,
    microsoft_provider: MicrosoftAdminProvider | None = None,
    core_client: M365GraphClient | None = None,
    now: datetime | None = None,
) -> dict[str, object]:
    """Functional entry point for callers that already own provider clients."""

    return BaselineService(
        store,
        microsoft_provider_factory=(lambda _client_id: microsoft_provider) if microsoft_provider else None,
        core_client_factory=(lambda _client_id: core_client) if core_client else None,
    ).compose_baseline(client_id, now=now)


def diff_baseline(
    client_id: str,
    *,
    store: Store,
    microsoft_provider: MicrosoftAdminProvider | None = None,
    core_client: M365GraphClient | None = None,
    baseline_version: int | None = None,
    now: datetime | None = None,
) -> dict[str, object]:
    return BaselineService(
        store,
        microsoft_provider_factory=(lambda _client_id: microsoft_provider) if microsoft_provider else None,
        core_client_factory=(lambda _client_id: core_client) if core_client else None,
    ).diff_baseline(client_id, baseline_version=baseline_version, now=now)


def compare_normalized_sections(
    before: Mapping[str, object],
    after: Mapping[str, object],
    before_coverage: Mapping[str, object] | None = None,
    after_coverage: Mapping[str, object] | None = None,
) -> list[dict[str, object]]:
    """Compare normalized sections while honoring the unavailable-source gate."""

    old_coverage = before_coverage or {
        section: "ready" for section in _SECTION_COVERAGE_PREFIXES
    }
    new_coverage = after_coverage or old_coverage
    findings: list[dict[str, object]] = []
    sections_changed = normalized_hash(before) != normalized_hash(after)
    for section, prefixes in _SECTION_COVERAGE_PREFIXES.items():
        statuses = [
            str(old_coverage[key]) for key in old_coverage if any(key.startswith(prefix) for prefix in prefixes)
        ] + [
            str(new_coverage[key]) for key in new_coverage if any(key.startswith(prefix) for prefix in prefixes)
        ]
        if not statuses:
            statuses = ["not_configured"]
        if any(_coverage_status(status) != "ready" for status in statuses):
            findings.append(
                _finding(
                    section,
                    "verification_unavailable",
                    old_coverage.get(section),
                    new_coverage.get(section),
                )
            )
            continue
        if sections_changed:
            _compare_values(before.get(section, {}), after.get(section, {}), section, section, findings)
    return findings


def _aggregate_coverage(statuses: list[object]) -> CoverageStatus:
    normalized = [_coverage_status(status) for status in statuses]
    if normalized and all(status == "ready" for status in normalized):
        return "ready"
    if any(status == "failed" for status in normalized):
        return "failed"
    if any(status == "blocked" for status in normalized):
        return "blocked"
    if any(status == "partial" for status in normalized):
        return "partial"
    return "not_configured"


def _finding(domain: str, classification: str, previous: object, current: object) -> dict[str, object]:
    return {
        "domain": domain,
        "path": domain,
        "classification": classification,
        "previous": previous,
        "current": current,
    }


def _compare_values(
    before: object,
    after: object,
    domain: str,
    path: str,
    findings: list[dict[str, object]],
) -> None:
    if isinstance(before, Mapping) and isinstance(after, Mapping):
        if (
            path.rsplit(".", 1)[-1] == "assets" and (before or after)
        ) or (_is_entity_map(before, path) and _is_entity_map(after, path)):
            _compare_entity_map(before, after, domain, path, findings)
            return
        keys = sorted(set(before) | set(after), key=str)
        for key in keys:
            child_path = f"{path}.{key}"
            if key not in before:
                if isinstance(after[key], Mapping):
                    _compare_mapping_entries(after[key], domain, child_path, "new", findings)
                else:
                    findings.append(_finding(domain, "new", None, after[key]))
                    findings[-1]["path"] = child_path
            elif key not in after:
                if isinstance(before[key], Mapping):
                    _compare_mapping_entries(before[key], domain, child_path, "removed", findings)
                else:
                    findings.append(_finding(domain, "removed", before[key], None))
                    findings[-1]["path"] = child_path
            else:
                _compare_values(before[key], after[key], domain, child_path, findings)
        return
    if _canonicalize(before) == _canonicalize(after):
        return
    classification = "changed"
    if isinstance(before, (int, float)) and not isinstance(before, bool) and isinstance(after, (int, float)):
        polarity = _POSTURE_POLARITY.get(path.rsplit(".", 1)[-1])
        if polarity == "bad_up":
            if after == 0 and before != 0:
                classification = "resolved"
            else:
                classification = "worsened" if after > before else "improved"
        elif polarity == "good_up":
            classification = "improved" if after > before else "worsened"
    findings.append(_finding(domain, classification, before, after))
    findings[-1]["path"] = path


def _is_entity_map(value: Mapping[object, object], path: str) -> bool:
    entries = [item for item in value.values() if isinstance(item, Mapping)]
    if not value or len(entries) != len(value):
        return False
    shapes = {tuple(sorted(entry, key=str)) for entry in entries}
    return path.rsplit(".", 1)[-1] == "assets" or (len(value) > 1 and len(shapes) == 1)


def _compare_entity_map(
    before: Mapping[str, object],
    after: Mapping[str, object],
    domain: str,
    path: str,
    findings: list[dict[str, object]],
) -> None:
    for key in sorted(set(before) | set(after), key=str):
        entry_path = f"{path}.{key}"
        if key not in before:
            classification, previous, current = "new", None, after[key]
        elif key not in after:
            classification, previous, current = "removed", before[key], None
        elif _canonicalize(before[key]) == _canonicalize(after[key]):
            continue
        else:
            classification, previous, current = "changed", before[key], after[key]
        findings.append(_finding(domain, classification, previous, current))
        findings[-1]["path"] = entry_path


def _compare_mapping_entries(
    values: Mapping[str, object],
    domain: str,
    path: str,
    classification: str,
    findings: list[dict[str, object]],
) -> None:
    """Emit one finding per entry when an entity map is added or removed."""

    for key in sorted(values, key=str):
        entry_path = f"{path}.{key}"
        previous = values[key] if classification == "removed" else None
        current = values[key] if classification == "new" else None
        findings.append(_finding(domain, classification, previous, current))
        findings[-1]["path"] = entry_path


def _matching_approval(
    approvals: list[ApprovalRequest], domain: str, start: datetime, end: datetime
) -> ApprovalRequest | None:
    keywords = {
        "microsoft_posture": ("m365", "microsoft", "device", "security", "conditional", "sign-in"),
        "environment_graph": ("graph", "environment", "inventory"),
        "canonical_assets": ("asset", "inventory", "device"),
        "connector_readiness": ("connector", "sync", "import"),
    }.get(domain, (domain,))
    for approval in approvals:
        if approval.id is None or approval.status != "approved" or not approval.executed_at:
            continue
        try:
            executed = datetime.fromisoformat(approval.executed_at)
        except ValueError:
            continue
        if executed.tzinfo is None:
            executed = executed.replace(tzinfo=UTC)
        if not start <= executed.astimezone(UTC) <= end:
            continue
        haystack = f"{approval.action_type} {approval.payload_json}".casefold()
        if any(keyword in haystack for keyword in keywords):
            return approval
    return None
