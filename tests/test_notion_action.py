from __future__ import annotations

from dataclasses import replace
from typing import Literal, cast

from wait_local_agent.models import ConnectorReadResult
from wait_local_agent.notion import NotionPage, NotionReadResponse
from wait_local_agent.smart_actions import ActionContext, NotionDocumentationSearchAction
from wait_local_agent.store import Store

PAGE_ID = "11111111-2222-3333-4444-555555555555"


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
