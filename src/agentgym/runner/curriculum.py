"""Run-scoped scenario materialization and domain verifier loading."""

from __future__ import annotations

import importlib
import inspect
from pathlib import Path
from types import ModuleType
from typing import Any, cast

from agentgym.core.scenario import ScenarioGenerator, _module_generators
from agentgym.core.splits import SplitSpec
from agentgym.core.task import Task


def materialize(
    split: SplitSpec,
    domain_package: str,
    *,
    snapshot_root: Path,
    split_name: str,
) -> list[Task]:
    """Generate every task in ``split`` under one caller-owned snapshot root.

    Scenario modules are resolved relative to ``domain_package``. Their
    exported generator objects are reconstructed with the run-scoped snapshot
    directory so importing a module's default generator cannot leak artifacts
    into another materialization run.
    """

    root = Path(snapshot_root)
    generators = _load_generators(split, domain_package, root)
    tasks: list[Task] = []
    for scenario_id, seed in split.iter_seeded():
        try:
            generator = generators[scenario_id]
        except KeyError as error:
            raise KeyError(f"no generator for scenario {scenario_id!r}") from error

        generated = generator.generate(seed)
        if inspect.isawaitable(generated):
            raise TypeError(
                f"scenario generator {scenario_id!r} returned an awaitable; "
                "materialize requires synchronous generators"
            )
        if not isinstance(generated, Task):
            raise TypeError(
                f"scenario generator {scenario_id!r} returned "
                f"{type(generated).__name__}, expected Task"
            )
        tasks.append(generated.model_copy(update={"split": split_name}))
    return tasks


def load_verifier(domain_package: str, verifier_ref: str) -> object:
    """Load the ``VERIFIER`` object from a domain-relative verifier module."""

    module = importlib.import_module(f"{domain_package}.{verifier_ref}")
    try:
        return module.VERIFIER
    except AttributeError as error:
        raise AttributeError(f"verifier module {module.__name__!r} must export VERIFIER") from error


def _load_generators(
    split: SplitSpec,
    domain_package: str,
    snapshot_root: Path,
) -> dict[str, ScenarioGenerator]:
    """Discover and reconstruct generators, rejecting duplicate stable ids."""

    generators: dict[str, ScenarioGenerator] = {}
    loaded_modules: dict[str, ModuleType] = {}
    for entry in split.entries:
        module_ref = f"{domain_package}.scenarios.{entry.scenario_id}"
        if module_ref in loaded_modules:
            continue
        module = importlib.import_module(module_ref)
        loaded_modules[module_ref] = module
        for candidate in _module_generators(module):
            generator = _construct_generator(candidate, snapshot_root)
            scenario_id = getattr(generator, "id", None)
            if not isinstance(scenario_id, str) or not scenario_id.strip():
                raise TypeError("scenario generator must expose a non-empty string id")
            if scenario_id in generators:
                raise ValueError(f"scenario generator already registered: {scenario_id}")
            generators[scenario_id] = generator
    return generators


def _construct_generator(candidate: object, snapshot_root: Path) -> ScenarioGenerator:
    """Instantiate one discovered generator with the caller's snapshot root."""

    generator_type: Any = candidate if inspect.isclass(candidate) else type(candidate)
    generator = generator_type(snapshot_dir=snapshot_root)
    return cast(ScenarioGenerator, generator)


__all__ = ["load_verifier", "materialize"]
