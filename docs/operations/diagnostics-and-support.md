# Diagnostics & Support

WAIT Local Agent ships appliance diagnostics and deterministic, redacted
support bundles. Collection is allowlist-first: it selects fixed operational
facts instead of copying broad configuration, environment, artifact, or content
stores and trying to clean them afterward.

## Access boundary

The diagnostics API is restricted to an appliance or MSP administrator. An
administrator bound to a single client cannot view or create an appliance-wide
bundle. The Diagnostics & Support screen applies the same administrator gate in
the browser, and the API remains the enforcement point.

## Local commands

```bash
wait-local-agent support doctor
wait-local-agent support bundle --preview
wait-local-agent support bundle --output /approved/private/location/support.zip
wait-local-agent support upload --consent
```

`support doctor` prints the allowlisted summary. Bundle preview writes no file.
Bundle creation writes a private local archive, optionally copies it to the
operator-selected output path, and prints its SHA-256 digest. Support upload is
not available in this edition: `support upload` records the unavailability and
exits nonzero. Download remains available for an operator-approved transfer.

## Local API

- `GET /diagnostics/summary` returns the allowlisted operational summary.
- `POST /diagnostics/bundle/preview` returns the fixed inclusion and exclusion
  lists without writing a file.
- `POST /diagnostics/bundle` creates and returns the ZIP archive.
- `POST /diagnostics/bundle/upload` returns `501` with
  `support_upload_unavailable`; it performs no network transfer.

Every request receives a validated `X-Correlation-ID` response header. A valid
incoming value is reused; an invalid or missing value is replaced. Run entry
points pass that identifier explicitly into execution recording.

## Bundle contents

Each bounded archive contains fixed JSON sections for:

- WAIT version, build commit when cheaply available, operating system, install
  mode, free disk, process start, and uptime;
- database migration version and SQLite integrity result;
- safe feature and connector-configuration booleans;
- path existence and writability facts without path strings;
- connector IDs and readiness;
- installed pack IDs, versions, and signature-recording status;
- recent failed execution metadata with scrubbed step errors;
- recent audit event types and statuses only;
- the latest hardening result and update-check status; and
- recent valid correlation IDs.

The archive never contains execution artifacts. It has fixed entry and total
size caps and never walks the filesystem. If a section cannot be collected, its
file contains a degraded marker rather than disappearing silently. The
deterministic `manifest.json` records every section's size and SHA-256 plus an
overall content digest. An optional case reference is stored only as a digest.

## Excluded data

The fixed exclusion list covers:

- ticket and email bodies;
- knowledge documents;
- prompts and completions;
- customer, user, and tenant identities;
- user email addresses;
- hostnames, IP addresses, device serial numbers, and customer URLs; and
- keys, passwords, tokens, certificates, and private keys.

Free-text failure details receive additional defense-in-depth scrubbing for
email addresses, IPv4 and IPv6 literals, URLs, hostnames, bearer and
JWT-shaped material, cloud access-key shapes, long token shapes, secret-style
assignments, and private identity assignments.

## Private structured logs

Server startup and `serve` initialize bounded rotating JSON-line logs under the
configured private log directory. Without `WAIT_LOG_DIR`, the directory is
derived from the local data-file location. Permissions are reapplied to the
active file and retained backups after rotation, and messages and exception
text pass through the same scrubber before being written.

Offline mode does not contact an update or support service. Diagnostics,
preview, and download remain available for air-gapped installations.
