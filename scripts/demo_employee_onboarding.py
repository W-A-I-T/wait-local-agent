#!/usr/bin/env python3
"""Run the canonical employee-onboarding scenario in an isolated local fixture."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from wait_local_agent.config import Settings  # noqa: E402
from wait_local_agent.employee_onboarding_demo import run_employee_onboarding_demo  # noqa: E402
from wait_local_agent.store import Store  # noqa: E402


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="wait-employee-onboarding-") as directory:
        data_path = Path(directory)
        settings = Settings(
            data_path=data_path / "state.db",
            allowed_doc_root=ROOT / "examples/sample_docs",
            allow_write_actions=False,
            allow_http_probing=False,
            allow_cloud_fallback=False,
            allow_llm_inference=False,
            offline_mode=True,
            local_model_provider="deterministic",
            local_model_base_url="",
            local_model_name="",
            local_model_timeout_seconds=20.0,
            vector_backend="sqlite",
            scheduler_enabled=False,
            rate_limit_enabled=False,
            client_id="",
            demo_mode=True,
        )
        store = Store(settings.data_path)
        store.create_client("acme", "Demo client")
        store.ingest_ticket_file(ROOT / "examples/sample_tickets/tickets.json", client_id="acme")
        with store._connect() as connection:  # noqa: SLF001 - isolated fixture tenant binding.
            connection.execute(
                "update tickets set client_id = ? where id = ?",
                ("acme", "TCK-1001"),
            )
        blueprint = json.loads(
            (ROOT / "examples/consultant/employee-onboarding-blueprint.json").read_text(encoding="utf-8")
        )
        result = run_employee_onboarding_demo(
            store=store,
            settings=settings,
            blueprint_payload=blueprint,
        )
        print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
