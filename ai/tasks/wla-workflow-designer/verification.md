# Workflow Designer verification

## Focused checks

- `uv run ruff check ...`
- `uv run mypy ...`
- `uv run pytest -q tests/test_workflow_designer.py ...`
- `pnpm test --run -- WorkflowDesigner.test.tsx`
- `pnpm run build`

## Full checks

The repository-wide Python coverage, security, dependency, public-surface, and
UI checks are run before opening the stacked PR. Any environment limitation is
recorded with the exact command and outcome.
