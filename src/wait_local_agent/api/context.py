"""Shared dependencies supplied to API router factories."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import Depends, FastAPI
from slowapi import Limiter

from wait_local_agent.agents import AgentService
from wait_local_agent.autotask import AutotaskClient
from wait_local_agent.baseline import BaselineService
from wait_local_agent.collectors import CollectorService
from wait_local_agent.config import Settings
from wait_local_agent.confluence import ConfluenceClient
from wait_local_agent.connectwise import ConnectWiseClient
from wait_local_agent.event_dispatch import EventDispatcher
from wait_local_agent.halopsa import HaloPSAClient
from wait_local_agent.hudu import HuduClient
from wait_local_agent.itglue import ItGlueClient
from wait_local_agent.m365_graph import M365GraphClient
from wait_local_agent.mcp import WaitMcpServer
from wait_local_agent.notion import NotionClient
from wait_local_agent.operational_graph import OperationalGraphService
from wait_local_agent.rbac import AuthContext, Role, require_end_user, require_role
from wait_local_agent.reports.service import ReportService
from wait_local_agent.rmm import RmmInventoryProvider
from wait_local_agent.scalepad import ScalePadClient
from wait_local_agent.scheduler import SchedulerManager
from wait_local_agent.servicenow import ServiceNowClient
from wait_local_agent.services import TicketIntelligenceService
from wait_local_agent.sharepoint import SharePointClient
from wait_local_agent.smart_actions import SmartActionService
from wait_local_agent.store import Store
from wait_local_agent.syncro import SyncroClient
from wait_local_agent.teams_graph import TeamsGraphClient
from wait_local_agent.timezest import TimeZestClient
from wait_local_agent.update_channel import UpdateStatusCache
from wait_local_agent.vault import SecretVault

ViewerAccess = Annotated[AuthContext, Depends(require_role(Role.VIEWER))]
# A client picker must retain the authorized directory after selecting a client.
ClientDirectoryAccess = Annotated[AuthContext, Depends(require_role(Role.VIEWER, scope_client=False))]
TechnicianAccess = Annotated[AuthContext, Depends(require_role(Role.TECHNICIAN))]
AdminAccess = Annotated[AuthContext, Depends(require_role(Role.ADMIN))]
EndUserAccess = Annotated[AuthContext, Depends(require_end_user)]


@dataclass(frozen=True, slots=True)
class ApiContext:
    active_settings: Settings
    store: Store
    vault: SecretVault
    app: FastAPI
    limiter: Limiter
    service: TicketIntelligenceService
    rmm_provider: RmmInventoryProvider
    operational_graph_service: OperationalGraphService
    halopsa_client: HaloPSAClient
    hudu_client: HuduClient
    connectwise_client: ConnectWiseClient
    syncro_client: SyncroClient
    servicenow_client: ServiceNowClient
    autotask_client: AutotaskClient
    itglue_client: ItGlueClient
    confluence_client: ConfluenceClient
    notion_client: NotionClient
    sharepoint_client: SharePointClient
    timezest_client: TimeZestClient
    scalepad_client: ScalePadClient
    m365_client: M365GraphClient
    teams_client: TeamsGraphClient
    update_status_cache: UpdateStatusCache
    report_service: ReportService
    collector_service: CollectorService
    smart_action_service: SmartActionService
    agent_service: AgentService
    mcp_server: WaitMcpServer
    event_dispatcher: EventDispatcher
    baseline_service: BaselineService
    scheduler: SchedulerManager
    m365_graph_service_for_client: Callable[[str], OperationalGraphService]
    m365_health_configured: Callable[[], bool]
    connector_read_client: Callable[..., object]
    approval_view: Callable[[Any], dict[str, object]]


__all__ = [
    "AdminAccess",
    "ApiContext",
    "ClientDirectoryAccess",
    "EndUserAccess",
    "TechnicianAccess",
    "ViewerAccess",
]
