"""Scenario generation contracts and initial-world snapshot staging.

Scenario generators are deliberately kept domain-agnostic.  A domain supplies
the generator implementation; this module only defines how generators are
identified, registered, invoked, and how a captured initial snapshot can be
persisted for a later world restore.
"""

from __future__ import annotations

import importlib
import inspect
import json
from collections.abc import Awaitable, Iterable, Iterator, Mapping
from pathlib import Path
from types import ModuleType
from typing import Any, Protocol, cast

from agentgym.core.task import Task
from agentgym.world.snapshot import WorldSnapshot

type ScenarioGeneration = Task | Awaitable[Task]


class ScenarioGenerator(Protocol):
    """Produce one deterministic task instance for a seed.

    Implementations may expose either a regular or an ``async`` ``generate``
    method.  The registry's :meth:`ScenarioRegistry.generate_async` method
    provides one normalized async entry point for both forms.
    """

    id: str

    def generate(self, seed: int) -> ScenarioGeneration:
        """Create the task and stage the task's initial world state."""


class SnapshotSource(Protocol):
    """The portion of a world/store needed by snapshot staging."""

    def snapshot(self, **kwargs: Any) -> WorldSnapshot | Awaitable[WorldSnapshot]:
        """Capture the current world state."""


def write_snapshot(
    source: WorldSnapshot | SnapshotSource,
    path: str | Path,
    *,
    snapshot_id: str | None = None,
) -> Path:
    """Serialize an initial snapshot to ``path`` and return that path.

    ``source`` may be an already captured :class:`WorldSnapshot` or a
    synchronous store exposing ``snapshot()``.  A source whose snapshot method
    is asynchronous should use :func:`write_snapshot_async` instead.  Parent
    directories are created so generators can point at a temporary snapshots
    directory without setup code of their own.
    """

    snapshot = _capture_sync_snapshot(source, snapshot_id=snapshot_id)
    return _write_snapshot(snapshot, path)


async def write_snapshot_async(
    source: WorldSnapshot | SnapshotSource,
    path: str | Path,
    *,
    snapshot_id: str | None = None,
) -> Path:
    """Serialize a snapshot from either a synchronous or asynchronous source."""

    snapshot = _capture_snapshot(source, snapshot_id=snapshot_id)
    if inspect.isawaitable(snapshot):
        snapshot = await snapshot
    return _write_snapshot(snapshot, path)


def read_snapshot(path: str | Path) -> WorldSnapshot:
    """Load and validate a previously staged snapshot JSON file."""

    snapshot_path = Path(path)
    with snapshot_path.open(encoding="utf-8") as stream:
        return WorldSnapshot.model_validate(json.load(stream))


class ScenarioRegistry:
    """Registry of domain scenario generators keyed by their stable ids."""

    def __init__(
        self,
        generators: Iterable[ScenarioGenerator]
        | Mapping[str, ScenarioGenerator]
        | None = None,
    ) -> None:
        self._generators: dict[str, ScenarioGenerator] = {}
        if generators is not None:
            values = generators.values() if isinstance(generators, Mapping) else generators
            for generator in values:
                self.register(generator)

    @classmethod
    def from_modules(cls, modules: Iterable[str | ModuleType]) -> ScenarioRegistry:
        """Build a registry from modules exporting generator objects.

        A scenario module may expose one generator as ``GENERATOR`` or
        ``SCENARIO_GENERATOR``, or a collection as ``GENERATORS``.  A module
        may also expose ``register_scenarios(registry)`` for custom discovery.
        The explicit names keep importing a module side-effect free for normal
        scenario modules while still allowing a domain to choose its own
        registration code.
        """

        registry = cls()
        for module_ref in modules:
            module = (
                importlib.import_module(module_ref)
                if isinstance(module_ref, str)
                else module_ref
            )
            register_scenarios = getattr(module, "register_scenarios", None)
            if callable(register_scenarios):
                register_scenarios(registry)
                continue
            for generator in _module_generators(module):
                registry.register(generator)
        return registry

    def register(self, generator: ScenarioGenerator) -> ScenarioGenerator:
        """Register ``generator`` and reject missing or duplicate ids."""

        scenario_id = _generator_id(generator)
        if scenario_id in self._generators:
            raise ValueError(f"scenario generator already registered: {scenario_id}")
        self._generators[scenario_id] = generator
        return generator

    def register_many(self, generators: Iterable[ScenarioGenerator]) -> None:
        """Register each generator in iteration order."""

        for generator in generators:
            self.register(generator)

    def get(self, scenario_id: str) -> ScenarioGenerator | None:
        """Return a generator if ``scenario_id`` is registered."""

        return self._generators.get(scenario_id)

    def require(self, scenario_id: str) -> ScenarioGenerator:
        """Return a generator or raise a clear lookup error."""

        try:
            return self._generators[scenario_id]
        except KeyError as error:
            raise KeyError(f"unknown scenario generator: {scenario_id}") from error

    def unregister(self, scenario_id: str) -> ScenarioGenerator:
        """Remove and return a registered generator."""

        try:
            return self._generators.pop(scenario_id)
        except KeyError as error:
            raise KeyError(f"unknown scenario generator: {scenario_id}") from error

    @property
    def ids(self) -> tuple[str, ...]:
        """Registered ids in insertion order."""

        return tuple(self._generators)

    @property
    def generators(self) -> Mapping[str, ScenarioGenerator]:
        """A read-only view of the registry contents."""

        return self._generators.copy()

    def generate(self, scenario_id: str, seed: int) -> ScenarioGeneration:
        """Invoke a generator, preserving whether its method is sync or async."""

        return self.require(scenario_id).generate(seed)

    async def generate_async(self, scenario_id: str, seed: int) -> Task:
        """Invoke either kind of generator and return a validated task."""

        result = self.generate(scenario_id, seed)
        if inspect.isawaitable(result):
            result = await result
        if not isinstance(result, Task):
            raise TypeError(
                f"scenario generator {scenario_id!r} returned {type(result).__name__}, "
                "expected Task"
            )
        return result

    def __contains__(self, scenario_id: object) -> bool:
        return scenario_id in self._generators

    def __getitem__(self, scenario_id: str) -> ScenarioGenerator:
        return self.require(scenario_id)

    def __iter__(self) -> Iterator[ScenarioGenerator]:
        return iter(self._generators.values())

    def __len__(self) -> int:
        return len(self._generators)


def _capture_sync_snapshot(
    source: WorldSnapshot | SnapshotSource,
    *,
    snapshot_id: str | None,
) -> WorldSnapshot:
    snapshot = _capture_snapshot(source, snapshot_id=snapshot_id)
    if inspect.isawaitable(snapshot):
        raise TypeError(
            "write_snapshot received an asynchronous snapshot source; "
            "use write_snapshot_async"
        )
    return snapshot


def _capture_snapshot(
    source: WorldSnapshot | SnapshotSource,
    *,
    snapshot_id: str | None,
) -> WorldSnapshot | Awaitable[WorldSnapshot]:
    if isinstance(source, WorldSnapshot):
        return source

    snapshot_method = source.snapshot
    if snapshot_id is None:
        return snapshot_method()
    return snapshot_method(snapshot_id=snapshot_id)


def _write_snapshot(snapshot: WorldSnapshot, path: str | Path) -> Path:
    snapshot_path = Path(path)
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    payload = snapshot.model_dump(mode="json")
    snapshot_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return snapshot_path


def _generator_id(generator: ScenarioGenerator) -> str:
    scenario_id = getattr(generator, "id", None)
    if not isinstance(scenario_id, str) or not scenario_id.strip():
        raise TypeError("scenario generator must expose a non-empty string id")
    generate = getattr(generator, "generate", None)
    if not callable(generate):
        raise TypeError(f"scenario generator {scenario_id!r} must expose generate(seed)")
    return scenario_id


def _module_generators(module: ModuleType) -> tuple[ScenarioGenerator, ...]:
    candidates: list[ScenarioGenerator] = []
    for name in ("GENERATOR", "SCENARIO_GENERATOR", "GENERATORS"):
        value = getattr(module, name, None)
        if value is None:
            continue
        if isinstance(value, Mapping):
            candidates.extend(cast(Iterable[ScenarioGenerator], value.values()))
        elif isinstance(value, Iterable) and not isinstance(value, (str, bytes)):
            candidates.extend(cast(Iterable[ScenarioGenerator], value))
        else:
            candidates.append(cast(ScenarioGenerator, value))
    return tuple(candidates)


scenario_registry = ScenarioRegistry()


def register_scenario(generator: ScenarioGenerator) -> ScenarioGenerator:
    """Register a generator in the process-wide default registry."""

    return scenario_registry.register(generator)


__all__ = [
    "ScenarioGeneration",
    "ScenarioGenerator",
    "ScenarioRegistry",
    "SnapshotSource",
    "read_snapshot",
    "register_scenario",
    "scenario_registry",
    "write_snapshot",
    "write_snapshot_async",
]
