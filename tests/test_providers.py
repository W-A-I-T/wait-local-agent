from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from wait_local_agent.config import Settings
from wait_local_agent.models import SourceReference, Ticket
from wait_local_agent.providers import (
    DeterministicLocalProvider,
    FallbackModelProvider,
    LocalModelProfile,
    OpenAICompatibleLocalProvider,
    ProviderUnavailableError,
    RemoteModelProfile,
    RemoteModelProvider,
    provider_from_settings,
    provider_metadata,
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


def _remote_profile(provider: str = "deepseek") -> RemoteModelProfile:
    return RemoteModelProfile(
        provider=provider,
        base_url="https://provider.example/v1",
        model="documented-model",
        api_key="remote-secret",
        timeout_seconds=7.5,
        cloud_fallback_enabled=True,
    )


def test_provider_defaults_to_deterministic_when_inference_disabled(tmp_path: Path) -> None:
    provider = provider_from_settings(_settings(tmp_path, allow_llm_inference=False))

    assert isinstance(provider, DeterministicLocalProvider)
    assert "local documentation" in provider.summarize_ticket(_ticket(), [])
    assert "the local runbook" in provider.draft_response(_ticket(), [])


def test_provider_defaults_to_deterministic_for_unknown_mode(tmp_path: Path) -> None:
    provider = provider_from_settings(_settings(tmp_path, provider="unknown"))

    assert isinstance(provider, DeterministicLocalProvider)


def test_provider_uses_openai_provider_when_enabled(tmp_path: Path) -> None:
    provider = provider_from_settings(_settings(tmp_path, provider="ollama"))

    assert isinstance(provider, OpenAICompatibleLocalProvider)


def test_openai_provider_selects_bounded_catalog_tools(tmp_path: Path) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": '{"tool_ids":["knowledge-search","ticket-summary"]}'
                        }
                    }
                ]
            },
        )

    provider = OpenAICompatibleLocalProvider(
        _profile(tmp_path),
        transport=httpx.MockTransport(handler),
    )
    tools = [
        {"id": "knowledge-search", "name": "Search knowledge", "description": "Find local evidence."},
        {"id": "ticket-summary", "name": "Ticket summary", "description": "Summarize the ticket."},
    ]

    selected = provider.select_tools(
        "Investigate this ticket with local evidence.",
        _ticket(),
        _sources(),
        tools,
        max_tools=2,
    )

    assert selected == ["knowledge-search", "ticket-summary"]
    prompt = json.loads(requests[0].content)["messages"][1]["content"]
    assert "Investigate this ticket" in prompt
    assert "knowledge-search" in prompt
    assert "Shared Mailbox Runbook" in prompt


def test_remote_provider_plan_redacts_ticket_and_source_context() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": '{"tool_ids":["ticket-summary"]}'
                        }
                    }
                ]
            },
        )

    provider = RemoteModelProvider(
        _remote_profile(),
        transport=httpx.MockTransport(handler),
    )
    ticket = _ticket_with(
        "Investigate access",
        "password=super-secret and person@example.com " + "x" * 3000,
    )
    sources = [
        SourceReference(
            title="Private runbook",
            path="/tenant/acme/private.md",
            excerpt="token=source-secret " + "y" * 2000,
        )
    ]

    assert provider.select_tools(
        "Find the safest next step.",
        ticket,
        sources,
        [{"id": "ticket-summary", "name": "Ticket summary", "description": "Summarize."}],
        max_tools=1,
    ) == ["ticket-summary"]
    prompt = json.loads(requests[0].content)["messages"][1]["content"]
    assert "super-secret" not in prompt
    assert "source-secret" not in prompt
    assert "person@example.com" not in prompt
    assert "/tenant/acme/private.md" not in prompt
    assert "[CLIENT]" in prompt


def test_anthropic_provider_selects_tools_with_messages_contract() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={"content": [{"type": "text", "text": '{"tool_ids":["ticket-triage"]}'}]},
        )

    provider = RemoteModelProvider(
        _remote_profile("anthropic"),
        transport=httpx.MockTransport(handler),
    )

    assert provider.select_tools(
        "Triage this ticket.",
        _ticket(),
        [],
        [{"id": "ticket-triage", "name": "Ticket triage", "description": "Classify."}],
        max_tools=1,
    ) == ["ticket-triage"]
    assert str(requests[0].url) == "https://provider.example/v1/messages"
    assert requests[0].headers["x-api-key"] == "remote-secret"


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, text="not response json"),
        httpx.Response(200, json={"choices": []}),
        httpx.Response(200, json={"choices": [{"message": {"content": "not json"}}]}),
        httpx.Response(200, json={"choices": [{"message": {"content": '{"tool_ids":{}}'}}]}),
        httpx.Response(200, json={"choices": [{"message": {"content": '{"tool_ids":[1]}'}}]}),
    ],
)
def test_openai_provider_plan_rejects_invalid_response_shapes(
    tmp_path: Path, response: httpx.Response
) -> None:
    provider = OpenAICompatibleLocalProvider(
        _profile(tmp_path),
        transport=httpx.MockTransport(lambda request, response=response: response),
    )

    with pytest.raises(ProviderUnavailableError, match="tool selection"):
        provider.select_tools("Investigate", _ticket(), [], [], max_tools=2)


def test_openai_provider_rejects_malformed_tool_selection(tmp_path: Path) -> None:
    provider = OpenAICompatibleLocalProvider(
        _profile(tmp_path),
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={"choices": [{"message": {"content": '{"tool_ids":"not-a-list"}'}}]},
            )
        ),
    )

    with pytest.raises(ProviderUnavailableError, match="tool selection"):
        provider.select_tools("Investigate", _ticket(), [], [], max_tools=2)


def test_remote_provider_requires_cloud_opt_in(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    settings = Settings(
        **{
            **settings.__dict__,
            "allow_cloud_fallback": True,
            "remote_model_provider": "deepseek",
            "remote_model_base_url": "https://provider.example/v1",
            "remote_model_name": "documented-model",
            "remote_model_api_key": "remote-secret",
        }
    )

    provider = provider_from_settings(settings)

    assert isinstance(provider, FallbackModelProvider)

    local_only = Settings(
        **{**settings.__dict__, "allow_cloud_fallback": False}
    )
    assert isinstance(provider_from_settings(local_only), OpenAICompatibleLocalProvider)


def test_offline_mode_denies_explicit_remote_fallback(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    settings = Settings(
        **{
            **settings.__dict__,
            "allow_cloud_fallback": True,
            "offline_mode": True,
            "remote_model_provider": "deepseek",
            "remote_model_base_url": "https://provider.example/v1",
            "remote_model_name": "documented-model",
            "remote_model_api_key": "remote-secret",
        }
    )

    provider = provider_from_settings(settings)

    assert isinstance(provider, OpenAICompatibleLocalProvider)


@pytest.mark.parametrize("provider_name", ["deepseek", "kimi", "co" + "dex", "openai-compatible"])
def test_openai_compatible_remote_provider_labels_use_explicit_endpoint(provider_name: str) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": '{"summary":"summary","suggested_response":"response"}'
                        }
                    }
                ]
            },
        )

    provider = RemoteModelProvider(
        _remote_profile(provider_name),
        transport=httpx.MockTransport(handler),
    )

    assert provider.summarize_ticket(_ticket(), []) == "summary"
    assert str(requests[0].url) == "https://provider.example/v1/chat/completions"


def test_remote_openai_compatible_provider_redacts_and_bounds_context() -> None:
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
                                    "summary": "Remote summary",
                                    "suggested_response": "Remote response",
                                }
                            )
                        }
                    }
                ]
            },
        )

    provider = RemoteModelProvider(
        _remote_profile(),
        transport=httpx.MockTransport(handler),
    )
    ticket = _ticket_with(
        "User request",
        "password=super-secret and contact person@example.com " + "x" * 3000,
    )
    sources = [
        SourceReference(
            title="Private runbook",
            path="/tenant/acme/private.md",
            excerpt="token=source-secret " + "y" * 2000,
        )
    ]

    assert provider.summarize_ticket(ticket, sources) == "Remote summary"
    assert provider.draft_response(ticket, sources) == "Remote response"
    payload = json.loads(requests[0].content)
    prompt = payload["messages"][1]["content"]
    assert "super-secret" not in prompt
    assert "source-secret" not in prompt
    assert "person@example.com" not in prompt
    assert "/tenant/acme/private.md" not in prompt
    assert "[CLIENT]" in prompt
    assert len(prompt) < 7_000
    assert requests[0].headers["authorization"] == "Bearer remote-secret"


def test_anthropic_provider_uses_messages_contract() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "content": [
                    {
                        "type": "text",
                        "text": '{"summary":"Anthropic summary","suggested_response":"Anthropic response"}',
                    }
                ]
            },
        )

    provider = RemoteModelProvider(
        _remote_profile("anthropic"),
        transport=httpx.MockTransport(handler),
    )

    assert provider.summarize_ticket(_ticket(), _sources()) == "Anthropic summary"
    request = requests[0]
    assert str(request.url) == "https://provider.example/v1/messages"
    assert request.headers["x-api-key"] == "remote-secret"
    assert request.headers["anthropic-version"] == "2023-06-01"
    payload = json.loads(request.content)
    assert payload["model"] == "documented-model"
    assert payload["max_tokens"] == 512
    assert payload["messages"][0]["role"] == "user"
    assert provider.draft_response(_ticket(), _sources()) == "Anthropic response"


def test_remote_fallback_runs_only_after_local_provider_is_unavailable() -> None:
    def local_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": "offline"})

    def remote_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": '{"summary":"fallback summary","suggested_response":"fallback response"}'
                        }
                    }
                ]
            },
        )

    primary = OpenAICompatibleLocalProvider(
        _profile(Path(".")),
        transport=httpx.MockTransport(local_handler),
    )
    fallback = RemoteModelProvider(
        _remote_profile(),
        transport=httpx.MockTransport(remote_handler),
    )

    provider = FallbackModelProvider(primary, fallback)

    assert provider.summarize_ticket(_ticket(), []) == "fallback summary"
    assert provider.draft_response(_ticket(), []) == "fallback response"


def test_remote_provider_surfaces_malformed_output() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "nope"}}]})

    provider = RemoteModelProvider(
        _remote_profile(),
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(ProviderUnavailableError):
        provider.summarize_ticket(_ticket(), [])


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, text="not json"),
        httpx.Response(200, json=[]),
        httpx.Response(200, json={"content": "bad"}),
        httpx.Response(200, json={"content": [{"type": "image"}]}),
        httpx.Response(503, json={"error": "unavailable"}),
    ],
)
def test_anthropic_provider_surfaces_invalid_responses(response: httpx.Response) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return response

    provider = RemoteModelProvider(
        _remote_profile("anthropic"),
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(ProviderUnavailableError):
        provider.summarize_ticket(_ticket(), [])


def test_fallback_provider_draft_and_safe_metadata(tmp_path: Path) -> None:
    local = DeterministicLocalProvider(_profile(tmp_path))

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": '{"summary":"s","suggested_response":"r"}'
                        }
                    }
                ]
            },
        )

    remote = RemoteModelProvider(
        _remote_profile(),
        transport=httpx.MockTransport(handler),
    )
    settings = _settings(tmp_path, allow_llm_inference=False)

    assert FallbackModelProvider(local, remote).draft_response(_ticket(), [])
    assert provider_metadata(settings) == {"provider": "openai-compatible", "model": "llama3.1"}
    fallback_metadata = provider_metadata(settings, FallbackModelProvider(local, remote))
    assert fallback_metadata["fallback_provider"] == "deepseek"
    assert "remote-secret" not in str(fallback_metadata)
    assert provider_metadata(settings, remote) == {"provider": "deepseek", "model": "documented-model"}


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


def test_openai_provider_surfaces_malformed_json(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "not json"}}]})

    provider = OpenAICompatibleLocalProvider(
        _profile(tmp_path),
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(ProviderUnavailableError, match="no valid model completion"):
        provider.summarize_ticket(_ticket(), _sources())


def test_openai_provider_surfaces_invalid_response_shapes(tmp_path: Path) -> None:
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

        with pytest.raises(ProviderUnavailableError):
            provider.summarize_ticket(_ticket(), _sources())


def test_openai_provider_surfaces_empty_and_non_2xx_responses(tmp_path: Path) -> None:
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

        with pytest.raises(ProviderUnavailableError):
            provider.summarize_ticket(_ticket(), _sources())


def test_openai_provider_does_not_cache_failure_after_transient_failure(
    tmp_path: Path,
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(503, json={"error": "unavailable"})
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "summary": "Recovered model summary",
                                    "suggested_response": "Recovered model response",
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

    with pytest.raises(ProviderUnavailableError):
        provider.summarize_ticket(_ticket(), _sources())
    assert provider.summarize_ticket(_ticket(), _sources()) == "Recovered model summary"
    assert len(requests) == 2


def test_openai_provider_surfaces_connection_error(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    provider = OpenAICompatibleLocalProvider(
        _profile(tmp_path),
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(ProviderUnavailableError):
        provider.summarize_ticket(_ticket(), [])


def test_openai_provider_selects_one_continuation_tool_and_redacts_result(tmp_path: Path) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"tool_id":"ticket-summary"}'}}]},
        )

    provider = OpenAICompatibleLocalProvider(
        _profile(tmp_path),
        transport=httpx.MockTransport(handler),
    )
    selected = provider.select_next_tool(
        "Inspect the result and continue safely.",
        _ticket(),
        _sources(),
        [{"id": "ticket-summary", "name": "Ticket summary", "description": "Summarize"}],
        {"status": "success", "output": {"password": "secret"}},
        ["ticket-triage"],
    )

    assert selected == "ticket-summary"
    body = requests[0].content.decode()
    assert "secret" not in body
    assert "[REDACTED]" in body


def test_remote_anthropic_provider_selects_continuation_tool(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/messages"
        assert request.headers["x-api-key"] == "remote-secret"
        return httpx.Response(
            200,
            json={"content": [{"type": "text", "text": '{"tool_id":"ticket-summary"}'}]},
        )

    provider = RemoteModelProvider(
        RemoteModelProfile(
            provider="anthropic",
            base_url="https://api.anthropic.com",
            model="claude-test",
            api_key="remote-secret",
            timeout_seconds=5,
            cloud_fallback_enabled=True,
        ),
        transport=httpx.MockTransport(handler),
    )

    assert provider.select_next_tool(
        "Continue",
        _ticket(),
        _sources(),
        [{"id": "ticket-summary", "name": "Ticket summary", "description": "Summarize"}],
        {"status": "success"},
        [],
    ) == "ticket-summary"


def test_continuation_provider_failure_shapes_and_deterministic_mode(tmp_path: Path) -> None:
    deterministic = DeterministicLocalProvider(_profile(tmp_path))
    with pytest.raises(ProviderUnavailableError):
        deterministic.select_next_tool("Continue", _ticket(), [], [], None, [])

    for response in [
        httpx.Response(200, text="not json"),
        httpx.Response(200, json={"choices": []}),
        httpx.Response(503, json={"error": "unavailable"}),
    ]:
        provider = OpenAICompatibleLocalProvider(
            _profile(tmp_path),
            transport=httpx.MockTransport(lambda request, response=response: response),
        )
        with pytest.raises(ProviderUnavailableError):
            provider.select_next_tool("Continue", _ticket(), [], [], None, [])


def test_remote_openai_compatible_continuation_and_fallback(tmp_path: Path) -> None:
    remote = RemoteModelProvider(
        RemoteModelProfile(
            provider="deepseek",
            base_url="https://api.deepseek.com/v1",
            model="deepseek-chat",
            api_key="remote-secret",
            timeout_seconds=5,
            cloud_fallback_enabled=True,
        ),
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={"choices": [{"message": {"content": '{"tool_id":"ticket-summary"}'}}]},
            )
        ),
    )
    primary = DeterministicLocalProvider(_profile(tmp_path))
    fallback = FallbackModelProvider(primary, remote)
    assert fallback.select_next_tool("Continue", _ticket(), [], [], None, []) == "ticket-summary"


def test_remote_continuation_rejects_malformed_and_http_errors(tmp_path: Path) -> None:
    for response in [
        httpx.Response(200, json={"content": [{"type": "text", "text": "{}"}]}),
        httpx.Response(503, json={"error": "unavailable"}),
    ]:
        provider = RemoteModelProvider(
            RemoteModelProfile(
                provider="anthropic",
                base_url="https://api.anthropic.com",
                model="claude-test",
                api_key="remote-secret",
                timeout_seconds=5,
                cloud_fallback_enabled=True,
            ),
            transport=httpx.MockTransport(lambda request, response=response: response),
        )
        with pytest.raises(ProviderUnavailableError):
            provider.select_next_tool("Continue", _ticket(), [], [], None, [])
