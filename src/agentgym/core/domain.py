"""Domain contracts."""

from pathlib import Path
from typing import Self

import yaml
from pydantic import BaseModel


class DomainSpec(BaseModel):
    """Declarative configuration for a domain and its task curriculum."""

    id: str
    version: str
    description: str
    world_provider: str
    scenario_modules: list[str]
    verifier_modules: list[str]
    train_split: str
    validation_split: str
    test_split: str
    capabilities: list[str]

    @classmethod
    def from_yaml(cls, path: str | Path) -> Self:
        """Load a domain specification from a YAML file."""

        with Path(path).open(encoding="utf-8") as stream:
            return cls.model_validate(yaml.safe_load(stream))
