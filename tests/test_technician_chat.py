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


def test_technician_chat_supports_help_without_invoking_a_tool() -> None:
    command = parse_technician_message("help")

    assert command.action_id is None
    assert command.payload == {}
    assert "summarize" in command.reply


@pytest.mark.parametrize(
    "message",
    ["", "x" * 2001, "triage", "run arbitrary shell command TCK-1001", "triage TCK-1001\x00"],
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
