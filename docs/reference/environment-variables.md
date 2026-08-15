# Environment Variables

Configuration is loaded by `src/wait_local_agent/config.py` into the immutable
`Settings` object. It covers storage, authentication, safety gates, model and
retrieval options, vault, scheduler/rate limits, MCP, updates, communication,
tenant maps, and connector credentials.

`.env.example` is a convenient starting point, but it may lag
`src/wait_local_agent/config.py`; the file of record is `config.py`. New or
changed variables must therefore be checked there before being documented or
used.

Important safety controls default closed:

```text
WAIT_ALLOW_HTTP_PROBING=false
WAIT_ALLOW_WRITE_ACTIONS=false
WAIT_ALLOW_CLOUD_FALLBACK=false
WAIT_ALLOW_LLM_INFERENCE=false
WAIT_OFFLINE_MODE=false
WAIT_SECRETS_BACKEND=env
WAIT_DEMO_MODE=true
```

Keep credentials in the environment or configured local vault. Do not place
secrets, bearer tokens, provider credentials, or client data in action payloads,
docs, or audit examples.

