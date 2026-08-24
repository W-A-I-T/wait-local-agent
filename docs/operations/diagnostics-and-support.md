# Diagnostics & Support Specification

> **Status: specification. Tracked for an upcoming release.**

This page defines a forthcoming Diagnostics & Support capability. It does not
describe a feature that ships in the current public runtime.

## Redacted support bundle

The capability will assemble a redacted bundle for troubleshooting without
collecting customer work content by default. Bundle creation will remain a
local, customer-initiated operation.

### What it will contain

- WAIT version, build commit, and update channel;
- operating system and install type;
- Docker, desktop, or CLI operating mode;
- database schema version and integrity result;
- safe configuration booleans only, never secret values;
- connector IDs and readiness;
- installed pack IDs, versions, and signature status;
- the last failed executions with redacted step errors;
- recent audit event types and statuses;
- healthcheck and hardening results;
- available disk space;
- process start time and uptime;
- recent structured errors after redaction;
- update-check status;
- correlation IDs used to trace related local events; and
- a manifest listing every bundle item with its SHA-256 hash.

### What it excludes by default

- ticket bodies and email bodies;
- knowledge documents;
- prompts and model completions;
- customer names;
- user names and email addresses;
- tenant IDs;
- hostnames and IP addresses;
- device serial numbers;
- URLs carrying customer information; and
- all keys, passwords, tokens, certificates, and private keys.

## Required flow

1. **Generate locally.** The operator requests a new redacted bundle.
2. **Preview exactly what is included.** The preview lists every file and field
   before any transfer can occur.
3. **Download.** The operator saves the bundle locally for their own review or
   delivery process.
4. **Optionally upload with explicit consent.** Upload is a separate action. The
   destination and stated retention period must be shown before the operator
   consents.
5. **Record upload and deletion locally.** The appliance keeps a local record
   of an upload and of any requested local or remote deletion, including its
   status.

The download-only path will be fully supported for European and air-gapped
installs. Upload will not be required for bundle creation, preview, or local
download.

Until this specification is implemented, use the local commands in
[Troubleshooting](troubleshooting.md) and redact their output before sharing it.

