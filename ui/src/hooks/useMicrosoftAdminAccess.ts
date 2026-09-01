import { useMemo } from "react";
import { useDashboard } from "../app/DashboardContext";

export const MICROSOFT_ADMIN_CAPABILITY = "microsoft_admin";

export type CapabilityGrantView = {
  capability_key: string;
  client_id: string | null;
};

export function useMicrosoftAdminAccess() {
  const {
    selectedClientId,
    roleResolved,
    capabilityGrants,
    capabilityResolved,
    capabilityError,
    refresh
  } = useDashboard();

  const grants = Array.isArray(capabilityGrants) ? capabilityGrants : [];
  const resolved = roleResolved && Boolean(capabilityResolved);
  const allowed = useMemo(() => {
    if (!resolved) return false;
    return grants.some((grant) => (
      grant.capability_key === MICROSOFT_ADMIN_CAPABILITY
      && (grant.client_id === null || (selectedClientId !== "" && grant.client_id === selectedClientId))
    ));
  }, [grants, resolved, selectedClientId]);
  const navAllowed = useMemo(() => {
    if (!resolved) return false;
    return grants.some((grant) => grant.capability_key === MICROSOFT_ADMIN_CAPABILITY);
  }, [grants, resolved]);

  return {
    allowed,
    navAllowed,
    resolved,
    grants,
    error: capabilityError ?? "",
    refresh
  };
}
