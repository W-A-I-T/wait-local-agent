# Desktop sidecar build

The desktop sidecar is a one-file PyInstaller build of the local FastAPI
server. Build it on the target operating system; PyInstaller does not
cross-compile between operating systems.

```bash
uv sync --extra desktop
uv run pyinstaller --clean --noconfirm --distpath dist packaging/server.spec
```

The output binary is `dist/wait-local-agent-server` (or the platform
equivalent). Run it with `WAIT_DATA_PATH` and `WAIT_VAULT_PATH` set when the
desktop shell needs state outside the current directory. `WAIT_HOST` and
`WAIT_PORT` default to `127.0.0.1` and `8788`.

## Version evidence

The build-only extra pins PyInstaller `6.22.0`. [PyPI's verified project
metadata](https://pypi.org/pypi/pyinstaller/6.22.0/json) identifies `6.22.0` as
a mature release checked on 2026-08-21 and lists Python 3.8 through 3.15,
which includes this project's Python `>=3.12` target. The [official PyInstaller
release notes](https://pyinstaller.org/en/stable/CHANGES.html) document the
supported Python versions. Existing FastAPI and uvicorn dependency ranges were
not changed; the server uses the already-supported programmatic `uvicorn.run()`
API.
