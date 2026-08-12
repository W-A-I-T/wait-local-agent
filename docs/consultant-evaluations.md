# Consultant evaluation contracts

WAIT exposes an observation-based evaluation contract for consultant-mode
agents. A JSON test set declares expected and forbidden tool IDs, required
approval tool IDs, and an observation records the tools and safety checks that
actually occurred. The evaluator reports functional, tool-selection,
approval-safety, tenant-isolation, and prompt-injection-safety percentages. A
case may also require evidence for source citations (grounding), a bounded
latency, failure handling, and regression results. Optional dimensions are
scored only for cases that explicitly request that evidence.

Evaluation is a dry-run analysis surface. It does not execute an agent, invoke
a connector, call an LLM, or treat missing observations as passing evidence.
Every case must supply explicit boolean evidence for tenant isolation and
prompt-injection blocking. Cases that set `required_citations`,
`max_latency_ms`, `failure_expected`, or `regression_expected` must also supply
the corresponding observation fields. Latency values are bounded to 120 seconds
and citations are treated as opaque evidence identifiers.

The API is:

```text
POST /consultant/evaluations
```

The CLI accepts a JSON file containing `test_set` and `observations`:

```bash
wait-local-agent microsoft evaluation run evaluation.json
```

A result is `pass` only when every bounded dimension reaches 100%; otherwise it
is `needs_review`. The result always reports `execution_started: false`.
