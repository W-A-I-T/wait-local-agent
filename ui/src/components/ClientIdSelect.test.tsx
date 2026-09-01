import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { ClientIdSelect } from "./ClientIdSelect";
import type { ClientDirectoryEntry } from "../api/types";

const clients: ClientDirectoryEntry[] = [
  { client_id: "acme", name: "Acme Support", status: "active" },
  { client_id: "globex", name: "Globex IT", status: "active" }
];

describe("ClientIdSelect", () => {
  it("renders client names with client IDs as option values", () => {
    render(<ClientIdSelect value="" onChange={vi.fn()} clients={clients} id="client-id" label="Client workspace" />);

    expect(screen.getByRole("combobox", { name: "Client workspace" })).toHaveValue("");
    expect(screen.getByRole("option", { name: "Acme Support" })).toHaveValue("acme");
    expect(screen.getByRole("option", { name: "Globex IT" })).toHaveValue("globex");
  });

  it("keeps an unmatched current value visible and selected", () => {
    render(<ClientIdSelect value="legacy-client" onChange={vi.fn()} clients={clients} />);

    expect(screen.getByRole("combobox")).toHaveValue("legacy-client");
    expect(screen.getByRole("option", { name: "legacy-client" })).toBeInTheDocument();
  });

  it("omits the empty option for a required selector", () => {
    render(<ClientIdSelect value="" onChange={vi.fn()} clients={clients} required />);

    expect(screen.getByRole("combobox")).toBeRequired();
    expect(screen.queryByRole("option", { name: "Choose a client" })).not.toBeInTheDocument();
  });

  it("round-trips a typed value through the freeform escape hatch", () => {
    const onChange = vi.fn();

    function ControlledSelect() {
      const [value, setValue] = useState("");
      return <ClientIdSelect value={value} onChange={(next) => { onChange(next); setValue(next); }} clients={clients} allowFreeform />;
    }

    render(<ControlledSelect />);

    fireEvent.click(screen.getByRole("button", { name: "Enter a new workspace ID" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Client ID" }), { target: { value: "new-workspace" } });
    fireEvent.click(screen.getByRole("button", { name: "Choose an existing client" }));

    expect(onChange).toHaveBeenLastCalledWith("new-workspace");
    expect(screen.getByRole("combobox")).toHaveValue("new-workspace");
    expect(screen.getByRole("option", { name: "new-workspace" })).toBeInTheDocument();
  });
});
