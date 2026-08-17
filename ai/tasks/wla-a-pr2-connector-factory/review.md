# Review

The factory is read-only and fail-closed at the instance boundary.

Security checks reviewed:

- Unknown connector types fail before any global provider fallback; inactive,
  disabled, and error instances fail before the vault is read.
- Vault and JSON failures use fixed messages and chain the original exception
  without copying its text into the factory error. Duplicate JSON keys,
  non-object payloads, extra keys, non-string values, and whitespace-only
  values are rejected. Valid surrounding secret bytes are preserved.
- The copied settings force `allow_write_actions=False`, clear Halo write
  endpoints and inherited token URL, blank the audited credential field map,
  and restore only the current instance's provider credentials.
- `base_url` is validated against `connector_instance_allowed_hosts` before a
  client is returned. Halo's token URL is derived from that same base, checked
  independently, and compared by scheme, host, and effective port.
- The optional resolver is passed to `PinnedIpTransport`; the optional inner
  transport is always nested inside it. Tests prove private DNS results fail
  before the inner transport and public results reach it only after resolution.

The DTO-deferred note is recorded in `implementation.md`. The module remains
unwired by design; A-PR3 owns ingestion and polling.
