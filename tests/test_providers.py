from __future__ import annotations

import json
from pathlib import Path

import httpx

from wait_local_agent.config import Settings
from wait_local_agent.models import SourceReference, Ticket
from wait_local_agent.providers import (
    DeterministicLocalProvider,
    LocalModelProfile,
    OpenAICompatibleLocalProvider,
    provider_from_settings,
)


def _settings(
    tmp_path: Path,
    *,
    provider: str = "openai-compatible",
    allow_llm_inference: bool = True,
) -> Settings:
    return Settings(
        data_path=tmp_path / "state.db",
        allowed_doc_root=Path("examples/sample_docs"),
        allow_write_actions=False,
        allow_http_probing=False,
        allow_cloud_fallback=False,
        allow_llm_inference=allow_llm_inference,
        local_model_provider=provider,
        local_model_base_url="http://127.0.0.1:11434/v1",
        local_model_name="llama3.1",
        local_model_timeout_seconds=7.5,
        vector_backend="sqlite",
    )


def _ticket() -> Ticket:
    return Ticket(
        id="TCK-1",
        client="Acme Dental",
        subject="Shared mailbox permissions",
        body="Please give Pat access to the billing shared mailbox.",
        priority="medium",
        status="open",
    )


def _ticket_with(subject: str, body: str, ticket_id: str = "TCK-2") -> Ticket:
    return Ticket(
        id=ticket_id,
        client="Northwind",
        subject=subject,
        body=body,
        priority="low",
        status="open",
    )


def _sources() -> list[SourceReference]:
    return [
        SourceReference(
            title="Shared Mailbox Runbook",
            path="examples/sample_docs/shared-mailbox.md",
            excerpt="Confirm the requester, target mailbox, and approval before changing access.",
            document_id=1,
            chunk_id=2,
        )
    ]


def _profile(tmp_path: Path) -> LocalModelProfile:
    settings = _settings(tmp_path)
    return LocalModelProfile(
        provider=settings.local_model_provider,
        base_url=settings.local_model_base_url,
        model=settings.local_model_name,
        inference_enabled=settings.allow_llm_inference,
        timeout_seconds=settings.local_model_timeout_seconds,
        cloud_fallback_enabled=settings.allow_cloud_fallback,
    )


def test_provider_defaults_to_deterministic_when_inference_disabled(tmp_path: Path) -> None:
    provider = provider_from_settings(_settings(tmp_path, allow_llm_inference=False))

    assert isinstance(provider, DeterministicLocalProvider)


def test_provider_defaults_to_deterministic_for_unknown_mode(tmp_path: Path) -> None:
    provider = provider_from_settings(_settings(tmp_path, provider="unknown"))

    assert isinstance(provider, DeterministicLocalProvider)


def test_provider_uses_openai_provider_when_enabled(tmp_path: Path) -> None:
    provider = provider_from_settings(_settings(tmp_path, provider="ollama"))

    assert isinstance(provider, OpenAICompatibleLocalProvider)


def test_openai_provider_sends_expected_request_payload(tmp_path: Path) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "summary": "Model summary",
                                    "suggested_response": "Model response",
                                }
                            )
                        }
                    }
                ]
            },
        )

    provider = OpenAICompatibleLocalProvider(
        _profile(tmp_path),
        transport=httpx.MockTransport(handler),
    )

    summary = provider.summarize_ticket(_ticket(), _sources())
    draft = provider.draft_response(_ticket(), _sources())

    assert summary == "Model summary"
    assert draft == "Model response"
    assert len(requests) == 1
    assert str(requests[0].url) == "http://127.0.0.1:11434/v1/chat/completions"
    payload = json.loads(requests[0].content)
    assert payload["model"] == "llama3.1"
    assert payload["stream"] is False
    assert payload["messages"][0]["role"] == "system"
    assert "Shared Mailbox Runbook" in payload["messages"][1]["content"]
    assert "collaboration-change" in payload["messages"][1]["content"]


def test_openai_provider_prompt_includes_other_classifications(tmp_path: Path) -> None:
    prompts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        prompts.append(payload["messages"][1]["content"])
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "summary": "Model summary",
                                    "suggested_response": "Model response",
                                }
                            )
                        }
                    }
                ]
            },
        )

    provider = OpenAICompatibleLocalProvider(
        _profile(tmp_path),
        transport=httpx.MockTransport(handler),
    )

    provider.summarize_ticket(_ticket_with("MFA reset", "User cannot sign-in", "TCK-2"), [])
    provider.summarize_ticket(
        _ticket_with("Printer offline", "Disk alert also appeared", "TCK-3"),
        [],
    )
    provider.summarize_ticket(_ticket_with("Question", "Need help with a request", "TCK-4"), [])

    assert "identity-access" in prompts[0]
    assert "endpoint-triage" in prompts[1]
    assert "general-service-desk" in prompts[2]
    assert "No local sources found." in prompts[2]


def test_openai_provider_accepts_json_code_fence(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": (
                                '```json\n{"summary":"Fenced summary",'
                                '"suggested_response":"Fenced response"}\n```'
                            )
                        }
                    }
                ]
            },
        )

    provider = OpenAICompatibleLocalProvider(
        _profile(tmp_path),
        transport=httpx.MockTransport(handler),
    )

    assert provider.summarize_ticket(_ticket(), _sources()) == "Fenced summary"


def test_openai_provider_falls_back_on_malformed_json(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "not json"}}]})

    provider = OpenAICompatibleLocalProvider(
        _profile(tmp_path),
        transport=httpx.MockTransport(handler),
    )

    summary = provider.summarize_ticket(_ticket(), _sources())
    draft = provider.draft_response(_ticket(), _sources())

    assert "Acme Dental needs help" in summary
    assert "A technician will confirm" in draft


def test_openai_provider_falls_back_on_invalid_response_shapes(tmp_path: Path) -> None:
    invalid_responses = [
        httpx.Response(200, text="not response json"),
        httpx.Response(200, json=[]),
        httpx.Response(200, json={"choices": ["bad"]}),
        httpx.Response(200, json={"choices": [{"message": "bad"}]}),
        httpx.Response(200, json={"choices": [{"message": {"content": {"bad": "shape"}}}]}),
        httpx.Response(200, json={"choices": [{"message": {"content": "[]"}}]}),
        httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"summary":"Only summary"}'}}]},
        ),
        httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": '{"summary":" ","suggested_response":" "}'}}]
            },
        ),
        httpx.Response(200, json={"choices": [{"message": {"content": "```json\n{}"}}]}),
    ]

    for response in invalid_responses:

        def handler(request: httpx.Request, response: httpx.Response = response) -> httpx.Response:
            return response

        provider = OpenAICompatibleLocalProvider(
            _profile(tmp_path),
            transport=httpx.MockTransport(handler),
        )

        assert "Acme Dental needs help" in provider.summarize_ticket(_ticket(), _sources())


def test_openai_provider_falls_back_on_empty_and_non_2xx_responses(tmp_path: Path) -> None:
    for response in [
        httpx.Response(200, json={"choices": []}),
        httpx.Response(503, json={"error": "unavailable"}),
    ]:

        def handler(request: httpx.Request, response: httpx.Response = response) -> httpx.Response:
            return response

        provider = OpenAICompatibleLocalProvider(
            _profile(tmp_path),
            transport=httpx.MockTransport(handler),
        )

        assert "Acme Dental needs help" in provider.summarize_ticket(_ticket(), _sources())


def test_openai_provider_falls_back_on_connection_error(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    provider = OpenAICompatibleLocalProvider(
        _profile(tmp_path),
        transport=httpx.MockTransport(handler),
    )

    assert "local documentation" in provider.summarize_ticket(_ticket(), [])
