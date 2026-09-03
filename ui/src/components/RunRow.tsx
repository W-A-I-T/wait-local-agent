import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { StatusChip } from "./StatusChip";

export type RunRowProps = {
  title: string;
  kind: string;
  clientId?: string | null;
  origin?: ReactNode;
  status?: string | null;
  timestamp?: string | null;
  href?: string;
  onOpen?: () => void;
};

const KIND_LABELS: Record<string, string> = {
  workflow: "Workflow",
  playbook: "Playbook",
  agent: "Agent",
  smart_action: "Smart action",
  "smart-action": "Smart action",
  scheduled: "Scheduled",
  backfill: "Backfill",
  execution: "Execution",
  collector: "Collector"
};

export function runKindLabel(kind: string): string {
  const normalized = kind.trim().toLowerCase();
  return KIND_LABELS[normalized] ?? humanizeKind(normalized);
}

export function RunRow({ title, kind, clientId, origin, status, timestamp, href, onOpen }: RunRowProps) {
  return (
    <article className="table-row run-row">
      <div className="run-row-main">
        <strong>{title}</strong>
        <span className="run-row-kind">{runKindLabel(kind)}</span>
        {origin ? <span>Origin: {origin}</span> : null}
      </div>
      <div className="run-row-context">
        <StatusChip status={status} />
        <span>Client: {clientId || "All clients"}</span>
      </div>
      <div className="run-row-time">
        <small>{timestamp || "Timestamp unavailable"}</small>
        {href ? <Link to={href} aria-label="Open">Open</Link> : <button type="button" onClick={onOpen} aria-label="Open">Open</button>}
      </div>
    </article>
  );
}

function humanizeKind(kind: string): string {
  if (!kind) return "Run";
  return kind.replace(/[_-]+/g, " ").replace(/\b\w/g, (character) => character.toUpperCase());
}
