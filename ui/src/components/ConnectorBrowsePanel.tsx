import { useEffect, useMemo, useState } from "react";
import { apiFetch } from "../api/client";

export type BrowseList = { label: string; path: string };

export type ConnectorBrowsePanelProps = {
  title: string;
  healthPath: string;
  lists: BrowseList[];
  pageSize?: number;
};

type BrowseItem = Record<string, unknown>;

type BrowseResponse = {
  result?: unknown;
  items?: unknown;
};

type HealthResponse = {
  status?: unknown;
  count?: unknown;
  message?: unknown;
};

const MAX_COLUMNS = 8;
const MAX_VALUE_LENGTH = 160;

function asRecord(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

function asItems(value: unknown): BrowseItem[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.flatMap((item) => {
    const record = asRecord(item);
    return record ? [record] : [];
  });
}

function responseMessage(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback;
}

function isNotConfigured(status: string | null): boolean {
  return status !== null && /not[_ ]configured|not connected|unavailable|unreachable/i.test(status);
}

function displayValue(value: unknown): string {
  let rendered: string;
  if (value !== null && typeof value === "object") {
    try {
      rendered = JSON.stringify(value) ?? String(value);
    } catch {
      rendered = String(value);
    }
  } else {
    rendered = String(value);
  }
  return rendered.length > MAX_VALUE_LENGTH
    ? `${rendered.slice(0, MAX_VALUE_LENGTH - 1)}…`
    : rendered;
}

export function ConnectorBrowsePanel({ title, healthPath, lists, pageSize = 25 }: ConnectorBrowsePanelProps) {
  const [activeIndex, setActiveIndex] = useState(0);
  const [page, setPage] = useState(1);
  const [items, setItems] = useState<BrowseItem[]>([]);
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [healthError, setHealthError] = useState<string | null>(null);
  const [listError, setListError] = useState<string | null>(null);
  const [healthLoading, setHealthLoading] = useState(true);
  const [listLoading, setListLoading] = useState(true);
  const [hasNextPage, setHasNextPage] = useState(false);

  const activeList = lists[activeIndex] ?? lists[0];
  const safePageSize = Number.isInteger(pageSize) && pageSize > 0 ? pageSize : 25;

  useEffect(() => {
    let current = true;
    setHealthLoading(true);
    setHealthError(null);
    void apiFetch<HealthResponse>(healthPath)
      .then((response) => {
        if (current) {
          setHealth(response);
        }
      })
      .catch((error: unknown) => {
        if (current) {
          setHealth(null);
          setHealthError(responseMessage(error, "Health is unavailable or not configured."));
        }
      })
      .finally(() => {
        if (current) {
          setHealthLoading(false);
        }
      });
    return () => {
      current = false;
    };
  }, [healthPath]);

  useEffect(() => {
    let current = true;
    if (!activeList) {
      setItems([]);
      setListError(null);
      setListLoading(false);
      setHasNextPage(false);
      return () => {
        current = false;
      };
    }

    setListLoading(true);
    setListError(null);
    const path = `${activeList.path}?page=${page}&page_size=${safePageSize}`;
    void apiFetch<BrowseResponse>(path)
      .then((response) => {
        if (current) {
          const nextItems = asItems(response.items);
          setItems(nextItems);
          setHasNextPage(nextItems.length >= safePageSize);
        }
      })
      .catch((error: unknown) => {
        if (current) {
          setItems([]);
          setHasNextPage(false);
          setListError(responseMessage(error, "Records could not be loaded."));
        }
      })
      .finally(() => {
        if (current) {
          setListLoading(false);
        }
      });
    return () => {
      current = false;
    };
  }, [activeList?.path, page, safePageSize]);

  const columns = useMemo(() => {
    const keys: string[] = [];
    for (const item of items) {
      for (const key of Object.keys(item)) {
        if (!keys.includes(key)) {
          keys.push(key);
        }
      }
    }
    return keys.slice(0, MAX_COLUMNS);
  }, [items]);

  const healthStatus = typeof health?.status === "string" ? health.status : null;
  const configuredProblem = Boolean(healthError || listError) || isNotConfigured(healthStatus);
  const healthCount = typeof health?.count === "number" || typeof health?.count === "string"
    ? ` · ${health.count}`
    : "";

  return (
    <section className="panel connector-browse-panel" aria-labelledby={`${title.toLowerCase()}-browse-heading`}>
      <div className="panel-heading">
        <div>
          <h2 id={`${title.toLowerCase()}-browse-heading`}>{title}</h2>
          <span>Read-only browse</span>
        </div>
        {healthLoading ? (
          <span className="status-chip info">Checking health…</span>
        ) : healthError ? (
          <span className="status-chip neutral">Unavailable / not configured</span>
        ) : (
          <span className="status-chip neutral">{healthStatus ?? "unknown"}{healthCount}</span>
        )}
      </div>

      {configuredProblem ? <p className="screen-note">{title} is unavailable or not configured.</p> : null}

      {lists.length > 0 ? (
        <div className="tab-list" role="tablist" aria-label={`${title} lists`}>
          <div className="row-actions">
            {lists.map((list, index) => (
              <button
                key={list.path}
                type="button"
                role="tab"
                aria-selected={activeIndex === index}
                className={activeIndex === index ? "selected" : "secondary-button"}
                onClick={() => {
                  setActiveIndex(index);
                  setPage(1);
                }}
              >
                {list.label}
              </button>
            ))}
          </div>
        </div>
      ) : null}

      {listLoading ? <div className="screen-note" aria-busy="true">Loading {activeList?.label ?? "records"}…</div> : null}
      {listError ? <div className="notice danger" role="alert">{listError}</div> : null}
      {!listLoading && !listError && items.length === 0 ? <p className="screen-note">No records.</p> : null}
      {!listLoading && !listError && items.length > 0 ? (
        <div className="clients-table-wrap">
          <table className="clients-table">
            <thead>
              <tr>{columns.map((column) => <th scope="col" key={column}>{column}</th>)}</tr>
            </thead>
            <tbody>
              {items.map((item, rowIndex) => (
                <tr key={`${page}-${rowIndex}`}>
                  {columns.map((column) => <td key={column}>{displayValue(item[column])}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}

      <div className="row-actions" aria-label={`${title} pagination`}>
        <button type="button" className="secondary-button" onClick={() => setPage((current) => Math.max(1, current - 1))} disabled={page === 1 || listLoading}>Prev</button>
        <span>Page {page}</span>
        <button type="button" className="secondary-button" onClick={() => setPage((current) => current + 1)} disabled={!hasNextPage || listLoading}>Next</button>
      </div>
    </section>
  );
}
