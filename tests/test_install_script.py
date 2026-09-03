from __future__ import annotations

import os
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts/install.sh"
RELEASE_VALIDATION = Path(__file__).parents[1] / "scripts/validate_release.sh"
CI_WORKFLOW = Path(__file__).parents[1] / ".github/workflows/test.yml"


def _stub(tmp_path: Path, name: str, contents: str) -> None:
    path = tmp_path / name
    path.write_text(contents, encoding="utf-8")
    path.chmod(0o755)


def _installer_environment(tmp_path: Path, *, with_cosign: bool = False) -> dict[str, str]:
    image_ref = "ghcr.io/w-a-i-t/wait-local-agent@sha256:" + "a" * 64
    _stub(
        tmp_path,
        "docker",
        f"""#!/bin/sh
if [ \"$1\" = compose ] && [ \"$2\" = version ]; then
  printf '%s\\n' 'Docker Compose version v2.30.0'
elif [ \"$1\" = image ] && [ \"$2\" = inspect ]; then
  printf '%s\\n' '{image_ref}'
elif [ \"$1\" = run ]; then
  printf '%s\\n' 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopq='
fi
""",
    )
    _stub(
        tmp_path,
        "curl",
        """#!/bin/sh
log_file=\"$FAKE_CURL_LOG\"
printf '%s\\n' \"$@\" >> \"$log_file\"
url=''
for arg do url=\"$arg\"; done
    case \"$url\" in
      https://api.github.com/*) printf '%s\\n' '{\"tag_name\":\"v2.0.0\"}' ;;
      https://raw.githubusercontent.com/*) printf '%s\\n' 'services: {}' ;;
  http://127.0.0.1:*) exit 0 ;;
  *) exit 1 ;;
esac
""",
    )
    if with_cosign:
        _stub(
            tmp_path,
            "cosign",
            """#!/bin/sh
printf '%s\\n' "$@" > "$FAKE_COSIGN_LOG"
""",
        )
    install_dir = tmp_path / "install"
    environment = {
        **os.environ,
        "PATH": f"{tmp_path}:/bin",
        "WAIT_INSTALL_DIR": str(install_dir),
        "FAKE_CURL_LOG": str(tmp_path / "curl.log"),
    }
    if with_cosign:
        environment["FAKE_COSIGN_LOG"] = str(tmp_path / "cosign.log")
    return environment


def _run_installer(
    tmp_path: Path, *args: str, with_cosign: bool = False
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["/bin/bash", str(SCRIPT), *args],
        env=_installer_environment(tmp_path, with_cosign=with_cosign),
        capture_output=True,
        text=True,
        check=False,
    )


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


def test_pinned_install_fetches_release_compose_and_records_digest(tmp_path: Path) -> None:
    result = _run_installer(tmp_path, "--version", "2.0.0", "--no-verify")

    assert result.returncode == 0, result.stderr
    install_dir = tmp_path / "install"
    env_file = (install_dir / ".env").read_text(encoding="utf-8")
    curl_log = (tmp_path / "curl.log").read_text(encoding="utf-8")
    assert "WAIT_IMAGE_REF=ghcr.io/w-a-i-t/wait-local-agent@sha256:" in env_file
    assert "WAIT_IMAGE_VERIFIED=false" in env_file
    assert "/v2.0.0/docker-compose.prod.yml" in curl_log
    assert "/main/" not in curl_log
    assert "One-time" not in result.stdout


def test_install_fails_closed_without_cosign(tmp_path: Path) -> None:
    result = _run_installer(tmp_path, "--version", "2.0.0")

    assert result.returncode != 0
    assert "cosign" in result.stderr
    assert "--no-verify" in result.stderr


def test_install_verifies_the_pulled_digest_with_cosign(tmp_path: Path) -> None:
    result = _run_installer(tmp_path, "--version", "2.0.0", with_cosign=True)

    assert result.returncode == 0, result.stderr
    env_file = (tmp_path / "install" / ".env").read_text(encoding="utf-8")
    cosign_log = (tmp_path / "cosign.log").read_text(encoding="utf-8")
    assert "WAIT_IMAGE_VERIFIED=true" in env_file
    assert "verify" in cosign_log
    assert "--certificate-identity-regexp" in cosign_log
    assert "--certificate-oidc-issuer" in cosign_log
    assert "@sha256:" in cosign_log


def test_stable_resolves_to_a_release_tag(tmp_path: Path) -> None:
    result = _run_installer(tmp_path, "--version", "stable", "--no-verify")

    assert result.returncode == 0, result.stderr
    assert "Resolved stable to release v2.0.0" in result.stderr
    curl_log = (tmp_path / "curl.log").read_text(encoding="utf-8")
    assert "/v2.0.0/docker-compose.prod.yml" in curl_log


def test_no_verify_is_loud_and_persists_bootstrap_token_wording(tmp_path: Path) -> None:
    result = _run_installer(tmp_path, "--version", "2.0.0", "--no-verify")

    assert result.returncode == 0, result.stderr
    assert "WARNING: --no-verify" in result.stderr
    assert "Bootstrap admin token (persisted in .env; rotate after creating a database admin):" in result.stdout
    assert "One-time" not in result.stdout


def test_release_validation_and_ci_measure_the_same_python_coverage_sources() -> None:
    release_script = RELEASE_VALIDATION.read_text(encoding="utf-8")
    workflow = CI_WORKFLOW.read_text(encoding="utf-8")

    expected_flags = ("--cov=wait_local_agent", "--cov=packs", "--cov-fail-under=95")
    for flag in expected_flags:
        assert flag in release_script
        assert flag in workflow
