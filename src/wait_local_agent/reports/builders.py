from __future__ import annotations

from dataclasses import asdict
from typing import Any

from wait_local_agent.reports.models import ReportSection
from wait_local_agent.store import Store


def build_collector_bundle_report(store: Store, run_id: int) -> tuple[list[ReportSection], dict[str, Any]]:
    run = _require_run(store, run_id)
    assets = store.list_canonical_assets(run_id=run_id)
    observations = store.list_asset_observations(run_id=run_id)
    snapshots = store.list_config_snapshots(run_id=run_id)
    diffs = store.list_config_diffs(run_id=run_id)
    restores = store.list_restore_exercises(run_id=run_id)
    sections = [
        ReportSection(
            title="Collector Run Manifest",
            summary=f"{run.module_id} completed with status {run.status}.",
            findings=[
                {
                    "run_id": run_id,
                    "module_id": run.module_id,
                    "source_id": run.source_id,
                    "status": run.status,
                }
            ],
            evidence=[
                {"kind": "preview", "payload": run.preview_json},
                {"kind": "result", "payload": run.result_json},
            ],
        ),
        ReportSection(
            title="Canonical Assets",
            summary=f"{len(assets)} canonical asset records persisted.",
            findings=[asdict(asset) for asset in assets],
        ),
        ReportSection(
            title="Observations And Evidence",
            summary=(
                f"{len(observations)} observations, {len(snapshots)} snapshots, "
                f"{len(diffs)} diffs, {len(restores)} restore exercises."
            ),
            evidence=[
                {"type": "asset_observation", **asdict(item)} for item in observations
            ]
            + [{"type": "config_snapshot", **asdict(item)} for item in snapshots]
            + [{"type": "config_diff", **asdict(item)} for item in diffs]
            + [{"type": "restore_exercise", **asdict(item)} for item in restores],
        ),
    ]
    return sections, _metadata(run_id, run.module_id, len(assets), len(observations))


def build_appliance_hardening_report(
    store: Store,
    run_id: int,
) -> tuple[list[ReportSection], dict[str, Any]]:
    run = _require_run(store, run_id)
    diffs = store.list_config_diffs(run_id=run_id)
    snapshots = store.list_config_snapshots(run_id=run_id)
    findings = [asdict(diff) for diff in diffs]
    sections = [
        ReportSection(
            title="Configuration Snapshot Coverage",
            summary=f"{len(snapshots)} configuration snapshots are attached to this run.",
            evidence=[asdict(snapshot) for snapshot in snapshots],
        ),
        ReportSection(
            title="Configuration Drift",
            summary=f"{len(diffs)} configuration diffs are attached to this run.",
            findings=findings,
            recommendations=[
                "Review unknown or regression-classified diffs before relying on the bundle."
            ]
            if diffs
            else [],
        ),
    ]
    return sections, _metadata(run_id, run.module_id, 0, 0)


def build_restore_evidence_report(
    store: Store,
    run_id: int,
) -> tuple[list[ReportSection], dict[str, Any]]:
    run = _require_run(store, run_id)
    restores = store.list_restore_exercises(run_id=run_id)
    sections = [
        ReportSection(
            title="Restore Exercises",
            summary=f"{len(restores)} restore exercises are attached to this run.",
            findings=[asdict(item) for item in restores],
            recommendations=["Repeat failed restore exercises after remediation."] if any(
                item.status != "passed" for item in restores
            ) else [],
        )
    ]
    return sections, _metadata(run_id, run.module_id, 0, 0)


def _require_run(store: Store, run_id: int):
    run = store.get_collector_run(run_id)
    if run is None:
        raise KeyError(run_id)
    return run


def _metadata(run_id: int, module_id: str, asset_count: int, observation_count: int) -> dict[str, Any]:
    return {
        "collector_run_id": run_id,
        "module_id": module_id,
        "asset_count": asset_count,
        "observation_count": observation_count,
    }
