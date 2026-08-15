# Release Process

Use this checklist before a public release tag or launch announcement.

## Safety gates

- [x] `WAIT_ALLOW_WRITE_ACTIONS=false` in `.env.example`, Dockerfile, and Compose defaults.
- [x] `WAIT_ALLOW_HTTP_PROBING=false` in `.env.example`, Dockerfile, and Compose defaults.
- [x] `WAIT_ALLOW_CLOUD_FALLBACK=false` in `.env.example`, Dockerfile, and Compose defaults.
- [x] `WAIT_ALLOW_LLM_INFERENCE=false` in `.env.example`, Dockerfile, and Compose defaults.
- [x] HaloPSA write execution requires an approved approval request.
- [x] Hudu remains read-only.
- [x] `packs/` is gitignored.
- [x] No proprietary pack implementation is committed.
- [x] No real client data or connector credentials are committed.

## Validation commands

```bash
python -m pip install -e ".[dev]"
ruff check .
mypy src tests
bandit -r src
pip-audit --skip-editable
python -m pytest --cov=wait_local_agent --cov-report=term-missing --cov-fail-under=95
python scripts/public_surface_audit.py
```

Dashboard validation:

```bash
cd ui
npm install
npm run test
npm run build
```

Appliance validation:

```bash
docker compose config
docker compose up --build
curl http://127.0.0.1:8788/health
```

Demo validation:

```bash
scripts/demo_appliance.sh
```

License validation when dependencies change:

```bash
pip-licenses --format=markdown
```

Secret scan before release:

```bash
gitleaks detect --source . --log-opts HEAD
```

## Launch assets

- [x] README explains ready-now scope and staged roadmap.
- [x] `docs/getting-started/local-demo.md` is accurate.
- [x] `docs/getting-started/quickstart-docker.md` is accurate.
- [x] `docs/concepts/security-model.md` reflects implemented auth, vault, redaction, and audit export.
- [x] `docs/connectors/README.md` and provider pages describe connector safety without enabling writes by default.
- [x] `docs/concepts/open-core-boundary.md` states public vs proprietary boundaries.
- [x] `CHANGELOG.md` includes the release entry.
- [x] GitHub issue templates are present.
- [x] Synthetic demo data is present under `demo/`.
- [ ] Demo GIF and external landing page copy are prepared outside this code pass.
- [x] Screenshots and architecture content are prepared for this release pass.

## Release decision

Do not tag a public release if any critical validation command fails, secrets are detected, or the open-core boundary is crossed.

## Publication checks

Before publishing a release, public branch, or public pull request, run the
release script or its backend and UI checks separately, then confirm that
`.env.example`, the README, status, roadmap, and architecture documentation
match the shipped interface. Keep optional OCR and Qdrant behavior clearly
optional and disabled by default, keep Hudu read-only, and verify that
approval payload preview/edit/approve/reject behavior matches the runtime.

Review docs, workflows, issue templates, release notes, and public text for
secrets, client data, unsupported capability claims, and implementation
attribution. Changes to dependencies also require a license inventory.
