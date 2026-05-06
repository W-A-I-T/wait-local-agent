import {
  Activity,
  BookOpenText,
  CheckCircle2,
  ClipboardCheck,
  ClipboardList,
  Database,
  GitBranch,
  KeyRound,
  Search,
  ServerCog,
  ShieldCheck,
  Workflow
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
      "Verify the requester, reset MFA registration, and require the user to register the new device."
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
      "Confirm business owner approval, requested mailbox name, required members, and send-as scope."
  }
];

const workflowTemplates = [
  ["Ticket Triage", "ticket.created", "No approval"],
  ["Assign Technician", "ticket.unassigned", "Approval required"],
  ["Inactive Ticket Follow-up", "schedule.daily", "Approval required"],
  ["P1 Alert", "ticket.priority_changed", "Approval required"],
  ["Documentation-assisted Response", "ticket.created", "Approval required"]
];

const approvalRequests = [
  {
    id: 1,
    action: "halopsa.add_note",
    ticket: "TCK-1002",
    status: "pending",
    detail: "Internal note draft waiting for technician review"
  },
  {
    id: 2,
    action: "ticket.draft_response",
    ticket: "TCK-1001",
    status: "pending",
    detail: "Client-safe response can be approved with edits"
  }
];

const connectors = [
  ["HaloPSA", "Draft mode", "Safe write drafts before live PSA execution"],
  ["Hudu", "Planned", "Documentation sync after HaloPSA read path"],
  ["RMM", "Planned", "Read-only inventory before approved scripts"],
  ["M365 / Entra", "Planned", "Identity, group, license, and mailbox lookup"]
];

const documents = [
  ["MFA Reset Runbook", "examples/sample_docs/mfa-reset.md", "md / 1 chunk"],
  ["Shared Mailbox Runbook", "examples/sample_docs/shared-mailbox.md", "md / 1 chunk"]
];

const eventHistory = [
  ["workflow.execution", "TCK-1001", "completed", "Classified ticket as identity-access"],
  ["approval.requested", "TCK-1002", "pending", "HaloPSA add-note draft created"],
  ["ticket.summarized", "TCK-1002", "completed", "Summary created from cited local sources"]
];

export function App() {
  return (
    <main className="shell">
      <aside className="sidebar" aria-label="Workspace navigation">
        <div className="brand">
          <ShieldCheck size={28} aria-hidden="true" />
          <div>
            <strong>WAIT Local Agent</strong>
            <span>Local MSP appliance</span>
          </div>
        </div>
        <nav>
          <a className="active" href="#tickets">
            <ClipboardList size={18} aria-hidden="true" />
            Tickets
          </a>
          <a href="#approvals">
            <ClipboardCheck size={18} aria-hidden="true" />
            Approvals
          </a>
          <a href="#workflows">
            <Workflow size={18} aria-hidden="true" />
            Workflows
          </a>
          <a href="#connectors">
            <GitBranch size={18} aria-hidden="true" />
            Connectors
          </a>
          <a href="#events">
            <Activity size={18} aria-hidden="true" />
            Events
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
            <p>Local summaries, source-backed drafts, approval queues, and auditable workflows.</p>
          </div>
          <div className="topbar-actions">
            <div className="status-pill">
              <CheckCircle2 size={18} aria-hidden="true" />
              Safe defaults active
            </div>
            <div className="status-pill secondary">
              <ServerCog size={18} aria-hidden="true" />
              Docker appliance ready
            </div>
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
          <article id="approvals" className="panel">
            <div className="panel-heading">
              <h2>Approval Queue</h2>
              <span>technician-in-the-loop</span>
            </div>
            <div className="stack-list">
              {approvalRequests.map((request) => (
                <div className="approval-row" key={request.id}>
                  <div>
                    <strong>{request.action}</strong>
                    <span>{request.ticket}</span>
                  </div>
                  <p>{request.detail}</p>
                  <em>{request.status}</em>
                </div>
              ))}
            </div>
          </article>

          <article id="workflows" className="panel">
            <div className="panel-heading">
              <h2>Workflow Templates</h2>
              <span>{workflowTemplates.length} starters</span>
            </div>
            <div className="table-list">
              {workflowTemplates.map(([name, trigger, approval]) => (
                <div className="table-row" key={name}>
                  <strong>{name}</strong>
                  <span>{trigger}</span>
                  <em>{approval}</em>
                </div>
              ))}
            </div>
          </article>

          <article id="connectors" className="panel">
            <div className="panel-heading">
              <h2>Connector Readiness</h2>
              <span>HaloPSA first</span>
            </div>
            <div className="stack-list">
              {connectors.map(([name, status, detail]) => (
                <div className="connector-row" key={name}>
                  <div>
                    <strong>{name}</strong>
                    <span>{detail}</span>
                  </div>
                  <em>{status}</em>
                </div>
              ))}
            </div>
          </article>

          <article id="events" className="panel">
            <div className="panel-heading">
              <h2>Event History</h2>
              <span>local state</span>
            </div>
            <div className="event-list">
              {eventHistory.map(([type, subject, status, message]) => (
                <div className="event-row" key={`${type}-${subject}-${message}`}>
                  <span>{type}</span>
                  <strong>{subject}</strong>
                  <em>{status}</em>
                  <p>{message}</p>
                </div>
              ))}
            </div>
          </article>

          <article id="knowledge" className="panel knowledge-panel">
            <div className="panel-heading">
              <h2>Knowledge Index</h2>
              <span>{documents.length} documents</span>
            </div>
            <div className="search-box">
              <Search size={18} aria-hidden="true" />
              <span>mailbox permissions</span>
            </div>
            <div className="table-list">
              {documents.map(([title, path, meta]) => (
                <div className="table-row" key={path}>
                  <strong>{title}</strong>
                  <span>{path}</span>
                  <em>{meta}</em>
                </div>
              ))}
            </div>
          </article>

          <article id="settings" className="panel settings-panel">
            <div className="panel-heading">
              <h2>Provider And Secrets</h2>
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
                <dt>HaloPSA secrets</dt>
                <dd>
                  <KeyRound size={15} aria-hidden="true" /> Stored as local environment values
                </dd>
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
