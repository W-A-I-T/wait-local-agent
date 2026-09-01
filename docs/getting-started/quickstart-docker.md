# Docker Quickstart

## 1. Production appliance (image, recommended for MSP operation)

The production appliance is one published image containing the FastAPI service
and compiled dashboard. It does not require Git, Node.js, npm, or a repository
checkout on the customer machine.

Follow the [production installation guide](production-install.md), or run the
pull-based installer on a Linux host with Docker and Compose v2:

```bash
curl -fsSL https://raw.githubusercontent.com/W-A-I-T/wait-local-agent/main/scripts/install.sh \
  | bash -s -- --version stable
```

The installer creates `/opt/wait-local-agent`, generates bootstrap credentials,
downloads the production Compose file, starts the versioned image, and waits
for `http://127.0.0.1:8788/healthz`. It prints the one-time administrator token
once. Keep the `.env` file private.

## 2. Development stack (source and Vite, contributors)

The development Compose file keeps the source checkout mounted and runs the
Vite dashboard separately so contributors can edit and reload code locally.
This path is not the production appliance.

Requirements:

- Docker with Compose v2
- Git
- Optional Python 3.12 environment for host-side CLI commands

```bash
git clone https://github.com/W-A-I-T/wait-local-agent.git
cd wait-local-agent
cp .env.example .env
docker compose up --build
```

Open:

- Dashboard: `http://127.0.0.1:5173`
- API: `http://127.0.0.1:8788`

The API state is kept in the `wait-local-agent-data` Docker volume. A fresh
non-demo start needs an administrator credential; set
`WAIT_DEMO_MODE=true` only for the bounded local demo. Demo seeding is explicit:

```bash
docker compose exec api wait-local-agent demo seed --client-id acme
```

For backups, vault setup, connectors, and scheduled workflows, see the
[configuration guide](configuration.md) and [operations documentation](../README.md#operations).

## 3. Desktop app (non-MSP surface)

The desktop bundle is a separate local UI and server-sidecar distribution. It
is intended for individual local use and is not the MSP production appliance.
See the [desktop installation guide](desktop-install.md).
