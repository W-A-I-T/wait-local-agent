import {
  Activity,
  BookOpenText,
  CheckCircle2,
  ClipboardList,
  Database,
  Search,
  ShieldCheck
} from "lucide-react";

const tickets = [
  {
    id: "TCK-1001",
    client: "Northwind Dental",
    subject: "User cannot complete MFA after phone replacement",
    classification: "identity-access",
    priority: "High",
    status: "Pending approval",
    source: "MFA Reset Runbook",
    excerpt:
      "Use identity-provider admin tools to verify the requester and require the user to register the new device."
  },
  {
    id: "TCK-1002",
    client: "Contoso Legal",
    subject: "Shared mailbox request for new matter intake",
    classification: "collaboration-change",
    priority: "Medium",
    status: "Draft ready",
    source: "Shared Mailbox Runbook",
    excerpt:
      "Confirm business owner approval, requested mailbox name, required members, and whether send-as permissions are needed."
  }
];

const documents = [
  {
    id: 1,
    title: "MFA Reset Runbook",
    kind: "md",
    chunks: 1,
    path: "examples/sample_docs/mfa-reset.md"
  },
  {
    id: 2,
    title: "Shared Mailbox Runbook",
    kind: "md",
    chunks: 1,
    path: "examples/sample_docs/shared-mailbox.md"
  }
];

const searchResults = [
  {
    title: "Shared Mailbox Runbook",
    path: "examples/sample_docs/shared-mailbox.md",
    excerpt:
      "Confirm business owner approval, requested mailbox name, required members, and whether send-as permissions are needed."
  }
];

const auditEvents = [
  "Ticket TCK-1001 summarized from local runbook context",
  "Approval state pending for identity-access workflow",
  "Deterministic provider active with local inference disabled"
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
          <a href="#knowledge">
            <BookOpenText size={18} aria-hidden="true" />
            Knowledge
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
                <div className="ticket-source">
                  <strong>Cited source</strong>
                  <span>{ticket.source}</span>
                  <p>{ticket.excerpt}</p>
                </div>
              </article>
            ))}
          </div>
        </section>

        <section className="grid">
          <article id="knowledge" className="panel knowledge-panel">
            <div className="panel-heading">
              <h2>Knowledge Index</h2>
              <span>{documents.length} documents</span>
            </div>
            <div className="search-box">
              <Search size={18} aria-hidden="true" />
              <span>mailbox permissions</span>
            </div>
            <div className="document-list">
              {documents.map((document) => (
                <div className="document-row" key={document.id}>
                  <div>
                    <strong>{document.title}</strong>
                    <span>{document.path}</span>
                  </div>
                  <em>
                    {document.kind} / {document.chunks} chunk
                  </em>
                </div>
              ))}
            </div>
            <div className="source-results">
              {searchResults.map((result) => (
                <article key={result.path}>
                  <strong>{result.title}</strong>
                  <span>{result.path}</span>
                  <p>{result.excerpt}</p>
                </article>
              ))}
            </div>
          </article>

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
                <dd>Deterministic default</dd>
              </div>
              <div>
                <dt>Local inference</dt>
                <dd>Disabled until configured</dd>
              </div>
              <div>
                <dt>Local endpoint</dt>
                <dd>OpenAI-compatible when enabled</dd>
              </div>
              <div>
                <dt>Timeout</dt>
                <dd>20 seconds</dd>
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
