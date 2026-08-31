# Implementation Notes

## Summary

Implemented the UI-only Connector Explorer contract on
`ai/wla-beta-p47-connector-explorer`.

- Added a verified-route resource catalog for ServiceNow, IT Glue, Confluence,
  Notion, SharePoint, Syncro, HaloPSA, Hudu, ConnectWise, Autotask, ScalePad,
  and Microsoft 365.
- Added connector/resource pickers, explicit path/query parameters, page and
  cursor pagination, safe URI encoding, generic read-only tables, and raw JSON
  detail drawers.
- Added posture-aware guidance using `connectorSetup.ts` environment variables;
  blocked or not-configured connectors do not request or render empty tables.
- Added the dedicated ScalePad QBR tab for risk summaries, compliance health,
  goals, and assessments, with links to and from Reports.

The implementation contains no write controls and does not add backend routes.

## Commands Run

- `pwd`, `git remote -v`, and `git status --short --branch` — confirmed
  `W-A-I-T/wait-local-agent` on `ai/wla-beta-p47-connector-explorer`.
- `npm ci --ignore-scripts` in `ui` — installed the existing lockfile; audit
  reported 0 vulnerabilities.
- Catalog route comparison against `src/wait_local_agent/api/app.py:3416-4296`
  — 55 catalog paths matched backend GET routes exactly; 14 health/write-health
  paths remain posture checks rather than resources.
- `npx vitest run src/components/ConnectorExplorer.test.tsx src/lib/connectorResources.test.ts`
  — passed, 2 files / 5 tests.
- `npm test -- --run` — passed twice, 66 files / 343 tests each.
- `npm run build` — passed; TypeScript and Vite production build completed.
- `git diff --check` — passed.

## Files Touched

- `ui/src/components/ConnectorExplorer.tsx`
- `ui/src/components/ConnectorExplorer.test.tsx`
- `ui/src/lib/connectorResources.ts`
- `ui/src/lib/connectorResources.test.ts`
- `ui/src/screens/Connectors.tsx`
- `ui/src/screens/Reports.tsx`
- `ui/src/styles.css`
- `ai/tasks/wla-beta-p47/implementation.md`, `review.md`, and `status.json`

## Catalog Evidence

The catalog records 55 verified resource/detail paths:

- ServiceNow: incidents, incident detail, companies, company detail.
- IT Glue: organizations, organization documents, document detail,
  organization folders.
- Confluence: pages and page detail.
- Notion: pages, page detail, data-source pages, data-source detail.
- SharePoint: sites, site detail, documents, document detail, document content.
- Syncro: tickets, ticket detail, ticket comments, customers, customer detail.
- HaloPSA: ticket detail, ticket notes, client assets, categories.
- Hudu: articles, article detail, folders, companies.
- ConnectWise: tickets, ticket detail, companies.
- Autotask: tickets, ticket detail, companies, company detail.
- ScalePad: clients, risk summaries, compliance health, goals, assessments.
- Microsoft 365: users, groups, licenses, user license details, mail folders,
  mail messages, managed devices, teams, channels, and channel messages.

Intentionally skipped: connector health and write-health routes are posture
checks, not table resources; the pre-range HaloPSA collection route
`/connectors/halopsa/tickets` is already surfaced elsewhere and is outside the
plan's stated route range; and there is no verified Notion data-source
collection/list route, so the catalog requires an explicitly mapped data-source
ID instead of inventing one. No ambiguous resource route inside the contract
range was guessed.

## Follow-Up

- The existing Vite warning about native config loading and the existing
  post-minification chunk-size warning remain; neither is caused by a new
  dependency or API change.
- A future UI pass can unify this generic table with the pending P4.6 evidence
  table component; this task intentionally keeps the explorer self-contained.
