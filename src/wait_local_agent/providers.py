from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from wait_local_agent.config import Settings
from wait_local_agent.models import SourceReference, Ticket


class ModelProvider(Protocol):
    def summarize_ticket(self, ticket: Ticket, sources: list[SourceReference]) -> str:
        """Return a concise ticket summary."""

    def draft_response(self, ticket: Ticket, sources: list[SourceReference]) -> str:
        """Return a technician-facing draft response."""


@dataclass(frozen=True)
class LocalModelProfile:
    provider: str
    base_url: str
    model: str
    cloud_fallback_enabled: bool


class DeterministicLocalProvider:
    def __init__(self, profile: LocalModelProfile) -> None:
        self.profile = profile

    def summarize_ticket(self, ticket: Ticket, sources: list[SourceReference]) -> str:
        source_hint = sources[0].title if sources else "local documentation"
        return (
            f"{ticket.client} needs help with {ticket.subject.lower()}. "
            f"Use {source_hint} and keep the work approval-first."
        )

    def draft_response(self, ticket: Ticket, sources: list[SourceReference]) -> str:
        source_hint = sources[0].title if sources else "the local runbook"
        return (
            f"Hi {ticket.client}, we are reviewing the request and validating it against "
            f"{source_hint}. A technician will confirm the approved next step before any "
            "change is made."
        )


def provider_from_settings(settings: Settings) -> DeterministicLocalProvider:
    profile = LocalModelProfile(
        provider=settings.local_model_provider,
        base_url=settings.local_model_base_url,
        model=settings.local_model_name,
        cloud_fallback_enabled=settings.allow_cloud_fallback,
    )
    return DeterministicLocalProvider(profile)

