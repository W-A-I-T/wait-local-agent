from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP_PARTS = {".git", ".venv", "node_modules", "dist", "__pycache__", ".pytest_cache"}
TEXT_SUFFIXES = {
    ".css",
    ".html",
    ".json",
    ".md",
    ".py",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".yml",
    ".yaml",
}


def tracked_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=ROOT,
        text=True,
        check=True,
        capture_output=True,
    )
    return [ROOT / line for line in result.stdout.splitlines() if line]


def blocked_terms() -> list[str]:
    pieces = [
        ("co", "dex"),
        ("cla", "ude"),
        ("dev", "in"),
        ("chat", "gpt"),
        ("generated", " by"),
        ("created", " by ai"),
        ("ai", " tool"),
    ]
    return ["".join(piece).lower() for piece in pieces]


def is_text_file(path: Path) -> bool:
    return path.suffix in TEXT_SUFFIXES and not any(part in SKIP_PARTS for part in path.parts)


def main() -> int:
    failures: list[str] = []
    terms = blocked_terms()
    for path in tracked_files():
        if not is_text_file(path):
            continue
        content = path.read_text(encoding="utf-8").lower()
        for term in terms:
            if term in content:
                failures.append(f"{path.relative_to(ROOT)} contains a blocked public-surface term")

    if failures:
        for failure in failures:
            print(failure)
        return 1

    print("public surface audit passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())

