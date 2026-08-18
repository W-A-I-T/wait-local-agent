import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { apiFetch } from "../api/client";
import { useDashboard } from "../app/DashboardContext";
import { RoleGate } from "../components/RoleGate";

type M365DraftApprovalView = {
  id: number | string;
  action_type: string;
  status: string;
};

type DraftNotice = { kind: "success" | "danger"; message: string } | null;

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

export function M365Actions() {
  const { role, roleResolved, selectedClientId } = useDashboard();
  const [userIdentity, setUserIdentity] = useState("");
  const [disableBusy, setDisableBusy] = useState(false);
  const [disableNotice, setDisableNotice] = useState<DraftNotice>(null);
  const [resetUserIdentity, setResetUserIdentity] = useState("");
  const [temporaryVaultName, setTemporaryVaultName] = useState("");
  const [forceChangeNextSignIn, setForceChangeNextSignIn] = useState(true);
  const [forceChangeNextSignInWithMfa, setForceChangeNextSignInWithMfa] = useState(false);
  const [resetBusy, setResetBusy] = useState(false);
  const [resetNotice, setResetNotice] = useState<DraftNotice>(null);
  const [deviceId, setDeviceId] = useState("");
  const [rebootBusy, setRebootBusy] = useState(false);
  const [rebootNotice, setRebootNotice] = useState<DraftNotice>(null);
  const hasClient = Boolean(selectedClientId);

  const approvalMessage = (approval: M365DraftApprovalView) =>
    `Draft created — pending approval #${approval.id} (${approval.action_type}). Review and execute it in Approvals.`;

  async function submitDisable(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!hasClient) return;
    setDisableBusy(true);
    setDisableNotice(null);
    try {
      const approval = await apiFetch<M365DraftApprovalView>("/connectors/m365/users/disable-drafts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_identity: userIdentity.trim(), client_id: selectedClientId })
      });
      setUserIdentity("");
      setDisableNotice({ kind: "success", message: approvalMessage(approval) });
    } catch (error) {
      setDisableNotice({ kind: "danger", message: draftError(error) });
    } finally {
      setDisableBusy(false);
    }
  }

  async function submitReset(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!hasClient || temporaryVaultName.trim().length < 14) return;
    setResetBusy(true);
    setResetNotice(null);
    try {
      const approval = await apiFetch<M365DraftApprovalView>("/connectors/m365/users/password-reset-drafts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          user_identity: resetUserIdentity.trim(),
          temporary_vault_name: temporaryVaultName.trim(),
          force_change_password_next_sign_in: forceChangeNextSignIn,
          force_change_password_next_sign_in_with_mfa: forceChangeNextSignInWithMfa,
          client_id: selectedClientId
        })
      });
      setResetUserIdentity("");
      setTemporaryVaultName("");
      setForceChangeNextSignIn(true);
      setForceChangeNextSignInWithMfa(false);
      setResetNotice({ kind: "success", message: approvalMessage(approval) });
    } catch (error) {
      setResetNotice({ kind: "danger", message: draftError(error) });
    } finally {
      setResetBusy(false);
    }
  }

  async function submitReboot(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!hasClient) return;
    setRebootBusy(true);
    setRebootNotice(null);
    try {
      const approval = await apiFetch<M365DraftApprovalView>("/connectors/m365/managed-devices/reboot-drafts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ device_id: deviceId.trim(), client_id: selectedClientId })
      });
      setDeviceId("");
      setRebootNotice({ kind: "success", message: approvalMessage(approval) });
    } catch (error) {
      setRebootNotice({ kind: "danger", message: draftError(error) });
    } finally {
      setRebootBusy(false);
    }
  }

  const clientNote = !hasClient ? <p className="screen-note">Select a client from the top bar to draft an action.</p> : null;

  return (
    <div className="screen-stack">
      <section className="panel">
        <p className="eyebrow">Approval drafts</p>
        <h2>Microsoft 365 Actions</h2>
        <p className="screen-note">Create Microsoft 365 action drafts queued for approval. These forms never execute a change here.</p>
      </section>

      <RoleGate
        role={role}
        resolved={roleResolved}
        allowed={["admin"]}
        fallback={<section className="panel"><h3>Administrator access required</h3><p className="screen-note">M365 action drafts are available to administrators only.</p></section>}
      >
        <section className="panel" aria-labelledby="disable-user-heading">
          <div className="panel-heading"><div><h3 id="disable-user-heading">Offboard — Disable user</h3><span>Queue an offboarding action for approval.</span></div></div>
          <form onSubmit={(event) => void submitDisable(event)}>
            <label htmlFor="disable-user-identity">User (UPN or email)</label>
            <input id="disable-user-identity" name="user_identity" value={userIdentity} required disabled={disableBusy} onChange={(event) => setUserIdentity(event.target.value)} />
            {clientNote}
            <ApprovalNotice notice={disableNotice} />
            <button type="submit" disabled={!hasClient || disableBusy}>{disableBusy ? "Creating draft…" : "Create approval draft"}</button>
          </form>
        </section>

        <section className="panel" aria-labelledby="password-reset-heading">
          <div className="panel-heading"><div><h3 id="password-reset-heading">Password reset</h3><span>Queue a password reset action for approval.</span></div></div>
          <form onSubmit={(event) => void submitReset(event)}>
            <label htmlFor="reset-user-identity">User (UPN or email)</label>
            <input id="reset-user-identity" name="user_identity" value={resetUserIdentity} required disabled={resetBusy} onChange={(event) => setResetUserIdentity(event.target.value)} />
            <label htmlFor="temporary-vault-name">Vault secret name holding the temporary password</label>
            <input id="temporary-vault-name" name="temporary_vault_name" value={temporaryVaultName} minLength={14} required aria-describedby="temporary-vault-name-help" disabled={resetBusy} onChange={(event) => setTemporaryVaultName(event.target.value)} onBlur={() => setTemporaryVaultName((value) => value.trim())} />
            <p className="screen-note" id="temporary-vault-name-help">Name of the vault secret that holds the temporary password (min 14 chars). The password value itself is never entered here.</p>
            {temporaryVaultName.length > 0 && temporaryVaultName.trim().length < 14 ? <p className="notice danger" role="alert">Vault secret name must be at least 14 characters.</p> : null}
            <label><input type="checkbox" checked={forceChangeNextSignIn} disabled={resetBusy} onChange={(event) => setForceChangeNextSignIn(event.target.checked)} /> Force change password at next sign-in</label>
            <label><input type="checkbox" checked={forceChangeNextSignInWithMfa} disabled={resetBusy} onChange={(event) => setForceChangeNextSignInWithMfa(event.target.checked)} /> Force change password at next sign-in with MFA</label>
            {clientNote}
            <ApprovalNotice notice={resetNotice} />
            <button type="submit" disabled={!hasClient || resetBusy || temporaryVaultName.trim().length < 14}>{resetBusy ? "Creating draft…" : "Create approval draft"}</button>
          </form>
        </section>

        <section className="panel" aria-labelledby="device-reboot-heading">
          <div className="panel-heading"><div><h3 id="device-reboot-heading">Device reboot</h3><span>Queue a managed-device reboot for approval.</span></div></div>
          <form onSubmit={(event) => void submitReboot(event)}>
            <label htmlFor="managed-device-id">Managed device ID</label>
            <input id="managed-device-id" name="device_id" value={deviceId} required disabled={rebootBusy} onChange={(event) => setDeviceId(event.target.value)} />
            {clientNote}
            <ApprovalNotice notice={rebootNotice} />
            <button type="submit" disabled={!hasClient || rebootBusy}>{rebootBusy ? "Creating draft…" : "Create approval draft"}</button>
          </form>
        </section>
      </RoleGate>
    </div>
  );
}
