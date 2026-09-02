# Frontend API contracts

The UI contract tests compare static `apiFetch` and `apiFetchBlob` calls with a
trimmed OpenAPI route snapshot. Regenerate the snapshot from the local FastAPI
application after an intentional backend route change:

```bash
./.venv/bin/python scripts/export_openapi.py > ui/tests/fixtures/openapi.json
```

The generator uses demo mode and temporary state, and emits only `paths` and
their HTTP methods. Do not add response examples, configuration values, or
credentials to the checked-in fixture.
