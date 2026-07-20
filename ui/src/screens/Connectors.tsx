import { useCallback, useEffect, useState } from "react";
import { useDashboard } from "../app/DashboardContext";
import { apiFetch } from "../api/client";
import { type ConnectorStatus } from "../api/types";

type HealthState = {
  status: string;
  message: string;
};

type CompanyRow = { id: string; name: string; archived?: boolean };

type HuduSnapshot = {
  companies: CompanyRow[];
  articles: CompanyRow[];
};

export function Connectors() {
  const { connectors, haloConnector, huduConnector, writeHealth, loading } = useDashboard();
  const [halopsaHealth, setHalopsaHealth] = useState<HealthState | null>(null);
  const [huduHealth, setHuduHealth] = useState<HealthState | null>(null);
  const [huduData, setHuduData] = useState<HuduSnapshot>({ companies: [], articles: [] });

  const refreshConnectivity = useCallback(async () => {
    const results = await Promise.allSettled([
      apiFetch<HealthState>("/connectors/halopsa/health"),
      apiFetch<HealthState>("/connectors/halopsa/write-health"),
      apiFetch<HealthState>("/connectors/hudu/health"),
      apiFetch<{ result: { count: number }; items: CompanyRow[] }>("/connectors/hudu/companies"),
      apiFetch<{ result: { count: number }; items: CompanyRow[] }>("/connectors/hudu/articles")
    ]);

    if (results[0].status === "fulfilled") {
      setHalopsaHealth(results[0].value);
    }
    if (results[2].status === "fulfilled") {
      setHuduHealth(results[2].value);
    }
    const companiesResult = results[3];
    if (companiesResult.status === "fulfilled") {
      setHuduData((current) => ({
        ...current,
        companies: Array.isArray(companiesResult.value.items)
          ? companiesResult.value.items.slice(0, 8)
          : []
      }));
    }
    const articlesResult = results[4];
    if (articlesResult.status === "fulfilled") {
      setHuduData((current) => ({
        ...current,
        articles: Array.isArray(articlesResult.value.items)
          ? articlesResult.value.items.slice(0, 8)
          : []
      }));
    }
  }, []);

  useEffect(() => {
    void refreshConnectivity();
  }, [refreshConnectivity]);

  const rows = connectors.length > 0 ? connectors : [
    { id: "halopsa", name: "HaloPSA", status: "loading", message: "Waiting for connector status" },
    { id: "hudu", name: "Hudu", status: "loading", message: "Waiting for connector status" }
  ];

  function renderConnector(status: ConnectorStatus) {
    return (
      <article className="connector-row" key={status.id}>
        <div>
          <strong>{status.name}</strong>
          <span>{status.message}</span>
        </div>
        <em>{status.status}</em>
      </article>
    );
  }

  return (
    <div className="screen-stack">
      <section className="panel">
        <div className="panel-heading">
          <h2>Connector Readiness</h2>
          <span>{loading ? "loading" : "live"}</span>
        </div>
        <div className="connector-summary">
          <div>
            <strong>HaloPSA</strong>
            <span>{haloConnector?.message || "Connector status unavailable."}</span>
          </div>
          <em>{haloConnector?.status || "unknown"}</em>
        </div>
        <div className="flag-grid">
          <span>HTTP probing: {haloConnector?.http_probing_enabled ? "enabled" : "disabled"}</span>
          <span>Write actions: {haloConnector?.write_actions_enabled ? "enabled" : "disabled"}</span>
          <span>Health: {halopsaHealth ? `${halopsaHealth.status} · ${halopsaHealth.message}` : "unknown"}</span>
        </div>
        <div className="connector-summary secondary">
          <div>
            <strong>Hudu</strong>
            <span>{huduConnector?.message || "Hudu connector status unavailable."}</span>
          </div>
          <em>{huduConnector?.status || "unknown"}</em>
        </div>
        <div className="flag-grid">
          <span>HTTP probing: {huduConnector?.http_probing_enabled ? "enabled" : "disabled"}</span>
          <span>Companies: {huduData.companies.length}</span>
          <span>Health: {huduHealth ? `${huduHealth.status} · ${huduHealth.message}` : "unknown"}</span>
        </div>
        <button type="button" className="icon-button" onClick={() => void refreshConnectivity()}>Refresh checks</button>
      </section>

      <section className="panel knowledge-panel">
        <div className="panel-heading">
          <h2>Live readout</h2>
          <span>read-only probe snapshot</span>
        </div>
        <div className="table-list">
          {rows.map((row) => renderConnector(row))}
        </div>
      </section>

      <section className="panel settings-panel">
        <div className="panel-heading">
          <h2>Hudu previews</h2>
          <span>{huduData.companies.length} companies</span>
        </div>
        <div className="table-list">
          {huduData.companies.map((company) => (
            <div className="table-row" key={company.id}>
              <div><strong>{company.name}</strong><span>{company.id}</span></div>
              <em>{company.archived ? "archived" : "active"}</em>
            </div>
          ))}
          {huduData.companies.length === 0 ? <p>No Hudu companies returned.</p> : null}
        </div>
      </section>

      <section className="panel">
        <div className="panel-heading">
          <h2>Write health detail</h2>
          <span>{writeHealth.status}</span>
        </div>
        <p>{writeHealth.message}</p>
      </section>
    </div>
  );
}
