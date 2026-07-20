# WAIT Local Agent desktop shell

This directory contains the Tauri v2 desktop wrapper for the existing React
dashboard. The Python API remains the source of application behavior and is
packaged as the `wait-local-agent-server` sidecar.

From the repository root, prepare a local build with:

```bash
python -m pip install -e ".[desktop]"
npm ci --prefix ui
npm install --prefix desktop
bash packaging/build-sidecar.sh
npm run tauri --prefix desktop -- build
```

The sidecar is deliberately kept out of source control. The packaging helper
creates the target-triple-named binary under `src-tauri/binaries/` immediately
before `tauri build`.
