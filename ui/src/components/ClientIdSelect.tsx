import { useId, useState } from "react";
import type { ClientDirectoryEntry } from "../api/types";

export type ClientIdSelectProps = {
  value: string;
  onChange: (value: string) => void;
  clients: ClientDirectoryEntry[];
  required?: boolean;
  allowFreeform?: boolean;
  label?: string;
  id?: string;
};

export function ClientIdSelect({
  value,
  onChange,
  clients,
  required = false,
  allowFreeform = false,
  label = "Client ID",
  id
}: ClientIdSelectProps) {
  const generatedId = useId();
  const controlId = id ?? generatedId;
  const [freeform, setFreeform] = useState(false);
  const currentValueIsKnown = value === "" || clients.some((client) => client.client_id === value);

  return (
    <div className="client-id-select">
      <label htmlFor={controlId}>{label}</label>
      {freeform ? (
        <input
          id={controlId}
          type="text"
          value={value}
          required={required}
          aria-required={required || undefined}
          onChange={(event) => onChange(event.target.value)}
          placeholder="Workspace ID"
        />
      ) : (
        <select
          id={controlId}
          value={value}
          required={required}
          aria-required={required || undefined}
          onChange={(event) => onChange(event.target.value)}
        >
          <option value="" disabled={required} hidden={required}>Choose a client</option>
          {!currentValueIsKnown ? <option value={value}>{value}</option> : null}
          {clients.map((client) => (
            <option key={client.client_id} value={client.client_id}>
              {client.name}
            </option>
          ))}
        </select>
      )}
      {allowFreeform ? (
        <button
          type="button"
          className="inline-link client-id-select-toggle"
          onClick={() => setFreeform((current) => !current)}
        >
          {freeform ? "Choose an existing client" : "Enter a new workspace ID"}
        </button>
      ) : null}
    </div>
  );
}
