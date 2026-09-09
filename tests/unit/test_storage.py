"""Unit tests for filesystem and SQLite run storage."""

from pathlib import Path

import aiosqlite
import pytest

from agentgym.core.trajectory import TrajectoryEventType
from agentgym.runner.recorder import TrajectoryRecorder
from agentgym.storage.filesystem import RunStore, StorageIntegrityError, sha256_json
from agentgym.storage.sqlite import IndexStore


def _run_inputs() -> tuple[dict[str, object], dict[str, object], TrajectoryRecorder]:
    initial = {"id": "initial", "resources": {"pages": {}}}
    final = {"id": "final", "resources": {"pages": {"page-1": {"version": 2}}}}
    recorder = TrajectoryRecorder()
    recorder.append(TrajectoryEventType.RUN_STARTED, "runner", {})
    return initial, final, recorder


def test_run_store_writes_atomic_layout_and_hashes(tmp_path: Path) -> None:
    initial, final, recorder = _run_inputs()
    run_dir = tmp_path / "runs" / "run-001"

    manifest = RunStore().store_run(
        run_dir,
        task_id="task-001",
        package_id="package-001",
        initial_state=initial,
        final_state=final,
        trajectory=recorder,
        verification={"passed": True},
        domain_version="0.1",
        runtime={"name": "test", "version": "1"},
        model={"provider": "fake", "identifier": "fake-1"},
        seed=42,
        status="pass",
    )

    assert set(manifest) >= {
        "task_hash",
        "package_hash",
        "world_snapshot_hash",
        "runtime",
        "model",
        "seed",
        "initial_state_hash",
        "final_state_hash",
    }
    assert manifest["world_snapshot_hash"] == sha256_json(initial)
    assert (run_dir / "initial-state.json").is_file()
    assert (run_dir / "final-state.json").is_file()
    assert (run_dir / "trajectory.jsonl").is_file()
    assert (run_dir / "verification.json").is_file()
    assert (run_dir / "manifest.json").is_file()
    assert not list(run_dir.glob(".*.tmp"))


def test_run_store_rejects_tampered_final_state(tmp_path: Path) -> None:
    initial, final, recorder = _run_inputs()
    run_dir = tmp_path / "run"
    RunStore().store_run(
        run_dir,
        task_id="task-001",
        package_id="package-001",
        initial_state=initial,
        final_state=final,
        trajectory=recorder,
        verification={},
    )
    (run_dir / "final-state.json").write_text('{"tampered":true}', encoding="utf-8")

    with pytest.raises(StorageIntegrityError, match=r"final-state\.json"):
        RunStore().load_run(run_dir)


async def test_index_store_initializes_inserts_and_queries(tmp_path: Path) -> None:
    path = tmp_path / "index.sqlite"
    store = IndexStore(path)
    await store.init_db()
    await store.insert_run(
        {
            "run_id": "run-001",
            "task_id": "task-001",
            "package_id": "package-001",
            "status": "pass",
            "created_at": "2026-09-06T00:00:00+00:00",
            "task_hash": "a" * 64,
            "package_hash": "b" * 64,
            "domain_version": "0.1",
            "world_snapshot_hash": "c" * 64,
            "runtime": {"name": "test", "version": "1"},
            "model": {"provider": "fake", "identifier": "fake-1"},
            "seed": 42,
        }
    )

    by_package = await store.runs_by_package("package-001")
    latest = await store.latest_run_ids(1)

    assert by_package[0]["run_id"] == "run-001"
    assert latest == ["run-001"]
    async with aiosqlite.connect(path) as database:
        tables = {
            row[0]
            async for row in await database.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        journal_mode = (await (await database.execute("PRAGMA journal_mode")).fetchone())[0]
    assert {
        "runs",
        "tasks",
        "packages",
        "generations",
        "mutations",
        "diagnoses",
        "evaluations",
    } <= tables
    assert journal_mode.lower() == "wal"
