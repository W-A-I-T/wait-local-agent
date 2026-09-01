from __future__ import annotations

import os
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts/install.sh"


def _stub(tmp_path: Path, name: str, contents: str) -> None:
    path = tmp_path / name
    path.write_text(contents, encoding="utf-8")
    path.chmod(0o755)


def test_dry_run_rejects_missing_docker(tmp_path: Path) -> None:
    _stub(tmp_path, "uname", "#!/bin/sh\nprintf '%s\\n' Linux\n")

    result = subprocess.run(
        ["/bin/bash", str(SCRIPT), "--dry-run"],
        env={"PATH": str(tmp_path)},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "Docker is required" in result.stderr


def test_installer_rejects_unsupported_os_before_docker_check(tmp_path: Path) -> None:
    _stub(tmp_path, "uname", "#!/bin/sh\nprintf '%s\\n' Darwin\n")

    result = subprocess.run(
        ["/bin/bash", str(SCRIPT), "--dry-run"],
        env={"PATH": str(tmp_path)},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "requires Linux" in result.stderr


def test_dry_run_reports_plan_without_side_effects(tmp_path: Path) -> None:
    _stub(tmp_path, "docker", """#!/bin/sh
if [ "$1" = compose ] && [ "$2" = version ]; then
  printf '%s\\n' 'Docker Compose version v2.30.0'
fi
""")
    install_dir = tmp_path / "install"
    environment = {**os.environ, "PATH": f"{tmp_path}:/bin", "WAIT_INSTALL_DIR": str(install_dir)}

    result = subprocess.run(
        ["/bin/bash", str(SCRIPT), "--version", "2.0.0", "--dry-run"],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "Image tag: 2.0.0" in result.stdout
    assert f"Install directory: {install_dir}" in result.stdout
    assert "Setup URL: http://127.0.0.1:8788" in result.stdout
    assert not install_dir.exists()
