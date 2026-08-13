# Dashboard Browser Validation

This record captures the focused real-browser check for the responsive dashboard
navigation and connector readiness surface.

## 2026-08-13 local demo check

Environment:

- Vite dashboard served from the clean PR worktree on `127.0.0.1:5177`.
- FastAPI demo API served locally with no bearer token, connector probing, or
  write actions enabled.
- Chromium viewport: `390 × 844`.

Observed results:

- `/connectors` loaded and rendered the Connector Readiness panel.
- The navigation changed from a vertically stacked sidebar to a horizontally
  scrollable row with 44px minimum navigation targets.
- The page and document scroll widths both measured `390px`; no horizontal
  overflow remained.
- The page heading wrapped within the content column and the token, refresh,
  role, and blocked-write controls remained reachable.
- The API returned explicit `not_configured`/`blocked` connector states; no
  provider success was inferred.
- The browser console contained no application errors after adding the shipped
  favicon. React DevTools' informational message is not an application error.

Desktop smoke at `1440 × 1000` retained the two-column shell and keyboard focus
advanced to the Overview navigation link after one Tab keypress.

This is a focused responsive/control slice, not completion of the full route,
permission, offline, provider-error, or accessibility matrix tracked in issue
[#257](https://github.com/W-A-I-T/wait-local-agent/issues/257).

## 2026-08-13 route and access-state replay

Environment:

- Vite dashboard from the browser-validation worktree on
  `127.0.0.1:5181`.
- FastAPI fixture on `127.0.0.1:8789`, first in deterministic demo mode with
  `WAIT_RATE_LIMIT_ENABLED=false`, then in token-enforced mode.
- Firefox via the Playwright CLI skill; desktop viewport `1280 × 720`, with a
  consultant replay at `390 × 844`.

Observed results:

- All 21 operator and direct-link end-user routes rendered their expected
  headings with no application console errors or warnings.
- The route replay produced no UI error alerts after the request limiter was
  disabled for deterministic navigation.
- The consultant route measured `documentWidth=390` at the mobile viewport;
  no horizontal overflow was present. All visible controls had accessible
  names; the only unlabeled form control was the intentionally hidden,
  `aria-hidden` username autofill field.
- Stopping the API produced a visible, generic appliance failure message;
  no provider success or completed operation was shown.
- An invalid token against token-enforced mode produced the explicit
  permission message. The replay exposed and the accompanying fix prevents
  the unauthorized dashboard from presenting the onboarding wizard or the
  `demo-ready` configuration label.

This replay expands the evidence for issue #257 but does not complete the
full control-success, permission-denied, offline, provider-error, keyboard,
and responsive matrix for every interactive surface.
