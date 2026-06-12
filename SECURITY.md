# Security

WAIT Local Agent is local-first and defaults to conservative behavior.

## Defaults

- Live connector writes are disabled unless explicitly enabled.
- External HTTP probing is disabled unless explicitly enabled.
- Cloud fallback is disabled unless explicitly enabled.
- Local model inference is disabled unless explicitly enabled.
- Sample and demo data are synthetic.
- Hudu is read-only in the public repo.

## API access

Demo mode allows local unauthenticated API access only when `WAIT_DEMO_MODE=true` and `WAIT_API_TOKEN` is empty.

For any shared host, LAN, or production-style install, set:

```text
WAIT_DEMO_MODE=false
WAIT_API_TOKEN=<strong-local-token>
```

API callers must then send:

```text
Authorization: Bearer <strong-local-token>
```

## Secrets

Environment variables remain supported for local demos. For longer-lived installs, use the local Fernet vault:

```bash
WAIT_SECRETS_BACKEND=fernet
wait-local-agent secrets init
wait-local-agent secrets set WAIT_HALOPSA_CLIENT_SECRET '<secret>'
wait-local-agent secrets list
```

Do not commit `.env`, vault keys, encrypted vault files, connector credentials, screenshots containing credentials, or client ticket bodies.

## Reporting

Please report sensitive security issues privately to the maintainers before opening public issues. Public issues are appropriate for non-sensitive hardening requests only.

## Operator responsibilities

- Keep API tokens and connector credentials in environment-specific secret stores or the local vault.
- Review connector scopes before enabling integrations.
- Require human approval before connector execution.
- Keep `WAIT_ALLOW_WRITE_ACTIONS=false` unless live execution is actively being tested or operated.
- Retain audit logs according to client and regulatory requirements.
- Validate dependency and license changes before release.
