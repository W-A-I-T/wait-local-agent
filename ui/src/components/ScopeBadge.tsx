import type { ClientDirectoryEntry } from "../api/types";

type ScopeBadgeProps = {
  selectedClientId: string;
  clients: ClientDirectoryEntry[];
};

export function ScopeBadge({ selectedClientId, clients }: ScopeBadgeProps) {
  if (!selectedClientId) {
    return <span className="scope-badge">All clients</span>;
  }
  const client = clients.find((entry) => entry.client_id === selectedClientId);
  return <span className="scope-badge">Scoped to {client?.name ?? selectedClientId}</span>;
}
