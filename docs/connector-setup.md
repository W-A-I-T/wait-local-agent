# Connector Setup

WAIT Local Agent keeps connectors conservative by default. Reads and writes are separate gates.

## Global gates

| Gate | Default | Required for |
| --- | --- | --- |
| `WAIT_ALLOW_HTTP_PROBING` | `false` | Any outbound HaloPSA or Hudu HTTP call |
| `WAIT_ALLOW_WRITE_ACTIONS` | `false` | Any live connector mutation |
| Approval request | `pending` by default | Every HaloPSA live write |

A fresh install can draft approval requests but cannot mutate HaloPSA.

## API authentication

Local demo mode is open on loopback/LAN only when both conditions are true:

```text
WAIT_DEMO_MODE=true
WAIT_API_TOKEN=
```

For any shared environment:

```bash
WAIT_DEMO_MODE=false
WAIT_API_TOKEN=<strong-local-token>
```

Requests then require:

```bash
curl -H 'Authorization: Bearer <strong-local-token>' http://127.0.0.1:8788/health
```

## Secrets backend

Default development path:

```text
WAIT_SECRETS_BACKEND=env
```

Encrypted local vault path:

```bash
WAIT_SECRETS_BACKEND=fernet
WAIT_VAULT_PATH=.wait-local-agent/vault
wait-local-agent secrets init
wait-local-agent secrets set WAIT_HALOPSA_CLIENT_SECRET '<secret>'
wait-local-agent secrets list
```

`secrets list` prints key names only. `secrets get` exists for local operator recovery and should not be used in shared shell history.

## HaloPSA read setup

Required values:

```text
WAIT_HALOPSA_BASE_URL=
WAIT_HALOPSA_CLIENT_ID=
WAIT_HALOPSA_CLIENT_SECRET=
WAIT_HALOPSA_TENANT=
WAIT_HALOPSA_TOKEN_URL=
WAIT_ALLOW_HTTP_PROBING=true
```

Validation commands:

```bash
wait-local-agent connectors halopsa-health
wait-local-agent connectors halopsa-tickets
wait-local-agent connectors halopsa-ticket <ticket-id>
wait-local-agent connectors halopsa-notes <ticket-id>
wait-local-agent connectors halopsa-clients
wait-local-agent connectors halopsa-categories
```

## HaloPSA write setup

Live HaloPSA writes require all of the following:

1. `WAIT_ALLOW_HTTP_PROBING=true`
2. `WAIT_ALLOW_WRITE_ACTIONS=true`
3. credentials configured
4. a pending draft created first
5. explicit technician approval

Draft example:

```bash
wait-local-agent connectors draft-halopsa HALO-1002 add_note \
  --field note='Internal note ready for review'
wait-local-agent approvals show 1
wait-local-agent approvals edit-field 1 note='Reviewed by technician'
wait-local-agent approvals update 1 approved 'approved by technician'
```

The write execution path records sanitized metadata only: action type, endpoint, status, HTTP status code, remote id when available, and result message.

## Hudu read-only setup

Hudu is documentation context in the public repo. There is no Hudu write surface.

```text
WAIT_HUDU_BASE_URL=
WAIT_HUDU_API_KEY=
WAIT_ALLOW_HTTP_PROBING=true
```

Validation commands:

```bash
wait-local-agent connectors hudu-health
wait-local-agent connectors hudu-companies
wait-local-agent connectors hudu-articles
wait-local-agent connectors hudu-article <article-id>
wait-local-agent connectors hudu-folders
```
