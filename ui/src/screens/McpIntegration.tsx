import { useEffect, useMemo, useState } from "react";
import { Check, Copy, ExternalLink, ShieldCheck } from "lucide-react";
import { apiFetch } from "../api/client";
import { useDashboard } from "../app/DashboardContext";
import { RoleGate } from "../components/RoleGate";
import { StatusChip } from "../components/StatusChip";
import { apiUrl } from "../lib/config";

type McpHandshake = {
  protocolVersion?: string;
  capabilities?: Record<string, unknown>;
  serverInfo?: {
    name?: string;
    version?: string;
    description?: string;
  };
  instructions?: string;
};

type McpInitializeResponse = {
  result?: McpHandshake;
  error?: { message?: string };
};

type McpTool = {
  id: string;
  name: string;
  description: string;
  risk_level?: string;
  required_role?: string;
  approval_required?: boolean;
  access_mode?: string;
};

const verifiedFallbackHandshake: McpHandshake = {
  protocolVersion: "2025-11-25",
  capabilities: { tools: { listChanged: false } },
  serverInfo: {
    name: "wait-local-agent",
    version: "2.0.0-rc.1",
    description: "WAIT's tenant-scoped, approval-aware local agent tool server"
  },
  instructions: "Tool calls remain subject to WAIT tenant scope, RBAC, provider readiness, approval gates, audit logging, and output redaction."
};

function endpointUrl(path: string): string {
  const configuredUrl = apiUrl(path);
  if (/^https?:\/\//.test(configuredUrl) || typeof window === "undefined") {
    return configuredUrl;
  }
  return new URL(configuredUrl, window.location.origin).toString();
}

function formatCapabilities(capabilities: Record<string, unknown> | undefined): string {
  if (!capabilities || Object.keys(capabilities).length === 0) {
    return "None reported";
  }
  return Object.entries(capabilities)
    .map(([name, value]) => {
      if (value && typeof value === "object" && "listChanged" in value) {
        return `${name} (listChanged: ${String((value as { listChanged?: unknown }).listChanged)})`;
      }
      return name;
    })
    .join(", ");
}

function McpIntegrationContent() {
  const [handshake, setHandshake] = useState<McpHandshake>(verifiedFallbackHandshake);
  const [tools, setTools] = useState<McpTool[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [handshakeNote, setHandshakeNote] = useState("");
  const [copied, setCopied] = useState(false);
  const mcpEndpoint = useMemo(() => endpointUrl("/mcp"), []);
  const toolsEndpoint = useMemo(() => endpointUrl("/tools"), []);
  const connectionSnippet = useMemo(() => JSON.stringify({
    mcpServers: {
      "wait-local-agent": {
        url: mcpEndpoint,
        headers: { Authorization: "Bearer <WAIT_API_TOKEN>" }
      }
    }
  }, null, 2), [mcpEndpoint]);

  useEffect(() => {
    let active = true;

    async function loadIntegration() {
      setLoading(true);
      setError("");
      try {
        const [handshakeResult, toolResult] = await Promise.allSettled([
          apiFetch<McpInitializeResponse>("/mcp", {
            method: "POST",
            headers: { "Content-Type": "application/json", Accept: "application/json" },
            body: JSON.stringify({
              jsonrpc: "2.0",
              id: 1,
              method: "initialize",
              params: {
                protocolVersion: verifiedFallbackHandshake.protocolVersion,
                capabilities: {},
                clientInfo: { name: "wait-local-agent-ui", version: "2.0.0-rc.1" }
              }
            })
          }),
          apiFetch<McpTool[]>("/tools")
        ]);
        if (!active) {
          return;
        }
        if (handshakeResult.status === "fulfilled" && handshakeResult.value.result) {
          setHandshake(handshakeResult.value.result);
          setHandshakeNote("Live handshake details loaded from the appliance.");
        } else {
          setHandshake(verifiedFallbackHandshake);
          setHandshakeNote("Static capability summary (live handshake unavailable).");
        }
        if (toolResult.status === "fulfilled") {
          setTools(Array.isArray(toolResult.value) ? toolResult.value : []);
        } else {
          throw toolResult.reason;
        }
      } catch (requestError) {
        if (!active) {
          return;
        }
        setError(requestError instanceof Error ? requestError.message : "Unable to load MCP integration details.");
      } finally {
        if (active) {
          setLoading(false);
        }
      }
    }

    void loadIntegration();
    return () => {
      active = false;
    };
  }, []);

  async function copyConnectionDetails() {
    try {
      await navigator.clipboard.writeText(connectionSnippet);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1800);
    } catch {
      setCopied(false);
    }
  }

  return (
    <section className="screen-stack">
      <section className="panel mcp-hero">
        <div>
          <p className="eyebrow">Integrations</p>
          <h2>MCP server</h2>
          <p className="screen-note">Connect an MCP-compatible client to WAIT's governed local tool catalog. This page is read-only; tool calls still pass through tenant scope, RBAC, approval, and audit controls.</p>
        </div>
        <StatusChip status="available" hint="The MCP endpoint is published by this appliance." />
      </section>

      {error ? <div className="notice danger" role="alert">{error}</div> : null}

      <section className="panel">
        <div className="panel-heading">
          <h2>Connection details</h2>
          <span>admin/developer view</span>
        </div>
        <div className="mcp-detail-grid">
          <div>
            <dt>MCP endpoint</dt>
            <dd><code>{mcpEndpoint}</code></dd>
          </div>
          <div>
            <dt>Transport</dt>
            <dd>Streamable HTTP via <code>POST /mcp</code></dd>
          </div>
          <div>
            <dt>Protocol</dt>
            <dd>{loading ? "Loading…" : handshake.protocolVersion ?? "Not reported"}</dd>
          </div>
          <div>
            <dt>Capabilities</dt>
            <dd>{loading ? "Loading…" : formatCapabilities(handshake.capabilities)}</dd>
          </div>
        </div>
        {handshakeNote ? <p className="screen-note">{handshakeNote}</p> : null}
        {handshake.serverInfo?.description ? <p className="screen-note">{handshake.serverInfo.description}</p> : null}
      </section>

      <section className="panel">
        <div className="panel-heading">
          <div>
            <h2>How to connect</h2>
            <span>Use a bearer token with the client request.</span>
          </div>
          <button className="icon-button" type="button" onClick={() => void copyConnectionDetails()}>
            {copied ? <Check size={17} aria-hidden="true" /> : <Copy size={17} aria-hidden="true" />}
            {copied ? "Copied" : "Copy configuration"}
          </button>
        </div>
        <ol className="mcp-steps">
          <li>Add the endpoint to your MCP client configuration.</li>
          <li>Send <code>Authorization: Bearer &lt;WAIT_API_TOKEN&gt;</code> with requests.</li>
          <li>Allow the client to initialize, then list tools. Do not share the token in prompts or logs.</li>
        </ol>
        <pre className="mcp-code"><code>{connectionSnippet}</code></pre>
        <p className="screen-note"><ShieldCheck size={16} aria-hidden="true" /> The token is used only for authentication. WAIT continues to enforce tenant scope, role checks, provider readiness, approval gates, audit logging, and redaction.</p>
      </section>

      <section className="panel">
        <div className="panel-heading">
          <div>
            <h2>Published tool catalog</h2>
            <span><code>{toolsEndpoint}</code></span>
          </div>
          <span>{loading ? "Loading…" : `${tools.length} tool${tools.length === 1 ? "" : "s"}`}</span>
        </div>
        {!loading && tools.length === 0 ? <p className="screen-note">No tools are currently published to the catalog.</p> : null}
        <div className="mcp-tool-list">
          {tools.map((tool) => (
            <article className="mcp-tool" key={tool.id}>
              <div>
                <h3>{tool.name}</h3>
                <p className="mcp-tool-id"><code>{tool.id}</code></p>
                <p>{tool.description}</p>
              </div>
              <div className="mcp-tool-meta">
                {tool.risk_level ? <StatusChip status={tool.risk_level} hint="Published risk level" /> : null}
                {tool.access_mode ? <StatusChip status={tool.access_mode === "read" ? "available" : "write"} hint="Access mode" /> : null}
                {tool.approval_required ? <StatusChip status="pending_approval" hint="Approval is required before execution." /> : <StatusChip status="not_required" hint="No approval flag was published." />}
                {tool.required_role ? <span className="mcp-role">Role: {tool.required_role}</span> : null}
              </div>
            </article>
          ))}
        </div>
      </section>

      <p className="screen-note"><ExternalLink size={15} aria-hidden="true" /> The catalog is sourced from the existing <code>GET /tools</code> endpoint. This screen does not call tools or create approvals.</p>
    </section>
  );
}

export function McpIntegration() {
  const { role, roleResolved } = useDashboard();
  const fallback = (
    <section className="panel">
      <h2>{roleResolved ? "MCP integrations" : "Checking access"}</h2>
      <p className="screen-note">{roleResolved ? "Administrator role required. MCP connection details and tool metadata are not available to this role." : "Confirming your administrator access before loading MCP details…"}</p>
    </section>
  );

  return (
    <RoleGate role={role} resolved={roleResolved} allowed={["admin"]} fallback={fallback}>
      <McpIntegrationContent />
    </RoleGate>
  );
}
