#!/usr/bin/env bash
set -euo pipefail

# Run a real-browser dashboard matrix against an already-running local stack.
# This intentionally does not start or mutate the appliance: callers choose the
# API/UI fixture and may point it at a token-enforced environment.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UI_URL="${WAIT_BROWSER_UI_URL:-http://127.0.0.1:5173}"
BROWSER="${WAIT_BROWSER_BROWSER:-firefox}"
SESSION="wait-ui-browser-${BASHPID}"
REPORT_PATH="${WAIT_BROWSER_REPORT:-$ROOT_DIR/output/playwright/ui-browser-matrix.json}"
REPORT_DIR="$(dirname "$REPORT_PATH")"
mkdir -p "$REPORT_DIR"
RECORDS_DIR="$(mktemp -d "$ROOT_DIR/output/playwright/ui-browser-matrix.XXXXXX")"
RECORDS_PATH="$RECORDS_DIR/records.jsonl"
touch "$RECORDS_PATH"

export CODEX_HOME="${CODEX_HOME:-$HOME/.codex}"
PWCLI="${PWCLI:-$CODEX_HOME/skills/playwright/scripts/playwright_cli.sh}"

if ! command -v npx >/dev/null 2>&1; then
  echo "npx is required to run the Playwright CLI." >&2
  exit 2
fi
if [[ ! -x "$PWCLI" ]]; then
  echo "Playwright CLI wrapper not found: $PWCLI" >&2
  exit 2
fi

cleanup() {
  "$PWCLI" --session "$SESSION" close >/dev/null 2>&1 || true
  rm -rf "$RECORDS_DIR"
}
trap cleanup EXIT

run_json() {
  "$PWCLI" --session "$SESSION" --json "$@"
}

run_eval() {
  local response result
  response="$(run_json eval "$1")"
  result="$(python3 -c '
import json
import sys

envelope = json.load(sys.stdin)
value = envelope.get("result")
if isinstance(value, str):
    value = json.loads(value)
print(json.dumps(value, separators=(",", ":")))
' <<<"$response")"
  printf '%s' "$result"
}

wait_for_render() {
  run_json run-code 'async () => { await page.waitForTimeout(500); }' >/dev/null
}

inventory_expression='({
  path: location.pathname,
  headings: [...document.querySelectorAll("h1,h2")].map(node => node.textContent?.trim()).filter(Boolean),
  unnamedControls: [...document.querySelectorAll("button,a,input:not([type=hidden]),select,textarea")]
    .filter(node => !node.matches("[aria-hidden=\"true\"]"))
    .filter(node => { const style = getComputedStyle(node); const box = node.getBoundingClientRect(); return style.display !== "none" && style.visibility !== "hidden" && box.width > 0 && box.height > 0; })
    .filter(node => !(node.getAttribute("aria-label") || node.textContent?.trim() || node.getAttribute("placeholder") || node.labels?.[0]?.textContent?.trim())).length,
  disabledControls: [...document.querySelectorAll("button,input,select,textarea")].filter(node => node.disabled).length,
  overflow: document.documentElement.scrollWidth > window.innerWidth,
  viewport: { width: window.innerWidth, height: window.innerHeight }
})'

route_specs=(
  "/|Operations Overview"
  "/connectors|Connector Readiness"
  "/knowledge|Knowledge"
  "/workflows|Workflows"
  "/workflow-designer|Workflow Designer"
  "/templates|Template Gallery"
  "/consultant|Consultant blueprints"
  "/collectors|Collectors"
  "/reports|Hardening posture"
  "/audit|Audit"
  "/scheduled-jobs|Scheduled Jobs"
  "/founder|Prepare your Launch Passport upload"
  "/tickets|HaloPSA Tickets"
  "/approvals|Approval Queue"
  "/analytics|Analytics"
  "/agents|Agents"
  "/technician-chat|Technician Chat"
  "/backfills|Agent Backfills"
  "/executions|Execution History"
  "/settings|Admin Settings"
  "/end-user|How can we help?"
)

first_route=1
for route_spec in "${route_specs[@]}"; do
  IFS='|' read -r route expected_heading <<<"$route_spec"
  if [[ "$first_route" == 1 ]]; then
    run_json open "${UI_URL%/}${route}" --browser "$BROWSER" >/dev/null
    if [[ -n "${WAIT_BROWSER_TOKEN:-}" ]]; then
      run_json localstorage-set wait-local-agent-api-token "$WAIT_BROWSER_TOKEN" >/dev/null
      run_json reload >/dev/null
    fi
    first_route=0
  else
    run_json goto "${UI_URL%/}${route}" >/dev/null
  fi
  wait_for_render
  inventory="$(run_eval "$inventory_expression")"
  python3 - "$route" "$expected_heading" "$inventory" >>"$RECORDS_PATH" <<'PY'
import json
import sys

route, expected, payload = sys.argv[1:]
inventory = json.loads(payload)
print(json.dumps({"kind": "route", "route": route, "expected_heading": expected, "inventory": inventory}))
PY
done

run_json goto "${UI_URL%/}/" >/dev/null
wait_for_render
permission_state="$(run_eval '({ body: document.body.innerText, permissionMessage: document.body.innerText.includes("You do not have permission"), accessUnavailable: document.body.innerText.toLowerCase().includes("access unavailable") })')"
printf '%s\n' "$(python3 - "$permission_state" <<'PY'
import json
import sys

print(json.dumps({"kind": "permission", "result": json.loads(sys.argv[1])}))
PY
)" >>"$RECORDS_PATH"

# Keyboard smoke: a fresh route must move focus to an exposed interactive
# control rather than leaving focus on the document body.
run_json goto "${UI_URL%/}/" >/dev/null
wait_for_render
run_json run-code 'async () => { await page.keyboard.press("Tab"); }' >/dev/null
focus="$(run_eval '({ tag: document.activeElement?.tagName ?? "", name: document.activeElement?.getAttribute("aria-label") || document.activeElement?.textContent?.trim() || document.activeElement?.getAttribute("placeholder") || "", isBody: document.activeElement === document.body })')"
printf '%s\n' "$(python3 - "$focus" <<'PY'
import json
import sys

print(json.dumps({"kind": "keyboard", "focus": json.loads(sys.argv[1])}))
PY
)" >>"$RECORDS_PATH"

# Responsive replay focuses the canonical Consultant surface because it
# contains the broadest bounded form/control set in the dashboard.
run_json resize 390 844 >/dev/null
run_json goto "${UI_URL%/}/consultant" >/dev/null
wait_for_render
mobile="$(run_eval "$inventory_expression")"
printf '%s\n' "$(python3 - "$mobile" <<'PY'
import json
import sys

print(json.dumps({"kind": "responsive", "route": "/consultant", "inventory": json.loads(sys.argv[1])}))
PY
)" >>"$RECORDS_PATH"

# Simulate an appliance-side failure through the browser's route mock. This
# verifies that the UI surfaces a handled error instead of provider success.
run_json resize 1280 720 >/dev/null
run_json goto "${UI_URL%/}/connectors" >/dev/null
wait_for_render
run_json route '**/connectors' --status 503 --body '{"detail":"browser-matrix-fixture"}' --content-type 'application/json' >/dev/null
run_json run-code 'async () => { await page.getByRole("button", { name: "Refresh", exact: true }).click(); await page.waitForTimeout(500); }' >/dev/null
provider_error="$(run_eval '({ alerts: [...document.querySelectorAll("[role=alert]")].map(node => node.textContent?.trim()).filter(Boolean), statuses: [...document.querySelectorAll("[role=status]")].map(node => node.textContent?.trim()).filter(Boolean), body: document.body.innerText })')"
run_json unroute '**/connectors' >/dev/null
printf '%s\n' "$(python3 - "$provider_error" <<'PY'
import json
import sys

payload = json.loads(sys.argv[1])
print(json.dumps({"kind": "provider_error", "route": "/connectors", "result": payload}))
PY
)" >>"$RECORDS_PATH"

# Simulate loss of connectivity after the page is loaded. The dashboard must
# retain a visible appliance error and must not present a successful operation.
run_json network-state-set offline >/dev/null
run_json route '**/auth/role' --status 503 --body '{"detail":"offline-fixture"}' --content-type 'application/json' >/dev/null
run_json run-code 'async () => { await page.getByRole("button", { name: "Refresh", exact: true }).click(); await page.waitForTimeout(1200); }' >/dev/null
offline="$(run_eval '({ alerts: [...document.querySelectorAll("[role=alert]")].map(node => node.textContent?.trim()).filter(Boolean), statuses: [...document.querySelectorAll("[role=status]")].map(node => node.textContent?.trim()).filter(Boolean), body: document.body.innerText })')"
run_json unroute '**/auth/role' >/dev/null
run_json network-state-set online >/dev/null
printf '%s\n' "$(python3 - "$offline" <<'PY'
import json
import sys

payload = json.loads(sys.argv[1])
print(json.dumps({"kind": "offline", "route": "/connectors", "result": payload}))
PY
)" >>"$RECORDS_PATH"

python3 - "$RECORDS_PATH" "$REPORT_PATH" "$UI_URL" "$BROWSER" "${WAIT_BROWSER_EXPECT_PERMISSION:-false}" <<'PY'
import json
import pathlib
import sys

records_path, report_path, ui_url, browser, expect_permission = sys.argv[1:]
records = [json.loads(line) for line in pathlib.Path(records_path).read_text().splitlines() if line]
failures = []
routes = [record for record in records if record["kind"] == "route"]
if len(routes) != 21:
    failures.append(f"expected 21 route records, got {len(routes)}")
for record in routes:
    inventory = record["inventory"]
    if expect_permission.lower() != "true" and record["expected_heading"] not in inventory["headings"]:
        failures.append(f"{record['route']}: missing heading {record['expected_heading']!r}")
    if inventory["unnamedControls"]:
        failures.append(f"{record['route']}: {inventory['unnamedControls']} unnamed visible controls")
    if inventory["overflow"]:
        failures.append(f"{record['route']}: horizontal overflow at {inventory['viewport']}")

keyboard = next(record for record in records if record["kind"] == "keyboard")["focus"]
if keyboard["isBody"] or not keyboard["name"]:
    failures.append("keyboard smoke did not focus a named interactive element")

responsive = next(record for record in records if record["kind"] == "responsive")["inventory"]
if responsive["overflow"] or responsive["viewport"]["width"] != 390:
    failures.append("consultant responsive replay overflowed or used the wrong viewport")

for kind, label in (("provider_error", "provider error"), ("offline", "offline")):
    result = next(record for record in records if record["kind"] == kind)["result"]
    visible = " ".join(result["alerts"] + result["statuses"])
    if not visible:
        failures.append(f"{label}: no visible status or alert")

permission_records = []
if expect_permission.lower() == "true":
    permission = next(record for record in records if record["kind"] == "permission")["result"]
    permission_records = [permission]
    if not permission["permissionMessage"] or not permission["accessUnavailable"]:
        failures.append("permission replay did not expose both the permission message and access-unavailable state")

report = {
    "ui_url": ui_url,
    "browser": browser,
    "route_count": len(routes),
    "records": records,
    "permission_replay_requested": expect_permission.lower() == "true",
    "permission_replay_records": permission_records,
    "notes": [
        "provider_error uses a controlled 503 route fixture",
        "offline uses the browser offline state plus a controlled unavailable auth route",
        "provider credentials and deployment are not exercised by this matrix",
    ],
    "failures": failures,
}
pathlib.Path(report_path).write_text(json.dumps(report, indent=2) + "\n")
if failures:
    for failure in failures:
        print(f"FAIL: {failure}", file=sys.stderr)
    raise SystemExit(1)
print(f"UI browser matrix passed: {len(routes)} routes, responsive, keyboard, provider-error, and offline checks.")
print(f"Report: {report_path}")
PY
