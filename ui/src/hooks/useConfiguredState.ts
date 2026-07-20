import { useEffect, useState } from "react";
import { apiFetch } from "../api/client";
import type { ConnectorStatus } from "../api/types";

type ConfigurationState = {
  isConfigured: boolean;
  loading: boolean;
};

export function useConfiguredState(): ConfigurationState {
  const [state, setState] = useState<ConfigurationState>({
    isConfigured: false,
    loading: true
  });

  useEffect(() => {
    let active = true;
    void Promise.allSettled([
      apiFetch<Record<string, unknown>>("/settings/security"),
      apiFetch<Record<string, unknown>>("/settings/providers"),
      apiFetch<ConnectorStatus[]>("/connectors")
    ]).then(([security, providers, connectors]) => {
      if (!active) {
        return;
      }
      const connectorRows = connectors.status === "fulfilled" && Array.isArray(connectors.value)
        ? connectors.value
        : [];
      const settingsAvailable = security.status === "fulfilled" || providers.status === "fulfilled";
      setState({
        isConfigured: settingsAvailable || connectorRows.some((connector) => connector.status === "ready"),
        loading: false
      });
    });

    return () => {
      active = false;
    };
  }, []);

  return state;
}
