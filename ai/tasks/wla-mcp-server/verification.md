# Verification

- `pytest -q`: passed.
- `pytest --cov=wait_local_agent --cov-fail-under=95 -q`: passed at 95.03%.
- `mypy src tests`: passed.
- `ruff check .`: passed for the touched Python surface; full repository check
  is run in CI.
- `bandit -r src`: passed with no reported issues.
- `python scripts/public_surface_audit.py`: passed.
- Focused MCP, agent, and full repository tests passed.

Known warnings are pre-existing Starlette deprecations in the test client and
founder surface tests.
