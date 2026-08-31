import type { CollectorConfigField, WorkflowTemplate } from "../api/types";

const CHANNEL_OPTIONS = ["ticket_note", "email", "teams", "slack", "sms"];
const OPERATION_OPTIONS = ["add", "remove"];
const METHOD_TYPE_OPTIONS = ["fido2", "microsoft_authenticator", "phone", "software_oath"];

export function workflowPayloadFields(template: WorkflowTemplate | undefined): CollectorConfigField[] {
  const schema = template?.payload_schema;
  const properties = schema?.properties ?? {};
  const required = new Set(schema?.required ?? []);
  const names = [...new Set([...Object.keys(properties), ...(schema?.required ?? [])])];
  return names.map((name) => fieldFromMetadata(name, properties[name], required.has(name)));
}

export function requiredInputFields(names: string[]): CollectorConfigField[] {
  return names.map((name) => fieldFromMetadata(name, undefined, true));
}

function fieldFromMetadata(name: string, description: string | undefined, required: boolean): CollectorConfigField {
  const type = inferFieldType(name, description);
  const field: CollectorConfigField = {
    name,
    type,
    required,
    help: description
  };

  const options = optionsForField(name);
  if (options) {
    field.options = options;
  }
  if (type === "array") {
    field.items = { type: "string" };
  }
  return field;
}

function inferFieldType(name: string, description: string | undefined): string {
  const normalized = `${name} ${description ?? ""}`.toLowerCase();
  if (
    name === "account_enabled" ||
    name === "force_change_password_next_sign_in" ||
    name === "force_change_password_next_sign_in_with_mfa" ||
    normalized.includes("boolean")
  ) {
    return "boolean";
  }
  if (name === "sku_ids") {
    return "array";
  }
  if (
    normalized.includes("object") ||
    name === "thresholds_minutes"
  ) {
    return "object";
  }
  if (
    normalized.includes("integer") ||
    normalized.includes("positive minutes") ||
    name === "limit" ||
    name.endsWith("_minutes")
  ) {
    return "number";
  }
  return optionsForField(name) ? "enum" : "string";
}

function optionsForField(name: string): string[] | undefined {
  if (name === "channel") return CHANNEL_OPTIONS;
  if (name === "operation") return OPERATION_OPTIONS;
  if (name === "method_type") return METHOD_TYPE_OPTIONS;
  return undefined;
}
