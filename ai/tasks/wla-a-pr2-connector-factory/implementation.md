# Implementation

Implemented `wla-a-pr2-connector-factory` as an additive leaf module.

- Added `wait_local_agent.connector_factory` with the `halopsa` and
  `connectwise` builder registry and `SUPPORTED_CONNECTOR_TYPES`.
- Added the active-status gate before vault access, strict duplicate-rejecting
  JSON credential parsing, exact provider schemas, fixed redacted errors, and
  non-secret config validation.
- Added per-instance `Settings` isolation through `dataclasses.replace`,
  forced `allow_write_actions=False`, cleared Halo write endpoints and token
  URL, inherited the transport policy fields, and always passed a
  `PinnedIpTransport` wrapper around the optional inner test transport.
- Added tests for the resolver seam, private-IP rejection before inner
  transport invocation, public-IP transport reachability, schema failures,
  active gating, isolation, same-origin token policy, and fixed errors.

## Isolation field map

The copied `Settings` container blanks these fields before restoring the
current instance's own provider fields:

```text
api_token, admin_token, tech_token, viewer_token, end_user_token,
communication_email_username, communication_email_password,
communication_sms_auth_token, ninjaone_access_token, datto_rmm_access_token,
ncentral_access_token, n_sight_api_key, timezest_api_key, scalepad_api_key,
kaseya_rmm_token_id, kaseya_rmm_token_secret, screenconnect_auth_secret,
halopsa_client_id, halopsa_client_secret, halopsa_tenant, halopsa_token_url,
hudu_api_key, itglue_api_key, confluence_api_token, notion_api_token,
sharepoint_access_token, work_iq_mcp_access_token, m365_access_token,
connectwise_company, connectwise_public_key, connectwise_private_key,
connectwise_client_id, syncro_api_token, servicenow_username,
servicenow_password, autotask_username, autotask_secret, license_key,
license_secret, pack_signing_secret, remote_model_api_key
```

The field set is derived from the live `Settings` dataclass for the credential
suffixes `_secret`, `_token`, `_password`, `_key`, and `_username`, with the
provider identifier exceptions listed above. For HaloPSA, the factory then
restores `halopsa_base_url`, `halopsa_client_id`, `halopsa_client_secret`, and
`halopsa_tenant`. For ConnectWise, it restores `connectwise_base_url`,
`connectwise_company`, `connectwise_public_key`, `connectwise_private_key`,
`connectwise_client_id`, and the validated effective `connectwise_api_version`.
`vault_path` is inherited and is not blanked.

The clients still receive a public `Settings` container in this version. A
narrow provider-configuration DTO is deliberately deferred to a follow-up
change; this implementation sanitizes the copied container and never logs
client settings or credential values.

No poller, scheduler, route, app wiring, provider-client change, store change,
network-security change, or config change was made.
