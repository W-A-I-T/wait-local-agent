# Architecture

WAIT Local Agent is a local-first runtime composed of five layers.

## Runtime

- FastAPI operator API
- Typer command line interface
- SQLite state store
- Safe-by-default configuration

## Knowledge

- Local file ingestion
- Documentation chunks with stable source references
- Citation-first retrieval contracts
- SQLite FTS5 keyword retrieval
- Planned vector backends: Qdrant and pgvector

## Model Providers

- Deterministic provider for repeatable offline demos and tests
- Optional local OpenAI-compatible chat-completions client
- Ollama profile for lightweight local inference
- vLLM profile for heavier production inference
- Local inference is disabled unless `WAIT_ALLOW_LLM_INFERENCE=true`
- Cloud fallback is not part of the default model path

When enabled, the provider posts ticket context and the top local source excerpts
to `{WAIT_LOCAL_MODEL_BASE_URL}/chat/completions`. The model is asked to return
JSON with `summary` and `suggested_response`. Timeouts, connection errors,
non-success responses, empty responses, and malformed JSON all fall back to the
deterministic provider so ticket summaries remain available offline.

## MSP Interfaces

- PSA tickets
- RMM events and script recommendations
- Documentation systems
- Microsoft 365 and Entra context
- Email and chat threads
- Local runbooks and scripts

## Control Plane

- Human approval queue
- Immutable audit events
- Policy gates for write actions
- Release hygiene checks before publishing
