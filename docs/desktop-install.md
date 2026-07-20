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

Signing is atomic per platform. If any secret in a platform's set is missing,
that platform remains unsigned; Linux remains unsigned.

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
