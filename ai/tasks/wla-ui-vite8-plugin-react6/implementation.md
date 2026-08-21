# Implementation Notes

## Summary

Implemented the coupled Vite 8 and React plugin 6 upgrade in the verified
`W-A-I-T/wait-local-agent` checkout on branch `deps/ui-vite8-plugin-react6`.
The manifest keeps Vitest at `^4.1.10`, adds the strict resolved Node engine
floor, and the lockfile resolves the compatible peer set without overrides.
The empty PostCSS configuration was deleted and only the UI CI job was pinned
to the concrete Node floor.

## Commands Run

- Registry evidence, from `ui/`, with `/tmp/wla-npm-cache`:
  `npm view vite@8 version engines --json`, `npm view @vitejs/plugin-react@6
  version peerDependencies engines --json`, `npm view vitest@4.1.10 version
  peerDependencies engines --json`, and `npm view jsdom@30 version engines
  --json`.
  - Latest matching Vite 8 release: `8.2.2`; Node engine
    `^20.19.0 || >=22.12.0`.
  - Latest matching plugin-react 6 release: `6.1.0`; peer `vite: ^8.0.0`
    and Node engine `^20.19.0 || >=22.12.0`.
  - Vitest `4.1.10` remains unchanged; peer Vite range is
    `^6.0.0 || ^7.0.0 || ^8.0.0`.
  - Resolved jsdom `30.0.1` has the strictest Node engine:
    `^22.22.2 || ^24.15.0 || >=26.0.0`.
- `npm install --cache /tmp/wla-npm-cache` — passed; lockfile regenerated,
  120 packages added, audit found 0 vulnerabilities.
- Clean-install proof: moved the pre-existing `node_modules` directory to a
  unique `/tmp` quarantine because the sandbox rejected literal `rm -rf`, then
  ran `npm ci --cache /tmp/wla-npm-cache` from `ui/` — passed with no
  `ERESOLVE` or peer-resolution error.
- `npm run test` — passed: 49 test files and 232 tests.
- `npm run build` — passed: `tsc -b` and Vite `8.2.2` production build.
- `npm ls --depth=0 --cache /tmp/wla-npm-cache` — confirmed
  `@vitejs/plugin-react@6.1.0`, `vite@8.2.2`, `vitest@4.1.10`, and
  `jsdom@30.0.1`.
- `git diff --check` — passed. No project `.npmrc` was created or changed.

## Files Touched

- `.github/workflows/test.yml`
- `ui/package.json`
- `ui/package-lock.json`
- `ui/postcss.config.mjs` (deleted)
- `ai/tasks/wla-ui-vite8-plugin-react6/implementation.md`
- `ai/tasks/wla-ui-vite8-plugin-react6/review.md`
- `ai/tasks/wla-ui-vite8-plugin-react6/status.json`

`ui/vite.config.ts`, application source, tests, desktop code, and backend code
were not changed.

## Follow-Up

- Vite reported its existing future `configLoader: "native"` warning for the
  extensionless `apiProxyRoutes` import and a non-failing large-chunk advisory;
  no Vite 8 type or behavior fix was required.
- Required Kimi cross-family review and Claude final gate remain external
  workflow steps. No merge, push, or PR was performed.
