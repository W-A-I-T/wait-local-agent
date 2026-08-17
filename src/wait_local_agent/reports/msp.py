from __future__ import annotations

from collections import Counter
from datetime import date, datetime
from typing import Any, cast

from wait_local_agent.models import Ticket
from wait_local_agent.observability import build_analytics_summary
from wait_local_agent.reports.models import ReportSection
from wait_local_agent.store import Store

# An automation opportunity needs enough evidence to support a review, rather
# than treating an isolated successful action as a repeatable pattern.
AUTOMATION_OPPORTUNITY_MIN_ATTEMPTS = 5
AUTOMATION_OPPORTUNITY_MIN_SUCCESSES = 3
AUTOMATION_OPPORTUNITY_MIN_SUCCESS_RATE = 0.80
AUTOMATION_OPPORTUNITY_MIN_WINDOW_DAYS = 30
AUTOMATION_OPPORTUNITY_MAX_WINDOW_DAYS = 90
AUTOMATION_OPPORTUNITY_MAX_CANDIDATES = 20


def build_qbr_report(
    store: Store,
    estimates: dict[str, int],
    *,
    client_id: str,
    period_start: str,
    period_end: str,
) -> tuple[list[ReportSection], dict[str, Any]]:
    """Build a deterministic, client-scoped quarterly review from local evidence.

    The report intentionally uses stored ticket/status and execution records only.
    It does not infer SLA compliance, customer sentiment, or measured time savings.
    Any savings value comes from the declared smart-action estimate metadata and is
    labelled as an estimate in both the report and metadata.
    """

    start, end = _period(period_start, period_end)
    tickets = [
        ticket
        for ticket in store.list_tickets(client_id=client_id)
        if _in_period(ticket.created_at, start, end)
    ]
    executions = [
        run
        for run in store.list_execution_runs(client_id=client_id)
        if _in_period(run.started_at, start, end)
    ]
    analytics = cast(
        dict[str, Any],
        build_analytics_summary(
            store,
            estimates,
            started_from=period_start,
            started_to=period_end,
            client_id=client_id,
        ),
    )
    action_candidates = _successful_action_candidates(store, estimates, client_id, start, end)
    status_counts = Counter(ticket.status.strip().lower() or "unknown" for ticket in tickets)
    priority_counts = Counter(ticket.priority.strip().lower() or "unknown" for ticket in tickets)
    ticket_metrics = cast(dict[str, Any], analytics["ticket_metrics"])
    historical = cast(dict[str, Any], ticket_metrics["historical_resolution"])
    estimated_minutes_saved = cast(dict[str, Any], analytics["estimated_minutes_saved"])
    evidence_status = _qbr_evidence_status(tickets, executions, historical)

    sections = [
        ReportSection(
            title="Service Volume And Status",
            summary=(
                f"{len(tickets)} client tickets were created in the requested period. "
                "Counts are based on locally stored ticket records."
            ),
            findings=[
                {
                    "ticket_count": len(tickets),
                    "status_counts": dict(sorted(status_counts.items())),
                    "priority_counts": dict(sorted(priority_counts.items())),
                    "ticket_ids": _bounded_ids(tickets),
                    "ticket_id_count": len(tickets),
                    "ticket_ids_truncated": len(tickets) > 100,
                }
            ],
            evidence=[
                {
                    "kind": "local_ticket_records",
                    "client_id": client_id,
                    "period_start": period_start,
                    "period_end": period_end,
                    "record_count": len(tickets),
                    "derivation": "Ticket created_at falls within the requested inclusive date range.",
                }
            ],
        ),
        ReportSection(
            title="Resolution Evidence",
            summary=(
                f"{status_counts.get('resolved', 0) + status_counts.get('closed', 0)} of "
                f"{len(tickets)} in-period tickets are currently resolved or closed."
            ),
            findings=[
                {
                    "current_resolved_or_closed": status_counts.get("resolved", 0)
                    + status_counts.get("closed", 0),
                    "current_resolution_rate": _rate(
                        status_counts.get("resolved", 0) + status_counts.get("closed", 0),
                        len(tickets),
                    ),
                    "historical_resolution": historical,
                }
            ],
            evidence=[
                {
                    "kind": "ticket_status_history",
                    "client_id": client_id,
                    "period_start": period_start,
                    "period_end": period_end,
                    "derivation": (
                        "Historical resolution metrics use explicit local status transitions; "
                        "missing transitions are not inferred."
                    ),
                }
            ],
            recommendations=(
                ["Import or ingest explicit status transitions before using historical resolution time."]
                if historical.get("with_duration", 0) == 0 and tickets
                else []
            ),
        ),
        ReportSection(
            title="Automation Activity And Savings Estimate",
            summary=(
                f"{len(executions)} execution records were observed. Any time-saved value "
                "is a declared action estimate, not a measured operational result."
            ),
            findings=[
                {
                    "execution_count": len(executions),
                    "success_rate": analytics["success_rate"],
                    "approval_rate": analytics["approval_rate"],
                    "estimated_minutes_saved": estimated_minutes_saved,
                    "top_candidates": action_candidates,
                }
            ],
            evidence=[
                {
                    "kind": "local_execution_records",
                    "client_id": client_id,
                    "period_start": period_start,
                    "period_end": period_end,
                    "record_count": len(executions),
                    "derivation": estimated_minutes_saved["derivation"],
                }
            ],
            recommendations=(
                ["Review successful actions as candidates for a bounded, approval-aware workflow."]
                if action_candidates
                else ["Collect more local execution history before ranking automation candidates."]
            ),
        ),
    ]
    metadata = {
        "client_id": client_id,
        "period_start": period_start,
        "period_end": period_end,
        "ticket_count": len(tickets),
        "execution_count": len(executions),
        "estimated_minutes_saved": analytics["estimated_minutes_saved"],
        "evidence_status": evidence_status,
        "scope": "single client",
    }
    return sections, metadata


def build_automation_opportunity_report(
    store: Store,
    estimates: dict[str, int],
    *,
    client_id: str,
    period_start: str,
    period_end: str,
) -> tuple[list[ReportSection], dict[str, Any]]:
    """Rank threshold-qualified local actions as reviewable workflow candidates."""

    start, end = _period(period_start, period_end)
    window_days = (end - start).days
    window_out_of_range = not (
        AUTOMATION_OPPORTUNITY_MIN_WINDOW_DAYS
        <= window_days
        <= AUTOMATION_OPPORTUNITY_MAX_WINDOW_DAYS
    )
    if window_out_of_range:
        candidates: list[dict[str, Any]] = []
        executions = []
        evidence_status = "window_out_of_range"
        evidence_reason = (
            "Automation opportunity reports require an inclusive window of 30 to 90 days."
        )
    else:
        candidates = _automation_opportunity_candidates(store, estimates, client_id, start, end)
        executions = [
            run
            for run in store.list_execution_runs(client_id=client_id)
            if _in_period(run.started_at, start, end)
        ]
        evidence_status = "completed" if candidates else "no_evidence"
    sections = [
        ReportSection(
            title="Automation Candidates",
            summary=(
                f"{len(candidates)} automation candidates met the thresholds of at least "
                f"{AUTOMATION_OPPORTUNITY_MIN_ATTEMPTS} attempts, "
                f"{AUTOMATION_OPPORTUNITY_MIN_SUCCESSES} successes, "
                f"{AUTOMATION_OPPORTUNITY_MIN_SUCCESS_RATE:.0%} success rate, and positive "
                "declared savings. Ranking is a review aid, not an automatic workflow change."
            ),
            findings=candidates,
            evidence=[
                {
                    "kind": "local_execution_records",
                    "client_id": client_id,
                    "period_start": period_start,
                    "period_end": period_end,
                    "record_count": len(executions),
                    "derivation": (
                        "Candidates group all in-window smart-action records by action_id; "
                        "non-success statuses contribute to attempts and failures, and only "
                        "threshold-qualified actions are included. No workflow is enabled or "
                        "executed by report generation."
                    ),
                }
            ],
            recommendations=(
                [
                    "Review the top candidate, define its allowed tools and approval rules, "
                    "then test it in dry-run mode."
                ]
                if candidates
                else [evidence_reason]
                if window_out_of_range
                else ["Collect successful local smart-action history before ranking candidates."]
            ),
        )
    ]
    estimated_minutes = sum(int(item["estimated_minutes_saved"]) for item in candidates)
    metadata: dict[str, Any] = {
        "client_id": client_id,
        "period_start": period_start,
        "period_end": period_end,
        "candidate_count": len(candidates),
        "estimated_minutes_saved": {
            "minutes": estimated_minutes,
            "estimate": True,
            "derivation": (
                "Sum of declared per-action estimates for successful candidate runs; "
                "not measured savings."
            ),
        },
        "evidence_status": evidence_status,
        "scope": "single client",
    }
    if window_out_of_range:
        metadata["window_days"] = window_days
        metadata["evidence_reason"] = evidence_reason
    return sections, metadata


def _automation_opportunity_candidates(
    store: Store,
    estimates: dict[str, int],
    client_id: str,
    start: date,
    end: date,
) -> list[dict[str, Any]]:
    action_metrics: dict[str, dict[str, int]] = {}
    for run in store.list_smart_action_runs(client_id=client_id):
        if not _in_period(run.created_at, start, end):
            continue
        metrics = action_metrics.setdefault(
            run.action_id,
            {"attempts": 0, "successes": 0, "approval_burden": 0},
        )
        metrics["attempts"] += 1
        if run.status in {"success", "completed"}:
            metrics["successes"] += 1
        if run.approval_id is not None:
            metrics["approval_burden"] += 1

    candidates: list[dict[str, Any]] = []
    for action_id, metrics in action_metrics.items():
        attempts = metrics["attempts"]
        successes = metrics["successes"]
        estimate = int(estimates.get(action_id, 0))
        success_rate = successes / attempts
        if not (
            attempts >= AUTOMATION_OPPORTUNITY_MIN_ATTEMPTS
            and successes >= AUTOMATION_OPPORTUNITY_MIN_SUCCESSES
            and success_rate >= AUTOMATION_OPPORTUNITY_MIN_SUCCESS_RATE
            and estimate > 0
        ):
            continue
        candidates.append(
            {
                "action_id": action_id,
                "attempts": attempts,
                "successes": successes,
                "failures": attempts - successes,
                "success_rate": success_rate,
                "approval_burden": metrics["approval_burden"],
                "estimated_minutes_saved": successes * estimate,
                "estimate": True,
                "candidate_reason": (
                    f"Action met the automation-candidate thresholds ({successes}/{attempts} "
                    "successful over the period); review before creating a workflow."
                ),
            }
        )
    candidates.sort(key=lambda item: (-int(item["successes"]), str(item["action_id"])))
    return candidates[:AUTOMATION_OPPORTUNITY_MAX_CANDIDATES]


def build_recurring_service_review_report(
    store: Store,
    *,
    client_id: str,
    period_start: str,
    period_end: str,
    follow_up_after_days: int = 14,
) -> tuple[list[ReportSection], dict[str, Any]]:
    """Build a deterministic recurring service review from local evidence.

    The review identifies service volume, current open-ticket follow-up candidates,
    explicit lifecycle evidence, and local execution activity. It does not infer
    vendor SLA compliance, customer sentiment, contract health, or measured savings.
    """

    start, end = _period(period_start, period_end)
    if isinstance(follow_up_after_days, bool) or not isinstance(follow_up_after_days, int):
        raise ValueError("follow_up_after_days must be an integer between 1 and 90")
    if not 1 <= follow_up_after_days <= 90:
        raise ValueError("follow_up_after_days must be an integer between 1 and 90")

    all_tickets = store.list_tickets(client_id=client_id)
    period_tickets = [
        ticket for ticket in all_tickets if _in_period(ticket.created_at, start, end)
    ]
    open_tickets = [
        ticket
        for ticket in all_tickets
        if ticket.status.strip().lower() not in {"resolved", "closed"}
    ]
    follow_up_candidates: list[dict[str, Any]] = []
    missing_activity_timestamp = 0
    for ticket in open_tickets:
        activity_at = ticket.updated_at or ticket.created_at
        activity_date = _timestamp_date(activity_at)
        if activity_date is None:
            missing_activity_timestamp += 1
            continue
        age_days = (end - activity_date).days
        if age_days >= follow_up_after_days:
            follow_up_candidates.append(
                {
                    "ticket_id": ticket.id,
                    "status": ticket.status,
                    "priority": ticket.priority,
                    "last_activity_at": activity_at,
                    "age_days": age_days,
                    "candidate_reason": (
                        "Open ticket has no recorded activity within the explicit follow-up threshold."
                    ),
                }
            )
    follow_up_candidates.sort(key=lambda item: (-int(item["age_days"]), str(item["ticket_id"])))
    executions = [
        run
        for run in store.list_execution_runs(client_id=client_id)
        if _in_period(run.started_at, start, end)
    ]
    status_counts = Counter(ticket.status.strip().lower() or "unknown" for ticket in period_tickets)
    priority_counts = Counter(ticket.priority.strip().lower() or "unknown" for ticket in period_tickets)
    lifecycle = cast(
        dict[str, Any],
        store.ticket_lifecycle_metrics(period_start, period_end, client_id),
    )
    evidence_status = (
        "no_evidence"
        if not all_tickets and not executions
        else "partial"
        if missing_activity_timestamp or lifecycle.get("with_duration", 0) == 0
        else "completed"
    )
    sections = [
        ReportSection(
            title="Service Posture",
            summary=(
                f"{len(period_tickets)} client tickets were created in the requested period; "
                f"{len(open_tickets)} tickets are currently open."
            ),
            findings=[
                {
                    "period_ticket_count": len(period_tickets),
                    "current_open_ticket_count": len(open_tickets),
                    "status_counts": dict(sorted(status_counts.items())),
                    "priority_counts": dict(sorted(priority_counts.items())),
                    "period_ticket_ids": _bounded_ids(period_tickets),
                    "period_ticket_ids_truncated": len(period_tickets) > 100,
                }
            ],
            evidence=[
                {
                    "kind": "local_ticket_records",
                    "client_id": client_id,
                    "period_start": period_start,
                    "period_end": period_end,
                    "record_count": len(period_tickets),
                    "derivation": "Ticket created_at falls within the requested inclusive date range.",
                }
            ],
        ),
        ReportSection(
            title="Follow-up Candidates",
            summary=(
                f"{len(follow_up_candidates)} open tickets meet the explicit {follow_up_after_days}-day "
                "follow-up threshold. These are review candidates, not automatic communications."
            ),
            findings=[
                {
                    "follow_up_after_days": follow_up_after_days,
                    "candidates": follow_up_candidates[:100],
                    "candidate_count": len(follow_up_candidates),
                    "candidates_truncated": len(follow_up_candidates) > 100,
                    "excluded_missing_activity_timestamp": missing_activity_timestamp,
                }
            ],
            evidence=[
                {
                    "kind": "local_ticket_activity",
                    "client_id": client_id,
                    "period_end": period_end,
                    "record_count": len(open_tickets),
                    "derivation": (
                        "Open tickets are compared with updated_at, or created_at when updated_at is absent; "
                        "records without timestamps are excluded and counted."
                    ),
                }
            ],
            recommendations=(
                ["Review candidates and use an approval-gated communication workflow for any follow-up."]
                if follow_up_candidates
                else ["No ticket met the explicit follow-up threshold in the available local records."]
            ),
        ),
        ReportSection(
            title="Lifecycle And Automation Evidence",
            summary=(
                f"{len(executions)} local execution records and explicit ticket lifecycle evidence "
                "were reviewed."
            ),
            findings=[
                {
                    "execution_count": len(executions),
                    "lifecycle": lifecycle,
                    "execution_status_counts": dict(
                        sorted(Counter(run.status.strip().lower() or "unknown" for run in executions).items())
                    ),
                }
            ],
            evidence=[
                {
                    "kind": "local_execution_records",
                    "client_id": client_id,
                    "period_start": period_start,
                    "period_end": period_end,
                    "record_count": len(executions),
                    "derivation": "Execution records are filtered by started_at and tenant scope.",
                },
                {
                    "kind": "ticket_status_history",
                    "client_id": client_id,
                    "period_start": period_start,
                    "period_end": period_end,
                    "derivation": (
                        "Only explicit locally recorded status transitions contribute to lifecycle metrics; "
                        "missing transitions are not inferred."
                    ),
                },
            ],
            recommendations=(
                ["Import explicit status transitions before using historical resolution duration."]
                if lifecycle.get("with_duration", 0) == 0 and period_tickets
                else []
            ),
        ),
    ]
    return sections, {
        "client_id": client_id,
        "period_start": period_start,
        "period_end": period_end,
        "follow_up_after_days": follow_up_after_days,
        "period_ticket_count": len(period_tickets),
        "current_open_ticket_count": len(open_tickets),
        "follow_up_candidate_count": len(follow_up_candidates),
        "execution_count": len(executions),
        "evidence_status": evidence_status,
        "scope": "single client",
        "claims_excluded": [
            "vendor_sla_compliance",
            "customer_sentiment",
            "contract_health",
            "measured_savings",
        ],
    }


def _successful_action_candidates(
    store: Store,
    estimates: dict[str, int],
    client_id: str,
    start: date,
    end: date,
) -> list[dict[str, Any]]:
    counts: Counter[str] = Counter()
    for run in store.list_smart_action_runs(client_id=client_id):
        if run.status not in {"success", "completed"} or not _in_period(run.created_at, start, end):
            continue
        counts[run.action_id] += 1
    candidates: list[dict[str, Any]] = [
        {
            "action_id": action_id,
            "successful_runs": count,
            "estimated_minutes_saved": count * int(estimates.get(action_id, 0)),
            "estimate": True,
            "candidate_reason": "Successful local action; review before creating a workflow.",
        }
        for action_id, count in counts.items()
    ]
    candidates.sort(key=lambda item: (-int(item["successful_runs"]), str(item["action_id"])))
    return candidates[:20]


def _period(period_start: str, period_end: str) -> tuple[date, date]:
    try:
        start = date.fromisoformat(period_start)
        end = date.fromisoformat(period_end)
    except ValueError as exc:
        raise ValueError("period_start and period_end must be ISO dates") from exc
    if end < start:
        raise ValueError("period_end must be on or after period_start")
    return start, end


def _in_period(value: str, start: date, end: date) -> bool:
    if not value:
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        return False
    return start <= parsed <= end


def _timestamp_date(value: str) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _bounded_ids(tickets: list[Ticket]) -> list[str]:
    return [ticket.id for ticket in tickets[:100]]


def _rate(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def _qbr_evidence_status(tickets: list[Ticket], executions: list[Any], historical: dict[str, Any]) -> str:
    if not tickets and not executions:
        return "no_evidence"
    if tickets and historical.get("with_duration", 0) == 0:
        return "partial"
    return "completed"
