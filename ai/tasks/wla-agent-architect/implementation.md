# Implementation record

- Added `architect_solution_blueprint` as a deterministic offline projection
  over the existing validated `SolutionBlueprint` model.
- Classified components as agents, child agents, deterministic workflows,
  connectors, MCP tools, and knowledge sources.
- Reused the existing WAIT tool and workflow catalogs when available and
  reported unresolved connector, tool, and runtime decisions explicitly.
- Added tenant-scoped `POST /consultant/blueprints/{id}/architect` with an
  audit event; it performs no external calls, writes, execution, or deploy.
- Added API/domain tests and documented the Microsoft-aligned decision model.
