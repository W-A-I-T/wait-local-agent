import { useEffect, useMemo, useState } from "react";
import { apiFetch } from "../api/client";
import type { ConnectorStatus } from "../api/types";
import { EmptyState } from "./EmptyState";
import { connectorSetup } from "../lib/connectorSetup";
import {
  connectorResourceHealthPaths,
  connectorResources,
  type ConnectorResource,
  type ConnectorResourcePagination
} from "../lib/connectorResources";

type JsonRecord = Record<string, unknown>;

type ResourceResponse = {
  result?: { status?: unknown; message?: unknown };
  items?: unknown;
  item?: unknown;
  next_cursor?: unknown;
};

type ResourceTableProps = {
  resource: ConnectorResource;
  values: Record<string, string>;
  healthReady: boolean;
  scalePad?: boolean;
};

const PAGE_SIZE = 25;
const MAX_VALUE_LENGTH = 240;
const CATALOG_CONNECTOR_IDS = Object.keys(connectorResources);

function isRecord(value: unknown): value is JsonRecord {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function labelForConnector(id: string): string {
  return connectorSetup[id as keyof typeof connectorSetup]?.label ?? id.replace(/[-_]/g, " ");
}

function isUnavailable(status: string | undefined): boolean {
  return Boolean(status && /blocked|not[_ ]configured|unavailable|unreachable|failed/i.test(status));
}

function displayValue(value: unknown): string {
  if (value === null || value === undefined || value === "") {
    return "—";
  }
  let rendered: string;
  if (typeof value === "object") {
    try {
      rendered = JSON.stringify(value) ?? String(value);
    } catch {
      rendered = String(value);
    }
  } else {
    rendered = String(value);
  }
  return rendered.length > MAX_VALUE_LENGTH
    ? `${rendered.slice(0, MAX_VALUE_LENGTH - 1)}…`
    : rendered;
}

function responseItems(response: ResourceResponse, shape: ConnectorResource["shape"]): JsonRecord[] {
  if (shape === "item" && isRecord(response.item)) {
    return [response.item];
  }
  if (!Array.isArray(response.items)) {
    return [];
  }
  return response.items.filter(isRecord);
}

function appendQuery(path: string, values: Record<string, string>, names: readonly string[]): string {
  const query = new URLSearchParams();
  for (const name of names) {
    const value = values[name]?.trim();
    if (value) {
      query.set(name, value);
    }
  }
  const encoded = query.toString();
  return encoded ? `${path}?${encoded}` : path;
}

function interpolationPath(
  template: string,
  values: Record<string, string>,
  requiredParams: readonly string[]
): string | null {
  for (const name of requiredParams) {
    if (!values[name]?.trim()) {
      return null;
    }
  }
  return template.replace(/\{([^}]+)\}/g, (_, name: string) => encodeURIComponent(values[name].trim()));
}

function queryParamNames(resource: ConnectorResource): string[] {
  return resource.params.filter((param) => param.location === "query").map((param) => param.name);
}

function paginationQuery(
  pagination: ConnectorResourcePagination,
  page: number,
  cursor: string,
  values: Record<string, string>
): Record<string, string> {
  if (pagination.kind === "page") {
    return {
      [pagination.pageParam]: String(page),
      ...(pagination.sizeParam ? { [pagination.sizeParam]: values[pagination.sizeParam]?.trim() || String(PAGE_SIZE) } : {})
    };
  }
  if (pagination.kind === "cursor") {
    return {
      ...(cursor ? { [pagination.cursorParam]: cursor } : {}),
      ...(pagination.sizeParam ? { [pagination.sizeParam]: values[pagination.sizeParam]?.trim() || String(PAGE_SIZE) } : {})
    };
  }
  return {};
}

function initialValues(resource: ConnectorResource): Record<string, string> {
  return Object.fromEntries(resource.params.map((param) => [param.name, ""]));
}

function ResourceTable({ resource, values, healthReady, scalePad = false }: ResourceTableProps) {
  const [items, setItems] = useState<JsonRecord[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const [cursor, setCursor] = useState("");
  const [cursorHistory, setCursorHistory] = useState<string[]>([]);
  const [nextCursor, setNextCursor] = useState("");
  const [detail, setDetail] = useState<{ row: JsonRecord; data?: unknown; loading: boolean; error?: string } | null>(null);

  const pathParamNames = resource.params.filter((param) => param.location === "path").map((param) => param.name);
  const requiredParamNames = resource.params.filter((param) => param.required).map((param) => param.name);
  const requestPath = useMemo(() => {
    const path = interpolationPath(resource.path, values, requiredParamNames);
    if (!path) {
      return null;
    }
    const queryValues = {
      ...Object.fromEntries(queryParamNames(resource).map((name) => [name, values[name] ?? ""])),
      ...paginationQuery(resource.pagination, page, cursor, values)
    };
    return appendQuery(path, queryValues, Object.keys(queryValues));
  }, [cursor, page, requiredParamNames, resource, values]);

  useEffect(() => {
    setItems([]);
    setError(null);
    setPage(1);
    setCursor("");
    setCursorHistory([]);
    setNextCursor("");
    setDetail(null);
  }, [resource.id, values]);

  useEffect(() => {
    let current = true;
    if (!healthReady || !requestPath) {
      setItems([]);
      setLoading(false);
      setNextCursor("");
      return () => {
        current = false;
      };
    }
    setLoading(true);
    setError(null);
    void apiFetch<ResourceResponse>(requestPath)
      .then((response) => {
        if (!current) return;
        const resultStatus = typeof response.result?.status === "string" ? response.result.status : undefined;
        if (isUnavailable(resultStatus)) {
          setItems([]);
          setError(typeof response.result?.message === "string" ? response.result.message : "This connector is unavailable or not configured.");
          return;
        }
        setItems(responseItems(response, resource.shape));
        setNextCursor(typeof response.next_cursor === "string" ? response.next_cursor : "");
      })
      .catch((reason: unknown) => {
        if (current) {
          setItems([]);
          setNextCursor("");
          setError(reason instanceof Error ? reason.message : "Records could not be loaded.");
        }
      })
      .finally(() => {
        if (current) setLoading(false);
      });
    return () => {
      current = false;
    };
  }, [healthReady, requestPath, resource.shape]);

  async function openDetail(row: JsonRecord) {
    const detailConfig = resource.detail;
    if (!detailConfig) {
      setDetail({ row, data: row, loading: false });
      return;
    }
    const id = row[detailConfig.idField];
    if (typeof id !== "string" && typeof id !== "number") {
      setDetail({ row, data: row, loading: false, error: `No ${detailConfig.idField} was returned for this row.` });
      return;
    }
    const path = interpolationPath(
      detailConfig.path,
      { ...values, [detailConfig.idParam]: String(id) },
      [detailConfig.idParam, ...pathParamNames.filter((name) => detailConfig.path.includes(`{${name}}`))]
    );
    if (!path) {
      setDetail({ row, data: row, loading: false, error: "The detail path needs a required identifier." });
      return;
    }
    const query = detailConfig.queryParams ?? [];
    setDetail({ row, loading: true });
    try {
      const data = await apiFetch<ResourceResponse>(appendQuery(path, values, query));
      setDetail({ row, data, loading: false });
    } catch (reason: unknown) {
      setDetail({ row, loading: false, error: reason instanceof Error ? reason.message : "Detail could not be loaded." });
    }
  }

  function goNext() {
    if (resource.pagination.kind === "cursor") {
      if (!nextCursor) return;
      setCursorHistory((history) => [...history, cursor]);
      setCursor(nextCursor);
      return;
    }
    setPage((current) => current + 1);
  }

  function goPrevious() {
    if (resource.pagination.kind === "cursor") {
      const previous = cursorHistory[cursorHistory.length - 1];
      if (previous === undefined) return;
      setCursorHistory((history) => history.slice(0, -1));
      setCursor(previous);
      return;
    }
    setPage((current) => Math.max(1, current - 1));
  }

  const columns = resource.columns.length > 0 ? resource.columns : Object.keys(items[0] ?? {});
  const missingRequired = resource.params
    .filter((param) => param.required && !values[param.name]?.trim())
    .map((param) => param.label);
  const canPrevious = resource.pagination.kind === "cursor" ? cursorHistory.length > 0 : page > 1;
  const canNext = resource.pagination.kind === "cursor" ? Boolean(nextCursor) : items.length >= Number(values.page_size || PAGE_SIZE);

  return (
    <section className={`connector-resource-table ${scalePad ? "scalepad-resource-table" : ""}`} aria-labelledby={`${resource.id}-resource-heading`}>
      <div className="panel-heading">
        <h3 id={`${resource.id}-resource-heading`}>{resource.label}</h3>
        {resource.pagination.kind !== "none" ? <span>{resource.pagination.kind === "cursor" ? "cursor pagination" : `page ${page}`}</span> : <span>read-only</span>}
      </div>
      {!loading && !error && missingRequired.length > 0 ? <p className="screen-note">Enter {missingRequired.join(" and ")} to browse these records.</p> : null}
      {loading ? <p className="screen-note" aria-busy="true">Loading {resource.label.toLowerCase()}…</p> : null}
      {error ? <div className="notice danger" role="alert">{error}</div> : null}
      {!loading && !error && missingRequired.length === 0 && items.length === 0 ? <EmptyState title="No records returned." why="The provider returned no data for this request." action={{ label: "Review connector setup", to: "#connector-setup" }} /> : null}
      {!loading && !error && items.length > 0 ? (
        <div className="clients-table-wrap">
          <table className="clients-table connector-resource-table-grid">
            <thead><tr>{columns.map((column) => <th scope="col" key={column}>{column}</th>)}</tr></thead>
            <tbody>
              {items.map((item, index) => (
                <tr key={`${resource.id}-${page}-${index}`}>
                  {columns.map((column) => (
                    <td key={column}>
                      {column === columns[0] ? (
                        <button type="button" className="connector-row-trigger" onClick={() => void openDetail(item)} aria-label={`Open ${resource.label} record ${displayValue(item[column])}`}>
                          {displayValue(item[column])}
                        </button>
                      ) : displayValue(item[column])}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
      {resource.pagination.kind !== "none" ? (
        <div className="row-actions" aria-label={`${resource.label} pagination`}>
          <button type="button" className="secondary-button" onClick={goPrevious} disabled={!canPrevious || loading}>Prev</button>
          <span>{resource.pagination.kind === "cursor" ? `Page ${cursorHistory.length + 1}` : `Page ${page}`}</span>
          <button type="button" className="secondary-button" onClick={goNext} disabled={!canNext || loading}>Next</button>
        </div>
      ) : null}
      {detail ? (
        <aside className="connector-detail-drawer" aria-label={`${resource.label} record detail`}>
          <div className="panel-heading">
            <h4>Record detail</h4>
            <button type="button" className="icon-button" onClick={() => setDetail(null)}>Close detail</button>
          </div>
          {detail.loading ? <p>Loading detail…</p> : detail.error ? <p className="screen-note">{detail.error}</p> : <pre className="code-panel">{JSON.stringify(detail.data, null, 2)}</pre>}
        </aside>
      ) : null}
    </section>
  );
}

export type ConnectorExplorerProps = {
  connectors: ConnectorStatus[];
};

export function ConnectorExplorer({ connectors }: ConnectorExplorerProps) {
  const statuses = useMemo(() => {
    const byId = new Map(connectors.map((connector) => [connector.id, connector]));
    return CATALOG_CONNECTOR_IDS.map((id) => byId.get(id) ?? {
      id,
      name: labelForConnector(id),
      status: "not_configured",
      message: "No connector status is available. Configure this connector to browse it."
    });
  }, [connectors]);
  const initialConnectorId = connectors.find((connector) => CATALOG_CONNECTOR_IDS.includes(connector.id))?.id ?? statuses[0]?.id ?? "";
  const [connectorId, setConnectorId] = useState(initialConnectorId);
  const [resourceId, setResourceId] = useState("");
  const [values, setValues] = useState<Record<string, string>>({});
  const [view, setView] = useState<"explorer" | "scalepad">(() => (
    typeof window !== "undefined" && new URLSearchParams(window.location.search).get("view") === "scalepad-qbr" ? "scalepad" : "explorer"
  ));
  const [healthStatus, setHealthStatus] = useState<string | undefined>();
  const [healthMessage, setHealthMessage] = useState<string | undefined>();
  const [healthLoading, setHealthLoading] = useState(false);
  const [healthError, setHealthError] = useState<string | null>(null);

  const selectedStatus = statuses.find((status) => status.id === connectorId) ?? statuses[0];
  const resources = connectorResources[connectorId] ?? [];
  const selectedResource = resources.find((resource) => resource.id === resourceId) ?? resources[0];
  const scalePadResources = connectorResources.scalepad ?? [];

  useEffect(() => {
    if (!statuses.some((status) => status.id === connectorId)) {
      setConnectorId(statuses[0]?.id ?? "");
    }
  }, [connectorId, statuses]);

  useEffect(() => {
    setResourceId("");
    setValues({});
    setHealthStatus(undefined);
    setHealthMessage(undefined);
    setHealthError(null);
    const status = statuses.find((candidate) => candidate.id === connectorId);
    if (!status || isUnavailable(status.status)) {
      setHealthStatus(status?.status ?? "not_configured");
      setHealthMessage(status?.message ?? "This connector is unavailable or not configured.");
      return;
    }
    let current = true;
    setHealthLoading(true);
    const healthPath = connectorResourceHealthPaths[connectorId];
    if (!healthPath) {
      setHealthLoading(false);
      setHealthError("Connector health is unavailable.");
      return () => {
        current = false;
      };
    }
    void apiFetch<{ status?: unknown; message?: unknown }>(healthPath)
      .then((response) => {
        if (!current) return;
        setHealthStatus(typeof response.status === "string" ? response.status : "unknown");
        setHealthMessage(typeof response.message === "string" ? response.message : undefined);
      })
      .catch((reason: unknown) => {
        if (current) setHealthError(reason instanceof Error ? reason.message : "Connector health could not be loaded.");
      })
      .finally(() => {
        if (current) setHealthLoading(false);
      });
    return () => {
      current = false;
    };
  }, [connectorId, statuses]);

  const healthReady = !healthLoading && !healthError && typeof healthStatus === "string" && !isUnavailable(healthStatus);
  const postureBlocked = Boolean(healthError || isUnavailable(healthStatus));
  const inputParams = (selectedResource?.params ?? []).filter((param) => param.location === "path" || param.name !== "page_size");
  const selectedValues = selectedResource ? { ...initialValues(selectedResource), ...values } : values;

  function chooseConnector(nextId: string) {
    setView("explorer");
    setConnectorId(nextId);
  }

  function chooseResource(nextId: string) {
    const nextResource = resources.find((resource) => resource.id === nextId);
    setResourceId(nextId);
    setValues(nextResource ? initialValues(nextResource) : {});
  }

  return (
    <section className="panel connector-explorer" aria-labelledby="connector-explorer-heading">
      <div className="panel-heading connector-explorer-heading">
        <div>
          <p className="eyebrow">Read-only provider data</p>
          <h2 id="connector-explorer-heading">Connector Explorer</h2>
          <p className="screen-note">Browse verified connector resources without enabling writes or guessing provider routes.</p>
        </div>
        <a className="inline-link" href="/reports">Reports</a>
      </div>
      <div className="connector-explorer-tabs" role="tablist" aria-label="Connector views">
        <button type="button" role="tab" aria-selected={view === "explorer"} className={view === "explorer" ? "selected" : "secondary-button"} onClick={() => setView("explorer")}>Explorer</button>
        <button type="button" role="tab" aria-selected={view === "scalepad"} className={view === "scalepad" ? "selected" : "secondary-button"} onClick={() => { setConnectorId("scalepad"); setView("scalepad"); }}>ScalePad QBR</button>
      </div>

      {view === "explorer" ? (
        <>
          <div className="connector-explorer-picker">
            <label>Connector<select value={connectorId} onChange={(event) => chooseConnector(event.target.value)}>
              {statuses.map((status) => <option value={status.id} key={status.id}>{status.name}</option>)}
            </select></label>
            <label>Resource<select value={selectedResource?.id ?? ""} onChange={(event) => chooseResource(event.target.value)} disabled={resources.length === 0}>
              {resources.map((resource) => <option value={resource.id} key={resource.id}>{resource.label}</option>)}
            </select></label>
          </div>
          <div className="connector-explorer-posture">
            <span className={`status-chip ${postureBlocked ? "warn" : "neutral"}`}>{healthLoading ? "Checking health…" : healthStatus ?? "unknown"}</span>
            <span>{safeConnectorMessage(healthMessage ?? selectedStatus?.message ?? "Connector status unavailable.")}</span>
          </div>
          {postureBlocked ? <div className="notice warning" aria-live="polite">
            <strong>{selectedStatus?.name ?? labelForConnector(connectorId)} is unavailable or not configured.</strong>
            <p>Configure the connector before browsing records. <a className="inline-link" href="#connector-setup">View configuration guidance</a></p>
            {connectorSetup[connectorId as keyof typeof connectorSetup] ? <details className="connector-explorer-setup" id="connector-setup">
              <summary>Technical details</summary>
              <p>{connectorSetup[connectorId as keyof typeof connectorSetup].docsNote}</p>
              <p>These are the exact environment variable names for appliance-wide setup:</p>
              <ul className="connector-setup-env-vars">
                {connectorSetup[connectorId as keyof typeof connectorSetup].envVars.map((envVar) => <li key={envVar}><code>{envVar}</code></li>)}
              </ul>
              <p>Reads stay gated by <code>WAIT_ALLOW_HTTP_PROBING</code>; this explorer never enables writes.</p>
            </details> : null}
          </div> : null}
          {selectedResource && !postureBlocked ? (
            <>
              {inputParams.length > 0 ? <div className="connector-resource-params" aria-label={`${selectedResource.label} parameters`}>
                {inputParams.map((param) => <label key={param.name}>{param.label}
                  <input value={selectedValues[param.name] ?? ""} placeholder={param.placeholder} maxLength={256} required={param.required} onChange={(event) => setValues((current) => ({ ...current, [param.name]: event.target.value }))} />
                </label>)}
              </div> : null}
              <ResourceTable resource={selectedResource} values={selectedValues} healthReady={healthReady} />
            </>
          ) : null}
        </>
      ) : (
        <ScalePadQbr resources={scalePadResources} healthReady={healthReady} postureBlocked={postureBlocked} healthMessage={healthMessage} values={selectedValues} />
      )}
      {!postureBlocked ? <span id="connector-setup" className="connector-explorer-setup-anchor" aria-hidden="true" /> : null}
    </section>
  );
}

function ScalePadQbr({
  resources,
  healthReady,
  postureBlocked,
  healthMessage,
  values
}: {
  resources: readonly ConnectorResource[];
  healthReady: boolean;
  postureBlocked: boolean;
  healthMessage?: string;
  values: Record<string, string>;
}) {
  return (
    <div className="scalepad-qbr">
      <div className="panel-heading">
        <div><h3>ScalePad QBR data</h3><p className="screen-note">Risk, compliance, goals, and assessments are read-only provider evidence for a client review.</p></div>
        <a className="inline-link" href="/reports">Open Reports →</a>
      </div>
      {postureBlocked ? <div className="notice warning" aria-live="polite">
        <strong>ScalePad is unavailable or not configured.</strong>
        <p>{safeConnectorMessage(healthMessage ?? "Configure ScalePad before browsing QBR data.")}</p>
        <details className="connector-explorer-setup">
          <summary>Technical details</summary>
          <p>{connectorSetup.scalepad.docsNote}</p>
          <p>These are the exact environment variable names for appliance-wide setup:</p>
          <ul className="connector-setup-env-vars">
            {connectorSetup.scalepad.envVars.map((envVar) => <li key={envVar}><code>{envVar}</code></li>)}
          </ul>
          <p>Reads stay gated by <code>WAIT_ALLOW_HTTP_PROBING</code>; this tab never enables writes.</p>
        </details>
      </div> : null}
      {!postureBlocked && healthReady ? <div className="scalepad-qbr-grid">
        {resources.filter((resource) => resource.id !== "clients").map((resource) => <ResourceTable key={resource.id} resource={resource} values={values} healthReady={healthReady} scalePad />)}
      </div> : null}
    </div>
  );
}

function safeConnectorMessage(message: string): string {
  return message
    .replace(/\bPSA\b/g, "ticketing system")
    .replace(/WAIT_[A-Z0-9_]+/g, "the required settings")
    .replace(/\bVault\b/gi, "secure store");
}
