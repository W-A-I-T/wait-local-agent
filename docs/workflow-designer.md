# Workflow Designer

The Workflow Designer is a bounded, design-only editor over the existing local
workflow-template gallery. It creates and versions a graph artifact; it does
not execute a workflow, invoke a provider, or enable a connector.

Each design uses the `wait-local-agent.workflow-design` format, version `1`,
with typed nodes and directed edges. The server enforces one trigger and one
end node, unique lowercase identifiers, acyclic connectivity, a 32-node and
64-edge limit, bounded labels/tool identifiers, and an 8 KiB serialized config
limit per node. Labels, tool identifiers, and configuration values are
redacted before persistence and export.

Designs are persisted in the existing tenant-scoped gallery entry and revision
tables. The authenticated technician PATCH route creates a new revision; the
viewer route can inspect the design. Restoring a gallery revision restores the
graph as well as the operator-facing gallery fields.

The canvas intentionally stops at graph authoring. Runtime binding, connector
selection, Power Platform export, provider credentials, and autonomous
execution remain separate capabilities and must be implemented with their own
approval, tenancy, and failure-path tests.
