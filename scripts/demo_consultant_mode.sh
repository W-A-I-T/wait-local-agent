#!/usr/bin/env bash
set -euo pipefail

# This path is local, deterministic, and review-only. It does not call a
# provider, deploy a solution, write Dataverse, or execute an agent.
wait-local-agent microsoft use-cases list --category teams
wait-local-agent microsoft discovery assess examples/consultant/discovery.json
wait-local-agent microsoft power-apps plan examples/consultant/power-apps-plan.json
wait-local-agent microsoft workflow plan examples/consultant/flow-plan.json
wait-local-agent microsoft evaluation run examples/consultant/evaluation.json
wait-local-agent microsoft governance evaluate examples/consultant/governance.json
wait-local-agent microsoft delivery plan examples/consultant/delivery.json
wait-local-agent microsoft solution status
wait-local-agent microsoft monitoring agents
