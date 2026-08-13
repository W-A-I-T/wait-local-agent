# Consultant delivery plan

The delivery-plan surface composes explicit architecture, evaluation,
governance, connector, generated review-artifact, and deployment-target
artifacts into one reviewable handoff:

```text
POST /consultant/delivery-plan
```

The CLI equivalent is:

```bash
wait-local-agent microsoft delivery plan delivery.json
```

It reports requirements analyzed, agents/workflows/knowledge sources,
approval boundaries, test scenario count, security evaluation, readiness, and
deployment targets. Connector artifacts and `review_artifacts` are bounded,
redacted, and included in a deterministic review-package manifest with a
SHA-256 digest.
Production deployment always remains approval-required.

This is an evidence composer, not an executor. The review package is not a
deployable Power Platform package. The surface does not invoke `pac`, call
Microsoft services, change authorization, create approvals, execute an agent,
or deploy a package. `deployment_package_generated` remains false until a
separate bounded packaging implementation produces an actual package.
