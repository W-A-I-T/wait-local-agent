import { AppShell } from "./app/AppShell";
import { DashboardProvider } from "./app/DashboardContext";

export function App() {
  return (
    <DashboardProvider>
      <AppShell />
    </DashboardProvider>
  );
}
