#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
dist_dir="$repo_root/dist"
work_dir="$repo_root/build/pyinstaller"
binary_name="wait-local-agent-server"

target="$(rustc -vV | awk '/^host: / { print $2 }')"
if [[ -z "$target" ]]; then
  echo "Unable to determine the Rust host target triple" >&2
  exit 1
fi

if [[ "$target" == *windows* ]]; then
  extension=".exe"
else
  extension=""
fi

if command -v uv >/dev/null 2>&1; then
  uv run --extra desktop pyinstaller --clean --noconfirm \
    --distpath "$dist_dir" --workpath "$work_dir" \
    "$repo_root/packaging/server.spec"
else
  python -m PyInstaller --clean --noconfirm \
    --distpath "$dist_dir" --workpath "$work_dir" \
    "$repo_root/packaging/server.spec"
fi

source_binary="$dist_dir/$binary_name$extension"
destination_dir="$repo_root/desktop/src-tauri/binaries"
destination="$destination_dir/$binary_name-$target$extension"

if [[ ! -f "$source_binary" ]]; then
  echo "PyInstaller did not produce $source_binary" >&2
  exit 1
fi

mkdir -p "$destination_dir"
cp "$source_binary" "$destination"
if [[ "$target" != *windows* ]]; then
  chmod +x "$destination"
fi
echo "Prepared sidecar: $destination"
