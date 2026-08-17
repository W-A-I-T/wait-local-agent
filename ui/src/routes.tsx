import { Navigate, Route, Routes } from "react-router-dom";
import { Approvals } from "./screens/Approvals";
import { Analytics } from "./screens/Analytics";
import { Agents } from "./screens/Agents";
import { Backfills } from "./screens/Backfills";
import { Executions } from "./screens/Executions";
import { Connectors } from "./screens/Connectors";
import { Consultant } from "./screens/Consultant";
import { Collectors } from "./screens/Collectors";
import { FounderJourney } from "./surfaces/founder/FounderJourney";
import { Knowledge } from "./screens/Knowledge";
import { Overview } from "./screens/Overview";
import { Audit } from "./screens/Audit";
import { Reports } from "./screens/Reports";
import { ScheduledJobs } from "./screens/ScheduledJobs";
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
import { Events } from "./screens/Events";
import { Schedules } from "./screens/Schedules";
import { ConnectorInstances } from "./screens/ConnectorInstances";
import { SyncReconciliation } from "./screens/SyncReconciliation";
import { Clients } from "./screens/Clients";

export function AppRoutes() {
  return (
    <Routes>
      <Route index element={<Overview />} />
      <Route path="clients" element={<Clients />} />
      <Route path="connectors" element={<Connectors />} />
      <Route path="knowledge" element={<Knowledge />} />
      <Route path="workflows" element={<Workflows />} />
      <Route path="automation/events" element={<Events />} />
      <Route path="automation/schedules" element={<Schedules />} />
      <Route path="workflow-designer" element={<WorkflowDesigner />} />
      <Route path="templates" element={<Templates />} />
      <Route path="playbooks" element={<Playbooks />} />
      <Route path="consultant" element={<Consultant />} />
      <Route path="collectors" element={<Collectors />} />
      <Route path="reports" element={<Reports />} />
      <Route path="audit" element={<Audit />} />
      <Route path="scheduled-jobs" element={<ScheduledJobs />} />
      <Route path="founder" element={<FounderJourney />} />
      <Route path="tickets" element={<Tickets />} />
      <Route path="approvals" element={<Approvals />} />
      <Route path="analytics" element={<Analytics />} />
      <Route path="agents" element={<Agents />} />
      <Route path="technician-chat" element={<TechnicianChat />} />
      <Route path="backfills" element={<Backfills />} />
      <Route path="executions" element={<Executions />} />
      <Route path="settings" element={<Settings />} />
      <Route path="system/appliance-health" element={<ApplianceHealth />} />
      <Route path="system/extensions" element={<ExtensionsPacks />} />
      <Route path="integrations/mcp" element={<McpIntegration />} />
      <Route path="integrations/connector-instances" element={<ConnectorInstances />} />
      <Route path="integrations/smart-actions" element={<SmartActionCatalog />} />
      <Route path="operations/reconciliation" element={<SyncReconciliation />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
