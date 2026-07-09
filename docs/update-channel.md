# Update Channel

The public repo implements a signed update-channel client only. It checks for a newer release, verifies the release metadata with pinned Ed25519 public keys, and reports status through the CLI and admin API. It never downloads artifacts, never executes updates, and never auto-applies anything.

## Configuration

- `WAIT_UPDATE_CHANNEL_URL`: HTTPS URL for the release metadata document. Default empty string disables update checks.
- `WAIT_UPDATE_PUBKEYS`: comma-separated list of pinned Ed25519 public keys encoded as unpadded base64url. Any listed key may verify a release, which is the supported key-rotation mechanism.

## Metadata Format

The update-channel document is JSON with exactly these fields:

```json
{
  "version": "99.0.0",
  "released": "2026-07-08T12:00:00Z",
  "sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
  "signature": "DQvd_7OrgaUCTdFJw3LIn_Z1Zm51MizeA5WM2Gl-muRuYn4InMntdiXezkxsdQOZXmmyhmSmNDjFKF6mBr4xDA",
  "min_supported": "1.0.0",
  "notes_url": "https://updates.wait.example.test/releases/99.0.0"
}
```

Public example key for the signed example above:

```text
MSBcQFtCKN1AW2Ek6aNeeJRD9UzvlWP4gztIRRwjLD8
```

Field requirements:

- `version`: SemVer string for the release.
- `released`: ISO-8601 timestamp with timezone.
- `sha256`: lowercase hex SHA-256 of the release artifact.
- `signature`: unpadded base64url Ed25519 signature.
- `min_supported`: SemVer string for the oldest client version still supported by the channel.
- `notes_url`: HTTPS URL for release notes.

## Canonical Signature Input

The signature covers the canonical unsigned metadata bytes, not the fetched document bytes and not a re-serialized copy of the full signed document.

Verification input:

1. Parse the JSON document.
2. Remove the `signature` field.
3. Reconstruct JSON with the remaining fields only.
4. Sort keys lexicographically.
5. Serialize with compact separators `(",", ":")`.
6. Encode as UTF-8 bytes.
7. Verify the Ed25519 signature against those exact bytes.

Canonical example bytes for the document above:

```json
{"min_supported":"1.0.0","notes_url":"https://updates.wait.example.test/releases/99.0.0","released":"2026-07-08T12:00:00Z","sha256":"0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef","version":"99.0.0"}
```

## Client Behavior

- CLI: `wait-local-agent update check`
- API: `GET /update-status` for admin role only

Outcomes:

- Trusted newer version: report `update_available` with the remote version and `notes_url`.
- Trusted equal or older version: report `up_to_date`.
- Empty channel URL or unreachable endpoint: report `unknown`.
- Invalid signature, invalid pinned key, or malformed signed metadata: report `invalid_signature` and treat it as no update.

The API caches the last computed status in-process for one hour so repeated admin reads do not hammer the channel. Startup never blocks on the update channel because checks happen only when explicitly requested.
