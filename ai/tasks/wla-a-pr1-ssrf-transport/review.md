# Review

The implementation follows the reconciled contract without changing provider
clients, `mcp_client.py`, storage, API wiring, UI, tickets, or connector
instance persistence.

Security checks reviewed:

- URL parsing is bounded, credential-free, allowlisted, HTTPS-for-non-loopback,
  and does not perform DNS.
- Every request repeats the URL gate, replaces a caller-supplied `Host`, and
  resolves exactly once before connecting to the validated numeric address.
- IPv4-mapped addresses recurse into IPv4 policy; multicast, reserved,
  metadata, NAT64, 6to4, Teredo, private, and other non-global addresses fail
  closed.
- TLS verification remains enabled, proxy environment variables are ignored,
  redirects and HTTP/2 are disabled, and SNI uses the original validated
  hostname through the httpcore `sni_hostname` extension.
- Raw response bytes are capped during iteration, non-identity encodings are
  rejected, and stream/transport closure is idempotent and performed on
  success, caller close, limit failure, and inner iteration failure.

No real network is used by the new tests. A-PR2 must validate the effective
Halo token URL immediately before its request, require that hostname in the
same allowlist, and send that request through this pinned client.
