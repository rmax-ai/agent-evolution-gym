"""Filesystem-backed run artifacts.

The filesystem is the authoritative v0.1 run store.  SQLite is intentionally
only an index over these artifacts; a run can always be reconstructed from the
directory written here.
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel, ConfigDict

from agentgym.core.trajectory import TrajectoryEvent
from agentgym.runner.recorder import TrajectoryRecorder


class StorageIntegrityError(RuntimeError):
    """Raised when a persisted run artifact no longer matches its manifest."""


class RunManifest(BaseModel):
    """Reproducibility fields required by SPEC section 54."""

    model_config = ConfigDict(extra="allow")

    task_id: str
    task_hash: str
    package_id: str
    package_hash: str
    domain_version: str
    world_snapshot_hash: str
    runtime: dict[str, str]
    model: dict[str, str]
    seed: int


def canonical_json_bytes(value: object) -> bytes:
    """Serialize a JSON value deterministically for hashing and persistence."""

    normalized = _json_value(value)
    return json.dumps(
        normalized,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    """Return the lowercase SHA-256 digest for ``value``."""

    return hashlib.sha256(value).hexdigest()


def sha256_json(value: object) -> str:
    """Hash the canonical JSON representation of ``value``."""

    return sha256_bytes(canonical_json_bytes(value))


class RunStore:
    """Write and load the authoritative ``runs/<run-id>`` artifact layout."""

    def __init__(self, root: str | Path = "runs") -> None:
        self.root = Path(root)

    def store_run(
        self,
        run_dir: str | Path | None = None,
        *,
        run_id: str | None = None,
        task: object | None = None,
        package: object | None = None,
        task_id: str | None = None,
        package_id: str | None = None,
        initial_state: object | None = None,
        final_state: object | None = None,
        trajectory: Sequence[TrajectoryEvent | Mapping[str, Any]]
        | TrajectoryRecorder
        | str
        | Path
        | None = None,
        verification: object | None = None,
        domain_version: str | None = None,
        runtime: Mapping[str, Any] | None = None,
        model: Mapping[str, Any] | None = None,
        seed: int | None = None,
        status: str | None = None,
        manifest: Mapping[str, Any] | None = None,
        task_hash: str | None = None,
        package_hash: str | None = None,
        world_snapshot_hash: str | None = None,
    ) -> dict[str, Any]:
        """Persist all run artifacts atomically and return its manifest.

        ``task`` and ``package`` are optional source contracts used to compute
        their reproducibility hashes.  Callers that already have those hashes
        may provide ``task_hash`` and ``package_hash`` instead.  State hashes
        are always computed from the exact canonical bytes written to disk.
        """

        manifest_data = dict(_mapping_value(manifest)) if manifest is not None else {}
        resolved_run_id = _text_value(run_id) or _text_value(manifest_data.get("run_id"))
        target = self._resolve_run_dir(run_dir, resolved_run_id)
        if resolved_run_id is None:
            resolved_run_id = target.name

        resolved_task_id = (
            _text_value(task_id) or _text_value(manifest_data.get("task_id")) or _object_id(task)
        )
        resolved_package_id = (
            _text_value(package_id)
            or _text_value(manifest_data.get("package_id"))
            or _object_id(package)
        )
        if resolved_task_id is None or resolved_package_id is None:
            raise ValueError("store_run requires task_id and package_id")

        initial_bytes = canonical_json_bytes({} if initial_state is None else initial_state)
        final_value = initial_state if final_state is None else final_state
        final_bytes = canonical_json_bytes({} if final_value is None else final_value)
        trajectory_bytes = _trajectory_bytes(trajectory)
        verification_bytes = canonical_json_bytes({} if verification is None else verification)

        resolved_task_hash = _hash_source(
            task,
            task_hash or _text_value(manifest_data.get("task_hash")),
            fallback={"task_id": resolved_task_id},
        )
        resolved_package_hash = _hash_source(
            package,
            package_hash or _text_value(manifest_data.get("package_hash")),
            fallback={"package_id": resolved_package_id},
        )
        initial_hash = sha256_bytes(initial_bytes)
        final_hash = sha256_bytes(final_bytes)
        # The required §54 world hash names the initial world snapshot.  The
        # explicit artifact hashes below additionally cover the final state.
        resolved_world_hash = initial_hash
        if world_snapshot_hash is not None and world_snapshot_hash != resolved_world_hash:
            raise ValueError("world_snapshot_hash does not match initial-state.json")

        runtime_data = _string_mapping(
            runtime or _mapping_value(manifest_data.get("runtime")),
            defaults={"name": "unknown", "version": "unknown"},
        )
        model_data = _string_mapping(
            model or _mapping_value(manifest_data.get("model")),
            defaults={"provider": "unknown", "identifier": "unknown"},
        )
        seed_value = _seed_value(seed, manifest_data.get("seed"))
        domain_value = (
            _text_value(domain_version)
            or _text_value(manifest_data.get("domain_version"))
            or "unknown"
        )
        status_value = _text_value(status) or _text_value(manifest_data.get("status")) or "unknown"
        created_at = _text_value(manifest_data.get("created_at")) or datetime.now(UTC).isoformat()

        result: dict[str, Any] = {
            **manifest_data,
            "run_id": resolved_run_id,
            "task_id": resolved_task_id,
            "task_hash": resolved_task_hash,
            "package_id": resolved_package_id,
            "package_hash": resolved_package_hash,
            "domain_version": domain_value,
            "world_snapshot_hash": resolved_world_hash,
            "runtime": runtime_data,
            "model": model_data,
            "seed": seed_value,
            "status": status_value,
            "created_at": created_at,
            "initial_state_hash": initial_hash,
            "final_state_hash": final_hash,
        }
        RunManifest.model_validate(result)
        manifest_bytes = canonical_json_bytes(result)

        _atomic_write(target / "initial-state.json", initial_bytes)
        _atomic_write(target / "final-state.json", final_bytes)
        _atomic_write(target / "trajectory.jsonl", trajectory_bytes)
        _atomic_write(target / "verification.json", verification_bytes)
        _atomic_write(target / "manifest.json", manifest_bytes)
        return cast(dict[str, Any], json.loads(manifest_bytes))

    def load_run(self, run_dir: str | Path) -> dict[str, Any]:
        """Load a run and verify the hashes of its persisted state artifacts."""

        target = self._resolve_run_dir(run_dir, None)
        manifest_path = target / "manifest.json"
        try:
            manifest = _read_json(manifest_path)
            RunManifest.model_validate(manifest)
        except StorageIntegrityError:
            raise
        except Exception as error:
            raise StorageIntegrityError(f"invalid manifest.json: {error}") from error

        initial_path = target / "initial-state.json"
        final_path = target / "final-state.json"
        try:
            initial_bytes = initial_path.read_bytes()
            final_bytes = final_path.read_bytes()
        except OSError as error:
            raise StorageIntegrityError(f"missing run state artifact: {error}") from error

        expected_initial = _text_value(manifest.get("initial_state_hash"))
        expected_world = _text_value(manifest.get("world_snapshot_hash"))
        actual_initial = sha256_bytes(initial_bytes)
        if expected_initial is not None and actual_initial != expected_initial:
            raise StorageIntegrityError(
                "initial-state.json hash mismatch: "
                f"expected {expected_initial}, got {actual_initial}"
            )
        if expected_world is None or actual_initial != expected_world:
            raise StorageIntegrityError(
                "initial-state.json does not match manifest world_snapshot_hash"
            )

        expected_final = _text_value(manifest.get("final_state_hash"))
        actual_final = sha256_bytes(final_bytes)
        if expected_final is not None and actual_final != expected_final:
            raise StorageIntegrityError(
                f"final-state.json hash mismatch: expected {expected_final}, got {actual_final}"
            )
        if expected_final is None:
            raise StorageIntegrityError("manifest is missing final_state_hash")

        try:
            initial_state = json.loads(initial_bytes)
            final_state = json.loads(final_bytes)
            verification = _read_json(target / "verification.json")
            trajectory = TrajectoryRecorder.load(target / "trajectory.jsonl")
        except StorageIntegrityError:
            raise
        except Exception as error:
            raise StorageIntegrityError(f"invalid run artifact: {error}") from error

        return {
            "manifest": manifest,
            "trajectory": trajectory,
            "initial_state": initial_state,
            "final_state": final_state,
            "verification": verification,
        }

    def _resolve_run_dir(self, run_dir: str | Path | None, run_id: str | None) -> Path:
        if run_dir is None:
            if run_id is None:
                raise ValueError("run_dir or run_id is required")
            return (self.root / run_id).resolve()
        candidate = Path(run_dir)
        if not candidate.is_absolute() and len(candidate.parts) == 1 and self.root != Path("."):
            candidate = self.root / candidate
        return candidate.resolve()


def _atomic_write(path: Path, value: bytes) -> None:
    """Write bytes through a same-directory temporary file and replace."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("wb") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _trajectory_bytes(
    trajectory: Sequence[TrajectoryEvent | Mapping[str, Any]]
    | TrajectoryRecorder
    | str
    | Path
    | None,
) -> bytes:
    if trajectory is None:
        return b""
    if isinstance(trajectory, TrajectoryRecorder):
        events: Sequence[TrajectoryEvent | Mapping[str, Any]] = trajectory.events
    elif isinstance(trajectory, Path):
        return trajectory.read_bytes()
    elif isinstance(trajectory, str):
        return Path(trajectory).read_bytes()
    elif isinstance(trajectory, Mapping):
        events = [trajectory]
    else:
        events = trajectory

    lines: list[str] = []
    for event in events:
        validated = (
            event if isinstance(event, TrajectoryEvent) else TrajectoryEvent.model_validate(event)
        )
        lines.append(
            json.dumps(
                validated.model_dump(mode="json"),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        )
    return ("\n".join(lines) + "\n").encode("utf-8") if lines else b""


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise TypeError(f"{path.name} must contain a JSON object")
    return cast(dict[str, Any], value)


def _json_value(value: object) -> object:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return model_dump(mode="json")
    return value


def _mapping_value(value: object) -> dict[str, Any]:
    normalized = _json_value(value)
    if isinstance(normalized, Mapping):
        return {str(key): item for key, item in normalized.items()}
    return {}


def _object_id(value: object | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, Mapping):
        candidate = value.get("id")
        return candidate if isinstance(candidate, str) and candidate else None
    candidate = getattr(value, "id", None)
    return candidate if isinstance(candidate, str) and candidate else None


def _text_value(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _hash_source(source: object | None, supplied: str | None, *, fallback: object) -> str:
    if source is not None:
        return sha256_json(source)
    if supplied is not None:
        _validate_digest(supplied, field="artifact hash")
        return supplied
    return sha256_json(fallback)


def _validate_digest(value: str, *, field: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{field} must be a lowercase SHA-256 hexadecimal digest")


def _string_mapping(value: object, *, defaults: Mapping[str, str]) -> dict[str, str]:
    result = dict(defaults)
    for key, item in _mapping_value(value).items():
        result[str(key)] = str(item)
    return result


def _seed_value(explicit: int | None, stored: object) -> int:
    value = explicit if explicit is not None else stored
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return value


__all__ = [
    "RunManifest",
    "RunStore",
    "StorageIntegrityError",
    "canonical_json_bytes",
    "sha256_bytes",
    "sha256_json",
]
