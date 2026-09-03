"""Shared Power Platform golden fixtures.

The canonical input below is deliberately literal: changing the producer must
not silently change the emitter's golden-test subject. To deliberately update
the checked-in output after reviewing a format change, run:

    WAIT_REGENERATE_GOLDEN=1 python -m pytest tests/test_power_platform_golden.py

The regeneration switch only updates the named fixture directory and should
not be used as a routine way to make a failing test pass.
"""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

CANONICAL_INPUT_ARTIFACT: dict[str, object] = {
    "format": "wait-local-agent.power-apps-artifact",
    "format_version": 1,
    "client_id": "acme",
    "app_name": "Employee onboarding workspace",
    "dataverse": {
        "schema_version": 1,
        "tables": [
            {
                "logical_name": "wait_employee",
                "display_name": "Employee",
                "primary_name_column": "wait_display_name",
                "columns": [
                    {
                        "logical_name": "wait_display_name",
                        "display_name": "Display name",
                        "type": "String",
                        "required": True,
                    },
                    {
                        "logical_name": "wait_start_date",
                        "display_name": "Start date",
                        "type": "DateOnly",
                    },
                ],
            }
        ],
    },
    "credentials_included": False,
    "execution_started": False,
    "deployment_started": False,
}

_GOLDEN_ROOT = Path(__file__).parent / "power_platform_reference" / "golden"


@dataclass(frozen=True)
class PacShim:
    """On-disk PAC substitute used to exercise real subprocess execution."""

    executable: Path
    argv_log: Path
    failure_trigger: str


def write_pac_shim(tmp_path: Path) -> PacShim:
    """Write a cross-platform executable that implements the tested PAC edges.

    The shim is intentionally tiny and local: it records each invocation, emits
    a stable version from ``help``, writes a real ZIP for ``solution pack``, and
    has one deterministic non-zero trigger for failure-path tests. It does not
    contact Dataverse or represent a tenant.
    """

    shim_directory = tmp_path / "pac-shim"
    shim_directory.mkdir()
    argv_log = shim_directory / "argv.jsonl"
    failure_trigger = "--wait-pac-shim-fail"
    implementation = f'''import json
import os
import sys
import zipfile
from pathlib import Path

argv = sys.argv[1:]
with Path(os.environ["WAIT_PAC_SHIM_ARGV_LOG"]).open("a", encoding="utf-8") as stream:
    json.dump({{"argv": argv, "cwd": os.getcwd()}}, stream)
    stream.write("\\n")

if {failure_trigger!r} in argv:
    print("token=REDACTION-PROBE-VALUE-DO-NOT-MATCH")
    print("authorization=REDACTION-PROBE-VALUE-DO-NOT-MATCH", file=sys.stderr)
    raise SystemExit(7)

if argv == ["help"]:
    print("Version: 2.4.1")
    raise SystemExit(0)

if len(argv) >= 2 and argv[:2] == ["solution", "pack"]:
    try:
        zipfile_argument = argv.index("--zipfile") + 1
        artifact = Path(argv[zipfile_argument])
    except (ValueError, IndexError):
        print("missing --zipfile", file=sys.stderr)
        raise SystemExit(2) from None
    artifact.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(artifact, "w") as archive:
        archive.writestr("solution.xml", "<ImportExportXml />")
    print("packed")
    raise SystemExit(0)

print("unsupported command", file=sys.stderr)
raise SystemExit(2)
'''

    if os.name == "nt":
        script = shim_directory / "pac_shim.py"
        script.write_text(implementation, encoding="utf-8", newline="\r\n")
        executable = shim_directory / "pac.cmd"
        executable.write_text(
            '@echo off\r\npython "%~dp0pac_shim.py" %*\r\nexit /b %ERRORLEVEL%\r\n',
            encoding="utf-8",
            newline="",
        )
    else:
        executable = shim_directory / "pac"
        executable.write_text("#!/usr/bin/env python3\n" + implementation, encoding="utf-8")
        executable.chmod(executable.stat().st_mode | 0o111)

    return PacShim(executable=executable, argv_log=argv_log, failure_trigger=failure_trigger)


def assert_matches_golden(files: Sequence[Mapping[str, object]], name: str) -> None:
    """Assert emitted file bytes match ``golden/<name>`` exactly.

    ``WAIT_REGENERATE_GOLDEN=1`` makes this helper replace files in that one
    fixture directory with the supplied output before asserting. Paths are
    constrained to the fixture directory during regeneration.
    """

    actual: dict[str, bytes] = {}
    for file in files:
        path = file.get("path")
        content = file.get("content")
        if not isinstance(path, str) or not isinstance(content, str):
            raise AssertionError("emitted files must contain string path and content values")
        relative = Path(path)
        if relative.is_absolute() or ".." in relative.parts:
            raise AssertionError(f"emitted path escapes the golden fixture: {path}")
        if path in actual:
            raise AssertionError(f"duplicate emitted path: {path}")
        actual[path] = content.encode("utf-8")

    fixture_name = Path(name)
    if fixture_name.is_absolute() or fixture_name.parts != (name,):
        raise AssertionError(f"golden fixture name must be a single relative directory: {name}")
    golden_dir = _GOLDEN_ROOT / fixture_name
    if os.environ.get("WAIT_REGENERATE_GOLDEN") == "1":
        golden_dir.mkdir(parents=True, exist_ok=True)
        for existing in sorted(golden_dir.rglob("*"), key=str, reverse=True):
            if existing.is_file():
                existing.unlink()
            elif existing.is_dir() and not any(existing.iterdir()):
                existing.rmdir()
        for path, content in actual.items():
            target = golden_dir / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)

    expected = {
        path.relative_to(golden_dir).as_posix(): path.read_bytes()
        for path in golden_dir.rglob("*")
        if path.is_file()
    }
    assert actual == expected
