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
