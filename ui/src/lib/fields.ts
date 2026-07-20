export function parseFields(text: string): Record<string, string> {
  return Object.fromEntries(
    text
      .split("\n")
      .map((line) => line.trim())
      .filter(Boolean)
      .map((line) => {
        const [key, ...rest] = line.split("=");
        return [key.trim(), rest.join("=").trim()];
      })
      .filter(([key]) => key)
  );
}

export function fieldsToText(fields: Record<string, unknown> | undefined): string {
  if (!fields || typeof fields !== "object") {
    return "";
  }
  return Object.entries(fields)
    .map(([key, value]) => `${key}=${value ?? ""}`)
    .join("\n");
}

export function formatPayload(payload: unknown): string {
  if (!payload) {
    return "No parsed payload.";
  }
  return JSON.stringify(payload, null, 2);
}
