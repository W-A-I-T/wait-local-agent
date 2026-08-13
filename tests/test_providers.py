from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

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
    _response_usage_metadata,
    probe_model_providers,
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


def test_openai_provider_caches_plan_and_records_planner_transport_failure(
    tmp_path: Path,
) -> None:
    requests: list[httpx.Request] = []

    def success_handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": '{"tool_ids":["ticket-summary"]}'}},
                ]
            },
        )

    provider = OpenAICompatibleLocalProvider(
        _profile(tmp_path),
        transport=httpx.MockTransport(success_handler),
    )
    assert provider.select_tools("Investigate", _ticket(), [], [], max_tools=1) == [
        "ticket-summary"
    ]
    assert provider.select_tools("Investigate", _ticket(), [], [], max_tools=1) == [
        "ticket-summary"
    ]
    assert len(requests) == 1

    failing = OpenAICompatibleLocalProvider(
        _profile(tmp_path),
        transport=httpx.MockTransport(
            lambda request: httpx.Response(503, json={"error": "unavailable"})
        ),
    )
    with pytest.raises(ProviderUnavailableError, match="tool selection"):
        failing.select_tools("Investigate", _ticket(), [], [], max_tools=1)
    assert failing._last_call_metadata["usage_status"] == "provider_error"


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


def test_remote_provider_caches_plan_and_surfaces_planner_failures() -> None:
    requests: list[httpx.Request] = []

    def success_handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": '{"tool_ids":["ticket-summary"]}'}},
                ]
            },
        )

    provider = RemoteModelProvider(
        _remote_profile(),
        transport=httpx.MockTransport(success_handler),
    )
    assert provider.select_tools("Investigate", _ticket(), [], [], max_tools=1) == [
        "ticket-summary"
    ]
    assert provider.select_tools("Investigate", _ticket(), [], [], max_tools=1) == [
        "ticket-summary"
    ]
    assert len(requests) == 1

    for response in [
        httpx.Response(200, json={"choices": [{"message": {"content": "not json"}}]}),
        httpx.Response(503, json={"error": "unavailable"}),
    ]:
        failing = RemoteModelProvider(
            _remote_profile(),
            transport=httpx.MockTransport(lambda request, response=response: response),
        )
        with pytest.raises(ProviderUnavailableError, match="tool selection"):
            failing.select_tools("Investigate", _ticket(), [], [], max_tools=1)


def test_tool_selection_skips_blank_and_duplicate_ids() -> None:
    provider = RemoteModelProvider(
        _remote_profile(),
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "content": '{"tool_ids":[" ","ticket-summary",'
                                '"ticket-summary","knowledge-search"]}'
                            }
                        }
                    ]
                },
            )
        ),
    )

    assert provider.select_tools("Investigate", _ticket(), [], [], max_tools=2) == [
        "ticket-summary",
        "knowledge-search",
    ]


def test_fallback_provider_select_tools_handles_missing_and_unavailable_primary() -> None:
    remote = RemoteModelProvider(
        _remote_profile(),
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={
                    "choices": [
                        {"message": {"content": '{"tool_ids":["ticket-summary"]}'}},
                    ]
                },
            )
        ),
    )

    class NoPlanningProvider:
        def summarize_ticket(self, ticket: Ticket, sources: list[SourceReference]) -> str:
            return "summary"

        def draft_response(self, ticket: Ticket, sources: list[SourceReference]) -> str:
            return "response"

    class UnavailablePlanningProvider(NoPlanningProvider):
        def select_tools(
            self,
            instruction: str,
            ticket: Ticket,
            sources: list[SourceReference],
            tools: list[dict[str, str]],
            *,
            max_tools: int,
        ) -> list[str]:
            raise ProviderUnavailableError("primary planner unavailable")

    for primary in [NoPlanningProvider(), UnavailablePlanningProvider()]:
        assert FallbackModelProvider(primary, remote).select_tools(
            "Investigate", _ticket(), [], [], max_tools=1
        ) == ["ticket-summary"]


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
    assert provider_metadata(settings) == {
        "provider": "openai-compatible",
        "model": "llama3.1",
        "scope": "appliance-wide",
        "context_scope": "tenant-scoped",
    }
    fallback_metadata = provider_metadata(settings, FallbackModelProvider(local, remote))
    assert fallback_metadata["fallback_provider"] == "deepseek"
    assert "remote-secret" not in str(fallback_metadata)
    assert provider_metadata(settings, remote) == {
        "provider": "deepseek",
        "model": "documented-model",
        "scope": "appliance-wide",
        "context_scope": "tenant-scoped",
    }


def test_provider_metadata_records_reported_usage_without_inventing_cost(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "usage": {"prompt_tokens": 11, "completion_tokens": 7},
                "choices": [
                    {"message": {"content": '{"summary":"s","suggested_response":"r"}'}},
                ],
            },
        )

    provider = OpenAICompatibleLocalProvider(
        _profile(tmp_path), transport=httpx.MockTransport(handler)
    )
    provider.summarize_ticket(_ticket(), [])

    metadata = provider_metadata(_settings(tmp_path), provider)
    assert metadata["usage_status"] == "reported"
    assert metadata["input_tokens"] == 11
    assert metadata["output_tokens"] == 7
    assert metadata["total_tokens"] == 18
    assert metadata["cost_status"] == "not_configured"
    assert metadata["cost_usd"] is None


def test_provider_metadata_calculates_cost_only_from_explicit_operator_rates(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "usage": {"prompt_tokens": 11, "completion_tokens": 7},
                "choices": [
                    {"message": {"content": '{"summary":"s","suggested_response":"r"}'}},
                ],
            },
        )

    provider = OpenAICompatibleLocalProvider(
        _profile(tmp_path), transport=httpx.MockTransport(handler)
    )
    provider.summarize_ticket(_ticket(), [])

    metadata = provider_metadata(
        _settings(tmp_path, provider="deterministic"),
        provider,
    )
    assert metadata["cost_status"] == "not_configured"
    priced = provider_metadata(
        replace(
            _settings(tmp_path),
            model_input_cost_usd_per_million_tokens=1.0,
            model_output_cost_usd_per_million_tokens=2.0,
        ),
        provider,
    )
    assert priced["cost_status"] == "configured_estimate"
    assert priced["cost_usd"] == 0.000025


def test_provider_metadata_keeps_partial_usage_unpriced(tmp_path: Path) -> None:
    metadata = {
        **_response_usage_metadata(httpx.Response(200, json={"usage": {"prompt_tokens": 11}})),
    }
    from wait_local_agent.providers import _add_configured_cost

    _add_configured_cost(
        metadata,
        replace(
            _settings(tmp_path),
            model_input_cost_usd_per_million_tokens=1.0,
            model_output_cost_usd_per_million_tokens=2.0,
        ),
    )
    assert metadata["cost_status"] == "incomplete_usage"
    assert metadata["cost_usd"] is None


def test_fallback_metadata_uses_primary_local_usage(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "usage": {"prompt_tokens": 3, "completion_tokens": 2},
                "choices": [
                    {"message": {"content": '{"summary":"s","suggested_response":"r"}'}},
                ],
            },
        )

    local = OpenAICompatibleLocalProvider(
        _profile(tmp_path), transport=httpx.MockTransport(handler)
    )
    fallback = FallbackModelProvider(local, RemoteModelProvider(_remote_profile()))
    local.summarize_ticket(_ticket(), [])

    metadata = provider_metadata(_settings(tmp_path), fallback)
    assert metadata["input_tokens"] == 3
    assert metadata["output_tokens"] == 2
    assert metadata["total_tokens"] == 5


def test_fallback_metadata_uses_remote_usage_after_local_failure(tmp_path: Path) -> None:
    def local_failure(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("local provider unavailable", request=request)

    def remote_success(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "usage": {"prompt_tokens": 5, "completion_tokens": 4, "total_tokens": 9},
                "choices": [
                    {"message": {"content": '{"summary":"s","suggested_response":"r"}'}},
                ],
            },
        )

    fallback = FallbackModelProvider(
        OpenAICompatibleLocalProvider(
            _profile(tmp_path), transport=httpx.MockTransport(local_failure)
        ),
        RemoteModelProvider(
            _remote_profile(), transport=httpx.MockTransport(remote_success)
        ),
    )
    fallback.draft_response(_ticket(), [])

    metadata = provider_metadata(_settings(tmp_path), fallback)
    assert metadata["usage_status"] == "reported"
    assert metadata["total_tokens"] == 9


def test_usage_metadata_handles_partial_and_explicit_totals() -> None:
    explicit = _response_usage_metadata(
        httpx.Response(200, json={"usage": {"total_tokens": 4}})
    )
    assert explicit["usage_status"] == "reported"
    assert explicit["total_tokens"] == 4
    partial = _response_usage_metadata(
        httpx.Response(200, json={"usage": {"prompt_tokens": 2}})
    )
    assert partial["usage_status"] == "reported"
    assert partial["input_tokens"] == 2


def test_provider_health_keeps_deterministic_mode_local(tmp_path: Path) -> None:
    result = cast(dict[str, Any], probe_model_providers(
        replace(_settings(tmp_path), allow_llm_inference=False),
        transport=httpx.MockTransport(lambda request: pytest.fail("network probe not expected")),
    ))
    assert result["local"] == {
        "provider": "openai-compatible",
        "model": "llama3.1",
        "scope": "appliance-wide",
        "status": "ready",
        "probe": "not_required",
        "detail": "deterministic local mode",
    }
    assert result["remote"]["status"] == "not_configured"


def test_provider_health_probes_local_models_contract_and_reports_missing_model(tmp_path: Path) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"data": [{"id": "other-model"}, {"id": 42}, "bad-entry"]})

    result = cast(dict[str, Any], probe_model_providers(
        _settings(tmp_path),
        transport=httpx.MockTransport(handler),
    ))
    assert requests[0].url.path == "/v1/models"
    assert result["local"]["status"] == "model_unavailable"
    assert result["local"]["model_available"] is False


def test_provider_health_probes_anthropic_with_documented_headers(tmp_path: Path) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"data": [{"id": "documented-model"}]})

    settings = replace(
        _settings(tmp_path),
        allow_cloud_fallback=True,
        remote_model_provider="anthropic",
        remote_model_base_url="https://api.example/v1",
        remote_model_name="documented-model",
        remote_model_api_key="remote-secret",
    )
    result = cast(dict[str, Any], probe_model_providers(settings, transport=httpx.MockTransport(handler)))

    assert requests[1].url.path == "/v1/models"
    assert requests[1].headers["x-api-key"] == "remote-secret"
    assert requests[1].headers["anthropic-version"] == "2023-06-01"
    assert result["remote"]["status"] == "ready"
    assert "remote-secret" not in str(result)


def test_provider_health_uses_bearer_auth_for_openai_compatible_remote(tmp_path: Path) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"data": [{"id": "documented-model"}]})

    settings = replace(
        _settings(tmp_path, provider="deterministic"),
        allow_cloud_fallback=True,
        remote_model_provider="deepseek",
        remote_model_base_url="https://api.example/v1",
        remote_model_name="documented-model",
        remote_model_api_key="remote-secret",
    )
    result = cast(dict[str, Any], probe_model_providers(settings, transport=httpx.MockTransport(handler)))

    assert requests[0].headers["authorization"] == "Bearer remote-secret"
    assert result["remote"]["status"] == "ready"


def test_provider_health_reports_missing_local_base_url_without_network(tmp_path: Path) -> None:
    result = cast(
        dict[str, Any],
        probe_model_providers(
            replace(_settings(tmp_path), local_model_base_url=""),
            transport=httpx.MockTransport(lambda request: pytest.fail("probe not expected")),
        ),
    )
    assert result["local"]["status"] == "not_configured"


def test_provider_health_denies_remote_probe_in_offline_mode(tmp_path: Path) -> None:
    settings = replace(
        _settings(tmp_path, provider="deterministic"),
        allow_cloud_fallback=True,
        offline_mode=True,
        remote_model_provider="deepseek",
        remote_model_base_url="https://api.example/v1",
        remote_model_name="documented-model",
        remote_model_api_key="remote-secret",
    )
    result = cast(dict[str, Any], probe_model_providers(
        settings,
        transport=httpx.MockTransport(lambda request: pytest.fail("offline probe not expected")),
    ))
    assert result["remote"] == {
        "provider": "deepseek",
        "model": "documented-model",
        "scope": "appliance-wide",
        "status": "blocked_offline",
        "probe": "not_run",
    }


@pytest.mark.parametrize(
    ("response", "expected_status"),
    [
        (httpx.Response(503, json={"error": "unavailable"}), "unavailable"),
        (httpx.Response(200, json={"unexpected": []}), "malformed_response"),
    ],
)
def test_provider_health_reports_provider_failures_without_response_body(
    tmp_path: Path,
    response: httpx.Response,
    expected_status: str,
) -> None:
    result = cast(
        dict[str, Any],
        probe_model_providers(
            _settings(tmp_path),
            transport=httpx.MockTransport(lambda request: response),
        ),
    )
    assert result["local"]["status"] == expected_status
    assert "unavailable" not in str(result["local"].get("detail", ""))


def test_provider_health_reports_disabled_and_unsupported_remote_config(tmp_path: Path) -> None:
    disabled = cast(
        dict[str, Any],
        probe_model_providers(
            replace(
                _settings(tmp_path, provider="deterministic"),
                remote_model_provider="deepseek",
                remote_model_base_url="https://api.example/v1",
                remote_model_name="documented-model",
                remote_model_api_key="remote-secret",
            )
        ),
    )
    assert disabled["remote"]["status"] == "disabled"

    unsupported = cast(
        dict[str, Any],
        probe_model_providers(
            replace(
                _settings(tmp_path, provider="deterministic"),
                allow_cloud_fallback=True,
                remote_model_provider="vendor-without-adapter",
                remote_model_base_url="https://api.example/v1",
                remote_model_name="documented-model",
                remote_model_api_key="remote-secret",
            )
        ),
    )
    assert unsupported["remote"]["status"] == "unsupported_provider"


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


def test_openai_provider_retries_transient_failure_and_caches_recovery(
    tmp_path: Path,
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(
                503,
                headers={"Retry-After": "not-a-duration"},
                json={"error": "unavailable"},
            )
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

    assert provider.summarize_ticket(_ticket(), _sources()) == "Recovered model summary"
    assert provider.summarize_ticket(_ticket(), _sources()) == "Recovered model summary"
    assert len(requests) == 2
    assert provider._last_call_metadata["retry_count"] == 1


def test_openai_provider_bounds_transient_retries_and_records_retry_count(
    tmp_path: Path,
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(429, headers={"Retry-After": "0"}, json={"error": "rate limited"})

    provider = OpenAICompatibleLocalProvider(
        _profile(tmp_path),
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(ProviderUnavailableError):
        provider.summarize_ticket(_ticket(), _sources())
    assert len(requests) == 3
    assert provider._last_call_metadata == {
        "usage_status": "provider_error",
        "cost_status": "not_configured",
        "cost_usd": None,
        "retry_count": 2,
    }


def test_openai_provider_surfaces_connection_error(tmp_path: Path) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        raise httpx.ConnectError("connection refused", request=request)

    provider = OpenAICompatibleLocalProvider(
        _profile(tmp_path),
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(ProviderUnavailableError):
        provider.summarize_ticket(_ticket(), [])
    assert len(requests) == 3
    assert provider._last_call_metadata["retry_count"] == 2


def test_remote_provider_retries_transient_failure_and_records_metadata() -> None:
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
                            "content": '{"summary":"recovered","suggested_response":"response"}'
                        }
                    }
                ]
            },
        )

    provider = RemoteModelProvider(
        _remote_profile(),
        transport=httpx.MockTransport(handler),
    )

    assert provider.summarize_ticket(_ticket(), []) == "recovered"
    assert len(requests) == 2
    assert provider._last_call_metadata["retry_count"] == 1


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
            model="remote-model-test",
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
        deterministic.select_tools("Plan", _ticket(), [], [], max_tools=1)
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

    class NoPlanningProvider:
        def summarize_ticket(self, ticket: Ticket, sources: list[SourceReference]) -> str:
            return "summary"

        def draft_response(self, ticket: Ticket, sources: list[SourceReference]) -> str:
            return "response"

    assert FallbackModelProvider(NoPlanningProvider(), remote).select_next_tool(
        "Continue", _ticket(), [], [], None, []
    ) == "ticket-summary"


def test_remote_continuation_rejects_malformed_and_http_errors(tmp_path: Path) -> None:
    for response in [
        httpx.Response(200, json={"content": [{"type": "text", "text": "{}"}]}),
        httpx.Response(
            200,
            json={"content": [{"type": "text", "text": "not json"}]},
        ),
        httpx.Response(200, json=[]),
        httpx.Response(503, json={"error": "unavailable"}),
    ]:
        provider = RemoteModelProvider(
            RemoteModelProfile(
                provider="anthropic",
                base_url="https://api.anthropic.com",
                model="remote-model-test",
                api_key="remote-secret",
                timeout_seconds=5,
                cloud_fallback_enabled=True,
            ),
            transport=httpx.MockTransport(lambda request, response=response: response),
        )
        with pytest.raises(ProviderUnavailableError):
            provider.select_next_tool("Continue", _ticket(), [], [], None, [])
