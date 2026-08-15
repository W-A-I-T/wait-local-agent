# Contributing

WAIT Local Agent is a C$0 Community edition under the Apache 2.0 license. It
is self-hosted and intended to provide useful local-first AI execution and
change governance, including use across multiple client environments. Keep
changes source-accurate, local-first, and safe by default.

## Development Environment

Recommended setup:

```bash
uv sync --extra dev
source .venv/bin/activate
```

If `uv` is unavailable, create `.venv` manually and install `.[dev]`.

The main developer surfaces are:

- backend package under `src/wait_local_agent`
- tests under `tests`
- UI under `ui`
- release and public-surface checks under `scripts`

## Validation Gate

Run the full release gate before opening or updating a PR:

```bash
./scripts/validate_release.sh
```

That script runs exactly:

1. `ruff check .`
2. `mypy src tests`
3. `bandit -r src`
4. `pip-audit --skip-editable`
5. `python -m pytest --cov=wait_local_agent --cov-report=term-missing --cov-fail-under=95`
6. `python scripts/public_surface_audit.py`
7. `cd ui`
8. `npm ci`
9. `npm run test`
10. `npm run build`

Coverage is a release gate. Backend coverage must stay at or above `95%`.

CI additionally runs `scripts/demo_consultant_mode.sh` and
`scripts/validate_local_first.sh`. CI uses `npm install` for the UI job; the
release script uses `npm ci`.

## Contributor Rules

- Branch from `main`.
- Do not add AI attribution, generated-by banners, or tool-credit lines in code, commits, PR text, screenshots, or docs.
- Keep public docs, examples, and screenshots aligned with shipped behavior only.
- Run `scripts/public_surface_audit.py` or the full validation gate before asking for review.

### AI-assisted contributions

Assistance is allowed, but every contributor must fully understand and be able to explain every change they submit. Changes
must be tested. Do not add AI attribution, generated-by banners, or tool-credit lines. Low-effort generated PRs will be
closed.

Before starting a large feature or a new connector, open a GitHub Discussion
to describe the proposal and invite design feedback.

Issue templates live under `.github/ISSUE_TEMPLATE/`.

## Writing a Connector

The public connector bar is intentionally strict.

### Contract

- Implement a `health()` path that returns a conservative readiness result.
- Keep reads separate from writes.
- Do not expose direct write verbs as first-class public commands.
- Model live writes as drafts plus approval execution.
- Respect `WAIT_ALLOW_HTTP_PROBING` for outbound calls.
- Respect `WAIT_ALLOW_WRITE_ACTIONS` for live mutations.
- Preserve `client_id` on stored approval, workflow, audit, and event records when the connector participates in tenant-scoped flows.

### Write safety

- Drafts must be stored locally first.
- Approval payloads must be reviewable and editable while pending.
- Execution must refuse to run unless the approval is already approved.
- Persist sanitized execution metadata only.

### Tests

- Add offline HTTP tests using the repo's current `httpx.MockTransport` pattern as shown in `tests/test_halopsa.py` and `tests/test_hudu.py`.
- Cover config-missing, probing-blocked, success, remote error, and malformed-response branches.
- Add API and CLI coverage for the approval flow if the connector exposes drafts or execution.
- Do not rely on live services in CI.

## PR Requirements

Before review:

1. Rebase or merge from current `main`.
2. Run `./scripts/validate_release.sh`.
3. Confirm docs reflect the exact shipped surface for any user-facing change.
4. Confirm `scripts/public_surface_audit.py` passes.

Public-surface changes should call out:

- new or changed CLI commands
- new or changed env vars
- new or changed API routes
- any security, RBAC, tenancy, backup, scheduler, update-channel, or pack-loader effects
