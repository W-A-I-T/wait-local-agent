import { Fragment, useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { apiFetch } from "../api/client";
import type { ClientConnectorMapping, ClientDirectoryEntry, ConnectorInstance, PollSummary, SyncCursor } from "../api/types";
import { useDashboard } from "../app/DashboardContext";
import { RoleGate } from "../components/RoleGate";
import { StatusChip } from "../components/StatusChip";
import { EmptyState } from "../components/EmptyState";
import { LoadingState } from "../components/LoadingState";
import { connectorSetup } from "../lib/connectorSetup";

type ConnectorType = "halopsa" | "connectwise" | "autotask" | "syncro" | "servicenow" | "ninjaone" | "dattormm" | "ncentral" | "m365";
type M365CredentialMode = "client_credentials" | "static_token";

const connectorTypeOptions: readonly { value: ConnectorType; label: string }[] = [
  { value: "halopsa", label: connectorSetup.halopsa.label },
  { value: "connectwise", label: friendlyProviderName(connectorSetup.connectwise.label) },
  { value: "autotask", label: friendlyProviderName(connectorSetup.autotask.label) },
  { value: "syncro", label: connectorSetup.syncro.label },
  { value: "servicenow", label: connectorSetup.servicenow.label },
  { value: "ninjaone", label: "NinjaOne" },
  { value: "dattormm", label: "Datto RMM" },
  { value: "ncentral", label: "N-able N-central" },
  { value: "m365", label: connectorSetup.m365.label }
];

type DiscoveredCompany = {
  externalCompanyId: string;
  name: string;
};

type MappingForm = {
  externalCompanyId: string;
  externalCompanyName: string;
  clientId: string;
};

type ConnectForm = {
  connectorType: ConnectorType;
  displayName: string;
  waitClientId: string;
  baseUrl: string;
  apiVersion: string;
  haloClientId: string;
  clientSecret: string;
  tenant: string;
  company: string;
  publicKey: string;
  privateKey: string;
  connectWiseClientId: string;
  autotaskUsername: string;
  autotaskSecret: string;
  autotaskIntegrationCode: string;
  syncroApiKey: string;
  syncroSubdomain: string;
  serviceNowUsername: string;
  serviceNowPassword: string;
  rmmAccessToken: string;
  m365CredentialMode: M365CredentialMode;
  m365TenantId: string;
  m365ClientId: string;
  m365ClientSecret: string;
  m365AccessToken: string;
  ninjaOrganizationMap: string;
  dattoSiteMap: string;
  ncentralOrgUnitMap: string;
};

type InstanceEditDraft = {
  connectorType: string;
  displayName: string;
  clientId: string;
  configJson: string;
  status: string;
};

const initialConnectForm: ConnectForm = {
  connectorType: "halopsa",
  displayName: "",
  waitClientId: "",
  baseUrl: "",
  apiVersion: "2024.1",
  haloClientId: "",
  clientSecret: "",
  tenant: "",
  company: "",
  publicKey: "",
  privateKey: "",
  connectWiseClientId: "",
  autotaskUsername: "",
  autotaskSecret: "",
  autotaskIntegrationCode: "",
  syncroApiKey: "",
  syncroSubdomain: "",
  serviceNowUsername: "",
  serviceNowPassword: "",
  rmmAccessToken: "",
  m365CredentialMode: "client_credentials",
  m365TenantId: "",
  m365ClientId: "",
  m365ClientSecret: "",
  m365AccessToken: "",
  ninjaOrganizationMap: "",
  dattoSiteMap: "",
  ncentralOrgUnitMap: ""
};

const demoSecretStorageNotice = "Secure credential storage is unavailable in demo mode — credentials can't be saved here. In a real deployment this stores the credential in the secure store.";
const credentialFieldHelp = "The value entered here is the credential. It is stored encrypted and never displayed again.";
const noCompaniesNotice = "No companies returned — the provider returned no data; you can enter a company ID manually below.";

const initialMappingForm: MappingForm = {
  externalCompanyId: "",
  externalCompanyName: "",
  clientId: ""
};

export function ConnectorInstances() {
  const { role, roleResolved, refresh, refreshConfiguration = refresh } = useDashboard();
  const canView = roleResolved && role === "admin";
  const [instances, setInstances] = useState<ConnectorInstance[]>([]);
  const [syncCursors, setSyncCursors] = useState<SyncCursor[]>([]);
  const [waitClients, setWaitClients] = useState<ClientDirectoryEntry[]>([]);
  const [selectedInstanceId, setSelectedInstanceId] = useState<string | null>(null);
  const [selectedInstance, setSelectedInstance] = useState<ConnectorInstance | null>(null);
  const [instanceEditDrafts, setInstanceEditDrafts] = useState<Record<string, InstanceEditDraft>>({});
  const [editingInstanceId, setEditingInstanceId] = useState<string | null>(null);
  const [instanceEditErrors, setInstanceEditErrors] = useState<Record<string, string>>({});
  const [loadingInstanceDetailId, setLoadingInstanceDetailId] = useState<string | null>(null);
  const [savingInstanceId, setSavingInstanceId] = useState<string | null>(null);
  const [mappings, setMappings] = useState<ClientConnectorMapping[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [clientsError, setClientsError] = useState("");
  const [mappingsLoading, setMappingsLoading] = useState(false);
  const [mappingsError, setMappingsError] = useState("");
  const [syncingId, setSyncingId] = useState<string | null>(null);
  const [syncResults, setSyncResults] = useState<Record<string, PollSummary>>({});
  const [syncErrors, setSyncErrors] = useState<Record<string, string>>({});
  const [connectForm, setConnectForm] = useState<ConnectForm>(() => ({
    ...initialConnectForm,
    connectorType: connectorTypeFromLocation()
  }));
  const [connectStep, setConnectStep] = useState<1 | 2 | 3>(1);
  const [connectBusy, setConnectBusy] = useState(false);
  const [connectError, setConnectError] = useState("");
  const [connectNotice, setConnectNotice] = useState("");
  const [discoveredCompanies, setDiscoveredCompanies] = useState<DiscoveredCompany[]>([]);
  const [discoverLoading, setDiscoverLoading] = useState(false);
  const [discoverAttempted, setDiscoverAttempted] = useState(false);
  const [discoverError, setDiscoverError] = useState("");
  const [mappingForm, setMappingForm] = useState<MappingForm>(initialMappingForm);
  const [mappingBusy, setMappingBusy] = useState(false);
  const [mappingError, setMappingError] = useState("");
  const [mappingNotice, setMappingNotice] = useState("");
  const [verifyingMappingId, setVerifyingMappingId] = useState<string | null>(null);
  const connectBusyRef = useRef(false);
  const mappingRequestId = useRef(0);

  const loadInstances = useCallback(async (): Promise<ConnectorInstance[]> => {
    mappingRequestId.current += 1;
    setLoading(true);
    setError("");
    setMappings([]);
    setMappingsError("");
    setDiscoveredCompanies([]);
    setDiscoverAttempted(false);
    setDiscoverError("");
    setMappingForm(initialMappingForm);
    setMappingError("");
    setMappingNotice("");
    try {
      const [result, cursorResult] = await Promise.all([
        apiFetch<ConnectorInstance[]>("/connector-instances"),
        apiFetch<SyncCursor[]>("/ingestion/sync-cursors").catch(() => [])
      ]);
      if (!Array.isArray(result)) {
        throw new Error("The appliance returned invalid Connector Instances data.");
      }
      setInstances(result);
      setSyncCursors(Array.isArray(cursorResult) ? cursorResult : []);
      return result;
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Unable to load Connector Instances.");
      return [];
    } finally {
      setLoading(false);
    }
  }, []);

  const loadWaitClients = useCallback(async () => {
    setClientsError("");
    try {
      const result = await apiFetch<ClientDirectoryEntry[]>("/clients");
      if (!Array.isArray(result)) {
        throw new Error("The appliance returned invalid WAIT client data.");
      }
      setWaitClients(result.filter((client) => client.client_id !== "__quarantine__"));
    } catch (requestError) {
      setClientsError(requestError instanceof Error ? requestError.message : "Unable to load WAIT clients.");
    }
  }, []);

  useEffect(() => {
    if (canView) {
      void loadInstances();
      void loadWaitClients();
    }
  }, [canView, loadInstances, loadWaitClients]);

  const selectInstance = useCallback(async (instance: ConnectorInstance) => {
    const requestId = ++mappingRequestId.current;
    setSelectedInstanceId(instance.connector_instance_id);
    setSelectedInstance(instance);
    setMappings([]);
    setMappingsError("");
    setMappingForm(initialMappingForm);
    setMappingError("");
    setMappingNotice("");
    setDiscoveredCompanies([]);
    setDiscoverAttempted(false);
    setDiscoverError("");
    setMappingsLoading(true);
    try {
      const [detail, result] = await Promise.all([
        Promise.resolve().then(() => apiFetch<ConnectorInstance>(`/connector-instances/${encodeURIComponent(instance.connector_instance_id)}`)).catch(() => instance),
        apiFetch<ClientConnectorMapping[]>(
          `/client-connector-mappings?connector_instance_id=${encodeURIComponent(instance.connector_instance_id)}`
        )
      ]);
      if (requestId !== mappingRequestId.current) {
        return;
      }
      setSelectedInstance(detail);
      if (!Array.isArray(result)) {
        throw new Error("The appliance returned invalid connector mapping data.");
      }
      setMappings(result);
    } catch (requestError) {
      if (requestId === mappingRequestId.current) {
        setMappingsError(requestError instanceof Error ? requestError.message : "Unable to load connector mappings.");
      }
    } finally {
      if (requestId === mappingRequestId.current) {
        setMappingsLoading(false);
      }
    }
  }, []);

  async function editInstance(instance: ConnectorInstance) {
    if (loadingInstanceDetailId || savingInstanceId) return;
    setLoadingInstanceDetailId(instance.connector_instance_id);
    setInstanceEditErrors((current) => ({ ...current, [instance.connector_instance_id]: "" }));
    try {
      const detail = await apiFetch<ConnectorInstance>(`/connector-instances/${encodeURIComponent(instance.connector_instance_id)}`);
      setInstanceEditDrafts((current) => ({ ...current, [instance.connector_instance_id]: editDraftFromInstance(detail) }));
      setEditingInstanceId(instance.connector_instance_id);
    } catch (requestError) {
      setInstanceEditErrors((current) => ({
        ...current,
        [instance.connector_instance_id]: requestError instanceof Error ? requestError.message : "Unable to load connector instance details."
      }));
    } finally {
      setLoadingInstanceDetailId(null);
    }
  }

  function updateInstanceDraft(instanceId: string, changes: Partial<InstanceEditDraft>) {
    setInstanceEditDrafts((current) => ({ ...current, [instanceId]: { ...current[instanceId], ...changes } }));
    setInstanceEditErrors((current) => ({ ...current, [instanceId]: "" }));
  }

  async function saveInstance(instance: ConnectorInstance) {
    if (savingInstanceId) return;
    const draft = instanceEditDrafts[instance.connector_instance_id];
    if (!draft) return;
    const configJson = draft.configJson.trim();
    if (!draft.displayName.trim() || !configJson) {
      setInstanceEditErrors((current) => ({ ...current, [instance.connector_instance_id]: "Display name and configuration are required." }));
      return;
    }
    try {
      const parsedConfig = JSON.parse(configJson);
      if (!parsedConfig || typeof parsedConfig !== "object" || Array.isArray(parsedConfig)) {
        throw new Error("Configuration must be a JSON object.");
      }
    } catch (parseError) {
      setInstanceEditErrors((current) => ({
        ...current,
        [instance.connector_instance_id]: parseError instanceof Error ? parseError.message : "Configuration must be valid JSON."
      }));
      return;
    }
    const body: Record<string, unknown> = {};
    if (draft.connectorType !== instance.connector_type) body.connector_type = draft.connectorType;
    if (draft.displayName.trim() !== instance.display_name) body.display_name = draft.displayName.trim();
    if (draft.clientId.trim() !== (instance.client_id ?? "")) body.client_id = draft.clientId.trim() || null;
    if (configJson !== instance.config_json) body.config_json = configJson;
    if (draft.status !== instance.status) body.status = draft.status;
    if (Object.keys(body).length === 0) {
      setInstanceEditErrors((current) => ({ ...current, [instance.connector_instance_id]: "Change at least one field before saving." }));
      return;
    }
    setSavingInstanceId(instance.connector_instance_id);
    setInstanceEditErrors((current) => ({ ...current, [instance.connector_instance_id]: "" }));
    try {
      const updated = await apiFetch<ConnectorInstance>(`/connector-instances/${encodeURIComponent(instance.connector_instance_id)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body)
      });
      setInstances((current) => current.map((item) => item.connector_instance_id === updated.connector_instance_id ? updated : item));
      if (selectedInstanceId === updated.connector_instance_id) setSelectedInstance(updated);
      setEditingInstanceId(null);
      await refreshConfiguration();
    } catch (requestError) {
      setInstanceEditErrors((current) => ({
        ...current,
        [instance.connector_instance_id]: requestStatus(requestError) === 409
          ? "This connector instance conflicts with another configured instance. Review the values and try again."
          : requestError instanceof Error ? requestError.message : "Unable to save connector instance changes."
      }));
    } finally {
      setSavingInstanceId(null);
    }
  }

  const discoverPath = selectedInstance ? discoveryPath(selectedInstance) : null;

  const discoverCompanies = useCallback(async () => {
    if (!discoverPath) {
      return;
    }
    setDiscoverLoading(true);
    setDiscoverAttempted(true);
    setDiscoverError("");
    setDiscoveredCompanies([]);
    try {
      const result = await apiFetch<unknown>(discoverPath);
      setDiscoveredCompanies(parseDiscoveredCompanies(result));
    } catch (requestError) {
      setDiscoverError(requestError instanceof Error ? requestError.message : "Unable to discover provider companies.");
    } finally {
      setDiscoverLoading(false);
    }
  }, [discoverPath]);

  const updateMappingForm = (field: keyof MappingForm, value: string) => {
    setMappingForm((current) => ({ ...current, [field]: value }));
    setMappingError("");
    setMappingNotice("");
  };

  const selectDiscoveredCompany = (company: DiscoveredCompany) => {
    setMappingForm((current) => ({
      ...current,
      externalCompanyId: company.externalCompanyId,
      externalCompanyName: company.name
    }));
    setMappingError("");
    setMappingNotice("");
  };

  const createMapping = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!selectedInstance || mappingBusy) {
      return;
    }
    const externalCompanyId = mappingForm.externalCompanyId.trim();
    const clientId = mappingForm.clientId.trim();
    if (!externalCompanyId || !clientId) {
      setMappingError("Choose a WAIT client and enter an external company ID.");
      return;
    }

    setMappingBusy(true);
    setMappingError("");
    setMappingNotice("");
    try {
      const createdMapping = await apiFetch<ClientConnectorMapping>("/client-connector-mappings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          connector_instance_id: selectedInstance.connector_instance_id,
          external_company_id: externalCompanyId,
          external_company_name: mappingForm.externalCompanyName.trim() || null,
          client_id: clientId
        })
      });
      setMappings((current) => [
        ...current.filter((mapping) => mapping.mapping_id !== createdMapping.mapping_id),
        createdMapping
      ]);
      setMappingForm(initialMappingForm);
      setMappingNotice("Mapping created.");
      await refreshConfiguration();
    } catch (requestError) {
      setMappingError(requestError instanceof Error ? requestError.message : "Unable to create the connector mapping.");
    } finally {
      setMappingBusy(false);
    }
  };

  const verifyMapping = async (mappingId: string) => {
    if (!selectedInstance || verifyingMappingId !== null) {
      return;
    }
    setVerifyingMappingId(mappingId);
    setMappingError("");
    setMappingNotice("");
    try {
      const verifiedMapping = await apiFetch<ClientConnectorMapping>(`/client-connector-mappings/${encodeURIComponent(mappingId)}/verify`, {
        method: "POST"
      });
      setMappings((current) => current.map((mapping) => (
        mapping.mapping_id === verifiedMapping.mapping_id ? verifiedMapping : mapping
      )));
      setMappingNotice("Mapping verified.");
      await refreshConfiguration();
    } catch (requestError) {
      setMappingError(requestError instanceof Error ? requestError.message : "Unable to verify the connector mapping.");
    } finally {
      setVerifyingMappingId(null);
    }
  };

  const syncInstance = useCallback(async (instance: ConnectorInstance) => {
    const instanceId = instance.connector_instance_id;
    setSyncingId(instanceId);
    setSyncErrors((current) => {
      const next = { ...current };
      delete next[instanceId];
      return next;
    });
    try {
      const summary = await apiFetch<PollSummary>(`/connectors/instances/${encodeURIComponent(instanceId)}/sync`, {
        method: "POST"
      });
      setSyncResults((current) => ({ ...current, [instanceId]: summary }));
    } catch (requestError) {
      setSyncErrors((current) => ({ ...current, [instanceId]: syncErrorMessage(requestError) }));
    } finally {
      setSyncingId(null);
    }
  }, []);

  const selectedSyncResult = selectedInstance ? syncResults[selectedInstance.connector_instance_id] : undefined;
  const selectedSyncError = selectedInstance ? syncErrors[selectedInstance.connector_instance_id] : undefined;

  const apiVersionValid = connectForm.connectorType === "connectwise"
    ? /^[0-9]{4}\.[0-9]+$/.test(connectForm.apiVersion.trim())
    : connectForm.connectorType !== "servicenow" || /^[A-Za-z0-9_]{1,20}$/.test(connectForm.apiVersion.trim());
  const hasProviderCredentials = connectForm.connectorType === "m365"
    ? connectForm.m365CredentialMode === "client_credentials"
      ? connectForm.m365TenantId.trim() && connectForm.m365ClientId.trim() && connectForm.m365ClientSecret.trim()
      : connectForm.m365AccessToken.trim()
    : connectForm.connectorType === "halopsa"
    ? connectForm.haloClientId.trim() && connectForm.clientSecret.trim() && connectForm.tenant.trim()
    : connectForm.connectorType === "connectwise"
      ? connectForm.company.trim() && connectForm.publicKey.trim() && connectForm.privateKey.trim() && connectForm.connectWiseClientId.trim()
      : connectForm.connectorType === "autotask"
        ? connectForm.autotaskUsername.trim() && connectForm.autotaskSecret.trim() && connectForm.autotaskIntegrationCode.trim()
        : connectForm.connectorType === "syncro"
          ? connectForm.syncroApiKey.trim() && connectForm.syncroSubdomain.trim()
          : connectForm.connectorType === "servicenow"
            ? connectForm.serviceNowUsername.trim() && connectForm.serviceNowPassword.trim()
            : connectForm.rmmAccessToken.trim() && (
                connectForm.connectorType === "ninjaone"
                  ? connectForm.ninjaOrganizationMap.trim()
                  : connectForm.connectorType === "dattormm"
                    ? connectForm.dattoSiteMap.trim()
                    : connectForm.ncentralOrgUnitMap.trim()
              );
  const connectFormReady = Boolean(
    connectForm.displayName.trim()
      && (connectForm.connectorType === "syncro" || connectForm.connectorType === "m365" || connectForm.baseUrl.trim())
      && apiVersionValid
      && hasProviderCredentials
  );
  const providerAndClientReady = Boolean(connectForm.displayName.trim());

  const advanceConnectStep = () => {
    if (connectStep === 1) {
      if (!providerAndClientReady) {
        setConnectError("Display name is required before adding credentials.");
        return;
      }
      setConnectError("");
      setConnectStep(2);
      return;
    }
    if (connectStep === 2) {
      if (!connectFormReady) {
        setConnectError(!apiVersionValid
          ? "ConnectWise API version must use the format YYYY.N, such as 2024.1."
          : "Complete the required credential fields before continuing.");
        return;
      }
      setConnectError("");
      setConnectStep(3);
    }
  };

  const updateConnectForm = (field: keyof ConnectForm, value: string) => {
    setConnectForm((current) => ({ ...current, [field]: value }));
    setConnectError("");
    setConnectNotice("");
  };

  const connect = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (connectBusyRef.current) {
      return;
    }
    if (!connectFormReady) {
      if (!apiVersionValid) {
        setConnectError("ConnectWise API version must use the format YYYY.N, such as 2024.1.");
      }
      return;
    }

    connectBusyRef.current = true;
    setConnectBusy(true);
    setConnectError("");
    setConnectNotice("");
    const connectorType = connectForm.connectorType;
    const displayName = connectForm.displayName.trim();
    const credentialRef = `connector:${connectorType}:${slug(displayName)}:${crypto.randomUUID()}`;
    const credentials: Record<string, string> = connectorType === "m365"
      ? connectForm.m365CredentialMode === "client_credentials"
        ? {
            mode: "client_credentials",
            tenant_id: connectForm.m365TenantId.trim(),
            client_id: connectForm.m365ClientId.trim(),
            client_secret: connectForm.m365ClientSecret.trim()
          }
        : { mode: "static_token", access_token: connectForm.m365AccessToken.trim() }
      : connectorType === "halopsa"
      ? {
          client_id: connectForm.haloClientId.trim(),
          client_secret: connectForm.clientSecret.trim(),
          tenant: connectForm.tenant.trim()
        }
      : connectorType === "connectwise"
        ? {
            company: connectForm.company.trim(),
            public_key: connectForm.publicKey.trim(),
            private_key: connectForm.privateKey.trim(),
            client_id: connectForm.connectWiseClientId.trim()
          }
        : connectorType === "autotask"
          ? {
              integration_code: connectForm.autotaskIntegrationCode.trim(),
              username: connectForm.autotaskUsername.trim(),
              secret: connectForm.autotaskSecret.trim()
            }
          : connectorType === "syncro"
            ? {
                api_key: connectForm.syncroApiKey.trim(),
                subdomain: connectForm.syncroSubdomain.trim()
              }
            : connectorType === "servicenow"
              ? {
                  username: connectForm.serviceNowUsername.trim(),
                  password: connectForm.serviceNowPassword.trim()
                }
              : {
                  access_token: connectForm.rmmAccessToken.trim()
                };
    const config: Record<string, string> = connectorType === "m365"
      ? {}
      : connectorType === "syncro"
      ? {}
      : connectorType === "ninjaone"
        ? { base_url: connectForm.baseUrl.trim(), organization_map_json: connectForm.ninjaOrganizationMap.trim() }
        : connectorType === "dattormm"
          ? { base_url: connectForm.baseUrl.trim(), site_map_json: connectForm.dattoSiteMap.trim() }
          : connectorType === "ncentral"
            ? { base_url: connectForm.baseUrl.trim(), org_unit_map_json: connectForm.ncentralOrgUnitMap.trim() }
            : {
          base_url: connectForm.baseUrl.trim(),
          ...(connectorType === "connectwise" || connectorType === "servicenow"
            ? { api_version: connectForm.apiVersion.trim() }
            : {})
              };

    try {
      await apiFetch<void>("/secrets", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: credentialRef, value: JSON.stringify(credentials) })
      });
    } catch (requestError) {
      setConnectError(requestStatus(requestError) === 403
        ? demoSecretStorageNotice
        : requestError instanceof Error ? requestError.message : "Unable to store the connector credential.");
      connectBusyRef.current = false;
      setConnectBusy(false);
      return;
    }

    let createdInstance: ConnectorInstance;
    try {
      createdInstance = await apiFetch<ConnectorInstance>("/connector-instances", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          connector_type: connectorType,
          display_name: displayName,
          client_id: connectForm.waitClientId || undefined,
          credential_ref: credentialRef,
          config_json: JSON.stringify(config)
        })
      });
    } catch (requestError) {
      const message = requestError instanceof Error ? requestError.message : "Unable to create the connector instance.";
      setConnectError(`The credential was stored in the secure store but the connector instance could not be created: ${message}. Stored under reference ${credentialRef}; it is unused until an instance references it. Retry to create it (a new credential will be stored).`);
      connectBusyRef.current = false;
      setConnectBusy(false);
      return;
    }

    try {
      setInstances((current) => [
        ...current.filter((instance) => instance.connector_instance_id !== createdInstance.connector_instance_id),
        createdInstance
      ]);
      await selectInstance(createdInstance);
      setConnectForm((current) => ({ ...initialConnectForm, connectorType: current.connectorType }));
      setConnectNotice(`Connected ${displayName}. Verify it with 'Sync now' / map its companies below.`);
      await refreshConfiguration();
    } catch (requestError) {
      setConnectError(requestError instanceof Error ? requestError.message : "Unable to create the connector instance.");
    } finally {
      connectBusyRef.current = false;
      setConnectBusy(false);
    }
  };

  const fallback = (
    <section className="panel">
      <div className="panel-heading">
        <h2>Connector Instances</h2>
        <span>Integrations</span>
      </div>
      <p className="screen-note">
        {roleResolved
          ? "Administrator role required to view connector instances."
          : "Checking administrator access before loading connector instances."}
      </p>
    </section>
  );

  return (
    <RoleGate role={role} resolved={roleResolved} allowed={["admin"]} fallback={fallback}>
      <div className="screen-stack">
        <section className="panel connector-instances-hero">
          <div>
            <p className="eyebrow">Integrations</p>
            <h2>Connector Instances</h2>
            <p className="screen-note">Review configured connector instances, mappings, and on-demand sync results.</p>
          </div>
          <button className="icon-button" type="button" onClick={() => void loadInstances()} disabled={loading}>
            {loading ? "Loading…" : "Refresh"}
          </button>
          <a className="secondary-button" href={`/?onboarding=1&step=${selectedInstance ? 2 : 1}`}>Return to setup</a>
        </section>

        <section className="panel" aria-labelledby="connect-system-heading">
          <div className="panel-heading">
            <div>
              <h2 id="connect-system-heading">Connect a system</h2>
              <span>Administrator setup</span>
            </div>
            <span>Client or workspace-wide connection</span>
          </div>
          <p className="screen-note">Connect a supported ticketing or RMM system. Appliance-wide environment configuration remains available as a bootstrap fallback.</p>
          {connectNotice ? <div className="notice" role="status">{connectNotice}</div> : null}
          {connectError ? <div className="notice danger" role="alert">{connectError}</div> : null}
          <ol className="guided-step-list" aria-label="Connector setup steps">
            {([1, 2, 3] as const).map((step) => (
              <li key={step} className={connectStep === step ? "current" : connectStep > step ? "complete" : ""}>
                <span>{step}</span>
                <strong>{step === 1 ? "Provider & client" : step === 2 ? "Credentials" : "Verify & map"}</strong>
              </li>
            ))}
          </ol>
          <form id="connect-system-form" className="draft-form" onSubmit={(event) => {
            if (connectStep === 3) {
              void connect(event);
            } else {
              event.preventDefault();
              advanceConnectStep();
            }
          }}>
            {connectStep === 1 ? <>
            <p className="step-prerequisite">Choose the provider and, if this connection belongs to one customer, select that WAIT client. A display name is required.</p>
            <fieldset>
              <legend>Ticketing / RMM</legend>
              <label htmlFor="connector-provider">Provider</label>
              <select
                id="connector-provider"
                value={connectForm.connectorType}
                onChange={(event) => {
                  const connectorType = event.target.value as ConnectorType;
                  setConnectForm((current) => ({
                    ...current,
                    connectorType,
                    apiVersion: connectorType === "servicenow" ? "v1" : connectorType === "connectwise" ? "2024.1" : current.apiVersion,
                    m365CredentialMode: connectorType === "m365" ? "client_credentials" : current.m365CredentialMode
                  }));
                  setConnectStep(1);
                  setConnectError("");
                  setConnectNotice("");
                }}
              >
                {connectorTypeOptions.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
              </select>
            </fieldset>

            <label htmlFor="connector-display-name">Display name
              <input id="connector-display-name" value={connectForm.displayName} onChange={(event) => updateConnectForm("displayName", event.target.value)} required />
            </label>

            <label htmlFor="connector-wait-client">WAIT client (optional)
              <select id="connector-wait-client" value={connectForm.waitClientId} onChange={(event) => updateConnectForm("waitClientId", event.target.value)}>
                <option value="">No WAIT client association</option>
                {waitClients.map((client) => <option key={client.client_id} value={client.client_id}>{client.name} ({client.client_id})</option>)}
              </select>
            </label>
            {clientsError ? <p className="field-error">{clientsError} You can still connect without a WAIT client association.</p> : null}
            <p className="field-help">Supported providers: {connectorTypeOptions.map((option) => option.label).join(", ")}.</p>
            </> : null}

            {connectStep === 2 ? <>
            <p className="step-prerequisite">Add the provider credentials and connection details. Required values are checked here before anything is saved to the secure store.</p>
            {connectForm.connectorType === "m365" ? (
              <p className="screen-note">Microsoft Graph uses the fixed Microsoft origin; choose how this profile acquires its token.</p>
            ) : connectForm.connectorType === "syncro" ? (
              <label htmlFor="syncro-subdomain">Syncro subdomain
                <input id="syncro-subdomain" aria-describedby="syncro-subdomain-help" value={connectForm.syncroSubdomain} onChange={(event) => updateConnectForm("syncroSubdomain", event.target.value)} required />
                <span id="syncro-subdomain-help" className="field-help">The subdomain from your Syncro address, for example acme in acme.syncromsp.com.</span>
              </label>
            ) : (
            <label htmlFor="connector-base-url">{connectForm.connectorType === "servicenow" ? "ServiceNow instance URL" : connectForm.connectorType === "ninjaone" || connectForm.connectorType === "dattormm" || connectForm.connectorType === "ncentral" ? "Provider service address" : "Service address"}
                <input id="connector-base-url" value={connectForm.baseUrl} onChange={(event) => updateConnectForm("baseUrl", event.target.value)} required />
              </label>
            )}

            {connectForm.connectorType === "connectwise" || connectForm.connectorType === "servicenow" ? (
              <label htmlFor="connector-api-version">API version
                <input
                  id="connector-api-version"
                  value={connectForm.apiVersion}
                  onChange={(event) => updateConnectForm("apiVersion", event.target.value)}
                  aria-invalid={!apiVersionValid}
                  aria-describedby="connector-api-version-hint"
                  required={connectForm.connectorType === "connectwise"}
                />
                <span id="connector-api-version-hint" className="field-help">{connectForm.connectorType === "connectwise" ? "Use the format YYYY.N, such as 2024.1." : "Optional ServiceNow Table API version, such as v1."}</span>
                {!apiVersionValid ? <span className="field-error">{connectForm.connectorType === "connectwise" ? "Use the format YYYY.N." : "Use letters, numbers, and underscores only."}</span> : null}
              </label>
            ) : null}

            {connectForm.connectorType === "m365" ? (
              <>
                <label htmlFor="m365-credential-mode">Credential mode
                  <select id="m365-credential-mode" value={connectForm.m365CredentialMode} onChange={(event) => updateConnectForm("m365CredentialMode", event.target.value as M365CredentialMode)}>
                    <option value="client_credentials">App registration (client credentials)</option>
                    <option value="static_token">Static access token (legacy/dev)</option>
                  </select>
                </label>
                {connectForm.m365CredentialMode === "client_credentials" ? (
                  <>
                    <label htmlFor="m365-tenant-id">Tenant ID
                      <input id="m365-tenant-id" aria-describedby="m365-tenant-id-help" value={connectForm.m365TenantId} onChange={(event) => updateConnectForm("m365TenantId", event.target.value)} required />
                    </label>
                    <span id="m365-tenant-id-help" className="field-help">{credentialFieldHelp}</span>
                    <label htmlFor="m365-client-id">Client ID
                      <input id="m365-client-id" aria-describedby="m365-client-id-help" value={connectForm.m365ClientId} onChange={(event) => updateConnectForm("m365ClientId", event.target.value)} required />
                    </label>
                    <span id="m365-client-id-help" className="field-help">{credentialFieldHelp}</span>
                    <label htmlFor="m365-client-secret">Client secret
                      <input id="m365-client-secret" aria-describedby="m365-client-secret-help" type="password" value={connectForm.m365ClientSecret} onChange={(event) => updateConnectForm("m365ClientSecret", event.target.value)} required />
                    </label>
                    <span id="m365-client-secret-help" className="field-help">{credentialFieldHelp}</span>
                  </>
                ) : (
                  <>
                    <label htmlFor="m365-access-token">Access token
                      <input id="m365-access-token" aria-describedby="m365-access-token-help" type="password" value={connectForm.m365AccessToken} onChange={(event) => updateConnectForm("m365AccessToken", event.target.value)} required />
                    </label>
                    <span id="m365-access-token-help" className="field-help">{credentialFieldHelp}</span>
                  </>
                )}
              </>
            ) : connectForm.connectorType === "halopsa" ? (
              <>
                <label htmlFor="halopsa-client-id">Client ID
                  <input id="halopsa-client-id" aria-describedby="halopsa-client-id-help" value={connectForm.haloClientId} onChange={(event) => updateConnectForm("haloClientId", event.target.value)} required />
                </label>
                <span id="halopsa-client-id-help" className="field-help">{credentialFieldHelp}</span>
                <label htmlFor="halopsa-client-secret">Client secret
                  <input id="halopsa-client-secret" aria-describedby="halopsa-client-secret-help" type="password" value={connectForm.clientSecret} onChange={(event) => updateConnectForm("clientSecret", event.target.value)} required />
                </label>
                <span id="halopsa-client-secret-help" className="field-help">{credentialFieldHelp}</span>
                <label htmlFor="halopsa-tenant">Tenant
                  <input id="halopsa-tenant" aria-describedby="halopsa-tenant-help" value={connectForm.tenant} onChange={(event) => updateConnectForm("tenant", event.target.value)} required />
                </label>
                <span id="halopsa-tenant-help" className="field-help">{credentialFieldHelp}</span>
              </>
            ) : connectForm.connectorType === "connectwise" ? (
              <>
                <label htmlFor="connectwise-company">Company
                  <input id="connectwise-company" aria-describedby="connectwise-company-help" value={connectForm.company} onChange={(event) => updateConnectForm("company", event.target.value)} required />
                </label>
                <span id="connectwise-company-help" className="field-help">{credentialFieldHelp}</span>
                <label htmlFor="connectwise-public-key">Public key
                  <input id="connectwise-public-key" aria-describedby="connectwise-public-key-help" value={connectForm.publicKey} onChange={(event) => updateConnectForm("publicKey", event.target.value)} required />
                </label>
                <span id="connectwise-public-key-help" className="field-help">{credentialFieldHelp}</span>
                <label htmlFor="connectwise-private-key">Private key
                  <input id="connectwise-private-key" aria-describedby="connectwise-private-key-help" type="password" value={connectForm.privateKey} onChange={(event) => updateConnectForm("privateKey", event.target.value)} required />
                </label>
                <span id="connectwise-private-key-help" className="field-help">{credentialFieldHelp}</span>
                <label htmlFor="connectwise-client-id">Client ID
                  <input id="connectwise-client-id" aria-describedby="connectwise-client-id-help" value={connectForm.connectWiseClientId} onChange={(event) => updateConnectForm("connectWiseClientId", event.target.value)} required />
                </label>
                <span id="connectwise-client-id-help" className="field-help">{credentialFieldHelp}</span>
              </>
            ) : connectForm.connectorType === "autotask" ? (
              <>
                <label htmlFor="autotask-username">Username
                  <input id="autotask-username" aria-describedby="autotask-username-help" value={connectForm.autotaskUsername} onChange={(event) => updateConnectForm("autotaskUsername", event.target.value)} required />
                </label>
                <span id="autotask-username-help" className="field-help">{credentialFieldHelp}</span>
                <label htmlFor="autotask-secret">Secret
                  <input id="autotask-secret" aria-describedby="autotask-secret-help" type="password" value={connectForm.autotaskSecret} onChange={(event) => updateConnectForm("autotaskSecret", event.target.value)} required />
                </label>
                <span id="autotask-secret-help" className="field-help">{credentialFieldHelp}</span>
                <label htmlFor="autotask-integration-code">API integration code
                  <input id="autotask-integration-code" aria-describedby="autotask-integration-code-help" value={connectForm.autotaskIntegrationCode} onChange={(event) => updateConnectForm("autotaskIntegrationCode", event.target.value)} required />
                </label>
                <span id="autotask-integration-code-help" className="field-help">{credentialFieldHelp}</span>
              </>
            ) : connectForm.connectorType === "syncro" ? (
              <>
                <label htmlFor="syncro-api-key">API key
                  <input id="syncro-api-key" aria-describedby="syncro-api-key-help" type="password" value={connectForm.syncroApiKey} onChange={(event) => updateConnectForm("syncroApiKey", event.target.value)} required />
                </label>
                <span id="syncro-api-key-help" className="field-help">{credentialFieldHelp}</span>
              </>
            ) : connectForm.connectorType === "servicenow" ? (
              <>
                <label htmlFor="servicenow-username">Username
                  <input id="servicenow-username" aria-describedby="servicenow-username-help" value={connectForm.serviceNowUsername} onChange={(event) => updateConnectForm("serviceNowUsername", event.target.value)} required />
                </label>
                <span id="servicenow-username-help" className="field-help">{credentialFieldHelp}</span>
                <label htmlFor="servicenow-password">Password
                  <input id="servicenow-password" aria-describedby="servicenow-password-help" type="password" value={connectForm.serviceNowPassword} onChange={(event) => updateConnectForm("serviceNowPassword", event.target.value)} required />
                </label>
                <span id="servicenow-password-help" className="field-help">{credentialFieldHelp}</span>
              </>
            ) : connectForm.connectorType === "ninjaone" ? (
              <>
                <label htmlFor="rmm-access-token">Access token
                  <input id="rmm-access-token" aria-describedby="rmm-access-token-help" type="password" value={connectForm.rmmAccessToken} onChange={(event) => updateConnectForm("rmmAccessToken", event.target.value)} required />
                </label>
                <span id="rmm-access-token-help" className="field-help">{credentialFieldHelp}</span>
                <label htmlFor="ninjaone-organization-map">NinjaOne organization map JSON
                  <textarea id="ninjaone-organization-map" aria-describedby="ninjaone-organization-map-help" rows={3} value={connectForm.ninjaOrganizationMap} onChange={(event) => updateConnectForm("ninjaOrganizationMap", event.target.value)} required spellCheck={false} />
                </label>
                <span id="ninjaone-organization-map-help" className="field-help">Map WAIT client IDs to NinjaOne organization IDs, for example {`{"acme":42}`}.</span>
              </>
            ) : connectForm.connectorType === "dattormm" ? (
              <>
                <label htmlFor="rmm-access-token">Access token
                  <input id="rmm-access-token" aria-describedby="rmm-access-token-help" type="password" value={connectForm.rmmAccessToken} onChange={(event) => updateConnectForm("rmmAccessToken", event.target.value)} required />
                </label>
                <span id="rmm-access-token-help" className="field-help">{credentialFieldHelp}</span>
                <label htmlFor="datto-site-map">Datto RMM site map JSON
                  <textarea id="datto-site-map" aria-describedby="datto-site-map-help" rows={3} value={connectForm.dattoSiteMap} onChange={(event) => updateConnectForm("dattoSiteMap", event.target.value)} required spellCheck={false} />
                </label>
                <span id="datto-site-map-help" className="field-help">Map WAIT client IDs to Datto site UIDs, for example {`{"acme":"site-uid"}`}.</span>
              </>
            ) : (
              <>
                <label htmlFor="rmm-access-token">Access token
                  <input id="rmm-access-token" aria-describedby="rmm-access-token-help" type="password" value={connectForm.rmmAccessToken} onChange={(event) => updateConnectForm("rmmAccessToken", event.target.value)} required />
                </label>
                <span id="rmm-access-token-help" className="field-help">{credentialFieldHelp}</span>
                <label htmlFor="ncentral-org-unit-map">N-central organization-unit map JSON
                  <textarea id="ncentral-org-unit-map" aria-describedby="ncentral-org-unit-map-help" rows={3} value={connectForm.ncentralOrgUnitMap} onChange={(event) => updateConnectForm("ncentralOrgUnitMap", event.target.value)} required spellCheck={false} />
                </label>
                <span id="ncentral-org-unit-map-help" className="field-help">Map WAIT client IDs to N-central organization-unit IDs, for example {`{"acme":[100]}`}.</span>
              </>
            )}
            </> : null}

            {connectStep === 3 ? <>
              <p className="step-prerequisite">Confirm the connection summary, then save the credentials to the secure store and create the connection. Afterward, discover an external company and verify its client mapping below.</p>
              <div className="connection-state" aria-label="Connection summary">
                <strong>{connectorTypeOptions.find((option) => option.value === connectForm.connectorType)?.label ?? connectForm.connectorType}</strong>
                <span>{connectForm.displayName.trim()}</span>
                <span>{connectForm.waitClientId ? `Mapped to WAIT client ${connectForm.waitClientId}` : "No WAIT client association"}</span>
              </div>
            </> : null}

            <div className="guided-step-actions">
              {connectStep > 1 ? <button type="button" className="secondary-button" onClick={() => { setConnectError(""); setConnectStep((current) => (current - 1) as 1 | 2 | 3); }} disabled={connectBusy}>Back</button> : null}
              <button type="submit" disabled={connectBusy || (connectStep === 1 ? !providerAndClientReady : connectStep === 2 ? !connectFormReady : false)}>
                {connectStep === 1 ? "Continue to credentials" : connectStep === 2 ? "Continue to verify and map" : connectBusy ? "Connecting…" : "Connect system"}
              </button>
            </div>
          </form>
        </section>

        {error ? (
          <div className="notice danger" role="alert">
            <span>{error}</span>
            <button className="secondary-button" type="button" onClick={() => void loadInstances()} disabled={loading}>Try again</button>
          </div>
        ) : null}

        {loading ? <LoadingState label="Loading Connector Instances…" /> : instances.length === 0 ? <EmptyState title="No connector instances are configured." why="No client connection has been added yet. Start with the guided setup above." action={{ label: "Connect a system", to: "#connect-system-form" }} /> : (
          <section className="panel" aria-labelledby="connector-instances-heading">
            <div className="panel-heading">
              <div>
                <h2 id="connector-instances-heading">Configured instances</h2>
                <span>{instances.length} instance{instances.length === 1 ? "" : "s"}</span>
              </div>
              <span>Administrator view</span>
            </div>
            <div className="connector-instances-table-wrap">
              <table className="connector-instances-table">
                <thead>
                  <tr>
                    <th scope="col">Display name</th>
                    <th scope="col">Type</th>
                    <th scope="col">Status</th>
                    <th scope="col">Owning client</th>
                    <th scope="col">Credential</th>
                    <th scope="col">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {instances.map((instance) => {
                    const selected = instance.connector_instance_id === selectedInstanceId;
                    const cursor = syncCursors.find((item) => item.connector_instance_id === instance.connector_instance_id && item.cursor_type === "connector_poll");
                    return (
                      <Fragment key={instance.connector_instance_id}>
                      <tr key={instance.connector_instance_id}>
                        <td>
                          <button
                            className="connector-instance-select"
                            type="button"
                            aria-pressed={selected}
                            onClick={() => void selectInstance(instance)}
                          >
                            <strong>{instance.display_name}</strong>
                            <code>{instance.connector_instance_id}</code>
                          </button>
                        </td>
                        <td>{instance.connector_type}</td>
                        <td>
                          <StatusChip status={instance.status} />
                          <span className="screen-note">Sync: {cursor?.status || "Not run"}{cursor?.last_synced_at ? ` · ${formatTimestamp(cursor.last_synced_at)}` : ""}</span>
                        </td>
                        <td>{instance.client_id || "Unassigned"}</td>
                        <td><PresenceBadge configured={Boolean(instance.credential_ref)} /></td>
                        <td>
                          <button className="icon-button" type="button" onClick={() => void editInstance(instance)} disabled={loadingInstanceDetailId === instance.connector_instance_id || savingInstanceId !== null}>
                            {loadingInstanceDetailId === instance.connector_instance_id ? "Loading…" : "Edit"}
                          </button>
                        </td>
                      </tr>
                      {editingInstanceId === instance.connector_instance_id && instanceEditDrafts[instance.connector_instance_id] ? (
                        <tr key={`${instance.connector_instance_id}-edit`}>
                          <td colSpan={6}>
                            <form className="playbook-edit-form" onSubmit={(event) => { event.preventDefault(); void saveInstance(instance); }}>
                              <div className="grid">
                                <label>Connector type
                                  <input value={instanceEditDrafts[instance.connector_instance_id].connectorType} onChange={(event) => updateInstanceDraft(instance.connector_instance_id, { connectorType: event.target.value })} />
                                </label>
                                <label>Display name
                                  <input aria-label="Edit connector display name" value={instanceEditDrafts[instance.connector_instance_id].displayName} onChange={(event) => updateInstanceDraft(instance.connector_instance_id, { displayName: event.target.value })} />
                                </label>
                                <label>WAIT client (optional)
                                  <select value={instanceEditDrafts[instance.connector_instance_id].clientId} onChange={(event) => updateInstanceDraft(instance.connector_instance_id, { clientId: event.target.value })}>
                                    <option value="">No WAIT client association</option>
                                    {waitClients.map((client) => <option key={client.client_id} value={client.client_id}>{client.name} ({client.client_id})</option>)}
                                  </select>
                                </label>
                                <label>Status
                                  <select value={instanceEditDrafts[instance.connector_instance_id].status} onChange={(event) => updateInstanceDraft(instance.connector_instance_id, { status: event.target.value })}>
                                    <option value="active">Active</option>
                                    <option value="inactive">Inactive</option>
                                    <option value="disabled">Disabled</option>
                                    {instance.status === "error" ? <option value="error">Error</option> : null}
                                  </select>
                                </label>
                              </div>
                              <label>Configuration JSON
                                <textarea rows={5} value={instanceEditDrafts[instance.connector_instance_id].configJson} onChange={(event) => updateInstanceDraft(instance.connector_instance_id, { configJson: event.target.value })} spellCheck={false} />
                              </label>
                              <p className="screen-note">Credential references are never editable or displayed here. Store a replacement credential separately before changing its reference.</p>
                              {instanceEditErrors[instance.connector_instance_id] ? <p className="inline-error" role="alert">{instanceEditErrors[instance.connector_instance_id]}</p> : null}
                              <div className="template-actions">
                                <button type="submit" disabled={savingInstanceId === instance.connector_instance_id}>{savingInstanceId === instance.connector_instance_id ? "Saving…" : "Save changes"}</button>
                                <button type="button" className="icon-button" disabled={savingInstanceId === instance.connector_instance_id} onClick={() => setEditingInstanceId(null)}>Cancel</button>
                              </div>
                            </form>
                          </td>
                        </tr>
                      ) : null}
                      </Fragment>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </section>
        )}

        <section className="panel connector-instance-mappings" aria-labelledby="connector-mappings-heading">
          <div className="panel-heading">
            <div>
              <h2 id="connector-mappings-heading">External company mappings</h2>
              <span>{selectedInstance ? selectedInstance.display_name : "Select an instance to inspect its mappings"}</span>
            </div>
            {selectedInstance ? (
              <button
                className="secondary-button"
                type="button"
                onClick={() => void syncInstance(selectedInstance)}
                disabled={syncingId !== null}
              >
                {syncingId === selectedInstance.connector_instance_id ? "Syncing…" : "Sync now"}
              </button>
            ) : <span>No instance selected</span>}
          </div>
          {selectedInstance ? <div className="event-row" aria-label="Connector instance detail">
            <span><strong>{selectedInstance.connector_type}</strong> · {selectedInstance.connector_instance_id}</span>
            <span>Status: {selectedInstance.status}</span>
            <span>Client: {selectedInstance.client_id || "Unassigned"}</span>
            <span>Credential: {selectedInstance.credential_ref ? "Configured" : "Not configured"}</span>
          </div> : null}

          {!selectedInstance ? (
            <p className="screen-note">Select a connector instance above to load its external-company to WAIT-client mappings.</p>
          ) : (
            <>
              {selectedSyncError ? (
                <div className="notice danger" role="alert">
                  <span>{selectedSyncError}</span>
                </div>
              ) : null}
              {selectedSyncResult ? (
                <div className="connector-summary" aria-label="Connector sync summary">
                  <strong>Sync result</strong>
                  <span>Status: {selectedSyncResult.status}</span>
                  <span>Written: {selectedSyncResult.written}</span>
                  <span>Quarantined: {selectedSyncResult.quarantined}</span>
                  <span>Pages fetched: {selectedSyncResult.pages_fetched}</span>
                  <span>Reason: {selectedSyncResult.reason || "None reported"}</span>
                </div>
              ) : null}
              {mappingNotice ? <div className="notice" role="status">{mappingNotice}</div> : null}
              {mappingError ? <div className="notice danger" role="alert">{mappingError}</div> : null}
              {discoverPath ? (
                <div className="draft-form">
                  <h3>Discover and map a company</h3>
                  <button type="button" onClick={() => void discoverCompanies()} disabled={discoverLoading}>
                    {discoverLoading ? "Discovering…" : "Discover companies"}
                  </button>
                  {discoverError ? <div className="notice danger" role="alert">{discoverError}</div> : null}
                  {discoverAttempted && discoveredCompanies.length === 0 ? <EmptyState title="No companies returned." why={noCompaniesNotice.replace("No companies returned — ", "")} action={{ label: "Enter a company ID", to: "#external-company-id" }} /> : null}
                  {discoveredCompanies.length > 0 ? (
                    <div className="connector-instances-table-wrap">
                      <table className="connector-instances-table">
                        <thead>
                          <tr>
                            <th scope="col">External company ID</th>
                            <th scope="col">Name</th>
                          </tr>
                        </thead>
                        <tbody>
                          {discoveredCompanies.map((company) => (
                            <tr key={company.externalCompanyId}>
                              <td>
                                <button
                                  className="connector-instance-select"
                                  type="button"
                                  aria-label={`Use ${company.name || company.externalCompanyId}`}
                                  onClick={() => selectDiscoveredCompany(company)}
                                >
                                  <code>{company.externalCompanyId}</code>
                                </button>
                              </td>
                              <td>{company.name || "Unnamed company"}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  ) : null}
                </div>
              ) : null}
              <form className="draft-form" onSubmit={(event) => void createMapping(event)}>
                <h3>Map a company</h3>
                <label htmlFor="external-company-id">External company ID
                  <input
                    id="external-company-id"
                    value={mappingForm.externalCompanyId}
                    onChange={(event) => updateMappingForm("externalCompanyId", event.target.value)}
                    required
                  />
                </label>
                <label htmlFor="external-company-name">External company name (optional)
                  <input
                    id="external-company-name"
                    value={mappingForm.externalCompanyName}
                    onChange={(event) => updateMappingForm("externalCompanyName", event.target.value)}
                  />
                </label>
                <label htmlFor="mapping-wait-client">WAIT client
                  <select
                    id="mapping-wait-client"
                    value={mappingForm.clientId}
                    onChange={(event) => updateMappingForm("clientId", event.target.value)}
                    required
                  >
                    <option value="">Choose a WAIT client</option>
                    {waitClients.map((client) => <option key={client.client_id} value={client.client_id}>{client.name} ({client.client_id})</option>)}
                  </select>
                </label>
                <button type="submit" disabled={mappingBusy || !mappingForm.externalCompanyId.trim() || !mappingForm.clientId}>
                  {mappingBusy ? "Creating…" : "Create mapping"}
                </button>
              </form>
              {mappingsLoading ? (
                <p className="screen-note" aria-busy="true">Loading mappings…</p>
              ) : mappingsError ? (
                <div className="notice danger" role="alert">
                  <span>{mappingsError}</span>
                  <button className="secondary-button" type="button" onClick={() => void selectInstance(selectedInstance)} disabled={mappingsLoading}>Try again</button>
                </div>
              ) : mappings.length === 0 ? (
                <EmptyState title="No mappings are configured." why="No external company is connected to this WAIT client yet." action={{ label: "Map an external company", to: "#external-company-id" }} />
              ) : (
                <div className="connector-instances-table-wrap">
                  <table className="connector-instances-table">
                    <thead>
                      <tr>
                        <th scope="col">External company</th>
                        <th scope="col">WAIT client</th>
                        <th scope="col">Verification</th>
                      </tr>
                    </thead>
                    <tbody>
                      {mappings.map((mapping) => (
                        <tr key={mapping.mapping_id}>
                          <td>
                            <strong>{mapping.external_company_name || mapping.external_company_id}</strong>
                            {mapping.external_company_name ? <code>{mapping.external_company_id}</code> : null}
                          </td>
                          <td>{mapping.client_id}</td>
                          <td>
                            {mapping.verified === 1 ? (
                              <StatusChip status="verified" />
                            ) : (
                              <>
                                <VerificationBadge verified={false} />
                                <button
                                  className="secondary-button"
                                  type="button"
                                  onClick={() => void verifyMapping(mapping.mapping_id)}
                                  disabled={verifyingMappingId !== null}
                                >
                                  {verifyingMappingId === mapping.mapping_id ? "Verifying…" : "Verify"}
                                </button>
                              </>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </>
          )}
        </section>
      </div>
    </RoleGate>
  );
}

function requestStatus(error: unknown): number | undefined {
  if (!error || typeof error !== "object" || !("status" in error)) {
    return undefined;
  }
  const status = error.status;
  return typeof status === "number" ? status : undefined;
}

function slug(value: string): string {
  return value
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "") || "system";
}

function formatTimestamp(value: string | null): string {
  if (!value) return "Never";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "Unknown" : date.toLocaleString();
}

function PresenceBadge({ configured }: { configured: boolean }) {
  return <span className={`status-chip ${configured ? "ok" : "neutral"}`}>{configured ? "Configured" : "Not configured"}</span>;
}

function editDraftFromInstance(instance: ConnectorInstance): InstanceEditDraft {
  return {
    connectorType: instance.connector_type,
    displayName: instance.display_name,
    clientId: instance.client_id ?? "",
    configJson: instance.config_json,
    status: instance.status
  };
}

function VerificationBadge({ verified }: { verified: boolean }) {
  return <span className={`status-chip ${verified ? "ok" : "warn"}`}>{verified ? "Verified" : "Unverified"}</span>;
}

function discoveryPath(instance: ConnectorInstance): string | null {
  if (instance.connector_type === "halopsa") {
    return "/connectors/halopsa/clients?page=1&page_size=50";
  }
  if (instance.connector_type === "connectwise") {
    return "/connectors/connectwise/companies?page=1&page_size=50";
  }
  return null;
}

function parseDiscoveredCompanies(payload: unknown): DiscoveredCompany[] {
  if (!isRecord(payload) || !Array.isArray(payload.items)) {
    return [];
  }
  return payload.items.flatMap((item) => {
    if (!isRecord(item)) {
      return [];
    }
    const externalCompanyId = firstStringValue(item, "id", "client_id", "company_id", "identifier");
    if (!externalCompanyId) {
      return [];
    }
    return [{
      externalCompanyId,
      name: firstStringValue(item, "name", "client_name", "companyName") ?? ""
    }];
  });
}

function firstStringValue(record: Record<string, unknown>, ...keys: string[]): string | null {
  for (const key of keys) {
    const value = record[key];
    if (typeof value === "string" && value.trim()) {
      return value;
    }
    if (typeof value === "number" && Number.isFinite(value)) {
      return String(value);
    }
  }
  return null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function syncErrorMessage(error: unknown): string {
  if (!(error instanceof Error)) {
    return "Unable to sync this connector instance.";
  }

  const status = "status" in error && typeof error.status === "number" ? error.status : undefined;
  if (status === 409 && "technicalDetail" in error && typeof error.technicalDetail === "string") {
    const separator = error.technicalDetail.lastIndexOf(": ");
    const detail = separator >= 0 ? error.technicalDetail.slice(separator + 2) : error.technicalDetail;
    if (detail) {
      return detail;
    }
  }
  return error.message;
}

function connectorTypeFromLocation(): ConnectorType {
  if (typeof window !== "undefined") {
    const provider = new URLSearchParams(window.location.search).get("provider");
    if (provider && connectorTypeOptions.some((option) => option.value === provider)) {
      return provider as ConnectorType;
    }
  }
  return initialConnectForm.connectorType;
}

function friendlyProviderName(name: string): string {
  return name.replace(/\sPSA\b/g, "");
}
