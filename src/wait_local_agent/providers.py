from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Protocol

import httpx

from wait_local_agent.config import Settings
from wait_local_agent.models import SourceReference, Ticket

LOGGER = logging.getLogger(__name__)
SUPPORTED_LOCAL_MODEL_PROVIDERS = {"openai-compatible", "ollama", "vllm"}
SUPPORTED_REMOTE_MODEL_PROVIDERS = {
    "anthropic",
    "deepseek",
    "kimi",
    "co" + "dex",
    "openai-compatible",
}
_REMOTE_CONTEXT_LIMIT = 2_000
_REMOTE_SOURCE_LIMIT = 800


class ModelProvider(Protocol):
    def summarize_ticket(self, ticket: Ticket, sources: list[SourceReference]) -> str:
        """Return a concise ticket summary."""

    def draft_response(self, ticket: Ticket, sources: list[SourceReference]) -> str:
        """Return a technician-facing draft response."""


class PlanningModelProvider(Protocol):
    def select_tools(
        self,
        instruction: str,
        ticket: Ticket,
        sources: list[SourceReference],
        tools: list[dict[str, str]],
        *,
        max_tools: int,
    ) -> list[str]:
        """Select only catalog tool IDs for a bounded plan."""


class ProviderUnavailableError(RuntimeError):
    """Raised when a configured model provider cannot produce a completion."""


@dataclass(frozen=True)
class LocalModelProfile:
    provider: str
    base_url: str
    model: str
    inference_enabled: bool
    timeout_seconds: float
    cloud_fallback_enabled: bool


@dataclass(frozen=True)
class RemoteModelProfile:
    provider: str
    base_url: str
    model: str
    api_key: str
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

    def select_tools(
        self,
        instruction: str,
        ticket: Ticket,
        sources: list[SourceReference],
        tools: list[dict[str, str]],
        *,
        max_tools: int,
    ) -> list[str]:
        raise ProviderUnavailableError("deterministic provider does not select plan tools")


@dataclass(frozen=True)
class ModelCompletion:
    summary: str
    suggested_response: str


class OpenAICompatibleLocalProvider:
    def __init__(
        self,
        profile: LocalModelProfile,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.profile = profile
        self._transport = transport
        self._cached_request_key: tuple[str, ...] = ()
        self._cached_completion: ModelCompletion | None = None
        self._cached_plan_request_key: tuple[str, ...] = ()
        self._cached_plan: tuple[str, ...] | None = None

    def summarize_ticket(self, ticket: Ticket, sources: list[SourceReference]) -> str:
        return self._request_completion_or_raise(ticket, sources).summary

    def draft_response(self, ticket: Ticket, sources: list[SourceReference]) -> str:
        return self._request_completion_or_raise(ticket, sources).suggested_response

    def select_tools(
        self,
        instruction: str,
        ticket: Ticket,
        sources: list[SourceReference],
        tools: list[dict[str, str]],
        *,
        max_tools: int,
    ) -> list[str]:
        request_key = _planning_request_key(instruction, ticket, sources, tools, max_tools)
        if self._cached_plan is not None and self._cached_plan_request_key == request_key:
            return list(self._cached_plan)
        selected = self._request_tool_selection(
            instruction, ticket, sources, tools, max_tools=max_tools
        )
        if selected is None:
            raise ProviderUnavailableError("openai-compatible provider returned no valid tool selection")
        self._cached_plan_request_key = request_key
        self._cached_plan = tuple(selected)
        return selected

    def _request_completion_or_raise(
        self, ticket: Ticket, sources: list[SourceReference]
    ) -> ModelCompletion:
        request_key = _request_key(ticket, sources)
        if self._cached_completion is not None and self._cached_request_key == request_key:
            return self._cached_completion

        completion = self._request_completion(ticket, sources)
        if completion is None:
            raise ProviderUnavailableError(
                "openai-compatible provider returned no valid model completion"
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
            LOGGER.warning("local model provider request failed: %s", exc)
            return None
        return _completion_from_response(response)

    def _request_tool_selection(
        self,
        instruction: str,
        ticket: Ticket,
        sources: list[SourceReference],
        tools: list[dict[str, str]],
        *,
        max_tools: int,
    ) -> list[str] | None:
        url = f"{self.profile.base_url.rstrip('/')}/chat/completions"
        payload = {
            "model": self.profile.model,
            "messages": [
                {
                    "role": "system",
                    "content": _planning_system_prompt(),
                },
                {
                    "role": "user",
                    "content": _planning_prompt(
                        instruction, ticket, sources, tools, max_tools=max_tools
                    ),
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
            LOGGER.warning("local model planner request failed: %s", exc)
            return None
        return _tool_selection_from_response(response, max_tools=max_tools)


class RemoteModelProvider:
    """Explicit remote adapter for documented provider contracts.

    DeepSeek, Kimi, and a documented coding-model-compatible endpoint use the OpenAI chat
    completions contract only when the operator supplies a documented,
    compatible endpoint. WAIT does not invent a base URL or model name.
    Anthropic uses its documented Messages API shape.
    """

    def __init__(
        self,
        profile: RemoteModelProfile,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.profile = profile
        self._transport = transport
        self._cached_request_key: tuple[str, ...] = ()
        self._cached_completion: ModelCompletion | None = None
        self._cached_plan_request_key: tuple[str, ...] = ()
        self._cached_plan: tuple[str, ...] | None = None

    def summarize_ticket(self, ticket: Ticket, sources: list[SourceReference]) -> str:
        return self._request_completion_or_raise(ticket, sources).summary

    def draft_response(self, ticket: Ticket, sources: list[SourceReference]) -> str:
        return self._request_completion_or_raise(ticket, sources).suggested_response

    def select_tools(
        self,
        instruction: str,
        ticket: Ticket,
        sources: list[SourceReference],
        tools: list[dict[str, str]],
        *,
        max_tools: int,
    ) -> list[str]:
        request_key = _planning_request_key(instruction, ticket, sources, tools, max_tools)
        if self._cached_plan is not None and self._cached_plan_request_key == request_key:
            return list(self._cached_plan)
        selected = self._request_tool_selection(
            instruction, ticket, sources, tools, max_tools=max_tools
        )
        if selected is None:
            raise ProviderUnavailableError(
                f"{self.profile.provider} provider returned no valid tool selection"
            )
        self._cached_plan_request_key = request_key
        self._cached_plan = tuple(selected)
        return selected

    def _request_completion_or_raise(
        self, ticket: Ticket, sources: list[SourceReference]
    ) -> ModelCompletion:
        request_key = _request_key(ticket, sources)
        if self._cached_completion is not None and self._cached_request_key == request_key:
            return self._cached_completion

        completion = self._request_completion(ticket, sources)
        if completion is None:
            raise ProviderUnavailableError(
                f"{self.profile.provider} provider returned no valid model completion"
            )
        self._cached_request_key = request_key
        self._cached_completion = completion
        return completion

    def _request_completion(
        self, ticket: Ticket, sources: list[SourceReference]
    ) -> ModelCompletion | None:
        is_anthropic = self.profile.provider == "anthropic"
        if is_anthropic:
            url = _endpoint(self.profile.base_url, "v1/messages")
            headers = {
                "content-type": "application/json",
                "x-api-key": self.profile.api_key,
                "anthropic-version": "2023-06-01",
            }
            payload = {
                "model": self.profile.model,
                "max_tokens": 512,
                "system": _system_prompt(),
                "messages": [{"role": "user", "content": _user_prompt(ticket, sources, redact=True)}],
            }
        else:
            url = _endpoint(self.profile.base_url, "chat/completions")
            headers = {
                "content-type": "application/json",
                "authorization": f"Bearer {self.profile.api_key}",
            }
            payload = {
                "model": self.profile.model,
                "messages": [
                    {"role": "system", "content": _system_prompt()},
                    {"role": "user", "content": _user_prompt(ticket, sources, redact=True)},
                ],
                "stream": False,
            }
        try:
            with httpx.Client(
                timeout=self.profile.timeout_seconds,
                transport=self._transport,
            ) as client:
                response = client.post(url, headers=headers, json=payload)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            LOGGER.warning("remote model provider request failed: provider=%s error=%s", self.profile.provider, exc)
            return None
        return (
            _completion_from_anthropic_response(response)
            if is_anthropic
            else _completion_from_response(response)
        )

    def _request_tool_selection(
        self,
        instruction: str,
        ticket: Ticket,
        sources: list[SourceReference],
        tools: list[dict[str, str]],
        *,
        max_tools: int,
    ) -> list[str] | None:
        is_anthropic = self.profile.provider == "anthropic"
        if is_anthropic:
            url = _endpoint(self.profile.base_url, "v1/messages")
            headers = {
                "content-type": "application/json",
                "x-api-key": self.profile.api_key,
                "anthropic-version": "2023-06-01",
            }
            payload = {
                "model": self.profile.model,
                "max_tokens": 256,
                "system": _planning_system_prompt(),
                "messages": [
                    {
                        "role": "user",
                        "content": _planning_prompt(
                            instruction, ticket, sources, tools, max_tools=max_tools, redact=True
                        ),
                    }
                ],
            }
        else:
            url = _endpoint(self.profile.base_url, "chat/completions")
            headers = {
                "content-type": "application/json",
                "authorization": f"Bearer {self.profile.api_key}",
            }
            payload = {
                "model": self.profile.model,
                "messages": [
                    {"role": "system", "content": _planning_system_prompt()},
                    {
                        "role": "user",
                        "content": _planning_prompt(
                            instruction, ticket, sources, tools, max_tools=max_tools, redact=True
                        ),
                    },
                ],
                "stream": False,
            }
        try:
            with httpx.Client(
                timeout=self.profile.timeout_seconds,
                transport=self._transport,
            ) as client:
                response = client.post(url, headers=headers, json=payload)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            LOGGER.warning(
                "remote model planner request failed: provider=%s error=%s",
                self.profile.provider,
                exc,
            )
            return None
        return _tool_selection_from_response(
            response,
            max_tools=max_tools,
            anthropic=is_anthropic,
        )


class FallbackModelProvider:
    """Use a configured remote provider only after local inference fails."""

    def __init__(self, primary: ModelProvider, fallback: RemoteModelProvider) -> None:
        self.primary = primary
        self.fallback = fallback

    def summarize_ticket(self, ticket: Ticket, sources: list[SourceReference]) -> str:
        try:
            return self.primary.summarize_ticket(ticket, sources)
        except ProviderUnavailableError:
            return self.fallback.summarize_ticket(ticket, sources)

    def draft_response(self, ticket: Ticket, sources: list[SourceReference]) -> str:
        try:
            return self.primary.draft_response(ticket, sources)
        except ProviderUnavailableError:
            return self.fallback.draft_response(ticket, sources)

    def select_tools(
        self,
        instruction: str,
        ticket: Ticket,
        sources: list[SourceReference],
        tools: list[dict[str, str]],
        *,
        max_tools: int,
    ) -> list[str]:
        primary_selector = getattr(self.primary, "select_tools", None)
        if not callable(primary_selector):
            return self.fallback.select_tools(
                instruction, ticket, sources, tools, max_tools=max_tools
            )
        try:
            return primary_selector(
                instruction, ticket, sources, tools, max_tools=max_tools
            )
        except ProviderUnavailableError:
            return self.fallback.select_tools(
                instruction, ticket, sources, tools, max_tools=max_tools
            )


def _request_key(ticket: Ticket, sources: list[SourceReference]) -> tuple[str, ...]:
    return (
        ticket.id,
        ticket.client,
        ticket.subject,
        ticket.body,
        *(f"{source.document_id}:{source.chunk_id}:{source.title}" for source in sources),
    )


def _user_prompt(
    ticket: Ticket, sources: list[SourceReference], *, redact: bool = False
) -> str:
    source_blocks = []
    for index, source in enumerate(sources[:3], start=1):
        title = _context_value(source.title, limit=200, redact=redact)
        path = "[LOCAL_PATH]" if redact else _context_value(source.path, limit=300)
        excerpt = _context_value(source.excerpt, limit=_REMOTE_SOURCE_LIMIT, redact=redact)
        source_blocks.append(
            f"Source {index}: {title}\nPath: {path}\nExcerpt: {excerpt}"
        )
    source_text = "\n\n".join(source_blocks) if source_blocks else "No local sources found."
    client = "[CLIENT]" if redact else _context_value(ticket.client, limit=200)
    return (
        f"Ticket client: {client}\n"
        f"Ticket subject: {_context_value(ticket.subject, redact=redact)}\n"
        f"Ticket body: {_context_value(ticket.body, redact=redact)}\n"
        f"Ticket classification: {_classify_ticket_for_prompt(ticket)}\n\n"
        f"Top local source excerpts:\n{source_text}\n\n"
        'Return JSON like {"summary":"...","suggested_response":"..."}'
    )


def _planning_system_prompt() -> str:
    return (
        "You assist a bounded MSP planner. Select only tool IDs from the supplied catalog. "
        "Do not explain, invent tools, claim execution, or return hidden reasoning. "
        'Return only JSON in the form {"tool_ids":["known-tool-id"]}. '
        "Return at most the requested number of IDs."
    )


def _planning_prompt(
    instruction: str,
    ticket: Ticket,
    sources: list[SourceReference],
    tools: list[dict[str, str]],
    *,
    max_tools: int,
    redact: bool = False,
) -> str:
    tool_lines = "\n".join(
        f"- {tool.get('id', '')}: {_context_value(tool.get('name', ''), limit=120, redact=redact)} — "
        f"{_context_value(tool.get('description', ''), limit=240, redact=redact)}"
        for tool in tools[:32]
    )
    source_lines = "\n".join(
        f"- {_context_value(source.title, limit=160, redact=redact)}: "
        f"{_context_value(source.excerpt, limit=_REMOTE_SOURCE_LIMIT, redact=redact)}"
        for source in sources[:3]
    ) or "No local sources found."
    client = "[CLIENT]" if redact else _context_value(ticket.client, limit=200)
    return (
        f"Instruction: {_context_value(instruction, limit=2_000, redact=redact)}\n"
        f"Ticket client: {client}\n"
        f"Ticket subject: {_context_value(ticket.subject, limit=500, redact=redact)}\n"
        f"Ticket body: {_context_value(ticket.body, limit=2_000, redact=redact)}\n"
        f"Local source excerpts:\n{source_lines}\n\n"
        f"Approved tool catalog:\n{tool_lines}\n\n"
        f"Select no more than {max_tools} tool IDs."
    )


def _planning_request_key(
    instruction: str,
    ticket: Ticket,
    sources: list[SourceReference],
    tools: list[dict[str, str]],
    max_tools: int,
) -> tuple[str, ...]:
    return (
        instruction,
        ticket.id,
        ticket.client,
        ticket.subject,
        ticket.body,
        str(max_tools),
        *(f"{source.title}:{source.excerpt}" for source in sources[:3]),
        *(f"{tool.get('id', '')}:{tool.get('name', '')}:{tool.get('description', '')}" for tool in tools[:32]),
    )


def _system_prompt() -> str:
    return (
        "You assist MSP technicians with service-desk work. Use only the ticket and "
        "source excerpts provided. Do not claim that any action was executed. Return "
        "only JSON with summary and suggested_response fields."
    )


def _context_value(value: str, *, limit: int = _REMOTE_CONTEXT_LIMIT, redact: bool = False) -> str:
    bounded = value[:limit]
    if len(value) > limit:
        bounded += "…"
    if not redact:
        return bounded
    redacted = re.sub(r"(?i)\b[\w.+-]+@[\w.-]+\.[a-z]{2,}\b", "[REDACTED_EMAIL]", bounded)
    redacted = re.sub(
        r"(?i)\b(bearer\s+|api[_ -]?key\s*[:=]\s*|token\s*[:=]\s*|"
        r"password\s*[:=]\s*|secret\s*[:=]\s*)[^\s,;]+",
        r"\1[REDACTED]",
        redacted,
    )
    redacted = re.sub(r"\b(?:\+?\d[\d ()-]{7,}\d)\b", "[REDACTED_PHONE]", redacted)
    return redacted


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
        LOGGER.warning("local model response was not valid JSON")
        return None
    content = _message_content(payload)
    if not content:
        LOGGER.warning("local model response was empty")
        return None
    completion = _completion_from_content(content)
    if completion is None:
        LOGGER.warning("local model content was malformed")
    return completion


def _tool_selection_from_response(
    response: httpx.Response,
    *,
    max_tools: int,
    anthropic: bool = False,
) -> list[str] | None:
    try:
        payload = response.json()
    except json.JSONDecodeError:
        LOGGER.warning("model planner response was not valid JSON")
        return None
    content = (
        _anthropic_message_content(payload)
        if anthropic
        else _message_content(payload)
    )
    if not content:
        return None
    try:
        selection = json.loads(_strip_json_fence(content))
    except json.JSONDecodeError:
        return None
    if not isinstance(selection, dict) or not isinstance(selection.get("tool_ids"), list):
        return None
    selected: list[str] = []
    for tool_id in selection["tool_ids"]:
        if not isinstance(tool_id, str):
            return None
        normalized = tool_id.strip()
        if not normalized or normalized in selected:
            continue
        selected.append(normalized)
        if len(selected) >= max_tools:
            break
    return selected or None


def _completion_from_anthropic_response(response: httpx.Response) -> ModelCompletion | None:
    try:
        payload = response.json()
    except json.JSONDecodeError:
        LOGGER.warning("anthropic response was not valid JSON")
        return None
    if not isinstance(payload, dict):
        return None
    text = _anthropic_message_content(payload)
    return _completion_from_content(text) if text else None


def _anthropic_message_content(payload: object) -> str:
    if not isinstance(payload, dict):
        return ""
    content = payload.get("content")
    if not isinstance(content, list):
        return ""
    text_blocks = [
        item.get("text", "")
        for item in content
        if isinstance(item, dict) and item.get("type") == "text" and isinstance(item.get("text"), str)
    ]
    return "\n".join(text_blocks).strip()


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
    local_provider: ModelProvider
    if (
        settings.allow_llm_inference
        and settings.local_model_provider in SUPPORTED_LOCAL_MODEL_PROVIDERS
    ):
        local_provider = OpenAICompatibleLocalProvider(profile)
    else:
        local_provider = DeterministicLocalProvider(profile)

    remote = _remote_provider_from_settings(settings)
    if remote is not None:
        return FallbackModelProvider(local_provider, remote)
    return local_provider


def _remote_provider_from_settings(settings: Settings) -> RemoteModelProvider | None:
    provider = settings.remote_model_provider.strip().lower()
    if not (
        settings.allow_llm_inference
        and settings.allow_cloud_fallback
        and not settings.offline_mode
        and provider in SUPPORTED_REMOTE_MODEL_PROVIDERS
        and settings.remote_model_base_url.strip()
        and settings.remote_model_name.strip()
        and settings.remote_model_api_key.strip()
    ):
        return None
    return RemoteModelProvider(
        RemoteModelProfile(
            provider=provider,
            base_url=settings.remote_model_base_url,
            model=settings.remote_model_name,
            api_key=settings.remote_model_api_key,
            timeout_seconds=settings.remote_model_timeout_seconds,
            cloud_fallback_enabled=settings.allow_cloud_fallback,
        )
    )


def provider_metadata(settings: Settings, provider: ModelProvider | None = None) -> dict[str, str]:
    """Return safe provider/model labels for operational audit records."""
    metadata = {
        "provider": settings.local_model_provider or "deterministic",
        "model": settings.local_model_name,
    }
    if isinstance(provider, FallbackModelProvider):
        metadata["fallback_provider"] = provider.fallback.profile.provider
        metadata["fallback_model"] = provider.fallback.profile.model
    elif isinstance(provider, RemoteModelProvider):
        metadata = {"provider": provider.profile.provider, "model": provider.profile.model}
    return metadata


def _endpoint(base_url: str, path: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith("/v1") and path.startswith("v1/"):
        path = path[3:]
    return f"{base}/{path.lstrip('/')}"
