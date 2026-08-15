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

Encrypted backups require a vault-backed `WAIT_BACKUP_FERNET_KEY`:

```bash
wait-local-agent secrets set WAIT_BACKUP_FERNET_KEY '<generated-fernet-key>'
wait-local-agent backup create .wait-local-agent/backups/state.db.enc --encrypt
wait-local-agent backup restore .wait-local-agent/backups/state.db.enc --encrypted
```

The backup API and CLI operate on the local SQLite state. Restore is an
operator action and should be tested against a copy or recovery environment
before replacing active state.

