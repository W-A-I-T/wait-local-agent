# ScalePad

ScalePad exposes separately mapped, read-only Core client inventory, ControlMap
risk summaries and compliance health, and Lifecycle Manager goals and
assessments. Writes and unscoped reads are unavailable.

```text
WAIT_SCALEPAD_BASE_URL=
WAIT_SCALEPAD_API_KEY=
WAIT_SCALEPAD_CLIENT_MAP_JSON={"acme":123}
WAIT_SCALEPAD_RISK_TENANT_MAP_JSON={"acme":456}
WAIT_SCALEPAD_COMPLIANCE_CLIENT_MAP_JSON={"acme":789}
WAIT_SCALEPAD_LIFECYCLE_CLIENT_MAP_JSON={"acme":321}
WAIT_ALLOW_HTTP_PROBING=true
```

Each provider identifier is checked in its own scope; IDs are never inferred
to be interchangeable. Mocked adapter tests cover the bounded read contract.
Live ScalePad verification is not claimed.

