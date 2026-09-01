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

The backup API and CLI operate on the local SQLite state. Restore is an
operator action and should be tested against a copy or recovery environment
before replacing active state. Backup and restore paths must remain inside the
configured local data directory; paths outside it are rejected.
