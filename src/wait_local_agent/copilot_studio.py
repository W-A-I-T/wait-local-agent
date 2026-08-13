"""Review-only Microsoft Copilot Studio handoff artifacts.

This module describes a bounded handoff for a later, official Microsoft
deployment path. It does not call Copilot Studio, acquire credentials, or
pretend that a topic or connector has been provisioned.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

MAX_TOPICS = 32
MAX_TRIGGER_PHRASES = 16
MAX_ACTIONS = 32
MAX_KNOWLEDGE_SOURCES = 32
MAX_TEXT = 240
_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_.:-]{0,63}$")
_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}
_SECRET_TOKENS = ("key", "token", "secret", "password", "credential", "authorization")


class CopilotStudioPlanError(ValueError):
    """Raised when a Copilot Studio handoff is malformed or unsafe."""


def build_copilot_studio_plan(
    *,
    client_id: str,
    copilot_name: str,
    business_goal: str,
    topics: list[dict[str, object]],
    knowledge_sources: list[object],
    actions: list[dict[str, object]],
) -> dict[str, Any]:
    tenant = _text(client_id, "client_id", 128)
    name = _text(copilot_name, "copilot_name", MAX_TEXT)
    goal = _text(business_goal, "business_goal", 500)
    topic_views = _topics(topics)
    knowledge_views = _text_list(knowledge_sources, "knowledge_sources", MAX_KNOWLEDGE_SOURCES)
    action_views = _actions(actions)
    return {
        "format": "wait-local-agent.copilot-studio-plan",
        "format_version": 1,
        "client_id": tenant,
        "target": "microsoft_copilot_studio",
        "copilot": {"name": name, "business_goal": goal},
        "topics": topic_views,
        "knowledge_sources": knowledge_views,
        "actions": action_views,
        "requires_approval": any(bool(action["approval_required"]) for action in action_views),
        "credentials_included": False,
        "generation_status": "review_only",
        "provider_verification": "not_run",
        "execution_started": False,
        "deployment_started": False,
        "open_items": [
            "Copilot Studio environment and licensing must be verified by an operator.",
            "Topic, connector, and knowledge-source provisioning requires an official Microsoft path.",
            "Production channel publication remains approval-gated and is not performed by this artifact.",
        ],
    }


def _topics(value: object) -> list[dict[str, object]]:
    items = _objects(value, "topics", MAX_TOPICS)
    result: list[dict[str, object]] = []
    seen: set[str] = set()
    for topic in items:
        unknown = sorted(set(topic) - {"id", "name", "trigger_phrases"})
        if unknown:
            raise CopilotStudioPlanError(f"topic contains unsupported fields: {', '.join(unknown)}")
        topic_id = _identifier(topic.get("id"), "topic.id")
        if topic_id in seen:
            raise CopilotStudioPlanError(f"duplicate topic id: {topic_id}")
        seen.add(topic_id)
        triggers = _text_list(topic.get("trigger_phrases", []), "topic.trigger_phrases", MAX_TRIGGER_PHRASES)
        result.append(
            {
                "id": topic_id,
                "name": _text(topic.get("name"), "topic.name"),
                "trigger_phrases": triggers,
            }
        )
    return result


def _actions(value: object) -> list[dict[str, object]]:
    items = _objects(value, "actions", MAX_ACTIONS)
    result: list[dict[str, object]] = []
    seen: set[str] = set()
    for action in items:
        unknown = sorted(set(action) - {"id", "connector_id", "method", "approval_required"})
        if unknown:
            raise CopilotStudioPlanError(f"action contains unsupported fields: {', '.join(unknown)}")
        action_id = _identifier(action.get("id"), "action.id")
        if action_id in seen:
            raise CopilotStudioPlanError(f"duplicate action id: {action_id}")
        seen.add(action_id)
        method = action.get("method", "GET")
        if method not in _METHODS:
            raise CopilotStudioPlanError(f"unsupported action method: {method}")
        approval_required = action.get("approval_required", method != "GET")
        if not isinstance(approval_required, bool):
            raise CopilotStudioPlanError("action approval_required must be boolean")
        if method != "GET" and not approval_required:
            raise CopilotStudioPlanError(f"Copilot Studio write action requires approval: {action_id}")
        connector_id = _identifier(action.get("connector_id"), "action.connector_id")
        result.append(
            {
                "id": action_id,
                "connector_id": connector_id,
                "method": method,
                "approval_required": approval_required,
            }
        )
    return result


def _objects(value: object, field: str, maximum: int) -> list[dict[str, object]]:
    if not isinstance(value, list) or len(value) > maximum:
        raise CopilotStudioPlanError(f"{field} must contain 0-{maximum} objects")
    if any(not isinstance(item, Mapping) for item in value):
        raise CopilotStudioPlanError(f"{field} must contain objects")
    return [dict(item) for item in value]


def _text_list(value: object, field: str, maximum: int) -> list[str]:
    if not isinstance(value, list) or len(value) > maximum:
        raise CopilotStudioPlanError(f"{field} must contain 0-{maximum} items")
    result = [_text(item, f"{field}[{index}]") for index, item in enumerate(value)]
    if len(set(result)) != len(result):
        raise CopilotStudioPlanError(f"{field} must not contain duplicates")
    return result


def _identifier(value: object, field: str) -> str:
    normalized = _text(value, field, 64).casefold()
    if any(token in normalized for token in _SECRET_TOKENS) or not _IDENTIFIER.fullmatch(normalized):
        raise CopilotStudioPlanError(f"{field} must be a safe lowercase identifier")
    return normalized


def _text(value: object, field: str, maximum: int = MAX_TEXT) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        raise CopilotStudioPlanError(f"{field} must be non-empty text of at most {maximum} characters")
    normalized = value.strip()
    if any(ord(character) < 32 for character in normalized) or any(
        token in normalized.casefold() for token in _SECRET_TOKENS
    ):
        raise CopilotStudioPlanError(f"{field} contains unsupported or secret-like text")
    return normalized


__all__ = ["CopilotStudioPlanError", "build_copilot_studio_plan"]
