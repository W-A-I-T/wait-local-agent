# Contributing

WAIT Local Agent `main` is the **2.0 development line** and is distributed as a combined work under **GNU Affero General Public License v3 only (`AGPL-3.0-only`)**. The preserved `1.x` baseline through commit `903cb595e8f735fcc306a68f2bee150fce58a416` remains available under Apache License 2.0. See [`LICENSE_HISTORY.md`](LICENSE_HISTORY.md).

Keep changes source-accurate, local-first, and safe by default.

WAIT also intends to offer separate commercial licenses. A pull request submitted under the repository's Community license does **not** by itself grant WAIT whatever additional rights may be necessary to relicense that contribution commercially. Until a counsel-approved CLA, copyright assignment, or equivalent contributor-rights process is published, maintainers may defer or decline material outside contributions that WAIT would need to include in both Community and Commercial distributions.

Review [`docs/legal/README.md`](docs/legal/README.md), [`docs/legal/PROVENANCE_REVIEW.md`](docs/legal/PROVENANCE_REVIEW.md), and the transition checklist before proposing licensing, attribution, contributor-rights, commercial-pack, or WAIT-Sync migration changes.

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
2. `python scripts/check_release_version.py`
3. `mypy src tests`
4. `bandit -r src`
5. `pip-audit --skip-editable`
6. `python -m pytest --cov=wait_local_agent --cov=packs --cov-report=term-missing --cov-fail-under=95`
7. `python scripts/public_surface_audit.py`
8. `cd ui`
9. `npm ci`
10. `npm run lint`
11. `npm run test:coverage`
12. `npm run build`

Coverage is a release gate. Backend coverage must stay at or above `95%`.

CI additionally runs `scripts/demo_consultant_mode.sh` and
`scripts/validate_local_first.sh`. CI uses `npm ci` for the UI job; the release
script uses `npm ci`.

## Contributor Rules

- Branch from `main` unless you are intentionally maintaining the preserved Apache `1.x` line.
- Contributions to `main` are accepted under `AGPL-3.0-only` unless an explicit, written repository policy says otherwise.
- Do not add AI attribution, generated-by banners, or tool-credit lines in code, commits, PR text, screenshots, or docs.
- Keep public docs, examples, and screenshots aligned with shipped behavior only.
- Run `scripts/public_surface_audit.py` or the full validation gate before asking for review.
- Identify copied, adapted, generated, or externally sourced material and confirm that WAIT may distribute it under the repository's effective license.

## Contributor rights and commercial dual licensing

WAIT's separate Commercial licensing program requires WAIT to control sufficient rights to offer the applicable code under separate commercial terms. Community contribution under AGPL alone does not automatically provide those additional relicensing rights.

Until a counsel-approved contributor-rights process is published:

- maintainers may defer or decline outside contributions that need to ship in proprietary/commercial distributions;
- contributors must not assume ordinary PR submission grants WAIT rights beyond the effective Community license;
- maintainers must not assert WAIT can commercially relicense an outside contribution without a documented legal basis; and
- code with uncertain authorship, copied expression, incompatible licensing, or unclear contractor/employment ownership must not be merged.

The required review is tracked in
[`docs/legal/PROVENANCE_REVIEW.md`](docs/legal/PROVENANCE_REVIEW.md).

### AI-assisted contributions

Assistance is allowed, but every contributor must fully understand and be able to explain every change they submit. Changes
must be tested. Do not add AI attribution, generated-by banners, or tool-credit lines. Low-effort generated PRs will be
closed.

AI-assisted code is not exempt from provenance review. The contributor remains
responsible for checking that the submission does not reproduce protected
third-party code, text, assets, credentials, or confidential material.

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
5. Confirm licensing and provenance documentation is updated when a change affects dependencies, bundled assets, public/private boundaries, attribution, packaging, or commercial entitlements.

Public-surface changes should call out:

- new or changed CLI commands
- new or changed env vars
- new or changed API routes
- any security, RBAC, tenancy, backup, scheduler, update-channel, or pack-loader effects
- any dependency, attribution, license-metadata, branding, or distribution effects
