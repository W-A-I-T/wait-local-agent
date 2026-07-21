# WAIT Local Agent desktop app

The desktop app packages the existing React dashboard together with the
`wait-local-agent-server` Python sidecar. It runs the server on `127.0.0.1:8788`,
keeps the workspace on the local computer, waits for the server to be ready,
and stops it when the app closes.

## Download and install

Download the draft release asset for the operating system:

- Windows: `.msi` or `.exe` installer
- macOS: `.dmg`
- Linux: `.AppImage` or `.deb`

macOS releases include two native bundles: one for Intel Macs and one for
Apple Silicon Macs. Choose the `.dmg` matching your Mac's processor.
Release signing is optional: when the repository signing secrets are absent,
the workflow still publishes the same unsigned installers and the first launch
may show the operating system's unsigned-app warning. Confirm that the file
came from the WAIT Local Agent GitHub Release before choosing the system's
option to open or keep it.

To enable signing in release CI, add all of these repository secrets:

- macOS Developer ID signing and notarization: `APPLE_CERTIFICATE` (base64
  encoded `.p12`), `APPLE_CERTIFICATE_PASSWORD`, `APPLE_SIGNING_IDENTITY`,
  `APPLE_ID`, `APPLE_PASSWORD` (an Apple app-specific password), and
  `APPLE_TEAM_ID`.
- Windows Authenticode signing: `WINDOWS_CERTIFICATE` (base64 encoded `.pfx`)
  and `WINDOWS_CERTIFICATE_PASSWORD`.
- Tauri updater artifacts: `TAURI_SIGNING_PRIVATE_KEY` and
  `TAURI_SIGNING_PRIVATE_KEY_PASSWORD`.
- Optional Linux checksum signature: `GPG_PRIVATE_KEY` and `GPG_PASSPHRASE`.

Signing is atomic per platform. If any secret in a platform's set is missing,
that platform remains unsigned. Linux installers remain unsigned, but every
Linux release also includes a `SHA256SUMS` integrity file. A detached
`SHA256SUMS.asc` signature is included when the release GPG secrets are
configured.

## In-app updates

Installed desktop builds check for a newer published GitHub release in the
background during startup. If an update is available, the app asks whether to
download and install it; accepting restarts the app after installation, while
declining leaves the current version running. Offline checks, missing releases,
and updater errors are logged and do not prevent the app from starting.

The updater endpoint uses published releases. Draft releases are not available
to the in-app updater until they are published. Updater artifacts require the
CI secrets `TAURI_SIGNING_PRIVATE_KEY` and
`TAURI_SIGNING_PRIVATE_KEY_PASSWORD`; without them, the normal unsigned
installer fallback remains available, but an installer cannot provide a signed
in-app update package.

## Verify Linux release integrity

Download `SHA256SUMS` alongside the Linux `.AppImage`, `.deb`, or `.rpm` assets
from the same release, then run this from the directory containing those files
and the checksum file:

```bash
sha256sum -c SHA256SUMS
```

When `SHA256SUMS.asc` is present, import the WAIT release-publishing GPG public
key provided by the release maintainer and verify the detached signature:

```bash
gpg --import WAIT-release-signing-public-key.asc
gpg --verify SHA256SUMS.asc SHA256SUMS
```

The signature is optional because release CI skips GPG signing when
`GPG_PRIVATE_KEY` or `GPG_PASSPHRASE` is not configured. A passing checksum
check confirms the downloaded Linux files match the release's published
integrity manifest; a passing GPG check additionally authenticates that
manifest against the imported release key.

## Build locally

Run these commands from the repository root. The sidecar must be built on the
same operating system and architecture as the Tauri bundle. On macOS, build on
an Intel runner for Intel output or on an Apple Silicon runner for Apple
Silicon output.

```bash
python -m pip install -e ".[desktop]"
npm ci --prefix ui
npm install --prefix desktop
bash packaging/build-sidecar.sh
npm run build --prefix desktop
```

The macOS command builds for the architecture of the current machine.

The resulting files are under `desktop/src-tauri/target/release/bundle/`:

- Linux: `appimage/` and `deb/`
- macOS: `dmg/`
- Windows: `msi/` and `nsis/`

For an interactive development run, build the sidecar first and then run:

```bash
npm run tauri --prefix desktop -- dev
```

The helper names the sidecar using the Rust host tuple required by Tauri, for
example `wait-local-agent-server-x86_64-unknown-linux-gnu` on Linux,
`wait-local-agent-server-x86_64-pc-windows-msvc.exe` on Windows,
`wait-local-agent-server-x86_64-apple-darwin` on Intel macOS, and
`wait-local-agent-server-aarch64-apple-darwin` on Apple Silicon macOS.

## Existing paths remain available

The Docker appliance and command-line workflows remain unchanged. Use the
existing [README quick start](../README.md#quick-start) for Docker or local
CLI operation when a desktop installer is not the right fit.

## Release automation

Pushing a `v*` tag starts `.github/workflows/release-desktop.yml`. Each runner
builds its own PyInstaller sidecar, builds the React UI in desktop mode, and
uses `tauri-apps/tauri-action@v1` to attach installers to a draft GitHub
Release. The workflow runs macOS on both `macos-15-intel` (Intel) and
`macos-latest` (Apple Silicon), producing one native `.dmg` from each runner.
macOS signing and notarization and Windows Authenticode signing are enabled
only when their complete secret sets are present; otherwise all jobs publish
unsigned installers.
