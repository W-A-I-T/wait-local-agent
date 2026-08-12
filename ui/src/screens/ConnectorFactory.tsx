import { useState, type FormEvent } from "react";
import { useDashboard } from "../app/DashboardContext";
import { apiFetch } from "../api/client";
import type { PowerPlatformConnectorBundle } from "../api/types";

const DEFAULT_OPENAPI = JSON.stringify(
  {
    swagger: "2.0",
    info: { title: "WAIT Ticket API", version: "1.0.0" },
    host: "api.example.test",
    basePath: "/v1",
    schemes: ["https"],
    paths: {
      "/tickets": {
        get: {
          operationId: "ListTickets",
          responses: { "200": { description: "Tickets" } }
        }
      }
    }
  },
  null,
  2
);

export function ConnectorFactory() {
  const { canWrite } = useDashboard();
  const [definitionText, setDefinitionText] = useState(DEFAULT_OPENAPI);
  const [name, setName] = useState("");
  const [clientId, setClientId] = useState("");
  const [bundle, setBundle] = useState<PowerPlatformConnectorBundle | null>(null);
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(false);

  async function generate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    let openapi: Record<string, unknown>;
    try {
      const parsed: unknown = JSON.parse(definitionText);
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
        throw new Error("OpenAPI definition must be a JSON object.");
      }
      openapi = parsed as Record<string, unknown>;
    } catch (error) {
      setBundle(null);
      setMessage(error instanceof Error ? error.message : "OpenAPI definition must be valid JSON.");
      return;
    }
    setLoading(true);
    setMessage("");
    try {
      const result = await apiFetch<PowerPlatformConnectorBundle>("/consultant/connectors/power-platform", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ openapi, name: name.trim() || null, client_id: clientId.trim() || null })
      });
      setBundle(result);
      setMessage(`Generated ${result.name} with ${result.operation_count} operation${result.operation_count === 1 ? "" : "s"}.`);
    } catch (error) {
      setBundle(null);
      setMessage(error instanceof Error ? error.message : "Connector artifacts could not be generated.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="screen-stack">
      <section className="panel">
        <div className="panel-heading">
          <div><h2>Power Platform Connector Factory</h2><span>OpenAPI 2.0 artifact generator</span></div>
          <span>design and package locally</span>
        </div>
        <p className="screen-note">
          Generate redacted apiDefinition.json and apiProperties.json files for review and import. WAIT does not call the API, resolve remote references, or store credentials.
        </p>
        <form className="connector-factory-form" onSubmit={(event) => void generate(event)}>
          <label>Connector name (optional)<input value={name} onChange={(event) => setName(event.target.value)} placeholder="WAIT Ticket API" /></label>
          <label>Tenant client ID<input value={clientId} onChange={(event) => setClientId(event.target.value)} placeholder="acme" /></label>
          <label>OpenAPI 2.0 definition<textarea aria-label="OpenAPI 2.0 definition" rows={18} value={definitionText} onChange={(event) => setDefinitionText(event.target.value)} /></label>
          <button type="submit" disabled={!canWrite || loading}>{loading ? "Generating…" : "Generate connector artifacts"}</button>
        </form>
        {message ? <div className="notice" role="status">{message}</div> : null}
      </section>
      {bundle ? (
        <section className="panel">
          <div className="panel-heading"><h2>Generated artifacts</h2><span>{bundle.auth_type} · {bundle.operation_count} operations</span></div>
          {bundle.warnings.map((warning) => <div className="notice" key={warning}>{warning}</div>)}
          <div className="connector-artifact-grid">
            <div><h3>apiDefinition.json</h3><pre>{JSON.stringify(bundle.api_definition, null, 2)}</pre></div>
            <div><h3>apiProperties.json</h3><pre>{JSON.stringify(bundle.api_properties, null, 2)}</pre></div>
          </div>
        </section>
      ) : null}
    </div>
  );
}
