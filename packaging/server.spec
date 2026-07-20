# ruff: noqa: F821

from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

project_root = Path(SPEC).resolve().parents[1]
source_root = project_root / "src"

a = Analysis(
    [str(source_root / "wait_local_agent" / "api" / "server_entry.py")],
    pathex=[str(source_root)],
    binaries=[],
    datas=[],
    hiddenimports=collect_submodules("wait_local_agent"),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="wait-local-agent-server",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
)
