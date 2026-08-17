# Review — `wla-f2-write-verify`

Implementation is complete and awaiting Claude's final gate.

The provider write return contract is preserved: only the approval execution
functions call `verify_write`, and they do so only after `execute_write`
returns `succeeded`. The read-back compares only fields exposed by the
normalized provider models. Identifier-only HaloPSA status, HaloPSA assignment
fields, ConnectWise status/assignment IDs, and mixed ConnectWise ID updates
remain `submitted`; a failed or mismatched GET is `unverified`.

The three load-bearing idempotency guards include every physically executed
status. Verification evidence contains source, outcome, and comparison state
without copying note bodies, credentials, or raw provider response bodies.

Claude should run the contract's full pytest/coverage, mypy, ruff, and bandit
gate before merge. Human authority remains required for merge and deploy.
