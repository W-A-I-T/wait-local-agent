# Proposal: Environment-Variable Configuration in the UI (Phase 5b)

Status: PROPOSAL — each tier needs an explicit go/no-go from the product owner.
Author: planning workstream. Implementation, if approved, follows the standard
internal packet workflow.

## Why

The product currently reads all configuration from `WAIT_*` environment
variables into a single `@dataclass(frozen=True)` `Settings` object
(`src/wait_local_agent/config.py:66`), constructed once at process startup
(`load_settings()`, called once inside `create_app()`, `api/app.py:963`).
There are **159 distinct `WAIT_*` variables**. None can be changed without
editing the environment and restarting the process — including things as
mundane as an SMTP password and as consequential as whether live writes are
enabled at all. The request is to make "everything from the env var" editable
in the UI. This is a real, large, and non-uniform ask — the 159 variables are
not one kind of thing, and treating them as one kind of thing would be a
mistake. This proposal splits them into three tiers with different
implementation paths and different levels of product risk.

## The three tiers

### Tier 1 — Credentials and connector config (84 variables): mostly already has a path, extend it

Covers every `WAIT_<PROVIDER>_*` variable for the 14 supported connectors
(HaloPSA, ConnectWise, Hudu, IT Glue, Confluence, Notion, SharePoint, Syncro,
ServiceNow, Autotask, M365, TimeZest, ScalePad, and the RMM family —
NinjaOne/DattoRMM/N-sight/N-central/Kaseya/ScreenConnect).

- **Current state**: an earlier phase (P2.4) already added per-provider
  guidance to the Connectors screen — the exact `WAIT_*` names, copyable
  templates, and an explanation of the vault-vs-env-var distinction. It does
  **not** let you set the values from the UI; you still edit `.env` and
  restart.
- **What's needed to go further**: these variables are already designed to be
  optionally vault-backed (`WAIT_SECRETS_BACKEND=fernet`, vault key = the
  exact env-var name — `config.py`'s `_secret_value` helper). The vault
  already supports runtime writes (`PUT /secrets/{name}`, admin-gated,
  403 in demo mode). **The UI-editable path for this tier already exists at
  the backend layer for the credential-shaped variables** (tokens, API keys,
  base URLs stored as vault values) — it just needs the Settings/Connectors
  UI to write into it directly per-provider instead of only reading the
  vault's presence/absence, which is closer to a UI packet than new backend
  work.
- **Caveat**: this only works when `WAIT_SECRETS_BACKEND=fernet`. Under the
  default `env` backend, the vault is not consulted for these settings at
  all, and no UI action can override an env var that was never re-read after
  startup — so this tier's UI-editability is conditional on the vault backend
  being enabled, and that condition itself should be surfaced clearly.
- **Effort**: small-medium per provider (mostly UI forms on an existing
  backend path); the "vault only works when `WAIT_SECRETS_BACKEND=fernet`"
  caveat needs to be prominent, not buried.
- **Recommendation: proceed**, scoped as its own packet extending the
  Connectors screen guidance already shipped.

### Tier 2 — Safety gates (10 variables): a deliberate product decision, not a technical one

`WAIT_ALLOW_WRITE_ACTIONS`, `WAIT_ALLOW_HTTP_PROBING`,
`WAIT_ALLOW_POWER_PLATFORM_DEPLOYMENT`, `WAIT_ALLOW_LLM_INFERENCE`,
`WAIT_ALLOW_CLOUD_FALLBACK`, `WAIT_ALLOW_INSECURE_PROVIDER_TRANSPORT`,
`WAIT_ALLOW_OCR`, `WAIT_DEMO_MODE`, `WAIT_OFFLINE_MODE`,
`WAIT_UPDATE_ALLOW_PRERELEASE`.

- **Current state**: restart-required by design. This friction is not an
  oversight — it is the mechanism that prevents a stray UI click from
  silently enabling live writes or Power Platform deployment. Anyone who can
  flip these must have server/environment access, which is itself an access
  control.
- **What UI-editability would remove**: the requirement that changing a
  safety posture leaves a trace outside the running application (someone
  edited a file or a process manager config) and required a restart (a
  natural pause point). A UI toggle collapses that into one click by whoever
  is currently authenticated to the running app — a materially different
  risk profile, especially for `WAIT_ALLOW_WRITE_ACTIONS` and
  `WAIT_ALLOW_POWER_PLATFORM_DEPLOYMENT`.
- **If approved anyway**: would need (a) the Tier 3 mutable-settings
  capability below, (b) mandatory audit logging of who changed which flag and
  when (arguably more important here than anywhere else in the app), (c)
  probably a re-confirmation/typed-acknowledgment step given the blast
  radius, (d) explicit product sign-off that the restart-as-friction property
  is being intentionally removed, not accidentally.
- **Recommendation: do not make these UI-editable.** Instead (already
  planned as its own packet, P5.8): make the Settings screen clearly explain
  what each active gate restricts and the exact restart procedure to change
  it, so the *lack* of a toggle reads as intentional rather than missing.

### Tier 3 — Everything else (65 variables): needs a new backend capability first

Auth bootstrap tokens (`WAIT_ADMIN_TOKEN`, `WAIT_API_TOKEN`,
`WAIT_TECH_TOKEN`, `WAIT_VIEWER_TOKEN`), communication channel config (email
SMTP, Slack/Teams/SMS webhooks), model/embedding provider settings
(`WAIT_EMBEDDING_PROVIDER`, `WAIT_REMOTE_MODEL_API_KEY`, per-token cost
fields), end-user portal branding, data/document paths, license and pack
signing secrets, and operational tuning (connector timeouts, allowed hosts).

- **Current state**: same as everything else — frozen `Settings`, read once,
  no vault path (the vault's `_secret_value` lookup is specific to the
  Settings fields that opt into it; most of this tier doesn't).
- **What's needed**: this is where "make everything env-var-editable in the
  UI" actually requires new backend engineering, not a UI packet:
  1. A mutable settings-override store (most naturally: a small DB table of
     `{key, value, updated_by, updated_at}` rows that override env-var
     defaults), separate from the vault (which is credential-shaped and
     already has its own model).
  2. A defined reload path — either re-read overrides per-request for the
     fields that support it, or a narrower "apply and restart" flow that at
     least avoids manual file editing even if a restart is still required.
  3. An audit trail (who changed what, when) — this app already has an audit
     log for approvals/executions; extending it to settings changes is
     consistent with the existing pattern.
  4. Per-field decisions on **which of these 65 are actually safe to edit
     live** vs. which have the same "changes must be deliberate and traceable"
     property as Tier 2 in miniature (e.g., `WAIT_ADMIN_TOKEN` — rotating the
     admin credential from a UI that credential itself grants access to is a
     circular trust problem worth thinking through, not a simple form).
  5. Bootstrap tokens specifically are load-bearing for the entire auth model
     (`rbac.py`) — changing how they're read is not a small edit, it's the
     access-control substrate. Recommend treating auth-bootstrap tokens as
     their own excluded sub-tier regardless of how the rest of Tier 3 is
     scoped.
- **Effort**: large — this is a new backend capability (mutable config store
  + reload + audit), not a form-building exercise.
- **Recommendation: scope Tier 3 narrowly if approved.** Start with the
  lowest-risk subset (communication-channel webhooks, branding, embedding
  provider/model selection) behind the new mutable-settings capability, and
  explicitly exclude auth bootstrap tokens and anything already covered by
  Tier 1's vault path from the first cut.

## Recommended order (if approved)

1. **Tier 1** (connector credentials) — extends an already-shipped pattern,
   smallest step, most directly useful day to day.
2. **Tier 2** — no code change recommended; ship the explanatory-copy packet
   (P5.8) instead of a toggle.
3. **Tier 3** — do not start without a separate design pass for the mutable
   settings store + audit trail; when scoped, exclude auth bootstrap tokens
   and treat them as permanently restart-only given their role in the trust
   model.

## Standing requirement

No settings-mutation UI ships without: (a) confirmation of exactly which
backend, if any, actually persists the change (env-only defaults are silently
inert once a UI "save" implies otherwise), (b) an audit trail entry, (c) clear
in-UI indication of whether a restart is still required for the change to take
effect.
