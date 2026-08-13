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

## 2026-08-13 current-main route/control inventory

Environment:

- Current merged main at `3712d7f`.
- Vite dashboard on `127.0.0.1:5196` with a local deterministic API on
  `127.0.0.1:8796`, connector probing and writes disabled.
- Firefox through the Playwright CLI skill at the desktop viewport.

Observed results:

- All 20 operator destinations and the direct-link `/end-user` destination
  rendered route-specific headings.
- The DOM inventory found no empty or unnamed buttons and no unnamed links.
  Disabled controls were exposed as disabled rather than presented as
  successful actions.
- The captured browser console logs contained no application errors or
  warnings during the route inventory.

This is route/control inventory evidence only. It does not prove each control's
success, denied, offline, provider-error, cancellation, or recovery path, so
issue #257 remains open.

## 2026-08-13 consultant discovery/save replay

Environment:

- Current-main API fixture on `127.0.0.1:8797` with demo mode and rate limiting
  disabled; no live provider or deployment call enabled.
- Patched dashboard on `127.0.0.1:5198` with Firefox through the Playwright CLI
  skill at the desktop viewport.

Observed results:

- An incomplete discovery submission remained explicit with the missing-answer
  list and did not enable architecture review.
- After the required answers were supplied, discovery reported readiness for
  architecture review and saving created the tenant-scoped `acme` blueprint.
- The save result stayed visible as `Solution blueprint saved for architecture
  review.`; the prior stale permission alert did not overwrite it when the new
  blueprint became selected.

This proves one bounded Consultant success path plus the incomplete-discovery
state. It does not complete the full control-success, denied, offline,
provider-error, cancellation, recovery, keyboard, or responsive matrix tracked
in issue [#257](https://github.com/W-A-I-T/wait-local-agent/issues/257).

## 2026-08-13 executable route/control matrix

The repository now includes `scripts/validate_ui_browser.sh`, exposed as
`npm run test:browser` from `ui/`. Set `PWCLI` to the Playwright CLI wrapper
provided by the local Playwright skill, then run it against an already-running
Vite and FastAPI stack. It uses a real browser; it does not start the appliance,
enable provider writes, or fabricate provider results.

Run it against a local demo-safe stack with:

```bash
PWCLI=/path/to/playwright_cli.sh \
WAIT_BROWSER_UI_URL=http://127.0.0.1:5199 \
WAIT_BROWSER_BROWSER=firefox \
WAIT_BROWSER_REPORT=output/playwright/ui-browser-matrix.json \
bash scripts/validate_ui_browser.sh
```

The current replay passed all 21 operator/direct-link destinations and checked
route headings, visible control names, desktop overflow, Consultant responsive
layout at `390 × 844`, first-tab keyboard focus, a controlled provider `503`
failure and recovery, and an unavailable-appliance transport state followed by
recovery. A separate token-enforced replay passed the permission state with the
visible permission message and `access unavailable` status. The generated
report is ignored because it is environment-specific evidence.

The provider-error and offline checks are controlled browser fixtures. The
offline fixture combines browser offline mode with an unavailable auth route;
it is not evidence that a particular customer network or external provider is
reachable. Recovery proves only that the dashboard clears its local error state
after a successful refresh; it does not prove provider execution,
cancellation, or live-provider behavior, which remain open under issue #257.
