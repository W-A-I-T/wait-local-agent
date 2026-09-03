import { lazy, Suspense } from "react";
import { Navigate, Route, Routes, useParams } from "react-router-dom";
import { Approvals } from "./screens/Approvals";
import { Analytics } from "./screens/Analytics";
import { Agents } from "./screens/Agents";
import { AgentPlatform } from "./screens/AgentPlatform";
import { ActivityRuns } from "./screens/ActivityRuns";
import { Connectors } from "./screens/Connectors";
import { Consultant } from "./screens/Consultant";
import { SolutionDelivery } from "./screens/SolutionDelivery";
import { Collectors } from "./screens/Collectors";
import { FounderJourney } from "./surfaces/founder/FounderJourney";
import { Knowledge } from "./screens/Knowledge";
import { Overview } from "./screens/Overview";
import { Audit } from "./screens/Audit";
import { Reports } from "./screens/Reports";
import { Workflows } from "./screens/Workflows";
import { WorkflowDesigner } from "./screens/WorkflowDesigner";
import { Tickets } from "./screens/Tickets";
import { Templates } from "./screens/Templates";
import { Playbooks } from "./screens/Playbooks";
import { Settings } from "./screens/Settings";
import { ApplianceHealth } from "./screens/ApplianceHealth";
import { TechnicianChat } from "./screens/TechnicianChat";
import { McpIntegration } from "./screens/McpIntegration";
import { ExtensionsPacks } from "./screens/ExtensionsPacks";
import { SmartActionCatalog } from "./screens/SmartActionCatalog";
import { ConnectorInstances } from "./screens/ConnectorInstances";
import { SyncReconciliation } from "./screens/SyncReconciliation";
import { Clients } from "./screens/Clients";
import { ClientDiscovery } from "./screens/ClientDiscovery";
import { Login } from "./screens/Login";
import { M365Actions } from "./screens/M365Actions";
import { DiagnosticsSupport } from "./screens/DiagnosticsSupport";
import { TechnicianPath } from "./screens/TechnicianPath";
import { MicrosoftAdmin } from "./screens/MicrosoftAdmin";
import { MicrosoftAdminAccess } from "./screens/MicrosoftAdminAccess";
import { EndUserSupport } from "./screens/EndUserSupport";
import { PrincipalsAdmin } from "./screens/PrincipalsAdmin";
import { MicrosoftAdminCapabilityGate } from "./components/MicrosoftAdminCapabilityGate";
import { RoleGate } from "./components/RoleGate";
import { useDashboard } from "./app/DashboardContext";
import { AutomationsShell } from "./app/AutomationsShell";
import { ActivityShell } from "./app/ActivityShell";

const AzureLighthouse = lazy(() => import("./screens/AzureLighthouse").then(({ AzureLighthouse: screen }) => ({ default: screen })));
const NotFound = lazy(() => import("./screens/NotFound"));

function RouteLoading() {
  return (
    <section className="panel" aria-live="polite">
      <h2>Loading screen…</h2>
    </section>
  );
}

function MicrosoftAdminAccessRoute() {
  const { role, roleResolved } = useDashboard();
  return (
    <RoleGate
      role={role}
      resolved={roleResolved}
      allowed={["admin"]}
      fallback={(
        <section className="panel" role="alert">
          <h2>Administrator access required</h2>
          <p className="screen-note">Only administrators can assign Microsoft Admin capability grants.</p>
        </section>
      )}
    >
      <MicrosoftAdminAccess />
    </RoleGate>
  );
}

function SettingsRoute() {
  const { role, roleResolved } = useDashboard();
  return (
    <RoleGate
      role={role}
      resolved={roleResolved}
      allowed={["admin"]}
      fallback={(
        <section className="panel" role="alert">
          <h2>Administrator access required</h2>
          <p className="screen-note">Only administrators can manage appliance settings.</p>
        </section>
      )}
    >
      <Settings />
    </RoleGate>
  );
}

function ExecutionDeepLink() {
  const { executionId } = useParams();
  return <Navigate to={`/activity/runs?kind=execution&execution_id=${encodeURIComponent(executionId ?? "")}`} replace />;
}

function PrincipalsAdminRoute() {
  const { role, roleResolved, isMspAdmin } = useDashboard();
  const allowed = roleResolved && isMspAdmin;
  return (
    <RoleGate
      role={role}
      resolved={allowed}
      allowed={["admin"]}
      fallback={(
        <section className="panel" role="alert">
          <h2>MSP administrator access required</h2>
          <p className="screen-note">Only MSP administrators can manage people, roles, and bearer credentials.</p>
        </section>
      )}
    >
      <PrincipalsAdmin />
    </RoleGate>
  );
}

export function AppRoutes() {
  return (
    <Routes>
      <Route path="login" element={<Login />} />
      <Route index element={<Overview />} />
      <Route path="clients" element={<Clients />} />
      <Route path="client-discovery" element={<ClientDiscovery />} />
      <Route path="connectors" element={<Connectors />} />
      <Route path="m365-actions" element={<M365Actions />} />
      <Route
        path="microsoft-admin"
        element={(
          <MicrosoftAdminCapabilityGate>
            <MicrosoftAdmin />
          </MicrosoftAdminCapabilityGate>
        )}
      />
      <Route
        path="microsoft-admin/azure-lighthouse"
        element={(
          <MicrosoftAdminCapabilityGate>
            <Suspense fallback={<RouteLoading />}>
              <AzureLighthouse />
            </Suspense>
          </MicrosoftAdminCapabilityGate>
        )}
      />
      <Route path="microsoft-admin/access" element={<MicrosoftAdminAccessRoute />} />
      <Route path="settings/access" element={<PrincipalsAdminRoute />} />
      <Route path="knowledge" element={<Knowledge />} />
      <Route path="workflows" element={<AutomationsShell><Workflows /></AutomationsShell>} />
      <Route path="automation/events" element={<Navigate to="/activity/runs" replace />} />
      <Route path="automation/schedules" element={<Navigate to="/activity/runs?kind=scheduled" replace />} />
      <Route path="activity/runs" element={<ActivityShell><ActivityRuns /></ActivityShell>} />
      <Route path="workflow-designer" element={<AutomationsShell><WorkflowDesigner /></AutomationsShell>} />
      <Route path="templates" element={<AutomationsShell><Templates /></AutomationsShell>} />
      <Route path="playbooks" element={<AutomationsShell><Playbooks /></AutomationsShell>} />
      <Route path="consultant" element={<Consultant />} />
      <Route path="consultant/solution-delivery" element={<SolutionDelivery />} />
      <Route path="collectors" element={<Collectors />} />
      <Route path="reports" element={<Reports />} />
      <Route path="audit" element={<ActivityShell><Audit /></ActivityShell>} />
      <Route path="scheduled-jobs" element={<Navigate to="/activity/runs?kind=scheduled" replace />} />
      <Route path="founder" element={<FounderJourney />} />
      <Route path="tickets" element={<Tickets />} />
      <Route path="approvals" element={<ActivityShell><Approvals /></ActivityShell>} />
      <Route path="analytics" element={<Analytics />} />
      <Route path="agents" element={<Agents />} />
      <Route path="agent-platform" element={<AgentPlatform />} />
      <Route path="technician-chat" element={<TechnicianChat />} />
      <Route path="technician-path" element={<TechnicianPath />} />
      <Route path="backfills" element={<Navigate to="/activity/runs?kind=backfill" replace />} />
      <Route path="executions" element={<Navigate to="/activity/runs?kind=execution" replace />} />
      <Route path="executions/:executionId" element={<ExecutionDeepLink />} />
      <Route path="settings" element={<SettingsRoute />} />
      <Route path="system/appliance-health" element={<ApplianceHealth />} />
      <Route path="system/diagnostics" element={<DiagnosticsSupport />} />
      <Route path="system/extensions" element={<ExtensionsPacks />} />
      <Route path="integrations/mcp" element={<McpIntegration />} />
      <Route path="integrations/connector-instances" element={<ConnectorInstances />} />
      <Route path="integrations/smart-actions" element={<AutomationsShell><SmartActionCatalog /></AutomationsShell>} />
      <Route path="smart-actions/runs" element={<Navigate to="/activity/runs?kind=smart_action" replace />} />
      <Route path="operations/reconciliation" element={<SyncReconciliation />} />
      <Route path="end-user" element={<EndUserSupport />} />
      <Route
        path="*"
        element={(
          <Suspense fallback={<RouteLoading />}>
            <NotFound />
          </Suspense>
        )}
      />
    </Routes>
  );
}
