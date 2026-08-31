import { useCallback, useEffect, useState, type ReactNode } from "react";

export type PaginatedEvidencePage<Row> = {
  result?: {
    status?: string;
    message?: string;
    count?: number;
  };
  items?: Row[];
  next_cursor?: string;
};

export type EvidenceColumn<Row> = {
  key: string;
  label: string;
  render?: (row: Row) => ReactNode;
};

type PaginatedEvidenceTableProps<Row extends Record<string, unknown>> = {
  title: string;
  description?: string;
  columns: EvidenceColumn<Row>[];
  loadPage: (cursor: string | null) => Promise<PaginatedEvidencePage<Row>>;
  onClose: () => void;
  rowKey?: (row: Row, index: number) => string;
};

export function PaginatedEvidenceTable<Row extends Record<string, unknown>>({
  title,
  description,
  columns,
  loadPage,
  onClose,
  rowKey
}: PaginatedEvidenceTableProps<Row>) {
  const [page, setPage] = useState<PaginatedEvidencePage<Row> | null>(null);
  const [currentCursor, setCurrentCursor] = useState<string | null>(null);
  const [cursorHistory, setCursorHistory] = useState<Array<string | null>>([]);
  const [selectedRow, setSelectedRow] = useState<Row | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [gated, setGated] = useState(false);

  const fetchPage = useCallback(async (cursor: string | null, history: Array<string | null>) => {
    setLoading(true);
    setError("");
    setGated(false);
    setSelectedRow(null);
    try {
      const response = await loadPage(cursor);
      if (response.result?.status === "blocked" || response.result?.status === "forbidden") {
        setPage(null);
        setGated(true);
        return;
      }
      if (response.result?.status && response.result.status !== "ready") {
        setPage(null);
        setError(response.result.message || "This evidence surface is unavailable.");
        return;
      }
      setPage({
        ...response,
        items: Array.isArray(response.items) ? response.items : [],
        next_cursor: typeof response.next_cursor === "string" ? response.next_cursor : ""
      });
      setCurrentCursor(cursor);
      setCursorHistory(history);
    } catch (requestError) {
      if (isGatedError(requestError)) {
        setPage(null);
        setGated(true);
      } else {
        setError(requestError instanceof Error ? requestError.message : "This evidence surface is unavailable.");
      }
    } finally {
      setLoading(false);
    }
  }, [loadPage]);

  useEffect(() => {
    void fetchPage(null, []);
  }, [fetchPage]);

  function goNext() {
    if (!page?.next_cursor || loading) return;
    void fetchPage(page.next_cursor, [...cursorHistory, currentCursor]);
  }

  function goPrevious() {
    if (cursorHistory.length === 0 || loading) return;
    const previousCursor = cursorHistory[cursorHistory.length - 1] ?? null;
    void fetchPage(previousCursor, cursorHistory.slice(0, -1));
  }

  const rows = page?.items ?? [];
  return (
    <section className="panel microsoft-evidence-panel" aria-labelledby="microsoft-evidence-heading">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">Evidence drill-down</p>
          <h3 id="microsoft-evidence-heading">{title}</h3>
          {description ? <span>{description}</span> : null}
        </div>
        <button type="button" className="secondary-button" onClick={onClose}>Close</button>
      </div>

      {loading ? <p className="screen-note" aria-busy="true">Loading {title.toLowerCase()}…</p> : null}
      {gated ? (
        <div className="empty-state" role="status">
          <h4>Evidence access is not available</h4>
          <p>Your current Microsoft access scope cannot view this evidence surface.</p>
        </div>
      ) : null}
      {error ? <div className="notice danger" role="alert">{error}</div> : null}
      {!loading && !gated && !error && rows.length === 0 ? (
        <div className="empty-state">
          <h4>No {title.toLowerCase()} records</h4>
          <p>The connected Microsoft tenant did not return any records for this surface.</p>
        </div>
      ) : null}
      {!loading && !gated && !error && rows.length > 0 ? (
        <>
          <div className="microsoft-evidence-table-wrap">
            <table className="microsoft-evidence-table">
              <thead>
                <tr>
                  {columns.map((column) => <th scope="col" key={column.key}>{column.label}</th>)}
                  <th scope="col">Details</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row, index) => (
                  <tr key={rowKey?.(row, index) ?? String(index)}>
                    {columns.map((column) => (
                      <td key={column.key}>{column.render ? column.render(row) : displayValue(row[column.key])}</td>
                    ))}
                    <td>
                      <button
                        type="button"
                        className="table-link"
                        onClick={() => setSelectedRow(row)}
                        aria-label={`Show details for ${rowLabel(row, index)}`}
                      >
                        Show details
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="microsoft-evidence-pagination" aria-label={`${title} pagination`}>
            <span>{page?.result?.count ?? rows.length} records in this page</span>
            <div>
              <button type="button" className="secondary-button" onClick={goPrevious} disabled={loading || cursorHistory.length === 0}>Previous</button>
              <button type="button" className="secondary-button" onClick={goNext} disabled={loading || !page?.next_cursor}>Next</button>
            </div>
          </div>
        </>
      ) : null}

      {selectedRow ? (
        <aside className="microsoft-evidence-detail-drawer" aria-labelledby="microsoft-evidence-detail-heading" role="dialog">
          <div className="panel-heading">
            <h4 id="microsoft-evidence-detail-heading">Raw evidence details</h4>
            <button type="button" className="secondary-button" onClick={() => setSelectedRow(null)}>Close details</button>
          </div>
          <pre>{formatJson(selectedRow)}</pre>
        </aside>
      ) : null}
    </section>
  );
}

function isGatedError(error: unknown): boolean {
  return Boolean(error && typeof error === "object" && "status" in error && ((error as { status?: unknown }).status === 401 || (error as { status?: unknown }).status === 403));
}

function displayValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "Not recorded";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "string" || typeof value === "number") return String(value);
  return formatJson(value);
}

function rowLabel<Row extends Record<string, unknown>>(row: Row, index: number): string {
  for (const key of ["display_name", "title", "user_display_name", "name", "service", "id"]) {
    const value = row[key];
    if (typeof value === "string" && value) return value;
  }
  return `record ${index + 1}`;
}

function formatJson(value: unknown): string {
  try {
    return JSON.stringify(value, null, 2) ?? "Not recorded";
  } catch {
    return "Unable to render this evidence.";
  }
}
