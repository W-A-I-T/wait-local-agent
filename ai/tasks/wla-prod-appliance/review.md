# Review

## Changed Files

- Production image and Compose: `Dockerfile`, `.dockerignore`,
  `docker-compose.prod.yml`, `docker-compose.yml`.
- Runtime and tests: `src/wait_local_agent/api/app.py`,
  `tests/test_static_ui.py`, `tests/test_compose_config.py`,
  `tests/test_install_script.py`.
- Operations and delivery: `scripts/install.sh`,
  `scripts/test_prod_compose.sh`, `scripts/check_release_version.py`,
  `.github/workflows/release-image.yml`, `.github/workflows/test.yml`.
- Documentation: `README.md`, `docs/README.md`,
  `docs/getting-started/quickstart-docker.md`,
  `docs/getting-started/production-install.md`.

## Risk Areas

- The root static mount is deliberately registered last; registered API, docs,
  OpenAPI, and pack routes remain ahead of it. The fallback reserves `/api`,
  `/docs`, `/openapi.json`, and `/packs`.
- The installer creates fresh credentials only for a new install directory and
  refuses an existing `.env` to avoid silently rotating operator access.
- Compose validation accepts the current plugin major (`v5.3.1` here) and any
  newer major while rejecting legacy pre-v2 output.
- Runtime volume writes depend on the named volume being mounted at `/data`;
  the image creates and owns that directory before switching to user `wait`.
- The release workflow performs a local image smoke test before registry login
  and push. Cosign signing is intentionally best effort per the task contract.

## Version & Compatibility Evidence

- No Python or npm dependency versions changed. The image keeps the existing
  compatible `node:22-slim` UI build stage and `python:3.12-slim` runtime.
- Official Docker action documentation was checked during implementation:
  `docker/login-action@v4`, `docker/build-push-action@v7`,
  `docker/metadata-action@v6`, `docker/setup-buildx-action@v4`, and the
  current `sigstore/cosign-installer@v4` are used.
- Remaining compatibility risk is environmental validation of the Docker
  daemon, image build, and GitHub Actions runner; local `actionlint` and
  `shellcheck` were unavailable.

## Open Questions

- Confirm the first release tag that should publish `stable`; the current
  repository version guard expects `v2.0.0-rc.1`.

## Test Results

- Passed: Ruff, diff check, shell syntax, compileall, six installer/Compose
  tests, Compose config parsing, release-version/tag checks, and the real
  installer dry-run with no filesystem side effect.
- Not run: full pytest/API/static-serving tests because the offline environment
  could not provision the locked `msgraph-sdk` dependency.
- Not run: Docker build and container integration because the Docker daemon
  socket is unavailable.

## Diff Summary

- Customers can pull one GHCR image that serves API plus compiled UI, with
  local-only production publishing, restart policy, persistent named volume,
  unauthenticated minimal liveness, and no Node/npm in the runtime stage.
- Contributors retain the source-mounted Vite Compose workflow.
- The installer is Linux/Docker/Compose-v2 gated, pull-based, secret-generating,
  bounded by health polling, and supports `--version` plus `--dry-run`.

## Requested Review Focus

- Verify FastAPI route ordering and SPA fallback behavior, especially API 404s,
  docs/OpenAPI, and pack routes.
- Verify workflow permission minimality, tag guard, smoke-before-push ordering,
  and absence of secret material in image layers/logs/Compose source.
- Verify non-root volume write behavior and upgrade persistence.

## Claude Final Gate — Review & Live Validation (2026-08-31)

Reviewed by Claude (orchestrator/final gate; per session policy no cross-family reviewer).

Verdict: APPROVED after two scoped Codex fixes.

Diff review findings:
1. tests/test_static_ui.py — Mount path lookup used `route.path == "/"`, but
   Starlette normalizes a "/" mount to path "". StopIteration on line 51.
   Fixed by Codex (scoped follow-up); 3/3 tests now pass locally.
2. scripts/install.sh — health poll used curl unconditionally while the script
   permits wget-only hosts; wget-only installs would false-fail after a healthy
   boot. Fixed by Codex (scoped follow-up).
All other reviewed surfaces clean: SPA mount ordering (registered last, reserved
prefixes 404), /healthz leaks nothing and /health keeps auth, installer refuses
existing .env and writes 0600 with umask 077, workflow smoke-test strictly
precedes registry login/push, minimal workflow permissions, no secrets in image
layers or compose sources.

Environment validation performed by Claude (was unavailable to the Codex sandbox):
- ruff, mypy (app.py), bash -n on both scripts: clean.
- Focused pytest: static-ui 3/3, compose-config, install-script, and
  tests/test_api.py -k health 5/5 — all pass with a fresh uv venv.
- Real docker build: SUCCESS (multi-stage, 1.09GB).
- Live container (wla-prod-test:local): /healthz 200 unauthenticated with
  {"status":"ok"}; /health 401 unauthenticated / 200 with bearer; / and SPA
  fallback routes serve compiled index (id="root"); node/npm ABSENT from
  runtime image; container uid 10001 (non-root).
- Live browser test (Claude Code browser pane at 127.0.0.1:18788): compiled UI
  renders the full dashboard shell with zero console errors; pasting the admin
  token authenticates end-to-end ("Role: admin", setup advances to 1 of 4,
  Safe Mode shows writes disabled); "Powered by WAIT" attribution present.

Open question resolution: the `stable` tag will first publish from tag
v2.0.0-rc.1 per the existing check_release_version guard; acceptable.
