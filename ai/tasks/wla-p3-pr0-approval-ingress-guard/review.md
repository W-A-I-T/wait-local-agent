# Review — approval ingress guard

Implementation complete; Claude final gate pending.

The guard rejects only the caller-supplied `_approval_completed` key. The
internal `complete_approval` path continues to call `_safe_run` directly, so
approved provider writes remain available without passing through `invoke`.
