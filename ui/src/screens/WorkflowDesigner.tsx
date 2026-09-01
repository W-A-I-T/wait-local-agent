import { useCallback, useEffect, useMemo, useState } from "react";
import { useDashboard } from "../app/DashboardContext";
import { apiFetch } from "../api/client";
import { Link } from "react-router-dom";
import { EmptyState } from "../components/EmptyState";
import { LoadingState } from "../components/LoadingState";
import type {
  TemplateGalleryEntry,
  WorkflowDesign,
  WorkflowDesignNode,
  WorkflowNodeType,
  WorkflowTemplate
} from "../api/types";

const NODE_TYPES: WorkflowNodeType[] = ["action", "approval", "condition", "knowledge", "connector", "notification"];

function defaultDesign(template: WorkflowTemplate): WorkflowDesign {
  const nodes: WorkflowDesignNode[] = [
    { id: "trigger", type: "trigger", label: template.trigger, tool_id: null, config: {} },
    { id: "action", type: "action", label: template.name, tool_id: template.tool_id ?? null, config: {} }
  ];
  const edges = [{ from: "trigger", to: "action" }];
  let previous = "action";
  if (template.approval_required) {
    nodes.push({ id: "approval", type: "approval", label: "Human approval", tool_id: null, config: {} });
    edges.push({ from: previous, to: "approval" });
    previous = "approval";
  }
  nodes.push({ id: "end", type: "end", label: "Complete", tool_id: null, config: {} });
  edges.push({ from: previous, to: "end" });
  return { format: "wait-local-agent.workflow-design", version: 1, nodes, edges };
}

function isWorkflowDesign(value: WorkflowDesign | undefined): value is WorkflowDesign {
  return value?.format === "wait-local-agent.workflow-design"
    && value.version === 1
    && Array.isArray(value.nodes)
    && Array.isArray(value.edges);
}

export function WorkflowDesigner() {
  const { canWrite, selectedClientId } = useDashboard();
  const [templates, setTemplates] = useState<WorkflowTemplate[]>([]);
  const [entries, setEntries] = useState<TemplateGalleryEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedId, setSelectedId] = useState("");
  const [sourceTemplateId, setSourceTemplateId] = useState("");
  const [design, setDesign] = useState<WorkflowDesign | null>(null);
  const [selectedNodeId, setSelectedNodeId] = useState("");
  const [newNodeType, setNewNodeType] = useState<WorkflowNodeType>("action");
  const [newNodeLabel, setNewNodeLabel] = useState("");
  const [connectFrom, setConnectFrom] = useState("");
  const [connectTo, setConnectTo] = useState("");
  const [message, setMessage] = useState("");

  const selectedEntry = entries.find((entry) => entry.id === selectedId);
  const selectedTemplate = templates.find((template) => template.id === (selectedEntry?.source_template_id ?? sourceTemplateId));
  const selectedNode = design?.nodes.find((node) => node.id === selectedNodeId);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [templateRows, galleryRows] = await Promise.all([
        apiFetch<WorkflowTemplate[]>("/workflows/templates"),
        apiFetch<TemplateGalleryEntry[]>("/workflow-templates/gallery")
      ]);
      setTemplates(templateRows);
      setEntries(galleryRows);
      setSourceTemplateId((current) => current || templateRows[0]?.id || "");
      setSelectedId((current) => current || galleryRows[0]?.id || "");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to load workflow designs.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    if (!selectedEntry) {
      setDesign(null);
      setSelectedNodeId("");
      return;
    }
    const template = templates.find((item) => item.id === selectedEntry.source_template_id);
    setDesign(isWorkflowDesign(selectedEntry.definition) ? selectedEntry.definition : (template ? defaultDesign(template) : null));
    setSelectedNodeId("");
    setConnectFrom("");
    setConnectTo("");
  }, [selectedEntry, templates]);

  const nodeOptions = useMemo(() => design?.nodes ?? [], [design]);

  async function createDesign() {
    if (!selectedClientId) {
      setMessage("Select a client from the top bar to create a workflow design.");
      return;
    }
    if (!sourceTemplateId) {
      setMessage("Choose a reviewed template first.");
      return;
    }
    const sourceTemplate = templates.find((template) => template.id === sourceTemplateId);
    if (!sourceTemplate) {
      setMessage("The selected template is unavailable. Refresh and try again.");
      return;
    }
    try {
      const created = await apiFetch<TemplateGalleryEntry>("/workflow-templates/gallery", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          source_template_id: sourceTemplateId,
          provenance: "Workflow designer draft",
          definition: defaultDesign(sourceTemplate),
          client_id: selectedClientId
        })
      });
      setEntries((current) => [...current, created]);
      setSelectedId(created.id);
      setMessage("Design created locally. Review it before enabling or running the template.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to create workflow design.");
    }
  }

  async function saveDesign() {
    if (!selectedEntry || !design || !selectedClientId) {
      if (!selectedClientId) setMessage("Select a client from the top bar to save this workflow design.");
      return;
    }
    try {
      const updated = await apiFetch<TemplateGalleryEntry>(`/workflow-templates/gallery/${encodeURIComponent(selectedEntry.id)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ definition: design, client_id: selectedClientId })
      });
      setEntries((current) => current.map((entry) => entry.id === updated.id ? updated : entry));
      setMessage(`Saved ${updated.name} as version ${updated.version}. The design remains side-effect free.`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to save workflow design.");
    }
  }

  function updateNode(nodeId: string, patch: Partial<WorkflowDesignNode>) {
    setDesign((current) => current ? {
      ...current,
      nodes: current.nodes.map((node) => node.id === nodeId ? { ...node, ...patch } : node)
    } : current);
  }

  function addNode() {
    if (!design || !newNodeLabel.trim()) {
      setMessage("Provide a label before adding a node.");
      return;
    }
    let suffix = design.nodes.length + 1;
    let id = `node-${suffix}`;
    while (design.nodes.some((node) => node.id === id)) {
      suffix += 1;
      id = `node-${suffix}`;
    }
    setDesign({
      ...design,
      nodes: [...design.nodes, { id, type: newNodeType, label: newNodeLabel.trim(), tool_id: null, config: {} }]
    });
    setSelectedNodeId(id);
    setNewNodeLabel("");
  }

  function removeSelectedNode() {
    if (!design || !selectedNode || selectedNode.type === "trigger" || selectedNode.type === "end") {
      setMessage("Trigger and end nodes are required.");
      return;
    }
    setDesign({
      ...design,
      nodes: design.nodes.filter((node) => node.id !== selectedNode.id),
      edges: design.edges.filter((edge) => edge.from !== selectedNode.id && edge.to !== selectedNode.id)
    });
    setSelectedNodeId("");
  }

  function connectNodes() {
    if (!design || !connectFrom || !connectTo || connectFrom === connectTo) {
      setMessage("Choose two different nodes to connect.");
      return;
    }
    if (design.edges.some((edge) => edge.from === connectFrom && edge.to === connectTo)) {
      setMessage("That connection already exists.");
      return;
    }
    setDesign({ ...design, edges: [...design.edges, { from: connectFrom, to: connectTo }] });
  }

  return (
    <div className="screen-stack">
      <section className="panel">
        <div className="panel-heading">
          <div><h2>Workflow Designer</h2><span>Design-only graph editor</span></div>
          <span>{design ? `${design.nodes.length} nodes · ${design.edges.length} connections` : "choose a design"}</span>
        </div>
        <p className="screen-note">
          Build a bounded trigger/action/approval graph from reviewed local templates. Saving changes the local design artifact only; it never runs a workflow or calls a provider.
        </p>
        <p className="screen-note automation-cross-link"><Link to="/workflows">Run your source template from the Run tab</Link></p>
        <div className="grid">
          <label>Local design<select value={selectedId} onChange={(event) => setSelectedId(event.target.value)}>
            <option value="">Choose a local design</option>
            {entries.map((entry) => <option key={entry.id} value={entry.id}>{entry.name} · v{entry.version}</option>)}
          </select></label>
          <label>Reviewed template<select value={sourceTemplateId} onChange={(event) => setSourceTemplateId(event.target.value)}>
            <option value="">Choose template</option>
            {templates.map((template) => <option key={template.id} value={template.id}>{template.name}</option>)}
          </select></label>
        </div>
        <div className="designer-actions">
          <button type="button" disabled={!canWrite || !selectedClientId || !sourceTemplateId} title={!canWrite ? "Requires technician access" : !selectedClientId ? "Select a client from the top bar first" : !sourceTemplateId ? "Choose a reviewed template first" : undefined} onClick={() => void createDesign()}>Create design</button>
          <button type="button" disabled={!canWrite || !selectedClientId || !selectedEntry || !design} title={!canWrite ? "Requires technician access" : !selectedClientId ? "Select a client from the top bar first" : !selectedEntry || !design ? "Choose a local design first" : undefined} onClick={() => void saveDesign()}>Save design</button>
          {selectedTemplate ? <span className="status-pill">Source: {selectedTemplate.name}</span> : null}
        </div>
        {message ? <div className="notice" role="status">{message}</div> : null}
      </section>

      {loading ? <LoadingState label="Loading workflow designs…" /> : !design ? <EmptyState title="No design selected" why="Create a local design from a reviewed template to begin." /> : (
        <>
          <section className="panel">
            <div className="panel-heading"><h2>Workflow canvas</h2><span>Trigger → bounded steps → end</span></div>
            <div className="workflow-canvas" aria-label="Workflow design canvas">
              {design.nodes.map((node) => (
                <button
                  type="button"
                  key={node.id}
                  className={`workflow-node ${node.id === selectedNodeId ? "selected" : ""}`}
                  aria-label={`${node.type} ${node.label}`}
                  onClick={() => setSelectedNodeId(node.id)}
                >
                  <span className="workflow-node-type">{node.type}</span>
                  <strong>{node.label}</strong>
                  <small>{node.tool_id || node.id}</small>
                </button>
              ))}
            </div>
            <div className="workflow-edges" aria-label="Workflow connections">
              {design.edges.length === 0 ? <p>No connections yet. Add one below.</p> : null}
              {design.edges.map((edge) => <span key={`${edge.from}-${edge.to}`}>{edge.from} <b>→</b> {edge.to}</span>)}
            </div>
          </section>

          <section className="designer-grid">
            <div className="panel">
              <div className="panel-heading"><h2>Node editor</h2><span>{selectedNode ? selectedNode.id : "select a node"}</span></div>
              {selectedNode ? <>
                <label>Node label<input aria-label="Node label" value={selectedNode.label} onChange={(event) => updateNode(selectedNode.id, { label: event.target.value })} /></label>
                <label>Tool id (optional)<input value={selectedNode.tool_id ?? ""} onChange={(event) => updateNode(selectedNode.id, { tool_id: event.target.value || null })} /></label>
                <p className="screen-note">Type: {selectedNode.type}. Node configuration stays bounded JSON and is validated by the server.</p>
                <button type="button" disabled={!canWrite || selectedNode.type === "trigger" || selectedNode.type === "end"} title={!canWrite ? "Requires technician access" : selectedNode.type === "trigger" || selectedNode.type === "end" ? "Trigger and end nodes are required" : undefined} onClick={removeSelectedNode}>Remove node</button>
              </> : <p>Select a node on the canvas to edit it.</p>}
            </div>
            <div className="panel">
              <div className="panel-heading"><h2>Add node</h2><span>bounded palette</span></div>
              <label>Type<select value={newNodeType} onChange={(event) => setNewNodeType(event.target.value as WorkflowNodeType)}>
                {NODE_TYPES.map((type) => <option key={type} value={type}>{type}</option>)}
              </select></label>
              <label>New node label<input aria-label="New node label" value={newNodeLabel} onChange={(event) => setNewNodeLabel(event.target.value)} placeholder="Validate manager" /></label>
              <button type="button" disabled={!canWrite || !newNodeLabel.trim() || design.nodes.length >= 32} title={!canWrite ? "Requires technician access" : !newNodeLabel.trim() ? "Provide a node label first" : design.nodes.length >= 32 ? "A design can contain at most 32 nodes" : undefined} onClick={addNode}>Add node</button>
            </div>
            <div className="panel">
              <div className="panel-heading"><h2>Connect nodes</h2><span>acyclic graph</span></div>
              <label>From<select value={connectFrom} onChange={(event) => setConnectFrom(event.target.value)}>
                <option value="">Choose source</option>{nodeOptions.map((node) => <option key={`from-${node.id}`} value={node.id}>{node.label}</option>)}
              </select></label>
              <label>To<select value={connectTo} onChange={(event) => setConnectTo(event.target.value)}>
                <option value="">Choose destination</option>{nodeOptions.map((node) => <option key={`to-${node.id}`} value={node.id}>{node.label}</option>)}
              </select></label>
              <button type="button" disabled={!canWrite || !connectFrom || !connectTo} title={!canWrite ? "Requires technician access" : !connectFrom || !connectTo ? "Choose a source and destination node" : undefined} onClick={connectNodes}>Add connection</button>
            </div>
          </section>
        </>
      )}
    </div>
  );
}
