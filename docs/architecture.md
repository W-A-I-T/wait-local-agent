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
- Planned vector backends: Qdrant and pgvector

## Model Providers

- Local OpenAI-compatible provider abstraction
- Ollama profile for lightweight local demos
- vLLM profile for heavier production inference
- Optional fallback services only when explicitly configured

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

