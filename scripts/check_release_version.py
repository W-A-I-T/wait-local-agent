from __future__ import annotations

import json
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXTERNAL_VERSION = "2.0.0-rc.1"
PEP440_VERSION = "2.0.0rc1"


def main() -> int:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    cargo = tomllib.loads((ROOT / "desktop/src-tauri/Cargo.toml").read_text(encoding="utf-8"))
    ui_package = json.loads((ROOT / "ui/package.json").read_text(encoding="utf-8"))
    ui_lock = json.loads((ROOT / "ui/package-lock.json").read_text(encoding="utf-8"))
    desktop_package = json.loads((ROOT / "desktop/package.json").read_text(encoding="utf-8"))
    tauri = json.loads((ROOT / "desktop/src-tauri/tauri.conf.json").read_text(encoding="utf-8"))
    runtime = re.search(
        r'__version__\s*=\s*"([^"]+)"',
        (ROOT / "src/wait_local_agent/__init__.py").read_text(encoding="utf-8"),
    )
    if runtime is None:
        print("runtime version was not found", file=sys.stderr)
        return 1

    checks = {
        "runtime": (runtime.group(1), EXTERNAL_VERSION),
        "python": (pyproject["project"]["version"], PEP440_VERSION),
        "ui package": (ui_package["version"], EXTERNAL_VERSION),
        "ui lock": (ui_lock["packages"][""]["version"], EXTERNAL_VERSION),
        "desktop package": (desktop_package["version"], EXTERNAL_VERSION),
        "cargo": (cargo["package"]["version"], EXTERNAL_VERSION),
        "tauri": (tauri["version"], EXTERNAL_VERSION),
    }
    failures = [
        f"{name}: {actual!r} != {expected!r}"
        for name, (actual, expected) in checks.items()
        if actual != expected
    ]
    if failures:
        print("release version check failed:", file=sys.stderr)
        print("\n".join(failures), file=sys.stderr)
        return 1
    print(f"release version aligned: {EXTERNAL_VERSION} (Python {PEP440_VERSION})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
