# Pack Loader

WAIT Local Agent supports optional installed packs discovered from importable
`packs.*` modules and the top-level `sync` package.

Each pack module may expose a `PACK_MANIFEST` dictionary with:

- `name`
- `version`
- `requires_license`
- `api_router_factory`
- `cli_app`

The loader imports each candidate module, ignores modules without
`PACK_MANIFEST`, and skips broken modules with a warning so pack failures do
not crash API or CLI startup.

## License Gating

Licensed packs read `WAIT_LICENSE_KEY`. When the Fernet vault backend is
enabled, the loader also checks the vaulted `license_key` secret. If
`packs.license.keys` is unavailable, licensed packs remain locked.

Locked packs appear in `wait-local-agent packs list` and
`wait-local-agent packs status`, but their routers and CLI groups are not
mounted.

## Mounting

Unlocked pack routers mount under `/packs/<name>`. The founder pack is
excluded from automatic router mounting because first-party `/founder/*`
surfaces can delegate through the loader registry.

Unlocked pack CLI apps mount as `wait-local-agent <name> ...` unless the pack
name collides with an existing first-party command.

## Installing Signed Tarballs

`wait-local-agent packs install /path/to/wait-pack-<name>-<version>.tar.gz --license <key>`

The installer verifies the adjacent `.sig` file with
`WAIT_PACK_SIGNING_SECRET`, validates `manifest.json` digests, rejects unsafe
archive members such as absolute paths or `..`, extracts the pack tree into
the local install, and stores the license in the Fernet vault when enabled.
