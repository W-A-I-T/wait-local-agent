from __future__ import annotations

from wait_local_agent.models import Ticket, WorkflowRun, WorkflowTemplate
from wait_local_agent.services import classify_ticket
from wait_local_agent.store import Store

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
) -> WorkflowRun:
    template = get_workflow_template(template_id)
    if template is None:
        raise KeyError(template_id)
    ticket = store.get_ticket(ticket_id)
    if ticket is None:
        raise LookupError(ticket_id)

    message = _workflow_message(template, ticket)
    approval_request_id = None
    status = "completed"
    if template.approval_required:
        approval = store.create_approval_request(
            ticket_id,
            template.action_type,
            {
                "template_id": template.id,
                "ticket_id": ticket.id,
                "message": message,
            },
            client_id=client_id,
        )
        approval_request_id = approval.id
        status = "pending_approval"

    return store.create_workflow_run(
        template_id=template.id,
        ticket_id=ticket.id,
        status=status,
        message=message,
        approval_request_id=approval_request_id,
        client_id=client_id,
    )


def _workflow_message(template: WorkflowTemplate, ticket: Ticket) -> str:
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
