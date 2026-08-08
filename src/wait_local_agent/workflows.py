from __future__ import annotations

from typing import Protocol

from wait_local_agent.models import Ticket, WorkflowRun, WorkflowTemplate
from wait_local_agent.observability import ExecutionRecorder, StepRecord
from wait_local_agent.reports.renderers import redact_text
from wait_local_agent.services import classify_ticket
from wait_local_agent.smart_actions import ActionResult
from wait_local_agent.store import Store


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
) -> WorkflowRun:
    template = get_workflow_template(template_id)
    if template is None:
        raise KeyError(template_id)
    ticket = store.get_ticket(ticket_id)
    if ticket is None:
        raise LookupError(ticket_id)
    effective_client_id = client_id if client_id is not None else ticket.client_id

    tool_result = _run_template_tool(
        template,
        ticket,
        tool_executor,
        actor=actor,
        client_id=effective_client_id,
    )
    message = _workflow_message(template, ticket, tool_result)
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
) -> ActionResult | None:
    if template.tool_id is None:
        return None
    if tool_executor is None:
        raise RuntimeError(f"workflow tool {template.tool_id} is not configured")
    return tool_executor.invoke(
        template.tool_id,
        {"ticket_id": ticket.id},
        actor or "workflow",
        client_id=client_id,
    )


def _workflow_status_for_tool(result: ActionResult) -> str:
    if result.status == "success":
        return "completed"
    if result.status == "pending_approval":
        return "pending_approval"
    return "failed"
