# Publication Checklist

Run this checklist before publishing a release, public branch, or public pull request.

- Run `scripts/validate_release.sh`.
- If validating manually, run backend lint/type/security/test checks.
- If validating manually, run UI tests and build the UI.
- If validating manually, run `python scripts/public_surface_audit.py`.
- Confirm `.env.example`, README, status, roadmap, and architecture docs match the current public interface.
- Confirm Docling OCR is documented as optional, dependency-gated, and disabled
  by default.
- Confirm Qdrant is documented as optional and SQLite remains the default
  retrieval backend.
- Confirm Hudu is described as read-only and no Hudu write surface is published.
- Confirm approval requests describe payload preview/edit/approve/reject gates
  before connector execution.
- Review README, docs, workflow files, issue templates, pull request text, and release notes for implementation-tool attribution.
- Confirm no generated-by footer or implementation credit line is present.
- Confirm no secrets or client data are present.

## Pre-Promotion Checklist (before actively promoting the public repo)

Complete all items below before announcing the repo publicly:

### Security

- [ ] Run `gitleaks detect --source . --log-opts HEAD` — confirm zero secrets in git history
- [ ] Run `pip-audit` — confirm no critical CVEs in dependencies
- [ ] Run `pip-licenses` — confirm all deps are Apache 2.0 or MIT
- [ ] API authentication implemented (Phase 1: `security.py` Bearer token middleware)
- [ ] Encrypted secrets vault implemented (Phase 1: `vault.py` Fernet backend)
- [ ] Redaction expanded to cover `apikey`, `auth_token`, `bearer`, `authorization` variants
- [ ] `SECURITY.md` updated with auth setup and vault setup instructions

### Disclaimer

- [ ] README contains prominent disclaimer: "Live PSA writes require explicit operator opt-in (`WAIT_ALLOW_WRITE_ACTIONS=true`) and human approval — they are never enabled by default"
- [ ] No claim is made that the product is safe for production without the Phase 1 security fixes

### Docs

- [ ] README reflects current positioning (local-first, MSP + founder modes, product tiers)
- [ ] Architecture diagram present in README (Mermaid or SVG)
- [ ] `docs/build-plan.md` covers Phase 0–8 with task detail
- [ ] `docs/competitive-analysis.md` includes all major competitors
- [ ] `docs/commercial-model.md` covers pricing and open-core strategy
- [ ] `docs/ecosystem-integration.md` covers LP/IDP/AER integration contracts
- [ ] `docs/security-model.md` covers threat model and safe-by-default policy
- [ ] `docs/status.md` updated with commercial readiness section

### Install Path

- [ ] `git clone → docker compose up → demo` tested on clean Ubuntu 22.04
- [ ] `git clone → docker compose up → demo` tested on macOS (Apple Silicon)
- [ ] `scripts/install.sh` one-liner tested (Phase 3)
- [ ] Demo data present in `demo/` (sample runbooks and tickets that are not real client data)

### Release

- [ ] `CHANGELOG.md` with first release entries
- [ ] Release tag `v1.0.0` (or `v1.0.0-beta` for soft launch) on main
- [ ] CI badge and license badge on README
- [ ] GitHub issue templates: bug report, connector request, workflow template request, security vulnerability
