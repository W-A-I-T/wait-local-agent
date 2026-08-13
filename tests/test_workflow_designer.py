from __future__ import annotations

from typing import cast

import pytest

from wait_local_agent.workflow_designer import (
    MAX_WORKFLOW_DESIGN_CONFIG_BYTES,
    WorkflowDesignError,
    default_workflow_design,
    normalize_workflow_design,
)
from wait_local_agent.workflows import get_workflow_template


def _design(*, nodes: list[dict[str, object]], edges: list[dict[str, str]]) -> dict[str, object]:
    return {
        "format": "wait-local-agent.workflow-design",
        "version": 1,
        "nodes": nodes,
        "edges": edges,
    }


def _linear_design() -> dict[str, object]:
    return _design(
        nodes=[
            {"id": "trigger", "type": "trigger", "label": "Start", "config": {}},
            {"id": "action", "type": "action", "label": "Act", "config": {}},
            {"id": "end", "type": "end", "label": "Done", "config": {}},
        ],
        edges=[
            {"from": "trigger", "to": "action"},
            {"from": "action", "to": "end"},
        ],
    )


def test_default_design_preserves_reviewed_template_approval_gate() -> None:
    template = get_workflow_template("assign-technician")
    assert template is not None

    normalized = default_workflow_design(template)

    nodes = cast(list[dict[str, object]], normalized["nodes"])
    assert [node["type"] for node in nodes] == [
        "trigger",
        "action",
        "approval",
        "end",
    ]
    edges = cast(list[dict[str, object]], normalized["edges"])
    assert edges[-1] == {"from": "approval", "to": "end"}


def test_normalize_design_redacts_untrusted_labels_and_accepts_branching() -> None:
    normalized = normalize_workflow_design(
        _design(
            nodes=[
                {"id": "trigger", "type": "trigger", "label": "Ticket", "config": {}},
                {"id": "condition", "type": "condition", "label": "Route", "config": {}},
                {"id": "action-a", "type": "action", "label": "token=secret-a", "config": {}},
                {"id": "action-b", "type": "action", "label": "Notify", "config": {}},
                {"id": "end", "type": "end", "label": "Done", "config": {}},
            ],
            edges=[
                {"from": "trigger", "to": "condition"},
                {"from": "condition", "to": "action-a"},
                {"from": "condition", "to": "action-b"},
                {"from": "action-a", "to": "end"},
                {"from": "action-b", "to": "end"},
            ],
        )
    )

    nodes = cast(list[dict[str, object]], normalized["nodes"])
    assert nodes[2]["label"] == "token=[redacted]"


@pytest.mark.parametrize(
    ("nodes", "edges", "message"),
    [
        (
            [
                {"id": "trigger", "type": "trigger", "label": "Start", "config": {}},
                {"id": "end", "type": "end", "label": "Done", "config": {}},
            ],
            [{"from": "trigger", "to": "end"}, {"from": "end", "to": "trigger"}],
            "cycles",
        ),
        (
            [
                {"id": "trigger", "type": "trigger", "label": "Start", "config": {}},
                {"id": "orphan", "type": "action", "label": "Orphan", "config": {}},
                {"id": "end", "type": "end", "label": "Done", "config": {}},
            ],
            [{"from": "trigger", "to": "end"}],
            "reachable",
        ),
        (
            [
                {"id": "trigger", "type": "trigger", "label": "Start", "config": {}},
                {
                    "id": "end",
                    "type": "end",
                    "label": "Done",
                    "config": {"large": "x" * MAX_WORKFLOW_DESIGN_CONFIG_BYTES},
                },
            ],
            [{"from": "trigger", "to": "end"}],
            "too large",
        ),
    ],
)
def test_normalize_design_rejects_unsafe_or_incoherent_graphs(
    nodes: list[dict[str, object]],
    edges: list[dict[str, str]],
    message: str,
) -> None:
    with pytest.raises(WorkflowDesignError, match=message):
        normalize_workflow_design(_design(nodes=nodes, edges=edges))


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (None, "must be an object"),
        ({**_linear_design(), "extra": True}, "unsupported workflow definition fields"),
        ({**_linear_design(), "format": "other"}, "format is invalid"),
        ({**_linear_design(), "version": 2}, "version is unsupported"),
        ({**_linear_design(), "nodes": []}, "non-empty array"),
        ({**_linear_design(), "nodes": [{}] * 33}, "at most 32"),
        ({**_linear_design(), "edges": [{}] * 65}, "0-64 edges"),
        ({**_linear_design(), "nodes": ["not a node"]}, "node 0 must be an object"),
        (
            {
                **_linear_design(),
                "nodes": [
                    {"id": "trigger", "type": "trigger", "label": "Start", "config": {}, "extra": True},
                    {"id": "action", "type": "action", "label": "Act", "config": {}},
                    {"id": "end", "type": "end", "label": "Done", "config": {}},
                ],
            },
            "unsupported fields",
        ),
        (
            {
                **_linear_design(),
                "nodes": [
                    {"id": "trigger", "type": "trigger", "label": "Start", "config": {}},
                    {"id": "trigger", "type": "action", "label": "Act", "config": {}},
                    {"id": "end", "type": "end", "label": "Done", "config": {}},
                ],
            },
            "unique",
        ),
        (
            {
                **_linear_design(),
                "nodes": [
                    {"id": "trigger", "type": "unknown", "label": "Start", "config": {}},
                    {"id": "action", "type": "action", "label": "Act", "config": {}},
                    {"id": "end", "type": "end", "label": "Done", "config": {}},
                ],
            },
            "unsupported",
        ),
        (
            {
                **_linear_design(),
                "nodes": [
                    {"id": "trigger", "type": "trigger", "label": "", "config": {}},
                    {"id": "action", "type": "action", "label": "Act", "config": {}},
                    {"id": "end", "type": "end", "label": "Done", "config": {}},
                ],
            },
            "non-empty",
        ),
        (
            {
                **_linear_design(),
                "nodes": [
                    {"id": "trigger", "type": "trigger", "label": "Start", "tool_id": "x" * 161, "config": {}},
                    {"id": "action", "type": "action", "label": "Act", "config": {}},
                    {"id": "end", "type": "end", "label": "Done", "config": {}},
                ],
            },
            "exceeds 160",
        ),
        (
            {
                **_linear_design(),
                "nodes": [
                    {"id": "trigger", "type": "trigger", "label": "Start", "config": "bad"},
                    {"id": "action", "type": "action", "label": "Act", "config": {}},
                    {"id": "end", "type": "end", "label": "Done", "config": {}},
                ],
            },
            "config must be an object",
        ),
        (
            {
                **_linear_design(),
                "nodes": [
                    {"id": "trigger", "type": "trigger", "label": "Start", "config": {"bad": object()}},
                    {"id": "action", "type": "action", "label": "Act", "config": {}},
                    {"id": "end", "type": "end", "label": "Done", "config": {}},
                ],
            },
            "not serializable",
        ),
        (
            {
                **_linear_design(),
                "nodes": [
                    {"id": "trigger", "type": "trigger", "label": "Start", "config": {}},
                    {"id": "action", "type": "action", "label": "Act", "config": {}},
                    {"id": "end", "type": "end", "label": "Done", "config": {}},
                ],
                "edges": [{"from": "trigger", "to": "action", "extra": "bad"}],
            },
            "only from and to",
        ),
        ({**_linear_design(), "edges": [{"from": "trigger", "to": "missing"}]}, "unknown node"),
        ({**_linear_design(), "edges": [{"from": "trigger", "to": "trigger"}]}, "same node"),
        (
            {
                **_linear_design(),
                "edges": [
                    {"from": "trigger", "to": "action"},
                    {"from": "trigger", "to": "action"},
                ],
            },
            "unique",
        ),
        (
            {
                **_linear_design(),
                "nodes": [
                    {"id": "trigger", "type": "action", "label": "Start", "config": {}},
                    {"id": "end", "type": "end", "label": "Done", "config": {}},
                ],
                "edges": [{"from": "trigger", "to": "end"}],
            },
            "exactly one trigger",
        ),
        (
            {
                **_linear_design(),
                "nodes": [
                    {"id": "trigger", "type": "trigger", "label": "Start", "config": {}},
                    {"id": "action", "type": "action", "label": "Act", "config": {}},
                ],
                "edges": [{"from": "trigger", "to": "action"}],
            },
            "exactly one end",
        ),
        (
            {
                **_linear_design(),
                "nodes": [
                    {"id": "Trigger", "type": "trigger", "label": "Start", "config": {}},
                    {"id": "action", "type": "action", "label": "Act", "config": {}},
                    {"id": "end", "type": "end", "label": "Done", "config": {}},
                ],
            },
            "lowercase identifier",
        ),
        (
            {
                **_linear_design(),
                "nodes": [
                    {"id": "trigger", "type": "trigger", "label": "Start\x01", "config": {}},
                    {"id": "action", "type": "action", "label": "Act", "config": {}},
                    {"id": "end", "type": "end", "label": "Done", "config": {}},
                ],
            },
            "control",
        ),
    ],
)
def test_normalize_design_rejects_additional_invalid_inputs(payload: object, message: str) -> None:
    with pytest.raises(WorkflowDesignError, match=message):
        normalize_workflow_design(payload)


def test_normalize_design_requires_every_reachable_node_to_finish() -> None:
    design = _design(
        nodes=[
            {"id": "trigger", "type": "trigger", "label": "Start", "config": {}},
            {"id": "action", "type": "action", "label": "Act", "config": {}},
            {"id": "dead", "type": "notification", "label": "Dead end", "config": {}},
            {"id": "end", "type": "end", "label": "Done", "config": {}},
        ],
        edges=[
            {"from": "trigger", "to": "action"},
            {"from": "trigger", "to": "dead"},
            {"from": "action", "to": "end"},
        ],
    )

    with pytest.raises(WorkflowDesignError, match="lead to the end"):
        normalize_workflow_design(design)
