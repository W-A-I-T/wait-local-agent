# Review

## Changed areas

- Migration 11 and knowledge document authority persistence.
- Scoped administrator API and CLI classification actions.
- Retrieval authority propagation and untrusted evidence envelope.
- Knowledge UI authority metadata and administrator-only controls.
- Regression tests, derived migration assertions, and surface manifest entries.

## Security review

- Existing documents are explicitly reset to `UNTRUSTED` during migration.
- Ingestion has no authority parameter and cannot promote content.
- Approved classes require `AdminAccess` or authenticated CLI administrator access.
- Approval actor and timestamp are generated server-side; request bodies cannot supply approval fields.
- Document and superseded-document access is tenant-scoped; cross-tenant IDs are not disclosed.
- Retrieved text is evidence-only context with an authority label and untrusted third-party delimiters. No execution path or tool permission changed.

## Validation results

- Ruff: passed.
- Mypy: passed in the project virtualenv across source and tests.
- Bandit: passed with no issues.
- Store migration/backfill and envelope smoke checks: passed.
- Pytest and UI suite: not run, per the task instruction to leave those suites to the operator because FastAPI `TestClient` hangs in this environment.

## Remaining risks

- Full Python coverage and UI validation remain operator gates.
- The host environment lacks `gitleaks`, and the project virtualenv lacks `itsdangerous`/`authlib` needed to instantiate the full API/CLI for runtime surface enumeration; the manifest entries were added from the repository's established enumeration naming pattern.
