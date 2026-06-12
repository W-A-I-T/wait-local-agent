# Launch Checklist

Use this checklist before a public release tag or launch announcement.

## Safety gates

- [ ] `WAIT_ALLOW_WRITE_ACTIONS=false` in `.env.example`, Dockerfile, and Compose defaults.
- [ ] `WAIT_ALLOW_HTTP_PROBING=false` in `.env.example`, Dockerfile, and Compose defaults.
- [ ] `WAIT_ALLOW_CLOUD_FALLBACK=false` in `.env.example`, Dockerfile, and Compose defaults.
- [ ] `WAIT_ALLOW_LLM_INFERENCE=false` in `.env.example`, Dockerfile, and Compose defaults.
- [ ] HaloPSA write execution requires an approved approval request.
- [ ] Hudu remains read-only.
- [ ] `packs/` is gitignored.
- [ ] No proprietary pack implementation is committed.
- [ ] No real client data or connector credentials are committed.

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

- [ ] README explains ready-now scope and staged roadmap.
- [ ] `docs/local-demo.md` is accurate.
- [ ] `docs/appliance-install.md` is accurate.
- [ ] `docs/security-model.md` reflects implemented auth, vault, redaction, and audit export.
- [ ] `docs/connector-setup.md` describes HaloPSA/Hudu setup without enabling writes by default.
- [ ] `docs/open-core-boundary.md` states public vs proprietary boundaries.
- [ ] `CHANGELOG.md` includes the release entry.
- [ ] GitHub issue templates are present.
- [ ] Synthetic demo data is present under `demo/`.
- [ ] Screenshots, demo GIF, architecture image, and landing page copy are prepared outside this code pass.

## Release decision

Do not tag a public release if any critical validation command fails, secrets are detected, or the open-core boundary is crossed.
