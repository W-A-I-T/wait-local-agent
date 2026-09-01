# Microsoft sign-in with Entra ID

WAIT Local Agent supports Microsoft 365 sign-in with the authorization-code
flow and PKCE. It is single-tenant by design: the configured tenant ID is used
to build the authority and is checked again against the token's `tid` claim.

## Register the application

In Microsoft Entra admin center, create an app registration for **Accounts in
this organizational directory only**. Add a **Web** redirect URI:

```text
{WAIT_OIDC_PUBLIC_BASE_URL}/auth/oidc/callback
```

Use the exact configured casing and path. Production redirect URIs should use
HTTPS. Entra permits HTTP for localhost during local development and supports
private hostnames when the reply URL rules for the registration are satisfied;
do not use a wildcard URL.

Create a client secret and enter it in **Settings → People & Access →
Microsoft sign-in**. The secret is write-only in the dashboard and is stored in
the encrypted local vault. Do not put it in `.env` or an audit record.

The first-boot defaults are:

```text
WAIT_OIDC_TENANT_ID=
WAIT_OIDC_CLIENT_ID=
WAIT_OIDC_PUBLIC_BASE_URL=
WAIT_OIDC_AUTO_PROVISION_CLIENT_ID=
```

After the settings are saved, the database values take precedence over these
environment values. The public base URL must be the URL users actually use to
reach the appliance; it is never inferred from the request `Host` header.

## Link access

OIDC sign-in is fail-closed. An administrator can link an Entra object ID to
an existing principal, or add an email invite. The first successful login for
an email invite consumes that invite and replaces it with the permanent Entra
object ID link.

Auto-provisioning is off by default. If enabled, only users whose token `tid`
equals the explicit configured tenant are provisioned, with viewer access to
the configured WAIT client. Email domains are never used as a tenant or access
rule.

Ensure the hostname in `WAIT_OIDC_PUBLIC_BASE_URL` is included in
`WAIT_TRUSTED_HOSTS`; otherwise TrustedHostMiddleware will reject the callback.

See Microsoft's [reply URL restrictions](https://learn.microsoft.com/en-us/entra/identity-platform/reply-url)
when registering localhost or private-hostname URLs.
