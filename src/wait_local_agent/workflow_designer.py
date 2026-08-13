"""Bounded workflow graph definitions for the local consultant designer."""

from __future__ import annotations

import json
import re
from typing import Literal, cast

from wait_local_agent.models import WorkflowTemplate
from wait_local_agent.reports.renderers import redact_text, redact_value

WorkflowNodeType = Literal[
    "trigger",
    "action",
    "approval",
    "condition",
    "knowledge",
    "connector",
    "notification",
    "end",
]

MAX_WORKFLOW_DESIGN_NODES = 32
MAX_WORKFLOW_DESIGN_EDGES = 64
MAX_WORKFLOW_DESIGN_LABEL = 160
MAX_WORKFLOW_DESIGN_TOOL_ID = 160
MAX_WORKFLOW_DESIGN_CONFIG_BYTES = 8 * 1024
_NODE_ID = re.compile(r"^[a-z0-9][a-z0-9_.:-]{0,63}$")
_NODE_TYPES = frozenset({"trigger", "action", "approval", "condition", "knowledge", "connector", "notification", "end"})


class WorkflowDesignError(ValueError):
    """Raised when a visual workflow definition is not bounded or coherent."""


def default_workflow_design(template: WorkflowTemplate) -> dict[str, object]:
    """Return a safe design-only graph derived from an existing template."""

    nodes: list[dict[str, object]] = [
        {"id": "trigger", "type": "trigger", "label": template.trigger, "tool_id": None, "config": {}},
        {
            "id": "action",
            "type": "action",
            "label": template.name,
            "tool_id": template.tool_id,
            "config": {},
        },
    ]
    edges: list[dict[str, str]] = [{"from": "trigger", "to": "action"}]
    previous = "action"
    if template.approval_required:
        nodes.append(
            {
                "id": "approval",
                "type": "approval",
                "label": "Human approval",
                "tool_id": None,
                "config": {},
            }
        )
        edges.append({"from": previous, "to": "approval"})
        previous = "approval"
    nodes.append({"id": "end", "type": "end", "label": "Complete", "tool_id": None, "config": {}})
    edges.append({"from": previous, "to": "end"})
    return normalize_workflow_design(
        {
            "format": "wait-local-agent.workflow-design",
            "version": 1,
            "nodes": nodes,
            "edges": edges,
        }
    )


def normalize_workflow_design(payload: object) -> dict[str, object]:
    """Validate and redact a graph before it is persisted or exported."""

    if not isinstance(payload, dict):
        raise WorkflowDesignError("workflow definition must be an object")
    allowed = {"format", "version", "nodes", "edges"}
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise WorkflowDesignError(f"unsupported workflow definition fields: {', '.join(unknown)}")
    if payload.get("format") != "wait-local-agent.workflow-design":
        raise WorkflowDesignError("workflow definition format is invalid")
    if payload.get("version") != 1:
        raise WorkflowDesignError("workflow definition version is unsupported")
    raw_nodes = payload.get("nodes")
    raw_edges = payload.get("edges")
    if not isinstance(raw_nodes, list) or not raw_nodes:
        raise WorkflowDesignError("workflow definition nodes must be a non-empty array")
    if len(raw_nodes) > MAX_WORKFLOW_DESIGN_NODES:
        raise WorkflowDesignError(f"workflow definition may contain at most {MAX_WORKFLOW_DESIGN_NODES} nodes")
    if not isinstance(raw_edges, list) or len(raw_edges) > MAX_WORKFLOW_DESIGN_EDGES:
        raise WorkflowDesignError(f"workflow definition may contain 0-{MAX_WORKFLOW_DESIGN_EDGES} edges")

    nodes: list[dict[str, object]] = []
    node_ids: set[str] = set()
    for index, raw_node in enumerate(raw_nodes):
        if not isinstance(raw_node, dict):
            raise WorkflowDesignError(f"workflow node {index} must be an object")
        if set(raw_node) - {"id", "type", "label", "tool_id", "config"}:
            raise WorkflowDesignError(f"workflow node {index} contains unsupported fields")
        node_id = _identifier(raw_node.get("id"), f"workflow node {index}.id")
        if node_id in node_ids:
            raise WorkflowDesignError(f"workflow node ids must be unique: {node_id}")
        node_ids.add(node_id)
        node_type = raw_node.get("type")
        if not isinstance(node_type, str) or node_type not in _NODE_TYPES:
            raise WorkflowDesignError(f"workflow node {index}.type is unsupported")
        label = _text(raw_node.get("label"), f"workflow node {index}.label", MAX_WORKFLOW_DESIGN_LABEL)
        tool_id = raw_node.get("tool_id")
        if tool_id is not None:
            tool_id = _text(tool_id, f"workflow node {index}.tool_id", MAX_WORKFLOW_DESIGN_TOOL_ID)
        config = raw_node.get("config", {})
        if not isinstance(config, dict):
            raise WorkflowDesignError(f"workflow node {index}.config must be an object")
        safe_config = cast(dict[str, object], redact_value(config))
        try:
            encoded_config = json.dumps(safe_config, sort_keys=True, separators=(",", ":"))
        except (TypeError, ValueError) as exc:
            raise WorkflowDesignError(f"workflow node {index}.config is not serializable") from exc
        if len(encoded_config.encode("utf-8")) > MAX_WORKFLOW_DESIGN_CONFIG_BYTES:
            raise WorkflowDesignError(f"workflow node {index}.config is too large")
        nodes.append(
            {
                "id": node_id,
                "type": cast(WorkflowNodeType, node_type),
                "label": redact_text(label),
                "tool_id": redact_text(tool_id) if isinstance(tool_id, str) else None,
                "config": safe_config,
            }
        )

    if sum(1 for node in nodes if node["type"] == "trigger") != 1:
        raise WorkflowDesignError("workflow definition requires exactly one trigger node")
    if sum(1 for node in nodes if node["type"] == "end") != 1:
        raise WorkflowDesignError("workflow definition requires exactly one end node")

    edges: list[dict[str, str]] = []
    edge_pairs: set[tuple[str, str]] = set()
    adjacency: dict[str, list[str]] = {node_id: [] for node_id in node_ids}
    for index, raw_edge in enumerate(raw_edges):
        if not isinstance(raw_edge, dict) or set(raw_edge) != {"from", "to"}:
            raise WorkflowDesignError(f"workflow edge {index} must contain only from and to")
        source = _identifier(raw_edge.get("from"), f"workflow edge {index}.from")
        target = _identifier(raw_edge.get("to"), f"workflow edge {index}.to")
        if source not in node_ids or target not in node_ids:
            raise WorkflowDesignError(f"workflow edge {index} references an unknown node")
        if source == target:
            raise WorkflowDesignError("workflow edges cannot point to the same node")
        if (source, target) in edge_pairs:
            raise WorkflowDesignError("workflow edges must be unique")
        edge_pairs.add((source, target))
        adjacency[source].append(target)
        edges.append({"from": source, "to": target})

    _ensure_acyclic(adjacency)
    trigger_id = next(node["id"] for node in nodes if node["type"] == "trigger")
    end_id = next(node["id"] for node in nodes if node["type"] == "end")
    reachable = _reachable(adjacency, cast(str, trigger_id))
    if len(reachable) != len(node_ids):
        raise WorkflowDesignError("every workflow node must be reachable from the trigger")
    reverse: dict[str, list[str]] = {node_id: [] for node_id in node_ids}
    for source, targets in adjacency.items():
        for target in targets:
            reverse[target].append(source)
    if len(_reachable(reverse, cast(str, end_id))) != len(node_ids):
        raise WorkflowDesignError("every workflow node must lead to the end node")
    return {
        "format": "wait-local-agent.workflow-design",
        "version": 1,
        "nodes": nodes,
        "edges": edges,
    }


def _text(value: object, field: str, limit: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise WorkflowDesignError(f"{field} must be non-empty text")
    normalized = value.strip()
    if len(normalized) > limit:
        raise WorkflowDesignError(f"{field} exceeds {limit} characters")
    if any(ord(character) < 32 and character not in "\t\n" for character in normalized):
        raise WorkflowDesignError(f"{field} contains unsupported control characters")
    return normalized


def _identifier(value: object, field: str) -> str:
    normalized = _text(value, field, 64)
    if not _NODE_ID.fullmatch(normalized):
        raise WorkflowDesignError(f"{field} must be a lowercase identifier")
    return normalized


def _ensure_acyclic(adjacency: dict[str, list[str]]) -> None:
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node_id: str) -> None:
        if node_id in visiting:
            raise WorkflowDesignError("workflow graph must not contain cycles")
        if node_id in visited:
            return
        visiting.add(node_id)
        for child in adjacency[node_id]:
            visit(child)
        visiting.remove(node_id)
        visited.add(node_id)

    for node_id in adjacency:
        visit(node_id)


def _reachable(adjacency: dict[str, list[str]], start: str) -> set[str]:
    reached: set[str] = set()
    pending = [start]
    while pending:
        current = pending.pop()
        if current in reached:
            continue
        reached.add(current)
        pending.extend(adjacency[current])
    return reached
