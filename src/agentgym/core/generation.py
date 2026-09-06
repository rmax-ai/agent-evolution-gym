"""Accepted package generation contracts."""

from typing import Any

from pydantic import BaseModel, ConfigDict


class Generation(BaseModel):
    """An immutable accepted agent-package state defined by SPEC section 45."""

    model_config = ConfigDict(frozen=True)

    number: int
    package_id: str
    parent_package_id: str | None
    mutation_ids: list[str]
    train_metrics: dict[str, Any]
    validation_metrics: dict[str, Any]
    created_at: str
