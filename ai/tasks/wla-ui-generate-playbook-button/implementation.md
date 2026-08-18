# Implementation

- Added a selected-blueprint-only `Generate Playbook` action to the Solutions Architect screen.
- The action posts to the encoded blueprint endpoint through `apiFetch`, preserves the existing write-access gating, and disables itself while the request is pending.
- Successful generation reports that the draft is disabled and links to Playbooks for review and enablement. No enable or deploy control was added.
- Added Consultant Vitest coverage for the POST request, success link/message, busy state, API error, and absence of enable/deploy controls.
- Updated the Unreleased changelog.

Validation is recorded in `review.md` after the requested UI test and build commands run.
