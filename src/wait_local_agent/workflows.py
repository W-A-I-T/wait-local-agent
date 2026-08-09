from __future__ import annotations

import json
from typing import Protocol

from wait_local_agent.models import Ticket, WorkflowRun, WorkflowTemplate
from wait_local_agent.observability import ExecutionRecorder, StepRecord
from wait_local_agent.reports.renderers import redact_text, redact_value
from wait_local_agent.services import classify_ticket
from wait_local_agent.smart_actions import ActionResult
from wait_local_agent.store import Store, _normalize_client_id

MAX_WORKFLOW_PAYLOAD_FIELDS = 16
MAX_WORKFLOW_PAYLOAD_BYTES = 8_000


class WorkflowToolExecutor(Protocol):
    def invoke(
        self,
        action_id: str,
        payload: dict[str, object],
        actor: str | None,
        *,
        confirm: bool = False,
        client_id: str | None = None,
    ) -> ActionResult:
        """Run one existing smart action inside a workflow boundary."""

WORKFLOW_TEMPLATES: tuple[WorkflowTemplate, ...] = (
    WorkflowTemplate(
        id="ticket-triage",
        name="Ticket Triage",
        trigger="ticket.created",
        description="Classify the ticket and prepare a technician-readable summary.",
        action_type="ticket.triage",
        approval_required=False,
        risk_level="low",
        preview_fields=("classification", "summary"),
    ),
    WorkflowTemplate(
        id="assign-technician",
        name="Assign Technician",
        trigger="ticket.unassigned",
        description="Draft an assignment based on priority, workload placeholders, and skills.",
        action_type="ticket.assign",
        approval_required=True,
        risk_level="medium",
        preview_fields=("ticket_id", "technician_id", "team_id"),
    ),
    WorkflowTemplate(
        id="inactive-ticket-follow-up",
        name="Inactive Ticket Follow-up",
        trigger="schedule.daily",
        description="Find stale tickets and draft a safe client or internal follow-up.",
        action_type="ticket.follow_up",
        approval_required=True,
        risk_level="medium",
        preview_fields=("ticket_id", "message"),
    ),
    WorkflowTemplate(
        id="p1-alert",
        name="P1 Alert",
        trigger="ticket.priority_changed",
        description="Detect urgent tickets and prepare an internal alert payload.",
        action_type="ticket.alert",
        approval_required=True,
        risk_level="high",
        preview_fields=("ticket_id", "priority", "message"),
    ),
    WorkflowTemplate(
        id="documentation-assisted-response",
        name="Documentation-assisted Response",
        trigger="ticket.created",
        description="Use cited local knowledge to draft a client-safe response.",
        action_type="ticket.draft_response",
        approval_required=True,
        risk_level="medium",
        preview_fields=("ticket_id", "response", "sources"),
    ),
    WorkflowTemplate(
        id="l1-resolution-review",
        name="L1 Resolution Review",
        trigger="ticket.created",
        description=(
            "Draft a cited, technician-facing L1 resolution suggestion from "
            "local knowledge; no ticket mutation is performed."
        ),
        action_type="ticket.l1_resolution",
        approval_required=False,
        risk_level="low",
        preview_fields=("ticket_id", "suggestion", "citations"),
        tool_id="suggest-resolution",
    ),
    WorkflowTemplate(
        id="ticket-quality-review",
        name="Ticket Quality Review",
        trigger="ticket.created",
        description="Check required ticket fields and controlled priority/status values.",
        action_type="ticket.quality",
        approval_required=False,
        risk_level="low",
        preview_fields=("ticket_id", "quality_score", "issues"),
        tool_id="ticket-quality",
    ),
    WorkflowTemplate(
        id="ticket-sentiment-review",
        name="Ticket Sentiment Review",
        trigger="ticket.updated",
        description="Assess customer-facing language and flag bounded escalation signals.",
        action_type="ticket.sentiment",
        approval_required=False,
        risk_level="low",
        preview_fields=("ticket_id", "sentiment", "score", "escalation_signal"),
        tool_id="ticket-sentiment",
    ),
    WorkflowTemplate(
        id="ticket-escalation-review",
        name="Ticket Escalation Review",
        trigger="ticket.priority_changed",
        description="Recommend a bounded urgency and next step without changing the ticket.",
        action_type="ticket.escalation",
        approval_required=False,
        risk_level="low",
        preview_fields=("ticket_id", "urgency", "recommendation"),
        tool_id="ticket-escalation",
    ),
    WorkflowTemplate(
        id="security-alert-review",
        name="Security Alert Review",
        trigger="ticket.created",
        description=(
            "Detect bounded security-alert indicators and route the ticket to "
            "human security handling without taking side effects."
        ),
        action_type="ticket.security_alert",
        approval_required=False,
        risk_level="low",
        preview_fields=("ticket_id", "security_signal", "severity", "indicators", "recommendation"),
        tool_id="security-alert-assessment",
    ),
    WorkflowTemplate(
        id="similar-ticket-review",
        name="Similar Ticket Review",
        trigger="ticket.created",
        description="Rank local tickets by deterministic subject and body overlap for technician review.",
        action_type="ticket.similar",
        approval_required=False,
        risk_level="low",
        preview_fields=("ticket_id", "matches"),
        tool_id="find-similar-tickets",
    ),
    WorkflowTemplate(
        id="duplicate-ticket-review",
        name="Duplicate Ticket Review",
        trigger="ticket.created",
        description=(
            "Find deterministic local candidate duplicates for technician review; "
            "this workflow never merges or closes tickets."
        ),
        action_type="ticket.duplicate_review",
        approval_required=False,
        risk_level="low",
        preview_fields=("ticket_id", "matches"),
        tool_id="find-similar-tickets",
    ),
    WorkflowTemplate(
        id="technician-dispatch-review",
        name="Technician Dispatch Review",
        trigger="ticket.unassigned",
        description=(
            "Draft a workload-aware technician recommendation for human approval; "
            "the workflow never assigns a technician by itself."
        ),
        action_type="ticket.assign",
        approval_required=True,
        risk_level="medium",
        preview_fields=("ticket_id", "recommendation", "approved"),
        tool_id="dispatch-suggestion",
    ),
    WorkflowTemplate(
        id="ticket-sla-risk-review",
        name="Ticket SLA Risk Review",
        trigger="schedule.daily",
        description=(
            "Compare ticket age with explicit operator-supplied thresholds and "
            "report evidence-backed SLA risk without inferring a vendor contract."
        ),
        action_type="ticket.sla_assessment",
        approval_required=False,
        risk_level="low",
        preview_fields=("ticket_id", "assessment", "evidence_status"),
        tool_id="ticket-sla-assessment",
        payload_schema={
            "type": "object",
            "required": ["thresholds_minutes"],
            "properties": {"thresholds_minutes": "object of priority to positive minutes"},
        },
    ),
    WorkflowTemplate(
        id="stale-ticket-sweep-review",
        name="Stale Ticket Sweep Review",
        trigger="schedule.daily",
        description=(
            "Find open local tickets older than an explicit threshold; missing "
            "timestamps are excluded and reported."
        ),
        action_type="ticket.stale_sweep",
        approval_required=False,
        risk_level="low",
        preview_fields=("tickets", "count", "excluded_missing_timestamp"),
        tool_id="stale-ticket-sweep",
        payload_schema={
            "type": "object",
            "required": ["stale_after_minutes"],
            "properties": {"stale_after_minutes": "positive integer"},
        },
    ),
    WorkflowTemplate(
        id="m365-user-onboarding-review",
        name="Microsoft 365 User Onboarding Review",
        trigger="ticket.created",
        description=(
            "Prepare a tenant-scoped Microsoft 365 user creation request from a ticket; "
            "the existing admin approval and local-vault credential path remains required."
        ),
        action_type="m365.user_onboarding",
        approval_required=True,
        risk_level="high",
        preview_fields=("user_principal_name", "display_name", "mail_nickname", "approval_required"),
        tool_id="m365-user-onboarding",
        payload_schema={
            "type": "object",
            "required": [
                "user_principal_name",
                "display_name",
                "mail_nickname",
                "temporary_vault_name",
            ],
            "properties": {
                "user_principal_name": "string",
                "display_name": "string",
                "mail_nickname": "string",
                "temporary_vault_name": "local vault key name",
                "account_enabled": "boolean",
                "force_change_password_next_sign_in": "boolean",  # nosec B105 - schema descriptor
            },
        },
    ),
    WorkflowTemplate(
        id="m365-user-offboarding-review",
        name="Microsoft 365 User Offboarding Review",
        trigger="ticket.updated",
        description=(
            "Prepare a tenant-scoped Microsoft 365 disable-and-revoke request; "
            "the existing admin approval and partial-failure reporting remain required."
        ),
        action_type="m365.user_offboarding",
        approval_required=True,
        risk_level="high",
        preview_fields=("user_identity", "user_id", "approval_required"),
        tool_id="m365-user-offboarding",
        payload_schema={
            "type": "object",
            "required": ["user_identity", "user_id"],
            "properties": {"user_identity": "string", "user_id": "immutable directory ID"},
        },
    ),
    WorkflowTemplate(
        id="m365-license-request-review",
        name="Microsoft 365 License Request Review",
        trigger="ticket.created",
        description=(
            "Prepare an approval-gated Microsoft 365 license add or removal request "
            "using immutable user and SKU IDs."
        ),
        action_type="m365.license_request",
        approval_required=True,
        risk_level="high",
        preview_fields=("operation", "user_id", "sku_ids", "approval_required"),
        tool_id="m365-license-change",
        payload_schema={
            "type": "object",
            "required": ["user_id", "sku_ids", "operation"],
            "properties": {
                "user_id": "immutable directory ID",
                "sku_ids": "array of immutable license SKU IDs",
                "operation": "add or remove",
            },
        },
    ),
)


def list_workflow_templates() -> list[WorkflowTemplate]:
    return list(WORKFLOW_TEMPLATES)


def get_workflow_template(template_id: str) -> WorkflowTemplate | None:
    return next((template for template in WORKFLOW_TEMPLATES if template.id == template_id), None)


def run_workflow_template(
    store: Store,
    template_id: str,
    ticket_id: str,
    *,
    client_id: str | None = None,
    actor: str = "",
    trigger_source: str = "workflow",
    tool_executor: WorkflowToolExecutor | None = None,
    template_override: WorkflowTemplate | None = None,
    operator_instructions: str = "",
    template_version: int | None = None,
    input_payload: dict[str, object] | None = None,
) -> WorkflowRun:
    template = template_override or get_workflow_template(template_id)
    if template is None:
        raise KeyError(template_id)
    normalized_client_id = _normalize_client_id(client_id)
    ticket = store.get_ticket(ticket_id, client_id=normalized_client_id)
    if ticket is None:
        raise LookupError(ticket_id)
    effective_client_id = normalized_client_id if normalized_client_id is not None else ticket.client_id
    bounded_payload = _bounded_workflow_payload(
        template,
        {} if input_payload is None else input_payload,
    )

    tool_result = _run_template_tool(
        template,
        ticket,
        tool_executor,
        actor=actor,
        client_id=effective_client_id,
        input_payload=bounded_payload,
    )
    message = _workflow_message(template, ticket, tool_result)
    safe_instructions = redact_text(operator_instructions).strip()
    if safe_instructions:
        message = f"{message} Operator instructions: {safe_instructions}"
    approval_request_id = None
    status = "completed"
    if tool_result is not None:
        status = _workflow_status_for_tool(tool_result)
        approval_request_id = tool_result.approval_id
    elif template.approval_required:
        approval = store.create_approval_request(
            ticket_id,
            template.action_type,
            {
                "template_id": template.id,
                "ticket_id": ticket.id,
                "message": message,
            },
            client_id=effective_client_id,
        )
        approval_request_id = approval.id
        status = "pending_approval"

    run = store.create_workflow_run(
        template_id=template.id,
        ticket_id=ticket.id,
        status=status,
        message=message,
        approval_request_id=approval_request_id,
        client_id=effective_client_id,
        template_version=template_version,
    )
    _record_workflow_execution(store, run, actor=actor, trigger_source=trigger_source)
    return run


def _record_workflow_execution(
    store: Store,
    run: WorkflowRun,
    *,
    actor: str,
    trigger_source: str,
) -> None:
    """Record the run for observability; never changes the run outcome."""
    step = StepRecord(
        kind="workflow.template",
        name=run.template_id,
        status=run.status,
        input={"template_id": run.template_id, "ticket_id": run.ticket_id},
        output={
            "message": run.message,
            "approval_request_id": run.approval_request_id,
            "template_version": run.template_version,
        },
    )
    ExecutionRecorder(store).record_execution(
        run_kind="workflow",
        source_run_id=run.id,
        actor=actor,
        status=run.status,
        trigger_source=trigger_source,
        client_id=run.client_id,
        steps=(step,),
    )


def _workflow_message(
    template: WorkflowTemplate,
    ticket: Ticket,
    tool_result: ActionResult | None = None,
) -> str:
    if tool_result is not None:
        if tool_result.status == "success":
            return f"Completed {template.name.lower()} for {ticket.id}."
        detail = redact_text(tool_result.error_detail).strip()
        suffix = f": {detail}" if detail else "."
        return f"{template.name} for {ticket.id} {tool_result.status}{suffix}"
    if template.id == "ticket-triage":
        return f"Classified {ticket.id} as {classify_ticket(ticket.subject, ticket.body)}."
    if template.id == "assign-technician":
        return (
            f"Drafted technician assignment for {ticket.id}; "
            "approval required before PSA update."
        )
    if template.id == "inactive-ticket-follow-up":
        return (
            f"Drafted inactive ticket follow-up for {ticket.id}; "
            "approval required before sending."
        )
    if template.id == "p1-alert":
        return f"Prepared priority alert for {ticket.id}; approval required before notification."
    return (
        f"Drafted documentation-assisted response for {ticket.id}; "
        "approval required before posting."
    )


def _run_template_tool(
    template: WorkflowTemplate,
    ticket: Ticket,
    tool_executor: WorkflowToolExecutor | None,
    *,
    actor: str,
    client_id: str | None,
    input_payload: dict[str, object],
) -> ActionResult | None:
    if template.tool_id is None:
        return None
    if tool_executor is None:
        raise RuntimeError(f"workflow tool {template.tool_id} is not configured")
    payload = dict(input_payload)
    payload["ticket_id"] = ticket.id
    return tool_executor.invoke(
        template.tool_id,
        payload,
        actor or "workflow",
        client_id=client_id,
    )


def _bounded_workflow_payload(
    template: WorkflowTemplate,
    payload: dict[str, object],
) -> dict[str, object]:
    if not isinstance(payload, dict):
        raise ValueError("workflow payload must be a JSON object")
    if len(payload) > MAX_WORKFLOW_PAYLOAD_FIELDS:
        raise ValueError(
            f"workflow payload may contain at most {MAX_WORKFLOW_PAYLOAD_FIELDS} fields"
        )
    safe_payload = redact_value(payload)
    try:
        encoded = json.dumps(safe_payload, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise ValueError("workflow payload must contain JSON-compatible values") from exc
    if len(encoded.encode("utf-8")) > MAX_WORKFLOW_PAYLOAD_BYTES:
        raise ValueError(
            f"workflow payload must be at most {MAX_WORKFLOW_PAYLOAD_BYTES} bytes"
        )
    required = template.payload_schema.get("required", [])
    if isinstance(required, list):
        missing = [field for field in required if isinstance(field, str) and field not in safe_payload]
        if missing:
            raise ValueError(f"workflow payload is missing required field(s): {', '.join(missing)}")
    if template.id == "ticket-sla-risk-review":
        thresholds = safe_payload.get("thresholds_minutes")
        if not isinstance(thresholds, dict) or not thresholds:
            raise ValueError("thresholds_minutes must map priorities to positive minutes")
        if any(
            not isinstance(priority, str)
            or not priority.strip()
            or isinstance(minutes, bool)
            or not isinstance(minutes, int)
            or minutes <= 0
            for priority, minutes in thresholds.items()
        ):
            raise ValueError("thresholds_minutes must map priorities to positive minutes")
    elif template.id == "stale-ticket-sweep-review":
        threshold = safe_payload.get("stale_after_minutes")
        if isinstance(threshold, bool) or not isinstance(threshold, int) or threshold <= 0:
            raise ValueError("stale_after_minutes must be a positive integer")
    return safe_payload


def _workflow_status_for_tool(result: ActionResult) -> str:
    if result.status == "success":
        return "completed"
    if result.status == "pending_approval":
        return "pending_approval"
    return "failed"
