from __future__ import annotations

import pytest

from wait_local_agent.technician_chat import TechnicianChatParseError, parse_technician_message


@pytest.mark.parametrize(
    ("message", "action_id"),
    [
        ("summarize TCK-1001", "ticket-summary"),
        ("triage TCK-1001", "ticket-triage"),
        ("find similar tickets for TCK-1001", "find-similar-tickets"),
        ("show the runbook for TCK-1001", "knowledge-search"),
        ("suggest a fix for TCK-1001", "suggest-resolution"),
        ("check ticket quality TCK-1001", "ticket-quality"),
        ("assess sentiment on TCK-1001", "ticket-sentiment"),
        ("assess escalation for TCK-1001", "ticket-escalation"),
        ("dispatch TCK-1001", "dispatch-suggestion"),
    ],
)
def test_technician_chat_maps_only_to_existing_bounded_actions(message: str, action_id: str) -> None:
    command = parse_technician_message(message)

    assert command.action_id == action_id
    assert command.payload == {"ticket_id": "TCK-1001"}


@pytest.mark.parametrize(
    ("message", "action_id"),
    [
        ("preview script script-1 on device device-1", "rmm-script-preview"),
        ("run approved script script-1 on device agent:device-1", "rmm-script-execute"),
    ],
)
def test_technician_chat_maps_explicit_rmm_script_requests(message: str, action_id: str) -> None:
    command = parse_technician_message(message)

    assert command.action_id == action_id
    assert command.payload == {
        "script_id": "script-1",
        "device_id": "device-1" if action_id == "rmm-script-preview" else "agent:device-1",
    }


def test_technician_chat_supports_help_without_invoking_a_tool() -> None:
    command = parse_technician_message("help")

    assert command.action_id is None
    assert command.payload == {}
    assert "summarize" in command.reply
    assert "approved script" in command.reply


def test_technician_chat_supports_explicit_bounded_plan_preview() -> None:
    command = parse_technician_message("plan triage, search documentation, and suggest a fix for TCK-1001")

    assert command.mode == "plan"
    assert command.action_id is None
    assert command.payload == {"ticket_id": "TCK-1001"}
    assert command.instruction == "triage, search documentation, and suggest a fix for TCK-1001"
    assert "plan preview" in command.reply


def test_technician_chat_requires_ticket_id_for_plan_preview() -> None:
    with pytest.raises(TechnicianChatParseError, match="include a ticket ID"):
        parse_technician_message("plan triage and suggest a fix")


@pytest.mark.parametrize(
    "message",
    [
        "",
        "x" * 2001,
        "triage",
        "run arbitrary shell command TCK-1001",
        "run approved script script-1 on device device-1; rm -rf /",
        "triage TCK-1001\x00",
    ],
)
def test_technician_chat_rejects_unbounded_or_incomplete_requests(message: str) -> None:
    with pytest.raises(TechnicianChatParseError):
        parse_technician_message(message)


def test_technician_chat_rejects_unsafe_explicit_ticket_id() -> None:
    with pytest.raises(TechnicianChatParseError, match="unsupported characters"):
        parse_technician_message("triage this ticket", ticket_id="TCK-1001/evil")


def test_technician_chat_accepts_explicit_ticket_id_without_echoing_free_form_text() -> None:
    command = parse_technician_message("please triage this ticket", ticket_id="TCK-1001")

    assert command.action_id == "ticket-triage"
    assert command.payload == {"ticket_id": "TCK-1001"}
