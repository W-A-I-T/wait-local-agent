#!/usr/bin/env bash
set -euo pipefail

# Release-time operator verification for the real Power Platform boundary.
# This script intentionally never calls pac solution delete or any other tenant
# cleanup command. Local temporary material is removed by the EXIT trap only.
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE_PATH="${1:-}"

fail() {
  echo "ERROR: $1" >&2
  exit 1
}

if [[ $# -ne 1 ]]; then
  echo "Usage: scripts/verify_power_platform_live.sh <package-input.json>" >&2
  exit 2
fi

if [[ "$SOURCE_PATH" != /* ]]; then
  SOURCE_PATH="$(pwd)/$SOURCE_PATH"
fi
if [[ ! -f "$SOURCE_PATH" ]]; then
  fail "package input does not exist: $SOURCE_PATH"
fi

cd "$ROOT_DIR"

WAIT_CLI="$(command -v wait-local-agent || true)"
if [[ -z "$WAIT_CLI" ]]; then
  fail "wait-local-agent is required; install the repository package first"
fi

if [[ -n "${WAIT_PAC_PATH:-}" ]]; then
  PAC_PATH="$WAIT_PAC_PATH"
  if [[ -L "$PAC_PATH" || ! -f "$PAC_PATH" || ! -x "$PAC_PATH" ]]; then
    fail "WAIT_PAC_PATH must name a regular executable file"
  fi
else
  PAC_PATH="$(command -v pac || true)"
  if [[ -z "$PAC_PATH" || ! -f "$PAC_PATH" || ! -x "$PAC_PATH" ]]; then
    fail "pac is required; set WAIT_PAC_PATH or put pac on PATH"
  fi
fi

if [[ -z "${WAIT_POWER_PLATFORM_WORKSPACE:-}" ]]; then
  fail "WAIT_POWER_PLATFORM_WORKSPACE must be set to a pre-existing directory"
fi
if [[ -L "$WAIT_POWER_PLATFORM_WORKSPACE" || ! -d "$WAIT_POWER_PLATFORM_WORKSPACE" ]]; then
  fail "WAIT_POWER_PLATFORM_WORKSPACE must exist and be a directory"
fi

if [[ "${WAIT_ALLOW_WRITE_ACTIONS:-}" != "true" ]]; then
  fail "WAIT_ALLOW_WRITE_ACTIONS=true is required for live verification"
fi
if [[ "${WAIT_ALLOW_POWER_PLATFORM_DEPLOYMENT:-}" != "true" ]]; then
  fail "WAIT_ALLOW_POWER_PLATFORM_DEPLOYMENT=true is required for live verification"
fi

LIVE_ENVIRONMENT_URL="${WAIT_LIVE_ENVIRONMENT_URL:-}"
if [[ -z "$LIVE_ENVIRONMENT_URL" ]]; then
  fail "WAIT_LIVE_ENVIRONMENT_URL must name the target environment explicitly"
fi
if [[ "$LIVE_ENVIRONMENT_URL" != https://* || "$LIVE_ENVIRONMENT_URL" == *$'\n'* || "$LIVE_ENVIRONMENT_URL" == *$'\r'* || "$LIVE_ENVIRONMENT_URL" == *"?"* || "$LIVE_ENVIRONMENT_URL" == *"#"* || "$LIVE_ENVIRONMENT_URL" == *"@"* ]]; then
  fail "WAIT_LIVE_ENVIRONMENT_URL must be a credential-free HTTPS URL"
fi

if ! PACKAGE_MINIMUM_VERSION="$(python3 -c 'from wait_local_agent.power_platform_package import PAC_XML_MINIMUM_VERSION; print(PAC_XML_MINIMUM_VERSION)')"; then
  fail "could not read the Power Platform package minimum PAC version"
fi

if ! PAC_HELP_OUTPUT="$("$PAC_PATH" help 2>&1)"; then
  echo "$PAC_HELP_OUTPUT" >&2
  fail "pac help failed"
fi
if ! PAC_VERSION="$(printf '%s\n' "$PAC_HELP_OUTPUT" | python3 -c '
import re
import sys

match = re.search(r"(?im)^\s*Version:\s*(\d+(?:\.\d+)+)", sys.stdin.read())
if match is None:
    raise SystemExit(1)
print(match.group(1))
')"; then
  fail "pac help did not report a parseable version"
fi
if ! python3 -c '
import sys

actual = tuple(int(part) for part in sys.argv[1].split("."))
minimum = tuple(int(part) for part in sys.argv[2].split("."))
if actual < minimum:
    raise SystemExit(1)
' "$PAC_VERSION" "$PACKAGE_MINIMUM_VERSION"; then
  fail "pac version $PAC_VERSION is below the package minimum $PACKAGE_MINIMUM_VERSION"
fi
echo "PAC version: $PAC_VERSION (package minimum: $PACKAGE_MINIMUM_VERSION)"

if ! PAC_AUTH_OUTPUT="$("$PAC_PATH" auth list 2>&1)"; then
  echo "$PAC_AUTH_OUTPUT" >&2
  fail "pac auth list failed; create or select an authenticated profile"
fi
if ! AUTH_ENVIRONMENT_URL="$(printf '%s\n' "$PAC_AUTH_OUTPUT" | python3 -c '
import re
import sys

urls = []
for line in sys.stdin:
    urls.extend(re.findall(r"https://[^\s|]+", line))
if not urls:
    raise SystemExit(1)
print(urls[0].rstrip(".,;)]"))
')"; then
  echo "$PAC_AUTH_OUTPUT" >&2
  fail "pac auth list found no profile resolving an environment URL"
fi
echo "PAC auth profiles:"
echo "$PAC_AUTH_OUTPUT"
echo "PAC profile environment URL: $AUTH_ENVIRONMENT_URL"
echo "Explicit live target: $LIVE_ENVIRONMENT_URL"

if ! RUN_DIR="$(mktemp -d "${WAIT_POWER_PLATFORM_WORKSPACE%/}/.wait-power-platform-live.XXXXXX")"; then
  fail "could not create a temporary live-verification directory"
fi
trap 'rm -rf -- "$RUN_DIR"' EXIT

STAGED_SOURCE="$RUN_DIR/package-input.json"
if ! python3 -c '
import json
import sys

source, destination, output_directory = sys.argv[1:]
with open(source, encoding="utf-8") as stream:
    payload = json.load(stream)
if not isinstance(payload, dict):
    raise SystemExit("package input must contain a JSON object")
payload["output_directory"] = output_directory
with open(destination, "w", encoding="utf-8") as stream:
    json.dump(payload, stream, indent=2, sort_keys=True)
    stream.write("\n")
' "$SOURCE_PATH" "$STAGED_SOURCE" "$RUN_DIR/source"; then
  fail "package input could not be staged"
fi

run_cli_json() {
  local label="$1"
  local output="$2"
  shift 2
  local error_output="${output}.stderr"
  if ! "$WAIT_CLI" "$@" >"$output" 2>"$error_output"; then
    if [[ -s "$error_output" ]]; then
      sed -n '1,160p' "$error_output" >&2
    fi
    fail "$label failed"
  fi
}

PACKAGE_JSON="$RUN_DIR/package.json"
run_cli_json "package build" "$PACKAGE_JSON" microsoft package build "$STAGED_SOURCE"

if ! python3 -c '
import json
import sys

with open(sys.argv[1], encoding="utf-8") as stream:
    package = json.load(stream)
if package.get("package_status") not in {"deployable_source", "partial_source"}:
    raise SystemExit("package build returned no recognized package_status")
print(package["package_status"])
for component in package.get("design_only_components", []):
    print(component["reason"])
' "$PACKAGE_JSON" >"$RUN_DIR/package-status.txt"; then
  fail "package build returned an invalid status or design-only record"
fi
PACKAGE_STATUS="$(sed -n '1p' "$RUN_DIR/package-status.txt")"
echo "package_status: $PACKAGE_STATUS"
echo "design_only_components reasons:"
if [[ "$(wc -l <"$RUN_DIR/package-status.txt")" -gt 1 ]]; then
  sed -n '2,$p' "$RUN_DIR/package-status.txt"
else
  echo "none"
fi

VALIDATION_JSON="$RUN_DIR/validation.json"
run_cli_json "package validation" "$VALIDATION_JSON" microsoft package validate "$PACKAGE_JSON"
if ! python3 -c '
import json
import sys

with open(sys.argv[1], encoding="utf-8") as stream:
    result = json.load(stream)
if result.get("valid") is not True:
    raise SystemExit(1)
' "$VALIDATION_JSON"; then
  fail "package validation did not report valid=true"
fi
echo "package validation: valid=true"

MATERIALIZATION_JSON="$RUN_DIR/materialization.json"
run_cli_json "package materialization" "$MATERIALIZATION_JSON" microsoft package materialize "$PACKAGE_JSON"

if ! MATERIALIZATION_STATUS="$(python3 -c 'import json, sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["status"])' "$MATERIALIZATION_JSON")"; then
  fail "package materialization returned unreadable JSON"
fi
if [[ "$MATERIALIZATION_STATUS" != "succeeded" ]]; then
  fail "package materialization did not succeed (status=$MATERIALIZATION_STATUS)"
fi
if ! MATERIALIZATION_DIR="$(python3 -c 'import json, sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["materialization_directory"])' "$MATERIALIZATION_JSON")"; then
  fail "successful materialization did not return a directory"
fi
if ! ZIP_PATH="$(python3 -c 'import json, sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["pac_plan"]["zipfile"])' "$MATERIALIZATION_JSON")"; then
  fail "successful materialization did not return a PAC zip path"
fi
if ! UNIQUE_NAME="$(python3 -c 'import json, sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["solution"]["unique_name"])' "$PACKAGE_JSON")"; then
  fail "package did not return a solution unique name"
fi
if ! MATERIALIZATION_MINIMUM_VERSION="$(python3 -c 'import json, sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["pac_plan"]["minimum_cli_version"])' "$MATERIALIZATION_JSON")"; then
  fail "successful materialization did not return PAC compatibility metadata"
fi
if [[ "$MATERIALIZATION_MINIMUM_VERSION" != "$PACKAGE_MINIMUM_VERSION" ]]; then
  fail "materialization PAC minimum differs from the package declaration"
fi
if [[ ! -d "$MATERIALIZATION_DIR" ]]; then
  fail "materialization directory does not exist: $MATERIALIZATION_DIR"
fi

EXPECTED_FILES="$RUN_DIR/expected-files.txt"
if ! python3 -c '
import json
import sys

with open(sys.argv[1], encoding="utf-8") as stream:
    package = json.load(stream)
files = package.get("files")
if not isinstance(files, list):
    raise SystemExit(1)
for item in files:
    if not isinstance(item, dict) or not isinstance(item.get("path"), str):
        raise SystemExit(1)
    print(item["path"])
' "$PACKAGE_JSON" | LC_ALL=C sort >"$EXPECTED_FILES"; then
  fail "package files could not be read for the materialization pollution check"
fi
ACTUAL_FILES="$RUN_DIR/actual-files.txt"
find "$MATERIALIZATION_DIR" \( -type f -o -type l \) -printf '%P\n' | LC_ALL=C sort >"$ACTUAL_FILES"
if ! diff -u "$EXPECTED_FILES" "$ACTUAL_FILES"; then
  fail "materialization pollution check failed: on-disk files differ from package files[]"
fi
echo "materialization pollution check: passed"

PAC_PLAN_ARGV="$RUN_DIR/pac-plan-argv.bin"
if ! python3 -c '
import json
import sys

with open(sys.argv[1], encoding="utf-8") as stream:
    result = json.load(stream)
commands = result.get("pac_plan", {}).get("commands")
if not isinstance(commands, list) or len(commands) != 1:
    raise SystemExit("pac_plan.commands must contain exactly one argv")
argv = commands[0]
if not isinstance(argv, list) or not argv or any(not isinstance(arg, str) for arg in argv):
    raise SystemExit("pac_plan.commands must contain a string argv")
for argument in argv:
    sys.stdout.buffer.write(argument.encode("utf-8") + b"\0")
' "$MATERIALIZATION_JSON" >"$PAC_PLAN_ARGV"; then
  fail "materialization returned an invalid pac_plan.commands argv"
fi
mapfile -d '' PAC_PLAN_COMMAND <"$PAC_PLAN_ARGV"
if [[ "${PAC_PLAN_COMMAND[0]:-}" != "pac" ]]; then
  fail "pac_plan.commands does not identify pac as its executable"
fi
echo -n "PAC plan argv:"
printf ' %q' "${PAC_PLAN_COMMAND[@]}"
echo

# The arguments come only from pac_plan.commands. The executable is resolved
# above so WAIT_PAC_PATH is honored without changing the planned arguments.
PAC_EXECUTION_COMMAND=("${PAC_PLAN_COMMAND[@]}")
PAC_EXECUTION_COMMAND[0]="$PAC_PATH"
if ! (cd "$MATERIALIZATION_DIR" && "${PAC_EXECUTION_COMMAND[@]}"); then
  fail "PAC command from pac_plan.commands failed"
fi
if [[ ! -f "$ZIP_PATH" ]]; then
  fail "PAC command succeeded but the planned solution zip was not created"
fi
echo "PAC pack: succeeded"

if ! "$PAC_PATH" solution import --path "$ZIP_PATH" --environment "$LIVE_ENVIRONMENT_URL"; then
  fail "PAC solution import failed"
fi
echo "PAC solution import: succeeded"

if ! SOLUTION_LIST_OUTPUT="$("$PAC_PATH" solution list --environment "$LIVE_ENVIRONMENT_URL" 2>&1)"; then
  echo "$SOLUTION_LIST_OUTPUT" >&2
  fail "PAC solution list failed"
fi
echo "PAC solution list:"
echo "$SOLUTION_LIST_OUTPUT"
if ! grep -Fq -- "$UNIQUE_NAME" <<<"$SOLUTION_LIST_OUTPUT"; then
  fail "solution unique name '$UNIQUE_NAME' was not found in PAC solution list"
fi
echo "solution verification: $UNIQUE_NAME appears in the target solution list"

echo
echo "Cleanup guidance (printed only; not executed):"
echo "  If tenant cleanup is authorized, remove the imported solution through the normal approved operator procedure."
echo "  This script never deletes a tenant solution."

echo
echo "What this run did not prove:"
echo "  Flows are design-only."
echo "  Connectors are design-only."
echo "  No canvas app exists."
echo "  Unmapped attribute types were omitted rather than guessed."
echo "  A zero exit code is not provider confirmation of runtime health."
