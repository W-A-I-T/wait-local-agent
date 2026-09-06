# Linux browser acceptance

The `linux-personas` CI job installs the Python application on Linux, builds the
TypeScript UI, and exercises both through Chromium. It uses the production SPA
and API routes with a temporary SQLite database and encrypted local vault.
It does not require a native desktop shell.

From a checkout, use Python 3.12 and the Node version in `.github/workflows/test.yml`:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
npm --prefix ui ci
npm --prefix ui run build
cd ui
npx playwright install --with-deps chromium
npm run test:personas
```

To run one journey independently:

```bash
npm run test:personas -- end-user-support.spec.ts
```

The configuration starts `scripts/browser_fixture_server.py` on loopback, then
removes its database and fixture project when the test server stops. It replaces
inherited `WAIT_*` configuration in that child process; it never loads an existing
appliance database or connector credentials. Port 18790 must be free. Set
`WAIT_BROWSER_PYTHON` to the Python executable when it is not on `PATH`.

| Persona | Browser actions and asserted outcomes |
| --- | --- |
| MSP administrator | Invalid and valid login, mode selection and persistence, scoped account creation, sign out, honest unconfigured discovery |
| Technician | Open a local requester ticket, start Technician Chat, investigate, revisit stored evidence, reject an unsupported command, close the session |
| Restricted viewer | Admin deep-link denial, denied principal API, client isolation, unavailable privileged chat controls |
| Requester | Required-field validation, submit and follow up, read an operator reply after reload, escalate, deny another requester/client's ticket, clear private state |
| Solutions architect | Answer the actual guided discovery schema, save and resume the resulting blueprint, build a local review package, reject deployment validation of design-only work |
| Founder | Scan a disposable project, preview metadata, cancel before upload, confirm a handoff, recover from a fixture provider failure |
| Appliance operator | Run a local collector, export its evidence, download diagnostics and audit records |

The Founder transport is the only provider mock: its first upload returns 503,
then a retry succeeds. It rejects outgoing source content, ignored-file content,
environment values and connector tokens. Scan, preview, confirmation, storage,
privacy projection and audit use the shipped services. A successful fixture
handoff is not live-provider or production verification.

The responsive specification checks 1440×900, 1024×768, 768×1024 and 390×844.
It covers onboarding keyboard behavior, long client names, whole-page overflow,
named controls and automated WCAG A/AA rules on operational, architect, Founder
and requester screens. Screenshots and browser diagnostics are retained in the
`linux-persona-acceptance` CI artifact; failures also retain Playwright traces.
Automated accessibility checks supplement visual and keyboard review; they do
not establish full assistive-technology conformance.

The production-image path is tested separately:

```bash
WAIT_PROD_COMPOSE_RUN_BROWSER=true scripts/test_prod_compose.sh
```

That script builds the production image, verifies health and the compiled SPA,
recreates the container to check named-volume persistence, then runs the existing
setup and authorization browser suite. It uses a disposable Fernet key and
raises rate limits only in a temporary test override. Authentication and secure
cookie defaults remain enabled. Live writes remain disabled.

The published-image installer and signed upgrade process are described in the
[production installation guide](../getting-started/production-install.md).
Building a local CI image does not verify a published release signature, an
external provider tenant or an upgrade of a real appliance.
