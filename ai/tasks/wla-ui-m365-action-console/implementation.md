# Implementation

- Added the admin-only Microsoft 365 Actions screen with independent approval-draft forms for disabling a user, resetting a password, and rebooting a managed device.
- Every draft request includes the selected client ID and is disabled until a client is selected.
- The password-reset form uses a plain-text vault secret name reference with a 14-character client-side minimum; it never accepts a raw password.
- Added route and sidebar navigation wiring, focused Vitest coverage, and the changelog entry.

