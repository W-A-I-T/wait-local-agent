import { Activity, CheckCircle2, ClipboardList, Database, ShieldCheck } from "lucide-react";

const tickets = [
  {
    id: "TCK-1001",
    client: "Northwind Dental",
    subject: "User cannot complete MFA after phone replacement",
    classification: "identity-access",
    priority: "High",
    status: "Pending approval"
  },
  {
    id: "TCK-1002",
    client: "Contoso Legal",
    subject: "Shared mailbox request for new matter intake",
    classification: "collaboration-change",
    priority: "Medium",
    status: "Draft ready"
  }
];

const auditEvents = [
  "Ticket TCK-1001 summarized from local runbook context",
  "Approval state pending for identity-access workflow",
  "Provider profile loaded for local endpoint"
];

export function App() {
  return (
    <main className="shell">
      <aside className="sidebar" aria-label="Workspace navigation">
        <div className="brand">
          <ShieldCheck size={28} aria-hidden="true" />
          <div>
            <strong>WAIT Local Agent</strong>
            <span>MSP workspace</span>
          </div>
        </div>
        <nav>
          <a className="active" href="#tickets">
            <ClipboardList size={18} aria-hidden="true" />
            Tickets
          </a>
          <a href="#audit">
            <Activity size={18} aria-hidden="true" />
            Audit
          </a>
          <a href="#settings">
            <Database size={18} aria-hidden="true" />
            Providers
          </a>
        </nav>
      </aside>

      <section className="workspace">
        <header className="topbar">
          <div>
            <h1>Ticket Intelligence</h1>
            <p>Local summaries, source-backed drafts, and approval-first workflow control.</p>
          </div>
          <div className="status-pill">
            <CheckCircle2 size={18} aria-hidden="true" />
            Safe defaults active
          </div>
        </header>

        <section id="tickets" className="panel">
          <div className="panel-heading">
            <h2>Service Desk Queue</h2>
            <span>{tickets.length} sample tickets</span>
          </div>
          <div className="ticket-list">
            {tickets.map((ticket) => (
              <article className="ticket-card" key={ticket.id}>
                <div>
                  <span className="ticket-id">{ticket.id}</span>
                  <h3>{ticket.subject}</h3>
                  <p>{ticket.client}</p>
                </div>
                <div className="ticket-meta">
                  <span>{ticket.classification}</span>
                  <strong>{ticket.priority}</strong>
                  <em>{ticket.status}</em>
                </div>
              </article>
            ))}
          </div>
        </section>

        <section className="grid">
          <article id="audit" className="panel">
            <div className="panel-heading">
              <h2>Audit Log</h2>
              <span>local state</span>
            </div>
            <ul className="audit-list">
              {auditEvents.map((event) => (
                <li key={event}>{event}</li>
              ))}
            </ul>
          </article>

          <article id="settings" className="panel">
            <div className="panel-heading">
              <h2>Provider Profile</h2>
              <span>local only</span>
            </div>
            <dl className="settings-list">
              <div>
                <dt>Model runtime</dt>
                <dd>Ollama-compatible endpoint</dd>
              </div>
              <div>
                <dt>Vector backend</dt>
                <dd>SQLite scaffold, Qdrant or pgvector later</dd>
              </div>
              <div>
                <dt>Cloud fallback</dt>
                <dd>Disabled until configured</dd>
              </div>
            </dl>
          </article>
        </section>
      </section>
    </main>
  );
}

