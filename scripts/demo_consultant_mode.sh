#!/usr/bin/env bash
set -euo pipefail

# This path is local, deterministic, and review-only. It does not call a
# provider, deploy a solution, write Dataverse, or execute an agent.
if command -v wait-local-agent >/dev/null 2>&1; then
  WAIT_LOCAL_AGENT=(wait-local-agent)
elif command -v uv >/dev/null 2>&1; then
  WAIT_LOCAL_AGENT=(uv run wait-local-agent)
else
  echo "wait-local-agent or uv is required to run the consultant demo" >&2
  exit 127
fi

"${WAIT_LOCAL_AGENT[@]}" microsoft use-cases list --category teams
"${WAIT_LOCAL_AGENT[@]}" microsoft discovery assess examples/consultant/discovery.json
"${WAIT_LOCAL_AGENT[@]}" microsoft power-apps plan examples/consultant/power-apps-plan.json
"${WAIT_LOCAL_AGENT[@]}" microsoft power-apps build examples/consultant/power-apps-build.json
"${WAIT_LOCAL_AGENT[@]}" microsoft workflow plan examples/consultant/flow-plan.json
"${WAIT_LOCAL_AGENT[@]}" microsoft copilot-studio plan examples/consultant/copilot-studio-plan.json
"${WAIT_LOCAL_AGENT[@]}" microsoft connector package examples/consultant/connector-openapi.json onboarding-review
"${WAIT_LOCAL_AGENT[@]}" microsoft solution deployment-plan examples/consultant/deployment.json
"${WAIT_LOCAL_AGENT[@]}" microsoft evaluation run examples/consultant/evaluation.json
"${WAIT_LOCAL_AGENT[@]}" microsoft governance evaluate examples/consultant/governance.json
"${WAIT_LOCAL_AGENT[@]}" microsoft delivery plan examples/consultant/delivery.json
"${WAIT_LOCAL_AGENT[@]}" microsoft solution status
"${WAIT_LOCAL_AGENT[@]}" microsoft monitoring agents
