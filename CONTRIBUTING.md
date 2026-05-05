# Contributing

Thanks for helping improve WAIT Local Agent.

## Development

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
python -m pytest
ruff check .
```

For the UI:

```bash
cd ui
npm install
npm run test
npm run build
```

## Public Surfaces

Public docs, pull requests, release notes, and examples should describe product behavior and implementation choices directly. Do not add implementation-tool credit lines, generated-by footers, or public attribution banners.

