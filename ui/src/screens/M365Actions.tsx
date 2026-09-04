import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { apiFetch } from "../api/client";
import { apiFetchForClient } from "../api/scopedFetch";
import { useDashboard } from "../app/DashboardContext";
import { LoadingState } from "../components/LoadingState";
import { RoleGate } from "../components/RoleGate";
import {
  M365_ACTION_CATALOG,
  M365_ACTION_CATEGORIES,
  type M365ActionDefinition,
  type M365ActionField,
  type M365LookupKind,
  type M365LookupValue
} from "./m365ActionCatalog";

type M365DraftApprovalView = {
  id: number | string;
  action_type: string;
  status: string;
};

type DraftNotice = { kind: "success" | "danger"; message: string } | null;
type LookupRow = Record<string, unknown>;
type LookupRows = Record<M365LookupKind, LookupRow[]>;
type StringMapEntry = { key: string; value: string };
type ActionValues = Record<string, unknown>;
type LookupOption = { value: string; label: string };

const EMPTY_LOOKUPS: LookupRows = {
  users: [],
  groups: [],
  licenses: [],
  "managed-devices": [],
  "mail-folders": [],
  teams: [],
  channels: []
};

const LOOKUP_ENDPOINTS: Partial<Record<M365LookupKind, string>> = {
  users: "/connectors/m365/users",
  groups: "/connectors/m365/groups",
  licenses: "/connectors/m365/licenses",
  "managed-devices": "/connectors/m365/managed-devices",
  "mail-folders": "/connectors/m365/mail-folders",
  teams: "/connectors/m365/teams"
};

function ApprovalNotice({ notice }: { notice: DraftNotice }) {
  if (!notice) return null;
  if (notice.kind === "danger") {
    return <div className="notice danger" role="alert">{notice.message}</div>;
  }
  return (
    <div className="notice success" role="status">
      {notice.message} <Link to="/approvals">Go to Approvals</Link>
    </div>
  );
}

function draftError(error: unknown): string {
  if (error && typeof error === "object" && "technicalDetail" in error && typeof error.technicalDetail === "string") {
    const detailSeparator = error.technicalDetail.indexOf(": ");
    return detailSeparator >= 0 ? error.technicalDetail.slice(detailSeparator + 2) : "The request could not be completed.";
  }
  return error instanceof Error ? error.message : "Unable to create the approval draft.";
}

function responseRows(payload: unknown): LookupRow[] {
  if (!payload || typeof payload !== "object" || !Array.isArray((payload as { items?: unknown }).items)) return [];
  return (payload as { items: unknown[] }).items.filter((item): item is LookupRow => Boolean(item) && typeof item === "object" && !Array.isArray(item));
}

function textValue(row: LookupRow, key: string): string {
  const value = row[key];
  return typeof value === "string" ? value : value === undefined || value === null ? "" : String(value);
}

function lookupOption(row: LookupRow, kind: M365LookupKind, valueKey: M365LookupValue): LookupOption | null {
  let value = "";
  let primary = "";
  let secondary = "";
  if (kind === "users") {
    const id = textValue(row, "id");
    const upn = textValue(row, "user_principal_name") || textValue(row, "mail");
    value = valueKey === "id" ? id : upn || id;
    primary = textValue(row, "display_name") || upn || id;
    secondary = [upn, id].filter(Boolean).join(" · ");
  } else if (kind === "groups") {
    value = textValue(row, "id");
    primary = textValue(row, "display_name") || textValue(row, "mail_nickname") || value;
    secondary = [textValue(row, "mail"), value].filter(Boolean).join(" · ");
  } else if (kind === "licenses") {
    value = textValue(row, "sku_id") || textValue(row, "id");
    primary = textValue(row, "sku_part_number") || value;
    secondary = value;
  } else if (kind === "managed-devices") {
    value = textValue(row, "id");
    primary = textValue(row, "device_name") || value;
    secondary = [textValue(row, "user_display_name"), textValue(row, "user_principal_name"), value].filter(Boolean).join(" · ");
  } else if (kind === "mail-folders") {
    value = textValue(row, "id");
    primary = textValue(row, "display_name") || value;
    secondary = value;
  } else {
    value = textValue(row, "id");
    primary = textValue(row, "display_name") || value;
    secondary = value;
  }
  if (!value) return null;
  return { value, label: [primary, secondary].filter(Boolean).join(" · ") };
}

function optionsFor(field: M365ActionField, rows: LookupRows, channelsByTeam: Record<string, LookupRow[]>, values: ActionValues): LookupOption[] {
  if (!field.lookup) return [];
  const source = field.lookup.kind === "channels"
    ? channelsByTeam[String(values[field.lookup.dependsOn ?? ""] ?? "").trim()]
    : rows[field.lookup.kind];
  if (!source) return [];
  const seen = new Set<string>();
  return source
    .map((row) => lookupOption(row, field.lookup!.kind, field.lookup!.value))
    .filter((option): option is LookupOption => option !== null && !seen.has(option.value) && Boolean(seen.add(option.value)));
}

function useM365Lookups(enabled: boolean, clientId: string) {
  const [lookups, setLookups] = useState<LookupRows>(EMPTY_LOOKUPS);
  const [channelsByTeam, setChannelsByTeam] = useState<Record<string, LookupRow[]>>({});
  const channelRequests = useRef(new Set<string>());
  const lookupGeneration = useRef(0);

  useEffect(() => {
    let cancelled = false;
    lookupGeneration.current += 1;
    channelRequests.current.clear();
    setLookups(EMPTY_LOOKUPS);
    setChannelsByTeam({});
    if (!enabled) return () => { cancelled = true; };

    const entries = (Object.entries(LOOKUP_ENDPOINTS) as [M365LookupKind, string][]).map(async ([kind, path]) => {
      try {
        const payload = await apiFetchForClient<unknown>(clientId, path);
        if (!cancelled) setLookups((current) => ({ ...current, [kind]: responseRows(payload) }));
      } catch {
        // Picker reads are optional. The field remains editable as plain text.
      }
    });
    void Promise.allSettled(entries);
    return () => { cancelled = true; };
  }, [clientId, enabled]);

  const loadChannels = useCallback(async (teamId: string) => {
    const normalizedTeamId = teamId.trim();
    if (!normalizedTeamId || channelRequests.current.has(normalizedTeamId)) return;
    channelRequests.current.add(normalizedTeamId);
    const generation = lookupGeneration.current;
    try {
      const payload = await apiFetch<unknown>(`/connectors/m365/teams/${encodeURIComponent(normalizedTeamId)}/channels`);
      if (generation === lookupGeneration.current) {
        setChannelsByTeam((current) => ({ ...current, [normalizedTeamId]: responseRows(payload) }));
      }
    } catch {
      if (generation === lookupGeneration.current) {
        setChannelsByTeam((current) => ({ ...current, [normalizedTeamId]: [] }));
      }
    }
  }, []);

  return { lookups, channelsByTeam, loadChannels };
}

function defaultsForAction(action: M365ActionDefinition): ActionValues {
  return Object.fromEntries(action.fields.map((field) => {
    if (field.default !== undefined) return [field.name, field.default];
    if (field.type === "array" || field.type === "string-map") return [field.name, []];
    return [field.name, ""];
  }));
}

function requiredValue(field: M365ActionField, value: unknown): boolean {
  if (field.type === "boolean") return true;
  if (field.type === "array") return Array.isArray(value) && value.some((item) => String(item ?? "").trim());
  if (field.type === "string-map") {
    return Array.isArray(value) && value.some((item) => {
      if (!item || typeof item !== "object") return false;
      const entry = item as StringMapEntry;
      return entry.key.trim() !== "";
    });
  }
  return typeof value === "string" && value.trim() !== "";
}

function validateAction(action: M365ActionDefinition, values: ActionValues): Record<string, string> {
  const errors: Record<string, string> = {};
  for (const field of action.fields) {
    const value = values[field.name];
    if (field.required && !requiredValue(field, value)) {
      errors[field.name] = `${field.label} is required.`;
      continue;
    }
    if (field.vaultReference && typeof value === "string" && value.trim() !== "" && value.trim().length < 14) {
      errors[field.name] = "Vault secret name must be at least 14 characters.";
    }
  }
  return errors;
}

function payloadFor(action: M365ActionDefinition, values: ActionValues, clientId: string): ActionValues {
  const payload: ActionValues = { client_id: clientId };
  for (const field of action.fields) {
    const value = values[field.name];
    if (field.type === "array") {
      payload[field.name] = Array.isArray(value) ? value.map((item) => String(item).trim()).filter(Boolean) : [];
    } else if (field.type === "string-map") {
      payload[field.name] = Object.fromEntries(
        (Array.isArray(value) ? value : [])
          .filter((item): item is StringMapEntry => Boolean(item) && typeof item === "object")
          .map((item) => [item.key.trim(), item.value.trim()])
          .filter(([key]) => key !== "")
      );
    } else if (field.type === "boolean") {
      payload[field.name] = Boolean(value);
    } else {
      payload[field.name] = typeof value === "string" ? value.trim() : value;
    }
  }
  return payload;
}

function ActionField({
  action,
  field,
  value,
  error,
  values,
  lookups,
  channelsByTeam,
  onChange
}: {
  action: M365ActionDefinition;
  field: M365ActionField;
  value: unknown;
  error?: string;
  values: ActionValues;
  lookups: LookupRows;
  channelsByTeam: Record<string, LookupRow[]>;
  onChange: (value: unknown) => void;
}) {
  const id = `m365-${action.id}-${field.name}`;
  const help = field.help ? <span className="field-help">{field.help}</span> : null;
  const errorMessage = error ? <span className="field-error">{error}</span> : null;
  const label = <label htmlFor={id}>{field.label}{field.required ? <span className="required-marker" aria-hidden="true" /> : null}</label>;

  if (field.type === "boolean") {
    return (
      <div className="schema-field schema-field-boolean">
        <input id={id} type="checkbox" checked={Boolean(value)} onChange={(event) => onChange(event.target.checked)} />
        {label}
        {help}
        {errorMessage}
      </div>
    );
  }

  if (field.type === "select") {
    return (
      <div className="schema-field">
        {label}
        <select id={id} value={typeof value === "string" ? value : ""} required={field.required} onChange={(event) => onChange(event.target.value)}>
          <option value="">Select an option</option>
          {(field.options ?? []).map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
        </select>
        {help}
        {errorMessage}
      </div>
    );
  }

  if (field.type === "array") {
    const items = Array.isArray(value) ? value.map((item) => String(item ?? "")) : [];
    const visibleItems = items.length > 0 ? items : [""];
    const options = optionsFor(field, lookups, channelsByTeam, values);
    const listId = `${id}-options`;
    return (
      <div className="schema-field">
        <span className="schema-field-heading">{field.label}{field.required ? <span className="required-marker" aria-hidden="true" /> : null}</span>
        {visibleItems.map((item, index) => (
          <div className="array-row" key={`${id}-${index}`}>
            <label className="array-item-label" htmlFor={`${id}-${index}`}>{field.label} {index + 1}</label>
            <input id={`${id}-${index}`} list={options.length > 0 ? listId : undefined} value={item} required={field.required && index === 0} onChange={(event) => {
              const next = [...visibleItems];
              next[index] = event.target.value;
              onChange(next);
            }} />
            {items.length > 0 ? <button type="button" className="icon-button" aria-label={`Remove ${field.label} ${index + 1}`} onClick={() => onChange(items.filter((_, position) => position !== index))}>Remove</button> : null}
          </div>
        ))}
        <button type="button" className="icon-button" onClick={() => onChange([...visibleItems, ""])}>Add another</button>
        {options.length > 0 ? <datalist id={listId}>{options.map((option) => <option key={option.value} value={option.value} label={option.label} />)}</datalist> : null}
        {help}
        {errorMessage}
      </div>
    );
  }

  if (field.type === "string-map") {
    const entries = Array.isArray(value) ? value.filter((item): item is StringMapEntry => Boolean(item) && typeof item === "object") : [];
    const visibleEntries = entries.length > 0 ? entries : [{ key: "", value: "" }];
    return (
      <div className="schema-field">
        <span className="schema-field-heading">{field.label}{field.required ? <span className="required-marker" aria-hidden="true" /> : null}</span>
        {visibleEntries.map((entry, index) => (
          <div className="array-row" key={`${id}-${index}`}>
            <label className="array-item-label" htmlFor={`${id}-${index}-key`}>Setting {index + 1}</label>
            <input id={`${id}-${index}-key`} aria-label={`Setting ${index + 1} name`} placeholder="Setting name" value={entry.key} onChange={(event) => {
              const next = [...visibleEntries];
              next[index] = { ...entry, key: event.target.value };
              onChange(next);
            }} />
            <input aria-label={`Setting ${index + 1} value`} placeholder="Value" value={entry.value} onChange={(event) => {
              const next = [...visibleEntries];
              next[index] = { ...entry, value: event.target.value };
              onChange(next);
            }} />
            {entries.length > 0 ? <button type="button" className="icon-button" aria-label={`Remove setting ${index + 1}`} onClick={() => onChange(entries.filter((_, position) => position !== index))}>Remove</button> : null}
          </div>
        ))}
        <button type="button" className="icon-button" onClick={() => onChange([...visibleEntries, { key: "", value: "" }])}>Add setting</button>
        {help}
        {errorMessage}
      </div>
    );
  }

  const options = field.lookup ? optionsFor(field, lookups, channelsByTeam, values) : [];
  const listId = `${id}-options`;
  const isVaultReference = Boolean(field.vaultReference);
  return (
    <div className="schema-field">
      {label}
      {field.type === "textarea" ? (
        <textarea id={id} rows={4} value={typeof value === "string" ? value : ""} required={field.required} onChange={(event) => onChange(event.target.value)} />
      ) : (
        <input
          id={id}
          type="text"
          autoComplete={isVaultReference ? "off" : undefined}
          value={typeof value === "string" ? value : ""}
          list={options.length > 0 ? listId : undefined}
          required={field.required}
          onChange={(event) => onChange(event.target.value)}
        />
      )}
      {options.length > 0 ? <datalist id={listId}>{options.map((option) => <option key={option.value} value={option.value} label={option.label} />)}</datalist> : null}
      {help}
      {errorMessage}
    </div>
  );
}

function ActionCard({
  action,
  selectedClientId,
  lookups,
  channelsByTeam,
  loadChannels
}: {
  action: M365ActionDefinition;
  selectedClientId: string;
  lookups: LookupRows;
  channelsByTeam: Record<string, LookupRow[]>;
  loadChannels: (teamId: string) => Promise<void>;
}) {
  const [values, setValues] = useState<ActionValues>(() => defaultsForAction(action));
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<DraftNotice>(null);
  const teamId = typeof values.team_id === "string" ? values.team_id : "";

  useEffect(() => {
    if (action.id !== "teams-message" || !teamId.trim()) return;
    const timer = window.setTimeout(() => void loadChannels(teamId), 250);
    return () => window.clearTimeout(timer);
  }, [action.id, loadChannels, teamId]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedClientId) return;
    const nextErrors = validateAction(action, values);
    setErrors(nextErrors);
    if (Object.keys(nextErrors).length > 0) return;
    setBusy(true);
    setNotice(null);
    try {
      const approval = await apiFetch<M365DraftApprovalView>(action.endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payloadFor(action, values, selectedClientId))
      });
      setValues(defaultsForAction(action));
      setErrors({});
      setNotice({ kind: "success", message: `Draft created — pending approval #${approval.id} (${approval.action_type}). Review and execute it in Approvals.` });
    } catch (error) {
      setNotice({ kind: "danger", message: draftError(error) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <article className="panel m365-action-card">
      <div className="panel-heading">
        <div><h3 id={`m365-${action.id}-heading`}>{action.title}</h3><span>{action.description}</span></div>
      </div>
      <form aria-labelledby={`m365-${action.id}-heading`} onSubmit={(event) => void submit(event)}>
        {action.fields.map((field) => (
          <ActionField
            key={field.name}
            action={action}
            field={field}
            value={values[field.name]}
            error={errors[field.name]}
            values={values}
            lookups={lookups}
            channelsByTeam={channelsByTeam}
            onChange={(value) => setValues((current) => ({ ...current, [field.name]: value }))}
          />
        ))}
        <ApprovalNotice notice={notice} />
        <button type="submit" disabled={!selectedClientId || busy}>{busy ? "Creating draft…" : "Create approval draft"}</button>
      </form>
    </article>
  );
}

export function M365Actions() {
  const { role, roleResolved, selectedClientId } = useDashboard();
  const { lookups, channelsByTeam, loadChannels } = useM365Lookups(Boolean(selectedClientId) && roleResolved && role === "admin", selectedClientId);

  return (
    <div className="screen-stack">
      <section className="panel">
        <p className="eyebrow">Approval drafts</p>
        <h2>Microsoft 365 Actions</h2>
        <p className="screen-note">Create Microsoft 365 action drafts queued for approval. These forms never execute a change here.</p>
      </section>

      {!roleResolved ? <LoadingState label="Checking administrator access…" /> : <RoleGate
        role={role}
        resolved={roleResolved}
        allowed={["admin"]}
        fallback={<section className="panel"><h3>Administrator access required</h3><p className="screen-note">M365 action drafts are available to administrators only.</p></section>}
      >
        {!selectedClientId ? <p className="notice">Select a client from the top bar to draft an action.</p> : null}
        {M365_ACTION_CATEGORIES.map((category) => {
          const actions = M365_ACTION_CATALOG.filter((action) => action.category === category);
          return (
            <section className="m365-category" key={category} aria-labelledby={`m365-category-${category}`}>
              <div className="panel-heading"><div><h2 id={`m365-category-${category}`}>{category}</h2><span>{actions.length} approval draft{actions.length === 1 ? "" : "s"}</span></div></div>
              <div className="m365-action-grid">
                {actions.map((action) => <ActionCard key={action.id} action={action} selectedClientId={selectedClientId} lookups={lookups} channelsByTeam={channelsByTeam} loadChannels={loadChannels} />)}
              </div>
            </section>
          );
        })}
      </RoleGate>}
    </div>
  );
}
