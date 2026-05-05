from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Protocol

import httpx

from wait_local_agent.config import Settings
from wait_local_agent.models import SourceReference, Ticket

LOGGER = logging.getLogger(__name__)
SUPPORTED_LOCAL_MODEL_PROVIDERS = {"openai-compatible", "ollama", "vllm"}


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
    inference_enabled: bool
    timeout_seconds: float
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


@dataclass(frozen=True)
class ModelCompletion:
    summary: str
    suggested_response: str


class OpenAICompatibleLocalProvider:
    def __init__(
        self,
        profile: LocalModelProfile,
        *,
        fallback: DeterministicLocalProvider | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.profile = profile
        self._fallback = fallback or DeterministicLocalProvider(profile)
        self._transport = transport
        self._cached_request_key: tuple[str, ...] = ()
        self._cached_completion: ModelCompletion | None = None

    def summarize_ticket(self, ticket: Ticket, sources: list[SourceReference]) -> str:
        return self._completion_or_fallback(ticket, sources).summary

    def draft_response(self, ticket: Ticket, sources: list[SourceReference]) -> str:
        return self._completion_or_fallback(ticket, sources).suggested_response

    def _completion_or_fallback(
        self, ticket: Ticket, sources: list[SourceReference]
    ) -> ModelCompletion:
        request_key = _request_key(ticket, sources)
        if self._cached_completion is not None and self._cached_request_key == request_key:
            return self._cached_completion

        completion = self._request_completion(ticket, sources)
        if completion is None:
            return ModelCompletion(
                summary=self._fallback.summarize_ticket(ticket, sources),
                suggested_response=self._fallback.draft_response(ticket, sources),
            )
        self._cached_request_key = request_key
        self._cached_completion = completion
        return completion

    def _request_completion(
        self, ticket: Ticket, sources: list[SourceReference]
    ) -> ModelCompletion | None:
        url = f"{self.profile.base_url.rstrip('/')}/chat/completions"
        payload = {
            "model": self.profile.model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You assist MSP technicians with local service-desk work. "
                        "Use only the ticket and local source excerpts provided. "
                        "Cite local source titles when useful. Do not claim that any "
                        "action was executed. Return only JSON with summary and "
                        "suggested_response fields."
                    ),
                },
                {
                    "role": "user",
                    "content": _user_prompt(ticket, sources),
                },
            ],
            "stream": False,
        }
        try:
            with httpx.Client(
                timeout=self.profile.timeout_seconds,
                transport=self._transport,
            ) as client:
                response = client.post(url, json=payload)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            LOGGER.warning("local model request failed; using deterministic provider: %s", exc)
            return None
        return _completion_from_response(response)


def _request_key(ticket: Ticket, sources: list[SourceReference]) -> tuple[str, ...]:
    return (
        ticket.id,
        ticket.client,
        ticket.subject,
        ticket.body,
        *(f"{source.document_id}:{source.chunk_id}:{source.title}" for source in sources),
    )


def _user_prompt(ticket: Ticket, sources: list[SourceReference]) -> str:
    source_blocks = []
    for index, source in enumerate(sources[:3], start=1):
        source_blocks.append(
            f"Source {index}: {source.title}\nPath: {source.path}\nExcerpt: {source.excerpt}"
        )
    source_text = "\n\n".join(source_blocks) if source_blocks else "No local sources found."
    return (
        f"Ticket client: {ticket.client}\n"
        f"Ticket subject: {ticket.subject}\n"
        f"Ticket body: {ticket.body}\n"
        f"Ticket classification: {_classify_ticket_for_prompt(ticket)}\n\n"
        f"Top local source excerpts:\n{source_text}\n\n"
        'Return JSON like {"summary":"...","suggested_response":"..."}'
    )


def _classify_ticket_for_prompt(ticket: Ticket) -> str:
    text = f"{ticket.subject} {ticket.body}".lower()
    if "mfa" in text or "password" in text or "sign-in" in text:
        return "identity-access"
    if "mailbox" in text or "distribution" in text:
        return "collaboration-change"
    if "disk" in text or "printer" in text:
        return "endpoint-triage"
    return "general-service-desk"


def _completion_from_response(response: httpx.Response) -> ModelCompletion | None:
    try:
        payload = response.json()
    except json.JSONDecodeError:
        LOGGER.warning("local model response was not valid JSON; using deterministic provider")
        return None
    content = _message_content(payload)
    if not content:
        LOGGER.warning("local model response was empty; using deterministic provider")
        return None
    completion = _completion_from_content(content)
    if completion is None:
        LOGGER.warning("local model content was malformed; using deterministic provider")
    return completion


def _message_content(payload: object) -> str:
    if not isinstance(payload, dict):
        return ""
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first_choice = choices[0]
    if not isinstance(first_choice, dict):
        return ""
    message = first_choice.get("message")
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    return content.strip() if isinstance(content, str) else ""


def _completion_from_content(content: str) -> ModelCompletion | None:
    normalized = _strip_json_fence(content)
    try:
        payload = json.loads(normalized)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    summary = payload.get("summary")
    suggested_response = payload.get("suggested_response")
    if not isinstance(summary, str) or not isinstance(suggested_response, str):
        return None
    summary = summary.strip()
    suggested_response = suggested_response.strip()
    if not summary or not suggested_response:
        return None
    return ModelCompletion(summary=summary, suggested_response=suggested_response)


def _strip_json_fence(content: str) -> str:
    stripped = content.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    if len(lines) >= 3 and lines[-1].strip() == "```":
        return "\n".join(lines[1:-1]).strip()
    return stripped


def provider_from_settings(settings: Settings) -> ModelProvider:
    profile = LocalModelProfile(
        provider=settings.local_model_provider,
        base_url=settings.local_model_base_url,
        model=settings.local_model_name,
        inference_enabled=settings.allow_llm_inference,
        timeout_seconds=settings.local_model_timeout_seconds,
        cloud_fallback_enabled=settings.allow_cloud_fallback,
    )
    if (
        settings.allow_llm_inference
        and settings.local_model_provider in SUPPORTED_LOCAL_MODEL_PROVIDERS
    ):
        return OpenAICompatibleLocalProvider(profile)
    return DeterministicLocalProvider(profile)
