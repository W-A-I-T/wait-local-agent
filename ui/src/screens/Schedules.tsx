import { useCallback, useEffect, useMemo, useState } from "react";
import { apiFetch } from "../api/client";
import type { ScheduledJob } from "../api/types";
import { StatusChip } from "../components/StatusChip";

type StatusFilter = "all" | "active" | "paused";
type TargetFilter = "all" | "workflow" | "playbook" | "graph_sync";
type TargetKind = "workflow" | "playbook" | "graph_sync" | "other";

export function Schedules() {
  const [jobs, setJobs] = useState<ScheduledJob[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [targetFilter, setTargetFilter] = useState<TargetFilter>("all");
  const [expandedJobId, setExpandedJobId] = useState<number | null>(null);

  const loadSchedules = useCallback(async () => {
    setLoading(true);
    setError("");
    setExpandedJobId(null);
    try {
      const result = await apiFetch<ScheduledJob[]>("/scheduled-jobs");
      if (!Array.isArray(result)) {
        throw new Error("The appliance returned invalid Schedules data.");
      }
      setJobs(result);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Unable to load Schedules.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadSchedules();
  }, [loadSchedules]);

  const visibleJobs = useMemo(() => jobs.filter((job) => {
    const statusMatches = statusFilter === "all" || (statusFilter === "paused" ? job.paused : !job.paused);
    const targetMatches = targetFilter === "all" || targetKind(job) === targetFilter;
    return statusMatches && targetMatches;
  }), [jobs, statusFilter, targetFilter]);

  return (
    <div className="screen-stack">
      <section className="panel schedules-hero">
        <div>
          <p className="eyebrow">Automation</p>
          <h2>Schedules</h2>
          <p className="screen-note">Review workflow, playbook, and environment schedules. This screen is read-only.</p>
        </div>
        <button className="icon-button" type="button" onClick={() => void loadSchedules()} disabled={loading}>
          {loading ? "Loading…" : "Refresh"}
        </button>
      </section>

      {error ? (
        <div className="notice danger" role="alert">
          <span>{error}</span>
          <button className="secondary-button" type="button" onClick={() => void loadSchedules()} disabled={loading}>Try again</button>
        </div>
      ) : null}

      {loading ? (
        <section className="panel" aria-busy="true">
          <p className="screen-note">Loading Schedules…</p>
        </section>
      ) : (
        <section className="panel" aria-labelledby="schedules-list-heading">
          <div className="panel-heading">
            <div>
              <h2 id="schedules-list-heading">Scheduled jobs</h2>
              <span>{visibleJobs.length} of {jobs.length} job{jobs.length === 1 ? "" : "s"}</span>
            </div>
            <span>Viewer access</span>
          </div>

          <div className="schedules-filters" aria-label="Schedule filters">
            <label>
              Status
              <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value as StatusFilter)}>
                <option value="all">All statuses</option>
                <option value="active">Active</option>
                <option value="paused">Paused</option>
              </select>
            </label>
            <label>
              Target type
              <select value={targetFilter} onChange={(event) => setTargetFilter(event.target.value as TargetFilter)}>
                <option value="all">All targets</option>
                <option value="workflow">Workflows</option>
                <option value="playbook">Playbooks</option>
                <option value="graph_sync">Environment sync</option>
              </select>
            </label>
          </div>

          {jobs.length === 0 ? (
            <div className="empty-state">
              <h3>No schedules are visible.</h3>
              <p>The appliance has not returned any scheduled jobs for this scope.</p>
            </div>
          ) : visibleJobs.length === 0 ? (
            <div className="empty-state schedules-filter-empty">
              <h3>No schedules match these filters.</h3>
              <p>Try a different status or target type.</p>
            </div>
          ) : (
            <div className="schedules-table-wrap">
              <table className="schedules-table">
                <thead>
                  <tr>
                    <th scope="col">Job ID</th>
                    <th scope="col">Target</th>
                    <th scope="col">Cadence</th>
                    <th scope="col">Next run</th>
                    <th scope="col">Status</th>
                    <th scope="col">Last run</th>
                  </tr>
                </thead>
                <tbody>
                  {visibleJobs.map((job) => {
                    const expanded = expandedJobId === job.id;
                    return (
                      <ScheduleRows
                        key={job.id}
                        job={job}
                        expanded={expanded}
                        onToggle={() => setExpandedJobId(expanded ? null : job.id)}
                      />
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </section>
      )}
    </div>
  );
}

function ScheduleRows({ job, expanded, onToggle }: { job: ScheduledJob; expanded: boolean; onToggle: () => void }) {
  const kind = targetKind(job);
  return (
    <>
      <tr>
        <td>
          <button className="schedules-row-trigger" type="button" onClick={onToggle} aria-expanded={expanded} aria-label={`${expanded ? "Hide" : "Show"} details for scheduled job ${job.id}`}>
            <strong>{job.id}</strong>
            <span>{expanded ? "Hide details" : "Show details"}</span>
          </button>
        </td>
        <td>
          <strong>{targetLabel(kind)}</strong>
          <code>{targetId(job, kind)}</code>
        </td>
        <td>{formatCadence(job)}</td>
        <td>{formatTimestamp(job.next_run_at)}</td>
        <td><StatusChip status={job.paused ? "paused" : "active"} /></td>
        <td>{formatTimestamp(job.last_run)}</td>
      </tr>
      {expanded ? (
        <tr className="schedules-detail-row">
          <td colSpan={6}>
            <ScheduleDetail job={job} kind={kind} />
          </td>
        </tr>
      ) : null}
    </>
  );
}

function ScheduleDetail({ job, kind }: { job: ScheduledJob; kind: TargetKind }) {
  return (
    <div className="schedules-detail">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">Schedule detail</p>
          <h3>Job {job.id}</h3>
        </div>
        <StatusChip status={job.paused ? "paused" : "active"} />
      </div>
      <dl className="schedules-detail-grid">
        <DetailField label="Job ID" value={job.id} />
        <DetailField label="Job kind" value={job.job_kind} />
        <DetailField label="Target type" value={targetLabel(kind)} />
        <DetailField label="Workflow ID" value={job.template_id} />
        <DetailField label="Playbook ID" value={job.playbook_id} />
        <DetailField label="Agent ID" value={job.agent_id} />
        <DetailField label="Entity ID" value={job.entity_id} />
        <DetailField label="Cadence" value={formatCadence(job)} />
        <DetailField label="Cron" value={job.cron} />
        <DetailField label="Schedule type" value={job.schedule_type} />
        <DetailField label="Interval seconds" value={job.interval_seconds} />
        <DetailField label="Run at" value={job.run_at} />
        <DetailField label="Timezone" value={job.timezone} />
        <DetailField label="Next run" value={job.next_run_at} />
        <DetailField label="Last run" value={job.last_run} />
        <DetailField label="Created" value={job.created_at} />
        <DetailField label="Updated" value={job.updated_at} />
        <DetailField label="Client" value={job.client_id} />
        <DetailField label="Paused" value={job.paused ? "Yes" : "No"} />
      </dl>
      <h4>Parameters</h4>
      <pre className="schedules-code"><code>{JSON.stringify(job.params ?? {}, null, 2)}</code></pre>
    </div>
  );
}

function DetailField({ label, value }: { label: string; value: unknown }) {
  return <div><dt>{label}</dt><dd>{formatValue(value)}</dd></div>;
}

function targetKind(job: ScheduledJob): TargetKind {
  if (job.job_kind === "graph_sync") {
    return "graph_sync";
  }
  if (job.job_kind === "playbook" || job.playbook_id) {
    return "playbook";
  }
  if (job.job_kind === "workflow" || job.template_id) {
    return "workflow";
  }
  return "other";
}

function targetLabel(kind: TargetKind): string {
  return kind === "playbook" ? "Playbook" : kind === "workflow" ? "Workflow" : kind === "graph_sync" ? "Environment sync" : "Other";
}

function targetId(job: ScheduledJob, kind: TargetKind): string {
  if (kind === "playbook") {
    return job.playbook_id ?? job.template_id ?? "Not provided";
  }
  if (kind === "workflow") {
    return job.template_id ?? "Not provided";
  }
  if (kind === "graph_sync") {
    return job.client_id ?? job.entity_id ?? "Not provided";
  }
  return job.agent_id ?? job.template_id ?? "Not provided";
}

function formatCadence(job: ScheduledJob): string {
  if (job.schedule_type === "interval") {
    return `Every ${formatDuration(job.interval_seconds)}`;
  }
  if (job.schedule_type === "once") {
    return `Once${job.run_at ? ` at ${job.run_at}` : ""}`;
  }
  return `Cron ${job.cron}`;
}

function formatDuration(seconds?: number | null): string {
  if (!seconds || seconds < 1) {
    return "an unspecified interval";
  }
  if (seconds % 3600 === 0) {
    return `${seconds / 3600} hour${seconds === 3600 ? "" : "s"}`;
  }
  if (seconds % 60 === 0) {
    return `${seconds / 60} minute${seconds === 60 ? "" : "s"}`;
  }
  return `${seconds} seconds`;
}

function formatTimestamp(value?: string | number | null): string {
  return value === undefined || value === null || value === "" ? "Not recorded" : String(value);
}

function formatValue(value: unknown): string {
  if (value === undefined || value === null || value === "") {
    return "Not provided";
  }
  return typeof value === "object" ? JSON.stringify(value) : String(value);
}
