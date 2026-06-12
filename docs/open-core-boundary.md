# Open-Core Boundary

WAIT Local Agent is the public open-core repository. It stays Apache 2.0 and self-hosted.

## Public repo scope

This repository may contain:

- local runtime, API, CLI, dashboard, and Docker Compose appliance
- SQLite store, knowledge index, approval engine, event history, and audit export
- HaloPSA read paths and approval-gated HaloPSA write execution
- Hudu read-only documentation context
- workflow schema and open-core workflow templates
- connector framework and tests
- launch docs, sample data, scripts, and issue templates

## Out of scope for this repo

Do not add paid or proprietary pack internals here. That includes:

- MSP Pack implementation beyond open-core interfaces
- Founder Pack project scanner, evidence vault, LP bundle implementation, or investor workflow internals
- private RMM connector implementation
- private white-label branding implementation
- paid license enforcement implementation beyond open-core interface stubs
- proprietary templates, scripts, or client-specific automations

Private pack work belongs in `W-A-I-T/wait-local-agent-packs` (https://github.com/W-A-I-T/wait-local-agent-packs — private) or another private repository.

## Local install directory

`packs/` is gitignored. It is reserved for local proprietary pack installs and should not be committed.

## Dependency policy

- Prefer Apache 2.0, MIT, BSD, and similarly permissive dependencies.
- Do not copy AGPL code into this repository.
- Treat `alga-psa` and similar AGPL projects as architecture references only unless WAIT explicitly accepts AGPL obligations.
- Run a license inventory before release when dependencies change.

This pass added `cryptography` for the local Fernet vault. It is a permissive dependency family and must still be confirmed by the release license check.

## Runtime boundary

Open-core behavior remains safe by default:

- no live writes by default
- no HTTP probing by default
- no cloud fallback by default
- no model inference by default
- no proprietary pack code by default
- all HaloPSA mutations require a draft and approval before execution
