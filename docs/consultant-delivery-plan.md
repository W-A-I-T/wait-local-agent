# Consultant delivery plan

The delivery-plan surface composes explicit architecture, evaluation,
governance, connector, and deployment-target artifacts into one reviewable
handoff:

```text
POST /consultant/delivery-plan
```

The CLI equivalent is:

```bash
wait-local-agent microsoft delivery plan delivery.json
```

It reports requirements analyzed, agents/workflows/knowledge sources,
approval boundaries, test scenario count, security evaluation, readiness, and
deployment targets. Production deployment always remains approval-required.

This is an evidence composer, not an executor. It does not invoke `pac`, call
Microsoft services, change authorization, create approvals, execute an agent,
or deploy a package.
