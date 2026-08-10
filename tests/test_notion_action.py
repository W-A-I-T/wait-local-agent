from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from typing import Literal, cast

from wait_local_agent.models import ConnectorReadResult
from wait_local_agent.notion import NotionPage, NotionReadResponse
from wait_local_agent.smart_actions import (
    ActionContext,
    NotionDataSourceQueryAction,
    NotionDocumentationSearchAction,
)
from wait_local_agent.store import Store

PAGE_ID = "11111111-2222-3333-4444-555555555555"
DATA_SOURCE_ID = "66666666-7777-8888-9999-000000000000"


class FakeNotionClient:
    def __init__(self, *, status: Literal["ready", "failed"] = "ready") -> None:
        self.status = status

    def search_pages(self, *, client_id: str, query: str, page_size: int) -> NotionReadResponse:
        if self.status != "ready":
            return NotionReadResponse(ConnectorReadResult(self.status, "provider unavailable"), [])
        return NotionReadResponse(
            ConnectorReadResult("ready", "search ok", 1),
            [NotionPage(PAGE_ID, "MFA runbook", "", "", False, "")],
        )

    def get_page(self, page_id: str, *, client_id: str) -> NotionReadResponse:
        return NotionReadResponse(
            ConnectorReadResult("ready", "page ok", 1),
            [NotionPage(PAGE_ID, "MFA runbook", "", "", False, "Rotate MFA keys.")],
        )

    def query_data_source(
        self, data_source_id: str, *, client_id: str, page_size: int, start_cursor: str
    ) -> NotionReadResponse:
        return NotionReadResponse(
            ConnectorReadResult("ready", "query ok", 1),
            [NotionPage(PAGE_ID, "MFA runbook", "/page", "", False, "")],
            "next-cursor",
        )


def _context(settings, client) -> ActionContext:
    active = replace(settings, client_id="acme")
    return ActionContext(
        store=Store(active.data_path),
        settings=active,
        client_id="acme",
        notion_client=client,
    )


def test_notion_action_searches_and_retrieves_scoped_markdown(settings) -> None:
    result = NotionDocumentationSearchAction().run(
        _context(settings, FakeNotionClient()),
        {"query": "MFA", "client_id": "acme", "limit": 1},
    )

    assert result.status == "success"
    assert result.output["count"] == 1
    pages = cast(list[dict[str, object]], result.output["pages"])
    assert pages[0]["markdown"] == "Rotate MFA keys."
    assert result.evidence[0]["connector"] == "notion"


def test_notion_action_rejects_cross_tenant_and_provider_failure(settings) -> None:
    action = NotionDocumentationSearchAction()
    cross_tenant = action.run(
        _context(settings, FakeNotionClient()),
        {"query": "MFA", "client_id": "other"},
    )
    failed = action.run(
        _context(settings, FakeNotionClient(status="failed")),
        {"query": "MFA", "client_id": "acme"},
    )

    assert cross_tenant.status == "failed"
    assert "outside the tenant scope" in cross_tenant.error_detail
    assert failed.status == "failed"
    assert cast(list[object], failed.output["pages"]) == []
    assert failed.error_detail == "provider unavailable"


def test_notion_data_source_action_is_scoped_and_bounded(settings) -> None:
    result = NotionDataSourceQueryAction().run(
        _context(settings, FakeNotionClient()),
        {"data_source_id": DATA_SOURCE_ID, "client_id": "acme", "limit": 1},
    )

    assert result.status == "success"
    assert result.output["count"] == 1
    assert result.output["next_cursor"] == "next-cursor"
    assert result.evidence[0]["operation"] == "data-sources.query"

    cross_tenant = NotionDataSourceQueryAction().run(
        _context(settings, FakeNotionClient()),
        {"data_source_id": DATA_SOURCE_ID, "client_id": "other"},
    )
    assert cross_tenant.status == "failed"
    assert "outside the tenant scope" in cross_tenant.error_detail


def test_notion_data_source_action_rejects_bad_inputs_and_provider_edges(settings) -> None:
    context = _context(settings, FakeNotionClient())
    action = NotionDataSourceQueryAction()
    for payload in (
        {"data_source_id": "", "client_id": "acme"},
        {"data_source_id": DATA_SOURCE_ID, "client_id": ""},
        {"data_source_id": DATA_SOURCE_ID, "client_id": "acme", "limit": 0},
        {"data_source_id": DATA_SOURCE_ID, "client_id": "acme", "start_cursor": 1},
    ):
        assert action.run(context, cast(dict[str, object], payload)).status == "failed"

    class RaisingClient(FakeNotionClient):
        def query_data_source(self, *args, **kwargs):
            raise RuntimeError("provider failed")

    assert action.run(
        _context(settings, RaisingClient()),
        {"data_source_id": DATA_SOURCE_ID, "client_id": "acme"},
    ).error_detail == "Notion data-source query failed"

    class MalformedClient(FakeNotionClient):
        def query_data_source(self, *args, **kwargs):
            return SimpleNamespace(
                result=ConnectorReadResult("ready", "ok"), items="not-a-list"
            )

    assert action.run(
        _context(settings, MalformedClient()),
        {"data_source_id": DATA_SOURCE_ID, "client_id": "acme"},
    ).error_detail == "Notion returned malformed data-source rows"

    class FailedClient(FakeNotionClient):
        def query_data_source(self, *args, **kwargs):
            return NotionReadResponse(ConnectorReadResult("failed", "secret=hidden"), [])

    failed = action.run(
        _context(settings, FailedClient()),
        {"data_source_id": DATA_SOURCE_ID, "client_id": "acme"},
    )
    assert failed.status == "failed"
    assert failed.error_detail == "secret=[redacted]"
