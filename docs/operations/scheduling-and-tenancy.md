# Scheduling and Tenancy

Workflow templates, bounded agents, and deterministic reports can be scheduled
with UTC cron, interval, or future one-time triggers. The scheduler persists
jobs in SQLite and supports pause, resume, tenant-scoped reschedule, delete,
and auditable history.

The scheduler is an in-process service and must run in exactly one server
process for a given SQLite store. The default `wait-local-agent serve` command
and the container command satisfy this requirement. Do not run multiple web
workers while scheduling is enabled: set `WAIT_SCHEDULER_ENABLED=false` before
using `WEB_CONCURRENCY` or `UVICORN_WORKERS` greater than one. This disables
scheduled execution while leaving the API available; connector polling is the
only scheduled job with a cross-process lease today.

Persisted jobs use one in-flight instance, `coalesce=True`, and a 300-second
misfire grace period. A restart can therefore accept a bounded delayed run
without replaying a backlog or overlapping the same job.

```bash
wait-local-agent workflows templates
wait-local-agent reports schedule qbr --cron "0 9 * * *" --client-id acme --period-days 90
```

API schedules use `/scheduled-jobs`; use `template_id` for workflow schedules
or `agent_id` plus `entity_id` for a scheduled agent. `params.input` carries
bounded, validated operator inputs. An agent's optional execution window is
evaluated in its configured IANA timezone before a run is created.

Stored ticket, approval, audit, workflow, knowledge, collector, and scheduled-job
views resolve the caller's `ClientScope` before applying a `client_id` filter.
Non-demo principals cannot widen that scope by omitting or changing the query
parameter. A global `msp_admin` must explicitly request all-client list access;
detail and mutation calls remain client-specific. Connector provider IDs and
credentials must be configured locally; they are not accepted as authorization
inputs. Invalid inputs produce an explicit failed schedule/run, not a
successful-looking result.
