# Launch Checklist

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
- [x] `docs/local-demo.md` is accurate.
- [x] `docs/appliance-install.md` is accurate.
- [x] `docs/security-model.md` reflects implemented auth, vault, redaction, and audit export.
- [x] `docs/connector-setup.md` describes HaloPSA/Hudu setup without enabling writes by default.
- [x] `docs/open-core-boundary.md` states public vs proprietary boundaries.
- [x] `CHANGELOG.md` includes the release entry.
- [x] GitHub issue templates are present.
- [x] Synthetic demo data is present under `demo/`.
- [ ] Demo GIF and external landing page copy are prepared outside this code pass.
- [x] Screenshots and architecture content are prepared for this release pass.

## Release decision

Do not tag a public release if any critical validation command fails, secrets are detected, or the open-core boundary is crossed.
