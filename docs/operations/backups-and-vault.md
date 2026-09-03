# Backups and Vault

The default secrets backend is environment variables. Longer-lived local
installations can use the Fernet vault:

```bash
WAIT_SECRETS_BACKEND=fernet
WAIT_VAULT_PATH=.wait-local-agent/vault
wait-local-agent secrets init
wait-local-agent secrets set WAIT_HALOPSA_CLIENT_SECRET '<secret>'
```

`wait-local-agent secrets list` prints names only. Treat `secrets get` output
as sensitive. The vault path and all credential values remain local.

For a new vault, `WAIT_VAULT_KEY` may provide an externally managed Fernet
key, so the key file does not need to be written to disk. Do not set it against
an existing vault that was created with a local key file unless that vault has
been explicitly migrated to the external key; otherwise the existing entries
will not decrypt.

To migrate an existing local-key vault, set the externally managed key and run
the explicit migration command. It decrypts the existing payload, re-encrypts
it with `WAIT_VAULT_KEY`, and retains `vault.key` so old key material is never
silently deleted or overwritten:

```bash
export WAIT_VAULT_KEY='[operator-supplied Fernet key]'
wait-local-agent secrets migrate-external-key
```

The command prompts for the existing key without echoing it. Back up both key
materials before migration and verify `secrets list` afterward.

Encrypted backups require a vault-backed `WAIT_BACKUP_FERNET_KEY`:

```bash
wait-local-agent secrets set WAIT_BACKUP_FERNET_KEY '<generated-fernet-key>'
wait-local-agent backup create .wait-local-agent/backups/state.db.enc --encrypt
wait-local-agent backup restore .wait-local-agent/backups/state.db.enc --encrypted
```

The appliance can also create encrypted backups from its scheduler. Create an
`Appliance backup` schedule in Scheduled Jobs, or use the admin-only
`POST /backups/run` endpoint for an on-demand run. Scheduled and on-demand
runs are recorded in the operator backup status surface; the default retention
is seven generated backup files. An administrator can override it with the
appliance configuration key `backup.retention_count`.

Backup history records metadata only. The API never streams backup contents or
the Fernet key. A successful creation is not proof that the artifact can be
recovered; use `run_restore_exercise` (or the restore-exercise API) and inspect
the last evidence reference in `GET /backups`.

The backup API and CLI operate on the local SQLite state. Restore is an
operator action and should be tested against a copy or recovery environment
before replacing active state. Backup and restore paths must remain inside the
configured local data directory or the optional `WAIT_BACKUP_DIR`; paths
outside those settings-controlled roots are rejected.

## What to copy off-box

To survive loss of the appliance host or its mounted volumes, copy all of the
following to protected off-box storage:

- every encrypted backup file from the configured backup directory;
- the `WAIT_VAULT_KEY` value from the `.env` file, stored as a secret; and
- the complete vault directory at `WAIT_VAULT_PATH`.

Keep the backup files, vault key, and vault directory under the same access
controls. A backup file without the vault key and vault directory cannot be
used to restore encrypted state.

## Restore rehearsal

At least periodically, copy the backup file, vault key, and vault directory to
a separate recovery environment, configure the same data and vault paths, and
run a restore exercise against the copied artifact. Confirm the exercise
passes its integrity and row-count checks, then record the date and artifact
used. Do not replace the live database as part of the rehearsal.
