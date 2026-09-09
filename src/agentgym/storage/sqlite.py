"""Async SQLite indexes for filesystem-backed run artifacts.

This module is deliberately non-authoritative.  The JSON files written by
``storage.filesystem.RunStore`` are the source of truth; SQLite only provides
cheap lookup indexes and may be rebuilt from those files.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import aiosqlite

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    package_id TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    task_hash TEXT,
    package_hash TEXT,
    domain_version TEXT,
    world_snapshot_hash TEXT,
    runtime_name TEXT,
    runtime_version TEXT,
    model_provider TEXT,
    model_identifier TEXT,
    seed INTEGER
);

CREATE TABLE IF NOT EXISTS tasks (
    task_id TEXT PRIMARY KEY,
    task_hash TEXT,
    domain_version TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS packages (
    package_id TEXT PRIMARY KEY,
    package_hash TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS generations (
    generation_id TEXT PRIMARY KEY,
    package_id TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS mutations (
    mutation_id TEXT PRIMARY KEY,
    package_id TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS diagnoses (
    diagnosis_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS evaluations (
    evaluation_id TEXT PRIMARY KEY,
    run_id TEXT,
    status TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_runs_package_created
    ON runs (package_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_runs_created
    ON runs (created_at DESC);
"""


class IndexStore:
    """Maintain a rebuildable, async SQLite index over run manifests."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    async def init_db(self) -> None:
        """Create the v0.1 index tables and enable WAL mode."""

        self.path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self.path) as database:
            await database.execute("PRAGMA journal_mode=WAL")
            await database.execute("PRAGMA synchronous=NORMAL")
            await database.executescript(_SCHEMA)
            await database.commit()

    async def insert_run(self, manifest: Mapping[str, Any] | object) -> None:
        """Insert or replace the searchable summary of one run manifest."""

        values = _mapping_value(manifest)
        run_id = _required_text(values, "run_id")
        task_id = _required_text(values, "task_id")
        package_id = _required_text(values, "package_id")
        status = str(values.get("status", "unknown"))
        created_at = str(values.get("created_at", datetime.now(UTC).isoformat()))
        runtime = _mapping_value(values.get("runtime"))
        model = _mapping_value(values.get("model"))

        await self.init_db()
        async with aiosqlite.connect(self.path) as database:
            await database.execute(
                """
                INSERT OR REPLACE INTO runs (
                    run_id, task_id, package_id, status, created_at,
                    task_hash, package_hash, domain_version, world_snapshot_hash,
                    runtime_name, runtime_version, model_provider,
                    model_identifier, seed
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    task_id,
                    package_id,
                    status,
                    created_at,
                    _optional_text(values.get("task_hash")),
                    _optional_text(values.get("package_hash")),
                    _optional_text(values.get("domain_version")),
                    _optional_text(values.get("world_snapshot_hash")),
                    _optional_text(runtime.get("name")),
                    _optional_text(runtime.get("version")),
                    _optional_text(model.get("provider")),
                    _optional_text(model.get("identifier")),
                    _optional_seed(values.get("seed")),
                ),
            )
            await database.execute(
                """
                INSERT OR REPLACE INTO tasks (task_id, task_hash, domain_version, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    task_id,
                    _optional_text(values.get("task_hash")),
                    _optional_text(values.get("domain_version")),
                    created_at,
                ),
            )
            await database.execute(
                """
                INSERT OR REPLACE INTO packages (package_id, package_hash, created_at)
                VALUES (?, ?, ?)
                """,
                (package_id, _optional_text(values.get("package_hash")), created_at),
            )
            await database.commit()

    async def runs_by_package(self, package_id: str) -> list[dict[str, Any]]:
        """Return indexed run summaries for ``package_id`` newest first."""

        await self.init_db()
        async with aiosqlite.connect(self.path) as database:
            database.row_factory = aiosqlite.Row
            cursor = await database.execute(
                "SELECT * FROM runs WHERE package_id = ? ORDER BY created_at DESC, run_id DESC",
                (package_id,),
            )
            rows = await cursor.fetchall()
            await cursor.close()
        return [dict(row) for row in rows]

    async def latest_run_ids(self, limit: int = 10) -> list[str]:
        """Return up to ``limit`` run ids ordered by creation time."""

        if limit < 0:
            raise ValueError("limit must be non-negative")
        await self.init_db()
        async with aiosqlite.connect(self.path) as database:
            cursor = await database.execute(
                "SELECT run_id FROM runs ORDER BY created_at DESC, run_id DESC LIMIT ?",
                (limit,),
            )
            rows = await cursor.fetchall()
            await cursor.close()
        return [str(row[0]) for row in rows]


async def init_db(path: str | Path) -> IndexStore:
    """Convenience factory that initializes and returns an ``IndexStore``."""

    store = IndexStore(path)
    await store.init_db()
    return store


def _mapping_value(value: object) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return {str(key): item for key, item in value.items()}
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump(mode="json")
        if isinstance(dumped, Mapping):
            return {str(key): item for key, item in dumped.items()}
    return {}


def _required_text(values: Mapping[str, Any], key: str) -> str:
    value = values.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"manifest requires a non-empty {key}")
    return value


def _optional_text(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _optional_seed(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


__all__ = ["IndexStore", "init_db"]
