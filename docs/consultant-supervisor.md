# Supervisor and child-agent delegation

WAIT can build a tenant-scoped delegation plan from existing persisted agent
definitions:

```text
POST /consultant/supervisor/plan
```

The CLI equivalent is:

```bash
wait-local-agent microsoft supervisor plan supervisor.json
```

The caller must name the child agents explicitly. WAIT revalidates that each
definition belongs to the requested tenant, preserves only dependencies among
the selected children, and assigns a bounded task/result contract. Child
agents receive only the tenant identifier, bounded supervisor task, and
structured results from completed dependencies.

This artifact does not start delegation, create approvals, execute a child,
or pass arbitrary context. Actual child execution continues to use the
existing AgentService, smart-action catalog, approval runtime, and audit
history rather than a second orchestration engine.
