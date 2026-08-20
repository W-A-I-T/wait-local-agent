import { useCallback, useEffect, useMemo, useState } from "react";
import { apiFetch } from "../api/client";
import type { ReadinessStep } from "../api/types";

type ConfigurationState = {
  isConfigured: boolean;
  loading: boolean;
  steps: ReadinessStep[];
  refresh: () => Promise<void>;
};

type FetchedReadiness = {
  loaded: boolean;
  clientReady: boolean;
  connectorReady: boolean;
  mappingReady: boolean;
  writesDisabled: boolean;
  writeSafetyAvailable: boolean;
};

const initialReadiness: FetchedReadiness = {
  loaded: false,
  clientReady: false,
  connectorReady: false,
  mappingReady: false,
  writesDisabled: false,
  writeSafetyAvailable: false
};

export function useConfiguredState({ role }: { role?: string | null }): ConfigurationState {
  const [readiness, setReadiness] = useState<FetchedReadiness>(initialReadiness);

  const refresh = useCallback(async () => {
    const [clients, connectors, mappings, health] = await Promise.allSettled([
      apiFetch<unknown>("/clients"),
      apiFetch<unknown>("/connector-instances"),
      apiFetch<unknown>("/client-connector-mappings"),
      apiFetch<unknown>("/health")
    ]);
    setReadiness({
      loaded: true,
      clientReady: clients.status === "fulfilled" && hasRealClient(clients.value),
      connectorReady: connectors.status === "fulfilled" && hasArrayEntry(connectors.value),
      mappingReady: mappings.status === "fulfilled" && hasVerifiedMapping(mappings.value),
      writesDisabled: health.status === "fulfilled" && isRecord(health.value) && health.value.write_actions_enabled === false,
      writeSafetyAvailable: health.status === "fulfilled"
    });
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const steps = useMemo<ReadinessStep[]>(() => [
    {
      id: "admin",
      label: "Administrator account",
      status: role === "admin" ? "done" : "todo",
      required: true
    },
    {
      id: "client",
      label: "Client created",
      status: readiness.clientReady ? "done" : "todo",
      required: true
    },
    {
      id: "connector",
      label: "Operational connector configured",
      status: readiness.connectorReady ? "done" : "todo",
      required: true
    },
    {
      id: "mapping",
      label: "Client mapping verified",
      status: readiness.mappingReady ? "done" : "todo",
      required: true
    },
    {
      id: "writes",
      label: readiness.writesDisabled ? "Writes disabled safely" : "Live writes enabled",
      status: "info",
      required: false,
      detail: readiness.writeSafetyAvailable ? undefined : "Write safety status unavailable."
    }
  ], [readiness, role]);

  return {
    isConfigured: steps.filter((step) => step.required).every((step) => step.status === "done"),
    loading: !readiness.loaded,
    steps,
    refresh
  };
}

function hasRealClient(value: unknown): boolean {
  return Array.isArray(value) && value.some((item) =>
    isRecord(item) && typeof item.client_id === "string" && item.client_id !== "__quarantine__"
  );
}

function hasArrayEntry(value: unknown): boolean {
  return Array.isArray(value) && value.length > 0;
}

function hasVerifiedMapping(value: unknown): boolean {
  return Array.isArray(value) && value.some((item) => isRecord(item) && (item.verified === 1 || item.verified === true));
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}
