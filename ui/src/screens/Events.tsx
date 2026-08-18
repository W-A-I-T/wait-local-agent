import { useCallback, useEffect, useState } from "react";
import { X } from "lucide-react";
import { apiFetch } from "../api/client";
import { useDashboard } from "../app/DashboardContext";
import type { EventDelivery, EventHistory } from "../api/types";
import { StatusChip } from "../components/StatusChip";

export function Events() {
  const { retryEventDelivery } = useDashboard();
  const [deliveries, setDeliveries] = useState<EventDelivery[]>([]);
  const [history, setHistory] = useState<EventHistory[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [selectedDelivery, setSelectedDelivery] = useState<EventDelivery | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState("");
  const [retryingDeliveryId, setRetryingDeliveryId] = useState<number | null>(null);
  const [retryError, setRetryError] = useState("");

  const loadEvents = useCallback(async () => {
    setLoading(true);
    setError("");
    setSelectedDelivery(null);
    setDetailError("");
    try {
      const [deliveryResult, historyResult] = await Promise.all([
        apiFetch<EventDelivery[]>("/automation/event-deliveries"),
        apiFetch<EventHistory[]>("/event-history")
      ]);
      if (!Array.isArray(deliveryResult) || !Array.isArray(historyResult)) {
        throw new Error("The appliance returned invalid Events data.");
      }
      setDeliveries(deliveryResult);
      setHistory(historyResult);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Unable to load Events.");
    } finally {
      setLoading(false);
    }
  }, []);

  const retryDelivery = useCallback(async (deliveryId: number) => {
    setRetryingDeliveryId(deliveryId);
    setRetryError("");
    try {
      await retryEventDelivery(deliveryId);
      await loadEvents();
    } catch (requestError) {
      setRetryError(requestError instanceof Error ? requestError.message : "Unable to retry event delivery.");
    } finally {
      setRetryingDeliveryId(null);
    }
  }, [loadEvents, retryEventDelivery]);

  useEffect(() => {
    void loadEvents();
  }, [loadEvents]);

  const openDelivery = useCallback(async (delivery: EventDelivery) => {
    setSelectedDelivery(delivery);
    setDetailLoading(true);
    setDetailError("");
    try {
      const detail = await apiFetch<EventDelivery>(`/automation/event-deliveries/${encodeURIComponent(String(delivery.id))}`);
      setSelectedDelivery(detail);
    } catch (requestError) {
      setDetailError(requestError instanceof Error ? requestError.message : "Unable to load delivery details.");
    } finally {
      setDetailLoading(false);
    }
  }, []);

  return (
    <div className="screen-stack">
      <section className="panel events-hero">
        <div>
          <p className="eyebrow">Automation</p>
          <h2>Events</h2>
          <p className="screen-note">Review event deliveries and history, and retry eligible failed deliveries.</p>
        </div>
        <button className="icon-button" type="button" onClick={() => void loadEvents()} disabled={loading}>
          {loading ? "Loading…" : "Refresh"}
        </button>
      </section>

      {error ? (
        <div className="notice danger" role="alert">
          <span>{error}</span>
          <button className="secondary-button" type="button" onClick={() => void loadEvents()} disabled={loading}>Try again</button>
        </div>
      ) : null}
      {retryError ? <div className="notice danger" role="alert">{retryError}</div> : null}

      {loading ? (
        <section className="panel" aria-busy="true">
          <p className="screen-note">Loading Events…</p>
        </section>
      ) : (
        <>
          <section className="panel" aria-labelledby="event-deliveries-heading">
            <div className="panel-heading">
              <div>
                <h2 id="event-deliveries-heading">Deliveries</h2>
                <span>{deliveries.length} delivery{deliveries.length === 1 ? "" : "ies"}</span>
              </div>
              <span>Viewer access</span>
            </div>

            {deliveries.length === 0 ? (
              <div className="empty-state">
                <h3>No event deliveries are visible.</h3>
                <p>The appliance has not recorded any event deliveries for this scope.</p>
              </div>
            ) : (
              <div className="events-table-wrap">
                <table className="events-table">
                  <thead>
                    <tr>
                      <th scope="col">Event</th>
                      <th scope="col">Target</th>
                      <th scope="col">Status</th>
                      <th scope="col">Attempts</th>
                      <th scope="col">Received</th>
                      <th scope="col">Processed</th>
                      <th scope="col">Action</th>
                    </tr>
                  </thead>
                  <tbody>
                    {deliveries.map((delivery) => (
                      <tr key={delivery.id}>
                        <td>
                          <button
                            className="events-row-trigger"
                            type="button"
                            aria-label={`Open delivery ${delivery.id}: ${delivery.event_type}`}
                            onClick={() => void openDelivery(delivery)}
                          >
                            <strong>{delivery.event_type}</strong>
                            <code>Delivery {delivery.id}</code>
                          </button>
                        </td>
                        <td>{formatTarget(delivery)}</td>
                        <td><StatusChip status={delivery.status} /></td>
                        <td>{delivery.retry_count} of {delivery.max_retries}</td>
                        <td>{formatTimestamp(delivery.received_at)}</td>
                        <td>{formatTimestamp(delivery.processed_at)}</td>
                        <td>
                          {delivery.status === "failed" && delivery.retry_count < delivery.max_retries ? (
                            <button
                              className="secondary-button"
                              type="button"
                              disabled={retryingDeliveryId !== null}
                              onClick={() => void retryDelivery(delivery.id)}
                            >
                              {retryingDeliveryId === delivery.id ? "Retrying…" : "Retry delivery"}
                            </button>
                          ) : null}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          {selectedDelivery ? (
            <DeliveryDetail
              delivery={selectedDelivery}
              loading={detailLoading}
              error={detailError}
              onClose={() => setSelectedDelivery(null)}
            />
          ) : null}

          <section className="panel" aria-labelledby="event-history-heading">
            <div className="panel-heading">
              <div>
                <h2 id="event-history-heading">History</h2>
                <span>{history.length} event{history.length === 1 ? "" : "s"}</span>
              </div>
              <span>Latest first</span>
            </div>

            {history.length === 0 ? (
              <div className="empty-state">
                <h3>No event history is visible.</h3>
                <p>The appliance has not recorded any event history for this scope.</p>
              </div>
            ) : (
              <div className="events-history-list">
                {history.map((event) => (
                  <article className="events-history-row" key={event.id}>
                    <div className="events-history-meta">
                      <strong>{event.event_type}</strong>
                      <span>Subject {event.subject_id}</span>
                      <StatusChip status={event.status} />
                      <span>{formatTimestamp(event.created_at)}</span>
                    </div>
                    <p>{event.message}</p>
                  </article>
                ))}
              </div>
            )}
          </section>
        </>
      )}
    </div>
  );
}

function DeliveryDetail({
  delivery,
  loading,
  error,
  onClose
}: {
  delivery: EventDelivery;
  loading: boolean;
  error: string;
  onClose: () => void;
}) {
  return (
    <section className="panel events-detail" aria-labelledby="event-delivery-detail-heading">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">Delivery detail</p>
          <h2 id="event-delivery-detail-heading">Delivery {delivery.id}</h2>
          <code>{delivery.idempotency_key}</code>
        </div>
        <button className="icon-button" type="button" onClick={onClose} aria-label="Close delivery details">
          <X size={17} aria-hidden="true" />
          Close
        </button>
      </div>

      {loading ? <p className="screen-note" aria-busy="true">Loading delivery details…</p> : null}
      {error ? <div className="notice danger" role="alert">{error}</div> : null}

      <dl className="events-detail-grid">
        <div><dt>Event type</dt><dd>{delivery.event_type}</dd></div>
        <div><dt>Entity type</dt><dd>{delivery.entity_type}</dd></div>
        <div><dt>Entity ID</dt><dd>{delivery.entity_id}</dd></div>
        <div><dt>Status</dt><dd><StatusChip status={delivery.status} /></dd></div>
        <div><dt>Retry count</dt><dd>{delivery.retry_count} of {delivery.max_retries}</dd></div>
        <div><dt>Matched agents</dt><dd>{delivery.matched_agent_count ?? 0}</dd></div>
        <div><dt>Matched playbooks</dt><dd>{delivery.matched_playbook_count ?? 0}</dd></div>
        <div><dt>Client</dt><dd>{delivery.client_id || "Appliance scope"}</dd></div>
        <div><dt>Received</dt><dd>{formatTimestamp(delivery.received_at)}</dd></div>
        <div><dt>Processed</dt><dd>{formatTimestamp(delivery.processed_at)}</dd></div>
        <div><dt>Next retry</dt><dd>{formatTimestamp(delivery.next_retry_at)}</dd></div>
        <div><dt>Error detail</dt><dd>{delivery.error_detail || "None recorded"}</dd></div>
      </dl>

      {delivery.payload ? (
        <>
          <h3>Payload</h3>
          <pre className="events-code"><code>{JSON.stringify(delivery.payload, null, 2)}</code></pre>
        </>
      ) : null}
    </section>
  );
}

function formatTarget(delivery: EventDelivery): string {
  return `${delivery.entity_type}:${delivery.entity_id}`;
}

function formatTimestamp(value?: string | null): string {
  return value || "Not recorded";
}
