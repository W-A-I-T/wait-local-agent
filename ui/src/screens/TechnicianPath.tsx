import { Link } from "react-router-dom";

const STEPS = [
  { label: "Ticket", detail: "Open the customer request and review its current facts.", to: "/tickets" },
  { label: "Triage", detail: "Use Technician Chat to prepare a bounded response or action plan.", to: "/technician-chat" },
  { label: "Plan", detail: "Review the proposed steps and confirm the intended scope.", to: "/technician-chat" },
  { label: "Approval", detail: "Approve or reject any action that can change a connected system.", to: "/approvals" },
  { label: "Evidence", detail: "Confirm the outcome in the local audit history.", to: "/audit" }
] as const;

export function TechnicianPath() {
  return (
    <section className="panel">
      <div className="panel-heading">
        <div>
          <h2>Technician path</h2>
          <p className="screen-note">A short route from customer request to reviewable local evidence.</p>
        </div>
        <span>5 steps</span>
      </div>
      <ol className="table-list">
        {STEPS.map((step) => (
          <li className="table-row" key={step.label}>
            <div><strong>{step.label}</strong><span>{step.detail}</span></div>
            <Link className="icon-button" to={step.to}>Open</Link>
          </li>
        ))}
      </ol>
    </section>
  );
}
