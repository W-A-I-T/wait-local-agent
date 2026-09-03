import { AppShell } from "./app/AppShell";
import { DashboardProvider, useDashboard } from "./app/DashboardContext";
import { EndUserSupport } from "./screens/EndUserSupport";
import { Login } from "./screens/Login";
import { useEffect, useRef } from "react";
import { useLocation } from "react-router-dom";

export function App() {
  const location = useLocation();
  if (location.pathname === "/end-user" || location.pathname.startsWith("/end-user/")) {
    return <EndUserSupport />;
  }
  return (
    <DashboardProvider>
      <DashboardRouteRefresh />
    </DashboardProvider>
  );
}

function DashboardRouteRefresh() {
  const location = useLocation();
  const { authState, loading, refreshConfiguration } = useDashboard();
  const previousLocationKey = useRef(location.key);

  useEffect(() => {
    if (previousLocationKey.current === location.key) {
      return;
    }
    previousLocationKey.current = location.key;
    void refreshConfiguration();
  }, [location.key, refreshConfiguration]);

  if (!loading && (authState === null || authState === "invalid-token")) {
    return <Login />;
  }
  return <AppShell />;
}
