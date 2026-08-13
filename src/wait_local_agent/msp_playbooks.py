"""Bounded, evidence-backed MSP playbooks built on existing WAIT primitives.

Playbooks are composition metadata plus a small coordinator. Individual work is
still performed by the existing workflow templates, smart actions, and report
service; this module does not create a second agent or provider engine.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from datetime import date
from typing import Any
from uuid import uuid4

from wait_local_agent.models import WorkflowRun
from wait_local_agent.reports.models import ReportType
from wait_local_agent.reports.msp import (
    build_automation_opportunity_report,
    build_qbr_report,
    build_recurring_service_review_report,
)
from wait_local_agent.reports.renderers import redact_text, redact_value
from wait_local_agent.reports.service import ReportService
from wait_local_agent.store import Store, _normalize_client_id
from wait_local_agent.workflows import (
    WorkflowToolExecutor,
    run_workflow_template,
    validate_workflow_input,
)

MAX_PLAYBOOK_PAYLOAD_FIELDS = 24
MAX_PLAYBOOK_PAYLOAD_BYTES = 12_000


@dataclass(frozen=True)
class MspPlaybookStep:
    id: str
    name: str
    kind: str
    description: str
    workflow_template_id: str | None = None
    report_type: str | None = None
    required_inputs: tuple[str, ...] = ()


@dataclass(frozen=True)
class MspPlaybookDefinition:
    id: str
    name: str
    version: int
    trigger: str
    description: str
    risk_level: str
    steps: tuple[MspPlaybookStep, ...]
    output_evidence: tuple[str, ...]
    local_fixture: bool = True


def _workflow_step(
    step_id: str,
    name: str,
    template_id: str,
    description: str,
    required_inputs: tuple[str, ...] = (),
) -> MspPlaybookStep:
    return MspPlaybookStep(
        id=step_id,
        name=name,
        kind="workflow",
        description=description,
        workflow_template_id=template_id,
        required_inputs=required_inputs,
    )


def _report_step(
    step_id: str,
    name: str,
    report_type: str,
    description: str,
) -> MspPlaybookStep:
    return MspPlaybookStep(
        id=step_id,
        name=name,
        kind="report",
        description=description,
        report_type=report_type,
        required_inputs=("period_start", "period_end"),
    )


MSP_PLAYBOOKS: tuple[MspPlaybookDefinition, ...] = (
    MspPlaybookDefinition(
        id="ticket-intake-review",
        name="Ticket Intake Review",
        version=1,
        trigger="ticket.created",
        description="Run bounded triage, quality, sentiment, duplicate, security, and escalation reviews.",
        risk_level="low",
        steps=(
            _workflow_step("triage", "Triage", "ticket-triage", "Classify and summarize the ticket."),
            _workflow_step("quality", "Quality", "ticket-quality-review", "Check required ticket fields."),
            _workflow_step("sentiment", "Sentiment", "ticket-sentiment-review", "Assess customer-facing language."),
            _workflow_step(
                "duplicates", "Duplicate candidates", "duplicate-ticket-review", "Find local duplicate candidates."
            ),
            _workflow_step(
                "security", "Security alert", "security-alert-review", "Assess bounded security indicators."
            ),
            _workflow_step("escalation", "Escalation", "ticket-escalation-review", "Recommend bounded urgency."),
        ),
        output_evidence=("workflow_run_ids", "local_ticket_records", "review_outputs"),
    ),
    MspPlaybookDefinition(
        id="resolution-review",
        name="Resolution Review",
        version=1,
        trigger="ticket.created",
        description="Prepare an L1 resolution and, when requested, a cited response for approval.",
        risk_level="medium",
        steps=(
            _workflow_step("triage", "Triage", "ticket-triage", "Classify the ticket before resolution review."),
            _workflow_step("l1", "L1 resolution", "l1-resolution-review", "Draft a technician-facing resolution."),
            _workflow_step(
                "response",
                "Documentation response",
                "documentation-assisted-response",
                "Prepare a cited response and stop for approval before delivery.",
            ),
        ),
        output_evidence=("workflow_run_ids", "citations", "approval_request_id"),
    ),
    MspPlaybookDefinition(
        id="dispatch-review",
        name="Dispatch Review",
        version=1,
        trigger="ticket.unassigned",
        description="Prepare a workload-aware technician recommendation for human approval.",
        risk_level="medium",
        steps=(
            _workflow_step(
                "dispatch",
                "Dispatch recommendation",
                "technician-dispatch-review",
                "Draft a bounded assignment recommendation.",
            ),
        ),
        output_evidence=("workflow_run_ids", "approval_request_id", "recommendation"),
    ),
    MspPlaybookDefinition(
        id="stale-sla-review",
        name="Stale and SLA Review",
        version=1,
        trigger="schedule.daily",
        description="Run stale-ticket and explicit-threshold SLA-risk reviews without inferring vendor contracts.",
        risk_level="low",
        steps=(
            _workflow_step(
                "stale",
                "Stale ticket sweep",
                "stale-ticket-sweep-review",
                "Find open tickets past an explicit age.",
                ("stale_after_minutes",),
            ),
            _workflow_step(
                "sla",
                "SLA risk",
                "ticket-sla-risk-review",
                "Compare age with operator-supplied thresholds.",
                ("thresholds_minutes",),
            ),
        ),
        output_evidence=("workflow_run_ids", "explicit_thresholds", "excluded_missing_timestamps"),
    ),
    MspPlaybookDefinition(
        id="security-response-review",
        name="Security Response Review",
        version=1,
        trigger="ticket.created",
        description="Assess security indicators, then prepare an approval-gated internal alert if needed.",
        risk_level="high",
        steps=(
            _workflow_step(
                "assessment", "Security assessment", "security-alert-review", "Assess indicators without side effects."
            ),
            _workflow_step("alert", "Internal alert", "p1-alert", "Prepare an approval-gated internal alert."),
        ),
        output_evidence=("workflow_run_ids", "security_indicators", "approval_request_id"),
    ),
    MspPlaybookDefinition(
        id="m365-onboarding-review",
        name="Microsoft 365 Onboarding Review",
        version=1,
        trigger="ticket.created",
        description="Prepare tenant-scoped user onboarding and stop before any approval-gated license change.",
        risk_level="high",
        steps=(
            _workflow_step(
                "user",
                "User creation",
                "m365-user-onboarding-review",
                "Prepare the tenant-scoped user request.",
                ("user_principal_name", "display_name", "mail_nickname", "temporary_vault_name"),
            ),
            _workflow_step(
                "license",
                "License request",
                "m365-license-request-review",
                "Prepare an immutable-SKU license request after approval.",
                ("user_id", "sku_ids", "operation"),
            ),
        ),
        output_evidence=("workflow_run_ids", "approval_request_id", "tenant_scope"),
    ),
    MspPlaybookDefinition(
        id="m365-offboarding-review",
        name="Microsoft 365 Offboarding Review",
        version=1,
        trigger="ticket.updated",
        description="Prepare a tenant-scoped disable-and-revoke request; no broad MFA reset is inferred.",
        risk_level="high",
        steps=(
            _workflow_step(
                "offboarding",
                "User offboarding",
                "m365-user-offboarding-review",
                "Prepare a bounded disable-and-revoke request.",
                ("user_identity", "user_id"),
            ),
        ),
        output_evidence=("workflow_run_ids", "approval_request_id", "partial_failure_state"),
    ),
    MspPlaybookDefinition(
        id="qbr-review",
        name="Quarterly Business Review",
        version=1,
        trigger="schedule.monthly",
        description="Build a client-scoped QBR from stored ticket and execution evidence; estimates stay labeled.",
        risk_level="low",
        steps=(_report_step("qbr", "QBR report", ReportType.QBR.value, "Persist a local evidence-backed QBR."),),
        output_evidence=("report_id", "ticket_records", "execution_records", "estimate_labels"),
    ),
    MspPlaybookDefinition(
        id="automation-opportunity-review",
        name="Automation Opportunity Review",
        version=1,
        trigger="schedule.monthly",
        description="Rank repeated successful local actions as review candidates without enabling automation.",
        risk_level="low",
        steps=(
            _report_step(
                "automation",
                "Automation opportunities",
                ReportType.AUTOMATION_OPPORTUNITY.value,
                "Persist a local candidate report.",
            ),
        ),
        output_evidence=("report_id", "successful_action_records", "estimate_labels"),
    ),
    MspPlaybookDefinition(
        id="recurring-service-review",
        name="Recurring Service Review",
        version=1,
        trigger="schedule.monthly",
        description="Build a client-scoped recurring service review with explicit follow-up thresholds.",
        risk_level="low",
        steps=(
            _report_step(
                "service",
                "Service review",
                ReportType.RECURRING_SERVICE_REVIEW.value,
                "Persist a local service posture report.",
            ),
        ),
        output_evidence=("report_id", "ticket_records", "lifecycle_evidence", "follow_up_threshold"),
    ),
)


def list_msp_playbooks() -> list[MspPlaybookDefinition]:
    return list(MSP_PLAYBOOKS)


def get_msp_playbook(playbook_id: str) -> MspPlaybookDefinition | None:
    return next((item for item in MSP_PLAYBOOKS if item.id == playbook_id), None)


def playbook_view(playbook: MspPlaybookDefinition) -> dict[str, object]:
    return asdict(playbook)


def preview_msp_playbook(
    store: Store,
    playbook_id: str,
    *,
    ticket_id: str | None = None,
    client_id: str | None = None,
    input_payload: Mapping[str, object] | None = None,
) -> dict[str, object]:
    playbook = _required_playbook(playbook_id)
    payload = _bounded_playbook_payload(input_payload)
    effective_client_id = _validate_scope_and_ticket(store, playbook, ticket_id, client_id)
    steps = _preview_steps(playbook, payload)
    return {
        "format": "wait-local-agent.msp-playbook-preview",
        "format_version": 1,
        "execution_started": False,
        "execution_mode": "preview",
        "playbook": playbook_view(playbook),
        "ticket_id": ticket_id,
        "client_id": effective_client_id,
        "input": payload,
        "steps": steps,
        "approval_required": any(bool(step["approval_required"]) for step in steps),
        "unsupported": _unsupported_playbook_outputs(playbook),
    }


def run_msp_playbook(
    store: Store,
    playbook_id: str,
    *,
    ticket_id: str | None = None,
    client_id: str | None = None,
    actor: str = "playbook",
    trigger_source: str = "msp_playbook",
    input_payload: Mapping[str, object] | None = None,
    tool_executor: WorkflowToolExecutor | None = None,
    smart_action_service: Any | None = None,
    on_workflow_run: Callable[[WorkflowRun], None] | None = None,
) -> dict[str, object]:
    """Execute a playbook sequentially and stop at the first gate or failure."""

    playbook = _required_playbook(playbook_id)
    payload = _bounded_playbook_payload(input_payload)
    effective_client_id = _validate_scope_and_ticket(store, playbook, ticket_id, client_id)
    # Validate every step before creating an approval or audit record. A later
    # step must not fail only after an earlier high-risk step has been staged.
    _preview_steps(playbook, payload)
    run_id = f"playbook-{uuid4().hex}"
    subject_id = f"{playbook.id}:{ticket_id or effective_client_id or 'scope'}"
    store.add_audit_event(
        "msp.playbook.started",
        subject_id,
        f"{playbook.id} version {playbook.version} run {run_id}",
        client_id=effective_client_id,
    )
    results: list[dict[str, object]] = []
    status = "completed"
    stopped_after_step: str | None = None
    try:
        for step in playbook.steps:
            if step.kind == "workflow":
                if ticket_id is None or step.workflow_template_id is None:  # pragma: no cover - catalog invariant
                    raise ValueError(f"playbook step {step.id} requires a ticket")
                workflow_run = run_workflow_template(
                    store,
                    step.workflow_template_id,
                    ticket_id,
                    client_id=effective_client_id,
                    actor=actor,
                    trigger_source=trigger_source,
                    tool_executor=tool_executor,
                    template_version=playbook.version,
                    input_payload=payload,
                )
                if on_workflow_run is not None:
                    on_workflow_run(workflow_run)
                step_result: dict[str, object] = {
                    "id": step.id,
                    "kind": step.kind,
                    "status": workflow_run.status,
                    "workflow_run_id": workflow_run.id,
                    "approval_request_id": workflow_run.approval_request_id,
                    "message": redact_text(workflow_run.message),
                }
                results.append(step_result)
                if workflow_run.status != "completed":
                    status = workflow_run.status
                    stopped_after_step = step.id
                    break
                continue
            report = _run_report_step(
                store,
                step,
                payload,
                effective_client_id,
                actor,
                smart_action_service,
            )
            results.append(
                {
                    "id": step.id,
                    "kind": step.kind,
                    "status": "completed",
                    "report_id": report.id,
                    "report_type": report.report_type.value,
                    "evidence_status": report.evidence_status,
                }
            )
    except Exception as exc:  # noqa: BLE001 - preserve a bounded failed playbook result.
        status = "failed"
        stopped_after_step = stopped_after_step or (
            playbook.steps[len(results)].id if len(results) < len(playbook.steps) else None
        )
        results.append(
            {
                "id": stopped_after_step,
                "kind": "error",
                "status": "failed",
                "error": redact_text(str(exc))[:240] or exc.__class__.__name__,
            }
        )
    store.add_audit_event(
        "msp.playbook.completed" if status == "completed" else "msp.playbook.stopped",
        subject_id,
        f"{playbook.id} version {playbook.version} run {run_id} status={status}",
        client_id=effective_client_id,
    )
    return {
        "format": "wait-local-agent.msp-playbook-run",
        "format_version": 1,
        "run_id": run_id,
        "execution_started": True,
        "execution_mode": "controlled_local",
        "playbook_id": playbook.id,
        "playbook_version": playbook.version,
        "output_evidence": list(playbook.output_evidence),
        "ticket_id": ticket_id,
        "client_id": effective_client_id,
        "status": status,
        "stopped_after_step": stopped_after_step,
        "steps": results,
        "unsupported": _unsupported_playbook_outputs(playbook),
    }


def _required_playbook(playbook_id: str) -> MspPlaybookDefinition:
    playbook = get_msp_playbook(playbook_id)
    if playbook is None:
        raise KeyError(playbook_id)
    return playbook


def _bounded_playbook_payload(value: Mapping[str, object] | None) -> dict[str, object]:
    payload = dict(value or {})
    if len(payload) > MAX_PLAYBOOK_PAYLOAD_FIELDS:
        raise ValueError(f"playbook input may contain at most {MAX_PLAYBOOK_PAYLOAD_FIELDS} fields")
    safe = redact_value(payload)
    try:
        encoded = json.dumps(safe, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise ValueError("playbook input must contain JSON-compatible values") from exc
    if len(encoded.encode("utf-8")) > MAX_PLAYBOOK_PAYLOAD_BYTES:
        raise ValueError(f"playbook input must be at most {MAX_PLAYBOOK_PAYLOAD_BYTES} bytes")
    return safe


def _validate_scope_and_ticket(
    store: Store,
    playbook: MspPlaybookDefinition,
    ticket_id: str | None,
    client_id: str | None,
) -> str | None:
    normalized_client_id = _normalize_client_id(client_id)
    needs_ticket = any(step.kind == "workflow" for step in playbook.steps)
    if needs_ticket and not ticket_id:
        raise ValueError("this playbook requires ticket_id")
    if ticket_id:
        ticket = store.get_ticket(ticket_id, client_id=normalized_client_id)
        if ticket is None:
            raise LookupError(ticket_id)
        if (
            normalized_client_id is not None and ticket.client_id != normalized_client_id
        ):  # pragma: no cover - scoped lookup
            raise LookupError(ticket_id)
        return normalized_client_id or ticket.client_id
    if not normalized_client_id:
        raise ValueError("report playbooks require client_id")
    return normalized_client_id


def _preview_steps(playbook: MspPlaybookDefinition, payload: dict[str, object]) -> list[dict[str, object]]:
    steps: list[dict[str, object]] = []
    for step in playbook.steps:
        if step.kind == "workflow":
            if step.workflow_template_id is None:  # pragma: no cover - catalog invariant
                raise ValueError(f"playbook step {step.id} has no workflow template")
            validate_workflow_input(step.workflow_template_id, payload)
            from wait_local_agent.workflows import get_workflow_template

            template = get_workflow_template(step.workflow_template_id)
            if template is None:  # pragma: no cover - catalog invariant
                raise KeyError(step.workflow_template_id)
            steps.append(
                {
                    "id": step.id,
                    "name": step.name,
                    "kind": step.kind,
                    "workflow_template_id": step.workflow_template_id,
                    "approval_required": template.approval_required,
                    "risk_level": template.risk_level,
                    "tool_id": template.tool_id,
                    "required_inputs": list(step.required_inputs),
                    "status": "planned",
                }
            )
        else:
            _validate_report_input(step, payload)
            steps.append(
                {
                    "id": step.id,
                    "name": step.name,
                    "kind": step.kind,
                    "report_type": step.report_type,
                    "approval_required": False,
                    "risk_level": playbook.risk_level,
                    "required_inputs": list(step.required_inputs),
                    "status": "planned",
                }
            )
    return steps


def _validate_report_input(step: MspPlaybookStep, payload: Mapping[str, object]) -> None:
    period_start = payload.get("period_start")
    period_end = payload.get("period_end")
    if not isinstance(period_start, str) or not isinstance(period_end, str):
        raise ValueError(f"playbook step {step.id} requires period_start and period_end")
    try:
        start = date.fromisoformat(period_start)
        end = date.fromisoformat(period_end)
    except ValueError as exc:
        raise ValueError("period_start and period_end must be ISO dates") from exc
    if start > end:
        raise ValueError("period_start must not be after period_end")
    if step.report_type == ReportType.RECURRING_SERVICE_REVIEW.value:
        follow_up = payload.get("follow_up_after_days", 14)
        if isinstance(follow_up, bool) or not isinstance(follow_up, int) or not 1 <= follow_up <= 90:
            raise ValueError("follow_up_after_days must be an integer between 1 and 90")


def _run_report_step(
    store: Store,
    step: MspPlaybookStep,
    payload: Mapping[str, object],
    client_id: str | None,
    actor: str,
    smart_action_service: Any | None,
):
    if client_id is None or step.report_type is None:  # pragma: no cover - validated catalog and scope
        raise ValueError(f"playbook step {step.id} requires a client scope and report type")
    _validate_report_input(step, payload)
    estimates = {}
    if smart_action_service is not None:
        estimates = {manifest.action_id: manifest.estimated_minutes_saved for manifest in smart_action_service.list()}
    period_start = str(payload["period_start"])
    period_end = str(payload["period_end"])
    report_type = ReportType(step.report_type)
    if report_type is ReportType.QBR:
        sections, metadata = build_qbr_report(
            store, estimates, client_id=client_id, period_start=period_start, period_end=period_end
        )
        title = f"Quarterly business review — {client_id}"
    elif report_type is ReportType.AUTOMATION_OPPORTUNITY:
        sections, metadata = build_automation_opportunity_report(
            store, estimates, client_id=client_id, period_start=period_start, period_end=period_end
        )
        title = f"Automation opportunities — {client_id}"
    else:
        follow_up_after_days = payload.get("follow_up_after_days", 14)
        if isinstance(follow_up_after_days, bool) or not isinstance(
            follow_up_after_days, int
        ):  # pragma: no cover - preview validates
            raise ValueError("follow_up_after_days must be an integer between 1 and 90")
        sections, metadata = build_recurring_service_review_report(
            store,
            client_id=client_id,
            period_start=period_start,
            period_end=period_end,
            follow_up_after_days=follow_up_after_days,
        )
        title = f"Recurring service review — {client_id}"
    return ReportService(store).create_report(
        report_type,
        title,
        sections,
        created_by=actor or "playbook",
        client_id=client_id,
        metadata=metadata,
    )


def _unsupported_playbook_outputs(playbook: MspPlaybookDefinition) -> list[str]:
    return [
        "live_provider_success",
        "vendor_sla_compliance",
        "measured_time_savings",
        "automatic_ticket_merge_or_close",
    ]
