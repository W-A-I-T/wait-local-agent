# Implementation

Implemented the read-only Smart Action catalog under Integrations. The screen uses the existing `GET /smart-actions` list endpoint and opens details from the already-loaded manifest; it does not invoke actions or load runs.

## Files touched

- `ui/src/screens/SmartActionCatalog.tsx`
- `ui/src/api/types.ts`
- `ui/src/app/Sidebar.tsx`
- `ui/src/routes.tsx`
- `ui/src/styles.css`
- `ui/tests/SmartActionCatalog.test.tsx`
- `docs/ai-workflow/surface-coverage.json`
- `CHANGELOG.md`
- `ai/tasks/wla-s3-smart-action-catalog/implementation.md`

No files under `src/` were changed. `ui/package-lock.json` was unchanged. `review.md` was not modified.

## Validation

Dependencies were installed with `cd ui && npm ci` because `vitest` was not initially installed in the checkout.

`cd ui && npm test`

```text
> wait-local-agent-ui@1.1.1 test
> vitest run


 RUN  v4.1.10 /home/josephp/wla-ui-actions/ui

 Test Files  29 passed (29)
      Tests  119 passed (119)
   Start at 22:56:06
   Duration 6.57s (transform 5.60s, setup 3.43s, import 11.38s, tests 31.52s, environment 33.53s)
```

`cd ui && npm run build`

```text
> wait-local-agent-ui@1.1.1 build
> tsc -b && vite build

vite v6.4.3 building for production...
transforming...
✓ 1861 modules transformed.
rendering chunks...
computing gzip size...
dist/index.html                   0.47 kB │ gzip:   0.30 kB
dist/assets/index-fCJ5K7px.css   28.26 kB │ gzip:   5.85 kB
dist/assets/index-B84GfUJI.js   496.67 kB │ gzip: 137.33 kB
✓ built in 2.21s
```
