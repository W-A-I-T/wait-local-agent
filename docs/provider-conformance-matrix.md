# Model-provider conformance matrix

This matrix is the evidence index for issue [#260](https://github.com/W-A-I-T/wait-local-agent/issues/260).
It describes the single provider boundary currently implemented by WAIT Local
Agent. A provider label is not a claim that WAIT ships credentials, a default
endpoint, uptime, or provider-native feature parity.

| Requirement | Contract / surface | Authoritative evidence | Status and boundary |
| --- | --- | --- | --- |
| Deterministic local mode | `provider_from_settings`, `DeterministicLocalProvider` | `tests/test_providers.py::test_provider_defaults_to_deterministic_when_inference_disabled`, `::test_provider_defaults_to_deterministic_for_unknown_mode` | Implemented; no model service or network call is required. |
| Local OpenAI-compatible inference | `OpenAICompatibleLocalProvider` with operator-supplied base URL/model | `tests/test_providers.py::test_openai_provider_sends_expected_request_payload`, malformed-response and connection-error tests | Implemented behind `WAIT_ALLOW_LLM_INFERENCE`; no endpoint is guessed. |
| Anthropic Messages adapter | `RemoteModelProvider(provider="anthropic")` | `::test_anthropic_provider_uses_messages_contract`, `::test_anthropic_provider_selects_tools_with_messages_contract`, health-header test | Implemented as a bounded Messages contract; provider-native features are not claimed. |
| DeepSeek, Kimi, coding-compatible, and generic OpenAI-compatible adapters | `RemoteModelProvider` with explicit operator-supplied endpoint/model | `::test_openai_compatible_remote_provider_labels_use_explicit_endpoint`, remote request/prompt tests | Implemented only when the operator supplies a documented compatible endpoint; WAIT does not invent provider URLs, model names, or authentication flows. |
| Explicit remote opt-in | `WAIT_ALLOW_LLM_INFERENCE`, `WAIT_ALLOW_CLOUD_FALLBACK`, complete `WAIT_REMOTE_MODEL_*` configuration | `::test_remote_provider_requires_cloud_opt_in`, `::test_offline_mode_denies_explicit_remote_fallback`, `tests/test_api.py` provider settings/health coverage | Implemented; remote calls are never required for basic local operation. |
| Offline enforcement | `WAIT_OFFLINE_MODE`, provider health API/CLI/UI | `::test_provider_health_denies_remote_probe_in_offline_mode`, `tests/test_cli.py`, `tests/test_api.py` | Implemented; status is `blocked_offline` and no probe/request is made. |
| Health and model readiness | `GET /settings/providers/health`, `wait-local-agent microsoft provider health` | health success, missing-model, malformed-response, unavailable, disabled, and unsupported-provider tests | Implemented as readiness evidence only; it is not an uptime or SLA claim. |
| Malformed output and provider errors | JSON shape validation and `ProviderUnavailableError` | malformed completion/tool/continuation tests in `tests/test_providers.py` | Implemented; failures remain explicit and do not become empty or fake success. |
| Timeout, rate limit, and bounded retry | Fixed three-attempt request budget for transient transport/408/429/5xx failures | `::test_openai_provider_bounds_transient_retries_and_records_retry_count`, `::test_openai_provider_surfaces_connection_error`, `::test_remote_provider_retries_transient_failure_and_records_metadata` | Implemented; retry metadata is bounded and redaction-safe. |
| Deterministic fallback | `FallbackModelProvider` | `::test_remote_fallback_runs_only_after_local_provider_is_unavailable`, fallback metadata tests | Implemented; fallback occurs only after local provider unavailability and remains explicitly configured. |
| Redaction and bounded context | Remote prompt construction and provider metadata | `::test_remote_openai_compatible_provider_redacts_and_bounds_context`, `::test_remote_provider_plan_redacts_ticket_and_source_context`, metadata tests | Implemented for WAIT-controlled prompts/metadata; external provider-side logging is outside WAIT evidence. |
| Usage and cost metadata | Provider-reported usage plus operator-supplied rates | provider usage/cost tests and analytics coverage | Implemented as reported usage or clearly labeled estimate; no pricing is inferred. |
| Tenant/client isolation | Runtime scope, route authorization, and tenant-scoped persisted context | `tests/test_rbac.py`, `tests/test_consultant.py`, `tests/test_agents.py`, `tests/test_runtime_scope.py`, enterprise validation matrix | Implemented at the runtime boundary. Provider adapters receive bounded ticket/source context and no tenant authority shortcut; provider tests alone cannot prove route/store isolation. |
| Remote-provider live conformance | Real credentials, external availability, provider SLA, provider-native lifecycle/cost APIs | No repository evidence | Intentionally unverified; requires operator credentials and external coordination. |

## Interpretation

The local and mocked provider contract is covered by repository tests. The
remote rows prove request shape, opt-in, redaction, bounded failure behavior,
and safe metadata with fakes; they do not prove that a particular tenant's
credentials or endpoint is reachable. Live-provider evidence remains an
explicit deployment/customer prerequisite.

The model boundary does not receive hidden chain-of-thought, tenant IDs as
authority inputs, provider credentials in prompts, or arbitrary tool commands.
Deterministic runtime policy remains authoritative for tenant scope, roles,
approvals, evidence, and safety decisions.
