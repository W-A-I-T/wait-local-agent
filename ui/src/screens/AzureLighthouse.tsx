import { useEffect, useMemo, useState, type FormEvent } from "react";
import { apiFetch } from "../api/client";
import { useDashboard } from "../app/DashboardContext";
import { StatusChip } from "../components/StatusChip";
import {
  emptyConnection,
  showError,
  type LighthouseDiscovery,
  type LighthouseInventory,
  type LighthouseStatus,
  type OnboardingBundle
} from "./azureLighthouseModels";

export function AzureLighthouse() {
  const {
    role,
    roleResolved,
    clients,
    selectedClientId,
    setSelectedClientId
  } = useDashboard();
  const [connection, setConnection] = useState(emptyConnection);
  const [status, setStatus] = useState<LighthouseStatus | null>(null);
  const [discovery, setDiscovery] = useState<LighthouseDiscovery | null>(null);
  const [inventory, setInventory] = useState<LighthouseInventory | null>(null);
  const [selectedSubscriptionId, setSelectedSubscriptionId] = useState("");
  const [busy, setBusy] = useState<"discover" | "inventory" | "onboarding" | null>(null);
  const [message, setMessage] = useState("");
  const [danger, setDanger] = useState(false);
  const [onboarding, setOnboarding] = useState({
    offerName: "WAIT Azure delegated inventory",
    description: "Read-only Azure resource inventory through Azure Lighthouse.",
    principalId: "",
    principalDisplayName: "WAIT Local Agent",
    deploymentScope: "subscription" as "subscription" | "resource_group"
  });
  const [bundle, setBundle] = useState<OnboardingBundle | null>(null);

  const isAdmin = roleResolved && role === "admin";
  const selectedClient = useMemo(
    () => clients.find((client) => client.client_id === selectedClientId),
    [clients, selectedClientId]
  );
  const connectionReady = Boolean(
    selectedClientId
    && connection.credentialRef.trim()
    && connection.managingTenantId.trim()
    && connection.customerTenantId.trim()
  );
  const inventoryReady = connectionReady && Boolean(selectedSubscriptionId);
  const onboardingReady = Boolean(
    selectedClientId
    && connection.managingTenantId.trim()
    && onboarding.offerName.trim()
    && onboarding.description.trim()
    && onboarding.principalId.trim()
    && onboarding.principalDisplayName.trim()
  );

  useEffect(() => {
    if (!isAdmin) {
      return;
    }
    let active = true;
    void apiFetch<LighthouseStatus>("/packs/microsoft-admin/azure-lighthouse/status")
      .then((result) => {
        if (active) {
          setStatus(result);
        }
      })
      .catch((error) => {
        if (active) {
          showError(error, setMessage, setDanger);
        }
      });
    return () => {
      active = false;
    };
  }, [isAdmin]);

  async function discover(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!connectionReady) {
      showError(new Error("Select a WAIT client and complete the Lighthouse connection fields."), setMessage, setDanger);
      return;
    }
    setBusy("discover");
    setDanger(false);
    setMessage("");
    setInventory(null);
    try {
      const result = await apiFetch<LighthouseDiscovery>("/packs/microsoft-admin/azure-lighthouse/discover", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          client_id: selectedClientId,
          credential_ref: connection.credentialRef.trim(),
          managing_tenant_id: connection.managingTenantId.trim(),
          expected_customer_tenant_id: connection.customerTenantId.trim()
        })
      });
      setDiscovery(result);
      const preferred = result.subscriptions.find((subscription) => subscription.verification_status === "verified")
        ?? result.subscriptions[0];
      setSelectedSubscriptionId(preferred?.subscription_id ?? "");
      setMessage(
        result.subscriptions.length
          ? `Found ${result.subscriptions.length} delegated subscription candidate${result.subscriptions.length === 1 ? "" : "s"}.`
          : "No delegated subscriptions matched this WAIT client and customer tenant."
      );
    } catch (error) {
      showError(error, setMessage, setDanger);
    } finally {
      setBusy(null);
    }
  }

  async function collectInventory() {
    if (!inventoryReady) {
      showError(new Error("Discover and select a delegated subscription first."), setMessage, setDanger);
      return;
    }
    setBusy("inventory");
    setDanger(false);
    setMessage("");
    try {
      const result = await apiFetch<LighthouseInventory>("/packs/microsoft-admin/azure-lighthouse/inventory", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          client_id: selectedClientId,
          credential_ref: connection.credentialRef.trim(),
          managing_tenant_id: connection.managingTenantId.trim(),
          expected_customer_tenant_id: connection.customerTenantId.trim(),
          subscription_id: selectedSubscriptionId,
          resource_group: connection.resourceGroup.trim() || null,
          limit: 200
        })
      });
      setInventory(result);
      setMessage(`Verified ${result.scope} and collected ${result.resources.length} Azure resources.`);
    } catch (error) {
      showError(error, setMessage, setDanger);
    } finally {
      setBusy(null);
    }
  }

  async function generateOnboarding(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!onboardingReady) {
      showError(new Error("Complete the onboarding identity and select a WAIT client."), setMessage, setDanger);
      return;
    }
    setBusy("onboarding");
    setDanger(false);
    setMessage("");
    try {
      const result = await apiFetch<OnboardingBundle>("/packs/microsoft-admin/azure-lighthouse/onboarding/plan", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          client_id: selectedClientId,
          offer_name: onboarding.offerName.trim(),
          offer_description: onboarding.description.trim(),
          managing_tenant_id: connection.managingTenantId.trim(),
          principal_id: onboarding.principalId.trim(),
          principal_display_name: onboarding.principalDisplayName.trim(),
          deployment_scope: onboarding.deploymentScope
        })
      });
      setBundle(result);
      setMessage("Generated a digest-bound Reader-only package for customer review and deployment.");
    } catch (error) {
      showError(error, setMessage, setDanger);
    } finally {
      setBusy(null);
    }
  }

  if (roleResolved && !isAdmin) {
    return (
      <div className="screen-stack">
        <section className="panel">
          <div className="panel-heading">
            <h2>Azure Lighthouse</h2>
            <StatusChip status="blocked" />
          </div>
          <div className="notice danger" role="alert">
            <strong>Administrator access required</strong>
            <p>Cross-tenant Azure delegation and credentials are available to administrators only.</p>
          </div>
        </section>
      </div>
    );
  }

  return (
    <div className="screen-stack">
      <section className="panel">
        <div className="panel-heading">
          <h2>Azure Lighthouse</h2>
          <StatusChip status={status?.status ?? "loading"} />
        </div>
        <p className="screen-note">
          Discover and inspect Azure subscriptions that a customer delegated to WAIT's managing tenant.
          This first integration is read-only and verifies the exact Lighthouse assignment before inventory.
        </p>
        <div className="notice">
          Customers deploy and can remove their own delegation. WAIT does not deploy the onboarding template,
          grant itself access, or expose a generic Azure command surface.
        </div>
        {status ? <p className="screen-note">{status.message}</p> : null}
      </section>

      <section className="panel">
        <div className="panel-heading">
          <h2>Delegated customer discovery</h2>
          <span>{selectedClient?.name ?? "Select a WAIT client"}</span>
        </div>
        <form className="draft-form" onSubmit={discover}>
          <label>
            WAIT client
            <select value={selectedClientId} onChange={(event) => setSelectedClientId(event.target.value)}>
              <option value="">Choose a client</option>
              {clients.map((client) => (
                <option key={client.client_id} value={client.client_id}>{client.name}</option>
              ))}
            </select>
          </label>
          <label>
            Vault credential reference
            <input
              value={connection.credentialRef}
              onChange={(event) => setConnection({ ...connection, credentialRef: event.target.value })}
              placeholder="cloud/azure-lighthouse-managing-tenant"
              autoComplete="off"
            />
          </label>
          <label>
            Managing tenant ID
            <input
              value={connection.managingTenantId}
              onChange={(event) => setConnection({ ...connection, managingTenantId: event.target.value })}
              placeholder="00000000-0000-0000-0000-000000000000"
              autoComplete="off"
            />
          </label>
          <label>
            Expected customer tenant ID
            <input
              value={connection.customerTenantId}
              onChange={(event) => setConnection({ ...connection, customerTenantId: event.target.value })}
              placeholder="00000000-0000-0000-0000-000000000000"
              autoComplete="off"
            />
          </label>
          <label>
            Resource group for resource-group delegation (optional)
            <input
              value={connection.resourceGroup}
              onChange={(event) => setConnection({ ...connection, resourceGroup: event.target.value })}
              placeholder="customer-production"
            />
          </label>
          <div className="row-actions">
            <button type="submit" disabled={!connectionReady || busy !== null}>
              {busy === "discover" ? "Discovering…" : "Discover delegated subscriptions"}
            </button>
            <button
              type="button"
              className="icon-button"
              disabled={!inventoryReady || busy !== null}
              onClick={() => void collectInventory()}
            >
              {busy === "inventory" ? "Collecting…" : "Verify scope and collect inventory"}
            </button>
          </div>
        </form>

        {discovery ? (
          <div className="table-list" aria-label="Delegated subscriptions">
            {discovery.subscriptions.length === 0 ? (
              <p className="screen-note">No matching delegated subscriptions were returned.</p>
            ) : null}
            {discovery.subscriptions.map((subscription) => (
              <article className="table-row" key={subscription.subscription_id}>
                <div>
                  <strong>{subscription.display_name}</strong>
                  <StatusChip status={subscription.verification_status} />
                  <p>{subscription.subscription_id}</p>
                  <p>{subscription.verification_message}</p>
                </div>
                <button
                  type="button"
                  className="icon-button"
                  aria-pressed={selectedSubscriptionId === subscription.subscription_id}
                  onClick={() => {
                    setSelectedSubscriptionId(subscription.subscription_id);
                    setInventory(null);
                  }}
                >
                  {selectedSubscriptionId === subscription.subscription_id ? "Selected" : "Select"}
                </button>
              </article>
            ))}
          </div>
        ) : null}

        {discovery?.source_errors.length ? (
          <div className="notice danger" role="alert">
            <strong>Some delegation checks were unavailable</strong>
            <ul>
              {discovery.source_errors.map((error) => (
                <li key={`${error.source}-${error.code}`}>{error.source}: {error.message}</li>
              ))}
            </ul>
          </div>
        ) : null}
      </section>

      {inventory ? (
        <section className="panel">
          <div className="panel-heading">
            <h2>Verified delegated inventory</h2>
            <StatusChip status={inventory.status} />
          </div>
          <p><strong>Scope:</strong> {inventory.scope}</p>
          <p><strong>Registration assignments:</strong> {inventory.delegations.length}</p>
          <div className="table-list">
            {Object.entries(inventory.resource_type_counts).map(([resourceType, count]) => (
              <article className="table-row" key={resourceType}>
                <strong>{resourceType}</strong>
                <span>{count}</span>
              </article>
            ))}
          </div>
          {inventory.source_errors.length ? (
            <div className="notice danger" role="alert">
              <strong>Some inventory records were excluded</strong>
              <ul>
                {inventory.source_errors.map((error) => (
                  <li key={`${error.source}-${error.code}`}>{error.message}</li>
                ))}
              </ul>
            </div>
          ) : null}
          <div className="table-list" aria-label="Azure resources">
            {inventory.resources.length === 0 ? (
              <p className="screen-note">No Azure resources were returned at the verified scope.</p>
            ) : null}
            {inventory.resources.map((resource) => (
              <article className="table-row" key={resource.resource_id}>
                <div>
                  <strong>{resource.name}</strong>
                  <p>{resource.resource_type}</p>
                  <p>{resource.resource_group || "subscription scope"} · {resource.location || "global"}</p>
                </div>
                <span>{resource.sku_name || resource.kind || "—"}</span>
              </article>
            ))}
          </div>
        </section>
      ) : null}

      <section className="panel">
        <div className="panel-heading">
          <h2>Customer onboarding package</h2>
          <span>Reader only</span>
        </div>
        <p className="screen-note">
          Generate an ARM template and parameter file for the customer to review and deploy. The package
          delegates only the Azure Reader built-in role and contains no credential or secret.
        </p>
        <form className="draft-form" onSubmit={generateOnboarding}>
          <label>
            Offer name
            <input
              value={onboarding.offerName}
              onChange={(event) => setOnboarding({ ...onboarding, offerName: event.target.value })}
            />
          </label>
          <label>
            Offer description
            <textarea
              value={onboarding.description}
              onChange={(event) => setOnboarding({ ...onboarding, description: event.target.value })}
            />
          </label>
          <label>
            Managing-tenant principal object ID
            <input
              value={onboarding.principalId}
              onChange={(event) => setOnboarding({ ...onboarding, principalId: event.target.value })}
              placeholder="Security group or service principal object ID"
              autoComplete="off"
            />
          </label>
          <label>
            Principal display name
            <input
              value={onboarding.principalDisplayName}
              onChange={(event) => setOnboarding({ ...onboarding, principalDisplayName: event.target.value })}
            />
          </label>
          <label>
            Customer deployment scope
            <select
              value={onboarding.deploymentScope}
              onChange={(event) => setOnboarding({
                ...onboarding,
                deploymentScope: event.target.value as "subscription" | "resource_group"
              })}
            >
              <option value="subscription">Subscription</option>
              <option value="resource_group">Resource group</option>
            </select>
          </label>
          <button type="submit" disabled={!onboardingReady || busy !== null}>
            {busy === "onboarding" ? "Generating…" : "Generate onboarding package"}
          </button>
        </form>

        {bundle ? (
          <div className="screen-stack">
            <div className="notice">
              <strong>Bundle digest</strong>
              <p>{bundle.bundle_sha256}</p>
              <ul>
                {bundle.deployment_guidance.map((item) => <li key={item}>{item}</li>)}
              </ul>
            </div>
            <details className="technical-details">
              <summary>ARM template</summary>
              <pre className="code-panel">{JSON.stringify(bundle.template, null, 2)}</pre>
            </details>
            <details className="technical-details">
              <summary>Parameter file</summary>
              <pre className="code-panel">{JSON.stringify(bundle.parameters, null, 2)}</pre>
            </details>
          </div>
        ) : null}
      </section>

      {message ? <div className={`notice${danger ? " danger" : ""}`} role={danger ? "alert" : "status"}>{message}</div> : null}
    </div>
  );
}

