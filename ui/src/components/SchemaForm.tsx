import { useState, type ReactNode } from "react";
import type { CollectorConfigField, CollectorConfigFieldOption } from "../api/types";
import { humanizeName } from "../lib/fields";

export type SchemaFormValue = Record<string, unknown>;

type SchemaFormProps = {
  fields: CollectorConfigField[];
  value: SchemaFormValue;
  onChange: (next: SchemaFormValue) => void;
  errors?: Record<string, string>;
  idPrefix?: string;
};

export function fieldLabel(field: CollectorConfigField): string {
  return field.label ?? humanizeName(field.name);
}

export function defaultsForFields(fields: CollectorConfigField[]): SchemaFormValue {
  const defaults: SchemaFormValue = {};
  for (const field of fields) {
    if (field.default !== undefined && field.default !== null) {
      defaults[field.name] = field.default;
    }
  }
  return defaults;
}

function withoutSecretValues(value: SchemaFormValue, fields: CollectorConfigField[]): SchemaFormValue {
  const secretFields = new Set(fields.filter((field) => field.type === "secret_ref").map((field) => field.name));
  return Object.fromEntries(Object.entries(value).filter(([name]) => !secretFields.has(name)));
}

function preserveSecretValues(
  value: SchemaFormValue,
  next: SchemaFormValue,
  fields: CollectorConfigField[]
): SchemaFormValue {
  const secretFields = new Set(fields.filter((field) => field.type === "secret_ref").map((field) => field.name));
  return {
    ...withoutSecretValues(next, fields),
    ...Object.fromEntries(Object.entries(value).filter(([name]) => secretFields.has(name)))
  };
}

export function validateRequiredFields(
  fields: CollectorConfigField[],
  value: SchemaFormValue
): Record<string, string> {
  const errors: Record<string, string> = {};
  for (const field of fields) {
    if (!field.required) {
      continue;
    }
    const current = value[field.name];
    const missing =
      current === undefined ||
      current === null ||
      current === "" ||
      (Array.isArray(current) && current.every((item) => String(item ?? "").trim() === ""));
    if (missing) {
      errors[field.name] = `${fieldLabel(field)} is required.`;
    }
  }
  return errors;
}

export function SchemaForm({ fields, value, onChange, errors = {}, idPrefix = "schema" }: SchemaFormProps) {
  const [advanced, setAdvanced] = useState(false);
  const [jsonText, setJsonText] = useState("");
  const [jsonError, setJsonError] = useState("");

  function setField(name: string, next: unknown) {
    const updated = { ...value };
    if (next === undefined) {
      delete updated[name];
    } else {
      updated[name] = next;
    }
    onChange(updated);
  }

  function openAdvanced() {
    setJsonText(JSON.stringify(withoutSecretValues(value, fields), null, 2));
    setJsonError("");
    setAdvanced(true);
  }

  function editJson(text: string) {
    setJsonText(text);
    try {
      const parsed = JSON.parse(text) as unknown;
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
        setJsonError("Settings must be a JSON object.");
        return;
      }
      const safeValue = preserveSecretValues(value, parsed as SchemaFormValue, fields);
      setJsonError("");
      setJsonText(JSON.stringify(safeValue, null, 2));
      onChange(safeValue);
    } catch {
      setJsonError("That JSON is not complete yet — keep editing or switch back to the form.");
    }
  }

  return (
    <div className="schema-form">
      <div className="schema-form-toolbar">
        <button type="button" className="icon-button" onClick={() => (advanced ? setAdvanced(false) : openAdvanced())}>
          {advanced ? "Back to form" : "Advanced (JSON)"}
        </button>
      </div>

      {advanced ? (
        <div className="schema-field">
          <label htmlFor={`${idPrefix}-json`}>Settings JSON</label>
          <textarea
            id={`${idPrefix}-json`}
            rows={10}
            value={jsonText}
            onChange={(event) => editJson(event.target.value)}
          />
          {jsonError ? <span className="field-error">{jsonError}</span> : null}
        </div>
      ) : fields.length === 0 ? (
        <p className="screen-note">
          This collector does not describe any settings. You can run it as-is, or open Advanced (JSON)
          if you know it accepts options.
        </p>
      ) : (
        fields.map((field) => (
          <SchemaField
            key={field.name}
            field={field}
            value={value[field.name]}
            error={errors[field.name]}
            idPrefix={idPrefix}
            onChange={(next) => setField(field.name, next)}
          />
        ))
      )}
    </div>
  );
}

type SchemaFieldProps = {
  field: CollectorConfigField;
  value: unknown;
  error?: string;
  idPrefix: string;
  onChange: (next: unknown) => void;
};

function SchemaField({ field, value, error, idPrefix, onChange }: SchemaFieldProps) {
  const id = `${idPrefix}-${field.name}`;
  const label = fieldLabel(field);
  const type = field.type ?? "";
  const heading = (
    <label htmlFor={id}>
      {label}
      {field.required ? <span className="required-marker" aria-hidden="true" /> : null}
    </label>
  );
  const help = field.help ? <span className="field-help">{field.help}</span> : null;
  const errorMessage = error ? <span className="field-error">{error}</span> : null;

  if (type === "boolean") {
    return (
      <div className="schema-field schema-field-boolean">
        <input
          id={id}
          type="checkbox"
          checked={Boolean(value)}
          required={field.required}
          aria-required={field.required || undefined}
          onChange={(event) => onChange(event.target.checked)}
        />
        {heading}
        {help}
        {errorMessage}
      </div>
    );
  }

  if (type === "number") {
    return (
      <div className="schema-field">
        {heading}
        <input
          id={id}
          type="number"
          value={typeof value === "number" ? value : ""}
          required={field.required}
          aria-required={field.required || undefined}
          onChange={(event) => onChange(event.target.value === "" ? undefined : Number(event.target.value))}
        />
        {help}
        {errorMessage}
      </div>
    );
  }

  if (type === "enum") {
    const options = (field.options ?? []).map(normalizeOption);
    return (
      <div className="schema-field">
        {heading}
        <select
          id={id}
          value={typeof value === "string" ? value : ""}
          required={field.required}
          aria-required={field.required || undefined}
          onChange={(event) => onChange(event.target.value === "" ? undefined : event.target.value)}
        >
          <option value="">Not set</option>
          {options.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
        {help}
        {errorMessage}
      </div>
    );
  }

  if (type === "array") {
    if (!canEditAsStringArray(field, value)) {
      return (
        <JsonFallbackField
          heading={heading}
          help={help}
          errorMessage={errorMessage}
          value={value}
          id={id}
          required={field.required}
          onChange={onChange}
        />
      );
    }
    const items = Array.isArray(value) ? value : [];
    return (
      <div className="schema-field">
        <span className="schema-field-heading">
          {label}
          {field.required ? <span className="required-marker" aria-hidden="true" /> : null}
        </span>
        {items.map((item, index) => (
          <div className="array-row" key={index}>
            <label className="array-item-label" htmlFor={`${id}-${index}`}>
              {label} {index + 1}
            </label>
            <input
              id={`${id}-${index}`}
              required={field.required && index === 0}
              aria-required={field.required || undefined}
              value={item}
              onChange={(event) => {
                const next = [...items];
                next[index] = event.target.value;
                onChange(next);
              }}
            />
            <button
              type="button"
              className="icon-button"
              aria-label={`Remove ${label} ${index + 1}`}
              onClick={() => onChange(items.filter((_, position) => position !== index))}
            >
              Remove
            </button>
          </div>
        ))}
        <button type="button" className="icon-button" onClick={() => onChange([...items, ""])}>
          Add another
        </button>
        {help}
        {errorMessage}
      </div>
    );
  }

  if (type === "secret_ref") {
    return (
      <div className="schema-field">
        {heading}
        <input
          id={id}
          type="password"
          autoComplete="off"
          placeholder="Saved credential reference"
          value=""
          required={field.required}
          aria-required={field.required || undefined}
          onChange={(event) => onChange(event.target.value === "" ? undefined : event.target.value)}
        />
        <span className="field-help">
          Enter the name of a credential saved on this appliance. The secret itself is never shown or stored here; the reference is masked and never included in Advanced JSON.
        </span>
        {help}
        {errorMessage}
      </div>
    );
  }

  if (type === "string") {
    return (
      <div className="schema-field">
        {heading}
        <input
          id={id}
          type="text"
          value={typeof value === "string" ? value : ""}
          required={field.required}
          aria-required={field.required || undefined}
          onChange={(event) => onChange(event.target.value === "" ? undefined : event.target.value)}
        />
        {help}
        {errorMessage}
      </div>
    );
  }

  return (
    <JsonFallbackField
      heading={heading}
      help={help}
      errorMessage={errorMessage}
      value={value}
      onChange={onChange}
      id={id}
      required={field.required}
    />
  );
}

type JsonFallbackFieldProps = {
  heading: ReactNode;
  help: ReactNode;
  errorMessage: ReactNode;
  value: unknown;
  id: string;
  required?: boolean;
  onChange: (next: unknown) => void;
};

function JsonFallbackField({ heading, help, errorMessage, value, id, required, onChange }: JsonFallbackFieldProps) {
  const [text, setText] = useState(() => (value === undefined ? "" : JSON.stringify(value, null, 2)));
  const [parseError, setParseError] = useState("");

  function edit(next: string) {
    setText(next);
    if (next.trim() === "") {
      setParseError("");
      onChange(undefined);
      return;
    }
    try {
      setParseError("");
      onChange(JSON.parse(next));
    } catch {
      setParseError("That JSON is not complete yet — keep editing.");
    }
  }

  return (
    <div className="schema-field">
      {heading}
      <textarea
        id={id}
        rows={4}
        required={required}
        aria-required={required || undefined}
        value={text}
        onChange={(event) => edit(event.target.value)}
      />
      <span className="field-help">
        This setting uses a format the form does not know, so it is edited as JSON.
      </span>
      {help}
      {parseError ? <span className="field-error">{parseError}</span> : null}
      {errorMessage}
    </div>
  );
}

function canEditAsStringArray(field: CollectorConfigField, value: unknown): value is string[] | undefined {
  const itemType = field.items?.type;
  if (itemType && itemType !== "string") {
    return false;
  }
  if (value === undefined) {
    return true;
  }
  return Array.isArray(value) && value.every((item) => typeof item === "string");
}

function normalizeOption(option: CollectorConfigFieldOption): { value: string; label: string } {
  if (typeof option === "string") {
    return { value: option, label: humanizeName(option) };
  }
  return { value: option.value, label: option.label ?? humanizeName(option.value) };
}
