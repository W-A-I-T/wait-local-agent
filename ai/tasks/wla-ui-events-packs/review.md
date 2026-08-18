# Review — wla-ui-events-packs

Implementation review pending final Claude gate.

The change is UI-only and reuses the existing dashboard retry mutation and
Settings pack install endpoint. Focused Vitest coverage checks retry eligibility,
retry invocation, pack install request payload, refresh behavior, and inline
install errors.
