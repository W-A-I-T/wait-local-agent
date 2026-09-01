import { useState } from "react";
import { Search } from "lucide-react";
import type { ConnectorStatus, AgentTool } from "../api/types";

const MAX_AGENT_TOOLS = 8;

type ToolGroupDefinition = {
  key: string;
  label: string;
  prefixes: string[];
  connectorIds: string[];
};

const TOOL_GROUPS: ToolGroupDefinition[] = [
  { key: "halopsa", label: "HaloPSA", prefixes: ["halopsa"], connectorIds: ["halopsa"] },
  { key: "connectwise", label: "ConnectWise", prefixes: ["connectwise"], connectorIds: ["connectwise"] },
  { key: "autotask", label: "Autotask", prefixes: ["autotask"], connectorIds: ["autotask"] },
  { key: "servicenow", label: "ServiceNow", prefixes: ["servicenow"], connectorIds: ["servicenow"] },
  { key: "syncro", label: "Syncro", prefixes: ["syncro"], connectorIds: ["syncro"] },
  { key: "m365", label: "Microsoft 365", prefixes: ["m365"], connectorIds: ["m365"] },
  { key: "teams", label: "Microsoft Teams", prefixes: ["teams"], connectorIds: ["m365"] },
  { key: "nsight", label: "N-sight", prefixes: ["nsight"], connectorIds: ["rmm"] },
  { key: "rmm", label: "RMM", prefixes: ["rmm"], connectorIds: ["rmm"] },
  { key: "screenconnect", label: "ScreenConnect", prefixes: ["screenconnect"], connectorIds: ["rmm"] },
  { key: "scalepad", label: "ScalePad", prefixes: ["scalepad"], connectorIds: ["scalepad"] },
  { key: "notion", label: "Notion", prefixes: ["notion"], connectorIds: ["notion"] },
  {
    key: "documentation",
    label: "Documentation",
    prefixes: ["hudu", "itglue", "confluence", "sharepoint"],
    connectorIds: ["hudu", "itglue", "confluence", "sharepoint"]
  },
  { key: "timezest", label: "TimeZest", prefixes: ["timezest"], connectorIds: ["timezest"] },
  { key: "core", label: "Core / ticket intelligence", prefixes: [], connectorIds: [] }
];

type AgentToolPickerProps = {
  tools: AgentTool[];
  selectedTools: string[];
  connectors: ConnectorStatus[];
  onToggle: (tool: AgentTool) => void;
  onLimitReached: () => void;
};

export function AgentToolPicker({
  tools,
  selectedTools,
  connectors,
  onToggle,
  onLimitReached
}: AgentToolPickerProps) {
  const [search, setSearch] = useState("");
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(new Set());
  const query = search.trim().toLowerCase();
  const groupedTools = groupTools(tools);

  return (
    <div className="agent-tool-picker">
      <label className="agent-tool-search">
        Search tools
        <span className="search-box">
          <Search size={17} aria-hidden="true" />
          <input
            aria-label="Search tools"
            type="search"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Search by name, title, or description"
          />
        </span>
      </label>
      <div className="agent-tool-groups">
        {groupedTools.map((group) => {
          const visibleTools = group.tools.filter((tool) => matchesTool(tool, query));
          if (visibleTools.length === 0) return null;
          const selectedCount = group.tools.filter((tool) => selectedTools.includes(tool.id)).length;
          const connectorNotConfigured = group.connectorIds.some((connectorId) =>
            connectors.some((connector) => connector.id === connectorId && connector.status === "not_configured")
          );
          const open = Boolean(query) || expandedGroups.has(group.key) || selectedCount > 0;

          return (
            <details
              className="agent-tool-group"
              key={group.key}
              open={open}
              onToggle={(event) => {
                const nextOpen = event.currentTarget.open;
                setExpandedGroups((current) => {
                  const next = new Set(current);
                  if (nextOpen) next.add(group.key);
                  else next.delete(group.key);
                  return next;
                });
              }}
            >
              <summary className="agent-tool-group-summary">
                <span className="agent-tool-group-heading">
                  <strong>{group.label}</strong>
                  <span>{group.tools.length} tools · {selectedCount} selected</span>
                </span>
                {connectorNotConfigured ? (
                  <span className="agent-tool-badge connector-warning">connector not configured</span>
                ) : null}
              </summary>
              <div className="agent-tool-options">
                {visibleTools.map((tool) => {
                  const selected = selectedTools.includes(tool.id);
                  const atLimit = selectedTools.length >= MAX_AGENT_TOOLS;
                  const risk = tool.risk_level?.trim();
                  return (
                    <label className="agent-tool-option" key={tool.id} title={tool.description}>
                      <input
                        type="checkbox"
                        aria-label={tool.name}
                        checked={selected}
                        disabled={!selected && atLimit}
                        onChange={() => {
                          if (!selected && atLimit) {
                            onLimitReached();
                            return;
                          }
                          onToggle(tool);
                        }}
                      />
                      <span className="agent-tool-name">{tool.name}</span>
                      <span className="agent-tool-badges" aria-hidden="true">
                        {tool.approval_required ? <span className="agent-tool-badge">approval</span> : null}
                        {risk ? <span className={`agent-tool-badge risk-${risk.toLowerCase().replace(/[^a-z0-9]+/g, "-")}`}>{risk}</span> : null}
                      </span>
                    </label>
                  );
                })}
              </div>
            </details>
          );
        })}
      </div>
    </div>
  );
}

function groupTools(tools: AgentTool[]): Array<ToolGroupDefinition & { tools: AgentTool[] }> {
  return TOOL_GROUPS.map((group) => ({
    ...group,
    tools: tools.filter((tool) => group.key === "core"
      ? !TOOL_GROUPS.some((candidate) => candidate.key !== "core" && candidate.prefixes.some((prefix) => hasPrefix(tool.id, prefix)))
      : group.prefixes.some((prefix) => hasPrefix(tool.id, prefix)))
  })).filter((group) => group.tools.length > 0);
}

function hasPrefix(value: string, prefix: string): boolean {
  return value === prefix || value.startsWith(`${prefix}-`) || value.startsWith(`${prefix}.`);
}

function matchesTool(tool: AgentTool, query: string): boolean {
  if (!query) return true;
  return [tool.name, tool.title, tool.description]
    .filter((value): value is string => Boolean(value))
    .some((value) => value.toLowerCase().includes(query));
}
