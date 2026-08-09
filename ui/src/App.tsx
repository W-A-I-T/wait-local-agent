import { AppShell } from "./app/AppShell";
import { DashboardProvider } from "./app/DashboardContext";
import { EndUserSupport } from "./screens/EndUserSupport";
import { useLocation } from "react-router-dom";

export function App() {
  const location = useLocation();
  if (location.pathname === "/end-user" || location.pathname.startsWith("/end-user/")) {
    return <EndUserSupport />;
  }
  return (
    <DashboardProvider>
      <AppShell />
    </DashboardProvider>
  );
}
