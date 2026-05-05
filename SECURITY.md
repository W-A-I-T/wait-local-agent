# Security

WAIT Local Agent is local-first and defaults to conservative behavior.

## Defaults

- Write actions are disabled unless explicitly enabled.
- External HTTP probing is disabled unless explicitly enabled.
- Cloud fallback is disabled unless explicitly enabled.
- Sample data is synthetic.

## Reporting

Please report security issues privately to the maintainers before opening public issues.

## Operator Responsibilities

- Keep secrets in environment-specific secret stores.
- Review connector scopes before enabling integrations.
- Require human approval before enabling workflow execution.
- Keep audit logs retained according to client and regulatory requirements.

