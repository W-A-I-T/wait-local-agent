from __future__ import annotations

from dataclasses import replace
from typing import cast

import pytest

from wait_local_agent.mcp_client import McpClientError, McpToolCallResult
from wait_local_agent.smart_actions import SmartActionService
from wait_local_agent.store import Store
from wait_local_agent.workiq import (
    MAX_WORKIQ_ENTITY_PATHS,
    MAX_WORKIQ_RESULT_BYTES,
    WorkIqClient,
    WorkIqValidationError,
    _validate_entity_path,
    classify_work_iq_operation,
    classify_work_iq_request,
)


class FakeMcpClient:
    def __init__(self, result: McpToolCallResult | Exception) -> None:
        self.session_id: str | None = None
        self.result = result
        self.calls: list[tuple[str, dict[str, object]]] = []

    def initialize(self, *, client_name: str) -> str:
        self.session_id = "workiq-session"
        return self.session_id

    def call_tool(self, name: str, arguments: dict[str, object]) -> McpToolCallResult:
        self.calls.append((name, arguments))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def _result(payload: dict[str, object]) -> McpToolCallResult:
    return McpToolCallResult(
        content=[{"type": "text", "text": "unused"}],
        structured_content=payload,
        is_error=False,
    )


def test_workiq_fetch_is_bounded_and_uses_relative_read_paths(settings) -> None:
    fake = FakeMcpClient(_result({"results": [{"data": {"subject": "hello", "token": "secret"}}]}))
    client = WorkIqClient(settings, mcp_client=fake)

    response = client.fetch(["/me/messages?$top=10"])

    assert response.status == "ready"
    assert response.data["results"][0]["data"]["token"] == "[redacted]"
    assert fake.calls == [("fetch", {"entityUrls": ["/me/messages?$top=10"]})]

    for path in (
        "https://graph.microsoft.com/v1.0/me/messages",
        "/authentication/methods",
        "/servicePrincipals/abc",
        "/me/messages?$skip=10",
        "relative/messages",
    ):
        assert client.fetch([path]).status == "failed"
    assert client.fetch(["/me/messages"] * (MAX_WORKIQ_ENTITY_PATHS + 1)).status == "failed"


def test_workiq_operation_policy_fails_closed_for_generic_or_unknown_requests() -> None:
    assert classify_work_iq_operation("fetch", resource_paths=["/me/messages"]) == "read"
    assert classify_work_iq_operation("get_schema", resource_paths="/sites/example") == "read"
    assert classify_work_iq_operation("call_function", resource_paths="/search/query") == "function"
    assert classify_work_iq_operation("create_entity", resource_paths="/me/events") == "write"
    assert classify_work_iq_operation("unexpected", resource_paths="/me/messages") == "unknown"
    assert classify_work_iq_operation("fetch", resource_paths=["/authentication/methods"]) == "unknown"


def test_workiq_request_policy_considers_arguments_identity_tenant_and_local_policy() -> None:
    allowed = classify_work_iq_request(
        "fetch",
        arguments={"entityUrls": ["/me/messages"]},
        tenant="acme",
        identity="technician-1",
        local_policy={"allowed_operations": ["fetch"], "allowed_path_prefixes": ["/me/"]},
    )
    assert allowed.classification == "read"

    denied_path = classify_work_iq_request(
        "fetch",
        arguments={"entityUrls": ["/sites/contoso"]},
        tenant="acme",
        identity="technician-1",
        local_policy={"allowed_path_prefixes": ["/me/"]},
    )
    assert denied_path.classification == "blocked"

    assert classify_work_iq_request(
        "fetch",
        arguments={"entityUrls": ["/me/messages"]},
        tenant="acme",
        identity="technician-1",
        local_policy={"offline": True},
    ).classification == "blocked"
    assert classify_work_iq_request(
        "call_function",
        arguments={"functionUrl": "/me/calendarView"},
        tenant="acme",
        identity="technician-1",
    ).classification == "high-risk"
    assert classify_work_iq_request(
        "fetch",
        arguments={"entityUrls": ["/me/messages"]},
        tenant="",
        identity="technician-1",
    ).classification == "unknown"
    assert classify_work_iq_request(
        "fetch",
        arguments={"entityUrls": ["/me/messages"]},
        tenant="other",
        identity="technician-1",
        local_policy={"tenant_id": "acme"},
    ).classification == "blocked"
    assert classify_work_iq_request(
        "fetch",
        arguments={"entityUrls": ["/me/messages"]},
        tenant="acme",
        identity="technician-1",
        local_policy={"allowed_identities": ["technician-2"]},
    ).classification == "blocked"
    assert classify_work_iq_request(
        "fetch",
        arguments={"entityUrls": ["/me/messages"]},
        tenant="acme",
        identity=None,
        local_policy={"require_identity": True},
    ).classification == "blocked"
    assert classify_work_iq_request(
        "fetch",
        arguments={"entityUrls": ["/me/messages"]},
        tenant="acme",
        identity="technician-1",
        local_policy={"allowed_identities": "technician-1"},
    ).classification == "unknown"


def test_workiq_client_blocks_before_mcp_when_local_policy_denies(settings) -> None:
    fake = FakeMcpClient(_result({"results": []}))
    client = WorkIqClient(settings, mcp_client=fake)

    response = client.fetch(
        ["/me/messages"],
        tenant_id="acme",
        identity="technician-1",
        local_policy={"offline": True},
    )

    assert response.status == "failed"
    assert response.classification == "blocked"
    assert fake.calls == []


def test_workiq_schema_search_not_configured_and_remote_failures(settings) -> None:
    fake = FakeMcpClient(_result({"paths": [{"path": "/me/messages", "operations": ["fetch"]}]}))
    client = WorkIqClient(settings, mcp_client=fake)
    assert client.search_paths("messages").status == "ready"
    assert client.get_fetch_schema("/me/messages").status == "ready"
    assert fake.calls[-1] == (
        "get_schema",
        {"path": "/me/messages", "operationType": "fetch", "format": "jsonschema"},
    )
    assert client.search_paths(" ").status == "failed"
    assert client.search_paths("x" * 201).status == "failed"
    assert client.get_fetch_schema("/users/abc").status == "ready"

    assert WorkIqClient(settings).fetch(["/me/messages"]).status == "not_configured"
    broken = WorkIqClient(settings, mcp_client=FakeMcpClient(McpClientError("remote secret")))
    assert broken.fetch(["/me/messages"]).status == "failed"
    tool_failed = WorkIqClient(
        settings,
        mcp_client=FakeMcpClient(
            McpToolCallResult([], {"error_detail": "remote failure"}, True)
        ),
    )
    assert tool_failed.fetch(["/me/messages"]).message == "remote failure"
    no_detail = WorkIqClient(
        settings,
        mcp_client=FakeMcpClient(McpToolCallResult([], {}, True)),
    )
    assert no_detail.fetch(["/me/messages"]).message == "Work IQ MCP tool call failed"


def test_workiq_payload_fallback_and_result_bounds(settings) -> None:
    text_client = WorkIqClient(
        settings,
        mcp_client=FakeMcpClient(
            McpToolCallResult(
                [{"type": "text", "text": '{"results": [{"id": "1"}]}'}],
                None,
                False,
            )
        ),
    )
    assert text_client.fetch(["/me/messages"]).data["results"]
    plain_client = WorkIqClient(
        settings,
        mcp_client=FakeMcpClient(McpToolCallResult([{"type": "text", "text": "plain"}], None, False)),
    )
    assert plain_client.fetch(["/me/messages"]).data["text"] == "plain"
    list_client = WorkIqClient(
        settings,
        mcp_client=FakeMcpClient(McpToolCallResult([{"type": "text", "text": "[1, 2]"}], None, False)),
    )
    assert list_client.fetch(["/me/messages"]).data["value"] == [1, 2]
    empty_client = WorkIqClient(settings, mcp_client=FakeMcpClient(McpToolCallResult([], None, False)))
    assert empty_client.fetch(["/me/messages"]).data == {}
    malformed_content = WorkIqClient(
        settings,
        mcp_client=FakeMcpClient(
            McpToolCallResult([{"type": "image", "data": "x"}, {"type": "text", "text": 3}], None, False)
        ),
    )
    assert malformed_content.fetch(["/me/messages"]).data == {}
    oversized = WorkIqClient(
        settings,
        mcp_client=FakeMcpClient(_result({"results": "x" * MAX_WORKIQ_RESULT_BYTES})),
    )
    assert oversized.fetch(["/me/messages"]).status == "failed"


def test_workiq_validation_edges_and_configured_endpoint(settings) -> None:
    configured = WorkIqClient(
        replace(
            settings,
            work_iq_mcp_endpoint="https://workiq.example.test/mcp",
            work_iq_mcp_access_token="access-token",
            mcp_client_allowed_hosts=("workiq.example.test",),
        )
    )
    assert configured._mcp_client is not None  # noqa: SLF001
    assert WorkIqClient(settings).fetch([]).status == "failed"
    assert WorkIqClient(settings).fetch(cast(list[str], [3])).status == "failed"
    assert WorkIqClient(settings).fetch(["/me/\x01messages"]).status == "failed"
    assert WorkIqClient(settings).fetch(["/admin/messages"]).status == "failed"
    assert WorkIqClient(settings).get_fetch_schema("relative").status == "failed"
    assert WorkIqClient(settings).get_fetch_schema("").status == "failed"


def test_workiq_endpoint_requires_non_empty_token_before_client_creation(settings, monkeypatch) -> None:
    constructed = False

    def fail_if_constructed(*args, **kwargs):
        nonlocal constructed
        constructed = True
        raise AssertionError("tokenless Work IQ endpoint must not construct an MCP client")

    monkeypatch.setattr("wait_local_agent.workiq.McpClient", fail_if_constructed)
    for token in ("", "   "):
        client = WorkIqClient(
            replace(
                settings,
                work_iq_mcp_endpoint="https://workiq.example.test/mcp",
                work_iq_mcp_access_token=token,
            )
        )

        assert client._mcp_client is None  # noqa: SLF001
        response = client.fetch(["/me/messages"])
        assert response.status == "not_configured"
        assert response.classification == "read"

    assert constructed is False


def test_workiq_injected_client_still_works_without_configured_token(settings) -> None:
    fake = FakeMcpClient(_result({"results": []}))
    client = WorkIqClient(
        replace(
            settings,
            work_iq_mcp_endpoint="https://workiq.example.test/mcp",
            work_iq_mcp_access_token="",
        ),
        mcp_client=fake,
    )

    assert client.fetch(["/me/messages"]).status == "ready"
    assert fake.calls == [("fetch", {"entityUrls": ["/me/messages"]})]


def test_workiq_operation_classifier_and_path_validation_fail_closed(settings) -> None:
    assert classify_work_iq_operation(None) == "unknown"
    assert classify_work_iq_operation("do_action") == "action"
    assert classify_work_iq_operation("fetch", resource_paths=[3]) == "unknown"
    assert classify_work_iq_operation("fetch", resource_paths=[], operation="write") == "unknown"
    assert classify_work_iq_operation("get_schema", resource_paths=3) == "unknown"
    assert classify_work_iq_operation("get_schema", resource_paths="/admin/items") == "unknown"
    client = WorkIqClient(settings, mcp_client=FakeMcpClient(_result({})))
    assert client._read("create_entity", {"path": "/me/items"}).status == "failed"  # noqa: SLF001
    for value in (None, "", "x" * 501, "https://graph.example/me/items", "/me/\x01items"):
        with pytest.raises(WorkIqValidationError):
            _validate_entity_path(value)  # type: ignore[arg-type]


def test_workiq_smart_action_is_tenant_scoped_and_read_only(settings) -> None:
    fake = FakeMcpClient(_result({"results": [{"data": {"id": "1"}}]}))
    service = SmartActionService(
        Store(settings.data_path),
        settings,
        work_iq_client=WorkIqClient(settings, mcp_client=fake),
    )
    success = service.invoke(
        "workiq-fetch",
        {"client_id": "acme", "entity_urls": ["/me/messages"]},
        "actor",
        client_id="acme",
    )

    assert success.status == "success"
    assert success.output["connector_status"] == "ready"
    assert success.evidence[0]["classification"] == "read"
    assert fake.calls[0][0] == "fetch"
    outside = service.invoke(
        "workiq-fetch",
        {"client_id": "other", "entity_urls": ["/me/messages"]},
        "actor",
        client_id="acme",
    )
    assert outside.status == "failed"

    for payload in (
        {"client_id": "", "entity_urls": ["/me/messages"]},
        {"client_id": "acme", "entity_urls": "not-an-array"},
        {"client_id": "acme", "entity_urls": [3]},
    ):
        invalid = service.invoke("workiq-fetch", cast(dict[str, object], payload), "actor", client_id="acme")
        assert invalid.status == "failed"

    malformed = SmartActionService(
        Store(settings.data_path),
        settings,
        work_iq_client=WorkIqClient(
            settings,
            mcp_client=FakeMcpClient(_result({"unexpected": []})),
        ),
    ).invoke(
        "workiq-fetch",
        {"client_id": "acme", "entity_urls": ["/me/messages"]},
        "actor",
        client_id="acme",
    )
    assert malformed.status == "failed"

    class ExplodingProvider:
        def fetch(self, _: list[str]):
            raise RuntimeError("unexpected")

    exploding = SmartActionService(
        Store(settings.data_path),
        settings,
        work_iq_client=ExplodingProvider(),  # type: ignore[arg-type]
    ).invoke(
        "workiq-fetch",
        {"client_id": "acme", "entity_urls": ["/me/messages"]},
        "actor",
        client_id="acme",
    )
    assert exploding.status == "failed"

    not_configured = SmartActionService(
        Store(settings.data_path),
        replace(settings, work_iq_mcp_endpoint=""),
    ).invoke(
        "workiq-fetch",
        {"client_id": "acme", "entity_urls": ["/me/messages"]},
        "actor",
        client_id="acme",
    )
    assert not_configured.status == "failed"
