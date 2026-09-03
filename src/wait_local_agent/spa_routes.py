"""Dashboard routes shared by the production SPA fallback and UI route source.

The route set mirrors ``ui/src/routes.tsx`` so production deep-link behavior
matches the Vite development proxy. Drift is test-enforced.
"""

from typing import Final

SPA_ROUTE_PATHS: Final[frozenset[str]] = frozenset(
    {
        "/",
        "/login",
        "/clients",
        "/client-discovery",
        "/connectors",
        "/m365-actions",
        "/microsoft-admin",
        "/microsoft-admin/azure-lighthouse",
        "/microsoft-admin/access",
        "/settings/access",
        "/knowledge",
        "/workflows",
        "/automation/events",
        "/automation/schedules",
        "/activity/runs",
        "/workflow-designer",
        "/templates",
        "/playbooks",
        "/consultant",
        "/consultant/solution-delivery",
        "/collectors",
        "/reports",
        "/audit",
        "/scheduled-jobs",
        "/founder",
        "/tickets",
        "/approvals",
        "/analytics",
        "/agents",
        "/agent-platform",
        "/technician-chat",
        "/technician-path",
        "/backfills",
        "/executions",
        "/settings",
        "/system/appliance-health",
        "/system/diagnostics",
        "/system/extensions",
        "/integrations/mcp",
        "/integrations/connector-instances",
        "/integrations/smart-actions",
        "/smart-actions/runs",
        "/operations/reconciliation",
        "/end-user",
    }
)
