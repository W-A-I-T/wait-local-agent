import { Navigate, Route, Routes } from "react-router-dom";
import { Approvals } from "./screens/Approvals";
import { Connectors } from "./screens/Connectors";
import { Collectors } from "./screens/Collectors";
import { FounderJourney } from "./surfaces/founder/FounderJourney";
import { Knowledge } from "./screens/Knowledge";
import { Overview } from "./screens/Overview";
import { Audit } from "./screens/Audit";
import { Reports } from "./screens/Reports";
import { ScheduledJobs } from "./screens/ScheduledJobs";
import { Workflows } from "./screens/Workflows";
import { Tickets } from "./screens/Tickets";
import { Settings } from "./screens/Settings";

export function AppRoutes() {
  return (
    <Routes>
      <Route index element={<Overview />} />
      <Route path="connectors" element={<Connectors />} />
      <Route path="knowledge" element={<Knowledge />} />
      <Route path="workflows" element={<Workflows />} />
      <Route path="collectors" element={<Collectors />} />
      <Route path="reports" element={<Reports />} />
      <Route path="audit" element={<Audit />} />
      <Route path="scheduled-jobs" element={<ScheduledJobs />} />
      <Route path="founder" element={<FounderJourney />} />
      <Route path="tickets" element={<Tickets />} />
      <Route path="approvals" element={<Approvals />} />
      <Route path="settings" element={<Settings />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
