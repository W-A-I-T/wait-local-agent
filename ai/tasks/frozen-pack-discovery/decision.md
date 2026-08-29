# Decision

Prefer an explicit frozen first-party module seed over weakening the CI gate or replacing the dynamic pack loader. This repairs the packaged-runtime discovery difference while preserving the current extension architecture and making the built executable, not source inspection, the final proof.
