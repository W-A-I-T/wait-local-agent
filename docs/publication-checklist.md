# Publication Checklist

Run this checklist before publishing a release, public branch, or public pull request.

- Run backend tests.
- Run UI tests.
- Build the UI.
- Run `python scripts/public_surface_audit.py`.
- Review README, docs, workflow files, issue templates, pull request text, and release notes for implementation-tool attribution.
- Confirm no generated-by footer or implementation credit line is present.
- Confirm no secrets or client data are present.

