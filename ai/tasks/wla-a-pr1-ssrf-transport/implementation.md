# Implementation

Implemented `wla-a-pr1-ssrf-transport` as an additive backend change.

- Added `wait_local_agent.net_security` with syntactic provider-origin
  validation, explicit globally-routable IP policy, DNS-result validation, a
  per-request pinned transport, SNI preservation, response streaming limits,
  identity encoding enforcement, and safe client construction.
- Added `Settings.connector_instance_allowed_hosts` and the
  `WAIT_CONNECTOR_INSTANCE_ALLOWED_HOSTS` CSV environment setting.
- Pinned the runtime dependencies to `httpx==0.28.1` and `httpcore==1.0.9`.
- Added focused no-network tests for the contract, including DNS rebinding
  defenses, stream lifecycle, client flags, configuration, and dependency
  pins.

The transport resolves with one `socket.getaddrinfo` call using
`AF_UNSPEC/SOCK_STREAM/IPPROTO_TCP`, validates every result, and puts the first
validated numeric address in the inner URL. It retains the validated original
authority in `Host` and sets the httpcore request extension
`sni_hostname=validated_hostname`; httpcore 1.0.9 consumes that extension as
the TLS `server_hostname` while the numeric URL controls TCP connection.

The real inner path creates `httpx.HTTPTransport(verify=True,
trust_env=False, http2=False)` per request and closes it when the bounded
response stream closes. This deliberate pool isolation prevents connection
reuse across requests and origins. The optional injected transport exists only
for deterministic tests.

Token URL validation and wiring remain A-PR2 responsibilities; this module
exposes the same origin validator and pinned client for that caller.
