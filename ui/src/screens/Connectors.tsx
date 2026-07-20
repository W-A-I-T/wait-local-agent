import { useDashboard } from "../app/DashboardContext";

export function Connectors() {
  const { haloConnector, huduConnector, writeHealth, loading } = useDashboard();

  return (
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
        <span>Write health: {writeHealth.message}</span>
      </div>
      <div className="connector-summary secondary">
        <div>
          <strong>Hudu</strong>
          <span>{huduConnector?.message || "Hudu connector status unavailable."}</span>
        </div>
        <em>{huduConnector?.status || "unknown"}</em>
      </div>
    </section>
  );
}
