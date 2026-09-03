import { useDashboard } from "../app/DashboardContext";

export function ScopeBadge() {
  const {
    selectedClientId = "",
    clients = [],
    clientScopeIds = null,
    isMspAdmin = false,
    role
  } = useDashboard();

  if (!selectedClientId) {
    // Bootstrap administrators are appliance-wide even when their auth response
    // reports no bound client IDs. Ordinary principals remain explicitly scoped.
    const applianceWide = isMspAdmin || (role === "admin" && clientScopeIds?.length === 0);
    return <span className="scope-badge">{applianceWide ? "All clients" : "No client selected"}</span>;
  }
  const client = clients.find((entry) => entry.client_id === selectedClientId);
  return <span className="scope-badge">Scoped to {client?.name ?? selectedClientId}</span>;
}
