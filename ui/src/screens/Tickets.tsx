import { FormEvent, useState } from "react";
import { Send } from "lucide-react";
import { defaultFieldText, useDashboard } from "../app/DashboardContext";
import { parseFields } from "../lib/fields";

export function Tickets() {
  const {
    haloTickets,
    selectedTicketId,
    selectTicket,
    actionTypes,
    canWrite,
    busyId,
    createDraft
  } = useDashboard();
  const [manualTicketId, setManualTicketId] = useState("");
  const [actionType, setActionType] = useState(actionTypes[0]);
  const [fieldText, setFieldText] = useState(defaultFieldText);
  const [validationMessage, setValidationMessage] = useState("");
  const targetTicketId = manualTicketId.trim() || selectedTicketId;

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!targetTicketId) {
      setValidationMessage("Choose a HaloPSA ticket or enter a ticket id.");
      return;
    }
    setValidationMessage("");
    void createDraft(targetTicketId, actionType, parseFields(fieldText));
  }

  return (
    <div className="grid">
      <section className="panel">
        <div className="panel-heading">
          <h2>HaloPSA Tickets</h2>
          <span>{haloTickets.length} loaded</span>
        </div>
        <div className="stack-list">
          {haloTickets.map((ticket) => (
            <button
              className={`ticket-select ${selectedTicketId === ticket.id ? "selected" : ""}`}
              key={ticket.id}
              type="button"
              onClick={() => {
                selectTicket(ticket.id);
                setManualTicketId("");
              }}
            >
              <strong>{ticket.id}</strong>
              <span>{ticket.summary || "No summary"}</span>
              <em>{ticket.status || "unknown"}</em>
            </button>
          ))}
          {haloTickets.length === 0 ? (
            <p>Live ticket reads are unavailable or returned no tickets.</p>
          ) : null}
        </div>
      </section>

      {canWrite ? (
        <section className="panel">
          <div className="panel-heading">
            <h2>Draft HaloPSA Write</h2>
            <span>approval required</span>
          </div>
          {validationMessage ? <div className="notice danger">{validationMessage}</div> : null}
          <form className="draft-form" onSubmit={handleSubmit}>
            <label>
              Ticket id
              <input
                placeholder="HALO ticket id"
                value={manualTicketId || selectedTicketId}
                onChange={(event) => {
                  setManualTicketId(event.target.value);
                  selectTicket("");
                }}
              />
            </label>
            <label>
              Action
              <select value={actionType} onChange={(event) => setActionType(event.target.value)}>
                {actionTypes.map((action) => (
                  <option key={action} value={action}>{action}</option>
                ))}
              </select>
            </label>
            <label>
              Fields
              <textarea value={fieldText} onChange={(event) => setFieldText(event.target.value)} rows={5} />
            </label>
            <button disabled={!targetTicketId || busyId === "draft"} type="submit">
              <Send size={17} aria-hidden="true" />
              Create Draft
            </button>
          </form>
        </section>
      ) : null}
    </div>
  );
}
