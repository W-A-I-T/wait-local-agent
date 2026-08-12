# Consultant evaluation contracts

WAIT exposes an observation-based evaluation contract for consultant-mode
agents. A JSON test set declares expected and forbidden tool IDs, required
approval tool IDs, and an observation records the tools and safety checks that
actually occurred. The evaluator reports functional, tool-selection,
approval-safety, tenant-isolation, and prompt-injection-safety percentages.

Evaluation is a dry-run analysis surface. It does not execute an agent, invoke
a connector, call an LLM, or treat missing observations as passing evidence.
Every case must supply explicit boolean evidence for tenant isolation and
prompt-injection blocking.

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
