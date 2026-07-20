import { Navigate, Route, Routes } from "react-router-dom";
import { Approvals } from "./screens/Approvals";
import { Connectors } from "./screens/Connectors";
import { Overview } from "./screens/Overview";
import { Tickets } from "./screens/Tickets";
import { Settings } from "./screens/Settings";
import { ComingSoon } from "./screens/ComingSoon";

export function AppRoutes() {
  return (
    <Routes>
      <Route index element={<Overview />} />
      <Route path="connectors" element={<Connectors />} />
      <Route path="tickets" element={<Tickets />} />
      <Route path="approvals" element={<Approvals />} />
      <Route path="settings" element={<Settings />} />
      <Route path="knowledge" element={<ComingSoon title="Knowledge" />} />
      <Route path="workflows" element={<ComingSoon title="Workflows" />} />
      <Route path="collectors" element={<ComingSoon title="Collectors" />} />
      <Route path="reports" element={<ComingSoon title="Reports" />} />
      <Route path="audit" element={<ComingSoon title="Audit" />} />
      <Route path="scheduled-jobs" element={<ComingSoon title="Scheduled Jobs" />} />
      <Route path="founder" element={<ComingSoon title="Founder" />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
