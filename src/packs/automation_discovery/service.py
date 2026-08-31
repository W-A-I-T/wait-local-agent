"""Deterministic historical PSA discovery built from tenant-scoped local evidence.

The discovery layer is intentionally read-only with respect to external systems.
It groups historical tickets, attaches measured labor only when normalized PSA time
entries are present, and maps recurring work to existing WAIT workflows/playbooks.
Generating a report never enables or executes an automation.
"""

from __future__ import annotations

import re
import sqlite3
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Iterable

from wait_local_agent.client_scope import BoundClients
from wait_local_agent.migrations import Migration, MigrationRunner
from wait_local_agent.models import Ticket
from wait_local_agent.msp_playbooks import MSP_PLAYBOOKS
from wait_local_agent.store import Store, utc_now
from wait_local_agent.workflows import get_workflow_template

DISCOVERY_MIGRATION_VERSION = 1200
MAX_DISCOVERY_TICKETS = 10_000
MAX_EVIDENCE_IDS = 50
MAX_DYNAMIC_SIGNATURES = 10
_STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "for",
    "from",
    "help",
    "i",
    "in",
    "is",
    "it",
    "my",
    "of",
    "on",
    "please",
    "re",
    "the",
    "to",
    "user",
    "with",
}
_TOKEN_RE = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class CategoryRule:
    category_id: str
    label: str
    patterns: tuple[str, ...]
    workflows: tuple[str, ...]
    playbooks: tuple[str, ...]
    prerequisites: tuple[str, ...]
    default_minutes_estimate: int


@dataclass(frozen=True)
class HistoricalTimeEntry:
    client_id: str
    ticket_id: str
    connector_instance_id: str
    external_time_entry_id: str
    minutes: int
    work_type: str
    occurred_at: str
    source_system: str


CATEGORY_RULES: tuple[CategoryRule, ...] = (
    CategoryRule(
        category_id="password-mfa-authentication",
        label="Password resets, MFA and sign-in",
        patterns=(
            r"password\s*(reset|expired|forgot|change)",
            r"mfa|multi[- ]factor|authenticator",
            r"locked\s*out|unlock",
            r"can.?t\s+(sign|log)\s*in|login\s+(issue|problem|failed)",
        ),
        workflows=("m365-password-reset-review", "m365-authentication-method-removal-review"),
        playbooks=("resolution-review",),
        prerequisites=("m365",),
        default_minutes_estimate=8,
    ),
    CategoryRule(
        category_id="onboarding-offboarding",
        label="User onboarding and offboarding",
        patterns=(
            r"onboard|new\s+(hire|starter|employee|user)",
            r"offboard|termination|terminate|departing\s+(employee|user)",
            r"disable\s+(account|user)",
        ),
        workflows=("m365-user-onboarding-review", "m365-user-offboarding-review"),
        playbooks=("m365-onboarding-review",),
        prerequisites=("m365", "psa"),
        default_minutes_estimate=30,
    ),
    CategoryRule(
        category_id="software-license-request",
        label="Software installation and license requests",
        patterns=(
            r"install\s+(app|application|software|program)",
            r"software\s+(install|request|access)",
            r"license\s+(request|assign|add|remove)",
            r"need\s+(a\s+)?license",
        ),
        workflows=("m365-license-request-review", "software-inventory-review"),
        playbooks=(),
        prerequisites=("m365", "rmm"),
        default_minutes_estimate=15,
    ),
    CategoryRule(
        category_id="mailbox-group-change",
        label="Mailbox, group and distribution-list changes",
        patterns=(
            r"shared\s+mailbox|mailbox\s+(permission|access|delegate)",
            r"distribution\s+(list|group)|distro",
            r"add\s+.*\s+to\s+(group|mailbox)|remove\s+.*\s+from\s+(group|mailbox)",
            r"send\s+as|send\s+on\s+behalf",
        ),
        workflows=("documentation-assisted-response",),
        playbooks=("resolution-review",),
        prerequisites=("m365", "psa"),
        default_minutes_estimate=12,
    ),
    CategoryRule(
        category_id="disk-printer-endpoint-alert",
        label="Disk, printer and endpoint alerts",
        patterns=(
            r"disk\s+(space|full|low)|low\s+disk",
            r"printer|printing|print\s+queue|spooler",
            r"endpoint\s+(alert|offline|issue)|device\s+(offline|alert)",
        ),
        workflows=("l1-resolution-review", "software-inventory-review"),
        playbooks=("resolution-review",),
        prerequisites=("rmm", "psa"),
        default_minutes_estimate=18,
    ),
    CategoryRule(
        category_id="stale-follow-up",
        label="Ticket follow-up and stale work",
        patterns=(
            r"follow\s*up|waiting\s+on\s+(user|client)|no\s+response",
            r"stale|pending\s+(customer|user|client)",
        ),
        workflows=("inactive-ticket-follow-up", "stale-ticket-sweep-review"),
        playbooks=("stale-sla-review",),
        prerequisites=("psa",),
        default_minutes_estimate=6,
    ),
    CategoryRule(
        category_id="security-alert",
        label="Security alerts and incident review",
        patterns=(
            r"phish|phishing|malware|ransomware|virus",
            r"security\s+(alert|incident)|suspicious\s+(login|sign.?in|activity)",
            r"compromis(ed|e)|breach",
        ),
        workflows=("security-alert-review",),
        playbooks=("security-response-review",),
        prerequisites=("psa",),
        default_minutes_estimate=25,
    ),
)


def ensure_schema(store: Store) -> None:
    """Install local normalized labor-evidence storage."""

    with store._connect() as connection:  # noqa: SLF001 - pack migration uses canonical local store
        MigrationRunner(connection).run(
            (
                Migration(
                    DISCOVERY_MIGRATION_VERSION,
                    "historical_psa_time_entries",
                    _apply_schema,
                ),
            )
        )


def _apply_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        create table if not exists historical_psa_time_entries (
            id integer primary key autoincrement,
            client_id text not null references clients(client_id) on delete cascade,
            ticket_id text not null,
            connector_instance_id text not null,
            external_time_entry_id text not null,
            minutes integer not null check (minutes >= 0 and minutes <= 1440),
            work_type text not null default '',
            occurred_at text not null,
            source_system text not null,
            created_at text not null,
            unique (connector_instance_id, external_time_entry_id)
        )
        """
    )
    connection.execute(
        """
        create index if not exists idx_historical_psa_time_entries_client_ticket
        on historical_psa_time_entries (client_id, ticket_id, occurred_at)
        """
    )


def import_time_entries(store: Store, entries: Iterable[HistoricalTimeEntry]) -> dict[str, int]:
    """Idempotently persist normalized provider time-entry evidence."""

    ensure_schema(store)
    inserted = 0
    duplicate = 0
    rejected = 0
    with store._connect() as connection:  # noqa: SLF001 - canonical local evidence store
        for entry in entries:
            if entry.minutes < 0 or entry.minutes > 1440:
                rejected += 1
                continue
            if not entry.ticket_id.strip() or not entry.external_time_entry_id.strip():
                rejected += 1
                continue
            try:
                connection.execute(
                    """
                    insert into historical_psa_time_entries (
                        client_id, ticket_id, connector_instance_id, external_time_entry_id,
                        minutes, work_type, occurred_at, source_system, created_at
                    ) values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        entry.client_id,
                        entry.ticket_id.strip(),
                        entry.connector_instance_id.strip(),
                        entry.external_time_entry_id.strip(),
                        int(entry.minutes),
                        entry.work_type.strip()[:160],
                        _iso_timestamp(entry.occurred_at),
                        entry.source_system.strip()[:80],
                        utc_now(),
                    ),
                )
                inserted += 1
            except sqlite3.IntegrityError:
                duplicate += 1
    return {"inserted": inserted, "duplicate": duplicate, "rejected": rejected}


def build_historical_discovery(
    store: Store,
    *,
    client_id: str,
    days: int = 60,
    min_tickets: int = 3,
) -> dict[str, object]:
    """Rank recurring historical ticket families without enabling any automation."""

    if not 7 <= days <= 365:
        raise ValueError("days must be between 7 and 365")
    if not 2 <= min_tickets <= 100:
        raise ValueError("min_tickets must be between 2 and 100")

    ensure_schema(store)
    cutoff = datetime.now(UTC) - timedelta(days=days)
    tickets = [
        ticket
        for ticket in store.list_tickets(client_id=client_id)[:MAX_DISCOVERY_TICKETS]
        if _timestamp(ticket.created_at) >= cutoff
    ]
    labor_by_ticket = _labor_by_ticket(store, client_id=client_id, cutoff=cutoff)
    mapping_readiness = build_mapping_readiness(store, client_id=client_id)

    grouped: dict[str, list[Ticket]] = defaultdict(list)
    unmatched: list[Ticket] = []
    for ticket in tickets:
        category = _classify(ticket)
        if category is None:
            unmatched.append(ticket)
        else:
            grouped[category.category_id].append(ticket)

    opportunities: list[dict[str, object]] = []
    rule_by_id = {rule.category_id: rule for rule in CATEGORY_RULES}
    for category_id, category_tickets in grouped.items():
        if len(category_tickets) < min_tickets:
            continue
        opportunities.append(
            _opportunity(
                rule=rule_by_id[category_id],
                tickets=category_tickets,
                labor_by_ticket=labor_by_ticket,
                mapping_readiness=mapping_readiness,
            )
        )

    opportunities.extend(
        _dynamic_opportunities(
            unmatched,
            labor_by_ticket=labor_by_ticket,
            min_tickets=min_tickets,
        )
    )
    opportunities.sort(key=_opportunity_sort_key)

    measured_minutes = sum(
        int(item["measured_labor_minutes"])
        for item in opportunities
        if item["measured_labor_available"] is True
    )
    estimated_minutes = sum(int(item["estimated_automation_minutes"]) for item in opportunities)
    source_counts = Counter(ticket.source_system or "local" for ticket in tickets)

    return {
        "client_id": client_id,
        "window_days": days,
        "ticket_count": len(tickets),
        "source_counts": dict(sorted(source_counts.items())),
        "opportunity_count": len(opportunities),
        "opportunities": opportunities,
        "labor": {
            "measured_minutes": measured_minutes,
            "measured": bool(labor_by_ticket),
            "measured_ticket_count": len(labor_by_ticket),
            "estimate_minutes": estimated_minutes,
            "estimate": True,
            "derivation": (
                "Measured labor uses normalized PSA time entries only. Estimated automation minutes use "
                "declared category defaults multiplied by ticket volume and are never presented as measured savings."
            ),
        },
        "mapping_readiness": mapping_readiness,
        "side_effects": False,
        "automation_enabled": False,
        "next_step": (
            "Review an opportunity, inspect its source ticket IDs and prerequisites, then test the mapped "
            "WAIT workflow or playbook before enabling any scheduled or event-driven execution."
        ),
    }


def build_mapping_readiness(store: Store, *, client_id: str) -> dict[str, object]:
    """Summarize cross-system client mapping evidence for discovery readiness."""

    scope = BoundClients(frozenset({client_id}))
    mappings = store.list_client_connector_mappings(scope)
    instances = {item.connector_instance_id: item for item in store.list_connector_instances()}
    families: dict[str, dict[str, int]] = defaultdict(lambda: {"verified": 0, "unverified": 0})
    details: list[dict[str, object]] = []
    for mapping in mappings:
        instance = instances.get(mapping.connector_instance_id)
        connector_type = instance.connector_type if instance else "unknown"
        family = _connector_family(connector_type)
        key = "verified" if mapping.verified == 1 else "unverified"
        families[family][key] += 1
        details.append(
            {
                "mapping_id": mapping.mapping_id,
                "connector_instance_id": mapping.connector_instance_id,
                "connector_type": connector_type,
                "family": family,
                "external_company_id": mapping.external_company_id,
                "external_company_name": mapping.external_company_name,
                "verified": mapping.verified == 1,
            }
        )
    return {
        "families": {key: value for key, value in sorted(families.items())},
        "mappings": details,
        "verified_count": sum(1 for item in mappings if item.verified == 1),
        "unverified_count": sum(1 for item in mappings if item.verified != 1),
        "coverage_goal": ["psa", "rmm", "documentation", "m365", "security"],
    }


def _opportunity(
    *,
    rule: CategoryRule,
    tickets: list[Ticket],
    labor_by_ticket: dict[str, int],
    mapping_readiness: dict[str, object],
) -> dict[str, object]:
    measured_ticket_ids = [ticket.id for ticket in tickets if ticket.id in labor_by_ticket]
    measured_minutes = sum(labor_by_ticket.get(ticket.id, 0) for ticket in tickets)
    source_counts = Counter(ticket.source_system or "local" for ticket in tickets)
    priority_counts = Counter(ticket.priority.strip().lower() or "unknown" for ticket in tickets)
    resolved_count = sum(1 for ticket in tickets if ticket.status.strip().lower() in {"resolved", "closed"})
    workflow_matches = [
        _workflow_match(workflow_id)
        for workflow_id in rule.workflows
        if get_workflow_template(workflow_id) is not None
    ]
    playbook_matches = [
        _playbook_match(playbook_id)
        for playbook_id in rule.playbooks
        if any(playbook.id == playbook_id for playbook in MSP_PLAYBOOKS)
    ]
    prerequisites = _prerequisite_status(rule.prerequisites, mapping_readiness)
    ready = bool(workflow_matches or playbook_matches) and all(item["status"] != "missing" for item in prerequisites)
    return {
        "category_id": rule.category_id,
        "label": rule.label,
        "ticket_count": len(tickets),
        "resolved_or_closed": resolved_count,
        "source_counts": dict(sorted(source_counts.items())),
        "priority_counts": dict(sorted(priority_counts.items())),
        "measured_labor_available": bool(measured_ticket_ids),
        "measured_labor_minutes": measured_minutes,
        "measured_labor_ticket_count": len(measured_ticket_ids),
        "estimated_automation_minutes": len(tickets) * rule.default_minutes_estimate,
        "estimate": True,
        "workflow_matches": workflow_matches,
        "playbook_matches": playbook_matches,
        "prerequisites": prerequisites,
        "readiness": "ready_for_review" if ready else "prerequisites_required",
        "source_ticket_ids": [ticket.id for ticket in tickets[:MAX_EVIDENCE_IDS]],
        "source_ticket_ids_truncated": len(tickets) > MAX_EVIDENCE_IDS,
        "reason": f"{len(tickets)} historical tickets matched the deterministic '{rule.label}' service pattern.",
    }


def _dynamic_opportunities(
    tickets: list[Ticket],
    *,
    labor_by_ticket: dict[str, int],
    min_tickets: int,
) -> list[dict[str, object]]:
    buckets: dict[str, list[Ticket]] = defaultdict(list)
    for ticket in tickets:
        signature = _subject_signature(ticket.subject)
        if signature:
            buckets[signature].append(ticket)
    results: list[dict[str, object]] = []
    for signature, members in sorted(buckets.items(), key=lambda item: (-len(item[1]), item[0])):
        if len(members) < min_tickets:
            continue
        measured_ids = [ticket.id for ticket in members if ticket.id in labor_by_ticket]
        results.append(
            {
                "category_id": f"recurring:{signature.replace(' ', '-')[:80]}",
                "label": f"Recurring ticket family: {signature}",
                "ticket_count": len(members),
                "resolved_or_closed": sum(
                    1 for ticket in members if ticket.status.strip().lower() in {"resolved", "closed"}
                ),
                "source_counts": dict(sorted(Counter(ticket.source_system or "local" for ticket in members).items())),
                "priority_counts": dict(sorted(Counter(ticket.priority.strip().lower() or "unknown" for ticket in members).items())),
                "measured_labor_available": bool(measured_ids),
                "measured_labor_minutes": sum(labor_by_ticket.get(ticket.id, 0) for ticket in members),
                "measured_labor_ticket_count": len(measured_ids),
                "estimated_automation_minutes": 0,
                "estimate": True,
                "workflow_matches": [],
                "playbook_matches": [],
                "prerequisites": [],
                "readiness": "needs_workflow_design",
                "source_ticket_ids": [ticket.id for ticket in members[:MAX_EVIDENCE_IDS]],
                "source_ticket_ids_truncated": len(members) > MAX_EVIDENCE_IDS,
                "reason": (
                    f"{len(members)} otherwise-unclassified tickets share the normalized subject signature "
                    f"'{signature}'. Review before designing a new automation."
                ),
            }
        )
        if len(results) >= MAX_DYNAMIC_SIGNATURES:
            break
    return results


def _workflow_match(workflow_id: str) -> dict[str, object]:
    template = get_workflow_template(workflow_id)
    if template is None:
        return {"id": workflow_id, "available": False}
    return {
        "id": template.id,
        "name": template.name,
        "approval_required": template.approval_required,
        "risk_level": template.risk_level,
        "available": True,
    }


def _playbook_match(playbook_id: str) -> dict[str, object]:
    playbook = next((item for item in MSP_PLAYBOOKS if item.id == playbook_id), None)
    if playbook is None:
        return {"id": playbook_id, "available": False}
    return {
        "id": playbook.id,
        "name": playbook.name,
        "risk_level": playbook.risk_level,
        "available": True,
    }


def _prerequisite_status(
    prerequisites: tuple[str, ...],
    mapping_readiness: dict[str, object],
) -> list[dict[str, str]]:
    raw_families = mapping_readiness.get("families", {})
    families = raw_families if isinstance(raw_families, dict) else {}
    result: list[dict[str, str]] = []
    for family in prerequisites:
        raw = families.get(family, {})
        counts = raw if isinstance(raw, dict) else {}
        verified = int(counts.get("verified", 0))
        unverified = int(counts.get("unverified", 0))
        if verified:
            status = "verified"
        elif unverified:
            status = "review_mapping"
        else:
            status = "missing"
        result.append({"family": family, "status": status})
    return result


def _classify(ticket: Ticket) -> CategoryRule | None:
    text = f"{ticket.subject}\n{ticket.body}".lower()
    for rule in CATEGORY_RULES:
        if any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in rule.patterns):
            return rule
    return None


def _subject_signature(subject: str) -> str:
    tokens = [token for token in _TOKEN_RE.findall(subject.lower()) if token not in _STOP_WORDS and len(token) > 2]
    if len(tokens) < 2:
        return ""
    return " ".join(tokens[:4])


def _labor_by_ticket(store: Store, *, client_id: str, cutoff: datetime) -> dict[str, int]:
    with store._connect() as connection:  # noqa: SLF001 - local evidence read
        rows = connection.execute(
            """
            select ticket_id, sum(minutes) as minutes
            from historical_psa_time_entries
            where client_id = ? and occurred_at >= ?
            group by ticket_id
            """,
            (client_id, cutoff.isoformat()),
        ).fetchall()
    return {str(row["ticket_id"]): int(row["minutes"] or 0) for row in rows}


def _connector_family(connector_type: str) -> str:
    normalized = connector_type.strip().lower()
    if any(token in normalized for token in ("connectwise", "autotask", "halopsa", "servicenow", "syncro")):
        return "psa"
    if any(token in normalized for token in ("rmm", "ninja", "datto", "ncentral", "n-central", "nsight", "n-sight", "kaseya", "screenconnect", "automate", "asio")):
        return "rmm"
    if any(token in normalized for token in ("itglue", "it-glue", "hudu", "confluence", "sharepoint", "notion", "lexful")):
        return "documentation"
    if any(token in normalized for token in ("m365", "microsoft", "entra", "intune", "exchange")):
        return "m365"
    if any(token in normalized for token in ("huntress", "threatlocker", "defender", "sentinel", "crowdstrike", "sophos")):
        return "security"
    return "other"


def _opportunity_sort_key(item: dict[str, object]) -> tuple[int, int, str]:
    measured = int(item.get("measured_labor_minutes", 0))
    count = int(item.get("ticket_count", 0))
    return (-measured, -count, str(item.get("label", "")))


def _timestamp(value: str) -> datetime:
    if not value.strip():
        return datetime.min.replace(tzinfo=UTC)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return datetime.min.replace(tzinfo=UTC)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _iso_timestamp(value: str) -> str:
    parsed = _timestamp(value)
    if parsed == datetime.min.replace(tzinfo=UTC):
        raise ValueError("occurred_at must be an ISO-8601 timestamp")
    return parsed.isoformat()


def category_catalog() -> list[dict[str, Any]]:
    return [asdict(rule) for rule in CATEGORY_RULES]
