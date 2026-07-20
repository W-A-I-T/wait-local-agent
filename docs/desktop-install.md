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

This first release is unsigned. Windows SmartScreen, macOS Gatekeeper, or a
Linux desktop may show a warning because the installer does not yet have a
publisher signature. Confirm that the file came from the WAIT Local Agent
GitHub Release before choosing the system's option to open or keep it.

## Build locally

Run these commands from the repository root. The sidecar must be built on the
same operating system and architecture as the Tauri bundle.

```bash
python -m pip install -e ".[desktop]"
npm ci --prefix ui
npm install --prefix desktop
bash packaging/build-sidecar.sh
npm run tauri --prefix desktop -- build
```

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
`wait-local-agent-server-x86_64-pc-windows-msvc.exe` on Windows, and the
matching `*-apple-darwin` tuple on macOS.

## Existing paths remain available

The Docker appliance and command-line workflows remain unchanged. Use the
existing [README quick start](../README.md#quick-start) for Docker or local
CLI operation when a desktop installer is not the right fit.

## Release automation

Pushing a `v*` tag starts `.github/workflows/release-desktop.yml`. Each runner
builds its own PyInstaller sidecar, builds the React UI in desktop mode, and
uses `tauri-apps/tauri-action@v1` to attach unsigned installers to a draft
GitHub Release. Code signing, notarization, and an updater are follow-up work.
