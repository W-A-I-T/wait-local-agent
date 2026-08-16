# Implementation

Implemented the read-only Schedules screen under Automation.

## Scope

- Added `ui/src/screens/Schedules.tsx` using only `GET /scheduled-jobs`.
- Rendered the live scheduled-job view fields, including workflow and playbook
  target IDs, cron/interval/once cadence, next run, paused status, timestamps,
  client scope, and redacted-by-backend params as read-only detail data.
- Added active/paused and workflow/playbook filters plus expandable job detail.
- Added the `automation/schedules` route and one viewer-visible Schedules sidebar
  entry. No create, pause, resume, reschedule, delete, or other mutation call is
  wired.
- Added supporting types, screen styles, focused UI tests, changelog coverage,
  and classified `GET /scheduled-jobs` as `embedded` in the surface manifest.
- The current live `_scheduled_job_view` has no `last_run` field. The table and
  detail view preserve that requested field honestly as `Not recorded` unless a
  compatible optional value is returned; no backend field was invented.

No files under `src/` were changed. No commit or push was performed.

## Validation

Validation results from the exact requested commands:

```text
$ cd ui && npm test
> wait-local-agent-ui@1.1.1 test
> vitest run


 RUN  v4.1.10 /home/josephp/wla-ui-sched/ui


 Test Files  32 passed (32)
      Tests  127 passed (127)
   Start at  01:14:30
   Duration  6.88s (transform 4.89s, setup 4.03s, import 11.30s, tests 35.36s, environment 35.61s)
```

```text
$ cd ui && npm run build
> wait-local-agent-ui@1.1.1 build
> tsc -b && vite build

vite v6.4.3 building for production...
transforming...
✓ 1864 modules transformed.
rendering chunks...
computing gzip size...
dist/index.html                   0.47 kB │ gzip:   0.30 kB

(!) Some chunks are larger than 500 kB after minification. Consider:
- Using dynamic import() to code-split the application
- Use build.rollupOptions.output.manualChunks to improve chunking
- Adjust chunk size limit with build.chunkSizeWarningLimit.
dist/assets/index-Bvt6bnYE.css   32.63 kB │ gzip:   6.32 kB
dist/assets/index-gaYfq-p5.js   514.75 kB │ gzip: 140.75 kB
✓ built in 4.80s
```

Both commands exited with code 0. The build emitted Vite's non-failing warning
that the JavaScript chunk is larger than 500 kB.

## Files changed

- `CHANGELOG.md`
- `docs/ai-workflow/surface-coverage.json`
- `ui/src/api/types.ts`
- `ui/src/app/Sidebar.tsx`
- `ui/src/routes.tsx`
- `ui/src/screens/Schedules.tsx`
- `ui/src/styles.css`
- `ui/tests/Schedules.test.tsx`
- `ai/tasks/wla-s1-schedules-viewer/implementation.md`
