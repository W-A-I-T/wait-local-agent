# Publication Checklist

Run this checklist before publishing a release, public branch, or public pull request.

- Run `scripts/validate_release.sh`.
- If validating manually, run backend lint/type/security/test checks.
- If validating manually, run UI tests and build the UI.
- If validating manually, run `python scripts/public_surface_audit.py`.
- Confirm `.env.example`, README, status, roadmap, and architecture docs match the current public interface.
- Confirm Docling OCR is documented as optional, dependency-gated, and disabled by default.
- Confirm Qdrant is documented as optional and SQLite remains the default retrieval backend.
- Confirm Hudu is described as read-only and no Hudu write surface is published.
- Confirm approval requests describe payload preview/edit/approve/reject gates before connector execution.
- Confirm API auth and local vault docs match implemented behavior.
- Review README, docs, workflow files, issue templates, pull request text, and release notes for implementation attribution.
- Confirm no generated footer or implementation credit line is present.
- Confirm no secrets or client data are present.

## Pre-promotion checklist

Complete all items below before announcing the repo publicly.

### Security

- [ ] Run `gitleaks detect --source . --log-opts HEAD` and confirm zero secrets in git history. If `gitleaks` is unavailable in the release environment, record that it was unavailable and escalate to the orchestrator instead of downloading tools during the pass.
- [x] Run `pip-audit --skip-editable` and confirm no critical CVEs in dependencies.
- [x] Run `pip-licenses` and confirm dependency licenses are compatible with the Apache 2.0 open-core repo.
- [x] API authentication implemented outside demo mode.
- [x] Optional encrypted local secrets vault implemented.
- [x] Redaction expanded to cover common API key, token, bearer, authorization, and secret key variants.
- [x] `SECURITY.md` updated with auth setup and vault setup instructions.

### Disclaimer

- [x] README contains prominent disclaimer that live PSA writes require explicit operator opt-in and human approval.
- [x] No claim is made that MSP production hardening is complete before the remaining post-1.0 commercial hardening work is finished.

### Docs

- [x] README reflects current positioning and open-core boundary.
- [x] `docs/roadmap.md` covers phases through public launch.
- [x] `docs/commercial-model.md` covers pricing and open-core strategy.
- [x] `docs/security-model.md` covers threat model and safe-by-default policy.
- [x] `docs/status.md` updated with commercial readiness section.
- [x] `docs/local-demo.md` added.
- [x] `docs/appliance-install.md` added.
- [x] `docs/connector-setup.md` added.
- [x] `docs/open-core-boundary.md` added.
- [x] `docs/launch-checklist.md` added.

### Install path

- [ ] `git clone -> docker compose up -> demo` tested on clean Ubuntu 22.04.
- [ ] `git clone -> docker compose up -> demo` tested on macOS Apple Silicon.
- [x] `scripts/install.sh` one-command helper added.
- [x] Synthetic demo data present in `demo/`.

### Release

- [x] `CHANGELOG.md` with first release entries.
- [ ] Release tag `v1.0.0` created locally by the orchestrator on the final release commit.
- [x] CI badge and license badge checked in README.
- [x] GitHub issue templates present: bug report, connector request, workflow template request, security report.
