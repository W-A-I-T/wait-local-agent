"""Deterministic technician profiles, workload snapshots, and dispatch ranking."""

from __future__ import annotations

import builtins
import re
import sqlite3
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, time
from typing import cast
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from wait_local_agent.store import Store

from .storage import (
    AgentPlatformError,
    AgentPlatformNotFoundError,
    actor_identifier,
    ensure_schema,
    json_dumps,
    json_loads_list,
    json_loads_object,
    parse_iso_timestamp,
    require_client,
    utc_now,
    validate_identifier,
    validate_text,
)

_DAY_NAMES = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)
_TOKEN_RE = re.compile(r"[a-z0-9]{2,}")
_CLOCK_RE = re.compile(r"^(?:[01][0-9]|2[0-3]):[0-5][0-9]$")
MAX_EXPERTISE = 32


@dataclass(frozen=True)
class TechnicianWorkload:
    id: int
    client_id: str
    technician_id: str
    open_tickets: int
    active_incidents: int
    scheduled_changes: int
    unavailable_until: str | None
    source: str
    observed_at: str
    created_by: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class TechnicianProfile:
    client_id: str
    technician_id: str
    display_name: str
    timezone: str
    working_hours: dict[str, object]
    expertise: list[str]
    client_familiarity: int
    capacity: int
    enabled: bool
    created_by: str
    created_at: str
    updated_at: str
    workload: TechnicianWorkload | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class TechnicianService:
    def __init__(self, store: Store) -> None:
        self.store = store
        ensure_schema(store)

    def upsert_profile(
        self,
        *,
        client_id: str,
        technician_id: str,
        display_name: str,
        timezone: str,
        working_hours: dict[str, object],
        expertise: list[str],
        client_familiarity: int,
        capacity: int,
        enabled: bool,
        actor: str,
    ) -> TechnicianProfile:
        client_id = require_client(self.store, client_id)
        technician_id = validate_identifier(technician_id, "technician_id")
        display_name = validate_text(display_name, "display_name", minimum=1, maximum=160)
        timezone = _timezone(timezone)
        working_hours = _working_hours(working_hours)
        expertise = _expertise(expertise)
        if (
            isinstance(client_familiarity, bool)
            or not isinstance(client_familiarity, int)
            or not 0 <= client_familiarity <= 5
        ):
            raise AgentPlatformError("client_familiarity must be an integer between 0 and 5")
        if isinstance(capacity, bool) or not isinstance(capacity, int) or not 1 <= capacity <= 100:
            raise AgentPlatformError("capacity must be an integer between 1 and 100")
        actor = actor_identifier(actor)
        now = utc_now()
        with self.store._connect() as connection:  # noqa: SLF001
            connection.execute(
                """
                insert into technician_profiles (
                    client_id, technician_id, display_name, timezone,
                    working_hours_json, expertise_json, client_familiarity,
                    capacity, enabled, created_by, created_at, updated_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                on conflict (client_id, technician_id) do update set
                    display_name = excluded.display_name,
                    timezone = excluded.timezone,
                    working_hours_json = excluded.working_hours_json,
                    expertise_json = excluded.expertise_json,
                    client_familiarity = excluded.client_familiarity,
                    capacity = excluded.capacity,
                    enabled = excluded.enabled,
                    updated_at = excluded.updated_at
                """,
                (
                    client_id,
                    technician_id,
                    display_name,
                    timezone,
                    json_dumps(working_hours),
                    json_dumps(expertise),
                    client_familiarity,
                    capacity,
                    int(bool(enabled)),
                    actor,
                    now,
                    now,
                ),
            )
        self.store.add_audit_event(
            "technician_profile.updated",
            technician_id,
            f"enabled={bool(enabled)} expertise={len(expertise)}",
            client_id=client_id,
            approver_id=actor,
        )
        return self.get(client_id=client_id, technician_id=technician_id)

    def record_workload(
        self,
        *,
        client_id: str,
        technician_id: str,
        open_tickets: int,
        active_incidents: int,
        scheduled_changes: int,
        unavailable_until: str | None,
        source: str,
        observed_at: str | None,
        actor: str,
    ) -> TechnicianWorkload:
        profile = self.get(client_id=client_id, technician_id=technician_id)
        for label, value in (
            ("open_tickets", open_tickets),
            ("active_incidents", active_incidents),
            ("scheduled_changes", scheduled_changes),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 100_000:
                raise AgentPlatformError(f"{label} must be a non-negative integer")
        unavailable_until = parse_iso_timestamp(unavailable_until, "unavailable_until")
        observed_at = parse_iso_timestamp(observed_at, "observed_at") or utc_now()
        source = validate_text(source, "source", minimum=1, maximum=120)
        actor = actor_identifier(actor)
        with self.store._connect() as connection:  # noqa: SLF001
            cursor = connection.execute(
                """
                insert into technician_workloads (
                    client_id, technician_id, open_tickets, active_incidents,
                    scheduled_changes, unavailable_until, source, observed_at, created_by
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    profile.client_id,
                    profile.technician_id,
                    open_tickets,
                    active_incidents,
                    scheduled_changes,
                    unavailable_until,
                    source,
                    observed_at,
                    actor,
                ),
            )
            if cursor.lastrowid is None:
                raise RuntimeError("technician workload insert did not return an ID")
            workload_id = int(cursor.lastrowid)
        self.store.add_audit_event(
            "technician_workload.recorded",
            technician_id,
            f"source={source} open={open_tickets} incidents={active_incidents}",
            client_id=profile.client_id,
            approver_id=actor,
        )
        return self._get_workload(workload_id, profile.client_id)

    def get(self, *, client_id: str, technician_id: str) -> TechnicianProfile:
        client_id = require_client(self.store, client_id)
        technician_id = validate_identifier(technician_id, "technician_id")
        with self.store._connect() as connection:  # noqa: SLF001
            row = connection.execute(
                """
                select * from technician_profiles
                where client_id = ? and technician_id = ?
                """,
                (client_id, technician_id),
            ).fetchone()
        if row is None:
            raise AgentPlatformNotFoundError("technician profile was not found")
        return _profile(row, self._latest_workload(client_id, technician_id))

    def list(self, *, client_id: str, include_disabled: bool = False) -> list[TechnicianProfile]:
        client_id = require_client(self.store, client_id)
        enabled_clause = "" if include_disabled else "and enabled = 1"
        with self.store._connect() as connection:  # noqa: SLF001
            rows = connection.execute(
                f"""
                select * from technician_profiles
                where client_id = ? {enabled_clause}
                order by display_name, technician_id
                """,  # nosec B608 - enabled clause is fixed locally
                (client_id,),
            ).fetchall()
        return [
            _profile(
                row,
                self._latest_workload(client_id, str(row["technician_id"])),
            )
            for row in rows
        ]

    def recommend(
        self,
        *,
        client_id: str,
        ticket_id: str,
        required_expertise: builtins.list[str] | None = None,
        limit: int = 5,
        now: str | None = None,
    ) -> dict[str, object]:
        client_id = require_client(self.store, client_id)
        ticket_id = validate_identifier(ticket_id, "ticket_id")
        ticket = self.store.get_ticket(ticket_id, client_id=client_id)
        if ticket is None:
            raise AgentPlatformNotFoundError("ticket was not found")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 20:
            raise AgentPlatformError("limit must be an integer between 1 and 20")
        required = _expertise(required_expertise or [])
        ticket_text = f"{ticket.subject} {ticket.body}".casefold()
        ticket_tokens = set(_TOKEN_RE.findall(ticket_text))
        effective_now = _timestamp(now)
        candidates: list[dict[str, object]] = []
        for profile in self.list(client_id=client_id):
            workload = profile.workload
            availability, availability_reason = _availability(profile, workload, effective_now)
            expertise_score, matched_expertise = _expertise_score(
                profile.expertise,
                required,
                ticket_text,
                ticket_tokens,
            )
            open_work = (
                (workload.open_tickets if workload else 0)
                + 3 * (workload.active_incidents if workload else 0)
                + 2 * (workload.scheduled_changes if workload else 0)
            )
            workload_ratio = min(open_work / max(profile.capacity, 1), 2.0)
            workload_score = max(0.0, 1.0 - min(workload_ratio, 1.0))
            familiarity_score = profile.client_familiarity / 5.0
            total = (
                50.0 * availability
                + 25.0 * expertise_score
                + 15.0 * workload_score
                + 10.0 * familiarity_score
            )
            reasons = [availability_reason]
            if matched_expertise:
                reasons.append(f"matched expertise: {', '.join(matched_expertise)}")
            elif required:
                reasons.append("no required expertise match")
            reasons.append(
                f"workload {open_work}/{profile.capacity}; client familiarity {profile.client_familiarity}/5"
            )
            candidates.append(
                {
                    "technician_id": profile.technician_id,
                    "display_name": profile.display_name,
                    "score": round(total, 3),
                    "available": availability > 0,
                    "matched_expertise": matched_expertise,
                    "workload_units": open_work,
                    "capacity": profile.capacity,
                    "workload_ratio": round(workload_ratio, 3),
                    "reasons": reasons,
                    "workload_observed_at": workload.observed_at if workload else None,
                }
            )
        candidates.sort(key=lambda item: (-cast(float, item["score"]), str(item["technician_id"])))
        ranked = candidates[:limit]
        available_ranked = [candidate for candidate in ranked if candidate["available"] is True]
        dispatch_payload = {
            "ticket_id": ticket_id,
            "technicians": [
                {
                    "id": str(candidate["technician_id"]),
                    "workload": cast(float, candidate["workload_ratio"]) * 100.0,
                }
                for candidate in available_ranked
            ],
        }
        return {
            "ticket_id": ticket_id,
            "client_id": client_id,
            "generated_at": effective_now.isoformat(),
            "required_expertise": required,
            "recommendation": available_ranked[0] if available_ranked else None,
            "candidates": ranked,
            "dispatch_payload": dispatch_payload,
            "side_effects": False,
        }

    def _latest_workload(self, client_id: str, technician_id: str) -> TechnicianWorkload | None:
        with self.store._connect() as connection:  # noqa: SLF001
            row = connection.execute(
                """
                select * from technician_workloads
                where client_id = ? and technician_id = ?
                order by observed_at desc, id desc limit 1
                """,
                (client_id, technician_id),
            ).fetchone()
        return _workload(row) if row is not None else None

    def _get_workload(self, workload_id: int, client_id: str) -> TechnicianWorkload:
        with self.store._connect() as connection:  # noqa: SLF001
            row = connection.execute(
                "select * from technician_workloads where id = ? and client_id = ?",
                (workload_id, client_id),
            ).fetchone()
        if row is None:
            raise AgentPlatformNotFoundError("technician workload was not found")
        return _workload(row)


def _profile(row: sqlite3.Row, workload: TechnicianWorkload | None) -> TechnicianProfile:
    return TechnicianProfile(
        client_id=str(row["client_id"]),
        technician_id=str(row["technician_id"]),
        display_name=str(row["display_name"]),
        timezone=str(row["timezone"]),
        working_hours=cast(dict[str, object], json_loads_object(str(row["working_hours_json"]))),
        expertise=[str(value) for value in json_loads_list(str(row["expertise_json"]))],
        client_familiarity=int(row["client_familiarity"]),
        capacity=int(row["capacity"]),
        enabled=bool(row["enabled"]),
        created_by=str(row["created_by"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
        workload=workload,
    )


def _workload(row: sqlite3.Row) -> TechnicianWorkload:
    return TechnicianWorkload(
        id=int(row["id"]),
        client_id=str(row["client_id"]),
        technician_id=str(row["technician_id"]),
        open_tickets=int(row["open_tickets"]),
        active_incidents=int(row["active_incidents"]),
        scheduled_changes=int(row["scheduled_changes"]),
        unavailable_until=(
            str(row["unavailable_until"]) if row["unavailable_until"] is not None else None
        ),
        source=str(row["source"]),
        observed_at=str(row["observed_at"]),
        created_by=str(row["created_by"]),
    )


def _timezone(value: str) -> str:
    normalized = validate_text(value, "timezone", minimum=1, maximum=80)
    try:
        ZoneInfo(normalized)
    except ZoneInfoNotFoundError as exc:
        raise AgentPlatformError("timezone is not a recognized IANA timezone") from exc
    return normalized


def _working_hours(value: dict[str, object]) -> dict[str, object]:
    if not isinstance(value, Mapping) or set(value) - set(_DAY_NAMES):
        raise AgentPlatformError("working_hours must use weekday names as keys")
    normalized: dict[str, object] = {}
    for day, windows in value.items():
        if not isinstance(windows, list) or len(windows) > 4:
            raise AgentPlatformError(f"working_hours.{day} must contain at most four windows")
        normalized_windows: list[dict[str, str]] = []
        for window in windows:
            if not isinstance(window, Mapping):
                raise AgentPlatformError(f"working_hours.{day} entries must be objects")
            start = _clock(str(window.get("start", "")), f"working_hours.{day}.start")
            end = _clock(str(window.get("end", "")), f"working_hours.{day}.end")
            if _as_minutes(start) >= _as_minutes(end):
                raise AgentPlatformError(f"working_hours.{day} start must be before end")
            normalized_windows.append({"start": start, "end": end})
        normalized[str(day)] = normalized_windows
    return normalized


def _clock(value: str, label: str) -> str:
    if not _CLOCK_RE.fullmatch(value):
        raise AgentPlatformError(f"{label} must use HH:MM")
    return time.fromisoformat(value).strftime("%H:%M")


def _as_minutes(value: str) -> int:
    hour, minute = value.split(":")
    return int(hour) * 60 + int(minute)


def _expertise(values: list[str]) -> list[str]:
    if not isinstance(values, list) or len(values) > MAX_EXPERTISE:
        raise AgentPlatformError(f"expertise must contain at most {MAX_EXPERTISE} entries")
    normalized: list[str] = []
    for value in values:
        item = validate_text(value, "expertise entry", minimum=1, maximum=80).casefold()
        if item not in normalized:
            normalized.append(item)
    return normalized


def _timestamp(value: str | None) -> datetime:
    normalized = parse_iso_timestamp(value, "now") if value else None
    return datetime.fromisoformat(normalized) if normalized else datetime.now(UTC)


def _availability(
    profile: TechnicianProfile,
    workload: TechnicianWorkload | None,
    now: datetime,
) -> tuple[float, str]:
    if workload and workload.unavailable_until:
        unavailable_until = datetime.fromisoformat(workload.unavailable_until)
        if unavailable_until > now:
            return 0.0, f"unavailable until {unavailable_until.isoformat()}"
    local = now.astimezone(ZoneInfo(profile.timezone))
    if not profile.working_hours:
        return 1.0, "no restrictive working-hours window configured"
    windows = profile.working_hours.get(_DAY_NAMES[local.weekday()])
    if not isinstance(windows, list) or not windows:
        return 0.0, f"outside working hours in {profile.timezone}"
    current_minutes = local.hour * 60 + local.minute
    for window in windows:
        if not isinstance(window, Mapping):
            continue
        start = window.get("start")
        end = window.get("end")
        if isinstance(start, str) and isinstance(end, str):
            if _as_minutes(start) <= current_minutes < _as_minutes(end):
                return 1.0, f"within working hours in {profile.timezone}"
    return 0.0, f"outside working hours in {profile.timezone}"


def _expertise_score(
    expertise: list[str],
    required: list[str],
    ticket_text: str,
    ticket_tokens: set[str],
) -> tuple[float, list[str]]:
    matched: list[str] = []
    candidates = required or expertise
    for item in expertise:
        item_tokens = set(_TOKEN_RE.findall(item))
        requested = item in required if required else False
        present = item in ticket_text or bool(item_tokens and item_tokens <= ticket_tokens)
        if requested or present:
            matched.append(item)
    if required:
        return len(set(matched) & set(required)) / max(len(required), 1), sorted(set(matched))
    if not candidates:
        return 0.5, []
    return min(len(matched) / max(len(candidates), 1), 1.0), sorted(set(matched))


__all__ = ["TechnicianProfile", "TechnicianService", "TechnicianWorkload"]
