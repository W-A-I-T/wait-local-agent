# Implementation Notes

## Summary

- Replaced the source-built Docker route with a multi-stage image that builds
  the React dashboard and serves it from FastAPI as a non-root runtime.
- Added authenticated-preserving `/healthz`, conditional static UI serving,
  SPA fallback, pull-based production Compose, installer bootstrap, release
  publishing/smoke testing, and named-volume persistence coverage.
- Kept `docker-compose.yml` as the contributor Vite stack and changed only its
  healthcheck to use `/healthz`.
- Added the optional `--tag` check to the existing release-version guard so the
  image workflow verifies the pushed tag against repository version metadata.
- Made installer health polling use curl or wget, matching compose-file download support.

## Commands Run

- `git diff --check` — passed.
- `bash -n scripts/install.sh scripts/test_prod_compose.sh` — passed.
- `ruff check .` — passed.
- `PYTHONPATH=src python3 -m pytest -q tests/test_install_script.py tests/test_compose_config.py` — 6 passed.
- `python3 -m compileall -q src tests` — passed.
- `docker compose -f docker-compose.yml config --format json` — passed; dev API healthcheck uses `/healthz`.
- `docker compose -f docker-compose.prod.yml config --format json` — passed; one image-backed API service, no build or bind mount, loopback port, restart policy, and named volume verified.
- `python3 scripts/check_release_version.py` and `--tag v2.0.0-rc.1` — passed; mismatched tag was rejected.
- Real `scripts/install.sh --version 2.0.0 --dry-run` — passed against the
  host's Docker Compose v5.3.1 plugin and created no install directory.
- Full API tests and Docker build were not runnable in this workspace: the
  system Python lacks project dependencies, offline `uv` lacks the locked
  `msgraph-sdk` wheel, and the Docker daemon socket is unavailable.

## Files Touched

- `.dockerignore`, `Dockerfile`, `docker-compose.yml`, `docker-compose.prod.yml`
- `.github/workflows/release-image.yml`, `.github/workflows/test.yml`
- `src/wait_local_agent/api/app.py`
- `scripts/check_release_version.py`, `scripts/install.sh`, `scripts/test_prod_compose.sh`
- `tests/test_compose_config.py`, `tests/test_install_script.py`, `tests/test_static_ui.py`
- `README.md`, `docs/README.md`, `docs/getting-started/quickstart-docker.md`,
  `docs/getting-started/production-install.md`
- `ai/tasks/wla-prod-appliance/implementation.md`,
  `ai/tasks/wla-prod-appliance/review.md`, `ai/tasks/wla-prod-appliance/status.json`

## Follow-Up

- Run the full locked backend/UI suite and the Docker smoke/integration tests in
  CI or a host with the required dependency cache and Docker daemon.
- Claude remains the required final cross-family review gate for this task.
- Fixed static UI mount assertions to tolerate Starlette's normalized empty root path.
- Classified `GET /healthz` as `exposed` in the surface manifest.
