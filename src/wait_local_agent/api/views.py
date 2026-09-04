"""Shared serialization and execution views for API routes."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import asdict
from typing import Any, cast

from fastapi import HTTPException

from wait_local_agent.agents import AgentDefinitionError, AgentService
from wait_local_agent.config import (
    Settings,
)
from wait_local_agent.event_dispatch import EventDispatcher
from wait_local_agent.halopsa import HaloPSAClient
from wait_local_agent.m365_graph import (
    M365GraphClient,
)
from wait_local_agent.models import (
    WorkflowRun,
)
from wait_local_agent.observability import (
    APPROVAL_RATE_DERIVATION,
    ESTIMATED_MINUTES_SAVED_DERIVATION,
    MODEL_COST_DERIVATION,
    TICKET_LIFECYCLE_DERIVATION,
    TICKET_METRICS_DERIVATION,
)
from wait_local_agent.power_platform import (
    resolve_pac_executable,
)
from wait_local_agent.reports.renderers import redact_text, redact_value
from wait_local_agent.smart_actions import SmartActionService
from wait_local_agent.store import (
    Store,
    _normalize_client_id,
)
from wait_local_agent.teams_graph import TeamsGraphClient
from wait_local_agent.technician_chat import TechnicianChatParseError, parse_technician_message

_TERMINAL_EXECUTION_STATUSES = frozenset({"succeeded", "verified", "unverified", "submitted"})
_EXECUTING_EXECUTION_STATUS = "running"

def make_approval_view(
    *,
    store: Store,
    active_settings: Settings,
    halopsa_client: HaloPSAClient,
    m365_client: M365GraphClient,
    teams_client: TeamsGraphClient,
) -> Callable[[Any], dict[str, object]]:
    def _approval_view(request) -> dict[str, object]:
        payload = _safe_json_object(request.payload_json)
        workflow_run = store.get_workflow_run_for_approval(request.id) if request.id is not None else None
        can_execute, block_reason = _approval_execution_state(request)
        view = asdict(request)
        view["payload_json"] = _redact_json_text(request.payload_json)
        view["execution_result_json"] = _redact_json_text(request.execution_result_json)
        view["comment"] = redact_text(request.comment)
        view["payload"] = _redact_payload(payload)
        view["output"] = _safe_redacted_json_object(request.execution_result_json)
        return {
            **view,
            "can_execute": can_execute,
            "block_reason": block_reason,
            "workflow_run_id": workflow_run.id if workflow_run is not None else None,
        }

    def _approval_execution_state(request) -> tuple[bool, str]:
        if request.action_type == "power_platform.solution_stage":
            if request.status != "approved":
                return False, "Approval must be approved before execution."
            if request.execution_status == _EXECUTING_EXECUTION_STATUS:
                return False, "Approval request is currently executing."
            if request.execution_status in _TERMINAL_EXECUTION_STATUSES:
                return False, "Approval request has already executed successfully."
            if not active_settings.allow_write_actions:
                return False, "Power Platform execution is blocked until WAIT_ALLOW_WRITE_ACTIONS=true."
            if not active_settings.allow_power_platform_deployment:
                return False, ("Power Platform deployment is blocked until WAIT_ALLOW_POWER_PLATFORM_DEPLOYMENT=true.")
            if resolve_pac_executable(active_settings) is None:
                if active_settings.pac_path is not None:
                    return False, "WAIT_PAC_PATH is configured but is not an executable regular file."
                return False, "The pac executable is not available on the local PATH."
            if not active_settings.power_platform_workspace.expanduser().is_dir():
                return False, "WAIT_POWER_PLATFORM_WORKSPACE must already exist."
            return True, ""
        if request.action_type == "teams.message.send":
            if request.status != "approved":
                return False, "Approval must be approved before execution."
            if request.execution_status == "succeeded":
                return False, "Approval request has already executed successfully."
            write_health = teams_client.write_health()
            if write_health.status != "ready":
                return False, write_health.message
            return True, ""
        if request.action_type.startswith("m365."):
            if request.status != "approved":
                return False, "Approval must be approved before execution."
            if request.execution_status == "succeeded":
                return False, "Approval request has already executed successfully."
            write_health = m365_client.write_health()
            if write_health.status != "ready":
                return False, write_health.message
            return True, ""
        if not request.action_type.startswith("halopsa."):
            return False, "Only HaloPSA approvals have live execution in this release."
        if request.status != "approved":
            return False, "Approval must be approved before execution."
        if request.execution_status in {"succeeded", "verified", "unverified", "submitted"}:
            return False, "Approval request has already executed successfully."
        if not hasattr(halopsa_client, "write_health"):
            return False, "HaloPSA write health is unavailable."
        write_health = halopsa_client.write_health()
        if write_health.status != "ready":
            return False, write_health.message
        return True, ""
    return _approval_view

def _scheduled_job_view(job) -> dict[str, object]:
    return {
        "id": job.id,
        "job_kind": job.job_kind,
        "template_id": job.template_id,
        "playbook_id": job.template_id if job.job_kind == "playbook" else None,
        "agent_id": job.agent_id,
        "entity_id": job.entity_id,
        "cron": job.cron,
        "schedule_type": job.schedule_type,
        "interval_seconds": job.interval_seconds,
        "run_at": job.run_at,
        "timezone": job.timezone,
        "paused": job.paused,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
        "client_id": job.client_id,
        "next_run_at": job.next_run_at,
        "params": _safe_json_object(job.params_json),
    }

def _baseline_view(baseline) -> dict[str, object]:
    """Decode the safe normalized baseline fields for API and UI consumers."""

    try:
        source_coverage = json.loads(baseline.source_coverage_json)
    except (TypeError, json.JSONDecodeError):
        source_coverage = {}
    try:
        summary = json.loads(baseline.summary_json)
    except (TypeError, json.JSONDecodeError):
        summary = {}
    try:
        sections = json.loads(baseline.sections_json)
    except (TypeError, json.JSONDecodeError):
        sections = {}
    return {
        "baseline_id": baseline.baseline_id,
        "client_id": baseline.client_id,
        "version": baseline.version,
        "generated_at": baseline.generated_at,
        "accepted": baseline.accepted,
        "source_coverage": source_coverage,
        "summary": summary,
        "sections": sections,
    }


def _smart_action_run_view(run) -> dict[str, object]:
    output = redact_value(_safe_json_object(run.output_json))
    evidence = redact_value(_safe_json_list(run.evidence_json))
    return {
        "id": run.id,
        "action_id": run.action_id,
        "actor": run.actor,
        "status": run.status,
        "payload_digest": run.payload_digest,
        "output": output,
        "evidence": evidence,
        "approval_id": run.approval_id,
        "created_at": run.created_at,
        "updated_at": run.updated_at,
        "client_id": run.client_id,
        "error_detail": redact_text(run.error_detail),
    }


def _agent_definition_view(definition) -> dict[str, object]:
    return cast(
        dict[str, object],
        redact_value(
            {
                "id": definition.id,
                "name": definition.name,
                "description": definition.description,
                "enabled": definition.enabled,
                "trigger": definition.trigger,
                "entity_type": definition.entity_type,
                "filters": definition.filters,
                "enabled_tools": definition.enabled_tools,
                "steps": definition.steps,
                "max_steps": definition.max_steps,
                "execution_timeout_seconds": definition.execution_timeout_seconds,
                "client_id": definition.client_id,
                "version": definition.version,
                "run_once_per_entity": definition.run_once_per_entity,
                "depends_on_agent_ids": definition.depends_on_agent_ids,
                "execution_window_start": definition.execution_window_start,
                "execution_window_end": definition.execution_window_end,
                "execution_window_timezone": definition.execution_window_timezone,
                "context_sources": definition.context_sources,
                "approval_expiry_seconds": definition.approval_expiry_seconds,
                "result_aware": definition.result_aware,
                "approval_required_tools": definition.approval_required_tools,
                "approval_rules": definition.approval_rules,
                "created_at": definition.created_at,
                "updated_at": definition.updated_at,
            }
        ),
    )


def _event_dispatch_view(result) -> dict[str, object]:
    return {
        "delivery": _event_delivery_view(result.delivery),
        "duplicate": result.duplicate,
        "matched_agent_ids": result.matched_agent_ids,
        "run_ids": result.run_ids,
        "matched_playbook_ids": result.matched_playbook_ids,
        "playbook_run_ids": result.playbook_run_ids,
        "errors": result.errors,
    }


def _event_delivery_view(delivery) -> dict[str, object]:
    return {
        "id": delivery.id,
        "idempotency_key": delivery.idempotency_key,
        "event_type": delivery.event_type,
        "entity_type": delivery.entity_type,
        "entity_id": delivery.entity_id,
        "payload": _safe_redacted_json_object(delivery.payload_json),
        "status": delivery.status,
        "matched_agent_count": delivery.matched_agent_count,
        "agent_ids": _safe_json_values(delivery.agent_ids_json),
        "run_ids": _safe_json_values(delivery.run_ids_json),
        "matched_playbook_count": delivery.matched_playbook_count,
        "playbook_ids": _safe_json_values(delivery.playbook_ids_json),
        "playbook_run_ids": _safe_json_values(delivery.playbook_run_ids_json),
        "playbook_attempts": _safe_redacted_json_object(delivery.playbook_attempts_json),
        "error_detail": redact_text(delivery.error_detail),
        "agent_attempts": _safe_redacted_json_object(delivery.agent_attempts_json),
        "retry_count": delivery.retry_count,
        "max_retries": delivery.max_retries,
        "retry_delay_seconds": delivery.retry_delay_seconds,
        "next_retry_at": delivery.next_retry_at,
        "received_at": delivery.received_at,
        "processed_at": delivery.processed_at,
        "client_id": delivery.client_id,
    }


def _template_gallery_view(entry) -> dict[str, object]:
    return {
        "id": entry.id,
        "source_template_id": entry.source_template_id,
        "name": entry.name,
        "trigger": entry.trigger,
        "description": entry.description,
        "action_type": entry.action_type,
        "approval_required": entry.approval_required,
        "risk_level": entry.risk_level,
        "preview_fields": _safe_json_values(entry.preview_fields_json),
        "provenance": redact_text(entry.provenance),
        "instructions": redact_text(entry.instructions),
        "definition": _safe_redacted_json_object(entry.definition_json),
        "enabled": entry.enabled,
        "version": entry.version,
        "created_at": entry.created_at,
        "updated_at": entry.updated_at,
        "client_id": entry.client_id,
    }


def _template_gallery_export_view(entry) -> dict[str, object]:
    """Return a portable artifact without local ids, timestamps, or tenant identity."""

    return {
        "format": "wait-local-agent.workflow-template",
        "format_version": 1,
        "source_template_id": entry.source_template_id,
        "name": redact_text(entry.name),
        "description": redact_text(entry.description),
        "provenance": redact_text(entry.provenance),
        "instructions": redact_text(entry.instructions),
        "definition": _safe_redacted_json_object(entry.definition_json),
        "enabled": entry.enabled,
    }


def _template_gallery_revision_view(revision) -> dict[str, object]:
    return {
        "id": revision.id,
        "gallery_id": revision.gallery_id,
        "version": revision.version,
        "definition": _safe_redacted_json_object(revision.definition_json),
        "created_at": revision.created_at,
        "client_id": revision.client_id,
    }


def _workflow_run_comparison_view(left: WorkflowRun, right: WorkflowRun) -> dict[str, object]:
    fields = (
        "template_id",
        "ticket_id",
        "status",
        "message",
        "approval_request_id",
        "template_version",
        "client_id",
    )
    left_view = asdict(left)
    right_view = asdict(right)
    left_view["message"] = redact_text(left.message)
    right_view["message"] = redact_text(right.message)
    changes = [
        {"field": field, "before": left_view[field], "after": right_view[field]}
        for field in fields
        if left_view[field] != right_view[field]
    ]
    return {
        "from_run": left_view,
        "to_run": right_view,
        "changed": bool(changes),
        "changes": changes,
    }


def _template_gallery_revision_diff_view(left, right) -> dict[str, object]:
    left_definition = _safe_redacted_json_object(left.definition_json)
    right_definition = _safe_redacted_json_object(right.definition_json)
    changed_fields: list[dict[str, object]] = []
    for field in sorted(set(left_definition) | set(right_definition)):
        before = left_definition.get(field)
        after = right_definition.get(field)
        if before != after:
            changed_fields.append({"field": field, "before": before, "after": after})
    return {
        "gallery_id": left.gallery_id,
        "from_version": left.version,
        "to_version": right.version,
        "changed": bool(changed_fields),
        "changes": changed_fields,
        "client_id": left.client_id,
    }


def _agent_revision_view(revision) -> dict[str, object]:
    return {
        "id": revision.id,
        "agent_id": revision.agent_id,
        "version": revision.version,
        "definition": _safe_redacted_json_object(revision.definition_json),
        "created_at": revision.created_at,
        "client_id": revision.client_id,
    }


def _agent_revision_diff_view(left, right) -> dict[str, object]:
    left_definition = _safe_redacted_json_object(left.definition_json)
    right_definition = _safe_redacted_json_object(right.definition_json)
    changed_fields: list[dict[str, object]] = []
    for field in sorted(set(left_definition) | set(right_definition)):
        before = left_definition.get(field)
        after = right_definition.get(field)
        if before != after:
            changed_fields.append({"field": field, "before": before, "after": after})
    return {
        "agent_id": left.agent_id,
        "from_version": left.version,
        "to_version": right.version,
        "changed": bool(changed_fields),
        "changes": changed_fields,
        "client_id": left.client_id,
    }


def _agent_run_view(run) -> dict[str, object]:
    state = _safe_json_object(run.state_json)
    final_result = state.get("final_result") if isinstance(state.get("final_result"), dict) else {}
    retry_count = state.get("retry_count") if isinstance(state.get("retry_count"), int) else 0
    retry_of_run_id = state.get("retry_of_run_id") if isinstance(state.get("retry_of_run_id"), int) else None
    history = final_result.get("history") if isinstance(final_result, dict) else None
    return cast(
        dict[str, object],
        redact_value(
            {
                "id": run.id,
                "agent_id": run.agent_id,
                "entity_id": run.entity_id,
                "actor": run.actor,
                "status": run.status,
                "current_step": run.current_step,
                "state": state,
                "started_at": run.started_at,
                "finished_at": run.finished_at,
                "revision_version": run.revision_version,
                "client_id": run.client_id,
                "lineage": {
                    "retry_count": retry_count,
                    "retry_of_run_id": retry_of_run_id,
                    "partial_history": history if isinstance(history, dict) else {},
                },
            }
        ),
    )


def _agent_backfill_view(backfill) -> dict[str, object]:
    return {
        "id": backfill.id,
        "agent_id": backfill.agent_id,
        "entity_ids": _safe_json_values(backfill.entity_ids_json),
        "input": _safe_redacted_json_object(backfill.input_json),
        "max_concurrency": backfill.max_concurrency,
        "status": backfill.status,
        "next_index": backfill.next_index,
        "processed_count": backfill.processed_count,
        "succeeded_count": backfill.succeeded_count,
        "failed_count": backfill.failed_count,
        "run_ids": _safe_json_values(backfill.run_ids_json),
        "failed_entity_ids": _safe_json_values(backfill.failed_entity_ids_json),
        "actor": redact_text(backfill.actor),
        "error_detail": redact_text(backfill.error_detail),
        "created_at": backfill.created_at,
        "updated_at": backfill.updated_at,
        "client_id": backfill.client_id,
    }


def _end_user_ticket_view(ticket) -> dict[str, object]:
    return {
        "ticket_id": ticket.id,
        "subject": redact_text(ticket.subject),
        "body": redact_text(ticket.body),
        "status": ticket.status,
        "priority": ticket.priority,
    }


def _end_user_branding_text(value: str, fallback: str) -> str:
    cleaned = redact_text(value.strip())[:120].strip()
    return cleaned or fallback


_END_USER_COLOR_PATTERN = re.compile(r"^#[0-9a-fA-F]{6}$")
_END_USER_LOGO_PATTERN = re.compile(r"^data:image/(?:png|jpeg|webp|gif);base64,[A-Za-z0-9+/=]+$")


def _end_user_brand_color(value: str, fallback: str) -> str:
    cleaned = value.strip()
    return cleaned if _END_USER_COLOR_PATTERN.fullmatch(cleaned) else fallback


def _end_user_brand_logo_data_uri(value: str) -> str:
    cleaned = value.strip()
    if len(cleaned) > 1_000_000 or not _END_USER_LOGO_PATTERN.fullmatch(cleaned):
        return ""
    return cleaned


def _end_user_message_view(message) -> dict[str, object]:
    return {
        "id": message.id,
        "ticket_id": message.ticket_id,
        "body": redact_text(message.body),
        "role": "support" if message.author_role == "support" else "requester",
        "created_at": message.created_at,
    }


def _operator_end_user_message_view(message) -> dict[str, object]:
    return {
        "id": message.id,
        "ticket_id": message.ticket_id,
        "role": "support" if message.author_role == "support" else "requester",
        "body": redact_text(message.body),
        "created_at": message.created_at,
    }


def _technician_chat_session_view(store: Store, session) -> dict[str, object]:
    return {
        "id": session.id,
        "status": session.status,
        "ticket_id": session.ticket_id,
        "client_id": session.client_id,
        "created_at": session.created_at,
        "updated_at": session.updated_at,
        "messages": [
            {
                "id": message.id,
                "role": message.role,
                "message": redact_text(message.message),
                "action_id": message.action_id,
                "status": message.status,
                "ticket_id": message.ticket_id,
                "created_at": message.created_at,
            }
            for message in store.list_technician_chat_messages(
                session.id,
                client_id=session.client_id,
            )
        ],
    }


def _invoke_technician_chat_message(
    store: Store,
    smart_action_service: SmartActionService,
    agent_service: AgentService,
    message: str,
    *,
    ticket_id: str | None,
    actor: str,
    client_id: str | None,
    session_id: str | None = None,
    principal_id: str | None = None,
    correlation_id: str | None = None,
) -> dict[str, object]:
    if session_id is not None:
        store.add_technician_chat_message(
            session_id,
            role="user",
            message=message,
            status="received",
            ticket_id=ticket_id,
            client_id=client_id,
            principal_id=principal_id,
        )
    try:
        command = parse_technician_message(message, ticket_id=ticket_id)
    except TechnicianChatParseError as exc:
        if session_id is not None:
            store.add_technician_chat_message(
                session_id,
                role="assistant",
                message=str(exc),
                status="failed",
                ticket_id=ticket_id,
                client_id=client_id,
                principal_id=principal_id,
            )
        raise
    candidate_ticket_id = command.payload.get("ticket_id")
    resolved_ticket_id = candidate_ticket_id if isinstance(candidate_ticket_id, str) else None
    if session_id is not None and resolved_ticket_id and client_id:
        if (
            store.update_technician_chat_session_ticket(
                session_id,
                client_id=client_id,
                ticket_id=resolved_ticket_id,
                principal_id=principal_id,
            )
            is None
        ):
            raise LookupError(resolved_ticket_id)
    if command.mode == "help":
        if session_id is not None:
            store.add_technician_chat_message(
                session_id,
                role="assistant",
                message=command.reply,
                status="help",
                ticket_id=resolved_ticket_id,
                client_id=client_id,
                principal_id=principal_id,
            )
        response: dict[str, object] = {
            "status": "help",
            "message": command.reply,
            "supported": True,
        }
        if session_id is not None:
            response["session_id"] = session_id
        return response
    if command.mode == "plan":
        if not resolved_ticket_id:  # pragma: no cover - parser guarantees a plan ticket ID
            raise TechnicianChatParseError("include a ticket ID such as TCK-1001")
        try:
            plan = agent_service.plan(
                command.instruction or message,
                entity_id=resolved_ticket_id,
                client_id=client_id,
            )
        except AgentDefinitionError as exc:
            plan_message = f"The plan is blocked: {redact_text(str(exc))}"
            plan_payload: dict[str, object] = {
                "instruction": command.instruction or message,
                "entity_id": resolved_ticket_id,
                "client_id": client_id,
                "status": "blocked",
                "steps": [],
                "blocked_reason": redact_text(str(exc)),
            }
            plan_status = "blocked"
        else:
            plan_payload = asdict(plan)
            plan_status = plan.status
            plan_message = (
                "I prepared a bounded plan preview. Review the selected tools and approvals "
                "before creating or running an agent."
                if plan.status == "preview"
                else f"The plan is blocked: {plan.blocked_reason}"
            )
        _record_technician_chat_assistant(
            store,
            session_id=session_id,
            message=plan_message,
            status=plan_status,
            ticket_id=resolved_ticket_id,
            client_id=client_id,
            principal_id=principal_id,
        )
        response = {
            "status": plan_status,
            "message": plan_message,
            "plan": redact_value(plan_payload),
            "supported": True,
        }
        response.update({"session_id": session_id} if session_id is not None else {})
        return response
    action_id = command.action_id
    if not action_id:  # pragma: no cover - parser assigns an action for this mode
        raise TechnicianChatParseError("technician request did not select an approved action")
    result = smart_action_service.invoke(
        action_id,
        command.payload,
        actor,
        client_id=client_id,
        correlation_id=correlation_id,
    )
    _record_technician_chat_assistant(
        store,
        session_id=session_id,
        message=command.reply,
        action_id=action_id,
        status=result.status,
        ticket_id=resolved_ticket_id,
        client_id=client_id,
        principal_id=principal_id,
    )
    response = {
        "status": result.status,
        "message": command.reply,
        "action_id": action_id,
        "result": asdict(result),
    }
    if session_id is not None:
        response["session_id"] = session_id
    return response


def _record_technician_chat_assistant(
    store: Store,
    *,
    session_id: str | None,
    message: str,
    status: str,
    ticket_id: str | None,
    client_id: str | None,
    principal_id: str | None,
    action_id: str | None = None,
) -> None:
    if session_id is None:
        return
    store.add_technician_chat_message(
        session_id,
        role="assistant",
        message=message,
        action_id=action_id,
        status=status,
        ticket_id=ticket_id,
        client_id=client_id,
        principal_id=principal_id,
    )


def _safe_end_user_ticket_id(ticket_id: str) -> bool:
    return bool(
        ticket_id
        and len(ticket_id) <= 100
        and not any(ord(character) < 32 or character.isspace() for character in ticket_id)
    )


def _safe_external_ticket_id(ticket_id: str) -> bool:
    return (
        bool(ticket_id.strip())
        and len(ticket_id) <= 100
        and all(ord(character) >= 32 and character not in "/?#\x00" for character in ticket_id)
    )


def _halopsa_client_mapping(settings: Settings, client_id: str | None) -> str | None:
    normalized_client_id = _normalize_client_id(client_id)
    if normalized_client_id is None:
        return None
    try:
        payload = json.loads(settings.halopsa_client_map_json or "{}")
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    mapped = payload.get(normalized_client_id)
    if isinstance(mapped, bool) or not isinstance(mapped, (str, int)):
        return None
    value = str(mapped).strip()
    return value or None


def _execution_run_view(run) -> dict[str, object]:
    return {
        "id": run.id,
        "run_kind": run.run_kind,
        "source_run_id": run.source_run_id,
        "actor": run.actor,
        "status": run.status,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "trigger_source": run.trigger_source,
        "client_id": run.client_id,
        "metadata": _safe_redacted_json_object(run.metadata_json),
    }


def _execution_step_view(step) -> dict[str, object]:
    # Step payloads are redacted at persistence and again here at
    # serialization so legacy rows never surface secrets.
    return {
        "id": step.id,
        "ordinal": step.ordinal,
        "kind": step.kind,
        "name": step.name,
        "status": step.status,
        "started_at": step.started_at,
        "finished_at": step.finished_at,
        "input_digest": step.input_digest,
        "output_digest": step.output_digest,
        "input": redact_value(_safe_json_value(step.input_json)),
        "output": redact_value(_safe_json_value(step.output_json)),
        "error_detail": redact_text(step.error_detail),
    }


def _execution_artifact_view(artifact) -> dict[str, object]:
    return {
        "id": artifact.id,
        "step_ordinal": artifact.step_ordinal,
        "name": artifact.name,
        "media_type": artifact.media_type,
        "byte_size": artifact.byte_size,
        "sha256": artifact.sha256,
    }


def _safe_json_value(payload_json: str) -> object:
    try:
        return json.loads(payload_json)
    except json.JSONDecodeError:
        return None


def _dispatch_workflow_completion_event(
    event_dispatcher: EventDispatcher,
    run: WorkflowRun,
    actor: str,
) -> None:
    """Continue completed API workflow runs without changing their outcome."""
    if run.status != "completed" or run.id is None or not run.ticket_id.strip():
        return
    payload: dict[str, object] = {
        "workflow_run_id": str(run.id),
        "workflow_template_id": run.template_id,
        "status": run.status,
    }
    try:
        event_dispatcher.dispatch(
            event_type="workflow.completed",
            entity_type="ticket",
            entity_id=run.ticket_id,
            payload=payload,
            idempotency_key=f"workflow-completed:{run.id}",
            client_id=run.client_id,
            actor=actor,
        )
        event_dispatcher.store.add_audit_event(
            "workflow.completion_dispatched",
            str(run.id),
            "workflow.completed event dispatched",
            client_id=run.client_id,
        )
    except Exception as exc:  # completion must not be undone
        detail = redact_text(f"workflow.completed dispatch failed: {exc}")
        event_dispatcher.store.add_audit_event(
            "workflow.completion_dispatch_failed",
            str(run.id),
            detail,
            client_id=run.client_id,
        )


def _empty_analytics_summary(started_from: str | None, started_to: str | None) -> dict[str, object]:
    return {
        "range": {"from": started_from, "to": started_to},
        "client_id": None,
        "executions_over_time": [],
        "success_rate": {"total": 0, "succeeded": 0, "rate": 0.0},
        "failures_by_status": [],
        "approval_rate": {
            "requested": 0,
            "decided": 0,
            "approved": 0,
            "rejected": 0,
            "pending": 0,
            "rate": 0.0,
            "derivation": APPROVAL_RATE_DERIVATION,
        },
        "ticket_metrics": {
            "touched": 0,
            "resolved": 0,
            "resolution_rate": 0.0,
            "derivation": TICKET_METRICS_DERIVATION,
            "historical_resolution": {
                "resolved_with_history": 0,
                "with_duration": 0,
                "average_minutes": None,
                "derivation": TICKET_LIFECYCLE_DERIVATION,
            },
        },
        "activity_by_workflow": [],
        "estimated_minutes_saved": {
            "minutes": 0,
            "estimate": True,
            "derivation": ESTIMATED_MINUTES_SAVED_DERIVATION,
        },
        "model_usage": {
            "runs_with_usage": 0,
            "runs_with_cost": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "estimated_cost_usd": 0.0,
            "estimate": True,
            "derivation": MODEL_COST_DERIVATION,
        },
    }


def _halopsa_draft_view(draft) -> dict[str, object]:
    payload = _safe_json_object(draft.payload_json)
    return {
        **asdict(draft),
        "payload_json": _redact_json_text(draft.payload_json),
        "payload": _redact_payload(payload),
    }


def _connectwise_draft_view(draft) -> dict[str, object]:
    payload = _safe_json_object(draft.payload_json)
    return {
        **asdict(draft),
        "payload_json": _redact_json_text(draft.payload_json),
        "payload": _redact_payload(payload),
    }


def _safe_json_object(payload_json: str) -> dict[str, object]:
    try:
        payload = json.loads(payload_json)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _power_platform_source_record(approval) -> dict[str, object] | None:
    if approval is None or approval.id is None:
        return None
    return {
        "id": approval.id,
        "client_id": approval.client_id,
        "action_type": approval.action_type,
        "status": approval.status,
        "execution_status": approval.execution_status,
        "payload": _safe_json_object(approval.payload_json),
        "execution_result": _safe_json_object(approval.execution_result_json),
    }


def _safe_json_list(payload_json: str) -> list[dict[str, object]]:
    try:
        payload = json.loads(payload_json)
    except json.JSONDecodeError:
        return []
    return [item for item in payload if isinstance(item, dict)] if isinstance(payload, list) else []


def _safe_json_values(payload_json: str) -> list[object]:
    try:
        payload = json.loads(payload_json)
    except json.JSONDecodeError:
        return []
    return payload if isinstance(payload, list) else []


def _redact_json_text(payload_json: str) -> str:
    try:
        payload = json.loads(payload_json)
    except json.JSONDecodeError:
        return "[redacted]"
    return json.dumps(redact_value(payload), sort_keys=True, separators=(",", ":"))


def _safe_redacted_json_object(payload_json: str) -> dict[str, object]:
    return cast(dict[str, object], redact_value(_safe_json_object(payload_json)))


def _scheduled_ticket_id(params: dict[str, object]) -> str:
    ticket_id = params.get("ticket_id")
    if not isinstance(ticket_id, str) or not ticket_id.strip():
        raise HTTPException(status_code=422, detail="scheduled job params must include ticket_id")
    return ticket_id


def _redact_request_input(value: object, sensitive_fields: set[str]) -> object:
    if isinstance(value, dict):
        return {
            str(key): "[redacted]"
            if str(key).lower() in sensitive_fields
            else _redact_request_input(item, sensitive_fields)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_request_input(item, sensitive_fields) for item in value]
    return "[redacted]" if sensitive_fields else value


SENSITIVE_KEY_PARTS = (
    "secret",
    "token",
    "api_key",
    "password",
    "apikey",
    "auth_token",
    "bearer",
    "authorization",
    "x-api-key",
    "client_secret",
    "access_token",
)


def _redact_payload(payload: dict[str, object]) -> dict[str, object]:
    redacted: dict[str, object] = {}
    for key, value in payload.items():
        if any(secret in key.lower() for secret in SENSITIVE_KEY_PARTS):
            redacted[key] = "[redacted]"
        else:
            redacted[key] = _redact_value(value)
    return redacted


def _redact_value(value: object) -> object:
    if isinstance(value, dict):
        return _redact_payload(value)
    if isinstance(value, list):
        return [_redact_value(item) for item in value]
    return value
