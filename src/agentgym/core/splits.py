"""Scenario-structured train, validation, and test split contracts."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any, Self

import yaml
from pydantic import BaseModel, Field, model_validator


class SplitEntry(BaseModel):
    """One scenario family and its deterministic seed allocation."""

    scenario_id: str
    count: int = Field(gt=0)
    seed_range: list[int] | None = None
    seeds: list[int] | None = None

    @model_validator(mode="after")
    def validate_seed_source(self) -> Self:
        """Require exactly one seed source and enough seeds for ``count``."""

        if (self.seed_range is None) == (self.seeds is None):
            raise ValueError("provide exactly one of seed_range or seeds")

        if self.seeds is not None:
            if len(self.seeds) != self.count:
                raise ValueError("count must equal the number of explicit seeds")
            if len(set(self.seeds)) != len(self.seeds):
                raise ValueError("explicit seeds must be unique")
            return self

        assert self.seed_range is not None
        if len(self.seed_range) != 2:
            raise ValueError("seed_range must contain inclusive start and end values")
        start, end = self.seed_range
        if end < start:
            raise ValueError("seed_range end must be greater than or equal to start")
        if self.count > end - start + 1:
            raise ValueError("count exceeds the inclusive seed_range")
        return self

    @property
    def resolved_seeds(self) -> tuple[int, ...]:
        """Return the exact seeds this entry contributes to its split."""

        if self.seeds is not None:
            return tuple(self.seeds)
        assert self.seed_range is not None
        start = self.seed_range[0]
        return tuple(range(start, start + self.count))

    @property
    def seed_values(self) -> tuple[int, ...]:
        """Alias for :attr:`resolved_seeds` used by curriculum callers."""

        return self.resolved_seeds


class SplitSpec(BaseModel):
    """A validated scenario-structured split manifest."""

    entries: list[SplitEntry]

    @property
    def scenarios(self) -> list[SplitEntry]:
        """Alias for callers that refer to entries as scenario records."""

        return self.entries

    @classmethod
    def from_yaml(cls, path: str | Path) -> Self:
        """Load a split manifest from a YAML list or an ``entries`` mapping."""

        split_path = Path(path)
        with split_path.open(encoding="utf-8") as stream:
            raw: Any = yaml.safe_load(stream)

        if isinstance(raw, list):
            entries = raw
        elif isinstance(raw, dict):
            entries = raw.get("entries", raw.get("scenarios"))
        else:
            entries = None

        if not isinstance(entries, list):
            raise ValueError(f"split YAML must contain a list of scenario entries: {split_path}")
        return cls.model_validate({"entries": entries})

    @property
    def scenario_ids(self) -> tuple[str, ...]:
        """Scenario ids in manifest order."""

        return tuple(entry.scenario_id for entry in self.entries)

    @property
    def total_count(self) -> int:
        """Total number of task instances described by the split."""

        return sum(entry.count for entry in self.entries)

    def for_scenario(self, scenario_id: str) -> tuple[SplitEntry, ...]:
        """Return all entries for a scenario id."""

        return tuple(entry for entry in self.entries if entry.scenario_id == scenario_id)

    def iter_seeded(self) -> Iterator[tuple[str, int]]:
        """Yield ``(scenario_id, seed)`` pairs in manifest order."""

        for entry in self.entries:
            yield from ((entry.scenario_id, seed) for seed in entry.resolved_seeds)


ScenarioSplit = SplitEntry
ScenarioEntry = SplitEntry


def load_split(path: str | Path) -> SplitSpec:
    """Load a split YAML file into a :class:`SplitSpec`."""

    return SplitSpec.from_yaml(path)


load_split_spec = load_split


__all__ = [
    "ScenarioEntry",
    "ScenarioSplit",
    "SplitEntry",
    "SplitSpec",
    "load_split",
    "load_split_spec",
]
