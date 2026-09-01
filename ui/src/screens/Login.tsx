import { useState, type FormEvent } from "react";
import { apiFetch } from "../api/client";
import { persistApiToken } from "../api/headers";
import { useDashboard } from "../app/DashboardContext";

type LocalLoginResponse = {
  session_created: boolean;
};

export function Login() {
  const { refresh, setStatusMessage } = useDashboard();
  const [token, setToken] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const candidate = token.trim();
    if (!candidate || busy) {
      return;
    }
    setBusy(true);
    setError("");
    try {
      const result = await apiFetch<LocalLoginResponse>("/auth/login/local", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token: candidate })
      });
      if (result.session_created) {
        persistApiToken("");
      } else {
        // Break-glass bootstrap tokens remain bearer-only by design.
        persistApiToken(candidate);
      }
      setToken("");
      const auth = await refresh();
      if (!auth?.role) {
        persistApiToken("");
        setError("That token was not accepted for dashboard access.");
      } else {
        setStatusMessage("Signed in.");
      }
    } catch (loginError) {
      setError(loginError instanceof Error ? loginError.message : "Sign-in failed. Try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="login-screen">
      <section className="login-card panel" aria-labelledby="login-heading">
        <p className="eyebrow">WAIT Local Agent</p>
        <h1 id="login-heading">Sign in to the appliance</h1>
        <p className="screen-note">Use the access token issued for your local account.</p>
        <form onSubmit={submit}>
          <label className="token-input" htmlFor="login-token">
            Access token
            <input
              id="login-token"
              type="password"
              autoComplete="current-password"
              value={token}
              onChange={(event) => setToken(event.target.value)}
              required
              autoFocus
            />
          </label>
          <button className="primary-button" type="submit" disabled={busy || !token.trim()}>
            {busy ? "Signing in…" : "Sign in"}
          </button>
        </form>
        {error ? <p className="notice danger" role="alert">{error}</p> : null}
      </section>
    </main>
  );
}
