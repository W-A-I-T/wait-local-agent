import { useState } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { CollectorConfigField } from "../../api/types";
import { SchemaForm, validateRequiredFields, type SchemaFormValue } from "../SchemaForm";

const fields: CollectorConfigField[] = [
  {
    name: "source_name",
    label: "Source name",
    help: "A friendly name for this source.",
    type: "string",
    required: true
  },
  { name: "limit", label: "Maximum items", type: "number" },
  { name: "dry_run", label: "Dry run", type: "boolean" },
  {
    name: "mode",
    label: "Mode",
    type: "enum",
    options: ["quick", { value: "full", label: "Full scan" }]
  },
  { name: "paths", label: "Paths", type: "array", items: { type: "string" } },
  { name: "api_credential", label: "API credential", type: "secret_ref", help: "Pick a saved credential." },
  { name: "custom_blob", label: "Custom blob", type: "matrix" }
];

describe("SchemaForm", () => {
  it("renders every supported field type from the manifest", () => {
    renderHarness();

    expect(screen.getByLabelText("Source name")).toHaveAttribute("type", "text");
    expect(screen.getByText("A friendly name for this source.")).toBeInTheDocument();
    expect(screen.getByLabelText("Maximum items")).toHaveAttribute("type", "number");
    expect(screen.getByRole("checkbox", { name: "Dry run" })).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Mode" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add another" })).toBeInTheDocument();

    const secret = screen.getByLabelText("API credential");
    expect(secret).toHaveAttribute("type", "password");
    expect(secret).toHaveAttribute("autocomplete", "off");
    expect(screen.getByText(/The secret itself is never shown/)).toBeInTheDocument();
  });

  it("supports repeatable inputs for array fields", () => {
    renderHarness();

    fireEvent.click(screen.getByRole("button", { name: "Add another" }));
    fireEvent.click(screen.getByRole("button", { name: "Add another" }));

    fireEvent.change(screen.getByLabelText("Paths 1"), { target: { value: "/var" } });
    fireEvent.change(screen.getByLabelText("Paths 2"), { target: { value: "/etc" } });
    expect(screen.getByTestId("value")).toHaveTextContent('"paths":["/var","/etc"]');

    fireEvent.click(screen.getByRole("button", { name: "Remove Paths 1" }));
    expect(screen.getByTestId("value")).toHaveTextContent('"paths":["/etc"]');
  });

  it("flags missing required fields", () => {
    expect(validateRequiredFields(fields, {})).toEqual({ source_name: "Source name is required." });
    expect(validateRequiredFields(fields, { source_name: "" })).toEqual({
      source_name: "Source name is required."
    });
    expect(validateRequiredFields(fields, { source_name: "demo" })).toEqual({});
  });

  it("shows inline messages for missing required fields", () => {
    render(
      <SchemaForm
        fields={fields}
        value={{}}
        onChange={() => undefined}
        errors={{ source_name: "Source name is required." }}
      />
    );

    expect(screen.getByText("Source name is required.")).toBeInTheDocument();
  });

  it("round-trips values through the Advanced (JSON) toggle", () => {
    renderHarness();

    fireEvent.change(screen.getByLabelText("Source name"), { target: { value: "demo" } });
    fireEvent.click(screen.getByRole("button", { name: "Advanced (JSON)" }));

    const json = screen.getByLabelText("Settings JSON");
    expect((json as HTMLTextAreaElement).value).toContain('"source_name": "demo"');

    fireEvent.change(json, { target: { value: '{"source_name": "edited", "limit": 5}' } });
    fireEvent.click(screen.getByRole("button", { name: "Back to form" }));

    expect(screen.getByLabelText("Source name")).toHaveValue("edited");
    expect(screen.getByLabelText("Maximum items")).toHaveValue(5);
  });

  it("keeps form values when the JSON draft is invalid", () => {
    renderHarness({ initial: { source_name: "demo" } });

    fireEvent.click(screen.getByRole("button", { name: "Advanced (JSON)" }));
    fireEvent.change(screen.getByLabelText("Settings JSON"), { target: { value: "{not json" } });

    expect(screen.getByText(/not complete yet/)).toBeInTheDocument();
    expect(screen.getByTestId("value")).toHaveTextContent('"source_name":"demo"');
  });

  it("reports non-object JSON drafts as invalid", () => {
    const validity = vi.fn();
    render(
      <SchemaForm
        fields={fields}
        value={{ source_name: "demo" }}
        onChange={() => undefined}
        onJsonValidityChange={validity}
      />
    );

    fireEvent.click(screen.getByRole("button", { name: "Advanced (JSON)" }));
    fireEvent.change(screen.getByLabelText("Settings JSON"), { target: { value: "[]" } });

    expect(screen.getByText("Settings must be a JSON object.")).toBeInTheDocument();
    expect(validity).toHaveBeenLastCalledWith(false);
  });

  it("falls back to a per-field JSON input for unknown schema nodes", () => {
    renderHarness();

    const fallback = screen.getByLabelText("Custom blob");
    expect(fallback.tagName).toBe("TEXTAREA");
    expect(screen.getByText(/edited as JSON/)).toBeInTheDocument();
    expect(screen.getByLabelText("Source name").tagName).toBe("INPUT");

    fireEvent.change(fallback, { target: { value: '{"depth": 2}' } });
    expect(screen.getByTestId("value")).toHaveTextContent('"custom_blob":{"depth":2}');
  });

  it("supports multi-character secret_ref input as a normal controlled field", () => {
    const secret = "vault-secret-name";
    renderHarness();
    const field = screen.getByLabelText("API credential");
    fireEvent.change(field, { target: { value: secret } });

    expect(field).toHaveValue(secret);
    expect(screen.getByTestId("value")).toHaveTextContent(`"api_credential":"${secret}"`);
    fireEvent.click(screen.getByRole("button", { name: "Advanced (JSON)" }));
    expect((screen.getByLabelText("Settings JSON") as HTMLTextAreaElement).value).not.toContain(`"api_credential":"${secret}"`);
  });

  it("keeps unsupported array shapes lossless through per-field JSON", () => {
    const unsupportedArrayFields: CollectorConfigField[] = [
      { name: "numbers", label: "Numbers", type: "array", items: { type: "number" } },
      { name: "records", label: "Records", type: "array", items: { type: "object" } }
    ];
    renderHarness({
      fields: unsupportedArrayFields,
      initial: { numbers: [1, 2], records: [{ name: "first", enabled: true }] }
    });

    const numbers = screen.getByLabelText("Numbers");
    const records = screen.getByLabelText("Records");
    expect(numbers.tagName).toBe("TEXTAREA");
    expect(records.tagName).toBe("TEXTAREA");

    fireEvent.change(numbers, { target: { value: "[1, 2, 3]" } });
    fireEvent.change(records, { target: { value: '[{"name":"second","enabled":false}]' } });
    expect(screen.getByTestId("value")).toHaveTextContent('"numbers":[1,2,3]');
    expect(screen.getByTestId("value")).toHaveTextContent('"records":[{"name":"second","enabled":false}]');
  });
});

function renderHarness({ initial = {}, fields: fieldsForHarness = fields }: { initial?: SchemaFormValue; fields?: CollectorConfigField[] } = {}) {
  function Harness() {
    const [value, setValue] = useState<SchemaFormValue>(initial);
    return (
      <div>
        <SchemaForm fields={fieldsForHarness} value={value} onChange={setValue} />
        <output data-testid="value">{JSON.stringify(value)}</output>
      </div>
    );
  }
  return render(<Harness />);
}
